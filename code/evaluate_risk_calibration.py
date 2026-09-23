#!/usr/bin/env python
import argparse
import json
import math
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
from torch.utils.data import DataLoader

try:
    from sklearn.linear_model import LogisticRegression
except Exception:  # pragma: no cover
    LogisticRegression = None

from kaf_profiti.experiments.datasets import create_protocol_datasets
from kaf_profiti.experiments.masks import MaskedWindowDataset, generate_or_load_split_masks
from kaf_profiti.experiments.metrics import (
    expected_calibration_error,
    risk_score_from_samples,
    safe_binary_metrics,
)
from kaf_profiti.experiments.registry import create_model
from kaf_profiti.industrial.batch import IndustrialCollator
from run_experiment import (
    ExperimentConfig,
    _apply_checkpoint_config,
    _load_checkpoint,
    _risk_labels,
)


def _finite_labels_scores(labels, scores) -> Tuple[np.ndarray, np.ndarray]:
    labels = np.asarray(labels, dtype=float).reshape(-1)
    scores = np.asarray(scores, dtype=float).reshape(-1)
    valid = np.isfinite(labels) & np.isfinite(scores)
    return labels[valid].astype(int), scores[valid]


def _sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    values = np.clip(values, -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-values))


class PlattCalibrator:
    def __init__(self, coef: float = 1.0, intercept: float = 0.0, status: str = "identity"):
        self.coef = float(coef)
        self.intercept = float(intercept)
        self.status = str(status)

    def transform(self, scores) -> np.ndarray:
        scores = np.asarray(scores, dtype=float)
        calibrated = _sigmoid(self.coef * scores + self.intercept)
        return np.clip(np.nan_to_num(calibrated, nan=0.5, posinf=1.0, neginf=0.0), 0.0, 1.0)

    def to_dict(self) -> Dict[str, object]:
        return {"coef": self.coef, "intercept": self.intercept, "status": self.status}


def fit_platt_calibrator(labels, scores) -> PlattCalibrator:
    labels, scores = _finite_labels_scores(labels, scores)
    if labels.size == 0 or np.unique(labels).size < 2 or LogisticRegression is None:
        return PlattCalibrator(status="identity_fallback")
    try:
        model = LogisticRegression(solver="lbfgs", max_iter=1000)
        model.fit(scores.reshape(-1, 1), labels)
        return PlattCalibrator(
            coef=float(model.coef_[0, 0]),
            intercept=float(model.intercept_[0]),
            status="sklearn_logistic_regression",
        )
    except Exception:
        return PlattCalibrator(status="identity_fallback")


def _f1_at_threshold(labels: np.ndarray, scores: np.ndarray, threshold: float) -> float:
    labels, scores = _finite_labels_scores(labels, scores)
    if labels.size == 0:
        return 0.0
    pred = (scores >= float(threshold)).astype(int)
    tp = int(((pred == 1) & (labels == 1)).sum())
    fp = int(((pred == 1) & (labels == 0)).sum())
    fn = int(((pred == 0) & (labels == 1)).sum())
    denom = 2 * tp + fp + fn
    return float(2 * tp / denom) if denom else 0.0


def best_f1_threshold_from_validation(labels, scores) -> Tuple[float, float]:
    labels, scores = _finite_labels_scores(labels, scores)
    if labels.size == 0:
        return 0.5, 0.0
    thresholds = np.unique(scores)
    if thresholds.size == 0:
        return 0.5, 0.0
    best_threshold = float(thresholds[0])
    best_f1 = -1.0
    for threshold in thresholds:
        score = _f1_at_threshold(labels, scores, float(threshold))
        if score > best_f1:
            best_f1 = score
            best_threshold = float(threshold)
    return best_threshold, float(best_f1)


def normal_quantile_threshold(labels, scores, quantile: float) -> float:
    labels, scores = _finite_labels_scores(labels, scores)
    if scores.size == 0:
        return 0.5
    normal = scores[labels < 1]
    source = normal if normal.size else scores
    return float(np.quantile(source, float(quantile)))


def _confusion(labels, scores, threshold: float) -> Dict[str, object]:
    labels, scores = _finite_labels_scores(labels, scores)
    pred = (scores >= float(threshold)).astype(int)
    tp = int(((pred == 1) & (labels == 1)).sum())
    fp = int(((pred == 1) & (labels == 0)).sum())
    tn = int(((pred == 0) & (labels == 0)).sum())
    fn = int(((pred == 0) & (labels == 1)).sum())
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    specificity = tn / max(tn + fp, 1)
    predicted_positive_rate = float(pred.mean()) if pred.size else None
    positive_rate = float(labels.mean()) if labels.size else None
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": float(precision),
        "recall": float(recall),
        "specificity": float(specificity),
        "predicted_positive_rate": predicted_positive_rate,
        "positive_rate": positive_rate,
        "num_examples": int(labels.size),
        "num_positive": int(labels.sum()) if labels.size else 0,
        "num_negative": int((labels == 0).sum()) if labels.size else 0,
    }


