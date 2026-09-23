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

from kaf_profiti.experiments.pilot_runner import (  # noqa: E402
    PROFILE_DATASETS,
    SMOKE_GROUPS,
    PilotRunner,
    load_matrix,
    validate_smoke_report,
)
from kaf_profiti.experiments.runtime_paths import resolve_runtime_paths  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unified dataset-profile pilot matrix runner")
    parser.add_argument("--profile", choices=tuple(PROFILE_DATASETS), default="fd004")
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


def main() -> int:
    args = parse_args()
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
