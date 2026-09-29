"""V2-CH4-CODE-T01: unified probabilistic adapter and head contract.

Pins the chapter-4 surface every matrix model must expose through the
adapter: ``point_mean`` (deterministic for flows = seeded sample mean),
``sample`` ([B,S,P*N], masked-zero, finite), ``quantiles`` (parameterized
levels, monotone non-decreasing), ``nll``; point-only models enter only via
an explicitly attached Gaussian head (``adapted_gaussian``); manifest
identity records head_type/quantile levels; the six unified metrics
(MAE/RMSE/NLL/CRPS/PICP/MPIW) come out finite from evaluate_batches.
"""

import math
import sys
from pathlib import Path

import pytest
import torch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "code"))

from kaf_profiti.experiments.evaluator import (  # noqa: E402
    evaluate_batches,
    require_probabilistic_contract,
)
from kaf_profiti.experiments.model_api import (  # noqa: E402
    UnifiedFlowModel,
    UnifiedGaussianModel,
)
from kaf_profiti.experiments.probabilistic_adapter import (  # noqa: E402
    GaussianHeadPointAdapter,
    ProbabilisticAdapter,
    adapt_probabilistic,
)
from kaf_profiti.industrial.batch import IndustrialBatch  # noqa: E402

B, H, P, N, S = 3, 6, 2, 4, 7


def _batch(seed: int = 0) -> IndustrialBatch:
    generator = torch.Generator().manual_seed(seed)
    Y_q = torch.randn(B, P, N, generator=generator)
    M_q = torch.ones(B, P, N)
    return IndustrialBatch(
        X_obs=torch.randn(B, H, N, generator=generator),
        T_obs=torch.arange(H, dtype=torch.float32).repeat(B, 1),
        M_obs=torch.ones(B, H, N),
        T_q=torch.arange(P, dtype=torch.float32).repeat(B, 1) + H,
        Y_q=Y_q,
        M_q=M_q,
        context=torch.randn(B, 5, generator=generator),
        y_flat=Y_q.reshape(B, P * N),
        mq_flat=M_q.reshape(B, P * N),
        query_channel_ids=torch.arange(N).repeat(P),
        rul=0.0,
        unit_id=torch.arange(B),
        window_id=[f"w{i}" for i in range(B)],
    )


class _TinyDiagonal(UnifiedGaussianModel):
    gaussian_kind = "diagonal"

    def __init__(self):
        super().__init__()
        self.mean = torch.nn.Parameter(torch.zeros(P, N))
        self.log_scale = torch.nn.Parameter(torch.full((P, N), -1.0))

    def gaussian_params(self, batch):
        mean = self.mean.unsqueeze(0).expand(batch.y_flat.shape[0], P, N)
        scale = torch.nn.functional.softplus(self.log_scale).unsqueeze(0).expand(
            batch.y_flat.shape[0], P, N
        )
        return mean, scale


class _TinyFlow(UnifiedFlowModel):
    def __init__(self):
        super().__init__()
        self.loc = torch.nn.Parameter(torch.zeros(P * N))
        self.log_scale = torch.nn.Parameter(torch.full((P * N,), -1.0))

    def flow_hidden(self, batch):
        return torch.zeros(batch.y_flat.shape[0], P * N)

    def _flow_nll_rows(self, y_flat, hidden, mq_flat):
        scale = torch.nn.functional.softplus(self.log_scale)
        log_prob = -0.5 * ((y_flat - self.loc) / scale).pow(2) - torch.log(scale) - 0.5 * math.log(
            2.0 * math.pi
        )
        return -(log_prob * mq_flat).sum(dim=-1)

    def _flow_sample(self, hidden, mq_flat, nsamples, generator=None):
        scale = torch.nn.functional.softplus(self.log_scale)
        eps = torch.randn(hidden.shape[0], nsamples, P * N, generator=generator)
        return self.loc + eps * scale


