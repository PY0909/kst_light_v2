"""CH34-S02-T02/T03: MetroPT-3 Chapter 3/4 matrix contracts.

The tracked MetroPT point matrix must expand to exactly 42 unique scientific
keys (5 baselines + 2 KST-Light heads, each on 6 preregistered history
conditions) and the probabilistic matrix to exactly 7 (6 baselines + KST
ProbFlow on the single center condition mixed@0.30). Both share the frozen
MetroPT protocol (chronological 50/20/30 via ``metropt3_chrono_502030_v2``,
168/24/60, single seed 2026). The tests also pin the runner's expanded key
order so a matrix edit cannot silently change what the runner schedules, and
assert baseline-first ordering as the baseline-first gate requires.
"""

from pathlib import Path

import pytest
import yaml

from kaf_profiti.experiments.pilot_runner import PilotRunner, load_matrix

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
PILOT_DIR = _PROJECT_ROOT / "configs" / "pilot" / "metropt3"
COMMON_YAML = PILOT_DIR / "common.yaml"
POINT_MATRIX = PILOT_DIR / "point_matrix.yaml"
PROBABILISTIC_MATRIX = PILOT_DIR / "probabilistic_matrix.yaml"
DATASET = "metropt3_chrono_502030_v2"

EXPECTED_POINT_MODELS = [
    ("li_tcn", "linear"),
    ("ff_gru", "linear"),
    ("masked_tcn", "linear"),
    ("gru_d", "linear"),
    ("ode_rnn", "linear"),
    ("kst_light", "linear"),
    ("kst_light", "mlp"),
]
EXPECTED_PROB_MODELS = [
    "tcn_gaussian",
    "patchtst_gaussian",
    "gru_d_gaussian",
    "ode_rnn_gaussian",
    "grafiti_gaussian",
    "profiti",
    "kst_probflow",
]
EXPECTED_CONDITION_IDS = [
    "point_random_000",
    "point_random_030",
    "point_random_070",
    "point_low_rate_030",
    "point_block_offline_030",
    "point_mixed_030",
]
EXPECTED_CONDITIONS = [
    ("random", 0.00, {"intensity"}),
    ("random", 0.30, {"intensity", "mechanism"}),
    ("random", 0.70, {"intensity"}),
    ("low_rate", 0.30, {"mechanism"}),
    ("block_offline", 0.30, {"mechanism"}),
    ("mixed", 0.30, {"mechanism"}),
]
FROZEN_FIELDS = {
    "dataset": DATASET,
    "seed": 2026,
    "split_seed": 2026,
    "mask_seed": 2026,
    "history_len": 168,
    "pred_len": 24,
    "stride": 60,
    "epochs": 50,
    "batch_size": 128,
    "hidden_dim": 64,
}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _runner(matrix_path: Path = POINT_MATRIX) -> PilotRunner:
    return PilotRunner([load_matrix(matrix_path)], _PROJECT_ROOT / "result", profile="metropt3")


def _canonical_ids() -> set:
    return {spec.condition_id for spec in _runner().expand()}


def test_common_yaml_pins_frozen_metropt_protocol():
    common = _load(COMMON_YAML)
    point = _load(POINT_MATRIX)

    assert common["run_level"] == "pilot"
    for field, expected in FROZEN_FIELDS.items():
        assert common[field] == expected, field
        assert point[field] == expected, field
    assert common["model"] == "kst_light_v2"
    assert common["max_train_batches"] is None and common["max_eval_batches"] is None


def test_point_matrix_expands_exactly_42_unique_keys():
    runner = _runner()
    specs = runner.expand()

    assert len(specs) == 42
    assert len({spec.key for spec in specs}) == 42
    assert {(spec.model_id, spec.head_type) for spec in specs} == set(EXPECTED_POINT_MODELS)
    assert len({spec.condition_id for spec in specs}) == 6
    assert {spec.condition_id for spec in specs} == set(EXPECTED_CONDITION_IDS)


