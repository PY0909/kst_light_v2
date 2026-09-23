"""CH2.5-P03-T05: pilot environment preflight checker tests.

The checker records the machine-independent identity (git commit, dataset
file SHAs, matrix SHAs, protocol mask-bundle SHAs, code fingerprint,
dependency versions) plus the machine-specific section (Python/torch/CUDA/
GPU/disk). Cross-machine comparison must be strict on the identity sections
and ignore environment and resolved paths. GPU fields stay null on machines
without CUDA (e.g. the no-GPU AutoDL mode) without failing the report.
"""

import copy
import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

check_pilot_environment = importlib.import_module("check_pilot_environment")

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATA_ROOT = Path(__import__("os").environ.get("KST_DATA_ROOT", _REPO_ROOT / "dataset"))
_FD004_READY = (_DATA_ROOT / "CMAPSSData" / "train_FD004.txt").exists() and (
    _DATA_ROOT / "CMAPSSData" / "test_FD004.txt"
).exists()
_METROPT_READY = (
    _DATA_ROOT / "metropt+3+dataset" / "MetroPT3(AirCompressor).csv"
).exists()

_requires_fd004 = pytest.mark.skipif(
    not _FD004_READY, reason="FD004 raw files not available under KST_DATA_ROOT"
)
_requires_metropt = pytest.mark.skipif(
    not _METROPT_READY, reason="MetroPT raw file not available under KST_DATA_ROOT"
)


def _build_report(**kwargs):
    return check_pilot_environment.build_report(
        repo_root=_REPO_ROOT,
        data_root=_DATA_ROOT,
        result_root=kwargs.pop("result_root", _REPO_ROOT / "result"),
        environment=kwargs.pop("environment", "local"),
        profile=kwargs.pop("profile", "fd004"),
        **kwargs,
    )


def test_report_records_git_dataset_matrices_protocol_and_code_identity():
    report = _build_report()

    assert report["schema"] == "pilot-environment-preflight-v2"
    assert report["profile"] == "fd004"
    assert len(report["git"]["commit_sha"]) == 40
    assert isinstance(report["git"]["clean"], bool)

    dataset = report["dataset"]["files"]
    for name in ("train_FD004.txt", "test_FD004.txt", "RUL_FD004.txt"):
        assert len(dataset[f"CMAPSSData/{name}"]["sha256"]) == 64
        assert dataset[f"CMAPSSData/{name}"]["bytes"] > 0

    assert report["matrices"]["point_matrix"] == check_pilot_environment.matrix_sha256(
        _REPO_ROOT / "configs" / "pilot" / "fd004" / "point_matrix.yaml"
    )
    assert len(report["code_fingerprint"]["package_sha256"]) == 64

    assert report["dependencies"]["torch"], "torch version must be recorded"
    assert report["python"]["version"]
    assert "free_gb" in report["disk"]


@_requires_metropt
def test_metropt_report_records_raw_matrix_and_full_protocol_identity(tmp_path):
    report = _build_report(profile="metropt3", result_root=tmp_path / "result")

    raw = report["dataset"]["files"][
        "metropt+3+dataset/MetroPT3(AirCompressor).csv"
    ]
    assert len(raw["sha256"]) == 64 and raw["bytes"] > 0
    assert report["matrices"]["point_matrix"] == check_pilot_environment.matrix_sha256(
        _REPO_ROOT / "configs" / "pilot" / "metropt3" / "point_matrix.yaml"
    )
    identity = report["protocol"]["dataset_identity"]
    for field in (
        "raw_data_sha256",
        "partition_sha256",
        "timeline_sha256",
        "window_catalog_sha256",
        "normalization_sha256",
        "time_scale_sha256",
        "target_schema_sha256",
        "evaluator",
    ):
        assert identity[field]
    assert set(report["protocol"]["realized_rate"]) == {"train", "valid", "test"}
    bundles = report["protocol"]["mask_bundles"]
    assert len(bundles) == 3
    assert all("_mixed_0.30_seed2026.npz" in path for path in bundles)
    assert sorted(bundles.values()) == sorted(report["protocol"]["mask_sha"].values())


def test_protocol_mask_bundles_are_recorded_when_present():
    report = _build_report()
    bundles = report["protocol"]["mask_bundles"]
    # Preflight must only fingerprint active-schema artifacts; on a fresh or
    # protocol-migrated result root there may be none before the first smoke.
    for relative, sha in bundles.items():
        assert "cmapss_fd004" in relative and "/v3_" in relative and len(sha) == 64


def test_gpu_section_stays_null_without_cuda(monkeypatch):
    torch = pytest.importorskip("torch")
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)

    section = check_pilot_environment.gpu_section()

    assert section["cuda_available"] is False
    assert section["gpu_name"] is None
    assert section["gpu_memory_total_mb"] is None
    assert section["cuda_version"] is None


