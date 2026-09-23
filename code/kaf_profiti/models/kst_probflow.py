import math
from dataclasses import asdict, dataclass
from typing import Dict, Sequence, Tuple

import torch
from torch import Tensor, nn
import torch.nn.functional as F

from .kafnet_encoder import MultiScaleKAFEncoder
from .query_condition_adapter import QueryConditionAdapter


class DynamicSensorGraphBlock(nn.Module):
    def __init__(self, num_sensors: int, hidden_dim: int, graph_layers: int = 1):
        super().__init__()
        self.num_sensors = num_sensors
        self.hidden_dim = hidden_dim
        self.graph_layers = int(graph_layers)
        self.q_proj = nn.Linear(hidden_dim, hidden_dim)
        self.k_proj = nn.Linear(hidden_dim, hidden_dim)
        self.v_proj = nn.Linear(hidden_dim, hidden_dim)
        self.static_logits = nn.Parameter(torch.zeros(num_sensors, num_sensors))
        self.gates = nn.ModuleList(
            [nn.Linear(hidden_dim * 2, hidden_dim) for _ in range(max(self.graph_layers, 1))]
        )
        self.out = nn.LayerNorm(hidden_dim)
        self.last_adjacency = None

    def _adjacency(self, z: Tensor) -> Tensor:
        dynamic = torch.bmm(self.q_proj(z), self.k_proj(z).transpose(-2, -1))
        dynamic = dynamic / math.sqrt(self.hidden_dim)
        dynamic = torch.softmax(dynamic, dim=-1)
        static = torch.softmax(self.static_logits, dim=-1).unsqueeze(0).expand_as(dynamic)
        adjacency = 0.5 * dynamic + 0.5 * static
        return adjacency / adjacency.sum(dim=-1, keepdim=True).clamp_min(1e-6)

    def forward(self, z: Tensor) -> Tensor:
        adjacency = self._adjacency(z)
        self.last_adjacency = adjacency.detach()
        h = z
        for gate_layer in self.gates:
            message = torch.bmm(adjacency, self.v_proj(h))
            gate = torch.sigmoid(gate_layer(torch.cat([h, message], dim=-1)))
            h = gate * h + (1.0 - gate) * message
        return self.out(h + z)


class LowRankCopulaFlowHead(nn.Module):
    def __init__(
        self,
        hidden_dim: int,
        copula_rank: int = 32,
        sample_clip: float = 30.0,
        attention_diag_floor: float = 0.05,
        min_scale: float = 0.05,
        df: float = 6.0,
    ):
        super().__init__()
        self.hidden_dim = hidden_dim
        self.copula_rank = int(copula_rank)
        self.sample_clip = float(sample_clip)
        self.attention_diag_floor = float(attention_diag_floor)
        self.min_scale = float(min_scale)
        self.df = float(df)
        self.param_net = nn.Linear(hidden_dim, 2)
        self.factor_net = nn.Linear(hidden_dim, self.copula_rank)
        nn.init.zeros_(self.param_net.weight)
        nn.init.zeros_(self.param_net.bias)
        nn.init.xavier_uniform_(self.factor_net.weight, gain=0.02)
        nn.init.zeros_(self.factor_net.bias)

    def params(self, hidden_states: Tensor) -> Tuple[Tensor, Tensor, Tensor]:
        raw = self.param_net(hidden_states)
        loc = raw[..., 0]
        scale = F.softplus(raw[..., 1]) + self.min_scale
        factors = torch.tanh(self.factor_net(hidden_states)) / math.sqrt(max(self.copula_rank, 1))
        return loc, scale, factors

    def nll(self, y_flat: Tensor, hidden_states: Tensor, mask: Tensor) -> Tensor:
        loc, scale, _ = self.params(hidden_states)
        residual = ((y_flat - loc) / scale) * mask
        df = torch.tensor(self.df, device=y_flat.device, dtype=y_flat.dtype)
        log_norm = (
            torch.lgamma((df + 1.0) * 0.5)
            - torch.lgamma(df * 0.5)
            - 0.5 * torch.log(df * torch.tensor(math.pi, device=y_flat.device, dtype=y_flat.dtype))
            - torch.log(scale)
        )
        log_prob = log_norm - ((df + 1.0) * 0.5) * torch.log1p(residual.pow(2) / df)
        nll = -(log_prob * mask).sum(dim=-1) / mask.sum(dim=-1).clamp_min(1.0)
        corr_penalty = 0.001 * self.factor_net(hidden_states).pow(2).mean(dim=(1, 2))
        return nll + corr_penalty

    def sample(
        self,
        hidden_states: Tensor,
        mask: Tensor,
        nsamples: int = 100,
        generator: torch.Generator = None,
    ) -> Tensor:
        loc, scale, factors = self.params(hidden_states)
        batch_size, query_count = loc.shape
        eps = torch.randn(
            batch_size, nsamples, query_count, device=hidden_states.device, generator=generator
        )
        shared = torch.randn(
            batch_size,
            nsamples,
            self.copula_rank,
            device=hidden_states.device,
            generator=generator,
        )
        correlated = torch.einsum("bsr,bkr->bsk", shared, factors)
        noise = eps + correlated
        y = loc.unsqueeze(1) + scale.unsqueeze(1) * noise
        y = torch.nan_to_num(y, nan=0.0, posinf=self.sample_clip, neginf=-self.sample_clip)
        y = y.clamp(-self.sample_clip, self.sample_clip)
        return y * mask.unsqueeze(1)

    def mean(self, hidden_states: Tensor, mask: Tensor, nsamples: int = 100) -> Tensor:
        loc, _, _ = self.params(hidden_states)
        return loc * mask

    def base_mean(self, hidden_states: Tensor, mask: Tensor) -> Tensor:
        return self.mean(hidden_states, mask)

    @staticmethod
    def masked_mse(y: Tensor, yhat: Tensor, mask: Tensor) -> Tensor:
        return (((yhat - y) ** 2) * mask).sum() / mask.sum().clamp_min(1.0)

    @staticmethod
    def crps(y: Tensor, samples: Tensor, mask: Tensor) -> Tensor:
        term1 = (samples - y.unsqueeze(1)).abs().mean(dim=1)
        pairwise = (samples.unsqueeze(2) - samples.unsqueeze(1)).abs().mean(dim=(1, 2))
        crps = (term1 - 0.5 * pairwise) * mask
        return crps.sum() / mask.sum().clamp_min(1.0)