def test_point_matrix_registers_five_baselines_and_two_ours_heads():
    models = sorted(_load(POINT_MATRIX)["models"], key=lambda entry: entry["priority"])

    baselines = [entry for entry in models if entry["family"] == "baseline"]
    ours = [entry for entry in models if entry["family"] == "ours"]
    assert [(entry["model_id"], entry["head_type"]) for entry in baselines] == [
        ("li_tcn", "linear"),
        ("ff_gru", "linear"),
        ("masked_tcn", "linear"),
        ("gru_d", "linear"),
        ("ode_rnn", "linear"),
    ]
    assert [entry["head_type"] for entry in ours] == ["linear", "mlp"]
    assert all(entry["model_id"] == "kst_light" for entry in ours)
    assert max(entry["priority"] for entry in baselines) < min(
        entry["priority"] for entry in ours
    )


def test_random_030_is_trained_once_and_maps_to_two_views():
    matrix = _load(POINT_MATRIX)
    conditions = matrix["conditions"]

    random_030 = [
        condition
        for condition in conditions
        if condition["missing_mode"] == "random"
        and abs(condition["target_missing_rate"] - 0.30) < 1e-9
    ]
    assert len(random_030) == 1
    assert set(random_030[0]["views"]) == {"intensity", "mechanism"}

    declared = {view: set(entries) for view, entries in matrix["views"].items()}
    assert declared["intensity"] == {"random@0.00", "random@0.30", "random@0.70"}
    assert declared["mechanism"] == {
        "random@0.30",
        "low_rate@0.30",
        "block_offline@0.30",
        "mixed@0.30",
    }
    for condition in conditions:
        signature = f"{condition['missing_mode']}@{condition['target_missing_rate']:.2f}"
        for view in condition["views"]:
            assert signature in declared[view], (signature, view)
    assert {
        (condition["missing_mode"], condition["target_missing_rate"]) for condition in conditions
    } == {(mode, rate) for mode, rate, _ in EXPECTED_CONDITIONS}


def test_expanded_key_order_is_baseline_first_and_condition_ordered():
    specs = _runner().expand()
    first_six = specs[:6]

    assert [spec.model_label for spec in first_six] == ["li_tcn|linear"] * 6
    assert [spec.condition_id for spec in first_six] == EXPECTED_CONDITION_IDS
    labels = [spec.model_label for spec in specs]
    baseline_labels = {"li_tcn|linear", "ff_gru|linear", "masked_tcn|linear",
                       "gru_d|linear", "ode_rnn|linear"}
    last_baseline = max(index for index, label in enumerate(labels) if label in baseline_labels)
    first_ours = min(index for index, label in enumerate(labels) if label == "kst_light|linear")
    assert last_baseline < first_ours
    assert labels[-6:] == ["kst_light|mlp"] * 6


def test_point_matrix_stores_no_machine_paths():
    for path in (COMMON_YAML, POINT_MATRIX):
        text = path.read_text(encoding="utf-8")
        # Literals are split so the portability scanner does not flag this test.
        for token in ("/Us" "ers/", "/ro" "ot/", "/ho" "me/", "aut" "odl", "conn" "ect."):
            assert token not in text, (path.name, token)


def test_unknown_condition_and_model_filters_are_rejected():
    runner = _runner()

    with pytest.raises(ValueError, match="unknown condition"):
        runner.dry_run(condition_ids=["point_not_registered"])
    with pytest.raises(ValueError, match="unknown model"):
        runner.dry_run(model_ids=["not_a_model"])
    report = runner.dry_run(family="baseline")
    assert report["expected_total"] == 30
    assert report["canonical_total"] == 42


# ---------------------------------------------------------------------------
# CH34-S02-T03: Chapter 4 probabilistic matrix
# ---------------------------------------------------------------------------


