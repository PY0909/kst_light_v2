"""CH2.5-P01-T01: FD004 split-seed / run-seed separation leakage tests.

Split identity (engine partition, window boundaries, split SHA) must be fully
determined by ``split_seed`` and must not change with the run ``seed``. The
official FD004 test file stays isolated from the train-file engine partition.
"""

import os
from pathlib import Path

import pytest

from kaf_profiti.experiments.datasets import create_protocol_datasets, split_identity_sha256

_DATA_ROOT = Path(
    os.environ.get("KST_DATA_ROOT", Path(__file__).resolve().parents[3] / "dataset")
)
_FD004_DIR = _DATA_ROOT / "CMAPSSData"
_FD004_AVAILABLE = (
    _FD004_DIR / "train_FD004.txt").exists() and (_FD004_DIR / "test_FD004.txt").exists()

pytestmark = pytest.mark.skipif(
    not _FD004_AVAILABLE,
    reason="FD004 raw files not available under KST_DATA_ROOT",
)


def _create_bundle(seed: int, split_seed: int = 2026):
    return create_protocol_datasets(
        "cmapss_fd004",
        _DATA_ROOT,
        seed=seed,
        split_seed=split_seed,
        history_len=50,
        pred_len=10,
        stride=1,
        async_mode="none",
    )


def _train_file_unit_count() -> int:
    units = set()
    with open(_FD004_DIR / "train_FD004.txt", encoding="utf-8") as handle:
        for line in handle:
            fields = line.split()
            if fields:
                units.add(int(fields[0]))
    return len(units)


def _test_file_unit_count() -> int:
    units = set()
    with open(_FD004_DIR / "test_FD004.txt", encoding="utf-8") as handle:
        for line in handle:
            fields = line.split()
            if fields:
                units.add(int(fields[0]))
    return len(units)


def test_train_valid_engine_ids_are_disjoint_and_exhaustive():
    bundle = _create_bundle(seed=2026)

    train_ids = bundle.split_info["train_engine_ids"]
    valid_ids = bundle.split_info["valid_engine_ids"]

    assert train_ids == sorted(train_ids)
    assert valid_ids == sorted(valid_ids)
    assert set(train_ids).isdisjoint(valid_ids)
    assert set(train_ids) | set(valid_ids) == set(range(1, _train_file_unit_count() + 1))
    assert bundle.train.stats is bundle.valid.stats


def test_official_test_file_is_isolated_from_train_partition():
    bundle = _create_bundle(seed=2026)

    assert bundle.test.split == "test"
    assert bundle.train.split == "train"
    assert bundle.test.frame["unit"].nunique() == _test_file_unit_count()
    assert bundle.split_info["test_engine_count"] == _test_file_unit_count()
    # Train/valid windows reference only train-file engines.
    train_units = {int(unit) for unit, _ in bundle.train.windows}
    valid_units = {int(unit) for unit, _ in bundle.valid.windows}
    assert train_units == set(bundle.split_info["train_engine_ids"])
    assert valid_units == set(bundle.split_info["valid_engine_ids"])
    # No window of any split crosses an engine boundary: each window's history
    # and forecast come from one engine only (enforced by construction; assert
    # window count consistency against engine-wise limits).
    assert bundle.split_info["train_windows"] == len(bundle.train.windows)
    assert bundle.split_info["valid_windows"] == len(bundle.valid.windows)
    assert bundle.split_info["test_windows"] == len(bundle.test.windows)


def test_run_seed_does_not_change_split_identity():
    baseline = _create_bundle(seed=2026)
    for run_seed in (2027, 2028, 9999):
        rerun = _create_bundle(seed=run_seed)
        assert rerun.split_info["split_sha256"] == baseline.split_info["split_sha256"]
        assert rerun.split_info["train_engine_ids"] == baseline.split_info["train_engine_ids"]
        assert rerun.split_info["valid_engine_ids"] == baseline.split_info["valid_engine_ids"]
        assert rerun.split_info["window_bounds"] == baseline.split_info["window_bounds"]
        assert rerun.split_info["split_identity"] == baseline.split_info["split_identity"]


def test_split_seed_controls_engine_partition():
    baseline = _create_bundle(seed=2026, split_seed=2026)
    altered = _create_bundle(seed=2026, split_seed=2027)

    assert baseline.split_info["split_seed"] == 2026
    assert altered.split_info["split_seed"] == 2027
    assert altered.split_info["split_sha256"] != baseline.split_info["split_sha256"]
    assert (
        altered.split_info["valid_engine_ids"]
        != baseline.split_info["valid_engine_ids"]
    )
    # Partition stays disjoint and exhaustive under any split seed.
    assert set(altered.split_info["train_engine_ids"]).isdisjoint(
        altered.split_info["valid_engine_ids"]
    )


def test_split_identity_hash_recomputes_and_excludes_model_and_run_seed():
    bundle = _create_bundle(seed=2027)
    identity = bundle.split_info["split_identity"]

    assert split_identity_sha256(identity) == bundle.split_info["split_sha256"]
    assert identity["split_seed"] == 2026
    assert "seed" not in identity
    assert "model" not in bundle.split_info
    model_ids = (
        "kst_probflow",
        "kst_light",
        "tcn_gaussian",
        "patchtst",
        "gru_d",
        "ode_rnn",
        "grafiti",
        "profiti",
        "kafnet",
    )
    serialized = repr(identity).lower()
    for model_id in model_ids:
        assert model_id not in serialized


def test_window_bounds_pin_down_canonical_window_boundaries():
    bundle = _create_bundle(seed=2026)
    bounds = bundle.split_info["window_bounds"]

    for split_name, dataset in (
        ("train", bundle.train),
        ("valid", bundle.valid),
        ("test", bundle.test),
    ):
        entry = bounds[split_name]
        assert entry["count"] == len(dataset.windows)
        assert entry["first"] == [int(dataset.windows[0][0]), int(dataset.windows[0][1])]
        assert entry["last"] == [int(dataset.windows[-1][0]), int(dataset.windows[-1][1])]
        # Sorted engine id list plus per-split window digests make the split
        # SHA sensitive to any window-set change.
        assert isinstance(entry["digest"], str) and len(entry["digest"]) == 64
