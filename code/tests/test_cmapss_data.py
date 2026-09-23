import os
from pathlib import Path

import torch

from kaf_profiti.industrial.batch import IndustrialCollator
from kaf_profiti.industrial.cmapss import (
    CMapssWindowDataset,
    CMapssWindowSample,
    load_cmapss_frame,
)


DATA_ROOT = Path(os.environ.get("KST_DATA_ROOT", "/root/autodl-tmp/dataset"))
DATA_DIR = DATA_ROOT / "CMAPSSData"


def test_load_cmapss_frame_matches_fd001_file_facts():
    frame = load_cmapss_frame(DATA_DIR, "FD001", "train")

    assert frame.shape == (20631, 27)
    assert frame["unit"].nunique() == 100
    assert frame["cycle"].max() == 362
    assert list(frame.columns[:5]) == [
        "unit",
        "cycle",
        "setting_1",
        "setting_2",
        "setting_3",
    ]
    assert frame.filter(regex=r"^sensor_").shape[1] == 21


def test_cmapss_window_does_not_cross_units_and_uses_future_target():
    dataset = CMapssWindowDataset(
        DATA_DIR,
        subset="FD001",
        split="train",
        history_len=30,
        pred_len=5,
        stride=25,
        async_mode="none",
        seed=123,
    )

    sample = dataset[0]

    assert isinstance(sample, CMapssWindowSample)
    assert sample.X_obs.shape == (30, 21)
    assert sample.T_obs.shape == (30,)
    assert sample.Y_q.shape == (5, 21)
    assert sample.T_q.shape == (5,)
    assert sample.context.shape == (3,)
    assert sample.unit_id == 1
    assert torch.equal(sample.T_obs, torch.arange(1, 31, dtype=torch.float32))
    assert torch.equal(sample.T_q, torch.arange(31, 36, dtype=torch.float32))
    assert torch.all(sample.M_obs == 1)
    assert torch.all(sample.M_q == 1)


def test_async_mask_is_reproducible_and_zero_filled():
    kwargs = dict(
        data_dir=DATA_DIR,
        subset="FD001",
        split="train",
        history_len=30,
        pred_len=5,
        stride=25,
        async_mode="mixed",
        seed=77,
    )
    sample_a = CMapssWindowDataset(**kwargs)[3]
    sample_b = CMapssWindowDataset(**kwargs)[3]

    assert torch.equal(sample_a.M_obs, sample_b.M_obs)
    assert torch.equal(sample_a.X_obs, sample_b.X_obs)
    assert (sample_a.M_obs == 0).any()
    assert torch.all(sample_a.X_obs[sample_a.M_obs == 0] == 0)
    assert torch.all(sample_a.M_q == 1)


def test_industrial_collator_flattens_queries_time_first():
    dataset = CMapssWindowDataset(
        DATA_DIR,
        subset="FD001",
        split="train",
        history_len=30,
        pred_len=5,
        stride=25,
        async_mode="none",
        seed=123,
    )
    batch = IndustrialCollator()([dataset[0], dataset[1]])

    assert batch.X_obs.shape == (2, 30, 21)
    assert batch.T_obs.shape == (2, 30)
    assert batch.Y_q.shape == (2, 5, 21)
    assert batch.y_flat.shape == (2, 105)
    assert batch.mq_flat.shape == (2, 105)
    assert torch.equal(batch.query_channel_ids[:21], torch.arange(21))
    assert torch.equal(batch.query_channel_ids[21:42], torch.arange(21))
    assert torch.equal(batch.y_flat[0, :21], batch.Y_q[0, 0])
    assert torch.equal(batch.y_flat[0, 21:42], batch.Y_q[0, 1])
