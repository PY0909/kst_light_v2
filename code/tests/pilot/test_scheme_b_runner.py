import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

torch = pytest.importorskip("torch")

from kaf_profiti.experiments.pilot_runner import PilotRunner, load_matrix


ROOT = Path(__file__).resolve().parents[3]


def test_scheme_b_matrices_expand_to_versioned_models_only(tmp_path):
    matrices = [
        load_matrix(ROOT / "configs/pilot/metropt3/scheme_b_point_matrix.yaml"),
        load_matrix(ROOT / "configs/pilot/metropt3/scheme_b_probabilistic_matrix.yaml"),
    ]
    runner = PilotRunner(
        matrices,
        result_root=tmp_path / "result",
        data_root=ROOT / "dataset",
        device="cpu",
        profile="metropt3",
    )
    specs = runner.expand()
    assert {spec.model_id for spec in specs} == {"kst_light_v2", "kst_flow_v2"}
    assert len(specs) == 2


def test_scheme_b_dry_run_cli_emits_versioned_key(tmp_path):
    result_root = tmp_path / "result"
    command = [
        sys.executable,
        str(ROOT / "code/run_scheme_b_matrix.py"),
        "--matrix",
        "point",
        "--mode",
        "dry-run",
        "--data-root",
        str(ROOT / "dataset"),
        "--result-root",
        str(result_root),
    ]
    completed = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    payload = json.loads(completed.stdout)
    assert payload["canonical_total"] == 1
    assert payload["keys"][0].split("|")[2] == "kst_light_v2"


def test_scheme_b_missing_static_recipe_fails_before_provider_loading(tmp_path):
    source = ROOT / "configs/pilot/metropt3/scheme_b_point_matrix.yaml"
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["models"][0].pop("cross_variable_mode")
    path = tmp_path / "invalid_scheme_b.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="cross_variable_mode"):
        load_matrix(path)
