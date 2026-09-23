import numpy as np
import torch
from torch import Tensor


def gaussian_crps(y: Tensor, mean: Tensor, scale: Tensor, mask: Tensor) -> float:
    normal = torch.distributions.Normal(torch.zeros_like(mean), torch.ones_like(scale))
    z = (y - mean) / scale.clamp_min(1e-6)
    phi = torch.exp(normal.log_prob(z))
    Phi = normal.cdf(z)
    crps = scale * (z * (2.0 * Phi - 1.0) + 2.0 * phi - 1.0 / np.sqrt(np.pi))
    valid = (mask > 0) & torch.isfinite(crps)
    total = torch.where(valid, crps, torch.zeros_like(crps)).sum()
    count = valid.float().sum().clamp_min(1.0)
    return float((total / count).detach().cpu())


def gaussian_interval_metrics(y: Tensor, mean: Tensor, scale: Tensor, mask: Tensor, alpha: float = 0.05):
    dist = torch.distributions.Normal(
        torch.zeros((), device=y.device, dtype=y.dtype),
        torch.ones((), device=y.device, dtype=y.dtype),
    )
    z_low = dist.icdf(torch.tensor(alpha / 2, device=y.device, dtype=y.dtype))
    z_high = dist.icdf(torch.tensor(1.0 - alpha / 2, device=y.device, dtype=y.dtype))
    lower = mean + z_low * scale
    upper = mean + z_high * scale
    valid = (mask > 0) & torch.isfinite(y) & torch.isfinite(lower) & torch.isfinite(upper)
    count = valid.float().sum().clamp_min(1.0)
    covered = ((y >= lower) & (y <= upper) & valid).float()
    width = torch.where(valid, upper - lower, torch.zeros_like(upper))
    return float((covered.sum() / count).detach().cpu()), float((width.sum() / count).detach().cpu())


def window_rmse(y: Tensor, mean: Tensor, mask: Tensor) -> np.ndarray:
    valid = (mask > 0) & torch.isfinite(y) & torch.isfinite(mean)
    diff2 = torch.where(valid, (mean - y).pow(2), torch.zeros_like(mean))
    denom = valid.float().sum(dim=(1, 2)).clamp_min(1.0)
    return torch.sqrt(diff2.sum(dim=(1, 2)) / denom).detach().cpu().numpy()
