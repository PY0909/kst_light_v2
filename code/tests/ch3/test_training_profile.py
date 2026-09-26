"""V2-LITE-T01: lite_pipeline_v1 training-pipeline contract and manifest.

Pins the pipeline interface (num_workers=4, pin_memory=true,
persistent_workers=true, non_blocking=true, fp32 amp_dtype=None), the
training-manifest fields (epoch_seconds, train_seconds, peak_gpu_memory_mb,
num_workers, amp_dtype, parameter_count), and the smoke/formal behavior of
``run_experiment`` (smoke never touches the test split and marks
``smoke_passed``; formal keeps exactly one test evaluation).
"""

import json
import sys
from pathlib import Path

import pytest
import torch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "code"))

from kaf_profiti.experiments.manifest import (  # noqa: E402
    LITE_PIPELINE_VERSION,
    LitePipeline,
    build_training_manifest,
    peak_gpu_memory_mb,
    peak_host_memory_mb,
    write_training_manifest,
)


def test_lite_pipeline_contract_flags() -> None:
    pipeline = LitePipeline.resolve("cpu")
    assert pipeline.version == LITE_PIPELINE_VERSION == "lite_pipeline_v1"
    assert pipeline.num_workers == 4
    assert pipeline.pin_memory is True
    assert pipeline.persistent_workers is True
    assert pipeline.non_blocking is True
    # lite_pipeline_v1 trains fp32; amp_dtype records the explicit choice.
    assert pipeline.amp_dtype is None
    kwargs = pipeline.dataloader_kwargs()
    assert kwargs == {
        "num_workers": 4,
        "pin_memory": True,
        "persistent_workers": True,
    }


def test_persistent_workers_flag_follows_worker_count() -> None:
    assert LitePipeline.resolve("cpu", num_workers=0).persistent_workers is False
    assert LitePipeline.resolve("cpu", num_workers=2).persistent_workers is True


def test_peak_memory_semantics_on_cpu() -> None:
    assert peak_gpu_memory_mb("cpu") is None
    assert peak_host_memory_mb() > 0.0


def _identity() -> dict:
    return {
        "run_id": "lite-t01-test",
        "dataset": "cmapss_fd004",
        "model": "kst_light_v2",
        "seed": 2026,
        "split_seed": 2026,
        "mask_seed": 2026,
    }


def test_training_manifest_roundtrip_and_status_mapping(tmp_path: Path) -> None:
    pipeline = LitePipeline.resolve("cpu")
    manifest = build_training_manifest(
        pipeline=pipeline,
        epoch_seconds=[1.5, 1.7],
        train_seconds=3.2,
        peak_gpu_memory_mb=None,
        parameter_count=1234,
        identity=_identity(),
        run_level="smoke",
        test_evaluation_count=0,
    )
    required = {
        "epoch_seconds", "train_seconds", "peak_gpu_memory_mb",
        "num_workers", "amp_dtype", "parameter_count",
    }
    assert required <= set(manifest)
    assert manifest["epoch_seconds"] == [1.5, 1.7]
    assert manifest["train_seconds"] == 3.2
    assert manifest["num_workers"] == 4
    assert manifest["amp_dtype"] is None
    assert manifest["parameter_count"] == 1234
    assert manifest["recipe_version"] == LITE_PIPELINE_VERSION
    assert manifest["run_level"] == "smoke"
    assert manifest["evidence_status"] == "smoke_passed"
    assert manifest["eligibility"] == "tuning_only"
    assert manifest["test_evaluation_count"] == 0

    formal = build_training_manifest(
        pipeline=pipeline,
        epoch_seconds=[3.2],
        train_seconds=3.2,
        peak_gpu_memory_mb=None,
        parameter_count=1234,
        identity=_identity(),
        run_level="formal",
        test_evaluation_count=1,
    )
    assert formal["evidence_status"] == "full_completed"
    assert formal["test_evaluation_count"] == 1

    out = tmp_path / "training_manifest.json"
    write_training_manifest(out, manifest)
    assert json.loads(out.read_text(encoding="utf-8")) == manifest


