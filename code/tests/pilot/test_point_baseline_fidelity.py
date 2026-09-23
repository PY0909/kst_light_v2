"""CH2.5-P02-T02: Chapter-3 point baseline mechanism and fidelity tests.

The five point baselines (li_tcn, ff_gru, masked_tcn, gru_d, ode_rnn) must all
pass the unified interface, implement their declared missing-data mechanism
correctly, keep every fill inside the history window with train-only fill
values, and carry an honest implementation identity in the registry.
"""

from pathlib import Path

import pytest
import torch
import yaml

from kaf_profiti.baselines.point import (
    compute_delta_t,
    create_point_baseline,
    forward_fill,
    linear_interpolate_fill,
)
from kaf_profiti.experiments.model_api import check_point_interface
from kaf_profiti.experiments.registry import get_model_spec
from kaf_profiti.industrial.batch import IndustrialBatch
from kaf_profiti.models.lightweight_head import KSTLight

_HISTORY, _PRED, _SENSORS = 10, 3, 4
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
POINT_MATRIX = _PROJECT_ROOT / "configs" / "pilot" / "fd004" / "point_matrix.yaml"

_POINT_BASELINE_IDS = ["li_tcn", "ff_gru", "masked_tcn", "gru_d", "ode_rnn"]


def _make_batch(batch_size: int = 5, seed: int = 11, irregular: bool = False) -> IndustrialBatch:
    generator = torch.Generator().manual_seed(seed)
    x_obs = torch.randn(batch_size, _HISTORY, _SENSORS, generator=generator)
    m_obs = (torch.rand(batch_size, _HISTORY, _SENSORS, generator=generator) > 0.3).float()
    if irregular:
        t_obs = torch.tensor([[0.0, 1.0, 2.5, 5.0, 9.0, 14.0, 20.0, 27.0, 35.0, 44.0]]).repeat(
            batch_size, 1
        )
    else:
        t_obs = torch.arange(_HISTORY, dtype=torch.float32).repeat(batch_size, 1)
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


def _model(name: str, **kwargs):
    return create_point_baseline(
        name,
        num_sensors=_SENSORS,
        context_dim=3,
        pred_len=_PRED,
        hidden_dim=16,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Registry identity
# ---------------------------------------------------------------------------


def test_point_matrix_models_have_registry_identity_and_pilot_ready_status():
    matrix = yaml.safe_load(POINT_MATRIX.read_text(encoding="utf-8"))
    model_ids = {entry["model_id"] for entry in matrix["models"]}

    for model_id in sorted(model_ids):
        spec = get_model_spec(model_id)
        assert spec.status == "pilot_ready", (model_id, spec.status)
        assert spec.implementation in {"faithful", "adapted", "own"}, model_id
        assert spec.source_identity, model_id
        assert spec.adapter, model_id
    gru_d = get_model_spec("gru_d")
    assert gru_d.requires_time_input is True
    ode_rnn = get_model_spec("ode_rnn")
    assert ode_rnn.requires_time_input is True
    li_tcn = get_model_spec("li_tcn")
    assert li_tcn.requires_time_input is True


def test_simplified_implementations_are_declared_adapted():
    for model_id in ("li_tcn", "ff_gru", "masked_tcn", "gru_d", "ode_rnn"):
        spec = get_model_spec(model_id)
        assert spec.implementation == "adapted", model_id


def test_registry_identity_matches_model_classes():
    from kaf_profiti.baselines.point import _POINT_FACTORIES

    for model_id, model_class in _POINT_FACTORIES.items():
        spec = get_model_spec(model_id)
        assert spec.implementation == model_class.IMPLEMENTATION, model_id
        assert spec.source_identity == model_class.SOURCE_IDENTITY, model_id
        assert spec.requires_time_input == model_class.REQUIRES_TIME_INPUT, model_id
        assert spec.adapter == model_class.ADAPTER, model_id


# ---------------------------------------------------------------------------
# Unified interface + one training step for every baseline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_id", _POINT_BASELINE_IDS)
def test_every_point_baseline_passes_unified_interface(model_id):
    torch.manual_seed(0)
    check_point_interface(_model(model_id), _make_batch(irregular=True))


@pytest.mark.parametrize("model_id", _POINT_BASELINE_IDS)
def test_one_train_step_changes_parameters(model_id):
    torch.manual_seed(0)
    model = _model(model_id)
    batch = _make_batch(irregular=True)
    before = [parameter.detach().clone() for parameter in model.parameters()]
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-2)
    optimizer.zero_grad()
    loss = model.loss(batch)
    loss.backward()
    optimizer.step()
    after = list(model.parameters())
    changed = any(
        not torch.equal(previous, current.detach()) for previous, current in zip(before, after)
    )
    assert changed, f"{model_id}: one optimizer step did not change any parameter"
    assert torch.isfinite(loss)