def _strategy_record(
    strategy: str,
    valid_labels,
    valid_scores,
    test_labels,
    test_scores,
    threshold: float,
    calibration_method: str,
    threshold_rule: str,
) -> Dict[str, object]:
    threshold = float(threshold)
    test_metrics = safe_binary_metrics(
        test_labels,
        test_scores,
        threshold=threshold,
        allow_orientation_selection=False,
    )
    valid_metrics = safe_binary_metrics(
        valid_labels,
        valid_scores,
        threshold=threshold,
        allow_orientation_selection=False,
    )
    record = {
        "strategy": strategy,
        "calibration_method": calibration_method,
        "threshold": threshold,
        "threshold_rule": threshold_rule,
        "threshold_source": "validation",
        "uses_test_labels_for_threshold": False,
        "valid_f1_at_threshold": valid_metrics.get("f1"),
        "valid_ece": expected_calibration_error(valid_labels, valid_scores),
        "test_ece": expected_calibration_error(test_labels, test_scores),
    }
    record.update(test_metrics)
    record.update(_confusion(test_labels, test_scores, threshold))
    return record


def build_risk_calibration_strategies(
    valid_labels,
    valid_scores,
    test_labels,
    test_scores,
) -> List[Dict[str, object]]:
    valid_labels, valid_scores = _finite_labels_scores(valid_labels, valid_scores)
    test_labels, test_scores = _finite_labels_scores(test_labels, test_scores)

    raw_best_threshold, _ = best_f1_threshold_from_validation(valid_labels, valid_scores)
    platt = fit_platt_calibrator(valid_labels, valid_scores)
    valid_platt = platt.transform(valid_scores)
    test_platt = platt.transform(test_scores)
    platt_best_threshold, _ = best_f1_threshold_from_validation(valid_labels, valid_platt)

    strategies = [
        _strategy_record(
            "raw_validation_best_f1",
            valid_labels,
            valid_scores,
            test_labels,
            test_scores,
            raw_best_threshold,
            "raw",
            "best_f1",
        ),
        _strategy_record(
            "raw_validation_normal_q90",
            valid_labels,
            valid_scores,
            test_labels,
            test_scores,
            normal_quantile_threshold(valid_labels, valid_scores, 0.90),
            "raw",
            "normal_q90",
        ),
        _strategy_record(
            "raw_validation_normal_q95",
            valid_labels,
            valid_scores,
            test_labels,
            test_scores,
            normal_quantile_threshold(valid_labels, valid_scores, 0.95),
            "raw",
            "normal_q95",
        ),
        _strategy_record(
            "platt_validation_best_f1",
            valid_labels,
            valid_platt,
            test_labels,
            test_platt,
            platt_best_threshold,
            "platt",
            "best_f1",
        ),
        _strategy_record(
            "platt_validation_normal_q95",
            valid_labels,
            valid_platt,
            test_labels,
            test_platt,
            normal_quantile_threshold(valid_labels, valid_platt, 0.95),
            "platt",
            "normal_q95",
        ),
    ]
    for item in strategies:
        item["platt"] = platt.to_dict()
    return strategies


def _parse_config_yaml(path: Path) -> Dict[str, object]:
    payload: Dict[str, object] = {}
    if not path.exists():
        return payload
    for line in path.read_text().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            payload[key] = ""
        elif value.lower() in {"true", "false"}:
            payload[key] = value.lower() == "true"
        else:
            try:
                if any(part in value.lower() for part in [".", "e"]):
                    number = float(value)
                    payload[key] = int(number) if number.is_integer() else number
                else:
                    payload[key] = int(value)
            except ValueError:
                payload[key] = value
    return payload


def _find_single(path: Path, pattern: str) -> Optional[Path]:
    matches = sorted(path.glob(pattern))
    return matches[0] if matches else None


def _load_experiment_config(run_dir: Path, checkpoint_path: Path, device: str, data_root: str) -> ExperimentConfig:
    config_path = _find_single(run_dir, "configs/*/*/config_seed*.yaml")
    payload = _parse_config_yaml(config_path) if config_path else {}
    allowed = set(ExperimentConfig.__dataclass_fields__.keys())
    init = {key: value for key, value in payload.items() if key in allowed}
    config = ExperimentConfig(**init)
    config.device = device
    config.checkpoint = str(checkpoint_path)
    if data_root:
        config.data_root = data_root
    config.output_dir = str(run_dir.parent)
    config.run_id = run_dir.name
    checkpoint = _load_checkpoint(str(checkpoint_path), torch.device(device))
    config = _apply_checkpoint_config(config, checkpoint)
    config.device = device
    if data_root:
        config.data_root = data_root
    config.output_dir = str(run_dir.parent)
    config.run_id = run_dir.name
    config.checkpoint = str(checkpoint_path)
    return config


