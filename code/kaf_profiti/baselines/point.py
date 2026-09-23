"""Chapter-3 point baselines on the unified pilot interface (CH2.5-P02-T02).

All five baselines share the unified lightweight Linear point head and the
masked-MSE loss from :mod:`kaf_profiti.experiments.model_api`, so their
differences come only from the encoder and the history-only missing-data
adapter. ``fill_value`` defaults to ``0.0``, which equals the train-only mean
in the frozen normalized space; fills never touch targets or future context.

Every class carries an honest implementation identity:

* ``IMPLEMENTATION`` — ``"adapted"`` when the mechanism is faithful but the
  realization is simplified (all five), ``"own"`` for the project model.
* ``SOURCE_IDENTITY`` — plain-text citation of the source mechanism.
* ``REQUIRES_TIME_INPUT`` — whether the model consumes real timestamps.
* ``ADAPTER`` — the preregistered missing-data adapter description.
"""

from typing import Callable

import torch
from torch import Tensor, nn

from kaf_profiti.experiments.model_api import UnifiedPointModel
from kaf_profiti.models.lightweight_head import LinearPointHead


# ---------------------------------------------------------------------------
# History-only missing-data adapters
# ---------------------------------------------------------------------------


def _expand_time(t: Tensor, reference: Tensor) -> Tensor:
    """Expand ``[B, L]`` (or scalar) timestamps to the ``[B, L, N]`` grid."""

    if t.dim() == 1:
        t = t.unsqueeze(0)
    if t.dim() == 2:
        t = t.unsqueeze(-1)
    return t.expand_as(reference)


def _scan_previous_observation(x: Tensor, mask: Tensor, t: Tensor):
    """Per position: last observed value/time before l and whether one exists."""

    batch, length, _ = x.shape
    prev_value = torch.zeros_like(x)
    prev_time = torch.zeros_like(t)
    has_prev = torch.zeros(x.shape[0], length, x.shape[2], dtype=torch.bool, device=x.device)
    value = torch.zeros_like(x[:, 0])
    time = torch.zeros_like(t[:, 0])
    seen = torch.zeros_like(value, dtype=torch.bool)
    for l in range(length):
        prev_value[:, l] = value
        prev_time[:, l] = time
        has_prev[:, l] = seen
        observed = mask[:, l] > 0
        value = torch.where(observed, x[:, l], value)
        time = torch.where(observed, t[:, l], time)
        seen = seen | observed
    return prev_value, prev_time, has_prev


def _scan_next_observation(x: Tensor, mask: Tensor, t: Tensor):
    """Per position: next observed value/time after l and whether one exists."""

    batch, length, _ = x.shape
    next_value = torch.zeros_like(x)
    next_time = torch.zeros_like(t)
    has_next = torch.zeros(x.shape[0], length, x.shape[2], dtype=torch.bool, device=x.device)
    value = torch.zeros_like(x[:, 0])
    time = torch.zeros_like(t[:, 0])
    seen = torch.zeros_like(value, dtype=torch.bool)
    for l in reversed(range(length)):
        next_value[:, l] = value
        next_time[:, l] = time
        has_next[:, l] = seen
        observed = mask[:, l] > 0
        value = torch.where(observed, x[:, l], value)
        time = torch.where(observed, t[:, l], time)
        seen = seen | observed
    return next_value, next_time, has_next


def linear_interpolate_fill(
    x: Tensor, mask: Tensor, t: Tensor, fill_value: float = 0.0
) -> Tensor:
    """Fill missing history positions by interpolation over real timestamps.

    Interior gaps interpolate linearly in time between the surrounding
    observed values; trailing gaps hold the last observation; leading gaps and
    fully unobserved channels fall back to ``fill_value`` (train-only). All
    values used lie inside the history window.
    """

    time = _expand_time(t, x)
    x = torch.where(mask > 0, x, torch.zeros_like(x))
    prev_value, prev_time, has_prev = _scan_previous_observation(x, mask, time)
    next_value, next_time, has_next = _scan_next_observation(x, mask, time)

    both = has_prev & has_next
    gap = (next_time - prev_time).clamp_min(1e-8)
    weight = ((time - prev_time) / gap).clamp(0.0, 1.0)
    interpolated = prev_value + weight * (next_value - prev_value)

    filled = torch.where(both, interpolated, prev_value)
    filled = torch.where(has_prev, filled, torch.full_like(filled, fill_value))
    return torch.where(mask > 0, x, filled)


