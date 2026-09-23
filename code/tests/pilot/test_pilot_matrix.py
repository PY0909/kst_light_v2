"""CH2.5-P00-T02: pilot matrix expansion, counting and consistency tests."""

from pathlib import Path

import yaml


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
PILOT_DIR = _PROJECT_ROOT / "configs" / "pilot" / "fd004"
COMMON_YAML = PILOT_DIR / "common.yaml"
POINT_MATRIX = PILOT_DIR / "point_matrix.yaml"
PROBABILISTIC_MATRIX = PILOT_DIR / "probabilistic_matrix.yaml"

EXPECTED_POINT_MODELS = [
    ("li_tcn", "linear"),
    ("ff_gru", "linear"),
    ("masked_tcn", "linear"),
    ("gru_d", "linear"),
    ("ode_rnn", "linear"),
    ("kst_light", "linear"),
    ("kst_light", "mlp"),
]
EXPECTED_POINT_CONDITIONS = [
    ("random", 0.00, {"intensity"}),
    ("random", 0.30, {"intensity", "mechanism"}),
    ("random", 0.70, {"intensity"}),
    ("low_rate", 0.30, {"mechanism"}),
    ("block_offline", 0.30, {"mechanism"}),
    ("mixed", 0.30, {"mechanism"}),
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
SHARED_FIXED_FIELDS = (
    "dataset",
    "seed",
    "split_seed",
    "mask_seed",
    "history_len",
    "pred_len",
    "stride",
    "epochs",
    "batch_size",
    "hidden_dim",
)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def expand(matrix: dict) -> list[dict]:
    """Expand a tracked pilot matrix into ordered scientific rows."""

    rows = []
    for model in sorted(matrix["models"], key=lambda entry: entry["priority"]):
        for condition in matrix["conditions"]:
            rows.append(
                {
                    "model_id": model["model_id"],
                    "head_type": model.get("head_type", "-"),
                    "family": model["family"],
                    "priority": model["priority"],
                    "condition_id": condition["condition_id"],
                    "missing_mode": condition["missing_mode"],
                    "target_missing_rate": condition["target_missing_rate"],
                    "views": tuple(condition["views"]),
                }
            )
    return rows


def scientific_key(row: dict) -> str:
    return "|".join(
        (
            row["model_id"],
            row["head_type"],
            row["missing_mode"],
            f"{row['target_missing_rate']:.2f}",
        )
    )


def dry_run_summary() -> dict[str, int]:
    point_rows = expand(_load(POINT_MATRIX))
    prob_rows = expand(_load(PROBABILISTIC_MATRIX))
    all_rows = point_rows + prob_rows
    keys = [scientific_key(row) for row in all_rows]
    return {
        "point": len(point_rows),
        "probabilistic": len(prob_rows),
        "total": len(all_rows),
        "duplicate": len(keys) - len(set(keys)),
    }


def test_point_matrix_expands_exactly_42_unique_rows():
    rows = expand(_load(POINT_MATRIX))
    keys = [scientific_key(row) for row in rows]

    assert len(rows) == 42
    assert len(set(keys)) == 42
    assert {(row["model_id"], row["head_type"]) for row in rows} == set(
        EXPECTED_POINT_MODELS
    )
    assert {
        (row["missing_mode"], row["target_missing_rate"]) for row in rows
    } == {(mode, rate) for mode, rate, _ in EXPECTED_POINT_CONDITIONS}


def test_random_030_is_one_condition_mapped_to_two_views():
    matrix = _load(POINT_MATRIX)
    conditions = matrix["conditions"]

    assert len(conditions) == 6
    random_030 = [
        condition
        for condition in conditions
        if condition["missing_mode"] == "random"
        and abs(condition["target_missing_rate"] - 0.30) < 1e-9
    ]
    assert len(random_030) == 1
    assert set(random_030[0]["views"]) == {"intensity", "mechanism"}

    view_rows = expand(matrix)
    intensity_rows = [row for row in view_rows if "intensity" in row["views"]]
    mechanism_rows = [row for row in view_rows if "mechanism" in row["views"]]
    assert len(intensity_rows) == 21  # 7 model configs x 3 intensity conditions
    assert len(mechanism_rows) == 28  # 7 model configs x 4 mechanism conditions
    assert len(view_rows) == 42  # random@0.30 trained once per model config


def test_point_matrix_conditions_match_declared_views():
    matrix = _load(POINT_MATRIX)
    declared = {
        view: set(entries) for view, entries in matrix["views"].items()
    }

    for condition in matrix["conditions"]:
        signature = (
            f"{condition['missing_mode']}@{condition['target_missing_rate']:.2f}"
        )
        for view in condition["views"]:
            assert signature in declared[view], (signature, view)
    assert set(declared["intensity"]) == {
        "random@0.00",
        "random@0.30",
        "random@0.70",
    }
    assert set(declared["mechanism"]) == {
        "random@0.30",
        "low_rate@0.30",
        "block_offline@0.30",
        "mixed@0.30",
    }


def test_point_models_are_baseline_first_with_unique_priorities():
    matrix = _load(POINT_MATRIX)
    models = sorted(matrix["models"], key=lambda entry: entry["priority"])

    assert [(entry["model_id"], entry["head_type"]) for entry in models] == [
        EXPECTED_POINT_MODELS
    ][0]
    priorities = [entry["priority"] for entry in models]
    assert len(set(priorities)) == len(priorities)
    baseline_priorities = [
        entry["priority"] for entry in models if entry["family"] == "baseline"
    ]
    ours_priorities = [
        entry["priority"] for entry in models if entry["family"] == "ours"
    ]
    assert max(baseline_priorities) < min(ours_priorities)
    assert len(baseline_priorities) == 5 and len(ours_priorities) == 2


def test_probabilistic_matrix_expands_7_rows_baseline_first_ours_last():
    matrix = _load(PROBABILISTIC_MATRIX)
    rows = expand(matrix)

    assert len(rows) == 7
    assert [row["model_id"] for row in rows] == EXPECTED_PROB_MODELS
    assert [row["family"] for row in rows] == ["baseline"] * 6 + ["ours"]
    assert rows[-1]["model_id"] == "kst_probflow"
    assert all(
        rows[i]["priority"] < rows[i + 1]["priority"] for i in range(len(rows) - 1)
    )
    assert all(
        row["missing_mode"] == "mixed"
        and abs(row["target_missing_rate"] - 0.30) < 1e-9
        for row in rows
    )


def test_dry_run_counts_are_point_42_probabilistic_7_total_49_duplicate_0():
    assert dry_run_summary() == {
        "point": 42,
        "probabilistic": 7,
        "total": 49,
        "duplicate": 0,
    }


def test_matrices_share_common_yaml_fixed_parameters_and_pilot_identity():
    common = _load(COMMON_YAML)
    point = _load(POINT_MATRIX)
    probabilistic = _load(PROBABILISTIC_MATRIX)

    for matrix in (point, probabilistic):
        assert matrix["run_level"] == "pilot"
        assert matrix["seed"] == 2026
        assert matrix["split_seed"] == 2026
        assert matrix["mask_seed"] == 2026
        for field in SHARED_FIXED_FIELDS:
            assert matrix[field] == common[field], field


def test_matrices_store_no_machine_paths_or_absolute_paths():
    for path in (POINT_MATRIX, PROBABILISTIC_MATRIX):
        text = path.read_text(encoding="utf-8")
        # Literals are split so the portability scanner does not flag this test.
        for token in ("/Us" "ers/", "/ro" "ot/", "/ho" "me/", "aut" "odl", "conn" "ect."):
            assert token not in text, (path.name, token)


if __name__ == "__main__":
    summary = dry_run_summary()
    print(
        "pilot matrix dry-run: "
        f"point={summary['point']}, "
        f"probabilistic={summary['probabilistic']}, "
        f"total={summary['total']}, "
        f"duplicate={summary['duplicate']}"
    )
