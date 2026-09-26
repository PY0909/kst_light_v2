import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import torch
from torch import Tensor
from torch.utils.data import Dataset

from .missing import MissingMechanismSimulator


METROPT_SENSOR_COLUMNS = [
    "TP2",
    "TP3",
    "H1",
    "DV_pressure",
    "Reservoirs",
    "Oil_temperature",
    "Motor_current",
    "COMP",
    "DV_eletric",
    "Towers",
    "MPG",
    "LPS",
    "Pressure_switch",
    "Oil_level",
    "Caudal_impulses",
]
METROPT_CONTINUOUS_COLUMNS = [
    "TP2",
    "TP3",
    "H1",
    "DV_pressure",
    "Reservoirs",
    "Oil_temperature",
    "Motor_current",
]
METROPT_BINARY_CONTEXT_COLUMNS = [
    "COMP",
    "DV_eletric",
    "Towers",
    "MPG",
    "LPS",
    "Pressure_switch",
    "Oil_level",
    "Caudal_impulses",
]
METROPT_CONTEXT_COLUMNS = ["COMP", "DV_eletric", "MPG"]
GAP_MULTIPLIER = 3.0
METROPT_FAULT_WINDOWS = [
    ("2020-04-18 00:00:00", "2020-04-18 23:59:00"),
    ("2020-05-29 23:30:00", "2020-05-30 06:00:00"),
    ("2020-06-05 10:00:00", "2020-06-07 14:30:00"),
    ("2020-07-15 14:30:00", "2020-07-15 19:00:00"),
]
CSV_NAME = "MetroPT3(AirCompressor).csv"
_METROPT_FRAME_CACHE = {}


@dataclass
class MetroPTWindowSample:
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


def load_metropt_frame(data_dir: Path) -> pd.DataFrame:
    data_dir = Path(data_dir)
    csv_path = data_dir / CSV_NAME
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)
    cache_key = str(csv_path.resolve())
    if cache_key in _METROPT_FRAME_CACHE:
        return _METROPT_FRAME_CACHE[cache_key].copy()

    # Same canonical float parse as load_metropt_frame_v2: keeps v1/v2 loads
    # byte-identical for the same CSV regardless of the pandas build.
    frame = pd.read_csv(
        csv_path,
        index_col=0,
        parse_dates=["timestamp"],
        float_precision="round_trip",
    )
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    missing = [col for col in METROPT_SENSOR_COLUMNS if col not in frame.columns]
    if missing:
        raise ValueError(f"MetroPT CSV missing sensor columns: {missing}")
    frame["fault_label"] = 0
    for start, end in METROPT_FAULT_WINDOWS:
        mask = (frame["timestamp"] >= pd.Timestamp(start)) & (
            frame["timestamp"] <= pd.Timestamp(end)
        )
        frame.loc[mask, "fault_label"] = 1
    frame["relative_time"] = (
        frame["timestamp"] - frame["timestamp"].iloc[0]
    ).dt.total_seconds()
    _METROPT_FRAME_CACHE[cache_key] = frame
    return frame.copy()


def _split_bounds(length: int, split: str, train_ratio: float, valid_ratio: float) -> Tuple[int, int]:
    split = split.lower()
    train_end = int(length * train_ratio)
    valid_end = int(length * (train_ratio + valid_ratio))
    if split == "train":
        return 0, train_end
    if split in {"valid", "val"}:
        return train_end, valid_end
    if split == "test":
        return valid_end, length
    if split == "all":
        return 0, length
    raise ValueError("split must be one of train, valid, test, all")


def _stats_from_frame(frame: pd.DataFrame, train_ratio: float) -> Dict[str, Tensor]:
    train_end = int(len(frame) * train_ratio)
    train_frame = frame.iloc[:train_end]
    sensors = torch.tensor(train_frame[METROPT_SENSOR_COLUMNS].to_numpy(), dtype=torch.float32)
    context = torch.tensor(train_frame[METROPT_CONTEXT_COLUMNS].to_numpy(), dtype=torch.float32)
    return {
        "sensor_mean": sensors.mean(dim=0),
        "sensor_std": sensors.std(dim=0).clamp_min(1e-6),
        "context_mean": context.mean(dim=0),
        "context_std": context.std(dim=0).clamp_min(1e-6),
    }


