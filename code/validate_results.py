#!/usr/bin/env python
"""V2-CH3-CODE-T03: formal result validator for the authoritative matrices.

Scans the formal run tree (``<result-root>/pilot/<profile>/runs/<key>/``),
checks every expected expanded key for completion, identity, finite point
metrics, exactly one test evaluation, parameter/timing fields, and per-group
fairness (identical protocol fingerprint and matrix SHA across the models of
one protocol-condition group). Emits a JSON verdict; exits non-zero when any
check fails so it can gate phase transitions.
"""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kaf_profiti.experiments.formal_matrix import (  # noqa: E402
    expand_formal_matrix,
    load_formal_matrix,
)
from run_pilot_matrix import _formal_manifest_path, _formal_profile_for  # noqa: E402


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_key(key, matrix, result_root: Path):
    """Return (issues_by_category, manifest) for one expected key."""

    issues = {
        "missing": None,
        "status": None,
        "key": None,
        "test_count": None,
        "artifacts": None,
        "nonfinite": None,
        "fields": None,
    }
    manifest_path = _formal_manifest_path(result_root, key)
    if not manifest_path.is_file():
        issues["missing"] = str(manifest_path.relative_to(result_root))
        return issues, None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        issues["status"] = f"unreadable manifest: {exc}"
        return issues, None

    if manifest.get("status") != "completed":
        issues["status"] = f"status={manifest.get('status')!r}"
    if manifest.get("run_id") != key.scientific_key:
        issues["key"] = f"run_id={manifest.get('run_id')!r}"
    if manifest.get("test_evaluation_count") != 1:
        issues["test_count"] = manifest.get("test_evaluation_count")

    run_dir = manifest_path.parent
    artifacts = manifest.get("artifacts", {})
    shas = manifest.get("artifact_sha256", {})
    for name, relative in artifacts.items():
        path = run_dir / relative
        if not path.is_file():
            issues["artifacts"] = f"missing artifact {name}"
            break
        if shas.get(name) != _sha256(path):
            issues["artifacts"] = f"artifact sha mismatch {name}"
            break

    metrics_path = run_dir / "metrics.json"
    if metrics_path.is_file():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        point = metrics.get("point", {}) if isinstance(metrics, dict) else {}
        for field in ("mae", "rmse"):
            value = point.get(field)
            if value is None or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                issues["nonfinite"] = f"{field}={value!r}"
                break

    for field in ("parameter_count", "train_seconds", "inference_time_sec"):
        value = manifest.get(field)
        if not isinstance(value, (int, float)) or (isinstance(value, float) and not math.isfinite(value)):
            issues["fields"] = f"{field}={value!r}"
            break
    if not (isinstance(manifest.get("parameter_count"), int) and manifest["parameter_count"] > 0):
        issues["fields"] = f"parameter_count={manifest.get('parameter_count')!r}"

    return issues, manifest


def validate_formal_results(matrix, result_root, protocols=None) -> dict:
    """Validate the expected key set of one authoritative matrix."""

    result_root = Path(result_root)
    keys = expand_formal_results_keys(matrix, protocols)
    missing, failed = [], []
    test_count_errors = 0
    nonfinite = 0
    manifests = {}
    for key in keys:
        issues, manifest = _check_key(key, matrix, result_root)
        key_label = key.scientific_key
        if issues["missing"]:
            missing.append(key_label)
            continue
        problems = [
            f"{category}: {detail}" for category, detail in issues.items()
            if detail and category != "missing"
        ]
        if problems:
            failed.append(f"{key_label} ({'; '.join(problems)})")
        if issues["test_count"] is not None:
            test_count_errors += 1
        if issues["nonfinite"]:
            nonfinite += 1
        manifests[key_label] = manifest or {}

    fairness_mismatch = 0
    groups: dict = {}
    for key in keys:
        groups.setdefault((key.protocol, key.condition_id), []).append(key)
    for (protocol, condition_id), group_keys in groups.items():
        fingerprints = []
        matrix_shas = set()
        for key in group_keys:
            manifest = manifests.get(key.scientific_key)
            if not manifest:
                continue
            protocol_sha = manifest.get("protocol_sha") or {}
            fingerprints.append((
                protocol_sha.get("split_sha256"),
                protocol_sha.get("normalization_sha256"),
                json.dumps(protocol_sha.get("mask_sha"), sort_keys=True),
            ))
            matrix_shas.add(manifest.get("matrix_sha256"))
        if not fingerprints:
            continue
        if len(set(fingerprints)) > 1 or len(matrix_shas) > 1 or None in matrix_shas:
            fairness_mismatch += len(fingerprints)

    # every key either resolved a manifest or is missing; among resolved ones
    # only the problem-free count as completed
    completed = len(keys) - len(missing) - len(failed)
    verdict = {
        "matrix_id": matrix.matrix_id,
        "expected": len(keys),
        "completed": completed,
        "missing": missing,
        "failed": failed,
        "nonfinite": nonfinite,
        "test_count_errors": test_count_errors,
        "fairness_mismatch": fairness_mismatch,
    }
    verdict["ok"] = (
        not missing and not failed and nonfinite == 0
        and test_count_errors == 0 and fairness_mismatch == 0
    )
    return verdict


def expand_formal_results_keys(matrix, protocols=None):
    keys = expand_formal_matrix(matrix)
    if protocols:
        keys = [key for key in keys if key.protocol in set(protocols)]
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description="Formal result validator")
    parser.add_argument(
        "--config", default="configs/ch3/point_matrix.yaml",
        help="authoritative matrix entry (repo-relative or absolute)",
    )
    parser.add_argument("--result-root", default=None)
    parser.add_argument("--protocol", action="append", default=None)
    args = parser.parse_args()

    from kaf_profiti.experiments.runtime_paths import resolve_runtime_paths

    repo_root = Path(__file__).resolve().parents[1]
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = repo_root / args.config
    matrix = load_formal_matrix(config_path)
    paths = resolve_runtime_paths(None, args.result_root, {})
    verdict = validate_formal_results(
        matrix, paths.output_root,
        protocols=set(args.protocol) if args.protocol else None,
    )
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
