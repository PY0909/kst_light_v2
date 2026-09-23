import os
from pathlib import Path

import torch
from torch.utils.data import DataLoader

DATA_ROOT = Path(os.environ.get("KST_DATA_ROOT", "/root/autodl-tmp/dataset"))

from kaf_profiti.experiments.metrics import interval_metrics, point_metrics, risk_score_from_samples
from kaf_profiti.industrial.batch import IndustrialCollator
from kaf_profiti.industrial.cmapss import CMapssWindowDataset
from kaf_profiti.industrial.batch import IndustrialBatch
from kaf_profiti.models.kaf_profiti import KAFProFITi, KAFProFITiConfig
from kaf_profiti.models.kafnet_encoder import MultiScaleKAFEncoder
from kaf_profiti.models.kst_probflow import (
    DynamicSensorGraphBlock,
    KSTProbFlow,
    KSTProbFlowConfig,
    LowRankCopulaFlowHead,
    QuantileHead,
    RiskHead,
)
from kaf_profiti.models.profiti_flow_head import ProFITiFlowHead
from kaf_profiti.models.query_condition_adapter import QueryConditionAdapter


def _make_batch(batch_size=2, history_len=8, pred_len=3, num_sensors=4):
    generator = torch.Generator().manual_seed(11)
    X_obs = torch.randn(batch_size, history_len, num_sensors, generator=generator)
    T_obs = torch.arange(history_len, dtype=torch.float32).repeat(batch_size, 1)
    M_obs = (torch.rand(batch_size, history_len, num_sensors, generator=generator) > 0.2).float()
    X_obs = X_obs * M_obs
    T_q = torch.arange(history_len, history_len + pred_len, dtype=torch.float32).repeat(batch_size, 1)
    Y_q = torch.randn(batch_size, pred_len, num_sensors, generator=generator)
    M_q = torch.ones(batch_size, pred_len, num_sensors)
    context = torch.randn(batch_size, 3, generator=generator)
    query_channel_ids = torch.arange(num_sensors).repeat(pred_len)
    return IndustrialBatch(
        X_obs=X_obs,
        T_obs=T_obs,
        M_obs=M_obs,
        T_q=T_q,
        Y_q=Y_q,
        M_q=M_q,
        context=context,
        y_flat=Y_q.reshape(batch_size, pred_len * num_sensors),
        mq_flat=M_q.reshape(batch_size, pred_len * num_sensors),
        query_channel_ids=query_channel_ids,
        rul=torch.linspace(0.0, 1.0, batch_size),
        unit_id=torch.arange(1, batch_size + 1),
    )


def test_query_condition_adapter_returns_time_first_query_states():
    adapter = QueryConditionAdapter(
        num_sensors=4,
        hidden_dim=16,
        time_dim=5,
        context_dim=3,
        max_len=16,
    )
    z_var = torch.randn(2, 4, 16)
    T_q = torch.tensor([[8.0, 9.0, 10.0], [8.0, 9.0, 10.0]])
    channel_ids = torch.arange(4).repeat(3)
    context = torch.randn(2, 3)

    h_query = adapter(z_var, T_q, channel_ids, context)

    assert h_query.shape == (2, 12, 16)
    assert torch.equal(adapter.build_time_first_channel_ids(3, device=z_var.device), channel_ids)


def test_profiti_flow_head_computes_finite_nll_and_samples():
    head = ProFITiFlowHead(
        hidden_dim=16,
        flow_layers=2,
        marginal_training=False,
        device=torch.device("cpu"),
    )
    y = torch.randn(2, 12)
    hidden_states = torch.randn(2, 12, 16)
    mask = torch.ones(2, 12)

    nll = head.nll(y, hidden_states, mask)
    samples = head.sample(hidden_states, mask, nsamples=5)

    assert nll.shape == (2,)
    assert torch.isfinite(nll).all()
    assert samples.shape == (2, 5, 12)
    assert torch.isfinite(samples).all()


def test_metrics_ignore_non_finite_prediction_values():
    y = torch.tensor([[1.0, 2.0, 3.0, 4.0]])
    mean = torch.tensor([[1.5, float("nan"), float("inf"), 6.0]])
    mask = torch.ones_like(y)
    samples = torch.tensor(
        [
            [
                [1.0, 2.0, float("nan"), 3.0],
                [1.5, float("inf"), 3.0, 4.0],
                [2.0, 2.5, 4.0, float("-inf")],
            ]
        ]
    )

    mae, rmse = point_metrics(y, mean, mask)
    picp, mpiw = interval_metrics(y, samples, mask)
    risk = risk_score_from_samples(samples.reshape(1, 3, 2, 2))

    assert torch.isfinite(torch.tensor([mae, rmse, picp, mpiw])).all()
    assert torch.isfinite(risk).all()


