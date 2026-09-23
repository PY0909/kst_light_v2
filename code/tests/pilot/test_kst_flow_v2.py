import pytest

torch = pytest.importorskip("torch")

from kaf_profiti.industrial.batch import IndustrialBatch
from kaf_profiti.models.kst_flow import KSTFlowV2, KSTFlowV2Config


def _batch(batch_size=2, history=12, pred=3, sensors=2):
    x = torch.randn(batch_size, history, sensors)
    t = torch.arange(history, dtype=torch.float32).repeat(batch_size, 1)
    m = torch.ones_like(x)
    y = torch.randn(batch_size, pred, sensors)
    mq = torch.ones_like(y)
    return IndustrialBatch(
        X_obs=x,
        T_obs=t,
        M_obs=m,
        T_q=torch.arange(pred).repeat(batch_size, 1).float(),
        Y_q=y,
        M_q=mq,
        context=torch.zeros(batch_size, 1),
        y_flat=y.flatten(1),
        mq_flat=mq.flatten(1),
        query_channel_ids=torch.arange(sensors).repeat(pred),
        rul=torch.zeros(batch_size),
        unit_id=torch.arange(batch_size),
    )


def test_kst_flow_v2_uses_one_finite_distribution_contract():
    model = KSTFlowV2(
        KSTFlowV2Config(num_sensors=2, context_dim=1, hidden_dim=8, te_dim=4, n_heads=2)
    )
    batch = _batch()
    nll = model.batch_nll(batch)
    samples = model.sample_flat(
        batch, nsamples=8, generator=torch.Generator().manual_seed(2026)
    )
    lower, upper = model.interval95_flat(batch)
    assert nll.ndim == 0 and torch.isfinite(nll)
    assert samples.shape == (2, 8, 6)
    assert torch.isfinite(samples).all()
    assert torch.isfinite(lower).all() and torch.isfinite(upper).all()
    assert (upper >= lower).all()


def test_kst_flow_v2_nll_has_joint_flow_gradients():
    model = KSTFlowV2(
        KSTFlowV2Config(num_sensors=2, context_dim=1, hidden_dim=8, te_dim=4, n_heads=2)
    )
    loss = model.batch_nll(_batch())
    loss.backward()
    flow_grads = [
        parameter.grad
        for name, parameter in model.named_parameters()
        if "flow_head" in name and parameter.requires_grad
    ]
    assert flow_grads
    assert all(gradient is not None and torch.isfinite(gradient).all() for gradient in flow_grads)
