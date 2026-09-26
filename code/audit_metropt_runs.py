#!/usr/bin/env python
"""V2-CH3-SINGLE-T00: MetroPT legacy single-seed run auditor.

Walks the formal MetroPT scan roots (``results/pilot/metropt3/runs`` and the
H2 archive ``archive/h2_pilot_kst_light_v2/runs``), re-derives a
``reuse|rerun|exclude`` decision for every run directory from its manifest
against the authoritative frozen contract (V2-LITE-T05 recipe + formal run
level + Conda environment + clean git identity), and writes
``metropt_single_seed_audit.json``. Metrics JSON files are never modified.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

AUDIT_SCHEMA = "metropt-single-seed-audit-v1"

SCAN_ROOTS = (
    Path("results/pilot/metropt3/runs"),
    Path("archive/h2_pilot_kst_light_v2/runs"),
)


@dataclass(frozen=True)
class AuditContract:
    """The frozen authoritative contract a run must satisfy to be reusable."""

    model_id: str
    head_type: str
    window: tuple
    seeds: dict
    run_level: str
    required_conditions: frozenset
    test_evaluation_count: int
    environment_hint: str
    #: Placeholder for a future stable code fingerprint; the current code
    #: fingerprint changes with every commit, so reuse requires a *clean* git
    #: provenance rather than a byte-identical fingerprint.
    registry_code_fingerprint: str = ""
    #: Documented runtime environment for runs whose manifests predate the
    #: environment field (H2 was produced by the legacy torch23 venv, Python
    #: 3.9.21 — progress 2026-09-20). Used both as audit evidence and to
    #: assign the legacy_venv_artifact eligibility the plan requires.
    documented_environment: str = ""


@dataclass
class _Decision:
    decision: str = "reuse"
    reasons: list = field(default_factory=list)

    def fail(self, decision: str, reason: str) -> None:
        # exclude is terminal: a run judged outside the audit scope can never
        # be downgraded back to rerun by a later check
        if self.decision == "exclude":
            self.reasons.append(reason)
            return
        self.decision = decision
        self.reasons.append(reason)


def _canonical_condition(key: str) -> str:
    parts = [part for part in key.split("|") if part]
    return parts[-2] if len(parts) >= 2 else ""


def audit_run_directory(run_dir: Path, contract: AuditContract, environment: str = "") -> dict:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.is_file():
        return {
            "run_id": run_dir.name,
            "decision": "exclude",
            "reasons": ["no manifest.json"],
            "commit": None,
            "protocol_split_sha256": None,
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    decision = _Decision()
    provenance = manifest.get("git_provenance") or {}

    if manifest.get("model_id") != contract.model_id:
        decision.fail("exclude", f"model_id={manifest.get('model_id')!r} is not the audited ours model")
    if manifest.get("family") == "baseline":
        decision.fail(
            "exclude",
            "baseline reference outside this audit: baseline formal references must "
            "be produced under the frozen authoritative matrix, not reused from "
            "pre-freeze pilot infrastructure",
        )
    if manifest.get("head_type") != contract.head_type:
        decision.fail(
            "rerun",
            f"head_type={manifest.get('head_type')!r} differs from the frozen "
            f"{contract.head_type!r} contract",
        )
    if manifest.get("run_level") != contract.run_level:
        decision.fail(
            "rerun",
            f"run_level={manifest.get('run_level')!r} is not {contract.run_level!r}",
        )
    window = (manifest.get("history_len"), manifest.get("pred_len"), manifest.get("stride"))
    if tuple(window) != contract.window:
        decision.fail("rerun", f"window={window} differs from the frozen contract {contract.window}")
    for name, expected in contract.seeds.items():
        if manifest.get(name) != expected:
            decision.fail("rerun", f"seed drift: {name}={manifest.get(name)!r} != {expected}")
    condition = manifest.get("condition_id") or _canonical_condition(manifest.get("run_id", ""))
    if condition not in contract.required_conditions:
        decision.fail("rerun", f"condition {condition!r} is outside the six registered conditions")
    if manifest.get("test_evaluation_count") != contract.test_evaluation_count:
        decision.fail(
            "rerun",
            f"test_evaluation_count={manifest.get('test_evaluation_count')!r} != "
            f"{contract.test_evaluation_count}",
        )
    if provenance and provenance.get("clean") is False:
        decision.fail(
            "rerun",
            f"dirty git provenance (commit {provenance.get('commit_sha')}, "
            f"{provenance.get('dirty_file_count')} dirty files): run identity is not "
            "reproducible from a clean checkout",
        )
    manifest_env = manifest.get("environment") or ""
    runtime_env = manifest_env or environment or contract.documented_environment
    eligibility = "eligible" if decision.decision == "reuse" else "failed"
    if contract.environment_hint and runtime_env and runtime_env != contract.environment_hint:
        decision.fail(
            "rerun",
            f"environment {runtime_env!r} is not the contract environment "
            f"{contract.environment_hint!r}",
        )
        if not manifest_env:
            # runs without an environment field inherit the documented one;
            # a legacy venv origin is exactly the legacy_venv_artifact case
            eligibility = "legacy_venv_artifact"
    if manifest.get("matrix_sha256") is None:
        decision.fail(
            "rerun",
            "manifest predates the authoritative matrix (no matrix_sha256): the run "
            "is not bound to the frozen ch3_lite_freeze_v1 recipe",
        )

    protocol_sha = manifest.get("protocol_sha") or {}
    history_path = run_dir / "history.json"
    epochs = None
    if history_path.is_file():
        history = json.loads(history_path.read_text(encoding="utf-8"))
        epochs = len(history)

    # artifact integrity: recompute on-disk SHAs against the manifest chain.
    # Manifest artifact paths are result-root-relative from the run's original
    # location; archived runs were moved whole, so each artifact is resolved
    # by basename inside the run directory (verifies content survived the
    # relocation untouched).
    import hashlib as _hashlib

    artifacts_intact = True
    artifacts = manifest.get("artifacts") or {}
    artifact_shas = manifest.get("artifact_sha256") or {}
    for name, relative in artifacts.items():
        artifact_path = run_dir / Path(str(relative)).name
        if not artifact_path.is_file():
            artifacts_intact = False
            continue
        if name in artifact_shas and _hashlib.sha256(
            artifact_path.read_bytes()
        ).hexdigest() != artifact_shas[name]:
            artifacts_intact = False
    checkpoint_sha = manifest.get("checkpoint_sha256")
    if checkpoint_sha and artifact_shas.get("checkpoint") != checkpoint_sha:
        artifacts_intact = False
    return {
        "run_id": manifest.get("run_id") or run_dir.name,
        "decision": decision.decision,
        "reasons": decision.reasons,
        "model_id": manifest.get("model_id"),
        "head_type": manifest.get("head_type"),
        "run_level": manifest.get("run_level"),
        "condition_id": condition,
        "window": list(window),
        "seed": manifest.get("seed"),
        "split_seed": manifest.get("split_seed"),
        "mask_seed": manifest.get("mask_seed"),
        "test_evaluation_count": manifest.get("test_evaluation_count"),
        "commit": provenance.get("commit_sha"),
        "git_clean": provenance.get("clean"),
        "code_fingerprint": manifest.get("code_fingerprint"),
        "device": manifest.get("device"),
        "epochs": epochs,
        "protocol_split_sha256": protocol_sha.get("split_sha256"),
        "protocol_mask_sha": protocol_sha.get("mask_sha"),
        "environment": runtime_env or None,
        "environment_source": (
            "manifest" if manifest_env else
            ("documented" if contract.documented_environment else None)
        ),
        "eligibility": eligibility,
        "checkpoint_sha256": checkpoint_sha,
        "artifacts_integrity": "intact" if artifacts_intact else "tampered_or_missing",
        "artifact_path": str(run_dir),
    }


def build_audit_document(scan_root: Path, contract: AuditContract, environment: str = "") -> dict:
    runs = []
    if scan_root.is_dir():
        for run_dir in sorted(scan_root.iterdir()):
            if not run_dir.is_dir():
                continue
            runs.append(audit_run_directory(run_dir, contract, environment=environment))
    counts = {"reuse": 0, "rerun": 0, "exclude": 0}
    for record in runs:
        counts[record["decision"]] += 1

    by_condition: dict = {}
    for record in runs:
        by_condition.setdefault(record["condition_id"], []).append(record)
    conditions_with_baselines = [
        condition
        for condition, records in sorted(by_condition.items())
        if any(record["model_id"] != contract.model_id for record in records)
    ]
    ours_by_condition = {
        condition: sum(
            1 for record in records if record["model_id"] == contract.model_id
            and record["decision"] == "reuse"
        )
        for condition, records in by_condition.items()
    }
    baseline_gap = not conditions_with_baselines
    conclusion = "ready" if (counts["reuse"] > 0 and not baseline_gap) else (
        "rerun_required" if runs else "no_runs_found"
    )
    return {
        "schema": AUDIT_SCHEMA,
        "contract": {
            "model_id": contract.model_id,
            "head_type": contract.head_type,
            "run_level": contract.run_level,
            "window": list(contract.window),
            "seeds": dict(contract.seeds),
            "required_conditions": sorted(contract.required_conditions),
            "environment_hint": contract.environment_hint,
        },
        "decision_counts": counts,
        "baseline_reference_gap": baseline_gap,
        "conditions_with_full_baseline_reference": conditions_with_baselines,
        "reusable_ours_runs_by_condition": ours_by_condition,
        "conclusion": conclusion,
        "metrics_not_modified": True,
        "runs": runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="MetroPT legacy single-seed audit (V2-CH3-SINGLE-T00)")
    parser.add_argument("--output", default="plan/metropt_single_seed_audit.json")
    args = parser.parse_args()

    from kaf_profiti.experiments.formal_matrix import load_formal_matrix

    repo_root = Path(__file__).resolve().parents[1]
    matrix = load_formal_matrix(repo_root / "configs" / "ch3" / "point_matrix.yaml")
    ours = next(model for model in matrix.models if model["family"] == "ours")
    arch = ours["architecture"]
    conditions = {
        condition["condition_id"]
        for block in matrix.protocols.values()
        if block["dataset"] == "metropt3_chrono_502030_v2"
        for condition in block["conditions"]
    }
    contract = AuditContract(
        model_id=ours["model_id"],
        head_type=ours["head_type"],
        window=(168, 24, 60),
        seeds={name: matrix.seeds[name] for name in ("seed", "split_seed", "mask_seed")},
        run_level="formal",
        required_conditions=frozenset(conditions),
        test_evaluation_count=1,
        environment_hint="kst_probflow",
        registry_code_fingerprint="",
    )

    merged_runs = []
    document = None
    for scan_root in SCAN_ROOTS:
        run_contract = contract
        if "archive/h2_pilot_kst_light_v2" in str(scan_root):
            # documented fact (progress 2026-09-20/09-23): the H2 runs were
            # produced by the legacy torch23 venv (Python 3.9.21), not the
            # kst_probflow Conda contract environment
            run_contract = AuditContract(
                **{**contract.__dict__,
                   "documented_environment": "torch23_venv_legacy"}
            )
        document = build_audit_document(repo_root / scan_root, run_contract)
        merged_runs.extend(document["runs"])

    counts = {"reuse": 0, "rerun": 0, "exclude": 0}
    for record in merged_runs:
        counts[record["decision"]] += 1
    conditions_with_baselines = sorted({
        record["condition_id"] for record in merged_runs
        if record["model_id"] != contract.model_id
    })
    conclusion = "ready" if (counts["reuse"] > 0 and not conditions_with_baselines) else (
        "rerun_required" if merged_runs else "no_runs_found"
    )
    output = {
        "schema": AUDIT_SCHEMA,
        "audited_at": "2026-09-26",
        "scan_roots": [str(root) for root in SCAN_ROOTS],
        "contract": document["contract"],
        "decision_counts": counts,
        "baseline_reference_gap": not conditions_with_baselines,
        "conditions_with_full_baseline_reference": conditions_with_baselines,
        "conclusion": conclusion,
        "metrics_not_modified": True,
        "runs": merged_runs,
    }
    out_path = repo_root / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    eligibility_counts: dict = {}
    for record in merged_runs:
        eligibility_counts[record.get("eligibility")] = (
            eligibility_counts.get(record.get("eligibility"), 0) + 1
        )
    print(json.dumps({
        "event": "metropt-single-seed-audit",
        "runs": len(merged_runs),
        "decision_counts": counts,
        "eligibility_counts": eligibility_counts,
        "conclusion": conclusion,
        "artifact": str(out_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
