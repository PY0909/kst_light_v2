"""V2-CH3 review remediation: GRU-D hidden-state decay upgrade.

The original GRU-D (Che et al., 2018) decays BOTH the input (toward the
empirical mean) AND the hidden state (toward the previous hidden state)
between observations. The prior adaptation omitted the hidden decay; these
tests pin the upgraded encoder: per-hidden-unit learnable decay applied on
the GRU-cell path using the same Δt recursion, gradient flow through the new
rate, time-stretch sensitivity, and full regression of the existing input
mechanics.
"""

import sys
from pathlib import Path

import torch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "code"))

from kaf_profiti.baselines.point import GRUDEncoder, GRUDPoint  # noqa: E402
from kaf_profiti.industrial.batch import IndustrialBatch  # noqa: E402

B, H, N, HIDDEN = 3, 5, 4, 8


def _batch(mask_last_missing: bool = True, time_scale: float = 1.0) -> IndustrialBatch:
    generator = torch.Generator().manual_seed(7)
    M_obs = torch.ones(B, H, N)
    if mask_last_missing:
        M_obs[:, -1, :] = 0.0  # last step fully missing → hidden decay active
    X = torch.randn(B, H, N, generator=generator) * M_obs
    T_obs = (torch.arange(H, dtype=torch.float32) * time_scale).repeat(B, 1)
    Y = torch.randn(B, 2, N, generator=generator)
    return IndustrialBatch(
        X_obs=X, T_obs=T_obs, M_obs=M_obs,
        T_q=T_obs[:, -1:] + torch.arange(1, 3, dtype=torch.float32), Y_q=Y, M_q=torch.ones_like(Y),
        context=torch.randn(B, 2, generator=generator),
        y_flat=Y.reshape(B, -1), mq_flat=torch.ones_like(Y.reshape(B, -1)),
        query_channel_ids=torch.arange(N).repeat(2),
        rul=0.0, unit_id=torch.arange(B), window_id=["w0", "w1", "w2"],
    )


def test_hidden_decay_parameters_exist_and_flow_gradient():
    encoder = GRUDEncoder(num_sensors=N, hidden_dim=HIDDEN)
    assert hasattr(encoder, "hidden_decay_rate"), "upgraded encoder must carry hidden_decay_rate"
    assert encoder.hidden_decay_rate.shape == (HIDDEN,), "per-hidden-unit diagonal rate"
    batch = _batch()
    out = encoder(batch)
    out.sum().backward()
    assert encoder.hidden_decay_rate.grad is not None
    assert encoder.hidden_decay_rate.grad.abs().sum() > 0, "decay rate receives gradient"


def test_hidden_decay_is_time_sensitive():
    """Stretching the timeline (larger Δt) must change the representation via
    the HIDDEN path — input decay is disabled (softplus≈0) so any sensitivity
    can only come from the hidden-state decay itself."""

    torch.manual_seed(11)
    encoder = GRUDEncoder(num_sensors=N, hidden_dim=HIDDEN)
    with torch.no_grad():
        encoder.decay_rate.fill_(-20.0)  # softplus≈0 → input decay inert
        near = encoder(_batch(mask_last_missing=True, time_scale=1.0))
        far = encoder(_batch(mask_last_missing=True, time_scale=4.0))
    assert not torch.allclose(near, far), "hidden decay must respond to Δt"


def test_hidden_decay_changes_output_when_active():
    """With the last step missing, hidden decay must alter the encoder output
    relative to a zero-rate (disabled) decay — proving the mechanism bites."""

    encoder = GRUDEncoder(num_sensors=N, hidden_dim=HIDDEN)
    with torch.no_grad():
        active = encoder(_batch(mask_last_missing=True))
        # simulate disabled hidden decay by zeroing the softplus input
        encoder.hidden_decay_rate.fill_(-20.0)  # softplus(-20) ≈ 0 → no decay
        disabled = encoder(_batch(mask_last_missing=True))
    assert not torch.allclose(active, disabled)


def test_input_decay_regression_preserved():
    """The existing input mechanics stay intact: decay rate parameter, Δt
    recursion features, fully-observed batch path."""

    encoder = GRUDEncoder(num_sensors=N, hidden_dim=HIDDEN)
    assert encoder.decay_rate.shape == (N,)
    out = encoder(_batch(mask_last_missing=False))
    assert out.shape == (B, HIDDEN) and torch.isfinite(out).all()


def test_grud_point_source_identity_updated():
    model = GRUDPoint(num_sensors=N, context_dim=2, pred_len=2, hidden_dim=HIDDEN)
    assert "hidden-state decay" in model.SOURCE_IDENTITY or "hidden decay" in model.SOURCE_IDENTITY, (
        "SOURCE_IDENTITY must describe the full dual-decay implementation"
    )
    assert "no hidden-state decay" not in model.SOURCE_IDENTITY
    batch = _batch()
    loss = model.loss(batch)
    loss.backward()
    encoder = model.encoder
    assert encoder.hidden_decay_rate.grad.abs().sum() > 0, (
        "the point model trains the hidden decay end to end"
    )


def test_grud_point_tq_invariance_regression():
    model = GRUDPoint(num_sensors=N, context_dim=2, pred_len=2, hidden_dim=HIDDEN)
    model.eval()
    batch = _batch()
    with torch.no_grad():
        first = model.predict_point(batch)
        batch.T_q = batch.T_q * 3.0 + 100.0  # perturb query times only
        second = model.predict_point(batch)
    assert torch.allclose(first, second), "history-only contract must hold"
