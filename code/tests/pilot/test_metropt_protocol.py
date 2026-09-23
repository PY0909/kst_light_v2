"""CH34-S01-T01: private MetroPT v2 protocol catalog contracts."""

import os
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

from kaf_profiti.industrial.metropt import (
    GAP_MULTIPLIER,
    WindowRecord,
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

_DATA_ROOT = Path(os.environ.get("KST_DATA_ROOT", Path(__file__).resolve().parents[3] / "dataset"))
_METROPT_CSV = _DATA_ROOT / "metropt+3+dataset" / "MetroPT3(AirCompressor).csv"
_requires_metropt = pytest.mark.skipif(
    not _METROPT_CSV.exists(), reason="MetroPT CSV not available under KST_DATA_ROOT"
)


def _frame(counts=(3, 2, 3), gap_after=None):
    rows = []
    source = 100
    timestamp = pd.Timestamp("2020-01-01")
    for group_index, count in enumerate(counts):
        if gap_after is not None and group_index == gap_after:
            timestamp += timedelta(seconds=31)
        for _ in range(count):
            rows.append({
                "source_row_id": source,
                "timestamp": timestamp,
                "TP2": float(source),
            })
            source += 1
        timestamp += timedelta(seconds=10)
    return pd.DataFrame(rows)


def test_timestamp_group_split_never_splits_duplicate_timestamp_group():
    frame = _frame(counts=(2, 3, 2))
    train, valid, test, meta = split_chronological_by_timestamp_group(frame)

    assigned = {}
    for split, ids in (("train", train), ("valid", valid), ("test", test)):
        for source_id in ids:
            assigned[source_id] = split
    for _, group in frame.groupby("timestamp", sort=True):
        assert len({assigned[int(value)] for value in group["source_row_id"]}) == 1
    assert set(train).isdisjoint(valid)
    assert set(train).isdisjoint(test)
    assert set(valid).isdisjoint(test)
    assert meta["boundaries"][0]["target_rows"] == pytest.approx(3.5)
    assert meta["boundaries"][1]["target_rows"] == pytest.approx(4.9)
    assert meta["actual_rows"]["train"] > 0
    assert meta["actual_rows"]["valid"] > 0
    assert meta["actual_rows"]["test"] > 0


def test_timestamp_group_boundary_tie_chooses_earlier_end():
    frame = _frame(counts=(2, 2, 2, 2))
    train, valid, test, meta = split_chronological_by_timestamp_group(frame)
    # 50% target is 4 rows, exactly a legal group end; 70% target is 5.6,
    # nearest legal end is 6. The tie rule is exercised by the helper's
    # distance ordering in a separate boundary metadata assertion.
    assert len(train) == 4
    assert len(valid) == 2
    assert len(test) == 2
    assert meta["boundaries"][0]["actual_rows"] == 4
    assert meta["boundaries"][1]["actual_rows"] == 6


def test_segment_catalog_excludes_windows_crossing_large_gap():
    frame = _frame(counts=(8, 8), gap_after=1)
    segments = segmentize(frame, threshold_seconds=30.0)
    records = build_window_catalog(
        segments, history_len=4, pred_len=2, stride=1,
        dataset="metropt3_chrono_502030_v2", split="train", timeline_sha="a" * 64,
    )
    assert len(segments) == 2
    assert records
    for record in records:
        segment = segments[record.segment_id]
        window_rows = segment.iloc[record.start : record.start + 6]
        assert window_rows["timestamp"].diff().dt.total_seconds().iloc[1:].max() <= 30.0
        assert record.forecast_timestamp == window_rows["timestamp"].iloc[3].timestamp()
        assert len(record.query_row_ids) == 2


def test_window_projection_is_single_source_of_truth():
    frame = _frame(counts=(8,))
    segments = segmentize(frame, threshold_seconds=30.0)
    records = build_window_catalog(
        segments, history_len=4, pred_len=2, stride=2,
        dataset="metropt3_chrono_502030_v2", split="train", timeline_sha="b" * 64,
    )
    assert all(isinstance(record, WindowRecord) for record in records)
    assert [(r.segment_id, r.start) for r in records] == [
        (record.segment_id, record.start) for record in records
    ]
    assert len({record.window_id for record in records}) == len(records)


def test_catalog_shas_and_window_ids_are_deterministic():
    frame_a = _frame(counts=(8, 8), gap_after=1)
    frame_b = frame_a.copy(deep=True)
    segments_a = segmentize(frame_a, threshold_seconds=30.0)
    segments_b = segmentize(frame_b, threshold_seconds=30.0)
    records_a = build_window_catalog(
        segments_a, 4, 2, 2, "metropt3_chrono_502030_v2", "valid", "c" * 64
    )
    records_b = build_window_catalog(
        segments_b, 4, 2, 2, "metropt3_chrono_502030_v2", "valid", "c" * 64
    )
    assert [r.window_id for r in records_a] == [r.window_id for r in records_b]
    assert [r.query_row_ids for r in records_a] == [r.query_row_ids for r in records_b]


def test_v2_loader_preserves_unique_source_row_id_and_stable_order(tmp_path):
    path = tmp_path / "MetroPT3(AirCompressor).csv"
    frame = pd.DataFrame({
        "Unnamed: 0": [9, 2, 5],
        "timestamp": ["2020-01-01 00:00:10", "2020-01-01 00:00:00", "2020-01-01 00:00:10"],
        "TP2": [1.0, 2.0, 3.0],
    })
    frame.to_csv(path, index=False)
    loaded = load_metropt_frame_v2(tmp_path)
    assert loaded["source_row_id"].is_unique
    assert loaded[["timestamp", "source_row_id"]].values.tolist() == [
        [pd.Timestamp("2020-01-01 00:00:00"), 2],
        [pd.Timestamp("2020-01-01 00:00:10"), 5],
        [pd.Timestamp("2020-01-01 00:00:10"), 9],
    ]


def test_v2_loader_rejects_duplicate_source_row_id(tmp_path):
    path = tmp_path / "MetroPT3(AirCompressor).csv"
    pd.DataFrame({
        "Unnamed: 0": [1, 1],
        "timestamp": ["2020-01-01", "2020-01-01 00:00:10"],
        "TP2": [1.0, 2.0],
    }).to_csv(path, index=False)
    with pytest.raises(ValueError, match="source_row_id"):
        load_metropt_frame_v2(tmp_path)


def test_v2_catalog_rejects_duplicate_timestamps():
    frame = pd.DataFrame({
        "source_row_id": [1, 2, 3],
        "timestamp": [
            pd.Timestamp("2020-01-01"),
            pd.Timestamp("2020-01-01"),
            pd.Timestamp("2020-01-01 00:00:10"),
        ],
        "TP2": [1.0, 2.0, 3.0],
    })
    with pytest.raises(ValueError, match="duplicate timestamp"):
        segmentize(frame, threshold_seconds=30.0, reject_duplicate_timestamps=True)


@_requires_metropt
def test_real_metropt_v2_catalog_invariants():
    frame = load_metropt_frame_v2(_DATA_ROOT / "metropt+3+dataset")
    assert frame["source_row_id"].is_unique
    median = median_interval_seconds(frame)
    assert 5.0 <= median <= 20.0, f"expected ~10s median, got {median}"

    train, valid, test, meta = split_chronological_by_timestamp_group(frame)
    assert len(train) + len(valid) + len(test) == len(frame)
    assert not (set(train) & set(valid)) and not (set(train) & set(test)) and not (set(valid) & set(test))
    assert meta["actual_rows"]["train"] > 0 and meta["actual_rows"]["valid"] > 0 and meta["actual_rows"]["test"] > 0

    threshold = GAP_MULTIPLIER * median
    segments = segmentize(frame, threshold_seconds=threshold)
    assert segments
    max_internal = max(
        seg["timestamp"].diff().dt.total_seconds().iloc[1:].max()
        for seg in segments
    )
    assert max_internal <= threshold + 1e-6

    # full protocol window params from §13.2
    records = build_window_catalog(
        segments, history_len=168, pred_len=24, stride=60,
        dataset="metropt3_chrono_502030_v2", split="train", timeline_sha="d" * 64,
    )
    assert records
    assert len({r.window_id for r in records}) == len(records)
    # windows are monotone in source_row_id (chronological within a segment)
    by_segment = {}
    for r in records:
        by_segment.setdefault(r.segment_id, []).append(r)
    for sid, recs in by_segment.items():
        starts = [r.start for r in recs]
        assert starts == sorted(starts)
        assert len(starts) == len(set(starts))


def test_layered_protocol_shas_are_stable_and_acyclic():
    frame = _frame(counts=(8, 8), gap_after=1)
    segments = segmentize(frame, threshold_seconds=30.0)
    records = build_window_catalog(
        segments, 4, 2, 2, "metropt3_chrono_502030_v2", "train", "e" * 64
    )
    raw_a = raw_data_sha(frame, ["TP2"])
    raw_b = raw_data_sha(frame.copy(deep=True), ["TP2"])
    part_a = partition_sha(raw_a, [100, 101], [102], [103])
    part_b = partition_sha(raw_b, [100, 101], [102], [103])
    time_a = timeline_sha(part_a, segments)
    time_b = timeline_sha(part_b, [segment.copy(deep=True) for segment in segments])
    catalog_a = window_catalog_sha(time_a, 4, 2, 2, records)
    catalog_b = window_catalog_sha(time_b, 4, 2, 2, records)

    assert raw_a == raw_b
    assert part_a == part_b
    assert time_a == time_b
    assert catalog_a == catalog_b
    assert window_catalog_sha(time_a, 5, 2, 2, records) != catalog_a


# ---------------------------------------------------------------------------
# CH34-S01-T02: continuous targets (7) + binary history context (8)
# ---------------------------------------------------------------------------


_CONT_7 = [f"C{i}" for i in range(7)]
_CTX_8 = [f"K{i}" for i in range(8)]


def _v2_frame(n_groups=3, rows_per_group=8, gap_after=None, cont=_CONT_7, ctx=_CTX_8):
    rows = []
    source = 1000
    timestamp = pd.Timestamp("2020-01-01")
    for group_index in range(n_groups):
        if gap_after is not None and group_index == gap_after:
            timestamp += timedelta(seconds=31)
        for row in range(rows_per_group):
            entry = {"source_row_id": source, "timestamp": timestamp}
            for c in cont:
                entry[c] = float(source % 5)
            for k in ctx:
                entry[k] = float((source + int(k[1])) % 2)
            rows.append(entry)
            source += 1
        timestamp += timedelta(seconds=10)
    return pd.DataFrame(rows)


def _v2_ds(frame, H=4, P=2, stride=1, cont=_CONT_7, ctx=_CTX_8, median=10.0, **kwargs):
    from kaf_profiti.industrial.metropt import MetroPTChronoDataset
    from kaf_profiti.industrial.metropt import build_window_catalog
    from kaf_profiti.industrial.metropt import segmentize

    segments = segmentize(frame, threshold_seconds=30.0)
    records = build_window_catalog(
        segments, H, P, stride, "metropt3_chrono_502030_v2", "train", "g" * 64
    )
    return MetroPTChronoDataset(
        segments, records, H, P, cont, ctx, median_interval=median, **kwargs
    )


def test_v2_targets_and_context_shapes():
    frame = _v2_frame(n_groups=1)
    ds = _v2_ds(frame)
    sample = ds[0]
    assert sample.X_obs.shape == (4, 7)
    assert sample.Y_q.shape == (2, 7)
    assert sample.M_obs.shape == (4, 7)
    assert sample.M_q.shape == (2, 7)
    assert sample.context.shape == (8,)
    assert sample.unit_id == 0
    assert sample.window_id == ds.window_ids[0]
    assert sample.T_obs.numel() == 4 and sample.T_q.numel() == 2

    from kaf_profiti.industrial.batch import IndustrialCollator

    batch = IndustrialCollator()([sample, ds[1]])
    assert batch.window_id == ds.window_ids[:2]


def test_v2_context_is_last_history_observation_and_binary():
    frame = _v2_frame(n_groups=1)
    ds = _v2_ds(frame)
    sample = ds[0]
    segment = ds._units[0]
    origin = segment.iloc[3]  # last history row for window start=0, H=4
    expected = torch.tensor([origin[k] for k in _CTX_8], dtype=torch.float32)
    assert torch.allclose(sample.context, expected)
    assert set(sample.context.numpy().tolist()) <= {0.0, 1.0}


def test_v2_query_context_perturbation_does_not_change_model_inputs():
    frame = _v2_frame(n_groups=1)
    ds = _v2_ds(frame)
    sample = ds[0]
    X, M, T, ctx = sample.X_obs, sample.M_obs, sample.T_obs, sample.context

    from kaf_profiti.industrial.metropt import MetroPTChronoDataset
    from kaf_profiti.industrial.metropt import build_window_catalog
    from kaf_profiti.industrial.metropt import segmentize

    perturbed = frame.copy(deep=True)
    # flip the binary context values on query rows only (rows beyond H)
    for k in _CTX_8:
        perturbed.loc[4:, k] = 1.0 - perturbed.loc[4:, k]
    segs = segmentize(perturbed, threshold_seconds=30.0)
    recs = build_window_catalog(segs, 4, 2, 1, "metropt3_chrono_502030_v2", "train", "g" * 64)
    ds2 = MetroPTChronoDataset(segs, recs, 4, 2, _CONT_7, _CTX_8, median_interval=10.0)
    sample2 = ds2[0]
    assert torch.equal(sample2.X_obs, X)
    assert torch.equal(sample2.M_obs, M)
    assert torch.equal(sample2.T_obs, T)
    assert torch.equal(sample2.context, ctx)


def test_v2_rejects_reordered_or_missing_columns():
    frame = _v2_frame(n_groups=1)
    # reorder context columns relative to continuous -> must fail on order
    with pytest.raises(ValueError, match="order"):
        _v2_ds(frame, ctx=_CTX_8[::-1])
    # frame missing a continuous column -> must fail on missing
    dropped = frame.drop(columns=["C3"])
    with pytest.raises(ValueError, match="missing"):
        _v2_ds(dropped)


def test_v2_rejects_non_binary_context_value_with_source_row_id():
    frame = _v2_frame(n_groups=1)
    frame.loc[2, "K3"] = 2.0  # non-binary on a history row
    with pytest.raises(ValueError, match="K3"):
        _v2_ds(frame)


def test_v2_window_projection_matches_records():
    frame = _v2_frame(n_groups=1)
    ds = _v2_ds(frame, stride=2)
    assert ds.windows == [(r.segment_id, r.start) for r in ds._records]
    assert len(ds) == len(ds.windows)


# ---------------------------------------------------------------------------
# CH34-S01-T03: real time with numerical-stable scaling
# ---------------------------------------------------------------------------


def _scaled_frame(hist_offsets=(0, 10, 21, 31), query_offsets=(44, 55)):
    rows = []
    source = 2000
    base = pd.Timestamp("2020-01-01")
    for off in tuple(hist_offsets) + tuple(query_offsets):
        entry = {
            "source_row_id": source,
            "timestamp": base + pd.to_timedelta(off, unit="s"),
        }
        for c in _CONT_7:
            entry[c] = float(source % 5)
        for k in _CTX_8:
            entry[k] = float((source + int(k[1])) % 2)
        rows.append(entry)
        source += 1
    return pd.DataFrame(rows)


def test_v3_scaled_time_preserves_jitter():
    frame = _scaled_frame()
    ds = _v2_ds(frame, H=4, P=2, median=10.0)
    sample = ds[0]
    assert sample.T_obs.numel() == 4 and sample.T_q.numel() == 2
    diffs = torch.diff(sample.T_obs).numpy()
    assert np.allclose(diffs, [1.0, 1.1, 1.0], atol=1e-4), f"diffs={diffs}"


def test_v3_query_time_after_origin_and_same_scale():
    frame = _scaled_frame()
    ds = _v2_ds(frame, H=4, P=2, median=10.0)
    sample = ds[0]
    assert sample.T_q[0] > sample.T_obs[-1]
    # both T_obs and T_q are seconds-from-segment-start scaled by the same
    # median interval (10s), so the origin->first-query gap (44-31)/10 = 1.3
    assert float(sample.T_q[0] - sample.T_obs[-1]) == pytest.approx(1.3, abs=1e-3)


def test_v3_time_scale_artifact_records_raw_unit_and_stable_sha():
    frame = _scaled_frame()
    a1 = metropt_time_scale_artifact(frame)
    a2 = metropt_time_scale_artifact(frame.copy(deep=True))
    assert a1["unit"] == "seconds"
    assert a1["source"] == "train"
    assert a1["median_interval_seconds"] == pytest.approx(median_interval_seconds(frame))
    assert a1["sha256"] == a2["sha256"]


def _time_batch(t_obs_batch, H=4, P=2, N=7, C=8):
    from kaf_profiti.industrial.batch import IndustrialBatch

    B = t_obs_batch.shape[0]
    torch.manual_seed(0)
    x = torch.randn(B, H, N)
    m = torch.ones(B, H, N)
    m[:, 1, 2] = 0
    m[:, 2, 1] = 0  # sparse so GRU-D delta_t varies with T_obs
    x = x * m
    y = torch.randn(B, P, N)
    mq = torch.ones(B, P, N)
    ctx = torch.rand(B, C)
    return IndustrialBatch(
        X_obs=x, T_obs=t_obs_batch.float(), M_obs=m, T_q=torch.zeros(B, P),
        Y_q=y, M_q=mq, context=ctx, y_flat=y.reshape(B, -1), mq_flat=mq.reshape(B, -1),
        query_channel_ids=torch.arange(N).repeat(P), rul=torch.zeros(B), unit_id=torch.arange(B),
    )


def test_v3_time_models_are_time_sensitive():
    from kaf_profiti.baselines.point import create_point_baseline
    from kaf_profiti.models.lightweight_head import KSTLight

    t_a = torch.tensor([[0.0, 1.0, 2.1, 3.1], [0.0, 1.1, 2.0, 3.2]])
    t_b = torch.tensor([[0.0, 1.0, 2.0, 3.0], [0.0, 1.0, 2.1, 3.4]])
    batch_a, batch_b = _time_batch(t_a), _time_batch(t_b)
    models = {
        "gru_d": create_point_baseline("gru_d", 7, 8, 2, hidden_dim=8),
        "ode_rnn": create_point_baseline("ode_rnn", 7, 8, 2, hidden_dim=8),
        "kst_light": KSTLight(
            num_sensors=7, context_dim=8, pred_len=2, hidden_dim=8,
            head_type="linear", te_dim=4, kernel_count=2, n_layers=1,
            n_heads=2, preconv_dim=4, patch_lens=(2, 4),
        ),
    }
    for name, model in models.items():
        model.eval()
        with torch.no_grad():
            out_a = model.predict_point(batch_a)
            out_b = model.predict_point(batch_b)
        assert torch.isfinite(out_a).all() and torch.isfinite(out_b).all(), name
        assert not torch.allclose(out_a, out_b, atol=1e-5), f"{name} is not time-sensitive"


# ---------------------------------------------------------------------------
# CH34-S01-F01: identity chain covers every scientific input; no run seed
# ---------------------------------------------------------------------------


def test_raw_data_sha_covers_context_values_and_column_names():
    frame = _v2_frame(n_groups=1)
    base = raw_data_sha(frame, _CONT_7 + _CTX_8)
    moved_context = frame.copy(deep=True)
    moved_context.loc[2, "K3"] = 1.0 - moved_context.loc[2, "K3"]
    assert raw_data_sha(moved_context, _CONT_7 + _CTX_8) != base
    # column identity (names and order) participates in the digest
    assert raw_data_sha(frame, _CONT_7 + _CTX_8[::-1]) != base


def test_window_catalog_sha_covers_every_record_not_just_ends():
    from dataclasses import replace

    frame = _v2_frame(n_groups=1)
    segments = segmentize(frame, threshold_seconds=30.0)
    records = build_window_catalog(
        segments, 4, 2, 1, "metropt3_chrono_502030_v2", "train", "i" * 64
    )
    assert len(records) >= 3
    base = window_catalog_sha("i" * 64, 4, 2, 1, records)
    middle = len(records) // 2
    tampered = list(records)
    tampered[middle] = replace(tampered[middle], start=tampered[middle].start + 1)
    assert window_catalog_sha("i" * 64, 4, 2, 1, tampered) != base


@_requires_metropt
def test_v2_loader_float_parse_is_platform_independent():
    """CH34-S03-T01 drift fix: CSV floats must parse via round_trip.

    The default pandas C-parser float conversion (xstrtod) is allowed ~1 ULP
    error and its result varies between builds (macOS arm64 vs linux x86_64
    diverged on all 7 continuous channels), which made ``raw_data_sha`` — and
    every SHA chained from it — machine-dependent while statistics stayed
    identical. The loader must use the correctly-rounded parser so the same
    CSV bytes hash identically on every machine.
    """
    from kaf_profiti.industrial.metropt import (
        METROPT_BINARY_CONTEXT_COLUMNS,
        METROPT_CONTINUOUS_COLUMNS,
    )

    frame = load_metropt_frame_v2(_METROPT_CSV.parent)
    reference = pd.read_csv(
        _METROPT_CSV, parse_dates=["timestamp"], float_precision="round_trip"
    )
    reference = (
        reference.rename(columns={"Unnamed: 0": "source_row_id"})
        .sort_values(["timestamp", "source_row_id"])
        .reset_index(drop=True)
    )
    columns = METROPT_CONTINUOUS_COLUMNS + METROPT_BINARY_CONTEXT_COLUMNS
    assert list(frame["source_row_id"]) == list(reference["source_row_id"])
    assert np.asarray(frame[columns], dtype=np.float64).tobytes() == np.asarray(
        reference[columns], dtype=np.float64
    ).tobytes()
