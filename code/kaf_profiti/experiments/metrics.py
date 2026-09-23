from typing import Dict, Optional

import numpy as np
import torch
from torch import Tensor

try:
    from sklearn.metrics import average_precision_score, f1_score, roc_auc_score
except Exception:  # pragma: no cover
    average_precision_score = None
    f1_score = None
    roc_auc_score = None


def safe_binary_metrics(
    labels: np.ndarray,
    scores: np.ndarray,
    threshold: float = 0.5,
    allow_orientation_selection: bool = False,
):
    labels = np.asarray(labels)
    scores = np.asarray(scores, dtype=float)
    valid = np.isfinite(labels) & np.isfinite(scores)
    labels = labels[valid].astype(int)
    scores = scores[valid]
    if labels.size == 0 or np.unique(labels).size < 2:
        return {
            "auroc": None,
            "auprc": None,
            "f1": None,
            "auroc_inverse": None,
            "auprc_inverse": None,
            "f1_inverse": None,
            "risk_orientation": None,
            "risk_orientation_selection": "enabled" if allow_orientation_selection else "disabled",
            "risk_inverse_would_help": None,
            "selected_auroc": None,
            "selected_auprc": None,
            "selected_f1": None,
            "best_f1": None,
            "best_f1_threshold": None,
            "best_f1_source": "same_split_diagnostic_only",
        }

    inverse_scores = 1.0 - scores
    pred = (scores >= threshold).astype(int)
    pred_inverse = (inverse_scores >= threshold).astype(int)
    auroc = float(roc_auc_score(labels, scores)) if roc_auc_score else None
    auprc = float(average_precision_score(labels, scores)) if average_precision_score else None
    f1 = float(f1_score(labels, pred)) if f1_score else None
    auroc_inverse = float(roc_auc_score(labels, inverse_scores)) if roc_auc_score else None
    auprc_inverse = (
        float(average_precision_score(labels, inverse_scores)) if average_precision_score else None
    )
    f1_inverse = float(f1_score(labels, pred_inverse)) if f1_score else None

    use_inverse = (
        allow_orientation_selection
        and auroc is not None
        and auroc_inverse is not None
        and auroc_inverse > auroc
    )
    inverse_would_help = (
        auroc is not None
        and auroc_inverse is not None
        and auroc_inverse > auroc
    )
    selected_scores = inverse_scores if use_inverse else scores
    selected_pred = pred_inverse if use_inverse else pred
    best_f1, best_threshold = _best_f1_threshold(labels, selected_scores)
    return {
        "auroc": auroc,
        "auprc": auprc,
        "f1": f1,
        "auroc_inverse": auroc_inverse,
        "auprc_inverse": auprc_inverse,
        "f1_inverse": f1_inverse,
        "risk_orientation": "inverted" if use_inverse else "direct",
        "risk_orientation_selection": "enabled" if allow_orientation_selection else "disabled",
        "risk_inverse_would_help": bool(inverse_would_help),
        "selected_auroc": auroc_inverse if use_inverse else auroc,
        "selected_auprc": auprc_inverse if use_inverse else auprc,
        "selected_f1": (
            float(f1_score(labels, selected_pred)) if f1_score else None
        ),
        "best_f1": best_f1,
        "best_f1_threshold": best_threshold,
        "best_f1_source": "same_split_diagnostic_only",
    }


def _best_f1_threshold(labels: np.ndarray, scores: np.ndarray):
    if f1_score is None:
        return None, None
    thresholds = np.unique(scores)
    best_f1 = None
    best_threshold = None
    for threshold in thresholds:
        pred = (scores >= threshold).astype(int)
        score = float(f1_score(labels, pred))
        if best_f1 is None or score > best_f1:
            best_f1 = score
            best_threshold = float(threshold)
    return best_f1, best_threshold


def expected_calibration_error(labels: np.ndarray, scores: np.ndarray, bins: int = 10) -> Optional[float]:
    labels = np.asarray(labels, dtype=float)
    scores = np.asarray(scores, dtype=float)
    valid = np.isfinite(labels) & np.isfinite(scores)
    labels = labels[valid]
    scores = scores[valid]
    if labels.size == 0:
        return None
    edges = np.linspace(0.0, 1.0, bins + 1)
    ece = 0.0
    for start, end in zip(edges[:-1], edges[1:]):
        in_bin = (scores >= start) & (scores < end if end < 1.0 else scores <= end)
        if not in_bin.any():
            continue
        confidence = scores[in_bin].mean()
        accuracy = labels[in_bin].mean()
        ece += float(in_bin.mean() * abs(confidence - accuracy))
    return ece


def interval_metrics(y: Tensor, samples: Tensor, mask: Tensor, alpha: float = 0.05):
    if torch.isfinite(samples).all() and torch.isfinite(y).all():
        lower = torch.quantile(samples, alpha / 2, dim=1)
        upper = torch.quantile(samples, 1 - alpha / 2, dim=1)
        covered = ((y >= lower) & (y <= upper)).float() * mask
        picp = covered.sum() / mask.sum().clamp_min(1.0)
        mpiw = ((upper - lower) * mask).sum() / mask.sum().clamp_min(1.0)
        return float(picp.cpu()), float(mpiw.cpu())

    sample_valid = torch.isfinite(samples)
    samples_clean = torch.where(sample_valid, samples, torch.full_like(samples, float("nan")))
    lower = torch.nanquantile(samples_clean, alpha / 2, dim=1)
    upper = torch.nanquantile(samples_clean, 1 - alpha / 2, dim=1)
    valid = (mask > 0) & torch.isfinite(y) & torch.isfinite(lower) & torch.isfinite(upper)
    covered = ((y >= lower) & (y <= upper) & valid).float()
    valid_count = valid.float().sum().clamp_min(1.0)
    picp = covered.sum() / valid_count
    mpiw = torch.where(valid, upper - lower, torch.zeros_like(upper)).sum() / valid_count
    return float(picp.cpu()), float(mpiw.cpu())


def point_metrics(y: Tensor, mean: Tensor, mask: Tensor):
    valid = (mask > 0) & torch.isfinite(y) & torch.isfinite(mean)
    diff = torch.where(valid, mean - y, torch.zeros_like(mean))
    valid_count = valid.float().sum().clamp_min(1.0)
    mae = diff.abs().sum() / valid_count
    rmse = torch.sqrt((diff.pow(2).sum() / valid_count).clamp_min(0.0))
    return float(mae.cpu()), float(rmse.cpu())


def risk_score_from_samples(samples: Tensor) -> Tensor:
    if torch.isfinite(samples).all():
        return torch.sigmoid(samples.abs().mean(dim=(1, 2, 3)))

    valid = torch.isfinite(samples)
    values = torch.where(valid, samples.abs(), torch.zeros_like(samples))
    count = valid.float().sum(dim=(1, 2, 3))
    mean_abs = values.sum(dim=(1, 2, 3)) / count.clamp_min(1.0)
    scores = torch.sigmoid(mean_abs)
    return torch.where(count > 0, scores, torch.full_like(scores, float("nan")))


def completed_metrics_template() -> Dict[str, object]:
    return {
        "mae": None,
        "rmse": None,
        "nll": None,
        "crps": None,
        "picp": None,
        "mpiw": None,
        "auroc": None,
        "auprc": None,
        "f1": None,
        "ece": None,
        "lead_time": None,
        "train_time_sec": None,
        "infer_time_ms_per_batch": None,
        "num_params": None,
        "gpu_memory_mb": None,
    }
