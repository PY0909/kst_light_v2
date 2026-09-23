from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from kaf_profiti.experiments.registry import get_model_spec, validate_scheme_b_recipe
from kaf_profiti.experiments.pilot_runner import (
    PilotRunSpec,
    PilotRunner,
    _model_config,
    build_model,
    load_matrix,
)


def test_scheme_b_registry_ids_are_distinct_from_legacy():
    assert get_model_spec("kst_light_v2").name == "kst_light_v2"
    assert get_model_spec("kst_flow_v2").name == "kst_flow_v2"
    assert get_model_spec("kst_light").name == "kst_light"
    assert get_model_spec("kst_probflow").name == "kst_probflow"


def test_scheme_b_recipe_requires_identity_fields():
    with pytest.raises(ValueError, match="recipe_version"):
        validate_scheme_b_recipe({"model_id": "kst_light_v2"})


def test_v2_model_config_records_recipe_version_and_architecture():
    spec = PilotRunSpec(
        key="k",
        track="point",
        matrix_name="m",
        dataset="metropt3_chrono_502030_v2",
        model_id="kst_light_v2",
        head_type="",
        family="ours",
        condition_id="point_mixed_030",
        missing_mode="mixed",
        target_missing_rate=0.3,
        seed=2026,
        split_seed=2026,
        mask_seed=2026,
        history_len=12,
        pred_len=3,
        stride=1,
        epochs=1,
        batch_size=2,
        hidden_dim=8,
    )
    model = build_model(spec, 2, 1, {}, device="cpu")
    config = _model_config(model, spec)
    assert config["recipe_version"] == "scheme_b_v1"
    assert config["recipe"]["cross_variable_mode"] == "fla"


def test_scheme_b_matrix_expansion_preserves_static_recipe_identity(tmp_path):
    root = Path(__file__).resolve().parents[3]
    runner = PilotRunner(
        [load_matrix(root / "configs/pilot/metropt3/scheme_b_point_matrix.yaml")],
        result_root=tmp_path / "result",
        data_root=root / "dataset",
        device="cpu",
        profile="metropt3",
    )
    spec = runner.expand()[0]
    assert spec.recipe_version == "scheme_b_v1"
    assert spec.encoder_version == "hierarchical_missingness_kaf_v1"
    assert spec.missing_feature_version == "causal_missingness_v1"
    assert spec.cross_variable_mode == "fla"
    assert spec.patch_lens == (12, 24, 48)
    assert spec.freshness_tau == 24.0


def test_scheme_b_recipe_identity_binds_protocol_and_source_hashes(tmp_path):
    root = Path(__file__).resolve().parents[3]
    runner = PilotRunner(
        [load_matrix(root / "configs/pilot/metropt3/scheme_b_point_matrix.yaml")],
        result_root=tmp_path / "result",
        data_root=root / "dataset",
        device="cpu",
        profile="metropt3",
    )
    spec = runner.expand()[0]
    protocol = {
        "split_sha256": "1" * 64,
        "normalization_sha256": "2" * 64,
        "mask_sha": {"train": "a" * 64, "valid": "b" * 64, "test": "c" * 64},
        "target_schema_sha256": "3" * 64,
        "evaluator": {"implementation": "test", "version": 1},
    }
    identity = runner._scheme_b_recipe_identity(spec, protocol)
    validate_scheme_b_recipe(identity)
    assert identity["split_sha"] == protocol["split_sha256"]
    assert identity["normalization_sha"] == protocol["normalization_sha256"]
    assert identity["mask_sha"] == protocol["mask_sha"]
    assert identity["target_schema_sha"] == protocol["target_schema_sha256"]
    assert len(identity["evaluator_sha"]) == 64
    assert identity["code_sha"] == runner.code_fingerprint
    assert identity["patch_lens"] == [12, 24, 48]
    assert identity["freshness_tau"] == 24.0


