"""V2-CH3-CODE-T03: formal point-matrix execution wiring and result validator.

The executor (``run_pilot_matrix.py --config``) expands the authoritative
matrix, enforces baseline-first gating per (protocol, condition), resumes
verified completed runs, writes PilotRunner-shaped manifests with the formal
identity chain, and supports a test-free smoke mode. ``validate_results.py``
checks the expected 66-key coverage plus key/fairness/finite/test-count/
parameter-and-timing fields over the produced run tree.
"""

import json
import sys
from pathlib import Path

import pytest
import torch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "code"))

from kaf_profiti.experiments.formal_matrix import (  # noqa: E402
    expand_formal_matrix,
    load_formal_matrix,
)
from run_pilot_matrix import (  # noqa: E402
    _formal_execute_keys,
    _formal_profile_for,
)
from validate_results import validate_formal_results  # noqa: E402

FD001_PRESENT = (REPO_ROOT / "dataset" / "CMAPSSData" / "train_FD001.txt").is_file()


def _matrix():
    return load_formal_matrix(REPO_ROOT / "configs" / "ch3" / "point_matrix.yaml")


def _fd001_keys(matrix):
    return [key for key in expand_formal_matrix(matrix) if key.protocol == "cmapss_fd001"]


class _FakeProvider:
    num_sensors = 21
    context_dim = 3

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def model_options(self):
        return {}

    def protocol_fingerprint(self):
        return {
            "dataset": "cmapss_fd001",
            "split_sha256": "fake-split-sha",
            "normalization_sha256": "fake-norm-sha",
            "mask_sha": {"train": "m1", "valid": "m2", "test": "m3"},
        }


def _fake_result(spec):
    return {
        "history": [{"epoch": 1, "train_loss": 0.5, "valid_score": 0.4}],
        "metrics": {"point": {"mae": 0.25, "rmse": 0.5, "valid_count": 10},
                    "probabilistic": {}},
        "checkpoint_bytes": b"fake-checkpoint",
        "predictions": {"parameter_count": 1234},
        "train_time_sec": 1.5,
        "inference_time_sec": 0.02,
        "model_class": "FakeModel",
        "model_config": {"hidden_dim": spec.hidden_dim},
        "optimizer_config": {"lr": 1e-3, "weight_decay": 1e-4,
                             "scheduler": "cosine", "grad_clip_norm": 1.0},
        "training_command_hash": "hash",
        "checkpoint_selection": "best_valid",
        "device": "cpu",
    }


def test_formal_profile_mapping_covers_six_protocols():
    assert _formal_profile_for("metropt3_chrono_502030_v2") == "metropt3"
    assert _formal_profile_for("cmapss_fd001") == "fd001"
    assert _formal_profile_for("cmapss_fd002") == "fd002"
    assert _formal_profile_for("cmapss_fd003") == "fd003"
    assert _formal_profile_for("cmapss_fd004") == "fd004"
    assert _formal_profile_for("tep_faulty") == "tep_faulty"


