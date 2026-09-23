import pytest

torch = pytest.importorskip("torch")
from torch import nn

from kaf_profiti.models.cross_variable import CrossVariableConfig, build_cross_variable_block


def _inputs(batch=2, length=5, sensors=3, hidden=8, context_dim=2):
    torch.manual_seed(7)
    z = torch.randn(batch, sensors, hidden)
    x = torch.randn(batch, length, sensors)
    mask = torch.ones_like(x)
    mask[:, 1, 1] = 0.0
    freshness = torch.tensor([[1.0, 0.5, 0.1]]).expand(batch, -1).clone()
    available = torch.ones(batch, sensors)
    context = torch.randn(batch, context_dim)
    return z, x, mask, freshness, available, context


def test_gru_mixer_preserves_token_shape_and_counts_parameters():
    config = CrossVariableConfig(hidden_dim=8, num_sensors=3, context_dim=2, gru_hidden=16)
    block = build_cross_variable_block("gru_mixer", config)
    z, x, mask, freshness, available, context = _inputs(hidden=8)
    out = block(z, freshness, available, x, mask, context)
    assert out.shape == z.shape
    assert torch.isfinite(out).all()
    assert sum(parameter.numel() for parameter in block.parameters()) > 0


def test_gru_mixer_freshness_and_availability_change_gate():
    config = CrossVariableConfig(hidden_dim=8, num_sensors=3, context_dim=2, gru_hidden=16)
    block = build_cross_variable_block("gru_mixer", config)
    z, x, mask, freshness, available, context = _inputs(hidden=8)
    block.eval()
    first = block(z, freshness, available, x, mask, context)
    changed = block(z, freshness, available * torch.tensor([[1.0, 0.0, 1.0]]), x, mask, context)
    assert not torch.allclose(first, changed)


@pytest.mark.parametrize("use_forward_fill", [True, False])
@pytest.mark.parametrize("gru_hidden", [16, 32])
def test_gru_mixer_configurations_are_finite_for_fully_missing_history(use_forward_fill, gru_hidden):
    config = CrossVariableConfig(
        hidden_dim=8,
        num_sensors=3,
        context_dim=2,
        gru_hidden=gru_hidden,
        use_forward_fill=use_forward_fill,
    )
    block = build_cross_variable_block("gru_mixer", config)
    z, x, mask, freshness, available, context = _inputs(hidden=8)
    mask.zero_()
    freshness.zero_()
    available.zero_()
    out = block(z, freshness, available, x, mask, context)
    assert out.shape == z.shape
    assert torch.isfinite(out).all()


def test_direct_residual_head_is_optional_and_sensor_shaped():
    config = CrossVariableConfig(
        hidden_dim=8,
        num_sensors=3,
        context_dim=2,
        gru_hidden=16,
        direct_residual=True,
    )
    block = build_cross_variable_block("gru_mixer", config)
    assert isinstance(block.direct_residual_head, nn.Linear)
    z, x, mask, freshness, available, context = _inputs(hidden=8)
    block(z, freshness, available, x, mask, context)
    assert block.last_direct_residual.shape == (z.shape[0], z.shape[1])