def test_scheme_b_model_constructor_uses_matrix_recipe(tmp_path):
    root = Path(__file__).resolve().parents[3]
    runner = PilotRunner(
        [load_matrix(root / "configs/pilot/metropt3/scheme_b_point_matrix.yaml")],
        result_root=tmp_path / "result",
        data_root=root / "dataset",
        device="cpu",
        profile="metropt3",
    )
    spec = runner.expand()[0]
    spec = PilotRunSpec(**{**spec.__dict__, "cross_variable_mode": "identity", "patch_lens": (6, 12), "freshness_tau": 11.0})
    model = build_model(spec, 2, 1, {"cross_variable_mode": "fla", "patch_lens": (99,), "freshness_tau": 99.0}, device="cpu")
    assert model.config.cross_variable_mode == "identity"
    assert model.config.patch_lens == (6, 12)
    assert model.config.freshness_tau == 11.0


def test_scheme_b_preconv_dim_is_explicit_model_identity(tmp_path):
    root = Path(__file__).resolve().parents[3]
    runner = PilotRunner(
        [load_matrix(root / "configs/pilot/metropt3/scheme_b_point_matrix.yaml")],
        result_root=tmp_path / "result",
        data_root=root / "dataset",
        device="cpu",
        profile="metropt3",
    )
    spec = runner.expand()[0]
    spec = PilotRunSpec(**{**spec.__dict__, "preconv_dim": 8})
    model = build_model(spec, 2, 1, {"scheme_b_preconv_dim": 16}, device="cpu")
    assert model.config.preconv_dim == 8
    identity = runner._manifest_identity(spec)
    assert identity["preconv_dim"] == 8


def test_scheme_b_architecture_axes_are_explicit_and_reach_model(tmp_path):
    root = Path(__file__).resolve().parents[3]
    runner = PilotRunner(
        [load_matrix(root / "configs/pilot/metropt3/scheme_b_point_matrix.yaml")],
        result_root=tmp_path / "result", data_root=root / "dataset",
        device="cpu", profile="metropt3",
    )
    spec = runner.expand()[0]
    spec = PilotRunSpec(**{**spec.__dict__, "kernel_count": 3, "n_layers": 1})
    model = build_model(spec, 2, 1, {}, device="cpu")
    assert model.config.kernel_count == 3
    assert model.config.n_layers == 1
    identity = runner._manifest_identity(spec)
    assert identity["kernel_count"] == 3
    assert identity["n_layers"] == 1


def test_scheme_b_fla_cost_axes_are_explicit_and_reach_model(tmp_path):
    root = Path(__file__).resolve().parents[3]
    runner = PilotRunner(
        [load_matrix(root / "configs/pilot/metropt3/scheme_b_point_a1_matrix.yaml")],
        result_root=tmp_path / "result", data_root=root / "dataset",
        device="cpu", profile="metropt3",
    )
    spec = runner.expand()[0]
    spec = PilotRunSpec(
        **{
            **spec.__dict__,
            "cross_variable_rank": 32,
            "cross_variable_mlp_ratio": 2.0,
        }
    )
    model = build_model(spec, 2, 1, {}, device="cpu")
    assert model.config.cross_variable_rank == 32
    assert model.config.cross_variable_mlp_ratio == 2.0
    assert model.cross_variable.block.attn.rank == 32
    assert model.cross_variable.block.mlp[0].out_features == 128
    identity = runner._manifest_identity(spec)
    assert identity["cross_variable_rank"] == 32
    assert identity["cross_variable_mlp_ratio"] == 2.0


def test_missing_sensor_mixer_recipe_reaches_model_and_identity(tmp_path):
    root = Path(__file__).resolve().parents[3]
    runner = PilotRunner(
        [load_matrix(root / "configs/pilot/metropt3/scheme_b_point_m1_missing_sensor_mixer_l1_matrix.yaml")],
        result_root=tmp_path / "result", data_root=root / "dataset",
        device="cpu", profile="metropt3",
    )
    spec = runner.expand()[0]
    model = build_model(spec, 4, 2, {}, device="cpu")
    assert model.config.cross_variable_mode == "missing_sensor_mixer"
    assert model.config.mixer_layers == 1
    assert model.config.mixer_relation_bias is True
    identity = runner._manifest_identity(spec)
    assert identity["cross_variable_mode"] == "missing_sensor_mixer"
    assert identity["mixer_layers"] == 1
