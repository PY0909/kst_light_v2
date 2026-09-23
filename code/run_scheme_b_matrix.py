#!/usr/bin/env python
"""Run the versioned Scheme B matrices without changing legacy pilot matrices."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kaf_profiti.experiments.pilot_runner import (  # noqa: E402
    PilotRunner,
    SMOKE_GROUPS,
    load_matrix,
    validate_smoke_report,
)
from kaf_profiti.experiments.runtime_paths import resolve_runtime_paths  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATHS = {
    "point": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_matrix.yaml",
    "point_a1": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_a1_matrix.yaml",
    "point_a2": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_a2_matrix.yaml",
    "point_a3": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_a3_matrix.yaml",
    "point_a4": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_a4_matrix.yaml",
    "point_a5": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_a5_matrix.yaml",
    "point_a6": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_a6_matrix.yaml",
    "point_f1": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_f1_matrix.yaml",
    "point_f2": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_f2_matrix.yaml",
    "point_f3": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_f3_matrix.yaml",
    "point_g1": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_g1_gru_mixer_h16_matrix.yaml",
    "point_g2": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_g2_gru_mixer_h32_matrix.yaml",
    "point_g3": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_g3_gru_mixer_no_ffill_matrix.yaml",
    "point_g4": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_g4_gru_mixer_direct_residual_matrix.yaml",
    "point_m1": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_m1_missing_sensor_mixer_l1_matrix.yaml",
    "point_m2": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_m2_missing_sensor_mixer_l2_matrix.yaml",
    "point_m2_tune_lr1e4_ep80": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_m2_tune_lr1e4_ep80_matrix.yaml",
    "point_m2_tune_lr3e4_ep50": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_m2_tune_lr3e4_ep50_matrix.yaml",
    "point_m2_tune_lr3e4_cosine_ep80": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_m2_tune_lr3e4_cosine_ep80_matrix.yaml",
    "point_m2_tune_lr3e4_cosine_ep80_remaining5": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_m2_tune_lr3e4_cosine_ep80_remaining5_matrix.yaml",
    "point_m2_tune_lr3e4_cosine_ep80_all6": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_m2_tune_lr3e4_cosine_ep80_all6_matrix.yaml",
    "point_m3": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_m3_missing_sensor_mixer_relation_matrix.yaml",
    "point_m4": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_point_m4_missing_sensor_mixer_age_matrix.yaml",
    "probabilistic": REPO_ROOT / "configs" / "pilot" / "metropt3" / "scheme_b_probabilistic_matrix.yaml",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Scheme B versioned pilot matrix runner")
    parser.add_argument("--matrix", choices=tuple(MATRIX_PATHS) + ("all",), default="all")
    parser.add_argument("--mode", choices=("dry-run", "smoke", "full", "sanity"), default="dry-run")
    parser.add_argument("--group", choices=tuple(SMOKE_GROUPS), default=None)
    parser.add_argument("--model-id", action="append", default=None)
    parser.add_argument("--family", choices=("baseline", "ours"), default=None)
    parser.add_argument("--condition-id", action="append", default=None)
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--result-root", default=None)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--num-workers", default="auto")
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument(
        "--max-batches",
        type=int,
        default=0,
        help="sanity-only cap for train/valid batches; 0 uses the full split",
    )
    parser.add_argument("--force-rerun", action="store_true")
    progress = parser.add_mutually_exclusive_group()
    progress.add_argument("--progress", dest="progress", action="store_true")
    progress.add_argument("--no-progress", dest="progress", action="store_false")
    parser.set_defaults(progress=None)
    return parser.parse_args()


def _matrices(selection):
    names = ("point", "probabilistic") if selection == "all" else (selection,)
    return [load_matrix(MATRIX_PATHS[name]) for name in names]


def main() -> int:
    args = parse_args()
    paths = resolve_runtime_paths(args.data_root, args.result_root, {})
    runner = PilotRunner(
        matrices=_matrices(args.matrix),
        result_root=str(paths.output_root),
        data_root=str(paths.data_root),
        device=args.device,
        num_workers=args.num_workers,
        profile="metropt3",
    )
    if args.mode == "dry-run":
        payload = runner.dry_run(
            family=args.family,
            condition_ids=args.condition_id,
            model_ids=args.model_id,
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    if args.mode == "smoke":
        groups = [args.group] if args.group else ["ours"]
        for group in groups:
            report = runner.run_smoke(group=group)
            counts = validate_smoke_report(report, expected_ready=runner.smoke_expected(group))
            print(json.dumps({"event": "smoke", "group": group, **counts}, ensure_ascii=False, indent=2))
        return 0
    if args.mode == "sanity":
        model_ids = args.model_id or ["kst_light_v2"]
        for model_id in model_ids:
            manifest = runner.run_sanity_train(
                model_id=model_id, epochs=args.epochs, max_batches=args.max_batches,
                show_progress=args.progress,
            )
            print(json.dumps({"event": "sanity", **manifest}, ensure_ascii=False, indent=2))
        return 0
    result = runner.execute(
        family=args.family,
        condition_ids=args.condition_id,
        model_ids=args.model_id,
        force_rerun=args.force_rerun,
        show_progress=args.progress,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