def test_compare_accepts_copies_and_ignores_environment_and_paths():
    report = _build_report()
    twin = copy.deepcopy(report)
    twin["environment"] = "autodl"
    twin["paths"] = {"data_root": "/data/remote-box/dataset", "result_root": "/data/remote-box/result"}
    twin["git"]["clean"] = not report["git"]["clean"]

    check_pilot_environment.compare_reports(report, twin)


def test_compare_flags_identity_drift():
    report = _build_report()

    drifted = copy.deepcopy(report)
    drifted["matrices"]["point_matrix"] = "0" * 64
    with pytest.raises(AssertionError, match="point_matrix"):
        check_pilot_environment.compare_reports(report, drifted)

    drifted = copy.deepcopy(report)
    drifted["git"]["commit_sha"] = "f" * 40
    with pytest.raises(AssertionError, match="commit"):
        check_pilot_environment.compare_reports(report, drifted)

    drifted = copy.deepcopy(report)
    drifted["dataset"]["files"]["CMAPSSData/train_FD004.txt"]["sha256"] = "1" * 64
    with pytest.raises(AssertionError, match="train_FD004"):
        check_pilot_environment.compare_reports(report, drifted)

    drifted = copy.deepcopy(report)
    drifted["profile"] = "metropt3"
    with pytest.raises(AssertionError, match="profile"):
        check_pilot_environment.compare_reports(report, drifted)

    metro_identity = {
        "dataset_identity": {"time_scale_sha256": "a" * 64},
        "mask_bundles": {},
    }
    local = copy.deepcopy(report)
    remote = copy.deepcopy(report)
    local["protocol"] = copy.deepcopy(metro_identity)
    remote["protocol"] = copy.deepcopy(metro_identity)
    remote["protocol"]["dataset_identity"]["time_scale_sha256"] = "b" * 64
    with pytest.raises(AssertionError, match="time_scale_sha256"):
        check_pilot_environment.compare_reports(local, remote)


@_requires_fd004
def test_single_batch_smoke_verifies_device_link_without_test_metrics(tmp_path):
    # A fresh result root: the smoke itself must generate the v3 mask bundles
    # and the report must record them, so a just-provisioned machine (AutoDL
    # before its first training run) produces a comparable protocol section.
    report = _build_report(include_smoke=True, result_root=tmp_path / "result")

    smoke = report["environment_smoke"]
    assert smoke["ok"] is True
    assert smoke["model_id"] == "li_tcn"
    assert smoke["loss_finite"] is True
    assert smoke["params_changed"] is True
    assert smoke["test_metric_count"] == 0
    assert smoke["device"] in ("cpu", "cuda")
    bundles = report["protocol"]["mask_bundles"]
    assert bundles, "smoke-generated v3 bundles must be fingerprinted in the same report"
    assert all("/v3_" in relative for relative in bundles)


@_requires_metropt
def test_metropt_single_batch_smoke_uses_center_condition_without_test_metrics(tmp_path):
    smoke = check_pilot_environment.single_batch_smoke(
        _REPO_ROOT, _DATA_ROOT, tmp_path / "result", profile="metropt3"
    )

    assert smoke["model_id"] == "li_tcn"
    assert smoke["condition_id"] == "point_mixed_030"
    assert smoke["mechanism"] == "mixed"
    assert smoke["requested_rate"] == pytest.approx(0.30)
    assert smoke["test_metric_count"] == 0
    assert smoke["ok"] is True


@_requires_fd004
def test_cli_writes_parseable_preflight_report(tmp_path):
    output_dir = tmp_path / "environment"
    completed = subprocess.run(
        [
            sys.executable,
            str(_REPO_ROOT / "code" / "check_pilot_environment.py"),
            "--environment", "local",
            "--output-dir", str(output_dir),
        ],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]

    report = json.loads((output_dir / "local-preflight.json").read_text(encoding="utf-8"))
    assert report["schema"] == "pilot-environment-preflight-v2"
    assert report["git"]["commit_sha"]


@_requires_metropt
def test_cli_profile_metropt_writes_profile_report(tmp_path):
    output_dir = tmp_path / "environment"
    completed = subprocess.run(
        [
            sys.executable,
            str(_REPO_ROOT / "code" / "check_pilot_environment.py"),
            "--profile", "metropt3",
            "--environment", "local",
            "--output-dir", str(output_dir),
        ],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    assert completed.returncode == 0, completed.stderr[-2000:]
    report = json.loads((output_dir / "local-preflight.json").read_text(encoding="utf-8"))
    assert report["profile"] == "metropt3"
    assert report["protocol"]["dataset_identity"]["raw_data_sha256"]
