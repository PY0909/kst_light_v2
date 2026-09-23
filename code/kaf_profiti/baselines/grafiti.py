"""GraFITi Gaussian baseline on the unified distribution API (CH2.5-P02-T03).

GraFITi (Yalavarthi et al., 2024) forecasts irregularly sampled series by
message passing over a graph whose nodes couple variables and observation
times. This pilot realization keeps the declared mechanism — cross-sensor
graph propagation whose strength decays with the real time gap since the last
propagation step — and feeds the pooled graph states to the unified diagonal
Gaussian head.
"""

import torch
from torch import Tensor, nn

from kaf_profiti.experiments.model_api import UnifiedGaussianModel
from kaf_profiti.models.lightweight_head import DiagonalGaussianHead


class GraFITiGaussian(UnifiedGaussianModel):
    """Time-decayed sensor-graph encoder + unified diagonal Gaussian head."""

    IMPLEMENTATION = "adapted"
    SOURCE_IDENTITY = (
        "GraFITi (Yalavarthi et al., 2024): irregular time series forecasting "
        "as graph message passing that couples sensors and observation times; "
        "adapted: a learnable static sensor adjacency with per-gap exponential "
        "time decay of the propagated state over the real T_obs grid, instead "
        "of the original sparse bipartite time-variable graph and learned edge "
        "weights"
    )
    REQUIRES_TIME_INPUT = True
    ADAPTER = (
        "native sparse input: features are concat(X*M, M, context) per "
        "observation step; propagation strength decays as "
        "exp(-softplus(rate)*dt) with the real inter-observation gap dt, so no "
        "values are imputed and no future field is read"
    )

    def __init__(
        self,
        num_sensors: int,
        context_dim: int,
        pred_len: int,
        hidden_dim: int = 64,
        min_scale: float = 0.05,
    ):
        super().__init__()
        self.num_sensors = int(num_sensors)
        self.context_dim = int(context_dim)
        self.pred_len = int(pred_len)
        self.hidden_dim = int(hidden_dim)
        self.sensor_proj = nn.Linear(2 + context_dim, hidden_dim)
        self.adjacency = nn.Parameter(torch.zeros(num_sensors, num_sensors))
        self.decay_rate = nn.Parameter(torch.full((num_sensors,), 0.5))
        self.readout = nn.GRU(hidden_dim, hidden_dim, batch_first=True)
        self.head = DiagonalGaussianHead(hidden_dim, min_scale)
        self.min_scale = float(min_scale)

    def _graph_states(self, batch) -> Tensor:
        """Propagate per-sensor states over the real observation time grid."""

        x, mask, context = batch.X_obs, batch.M_obs, batch.context
        batch_size, length, num_sensors = x.shape
        context_seq = (
            context[:, None, None, :]
            .expand(batch_size, length, num_sensors, self.context_dim)
        )
        features = torch.cat(
            [(x * mask).unsqueeze(-1), mask.unsqueeze(-1), context_seq], dim=-1
        )  # [B, L, N, F]
        projected = self.sensor_proj(features)  # [B, L, N, H]

        adjacency = torch.softmax(self.adjacency, dim=-1)  # [N, N]
        time = batch.T_obs if batch.T_obs.dim() == 2 else batch.T_obs.squeeze(-1)
        state = x.new_zeros(batch_size, num_sensors, self.hidden_dim)
        readout_steps = []
        for step in range(length):
            gap = time[:, step] - time[:, step - 1] if step else torch.zeros_like(time[:, 0])
            decay = torch.exp(
                -torch.nn.functional.softplus(self.decay_rate) * gap.clamp_min(0.0).unsqueeze(-1)
            )  # [B, N]
            message = torch.einsum("nm,bmh->bnh", adjacency, state)
            state = torch.tanh(decay.unsqueeze(-1) * message + projected[:, step])
            step_mask = mask[:, step].unsqueeze(-1)  # [B, 1]
            pooled = (state * step_mask).sum(dim=1) / step_mask.sum(dim=1).clamp_min(1.0)
            readout_steps.append(pooled)
        sequence = torch.stack(readout_steps, dim=1)  # [B, L, H]
        _, hidden = self.readout(sequence)
        return hidden[-1]

    def gaussian_params(self, batch) -> tuple:
        pooled = self._graph_states(batch)  # [B, H]
        repeated = pooled.unsqueeze(1).expand(-1, self.pred_len * self.num_sensors, -1)
        mean, scale = self.head(repeated)  # [B, P*N]
        return (
            mean.view(-1, self.pred_len, self.num_sensors),
            scale.view(-1, self.pred_len, self.num_sensors),
        )
