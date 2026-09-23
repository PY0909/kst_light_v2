import pytest

torch = pytest.importorskip("torch")

from kaf_profiti.models.cross_variable import CrossVariableConfig, build_cross_variable_block


def _inputs(batch=2, sensors=4, hidden=8):
    torch.manual_seed(11)
    z = torch.randn(batch, sensors, hidden)
    freshness = torch.tensor([[1.0, 0.8, 0.2, 0.05]]).expand(batch, -1).clone()
    available = torch.ones(batch, sensors)
    return z, freshness, available


def test_missing_sensor_mixer_preserves_shape_and_has_parameters():
    config = CrossVariableConfig(
        hidden_dim=8, num_sensors=4, mixer_layers=1, mixer_relation_bias=True
    )
    block = build_cross_variable_block("missing_sensor_mixer", config)
    z, freshness, available = _inputs()
    output = block(z, freshness, available)
    assert output.shape == z.shape
    assert torch.isfinite(output).all()
    assert sum(parameter.numel() for parameter in block.parameters()) > 0


def test_freshness_and_available_change_message():
    config = CrossVariableConfig(hidden_dim=8, num_sensors=4, mixer_layers=1)
    block = build_cross_variable_block("missing_sensor_mixer", config)
    z, freshness, available = _inputs()
    block.eval()
    first = block(z, freshness, available)
    changed = block(z, freshness * 0.1, available * torch.tensor([[1, 0, 1, 1.]]))
    assert not torch.allclose(first, changed)


@pytest.mark.parametrize("layers", [1, 2])
@pytest.mark.parametrize("relation_bias", [False, True])
def test_missing_sensor_mixer_is_finite_with_all_missing_sources(layers, relation_bias):
    config = CrossVariableConfig(
        hidden_dim=8,
        num_sensors=4,
        mixer_layers=layers,
        mixer_relation_bias=relation_bias,
    )
    block = build_cross_variable_block("missing_sensor_mixer", config)
    z, freshness, available = _inputs()
    output = block(z, torch.zeros_like(freshness), torch.zeros_like(available))
    assert torch.isfinite(output).all()
    assert torch.allclose(output, z, atol=1e-5)


def test_missing_sensor_mixer_rejects_invalid_layer_count():
    with pytest.raises(ValueError, match="mixer_layers"):
        build_cross_variable_block(
            "missing_sensor_mixer",
            CrossVariableConfig(hidden_dim=8, num_sensors=4, mixer_layers=0),
        )
