import math

import torch
from torch import Tensor, nn


class QueryConditionAdapter(nn.Module):
    def __init__(
        self,
        num_sensors: int,
        hidden_dim: int,
        time_dim: int,
        context_dim: int = 0,
        max_len: int = 1024,
    ):
        super().__init__()
        self.num_sensors = num_sensors
        self.hidden_dim = hidden_dim
        self.time_dim = time_dim
        self.channel_embedding = nn.Embedding(num_sensors, hidden_dim)
        self.time_scale = nn.Linear(1, 1)
        self.time_sin = nn.Linear(1, (time_dim - 1) // 2)
        self.time_cos = nn.Linear(1, time_dim - 1 - ((time_dim - 1) // 2))
        self.context_proj = nn.Linear(context_dim, hidden_dim) if context_dim > 0 else None
        input_dim = hidden_dim + time_dim + hidden_dim
        if self.context_proj is not None:
            input_dim += hidden_dim
        self.proj = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(True),
            nn.Linear(hidden_dim, hidden_dim),
        )

    def build_time_first_channel_ids(self, pred_len: int, device=None) -> Tensor:
        return torch.arange(self.num_sensors, dtype=torch.long, device=device).repeat(pred_len)

    def _time_embedding(self, t: Tensor) -> Tensor:
        t = t.unsqueeze(-1)
        return torch.cat(
            [self.time_scale(t), torch.sin(self.time_sin(t)), torch.cos(self.time_cos(t))],
            dim=-1,
        )

    def forward(
        self,
        z_var: Tensor,
        T_q: Tensor,
        channel_ids: Tensor,
        context: Tensor = None,
    ) -> Tensor:
        batch_size, num_sensors, hidden_dim = z_var.shape
        if num_sensors != self.num_sensors:
            raise ValueError(f"Expected {self.num_sensors} sensors, got {num_sensors}")
        if hidden_dim != self.hidden_dim:
            raise ValueError(f"Expected hidden_dim {self.hidden_dim}, got {hidden_dim}")

        channel_ids = channel_ids.to(z_var.device).long()
        query_count = channel_ids.numel()
        pred_len = T_q.shape[1]
        if query_count != pred_len * self.num_sensors:
            raise ValueError("channel_ids must have length pred_len * num_sensors")

        z_query = z_var[:, channel_ids, :]
        t_flat = T_q.repeat_interleave(self.num_sensors, dim=1)
        time_features = self._time_embedding(t_flat)
        channel_features = self.channel_embedding(channel_ids).unsqueeze(0).expand(batch_size, -1, -1)
        pieces = [z_query, time_features, channel_features]
        if self.context_proj is not None:
            if context is None:
                context_features = torch.zeros(
                    batch_size, query_count, self.hidden_dim, device=z_var.device
                )
            else:
                context_features = self.context_proj(context).unsqueeze(1).expand(-1, query_count, -1)
            pieces.append(context_features)
        return self.proj(torch.cat(pieces, dim=-1))
