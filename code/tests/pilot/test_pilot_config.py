"""CH2.5-P00-T01: pilot config schema tests (FD004 single-seed pre-experiments)."""

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_config_module():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "kaf_profiti"
        / "experiments"
        / "ch3"
        / "config.py"
    )
    spec = importlib.util.spec_from_file_location("ch3_config_under_test", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load Chapter 3 config module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_config_module = _load_config_module()
Ch3ExperimentConfig = _config_module.Ch3ExperimentConfig
from_yaml = _config_module.from_yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
PILOT_COMMON_YAML = _PROJECT_ROOT / "configs" / "pilot" / "fd004" / "common.yaml"


def _pilot_values(**overrides):
    values = {
        "experiment_id": "pilot_fd004_common",
        "dataset": "cmapss_fd004",
        "model": "kst_light",
        "seed": 2026,
        "split_seed": 2026,
        "mask_seed": 2026,
        "history_len": 50,
        "pred_len": 10,
        "stride": 1,
        "missing_mode": "mixed",
        "target_missing_rate": 0.30,
        "epochs": 80,
        "batch_size": 128,
        "hidden_dim": 64,
        "head_type": "mlp",
        "run_level": "pilot",
        "max_train_batches": None,
        "max_eval_batches": None,
    }
    values.update(overrides)
    return values


def test_pilot_run_level_loads_tracked_common_yaml():
    config = from_yaml(PILOT_COMMON_YAML)

    assert config.run_level == "pilot"
    assert config.dataset == "cmapss_fd004"
    assert config.split_seed == 2026
    assert (config.history_len, config.pred_len, config.stride) == (50, 10, 1)
    assert config.max_train_batches is None
    assert config.max_eval_batches is None


def test_pilot_identity_is_distinct_from_smoke_and_formal():
    pilot = Ch3ExperimentConfig(**_pilot_values())
    smoke = Ch3ExperimentConfig(**_pilot_values(run_level="smoke", epochs=1))
    formal = Ch3ExperimentConfig(
        **_pilot_values(
            dataset="metropt3_chrono_502030",
            history_len=168,
            pred_len=24,
            stride=60,
            run_level="formal",
        )
    )

    assert {pilot.run_level, smoke.run_level, formal.run_level} == {
        "pilot",
        "smoke",
        "formal",
    }
    assert pilot.is_formal_evidence is False
    assert smoke.is_formal_evidence is False
    assert formal.is_formal_evidence is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_train_batches", 2),
        ("max_eval_batches", 2),
        ("max_train_batches", 1),
        ("max_eval_batches", 1),
    ],
)
def test_pilot_rejects_truncated_loaders(field, value):
    with pytest.raises(ValueError):
        Ch3ExperimentConfig(**_pilot_values(**{field: value}))


@pytest.mark.parametrize(
    "overrides",
    [
        {"dataset": "metropt3_chrono_502030"},
        {"dataset": "tep"},
        {"split_seed": 2027},
        {"history_len": 168},
        {"pred_len": 24},
        {"stride": 60},
        {"epochs": 1},
    ],
)
def test_pilot_fixes_dataset_split_seed_windows_and_full_training(overrides):
    with pytest.raises(ValueError):
        Ch3ExperimentConfig(**_pilot_values(**overrides))


def test_pilot_rejects_runtime_scientific_overrides_but_allows_seed_identity():
    config = Ch3ExperimentConfig(**_pilot_values())

    with pytest.raises(ValueError):
        config.with_overrides({"missing_mode": "random"})
    with pytest.raises(ValueError):
        config.with_overrides({"dataset": "tep"})
    with pytest.raises(ValueError):
        config.with_overrides({"history_len": 168})

    adjusted = config.with_overrides({"seed": 2027, "mask_seed": 2027})
    assert (adjusted.seed, adjusted.mask_seed) == (2027, 2027)


def test_pilot_yaml_schema_rejects_engine_subset_and_unknown_keys(tmp_path):
    text = PILOT_COMMON_YAML.read_text(encoding="utf-8")
    lines = text.splitlines()
    lines.append("engine_subset: [1, 2, 3]")
    broken = tmp_path / "broken_common.yaml"
    broken.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        from_yaml(broken)


def test_pilot_common_yaml_stores_no_machine_paths():
    text = PILOT_COMMON_YAML.read_text(encoding="utf-8")
    # Literals are split so the portability scanner does not flag this test line.
    forbidden_fragments = ("/Us" "ers/", "/ro" "ot/", "/ho" "me/", "aut" "odl", "conn" "ect.")
    for token in forbidden_fragments:
        assert token not in text

    fields = set(Ch3ExperimentConfig.__dataclass_fields__)
    assert not any("root" in field or "path" in field for field in fields)