def test_execute_writes_verified_manifests_and_resumes(tmp_path: Path):
    matrix = _matrix()
    keys = _fd001_keys(matrix)
    assert len(keys) == 6

    calls = []

    def run_fn(spec, provider, device):
        calls.append(spec.key)
        assert provider.protocol_fingerprint()["dataset"] == "cmapss_fd001"
        return _fake_result(spec)

    summary = _formal_execute_keys(
        matrix, keys, result_root=tmp_path, data_root=tmp_path,
        device="cpu", run_fn=run_fn,
        provider_factory=lambda **kwargs: _FakeProvider(**kwargs),
    )
    assert summary["failed"] == [] and summary["gate_blocked"] == []
    assert summary["executed"] == 6 and summary["resumed"] == 0
    # baseline-first ordering within the condition group
    assert calls[-1].split("|")[2] == "kst_light_v2"

    manifest_dir = tmp_path / "pilot" / "fd001" / "runs"
    manifests = list(manifest_dir.glob("*/manifest.json"))
    assert len(manifests) == 6
    manifest = json.loads(
        (manifest_dir / keys[0].scientific_key / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "completed"
    assert manifest["run_id"] == keys[0].scientific_key
    assert manifest["test_evaluation_count"] == 1
    assert manifest["matrix_id"] == matrix.matrix_id
    assert manifest["matrix_sha256"] == matrix.matrix_sha256
    assert manifest["protocol_sha"]["split_sha256"] == "fake-split-sha"
    assert manifest["parameter_count"] == 1234
    assert manifest["train_seconds"] == 1.5
    assert manifest["inference_time_sec"] == 0.02
    for name in ("history", "metrics", "checkpoint", "predictions"):
        assert manifest["artifacts"][name]
        assert manifest["artifact_sha256"][name]

    # a second pass resumes: nothing re-executed
    second = _formal_execute_keys(
        matrix, keys, result_root=tmp_path, data_root=tmp_path,
        device="cpu", run_fn=run_fn,
        provider_factory=lambda **kwargs: _FakeProvider(**kwargs),
    )
    assert second["executed"] == 0 and second["resumed"] == 6


def test_baseline_first_gate_blocks_ours(tmp_path: Path):
    matrix = _matrix()
    keys = _fd001_keys(matrix)

    def failing_baselines(spec, provider, device):
        if spec.family == "baseline":
            raise RuntimeError("baseline exploded")
        return _fake_result(spec)

    summary = _formal_execute_keys(
        matrix, keys, result_root=tmp_path, data_root=tmp_path,
        device="cpu", run_fn=failing_baselines,
        provider_factory=lambda **kwargs: _FakeProvider(**kwargs),
    )
    assert len(summary["failed"]) == 5
    assert len(summary["gate_blocked"]) == 1
    assert "kst_light_v2" in summary["gate_blocked"][0]
    # the ours run was never attempted
    ours_dir = tmp_path / "pilot" / "fd001" / "runs"
    ours_keys = [d.name for d in ours_dir.glob("*kst_light_v2*")] if ours_dir.exists() else []
    assert ours_keys == []


@pytest.mark.skipif(not FD001_PRESENT, reason="FD001 raw data not present")
def test_formal_smoke_real_fd001_li_tcn(tmp_path: Path):
    from run_pilot_matrix import _formal_smoke

    matrix = _matrix()
    keys = [k for k in _fd001_keys(matrix) if k.model_id == "li_tcn"]
    report = _formal_smoke(matrix, keys, result_root=tmp_path, data_root=REPO_ROOT / "dataset",
                           device="cpu")
    entry = report["entries"][0]
    assert entry["model_id"] == "li_tcn"
    assert entry["loss_finite"] is True
    assert entry["params_changed"] is True
    assert entry["valid_point_finite"] is True
    assert entry["test_loader_touched"] is False
    assert report["test_metric_count"] == 0
    # smoke never creates run directories
    assert list((tmp_path / "pilot" / "fd001").glob("runs/*")) == []


def _fabricate_run(root: Path, key, matrix, *, protocol_sha=None, mae=0.25,
                   test_count=1, status="completed"):
    profile = _formal_profile_for(key.protocol)
    run_dir = root / "pilot" / profile / "runs" / key.scientific_key
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "history.json").write_text(json.dumps(
        [{"epoch": 1, "train_loss": 0.5, "valid_score": 0.4}]), encoding="utf-8")
    metrics = {"point": {"mae": mae, "rmse": 0.5, "valid_count": 10}, "probabilistic": {}}
    (run_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    (run_dir / "predictions.json").write_text(json.dumps({"parameter_count": 1234}), encoding="utf-8")
    (run_dir / "checkpoint.pt").write_bytes(b"fake-checkpoint")
    manifest = {
        "status": status,
        "run_id": key.scientific_key,
        "matrix_id": matrix.matrix_id,
        "matrix_sha256": matrix.matrix_sha256,
        "test_evaluation_count": test_count,
        "protocol_sha": protocol_sha or {
            "dataset": key.protocol,
            "split_sha256": f"split-{key.protocol}",
            "normalization_sha256": f"norm-{key.protocol}",
            "mask_sha": {"train": "m1", "valid": "m2", "test": "m3"},
        },
        "parameter_count": 1234,
        "train_seconds": 1.0,
        "inference_time_sec": 0.01,
        "artifacts": {
            "history": "history.json", "metrics": "metrics.json",
            "checkpoint": "checkpoint.pt", "predictions": "predictions.json",
        },
        "artifact_sha256": {},
    }
    import hashlib

    for name, relative in manifest["artifacts"].items():
        manifest["artifact_sha256"][name] = hashlib.sha256(
            (run_dir / relative).read_bytes()
        ).hexdigest()
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_validator_passes_fabricated_fd001_group(tmp_path: Path):
    matrix = _matrix()
    for key in _fd001_keys(matrix):
        _fabricate_run(tmp_path, key, matrix)
    verdict = validate_formal_results(matrix, tmp_path, protocols={"cmapss_fd001"})
    assert verdict["expected"] == 6
    assert verdict["completed"] == 6
    assert verdict["missing"] == [] and verdict["failed"] == []
    assert verdict["fairness_mismatch"] == 0


def test_validator_flags_missing_fairness_nonfinite_and_test_count(tmp_path: Path):
    matrix = _matrix()
    keys = _fd001_keys(matrix)
    for key in keys:
        _fabricate_run(tmp_path, key, matrix)
    # 1) missing run
    (tmp_path / "pilot" / "fd001" / "runs" / keys[2].scientific_key / "manifest.json").unlink()
    verdict = validate_formal_results(matrix, tmp_path, protocols={"cmapss_fd001"})
    assert verdict["completed"] == 5 and len(verdict["missing"]) == 1

    # restore, then break fairness: one model sees a different split sha
    _fabricate_run(tmp_path, keys[2], matrix)
    drifted = {"dataset": "cmapss_fd001", "split_sha256": "DRIFT",
               "normalization_sha256": "n", "mask_sha": {}}
    _fabricate_run(tmp_path, keys[4], matrix, protocol_sha=drifted)
    verdict = validate_formal_results(matrix, tmp_path, protocols={"cmapss_fd001"})
    assert verdict["fairness_mismatch"] >= 1

    # restore, then non-finite metric
    _fabricate_run(tmp_path, keys[4], matrix)
    _fabricate_run(tmp_path, keys[1], matrix, mae=float("inf"))
    verdict = validate_formal_results(matrix, tmp_path, protocols={"cmapss_fd001"})
    assert verdict["nonfinite"] >= 1

    # restore, then wrong test count
    _fabricate_run(tmp_path, keys[1], matrix)
    _fabricate_run(tmp_path, keys[0], matrix, test_count=0)
    verdict = validate_formal_results(matrix, tmp_path, protocols={"cmapss_fd001"})
    assert verdict["test_count_errors"] >= 1
