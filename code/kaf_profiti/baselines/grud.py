"""GRU-D Gaussian baseline on the unified distribution API (CH2.5-P02-T03).

The Chapter-4 probabilistic GRU-D baseline shares the exact time mechanism of
the Chapter-3 point version (:class:`GRUDEncoder`: mask + GRU-D ``delta_t``
recursion + learnable per-sensor exponential input decay) and swaps only the
head for the unified diagonal Gaussian head, so point/probabilistic GRU-D
differences come from the prediction structure, never from the encoder.
"""

import torch
from torch import Tensor

from kaf_profiti.baselines.point import GRUDEncoder
from kaf_profiti.experiments.model_api import UnifiedGaussianModel
from kaf_profiti.models.lightweight_head import DiagonalGaussianHead


class GRUDGaussian(UnifiedGaussianModel):
    """GRU-D encoder + unified diagonal Gaussian head."""

    IMPLEMENTATION = "adapted"
    SOURCE_IDENTITY = (
        "GRU-D (Che et al., 2018): the model consumes the observation mask, "
        "the elapsed time since the last observation and a learnable "
        "exponential input decay toward the train mean, followed by a unified "
        "diagonal Gaussian prediction head; adapted: one learnable "
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
        min_scale: float = 0.05,
    ):
        super().__init__()
        self.num_sensors = int(num_sensors)
        self.context_dim = int(context_dim)
        self.pred_len = int(pred_len)
        self.hidden_dim = int(hidden_dim)
        self.encoder = GRUDEncoder(num_sensors, hidden_dim, num_layers, fill_value)
        self.head = DiagonalGaussianHead(hidden_dim, min_scale)
        self.min_scale = float(min_scale)

    def gaussian_params(self, batch) -> tuple:
        pooled = self.encoder(batch)  # [B, H]
        repeated = pooled.unsqueeze(1).expand(-1, self.pred_len * self.num_sensors, -1)
        mean, scale = self.head(repeated)  # [B, P*N]
        return (
            mean.view(-1, self.pred_len, self.num_sensors),
            scale.view(-1, self.pred_len, self.num_sensors),
        )
