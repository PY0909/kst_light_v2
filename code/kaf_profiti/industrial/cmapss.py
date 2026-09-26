from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
import torch
from torch import Tensor
from torch.utils.data import Dataset

from .missing import MissingMechanismSimulator


SETTING_COLUMNS = ["setting_1", "setting_2", "setting_3"]
SENSOR_COLUMNS = [f"sensor_{idx}" for idx in range(1, 22)]
#: Frozen Chapter-5 risk rule for C-MAPSS: risk at the forecast origin.
CMAPSS_RISK_RUL_THRESHOLD = 30.0

BASE_COLUMNS = ["unit", "cycle"] + SETTING_COLUMNS + SENSOR_COLUMNS


@dataclass
class CMapssWindowSample:
    X_obs: Tensor
    T_obs: Tensor
    M_obs: Tensor
    T_q: Tensor
    Y_q: Tensor
    M_q: Tensor
    context: Tensor
    rul: float
    unit_id: int
    window_id: str = ""
    risk_label: float = 0.0


def load_cmapss_frame(data_dir: Path, subset: str, split: str) -> pd.DataFrame:
    data_dir = Path(data_dir)
    split = split.lower()
    if split not in {"train", "test"}:
        raise ValueError("split must be 'train' or 'test'")

    data_path = data_dir / f"{split}_{subset}.txt"
    if not data_path.exists():
        raise FileNotFoundError(data_path)

    frame = pd.read_csv(data_path, sep=r"\s+", header=None, names=BASE_COLUMNS)
    frame = frame.sort_values(["unit", "cycle"]).reset_index(drop=True)
    frame["rul"] = _compute_rul(frame, data_dir, subset, split)
    return frame


def _compute_rul(frame: pd.DataFrame, data_dir: Path, subset: str, split: str) -> pd.Series:
    if split == "train":
        max_cycle = frame.groupby("unit")["cycle"].transform("max")
        return (max_cycle - frame["cycle"]).astype(float)

    rul_path = data_dir / f"RUL_{subset}.txt"
    if not rul_path.exists():
        raise FileNotFoundError(rul_path)
    final_rul = pd.read_csv(rul_path, sep=r"\s+", header=None).iloc[:, 0]
    units = sorted(frame["unit"].unique().tolist())
    if len(final_rul) != len(units):
        raise ValueError(
            f"{rul_path} has {len(final_rul)} rows but {split}_{subset} has {len(units)} units"
        )
    unit_to_extra = {unit: float(final_rul.iloc[idx]) for idx, unit in enumerate(units)}
    observed_max = frame.groupby("unit")["cycle"].transform("max")
    extra = frame["unit"].map(unit_to_extra)
    return (observed_max + extra - frame["cycle"]).astype(float)


def _training_stats(data_dir: Path, subset: str) -> Dict[str, Tensor]:
    train_frame = load_cmapss_frame(data_dir, subset, "train")
    sensors = torch.tensor(train_frame[SENSOR_COLUMNS].to_numpy(), dtype=torch.float32)
    settings = torch.tensor(train_frame[SETTING_COLUMNS].to_numpy(), dtype=torch.float32)
    return {
        "sensor_mean": sensors.mean(dim=0),
        "sensor_std": sensors.std(dim=0).clamp_min(1e-6),
        "setting_mean": settings.mean(dim=0),
        "setting_std": settings.std(dim=0).clamp_min(1e-6),
    }


