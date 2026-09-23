"""CH2.5-P02-T03: probabilistic baseline distribution/sampling fidelity tests.

The six Chapter-4 baselines and KST ProbFlow must all speak the unified
distribution API: finite NLL with the shared valid-position denominator,
sample/interval/point predictions from one trained distribution, mask
invariance, gradients, and checkpoint round-trips. Diagonal models share one
scale parameterization (softplus + min scale) and one 95% interval definition
(mean +/- Z95 * scale); flow models (ProFITi, KST ProbFlow) derive NLL and
samples from the same flow.
"""

import math
import sys
from pathlib import Path

import pytest
import torch
import yaml

from kaf_profiti.baselines.probabilistic import create_probabilistic_baseline
from kaf_profiti.experiments.model_api import check_gaussian_interface
from kaf_profiti.experiments.registry import get_model_spec
from kaf_profiti.industrial.batch import IndustrialBatch

_REPO_ROOT = Path(__file__).resolve().parents[3]
PROBABILISTIC_MATRIX = _REPO_ROOT / "configs" / "pilot" / "fd004" / "probabilistic_matrix.yaml"

_HISTORY, _PRED, _SENSORS = 10, 3, 4
_DIAGONAL_MODELS = [
    "tcn_gaussian",
    "patchtst_gaussian",
    "gru_d_gaussian",
    "ode_rnn_gaussian",
    "grafiti_gaussian",
]
_ALL_MODELS = _DIAGONAL_MODELS + ["profiti", "kst_probflow"]


def _make_batch(batch_size: int = 5, seed: int = 11) -> IndustrialBatch:
    generator = torch.Generator().manual_seed(seed)
    x_obs = torch.randn(batch_size, _HISTORY, _SENSORS, generator=generator)
    m_obs = (torch.rand(batch_size, _HISTORY, _SENSORS, generator=generator) > 0.3).float()
    t_obs = torch.tensor([[0.0, 1.0, 2.5, 5.0, 9.0, 14.0, 20.0, 27.0, 35.0, 44.0]]).repeat(
        batch_size, 1
    )
    y_q = torch.randn(batch_size, _PRED, _SENSORS, generator=generator)
    m_q = (torch.rand(batch_size, _PRED, _SENSORS, generator=generator) > 0.25).float()
    m_q[:, 0] = 1.0
    return IndustrialBatch(
        X_obs=x_obs,
        T_obs=t_obs,
        M_obs=m_obs,
        T_q=(t_obs[:, -1:] + torch.arange(1, _PRED + 1, dtype=torch.float32)).repeat(1, 1),
        Y_q=y_q,
        M_q=m_q,
        context=torch.randn(batch_size, 3, generator=generator),
        y_flat=y_q.reshape(batch_size, -1),
        mq_flat=m_q.reshape(batch_size, -1),
        query_channel_ids=torch.arange(_SENSORS).repeat(_PRED),
        rul=torch.rand(batch_size, generator=generator) * 100.0,
        unit_id=torch.arange(batch_size),
    )


def _model(name: str):
    return create_probabilistic_baseline(
        name,
        num_sensors=_SENSORS,
        context_dim=3,
        pred_len=_PRED,
        hidden_dim=16,
    )


# ---------------------------------------------------------------------------
# Registry identity
# ---------------------------------------------------------------------------


def test_probabilistic_matrix_models_have_registry_identity():
    matrix = yaml.safe_load(PROBABILISTIC_MATRIX.read_text(encoding="utf-8"))
    model_ids = sorted(entry["model_id"] for entry in matrix["models"])
    assert model_ids == sorted(_ALL_MODELS)

    time_expected = {
        "tcn_gaussian": False,
        "patchtst_gaussian": False,
        "gru_d_gaussian": True,
        "ode_rnn_gaussian": True,
        "grafiti_gaussian": True,
        "profiti": True,
        "kst_probflow": True,
    }
    for model_id in model_ids:
        spec = get_model_spec(model_id)
        assert spec.status in {"pilot_ready", "enabled"}, (model_id, spec.status)
        assert spec.implementation in {"faithful", "adapted", "adapted_profiti", "own"}, model_id
        assert spec.source_identity, model_id
        assert spec.adapter, model_id
        assert spec.requires_time_input == time_expected[model_id], model_id
    assert get_model_spec("profiti").implementation == "adapted_profiti"
    assert get_model_spec("kst_probflow").implementation == "own"


def test_registry_identity_matches_model_classes():
    for model_id in _ALL_MODELS:
        model = _model(model_id)
        spec = get_model_spec(model_id)
        assert spec.implementation == model.IMPLEMENTATION, model_id
        assert spec.source_identity == model.SOURCE_IDENTITY, model_id
        assert spec.requires_time_input == model.REQUIRES_TIME_INPUT, model_id
        assert spec.adapter == model.ADAPTER, model_id


# ---------------------------------------------------------------------------
# Unified distribution contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", _ALL_MODELS)
def test_every_probabilistic_model_passes_unified_gaussian_interface(model_id):
    torch.manual_seed(0)
    check_gaussian_interface(_model(model_id), _make_batch(), nsamples=128)


