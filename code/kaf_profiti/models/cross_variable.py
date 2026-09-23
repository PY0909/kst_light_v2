"""Mutually exclusive cross-sensor interaction blocks for Scheme B."""

from __future__ import annotations

from dataclasses import dataclass
import math

import torch
from torch import Tensor, nn

from .kafnet_encoder import FreqBlock


@dataclass(frozen=True)
class CrossVariableConfig:
    hidden_dim: int
    heads: int = 2
    graph_layers: int = 1
    rank: int = 64
    mlp_ratio: float = 4.0
    freshness_floor: float = 1e-4
    num_sensors: int = 0
    context_dim: int = 0
    gru_hidden: int = 16
    gru_bottleneck_ratio: float = 4.0
    use_forward_fill: bool = True
    direct_residual: bool = False
    mixer_layers: int = 1
    mixer_relation_bias: bool = True
    mixer_relation_scale: float = 1.0
    mixer_freshness_scale: float = 1.0


class IdentityCrossVariable(nn.Module):
    def __init__(self, config: CrossVariableConfig):
        super().__init__()

    def forward(self, z: Tensor, freshness: Tensor, available: Tensor) -> Tensor:
        return z


class FLACrossVariable(nn.Module):
    def __init__(self, config: CrossVariableConfig):
        super().__init__()
        self.block = FreqBlock(
            config.hidden_dim,
            heads=config.heads,
            rank=config.rank,
            mlp_ratio=config.mlp_ratio,
        )

    def forward(self, z: Tensor, freshness: Tensor, available: Tensor) -> Tensor:
        return self.block(z)


class MissingnessAwareGraph(nn.Module):
    def __init__(self, config: CrossVariableConfig):
        super().__init__()
        self.hidden_dim = int(config.hidden_dim)
        self.q = nn.Linear(self.hidden_dim, self.hidden_dim)
        self.k = nn.Linear(self.hidden_dim, self.hidden_dim)
        self.v = nn.Linear(self.hidden_dim, self.hidden_dim)
        self.gates = nn.ModuleList(
            [nn.Linear(self.hidden_dim * 2, self.hidden_dim) for _ in range(max(1, config.graph_layers))]
        )
        self.norm = nn.LayerNorm(self.hidden_dim)
        self.freshness_floor = float(config.freshness_floor)
        self.last_adjacency = None

    def _adjacency(self, z: Tensor, freshness: Tensor, available: Tensor) -> Tensor:
        logits = torch.bmm(self.q(z), self.k(z).transpose(1, 2)) / math.sqrt(self.hidden_dim)
        age = (-torch.log(freshness.clamp_min(self.freshness_floor))).unsqueeze(1)
        logits = logits - age
        source = available.unsqueeze(1) > 0
        logits = logits.masked_fill(~source, torch.finfo(logits.dtype).min)
        adjacency = torch.softmax(logits, dim=-1)
        no_source = (available.sum(dim=-1) <= 0).view(-1, 1, 1)
        identity = torch.eye(z.shape[1], device=z.device, dtype=z.dtype).unsqueeze(0)
        adjacency = torch.where(no_source, identity, adjacency)
        return adjacency / adjacency.sum(dim=-1, keepdim=True).clamp_min(1e-6)

    def forward(self, z: Tensor, freshness: Tensor, available: Tensor) -> Tensor:
        adjacency = self._adjacency(z, freshness, available)
        self.last_adjacency = adjacency.detach()
        hidden = z
        for gate_layer in self.gates:
            message = torch.bmm(adjacency, self.v(hidden))
            gate = torch.sigmoid(gate_layer(torch.cat([hidden, message], dim=-1)))
            hidden = gate * hidden + (1.0 - gate) * message
        return self.norm(hidden + z)


