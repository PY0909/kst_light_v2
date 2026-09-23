import os
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from kaf_profiti.industrial.batch import IndustrialCollator
from kaf_profiti.industrial.metropt import (
    METROPT_CONTEXT_COLUMNS,
    METROPT_FAULT_WINDOWS,
    METROPT_SENSOR_COLUMNS,
    MetroPTWindowDataset,
    MetroPTWindowSample,
    load_metropt_frame,
)
from kaf_profiti.models.kaf_profiti import KAFProFITi, KAFProFITiConfig


DATA_ROOT = Path(os.environ.get("KST_DATA_ROOT", "/root/autodl-tmp/dataset"))
DATA_DIR = DATA_ROOT / "metropt+3+dataset"


def test_load_metropt_frame_matches_csv_facts():
    frame = load_metropt_frame(DATA_DIR)

    assert frame.shape == (1516948, 18)
    assert frame["timestamp"].min().isoformat() == "2020-02-01T00:00:00"
    assert frame["timestamp"].max().isoformat() == "2020-09-01T03:59:50"
    assert frame["timestamp"].is_monotonic_increasing
    assert len(METROPT_SENSOR_COLUMNS) == 15
    assert METROPT_CONTEXT_COLUMNS == ["COMP", "DV_eletric", "MPG"]
    assert frame[METROPT_SENSOR_COLUMNS].isna().sum().sum() == 0


def test_metropt_fault_windows_label_known_ranges():
    frame = load_metropt_frame(DATA_DIR)

    assert len(METROPT_FAULT_WINDOWS) == 4
    assert int(frame["fault_label"].sum()) > 0
    failure_slice = frame[
        (frame["timestamp"] >= "2020-04-18 00:00:00")
        & (frame["timestamp"] <= "2020-04-18 23:59:00")
    ]
    normal_slice = frame[
        (frame["timestamp"] >= "2020-02-01 00:00:00")
        & (frame["timestamp"] <= "2020-02-01 00:10:00")
    ]

    assert failure_slice["fault_label"].max() == 1
    assert normal_slice["fault_label"].max() == 0


def test_metropt_window_shapes_and_split_boundary():
    dataset = MetroPTWindowDataset(
        DATA_DIR,
        split="train",
        history_len=12,
        pred_len=3,
        stride=120,
        async_mode="none",
        seed=13,
    )

    sample = dataset[0]

    assert isinstance(sample, MetroPTWindowSample)
    assert sample.X_obs.shape == (12, 15)
    assert sample.T_obs.shape == (12,)
    assert sample.Y_q.shape == (3, 15)
    assert sample.T_q.shape == (3,)
    assert sample.context.shape == (3,)
    assert torch.all(sample.M_obs == 1)
    assert torch.all(sample.M_q == 1)
    assert sample.T_obs[0].item() == 0.0
    assert sample.T_obs[-1].item() == 11.0
    assert sample.T_q[0].item() == 12.0
    assert sample.T_q[0] > sample.T_obs[-1]
    assert sample.unit_id == 0


def test_metropt_async_mask_is_reproducible_and_zero_filled():
    kwargs = dict(
        data_dir=DATA_DIR,
        split="train",
        history_len=12,
        pred_len=3,
        stride=120,
        async_mode="mixed",
        seed=99,
    )
    sample_a = MetroPTWindowDataset(**kwargs)[5]
    sample_b = MetroPTWindowDataset(**kwargs)[5]

    assert torch.equal(sample_a.M_obs, sample_b.M_obs)
    assert torch.equal(sample_a.X_obs, sample_b.X_obs)
    assert (sample_a.M_obs == 0).any()
    assert torch.all(sample_a.X_obs[sample_a.M_obs == 0] == 0)


def test_metropt_batch_runs_kaf_profiti_loss():
    torch.manual_seed(7)
    dataset = MetroPTWindowDataset(
        DATA_DIR,
        split="train",
        history_len=12,
        pred_len=3,
        stride=240,
        async_mode="mixed",
        seed=7,
    )
    batch = next(iter(DataLoader(dataset, batch_size=4, collate_fn=IndustrialCollator())))
    model = KAFProFITi(
        KAFProFITiConfig(
            num_sensors=15,
            context_dim=3,
            hidden_dim=24,
            te_dim=5,
            kernel_count=4,
            n_layers=1,
            n_heads=2,
            flow_layers=1,
            preconv_dim=4,
            lambda_point=0.1,
            device="cpu",
        )
    )

    loss = model.loss(batch, nsamples_for_point=1)

    assert batch.y_flat.shape == (4, 45)
    assert torch.isfinite(loss)
