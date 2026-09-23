from typing import Dict, Optional, Tuple

import pandas as pd
import torch
from torch import Tensor

from .cmapss import SENSOR_COLUMNS


def compute_sensor_thresholds(
    frame: pd.DataFrame,
    lower_quantile: float = 0.05,
    upper_quantile: float = 0.95,
    sensor_mean: Optional[Tensor] = None,
    sensor_std: Optional[Tensor] = None,
) -> Tuple[Tensor, Tensor]:
    lower = torch.tensor(
        frame[SENSOR_COLUMNS].quantile(lower_quantile).to_numpy(), dtype=torch.float32
    )
    upper = torch.tensor(
        frame[SENSOR_COLUMNS].quantile(upper_quantile).to_numpy(), dtype=torch.float32
    )
    if sensor_mean is not None and sensor_std is not None:
        lower = (lower - sensor_mean) / sensor_std
        upper = (upper - sensor_mean) / sensor_std
    return lower, upper


def risk_from_samples(
    samples: Tensor,
    lower: Tensor,
    upper: Tensor,
    mask: Optional[Tensor] = None,
    aggregation: str = "any_sensor",
) -> Dict[str, Tensor]:
    """Convert joint samples into sensor, horizon, and device risk views.

    ``samples`` uses ``[B, S, H, N]``. The returned probabilities are sample
    frequencies; a query mask excludes positions from every denominator. The
    explicit aggregation controls the device score and is recorded alongside
    the tensors so calibration cannot silently change its meaning.
    """
    if samples.dim() != 4:
        raise ValueError("samples must have shape (B, S, Lp, N)")
    if aggregation not in {"any_sensor", "horizon_max"}:
        raise ValueError("aggregation must be any_sensor or horizon_max")
    if mask is None:
        mask = torch.ones(samples.shape[0], samples.shape[2], samples.shape[3], device=samples.device)
    mask = mask.to(samples.device).bool()
    if tuple(mask.shape) != (samples.shape[0], samples.shape[2], samples.shape[3]):
        raise ValueError("mask must have shape (B, Lp, N)")
    lower = lower.to(samples.device).view(1, 1, 1, -1)
    upper = upper.to(samples.device).view(1, 1, 1, -1)
    crossed = ((samples < lower) | (samples > upper)) & mask.unsqueeze(1)
    sensor_horizon_risk = crossed.float().mean(dim=1)
    sensor_horizon_risk = torch.where(mask, sensor_horizon_risk, torch.zeros_like(sensor_horizon_risk))
    sensor_risk = crossed.any(dim=2).float().mean(dim=1).clamp(0.0, 1.0)
    horizon_risk = crossed.any(dim=3).float().mean(dim=1).clamp(0.0, 1.0)
    any_sensor = crossed.any(dim=(2, 3)).float().mean(dim=1)
    horizon_max = horizon_risk.amax(dim=1)
    device_risk = any_sensor if aggregation == "any_sensor" else horizon_max
    return {
        "sensor_horizon_risk": sensor_horizon_risk,
        "sensor_risk": sensor_risk,
        "horizon_risk": horizon_risk,
        "device_risk": device_risk,
        "aggregation": aggregation,
    }


def rul_to_state(rul: Tensor, warning_threshold: float = 30.0, critical_threshold: float = 15.0) -> Tensor:
    state = torch.zeros_like(rul, dtype=torch.long)
    state = torch.where(rul <= warning_threshold, torch.ones_like(state), state)
    state = torch.where(rul <= critical_threshold, torch.full_like(state, 2), state)
    return state