def test_profiti_flow_head_clips_pathological_inverse_samples():
    head = ProFITiFlowHead(
        hidden_dim=16,
        flow_layers=2,
        marginal_training=False,
        device=torch.device("cpu"),
        attention_diag_floor=0.05,
        sample_clip=20.0,
    )
    hidden_states = torch.randn(2, 360, 16) * 8.0
    mask = torch.ones(2, 360)

    samples = head.sample(hidden_states, mask, nsamples=4)

    assert samples.shape == (2, 4, 360)
    assert torch.isfinite(samples).all()
    assert samples.abs().max() <= 20.0


def test_kaf_profiti_loss_backward_smoke():
    batch = _make_batch()
    config = KAFProFITiConfig(
        num_sensors=4,
        context_dim=3,
        hidden_dim=16,
        te_dim=5,
        kernel_count=3,
        n_layers=1,
        n_heads=2,
        flow_layers=2,
        preconv_dim=4,
        lambda_point=0.1,
        device="cpu",
    )
    model = KAFProFITi(config)

    loss = model.loss(batch, nsamples_for_point=3)
    loss.backward()

    grads = [p.grad for p in model.parameters() if p.requires_grad]
    assert torch.isfinite(loss)
    assert any(g is not None and torch.isfinite(g).all() and g.abs().sum() > 0 for g in grads)


def test_kaf_profiti_supports_batch_size_different_from_attention_heads():
    batch = _make_batch(batch_size=3)
    config = KAFProFITiConfig(
        num_sensors=4,
        context_dim=3,
        hidden_dim=16,
        te_dim=5,
        kernel_count=3,
        n_layers=1,
        n_heads=2,
        flow_layers=1,
        preconv_dim=4,
        lambda_point=0.0,
        device="cpu",
    )
    model = KAFProFITi(config)

    loss = model.loss(batch)

    assert torch.isfinite(loss)


def test_default_point_loss_is_finite_on_training_like_batch():
    torch.manual_seed(42)
    batch = _make_batch(batch_size=8, history_len=30, pred_len=5, num_sensors=21)
    config = KAFProFITiConfig(
        num_sensors=21,
        context_dim=3,
        hidden_dim=32,
        te_dim=5,
        kernel_count=4,
        n_layers=2,
        n_heads=2,
        flow_layers=2,
        preconv_dim=8,
        lambda_point=0.1,
        device="cpu",
    )
    model = KAFProFITi(config)

    loss = model.loss(batch, nsamples_for_point=1)

    assert torch.isfinite(loss)


def test_default_point_loss_is_finite_on_real_cmapss_shuffle_batch():
    torch.manual_seed(42)
    dataset = CMapssWindowDataset(
        str(DATA_ROOT / "CMAPSSData"),
        subset="FD001",
        split="train",
        history_len=30,
        pred_len=5,
        stride=1,
        async_mode="mixed",
        seed=42,
    )
    loader = DataLoader(
        dataset,
        batch_size=8,
        shuffle=True,
        collate_fn=IndustrialCollator(),
    )
    config = KAFProFITiConfig(
        num_sensors=21,
        context_dim=3,
        hidden_dim=32,
        te_dim=5,
        kernel_count=4,
        n_layers=2,
        n_heads=2,
        flow_layers=2,
        preconv_dim=8,
        lambda_point=0.1,
        device="cpu",
    )
    model = KAFProFITi(config)
    batch = next(iter(loader))

    loss = model.loss(batch, nsamples_for_point=1)

    assert torch.isfinite(loss)


def test_multiscale_kaf_encoder_handles_missing_values():
    batch = _make_batch(batch_size=3, history_len=24, pred_len=2, num_sensors=5)
    encoder = MultiScaleKAFEncoder(
        num_sensors=5,
        hidden_dim=16,
        kernel_count=3,
        time_dim=5,
        n_layers=1,
        n_heads=2,
        preconv_dim=4,
        patch_lens=(6, 12),
        context_dim=3,
    )

    z = encoder(batch.X_obs, batch.T_obs, batch.M_obs, batch.context)

    assert z.shape == (3, 5, 16)
    assert torch.isfinite(z).all()


def test_multiscale_kaf_encoder_supports_history_shorter_than_patch_lengths():
    batch = _make_batch(batch_size=2, history_len=5, pred_len=2, num_sensors=4)
    encoder = MultiScaleKAFEncoder(
        num_sensors=4,
        hidden_dim=16,
        kernel_count=3,
        time_dim=5,
        n_layers=1,
        n_heads=2,
        preconv_dim=4,
        patch_lens=(12, 24, 48),
        context_dim=3,
    )

    z = encoder(batch.X_obs, batch.T_obs, batch.M_obs, batch.context)

    assert z.shape == (2, 4, 16)
    assert torch.isfinite(z).all()


