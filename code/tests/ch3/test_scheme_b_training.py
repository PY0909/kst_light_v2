import pytest

torch = pytest.importorskip("torch")

from kaf_profiti.experiments.pilot_runner import PilotRunSpec, _optimizer_config, load_matrix


def _v2_spec(**overrides):
    values = dict(
        key="scheme-b-training",
        track="point",
        matrix_name="scheme_b",
        dataset="metropt3_chrono_502030_v2",
        model_id="kst_light_v2",
        head_type="residual",
        family="ours",
        condition_id="point_mixed_030",
        missing_mode="mixed",
        target_missing_rate=0.3,
        seed=2026,
        split_seed=2026,
        mask_seed=2026,
        history_len=168,
        pred_len=24,
        stride=60,
        epochs=5,
        batch_size=8,
        hidden_dim=64,
    )
    values.update(overrides)
    return PilotRunSpec(**values)


def test_v2_optimizer_recipe_is_serialized_with_selection_controls():
    spec = _v2_spec(
        learning_rate=2e-4,
        weight_decay=1e-5,
        scheduler="cosine",
        patience=3,
        grad_clip_norm=0.5,
    )
    config = _optimizer_config(spec)
    assert config == {
        "class": "torch.optim.AdamW",
        "lr": 2e-4,
        "weight_decay": 1e-5,
        "scheduler": "cosine",
        "patience": 3,
        "grad_clip_norm": 0.5,
    }


def test_invalid_v2_optimizer_values_are_rejected_before_data_loading(tmp_path):
    source = tmp_path / "invalid.yaml"
    source.write_text(
        """matrix_id: scheme_b_invalid_point
dataset: metropt3_chrono_502030_v2
seed: 2026
split_seed: 2026
mask_seed: 2026
history_len: 168
pred_len: 24
stride: 60
epochs: 5
batch_size: 8
hidden_dim: 64
learning_rate: -0.001
conditions:
  - condition_id: point_mixed_030
    missing_mode: mixed
    target_missing_rate: 0.30
models:
  - model_id: kst_light_v2
    head_type: residual
    family: ours
    recipe_version: scheme_b_v1
    encoder_version: hierarchical_missingness_kaf_v1
    missing_feature_version: causal_missingness_v1
    cross_variable_mode: fla
    patch_lens: [12, 24, 48]
    freshness_tau: 24.0
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="learning_rate"):
        load_matrix(source)


def test_legacy_optimizer_defaults_remain_frozen():
    config = _optimizer_config()
    assert config["class"] == "torch.optim.AdamW"
    assert config["lr"] == 1e-3
    assert config["weight_decay"] == 1e-4
    assert config["grad_clip_norm"] == 1.0
