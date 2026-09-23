"""Window/target continuity tests for the FD004 pilot protocol (diagnostic step 2).

Fixed-engine/fixed-start assertions against the raw C-MAPSS tables:
  * the returned ``X_obs[-1]`` and ``Y_q[0]`` equal the normalized correct two
    rows of the raw file for ``(engine, start)``;
  * ``T_q[0]`` is exactly the cycle after ``T_obs[-1]``;
  * history is rows ``[start, start+50)`` and target ``[start+50, start+60)``;
  * train/valid/test windows never reshuffle across splits (engine sets
    disjoint, canonical ordering, no shared ``(unit, start)``).

Run: pytest tests/pilot/test_fd004_window_continuity.py
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch

from kaf_profiti.experiments.datasets import create_protocol_datasets

HISTORY_LEN = 50
PRED_LEN = 10
STRIDE = 1
SEED = 2026
SPLIT_SEED = 2026

_COLUMNS = (
    ["unit", "cycle"]
    + [f"setting_{idx}" for idx in (1, 2, 3)]
    + [f"sensor_{idx}" for idx in range(1, 22)]
)


def _data_root() -> Path:
    root = os.environ.get("KST_DATA_ROOT")
    if root:
        candidate = Path(root)
        if (candidate / "CMAPSSData" / "train_FD004.txt").exists():
            return candidate
    local = Path(__file__).resolve().parents[3] / "dataset"
    if (local / "CMAPSSData" / "train_FD004.txt").exists():
        return local
    pytest.skip("FD004 raw data not available")


def _read_raw(split: str) -> pd.DataFrame:
    frame = pd.read_csv(
        _data_root() / "CMAPSSData" / f"{split}_FD004.txt", sep=r"\s+", header=None
    )
    frame.columns = _COLUMNS
    return frame


@pytest.fixture(scope="module")
def protocol():
    return create_protocol_datasets(
        "cmapss_fd004",
        _data_root(),
        seed=SEED,
        history_len=HISTORY_LEN,
        pred_len=PRED_LEN,
        stride=STRIDE,
        async_mode="none",
        split_seed=SPLIT_SEED,
    )


@pytest.fixture(scope="module")
def raw_tables():
    return {"train": _read_raw("train"), "test": _read_raw("test")}


def _normalized_row(frame: pd.DataFrame, unit: int, row_index: int, stats) -> np.ndarray:
    row = frame[frame["unit"] == unit].iloc[row_index]
    values = np.array([row[f"sensor_{idx}"] for idx in range(1, 22)], dtype=np.float64)
    return (values - stats["sensor_mean"].numpy()) / stats["sensor_std"].numpy()


@pytest.mark.parametrize(
    "split, unit, start",
    [
        ("train", 1, 0),
        ("train", 1, 261),      # last window of engine 1 (len 302)
        ("valid", 5, 0),
        ("valid", 5, 133),     # last window of engine 5 (len 194)
        ("test", 1, 0),
        ("test", 1, 170),      # last window of test engine 1
    ],
)
def test_fixed_window_matches_raw_table(protocol, raw_tables, split, unit, start):
    dataset = getattr(protocol, split)
    assert (unit, start) in dataset.windows, "chosen window missing from split"
    sample = dataset[dataset.windows.index((unit, start))]

    frame = raw_tables["train" if split != "test" else "test"]
    cycles = frame[frame["unit"] == unit]["cycle"].to_numpy()
    assert len(cycles) >= start + HISTORY_LEN + PRED_LEN

    assert sample.T_obs.numel() == HISTORY_LEN and sample.T_q.numel() == PRED_LEN
    np.testing.assert_array_equal(sample.T_obs.numpy(), cycles[start : start + HISTORY_LEN])
    np.testing.assert_array_equal(
        sample.T_q.numpy(), cycles[start + HISTORY_LEN : start + HISTORY_LEN + PRED_LEN]
    )
    assert sample.T_q[0].item() == sample.T_obs[-1].item() + 1

    stats = protocol.train.stats
    np.testing.assert_allclose(
        sample.X_obs[-1].numpy(),
        _normalized_row(frame, unit, start + HISTORY_LEN - 1, stats),
        atol=1e-4,
    )
    np.testing.assert_allclose(
        sample.Y_q[0].numpy(),
        _normalized_row(frame, unit, start + HISTORY_LEN, stats),
        atol=1e-4,
    )

    raw_last = (
        frame[frame["unit"] == unit]
        .iloc[start + HISTORY_LEN - 1][[f"sensor_{idx}" for idx in range(1, 22)]]
        .to_numpy(dtype=np.float64)
    )
    denorm = sample.X_obs[-1].numpy() * stats["sensor_std"].numpy() + stats["sensor_mean"].numpy()
    assert np.abs(denorm - raw_last).max() < 1e-2, "denormalized boundary row must match raw scale"


def test_base_mask_is_fully_observed(protocol):
    sample = protocol.train[0]
    assert bool((sample.M_obs == 1).all()), "async_mode=none must yield an all-observed base mask"
    assert bool((sample.M_q == 1).all()), "targets are never artificially masked"


def test_splits_are_engine_disjoint_and_unshuffled(protocol):
    info = protocol.split_info
    train_ids, valid_ids = set(info["train_engine_ids"]), set(info["valid_engine_ids"])
    assert not (train_ids & valid_ids)
    train_windows = [tuple(w) for w in protocol.train.windows]
    valid_windows = [tuple(w) for w in protocol.valid.windows]
    assert not (set(train_windows) & set(valid_windows))
    for windows, allowed in (
        (train_windows, train_ids),
        (valid_windows, valid_ids),
        ([tuple(w) for w in protocol.test.windows], None),
    ):
        assert windows == sorted(windows)
        assert len(set(windows)) == len(windows)
        if allowed is not None:
            assert {unit for unit, _ in windows} <= allowed
    bounds = info["window_bounds"]
    assert bounds["train"]["count"] == len(train_windows)
    assert bounds["valid"]["count"] == len(valid_windows)
    assert bounds["test"]["count"] == len(protocol.test.windows)


def test_window_bounds_are_stable(protocol):
    info = protocol.split_info
    for split in ("train", "valid", "test"):
        dataset = getattr(protocol, split)
        entry = info["window_bounds"][split]
        assert tuple(entry["first"]) == tuple(dataset.windows[0])
        assert tuple(entry["last"]) == tuple(dataset.windows[-1])
