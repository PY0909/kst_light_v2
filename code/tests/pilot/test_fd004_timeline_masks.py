"""CH2.5-P01-T03: FD004 timeline-first shared mask tests.

Masks are generated once per engine timeline within a split and sliced by
canonical window indices, so the same engine/cycle always carries the same
observation state across overlapping windows. Bundles live in a shared
artifact file whose identity binds schema, dataset, split, mechanism,
requested rate, mask seed, and the source split SHA; loads are strictly
validated and never silently reused on mismatch.
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest
import torch

from kaf_profiti.experiments.datasets import create_protocol_datasets
from kaf_profiti.experiments.masks import (
    TIMELINE_MASK_SCHEMA_VERSION,
    TimelineMaskConfig,
    TimelineMaskedWindowDataset,
    generate_or_load_timeline_masks,
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


def _timeline_lengths(dataset) -> dict:
    lengths = {}
    for unit, group in dataset._units.items():
        lengths[int(unit)] = len(group)
    return lengths


def _config(bundle, split: str = "train", mechanism: str = "random", mask_seed: int = 2026):
    return TimelineMaskConfig(
        dataset="cmapss_fd004",
        split=split,
        mechanism=mechanism,
        requested_rate=0.30,
        mask_seed=mask_seed,
        source_split_sha256=bundle.split_info["split_sha256"],
    )


def test_overlapping_windows_share_observation_state(tmp_path):
    bundle = _create_bundle()
    config = _config(bundle)
    masks = generate_or_load_timeline_masks(
        tmp_path / "shared_mask.npz", config, _timeline_lengths(bundle.train), 21
    )

    by_unit: dict = {}
    for unit, start in bundle.train.windows:
        by_unit.setdefault(unit, []).append(start)
    # Pick an engine whose stride-1 windows overlap heavily.
    unit = next(u for u, starts in by_unit.items() if len(starts) >= 20)
    starts = sorted(by_unit[unit])

    base = masks.masks[unit]
    for start in starts:
        window = base[start : start + bundle.train.history_len]
        assert window.shape == (bundle.train.history_len, 21)
        assert window.dtype == np.uint8
    # The same timeline row observed through two overlapping windows is identical.
    first = base[starts[0] : starts[0] + 50]
    second = base[starts[1] : starts[1] + 50]
    overlap = 50 - (starts[1] - starts[0])
    assert np.array_equal(first[starts[1] - starts[0] :], second[:overlap])


def test_engine_and_split_streams_do_not_chain(tmp_path):
    bundle = _create_bundle()
    base = generate_or_load_timeline_masks(
        tmp_path / "a.npz", _config(bundle), _timeline_lengths(bundle.train), 21
    )
    same = generate_or_load_timeline_masks(
        tmp_path / "b.npz", _config(bundle), _timeline_lengths(bundle.train), 21
    )
    assert base.content_sha256 == same.content_sha256
    for unit in base.masks:
        assert np.array_equal(base.masks[unit], same.masks[unit])

    other_seed = generate_or_load_timeline_masks(
        tmp_path / "c.npz", _config(bundle, mask_seed=2027), _timeline_lengths(bundle.train), 21
    )
    assert other_seed.content_sha256 != base.content_sha256

    # Different engines use independent streams (no chaining by id or order).
    units = sorted(base.masks)
    assert not np.array_equal(base.masks[units[0]], base.masks[units[1]])

    # A different valid engine set loads independently: valid split has its own
    # namespace even though it lives in the same official train file.
    valid = generate_or_load_timeline_masks(
        tmp_path / "d.npz",
        _config(bundle, split="valid"),
        _timeline_lengths(bundle.valid),
        21,
    )
    shared_units = set(valid.masks) & set(base.masks)
    assert shared_units  # engine ids overlap numerically across train/valid...
    for unit in sorted(shared_units)[:3]:
        assert not np.array_equal(valid.masks[unit], base.masks[unit])  # ...but streams differ


def test_artifact_identity_binds_protocol_fields(tmp_path):
    bundle = _create_bundle()
    config = _config(bundle)
    path = tmp_path / "shared_mask.npz"
    masks = generate_or_load_timeline_masks(path, config, _timeline_lengths(bundle.train), 21)

    with np.load(path) as loaded:
        meta = json.loads(str(loaded["meta"].item()))

    assert meta["schema_version"] == TIMELINE_MASK_SCHEMA_VERSION
    assert meta["dataset"] == "cmapss_fd004"
    assert meta["split"] == "train"
    assert meta["mechanism"] == "random"
    assert meta["requested_rate"] == pytest.approx(0.30)
    assert meta["mask_seed"] == 2026
    assert meta["source_split_sha256"] == bundle.split_info["split_sha256"]
    assert meta["num_sensors"] == 21
    assert meta["engine_lengths"] == {str(k): v for k, v in _timeline_lengths(bundle.train).items()}
    assert meta["content_sha256"] == masks.content_sha256
    assert masks.path == path


def test_load_strictly_validates_shape_metadata_and_content(tmp_path):
    bundle = _create_bundle()
    config = _config(bundle)
    lengths = _timeline_lengths(bundle.train)
    path = tmp_path / "shared_mask.npz"
    original = generate_or_load_timeline_masks(path, config, lengths, 21)

    # Faithful reload returns identical content.
    reloaded = generate_or_load_timeline_masks(path, config, lengths, 21)
    assert reloaded.content_sha256 == original.content_sha256

    # Wrong mechanism must be rejected.
    with pytest.raises(ValueError, match="mechanism"):
        generate_or_load_timeline_masks(path, _config(bundle, mechanism="mixed"), lengths, 21)

    # Wrong split-source SHA must be rejected.
    tampered_identity = TimelineMaskConfig(
        dataset="cmapss_fd004",
        split="train",
        mechanism="random",
        requested_rate=0.30,
        mask_seed=2026,
        source_split_sha256="0" * 64,
    )
    with pytest.raises(ValueError, match="source_split_sha256"):
        generate_or_load_timeline_masks(path, tampered_identity, lengths, 21)

    # Wrong expected engine set (shape mismatch) must be rejected.
    wrong_lengths = {unit: length + 1 for unit, length in list(lengths.items())}
    with pytest.raises(ValueError, match="shape|engine"):
        generate_or_load_timeline_masks(path, config, wrong_lengths, 21)

    # Corrupted mask content must be rejected by the content digest.
    with np.load(path) as loaded:
        arrays = {key: loaded[key] for key in loaded.files if key != "meta"}
        meta = str(loaded["meta"].item())
    first_engine = sorted(unit for unit in arrays if unit != "content_sha256")[0]
    arrays[first_engine] = (arrays[first_engine].astype(np.uint8) ^ 1).astype(np.uint8)
    np.savez_compressed(path, **arrays, meta=np.array(meta))

    with pytest.raises(ValueError, match="content"):
        generate_or_load_timeline_masks(path, config, lengths, 21)


def test_shared_bundle_is_reused_across_model_callers(tmp_path, monkeypatch):
    bundle = _create_bundle()
    config = _config(bundle)
    path = tmp_path / "shared_mask.npz"
    lengths = _timeline_lengths(bundle.train)

    generate_or_load_timeline_masks(path, config, lengths, 21)

    calls = {"count": 0}
    import kaf_profiti.experiments.masks as masks_module

    original_generate = masks_module._generate_timeline_masks

    def _counted(*args, **kwargs):
        calls["count"] += 1
        return original_generate(*args, **kwargs)

    monkeypatch.setattr(masks_module, "_generate_timeline_masks", _counted)
    # A second "model" hitting the same shared artifact path must load, not regenerate.
    second = generate_or_load_timeline_masks(path, config, lengths, 21)
    assert calls["count"] == 0
    assert second.path == path


def test_timeline_masked_window_dataset_slices_canonical_windows(tmp_path):
    bundle = _create_bundle()
    config = _config(bundle)
    masks = generate_or_load_timeline_masks(
        tmp_path / "shared_mask.npz", config, _timeline_lengths(bundle.train), 21
    )
    masked = TimelineMaskedWindowDataset(bundle.train, masks)

    assert len(masked) == len(bundle.train)
    index = min(37, len(masked) - 1)
    sample = masked[index]
    unit, start = bundle.train.windows[index]

    expected = masks.masks[unit][start : start + bundle.train.history_len]
    assert np.array_equal(sample.M_obs.numpy().astype(np.uint8), expected)
    assert torch.equal(sample.X_obs, bundle.train[index].X_obs * sample.M_obs)
    # Artificial missingness applies only to the history input. All conditions
    # must retain the base query mask and future target values, so MAE/RMSE are
    # computed on the same future positions.
    assert torch.equal(sample.M_q, bundle.train[index].M_q)
    assert torch.equal(sample.Y_q, bundle.train[index].Y_q)
    # Mask actually drops something from the history input at this rate.
    assert (sample.M_obs == 0).any()
