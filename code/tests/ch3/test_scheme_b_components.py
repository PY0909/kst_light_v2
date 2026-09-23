import pytest

torch = pytest.importorskip("torch")
from torch import nn

from kaf_profiti.models.cross_variable import (
    CrossVariableConfig,
    build_cross_variable_block,
)
from kaf_profiti.models.missingness_features import MissingnessFeatures


def test_missingness_features_are_causal_and_reset_on_observation():
    times = torch.tensor([[[0.0, 0.0], [1.0, 1.0], [3.0, 3.0], [6.0, 6.0]]])
    mask = torch.tensor([[[1.0, 0.0], [0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]])
    module = MissingnessFeatures(freshness_tau=2.0, max_delta=10.0)
    first = module(times, mask)
    changed_mask = mask.clone()
    changed_mask[:, 3] = 0.0
    changed_future = module(times, changed_mask)
    assert torch.equal(first.has_history[:, :3], changed_future.has_history[:, :3])
    assert torch.allclose(first.delta_t[0, 2, 0], torch.tensor(0.0))
    assert torch.allclose(first.block_length[0, 1, 0], torch.tensor(1.0))
    assert torch.allclose(first.has_history[0, :, 1], torch.tensor([0.0, 0.0, 0.0, 1.0]))
    assert bool(torch.isfinite(first.freshness).all())


def test_cross_variable_modes_are_exclusive_and_graph_uses_freshness():
    cfg = CrossVariableConfig(hidden_dim=8, heads=2)
    with pytest.raises(ValueError, match="cross_variable_mode"):
        build_cross_variable_block("fla+missing_graph", cfg)
    graph = build_cross_variable_block("missing_graph", cfg)
    z = torch.randn(2, 3, 8)
    fresh = torch.ones(2, 3)
    available = torch.ones(2, 3)
    out = graph(z, fresh, available)
    assert out.shape == z.shape
    assert torch.isfinite(out).all()
    old = graph.last_adjacency.clone()
    newer = graph(z, torch.tensor([[1.0, 0.01, 1.0], [1.0, 0.01, 1.0]]), available)
    assert newer.shape == z.shape
    assert bool((graph.last_adjacency[:, :, 1] <= old[:, :, 1] + 1e-5).all())


def test_cross_variable_identity_is_a_noop():
    cfg = CrossVariableConfig(hidden_dim=8, heads=2)
    block = build_cross_variable_block("identity", cfg)
    z = torch.randn(1, 3, 8)
    assert torch.equal(block(z, torch.ones(1, 3), torch.ones(1, 3)), z)
