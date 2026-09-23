"""Causal, history-only features for asynchronous observations."""

from dataclasses import dataclass

import torch
from torch import Tensor, nn


@dataclass(frozen=True)
class MissingnessFeatureBatch:
    delta_t: Tensor
    freshness: Tensor
    block_length: Tensor
    has_history: Tensor
    observed_ratio: Tensor


class MissingnessFeatures(nn.Module):
    """Compute observation age and missing-block features for ``[B, L, N]``."""

    def __init__(self, freshness_tau: float = 24.0, max_delta: float = 1_000.0):
        super().__init__()
        if freshness_tau <= 0 or max_delta <= 0:
            raise ValueError("freshness_tau and max_delta must be positive")
        self.freshness_tau = float(freshness_tau)
        self.max_delta = float(max_delta)

    @staticmethod
    def _expand_times(times: Tensor, sensors: int) -> Tensor:
        if times.dim() == 2:
            return times.unsqueeze(-1).expand(-1, -1, sensors)
        if times.dim() == 3 and times.shape[-1] == sensors:
            return times
        raise ValueError("times must have shape [B,L] or [B,L,N]")

    def forward(self, times: Tensor, mask: Tensor) -> MissingnessFeatureBatch:
        if mask.dim() != 3:
            raise ValueError("mask must have shape [B,L,N]")
        if times.shape[:2] != mask.shape[:2]:
            raise ValueError("times and mask history dimensions must match")
        mask = mask.to(dtype=torch.float32)
        times = self._expand_times(times.to(mask), mask.shape[-1])
        batch, length, sensors = mask.shape
        last_time = torch.zeros(batch, sensors, device=mask.device, dtype=times.dtype)
        seen = torch.zeros(batch, sensors, device=mask.device, dtype=mask.dtype)
        previous_block = torch.zeros_like(seen)
        deltas = []
        blocks = []
        histories = []
        for step in range(length):
            observed = mask[:, step] > 0
            current_time = times[:, step]
            elapsed = (current_time - last_time).clamp_min(0.0)
            elapsed = torch.where(seen > 0, elapsed, torch.full_like(elapsed, self.max_delta))
            step_delta = torch.where(observed, torch.zeros_like(elapsed), elapsed)
            step_block = torch.where(observed, torch.zeros_like(previous_block), previous_block + 1.0)
            seen = torch.maximum(seen, observed.to(mask.dtype))
            last_time = torch.where(observed, current_time, last_time)
            previous_block = step_block
            deltas.append(step_delta)
            blocks.append(step_block)
            histories.append(seen.clone())
        delta_t = torch.stack(deltas, dim=1).clamp(0.0, self.max_delta)
        block_length = torch.stack(blocks, dim=1)
        has_history = torch.stack(histories, dim=1)
        freshness = torch.exp(-delta_t / self.freshness_tau)
        cumulative_count = mask.cumsum(dim=1)
        denominator = torch.arange(1, length + 1, device=mask.device, dtype=mask.dtype).view(1, -1, 1)
        observed_ratio = cumulative_count / denominator
        return MissingnessFeatureBatch(
            delta_t=delta_t,
            freshness=freshness,
            block_length=block_length,
            has_history=has_history,
            observed_ratio=observed_ratio,
        )
