"""V2-CH3-CODE-T02: chapter=ch3 point contract in the run_experiment entry.

Pins: the enforced point contract (``predict_point`` + point loss), the ch3
training/validation/test path for ``kst_light_v2`` (validation-MAE checkpoint
selection, exactly one formal test evaluation, null probabilistic metrics),
seed passthrough (split_seed/mask_seed), the run-identity manifest chain
(dataset/split/normalization/mask/evaluator/code/matrix SHA + command +
environment + checkpoint SHA), resume identity rejection, and the registry
``pred_len`` pass-through for the v2 point model.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "code"))

from kaf_profiti.experiments.evaluator import require_point_contract  # noqa: E402
from kaf_profiti.experiments.registry import create_model  # noqa: E402

FD004_PRESENT = (REPO_ROOT / "dataset" / "CMAPSSData" / "train_FD004.txt").is_file()


def _config(**overrides):
    from run_experiment import ExperimentConfig

    base = dict(
        dataset="cmapss_fd004",
        model="kst_light_v2",
        seed=2026,
        split_seed=2026,
        mask_seed=2026,
        history_len=50,
        pred_len=10,
        stride=1,
        epochs=1,
        batch_size=8,
        max_train_batches=2,
        max_eval_batches=2,
        hidden_dim=16,
        patch_lens="5,10",
        device="cpu",
        num_workers=0,
        run_level="formal",
    )
    base.update(overrides)
    return ExperimentConfig(**base)


def test_require_point_contract_accepts_v2_and_rejects_legacy():
    point_model = create_model(
        "kst_light_v2", num_sensors=21, context_dim=3, device="cpu",
        hidden_dim=16, patch_lens="5,10", pred_len=10,
    )
    require_point_contract(point_model)  # must not raise

    legacy_model = create_model(
        "kaf_profiti_joint", num_sensors=21, context_dim=3, device="cpu",
        hidden_dim=16,
    )
    with pytest.raises(ValueError, match="predict_point"):
        require_point_contract(legacy_model)


def test_registry_create_model_passes_pred_len():
    model = create_model(
        "kst_light_v2", num_sensors=21, context_dim=3, device="cpu",
        hidden_dim=16, patch_lens="5,10", pred_len=10,
    )
    assert model.config.pred_len == 10


def test_ch3_enforcement_rejects_non_point_model(tmp_path: Path):
    from run_experiment import run_experiment

    config = _config(
        model="kaf_profiti_joint",
        chapter="ch3",
        output_dir=str(tmp_path),
        run_id="ch3-contract-reject",
    )
    with pytest.raises(ValueError, match="predict_point"):
        run_experiment(config)


@pytest.mark.skipif(not FD004_PRESENT, reason="FD004 raw data not present")
def test_kst_light_v2_ch3_formal_run_end_to_end(tmp_path: Path):
    from run_experiment import run_experiment

    config = _config(output_dir=str(tmp_path), run_id="ch3-e2e")
    metrics = run_experiment(config)

    assert metrics["status"] == "completed"
    assert metrics["test_evaluation_count"] == 1
    assert metrics["chapter"] == "ch3"
    assert metrics["mae"] == metrics["mae"] and metrics["mae"] >= 0.0
    assert metrics["rmse"] >= 0.0
    assert metrics["nll"] is None  # point contract: probabilistic metrics null
    assert metrics["best_valid_metric_name"] == "valid_mae"

    manifest = json.loads(
        Path(metrics["training_manifest_path"]).read_text(encoding="utf-8")
    )
    identity = manifest["protocol_identity"]
    # the FD004 protocol identity is public and stable (pinned elsewhere)
    assert identity["dataset"] == "cmapss_fd004"
    assert identity["split_sha256"].startswith("61c7db91")
    assert identity["normalization_sha256"]
    assert identity["mask_sha256"]
    assert identity["evaluator_sha256"]
    assert identity["code_sha256"]
    assert identity["matrix_sha256"]
    assert manifest["command"]
    assert manifest["environment"]["torch"]
    assert manifest["checkpoint_sha256"]
    assert manifest["split_seed"] == 2026 and manifest["mask_seed"] == 2026

    matrix_path = REPO_ROOT / "configs" / "ch3" / "point_matrix.yaml"
    import hashlib

    assert identity["matrix_sha256"] == hashlib.sha256(
        matrix_path.read_bytes()
    ).hexdigest()


@pytest.mark.skipif(not FD004_PRESENT, reason="FD004 raw data not present")
def test_ch3_smoke_never_touches_test(tmp_path: Path):
    from run_experiment import run_experiment

    config = _config(
        run_level="smoke",
        output_dir=str(tmp_path),
        run_id="ch3-smoke",
    )
    summary = run_experiment(config)
    assert summary["status"] == "smoke_passed"
    assert summary["test_evaluation_count"] == 0
    assert list(tmp_path.rglob("metrics_seed*.json")) == []


@pytest.mark.skipif(not FD004_PRESENT, reason="FD004 raw data not present")
def test_resume_identity_mismatch_rejected(tmp_path: Path):
    from run_experiment import run_experiment

    config = _config(
        run_level="smoke",
        output_dir=str(tmp_path),
        run_id="ch3-resume",
    )
    summary = run_experiment(config)
    checkpoint_path = summary["final_checkpoint_path"]

    same = _config(
        run_level="smoke",
        output_dir=str(tmp_path),
        run_id="ch3-resume",
        checkpoint=checkpoint_path,
    )
    resumed = run_experiment(same)
    assert resumed["status"] == "smoke_passed"

    drifted = _config(
        run_level="smoke",
        output_dir=str(tmp_path),
        run_id="ch3-resume",
        checkpoint=checkpoint_path,
        dataset="cmapss_fd001",
    )
    with pytest.raises(ValueError, match="identity"):
        run_experiment(drifted)
