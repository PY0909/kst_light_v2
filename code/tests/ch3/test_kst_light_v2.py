import pytest

torch = pytest.importorskip("torch")
from torch import Tensor

from kaf_profiti.industrial.batch import IndustrialBatch
from kaf_profiti.models.kst_light import KSTLightV2, KSTLightV2Config


def _batch(batch_size=2, history=12, pred=3, sensors=2):
    x = torch.randn(batch_size, history, sensors)
    t = torch.arange(history, dtype=torch.float32).repeat(batch_size, 1)
    m = torch.ones_like(x)
    y = torch.randn(batch_size, pred, sensors)
    mq = torch.ones_like(y)
    return IndustrialBatch(
        X_obs=x, T_obs=t, M_obs=m, T_q=torch.arange(pred).repeat(batch_size, 1).float(),
        Y_q=y, M_q=mq, context=torch.zeros(batch_size, 1), y_flat=y.flatten(1),
        mq_flat=mq.flatten(1), query_channel_ids=torch.arange(sensors).repeat(pred),
        rul=torch.zeros(batch_size), unit_id=torch.arange(batch_size),
    )


def test_kst_light_v2_returns_residual_point_shape_and_finite_loss():
    model = KSTLightV2(KSTLightV2Config(num_sensors=2, context_dim=1, hidden_dim=8, te_dim=4, n_heads=2))
    batch = _batch()
    pred = model.predict_point(batch)
    assert pred.shape == batch.y_flat.shape
    assert torch.isfinite(pred).all()
    loss = model.loss(batch)
    assert loss.ndim == 0 and torch.isfinite(loss)
    loss.backward()
    assert any(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters())


def test_masked_fill_value_does_not_change_kst_light_v2_prediction():
    model = KSTLightV2(KSTLightV2Config(num_sensors=2, context_dim=1, hidden_dim=8, te_dim=4, n_heads=2))
    batch = _batch()
    batch.M_obs[:, 3:6, 1] = 0
    changed = IndustrialBatch(**{**batch.__dict__, "X_obs": batch.X_obs + (1 - batch.M_obs) * 1000.0})
    model.eval()
    with torch.no_grad():
        assert torch.allclose(model.predict_point(batch), model.predict_point(changed), atol=1e-5)