class CMapssWindowDataset(Dataset):
    def __init__(
        self,
        data_dir,
        subset: str = "FD001",
        split: str = "train",
        history_len: int = 50,
        pred_len: int = 10,
        stride: int = 1,
        async_mode: str = "mixed",
        seed: int = 42,
        rul_cap: int = 125,
        normalize: bool = True,
        context_mode: str = "mean",
        stats: Optional[Dict[str, "Tensor"]] = None,
    ):
        """Initialize a C-MAPSS window dataset.

        Args:
            data_dir: Directory holding the official ``train_/test_<subset>.txt`` files.
            subset: C-MAPSS subset name such as ``FD004``.
            split: ``train`` or ``test`` (official file to load).
            history_len: History window length.
            pred_len: Forecast window length.
            stride: Window stride in cycles.
            async_mode: Missing-mechanism mode for the built-in simulator.
            seed: Run seed for the built-in per-window mask simulator.
            rul_cap: Cap applied to RUL labels.
            normalize: Whether to normalize when no frozen ``stats`` are given.
            context_mode: ``mean`` or ``last`` aggregation of setting channels.
            stats: Frozen normalization statistics (``sensor_mean``/``sensor_std``/
                ``setting_mean``/``setting_std``). When provided they are used
                as-is and the constructor never re-estimates statistics from
                the loaded frame; protocol code must always pass train-engine
                only statistics here.
        """
        self.data_dir = Path(data_dir)
        self.subset = subset
        self.split = split
        self.history_len = int(history_len)
        self.pred_len = int(pred_len)
        self.stride = int(stride)
        self.async_mode = async_mode
        self.seed = int(seed)
        self.rul_cap = float(rul_cap)
        self.normalize = bool(normalize)
        self.context_mode = context_mode

        if self.history_len <= 0 or self.pred_len <= 0:
            raise ValueError("history_len and pred_len must be positive")
        if self.stride <= 0:
            raise ValueError("stride must be positive")
        if context_mode not in {"mean", "last"}:
            raise ValueError("context_mode must be 'mean' or 'last'")

        self.frame = load_cmapss_frame(self.data_dir, subset, split)
        if stats is not None:
            self.stats = stats
        else:
            self.stats = _training_stats(self.data_dir, subset) if normalize else None
        self.masker = MissingMechanismSimulator(mode=async_mode)
        self._units: Dict[int, pd.DataFrame] = {
            int(unit): group.reset_index(drop=True)
            for unit, group in self.frame.groupby("unit", sort=True)
        }
        self.windows = self._build_windows()
        if not self.windows:
            raise ValueError(
                f"No C-MAPSS windows for {subset}/{split}; reduce history_len or pred_len"
            )

    def _build_windows(self) -> List[Tuple[int, int]]:
        windows: List[Tuple[int, int]] = []
        total_len = self.history_len + self.pred_len
        for unit, group in self._units.items():
            limit = len(group) - total_len + 1
            for start in range(0, max(0, limit), self.stride):
                windows.append((unit, start))
        return windows

    def __len__(self) -> int:
        return len(self.windows)

    def __getitem__(self, index: int) -> CMapssWindowSample:
        unit, start = self.windows[index]
        group = self._units[unit]
        hist = group.iloc[start : start + self.history_len]
        fut = group.iloc[
            start + self.history_len : start + self.history_len + self.pred_len
        ]

        sensors_hist = torch.tensor(hist[SENSOR_COLUMNS].to_numpy(), dtype=torch.float32)
        sensors_future = torch.tensor(fut[SENSOR_COLUMNS].to_numpy(), dtype=torch.float32)
        settings_hist = torch.tensor(hist[SETTING_COLUMNS].to_numpy(), dtype=torch.float32)
        if self.normalize:
            sensors_hist = (sensors_hist - self.stats["sensor_mean"]) / self.stats["sensor_std"]
            sensors_future = (
                sensors_future - self.stats["sensor_mean"]
            ) / self.stats["sensor_std"]
            settings_hist = (
                settings_hist - self.stats["setting_mean"]
            ) / self.stats["setting_std"]

        if self.context_mode == "mean":
            context = settings_hist.mean(dim=0)
        else:
            context = settings_hist[-1]

        mask_seed = self.seed + unit * 100_000 + start
        M_obs = self.masker((self.history_len, len(SENSOR_COLUMNS)), mask_seed)
        X_obs = sensors_hist * M_obs

        return CMapssWindowSample(
            X_obs=X_obs,
            T_obs=torch.tensor(hist["cycle"].to_numpy(), dtype=torch.float32),
            M_obs=M_obs,
            T_q=torch.tensor(fut["cycle"].to_numpy(), dtype=torch.float32),
            Y_q=sensors_future,
            M_q=torch.ones_like(sensors_future),
            context=context,
            rul=float(min(hist["rul"].iloc[-1], self.rul_cap)),
            unit_id=unit,
            window_id=f"engine{unit}:start{start}",
            risk_label=float(min(hist["rul"].iloc[-1], self.rul_cap) <= CMAPSS_RISK_RUL_THRESHOLD),
        )