class MissingSensorMixer(nn.Module):
    """Missingness-aware sensor-token mixer that directly replaces FLA."""

    def __init__(self, config: CrossVariableConfig):
        super().__init__()
        self.hidden_dim = int(config.hidden_dim)
        self.num_sensors = int(config.num_sensors)
        self.layers = int(config.mixer_layers)
        if self.num_sensors <= 0:
            raise ValueError("missing_sensor_mixer requires num_sensors")
        if self.layers <= 0:
            raise ValueError("mixer_layers must be positive")
        self.freshness_scale = float(config.mixer_freshness_scale)
        self.relation_scale = float(config.mixer_relation_scale)
        if self.freshness_scale <= 0 or self.relation_scale <= 0:
            raise ValueError("mixer scales must be positive")
        self.norms = nn.ModuleList([nn.LayerNorm(self.hidden_dim) for _ in range(self.layers)])
        self.q = nn.ModuleList([nn.Linear(self.hidden_dim, self.hidden_dim) for _ in range(self.layers)])
        self.k = nn.ModuleList([nn.Linear(self.hidden_dim, self.hidden_dim) for _ in range(self.layers)])
        self.v = nn.ModuleList([nn.Linear(self.hidden_dim, self.hidden_dim) for _ in range(self.layers)])
        self.proj = nn.ModuleList([nn.Linear(self.hidden_dim, self.hidden_dim) for _ in range(self.layers)])
        bottleneck = max(1, self.hidden_dim // 4)
        self.gates = nn.ModuleList([
            nn.Sequential(nn.Linear(2 * self.hidden_dim + 2, bottleneck), nn.SiLU(), nn.Linear(bottleneck, self.hidden_dim))
            for _ in range(self.layers)
        ])
        self.relation_bias = (
            nn.Parameter(torch.zeros(self.layers, self.num_sensors, self.num_sensors))
            if config.mixer_relation_bias else None
        )
        self.last_adjacency = None
        self.last_gate = None

    def forward(self, z: Tensor, freshness: Tensor, available: Tensor) -> Tensor:
        if z.shape[1:] != (self.num_sensors, self.hidden_dim):
            raise ValueError("missing_sensor_mixer received incompatible token shape")
        hidden = z
        all_missing = available.sum(dim=-1) <= 0
        for index in range(self.layers):
            normalized = self.norms[index](hidden)
            q = self.q[index](normalized)
            k = self.k[index](normalized)
            v = self.v[index](normalized)
            logits = torch.bmm(q, k.transpose(1, 2)) / math.sqrt(self.hidden_dim)
            if self.relation_bias is not None:
                logits = logits + self.relation_scale * self.relation_bias[index].unsqueeze(0)
            logits = logits - self.freshness_scale * (-torch.log(freshness.clamp_min(1e-4))).unsqueeze(1)
            source = available.unsqueeze(1) > 0
            valid_source = available.sum(dim=-1) > 0
            safe_logits = logits.masked_fill(~source, torch.finfo(logits.dtype).min)
            adjacency = torch.softmax(safe_logits, dim=-1)
            identity = torch.eye(self.num_sensors, device=z.device, dtype=z.dtype).unsqueeze(0)
            adjacency = torch.where(valid_source[:, None, None], adjacency, identity)
            adjacency = adjacency / adjacency.sum(dim=-1, keepdim=True).clamp_min(1e-6)
            message = self.proj[index](torch.bmm(adjacency, v))
            gate_input = torch.cat([hidden, message, freshness.unsqueeze(-1), available.unsqueeze(-1)], dim=-1)
            gate = torch.sigmoid(self.gates[index](gate_input))
            hidden = hidden + gate * message
            hidden = torch.where(all_missing[:, None, None], z, hidden)
            self.last_adjacency = adjacency.detach()
            self.last_gate = gate
        return hidden


def _forward_fill_history(x: Tensor, mask: Tensor) -> Tensor:
    """History-only carry-forward used exclusively by the GRU auxiliary path."""

    value = torch.zeros_like(x[:, 0])
    filled = torch.zeros_like(x)
    for step in range(x.shape[1]):
        observed = mask[:, step] > 0
        value = torch.where(observed, x[:, step], value)
        filled[:, step] = value
    return filled


class GRUConditionedMixer(nn.Module):
    """Small missingness-aware GRU conditioner replacing the FLA block.

    ``z`` remains the mask-safe main representation. The GRU only reads an
    auxiliary history sequence and its message is gated per sensor using the
    existing freshness/availability signals.
    """

    def __init__(self, config: CrossVariableConfig):
        super().__init__()
        self.hidden_dim = int(config.hidden_dim)
        self.num_sensors = int(config.num_sensors)
        self.context_dim = int(config.context_dim)
        self.gru_hidden = int(config.gru_hidden)
        if self.gru_hidden <= 0:
            raise ValueError("gru_hidden must be positive")
        if self.num_sensors <= 0:
            raise ValueError("gru_mixer requires num_sensors")
        if self.context_dim < 0:
            raise ValueError("context_dim must be non-negative")
        ratio = float(config.gru_bottleneck_ratio)
        if ratio <= 0:
            raise ValueError("gru_bottleneck_ratio must be positive")
        self.use_forward_fill = bool(config.use_forward_fill)
        input_dim = 2 * self.num_sensors + self.context_dim
        self.gru = nn.GRU(input_dim, self.gru_hidden, num_layers=1, batch_first=True)
        self.message = nn.Linear(self.gru_hidden, self.hidden_dim)
        bottleneck = max(1, int(self.hidden_dim / ratio))
        self.gate = nn.Sequential(
            nn.Linear(2 * self.hidden_dim + 2, bottleneck),
            nn.SiLU(),
            nn.Linear(bottleneck, self.hidden_dim),
        )
        self.direct_residual_head = (
            nn.Linear(self.gru_hidden, self.num_sensors)
            if config.direct_residual
            else None
        )
        if self.direct_residual_head is not None:
            nn.init.zeros_(self.direct_residual_head.weight)
            nn.init.zeros_(self.direct_residual_head.bias)
        self.last_gate = None
        self.last_direct_residual = None

    def forward(
        self,
        z: Tensor,
        freshness: Tensor,
        available: Tensor,
        X: Tensor | None = None,
        M_obs: Tensor | None = None,
        context: Tensor | None = None,
    ) -> Tensor:
        batch_size, num_sensors, hidden_dim = z.shape
        if num_sensors != self.num_sensors or hidden_dim != self.hidden_dim:
            raise ValueError(
                f"gru_mixer expected z [B,{self.num_sensors},{self.hidden_dim}], got {tuple(z.shape)}"
            )
        if X is None or M_obs is None:
            # Backward-compatible direct calls still produce finite output; the
            # KST-Light path always supplies the real auxiliary history.
            X = z.new_zeros(batch_size, 1, self.num_sensors)
            M_obs = z.new_zeros(batch_size, 1, self.num_sensors)
        if X.shape[:1] != z.shape[:1] or X.shape[-1] != self.num_sensors:
            raise ValueError("gru_mixer X must have shape [B,L,num_sensors]")
        if M_obs.shape != X.shape:
            raise ValueError("gru_mixer M_obs must match X shape")
        history = _forward_fill_history(X, M_obs) if self.use_forward_fill else X * M_obs
        sequence = [history, M_obs]
        if self.context_dim:
            if context is None:
                context = z.new_zeros(batch_size, self.context_dim)
            if context.shape != (batch_size, self.context_dim):
                raise ValueError("gru_mixer context has incompatible shape")
            sequence.append(context.unsqueeze(1).expand(-1, X.shape[1], -1))
        sequence_features = torch.cat(sequence, dim=-1)
        _, hidden = self.gru(sequence_features)
        global_state = hidden[-1]
        message = self.message(global_state).unsqueeze(1).expand(-1, num_sensors, -1)
        gate_features = torch.cat(
            [z, message, freshness.unsqueeze(-1), available.unsqueeze(-1)], dim=-1
        )
        gate = torch.sigmoid(self.gate(gate_features))
        self.last_gate = gate
        self.last_direct_residual = (
            self.direct_residual_head(global_state)
            if self.direct_residual_head is not None
            else None
        )
        return z + gate * message


def build_cross_variable_block(mode: str, config: CrossVariableConfig) -> nn.Module:
    builders = {
        "identity": IdentityCrossVariable,
        "fla": FLACrossVariable,
        "missing_graph": MissingnessAwareGraph,
        "gru_mixer": GRUConditionedMixer,
        "missing_sensor_mixer": MissingSensorMixer,
    }
    if mode not in builders:
        raise ValueError(f"unsupported cross_variable_mode: {mode}")
    return builders[mode](config)