class MetroPTWindowDataset(Dataset):
    def __init__(
        self,
        data_dir,
        split: str = "train",
        history_len: int = 60,
        pred_len: int = 12,
        stride: int = 12,
        async_mode: str = "mixed",
        seed: int = 42,
        normalize: bool = True,
        context_mode: str = "mean",
        train_ratio: float = 0.7,
        valid_ratio: float = 0.15,
    ):
        self.data_dir = Path(data_dir)
        self.split = split
        self.history_len = int(history_len)
        self.pred_len = int(pred_len)
        self.stride = int(stride)
        self.async_mode = async_mode
        self.seed = int(seed)
        self.normalize = bool(normalize)
        self.context_mode = context_mode
        self.train_ratio = float(train_ratio)
        self.valid_ratio = float(valid_ratio)

        if self.history_len <= 0 or self.pred_len <= 0:
            raise ValueError("history_len and pred_len must be positive")
        if self.stride <= 0:
            raise ValueError("stride must be positive")
        if context_mode not in {"mean", "last"}:
            raise ValueError("context_mode must be 'mean' or 'last'")
        if not 0 < train_ratio < 1:
            raise ValueError("train_ratio must be between 0 and 1")
        if not 0 <= valid_ratio < 1 or train_ratio + valid_ratio >= 1:
            raise ValueError("train_ratio + valid_ratio must be less than 1")

        full_frame = load_metropt_frame(self.data_dir)
        self.stats = _stats_from_frame(full_frame, self.train_ratio) if normalize else None
        start, end = _split_bounds(len(full_frame), split, self.train_ratio, self.valid_ratio)
        self.frame = full_frame.iloc[start:end].reset_index(drop=True)
        self.global_start = start
        self.masker = MissingMechanismSimulator(mode=async_mode)
        self.windows = self._build_windows()
        if not self.windows:
            raise ValueError(
                f"No MetroPT windows for split={split}; reduce history_len or pred_len"
            )

    def _build_windows(self) -> List[int]:
        total_len = self.history_len + self.pred_len
        limit = len(self.frame) - total_len + 1
        return list(range(0, max(0, limit), self.stride))

    def __len__(self) -> int:
        return len(self.windows)

    def __getitem__(self, index: int) -> MetroPTWindowSample:
        start = self.windows[index]
        hist = self.frame.iloc[start : start + self.history_len]
        fut = self.frame.iloc[start + self.history_len : start + self.history_len + self.pred_len]

        sensors_hist = torch.tensor(hist[METROPT_SENSOR_COLUMNS].to_numpy(), dtype=torch.float32)
        sensors_future = torch.tensor(fut[METROPT_SENSOR_COLUMNS].to_numpy(), dtype=torch.float32)
        context_hist = torch.tensor(hist[METROPT_CONTEXT_COLUMNS].to_numpy(), dtype=torch.float32)
        if self.normalize:
            sensors_hist = (
                sensors_hist - self.stats["sensor_mean"]
            ) / self.stats["sensor_std"]
            sensors_future = (
                sensors_future - self.stats["sensor_mean"]
            ) / self.stats["sensor_std"]
            context_hist = (
                context_hist - self.stats["context_mean"]
            ) / self.stats["context_std"]

        context = context_hist.mean(dim=0) if self.context_mode == "mean" else context_hist[-1]
        mask_seed = self.seed + (self.global_start + start) * 1009
        M_obs = self.masker((self.history_len, len(METROPT_SENSOR_COLUMNS)), mask_seed)
        X_obs = sensors_hist * M_obs
        future_fault = float(fut["fault_label"].max())

        return MetroPTWindowSample(
            X_obs=X_obs,
            T_obs=torch.arange(self.history_len, dtype=torch.float32),
            M_obs=M_obs,
            T_q=torch.arange(
                self.history_len,
                self.history_len + self.pred_len,
                dtype=torch.float32,
            ),
            Y_q=sensors_future,
            M_q=torch.ones_like(sensors_future),
            context=context,
            rul=future_fault,
            unit_id=0,
        )


# ---------------------------------------------------------------------------
# CH34-S01-T01: private MetroPT v2 catalog (source rows, split, segments,
# windows). Kept private this task; a public dataset entry is added only at
# T04 once normalization/masks complete the protocol identity.
# ---------------------------------------------------------------------------