class QuantileHead(nn.Module):
    def __init__(self, hidden_dim: int, quantiles: Sequence[float] = (0.025, 0.1, 0.5, 0.9, 0.975)):
        super().__init__()
        self.quantiles = tuple(float(q) for q in quantiles)
        self.base = nn.Linear(hidden_dim, 1)
        self.delta = nn.Linear(hidden_dim, len(self.quantiles) - 1)

    def forward(self, hidden_states: Tensor) -> Tensor:
        base = self.base(hidden_states).squeeze(-1)
        deltas = F.softplus(self.delta(hidden_states)).permute(0, 2, 1)
        pieces = [base.unsqueeze(1)]
        current = base
        for idx in range(deltas.shape[1]):
            current = current + deltas[:, idx, :]
            pieces.append(current.unsqueeze(1))
        return torch.cat(pieces, dim=1)

    def loss(self, quantile_pred: Tensor, y: Tensor, mask: Tensor) -> Tensor:
        losses = []
        for idx, quantile in enumerate(self.quantiles):
            error = y - quantile_pred[:, idx, :]
            q = torch.tensor(quantile, device=y.device, dtype=y.dtype)
            losses.append(torch.maximum(q * error, (q - 1.0) * error))
        stacked = torch.stack(losses, dim=1) * mask.unsqueeze(1)
        return stacked.sum() / (mask.sum() * len(self.quantiles)).clamp_min(1.0)


class RiskHead(nn.Module):
    def __init__(self, hidden_dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(hidden_dim + 3, hidden_dim),
            nn.ReLU(True),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, z_var: Tensor, mean: Tensor, variance: Tensor, quantile_width: Tensor) -> Tensor:
        z_summary = z_var.mean(dim=1)
        stats = torch.stack(
            [
                mean.abs().mean(dim=-1),
                variance.clamp_min(0.0).mean(dim=-1),
                quantile_width.clamp_min(0.0).mean(dim=-1),
            ],
            dim=-1,
        )
        normality = torch.sigmoid(self.net(torch.cat([z_summary, stats], dim=-1)).squeeze(-1))
        return 1.0 - normality

    @staticmethod
    def loss(scores: Tensor, labels: Tensor, gamma: float = 2.0, alpha: float = 0.75) -> Tensor:
        labels = labels.float().clamp(0.0, 1.0)
        bce = F.binary_cross_entropy(scores.clamp(1e-6, 1.0 - 1e-6), labels, reduction="none")
        pt = torch.where(labels > 0.5, scores, 1.0 - scores)
        weights = torch.where(labels > 0.5, torch.full_like(labels, alpha), torch.full_like(labels, 1.0 - alpha))
        return (weights * (1.0 - pt).pow(gamma) * bce).mean()


