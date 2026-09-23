"""Unified lightweight prediction heads and the KST-Light model (CH2.5-P02-T01).

The heads consume only encoder history representations — never the query
targets ``Y_q``/``M_q`` or future context. ``KSTLight`` pairs the project's
asynchronous regularized-history encoder (:class:`MultiScaleKAFEncoder`) with
the shared Linear/MLP point head, so Chapter 3 point baselines and the own
light configurations differ only in the encoder, not in the target or trainer.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Dict, Tuple

import torch
from torch import Tensor, nn

from kaf_profiti.experiments.model_api import UnifiedPointModel, Z95
from kaf_profiti.models.kafnet_encoder import MultiScaleKAFEncoder
from kaf_profiti.models.query_condition_adapter import QueryConditionAdapter


class LinearPointHead(nn.Module):
    """Single affine map from per-query history representations to flat targets."""

    def __init__(self, input_dim: int, output_dim: int):
        super().__init__()
        self.input_dim = int(input_dim)
        self.output_dim = int(output_dim)
        self.out = nn.Linear(input_dim, output_dim)

    def forward(self, hidden: Tensor) -> Tensor:
        return self.out(hidden)


class MLPPointHead(nn.Module):
    """Two-layer MLP head with the same input/output contract as the linear head."""

    def __init__(self, input_dim: int, hidden_dim: int, output_dim: int):
        super().__init__()
        self.input_dim = int(input_dim)
        self.hidden_dim = int(hidden_dim)
        self.output_dim = int(output_dim)
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, output_dim),
        )

    def forward(self, hidden: Tensor) -> Tensor:
        return self.net(hidden)


class DiagonalGaussianHead(nn.Module):
    """Unified diagonal Gaussian head (CH2.5-P02-T03 shared spec).

    Scale parameterization is ``softplus(raw) + min_scale``; the NLL
    denominator is ``mask.sum()``; ``sample`` returns ``[B, S, D]`` and the 95%
    interval is ``mean +/- Z95 * scale``.
    """

    def __init__(self, hidden_dim: int, min_scale: float = 0.05):
        super().__init__()
        self.hidden_dim = int(hidden_dim)
        self.min_scale = float(min_scale)
        self.proj = nn.Linear(hidden_dim, 2)

    def forward(self, hidden: Tensor) -> Tuple[Tensor, Tensor]:
        raw = self.proj(hidden)
        mean = raw[..., 0]
        scale = torch.nn.functional.softplus(raw[..., 1]) + self.min_scale
        return mean, scale

    def nll(self, y: Tensor, mean: Tensor, scale: Tensor, mask: Tensor) -> Tensor:
        log_prob = (
            -0.5 * ((y - mean) / scale).pow(2)
            - torch.log(scale)
            - 0.5 * math.log(2.0 * math.pi)
        )
        return -((log_prob * mask).sum() / mask.sum().clamp_min(1.0))

    def sample(
        self,
        mean: Tensor,
        scale: Tensor,
        nsamples: int = 100,
        generator: torch.Generator = None,
    ) -> Tensor:
        eps = torch.randn(
            mean.shape[0],
            int(nsamples),
            mean.shape[1],
            device=mean.device,
            dtype=mean.dtype,
            generator=generator,
        )
        return mean.unsqueeze(1) + scale.unsqueeze(1) * eps

    @staticmethod
    def interval_95(mean: Tensor, scale: Tensor) -> Tuple[Tensor, Tensor]:
        return mean - Z95 * scale, mean + Z95 * scale


@dataclass
class KSTLightConfig:
    num_sensors: int = 21
    context_dim: int = 3
    pred_len: int = 10
    hidden_dim: int = 64
    te_dim: int = 10
    kernel_count: int = 4
    n_layers: int = 2
    n_heads: int = 2
    preconv_dim: int = 16
    patch_lens: Tuple[int, ...] = (12, 24, 48)
    head_type: str = "linear"
    head_hidden_dim: int = 64

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["patch_lens"] = list(self.patch_lens)
        return payload


class KSTLight(UnifiedPointModel):
    """KST-Light: asynchronous regularized-history encoder + lightweight head."""

    IMPLEMENTATION = "own"
    REQUIRES_TIME_INPUT = False
    ADAPTER = (
        "history-only encoder consumption; missing history handled inside the "
        "encoder through the observation mask, no target or future input"
    )

    def __init__(self, config: KSTLightConfig | None = None, **kwargs):
        super().__init__()
        if config is None:
            config = KSTLightConfig(**kwargs)
        self.config = config
        self.encoder = MultiScaleKAFEncoder(
            num_sensors=config.num_sensors,
            hidden_dim=config.hidden_dim,
            kernel_count=config.kernel_count,
            time_dim=config.te_dim,
            n_layers=config.n_layers,
            n_heads=config.n_heads,
            preconv_dim=config.preconv_dim,
            patch_lens=config.patch_lens,
            context_dim=config.context_dim,
        )
        self.adapter = QueryConditionAdapter(
            num_sensors=config.num_sensors,
            hidden_dim=config.hidden_dim,
            time_dim=config.te_dim,
            context_dim=config.context_dim,
        )
        if config.head_type == "linear":
            self.head = LinearPointHead(config.hidden_dim, 1)
        elif config.head_type == "mlp":
            self.head = MLPPointHead(config.hidden_dim, config.head_hidden_dim, 1)
        else:
            raise ValueError(
                f"head_type must be 'linear' or 'mlp', got {config.head_type!r}"
            )

    def hidden_representation(self, batch) -> Tensor:
        z = self.encoder(batch.X_obs, batch.T_obs, batch.M_obs, batch.context)
        return self.adapter(z, batch.T_q, batch.query_channel_ids, batch.context)

    def predict_point(self, batch) -> Tensor:
        hidden = self.hidden_representation(batch)
        return self.head(hidden).squeeze(-1)