def forward_fill(x: Tensor, mask: Tensor, fill_value: float = 0.0) -> Tensor:
    """Carry the last observation forward; leading gaps use ``fill_value``."""

    length = x.shape[1]
    x = torch.where(mask > 0, x, torch.zeros_like(x))
    value = torch.full_like(x[:, 0], fill_value)
    filled = torch.zeros_like(x)
    for l in range(length):
        value = torch.where(mask[:, l] > 0, x[:, l], value)
        filled[:, l] = value
    return filled


def compute_delta_t(t: Tensor, mask: Tensor) -> Tensor:
    """GRU-D elapsed-time-since-last-observation with shape ``[B, L, N]``.

    Implements the GRU-D recursion ``delta_l = dt_l + delta_{l-1} *
    (1 - m_{l-1})`` with ``delta_0 = 0``, then zeroes delta at observed
    positions (an observation is its own last observation).
    """

    if t.dim() == 1:
        t = t.unsqueeze(0)
    time = _expand_time(t, mask)
    length = mask.shape[1]
    delta = torch.zeros_like(time)
    for l in range(1, length):
        step = (time[:, l] - time[:, l - 1]).clamp_min(0.0)
        carried = delta[:, l - 1] * (1.0 - mask[:, l - 1])
        delta[:, l] = step + carried
    return torch.where(mask > 0, torch.zeros_like(delta), delta)


def _context_sequence(context: Tensor, length: int) -> Tensor:
    """Broadcast the static operating-condition vector over time steps."""

    return context.unsqueeze(1).expand(-1, length, -1)


# ---------------------------------------------------------------------------
# Causal TCN backbone (adapted from the TCN-Gaussian reference, point-only)
# ---------------------------------------------------------------------------


class _ChompConv1d(nn.Conv1d):
    """Causal convolution that drops the padding lookahead."""

    def forward(self, x: Tensor) -> Tensor:
        return super().forward(x)[:, :, : -self.padding[0]]


class _TemporalBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, kernel_size: int, dropout: float):
        super().__init__()
        self.conv1 = _ChompConv1d(
            in_channels, out_channels, kernel_size, padding=(kernel_size - 1) * 1
        )
        self.conv2 = _ChompConv1d(
            out_channels, out_channels, kernel_size, padding=(kernel_size - 1) * 1
        )
        self.dropout = nn.Dropout(dropout)
        self.downsample = (
            nn.Identity() if in_channels == out_channels else nn.Conv1d(in_channels, out_channels, 1)
        )
        self.activation = nn.ReLU()

    def forward(self, x: Tensor) -> Tensor:
        residual = self.downsample(x)
        out = self.activation(self.conv1(x))
        out = self.dropout(out)
        out = self.activation(self.conv2(out))
        out = self.dropout(out)
        return self.activation(out + residual)


