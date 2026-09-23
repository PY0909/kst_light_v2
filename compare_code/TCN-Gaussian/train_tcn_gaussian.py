#!/usr/bin/env python
import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
CODE_ROOT = ROOT / "code"
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

import numpy as np
import torch
from torch.optim import AdamW
from torch.utils.data import DataLoader

from kaf_profiti.experiments.accumulators import GlobalMetricAccumulator
from kaf_profiti.experiments.datasets import create_protocol_datasets
from kaf_profiti.experiments.masks import MaskedWindowDataset, generate_or_load_split_masks
from kaf_profiti.experiments.metrics import (
    completed_metrics_template,
    expected_calibration_error,
    safe_binary_metrics,
)
from kaf_profiti.industrial.batch import IndustrialCollator
from run_experiment import (
    PredictionNpyWriter,
    _apply_risk_calibration,
    _fit_risk_calibration,
    _risk_labels,
    _top_error_diagnostics,
)
from tcn_gaussian.metrics import gaussian_crps, gaussian_interval_metrics, gaussian_risk_score
from tcn_gaussian.model import TCNGaussian


MODEL_NAME = "tcn_gaussian"


@dataclass
class TCNGaussianConfig:
    dataset: str
    seed: int = 2026
    missing_rate: float = 0.3
    history_len: int = 96
    pred_len: int = 24
    stride: int = 1
    data_root: str = "/home/work/new_work/dataset"
    output_dir: str = "/home/work/new_work/result"
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
    hidden_dim: int = 64
    levels: int = 4
    kernel_size: int = 3
    dropout: float = 0.1
    lambda_point: float = 0.1
    min_scale: float = 0.05
    sample_clip: float = 30.0
    checkpoint: str = ""


def _timestamp_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _run_dir(config: TCNGaussianConfig) -> Path:
    return Path(config.output_dir) / config.run_id


def _artifact_dir(config: TCNGaussianConfig, artifact: str) -> Path:
    return _run_dir(config) / artifact / config.dataset / MODEL_NAME


