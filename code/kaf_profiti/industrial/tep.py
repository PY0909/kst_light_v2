from __future__ import annotations

import gzip
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd
import torch
from torch import Tensor
from torch.utils.data import Dataset

from .missing import MissingMechanismSimulator


TEP_XMEAS_COLUMNS = [f"xmeas_{idx}" for idx in range(1, 42)]
TEP_XMV_COLUMNS = [f"xmv_{idx}" for idx in range(1, 12)]
TEP_CONTEXT_COLUMNS = TEP_XMV_COLUMNS
TEP_SENSOR_COLUMNS = TEP_XMEAS_COLUMNS + TEP_XMV_COLUMNS
TEP_META_COLUMNS = ["faultNumber", "simulationRun", "sample"]
TEP_COLUMNS = TEP_META_COLUMNS + TEP_SENSOR_COLUMNS
TEP_FAULT_START_SAMPLE = 161

_SOURCE_TO_FILE = {
    "fault_free_training": "TEP_FaultFree_Training.RData",
    "fault_free_testing": "TEP_FaultFree_Testing.RData",
    "faulty_training": "TEP_Faulty_Training.RData",
    "faulty_testing": "TEP_Faulty_Testing.RData",
}
_ALIASES = {
    "ff_train": "fault_free_training",
    "ff_test": "fault_free_testing",
    "faultfree_training": "fault_free_training",
    "faultfree_testing": "fault_free_testing",
    "train_fault_free": "fault_free_training",
    "test_fault_free": "fault_free_testing",
    "fault_train": "faulty_training",
    "fault_test": "faulty_testing",
}
_TEP_FRAME_CACHE: Dict[Tuple[object, ...], pd.DataFrame] = {}


@dataclass
class TEPWindowSample:
    X_obs: Tensor
    T_obs: Tensor
    M_obs: Tensor
    T_q: Tensor
    Y_q: Tensor
    M_q: Tensor
    context: Tensor
    rul: float
    unit_id: int


@dataclass
class _PairList:
    tag: object
    car: object
    cdr: object


def _info_type(info_int: int) -> int:
    return info_int & 0xFF


def _info_has_attributes(info_int: int) -> bool:
    return bool((info_int >> 9) & 1)


def _info_has_tag(info_int: int) -> bool:
    return bool((info_int >> 10) & 1)


def _info_reference(info_int: int) -> int:
    return info_int >> 8


