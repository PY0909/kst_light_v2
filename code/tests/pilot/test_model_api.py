"""CH2.5-P02-T01: unified point/probabilistic model interface tests.

The unified contract lets one trainer and one evaluator serve every model:
point models expose ``predict_point``/``loss``/``parameter_count`` over the
history-only batch fields, probabilistic models additionally expose
``gaussian_params``/``batch_nll``/``sample_flat``/``interval95_flat``. No model
may read ``Y_q``/``y_flat``/``M_q``/``mq_flat``/``rul`` when producing
predictions, and the lightweight heads must only consume encoder history
representations.
"""

import inspect
import math

import pytest
import torch
from torch import nn

from kaf_profiti.experiments.model_api import (
    FORBIDDEN_BATCH_FIELDS,
    Z95,
    assert_history_only,
    check_gaussian_interface,
    check_point_interface,
    masked_mse,
    parameter_count,
)
from kaf_profiti.industrial.batch import IndustrialBatch
from kaf_profiti.models.lightweight_head import (
    DiagonalGaussianHead,
    KSTLight,
    LinearPointHead,
    MLPPointHead,
)

_HISTORY, _PRED, _SENSORS = 8, 3, 4


def _make_batch(batch_size: int = 5, seed: int = 11) -> IndustrialBatch:
    generator = torch.Generator().manual_seed(seed)
    rows = []
    for _ in range(batch_size):
        rows.append(
            (
                torch.randn(_HISTORY, _SENSORS, generator=generator),
                (torch.rand(_PRED, _SENSORS, generator=generator) > 0.25).float(),
            )
        )
    x_obs = torch.stack([row[0] for row in rows])
    m_q = torch.stack([row[1] for row in rows])
    m_q[:, 0] = 1.0
    y_q = torch.randn(batch_size, _PRED, _SENSORS, generator=generator)
    return IndustrialBatch(
        X_obs=x_obs,
        T_obs=torch.arange(_HISTORY, dtype=torch.float32).repeat(batch_size, 1),
        M_obs=(torch.rand(batch_size, _HISTORY, _SENSORS, generator=generator) > 0.2).float(),
        T_q=torch.arange(_HISTORY, _HISTORY + _PRED, dtype=torch.float32).repeat(batch_size, 1),
        Y_q=y_q,
        M_q=m_q,
        context=torch.randn(batch_size, 3, generator=generator),
        y_flat=y_q.reshape(batch_size, -1),
        mq_flat=m_q.reshape(batch_size, -1),
        query_channel_ids=torch.arange(_SENSORS).repeat(_PRED),
        rul=torch.rand(batch_size, generator=generator) * 100.0,
        unit_id=torch.arange(batch_size),
    )


