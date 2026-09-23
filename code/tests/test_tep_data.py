import os
from pathlib import Path

import torch

from kaf_profiti.experiments.datasets import create_protocol_datasets
from kaf_profiti.industrial.batch import IndustrialCollator
from kaf_profiti.industrial.tep import (
    TEP_CONTEXT_COLUMNS,
    TEP_SENSOR_COLUMNS,
    TEPWindowDataset,
    TEPWindowSample,
    inspect_tep_rdata_file,
    load_tep_frame,
)


DATA_ROOT = Path(os.environ.get("KST_DATA_ROOT", "/root/autodl-tmp/dataset"))
DATA_DIR = DATA_ROOT / "dataverse_files"


def test_inspect_tep_fault_free_training_rdata_facts():
    info = inspect_tep_rdata_file(DATA_DIR / "TEP_FaultFree_Training.RData")

    assert info["object_name"] == "fault_free_training"
    assert info["num_rows"] == 250000
    assert info["num_columns"] == 55
    assert info["columns"][:3] == ["faultNumber", "simulationRun", "sample"]
    assert info["columns"][3] == "xmeas_1"
    assert info["columns"][-1] == "xmv_11"
    assert len(TEP_SENSOR_COLUMNS) == 52
    assert TEP_CONTEXT_COLUMNS == [f"xmv_{idx}" for idx in range(1, 12)]


def test_load_tep_frame_filters_runs_without_full_materialization():
    frame = load_tep_frame(
        DATA_DIR,
        source="fault_free_training",
        max_runs_per_fault=2,
    )

    assert frame.shape == (1000, 55)
    assert sorted(frame["simulationRun"].unique().tolist()) == [1, 2]
    assert frame["faultNumber"].nunique() == 1
    assert int(frame["faultNumber"].iloc[0]) == 0
    assert frame.groupby(["faultNumber", "simulationRun"])["sample"].min().eq(1).all()
    assert frame.groupby(["faultNumber", "simulationRun"])["sample"].max().eq(500).all()


def test_tep_window_dataset_shapes_and_run_boundaries():
    dataset = TEPWindowDataset(
        DATA_DIR,
        source="fault_free_training",
        history_len=12,
        pred_len=3,
        stride=250,
        async_mode="none",
        seed=2026,
        max_runs_per_fault=2,
    )

    sample = dataset[0]
    last_sample = dataset[-1]

    assert isinstance(sample, TEPWindowSample)
    assert sample.X_obs.shape == (12, 52)
    assert sample.T_obs.shape == (12,)
    assert sample.Y_q.shape == (3, 52)
    assert sample.T_q.shape == (3,)
    assert sample.context.shape == (11,)
    assert torch.all(sample.M_obs == 1)
    assert torch.all(sample.M_q == 1)
    assert sample.T_q[0] > sample.T_obs[-1]
    assert sample.unit_id != last_sample.unit_id


def test_tep_async_mask_is_reproducible_and_zero_filled():
    kwargs = dict(
        data_dir=DATA_DIR,
        source="fault_free_training",
        history_len=12,
        pred_len=3,
        stride=250,
        async_mode="mixed",
        seed=99,
        max_runs_per_fault=2,
    )
    sample_a = TEPWindowDataset(**kwargs)[1]
    sample_b = TEPWindowDataset(**kwargs)[1]

    assert torch.equal(sample_a.M_obs, sample_b.M_obs)
    assert torch.equal(sample_a.X_obs, sample_b.X_obs)
    assert (sample_a.M_obs == 0).any()
    assert torch.all(sample_a.X_obs[sample_a.M_obs == 0] == 0)


def test_tep_protocol_split_uses_run_ids_without_overlap():
    bundle = create_protocol_datasets(
        "tep",
        DATA_ROOT,
        seed=2026,
        history_len=12,
        pred_len=3,
        stride=250,
        async_mode="none",
    )

    train_ids = set(bundle.split_info["train_run_ids"])
    valid_ids = set(bundle.split_info["valid_run_ids"])

    assert bundle.name == "tep"
    assert bundle.num_sensors == 52
    assert bundle.context_dim == 11
    assert bundle.split_info["split_rule"] == "simulation_run_80_20_official_test"
    assert train_ids
    assert valid_ids
    assert train_ids.isdisjoint(valid_ids)
    assert len(bundle.train) > 0
    assert len(bundle.valid) > 0
    assert len(bundle.test) > 0


def test_tep_batch_collator_shapes():
    dataset = TEPWindowDataset(
        DATA_DIR,
        source="fault_free_training",
        history_len=12,
        pred_len=3,
        stride=250,
        async_mode="none",
        seed=7,
        max_runs_per_fault=2,
    )
    batch = IndustrialCollator()([dataset[0], dataset[1]])

    assert batch.X_obs.shape == (2, 12, 52)
    assert batch.y_flat.shape == (2, 156)
    assert batch.query_channel_ids.shape == (156,)
    assert torch.equal(batch.query_channel_ids[:52], torch.arange(52))