def test_probabilistic_matrix_pins_frozen_protocol_and_center_condition():
    common = _load(COMMON_YAML)
    probabilistic = _load(PROBABILISTIC_MATRIX)

    assert probabilistic["schema_version"] == "pilot-probabilistic-matrix-v1"
    assert probabilistic["matrix_id"] == "pilot_metropt3_probabilistic"
    assert probabilistic["run_level"] == "pilot"
    for field, expected in FROZEN_FIELDS.items():
        assert probabilistic[field] == expected, field
        assert common[field] == expected, field
    assert probabilistic["interval_level"] == 0.95
    assert probabilistic["nsamples"] == 100

    conditions = probabilistic["conditions"]
    assert len(conditions) == 1, "Chapter 4 uses exactly one center condition"
    assert conditions[0]["condition_id"] == "prob_mixed_030"
    assert conditions[0]["missing_mode"] == "mixed"
    assert abs(conditions[0]["target_missing_rate"] - 0.30) < 1e-9
    assert conditions[0]["views"] == ["mechanism"]
    assert probabilistic["views"] == {"mechanism": ["mixed@0.30"]}


def test_probabilistic_matrix_registers_six_baselines_then_kst_probflow():
    models = sorted(_load(PROBABILISTIC_MATRIX)["models"], key=lambda entry: entry["priority"])

    assert [entry["model_id"] for entry in models] == EXPECTED_PROB_MODELS
    assert [entry["family"] for entry in models] == ["baseline"] * 6 + ["ours"]
    priorities = [entry["priority"] for entry in models]
    assert len(set(priorities)) == len(priorities)
    baselines = [entry["priority"] for entry in models if entry["family"] == "baseline"]
    ours = [entry["priority"] for entry in models if entry["family"] == "ours"]
    assert max(baselines) < min(ours)
    assert not any("head_type" in entry for entry in models)


def test_probabilistic_matrix_expands_exactly_seven_unique_keys():
    specs = _runner(PROBABILISTIC_MATRIX).expand()

    assert len(specs) == 7
    assert len({spec.key for spec in specs}) == 7
    assert [spec.model_id for spec in specs] == EXPECTED_PROB_MODELS
    assert {spec.track for spec in specs} == {"probabilistic"}
    assert {spec.dataset for spec in specs} == {DATASET}
    assert {spec.condition_id for spec in specs} == {"prob_mixed_030"}
    assert {spec.seed for spec in specs} == {2026}
    assert (specs[0].history_len, specs[0].pred_len, specs[0].stride) == (168, 24, 60)
    assert specs[-1].family == "ours"
    assert specs[-1].key.startswith(f"{DATASET}|probabilistic|kst_probflow|")


def test_probabilistic_dry_run_reports_seven_new_runs():
    report = _runner(PROBABILISTIC_MATRIX).dry_run()

    assert report["profile"] == "metropt3"
    assert report["canonical_total"] == 7
    assert report["expected_total"] == 7
    assert report["expected_new"] == 7
    assert len(report["keys"]) == 7
    assert len(set(report["keys"])) == 7
    assert report["model_order"] == EXPECTED_PROB_MODELS
    assert all("prob_mixed_030" in key for key in report["keys"])


def test_point_and_probabilistic_keys_never_collide():
    point_keys = {spec.key for spec in _runner(POINT_MATRIX).expand()}
    prob_keys = {spec.key for spec in _runner(PROBABILISTIC_MATRIX).expand()}

    assert not point_keys & prob_keys
    assert len(point_keys | prob_keys) == 49
    assert all("|point|" in key for key in point_keys)
    assert all("|probabilistic|" in key for key in prob_keys)


def test_probabilistic_matrix_stores_no_machine_paths():
    text = PROBABILISTIC_MATRIX.read_text(encoding="utf-8")
    for token in ("/Us" "ers/", "/ro" "ot/", "/ho" "me/", "aut" "odl", "conn" "ect."):
        assert token not in text, token
