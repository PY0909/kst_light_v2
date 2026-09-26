#!/usr/bin/env python
import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import torch
from torch.optim import AdamW
from torch.utils.data import DataLoader

from kaf_profiti.experiments.accumulators import GlobalMetricAccumulator
from kaf_profiti.experiments.datasets import create_protocol_datasets
from kaf_profiti.experiments.manifest import (
    LitePipeline,
    build_training_manifest,
    peak_gpu_memory_mb,
    peak_host_memory_mb,
    write_training_manifest,
)
from kaf_profiti.experiments.masks import MaskedWindowDataset, generate_or_load_split_masks
from kaf_profiti.experiments.metrics import (
    completed_metrics_template,
    expected_calibration_error,
    interval_metrics,
    risk_score_from_samples,
    safe_binary_metrics,
)
from kaf_profiti.experiments.registry import create_model, get_model_spec
from kaf_profiti.experiments.runtime_paths import resolve_runtime_paths
from kaf_profiti.industrial.batch import IndustrialCollator, IndustrialBatch


@dataclass
class ExperimentConfig:
    dataset: str
    model: str = "kaf_profiti_joint"
    seed: int = 2026
    missing_rate: float = 0.3
    history_len: int = 96
    pred_len: int = 24
    stride: int = 1
    data_root: Optional[str] = None
    output_dir: Optional[str] = None
    run_id: str = ""
    epochs: int = 1
    batch_size: int = 16
    max_train_batches: int = 20
    max_eval_batches: int = 20
    nsamples: int = 20
    device: str = "cpu"
    missing_mode: str = "mixed"
    lr: float = 1e-3
    weight_decay: float = 1e-4
    risk_threshold: float = 30.0
    hidden_dim: int = 32
    te_dim: int = 5
    kernel_count: int = 4
    n_layers: int = 2
    n_heads: int = 2
    flow_layers: int = 2
    preconv_dim: int = 8
    lambda_point: float = 0.1
    patch_lens: str = "12,24,48"
    graph_layers: int = 1
    copula_rank: int = 32
    lambda_quantile: float = 0.2
    lambda_risk: float = 0.05
    attention_diag_floor: float = 0.05
    sample_clip: float = 20.0
    inverse_clip: float = 1_000_000.0
    checkpoint: str = ""
    run_level: str = "formal"
    #: 0 keeps library/test callers workerless; the CLI pins the
    #: lite_pipeline_v1 contract value 4 for real invocations.
    num_workers: int = 0


def _batch_to_device(batch: IndustrialBatch, device, non_blocking: bool = True) -> IndustrialBatch:
    if not non_blocking:
        return batch.to(device)
    import dataclasses as _dc

    return IndustrialBatch(**{
        f.name: (
            getattr(batch, f.name).to(device, non_blocking=True)
            if torch.is_tensor(getattr(batch, f.name))
            else getattr(batch, f.name)
        )
        for f in _dc.fields(IndustrialBatch)
    })


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def _write_config_yaml(path: Path, config: ExperimentConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}: {value}" for key, value in asdict(config).items()]
    path.write_text("\n".join(lines) + "\n")


def _timestamp_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _run_dir(output_dir: Path, config: ExperimentConfig) -> Path:
    return output_dir / config.run_id


def _run_artifact_dir(output_dir: Path, artifact: str, config: ExperimentConfig) -> Path:
    return _run_dir(output_dir, config) / artifact / config.dataset / config.model


def _finite_np(array: np.ndarray, clip: Optional[float] = None) -> np.ndarray:
    if clip is None:
        cleaned = np.nan_to_num(array, nan=0.0, posinf=0.0, neginf=0.0)
        return cleaned
    clip = float(clip)
    cleaned = np.nan_to_num(array, nan=0.0, posinf=clip, neginf=-clip)
    return np.clip(cleaned, -clip, clip)


class PredictionNpyWriter:
    def __init__(
        self,
        pred_dir: Path,
        seed: int,
        total_examples: int,
        nsamples: int,
        query_count: int,
        suffix: str = "",
        finite_clip: float = 20.0,
    ):
        self.pred_dir = Path(pred_dir)
        self.pred_dir.mkdir(parents=True, exist_ok=True)
        self.total_examples = int(total_examples)
        self.offset = 0
        self.finite_clip = float(finite_clip)
        suffix = str(suffix)
        self.mean = np.lib.format.open_memmap(
            self.pred_dir / f"mean_seed{seed}{suffix}.npy",
            mode="w+",
            dtype=np.float32,
            shape=(self.total_examples, int(query_count)),
        )
        self.samples = np.lib.format.open_memmap(
            self.pred_dir / f"samples_seed{seed}{suffix}.npy",
            mode="w+",
            dtype=np.float32,
            shape=(self.total_examples, int(nsamples), int(query_count)),
        )
        self.risk = np.lib.format.open_memmap(
            self.pred_dir / f"risk_seed{seed}{suffix}.npy",
            mode="w+",
            dtype=np.float32,
            shape=(self.total_examples,),
        )

    def write(self, mean: np.ndarray, samples: np.ndarray, risk: np.ndarray) -> None:
        batch_size = int(mean.shape[0])
        end = self.offset + batch_size
        if end > self.total_examples:
            raise ValueError("Prediction writer received more rows than allocated")
        self.mean[self.offset:end] = _finite_np(mean, self.finite_clip).astype(
            np.float32, copy=False
        )
        self.samples[self.offset:end] = _finite_np(samples, self.finite_clip).astype(
            np.float32, copy=False
        )
        self.risk[self.offset:end] = np.clip(_finite_np(risk, None), 0.0, 1.0).astype(
            np.float32, copy=False
        )
        self.offset = end
        self.mean.flush()
        self.samples.flush()
        self.risk.flush()

    def close(self) -> None:
        self.mean.flush()
        self.samples.flush()
        self.risk.flush()