def _smoke_config(**overrides):
    from run_experiment import ExperimentConfig

    # Pipeline smoke vehicle: run_experiment's evaluator still binds the
    # legacy probabilistic model API (model.distribution/flow_head); the v2
    # point-model contract lands in V2-CH3-CODE-T02. The pipeline itself
    # (loaders/flags/timing/manifest) is model-agnostic.
    base = dict(
        dataset="cmapss_fd004",
        model="kaf_profiti_joint",
        seed=2026,
        history_len=50,
        pred_len=10,
        stride=1,
        epochs=1,
        batch_size=16,
        max_train_batches=2,
        max_eval_batches=2,
        hidden_dim=16,
        patch_lens="5,10",
        device="cpu",
        num_workers=0,
    )
    base.update(overrides)
    return ExperimentConfig(**base)


def _run_artifact_root(output_dir: Path, config) -> Path:
    from run_experiment import _run_dir

    return _run_dir(output_dir, config)


@pytest.mark.skipif(
    not (REPO_ROOT / "dataset" / "CMAPSSData" / "train_FD004.txt").is_file(),
    reason="FD004 raw data not present",
)
def test_run_experiment_smoke_never_touches_test(tmp_path: Path) -> None:
    from run_experiment import run_experiment

    config = _smoke_config(
        run_level="smoke",
        output_dir=str(tmp_path),
        run_id="lite-t01-smoke",
    )
    summary = run_experiment(config)
    assert summary["status"] == "smoke_passed"
    assert summary["test_evaluation_count"] == 0

    run_root = _run_artifact_root(tmp_path, config)
    manifest_path = Path(summary["training_manifest_path"])
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for field in ("epoch_seconds", "train_seconds", "peak_gpu_memory_mb",
                  "num_workers", "amp_dtype", "parameter_count"):
        assert field in manifest, field
    assert manifest["evidence_status"] == "smoke_passed"
    assert manifest["eligibility"] == "tuning_only"
    assert manifest["test_evaluation_count"] == 0
    assert len(manifest["epoch_seconds"]) == 1
    assert manifest["train_seconds"] > 0.0
    assert manifest["parameter_count"] > 0
    # A smoke run produces no test metrics and no predictions.
    metrics_files = list((tmp_path).rglob("metrics_seed*.json"))
    assert metrics_files == []
    pred_files = list((tmp_path).rglob("*.npy"))
    assert pred_files == []


@pytest.mark.skipif(
    not (REPO_ROOT / "dataset" / "CMAPSSData" / "train_FD004.txt").is_file(),
    reason="FD004 raw data not present",
)
def test_run_experiment_formal_keeps_single_test_evaluation(tmp_path: Path) -> None:
    from run_experiment import run_experiment

    config = _smoke_config(
        run_level="formal",
        output_dir=str(tmp_path),
        run_id="lite-t01-formal",
    )
    metrics = run_experiment(config)
    assert metrics["status"] == "completed"
    assert metrics["test_evaluation_count"] == 1
    manifest = json.loads(
        Path(metrics["training_manifest_path"]).read_text(encoding="utf-8")
    )
    assert manifest["evidence_status"] == "full_completed"
    assert manifest["test_evaluation_count"] == 1


def test_smoke_loader_accepts_contract_flags_on_cpu(tmp_path: Path) -> None:
    """Interface check: the pinned flags are accepted by DataLoader on CPU."""

    from torch.utils.data import DataLoader, TensorDataset

    pipeline = LitePipeline.resolve("cpu")
    loader = DataLoader(
        TensorDataset(torch.arange(64).float()),
        batch_size=8,
        **pipeline.dataloader_kwargs(),
    )
    batches = [batch for batch in loader]
    assert len(batches) == 8
    del loader
