"""CH3-S05 audit: model_id -> model class mapping and run provenance metadata."""

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from kaf_profiti.experiments.pilot_runner import (
    PilotRunner,
    _model_class_name,
    _model_config,
    _optimizer_config,
    _training_command_hash,
    GRAD_CLIP_NORM,
    build_model,
    load_matrix,
)

POINT_MODEL_CLASSES = {
    "li_tcn": "LITCNPoint",
    "ff_gru": "FFGRUPoint",
    "masked_tcn": "MaskedTCNPoint",
    "gru_d": "GRUDPoint",
    "ode_rnn": "ODERNNPoint",
}


def _registry_matrix(tmp_path, model_ids):
    payload = {
        "matrix_id": "tiny_registry_point",
        "dataset": "metropt3_chrono_502030_v2",
        "seed": 2026,
        "split_seed": 2026,
        "mask_seed": 2026,
        "history_len": 8,
        "pred_len": 3,
        "stride": 1,
        "epochs": 2,
        "batch_size": 2,
        "hidden_dim": 8,
        "conditions": [
            {"condition_id": "point_random_000", "missing_mode": "random", "target_missing_rate": 0.0},
        ],
        "models": [
            {"model_id": model_id, "head_type": "linear", "family": "baseline", "priority": index + 1}
            for index, model_id in enumerate(model_ids)
        ],
    }
    path = tmp_path / "point.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return load_matrix(path)


def _spec_for(tmp_path, model_id):
    runner = PilotRunner([_registry_matrix(tmp_path, [model_id])], tmp_path / "result", profile="metropt3")
    return runner.expand()[0]


def test_each_model_id_builds_its_own_class(tmp_path):
    """A wrong registry mapping would silently duplicate one model's artifacts."""

    classes = {}
    for model_id in POINT_MODEL_CLASSES:
        spec = _spec_for(tmp_path, model_id)
        model = build_model(spec, num_sensors=7, context_dim=3, options={}, device="cpu")
        classes[model_id] = type(model).__name__

    assert classes == POINT_MODEL_CLASSES
    assert len(set(classes.values())) == len(classes)


def test_li_tcn_and_masked_tcn_are_distinct_implementations(tmp_path):
    """The 0%-missing equivalence must come from data, not a shared class."""

    li_tcn = build_model(_spec_for(tmp_path, "li_tcn"), 7, 3, {}, device="cpu")
    masked_tcn = build_model(_spec_for(tmp_path, "masked_tcn"), 7, 3, {}, device="cpu")

    assert type(li_tcn) is not type(masked_tcn)
    assert hasattr(li_tcn, "encode_history") and hasattr(masked_tcn, "encode_history")
    assert type(li_tcn).encode_history is not type(masked_tcn).encode_history


def test_model_class_name_is_fully_qualified(tmp_path):
    model = build_model(_spec_for(tmp_path, "li_tcn"), 7, 3, {}, device="cpu")
    name = _model_class_name(model)

    assert name.endswith(".LITCNPoint")
    assert "kaf_profiti.baselines.point" in name


def test_model_and_optimizer_config_capture_recipe(tmp_path):
    spec = _spec_for(tmp_path, "gru_d")
    model = build_model(spec, 7, 3, {}, device="cpu")

    config = _model_config(model, spec)
    assert config["model_class"].endswith(".GRUDPoint")
    assert config["model_id"] == "gru_d"
    assert config["num_parameters"] == sum(
        p.numel() for p in model.parameters() if p.requires_grad
    )
    assert config["hidden_dim"] == spec.hidden_dim

    optimizer = _optimizer_config()
    assert optimizer["class"] == "torch.optim.AdamW"
    assert optimizer["grad_clip_norm"] == GRAD_CLIP_NORM
    assert optimizer["lr"] == 1e-3 and optimizer["weight_decay"] == 1e-4


def test_training_command_hash_is_stable_and_recorded():
    first = _training_command_hash()
    second = _training_command_hash()

    assert first == second
    assert first == hashlib.sha256(" ".join(__import__("sys").argv).encode("utf-8")).hexdigest()