@dataclass
class KSTProbFlowConfig:
    num_sensors: int = 21
    context_dim: int = 3
    hidden_dim: int = 64
    te_dim: int = 10
    kernel_count: int = 4
    n_layers: int = 2
    n_heads: int = 2
    preconv_dim: int = 16
    patch_lens: Tuple[int, ...] = (12, 24, 48)
    graph_layers: int = 1
    copula_rank: int = 32
    lambda_point: float = 0.5
    lambda_quantile: float = 0.2
    lambda_risk: float = 0.05
    sample_clip: float = 30.0
    attention_diag_floor: float = 0.05
    device: str = "cpu"

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["patch_lens"] = list(self.patch_lens)
        return payload


class KSTProbFlow(nn.Module):
    def __init__(self, config: KSTProbFlowConfig):
        super().__init__()
        self.config = config
        device = torch.device(config.device)
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
        self.graph = DynamicSensorGraphBlock(
            num_sensors=config.num_sensors,
            hidden_dim=config.hidden_dim,
            graph_layers=config.graph_layers,
        )
        self.adapter = QueryConditionAdapter(
            num_sensors=config.num_sensors,
            hidden_dim=config.hidden_dim,
            time_dim=config.te_dim,
            context_dim=config.context_dim,
        )
        self.flow_head = LowRankCopulaFlowHead(
            hidden_dim=config.hidden_dim,
            copula_rank=config.copula_rank,
            sample_clip=config.sample_clip,
            attention_diag_floor=config.attention_diag_floor,
        )
        self.quantile_head = QuantileHead(config.hidden_dim)
        self.risk_head = RiskHead(config.hidden_dim)
        self._hidden_states = None
        self._z_var = None
        self.to(device)

    @property
    def hidden_states(self) -> Tensor:
        if self._hidden_states is None:
            raise RuntimeError("Must call distribution first")
        return self._hidden_states

    @property
    def z_var(self) -> Tensor:
        if self._z_var is None:
            raise RuntimeError("Must call distribution first")
        return self._z_var

    def encode_variables(self, batch) -> Tensor:
        z = self.encoder(batch.X_obs, batch.T_obs, batch.M_obs, batch.context)
        return self.graph(z)

    def distribution(self, batch) -> Tensor:
        self._z_var = self.encode_variables(batch)
        self._hidden_states = self.adapter(
            self._z_var,
            batch.T_q,
            batch.query_channel_ids,
            batch.context,
        )
        return self._hidden_states

    def _risk_label(self, batch) -> Tensor:
        labels = batch.rul.float()
        if labels.numel() > 0 and labels.max() > 1.0:
            return (labels <= 30.0).float()
        return labels.clamp(0.0, 1.0)

    def loss(self, batch, nsamples_for_point: int = 3) -> Tensor:
        hidden = self.distribution(batch)
        nll = self.flow_head.nll(batch.y_flat, hidden, batch.mq_flat).mean()
        mean = self.flow_head.base_mean(hidden, batch.mq_flat)
        point = self.flow_head.masked_mse(batch.y_flat, mean, batch.mq_flat)
        quantiles = self.quantile_head(hidden)
        q_loss = self.quantile_head.loss(quantiles, batch.y_flat, batch.mq_flat)
        quantile_width = quantiles[:, -1, :] - quantiles[:, 0, :]
        loc, scale, _ = self.flow_head.params(hidden)
        risk = self.risk_head(self.z_var, loc * batch.mq_flat, scale.pow(2) * batch.mq_flat, quantile_width)
        risk_loss = self.risk_head.loss(risk, self._risk_label(batch))
        return (
            nll
            + self.config.lambda_point * point
            + self.config.lambda_quantile * q_loss
            + self.config.lambda_risk * risk_loss
        )

    def sample(self, batch, nsamples: int = 100) -> Tensor:
        hidden = self.distribution(batch)
        flat_samples = self.flow_head.sample(hidden, batch.mq_flat, nsamples=nsamples)
        pred_len = batch.T_q.shape[1]
        return flat_samples.reshape(flat_samples.shape[0], nsamples, pred_len, self.config.num_sensors)

    def predict_mean(self, batch, nsamples: int = 100) -> Tensor:
        hidden = self.distribution(batch)
        return self.flow_head.mean(hidden, batch.mq_flat, nsamples=nsamples)

    def predict_quantiles(self, batch) -> Tensor:
        hidden = self.distribution(batch)
        return self.quantile_head(hidden)

    def predict_risk(self, batch, nsamples: int = 100) -> Tensor:
        hidden = self.distribution(batch)
        quantiles = self.quantile_head(hidden)
        loc, scale, _ = self.flow_head.params(hidden)
        width = quantiles[:, -1, :] - quantiles[:, 0, :]
        return self.risk_head(self.z_var, loc * batch.mq_flat, scale.pow(2) * batch.mq_flat, width)
