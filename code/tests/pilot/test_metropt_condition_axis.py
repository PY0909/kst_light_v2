"""CH34-S01-T04: MetroPT v2 normalization isolation + condition axis.

The v2 protocol must (a) freeze train-only normalization over the 7 continuous
channels so valid/test rows can never move the artifact, (b) make the six
missingness conditions change ONLY the history input (distinct per-condition
timeline-mask bundles, monotone observable rate under random 0/30/70) while
query targets, ``M_q``, window ids and valid counts stay byte-identical, and
(c) expose a public ``metropt3_chrono_502030_v2`` entry whose split identity
carries the full layered SHA chain.
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

from kaf_profiti.experiments.datasets import create_protocol_datasets
from kaf_profiti.experiments.masks import (
    TimelineMaskConfig,
    TimelineMaskedWindowDataset,
    generate_or_load_timeline_masks,
)

from kaf_profiti.industrial.metropt import (
    METROPT_BINARY_CONTEXT_COLUMNS,
    METROPT_CONTINUOUS_COLUMNS,
)

_DATA_ROOT = Path(os.environ.get("KST_DATA_ROOT", Path(__file__).resolve().parents[3] / "dataset"))
_METROPT_DIR = _DATA_ROOT / "metropt+3+dataset"
_METROPT_CSV = _METROPT_DIR / "MetroPT3(AirCompressor).csv"
_requires_metropt = pytest.mark.skipif(
    not _METROPT_CSV.exists(), reason="MetroPT CSV not available under KST_DATA_ROOT"
)

_DATASET = "metropt3_chrono_502030_v2"


def _stats_frame():
    rows = []
    for source in range(1000, 1012):
        entry = {"source_row_id": source}
        for c in METROPT_CONTINUOUS_COLUMNS:
            entry[c] = float(source % 5)
        rows.append(entry)
    return pd.DataFrame(rows)


def test_normalization_sha_ignores_valid_and_test_rows():
    from kaf_profiti.experiments.datasets import metropt_v2_stats_artifact

    frame = _stats_frame()
    train_ids = list(range(1000, 1006))
    base = metropt_v2_stats_artifact(frame, train_ids, METROPT_CONTINUOUS_COLUMNS)

    moved_valid = frame.copy(deep=True)
    moved_valid.loc[~moved_valid["source_row_id"].isin(train_ids), METROPT_CONTINUOUS_COLUMNS] += 7.0
    assert metropt_v2_stats_artifact(moved_valid, train_ids, METROPT_CONTINUOUS_COLUMNS)["sha256"] == base["sha256"]

    moved_train = frame.copy(deep=True)
    moved_train.loc[moved_train["source_row_id"].isin(train_ids), METROPT_CONTINUOUS_COLUMNS] += 7.0
    assert metropt_v2_stats_artifact(moved_train, train_ids, METROPT_CONTINUOUS_COLUMNS)["sha256"] != base["sha256"]


@pytest.fixture(scope="module")
def v2_protocol():
    return create_protocol_datasets(
        _DATASET,
        _DATA_ROOT,
        seed=2026,
        history_len=168,
        pred_len=24,
        stride=60,
        async_mode="none",
        split_seed=2026,
    )


@_requires_metropt
def test_v2_public_entry_identity(v2_protocol):
    bundle = v2_protocol
    assert bundle.name == _DATASET
    assert bundle.num_sensors == 7
    assert bundle.context_dim == 8

    info = bundle.split_info
    assert len(info["split_sha256"]) == 64
    assert len(info["normalization"]["sha256"]) == 64
    assert info["normalization"]["columns"] == list(METROPT_CONTINUOUS_COLUMNS)
    assert info["context_observation_policy"] == "fully_observed_history_last"
    assert info["masked_channels"] == "7 continuous channels"
    assert info["split_rule"] == "timestamp_group_chronological_50_20_30_segment_v2"
    assert info["split_seed"] == "not_applicable_chronological"
    # layered chain recorded inside the split identity
    identity = info["split_identity"]
    assert len(identity["raw_data_sha256"]) == 64
    assert len(identity["partition_sha256"]) == 64
    assert set(identity["timeline_sha256"]) == {"train", "valid", "test"}
    assert set(identity["window_catalog_sha256"]) == {"train", "valid", "test"}
    for split in ("train", "valid", "test"):
        entry = info["window_bounds"][split]
        assert entry["count"] == info[f"{split}_windows"] > 0

    for split in ("train", "valid", "test"):
        dataset = getattr(bundle, split)
        assert dataset.windows
        first_segment, _ = dataset.windows[0]
        assert first_segment in dataset._units


@_requires_metropt
def test_condition_history_masks_differ_and_rate_monotone(v2_protocol, tmp_path):
    bundle = v2_protocol
    dataset = bundle.test
    lengths = {int(unit): len(group) for unit, group in dataset._units.items()}

    conditions = (
        ("random_000", "random", 0.00),
        ("random_030", "random", 0.30),
        ("random_070", "random", 0.70),
        ("low_rate_030", "low_rate", 0.30),
        ("block_offline_030", "block_offline", 0.30),
        ("mixed_030", "mixed", 0.30),
    )
    shas, observed = {}, {}
    for key, mechanism, rate in conditions:
        config = TimelineMaskConfig(
            dataset=_DATASET,
            split="test",
            mechanism=mechanism,
            requested_rate=rate,
            mask_seed=2026,
            source_split_sha256=bundle.split_info["split_sha256"],
        )
        mask_bundle = generate_or_load_timeline_masks(
            tmp_path / f"{key}.npz", config, lengths, bundle.num_sensors
        )
        shas[key] = mask_bundle.content_sha256
        observed[key] = 1.0 - mask_bundle.realized_rate

    assert len(set(shas.values())) == len(conditions), "conditions must not share a bundle"
    assert observed["random_000"] == pytest.approx(1.0)
    assert observed["random_000"] > observed["random_030"] > observed["random_070"]
    assert 0.60 < observed["random_030"] < 0.80
    assert 0.20 < observed["random_070"] < 0.45
    # all four 30% mechanisms realize the same total missing rate (within tolerance)
    for key in ("low_rate_030", "block_offline_030", "mixed_030"):
        assert abs(observed[key] - observed["random_030"]) <= 0.01, key


@_requires_metropt
def test_query_side_is_invariant_across_conditions(v2_protocol, tmp_path):
    bundle = v2_protocol
    base = bundle.test
    lengths = {int(unit): len(group) for unit, group in base._units.items()}

    def wrapped(mechanism, rate):
        config = TimelineMaskConfig(
            dataset=_DATASET, split="test", mechanism=mechanism, requested_rate=rate,
            mask_seed=2026, source_split_sha256=bundle.split_info["split_sha256"],
        )
        mask_bundle = generate_or_load_timeline_masks(
            tmp_path / f"{mechanism}_{rate:.2f}.npz", config, lengths, bundle.num_sensors
        )
        return TimelineMaskedWindowDataset(base, mask_bundle)

    masked_a, masked_b = wrapped("random", 0.30), wrapped("mixed", 0.30)
    count = len(base)
    step = max(1, count // 25)
    indices = list(range(0, count, step))
    differing_masks = 0
    valid_counts = {0: 0, 1: 0}
    for index in indices:
        sample_a, sample_b = masked_a[index], masked_b[index]
        reference = base[index]
        # query side and context are byte-identical across conditions
        assert torch.equal(sample_a.Y_q, reference.Y_q)
        assert torch.equal(sample_b.Y_q, reference.Y_q)
        assert torch.equal(sample_a.M_q, reference.M_q)
        assert torch.equal(sample_b.M_q, reference.M_q)
        assert torch.equal(sample_a.context, reference.context)
        assert torch.equal(sample_b.context, reference.context)
        # masked history equals base values times the condition's own mask
        assert torch.equal(sample_a.X_obs, reference.X_obs * sample_a.M_obs)
        assert torch.equal(sample_b.X_obs, reference.X_obs * sample_b.M_obs)
        if not torch.equal(sample_a.M_obs, sample_b.M_obs):
            differing_masks += 1
        valid_counts[0] += int(sample_a.M_q.sum())
        valid_counts[1] += int(sample_b.M_q.sum())
    assert differing_masks > 0, "two mechanisms at 30% must not produce identical history masks"
    assert valid_counts[0] == valid_counts[1]
    # window identity is carried by the base catalog and untouched by conditions
    assert masked_a.dataset.windows == base.windows
    assert masked_b.dataset.windows == base.windows


@_requires_metropt
def test_v2_split_identity_excludes_run_seed_and_records_full_schema(v2_protocol):
    identity = v2_protocol.split_info["split_identity"]
    # the run seed must never influence the split identity
    assert "seed" not in identity and "split_seed" not in identity
    assert identity["split_seed_applicability"] == "not_applicable_chronological"
    # full target schema, label rule and evaluator identity are recorded
    assert identity["target_schema"]["continuous_columns"] == list(METROPT_CONTINUOUS_COLUMNS)
    assert identity["target_schema"]["context_columns"] == list(METROPT_BINARY_CONTEXT_COLUMNS)
    assert identity["target_schema"]["context_observation_policy"] == "fully_observed_history_last"
    assert identity["evaluator"]["implementation"].endswith("GlobalMetricAccumulator")
    assert identity["fault_windows"], "registered fault intervals must be part of the identity"
    assert "query timestamp" in identity["label_rule"]


@_requires_metropt
def test_provider_fingerprint_carries_v2_schema_identity(v2_protocol, tmp_path):
    from kaf_profiti.experiments.pilot_runner import RealProtocolProvider

    provider = RealProtocolProvider(
        data_root=_DATA_ROOT,
        result_root=tmp_path,
        dataset=_DATASET,
        history_len=168,
        pred_len=24,
        stride=60,
        mechanism="random",
        requested_rate=0.30,
        mask_seed=2026,
        split_seed=2026,
        pilot_root="pilot/metropt3",
    )
    fingerprint = provider.protocol_fingerprint()
    assert fingerprint["target_schema_sha256"] == v2_protocol.split_info["target_schema_sha256"]
    assert fingerprint["evaluator"] == v2_protocol.split_info["evaluator"]
    identity = v2_protocol.split_info["split_identity"]
    for field in (
        "raw_data_sha256",
        "partition_sha256",
        "timeline_sha256",
        "window_catalog_sha256",
        "time_scale_sha256",
    ):
        assert fingerprint[field] == identity[field]
    assert set(fingerprint["realized_rate"]) == {"train", "valid", "test"}
    assert all(
        abs(rate - 0.30) <= 0.01 for rate in fingerprint["realized_rate"].values()
    )