def _sha256_canonical(payload: Dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def load_metropt_frame_v2(data_dir) -> pd.DataFrame:
    """Load MetroPT CSV preserving a unique stable ``source_row_id``.

    The original CSV row index (``Unnamed: 0``, present in the MetroPT files)
    becomes ``source_row_id``; rows are sorted by ``(timestamp, source_row_id)``
    so shuffle order is never a silent input to the protocol. ``source_row_id``
    is asserted unique (a duplicate would make window provenance ambiguous).
    """
    path = Path(data_dir) / CSV_NAME
    if not path.exists():
        raise FileNotFoundError(path)
    # float_precision="round_trip" pins the correctly-rounded decimal->binary
    # conversion: the default xstrtod path is allowed ~1 ULP error and its
    # result differs between pandas builds (macOS arm64 vs linux x86_64),
    # which silently made raw_data_sha and every chained protocol SHA
    # machine-dependent (found by the CH34-S03-T01 cross-machine preflight).
    frame = pd.read_csv(
        path, parse_dates=["timestamp"], float_precision="round_trip"
    )
    if "Unnamed: 0" in frame.columns:
        sourceless = frame.rename(columns={"Unnamed: 0": "source_row_id"})
    elif "source_row_id" in frame.columns:
        sourceless = frame
    else:
        sourceless = frame.copy()
        sourceless["source_row_id"] = range(len(frame))
    if not sourceless["source_row_id"].is_unique:
        raise ValueError("MetroPT v2 source_row_id is not unique")
    return sourceless.sort_values(["timestamp", "source_row_id"]).reset_index(drop=True)


def median_interval_seconds(frame: pd.DataFrame, timestamp: str = "timestamp") -> float:
    """Median inter-sample interval (seconds) over unique sorted timestamps.

    Unit-robust by construction: ``.dt.total_seconds()`` works on any
    datetime64 resolution. (The earlier ``astype("int64") / 1e9`` assumed
    nanosecond resolution — true for pandas 2.x, but pandas 3.0 changed the
    default datetime unit to microseconds, silently shrinking the interval
    1000x, collapsing every segment, and emptying the window catalog.)
    """
    import numpy as np

    values = pd.to_datetime(frame[timestamp]).drop_duplicates().sort_values()
    diffs = (
        values.diff().dropna().dt.total_seconds().to_numpy()
        if len(values) > 1
        else []
    )
    if len(diffs) == 0 or np.all(diffs <= 0):
        raise ValueError("cannot derive a positive median sample interval")
    return float(np.median(diffs))


def split_chronological_by_timestamp_group(frame, ratios=(0.5, 0.2), timestamp="timestamp", source="source_row_id"):
    """Chronological timestamp-group split by row-count ratio.

    Rows are assumed sorted by ``(timestamp, source_row_id)``. Target absolute
    row boundaries are ``ratios`` against total rows; the legal cut is the
    timestamp-group end nearest the target (ties choose the earlier end), with
    both boundaries strictly increasing and all three splits non-empty. Returns
    ``(train_ids, valid_ids, test_ids, meta)``.
    """
    total = int(len(frame))
    if total < 3:
        raise ValueError("too few rows to split into three non-empty partitions")
    groups = frame.groupby(timestamp, sort=True)
    cumuls = list(groups.size().cumsum())  # cumulative row index at each group end
    ends = list(dict.fromkeys(int(c) for c in cumuls))  # legal cut positions

    def nearest(target: float, allowed) -> int:
        allowed = sorted(allowed)
        best = min(allowed, key=lambda end: (abs(end - target), end))  # tie -> earlier (smaller end)
        return best

    target1, target2 = total * ratios[0], total * (ratios[0] + ratios[1])
    b1 = nearest(target1, [e for e in ends if 0 < e < total])
    b2 = nearest(target2, [e for e in ends if e > b1 < total and e < total])
    # strictly increasing + non-empty final partition
    if not (0 < b1 < b2 < total):
        raise ValueError(f"split produced invalid boundaries b1={b1} b2={b2} total={total}")

    ids = frame[source].astype(int).tolist()
    train_ids = ids[:b1]
    valid_ids = ids[b1:b2]
    test_ids = ids[b2:]

    def boundary_meta(target_rows, actual_rows):
        return {
            "target_rows": float(target_rows),
            "actual_rows": int(actual_rows),
            "boundary_time": frame[timestamp].iloc[actual_rows - 1].timestamp() if actual_rows <= len(frame) else None,
        }

    meta = {
        "total_rows": total,
        "target_ratios": list(ratios),
        "boundaries": [
            boundary_meta(target1, b1),
            boundary_meta(target2, b2),
        ],
        "actual_rows": {"train": len(train_ids), "valid": len(valid_ids), "test": len(test_ids)},
    }
    return train_ids, valid_ids, test_ids, meta


def segmentize(frame, threshold_seconds: float, timestamp="timestamp", reject_duplicate_timestamps=False):
    """Split a (split-local, sorted) frame into gap-free segments.

    A segment boundary is placed wherever the gap to the next row exceeds
    ``threshold_seconds``. Returns a list of DataFrames (one per segment, in
    chronological order); the list index is the ``segment_id``.
    """
    if len(frame) == 0:
        return []
    if reject_duplicate_timestamps and frame[timestamp].duplicated().any():
        raise ValueError("MetroPT v2 catalog rejects duplicate timestamps (no aggregation rule)")
    diffs = frame[timestamp].diff().dt.total_seconds()
    boundaries = [0]
    for index in range(1, len(frame)):
        if diffs.iloc[index] > threshold_seconds:
            boundaries.append(index)
    boundaries.append(len(frame))
    return [
        frame.iloc[boundaries[i] : boundaries[i + 1]].reset_index(drop=True)
        for i in range(len(boundaries) - 1)
    ]


@dataclass(frozen=True)
class WindowRecord:
    """One canonical forecast window in the MetroPT v2 catalog.

    ``start`` is a row offset within ``segment_id``'s frame. ``window_id`` is a
    content SHA over the timeline layer (segment identity + forecast/query
    timestamps) and never over a window-bounds-containing split SHA, so no
    "split SHA <-> window SHA" cycle exists.
    """

    segment_id: int
    start: int
    forecast_timestamp: float
    query_timestamps: Tuple[float, ...]
    query_row_ids: Tuple[int, ...]
    window_id: str


def build_window_catalog(
    segments,
    history_len: int,
    pred_len: int,
    stride: int,
    dataset: str,
    split: str,
    timeline_sha: str,
) -> List[WindowRecord]:
    """Build every window fully inside each segment (never crossing a gap)."""
    records: List[WindowRecord] = []
    for segment_id, segment in enumerate(segments):
        total = len(segment)
        limit = total - history_len - pred_len + 1
        ts = segment["timestamp"].map(pd.Timestamp.timestamp)
        source_ids = segment["source_row_id"].astype(int).tolist()
        for start in range(0, max(0, limit), stride):
            forecast_ts = float(ts.iloc[start + history_len - 1])
            query_ts = tuple(float(value) for value in ts.iloc[start + history_len : start + history_len + pred_len])
            query_ids = tuple(int(value) for value in source_ids[start + history_len : start + history_len + pred_len])
            window_id = _sha256_canonical(
                {
                    "dataset": dataset,
                    "split": split,
                    "segment_id": segment_id,
                    "forecast_timestamp": forecast_ts,
                    "query_timestamps": list(query_ts),
                    "query_row_ids": list(query_ids),
                    "timeline_sha256": timeline_sha,
                }
            )
            records.append(WindowRecord(segment_id, start, forecast_ts, query_ts, query_ids, window_id))
    return records


# ---------------------------------------------------------------------------
# Layered protocol SHAs (raw -> partition -> timeline -> window catalog).
# Each layer depends only on strictly lower layers, so there is no cycle:
#   raw_data_sha -> partition_sha -> timeline_sha -> window_catalog_sha
#   (normalization_sha joins at T04 to form the final protocol_sha).
# window_id uses the timeline layer + the window's own rows, never a
# window-bounds-containing split SHA.
# ---------------------------------------------------------------------------


def raw_data_sha(frame, value_columns, timestamp="timestamp", source="source_row_id") -> str:
    """Content SHA over the chronologically ordered raw rows.

    Hashes the column identity (names and order) plus the exact byte content
    (int row ids, int64-ns timestamps, float64 values) so it depends only on
    the source data and schema, never on dict order or float formatting.
    Callers must pass every scientifically consumed value column (targets AND
    context), not only the prediction targets.
    """
    import numpy as np

    # Normalize to nanosecond resolution before the int64 cast: pandas 2.x
    # datetimes are already ns, but pandas 3.0 defaults to microseconds, which
    # would silently change every timestamp byte and thus the identity SHA.
    timestamps_ns = pd.to_datetime(frame[timestamp]).astype("datetime64[ns]")
    columns = list(value_columns)
    digest = hashlib.sha256()
    digest.update(("|".join(columns)).encode("utf-8"))
    digest.update(b"\x00")
    digest.update(np.asarray(frame[source], dtype=np.int64).tobytes())
    digest.update(np.asarray(timestamps_ns.astype("int64"), dtype=np.int64).tobytes())
    digest.update(np.asarray(frame[columns], dtype=np.float64).tobytes())
    return digest.hexdigest()


def partition_sha(raw_sha: str, train_ids, valid_ids, test_ids) -> str:
    return _sha256_canonical(
        {
            "raw_data_sha256": raw_sha,
            "train": sorted(int(v) for v in train_ids),
            "valid": sorted(int(v) for v in valid_ids),
            "test": sorted(int(v) for v in test_ids),
        }
    )


def timeline_sha(partition_sha256: str, segments) -> str:
    """SHA over per-segment row membership relative to the partition."""
    seg_map = {}
    for segment_id, segment in enumerate(segments):
        seg_map[str(segment_id)] = sorted(int(v) for v in segment["source_row_id"])
    return _sha256_canonical({"partition_sha256": partition_sha256, "segments": seg_map})


def window_catalog_sha(
    timeline_sha256: str,
    history_len: int,
    pred_len: int,
    stride: int,
    records,
) -> str:
    """SHA over the COMPLETE window catalog (every record), not just ends."""
    return _sha256_canonical(
        {
            "timeline_sha256": timeline_sha256,
            "history_len": int(history_len),
            "pred_len": int(pred_len),
            "stride": int(stride),
            "count": len(records),
            "records": [
                {
                    "window_id": record.window_id,
                    "segment_id": int(record.segment_id),
                    "start": int(record.start),
                    "query_row_ids": [int(v) for v in record.query_row_ids],
                }
                for record in records
            ],
        }
    )


class MetroPTChronoDataset(Dataset):
    """C-MAPSS-shaped MetroPT v2 dataset (segment-as-unit) producing a sample
    with 7 continuous targets and an 8-dimensional binary history context.

    ``segments`` is the T01 list of per-segment frames; ``records`` is the
    T01 ``WindowRecord`` catalog. ``_units`` maps segment_id -> frame and
    ``windows`` is ``[(segment_id, start)]`` so the timeline-mask machinery and
    the provider can slice masks by segment the same way C-MAPSS slices by
    engine. ``sample.unit_id`` stays the physical device id ``0``; segment and
    window identity live on the artifact tracking record, never as an
    independent statistical unit.
    """

    def __init__(
        self,
        segments,
        records,
        history_len: int,
        pred_len: int,
        continuous_columns,
        context_columns,
        fault_windows=None,
        median_interval: float = None,
        stats: Dict[str, Tensor] = None,
    ):
        self._units = {int(index): segment.reset_index(drop=True) for index, segment in enumerate(segments)}
        self._records = list(records)
        self.windows = [(record.segment_id, record.start) for record in self._records]
        self.window_ids = [record.window_id for record in self._records]
        self.history_len = int(history_len)
        self.pred_len = int(pred_len)
        self.continuous = list(continuous_columns)
        self.context_cols = list(context_columns)
        self.fault_windows = fault_windows
        self.median_interval = median_interval
        self.stats = stats
        self._validate_columns()
        self._validate_context_binary()

    def _validate_columns(self):
        required = list(self.continuous) + list(self.context_cols)
        for segment_id, seg in self._units.items():
            cols = list(seg.columns)
            missing = [c for c in required if c not in cols]
            if missing:
                raise ValueError(f"MetroPT v2 segment {segment_id} missing column(s): {' '.join(missing)}")
            positions = [cols.index(c) for c in required]
            if len(set(positions)) != len(positions):
                raise ValueError(f"MetroPT v2 segment {segment_id} has duplicate columns")
            if positions != sorted(positions):
                raise ValueError(
                    "MetroPT v2 column order drift: continuous/context columns must keep fixed order"
                )

    def _validate_context_binary(self):
        for segment_id, seg in self._units.items():
            for col in self.context_cols:
                bad = ~seg[col].isin([0, 1])
                if bool(bad.any()):
                    row_id = int(seg.loc[bad, "source_row_id"].iloc[0])
                    raise ValueError(
                        f"MetroPT v2 binary context column {col} has a non-0/1 value "
                        f"at source_row_id {row_id}"
                    )

    def __len__(self) -> int:
        return len(self._records)

    def _risk(self, fut) -> float:
        if not self.fault_windows:
            return 0.0
        query_ts = pd.to_datetime(fut["timestamp"])
        for start, end in self.fault_windows:
            if bool(((query_ts >= pd.Timestamp(start)) & (query_ts <= pd.Timestamp(end))).any()):
                return 1.0
        return 0.0

    def __getitem__(self, index: int) -> MetroPTWindowSample:
        record = self._records[index]
        segment = self._units[record.segment_id]
        hist = segment.iloc[record.start : record.start + self.history_len]
        fut = segment.iloc[
            record.start + self.history_len : record.start + self.history_len + self.pred_len
        ]
        X_obs = torch.tensor(hist[self.continuous].to_numpy(), dtype=torch.float32)
        Y_q = torch.tensor(fut[self.continuous].to_numpy(), dtype=torch.float32)
        if self.stats is not None:
            # train-only normalization over the 7 continuous channels only;
            # the binary context stays raw 0/1 by protocol policy.
            X_obs = (X_obs - self.stats["sensor_mean"]) / self.stats["sensor_std"]
            Y_q = (Y_q - self.stats["sensor_mean"]) / self.stats["sensor_std"]
        M_obs = torch.ones_like(X_obs)
        M_q = torch.ones_like(Y_q)
        context = torch.tensor(
            hist[self.context_cols].iloc[-1].to_numpy(dtype="float32")
        )
        T_obs, T_q = self._real_time(segment, record)
        return MetroPTWindowSample(
            X_obs=X_obs,
            T_obs=T_obs,
            M_obs=M_obs,
            T_q=T_q,
            Y_q=Y_q,
            M_q=M_q,
            context=context,
            rul=self._risk(fut),
            unit_id=0,
            window_id=record.window_id,
            risk_label=self._risk(fut),
        )

    def _real_time(self, segment, record):
        """Real timestamps relative to the segment start, scaled by the train
        median interval: keeps jitter (e.g. diffs ``[1.0, 1.1, 1.0]``) instead
        of collapsing to an equidistant ``arange``."""
        if self.median_interval is None or self.median_interval <= 0:
            raise ValueError("MetroPT v2 real time requires a positive train median_interval")
        hist_ts = segment["timestamp"].iloc[
            record.start : record.start + self.history_len
        ]
        fut_ts = segment["timestamp"].iloc[
            record.start + self.history_len : record.start + self.history_len + self.pred_len
        ]
        origin = hist_ts.iloc[0]
        scale = self.median_interval
        T_obs = ((hist_ts - origin).dt.total_seconds() / scale).to_numpy(dtype="float32")
        T_q = ((fut_ts - origin).dt.total_seconds() / scale).to_numpy(dtype="float32")
        return (
            torch.tensor(T_obs, dtype=torch.float32),
            torch.tensor(T_q, dtype=torch.float32),
        )


def metropt_time_scale_artifact(train_frame, timestamp="timestamp") -> Dict[str, object]:
    """Nominal time scale artifact derived only from the train split.

    Records the raw unit (seconds), the train median sample interval, and a
    content SHA. ``T_obs``/``T_q`` are divided by this interval so a nominal
    10-second cadence maps to diffs around 1.0 while true jitter is preserved.
    """
    median = median_interval_seconds(train_frame, timestamp)
    payload = {
        "unit": "seconds",
        "source": "train",
        "median_interval_seconds": float(median),
    }
    artifact = dict(payload)
    artifact["sha256"] = _sha256_canonical(payload)
    return artifact
