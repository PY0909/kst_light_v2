from dataclasses import asdict, dataclass
from typing import Dict

import torch
from torch import Tensor, nn

from .kafnet_encoder import KAFNetEncoder
from .profiti_flow_head import ProFITiFlowHead
from .query_condition_adapter import QueryConditionAdapter


@dataclass
class KAFProFITiConfig:
    num_sensors: int = 21
    context_dim: int = 3
    hidden_dim: int = 32
    te_dim: int = 5
    kernel_count: int = 4
    n_layers: int = 2
    n_heads: int = 2
    flow_layers: int = 2
    preconv_dim: int = 8
    lambda_point: float = 0.1
    marginal_training: bool = False
    attention_diag_floor: float = 0.05
    sample_clip: float = 20.0
    inverse_clip: float = 1_000_000.0
    device: str = "cpu"

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


class KAFProFITi(nn.Module):
    def __init__(self, config: KAFProFITiConfig):
        super().__init__()
        self.config = config
        device = torch.device(config.device)
        self.encoder = KAFNetEncoder(
            num_sensors=config.num_sensors,
            hidden_dim=config.hidden_dim,
            kernel_count=config.kernel_count,
            time_dim=config.te_dim,
            n_layers=config.n_layers,
            n_heads=config.n_heads,
            preconv_dim=config.preconv_dim,
            context_dim=config.context_dim,
        )
        self.adapter = QueryConditionAdapter(
            num_sensors=config.num_sensors,
            hidden_dim=config.hidden_dim,
            time_dim=config.te_dim,
            context_dim=config.context_dim,
        )
        self.flow_head = ProFITiFlowHead(
            hidden_dim=config.hidden_dim,
            flow_layers=config.flow_layers,
            marginal_training=config.marginal_training,
            device=device,
            attention_diag_floor=config.attention_diag_floor,
            sample_clip=config.sample_clip,
            inverse_clip=config.inverse_clip,
        )
        self._hidden_states = None
        self.to(device)

    @property
    def hidden_states(self) -> Tensor:
        if self._hidden_states is None:
            raise RuntimeError("Must call distribution first")
        return self._hidden_states

    def distribution(self, batch) -> Tensor:
        z_var = self.encoder(batch.X_obs, batch.T_obs, batch.M_obs, batch.context)
        self._hidden_states = self.adapter(
            z_var,
            batch.T_q,
            batch.query_channel_ids,
            batch.context,
        )
        return self._hidden_states

    def loss(self, batch, nsamples_for_point: int = 3) -> Tensor:
        hidden_states = self.distribution(batch)
        nll = self.flow_head.nll(batch.y_flat, hidden_states, batch.mq_flat).mean()
        if self.config.lambda_point <= 0:
            return nll
        yhat = self.flow_head.base_mean(hidden_states, batch.mq_flat)
        point_loss = self.flow_head.masked_mse(batch.y_flat, yhat, batch.mq_flat)
        return nll + self.config.lambda_point * point_loss

    def sample(self, batch, nsamples: int = 100) -> Tensor:
        hidden_states = self.distribution(batch)
        flat_samples = self.flow_head.sample(hidden_states, batch.mq_flat, nsamples=nsamples)
        batch_size, _, query_count = flat_samples.shape
        pred_len = batch.T_q.shape[1]
        return flat_samples.reshape(batch_size, nsamples, pred_len, self.config.num_sensors)

    def predict_mean(self, batch, nsamples: int = 100) -> Tensor:
        hidden_states = self.distribution(batch)
        return self.flow_head.mean(hidden_states, batch.mq_flat, nsamples=nsamples)