class _TinyPoint(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.dummy = torch.nn.Parameter(torch.zeros(P * N))

    def predict_point(self, batch):
        return self.dummy.unsqueeze(0).expand(batch.y_flat.shape[0], P * N)

    def loss(self, batch):
        return (self.predict_point(batch) - batch.y_flat).pow(2).mean()


def test_adapter_over_diagonal_model():
    adapter = adapt_probabilistic(_TinyDiagonal())
    assert adapter.head_type == "gaussian_diag"
    batch = _batch()
    mean = adapter.point_mean(batch)
    assert mean.shape == (B, P * N) and torch.isfinite(mean).all()
    samples = adapter.sample(batch, nsamples=S)
    assert samples.shape == (B, S, P * N) and torch.isfinite(samples).all()
    quantiles = adapter.quantiles(batch, levels=(0.05, 0.5, 0.95))
    assert quantiles.shape == (3, B, P * N)
    diffs = (quantiles[1:] - quantiles[:-1]).flatten()
    assert (diffs >= -1e-6).all(), "quantiles must be monotone non-decreasing"
    assert math.isfinite(adapter.nll(batch))
    identity = adapter.manifest_identity()
    assert identity["head_type"] == "gaussian_diag"
    assert identity["gaussian_kind"] == "diagonal"
    assert identity["selection_metric"] == "valid_crps"


def test_adapter_over_flow_model_fixes_point_mean_caliber():
    adapter = adapt_probabilistic(_TinyFlow())
    assert adapter.head_type == "flow"
    batch = _batch()
    first = adapter.point_mean(batch)
    second = adapter.point_mean(batch)
    assert torch.equal(first, second), "flow point_mean must be deterministic (seeded)"
    # caliber: equals the model's own predict_point (seeded sample mean)
    assert torch.allclose(first, adapter.model.predict_point(batch))
    quantiles = adapter.quantiles(batch, levels=(0.025, 0.975))
    assert ((quantiles[1] - quantiles[0]) > 0).all()
    identity = adapter.manifest_identity()
    assert identity["head_type"] == "flow"
    assert identity["point_nsamples"] == adapter.model.point_nsamples
    assert identity["point_seed"] == adapter.model.point_seed


def test_gaussian_head_adapter_for_point_models():
    point_model = _TinyPoint()
    adapter = adapt_probabilistic(point_model, explicit_gaussian_head=True)
    assert adapter.head_type == "adapted_gaussian"
    assert isinstance(adapter.model, GaussianHeadPointAdapter)
    batch = _batch()
    mean = adapter.point_mean(batch)
    assert torch.allclose(mean, point_model.predict_point(batch).reshape(B, P, N).reshape(B, P * N))
    assert math.isfinite(adapter.nll(batch))
    samples = adapter.sample(batch, nsamples=S)
    assert samples.shape == (B, S, P * N) and torch.isfinite(samples).all()
    quantiles = adapter.quantiles(batch, levels=(0.1, 0.9))
    assert ((quantiles[1] - quantiles[0]) > 0).all()
    # the scale is a real trainable parameter: one AdamW step moves it
    before = adapter.model.log_scale.detach().clone()
    optimizer = torch.optim.AdamW(adapter.model.parameters(), lr=1e-2)
    optimizer.zero_grad()
    adapter.model.loss(batch).backward()
    optimizer.step()
    assert not torch.equal(before, adapter.model.log_scale.detach())


def test_point_model_without_explicit_head_is_rejected():
    with pytest.raises(ValueError, match="probabilistic"):
        adapt_probabilistic(_TinyPoint())


def test_require_probabilistic_contract_accepts_and_rejects():
    batch = _batch()
    require_probabilistic_contract(_TinyDiagonal(), batch=batch)  # no raise
    require_probabilistic_contract(_TinyFlow(), batch=batch)  # no raise
    with pytest.raises(ValueError, match="sample_flat"):
        require_probabilistic_contract(_TinyPoint(), batch=batch)


def test_require_probabilistic_contract_flags_inverted_intervals():
    class _Broken(_TinyDiagonal):
        def interval95_flat(self, batch):
            lower, upper = super().interval95_flat(batch)
            return upper, lower  # a broken head could invert the interval

    batch = _batch()
    with pytest.raises(ValueError, match="monotone|interval"):
        require_probabilistic_contract(_Broken(), batch=batch)


def test_unified_metrics_finite_over_adapter_outputs():
    adapter = adapt_probabilistic(_TinyDiagonal())
    batch = _batch()
    mean = adapter.point_mean(batch)
    samples = adapter.sample(batch, nsamples=64)
    nll = adapter.nll(batch)
    mapping = {
        "target": batch.y_flat,
        "prediction": mean.reshape(B, -1),
        "mask": batch.mq_flat,
        "nll_sum": torch.full((), float(nll) * float(batch.mq_flat.sum())),
        "crps_sum": torch.full((), 0.5),
        "samples": samples,
    }
    metrics = evaluate_batches([mapping], track="probabilistic")
    for field in ("mae", "rmse", "nll", "crps", "picp", "mpiw"):
        value = metrics[field]
        assert value is not None and math.isfinite(value) and value >= 0.0, field
    assert 0.0 <= metrics["picp"] <= 1.0


def test_factory_baseline_models_adapt_cleanly():
    """The compare_code factory baselines must pass the same adapter surface
    (guards against interface drift between the adapter and real models)."""

    from kaf_profiti.baselines.probabilistic import create_probabilistic_baseline

    for model_id, head in (
        ("tcn_gaussian", "gaussian_diag"),
        ("gru_d_gaussian", "gaussian_diag"),
        ("profiti", "flow"),
    ):
        model = create_probabilistic_baseline(
            model_id, num_sensors=N, context_dim=5, pred_len=P, hidden_dim=8,
        )
        adapter = adapt_probabilistic(model)
        assert adapter.head_type == head, model_id
        batch = _batch()
        require_probabilistic_contract(model, batch=batch)
        quantiles = adapter.quantiles(batch, levels=(0.1, 0.9))
        assert ((quantiles[1] - quantiles[0]) > 0).all()


def test_gaussian_head_eager_construction_covers_optimizer_ordering():
    """Review remediation: with num_flat the scale parameter exists before any
    forward, so an optimizer built first (the trainer's ordering) trains it."""

    adapter = adapt_probabilistic(
        _TinyPoint(), explicit_gaussian_head=True, num_flat=P * N
    )
    assert adapter.model.log_scale is not None
    # optimizer built BEFORE any forward still sees the parameter
    before = adapter.model.log_scale.detach().clone()
    optimizer = torch.optim.AdamW(
        [p for p in adapter.model.parameters() if p.requires_grad], lr=1e-2
    )
    batch = _batch()
    optimizer.zero_grad()
    adapter.model.loss(batch).backward()
    optimizer.step()
    assert not torch.equal(before, adapter.model.log_scale.detach())


def test_adapter_distribution_accessor():
    diagonal = adapt_probabilistic(_TinyDiagonal())
    flow = adapt_probabilistic(_TinyFlow())
    batch = _batch()
    diag_dist = diagonal.distribution(batch)
    assert diag_dist["kind"] == "diagonal_gaussian"
    assert diag_dist["mean"].shape == (B, P, N)
    assert (diag_dist["scale"] > 0).all()
    flow_dist = flow.distribution(batch)
    assert flow_dist["kind"] == "flow_samples"
    assert flow_dist["sample_accessor"] == "sample"


def test_registry_kst_flow_v2_adapter_end_to_end():
    from kaf_profiti.experiments.registry import create_model

    model = create_model(
        "kst_flow_v2", num_sensors=N, context_dim=5, device="cpu",
        hidden_dim=8, patch_lens=(2, 3), pred_len=P,
    )
    adapter = adapt_probabilistic(model)
    assert adapter.head_type == "flow"
    batch = _batch()
    require_probabilistic_contract(model, batch=batch)
    assert torch.equal(adapter.point_mean(batch), adapter.point_mean(batch))
    identity = adapter.manifest_identity()
    assert identity["head_type"] == "flow"
    assert identity["gaussian_kind"] == "flow"