def test_dynamic_sensor_graph_block_returns_row_normalized_adjacency():
    block = DynamicSensorGraphBlock(num_sensors=5, hidden_dim=16, graph_layers=1)
    z = torch.randn(3, 5, 16)

    out = block(z)
    adjacency = block.last_adjacency

    assert out.shape == z.shape
    assert adjacency.shape == (3, 5, 5)
    assert torch.isfinite(out).all()
    assert torch.allclose(adjacency.sum(dim=-1), torch.ones(3, 5), atol=1e-5)


def test_low_rank_copula_flow_head_computes_finite_nll_and_samples():
    head = LowRankCopulaFlowHead(hidden_dim=16, copula_rank=4, sample_clip=30.0)
    hidden = torch.randn(3, 12, 16)
    y = torch.randn(3, 12)
    mask = torch.ones(3, 12)

    nll = head.nll(y, hidden, mask)
    samples = head.sample(hidden, mask, nsamples=5)
    mean = head.mean(hidden, mask, nsamples=5)

    assert nll.shape == (3,)
    assert samples.shape == (3, 5, 12)
    assert mean.shape == (3, 12)
    assert torch.isfinite(nll).all()
    assert torch.isfinite(samples).all()


def test_quantile_head_outputs_monotonic_quantiles():
    head = QuantileHead(hidden_dim=16, quantiles=(0.025, 0.1, 0.5, 0.9, 0.975))
    hidden = torch.randn(3, 12, 16)

    quantiles = head(hidden)

    assert quantiles.shape == (3, 5, 12)
    assert torch.isfinite(quantiles).all()
    assert torch.all(quantiles[:, 1:, :] >= quantiles[:, :-1, :])


def test_risk_head_outputs_probability_and_finite_loss():
    head = RiskHead(hidden_dim=16)
    z_var = torch.randn(3, 5, 16)
    mean = torch.randn(3, 12)
    variance = torch.rand(3, 12)
    quantile_width = torch.rand(3, 12)
    labels = torch.tensor([0.0, 1.0, 1.0])

    score = head(z_var, mean, variance, quantile_width)
    loss = head.loss(score, labels)

    assert score.shape == (3,)
    assert torch.isfinite(score).all()
    assert ((score >= 0) & (score <= 1)).all()
    assert torch.isfinite(loss)


def test_risk_head_maps_high_normality_logit_to_low_risk():
    head = RiskHead(hidden_dim=16)
    with torch.no_grad():
        for parameter in head.parameters():
            parameter.zero_()
        head.net[-1].bias.fill_(2.0)
    z_var = torch.zeros(2, 5, 16)
    mean = torch.zeros(2, 12)
    variance = torch.zeros(2, 12)
    quantile_width = torch.zeros(2, 12)

    score = head(z_var, mean, variance, quantile_width)

    assert score.shape == (2,)
    assert torch.all(score < 0.2)


def test_kst_probflow_loss_backward_and_probabilistic_outputs():
    batch = _make_batch(batch_size=3, history_len=24, pred_len=3, num_sensors=5)
    config = KSTProbFlowConfig(
        num_sensors=5,
        context_dim=3,
        hidden_dim=16,
        te_dim=5,
        kernel_count=3,
        n_layers=1,
        n_heads=2,
        preconv_dim=4,
        patch_lens=(6, 12),
        graph_layers=1,
        copula_rank=4,
        lambda_point=0.5,
        lambda_quantile=0.2,
        lambda_risk=0.05,
        sample_clip=30.0,
        device="cpu",
    )
    model = KSTProbFlow(config)

    assert not hasattr(model, "patch_encoder")
    assert not hasattr(model, "fusion_gate")

    loss = model.loss(batch)
    loss.backward()
    samples = model.sample(batch, nsamples=4)
    mean = model.predict_mean(batch, nsamples=4)
    quantiles = model.predict_quantiles(batch)
    risk = model.predict_risk(batch, nsamples=4)

    grads = [p.grad for p in model.parameters() if p.requires_grad]
    assert torch.isfinite(loss)
    assert samples.shape == (3, 4, 3, 5)
    assert mean.shape == (3, 15)
    assert quantiles.shape == (3, 5, 15)
    assert risk.shape == (3,)
    assert torch.isfinite(samples).all()
    assert torch.isfinite(quantiles).all()
    assert torch.isfinite(risk).all()
    assert any(g is not None and torch.isfinite(g).all() and g.abs().sum() > 0 for g in grads)