def _write_json(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def _write_config_yaml(path: Path, config: TCNGaussianConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(f"{k}: {v}" for k, v in asdict(config).items()) + "\n")


def _load_checkpoint(path: str, device: torch.device) -> Dict[str, object]:
    try:
        return torch.load(path, map_location=device, weights_only=False)
    except TypeError:
        return torch.load(path, map_location=device)


def _checkpoint_payload(model, config: TCNGaussianConfig, history, best_record=None):
    return {
        "model_state": model.state_dict(),
        "config": asdict(config),
        "history": history,
        "best_record": best_record,
    }


def _limited_eval_examples(loader, max_batches: int) -> int:
    if not max_batches:
        return len(loader.dataset)
    return min(len(loader.dataset), int(max_batches) * int(loader.batch_size))


def _window_rmse(y: torch.Tensor, mean: torch.Tensor, mask: torch.Tensor) -> np.ndarray:
    valid = (mask > 0) & torch.isfinite(y) & torch.isfinite(mean)
    diff2 = torch.where(valid, (mean - y).pow(2), torch.zeros_like(mean))
    denom = valid.float().sum(dim=(1, 2)).clamp_min(1.0)
    rmse = torch.sqrt(diff2.sum(dim=(1, 2)) / denom)
    return rmse.detach().cpu().numpy()


def _train_epoch(model, loader, optimizer, device: torch.device, config: TCNGaussianConfig):
    model.train()
    total = 0.0
    count = 0
    start = time.perf_counter()
    for idx, batch in enumerate(loader):
        if config.max_train_batches and idx >= config.max_train_batches:
            break
        batch = batch.to(device)
        optimizer.zero_grad(set_to_none=True)
        mean, scale = model(batch.X_obs, batch.M_obs, batch.context)
        nll = model.nll(batch.Y_q, mean, scale, batch.M_q)
        point = model.mse(batch.Y_q, mean, batch.M_q)
        loss = nll + config.lambda_point * point
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


def _evaluate(
    model,
    loader,
    device: torch.device,
    config: TCNGaussianConfig,
    prediction_writer: Optional[PredictionNpyWriter] = None,
    calibration: Optional[Dict[str, object]] = None,
):
    accumulator = GlobalMetricAccumulator()
    diagnostics = {
        "nonfinite_sample_rows": 0,
        "nonfinite_mean_rows": 0,
        "nonfinite_risk_rows": 0,
        "finite_metric_positions": 0,
    }
    risks = []
    labels = []
    window_errors = []
    count = 0
    start = time.perf_counter()
    risk_threshold = float(calibration.get("risk_threshold", 0.5)) if calibration else 0.5
    model.eval()
    with torch.no_grad():
        for idx, batch in enumerate(loader):
            if config.max_eval_batches and idx >= config.max_eval_batches:
                break
            batch = batch.to(device)
            mean, scale = model(batch.X_obs, batch.M_obs, batch.context)
            nll = model.nll(batch.Y_q, mean, scale, batch.M_q)
            crps = gaussian_crps(batch.Y_q, mean, scale, batch.M_q)
            picp, mpiw = gaussian_interval_metrics(batch.Y_q, mean, scale, batch.M_q)
            mask_count = float(batch.M_q.sum())
            # model.nll and gaussian_crps divide by mask.sum(), so multiplying
            # the batch means back by mask_count recovers exact sums; the
            # interval metrics divide by the finite-and-masked valid count.
            interval_count = float(
                (
                    (batch.M_q > 0)
                    & torch.isfinite(batch.Y_q)
                    & torch.isfinite(mean)
                    & torch.isfinite(scale)
                ).sum()
            )
            accumulator.update_point(batch.Y_q, mean, batch.M_q)
            accumulator.update_nll(float(nll.detach().cpu()) * mask_count, mask_count)
            accumulator.update_crps(crps * mask_count, mask_count)
            accumulator.update_interval_means("main", picp, mpiw, interval_count)
            risk = gaussian_risk_score(mean, scale)
            risk = _apply_risk_calibration(risk, calibration)
            label = _risk_labels(config.dataset, batch, config.risk_threshold)

            samples = None
            if prediction_writer is not None:
                samples = model.sample(batch.X_obs, batch.M_obs, batch.context, config.nsamples)
                samples = samples.clamp(-config.sample_clip, config.sample_clip)
                prediction_writer.write(
                    mean.reshape(mean.shape[0], -1).detach().cpu().numpy(),
                    samples.reshape(samples.shape[0], samples.shape[1], -1).detach().cpu().numpy(),
                    risk.detach().cpu().numpy(),
                )

            diagnostics["nonfinite_mean_rows"] += int(
                (~torch.isfinite(mean).reshape(mean.shape[0], -1).all(dim=1)).sum().cpu()
            )
            if samples is not None:
                diagnostics["nonfinite_sample_rows"] += int(
                    (~torch.isfinite(samples).reshape(samples.shape[0], -1).all(dim=1)).sum().cpu()
                )
            diagnostics["nonfinite_risk_rows"] += int((~torch.isfinite(risk)).sum().cpu())
            diagnostics["finite_metric_positions"] += int(
                ((batch.M_q > 0) & torch.isfinite(batch.Y_q) & torch.isfinite(mean)).sum().cpu()
            )
            window_errors.append(_window_rmse(batch.Y_q, mean, batch.M_q))
            risks.append(risk.detach().cpu().numpy())
            labels.append(label.detach().cpu().numpy())
            count += 1
    if prediction_writer is not None:
        prediction_writer.close()
    averaged = accumulator.result()
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
    averaged["infer_time_ms_per_batch"] = ((time.perf_counter() - start) / max(count, 1)) * 1000.0
    averaged.update(diagnostics)
    averaged.update(_top_error_diagnostics(np.concatenate(window_errors) if window_errors else np.array([])))
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
            }
        )
    averaged["risk_source"] = "gaussian_mean_scale"
    return averaged


