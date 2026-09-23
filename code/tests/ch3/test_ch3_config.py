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


def _valid_values(**overrides):
    values = {
        "experiment_id": "ch3_test",
        "dataset": "metropt3_chrono_502030",
        "model": "kst_light",
        "seed": 2026,
        "split_seed": 2026,
        "mask_seed": 2026,
        "history_len": 168,
        "pred_len": 24,
        "stride": 60,
        "missing_mode": "mixed",
        "target_missing_rate": 0.30,
        "epochs": 50,
        "batch_size": 128,
        "hidden_dim": 64,
        "head_type": "mlp",
        "run_level": "formal",
        "max_train_batches": None,
        "max_eval_batches": None,
    }
    values.update(overrides)
    return values


@pytest.mark.parametrize(
    "overrides",
    [
        {"seed": 2029},
        {"seed": 2026.0},
        {"dataset": []},
        {"missing_mode": []},
        {"target_missing_rate": 1.01},
        {"head_type": "cnn"},
        {"run_level": "release"},
        {"history_len": 0},
        {"pred_len": 0},
        {"stride": 0},
    ],
)
def test_invalid_scientific_values_are_rejected(overrides):
    with pytest.raises(ValueError):
        Ch3ExperimentConfig(**_valid_values(**overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"epochs": 1},
        {"max_train_batches": 1},
        {"max_eval_batches": 1},
        {"split_seed": 2027},
    ],
)
def test_formal_config_rejects_short_or_truncated_runs(overrides):
    with pytest.raises(ValueError):
        Ch3ExperimentConfig(**_valid_values(**overrides))


def test_yaml_loads_tracked_formal_configs_and_merges_overrides():
    project_root = Path(__file__).resolve().parents[3]
    configs = [
        project_root / "configs" / "ch3" / "metropt_main.yaml",
        project_root / "configs" / "ch3" / "fd004_external.yaml",
        project_root / "configs" / "ch3" / "tep_external.yaml",
    ]

    loaded = [from_yaml(path) for path in configs]
    override = loaded[0].with_overrides({"seed": 2027, "mask_seed": 2027})

    assert [config.run_level for config in loaded] == ["formal", "formal", "formal"]
    assert [config.dataset for config in loaded] == [
        "metropt3_chrono_502030",
        "cmapss_fd004",
        "tep",
    ]
    assert override.seed == 2027
    assert override.to_dict()["mask_seed"] == 2027


def test_tuning_config_explicitly_disallows_test_loader_construction():
    config = Ch3ExperimentConfig(**_valid_values(run_level="tuning", epochs=15))

    assert not config.allows_test_loader
