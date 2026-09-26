"""V2-X0-CLOSE-T03: authoritative formal-matrix schema gates and expansion.

These tests pin the three authoritative configuration entries
(configs/ch3/point_matrix.yaml, configs/ch4/probabilistic_matrix.yaml,
configs/ch5/risk_matrix.yaml): the per-chapter hard gates (baseline counts,
ours model identity, legacy-id rejection, registry cross-check), the A.1
protocol contract (six protocols, windows, condition sets), the expanded
scientific-key counts (66 / 42 / 30), and the CLI ``--config`` dry-run entry
which must refuse legacy pilot matrices and non-dry-run modes.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "code"))

from kaf_profiti.experiments.formal_matrix import (  # noqa: E402
    AUTHORITATIVE_MATRICES,
    assert_no_planned_for_execution,
    expand_formal_matrix,
    load_formal_matrix,
    validate_formal_matrix,
)
from kaf_profiti.experiments.registry import get_model_spec  # noqa: E402


def _load_dict(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _check_rejected(raw: dict) -> None:
    validate_formal_matrix(raw, raw["chapter"])


def test_three_authoritative_entries_exist_and_load() -> None:
    for chapter, rel in AUTHORITATIVE_MATRICES.items():
        path = REPO_ROOT / rel
        assert path.is_file(), f"missing authoritative entry for {chapter}: {rel}"
        matrix = load_formal_matrix(path)
        assert matrix.chapter == chapter


def test_ch3_point_matrix_expands_exactly_66_keys() -> None:
    matrix = load_formal_matrix(REPO_ROOT / AUTHORITATIVE_MATRICES["ch3"])
    keys = expand_formal_matrix(matrix)
    assert len(keys) == 66
    assert len({k.scientific_key for k in keys}) == 66
    metropt = [k for k in keys if k.protocol == "metropt3_chrono_502030_v2"]
    external = [k for k in keys if k.protocol != "metropt3_chrono_502030_v2"]
    assert len(metropt) == 36  # 6 conditions x 6 models
    assert len({k.condition_id for k in metropt}) == 6
    assert len(external) == 30  # 5 protocols x 1 condition x 6 models
    assert {k.protocol for k in external} == {
        "cmapss_fd001", "cmapss_fd002", "cmapss_fd003", "cmapss_fd004", "tep_faulty",
    }
    # Baseline-first ordering: ours model is the last key of every condition group.
    for condition_keys in _group_by_condition(keys):
        assert condition_keys[-1].model_id == "kst_light_v2"
        assert all(k.family == "baseline" for k in condition_keys[:-1])
    assert all(k.seed == 2026 for k in keys)


def test_ch4_matrix_expands_exactly_42_keys_with_flow_ours() -> None:
    matrix = load_formal_matrix(REPO_ROOT / AUTHORITATIVE_MATRICES["ch4"])
    keys = expand_formal_matrix(matrix)
    assert len(keys) == 42  # 6 protocol-condition pairs x 7 models
    assert len({k.protocol for k in keys}) == 6
    assert keys[-1].model_id == "kst_flow_v2"
    assert all(k.model_id != "kst_probflow" for k in keys)


def test_ch5_matrix_declares_planned_ours_and_expands_30_keys() -> None:
    matrix = load_formal_matrix(REPO_ROOT / AUTHORITATIVE_MATRICES["ch5"])
    assert matrix.planned_model_ids == ["kst_probflow_v2"]
    keys = expand_formal_matrix(matrix)
    assert len(keys) == 30  # 6 pairs x (4 baselines + 1 planned ours)
    planned = [k for k in keys if k.status == "planned"]
    assert [k.model_id for k in planned] == ["kst_probflow_v2"] * 6
    # The planned declaration must block execution (dry-run only at C0).
    with pytest.raises(ValueError, match="planned"):
        assert_no_planned_for_execution(matrix)


def test_legacy_model_ids_are_rejected_everywhere() -> None:
    for legacy_id in ("kst_light", "kst_probflow"):
        for chapter in ("ch3", "ch4", "ch5"):
            raw = _load_dict(REPO_ROOT / AUTHORITATIVE_MATRICES[chapter])
            raw["models"].append({"model_id": legacy_id, "family": "baseline",
                                  "head_type": "linear"})
            with pytest.raises(ValueError, match=legacy_id):
                _check_rejected(raw)


def test_duplicate_model_ids_are_rejected() -> None:
    raw = _load_dict(REPO_ROOT / AUTHORITATIVE_MATRICES["ch3"])
    raw["models"].append(dict(raw["models"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        _check_rejected(raw)


def test_ch3_baseline_count_is_pinned_to_five() -> None:
    raw = _load_dict(REPO_ROOT / AUTHORITATIVE_MATRICES["ch3"])
    raw["models"] = [m for m in raw["models"] if m["model_id"] != "ode_rnn"]
    with pytest.raises(ValueError, match="baseline"):
        _check_rejected(raw)

    raw = _load_dict(REPO_ROOT / AUTHORITATIVE_MATRICES["ch3"])
    raw["models"].insert(0, {"model_id": "kaf_profiti_joint", "family": "baseline",
                             "head_type": "flow"})
    with pytest.raises(ValueError, match="baseline"):
        _check_rejected(raw)


def test_ch4_missing_flow_ours_is_rejected() -> None:
    raw = _load_dict(REPO_ROOT / AUTHORITATIVE_MATRICES["ch4"])
    raw["models"] = [m for m in raw["models"] if m["model_id"] != "kst_flow_v2"]
    with pytest.raises(ValueError, match="kst_flow_v2"):
        _check_rejected(raw)


def test_not_implemented_registry_models_are_rejected() -> None:
    # Replace one core baseline (count stays valid) to exercise the registry
    # gate itself, not the composition count.
    raw = _load_dict(REPO_ROOT / AUTHORITATIVE_MATRICES["ch4"])
    raw["models"] = [
        {"model_id": "kafnet_gaussian", "family": "baseline", "head_type": "flow"}
        if m["model_id"] == "grafiti_gaussian" else m
        for m in raw["models"]
    ]
    with pytest.raises(ValueError, match="kafnet_gaussian"):
        _check_rejected(raw)


def test_active_models_are_registry_known_and_ready() -> None:
    for chapter in ("ch3", "ch4", "ch5"):
        matrix = load_formal_matrix(REPO_ROOT / AUTHORITATIVE_MATRICES[chapter])
        for model in matrix.models:
            if model.get("status") == "planned":
                continue
            spec = get_model_spec(model["model_id"])
            assert spec.status in {"pilot_ready", "enabled"}, (
                f"{chapter}: {model['model_id']} registry status {spec.status}"
            )


def test_ch5_planned_ours_must_not_be_registered_yet() -> None:
    from kaf_profiti.experiments.registry import _MODEL_SPECS

    assert "kst_probflow_v2" not in _MODEL_SPECS, (
        "kst_probflow_v2 must stay unregistered until V2-CH5-CODE-T02"
    )


def test_protocol_windows_follow_a1_contract() -> None:
    contract = {
        "metropt3_chrono_502030_v2": (168, 24, 60),
        "cmapss_fd001": (50, 10, 1),
        "cmapss_fd002": (50, 10, 1),
        "cmapss_fd003": (50, 10, 1),
        "cmapss_fd004": (50, 10, 1),
        "tep_faulty": (96, 24, 12),
    }
    for chapter in ("ch3", "ch4", "ch5"):
        raw = _load_dict(REPO_ROOT / AUTHORITATIVE_MATRICES[chapter])
        assert set(raw["protocols"]) == set(contract), chapter
        for protocol_id, windows in contract.items():
            entry = raw["protocols"][protocol_id]
            got = (entry["history_len"], entry["pred_len"], entry["stride"])
            assert got == windows, (chapter, protocol_id, got)

    # A drifted window must fail validation.
    raw = _load_dict(REPO_ROOT / AUTHORITATIVE_MATRICES["ch3"])
    raw["protocols"]["tep_faulty"]["pred_len"] = 25
    with pytest.raises(ValueError, match="tep_faulty"):
        _check_rejected(raw)


def test_metropt_condition_set_is_exact_and_external_single() -> None:
    raw = _load_dict(REPO_ROOT / AUTHORITATIVE_MATRICES["ch3"])
    metropt = raw["protocols"]["metropt3_chrono_502030_v2"]
    got = {(c["missing_mode"], float(c["target_missing_rate"])) for c in metropt["conditions"]}
    assert got == {
        ("mixed", 0.30), ("random", 0.00), ("random", 0.30),
        ("random", 0.70), ("low_rate", 0.30), ("block_offline", 0.30),
    }
    for protocol_id in ("cmapss_fd001", "cmapss_fd004", "tep_faulty"):
        conditions = raw["protocols"][protocol_id]["conditions"]
        assert len(conditions) == 1
        assert (conditions[0]["missing_mode"], float(conditions[0]["target_missing_rate"])) == ("mixed", 0.30)

    # A missing MetroPT condition must fail; an extra external condition too.
    raw = _load_dict(REPO_ROOT / AUTHORITATIVE_MATRICES["ch3"])
    raw["protocols"]["metropt3_chrono_502030_v2"]["conditions"].pop()
    with pytest.raises(ValueError, match="metropt3_chrono_502030_v2"):
        _check_rejected(raw)

    raw = _load_dict(REPO_ROOT / AUTHORITATIVE_MATRICES["ch3"])
    raw["protocols"]["cmapss_fd001"]["conditions"].append(
        {"condition_id": "point_random_030", "missing_mode": "random",
         "target_missing_rate": 0.30}
    )
    with pytest.raises(ValueError, match="cmapss_fd001"):
        _check_rejected(raw)


def _group_by_condition(keys):
    groups: dict = {}
    for key in keys:
        groups.setdefault((key.protocol, key.condition_id), []).append(key)
    return [groups[k] for k in groups]


def _run_cli(*extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT / "code")
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "code" / "run_pilot_matrix.py"), *extra],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT), timeout=120,
    )


def test_cli_config_dry_run_expands_expected_key_counts() -> None:
    expected = {"ch3": 66, "ch4": 42, "ch5": 30}
    for chapter, count in expected.items():
        result = _run_cli("--config", AUTHORITATIVE_MATRICES[chapter], "--mode", "dry-run")
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["chapter"] == chapter
        assert payload["expanded_keys"] == count
        assert payload["unique_keys"] == count
        assert payload["test_metric_count"] == 0
    # The ch5 dry-run must list, but never instantiate, the planned model.
    result = _run_cli("--config", AUTHORITATIVE_MATRICES["ch5"], "--mode", "dry-run")
    payload = json.loads(result.stdout)
    assert payload["planned_models"] == ["kst_probflow_v2"]
    assert payload["instantiated_models"] == []


def test_cli_config_rejects_legacy_pilot_matrices_and_full_mode() -> None:
    legacy = _run_cli("--config", "configs/pilot/metropt3/point_matrix.yaml", "--mode", "dry-run")
    assert legacy.returncode != 0
    assert "configs/pilot" in legacy.stderr or "authoritative" in legacy.stderr

    full = _run_cli("--config", AUTHORITATIVE_MATRICES["ch3"], "--mode", "full")
    assert full.returncode != 0
    assert "dry-run" in full.stderr

    both = _run_cli("--config", AUTHORITATIVE_MATRICES["ch3"], "--profile", "fd004")
    assert both.returncode != 0
