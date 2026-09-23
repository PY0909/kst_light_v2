"""CH2.5-P01-T04: matched realized missing-rate tests for FD004 mechanisms.

``requested_rate`` must mean the final realized missing rate of the whole
split timeline bundle (within +/-0.01), not an internal deletion parameter.
Generation is deterministically calibrated per mechanism, keeps at least one
observation per channel, records the safety-constraint deviation, canonicalizes
the ``block`` alias, and never reads RUL/targets/metrics/labels.
"""

import inspect
import json
import os
from pathlib import Path

import numpy as np
import pytest

from kaf_profiti.experiments.datasets import create_protocol_datasets
from kaf_profiti.experiments.masks import (
    TimelineMaskConfig,
    generate_or_load_timeline_masks,
)
from kaf_profiti.industrial.missing import canonical_mechanism

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

MECHANISMS = ("random", "low_rate", "block_offline", "mixed")


@pytest.fixture(scope="module")
def protocol():
    return create_protocol_datasets(
        "cmapss_fd004",
        _DATA_ROOT,
        seed=2026,
        history_len=50,
        pred_len=10,
        stride=1,
        async_mode="none",
    )


@pytest.fixture(scope="module")
def bundles(protocol, tmp_path_factory):
    lengths = {
        int(unit): len(group) for unit, group in protocol.train._units.items()
    }
    out = {}
    for mechanism in MECHANISMS:
        config = TimelineMaskConfig(
            dataset="cmapss_fd004",
            split="train",
            mechanism=mechanism,
            requested_rate=0.30,
            mask_seed=2026,
            source_split_sha256=protocol.split_info["split_sha256"],
        )
        directory = tmp_path_factory.mktemp(f"mask_{mechanism}")
        out[mechanism] = generate_or_load_timeline_masks(
            directory / "mask.npz", config, lengths, 21
        )
    return out


def _realized_rate(bundle) -> float:
    total = 0
    missing = 0
    for engine, mask in bundle.masks.items():
        total += mask.size
        missing += int((mask == 0).sum())
    return missing / total


def test_four_mechanisms_realize_requested_rate(protocol, bundles):
    for mechanism in MECHANISMS:
        realized = _realized_rate(bundles[mechanism])
        assert 0.29 <= realized <= 0.31, f"{mechanism}: realized {realized}"
        assert bundles[mechanism].realized_rate == pytest.approx(realized, abs=1e-9)


def test_calibration_metadata_is_recorded_and_deterministic(protocol, tmp_path, bundles):
    bundle = bundles["random"]
    with np.load(bundle.path) as loaded:
        meta = json.loads(str(loaded["meta"].item()))

    assert meta["realized_rate"] == pytest.approx(bundle.realized_rate, abs=1e-9)
    assert meta["requested_rate"] == pytest.approx(0.30)
    calibration = meta["calibration"]
    assert calibration["mechanism"] == "random"
    assert calibration["iterations"] >= 1
    assert calibration["knob"] == "keep_prob"
    assert 0.0 < calibration["value"] <= 1.0
    assert meta["safety_adjustment"] >= 0.0
    assert meta["pre_safety_realized_rate"] >= meta["realized_rate"]

    # Same identity at a fresh path reproduces byte-identical masks and digest.
    lengths = {
        int(unit): len(group) for unit, group in protocol.train._units.items()
    }
    config = TimelineMaskConfig(
        dataset="cmapss_fd004",
        split="train",
        mechanism="random",
        requested_rate=0.30,
        mask_seed=2026,
        source_split_sha256=protocol.split_info["split_sha256"],
    )
    rerun = generate_or_load_timeline_masks(tmp_path / "again.npz", config, lengths, 21)
    assert rerun.content_sha256 == bundle.content_sha256
    assert rerun.realized_rate == pytest.approx(bundle.realized_rate, abs=1e-12)
    assert rerun.calibration == bundle.calibration


def test_block_alias_maps_to_single_canonical_mechanism(protocol, tmp_path):
    assert canonical_mechanism("block") == "block_offline"
    assert canonical_mechanism("block_offline") == "block_offline"
    assert canonical_mechanism("random") == "random"
    with pytest.raises(ValueError):
        canonical_mechanism("unknown_mechanism")

    lengths = {
        int(unit): len(group) for unit, group in protocol.train._units.items()
    }
    shared_kwargs = dict(
        dataset="cmapss_fd004",
        split="train",
        requested_rate=0.30,
        mask_seed=2026,
        source_split_sha256=protocol.split_info["split_sha256"],
    )
    via_alias = generate_or_load_timeline_masks(
        tmp_path / "alias.npz",
        TimelineMaskConfig(mechanism="block", **shared_kwargs),
        lengths,
        21,
    )
    via_canonical = generate_or_load_timeline_masks(
        tmp_path / "canonical.npz",
        TimelineMaskConfig(mechanism="block_offline", **shared_kwargs),
        lengths,
        21,
    )
    # One mechanism, one scientific key: identical canonical id, digest, masks.
    assert via_alias.config.mechanism == "block_offline"
    assert via_alias.content_sha256 == via_canonical.content_sha256
    for engine in via_alias.masks:
        assert np.array_equal(via_alias.masks[engine], via_canonical.masks[engine])


def test_every_channel_keeps_at_least_one_observation(bundles):
    for mechanism in MECHANISMS:
        for engine, mask in list(bundles[mechanism].masks.items())[:25]:
            assert (mask.sum(axis=0) >= 1).all(), f"{mechanism} engine {engine} has a blind channel"


def test_mask_generation_signature_has_no_label_or_target_inputs():
    signature = inspect.signature(generate_or_load_timeline_masks)
    params = set(signature.parameters)
    assert params == {"path", "config", "engine_timeline_lengths", "num_sensors", "tolerance"}
    config_fields = {field.name for field in TimelineMaskConfig.__dataclass_fields__.values()}
    assert not config_fields & {"rul", "fault_label", "y", "target", "metric", "labels"}


def test_tolerances_below_reachable_rates_are_rejected(protocol, tmp_path):
    lengths = {
        int(unit): len(group) for unit, group in protocol.train._units.items()
    }
    # An unreachable tolerance must raise instead of silently saving a wrong rate.
    config = TimelineMaskConfig(
        dataset="cmapss_fd004",
        split="train",
        mechanism="random",
        requested_rate=0.30,
        mask_seed=2026,
        source_split_sha256=protocol.split_info["split_sha256"],
    )
    with pytest.raises((ValueError, RuntimeError)):
        generate_or_load_timeline_masks(
            tmp_path / "strict.npz", config, lengths, 21, tolerance=1e-12
        )
