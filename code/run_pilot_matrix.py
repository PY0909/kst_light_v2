#!/usr/bin/env python
"""CLI for the dataset-profile pilot matrix runner.

Modes:
  dry-run  ordered scientific keys, model order, shared artifact SHAs,
           expected new-training count (default; writes nothing)
  smoke    one-batch per-model validation for a group; never produces test metrics
  sanity   validation-only short training per requested model (--model-id,
           default li_tcn); never touches the test split
  full     full train/validation/test pilot runs with baseline-first gating

All roots resolve through ``resolve_runtime_paths`` (CLI flag, then
``KST_DATA_ROOT``/``KST_RESULT_ROOT``, then repository-relative defaults).
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kaf_profiti.experiments.formal_matrix import (  # noqa: E402
    AUTHORITATIVE_MATRICES,
    FormalMatrix,
    FormalRunKey,
    expand_formal_matrix,
    load_formal_matrix,
)
from kaf_profiti.experiments.pilot_runner import (  # noqa: E402
    PROFILE_DATASETS,
    SMOKE_GROUPS,
    PilotRunner,
    PilotRunSpec,
    RealProtocolProvider,
    _code_fingerprint,
    _loaders,
    build_model,
    load_matrix,
    pilot_train_and_evaluate,
    validate_smoke_report,
)
from kaf_profiti.experiments.runtime_paths import resolve_runtime_paths  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unified dataset-profile pilot matrix runner")
    parser.add_argument("--profile", choices=tuple(PROFILE_DATASETS), default=None)
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "authoritative formal-matrix entry (one of: "
            + ", ".join(sorted(AUTHORITATIVE_MATRICES.values()))
            + "); C0 stage supports --mode dry-run only — legacy configs/pilot "
            "matrices are historical-audit-only and are rejected"
        ),
    )
    parser.add_argument("--mode", choices=("dry-run", "smoke", "full", "sanity"), default="dry-run")
    parser.add_argument("--matrix", choices=("point", "probabilistic", "all"), default="all")
    parser.add_argument(
        "--group",
        choices=tuple(SMOKE_GROUPS),
        default=None,
        help="smoke group to execute (smoke mode only)",
    )
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--result-root", default=None)
    parser.add_argument(
        "--family", choices=("baseline", "ours"), default=None,
        help="narrow the scheduled family; scientific keys and matrix SHA are unchanged",
    )
    parser.add_argument(
        "--condition-id", action="append", default=None,
        help="narrow to a condition (repeatable); unknown ids are rejected",
    )
    parser.add_argument(
        "--model-id", action="append", default=None,
        help="narrow to a model id (repeatable); unknown ids are rejected; "
        "sanity mode trains these models (default li_tcn)",
    )
    parser.add_argument(
        "--protocol", action="append", default=None,
        help="formal --config mode: narrow to a protocol (repeatable)",
    )
    parser.add_argument(
        "--force-rerun", action="store_true",
        help="rerun scheduled runs even when their existing manifests verify",
    )
    parser.add_argument(
        "--device",
        default="auto",
        help="auto resolves to cuda when a GPU is visible, else cpu",
    )
    parser.add_argument(
        "--num-workers",
        default="auto",
        help="DataLoader worker processes; auto resolves to 4 on GPU hosts, else 0",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=5,
        help="sanity mode only: fixed train/validation epoch budget (default 5)",
    )
    return parser.parse_args()


def _load_matrices(selection: str, profile: str):
    config_dir = _REPO_ROOT / "configs" / "pilot" / profile
    paths = []
    if selection in ("point", "all"):
        paths.append(config_dir / "point_matrix.yaml")
    if selection in ("probabilistic", "all"):
        paths.append(config_dir / "probabilistic_matrix.yaml")
    return [load_matrix(path) for path in paths]


# ---------------------------------------------------------------------------
# V2-CH3-CODE-T03: formal matrix execution (baseline-first, resumable)
# ---------------------------------------------------------------------------

def _resolve_formal_workers(device, requested) -> int:
    """lite_pipeline_v1 contract: 4 workers on GPU hosts, 0 otherwise."""

    if isinstance(requested, str):
        if requested == "auto":
            return 4 if str(device) == "cuda" else 0
        return int(requested)
    return int(requested)


def _formal_profile_for(protocol: str) -> str:
    if protocol == "metropt3_chrono_502030_v2":
        return "metropt3"
    if protocol.startswith("cmapss_fd"):
        return protocol.replace("cmapss_", "")
    if protocol == "tep_faulty":
        return "tep_faulty"
    raise ValueError(f"no formal result profile for protocol {protocol!r}")


def _formal_recipe(matrix: FormalMatrix, protocol_block: dict) -> dict:
    return {**matrix.recipe, **protocol_block.get("recipe_override", {})}


def _formal_spec(key: FormalRunKey, matrix: FormalMatrix, protocol_block: dict, condition: dict) -> PilotRunSpec:
    recipe = _formal_recipe(matrix, protocol_block)
    arch = protocol_block.get("ours_architecture", {})
    return PilotRunSpec(
        key=key.scientific_key,
        track=key.track,
        matrix_name=matrix.matrix_id,
        dataset=key.protocol,
        model_id=key.model_id,
        head_type=key.head_type,
        family=key.family,
        condition_id=key.condition_id,
        missing_mode=condition["missing_mode"],
        target_missing_rate=float(condition["target_missing_rate"]),
        seed=key.seed,
        split_seed=matrix.seeds["split_seed"],
        mask_seed=matrix.seeds["mask_seed"],
        history_len=int(protocol_block["history_len"]),
        pred_len=int(protocol_block["pred_len"]),
        stride=int(protocol_block["stride"]),
        epochs=int(recipe["epochs"]),
        batch_size=int(recipe["batch_size"]),
        hidden_dim=int(arch.get("hidden_dim", 64)),
        recipe_version=matrix.recipe_version,
        cross_variable_mode=arch.get("cross_variable_mode"),
        mixer_layers=arch.get("mixer_layers"),
        mixer_relation_bias=arch.get("mixer_relation_bias"),
        mixer_relation_scale=arch.get("mixer_relation_scale"),
        mixer_freshness_scale=arch.get("mixer_freshness_scale"),
        patch_lens=tuple(arch.get("patch_lens", ())),
        freshness_tau=arch.get("freshness_tau"),
        preconv_dim=arch.get("preconv_dim"),
        kernel_count=arch.get("kernel_count"),
        n_layers=arch.get("n_layers"),
        learning_rate=float(recipe["learning_rate"]),
        weight_decay=float(recipe["weight_decay"]),
        scheduler=recipe.get("scheduler"),
        patience=recipe.get("patience"),
        grad_clip_norm=float(recipe["grad_clip_norm"]),
    )


def _provider_options(provider):
    options = provider.model_options
    return options() if callable(options) else options


def _formal_provider_factory(data_root, result_root, device, num_workers=0):
    def factory(**kwargs):
        return RealProtocolProvider(
            data_root=data_root,
            result_root=result_root,
            pilot_root=f"pilot/{_formal_profile_for(kwargs['dataset'])}",
            num_workers=int(num_workers),
            pin_memory=str(device) == "cuda",
            **kwargs,
        )

    return factory


def _default_formal_run(spec, provider, device, show_progress=None):
    import torch as _torch

    _torch.manual_seed(spec.seed)
    model = build_model(
        spec, provider.num_sensors, provider.context_dim,
        _provider_options(provider), device=device,
    )
    loaders = _loaders(provider, spec.batch_size, spec.seed)
    result = pilot_train_and_evaluate(
        model, loaders, spec, provider, device=device, show_progress=show_progress,
    )
    timing = result.get("predictions", {}).get("timing", {})
    repeats = [float(v) for v in timing.get("inference_seconds", [])]
    if repeats:
        import statistics as _stats

        result["inference_time_sec"] = _stats.median(repeats)
    return result


def _formal_manifest_path(result_root, key: FormalRunKey) -> Path:
    return (
        Path(result_root) / "pilot" / _formal_profile_for(key.protocol)
        / "runs" / key.scientific_key / "manifest.json"
    )


def _formal_run_verified(manifest_path: Path, key: FormalRunKey, matrix: FormalMatrix) -> bool:
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if manifest.get("status") != "completed" or manifest.get("run_id") != key.scientific_key:
        return False
    if manifest.get("matrix_sha256") != matrix.matrix_sha256:
        return False
    if manifest.get("test_evaluation_count") != 1:
        return False
    artifacts = manifest.get("artifacts", {})
    shas = manifest.get("artifact_sha256", {})
    if not isinstance(artifacts, dict) or not isinstance(shas, dict):
        return False
    if not {"history", "metrics", "checkpoint", "predictions"}.issubset(artifacts):
        return False
    run_dir = manifest_path.parent
    for name, relative in artifacts.items():
        path = run_dir / relative
        if not path.is_file():
            return False
        import hashlib as _hashlib

        if _hashlib.sha256(path.read_bytes()).hexdigest() != shas.get(name):
            return False
    if shas.get("checkpoint") != manifest.get("checkpoint_sha256"):
        return False
    return True


def _write_formal_run(result_root, spec: PilotRunSpec, matrix: FormalMatrix, provider, result, device) -> Path:
    import hashlib

    run_dir = Path(result_root) / "pilot" / _formal_profile_for(spec.dataset) / "runs" / spec.key
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "history.json").write_text(json.dumps(result["history"]), encoding="utf-8")
    (run_dir / "metrics.json").write_text(json.dumps(result["metrics"]), encoding="utf-8")
    (run_dir / "predictions.json").write_text(json.dumps(result["predictions"]), encoding="utf-8")
    (run_dir / "checkpoint.pt").write_bytes(result["checkpoint_bytes"])
    artifacts = {
        "history": "history.json",
        "metrics": "metrics.json",
        "checkpoint": "checkpoint.pt",
        "predictions": "predictions.json",
    }
    artifact_sha = {
        name: hashlib.sha256((run_dir / relative).read_bytes()).hexdigest()
        for name, relative in artifacts.items()
    }
    recipe = {
        "recipe_version": matrix.recipe_version,
        "selection_metric": matrix.selection_metric,
        "epochs": spec.epochs,
        "batch_size": spec.batch_size,
        "learning_rate": spec.learning_rate,
        "weight_decay": spec.weight_decay,
        "scheduler": spec.scheduler,
        "patience": spec.patience,
        "grad_clip_norm": spec.grad_clip_norm,
    }
    manifest = {
        "status": "completed",
        "run_level": "formal",
        "run_id": spec.key,
        "matrix_id": matrix.matrix_id,
        "matrix_sha256": matrix.matrix_sha256,
        "track": spec.track,
        "model_id": spec.model_id,
        "head_type": spec.head_type,
        "family": spec.family,
        "condition_id": spec.condition_id,
        "missing_mode": spec.missing_mode,
        "target_missing_rate": spec.target_missing_rate,
        "seed": spec.seed,
        "split_seed": spec.split_seed,
        "mask_seed": spec.mask_seed,
        "dataset": spec.dataset,
        "history_len": spec.history_len,
        "pred_len": spec.pred_len,
        "stride": spec.stride,
        "hidden_dim": spec.hidden_dim,
        "recipe": recipe,
        "protocol_sha": provider.protocol_fingerprint(),
        "model_class": result.get("model_class"),
        "model_config": result.get("model_config"),
        "optimizer_config": result.get("optimizer_config"),
        "training_command_hash": result.get("training_command_hash"),
        "checkpoint_selection": result.get("checkpoint_selection", "best_valid"),
        "valid_selection_score": result.get("valid_selection_score"),
        "parameter_count": result.get("predictions", {}).get("parameter_count"),
        "train_seconds": result.get("train_time_sec"),
        "inference_time_sec": result.get("inference_time_sec"),
        "artifacts": artifacts,
        "artifact_sha256": artifact_sha,
        "checkpoint_sha256": artifact_sha["checkpoint"],
        "test_evaluation_count": 1,
        "code_fingerprint": _code_fingerprint(_REPO_ROOT),
        "device": str(device),
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def _formal_execute_keys(
    matrix: FormalMatrix,
    keys,
    result_root,
    data_root,
    device,
    run_fn=None,
    provider_factory=None,
    show_progress=None,
    num_workers=None,
) -> dict:
    """Execute formal keys: baseline-first gating, verified resume, per-key
    continue-on-error, PilotRunner-shaped manifests with the formal identity."""

    run_fn = run_fn or _default_formal_run
    workers = _resolve_formal_workers(
        device, num_workers if num_workers is not None else "auto"
    )
    factory = provider_factory or _formal_provider_factory(
        data_root, result_root, device, num_workers=workers,
    )
    provider_cache: dict = {}
    summary = {
        "expected_total": len(keys),
        "executed": 0,
        "resumed": 0,
        "failed": [],
        "gate_blocked": [],
    }
    completed_groups: set = set()
    for key in keys:
        manifest_path = _formal_manifest_path(result_root, key)
        if _formal_run_verified(manifest_path, key, matrix):
            summary["resumed"] += 1
            if key.family == "baseline":
                completed_groups.add((key.protocol, key.condition_id))
            continue
        protocol_block = matrix.protocols[key.protocol]
        condition = next(
            item for item in protocol_block["conditions"]
            if item["condition_id"] == key.condition_id
        )
        spec = _formal_spec(key, matrix, protocol_block, condition)
        if key.family == "ours":
            group = (key.protocol, key.condition_id)
            if group not in completed_groups:
                summary["gate_blocked"].append(key.scientific_key)
                continue
        provider_key = (
            key.protocol, condition["missing_mode"],
            float(condition["target_missing_rate"]),
        )
        if provider_key not in provider_cache:
            provider_cache[provider_key] = factory(
                dataset=key.protocol,
                history_len=spec.history_len,
                pred_len=spec.pred_len,
                stride=spec.stride,
                mechanism=spec.missing_mode,
                requested_rate=spec.target_missing_rate,
                mask_seed=spec.mask_seed,
                split_seed=spec.split_seed,
            )
        provider = provider_cache[provider_key]
        try:
            result = run_fn(spec, provider, device)
            _write_formal_run(result_root, spec, matrix, provider, result, device)
            summary["executed"] += 1
            if key.family == "baseline":
                completed_groups.add((key.protocol, key.condition_id))
        except Exception as exc:  # noqa: BLE001 — continue-on-error per key
            summary["failed"].append(f"{key.scientific_key}: {type(exc).__name__}: {exc}")
    return summary


def _formal_smoke(matrix: FormalMatrix, keys, result_root, data_root, device, num_workers=None) -> dict:
    """One train batch + one valid forward per key; the test split is never
    loaded, no run directories are created."""

    import torch

    factory = _formal_provider_factory(
        data_root, result_root, device,
        num_workers=_resolve_formal_workers(
            device, num_workers if num_workers is not None else "auto"
        ),
    )
    provider_cache: dict = {}
    entries = []
    for key in keys:
        protocol_block = matrix.protocols[key.protocol]
        condition = next(
            item for item in protocol_block["conditions"]
            if item["condition_id"] == key.condition_id
        )
        spec = _formal_spec(key, matrix, protocol_block, condition)
        provider_key = (key.protocol, condition["missing_mode"], float(condition["target_missing_rate"]))
        if provider_key not in provider_cache:
            provider_cache[provider_key] = factory(
                dataset=key.protocol,
                history_len=spec.history_len,
                pred_len=spec.pred_len,
                stride=spec.stride,
                mechanism=spec.missing_mode,
                requested_rate=spec.target_missing_rate,
                mask_seed=spec.mask_seed,
                split_seed=spec.split_seed,
            )
        provider = provider_cache[provider_key]
        torch.manual_seed(spec.seed)
        model = build_model(
            spec, provider.num_sensors, provider.context_dim,
            _provider_options(provider), device=device,
        )
        from kaf_profiti.industrial.batch import IndustrialCollator
        from torch.utils.data import DataLoader

        collator = IndustrialCollator()
        batch = next(iter(DataLoader(provider.datasets()["train"], batch_size=spec.batch_size,
                                     shuffle=False, collate_fn=collator))).to(torch.device(device))
        before = [value.detach().clone() for value in model.parameters()]
        model.train()
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        optimizer.zero_grad()
        loss = model.loss(batch)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        params_changed = any(
            (value.detach() - prev).abs().max().item() > 0.0
            for prev, value in zip(before, model.parameters())
        )
        vbatch = next(iter(DataLoader(provider.datasets()["valid"], batch_size=spec.batch_size,
                                      shuffle=False, collate_fn=collator))).to(torch.device(device))
        model.eval()
        with torch.no_grad():
            point = model.predict_point(vbatch)
        entries.append({
            "key": key.scientific_key,
            "model_id": key.model_id,
            "protocol": key.protocol,
            "loss_finite": bool(torch.isfinite(loss).item()),
            "params_changed": bool(params_changed),
            "valid_point_finite": bool(torch.isfinite(point).all().item()),
            "test_loader_touched": False,
            "run_level": "smoke",
        })
    report = {
        "matrix_id": matrix.matrix_id,
        "entries": entries,
        "test_metric_count": 0,
    }
    report_path = Path(result_root) / "pilot" / "formal_smoke.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _formal_dry_run(config: str) -> int:
    """Authoritative-entry formal dry-run: expansion only, no instantiation."""

    try:
        matrix = load_formal_matrix(_REPO_ROOT / config if not Path(config).is_absolute() else config)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    keys = expand_formal_matrix(matrix)
    per_protocol: dict = {}
    for key in keys:
        per_protocol[key.protocol] = per_protocol.get(key.protocol, 0) + 1
    print(json.dumps(
        {
            "matrix_id": matrix.matrix_id,
            "chapter": matrix.chapter,
            "track": matrix.track,
            "matrix_sha256": matrix.matrix_sha256,
            "selection_metric": matrix.selection_metric,
            "recipe_version": matrix.recipe_version,
            "seeds": matrix.seeds,
            "model_order": [m["model_id"] for m in matrix.models],
            "planned_models": matrix.planned_model_ids,
            "instantiated_models": [],
            "expanded_keys": len(keys),
            "unique_keys": len({k.scientific_key for k in keys}),
            "keys_per_protocol": dict(sorted(per_protocol.items())),
            "test_metric_count": 0,
            "scientific_keys": [k.scientific_key for k in keys],
        },
        ensure_ascii=False, indent=2,
    ))
    return 0


def main() -> int:
    args = parse_args()
    if args.config is not None:
        if args.profile is not None:
            print(
                "--config and --profile are mutually exclusive (--config is the "
                "formal entry; --profile is the legacy audit path)",
                file=sys.stderr,
            )
            return 2
        matrix = load_formal_matrix(
            _REPO_ROOT / args.config if not Path(args.config).is_absolute() else args.config
        )
        keys = expand_formal_matrix(matrix)
        if args.protocol:
            keys = [key for key in keys if key.protocol in set(args.protocol)]
        if args.condition_id:
            keys = [key for key in keys if key.condition_id in set(args.condition_id)]
        if args.model_id:
            keys = [key for key in keys if key.model_id in set(args.model_id)]
        if args.family:
            keys = [key for key in keys if key.family == args.family]
        if args.mode == "dry-run":
            return _formal_dry_run(args.config)
        paths = resolve_runtime_paths(args.data_root, args.result_root, {})
        import torch

        formal_device = args.device if args.device != "auto" else (
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        if args.mode == "smoke":
            report = _formal_smoke(
                matrix, keys, result_root=paths.output_root, data_root=paths.data_root,
                device=formal_device, num_workers=args.num_workers,
            )
            print(json.dumps({
                "event": "formal-smoke",
                "entries": len(report["entries"]),
                "all_passed": all(
                    entry["loss_finite"] and entry["params_changed"]
                    and entry["valid_point_finite"] for entry in report["entries"]
                ),
                "test_metric_count": report["test_metric_count"],
            }, ensure_ascii=False))
            return 0
        if args.mode == "full":
            summary = _formal_execute_keys(
                matrix, keys,
                result_root=paths.output_root, data_root=paths.data_root,
                device=formal_device, num_workers=args.num_workers,
            )
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0 if not summary["failed"] and not summary["gate_blocked"] else 1
        print(
            f"--config supports dry-run/smoke/full (got {args.mode!r})",
            file=sys.stderr,
        )
        return 2
    if args.profile is None:
        args.profile = "fd004"
    paths = resolve_runtime_paths(args.data_root, args.result_root, {})
    runner = PilotRunner(
        matrices=_load_matrices(args.matrix, args.profile),
        result_root=str(paths.output_root),
        data_root=str(paths.data_root),
        device=args.device,
        num_workers=args.num_workers,
        profile=args.profile,
    )

    if args.mode == "dry-run":
        print(json.dumps(
            runner.dry_run(
                family=args.family,
                condition_ids=args.condition_id,
                model_ids=args.model_id,
            ), ensure_ascii=False, indent=2
        ))
        return 0

    if args.mode == "smoke":
        groups = [args.group] if args.group else [
            group for group in SMOKE_GROUPS if runner.smoke_expected(group) > 0
        ]
        for group in groups:
            report = runner.run_smoke(group=group)
            counts = validate_smoke_report(
                report, expected_ready=runner.smoke_expected(group)
            )
            print(
                json.dumps(
                    {"event": "smoke", "group": group, **counts, "report": str(
                        paths.output_root / "pilot" / args.profile / "smoke" / f"{group}_smoke.json"
                    )},
                    ensure_ascii=False,
                ),
                flush=True,
            )
        return 0

    if args.mode == "sanity":
        # The 2026-09-17 grad-clip revision requires the next sanity round to
        # cover ODE-RNN alongside the registered li_tcn gate model.
        gate_failed = False
        for model_id in (args.model_id or ["li_tcn"]):
            manifest = runner.run_sanity_train(epochs=args.epochs, model_id=model_id)
            print(json.dumps(manifest, ensure_ascii=False, indent=2), flush=True)
            if not all(
                manifest[flag] for flag in ("finite", "updated", "validation_improved")
            ):
                gate_failed = True
        return 1 if gate_failed else 0

    summary = runner.execute(
        family=args.family,
        condition_ids=args.condition_id,
        model_ids=args.model_id,
        force_rerun=args.force_rerun,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if not summary["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