def test_kst_light_registered_and_uses_unified_head():
    spec = get_model_spec("kst_light")
    assert spec.status == "pilot_ready"
    assert spec.implementation == "own"
    for head_type in ("linear", "mlp"):
        model = KSTLight(
            num_sensors=_SENSORS,
            context_dim=3,
            pred_len=_PRED,
            hidden_dim=16,
            te_dim=5,
            kernel_count=2,
            n_layers=1,
            n_heads=2,
            preconv_dim=4,
            patch_lens=(2, 4),
            head_type=head_type,
        )
        check_point_interface(model, _make_batch(irregular=True))


# ---------------------------------------------------------------------------
# Adapter mechanisms: fills stay inside the history with train-only values
# ---------------------------------------------------------------------------


def test_linear_interpolate_fill_matches_manual_rule():
    x = torch.tensor([[[float("nan"), 5.0], [1.0, float("nan")], [float("nan"), 7.0], [4.0, float("nan")]]])
    mask = torch.tensor([[[0.0, 1.0], [1.0, 0.0], [0.0, 1.0], [1.0, 0.0]]])
    t = torch.tensor([[0.0, 1.0, 2.0, 4.0]])
    filled = linear_interpolate_fill(x, mask, t, fill_value=0.25)

    # channel 0: leading missing -> fill_value; interior missing at t=2
    # interpolates between t=1 (1.0) and t=4 (4.0) -> 2.0
    assert filled[0, 0, 0] == pytest.approx(0.25)
    assert filled[0, 2, 0] == pytest.approx(2.0)
    assert filled[0, 1, 0] == pytest.approx(1.0)
    assert filled[0, 3, 0] == pytest.approx(4.0)
    # channel 1: interior missing at t=1 interpolates (5.0 + 7.0)/2 = 6.0;
    # trailing missing at t=4 holds the last observed value (7.0)
    assert filled[0, 1, 1] == pytest.approx(6.0)
    assert filled[0, 3, 1] == pytest.approx(7.0)


def test_linear_interpolate_fill_uses_time_not_position():
    x = torch.tensor([[[1.0], [float("nan")], [3.0]]])
    mask = torch.tensor([[[1.0], [0.0], [1.0]]])
    uniform = linear_interpolate_fill(x, mask, torch.tensor([[0.0, 1.0, 2.0]]))
    stretched = linear_interpolate_fill(x, mask, torch.tensor([[0.0, 0.1, 2.0]]))
    assert uniform[0, 1, 0] == pytest.approx(2.0)
    assert stretched[0, 1, 0] == pytest.approx(1.1)


def test_linear_interpolate_fill_all_missing_channel_uses_train_only_fill():
    x = torch.tensor([[[7.0, 1.0], [7.0, 2.0]]])
    mask = torch.tensor([[[1.0, 0.0], [1.0, 0.0]]])
    filled = linear_interpolate_fill(x, mask, torch.tensor([[0.0, 1.0]]), fill_value=-3.5)
    assert torch.equal(filled[:, :, 1], torch.full((1, 2), -3.5))


