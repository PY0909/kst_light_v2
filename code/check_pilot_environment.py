#!/usr/bin/env python
"""Dataset-profile pilot environment preflight checker.

Records the machine-independent identity of a pilot execution environment —
git commit, dataset file SHAs, tracked matrix SHAs, protocol mask-bundle
SHAs, code fingerprint, dependency versions — alongside the machine-specific
section (Python/torch/CUDA/GPU/disk). On machines without a GPU (e.g. the
AutoDL no-GPU boot mode) the GPU fields are recorded as null and the report
still succeeds; pass ``--require-gpu`` for the final preflight that gates
P04/P05. ``--compare`` checks two reports agree on every identity section
while ignoring environment names and resolved paths.

The report is written to ``<result-root>/pilot/<profile>/environment/<name>-preflight.json``
(result-root relative artifact; never written back into tracked YAML).
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Optional

from kaf_profiti.experiments.masks import TIMELINE_MASK_SCHEMA_VERSION
from kaf_profiti.experiments.pilot_runner import PROFILE_DATASETS

sys.path.insert(0, str(Path(__file__).resolve().parent))

_SCHEMA = "pilot-environment-preflight-v2"
_FD004_FILES = ("train_FD004.txt", "test_FD004.txt", "RUL_FD004.txt")
_METROPT_FILE = "metropt+3+dataset/MetroPT3(AirCompressor).csv"
_DEPENDENCIES = ("torch", "numpy", "pandas", "pyyaml", "pytest", "scikit-learn")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def matrix_sha256(path: Path) -> str:
    return _sha256_file(Path(path))


def git_state(repo_root: Path) -> Dict[str, object]:
    """Commit identity and dirty status; AutoDL must run one clean commit."""

    def _git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments], cwd=str(repo_root), capture_output=True, text=True
        )
        if completed.returncode != 0:
            raise RuntimeError(f"git {' '.join(arguments)} failed: {completed.stderr.strip()}")
        return completed.stdout.strip()

    commit_sha = _git("rev-parse", "HEAD")
    porcelain = _git("status", "--porcelain")
    dirty_files = porcelain.splitlines() if porcelain else []
    return {
        "commit_sha": commit_sha,
        "clean": not dirty_files,
        "dirty_file_count": len(dirty_files),
        "dirty_files": dirty_files[:50],
    }


def code_fingerprint(repo_root: Path) -> Dict[str, object]:
    """Use the exact code + compare_code identity used by pilot resume."""

    from kaf_profiti.experiments.pilot_runner import _code_fingerprint

    files = []
    for root_name in ("code", "compare_code"):
        root = Path(repo_root) / root_name
        if root.exists():
            files.extend(
                path for path in root.rglob("*.py") if "__pycache__" not in path.parts
            )
    return {
        "file_count": len(files),
        "package_sha256": _code_fingerprint(Path(repo_root)),
        "source_roots": ["code", "compare_code"],
    }


def gpu_section() -> Dict[str, object]:
    import torch

    cuda_available = bool(torch.cuda.is_available())
    section: Dict[str, object] = {
        "cuda_available": cuda_available,
        "torch_version": torch.__version__,
        "cuda_version": None,
        "gpu_name": None,
        "gpu_memory_total_mb": None,
        "gpu_count": 0,
    }
    if cuda_available:
        section["cuda_version"] = torch.version.cuda
        section["gpu_count"] = torch.cuda.device_count()
        section["gpu_name"] = torch.cuda.get_device_name(0)
        section["gpu_memory_total_mb"] = int(
            torch.cuda.get_device_properties(0).total_memory / (1024 * 1024)
        )
    return section


def dataset_section(data_root: Path, profile: str = "fd004") -> Dict[str, object]:
    files: Dict[str, object] = {}
    if profile == "fd004":
        for name in _FD004_FILES:
            relative = f"CMAPSSData/{name}"
            path = data_root / relative
            if not path.exists():
                raise FileNotFoundError(f"FD004 raw file missing under data root: {path}")
            files[relative] = {
                "sha256": _sha256_file(path),
                "bytes": path.stat().st_size,
            }
    elif profile == "metropt3":
        path = data_root / _METROPT_FILE
        if not path.exists():
            raise FileNotFoundError(f"MetroPT raw file missing under data root: {path}")
        files[_METROPT_FILE] = {
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
        }
    else:
        raise ValueError(f"unknown pilot profile: {profile!r}")
    return {"files": files}


def dependency_section() -> Dict[str, object]:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version

    section: Dict[str, object] = {}
    for package in _DEPENDENCIES:
        try:
            section[package] = version(package)
        except PackageNotFoundError:
            section[package] = None
    return section


def matrix_section(repo_root: Path, profile: str = "fd004") -> Dict[str, str]:
    if profile not in PROFILE_DATASETS:
        raise ValueError(f"unknown pilot profile: {profile!r}")
    config_dir = repo_root / "configs" / "pilot" / profile
    return {
        "point_matrix": matrix_sha256(config_dir / "point_matrix.yaml"),
        "probabilistic_matrix": matrix_sha256(config_dir / "probabilistic_matrix.yaml"),
    }


def _center_protocol_provider(
    repo_root: Path, data_root: Path, result_root: Path, profile: str
):
    from kaf_profiti.experiments.pilot_runner import RealProtocolProvider, load_matrix

    matrix = load_matrix(
        repo_root / "configs" / "pilot" / profile / "point_matrix.yaml"
    )
    raw = matrix.raw
    condition = next(
        condition
        for condition in raw["conditions"]
        if condition["missing_mode"] == "mixed"
        and abs(float(condition["target_missing_rate"]) - 0.30) <= 1e-12
    )
    provider = RealProtocolProvider(
        data_root=data_root,
        result_root=result_root,
        dataset=raw["dataset"],
        history_len=raw["history_len"],
        pred_len=raw["pred_len"],
        stride=raw["stride"],
        mechanism=condition["missing_mode"],
        requested_rate=condition["target_missing_rate"],
        mask_seed=raw["mask_seed"],
        split_seed=raw["split_seed"],
        pilot_root=f"pilot/{profile}",
    )
    return matrix, condition, provider


def protocol_section(
    result_root: Path,
    profile: str = "fd004",
    repo_root: Optional[Path] = None,
    data_root: Optional[Path] = None,
) -> Dict[str, object]:
    """Fingerprint active masks and the data-derived MetroPT protocol identity."""

    mask_root = result_root / "pilot" / profile / "protocol" / "masks"
    fingerprint = None
    if profile == "metropt3":
        if repo_root is None or data_root is None:
            raise ValueError("MetroPT protocol identity requires repo_root and data_root")
        _, _, provider = _center_protocol_provider(
            Path(repo_root), Path(data_root), Path(result_root), profile
        )
        fingerprint = provider.protocol_fingerprint()
    bundles: Dict[str, str] = {}
    if mask_root.is_dir():
        # Bundles are schema-versioned in their filenames. Only the active
        # schema participates in cross-machine identity; stale artifacts from
        # an incompatible protocol revision are deliberately ignored.
        active_prefix = f"v{TIMELINE_MASK_SCHEMA_VERSION}_"
        candidates = sorted(mask_root.rglob(f"{active_prefix}*.npz"))
        content_sha_by_name = None
        if fingerprint is not None:
            content_sha_by_name = {
                (
                    f"v{TIMELINE_MASK_SCHEMA_VERSION}_{split}_"
                    f"{fingerprint['mechanism']}_"
                    f"{float(fingerprint['requested_rate']):.2f}_"
                    f"seed{int(fingerprint['mask_seed'])}.npz"
                ): fingerprint["mask_sha"][split]
                for split in ("train", "valid", "test")
            }
            candidates = [
                path for path in candidates
                if path.name in content_sha_by_name
                and path.parent.name == PROFILE_DATASETS[profile]
            ]
        for path in candidates:
            bundles[path.relative_to(result_root).as_posix()] = (
                content_sha_by_name[path.name]
                if content_sha_by_name is not None else _sha256_file(path)
            )
    section: Dict[str, object] = {"mask_bundles": bundles}
    if fingerprint is not None:
        identity_fields = (
            "raw_data_sha256",
            "partition_sha256",
            "timeline_sha256",
            "window_catalog_sha256",
            "normalization_sha256",
            "time_scale_sha256",
            "target_schema_sha256",
            "evaluator",
            "split_sha256",
        )
        section["dataset_identity"] = {
            field: fingerprint[field] for field in identity_fields
        }
        section["mask_sha"] = fingerprint["mask_sha"]
        section["realized_rate"] = fingerprint["realized_rate"]
        section["condition"] = {
            "mechanism": fingerprint["mechanism"],
            "requested_rate": fingerprint["requested_rate"],
            "mask_seed": fingerprint["mask_seed"],
        }
    return section


def disk_section(root: Path) -> Dict[str, object]:
    usage = shutil.disk_usage(root)
    return {"path_parent": str(root), "free_gb": round(usage.free / (1024**3), 2),
            "total_gb": round(usage.total / (1024**3), 2)}


def single_batch_smoke(
    repo_root: Path,
    data_root: Path,
    result_root: Path,
    profile: str = "fd004",
) -> Dict[str, object]:
    """One baseline, one batch: device + data link only, never test metrics."""

    import torch

    from kaf_profiti.experiments.pilot_runner import (
        build_model,
    )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    matrix, condition, provider = _center_protocol_provider(
        repo_root, data_root, result_root, profile
    )
    raw = matrix.raw
    # The plan pins the environment smoke to LI+TCN specifically; selecting
    # "the first baseline" would silently drift if the matrix were reordered.
    first_model = next(
        (model for model in raw["models"] if model["model_id"] == "li_tcn"), None
    )
    if first_model is None:
        raise ValueError("point matrix does not register li_tcn for the environment smoke")
    spec = SimpleNamespace(
        model_id=first_model["model_id"],
        head_type=first_model.get("head_type", ""),
        track="point",
        pred_len=int(raw["pred_len"]),
        hidden_dim=int(raw["hidden_dim"]),
        batch_size=int(raw["batch_size"]),
        seed=int(raw["seed"]),
        mask_seed=int(raw["mask_seed"]),
        split_seed=int(raw["split_seed"]),
    )
    torch.manual_seed(raw["seed"])
    model = build_model(
        spec,
        provider.num_sensors,
        provider.context_dim,
        provider.model_options,
        device=device,
    )
    from torch.utils.data import DataLoader

    from kaf_profiti.industrial.batch import IndustrialCollator

    batch = next(iter(DataLoader(
        provider.datasets()["train"],
        batch_size=spec.batch_size,
        shuffle=False,
        collate_fn=IndustrialCollator(),
    )))
    batch = _batch_to_device(batch, device)
    before = [value.detach().clone() for value in model.parameters()]
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
    start = time.perf_counter()
    optimizer.zero_grad()
    loss = model.loss(batch)
    loss_finite = bool(torch.isfinite(loss))
    loss.backward()
    optimizer.step()
    elapsed = time.perf_counter() - start
    params_changed = any(
        not torch.equal(previous, current.detach())
        for previous, current in zip(before, list(model.parameters()))
    )
    return {
        "model_id": spec.model_id,
        "condition_id": condition["condition_id"],
        "mechanism": condition["missing_mode"],
        "requested_rate": float(condition["target_missing_rate"]),
        "device": device,
        "ok": bool(loss_finite and params_changed),
        "loss_finite": loss_finite,
        "params_changed": params_changed,
        "batch_time_sec": elapsed,
        "test_metric_count": 0,
    }


def _batch_to_device(batch, device: str):
    if device != "cuda":
        return batch
    import torch

    moved = {}
    for key, value in batch.__dict__.items():
        moved[key] = value.to(device) if torch.is_tensor(value) else value
    return type(batch)(**moved)


def build_report(
    repo_root: Path,
    data_root: Path,
    result_root: Path,
    environment: str,
    include_smoke: bool = False,
    profile: str = "fd004",
) -> Dict[str, object]:
    import platform

    repo_root = Path(repo_root)
    if profile not in PROFILE_DATASETS:
        raise ValueError(f"unknown pilot profile: {profile!r}")
    # The smoke must run before the protocol section is captured: on a
    # just-provisioned machine it generates the active-schema mask bundles,
    # and the report must fingerprint what the smoke itself created.
    environment_smoke = (
        single_batch_smoke(repo_root, data_root, result_root, profile=profile)
        if include_smoke else None
    )
    report: Dict[str, object] = {
        "schema": _SCHEMA,
        "profile": profile,
        "environment": environment,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "paths": {"data_root": str(data_root), "result_root": str(result_root)},
        "git": git_state(repo_root),
        "python": {"version": platform.python_version()},
        "torch": {"version": dependency_section()["torch"]},
        "gpu": gpu_section(),
        "disk": disk_section(data_root),
        "dataset": dataset_section(Path(data_root), profile=profile),
        "dependencies": dependency_section(),
        "matrices": matrix_section(repo_root, profile=profile),
        "protocol": protocol_section(
            Path(result_root),
            profile=profile,
            repo_root=repo_root,
            data_root=Path(data_root),
        ),
        "code_fingerprint": code_fingerprint(repo_root),
        "environment_smoke": environment_smoke,
        "test_metric_count": 0,
    }
    return report


_IDENTITY_SECTIONS = ("matrices", "protocol", "code_fingerprint", "dataset")


def _drifted_leaf_paths(local_value, remote_value, prefix: str) -> list:
    """Leaf paths where two identity values disagree (dicts compared recursively)."""

    if isinstance(local_value, dict) and isinstance(remote_value, dict):
        paths = []
        for key in sorted(set(local_value) | set(remote_value)):
            child = f"{prefix}.{key}" if prefix else str(key)
            if key not in local_value or key not in remote_value:
                paths.append(f"{child} (missing on one side)")
            else:
                paths.extend(_drifted_leaf_paths(local_value[key], remote_value[key], child))
        return paths
    if local_value != remote_value:
        return [prefix or "<root>"]
    return []


def compare_reports(local: Dict[str, object], remote: Dict[str, object]) -> None:
    """Strict on identity, silent on environment names, paths, and package builds.

    Dependency versions are recorded but not compared: every pilot run executes
    inside the single AutoDL environment, so only that environment's internal
    lock (requirement.txt) matters for fairness.
    """

    drifts = []
    if local.get("schema") != remote.get("schema"):
        drifts.append(
            f"schema drift: local={local.get('schema')} remote={remote.get('schema')}"
        )
    if local.get("profile") != remote.get("profile"):
        drifts.append(
            f"profile drift: local={local.get('profile')} remote={remote.get('profile')}"
        )
    if local.get("git", {}).get("commit_sha") != remote.get("git", {}).get("commit_sha"):
        drifts.append(
            f"git commit drift: local={local.get('git', {}).get('commit_sha')} "
            f"remote={remote.get('git', {}).get('commit_sha')}"
        )
    for section in _IDENTITY_SECTIONS:
        paths = _drifted_leaf_paths(local.get(section), remote.get(section), section)
        if paths:
            drifts.append(f"{section} mismatch at: {paths}")
    assert not drifts, "environment identity drift detected:\n" + "\n".join(drifts)


def main() -> int:
    from kaf_profiti.experiments.runtime_paths import resolve_runtime_paths

    parser = argparse.ArgumentParser(description="Pilot environment preflight checker")
    parser.add_argument("--profile", choices=tuple(PROFILE_DATASETS), default="fd004")
    parser.add_argument("--environment", choices=("local", "autodl"), default="local")
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--result-root", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--smoke", action="store_true", help="run the one-baseline device smoke")
    parser.add_argument("--require-gpu", action="store_true")
    parser.add_argument("--require-clean", action="store_true")
    parser.add_argument("--compare", default=None, help="path to another preflight report")
    args = parser.parse_args()

    paths = resolve_runtime_paths(args.data_root, args.result_root, {})
    repo_root = paths.project_root
    if args.require_clean:
        assert git_state(repo_root)["clean"] is True, (
            "--require-clean set but git status contains changes"
        )
    output_dir = Path(args.output_dir) if args.output_dir else (
        paths.output_root / "pilot" / args.profile / "environment"
    )

    report = build_report(
        repo_root=repo_root,
        data_root=paths.data_root,
        result_root=paths.output_root,
        environment=args.environment,
        include_smoke=args.smoke,
        profile=args.profile,
    )

    if args.require_gpu:
        assert report["gpu"]["cuda_available"] is True, (
            "--require-gpu set but no CUDA device is visible"
        )
    if args.compare:
        other = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        local_for_compare, remote_for_compare = (
            (other, report) if other["environment"] == "local" else (report, other)
        )
        compare_reports(local_for_compare, remote_for_compare)
        report["compared_with"] = {
            "environment": other["environment"],
            "git_commit_sha": other.get("git", {}).get("commit_sha"),
            "result": "identity_sections_match",
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{args.environment}-preflight.json"
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "event": "preflight",
                "environment": args.environment,
                "profile": args.profile,
                "report": str(output_path),
                "commit_sha": report["git"]["commit_sha"],
                "clean": report["git"]["clean"],
                "cuda_available": report["gpu"]["cuda_available"],
                "dataset_files_verified": len(report["dataset"]["files"]),
                "mask_bundles_fingerprinted": len(report["protocol"]["mask_bundles"]),
                "smoke_ok": None if report["environment_smoke"] is None
                else report["environment_smoke"]["ok"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