class CausalTCN(nn.Module):
    """Stack of causal dilated temporal blocks; returns the last hidden step."""

    def __init__(
        self,
        input_dim: int,
        hidden_dim: int,
        levels: int = 4,
        kernel_size: int = 3,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.input_proj = nn.Linear(input_dim, hidden_dim)
        blocks = []
        channels = hidden_dim
        for level in range(levels):
            blocks.append(
                _TemporalBlock(channels, channels, kernel_size, dropout)
            )
        self.blocks = nn.ModuleList(blocks)

    def forward(self, features: Tensor) -> Tensor:
        # features: [B, L, F] -> conv layout [B, F, L]; causal, so the last
        # step only sees history.
        hidden = self.input_proj(features).transpose(1, 2)
        for block in self.blocks:
            hidden = block(hidden)
        return hidden[:, :, -1]


# ---------------------------------------------------------------------------
# Point baselines
# ---------------------------------------------------------------------------


class _PooledPointBaseline(UnifiedPointModel):
    """Shared skeleton: encode history to ``[B, H]`` then the unified head."""

    def __init__(self, num_sensors: int, context_dim: int, pred_len: int, hidden_dim: int):
        super().__init__()
        self.num_sensors = int(num_sensors)
        self.context_dim = int(context_dim)
        self.pred_len = int(pred_len)
        self.hidden_dim = int(hidden_dim)
        self.head = LinearPointHead(hidden_dim, pred_len * num_sensors)

    def encode_history(self, batch) -> Tensor:
        raise NotImplementedError

    def predict_point(self, batch) -> Tensor:
        return self.head(self.encode_history(batch))


class LITCNPoint(_PooledPointBaseline):
    """Linear interpolation inside history + causal TCN encoder."""

    IMPLEMENTATION = "adapted"
    SOURCE_IDENTITY = (
        "Linear interpolation over real history timestamps (Che et al., 2018, "
        "GRU-D-style interpolation baseline) feeding a causal dilated TCN "
        "encoder (Bai et al., 2018); TCN backbone adapted from the project's "
        "TCN-Gaussian reference with the Gaussian parts removed"
    )
    REQUIRES_TIME_INPUT = True
    ADAPTER = (
        "history-only linear interpolation between observed neighbors in real "
        "time; leading gaps and fully unobserved channels use the train-only "
        "fill value (0.0 in the frozen normalized space)"
    )

    def __init__(
        self,
        num_sensors: int,
        context_dim: int,
        pred_len: int,
        hidden_dim: int = 64,
        levels: int = 4,
        kernel_size: int = 3,
        dropout: float = 0.1,
        fill_value: float = 0.0,
    ):
        super().__init__(num_sensors, context_dim, pred_len, hidden_dim)
        self.fill_value = float(fill_value)
        self.tcn = CausalTCN(
            2 * num_sensors + context_dim, hidden_dim, levels, kernel_size, dropout
        )

    def encode_history(self, batch) -> Tensor:
        filled = linear_interpolate_fill(
            batch.X_obs, batch.M_obs, batch.T_obs, self.fill_value
        )
        features = torch.cat(
            [filled, batch.M_obs, _context_sequence(batch.context, filled.shape[1])], dim=-1
        )
        return self.tcn(features)


class FFGRUPoint(_PooledPointBaseline):
    """Forward fill inside history + unidirectional GRU encoder."""

    IMPLEMENTATION = "adapted"
    SOURCE_IDENTITY = (
        "Forward-fill missing-data adapter with a unidirectional GRU encoder "
        "(Cho et al., 2014); last-observation carry-forward inside the history "
        "window only"
    )
    REQUIRES_TIME_INPUT = False
    ADAPTER = (
        "history-only forward fill; leading gaps and fully unobserved channels "
        "use the train-only fill value (0.0 in the frozen normalized space)"
    )

    def __init__(
        self,
        num_sensors: int,
        context_dim: int,
        pred_len: int,
        hidden_dim: int = 64,
        num_layers: int = 1,
        fill_value: float = 0.0,
    ):
        super().__init__(num_sensors, context_dim, pred_len, hidden_dim)
        self.fill_value = float(fill_value)
        self.gru = nn.GRU(2 * num_sensors + context_dim, hidden_dim, batch_first=True)

    def encode_history(self, batch) -> Tensor:
        filled = forward_fill(batch.X_obs, batch.M_obs, self.fill_value)
        features = torch.cat(
            [filled, batch.M_obs, _context_sequence(batch.context, filled.shape[1])], dim=-1
        )
        _, hidden = self.gru(features)
        return hidden[-1]


class MaskedTCNPoint(_PooledPointBaseline):
    """Masked input TCN: no imputation, mask is an explicit input channel."""

    IMPLEMENTATION = "adapted"
    SOURCE_IDENTITY = (
        "Masked-input causal TCN: features are concat(X*M, M, context) with no "
        "imputation; TCN backbone adapted from the project's TCN-Gaussian "
        "reference (Bai et al., 2018) with the Gaussian parts removed"
    )
    REQUIRES_TIME_INPUT = False
    ADAPTER = (
        "no fill: masked-out positions are zeroed and the observation mask is "
        "concatenated as input channels, so the model sees exactly what was "
        "observed in history"
    )

    def __init__(
        self,
        num_sensors: int,
        context_dim: int,
        pred_len: int,
        hidden_dim: int = 64,
        levels: int = 4,
        kernel_size: int = 3,
        dropout: float = 0.1,
    ):
        super().__init__(num_sensors, context_dim, pred_len, hidden_dim)
        self.tcn = CausalTCN(
            2 * num_sensors + context_dim, hidden_dim, levels, kernel_size, dropout
        )

    def encode_history(self, batch) -> Tensor:
        observed = batch.X_obs * batch.M_obs
        features = torch.cat(
            [observed, batch.M_obs, _context_sequence(batch.context, batch.X_obs.shape[1])],
            dim=-1,
        )
        return self.tcn(features)


class GRUDEncoder(nn.Module):
    """Shared GRU-D history encoder (mask + delta_t + learnable input decay).

    Consumes ``[x_hat, M, delta_t]`` where ``x_hat`` decays missing values as
    ``exp(-softplus(rate)*delta_t)`` toward ``fill_value`` and returns the last
    GRU hidden state ``[B, H]``. Shared by the point and Gaussian GRU-D
    baselines so both speak the identical time mechanism.
    """

    def __init__(
        self,
        num_sensors: int,
        hidden_dim: int,
        num_layers: int = 1,
        fill_value: float = 0.0,
    ):
        super().__init__()
        self.num_sensors = int(num_sensors)
        self.fill_value = float(fill_value)
        self.decay_rate = nn.Parameter(torch.full((num_sensors,), 0.5))
        self.gru = nn.GRU(
            3 * num_sensors, hidden_dim, num_layers=int(num_layers), batch_first=True
        )

    def forward(self, batch) -> Tensor:
        delta = compute_delta_t(batch.T_obs, batch.M_obs)
        last_observed = forward_fill(batch.X_obs, batch.M_obs, self.fill_value)
        gamma = torch.exp(-torch.nn.functional.softplus(self.decay_rate) * delta)
        decayed_missing = gamma * last_observed + (1.0 - gamma) * self.fill_value
        x_hat = torch.where(batch.M_obs > 0, batch.X_obs, decayed_missing)
        features = torch.cat([x_hat, batch.M_obs, delta], dim=-1)
        _, hidden = self.gru(features)
        return hidden[-1]


class GRUDPoint(_PooledPointBaseline):
    """GRU-D input decay: mask + delta_t + learnable per-sensor decay."""

    IMPLEMENTATION = "adapted"
    SOURCE_IDENTITY = (
        "GRU-D (Che et al., 2018): the model consumes the observation mask, "
        "the elapsed time since the last observation and a learnable "
        "exponential input decay toward the train mean; adapted: one learnable "
        "non-negative decay rate per sensor instead of a per-feature affine "
        "rate map, and no hidden-state decay term"
    )
    REQUIRES_TIME_INPUT = True
    ADAPTER = (
        "native sparse input: missing values decay as "
        "exp(-softplus(rate)*delta_t) toward the train-only fill value (0.0 in "
        "the frozen normalized space); delta_t follows the GRU-D recursion over "
        "the final shared mask"
    )

    def __init__(
        self,
        num_sensors: int,
        context_dim: int,
        pred_len: int,
        hidden_dim: int = 64,
        num_layers: int = 1,
        fill_value: float = 0.0,
    ):
        super().__init__(num_sensors, context_dim, pred_len, hidden_dim)
        self.encoder = GRUDEncoder(num_sensors, hidden_dim, num_layers, fill_value)

    def encode_history(self, batch) -> Tensor:
        return self.encoder(batch)


class ODERNNPoint(_PooledPointBaseline):
    """ODE-RNN: hidden state evolves by real historical inter-event times."""

    IMPLEMENTATION = "adapted"
    SOURCE_IDENTITY = (
        "ODE-RNN (Rubanova et al., 2019, latent ODE): the hidden state evolves "
        "by the real elapsed time between historical observations and is "
        "updated by a GRUCell at each observation step; adapted: Euler "
        "integration with a learned tanh vector field instead of a black-box "
        "adjoint ODE solver. The Euler expansion is multiplicative over the "
        "time gap, which makes it sensitive to gradient scale; training "
        "therefore relies on the shared global grad-norm clip (1.0, the "
        "repository's established recipe) — without clipping this adapted "
        "implementation diverges (2026-09-17 local diagnostic: grad-norm "
        "peaks ~6.6e7, valid MAE 9.30 vs persistence floor 0.9159)"
    )
    REQUIRES_TIME_INPUT = True
    ADAPTER = (
        "native sparse input: values enter as X*M with the mask as an input "
        "channel; the hidden state integrates over real T_obs gaps within the "
        "history window and never reads T_q or any future field"
    )

    def __init__(
        self,
        num_sensors: int,
        context_dim: int,
        pred_len: int,
        hidden_dim: int = 64,
    ):
        super().__init__(num_sensors, context_dim, pred_len, hidden_dim)
        self.input_proj = nn.Linear(2 * num_sensors + context_dim, hidden_dim)
        self.cell = nn.GRUCell(hidden_dim, hidden_dim)
        self.dynamics = nn.Linear(hidden_dim, hidden_dim)
        self.initial_hidden = nn.Parameter(torch.zeros(hidden_dim))

    def _evolve(self, hidden: Tensor, dt: Tensor) -> Tensor:
        """Euler integration of the learned vector field over real time ``dt``.

        Each batch element advances exactly ``dt`` in total; the substep count
        scales with the largest gap in the batch so fractional gaps are still
        integrated (at least one substep whenever any gap is positive).
        """

        if dt.numel() == 0:
            return hidden
        max_gap = float(dt.max().item())
        if max_gap <= 1e-12:
            return hidden
        steps = max(1, int(round(max_gap)))
        sub = (dt / steps).unsqueeze(-1)
        for _ in range(steps):
            hidden = hidden + sub * torch.tanh(self.dynamics(hidden))
        return hidden

    def encode_history(self, batch) -> Tensor:
        observed = batch.X_obs * batch.M_obs
        features = torch.cat(
            [observed, batch.M_obs, _context_sequence(batch.context, batch.X_obs.shape[1])],
            dim=-1,
        )
        projected = self.input_proj(features)
        time = batch.T_obs if batch.T_obs.dim() == 2 else batch.T_obs.squeeze(-1)
        hidden = self.initial_hidden.unsqueeze(0).expand(features.shape[0], -1).contiguous()
        for l in range(features.shape[1]):
            dt = (time[:, l] - time[:, l - 1]).clamp_min(0.0) if l else torch.zeros_like(time[:, 0])
            hidden = self._evolve(hidden, dt)
            hidden = self.cell(projected[:, l], hidden)
        return hidden


_POINT_FACTORIES = {
    "li_tcn": LITCNPoint,
    "ff_gru": FFGRUPoint,
    "masked_tcn": MaskedTCNPoint,
    "gru_d": GRUDPoint,
    "ode_rnn": ODERNNPoint,
}


def create_point_baseline(name: str, num_sensors: int, context_dim: int, pred_len: int, head_type: str = "linear", **kwargs):
    """Instantiate a registered point baseline by its matrix ``model_id`` and ``head_type``."""

    try:
        factory: Callable = _POINT_FACTORIES[name]
    except KeyError as exc:
        raise KeyError(f"Unknown point baseline: {name}") from exc
    if head_type != "linear":
        raise ValueError(f"Point baseline {name} only supports head_type='linear'")
    return factory(
        num_sensors=num_sensors, context_dim=context_dim, pred_len=pred_len, **kwargs
    )