def test_forward_fill_matches_manual_rule():
    x = torch.tensor([[[float("nan"), 5.0], [2.0, float("nan")], [float("nan"), float("nan")]]])
    mask = torch.tensor([[[0.0, 1.0], [1.0, 0.0], [0.0, 0.0]]])
    filled = forward_fill(x, mask, fill_value=0.5)
    assert filled[0, 0, 0] == pytest.approx(0.5)  # leading gap -> train-only fill
    assert filled[0, 1, 0] == pytest.approx(2.0)
    assert filled[0, 2, 0] == pytest.approx(2.0)  # trailing gap holds last observed
    assert filled[0, 2, 1] == pytest.approx(5.0)


def test_masked_tcn_ignores_values_at_masked_history_positions():
    torch.manual_seed(0)
    model = _model("masked_tcn")
    model.eval()
    batch = _make_batch(irregular=True)
    with torch.no_grad():
        reference = model.predict_point(batch)

    generator = torch.Generator().manual_seed(99)
    garbage = torch.randn(batch.X_obs.shape, generator=generator)
    x_tampered = torch.where(batch.M_obs > 0, batch.X_obs, garbage)
    tampered = IndustrialBatch(**{**batch.__dict__, "X_obs": x_tampered})
    with torch.no_grad():
        replay = model.predict_point(tampered)
    assert torch.allclose(reference, replay, atol=1e-6)


# ---------------------------------------------------------------------------
# GRU-D mechanism: delta_t recursion + learnable decay
# ---------------------------------------------------------------------------


def test_compute_delta_t_matches_gru_d_recursion():
    t = torch.tensor([[0.0, 1.0, 3.0, 6.0, 7.0]])
    mask = torch.tensor([[[1.0], [0.0], [1.0], [0.0], [0.0]]])
    delta = compute_delta_t(t, mask)
    # GRU-D: delta_l = (t_l - t_{l-1}) + delta_{l-1} * (1 - m_{l-1})
    expected = torch.tensor([[[0.0], [1.0], [0.0], [3.0], [4.0]]])
    assert torch.allclose(delta, expected, atol=1e-6)


def test_gru_d_has_learnable_decay_and_uses_time_gaps():
    torch.manual_seed(0)
    model = _model("gru_d")
    decay_params = [
        name for name, parameter in model.named_parameters() if "decay" in name
    ]
    assert decay_params, "GRU-D must expose learnable decay parameters"

    batch = _make_batch(irregular=True)
    model.eval()
    with torch.no_grad():
        reference = model.predict_point(batch)

    # Same values/mask but compressed observation times -> decay shrinks.
    squeezed = IndustrialBatch(**{**batch.__dict__, "T_obs": batch.T_obs * 0.05})
    with torch.no_grad():
        replay = model.predict_point(squeezed)
    assert not torch.allclose(reference, replay, atol=1e-6), (
        "GRU-D output must react to observation time gaps"
    )

    model.zero_grad(set_to_none=True)
    model.loss(batch).backward()
    decay_grads = [
        parameter.grad
        for name, parameter in model.named_parameters()
        if "decay" in name and parameter.grad is not None
    ]
    assert decay_grads, "decay parameters receive no gradient"


def test_ode_rnn_hidden_evolves_by_real_time():
    torch.manual_seed(0)
    model = _model("ode_rnn")
    model.eval()
    batch = _make_batch(irregular=True)
    with torch.no_grad():
        reference = model.predict_point(batch)

    stretched = IndustrialBatch(**{**batch.__dict__, "T_obs": batch.T_obs * 3.0})
    with torch.no_grad():
        replay = model.predict_point(stretched)
    assert not torch.allclose(reference, replay, atol=1e-6), (
        "ODE-RNN hidden evolution must depend on real time gaps"
    )


def test_point_baselines_never_read_future_context():
    torch.manual_seed(0)
    for model_id in _POINT_BASELINE_IDS:
        model = _model(model_id)
        model.eval()
        batch = _make_batch(irregular=True)
        with torch.no_grad():
            reference = model.predict_point(batch)
            tampered_batch = IndustrialBatch(
                **{
                    **batch.__dict__,
                    "T_q": batch.T_q + 100.0,
                }
            )
            replay = model.predict_point(tampered_batch)
        assert torch.allclose(reference, replay, atol=1e-6), model_id
