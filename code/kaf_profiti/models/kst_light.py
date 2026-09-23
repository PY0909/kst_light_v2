"""Scheme B v2 point predictor."""

from dataclasses import asdict, dataclass
from typing import Dict, Optional, Tuple

import torch
from torch import Tensor, nn
import torch.nn.functional as F

from kaf_profiti.experiments.model_api import UnifiedPointModel
from kaf_profiti.models.cross_variable import CrossVariableConfig, build_cross_variable_block
from kaf_profiti.models.kafnet_encoder import HierarchicalMissingnessKAFEncoder
from kaf_profiti.models.query_condition_adapter import QueryConditionAdapter


@dataclass
class KSTLightV2Config:
    recipe_version: str = "scheme_b_v1"
    encoder_version: str = "hierarchical_missingness_kaf_v1"
    missing_feature_version: str = "causal_missingness_v1"
    num_sensors: int = 21
    context_dim: int = 3
    pred_len: int = 24
    hidden_dim: int = 64
    te_dim: int = 10
    kernel_count: int = 4
    n_layers: int = 2
    n_heads: int = 2
    preconv_dim: int = 16
    patch_lens: Tuple[int, ...] = (12, 24, 48)
    cross_variable_mode: str = "fla"
    cross_variable_rank: int = 64
    cross_variable_mlp_ratio: float = 4.0
    gru_hidden: int = 16
    gru_bottleneck_ratio: float = 4.0
    gru_use_forward_fill: bool = True
    gru_direct_residual: bool = False
    mixer_layers: int = 1
    mixer_relation_bias: bool = True
    mixer_relation_scale: float = 1.0
    mixer_freshness_scale: float = 1.0
    graph_layers: int = 1
    freshness_tau: float = 24.0
    anchor_fallback: float = 0.0

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["patch_lens"] = list(self.patch_lens)
        return payload


class KSTLightV2(UnifiedPointModel):
    MODEL_ID = "kst_light_v2"
    RECIPE_VERSION = "scheme_b_v1"

    def __init__(self, config: Optional[KSTLightV2Config] = None, **kwargs):
        super().__init__()
        self.config = config or KSTLightV2Config(**kwargs)
        c = self.config
        self.encoder = HierarchicalMissingnessKAFEncoder(
            num_sensors=c.num_sensors,
            hidden_dim=c.hidden_dim,
            kernel_count=c.kernel_count,
            time_dim=c.te_dim,
            n_layers=c.n_layers,
            n_heads=c.n_heads,
            preconv_dim=c.preconv_dim,
            patch_lens=c.patch_lens,
            context_dim=c.context_dim,
            freshness_tau=c.freshness_tau,
        )
        self.cross_variable = build_cross_variable_block(
            c.cross_variable_mode,
            CrossVariableConfig(
                hidden_dim=c.hidden_dim,
                heads=c.n_heads,
                graph_layers=c.graph_layers,
                rank=c.cross_variable_rank,
                mlp_ratio=c.cross_variable_mlp_ratio,
                num_sensors=c.num_sensors,
                context_dim=c.context_dim,
                gru_hidden=c.gru_hidden,
                gru_bottleneck_ratio=c.gru_bottleneck_ratio,
                use_forward_fill=c.gru_use_forward_fill,
                direct_residual=c.gru_direct_residual,
                mixer_layers=c.mixer_layers,
                mixer_relation_bias=c.mixer_relation_bias,
                mixer_relation_scale=c.mixer_relation_scale,
                mixer_freshness_scale=c.mixer_freshness_scale,
            ),
        )
        self.adapter = QueryConditionAdapter(c.num_sensors, c.hidden_dim, c.te_dim, c.context_dim)
        self.decoder = nn.Sequential(
            nn.Linear(c.hidden_dim, c.hidden_dim), nn.GELU(), nn.Linear(c.hidden_dim, 1)
        )
        nn.init.zeros_(self.decoder[-1].weight)
        nn.init.zeros_(self.decoder[-1].bias)

    def _last_value(self, batch) -> Tuple[Tensor, Tensor]:
        observed = batch.M_obs > 0
        steps = torch.arange(batch.X_obs.shape[1], device=batch.X_obs.device).view(1, -1, 1)
        last_step = torch.where(observed, steps, torch.zeros_like(steps)).max(dim=1).values
        gather_index = last_step.unsqueeze(1)
        value = torch.gather(batch.X_obs, 1, gather_index).squeeze(1)
        has_history = observed.any(dim=1)
        value = torch.where(
            has_history, value, torch.full_like(value, self.config.anchor_fallback)
        )
        return value, has_history.to(batch.X_obs.dtype)

    def variable_representation(self, batch) -> Tensor:
        z = self.encoder(batch.X_obs, batch.T_obs, batch.M_obs, batch.context)
        features = self.encoder.missingness(batch.T_obs, batch.M_obs)
        if self.config.cross_variable_mode == "gru_mixer":
            return self.cross_variable(
                z,
                features.freshness[:, -1],
                features.has_history[:, -1],
                batch.X_obs,
                batch.M_obs,
                batch.context,
            )
        return self.cross_variable(z, features.freshness[:, -1], features.has_history[:, -1])

    def hidden_representation(self, batch) -> Tensor:
        z = self.variable_representation(batch)
        return self.adapter(z, batch.T_q, batch.query_channel_ids, batch.context)

    def predict_point(self, batch) -> Tensor:
        hidden = self.hidden_representation(batch)
        delta = self.decoder(hidden).squeeze(-1)
        anchor, _ = self._last_value(batch)
        anchor_flat = anchor[:, batch.query_channel_ids]
        direct_residual = getattr(self.cross_variable, "last_direct_residual", None)
        if direct_residual is not None:
            delta = delta + direct_residual[:, batch.query_channel_ids]
        return anchor_flat + delta

    def loss(self, batch) -> Tensor:
        prediction = self.predict_point(batch)
        return (
            F.huber_loss(prediction, batch.y_flat, reduction="none") * batch.mq_flat
        ).sum() / batch.mq_flat.sum().clamp_min(1.0)