class _XDRGzipParser:
    """Small RData/XDR reader for the Dataverse TEP data.frame layout."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.file = gzip.open(self.path, "rb")
        self.references: List[object] = []

    def close(self) -> None:
        self.file.close()

    def __enter__(self) -> "_XDRGzipParser":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def read_exact(self, size: int) -> bytes:
        data = self.file.read(size)
        if len(data) != size:
            raise EOFError(f"Unexpected EOF reading {size} bytes from {self.path}")
        return data

    def skip_exact(self, size: int) -> None:
        chunk_size = 1024 * 1024
        remaining = size
        while remaining > 0:
            chunk = self.file.read(min(chunk_size, remaining))
            if not chunk:
                raise EOFError(f"Unexpected EOF skipping {size} bytes from {self.path}")
            remaining -= len(chunk)

    def read_int(self) -> int:
        return struct.unpack(">i", self.read_exact(4))[0]

    def read_header(self) -> Tuple[int, int, int]:
        magic = self.read_exact(5)
        if magic not in {b"RDX2\n", b"RDX3\n"}:
            raise ValueError(f"{self.path} is not a binary RData file")
        xdr_marker = self.read_exact(2)
        if xdr_marker != b"X\n":
            raise NotImplementedError(f"{self.path} is not XDR-encoded RData")
        return self.read_int(), self.read_int(), self.read_int()

    def parse_object(self):
        return self._parse_object_with_info(self.read_int())

    def _parse_object_with_info(self, info_int: int):
        typ = _info_type(info_int)
        attrs = None
        if typ in {0, 254}:
            return None
        if typ == 255:
            ref = _info_reference(info_int)
            return self.references[ref - 1] if 0 < ref <= len(self.references) else None
        if _info_has_attributes(info_int):
            attrs = self.parse_object()

        tag = self.parse_object() if _info_has_tag(info_int) else None

        if typ == 1:
            value = self.parse_object()
            self.references.append(value)
            return value
        if typ == 2:
            car = self.parse_object()
            cdr = self.parse_object()
            return _PairList(tag=tag, car=car, cdr=cdr)
        if typ == 9:
            length = self.read_int()
            if length == -1:
                value = None
            elif length == 0:
                value = ""
            elif length > 0:
                value = self.read_exact(length).decode("utf-8", errors="replace")
            else:
                raise ValueError(f"Invalid R CHAR length {length}")
            return value
        if typ == 13:
            value = self._read_numeric_array(np.dtype(">i4")).astype(np.int32, copy=False)
        elif typ == 14:
            value = self._read_numeric_array(np.dtype(">f8")).astype(np.float64, copy=False)
        elif typ == 16:
            length = self.read_int()
            value = [self.parse_object() for _ in range(length)]
        elif typ == 19:
            length = self.read_int()
            value = [self.parse_object() for _ in range(length)]
        else:
            raise NotImplementedError(f"Unsupported R object type {typ} in {self.path}")

        if attrs is not None:
            return {"value": value, "attributes": attrs}
        return value

    def _read_numeric_array(self, dtype: np.dtype) -> np.ndarray:
        length = self.read_int()
        data = self.read_exact(length * dtype.itemsize)
        return np.frombuffer(data, dtype=dtype)

    def read_column(self, selected_indices: Optional[np.ndarray] = None) -> np.ndarray:
        info_int = self.read_int()
        typ = _info_type(info_int)
        if _info_has_tag(info_int):
            raise NotImplementedError("Tagged data.frame columns are not supported")
        if _info_has_attributes(info_int):
            raise NotImplementedError("Attributed data.frame columns are not supported")
        if typ not in {13, 14}:
            raise NotImplementedError(f"Unsupported TEP column type {typ}")

        length = self.read_int()
        dtype = np.dtype(">i4") if typ == 13 else np.dtype(">f8")
        data = self.read_exact(length * dtype.itemsize)
        values = np.frombuffer(data, dtype=dtype)
        if typ == 13:
            values = values.astype(np.int32, copy=False)
        else:
            values = values.astype(np.float64, copy=False)
        if selected_indices is None:
            return values
        return values[selected_indices]

    def skip_column(self) -> int:
        info_int = self.read_int()
        typ = _info_type(info_int)
        if _info_has_tag(info_int) or _info_has_attributes(info_int):
            raise NotImplementedError("Complex data.frame columns are not supported")
        if typ not in {13, 14}:
            raise NotImplementedError(f"Unsupported TEP column type {typ}")
        length = self.read_int()
        itemsize = 4 if typ == 13 else 8
        self.skip_exact(length * itemsize)
        return length


def _pairlist_to_dict(node: object) -> Dict[str, object]:
    attrs: Dict[str, object] = {}
    current = node
    while isinstance(current, _PairList):
        if current.tag is not None:
            attrs[str(current.tag)] = current.car
        current = current.cdr
    return attrs


def _row_count_from_attrs(attrs: Dict[str, object]) -> int:
    row_names = attrs.get("row.names")
    if isinstance(row_names, dict):
        row_names = row_names.get("value")
    if isinstance(row_names, np.ndarray) and len(row_names) == 2:
        return int(abs(int(row_names[1])))
    if isinstance(row_names, np.ndarray):
        return int(len(row_names))
    raise ValueError("TEP RData file does not expose data.frame row.names")


def _normalize_source(source: str) -> str:
    normalized = source.lower()
    normalized = _ALIASES.get(normalized, normalized)
    if normalized not in _SOURCE_TO_FILE:
        valid = ", ".join(sorted(_SOURCE_TO_FILE))
        raise ValueError(f"Unknown TEP source {source!r}; valid sources: {valid}")
    return normalized


def _as_int_set(values: Optional[Sequence[int]]) -> Optional[set]:
    if values is None:
        return None
    return {int(value) for value in values}


def inspect_tep_rdata_file(path: Union[str, Path]) -> Dict[str, object]:
    """Inspect a TEP RData data.frame without materializing all columns."""

    path = Path(path)
    with _XDRGzipParser(path) as parser:
        parser.read_header()
        top_info = parser.read_int()
        if _info_type(top_info) != 2 or not _info_has_tag(top_info):
            raise ValueError(f"{path} does not contain a named RData object")
        object_name = parser.parse_object()
        vec_info = parser.read_int()
        if _info_type(vec_info) != 19:
            raise ValueError(f"{path} does not contain a data.frame vector")
        num_columns = parser.read_int()
        lengths = [parser.skip_column() for _ in range(num_columns)]
        attrs = _pairlist_to_dict(parser.parse_object()) if _info_has_attributes(vec_info) else {}
        columns = attrs.get("names", TEP_COLUMNS)
        if isinstance(columns, dict):
            columns = columns.get("value", TEP_COLUMNS)
        columns = [str(column) for column in columns]
        num_rows = _row_count_from_attrs(attrs) if attrs else int(lengths[0])

    return {
        "object_name": str(object_name),
        "num_rows": int(num_rows),
        "num_columns": int(num_columns),
        "columns": columns,
    }


def _selected_indices(
    fault_numbers: np.ndarray,
    simulation_runs: np.ndarray,
    samples: np.ndarray,
    fault_filter: Optional[set],
    run_filter: Optional[set],
    max_runs_per_fault: Optional[int],
    sample_range: Optional[Tuple[int, int]],
) -> np.ndarray:
    fault_int = fault_numbers.astype(np.int64, copy=False)
    run_int = simulation_runs.astype(np.int64, copy=False)
    sample_int = samples.astype(np.int64, copy=False)
    mask = np.ones(len(fault_int), dtype=bool)
    if fault_filter is not None:
        mask &= np.isin(fault_int, list(fault_filter))
    if run_filter is not None:
        mask &= np.isin(run_int, list(run_filter))
    if sample_range is not None:
        start, end = sample_range
        mask &= (sample_int >= int(start)) & (sample_int <= int(end))
    if max_runs_per_fault is not None:
        keep_pairs = set()
        for fault in sorted(np.unique(fault_int[mask]).tolist()):
            fault_mask = mask & (fault_int == fault)
            runs = sorted(np.unique(run_int[fault_mask]).tolist())
            for run_id in runs[: int(max_runs_per_fault)]:
                keep_pairs.add((int(fault), int(run_id)))
        mask &= np.array(
            [(int(fault), int(run)) in keep_pairs for fault, run in zip(fault_int, run_int)],
            dtype=bool,
        )
    return np.flatnonzero(mask)


def _load_single_tep_source(
    data_dir: Path,
    source: str,
    fault_numbers: Optional[Sequence[int]] = None,
    run_ids: Optional[Sequence[int]] = None,
    max_runs_per_fault: Optional[int] = None,
    sample_range: Optional[Tuple[int, int]] = None,
) -> pd.DataFrame:
    source = _normalize_source(source)
    path = data_dir / _SOURCE_TO_FILE[source]
    if not path.exists():
        raise FileNotFoundError(path)

    fault_filter = _as_int_set(fault_numbers)
    run_filter = _as_int_set(run_ids)
    with _XDRGzipParser(path) as parser:
        parser.read_header()
        top_info = parser.read_int()
        if _info_type(top_info) != 2 or not _info_has_tag(top_info):
            raise ValueError(f"{path} does not contain a named RData object")
        parser.parse_object()
        vec_info = parser.read_int()
        if _info_type(vec_info) != 19:
            raise ValueError(f"{path} does not contain a data.frame vector")
        num_columns = parser.read_int()
        if num_columns != len(TEP_COLUMNS):
            raise ValueError(f"{path} has {num_columns} columns; expected {len(TEP_COLUMNS)}")

        raw: Dict[str, np.ndarray] = {}
        fault_values = parser.read_column()
        run_values = parser.read_column()
        sample_values = parser.read_column()
        selected = _selected_indices(
            fault_values,
            run_values,
            sample_values,
            fault_filter=fault_filter,
            run_filter=run_filter,
            max_runs_per_fault=max_runs_per_fault,
            sample_range=sample_range,
        )
        raw["faultNumber"] = fault_values[selected].astype(np.int16, copy=False)
        raw["simulationRun"] = run_values[selected].astype(np.int32, copy=False)
        raw["sample"] = sample_values[selected].astype(np.int32, copy=False)
        for column in TEP_SENSOR_COLUMNS:
            raw[column] = parser.read_column(selected).astype(np.float32, copy=False)
        attrs = _pairlist_to_dict(parser.parse_object()) if _info_has_attributes(vec_info) else {}
        columns = attrs.get("names", TEP_COLUMNS)
        if isinstance(columns, dict):
            columns = columns.get("value", TEP_COLUMNS)
        columns = [str(column) for column in columns]
        if columns != TEP_COLUMNS:
            raise ValueError(f"{path} columns do not match expected TEP schema")

    frame = pd.DataFrame(raw, columns=TEP_COLUMNS)
    frame["faultNumber"] = frame["faultNumber"].astype(int)
    frame["simulationRun"] = frame["simulationRun"].astype(int)
    frame["sample"] = frame["sample"].astype(int)
    frame = frame.sort_values(["faultNumber", "simulationRun", "sample"]).reset_index(drop=True)
    return frame


def load_tep_frame(
    data_dir: Union[str, Path],
    source: Union[str, Sequence[str]] = "fault_free_training",
    fault_numbers: Optional[Sequence[int]] = None,
    run_ids: Optional[Sequence[int]] = None,
    max_runs_per_fault: Optional[int] = None,
    sample_range: Optional[Tuple[int, int]] = None,
    use_cache: bool = True,
) -> pd.DataFrame:
    data_dir = Path(data_dir)
    sources = [source] if isinstance(source, str) else list(source)
    normalized_sources = tuple(_normalize_source(item) for item in sources)
    key = (
        str(data_dir.resolve()),
        normalized_sources,
        tuple(sorted(_as_int_set(fault_numbers) or [])),
        tuple(sorted(_as_int_set(run_ids) or [])),
        None if max_runs_per_fault is None else int(max_runs_per_fault),
        None if sample_range is None else (int(sample_range[0]), int(sample_range[1])),
    )
    if use_cache and key in _TEP_FRAME_CACHE:
        return _TEP_FRAME_CACHE[key].copy()

    frames = [
        _load_single_tep_source(
            data_dir,
            item,
            fault_numbers=fault_numbers,
            run_ids=run_ids,
            max_runs_per_fault=max_runs_per_fault,
            sample_range=sample_range,
        )
        for item in normalized_sources
    ]
    frame = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    frame = frame.sort_values(["faultNumber", "simulationRun", "sample"]).reset_index(drop=True)
    if use_cache:
        _TEP_FRAME_CACHE[key] = frame
    return frame.copy()


def tep_training_stats(frame: pd.DataFrame) -> Dict[str, Tensor]:
    sensors = torch.tensor(frame[TEP_SENSOR_COLUMNS].to_numpy(), dtype=torch.float32)
    context = torch.tensor(frame[TEP_CONTEXT_COLUMNS].to_numpy(), dtype=torch.float32)
    sensor_std = sensors.std(dim=0)
    context_std = context.std(dim=0)
    sensor_std = torch.where(sensor_std < 1e-6, torch.ones_like(sensor_std), sensor_std)
    context_std = torch.where(context_std < 1e-6, torch.ones_like(context_std), context_std)
    return {
        "sensor_mean": sensors.mean(dim=0),
        "sensor_std": sensor_std,
        "context_mean": context.mean(dim=0),
        "context_std": context_std,
    }


class TEPWindowDataset(Dataset):
    def __init__(
        self,
        data_dir,
        source: Union[str, Sequence[str]] = "fault_free_training",
        split: str = "all",
        history_len: int = 60,
        pred_len: int = 12,
        stride: int = 12,
        async_mode: str = "mixed",
        seed: int = 42,
        normalize: bool = True,
        context_mode: str = "mean",
        fault_numbers: Optional[Sequence[int]] = None,
        run_ids: Optional[Sequence[int]] = None,
        max_runs_per_fault: Optional[int] = None,
        sample_range: Optional[Tuple[int, int]] = None,
        fault_start_sample: int = TEP_FAULT_START_SAMPLE,
        frame: Optional[pd.DataFrame] = None,
        stats: Optional[Dict[str, Tensor]] = None,
    ):
        self.data_dir = Path(data_dir)
        self.source = source
        self.split = split
        self.history_len = int(history_len)
        self.pred_len = int(pred_len)
        self.stride = int(stride)
        self.async_mode = async_mode
        self.seed = int(seed)
        self.normalize = bool(normalize)
        self.context_mode = context_mode
        self.fault_start_sample = int(fault_start_sample)

        if self.history_len <= 0 or self.pred_len <= 0:
            raise ValueError("history_len and pred_len must be positive")
        if self.stride <= 0:
            raise ValueError("stride must be positive")
        if context_mode not in {"mean", "last"}:
            raise ValueError("context_mode must be 'mean' or 'last'")

        if frame is None:
            frame = load_tep_frame(
                self.data_dir,
                source=source,
                fault_numbers=fault_numbers,
                run_ids=run_ids,
                max_runs_per_fault=max_runs_per_fault,
                sample_range=sample_range,
            )
        self.frame = frame.copy().reset_index(drop=True)
        if "unit_id" not in self.frame.columns:
            self.frame["unit_id"] = (
                self.frame["faultNumber"].astype(int) * 100_000
                + self.frame["simulationRun"].astype(int)
            )
        self.stats = stats if stats is not None else (tep_training_stats(self.frame) if normalize else None)
        self.masker = MissingMechanismSimulator(mode=async_mode)
        self._units: Dict[int, pd.DataFrame] = {
            int(unit): group.reset_index(drop=True)
            for unit, group in self.frame.groupby("unit_id", sort=True)
        }
        self.windows = self._build_windows()
        if not self.windows:
            raise ValueError(
                f"No TEP windows for source={source}; reduce history_len or pred_len"
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

    def __getitem__(self, index: int) -> TEPWindowSample:
        unit, start = self.windows[index]
        group = self._units[unit]
        hist = group.iloc[start : start + self.history_len]
        fut = group.iloc[start + self.history_len : start + self.history_len + self.pred_len]

        sensors_hist = torch.tensor(hist[TEP_SENSOR_COLUMNS].to_numpy(), dtype=torch.float32)
        sensors_future = torch.tensor(fut[TEP_SENSOR_COLUMNS].to_numpy(), dtype=torch.float32)
        context_hist = torch.tensor(hist[TEP_CONTEXT_COLUMNS].to_numpy(), dtype=torch.float32)
        if self.normalize:
            sensors_hist = (sensors_hist - self.stats["sensor_mean"]) / self.stats["sensor_std"]
            sensors_future = (
                sensors_future - self.stats["sensor_mean"]
            ) / self.stats["sensor_std"]
            context_hist = (
                context_hist - self.stats["context_mean"]
            ) / self.stats["context_std"]

        context = context_hist.mean(dim=0) if self.context_mode == "mean" else context_hist[-1]
        mask_seed = self.seed + int(unit) * 100_000 + int(start)
        M_obs = self.masker((self.history_len, len(TEP_SENSOR_COLUMNS)), mask_seed)
        X_obs = sensors_hist * M_obs
        future_fault = (
            (fut["faultNumber"].to_numpy() > 0)
            & (fut["sample"].to_numpy() >= self.fault_start_sample)
        ).any()

        return TEPWindowSample(
            X_obs=X_obs,
            T_obs=torch.tensor(hist["sample"].to_numpy(), dtype=torch.float32),
            M_obs=M_obs,
            T_q=torch.tensor(fut["sample"].to_numpy(), dtype=torch.float32),
            Y_q=sensors_future,
            M_q=torch.ones_like(sensors_future),
            context=context,
            rul=float(future_fault),
            unit_id=int(unit),
        )
