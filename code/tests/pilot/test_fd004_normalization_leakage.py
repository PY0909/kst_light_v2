"""CH2.5-P01-T02: FD004 train-only frozen normalization leakage tests.

Normalization statistics must be computed from train-engine rows only, frozen
into a shareable artifact, and consumed as-is by train/valid/test datasets.
Validation/test rows must never enter any mean, std, or fill-value choice.
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

from kaf_profiti.experiments.datasets import (
    _cmapss_stats_artifact,
    create_protocol_datasets,
    split_identity_sha256,
)
from kaf_profiti.industrial import cmapss as cmapss_module
from kaf_profiti.industrial.cmapss import (
    CMapssWindowDataset,
    SETTING_COLUMNS,
    SENSOR_COLUMNS,
    load_cmapss_frame,
)

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


def _create_bundle():
    return create_protocol_datasets(
        "cmapss_fd004",
        _DATA_ROOT,
        seed=2026,
        history_len=50,
        pred_len=10,
        stride=1,
        async_mode="none",
    )


def test_stats_unchanged_when_validation_rows_are_perturbed():
    bundle = _create_bundle()
    train_ids = bundle.split_info["train_engine_ids"]
    valid_ids = bundle.split_info["valid_engine_ids"]
    frame = load_cmapss_frame(_FD004_DIR, "FD004", "train")

    baseline = _cmapss_stats_artifact(frame, train_ids)

    perturbed = frame.copy()
    value_columns = SETTING_COLUMNS + SENSOR_COLUMNS
    perturbed.loc[perturbed["unit"].isin(valid_ids), value_columns] *= 1000.0
    perturbed_stats = _cmapss_stats_artifact(perturbed, train_ids)

    for key in ("sensor_mean", "sensor_std", "setting_mean", "setting_std", "sha256"):
        assert baseline[key] == perturbed_stats[key], f"{key} changed after perturbing valid rows"
    # And perturbing test rows is equally invisible: the artifact only sees the
    # official train file's train-engine rows by construction.
    assert baseline["engine_ids"] == sorted(int(unit) for unit in train_ids)
    assert set(valid_ids).isdisjoint(baseline["engine_ids"])


def test_protocol_datasets_share_frozen_stats_matching_train_engines():
    bundle = _create_bundle()
    frame = load_cmapss_frame(_FD004_DIR, "FD004", "train")
    artifact = _cmapss_stats_artifact(frame, bundle.split_info["train_engine_ids"])

    for key in ("sensor_mean", "sensor_std", "setting_mean", "setting_std"):
        expected = torch.tensor(artifact[key], dtype=torch.float32)
        for split_dataset in (bundle.train, bundle.valid, bundle.test):
            assert torch.equal(split_dataset.stats[key], expected)

    assert bundle.train.stats is bundle.valid.stats
    assert bundle.train.stats is bundle.test.stats


def test_normalization_artifact_records_source_columns_count_and_sha():
    bundle = _create_bundle()
    artifact = bundle.split_info["normalization"]

    assert artifact["source_split"] == "official_train"
    assert artifact["engine_ids"] == bundle.split_info["train_engine_ids"]
    assert artifact["sensor_columns"] == list(SENSOR_COLUMNS)
    assert artifact["setting_columns"] == list(SETTING_COLUMNS)
    assert artifact["count"] > 0
    assert artifact["std_floor"] == 1e-6

    payload = {key: value for key, value in artifact.items() if key != "sha256"}
    assert artifact["sha256"] == split_identity_sha256(payload)
    assert (
        bundle.split_info["split_identity"]["normalization_sha256"]
        == artifact["sha256"]
    )


def test_constructor_accepts_frozen_stats_without_reestimation(monkeypatch):
    bundle = _create_bundle()
    frozen = bundle.train.stats

    def _fail(*args, **kwargs):
        raise AssertionError("constructor re-estimated normalization stats")

    monkeypatch.setattr(cmapss_module, "_training_stats", _fail)

    dataset = CMapssWindowDataset(
        _FD004_DIR,
        subset="FD004",
        split="test",
        history_len=50,
        pred_len=10,
        stride=100,
        async_mode="none",
        seed=2026,
        stats=frozen,
    )
    sample = dataset[0]

    assert dataset.stats is frozen
    assert torch.isfinite(sample.X_obs).all()
    assert torch.isfinite(sample.Y_q).all()


def test_constant_sensor_floors_std_and_nonfinite_values_are_rejected():
    rows = 8
    frame = pd.DataFrame(
        {
            "unit": [1] * rows,
            "cycle": list(range(1, rows + 1)),
            **{column: np.linspace(-1.0, 1.0, rows) for column in SETTING_COLUMNS},
        }
    )
    for idx, column in enumerate(SENSOR_COLUMNS):
        frame[column] = 3.0 if idx == 0 else np.linspace(0.0, 2.0, rows) + idx

    artifact = _cmapss_stats_artifact(frame, [1])

    assert artifact["sensor_std"][0] == pytest.approx(1e-6)
    dataset_stats = {
        "sensor_mean": torch.tensor(artifact["sensor_mean"], dtype=torch.float32),
        "sensor_std": torch.tensor(artifact["sensor_std"], dtype=torch.float32),
        "setting_mean": torch.tensor(artifact["setting_mean"], dtype=torch.float32),
        "setting_std": torch.tensor(artifact["setting_std"], dtype=torch.float32),
    }
    dataset = CMapssWindowDataset(
        _FD004_DIR,
        subset="FD004",
        split="train",
        history_len=4,
        pred_len=2,
        stride=1,
        async_mode="none",
        seed=1,
        stats=dataset_stats,
        normalize=True,
    )
    # Constant channel normalizes to exactly zero and stays finite even though
    # the frozen stats were not estimated from this raw frame.
    sample = dataset[0]
    assert torch.isfinite(sample.X_obs).all()

    broken = frame.copy()
    broken.loc[broken.index[0], SENSOR_COLUMNS[1]] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        _cmapss_stats_artifact(broken, [1])
