import numpy as np
import torch
from torch import Tensor


def gaussian_crps(y: Tensor, mean: Tensor, scale: Tensor, mask: Tensor) -> float:
    normal = torch.distributions.Normal(torch.zeros_like(mean), torch.ones_like(scale))
    z = (y - mean) / scale
    phi = torch.exp(normal.log_prob(z))
    Phi = normal.cdf(z)
    crps = scale * (z * (2.0 * Phi - 1.0) + 2.0 * phi - 1.0 / np.sqrt(np.pi))
    crps = crps * mask
    return float((crps.sum() / mask.sum().clamp_min(1.0)).detach().cpu())


def gaussian_interval_metrics(
    y: Tensor,
    mean: Tensor,
    scale: Tensor,
    mask: Tensor,
    alpha: float = 0.05,
):
    dist = torch.distributions.Normal(torch.zeros((), device=y.device), torch.ones((), device=y.device))
    z_low = dist.icdf(torch.tensor(alpha / 2, device=y.device, dtype=y.dtype))
    z_high = dist.icdf(torch.tensor(1.0 - alpha / 2, device=y.device, dtype=y.dtype))
    lower = mean + z_low * scale
    upper = mean + z_high * scale
    valid = (mask > 0) & torch.isfinite(y) & torch.isfinite(lower) & torch.isfinite(upper)
    count = valid.float().sum().clamp_min(1.0)
    covered = ((y >= lower) & (y <= upper) & valid).float()
    picp = covered.sum() / count
    mpiw = torch.where(valid, upper - lower, torch.zeros_like(upper)).sum() / count
    return float(picp.detach().cpu()), float(mpiw.detach().cpu())


def gaussian_risk_score(mean: Tensor, scale: Tensor) -> Tensor:
    return torch.sigmoid(mean.abs().mean(dim=(1, 2)) + scale.clamp_min(0.0).mean(dim=(1, 2)))