def _find_checkpoint(run_dir: Path, checkpoint_arg: str) -> Path:
    if checkpoint_arg:
        return Path(checkpoint_arg)
    best = _find_single(run_dir, "checkpoints/*/*/checkpoint_seed*_best.pt")
    if best:
        return best
    final = _find_single(run_dir, "checkpoints/*/*/checkpoint_seed*.pt")
    if final:
        return final
    raise FileNotFoundError(f"No checkpoint found under {run_dir}")


def _collect_risk_outputs(model, loader, device: torch.device, dataset: str, risk_threshold: float, nsamples: int, num_sensors: int):
    labels = []
    scores = []
    model.eval()
    with torch.no_grad():
        for batch in loader:
            batch = batch.to(device)
            if hasattr(model, "predict_risk"):
                risk = model.predict_risk(batch, nsamples=nsamples)
            else:
                hidden = model.distribution(batch)
                samples = model.flow_head.sample(hidden, batch.mq_flat, nsamples=nsamples)
                risk = risk_score_from_samples(
                    samples.reshape(samples.shape[0], nsamples, -1, num_sensors)
                )
            labels.append(_risk_labels(dataset, batch, risk_threshold).detach().cpu().numpy())
            scores.append(risk.detach().cpu().numpy())
    return np.concatenate(labels), np.concatenate(scores)


def run_e1_risk_calibration(args) -> Dict[str, object]:
    run_dir = Path(args.run_dir)
    checkpoint_path = _find_checkpoint(run_dir, args.checkpoint)
    device = torch.device(args.device)
    config = _load_experiment_config(run_dir, checkpoint_path, args.device, args.data_root)
    checkpoint = _load_checkpoint(str(checkpoint_path), device)

    bundle = create_protocol_datasets(
        config.dataset,
        config.data_root,
        seed=config.seed,
        history_len=config.history_len,
        pred_len=config.pred_len,
        stride=config.stride,
        async_mode="none",
    )
    mask_path = (
        run_dir
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
    valid_loader = DataLoader(
        MaskedWindowDataset(bundle.valid, split_masks["valid"]),
        batch_size=args.batch_size or config.batch_size,
        shuffle=False,
        collate_fn=collator,
    )
    test_loader = DataLoader(
        MaskedWindowDataset(bundle.test, split_masks["test"]),
        batch_size=args.batch_size or config.batch_size,
        shuffle=False,
        collate_fn=collator,
    )
    model = create_model(
        config.model,
        num_sensors=bundle.num_sensors,
        context_dim=bundle.context_dim,
        device=args.device,
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
    model.load_state_dict(checkpoint["model_state"])

    valid_labels, valid_scores = _collect_risk_outputs(
        model,
        valid_loader,
        device,
        config.dataset,
        config.risk_threshold,
        config.nsamples,
        bundle.num_sensors,
    )
    test_labels, test_scores = _collect_risk_outputs(
        model,
        test_loader,
        device,
        config.dataset,
        config.risk_threshold,
        config.nsamples,
        bundle.num_sensors,
    )
    strategies = build_risk_calibration_strategies(
        valid_labels,
        valid_scores,
        test_labels,
        test_scores,
    )
    best_official = max(
        strategies,
        key=lambda item: -math.inf if item.get("f1") is None else float(item["f1"]),
    )
    output = {
        "run_dir": str(run_dir),
        "dataset": config.dataset,
        "model": config.model,
        "seed": config.seed,
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_selection": "provided_or_best_valid",
        "data_root": config.data_root,
        "calibration_split": "validation",
        "calibration_uses_test_labels": False,
        "task": "E1_threshold_and_calibration_reevaluation_no_retraining",
        "valid_examples": int(valid_labels.size),
        "valid_positive": int(valid_labels.sum()),
        "test_examples": int(test_labels.size),
        "test_positive": int(test_labels.sum()),
        "strategies": strategies,
        "best_official_strategy_by_test_f1": best_official["strategy"],
        "best_official_strategy_by_test_f1_value": best_official.get("f1"),
    }
    output_dir = run_dir / "calibration" / config.dataset / config.model
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"risk_calibration_e1_seed{config.seed}.json"
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    output["output_path"] = str(output_path)
    return output


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate validation-only risk thresholds/calibration without retraining")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--checkpoint", default="")
    parser.add_argument("--data-root", default="/root/autodl-tmp/dataset")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=0)
    return parser.parse_args()


def main():
    output = run_e1_risk_calibration(parse_args())
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
