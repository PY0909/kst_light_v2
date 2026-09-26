"""V2-CH3-SINGLE-T00: MetroPT legacy single-seed run auditor.

The auditor walks every MetroPT run directory under the formal scan roots
(``results/pilot/metropt3/runs`` plus the H2 archive), re-derives the
reuse/rerun/exclude decision from the manifest against the authoritative
frozen contract, and emits ``metropt_single_seed_audit.json`` with per-run
decisions and the missing-baseline-reference finding.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "code"))

from audit_metropt_runs import (  # noqa: E402
    AuditContract,
    audit_run_directory,
    build_audit_document,
)


def _write_run(root: Path, key: str, manifest_overrides: dict, *,
               metrics_overrides: dict | None = None,
               epochs: int = 80, files=("manifest.json",)) -> Path:
    run_dir = root / key
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "status": "completed",
        "run_level": "pilot",
        "run_id": key,
        "matrix": "point_matrix",
        "matrix_sha256": None,
        "track": "point",
        "model_id": "kst_light_v2",
        "head_type": "residual",
        "family": "ours",
        "variant_id": "m2_tune_lr3e4_cosine_ep80",
        "seed": 2026,
        "split_seed": 2026,
        "mask_seed": 2026,
        "dataset": "metropt3_chrono_502030_v2",
        "history_len": 168,
        "pred_len": 24,
        "stride": 60,
        "test_evaluation_count": 1,
        "device": "cuda",
        "code_fingerprint": "deadbeef",
        "git_provenance": {"commit_sha": "29a04d74", "clean": False, "dirty_file_count": 7},
        "protocol_sha": {"split_sha256": "eb7b957c"},
    }
    manifest.update(manifest_overrides)
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if "metrics.json" in files or "all":
        metrics = {"mae": 0.25, "rmse": 0.5, "parameter_count": 240218}
        metrics.update(metrics_overrides or {})
        (run_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
        files = tuple(files) + ("metrics.json",)
    history = [{"epoch": e, "valid_mae": 0.4 - e * 0.001} for e in range(1, epochs + 1)]
    (run_dir / "history.json").write_text(json.dumps(history), encoding="utf-8")
    return run_dir


CONTRACT = AuditContract(
    model_id="kst_light_v2",
    head_type="mlp",
    window=(168, 24, 60),
    seeds={"seed": 2026, "split_seed": 2026, "mask_seed": 2026},
    run_level="formal",
    required_conditions={
        "point_mixed_030", "point_random_000", "point_random_030",
        "point_random_070", "point_low_rate_030", "point_block_offline_030",
    },
    test_evaluation_count=1,
    environment_hint="kst_probflow",
    registry_code_fingerprint="whatever",
)


def test_residual_head_h2_run_is_rerun(tmp_path: Path):
    key = ("metropt3_chrono_502030_v2|point|kst_light_v2|m2_tune_lr3e4_cosine_ep80"
           "|residual|point_mixed_030|2026")
    _write_run(tmp_path, key, {})
    record = audit_run_directory(tmp_path / key, CONTRACT)
    assert record["decision"] == "rerun"
    reasons = " ".join(record["reasons"])
    assert "head_type" in reasons       # residual != frozen mlp contract
    assert "run_level" in reasons       # pilot != formal
    assert "matrix_sha256" in reasons   # not bound to the frozen authoritative matrix
    assert record["protocol_split_sha256"] == "eb7b957c"


def test_baseline_model_cannot_reuse_as_ours(tmp_path: Path):
    key = "metropt3_chrono_502030_v2|point|li_tcn|linear|point_mixed_030|2026"
    _write_run(tmp_path, key, {
        "model_id": "li_tcn", "head_type": "linear", "family": "baseline",
        "run_level": "formal", "git_provenance": {"commit_sha": "84f96bc", "clean": True},
        "code_fingerprint": CONTRACT.registry_code_fingerprint,
    })
    record = audit_run_directory(tmp_path / key, CONTRACT)
    assert record["decision"] == "exclude"
    assert "baseline reference outside this audit" in " ".join(record["reasons"])


def test_formal_contract_compliant_run_is_reusable(tmp_path: Path):
    key = ("metropt3_chrono_502030_v2|point|kst_light_v2|mlp|point_mixed_030|2026")
    manifest_overrides = {
        "run_level": "formal",
        "head_type": "mlp",
        "git_provenance": {"commit_sha": "84f96bc", "clean": True},
        "code_fingerprint": CONTRACT.registry_code_fingerprint,
        "environment": "kst_probflow",
        "matrix_sha256": "frozen-matrix-sha",  # bound to the authoritative matrix
    }
    _write_run(tmp_path, key, manifest_overrides)
    record = audit_run_directory(tmp_path / key, CONTRACT, environment="kst_probflow")
    assert record["decision"] == "reuse"
    assert record["reasons"] == []


def test_dirty_git_or_wrong_environment_downgrades_to_rerun(tmp_path: Path):
    key = "metropt3_chrono_502030_v2|point|kst_light_v2|mlp|point_mixed_030|2026"
    base = {"run_level": "formal", "head_type": "mlp", "environment": "torch23"}
    _write_run(tmp_path, key + "_env", base)
    record = audit_run_directory(tmp_path / (key + "_env"), CONTRACT, environment="kst_probflow")
    assert record["decision"] == "rerun"
    assert "environment" in " ".join(record["reasons"])

    _write_run(tmp_path, key + "_dirty", {
        "run_level": "formal", "head_type": "mlp", "environment": "kst_probflow",
        "git_provenance": {"commit_sha": "29a04d74", "clean": False, "dirty_file_count": 7},
    })
    record = audit_run_directory(tmp_path / (key + "_dirty"), CONTRACT, environment="kst_probflow")
    assert record["decision"] == "rerun"
    assert "dirty" in " ".join(record["reasons"])


def test_condition_and_seed_drift_flagged(tmp_path: Path):
    key = "metropt3_chrono_502030_v2|point|kst_light_v2|mlp|point_random_042|2027"
    _write_run(tmp_path, key, {
        "run_level": "formal", "head_type": "mlp", "seed": 2027, "mask_seed": 2027,
        "condition_id": "point_random_042",
    })
    record = audit_run_directory(tmp_path / key, CONTRACT)
    reasons = " ".join(record["reasons"])
    assert "condition" in reasons and "seed" in reasons


def test_build_audit_document_reports_baseline_gap(tmp_path: Path):
    key = ("metropt3_chrono_502030_v2|point|kst_light_v2|m2_tune_lr3e4_cosine_ep80"
           "|residual|point_mixed_030|2026")
    _write_run(tmp_path, key, {})
    document = build_audit_document(tmp_path, CONTRACT, environment="kst_probflow")
    assert document["schema"] == "metropt-single-seed-audit-v1"
    assert document["decision_counts"] == {"reuse": 0, "rerun": 1, "exclude": 0}
    assert document["baseline_reference_gap"] is True
    assert document["conditions_with_full_baseline_reference"] == []
    assert document["conclusion"] == "rerun_required"
    assert document["runs"][0]["run_id"] == key
    assert "metrics_not_modified" in document