@pytest.mark.parametrize("model_id", _DIAGONAL_MODELS)
def test_diagonal_nll_matches_manual_formula_and_shared_denominator(model_id):
    torch.manual_seed(0)
    model = _model(model_id)
    batch = _make_batch()
    model.eval()
    with torch.no_grad():
        nll = float(model.batch_nll(batch))
        mean, scale = model.gaussian_params(batch)
    log_prob = (
        -0.5 * ((batch.Y_q - mean) / scale).pow(2)
        - torch.log(scale)
        - 0.5 * math.log(2.0 * math.pi)
    )
    expected = float(-((log_prob * batch.M_q).sum() / batch.M_q.sum()))
    assert nll == pytest.approx(expected, rel=1e-5), model_id


@pytest.mark.parametrize("model_id", _ALL_MODELS)
def test_one_train_step_changes_parameters(model_id):
    torch.manual_seed(0)
    model = _model(model_id)
    batch = _make_batch()
    before = [parameter.detach().clone() for parameter in model.parameters()]
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-2)
    optimizer.zero_grad()
    loss = model.loss(batch)
    loss.backward()
    optimizer.step()
    assert torch.isfinite(loss)
    changed = any(
        not torch.equal(previous, current.detach())
        for previous, current in zip(before, list(model.parameters()))
    )
    assert changed, f"{model_id}: one optimizer step did not change any parameter"


# ---------------------------------------------------------------------------
# ProFITi: NLL and samples must come from one trained distribution
# ---------------------------------------------------------------------------


def test_profiti_nll_and_sample_come_from_the_same_flow():
    torch.manual_seed(0)
    model = _model("profiti")
    assert model.gaussian_kind == "flow"
    batch = _make_batch()
    model.eval()
    with torch.no_grad():
        nll = float(model.batch_nll(batch))
        hidden = model.flow_hidden(batch)
        rows = model.flow_head.nll(batch.y_flat, hidden, batch.mq_flat)
        row_counts = batch.mq_flat.sum(dim=-1).clamp_min(1.0)
        expected = float((rows * row_counts).sum() / batch.mq_flat.sum())
        generator = torch.Generator().manual_seed(3)
        samples = model._flow_sample(hidden, batch.mq_flat, 32, generator)
        point_a = model.predict_point(batch)
        point_b = model.predict_point(batch)
    assert nll == pytest.approx(expected, rel=1e-5)
    assert samples.shape == (batch.X_obs.shape[0], 32, _PRED * _SENSORS)
    assert torch.equal(point_a, point_b), "flow point prediction must be deterministic"


def test_profiti_legacy_cached_hidden_path_is_not_used_by_unified_api():
    torch.manual_seed(0)
    model = _model("profiti")
    batch = _make_batch()
    model.eval()
    model._last_hidden = None
    with torch.no_grad():
        nll = float(model.batch_nll(batch))
    model._last_hidden = None
    with torch.no_grad():
        replay = float(model.batch_nll(batch))
    assert nll == pytest.approx(replay, rel=1e-6), (
        "unified batch_nll must recompute hidden states instead of relying on "
        "the legacy cached _last_hidden"
    )


# ---------------------------------------------------------------------------
# Time-aware mechanisms
# ---------------------------------------------------------------------------


def test_gru_d_gaussian_has_learnable_decay_and_uses_time_gaps():
    torch.manual_seed(0)
    model = _model("gru_d_gaussian")
    decay_params = [name for name, _ in model.named_parameters() if "decay" in name]
    assert decay_params, "GRU-D Gaussian must expose learnable decay parameters"

    batch = _make_batch()
    model.eval()
    with torch.no_grad():
        reference_mean, _ = model.gaussian_params(batch)
        squeezed = IndustrialBatch(**{**batch.__dict__, "T_obs": batch.T_obs * 0.05})
        squeezed_mean, _ = model.gaussian_params(squeezed)
    assert not torch.allclose(reference_mean, squeezed_mean, atol=1e-6)

    model.zero_grad(set_to_none=True)
    model.loss(batch).backward()
    decay_grads = [
        parameter.grad
        for name, parameter in model.named_parameters()
        if "decay" in name and parameter.grad is not None
    ]
    assert decay_grads, "decay parameters receive no gradient"


def test_grafiti_gaussian_has_time_aware_sensor_graph():
    torch.manual_seed(0)
    model = _model("grafiti_gaussian")
    names = [name for name, _ in model.named_parameters()]
    assert any("adjacency" in name for name in names), "GraFITi needs a sensor graph"
    assert any("decay" in name for name in names), "GraFITi needs a time-gap decay"

    batch = _make_batch()
    model.eval()
    with torch.no_grad():
        reference_mean, _ = model.gaussian_params(batch)
        stretched = IndustrialBatch(**{**batch.__dict__, "T_obs": batch.T_obs * 3.0})
        stretched_mean, _ = model.gaussian_params(stretched)
    assert not torch.allclose(reference_mean, stretched_mean, atol=1e-6), (
        "GraFITi graph propagation must react to real observation time gaps"
    )


def test_ode_rnn_gaussian_evolves_by_real_time():
    torch.manual_seed(0)
    model = _model("ode_rnn_gaussian")
    batch = _make_batch()
    model.eval()
    with torch.no_grad():
        reference_mean, _ = model.gaussian_params(batch)
        stretched = IndustrialBatch(**{**batch.__dict__, "T_obs": batch.T_obs * 3.0})
        stretched_mean, _ = model.gaussian_params(stretched)
    assert not torch.allclose(reference_mean, stretched_mean, atol=1e-6), (
        "ODE-RNN hidden evolution must depend on real time gaps"
    )
