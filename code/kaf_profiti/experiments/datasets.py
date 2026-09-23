import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

import pandas as pd
import torch

from kaf_profiti.industrial.cmapss import (
    CMapssWindowDataset,
    SENSOR_COLUMNS as CMAPSS_SENSOR_COLUMNS,
    SETTING_COLUMNS,
    load_cmapss_frame,
)
from kaf_profiti.industrial.metropt import (
    METROPT_CONTEXT_COLUMNS,
    METROPT_SENSOR_COLUMNS,
    MetroPTWindowDataset,
    load_metropt_frame,
)
from kaf_profiti.industrial.tep import (
    TEP_CONTEXT_COLUMNS,
    TEP_SENSOR_COLUMNS,
    TEPWindowDataset,
    load_tep_frame,
    tep_training_stats,
)


@dataclass
class ProtocolDatasets:
    name: str
    train: object
    valid: object
    test: object
    split_info: Dict[str, object]
    num_sensors: int
    context_dim: int


def split_identity_sha256(payload: Dict[str, object]) -> str:
    """Return the canonical-JSON SHA-256 digest of a split-identity payload.

    Keys are sorted and separators are fixed so the digest depends only on the
    payload content, never on dict insertion order. The payload must contain
    plain JSON types only; it must not include the run seed, model name, or any
    other per-run randomness so the same data protocol always yields the same
    split identity.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def create_protocol_datasets(
    dataset: str,
    data_root,
    seed: int,
    history_len: int,
    pred_len: int,
    stride: int,
    async_mode: str = "none",
    split_seed: int = 2026,
) -> ProtocolDatasets:
    """Build the train/valid/test protocol datasets for a dataset name.

    Args:
        dataset: Registered dataset name (``metropt3*``, ``cmapss_fdXXX``, ``tep``).
        data_root: Dataset root directory holding the raw per-dataset folders.
        seed: Run seed (model init / per-window mask randomness). It must never
            influence the data split.
        history_len: History window length.
        pred_len: Forecast window length.
        stride: Window stride.
        async_mode: Missing-mechanism mode used while constructing raw windows.
        split_seed: Fixed seed for randomized engine/run partitions (C-MAPSS
            engines, TEP simulation runs); defaults to the registered protocol
            value ``2026``. MetroPT protocols split chronologically and ignore
            it. ``split_info`` records the resulting engine IDs, canonical
            window boundaries, and a ``split_sha256`` identity digest.

    Returns:
        ProtocolDatasets with train/valid/test datasets and split metadata.
    """
    data_root = Path(data_root)
    if dataset == "metropt3":
        return _create_metropt(data_root, seed, history_len, pred_len, stride)
    if dataset == "metropt3_chrono_602020":
        return _create_metropt_chrono_602020(data_root, seed, history_len, pred_len, stride)
    if dataset == "metropt3_chrono_502030":
        return _create_metropt_chrono_502030(data_root, seed, history_len, pred_len, stride)
    if dataset == "metropt3_chrono_502030_v2":
        return _create_metropt_chrono_502030_v2(data_root, seed, history_len, pred_len, stride)
    if dataset.startswith("cmapss_fd"):
        subset = dataset.replace("cmapss_", "").upper()
        return _create_cmapss(data_root, subset, seed, split_seed, history_len, pred_len, stride)
    if dataset == "tep":
        return _create_tep(data_root, seed, split_seed, history_len, pred_len, stride)
    raise ValueError(f"Unknown dataset: {dataset}")


def _copy_with_windows(dataset: CMapssWindowDataset, windows) -> CMapssWindowDataset:
    clone = copy.copy(dataset)
    clone.windows = list(windows)
    return clone


_CMAPSS_STD_FLOOR = 1e-6


def _cmapss_stats_artifact(frame: pd.DataFrame, train_engine_ids: Sequence[int]) -> Dict[str, object]:
    """Build the frozen train-only normalization artifact for C-MAPSS.

    Only rows of ``train_engine_ids`` (the protocol train engines inside the
    official train file) enter every mean/std. Validation-engine rows in the
    same file and all official test rows are invisible to the artifact. The
    ``sha256`` covers every payload field, so any change to the source rows,
    engine set, or column order changes the digest.
    """
    train_frame = frame[frame["unit"].isin(set(int(u) for u in train_engine_ids))]
    sensors = torch.tensor(train_frame[CMAPSS_SENSOR_COLUMNS].to_numpy(), dtype=torch.float32)
    settings = torch.tensor(train_frame[SETTING_COLUMNS].to_numpy(), dtype=torch.float32)
    for name, values in (("sensor", sensors), ("setting", settings)):
        if values.numel() and not torch.isfinite(values).all():
            raise ValueError(f"non-finite {name} values in C-MAPSS normalization source rows")
    payload = {
        "source_split": "official_train",
        "engine_ids": sorted(int(unit) for unit in train_engine_ids),
        "sensor_columns": list(CMAPSS_SENSOR_COLUMNS),
        "setting_columns": list(SETTING_COLUMNS),
        "count": int(len(train_frame)),
        "std_floor": _CMAPSS_STD_FLOOR,
        "sensor_mean": [float(value) for value in sensors.mean(dim=0)],
        "sensor_std": [float(value) for value in sensors.std(dim=0).clamp_min(_CMAPSS_STD_FLOOR)],
        "setting_mean": [float(value) for value in settings.mean(dim=0)],
        "setting_std": [float(value) for value in settings.std(dim=0).clamp_min(_CMAPSS_STD_FLOOR)],
    }
    artifact = dict(payload)
    artifact["sha256"] = split_identity_sha256(payload)
    return artifact


def _stats_tensors_from_artifact(artifact: Dict[str, object]) -> Dict[str, torch.Tensor]:
    """Convert a frozen normalization artifact into the dataset stats tensors.

    Round-trips through float32, matching the tensors used to compute the
    artifact, so protocol datasets consume the frozen values byte-for-byte.
    """
    return {
        key: torch.tensor(artifact[key], dtype=torch.float32)
        for key in ("sensor_mean", "sensor_std", "setting_mean", "setting_std")
    }


def _window_bounds_entry(windows) -> Dict[str, object]:
    """Summarize a canonical window list for split metadata.

    ``first``/``last`` pin the boundary windows, ``count`` fixes the size, and
    ``digest`` is the SHA-256 over the full ``[unit, start]`` list so any
    window-set change alters the split identity.
    """
    windows_list = [[int(unit), int(start)] for unit, start in windows]
    return {
        "count": len(windows_list),
        "first": windows_list[0],
        "last": windows_list[-1],
        "digest": split_identity_sha256({"windows": windows_list}),
    }


def _create_cmapss(
    data_root: Path,
    subset: str,
    seed: int,
    split_seed: int,
    history_len: int,
    pred_len: int,
    stride: int,
):
    data_dir = data_root / "CMAPSSData"
    train_frame = load_cmapss_frame(data_dir, subset, "train")
    units = sorted(int(unit) for unit in train_frame["unit"].unique())
    permutation = torch.randperm(len(units), generator=torch.Generator().manual_seed(split_seed)).tolist()
    shuffled = [units[idx] for idx in permutation]
    train_count = max(1, int(0.8 * len(shuffled)))
    train_engine_ids = sorted(shuffled[:train_count])
    valid_engine_ids = sorted(shuffled[train_count:])

    normalization = _cmapss_stats_artifact(train_frame, train_engine_ids)
    stats = _stats_tensors_from_artifact(normalization)
    train_base = CMapssWindowDataset(
        data_dir,
        subset=subset,
        split="train",
        history_len=history_len,
        pred_len=pred_len,
        stride=stride,
        async_mode="none",
        seed=seed,
        stats=stats,
    )
    test = CMapssWindowDataset(
        data_dir,
        subset=subset,
        split="test",
        history_len=history_len,
        pred_len=pred_len,
        stride=stride,
        async_mode="none",
        seed=seed,
        stats=stats,
    )
    train_windows = [window for window in train_base.windows if window[0] in set(train_engine_ids)]
    valid_windows = [window for window in train_base.windows if window[0] in set(valid_engine_ids)]
    train = _copy_with_windows(train_base, train_windows)
    valid = _copy_with_windows(train_base, valid_windows)
    window_bounds = {
        "train": _window_bounds_entry(train.windows),
        "valid": _window_bounds_entry(valid.windows),
        "test": _window_bounds_entry(test.windows),
    }
    split_identity = {
        "identity_version": 1,
        "dataset": f"cmapss_{subset.lower()}",
        "split_rule": "engine_id_80_20_official_test",
        "split_seed": int(split_seed),
        "history_len": int(history_len),
        "pred_len": int(pred_len),
        "stride": int(stride),
        "train_engine_ids": [int(unit) for unit in train_engine_ids],
        "valid_engine_ids": [int(unit) for unit in valid_engine_ids],
        "test_engine_count": int(test.frame["unit"].nunique()),
        "window_bounds": window_bounds,
        "normalization_sha256": normalization["sha256"],
    }
    split_info = {
        "dataset": f"cmapss_{subset.lower()}",
        "split_rule": "engine_id_80_20_official_test",
        "seed": seed,
        "split_seed": int(split_seed),
        "train_engine_ids": train_engine_ids,
        "valid_engine_ids": valid_engine_ids,
        "test_engine_count": int(test.frame["unit"].nunique()),
        "train_windows": len(train),
        "valid_windows": len(valid),
        "test_windows": len(test),
        "window_bounds": window_bounds,
        "split_identity": split_identity,
        "split_sha256": split_identity_sha256(split_identity),
        "normalization": normalization,
        "num_sensors": len(CMAPSS_SENSOR_COLUMNS),
        "context_dim": len(SETTING_COLUMNS),
        "label_rule": "risk = RUL <= threshold",
    }
    return ProtocolDatasets(
        name=f"cmapss_{subset.lower()}",
        train=train,
        valid=valid,
        test=test,
        split_info=split_info,
        num_sensors=len(CMAPSS_SENSOR_COLUMNS),
        context_dim=len(SETTING_COLUMNS),
    )


def _metro_stats(frame: pd.DataFrame):
    sensors = torch.tensor(frame[METROPT_SENSOR_COLUMNS].to_numpy(), dtype=torch.float32)
    context = torch.tensor(frame[METROPT_CONTEXT_COLUMNS].to_numpy(), dtype=torch.float32)
    sensor_std = sensors.std(dim=0)
    context_std = context.std(dim=0)
    sensor_std = torch.where(sensor_std < 1e-3, torch.ones_like(sensor_std), sensor_std)
    context_std = torch.where(context_std < 1e-3, torch.ones_like(context_std), context_std)
    return {
        "sensor_mean": sensors.mean(dim=0),
        "sensor_std": sensor_std,
        "context_mean": context.mean(dim=0),
        "context_std": context_std,
    }


def _metro_clone(base: MetroPTWindowDataset, frame: pd.DataFrame, stats, global_start: int):
    clone = copy.copy(base)
    clone.frame = frame.reset_index(drop=True)
    clone.stats = stats
    clone.global_start = int(global_start)
    clone.windows = clone._build_windows()
    if not clone.windows:
        raise ValueError("MetroPT protocol split produced no windows")
    return clone


def _create_metropt(data_root: Path, seed: int, history_len: int, pred_len: int, stride: int):
    data_dir = data_root / "metropt+3+dataset"
    full_frame = load_metropt_frame(data_dir)
    first_month = full_frame[
        (full_frame["timestamp"] >= pd.Timestamp("2020-02-01"))
        & (full_frame["timestamp"] < pd.Timestamp("2020-03-01"))
    ]
    train_rel_end = int(0.8 * len(first_month))
    train_frame = first_month.iloc[:train_rel_end]
    valid_frame = first_month.iloc[train_rel_end:]
    test_frame = full_frame[full_frame["timestamp"] >= pd.Timestamp("2020-03-01")]
    train_start = int(train_frame.index.min())
    valid_start = int(valid_frame.index.min())
    test_start = int(test_frame.index.min())
    stats = _metro_stats(train_frame)

    base = MetroPTWindowDataset(
        data_dir,
        split="all",
        history_len=history_len,
        pred_len=pred_len,
        stride=stride,
        async_mode="none",
        seed=seed,
    )
    train = _metro_clone(base, train_frame, stats, train_start)
    valid = _metro_clone(base, valid_frame, stats, valid_start)
    test = _metro_clone(base, test_frame, stats, test_start)
    split_info = {
        "dataset": "metropt3",
        "split_rule": "first_month_80_20_then_remaining_months",
        "seed": seed,
        "train_start": train_frame["timestamp"].iloc[0].isoformat(),
        "train_end": train_frame["timestamp"].iloc[-1].isoformat(),
        "valid_start": valid_frame["timestamp"].iloc[0].isoformat(),
        "valid_end": valid_frame["timestamp"].iloc[-1].isoformat(),
        "test_start": pd.Timestamp("2020-03-01").isoformat(),
        "test_first_observed": test_frame["timestamp"].iloc[0].isoformat(),
        "test_end": test_frame["timestamp"].iloc[-1].isoformat(),
        "train_rows": len(train_frame),
        "valid_rows": len(valid_frame),
        "test_rows": len(test_frame),
        "train_windows": len(train),
        "valid_windows": len(valid),
        "test_windows": len(test),
        "num_sensors": len(METROPT_SENSOR_COLUMNS),
        "context_dim": len(METROPT_CONTEXT_COLUMNS),
        "label_rule": "fault report interval and pre-fault warning windows",
    }
    return ProtocolDatasets(
        name="metropt3",
        train=train,
        valid=valid,
        test=test,
        split_info=split_info,
        num_sensors=len(METROPT_SENSOR_COLUMNS),
        context_dim=len(METROPT_CONTEXT_COLUMNS),
    )


def _create_metropt_chrono_602020(
    data_root: Path,
    seed: int,
    history_len: int,
    pred_len: int,
    stride: int,
):
    data_dir = data_root / "metropt+3+dataset"
    full_frame = load_metropt_frame(data_dir)
    train_end = int(0.6 * len(full_frame))
    valid_end = int(0.8 * len(full_frame))
    train_frame = full_frame.iloc[:train_end]
    valid_frame = full_frame.iloc[train_end:valid_end]
    test_frame = full_frame.iloc[valid_end:]
    train_start = int(train_frame.index.min())
    valid_start = int(valid_frame.index.min())
    test_start = int(test_frame.index.min())
    stats = _metro_stats(train_frame)

    base = MetroPTWindowDataset(
        data_dir,
        split="all",
        history_len=history_len,
        pred_len=pred_len,
        stride=stride,
        async_mode="none",
        seed=seed,
    )
    train = _metro_clone(base, train_frame, stats, train_start)
    valid = _metro_clone(base, valid_frame, stats, valid_start)
    test = _metro_clone(base, test_frame, stats, test_start)
    split_info = {
        "dataset": "metropt3_chrono_602020",
        "split_rule": "chronological_60_20_20_no_overlap",
        "seed": seed,
        "row_ratios": [0.6, 0.2, 0.2],
        "normalization_source": "train_only",
        "window_cross_boundary": False,
        "train_start": train_frame["timestamp"].iloc[0].isoformat(),
        "train_end": train_frame["timestamp"].iloc[-1].isoformat(),
        "valid_start": valid_frame["timestamp"].iloc[0].isoformat(),
        "valid_end": valid_frame["timestamp"].iloc[-1].isoformat(),
        "test_start": test_frame["timestamp"].iloc[0].isoformat(),
        "test_end": test_frame["timestamp"].iloc[-1].isoformat(),
        "train_rows": len(train_frame),
        "valid_rows": len(valid_frame),
        "test_rows": len(test_frame),
        "train_windows": len(train),
        "valid_windows": len(valid),
        "test_windows": len(test),
        "num_sensors": len(METROPT_SENSOR_COLUMNS),
        "context_dim": len(METROPT_CONTEXT_COLUMNS),
        "label_rule": "fault report interval and pre-fault warning windows",
    }
    return ProtocolDatasets(
        name="metropt3_chrono_602020",
        train=train,
        valid=valid,
        test=test,
        split_info=split_info,
        num_sensors=len(METROPT_SENSOR_COLUMNS),
        context_dim=len(METROPT_CONTEXT_COLUMNS),
    )


def _create_metropt_chrono_split(
    data_root: Path,
    seed: int,
    history_len: int,
    pred_len: int,
    stride: int,
    train_ratio: float,
    valid_ratio: float,
    dataset_name: str,
    split_rule: str,
):
    data_dir = data_root / "metropt+3+dataset"
    full_frame = load_metropt_frame(data_dir)
    train_end = int(train_ratio * len(full_frame))
    valid_end = int((train_ratio + valid_ratio) * len(full_frame))
    train_frame = full_frame.iloc[:train_end]
    valid_frame = full_frame.iloc[train_end:valid_end]
    test_frame = full_frame.iloc[valid_end:]
    train_start = int(train_frame.index.min())
    valid_start = int(valid_frame.index.min())
    test_start = int(test_frame.index.min())
    stats = _metro_stats(train_frame)

    base = MetroPTWindowDataset(
        data_dir,
        split="all",
        history_len=history_len,
        pred_len=pred_len,
        stride=stride,
        async_mode="none",
        seed=seed,
    )
    train = _metro_clone(base, train_frame, stats, train_start)
    valid = _metro_clone(base, valid_frame, stats, valid_start)
    test = _metro_clone(base, test_frame, stats, test_start)
    test_labels = test_frame["fault_label"]
    valid_labels = valid_frame["fault_label"]
    test_ratio = round(1.0 - train_ratio - valid_ratio, 10)
    split_info = {
        "dataset": dataset_name,
        "split_rule": split_rule,
        "seed": seed,
        "row_ratios": [train_ratio, valid_ratio, test_ratio],
        "normalization_source": "train_only",
        "window_cross_boundary": False,
        "train_start": train_frame["timestamp"].iloc[0].isoformat(),
        "train_end": train_frame["timestamp"].iloc[-1].isoformat(),
        "valid_start": valid_frame["timestamp"].iloc[0].isoformat(),
        "valid_end": valid_frame["timestamp"].iloc[-1].isoformat(),
        "test_start": test_frame["timestamp"].iloc[0].isoformat(),
        "test_end": test_frame["timestamp"].iloc[-1].isoformat(),
        "train_rows": len(train_frame),
        "valid_rows": len(valid_frame),
        "test_rows": len(test_frame),
        "valid_fault_rows": int(valid_labels.sum()),
        "test_fault_rows": int(test_labels.sum()),
        "valid_has_two_risk_classes": bool(valid_labels.nunique() >= 2),
        "test_has_two_risk_classes": bool(test_labels.nunique() >= 2),
        "train_windows": len(train),
        "valid_windows": len(valid),
        "test_windows": len(test),
        "num_sensors": len(METROPT_SENSOR_COLUMNS),
        "context_dim": len(METROPT_CONTEXT_COLUMNS),
        "label_rule": "fault report interval and pre-fault warning windows",
    }
    return ProtocolDatasets(
        name=dataset_name,
        train=train,
        valid=valid,
        test=test,
        split_info=split_info,
        num_sensors=len(METROPT_SENSOR_COLUMNS),
        context_dim=len(METROPT_CONTEXT_COLUMNS),
    )


def _create_metropt_chrono_502030(
    data_root: Path,
    seed: int,
    history_len: int,
    pred_len: int,
    stride: int,
):
    return _create_metropt_chrono_split(
        data_root=data_root,
        seed=seed,
        history_len=history_len,
        pred_len=pred_len,
        stride=stride,
        train_ratio=0.5,
        valid_ratio=0.2,
        dataset_name="metropt3_chrono_502030",
        split_rule="chronological_50_20_30_fault_evaluable_no_overlap",
    )


def _create_tep(
    data_root: Path,
    seed: int,
    split_seed: int,
    history_len: int,
    pred_len: int,
    stride: int,
):
    data_dir = data_root / "dataverse_files"
    if not data_dir.exists():
        raise FileNotFoundError(data_dir)

    train_full = load_tep_frame(data_dir, source="fault_free_training")
    test_frame = load_tep_frame(data_dir, source="fault_free_testing")
    runs = sorted(int(run) for run in train_full["simulationRun"].unique())
    permutation = torch.randperm(len(runs), generator=torch.Generator().manual_seed(split_seed)).tolist()
    shuffled = [runs[idx] for idx in permutation]
    train_count = max(1, int(0.8 * len(shuffled)))
    train_run_ids = sorted(shuffled[:train_count])
    valid_run_ids = sorted(shuffled[train_count:])
    if not valid_run_ids:
        raise ValueError("TEP protocol split produced no validation runs")

    train_frame = train_full[train_full["simulationRun"].isin(train_run_ids)].reset_index(drop=True)
    valid_frame = train_full[train_full["simulationRun"].isin(valid_run_ids)].reset_index(drop=True)
    stats = tep_training_stats(train_frame)
    dataset_kwargs = dict(
        data_dir=data_dir,
        history_len=history_len,
        pred_len=pred_len,
        stride=stride,
        async_mode="none",
        seed=seed,
        stats=stats,
    )
    train = TEPWindowDataset(
        source="fault_free_training",
        frame=train_frame,
        split="train",
        **dataset_kwargs,
    )
    valid = TEPWindowDataset(
        source="fault_free_training",
        frame=valid_frame,
        split="valid",
        **dataset_kwargs,
    )
    test = TEPWindowDataset(
        source="fault_free_testing",
        frame=test_frame,
        split="test",
        **dataset_kwargs,
    )
    split_info = {
        "dataset": "tep",
        "split_rule": "simulation_run_80_20_official_test",
        "seed": seed,
        "split_seed": int(split_seed),
        "sources": {
            "train_valid": "TEP_FaultFree_Training.RData",
            "test": "TEP_FaultFree_Testing.RData",
        },
        "train_run_ids": train_run_ids,
        "valid_run_ids": valid_run_ids,
        "test_run_count": int(test_frame["simulationRun"].nunique()),
        "train_rows": len(train_frame),
        "valid_rows": len(valid_frame),
        "test_rows": len(test_frame),
        "train_windows": len(train),
        "valid_windows": len(valid),
        "test_windows": len(test),
        "num_sensors": len(TEP_SENSOR_COLUMNS),
        "context_dim": len(TEP_CONTEXT_COLUMNS),
        "label_rule": "risk = faultNumber > 0 and sample >= 161; fault-free protocol labels are 0",
        "faulty_sources_note": (
            "Faulty TEP RData files are present but are not expanded by the default "
            "protocol because full materialization exceeds the current memory limit."
        ),
    }
    return ProtocolDatasets(
        name="tep",
        train=train,
        valid=valid,
        test=test,
        split_info=split_info,
        num_sensors=len(TEP_SENSOR_COLUMNS),
        context_dim=len(TEP_CONTEXT_COLUMNS),
    )


# ---------------------------------------------------------------------------
# MetroPT-3 v2 protocol (CH34-S01-T04): train-only normalization + public entry
# ---------------------------------------------------------------------------

_METROPT_V2_STD_FLOOR = 1e-6


def metropt_v2_stats_artifact(frame, train_source_row_ids, continuous_columns):
    """Frozen train-only normalization artifact over the continuous channels.

    Only rows whose ``source_row_id`` is in ``train_source_row_ids`` enter the
    mean/std, so valid/test values can never move the artifact. The binary
    history context is deliberately absent: by protocol policy it stays raw 0/1
    and is never z-scored.
    """
    train_frame = frame[frame["source_row_id"].isin(set(int(v) for v in train_source_row_ids))]
    values = torch.tensor(train_frame[list(continuous_columns)].to_numpy(), dtype=torch.float32)
    if values.numel() and not torch.isfinite(values).all():
        raise ValueError("non-finite continuous values in MetroPT v2 normalization source rows")
    payload = {
        "source_split": "train",
        "columns": list(continuous_columns),
        "count": int(len(train_frame)),
        "std_floor": _METROPT_V2_STD_FLOOR,
        "mean": [float(value) for value in values.mean(dim=0)],
        "std": [float(value) for value in values.std(dim=0).clamp_min(_METROPT_V2_STD_FLOOR)],
    }
    artifact = dict(payload)
    artifact["sha256"] = split_identity_sha256(payload)
    return artifact


def _create_metropt_chrono_502030_v2(
    data_root: Path,
    seed: int,
    history_len: int,
    pred_len: int,
    stride: int,
):
    from kaf_profiti.industrial.metropt import (
        GAP_MULTIPLIER,
        METROPT_BINARY_CONTEXT_COLUMNS,
        METROPT_CONTINUOUS_COLUMNS,
        METROPT_FAULT_WINDOWS,
        MetroPTChronoDataset,
        build_window_catalog,
        load_metropt_frame_v2,
        median_interval_seconds,
        metropt_time_scale_artifact,
        partition_sha,
        raw_data_sha,
        segmentize,
        split_chronological_by_timestamp_group,
        timeline_sha,
        window_catalog_sha,
    )

    dataset_name = "metropt3_chrono_502030_v2"
    data_dir = data_root / "metropt+3+dataset"
    frame = load_metropt_frame_v2(data_dir)
    train_ids, valid_ids, test_ids, split_meta = split_chronological_by_timestamp_group(frame)

    # every scientifically consumed value column participates in the raw
    # identity: the 7 prediction targets AND the 8 binary context channels
    raw_sha = raw_data_sha(frame, METROPT_CONTINUOUS_COLUMNS + METROPT_BINARY_CONTEXT_COLUMNS)
    partition = partition_sha(raw_sha, train_ids, valid_ids, test_ids)
    train_frame = frame[frame["source_row_id"].isin(set(int(v) for v in train_ids))]
    median_interval = median_interval_seconds(train_frame)
    gap_threshold = GAP_MULTIPLIER * median_interval
    time_scale = metropt_time_scale_artifact(train_frame)
    normalization = metropt_v2_stats_artifact(frame, train_ids, METROPT_CONTINUOUS_COLUMNS)
    stats = {
        "sensor_mean": torch.tensor(normalization["mean"], dtype=torch.float32),
        "sensor_std": torch.tensor(normalization["std"], dtype=torch.float32),
    }
    target_schema = {
        "continuous_columns": list(METROPT_CONTINUOUS_COLUMNS),
        "context_columns": list(METROPT_BINARY_CONTEXT_COLUMNS),
        "context_observation_policy": "fully_observed_history_last",
        "masked_channels": "7 continuous channels",
    }
    target_schema_sha256 = split_identity_sha256(target_schema)
    evaluator_identity = {
        "implementation": "kaf_profiti.experiments.accumulators.GlobalMetricAccumulator",
        "version": 1,
    }

    id_sets = {"train": train_ids, "valid": valid_ids, "test": test_ids}
    datasets, timeline_shas, catalog_shas, window_bounds = {}, {}, {}, {}
    for split in ("train", "valid", "test"):
        rows = frame[frame["source_row_id"].isin(set(int(v) for v in id_sets[split]))]
        segments = segmentize(rows, threshold_seconds=gap_threshold, reject_duplicate_timestamps=True)
        split_timeline_sha = timeline_sha(partition, segments)
        records = build_window_catalog(
            segments, history_len, pred_len, stride, dataset_name, split, split_timeline_sha
        )
        datasets[split] = MetroPTChronoDataset(
            segments,
            records,
            history_len,
            pred_len,
            METROPT_CONTINUOUS_COLUMNS,
            METROPT_BINARY_CONTEXT_COLUMNS,
            fault_windows=METROPT_FAULT_WINDOWS,
            median_interval=median_interval,
            stats=stats,
        )
        timeline_shas[split] = split_timeline_sha
        catalog_shas[split] = window_catalog_sha(split_timeline_sha, history_len, pred_len, stride, records)
        window_bounds[split] = _window_bounds_entry(datasets[split].windows)

    split_identity = {
        "identity_version": 1,
        "dataset": dataset_name,
        "split_rule": "timestamp_group_chronological_50_20_30_segment_v2",
        # the run seed must never influence the split identity; MetroPT v2
        # splits chronologically, so no split seed applies at all
        "split_seed_applicability": "not_applicable_chronological",
        "history_len": int(history_len),
        "pred_len": int(pred_len),
        "stride": int(stride),
        "row_ratios": [0.5, 0.2, 0.3],
        "train_rows": len(train_ids),
        "valid_rows": len(valid_ids),
        "test_rows": len(test_ids),
        "train_median_interval_seconds": float(median_interval),
        "gap_threshold_seconds": float(gap_threshold),
        "raw_data_sha256": raw_sha,
        "partition_sha256": partition,
        "timeline_sha256": timeline_shas,
        "window_catalog_sha256": catalog_shas,
        "normalization_sha256": normalization["sha256"],
        "time_scale_sha256": time_scale["sha256"],
        "target_schema": target_schema,
        "target_schema_sha256": target_schema_sha256,
        "evaluator": evaluator_identity,
        "fault_windows": [[start, end] for start, end in METROPT_FAULT_WINDOWS],
        "label_rule": "risk = query timestamp intersects registered fault interval",
        "window_bounds": window_bounds,
    }
    split_info = {
        "dataset": dataset_name,
        "split_rule": split_identity["split_rule"],
        "split_seed": "not_applicable_chronological",
        "boundaries": split_meta,
        "train_rows": len(train_ids),
        "valid_rows": len(valid_ids),
        "test_rows": len(test_ids),
        "train_windows": len(datasets["train"]),
        "valid_windows": len(datasets["valid"]),
        "test_windows": len(datasets["test"]),
        "train_median_interval_seconds": float(median_interval),
        "gap_threshold_seconds": float(gap_threshold),
        "time_scale": time_scale,
        "normalization": normalization,
        "target_schema": target_schema,
        "target_schema_sha256": target_schema_sha256,
        "evaluator": evaluator_identity,
        "window_bounds": window_bounds,
        "split_identity": split_identity,
        "split_sha256": split_identity_sha256(split_identity),
        "num_sensors": len(METROPT_CONTINUOUS_COLUMNS),
        "context_dim": len(METROPT_BINARY_CONTEXT_COLUMNS),
        "context_observation_policy": "fully_observed_history_last",
        "masked_channels": "7 continuous channels",
        "label_rule": "risk = query timestamp intersects registered fault interval",
    }
    return ProtocolDatasets(
        name=dataset_name,
        train=datasets["train"],
        valid=datasets["valid"],
        test=datasets["test"],
        split_info=split_info,
        num_sensors=len(METROPT_CONTINUOUS_COLUMNS),
        context_dim=len(METROPT_BINARY_CONTEXT_COLUMNS),
    )
