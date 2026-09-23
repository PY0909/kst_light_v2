"""Scheme B v2 coherent conditional joint flow predictor."""

from dataclasses import asdict, dataclass
from typing import Optional, Tuple

import torch
from torch import Tensor
import torch.nn.functional as F

from kaf_profiti.models.kst_light import KSTLightV2, KSTLightV2Config
from kaf_profiti.models.profiti_flow_head import ProFITiFlowHead


@dataclass
class KSTFlowV2Config(KSTLightV2Config):
    flow_layers: int = 2
    lambda_point: float = 0.1
    sample_clip: float = 30.0
    inverse_clip: float = 1_000_000.0
    device: str = "cpu"
    flow_order: str = "horizon_major_sensor_minor"

    def to_dict(self):
        payload = asdict(self)
        payload["patch_lens"] = list(self.patch_lens)
        return payload


class KSTFlowV2(KSTLightV2):
    MODEL_ID = "kst_flow_v2"
    RECIPE_VERSION = "scheme_b_v1"

    def __init__(self, config: Optional[KSTFlowV2Config] = None, **kwargs):
        flow_config = config or KSTFlowV2Config(**kwargs)
        super().__init__(KSTLightV2Config(**{
            key: getattr(flow_config, key)
            for key in KSTLightV2Config.__dataclass_fields__
        }))
        self.config = flow_config
        c = flow_config
        self.flow_head = ProFITiFlowHead(
            hidden_dim=c.hidden_dim,
            flow_layers=c.flow_layers,
            marginal_training=False,
            device=torch.device(c.device),
            sample_clip=c.sample_clip,
            inverse_clip=c.inverse_clip,
        )
        self.gaussian_kind = "flow"

    def _hidden_and_mask(self, batch):
        return self.hidden_representation(batch), batch.mq_flat

    def flow_hidden(self, batch) -> Tensor:
        """Expose the deterministic conditioning tensor for runner gates."""

        return self.hidden_representation(batch)

    def _point_mean(self, batch) -> Tensor:
        hidden = self.hidden_representation(batch)
        ones = torch.ones_like(batch.mq_flat)
        return self.flow_head.base_mean(hidden, ones)

    def predict_point(self, batch) -> Tensor:
        return self._point_mean(batch)

    def batch_nll(self, batch) -> Tensor:
        hidden, mask = self._hidden_and_mask(batch)
        return self.flow_head.nll(batch.y_flat, hidden, mask).mean()

    def batch_nll_rows(self, batch) -> Tensor:
        hidden, mask = self._hidden_and_mask(batch)
        return self.flow_head.nll(batch.y_flat, hidden, mask)

    def loss(self, batch) -> Tensor:
        nll = self.batch_nll(batch)
        point = F.huber_loss(self.predict_point(batch), batch.y_flat, reduction="none")
        point = (point * batch.mq_flat).sum() / batch.mq_flat.sum().clamp_min(1.0)
        return nll + self.config.lambda_point * point

    def sample_flat(self, batch, nsamples: int = 100, generator=None) -> Tensor:
        hidden, mask = self._hidden_and_mask(batch)
        return self.flow_head.sample(hidden, mask, nsamples=nsamples, generator=generator)

    def interval95_flat(self, batch) -> Tuple[Tensor, Tensor]:
        generator = torch.Generator(device=batch.X_obs.device).manual_seed(2026)
        samples = self.sample_flat(batch, nsamples=128, generator=generator)
        return torch.quantile(samples, 0.025, dim=1), torch.quantile(samples, 0.975, dim=1)

    def gaussian_params(self, batch):
        raise AttributeError("kst_flow_v2 exposes a conditional flow, not diagonal Gaussian parameters")