def _kst_light(head_type: str) -> KSTLight:
    return KSTLight(
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


# ---------------------------------------------------------------------------
# Lightweight heads
# ---------------------------------------------------------------------------


def test_diagonal_gaussian_head_scale_bound_and_manual_nll():
    torch.manual_seed(0)
    head = DiagonalGaussianHead(hidden_dim=12, min_scale=0.05)
    hidden = torch.randn(3, _PRED * _SENSORS, 12)
    mean, scale = head(hidden)
    assert head.min_scale == 0.05

    assert mean.shape == (3, _PRED * _SENSORS)
    assert scale.shape == mean.shape
    assert bool((scale >= 0.05).all())

    y = torch.randn_like(mean)
    mask = torch.ones_like(mean)
    nll = head.nll(y, mean, scale, mask)
    log_prob = -0.5 * ((y - mean) / scale).pow(2) - torch.log(scale) - 0.5 * math.log(
        2.0 * math.pi
    )
    expected = -(log_prob * mask).sum() / mask.sum()
    assert float(nll) == pytest.approx(float(expected), rel=1e-6)


def test_diagonal_gaussian_head_sampling_moments_and_interval():
    torch.manual_seed(0)
    head = DiagonalGaussianHead(hidden_dim=12, min_scale=0.02)
    hidden = torch.randn(2, 6, 12)
    mean, scale = head(hidden)

    generator = torch.Generator().manual_seed(2026)
    samples = head.sample(mean, scale, nsamples=4000, generator=generator)
    assert samples.shape == (2, 4000, 6)
    assert bool(torch.isfinite(samples).all())
    assert float(samples.mean(dim=1).sub(mean).abs().max()) < 0.05
    assert float(samples.std(dim=1).div(scale).sub(1.0).abs().max()) < 0.1

    lower, upper = head.interval_95(mean, scale)
    assert torch.allclose(lower, mean - Z95 * scale)
    assert torch.allclose(upper, mean + Z95 * scale)


def test_point_heads_only_consume_history_representation():
    for head in (LinearPointHead(16, 6), MLPPointHead(16, 8, 6)):
        for name, parameter in inspect.signature(head.forward).parameters.items():
            assert name not in FORBIDDEN_BATCH_FIELDS, name
        pooled = head(torch.randn(3, head.input_dim))
        assert pooled.shape == (3, head.output_dim)
        per_query = head(torch.randn(3, _PRED * _SENSORS, head.input_dim))
        assert per_query.shape == (3, _PRED * _SENSORS, head.output_dim)
        assert bool(torch.isfinite(pooled).all()) and bool(torch.isfinite(per_query).all())


def test_linear_head_is_exact_affine_map():
    torch.manual_seed(1)
    head = LinearPointHead(6, 4)
    hidden = torch.randn(2, 5, 6)
    expected = torch.einsum("bqh,ho->bqo", hidden, head.out.weight.T) + head.out.bias
    assert torch.allclose(head(hidden), expected, atol=1e-6)


# ---------------------------------------------------------------------------
# Unified point contract: KST-Light with both heads
# ---------------------------------------------------------------------------


def test_kst_light_linear_and_mlp_pass_point_interface():
    for head_type in ("linear", "mlp"):
        model = _kst_light(head_type)
        batch = _make_batch()
        check_point_interface(model, batch)


def test_kst_light_loss_ignores_masked_targets():
    model = _kst_light("linear")
    batch = _make_batch()
    model.eval()
    with torch.no_grad():
        reference = float(model.loss(batch))

    perturbed = _make_batch(seed=99)
    invalid = batch.mq_flat == 0
    y_flat = batch.y_flat.clone()
    y_flat[invalid] = perturbed.y_flat[invalid]
    y_q = y_flat.reshape(batch.Y_q.shape)
    tampered = IndustrialBatch(
        **{**batch.__dict__, "Y_q": y_q, "y_flat": y_flat}
    )
    with torch.no_grad():
        replay = float(model.loss(tampered))
    assert replay == pytest.approx(reference, rel=1e-6)


def test_kst_light_parameter_count_is_positive_and_matches_sum():
    model = _kst_light("mlp")
    assert model.parameter_count() > 0
    assert model.parameter_count() == parameter_count(model)


# ---------------------------------------------------------------------------
# Unified diagonal-Gaussian contract on a minimal model
# ---------------------------------------------------------------------------


class _TinyGaussian(nn.Module):
    """Contract-compliant diagonal Gaussian model over the history summary."""

    def __init__(self, num_sensors: int, pred_len: int, min_scale: float = 0.05):
        super().__init__()
        self.gaussian_kind = "diagonal"
        self.min_scale = float(min_scale)
        self.lambda_point = 0.1
        self.trunk = nn.Linear(num_sensors, 32)
        self.head = DiagonalGaussianHead(32, min_scale)

    def gaussian_params(self, batch):
        summary = (batch.X_obs * batch.M_obs).sum(dim=1) / batch.M_obs.sum(dim=1).clamp_min(1.0)
        batch_size = summary.shape[0]
        trunk = self.trunk(summary).unsqueeze(1).repeat(1, _PRED * _SENSORS, 1)
        mean, scale = self.head(trunk)
        return mean.reshape(batch_size, _PRED, _SENSORS), scale.reshape(
            batch_size, _PRED, _SENSORS
        )


def test_unified_diagonal_gaussian_contract_passes_and_matches_manual_nll():
    from kaf_profiti.experiments.model_api import UnifiedGaussianModel

    class _ContractGaussian(_TinyGaussian, UnifiedGaussianModel):
        pass

    model = _ContractGaussian(_SENSORS, _PRED)
    batch = _make_batch()
    check_gaussian_interface(model, batch, nsamples=256)

    model.eval()
    with torch.no_grad():
        nll = float(model.batch_nll(batch))
        mean, scale = model.gaussian_params(batch)
    log_prob = -0.5 * ((batch.Y_q - mean) / scale).pow(2) - torch.log(scale) - 0.5 * math.log(
        2.0 * math.pi
    )
    expected = -(log_prob * batch.M_q).sum() / batch.M_q.sum()
    assert nll == pytest.approx(float(expected), rel=1e-5)


def test_gaussian_sample_flat_masked_and_moment_consistent():
    from kaf_profiti.experiments.model_api import UnifiedGaussianModel

    class _ContractGaussian(_TinyGaussian, UnifiedGaussianModel):
        pass

    model = _ContractGaussian(_SENSORS, _PRED)
    model.eval()
    batch = _make_batch()
    generator = torch.Generator().manual_seed(7)
    with torch.no_grad():
        samples = model.sample_flat(batch, nsamples=512, generator=generator)
        point = model.predict_point(batch)
    assert samples.shape == (batch.X_obs.shape[0], 512, _PRED * _SENSORS)
    invalid = batch.mq_flat == 0
    kept = samples * invalid.unsqueeze(1).float()
    assert bool((kept == 0).all()), "sample_flat leaked values at masked-out targets"
    valid = batch.mq_flat > 0
    error = (samples.mean(dim=1) - point).abs()[valid]
    tolerance = 6.0 * samples.std(dim=1)[valid] / math.sqrt(512) + 1e-4
    assert bool((error <= tolerance).all())


# ---------------------------------------------------------------------------
# The interface checks must actually catch violations
# ---------------------------------------------------------------------------


class _FutureReadingPoint(nn.Module):
    def predict_point(self, batch):
        return batch.y_flat.sum(dim=-1, keepdim=True).repeat(1, batch.y_flat.shape[1])

    def loss(self, batch):
        return masked_mse(batch.y_flat, self.predict_point(batch), batch.mq_flat)

    def parameter_count(self):
        return 0


def test_history_only_check_detects_future_reader():
    model = _FutureReadingPoint()
    batch = _make_batch()
    with pytest.raises(AssertionError, match="history"):
        assert_history_only(model, batch, ("predict_point",))
    with pytest.raises(AssertionError, match="history"):
        check_point_interface(model, batch)


class _DeadGradientPoint(nn.Module):
    def __init__(self):
        super().__init__()
        self.dummy = nn.Linear(4, 4)

    def predict_point(self, batch):
        pooled = (batch.X_obs * batch.M_obs).sum(dim=(1, 2))
        return pooled[:, None].expand(-1, _PRED * _SENSORS)

    def loss(self, batch):
        return masked_mse(batch.y_flat, self.predict_point(batch), batch.mq_flat)

    def parameter_count(self):
        return parameter_count(self)


def test_interface_check_detects_dead_gradient():
    with pytest.raises(AssertionError, match="parameter"):
        check_point_interface(_DeadGradientPoint(), _make_batch())


class _MaskIgnoringNLL(_TinyGaussian):
    def batch_nll(self, batch):
        mean, scale = self.gaussian_params(batch)
        residual = (batch.Y_q - mean) / scale
        per_pos = 0.5 * residual.pow(2) + torch.log(scale) + 0.5 * math.log(2.0 * math.pi)
        return per_pos.mean()


def test_gaussian_check_detects_mask_ignoring_nll():
    from kaf_profiti.experiments.model_api import UnifiedGaussianModel

    class _Bad(_MaskIgnoringNLL, UnifiedGaussianModel):
        pass

    with pytest.raises(AssertionError, match="mask"):
        check_gaussian_interface(_Bad(_SENSORS, _PRED), _make_batch(), nsamples=64)