def _train_epoch(model, loader, optimizer, device: torch.device, max_batches: int):
    total = 0.0
    count = 0
    start = time.perf_counter()
    model.train()
    for idx, batch in enumerate(loader):
        if max_batches and idx >= max_batches:
            break
        batch = _batch_to_device(batch, device, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        loss = model.loss(batch, nsamples_for_point=1)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        total += float(loss.detach().cpu())
        count += 1
    return {
        "train_loss": total / max(count, 1),
        "train_batches": count,
        "train_time_sec": time.perf_counter() - start,
    }


def _risk_labels(dataset: str, batch, risk_threshold: float):
    if dataset.startswith("cmapss"):
        return (batch.rul <= risk_threshold).float()
    return batch.rul.float().clamp(0, 1)


def _limited_eval_examples(loader, max_batches: int) -> int:
    dataset_len = len(loader.dataset)
    if not max_batches:
        return dataset_len
    return min(dataset_len, int(max_batches) * int(loader.batch_size))


def _nonfinite_rows(tensor: torch.Tensor) -> int:
    return int((~torch.isfinite(tensor).reshape(tensor.shape[0], -1).all(dim=1)).sum().cpu())


def _finite_metric_positions(y: torch.Tensor, mean: torch.Tensor, mask: torch.Tensor) -> int:
    valid = (mask > 0) & torch.isfinite(y) & torch.isfinite(mean)
    return int(valid.sum().cpu())


def _quantile_interval_metrics(y: torch.Tensor, quantiles: torch.Tensor, mask: torch.Tensor):
    if quantiles is None:
        return None, None
    lower = quantiles[:, 0, :]
    upper = quantiles[:, -1, :]
    valid = (mask > 0) & torch.isfinite(y) & torch.isfinite(lower) & torch.isfinite(upper)
    valid_count = valid.float().sum().clamp_min(1.0)
    covered = ((y >= lower) & (y <= upper) & valid).float()
    picp = covered.sum() / valid_count
    mpiw = torch.where(valid, upper - lower, torch.zeros_like(upper)).sum() / valid_count
    return float(picp.cpu()), float(mpiw.cpu())


def _quantile_interval_tensors(
    y: torch.Tensor,
    quantiles: torch.Tensor,
    mask: torch.Tensor,
    conformal_qhat: float = 0.0,
):
    if quantiles is None:
        return None, None, None, None
    qhat = float(max(conformal_qhat, 0.0))
    lower = quantiles[:, 0, :] - qhat
    upper = quantiles[:, -1, :] + qhat
    valid = (mask > 0) & torch.isfinite(y) & torch.isfinite(lower) & torch.isfinite(upper)
    valid_count = valid.float().sum().clamp_min(1.0)
    covered = ((y >= lower) & (y <= upper) & valid).float()
    picp = covered.sum() / valid_count
    mpiw = torch.where(valid, upper - lower, torch.zeros_like(upper)).sum() / valid_count
    return lower, upper, float(picp.cpu()), float(mpiw.cpu())


def _sample_interval_tensors(
    y: torch.Tensor,
    samples: torch.Tensor,
    mask: torch.Tensor,
    alpha: float = 0.05,
    conformal_qhat: float = 0.0,
):
    qhat = float(max(conformal_qhat, 0.0))
    samples_clean = torch.where(
        torch.isfinite(samples),
        samples,
        torch.full_like(samples, float("nan")),
    )
    lower = torch.nanquantile(samples_clean, alpha / 2, dim=1) - qhat
    upper = torch.nanquantile(samples_clean, 1 - alpha / 2, dim=1) + qhat
    valid = (mask > 0) & torch.isfinite(y) & torch.isfinite(lower) & torch.isfinite(upper)
    valid_count = valid.float().sum().clamp_min(1.0)
    covered = ((y >= lower) & (y <= upper) & valid).float()
    picp = covered.sum() / valid_count
    mpiw = torch.where(valid, upper - lower, torch.zeros_like(upper)).sum() / valid_count
    return lower, upper, float(picp.cpu()), float(mpiw.cpu())


def _window_rmse(y: torch.Tensor, mean: torch.Tensor, mask: torch.Tensor) -> np.ndarray:
    valid = (mask > 0) & torch.isfinite(y) & torch.isfinite(mean)
    diff2 = torch.where(valid, (mean - y).pow(2), torch.zeros_like(mean))
    denom = valid.float().sum(dim=-1).clamp_min(1.0)
    rmse = torch.sqrt(diff2.sum(dim=-1) / denom)
    return rmse.detach().cpu().numpy()


def _top_error_diagnostics(
    window_rmse: np.ndarray,
    fraction: float = 0.01,
    source: str = "test_diagnostic_only",
) -> Dict[str, object]:
    values = np.asarray(window_rmse, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return {
            "top_error_source": source,
            "top_error_fraction": fraction,
            "top_error_count": 0,
            "top_error_rmse_mean": None,
            "top_error_rmse_max": None,
        }
    count = max(1, int(np.ceil(values.size * float(fraction))))
    top = np.sort(values)[-count:]
    return {
        "top_error_source": source,
        "top_error_fraction": float(fraction),
        "top_error_count": int(count),
        "top_error_rmse_mean": float(top.mean()),
        "top_error_rmse_max": float(top.max()),
    }


def _apply_risk_calibration(scores, calibration: Optional[Dict[str, object]]):
    if calibration is None:
        return scores
    orientation = calibration.get("risk_orientation", "direct")
    calibrated = 1.0 - scores if orientation == "inverted" else scores
    return calibrated.clamp(0.0, 1.0) if torch.is_tensor(calibrated) else np.clip(calibrated, 0.0, 1.0)


def _fit_risk_calibration(
    labels: np.ndarray,
    scores: np.ndarray,
    quantile: float = 0.95,
) -> Dict[str, object]:
    labels = np.asarray(labels, dtype=float)
    scores = np.asarray(scores, dtype=float)
    valid = np.isfinite(labels) & np.isfinite(scores)
    labels = labels[valid]
    scores = scores[valid]
    if labels.size == 0:
        return {
            "risk_calibration_source": "validation_unavailable",
            "risk_orientation": "direct",
            "risk_threshold": 0.5,
            "risk_threshold_source": "default",
            "risk_calibration_quantile": float(quantile),
        }

    labels = np.clip(labels, 0.0, 1.0).astype(int)
    normal_mask = labels < 0.5
    metrics = None
    if np.unique(labels).size >= 2:
        metrics = safe_binary_metrics(labels, scores, allow_orientation_selection=True)
        orientation = metrics.get("risk_orientation") or "direct"
    else:
        normal_scores = scores[normal_mask] if normal_mask.any() else scores
        orientation = "inverted" if float(np.median(normal_scores)) > 0.5 else "direct"
    selected_scores = 1.0 - scores if orientation == "inverted" else scores
    selected_normal = selected_scores[normal_mask] if normal_mask.any() else selected_scores
    threshold = float(np.quantile(selected_normal, float(quantile)))
    return {
        "risk_calibration_source": "validation_normal_quantile",
        "risk_orientation": orientation,
        "risk_threshold": threshold,
        "risk_threshold_source": "validation_normal_quantile",
        "risk_calibration_quantile": float(quantile),
        "risk_alarm_budget": float(quantile),
        "validation_selected_auroc": metrics.get("selected_auroc") if metrics else None,
        "validation_selected_auprc": metrics.get("selected_auprc") if metrics else None,
        "validation_best_f1": metrics.get("best_f1") if metrics else None,
        "validation_best_f1_threshold": metrics.get("best_f1_threshold") if metrics else None,
        "validation_best_f1_source": "diagnostic_only" if metrics else None,
        "validation_risk_score_mean": float(np.mean(selected_scores)),
        "validation_normal_score_quantile": threshold,
        "validation_normal_count": int(normal_mask.sum()),
    }


def _fit_conformal_qhat(
    y: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    mask: np.ndarray,
    alpha: float = 0.05,
) -> float:
    y = np.asarray(y, dtype=float).reshape(-1)
    lower = np.asarray(lower, dtype=float).reshape(-1)
    upper = np.asarray(upper, dtype=float).reshape(-1)
    mask = np.asarray(mask, dtype=float).reshape(-1)
    valid = (mask > 0) & np.isfinite(y) & np.isfinite(lower) & np.isfinite(upper)
    if not valid.any():
        return 0.0
    scores = np.maximum.reduce([lower[valid] - y[valid], y[valid] - upper[valid], np.zeros(valid.sum())])
    scores = np.sort(scores)
    n = len(scores)
    rank = int(np.ceil((n + 1) * (1.0 - float(alpha))))
    rank = min(max(rank, 1), n)
    return float(max(scores[rank - 1], 0.0))


def _collect_validation_calibration(
    model,
    loader,
    device: torch.device,
    config: ExperimentConfig,
    num_sensors: int,
) -> Dict[str, object]:
    y_values: List[np.ndarray] = []
    lower_values: List[np.ndarray] = []
    upper_values: List[np.ndarray] = []
    mask_values: List[np.ndarray] = []
    risk_values: List[np.ndarray] = []
    label_values: List[np.ndarray] = []

    model.eval()
    with torch.no_grad():
        for idx, batch in enumerate(loader):
            if config.max_eval_batches and idx >= config.max_eval_batches:
                break
            batch = batch.to(device)
            hidden = model.distribution(batch)
            samples = None
            if hasattr(model, "predict_quantiles"):
                quantiles = model.quantile_head(hidden)
                lower = quantiles[:, 0, :]
                upper = quantiles[:, -1, :]
            else:
                samples = model.flow_head.sample(hidden, batch.mq_flat, nsamples=config.nsamples)
                lower = torch.quantile(samples, 0.025, dim=1)
                upper = torch.quantile(samples, 0.975, dim=1)

            if hasattr(model, "predict_risk"):
                risk = model.predict_risk(batch, nsamples=config.nsamples)
            else:
                if samples is None:
                    samples = model.flow_head.sample(hidden, batch.mq_flat, nsamples=config.nsamples)
                risk = risk_score_from_samples(
                    samples.reshape(samples.shape[0], config.nsamples, config.pred_len, num_sensors)
                )

            y_values.append(batch.y_flat.detach().cpu().numpy())
            lower_values.append(lower.detach().cpu().numpy())
            upper_values.append(upper.detach().cpu().numpy())
            mask_values.append(batch.mq_flat.detach().cpu().numpy())
            risk_values.append(risk.detach().cpu().numpy())
            label_values.append(_risk_labels(config.dataset, batch, config.risk_threshold).detach().cpu().numpy())

    y = np.concatenate(y_values) if y_values else np.array([])
    lower = np.concatenate(lower_values) if lower_values else np.array([])
    upper = np.concatenate(upper_values) if upper_values else np.array([])
    mask = np.concatenate(mask_values) if mask_values else np.array([])
    risks = np.concatenate(risk_values) if risk_values else np.array([])
    labels = np.concatenate(label_values) if label_values else np.array([])

    risk_calibration = _fit_risk_calibration(labels, risks)
    conformal_qhat = _fit_conformal_qhat(y, lower, upper, mask, alpha=0.05)
    risk_calibration.update(
        {
            "conformal_qhat": conformal_qhat,
            "conformal_qhat_source": "validation",
            "conformal_alpha": 0.05,
            "calibration_split": "validation",
            "calibration_uses_test_labels": False,
            "calibration_num_examples": int(len(labels)),
        }
    )
    return risk_calibration


def _load_checkpoint(path: str, device: torch.device) -> Dict[str, object]:
    try:
        return torch.load(path, map_location=device, weights_only=False)
    except TypeError:
        return torch.load(path, map_location=device)


def _checkpoint_payload(model, config: ExperimentConfig, history, best_record=None) -> Dict[str, object]:
    return {
        "model_state": model.state_dict(),
        "config": model.config.to_dict(),
        "experiment": asdict(config),
        "history": history,
        "best_record": best_record,
    }


def _apply_checkpoint_config(config: ExperimentConfig, checkpoint: Dict[str, object]) -> ExperimentConfig:
    saved_experiment = checkpoint.get("experiment", {})
    saved_model_config = checkpoint.get("config", {})
    merged = asdict(config)
    architecture_keys = [
        "hidden_dim",
        "te_dim",
        "kernel_count",
        "n_layers",
        "n_heads",
        "flow_layers",
        "preconv_dim",
        "lambda_point",
        "patch_lens",
        "graph_layers",
        "copula_rank",
        "lambda_quantile",
        "lambda_risk",
    ]
    for key in architecture_keys:
        if key in saved_experiment:
            merged[key] = saved_experiment[key]
        elif key in saved_model_config:
            merged[key] = saved_model_config[key]
    merged["attention_diag_floor"] = config.attention_diag_floor
    merged["sample_clip"] = config.sample_clip
    merged["inverse_clip"] = config.inverse_clip
    merged["checkpoint"] = config.checkpoint
    return ExperimentConfig(**merged)


def _evaluate(
    model,
    loader,
    device: torch.device,
    config: ExperimentConfig,
    num_sensors: int,
    prediction_writer: PredictionNpyWriter = None,
    collect_outputs: bool = True,
    calibration: Optional[Dict[str, object]] = None,
):
    accumulator = GlobalMetricAccumulator()
    optional_counts = {"quantile": 0}
    diagnostics = {
        "nonfinite_sample_rows": 0,
        "nonfinite_mean_rows": 0,
        "nonfinite_risk_rows": 0,
        "finite_metric_positions": 0,
    }
    count = 0
    means: List[np.ndarray] = []
    samples_out: List[np.ndarray] = []
    risks: List[np.ndarray] = []
    labels: List[np.ndarray] = []
    window_errors: List[np.ndarray] = []
    start = time.perf_counter()
    conformal_qhat = float(calibration.get("conformal_qhat", 0.0)) if calibration else 0.0
    risk_threshold = float(calibration.get("risk_threshold", 0.5)) if calibration else 0.5
    model.eval()
    with torch.no_grad():
        for idx, batch in enumerate(loader):
            if config.max_eval_batches and idx >= config.max_eval_batches:
                break
            batch = batch.to(device)
            hidden = model.distribution(batch)
            nll_rows = model.flow_head.nll(batch.y_flat, hidden, batch.mq_flat)
            samples = model.flow_head.sample(hidden, batch.mq_flat, nsamples=config.nsamples)
            mean = samples.mean(dim=1)
            diagnostics["nonfinite_sample_rows"] += _nonfinite_rows(samples)
            diagnostics["nonfinite_mean_rows"] += _nonfinite_rows(mean)
            diagnostics["finite_metric_positions"] += _finite_metric_positions(
                batch.y_flat, mean, batch.mq_flat
            )
            mask_count = float(batch.mq_flat.sum())
            row_counts = batch.mq_flat.sum(dim=-1)
            accumulator.update_point(batch.y_flat, mean, batch.mq_flat)
            accumulator.update_nll(
                float((nll_rows * row_counts).sum().cpu()), float(row_counts.sum().cpu())
            )
            window_errors.append(_window_rmse(batch.y_flat, mean, batch.mq_flat))
            sample_picp, sample_mpiw = interval_metrics(batch.y_flat, samples, batch.mq_flat)
            accumulator.update_interval_means("sample", sample_picp, sample_mpiw, mask_count)
            quantile_picp, quantile_mpiw = None, None
            if hasattr(model, "predict_quantiles"):
                quantiles = model.quantile_head(hidden)
                quantile_picp, quantile_mpiw = _quantile_interval_metrics(
                    batch.y_flat, quantiles, batch.mq_flat
                )
                _, _, picp, mpiw = _quantile_interval_tensors(
                    batch.y_flat,
                    quantiles,
                    batch.mq_flat,
                    conformal_qhat=conformal_qhat,
                )
                optional_counts["quantile"] += 1
            else:
                _, _, picp, mpiw = _sample_interval_tensors(
                    batch.y_flat,
                    samples,
                    batch.mq_flat,
                    conformal_qhat=conformal_qhat,
                )
            accumulator.update_interval_means("main", picp, mpiw, mask_count)
            if quantile_picp is not None:
                accumulator.update_interval_means(
                    "quantile", quantile_picp, quantile_mpiw, mask_count
                )
            crps = float(model.flow_head.crps(batch.y_flat, samples, batch.mq_flat).cpu())
            accumulator.update_crps(crps * mask_count, mask_count)
            risk_source = "samples"
            if hasattr(model, "predict_risk"):
                risk = model.predict_risk(batch, nsamples=config.nsamples)
                risk_source = "risk_head"
            else:
                risk = risk_score_from_samples(samples.reshape(samples.shape[0], config.nsamples, config.pred_len, num_sensors))
            risk = _apply_risk_calibration(risk, calibration)
            diagnostics["nonfinite_risk_rows"] += _nonfinite_rows(risk)
            label = _risk_labels(config.dataset, batch, config.risk_threshold)
            mean_np = mean.cpu().numpy()
            samples_np = samples.cpu().numpy()
            risk_np = risk.cpu().numpy()
            if prediction_writer is not None:
                prediction_writer.write(mean_np, samples_np, risk_np)
            elif collect_outputs:
                means.append(mean_np)
                samples_out.append(samples_np)
            risks.append(risk_np)
            labels.append(label.cpu().numpy())
            count += 1
    elapsed = time.perf_counter() - start
    averaged = accumulator.result()
    if not optional_counts["quantile"]:
        averaged["quantile_picp"] = None
        averaged["quantile_mpiw"] = None
    risk_scores = np.concatenate(risks) if risks else np.array([])
    risk_labels = np.concatenate(labels) if labels else np.array([])
    averaged.update(
        safe_binary_metrics(
            risk_labels,
            risk_scores,
            threshold=risk_threshold,
            allow_orientation_selection=False,
        )
    )
    averaged["ece"] = expected_calibration_error(risk_labels, risk_scores)
    averaged["lead_time"] = None
    averaged["infer_time_ms_per_batch"] = (elapsed / max(count, 1)) * 1000.0
    averaged.update(diagnostics)
    if window_errors:
        averaged.update(_top_error_diagnostics(np.concatenate(window_errors)))
    else:
        averaged.update(_top_error_diagnostics(np.array([])))
    if calibration:
        averaged.update(calibration)
    else:
        averaged.update(
            {
                "calibration_split": None,
                "calibration_uses_test_labels": False,
                "risk_calibration_source": "not_applied",
                "risk_threshold": risk_threshold,
                "risk_threshold_source": "default",
                "conformal_qhat": conformal_qhat,
                "conformal_qhat_source": "not_applied",
            }
        )
    averaged["sample_clip"] = model.flow_head.sample_clip
    averaged["attention_diag_floor"] = model.flow_head.attention_diag_floor
    averaged["risk_source"] = risk_source if count else None
    if prediction_writer is not None:
        prediction_writer.close()
    return averaged, means, samples_out, risks


def run_experiment(config: ExperimentConfig) -> Dict[str, object]:
    spec = get_model_spec(config.model)
    if spec.status != "enabled":
        raise NotImplementedError(f"Model {config.model} is registered as {spec.status}")
    torch.manual_seed(config.seed)
    np.random.seed(config.seed)
    # Resolve roots through the KST_* contract: explicit values win, then
    # environment, then repository-relative dataset/ and results/ defaults.
    # Explicit absolute paths (tests, checkpoint re-runs) pass through.
    paths = resolve_runtime_paths(config.data_root, config.output_dir, os.environ)
    config.data_root = str(paths.data_root)
    config.output_dir = str(paths.output_root)
    output_dir = Path(config.output_dir)
    if not config.run_id:
        config.run_id = _timestamp_run_id()
    device = torch.device(config.device)
    checkpoint = None
    checkpoint_path = ""
    checkpoint_mode = bool(config.checkpoint)
    if checkpoint_mode:
        checkpoint_path = str(Path(config.checkpoint))
        checkpoint = _load_checkpoint(checkpoint_path, device)
        config = _apply_checkpoint_config(config, checkpoint)
    bundle = create_protocol_datasets(
        config.dataset,
        config.data_root,
        seed=config.seed,
        history_len=config.history_len,
        pred_len=config.pred_len,
        stride=config.stride,
        async_mode="none",
    )
    split_info = dict(bundle.split_info)
    split_info["run_id"] = config.run_id
    split_path = (
        _run_artifact_dir(output_dir, "splits", config)
        / f"{config.dataset}_split_seed{config.seed}.json"
    )
    _write_json(split_path, split_info)
    mask_path = (
        _run_dir(output_dir, config)
        / "masks"
        / config.dataset
        / f"{config.dataset}_missing_{config.missing_rate}_seed{config.seed}.npz"
    )
    split_masks = generate_or_load_split_masks(
        mask_path,
        {
            "train": (len(bundle.train), config.history_len, bundle.num_sensors),
            "valid": (len(bundle.valid), config.history_len, bundle.num_sensors),
            "test": (len(bundle.test), config.history_len, bundle.num_sensors),
        },
        missing_rate=config.missing_rate,
        seed=config.seed,
        mode=config.missing_mode,
    )
    train_set = MaskedWindowDataset(bundle.train, split_masks["train"])
    valid_set = MaskedWindowDataset(bundle.valid, split_masks["valid"])
    test_set = MaskedWindowDataset(bundle.test, split_masks["test"])
    collator = IndustrialCollator()
    pipeline = LitePipeline.resolve(config.device, config.num_workers)
    loader_kwargs = pipeline.dataloader_kwargs()
    train_loader = DataLoader(train_set, batch_size=config.batch_size, shuffle=True, collate_fn=collator, **loader_kwargs)
    valid_loader = DataLoader(valid_set, batch_size=config.batch_size, shuffle=False, collate_fn=collator, **loader_kwargs)
    # Smoke runs never construct the test loader: test_evaluation_count=0.
    test_loader = None
    if config.run_level == "formal":
        test_loader = DataLoader(test_set, batch_size=config.batch_size, shuffle=False, collate_fn=collator, **loader_kwargs)
    model = create_model(
        config.model,
        num_sensors=bundle.num_sensors,
        context_dim=bundle.context_dim,
        device=config.device,
        hidden_dim=config.hidden_dim,
        te_dim=config.te_dim,
        kernel_count=config.kernel_count,
        n_layers=config.n_layers,
        n_heads=config.n_heads,
        flow_layers=config.flow_layers,
        preconv_dim=config.preconv_dim,
        lambda_point=config.lambda_point,
        patch_lens=config.patch_lens,
        graph_layers=config.graph_layers,
        copula_rank=config.copula_rank,
        lambda_quantile=config.lambda_quantile,
        lambda_risk=config.lambda_risk,
        attention_diag_floor=config.attention_diag_floor,
        sample_clip=config.sample_clip,
        inverse_clip=config.inverse_clip,
    )
    if checkpoint is not None:
        model.load_state_dict(checkpoint["model_state"])
        history = checkpoint.get("history", [])
        best_record = checkpoint.get("best_record")
        best_checkpoint_path = checkpoint_path
        final_checkpoint_path = checkpoint_path
        checkpoint_selection = "provided_checkpoint"
        train_time = 0.0
    else:
        history = []
        train_start = time.perf_counter()
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        optimizer = AdamW(model.parameters(), lr=config.lr, weight_decay=config.weight_decay)
        history_path = (
            _run_artifact_dir(output_dir, "training_history", config)
            / f"history_seed{config.seed}.json"
        )
        checkpoint_dir = _run_artifact_dir(output_dir, "checkpoints", config)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        final_checkpoint_path = str(checkpoint_dir / f"checkpoint_seed{config.seed}.pt")
        best_checkpoint_path = str(checkpoint_dir / f"checkpoint_seed{config.seed}_best.pt")
        best_record = None
        best_valid_score = None
        for epoch in range(1, config.epochs + 1):
            epoch_start = time.perf_counter()
            train_record = _train_epoch(model, train_loader, optimizer, device, config.max_train_batches)
            valid_metrics, _, _, _ = _evaluate(
                model,
                valid_loader,
                device,
                config,
                bundle.num_sensors,
                collect_outputs=False,
            )
            record = {
                "epoch": epoch,
                "train_loss": train_record["train_loss"],
                "train_batches": train_record["train_batches"],
                "train_time_sec": train_record["train_time_sec"],
                "valid_nll": valid_metrics["nll"],
                "valid_mae": valid_metrics["mae"],
                "valid_rmse": valid_metrics["rmse"],
                "valid_crps": valid_metrics["crps"],
                "valid_picp": valid_metrics["picp"],
                "valid_mpiw": valid_metrics["mpiw"],
                "valid_batches": min(len(valid_loader), config.max_eval_batches)
                if config.max_eval_batches
                else len(valid_loader),
                "epoch_time_sec": time.perf_counter() - epoch_start,
            }
            history.append(record)
            _write_json(history_path, history)
            valid_score = record["valid_crps"]
            if best_valid_score is None or valid_score < best_valid_score:
                best_valid_score = valid_score
                best_record = record
                torch.save(
                    _checkpoint_payload(model, config, history, best_record),
                    best_checkpoint_path,
                )
            print(json.dumps({"event": "epoch", **record}, ensure_ascii=False), flush=True)
        train_time = time.perf_counter() - train_start
        torch.save(
            _checkpoint_payload(model, config, history, best_record),
            final_checkpoint_path,
        )
        if best_record is not None:
            best_checkpoint = _load_checkpoint(best_checkpoint_path, device)
            model.load_state_dict(best_checkpoint["model_state"])
            checkpoint_path = best_checkpoint_path
            checkpoint_selection = "best_valid"
        else:
            checkpoint_path = final_checkpoint_path
            checkpoint_selection = "final"
    history_path = (
        _run_artifact_dir(output_dir, "training_history", config)
        / f"history_seed{config.seed}.json"
    )
    _write_json(history_path, history)
    config_path = (
        _run_artifact_dir(output_dir, "configs", config)
        / f"config_seed{config.seed}.yaml"
    )
    _write_config_yaml(config_path, config)
    suffix = "_fixed" if checkpoint_mode else ""
    training_manifest = build_training_manifest(
        pipeline=pipeline,
        epoch_seconds=[float(record.get("epoch_time_sec", 0.0)) for record in history],
        train_seconds=float(train_time),
        peak_gpu_memory_mb=peak_gpu_memory_mb(config.device),
        peak_host_memory_mb=peak_host_memory_mb(),
        parameter_count=sum(param.numel() for param in model.parameters()),
        identity={
            "run_id": config.run_id,
            "dataset": config.dataset,
            "model": config.model,
            "seed": config.seed,
            "history_len": config.history_len,
            "pred_len": config.pred_len,
            "stride": config.stride,
            "missing_mode": config.missing_mode,
            "missing_rate": config.missing_rate,
            "device": config.device,
        },
        run_level=config.run_level,
        test_evaluation_count=0 if config.run_level == "smoke" else 1,
    )
    training_manifest_path = (
        _run_artifact_dir(output_dir, "manifests", config)
        / f"training_manifest_seed{config.seed}{suffix}.json"
    )
    write_training_manifest(training_manifest_path, training_manifest)
    if config.run_level == "smoke":
        # Pipeline smoke: train/validation only, no calibration fit, no test
        # evaluation, no metrics/prediction artifacts.
        return {
            "dataset": config.dataset,
            "model": config.model,
            "run_id": config.run_id,
            "seed": config.seed,
            "status": "smoke_passed",
            "run_level": "smoke",
            "test_evaluation_count": 0,
            "evidence_status": training_manifest["evidence_status"],
            "train_seconds": training_manifest["train_seconds"],
            "parameter_count": training_manifest["parameter_count"],
            "training_manifest_path": str(training_manifest_path),
            "history_path": str(history_path),
            "config_path": str(config_path),
            "checkpoint_path": checkpoint_path,
            "final_checkpoint_path": final_checkpoint_path,
            "best_checkpoint_path": best_checkpoint_path,
        }
    calibration = _collect_validation_calibration(
        model,
        valid_loader,
        device,
        config,
        bundle.num_sensors,
    )
    calibration_path = (
        _run_artifact_dir(output_dir, "calibration", config)
        / f"calibration_seed{config.seed}{'_fixed' if checkpoint_mode else ''}.json"
    )
    _write_json(calibration_path, calibration)
    status = "completed_from_checkpoint_fixed" if checkpoint_mode else "completed"
    metrics_name = f"metrics_seed{config.seed}{suffix}.json"
    pred_dir = _run_artifact_dir(output_dir, "predictions", config)
    query_count = config.pred_len * bundle.num_sensors
    prediction_writer = PredictionNpyWriter(
        pred_dir,
        seed=config.seed,
        total_examples=_limited_eval_examples(test_loader, config.max_eval_batches),
        nsamples=config.nsamples,
        query_count=query_count,
        suffix=suffix,
        finite_clip=config.sample_clip,
    )
    eval_start = time.perf_counter()
    eval_metrics, _, _, _ = _evaluate(
        model,
        test_loader,
        device,
        config,
        bundle.num_sensors,
        prediction_writer=prediction_writer,
        collect_outputs=False,
        calibration=calibration,
    )
    eval_time = time.perf_counter() - eval_start
    metrics_path = _run_artifact_dir(output_dir, "metrics", config) / metrics_name
    metrics = {
        "dataset": config.dataset,
        "model": config.model,
        "run_id": config.run_id,
        "seed": config.seed,
        "missing_rate": config.missing_rate,
        "history": config.history_len,
        "horizon": config.pred_len,
        **completed_metrics_template(),
        **eval_metrics,
        "train_time_sec": train_time,
        "eval_time_sec": eval_time,
        "num_params": sum(param.numel() for param in model.parameters()),
        "gpu_memory_mb": None,
        "test_evaluation_count": 1,
        "training_manifest_path": str(training_manifest_path),
        "metrics_path": str(metrics_path),
        "config_path": str(config_path),
        "calibration_path": str(calibration_path),
        "split_path": str(split_path),
        "mask_path": str(mask_path),
        "prediction_dir": str(pred_dir),
        "history_path": str(history_path),
        "checkpoint_path": checkpoint_path,
        "final_checkpoint_path": final_checkpoint_path,
        "best_checkpoint_path": best_checkpoint_path,
        "checkpoint_selection": checkpoint_selection,
        "best_epoch": best_record.get("epoch") if best_record else None,
        "best_valid_metric_name": "valid_crps" if best_record else None,
        "best_valid_metric_value": best_record.get("valid_crps") if best_record else None,
        "status": status,
        "error": None,
    }
    _write_json(metrics_path, metrics)
    return metrics


def parse_args() -> ExperimentConfig:
    parser = argparse.ArgumentParser(description="Run unified KAF-ProFITi experiment")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--model", default="kaf_profiti_joint")
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--missing-rate", type=float, default=0.3)
    parser.add_argument("--history-len", type=int, default=96)
    parser.add_argument("--pred-len", type=int, default=24)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--data-root", default=None, help="defaults to KST_DATA_ROOT / repo dataset/")
    parser.add_argument("--output-dir", default=None, help="defaults to KST_RESULT_ROOT / repo results/")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-train-batches", type=int, default=20)
    parser.add_argument("--max-eval-batches", type=int, default=20)
    parser.add_argument("--nsamples", type=int, default=20)
    parser.add_argument("--device", default="cpu")
    parser.add_argument(
        "--run-level", choices=("formal", "smoke"), default="formal",
        help="smoke trains/validates only and never touches the test split",
    )
    parser.add_argument(
        "--num-workers", type=int, default=4,
        help="lite_pipeline_v1 contract value; 0 disables worker processes",
    )
    parser.add_argument("--missing-mode", default="mixed")
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--risk-threshold", type=float, default=30.0)
    parser.add_argument("--hidden-dim", type=int, default=32)
    parser.add_argument("--te-dim", type=int, default=5)
    parser.add_argument("--kernel-count", type=int, default=4)
    parser.add_argument("--n-layers", type=int, default=2)
    parser.add_argument("--n-heads", type=int, default=2)
    parser.add_argument("--flow-layers", type=int, default=2)
    parser.add_argument("--preconv-dim", type=int, default=8)
    parser.add_argument("--lambda-point", type=float, default=0.1)
    parser.add_argument("--patch-lens", default="12,24,48")
    parser.add_argument("--graph-layers", type=int, default=1)
    parser.add_argument("--copula-rank", type=int, default=32)
    parser.add_argument("--lambda-quantile", type=float, default=0.2)
    parser.add_argument("--lambda-risk", type=float, default=0.05)
    parser.add_argument("--attention-diag-floor", type=float, default=0.05)
    parser.add_argument("--sample-clip", type=float, default=20.0)
    parser.add_argument("--inverse-clip", type=float, default=1_000_000.0)
    parser.add_argument("--checkpoint", default="")
    return ExperimentConfig(**vars(parser.parse_args()))


def main():
    metrics = run_experiment(parse_args())
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