def _collect_validation_calibration(model, loader, device: torch.device, config: TCNGaussianConfig):
    risks = []
    labels = []
    model.eval()
    with torch.no_grad():
        for idx, batch in enumerate(loader):
            if config.max_eval_batches and idx >= config.max_eval_batches:
                break
            batch = batch.to(device)
            mean, scale = model(batch.X_obs, batch.M_obs, batch.context)
            risks.append(gaussian_risk_score(mean, scale).detach().cpu().numpy())
            labels.append(_risk_labels(config.dataset, batch, config.risk_threshold).detach().cpu().numpy())
    risk_scores = np.concatenate(risks) if risks else np.array([])
    risk_labels = np.concatenate(labels) if labels else np.array([])
    calibration = _fit_risk_calibration(risk_labels, risk_scores)
    calibration.update(
        {
            "calibration_split": "validation",
            "calibration_uses_test_labels": False,
            "calibration_num_examples": int(len(risk_labels)),
            "conformal_qhat": 0.0,
            "conformal_qhat_source": "not_used_by_gaussian_baseline",
        }
    )
    return calibration


def run_experiment(config: TCNGaussianConfig):
    torch.manual_seed(config.seed)
    np.random.seed(config.seed)
    if not config.run_id:
        config.run_id = f"{config.dataset}_{MODEL_NAME}_{_timestamp_run_id()}"
    device = torch.device(config.device)
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
    split_path = _artifact_dir(config, "splits") / f"{config.dataset}_split_seed{config.seed}.json"
    _write_json(split_path, split_info)

    mask_path = (
        _run_dir(config)
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
    collator = IndustrialCollator()
    train_loader = DataLoader(
        MaskedWindowDataset(bundle.train, split_masks["train"]),
        batch_size=config.batch_size,
        shuffle=True,
        collate_fn=collator,
    )
    valid_loader = DataLoader(
        MaskedWindowDataset(bundle.valid, split_masks["valid"]),
        batch_size=config.batch_size,
        shuffle=False,
        collate_fn=collator,
    )
    test_loader = DataLoader(
        MaskedWindowDataset(bundle.test, split_masks["test"]),
        batch_size=config.batch_size,
        shuffle=False,
        collate_fn=collator,
    )
    model = TCNGaussian(
        num_sensors=bundle.num_sensors,
        context_dim=bundle.context_dim,
        pred_len=config.pred_len,
        hidden_dim=config.hidden_dim,
        levels=config.levels,
        kernel_size=config.kernel_size,
        dropout=config.dropout,
        min_scale=config.min_scale,
    ).to(device)

    checkpoint_mode = bool(config.checkpoint)
    if checkpoint_mode:
        checkpoint = _load_checkpoint(config.checkpoint, device)
        model.load_state_dict(checkpoint["model_state"])
        history = checkpoint.get("history", [])
        best_record = checkpoint.get("best_record")
        final_checkpoint_path = config.checkpoint
        best_checkpoint_path = config.checkpoint
        checkpoint_path = config.checkpoint
        checkpoint_selection = "provided_checkpoint"
        train_time = 0.0
    else:
        history = []
        train_start = time.perf_counter()
        optimizer = AdamW(model.parameters(), lr=config.lr, weight_decay=config.weight_decay)
        checkpoint_dir = _artifact_dir(config, "checkpoints")
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        final_checkpoint_path = str(checkpoint_dir / f"checkpoint_seed{config.seed}.pt")
        best_checkpoint_path = str(checkpoint_dir / f"checkpoint_seed{config.seed}_best.pt")
        best_record = None
        best_valid_score = None
        history_path = _artifact_dir(config, "training_history") / f"history_seed{config.seed}.json"
        for epoch in range(1, config.epochs + 1):
            epoch_start = time.perf_counter()
            train_record = _train_epoch(model, train_loader, optimizer, device, config)
            valid_metrics = _evaluate(model, valid_loader, device, config)
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
            if best_valid_score is None or record["valid_crps"] < best_valid_score:
                best_valid_score = record["valid_crps"]
                best_record = record
                torch.save(_checkpoint_payload(model, config, history, best_record), best_checkpoint_path)
            print(json.dumps({"event": "epoch", **record}, ensure_ascii=False), flush=True)
        train_time = time.perf_counter() - train_start
        torch.save(_checkpoint_payload(model, config, history, best_record), final_checkpoint_path)
        if best_record is not None:
            best_checkpoint = _load_checkpoint(best_checkpoint_path, device)
            model.load_state_dict(best_checkpoint["model_state"])
            checkpoint_path = best_checkpoint_path
            checkpoint_selection = "best_valid"
        else:
            checkpoint_path = final_checkpoint_path
            checkpoint_selection = "final"

    history_path = _artifact_dir(config, "training_history") / f"history_seed{config.seed}.json"
    _write_json(history_path, history)
    config_path = _artifact_dir(config, "configs") / f"config_seed{config.seed}.yaml"
    _write_config_yaml(config_path, config)
    calibration = _collect_validation_calibration(model, valid_loader, device, config)
    calibration_path = _artifact_dir(config, "calibration") / f"calibration_seed{config.seed}.json"
    _write_json(calibration_path, calibration)

    pred_dir = _artifact_dir(config, "predictions")
    writer = PredictionNpyWriter(
        pred_dir,
        seed=config.seed,
        total_examples=_limited_eval_examples(test_loader, config.max_eval_batches),
        nsamples=config.nsamples,
        query_count=config.pred_len * bundle.num_sensors,
        finite_clip=config.sample_clip,
    )
    eval_start = time.perf_counter()
    eval_metrics = _evaluate(
        model,
        test_loader,
        device,
        config,
        prediction_writer=writer,
        calibration=calibration,
    )
    eval_time = time.perf_counter() - eval_start
    metrics_path = _artifact_dir(config, "metrics") / f"metrics_seed{config.seed}.json"
    metrics = {
        "dataset": config.dataset,
        "model": MODEL_NAME,
        "run_id": config.run_id,
        "seed": config.seed,
        "missing_rate": config.missing_rate,
        "history": config.history_len,
        "horizon": config.pred_len,
        **completed_metrics_template(),
        **eval_metrics,
        "sample_picp": eval_metrics.get("picp"),
        "sample_mpiw": eval_metrics.get("mpiw"),
        "quantile_picp": None,
        "quantile_mpiw": None,
        "train_time_sec": train_time,
        "eval_time_sec": eval_time,
        "num_params": sum(p.numel() for p in model.parameters()),
        "gpu_memory_mb": None,
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
        "status": "completed_from_checkpoint" if checkpoint_mode else "completed",
        "error": None,
    }
    _write_json(metrics_path, metrics)
    return metrics


def parse_args() -> TCNGaussianConfig:
    parser = argparse.ArgumentParser(description="Train/evaluate TCN-Gaussian baseline")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--missing-rate", type=float, default=0.3)
    parser.add_argument("--history-len", type=int, default=96)
    parser.add_argument("--pred-len", type=int, default=24)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--data-root", default="/home/work/new_work/dataset")
    parser.add_argument("--output-dir", default="/home/work/new_work/result")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-train-batches", type=int, default=20)
    parser.add_argument("--max-eval-batches", type=int, default=20)
    parser.add_argument("--nsamples", type=int, default=20)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--missing-mode", default="mixed")
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--risk-threshold", type=float, default=30.0)
    parser.add_argument("--hidden-dim", type=int, default=64)
    parser.add_argument("--levels", type=int, default=4)
    parser.add_argument("--kernel-size", type=int, default=3)
    parser.add_argument("--dropout", type=float, default=0.1)
    parser.add_argument("--lambda-point", type=float, default=0.1)
    parser.add_argument("--min-scale", type=float, default=0.05)
    parser.add_argument("--sample-clip", type=float, default=30.0)
    parser.add_argument("--checkpoint", default="")
    return TCNGaussianConfig(**vars(parser.parse_args()))


def main():
    metrics = run_experiment(parse_args())
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
