import math
from dataclasses import dataclass
from typing import Dict, Tuple

import torch
from torch import Tensor


# Canonical mechanism ids and their accepted display aliases. A mechanism must
# have exactly one canonical id so pilot matrices and mask artifacts share one
# scientific key per missing structure.
_MECHANISM_ALIASES: Dict[str, str] = {
    "random": "random",
    "low_rate": "low_rate",
    "low-rate": "low_rate",
    "block": "block_offline",
    "block_offline": "block_offline",
    "block-offline": "block_offline",
    "mixed": "mixed",
    "none": "none",
}


def canonical_mechanism(name: str) -> str:
    """Return the canonical mechanism id for a display name or alias.

    Raises:
        ValueError: If the name is not a registered mechanism or alias.
    """
    canonical = _MECHANISM_ALIASES.get(str(name).strip().lower())
    if canonical is None:
        raise ValueError(f"Unknown missing mechanism: {name!r}")
    return canonical


def timeline_random_mask(timeline_len: int, num_sensors: int, keep_prob: float, generator) -> Tensor:
    """Independent per-cell observation with keep probability ``keep_prob``."""
    return (torch.rand(timeline_len, num_sensors, generator=generator) < keep_prob).float()


def timeline_low_rate_mask(timeline_len: int, num_sensors: int, keep_prob: float, generator) -> Tensor:
    """Low-rate periodic sampling with expected keep probability ``keep_prob``.

    Each channel keeps its period grid (``period = floor(1/keep_prob)``) and
    retains grid rows with probability ``keep_prob * period`` so the expected
    observed fraction equals ``keep_prob`` exactly while observations stay on
    the low-rate grid.
    """
    period = max(1, int(math.floor(1.0 / max(keep_prob, 1e-6))))
    retain = min(1.0, keep_prob * period)
    mask = torch.zeros(timeline_len, num_sensors)
    for sensor_idx in range(num_sensors):
        offset = int(torch.randint(0, period, (1,), generator=generator).item())
        grid = torch.arange(offset, timeline_len, period)
        if grid.numel() == 0:
            continue
        keep = (torch.rand(grid.numel(), generator=generator) < retain).float()
        mask[grid, sensor_idx] = keep
    return mask


def timeline_block_offline_mask(
    timeline_len: int,
    num_sensors: int,
    block_prob: float,
    generator,
    max_block_fraction: float = 0.5,
) -> Tensor:
    """Continuous per-channel offline segments; ``block_prob`` is the knob.

    Each channel goes offline (one contiguous segment of random length up to
    ``max_block_fraction`` of the timeline) with probability ``block_prob``.
    The expected realized missing rate is monotone in ``block_prob``, which is
    what the calibration loop bisects.
    """
    mask = torch.ones(timeline_len, num_sensors)
    max_block = max(1, int(timeline_len * max_block_fraction))
    for sensor_idx in range(num_sensors):
        if torch.rand((), generator=generator).item() >= block_prob:
            continue
        block_len = int(torch.randint(1, max_block + 1, (1,), generator=generator).item())
        max_start = max(1, timeline_len - block_len + 1)
        start = int(torch.randint(0, max_start, (1,), generator=generator).item())
        mask[start : start + block_len, sensor_idx] = 0.0
    return mask


def timeline_mixed_mask(
    timeline_len: int,
    num_sensors: int,
    keep_prob: float,
    generator,
    low_rate_keep: float = 0.80,
    block_prob: float = 0.25,
) -> Tensor:
    """Mixed mechanism: fixed low-rate + block structure, calibrated dropout.

    The low-rate and offline-block structural contributions are fixed at
    pre-registered defaults; the independent dropout ``keep_prob`` is the
    continuous knob calibrated so the combined realized rate hits the target.
    """
    low_rate = timeline_low_rate_mask(timeline_len, num_sensors, low_rate_keep, generator)
    dropout = timeline_random_mask(timeline_len, num_sensors, keep_prob, generator)
    mask = low_rate * dropout
    return timeline_block_offline_mask(
        timeline_len, num_sensors, block_prob, generator
    ) * mask


@dataclass
class MissingMechanismSimulator:
    """Deterministic asynchronous-observation mask simulator."""

    mode: str = "mixed"
    random_keep_prob: float = 0.85
    min_period: int = 1
    max_period: int = 4
    block_prob: float = 0.25
    max_block_fraction: float = 0.25

    def __call__(self, shape: Tuple[int, int], seed: int) -> Tensor:
        history_len, num_sensors = shape
        if self.mode == "none":
            return torch.ones(history_len, num_sensors, dtype=torch.float32)

        generator = torch.Generator().manual_seed(int(seed))
        if self.mode == "random":
            mask = self._random_mask(history_len, num_sensors, generator)
        elif self.mode == "low_rate":
            mask = self._low_rate_mask(history_len, num_sensors, generator)
        elif self.mode == "block_offline":
            mask = torch.ones(history_len, num_sensors, dtype=torch.float32)
            mask = self._apply_block_offline(mask, generator)
        elif self.mode == "mixed":
            mask = self._low_rate_mask(history_len, num_sensors, generator)
            mask = mask * self._random_mask(history_len, num_sensors, generator)
            mask = self._apply_block_offline(mask, generator)
        else:
            raise ValueError(f"Unknown async mask mode: {self.mode}")

        return self._ensure_observed(mask, generator)

    def _random_mask(self, history_len: int, num_sensors: int, generator: torch.Generator) -> Tensor:
        return (
            torch.rand(history_len, num_sensors, generator=generator) < self.random_keep_prob
        ).float()

    def _low_rate_mask(self, history_len: int, num_sensors: int, generator: torch.Generator) -> Tensor:
        mask = torch.zeros(history_len, num_sensors, dtype=torch.float32)
        periods = torch.randint(
            self.min_period,
            self.max_period + 1,
            (num_sensors,),
            generator=generator,
        )
        for sensor_idx, period in enumerate(periods.tolist()):
            offset = int(torch.randint(0, period, (1,), generator=generator).item())
            mask[offset::period, sensor_idx] = 1.0
        return mask

    def _apply_block_offline(self, mask: Tensor, generator: torch.Generator) -> Tensor:
        history_len, num_sensors = mask.shape
        max_block = max(1, int(history_len * self.max_block_fraction))
        for sensor_idx in range(num_sensors):
            if torch.rand((), generator=generator).item() >= self.block_prob:
                continue
            block_len = int(torch.randint(1, max_block + 1, (1,), generator=generator).item())
            max_start = max(1, history_len - block_len + 1)
            start = int(torch.randint(0, max_start, (1,), generator=generator).item())
            mask[start : start + block_len, sensor_idx] = 0.0
        return mask

    @staticmethod
    def _ensure_observed(mask: Tensor, generator: torch.Generator) -> Tensor:
        history_len, num_sensors = mask.shape
        for sensor_idx in range(num_sensors):
            if mask[:, sensor_idx].sum() == 0:
                row = int(torch.randint(0, history_len, (1,), generator=generator).item())
                mask[row, sensor_idx] = 1.0
        if mask.sum() == 0:
            mask[0, 0] = 1.0
        return mask
