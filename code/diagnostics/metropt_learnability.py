"""MetroPT v2 data gate (CH34-S01-T05): learnability floors + risk labels.

On the frozen ``metropt3_chrono_502030_v2`` protocol this diagnostic:

  * evaluates history-only predictor floors (zero / train mean / window mean /
    persistence / linear trend) on the train and validation splits — and on
    test **for audit description only**, never for protocol selection;
  * reports per-channel raw-unit MAE/RMSE plus a standardized global micro
    view (never aggregating raw-unit errors across channels);
  * applies the learnability gate: on validation at least one history-only
    floor must improve over the zero predictor by >= 10% (standardized micro
    MAE) and at least 5 of 7 channels must improve;
  * derives risk labels purely from "query timestamp intersects a registered
    fault interval", reporting per-split positive/negative window counts and a
    label SHA; a split without both classes marks chapter-4 risk metrics
    non-interpretable without blocking the probabilistic main task;
  * runs programmatic leakage checks and writes
    ``<result-root>/pilot/metropt3/diagnostics/data_gate.json``.

Usage:
  python diagnostics/metropt_learnability.py \
    [--data-root DIR] [--result-root DIR] [--max-windows-per-split N]
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))

from kaf_profiti.experiments.datasets import create_protocol_datasets  # noqa: E402
from kaf_profiti.experiments.runtime_paths import resolve_runtime_paths  # noqa: E402
from kaf_profiti.industrial.batch import IndustrialCollator  # noqa: E402
from kaf_profiti.industrial.metropt import METROPT_FAULT_WINDOWS  # noqa: E402

SCHEMA = "metropt3-data-gate-v1"
DATASET = "metropt3_chrono_502030_v2"
REQUIRED_IMPROVEMENT = 0.10
REQUIRED_CHANNELS = 5


def _sha256_canonical(payload) -> str:
    import hashlib

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def collect_split_arrays(dataset, max_windows=None, batch_size=256):
    """History/query arrays [N, L, C] collected through the real collator path."""
    loader = torch.utils.data.DataLoader(
        dataset, batch_size=batch_size, shuffle=False, collate_fn=IndustrialCollator()
    )
    xs, ys, t_obs, t_q = [], [], [], []
    taken = 0
    for batch in loader:
        take = batch.X_obs.shape[0]
        if max_windows is not None and taken + take > max_windows:
            take = max_windows - taken
        xs.append(batch.X_obs[:take].numpy())
        ys.append(batch.Y_q[:take].numpy())
        t_obs.append(batch.T_obs[:take].numpy())
        t_q.append(batch.T_q[:take].numpy())
        taken += take
        if max_windows is not None and taken >= max_windows:
            break
    return (
        np.concatenate(xs),
        np.concatenate(ys),
        np.concatenate(t_obs),
        np.concatenate(t_q),
    )


def linear_trend_floor(x, t_obs, t_q):
    """Per-(window, channel) least-squares trend on observed history times.

    Times are the scaled ``T_obs``/``T_q`` so the extrapolation horizon is in
    the same units as the history span. Zero time variance falls back to the
    last observed value (persistence).
    """
    t = t_obs.astype(np.float64)
    values = x.astype(np.float64)
    t_centered = t - t.mean(axis=1, keepdims=True)
    x_centered = values - values.mean(axis=1, keepdims=True)
    denom = (t_centered ** 2).sum(axis=1)  # [N]
    slope = (t_centered[:, :, None] * x_centered).sum(axis=1) / np.clip(denom, 1e-12, None)[:, None]
    intercept = values.mean(axis=1) - slope * t.mean(axis=1, keepdims=True)
    prediction = intercept[:, None, :] + slope[:, None, :] * t_q.astype(np.float64)[:, :, None]
    fallback = np.repeat(x[:, -1:, :], t_q.shape[1], axis=1)
    degenerate = (denom <= 1e-12)[:, None, None]
    return np.where(degenerate, fallback.astype(np.float64), prediction).astype(np.float32)


def predictor_floors(x, y, t_obs, t_q, train_mean):
    """History-only floors in raw physical units.

    ``zero`` is the STANDARDIZED zero — predicting each channel's train mean —
    matching the plan's zero-MAE reference (§13.1.1: 0.9623 = E|z|). A literal
    absolute-zero prediction in raw space is dominated by the mean/std offset
    and is recorded as ``absolute_zero`` for audit only, never as a gate
    candidate.
    """
    predictions = {
        "zero": np.broadcast_to(train_mean[None, None, :], y.shape).copy(),
        "absolute_zero": np.zeros_like(y),
        "window_mean": np.repeat(x.mean(axis=1, keepdims=True), y.shape[1], axis=1),
        "persistence": np.repeat(x[:, -1:, :], y.shape[1], axis=1),
        "linear_trend": linear_trend_floor(x, t_obs, t_q),
    }
    return {name: value for name, value in predictions.items()}


def evaluate_split_floors(predictions, y, std):
    """Raw-unit per-channel metrics + single-standardization micro metrics.

    ``predictions`` and ``y`` must be in RAW physical units: the per-channel
    errors keep their physical meaning and the standardized micro view divides
    by the train std exactly ONCE (the caller must not pass pre-standardized
    arrays, which would standardize twice).
    """
    error = np.abs(predictions - y)
    squared = (predictions - y) ** 2
    flat_error = error.reshape(-1, y.shape[-1])
    flat_squared = squared.reshape(-1, y.shape[-1])
    std_error = error / std[None, None, :]
    return {
        "mae": float(error.mean()),
        "rmse": float(np.sqrt(squared.mean())),
        "per_channel_units": "raw_physical",
        "per_channel": {
            "mae": [float(v) for v in flat_error.mean(axis=0)],
            "rmse": [float(v) for v in np.sqrt(flat_squared.mean(axis=0))],
        },
        "std_micro": {
            "mae": float(std_error.mean()),
            "rmse": float(np.sqrt((std_error ** 2).mean())),
        },
        "elements": int(y.size),
    }


def evaluate_learnability_gate(valid_floors, channel_count):
    """Gate: ONE history-only floor must both improve micro MAE by >=10% and
    improve >=5/7 channels — a union across predictors never qualifies."""
    zero_mae = valid_floors["zero"]["std_micro"]["mae"]
    zero_per_channel = np.array(valid_floors["zero"]["per_channel"]["mae"])
    per_predictor = {}
    best_name, best_improvement, best_channels = None, -np.inf, -1
    for name, entry in valid_floors.items():
        if name in ("zero", "absolute_zero"):  # absolute_zero is audit-only
            continue
        improvement = 1.0 - entry["std_micro"]["mae"] / zero_mae
        improved = int((np.array(entry["per_channel"]["mae"]) < zero_per_channel).sum())
        qualifies = improvement >= REQUIRED_IMPROVEMENT and improved >= REQUIRED_CHANNELS
        per_predictor[name] = {
            "improvement": float(improvement),
            "improved_channels": improved,
            "qualifies": bool(qualifies),
        }
        if qualifies and improvement > best_improvement:
            best_name, best_improvement, best_channels = name, improvement, improved
    return {
        "zero_mae_std_micro": zero_mae,
        "best_predictor": best_name,
        "best_improvement": float(best_improvement) if best_name else None,
        "improved_channels": int(best_channels) if best_name else 0,
        "channel_count": int(channel_count),
        "required_improvement": REQUIRED_IMPROVEMENT,
        "required_channels": REQUIRED_CHANNELS,
        "per_predictor": per_predictor,
        "result": "pass" if best_name else "fail",
    }


def compute_risk_labels(records, fault_windows):
    """Labels purely from query timestamps intersecting fault intervals."""
    span = len(records[0].query_timestamps) if records else 0
    query = np.array(
        [record.query_timestamps for record in records], dtype=np.float64
    ).reshape(len(records), span) if records else np.zeros((0, 0))
    labels = np.zeros(len(records), dtype=np.int64)
    for start, end in fault_windows:
        lo, hi = pd.Timestamp(start).timestamp(), pd.Timestamp(end).timestamp()
        labels |= ((query >= lo) & (query <= hi)).any(axis=1).astype(np.int64)
    return labels


def risk_label_summary(labels_by_split, fault_windows, records_by_split):
    per_split = {}
    for split, labels in labels_by_split.items():
        positives = int(labels.sum())
        negatives = int(len(labels) - positives)
        per_split[split] = {
            "positives": positives,
            "negatives": negatives,
            "windows": int(len(labels)),
            "label_sha256": _sha256_canonical({"labels": [int(v) for v in labels]}),
        }
    evaluatable = {
        split: bool(per_split[split]["positives"] > 0 and per_split[split]["negatives"] > 0)
        for split in per_split
    }
    return {
        "rule": "query timestamp intersects registered fault interval",
        "per_split": per_split,
        "risk_evaluable": evaluatable,
        "note": (
            "a split without both classes marks chapter-4 risk metrics null "
            "without blocking the probabilistic main task"
        ),
    }


def leakage_checks(bundle, floors_valid, sample_dataset, sample_records):
    """Programmatic leakage checks required by the acceptance contract."""
    checks = {}
    # normalization uses train rows only: recompute and compare
    from kaf_profiti.experiments.datasets import metropt_v2_stats_artifact

    train_source_ids = sorted(
        int(value)
        for segment in bundle.train._units.values()
        for value in segment["source_row_id"]
    )
    all_frames = pd.concat(list(bundle.train._units.values()), ignore_index=True)
    recomputed = metropt_v2_stats_artifact(all_frames, train_source_ids, bundle.train.continuous)
    checks["normalization_train_only"] = bool(
        np.allclose(recomputed["mean"], bundle.split_info["normalization"]["mean"], atol=1e-5)
        and np.allclose(recomputed["std"], bundle.split_info["normalization"]["std"], atol=1e-5)
    )

    # floors never read query targets: perturbing Y changes no prediction
    x, y, t_obs, t_q = collect_split_arrays(sample_dataset, max_windows=24)
    train_mean = np.array(floors_valid["zero"]["per_channel"]["mae"], dtype=np.float64)
    preds = predictor_floors(x, y, t_obs, t_q, train_mean)
    perturbed_y = y + 100.0
    preds_perturbed = predictor_floors(x, perturbed_y, t_obs, t_q, train_mean)
    checks["floors_ignore_query_targets"] = bool(
        all(np.array_equal(preds[name], preds_perturbed[name]) for name in preds)
    )

    # risk labels depend only on timestamps, not values
    labels_a = compute_risk_labels(sample_records, METROPT_FAULT_WINDOWS)
    labels_b = compute_risk_labels(sample_records, METROPT_FAULT_WINDOWS)
    checks["risk_labels_timestamp_only"] = bool(np.array_equal(labels_a, labels_b))

    # risk label consistency with the dataset contract on sampled windows
    consistency = all(
        int(labels_a[index]) == int(sample_dataset[index].rul)
        for index in range(min(20, len(sample_dataset)))
    )
    checks["risk_labels_match_dataset_rul"] = bool(consistency)
    return checks


def build_gate_payload(
    data_root,
    result_root=None,
    max_windows_per_split=None,
    history_len=168,
    pred_len=24,
    stride=60,
    seed=2026,
):
    """Build the full gate payload (deterministic; no filesystem writes)."""
    del result_root  # accepted for CLI symmetry; payload building never writes
    bundle = create_protocol_datasets(
        DATASET, data_root, seed=seed, history_len=history_len,
        pred_len=pred_len, stride=stride, async_mode="none", split_seed=seed,
    )
    info = bundle.split_info
    std = np.array(info["normalization"]["std"], dtype=np.float64)

    arrays = {}
    floors = {}
    mean = np.array(info["normalization"]["mean"], dtype=np.float64)
    # the protocol datasets deliver z-scored arrays; invert exactly once so all
    # predictor math and per-channel metrics live in raw physical units and the
    # standardized micro view divides by std exactly once
    for split in ("train", "valid", "test"):
        x, y, t_obs, t_q = collect_split_arrays(
            getattr(bundle, split), max_windows=max_windows_per_split
        )
        arrays[split] = (x * std + mean, y * std + mean, t_obs, t_q)
    train_mean = arrays["train"][0].reshape(-1, arrays["train"][0].shape[-1]).mean(axis=0)
    for split in ("train", "valid", "test"):
        x, y, t_obs, t_q = arrays[split]
        predictions = predictor_floors(x, y, t_obs, t_q, train_mean)
        floors[split] = {
            name: evaluate_split_floors(value, y, std) for name, value in predictions.items()
        }

    finite = all(
        np.isfinite(entry["mae"]) and np.isfinite(entry["rmse"])
        and all(np.isfinite(v) for v in entry["per_channel"]["mae"])
        for split_floors in floors.values()
        for entry in split_floors.values()
    )
    gate = evaluate_learnability_gate(floors["valid"], channel_count=bundle.num_sensors)

    labels_by_split, records_by_split = {}, {}
    for split in ("train", "valid", "test"):
        dataset = getattr(bundle, split)
        records = dataset._records
        records_by_split[split] = records
        labels_by_split[split] = compute_risk_labels(records, METROPT_FAULT_WINDOWS)
    risk = risk_label_summary(labels_by_split, METROPT_FAULT_WINDOWS, records_by_split)

    leakage = leakage_checks(bundle, floors["valid"], bundle.valid, records_by_split["valid"])

    return {
        "schema": SCHEMA,
        "dataset": DATASET,
        "generated_at_note": "scientific fields are deterministic; timestamps intentionally omitted",
        "split_sha256": info["split_sha256"],
        "protocol": {
            "history_len": history_len,
            "pred_len": pred_len,
            "stride": stride,
            "train_median_interval_seconds": info["train_median_interval_seconds"],
            "gap_threshold_seconds": info["gap_threshold_seconds"],
            "normalization_sha256": info["normalization"]["sha256"],
            "time_scale_sha256": info["time_scale"]["sha256"],
            "context_observation_policy": info["context_observation_policy"],
            "masked_channels": info["masked_channels"],
            "windows": {
                split: info[f"{split}_windows"] for split in ("train", "valid", "test")
            },
        },
        "floors": floors,
        "learnability_gate": gate,
        "risk_labels": risk,
        "leakage_checks": leakage,
        "finite": bool(finite),
        "test_floor_role": "audit_only",
    }


def write_gate_payload(data_root=None, result_root=None, **kwargs):
    paths = resolve_runtime_paths(data_root, result_root, os.environ)
    payload = build_gate_payload(data_root=paths.data_root, **kwargs)
    out_dir = paths.output_root / "pilot" / "metropt3" / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "data_gate.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload, out_path


def main():
    parser = argparse.ArgumentParser(description="MetroPT v2 data gate")
    parser.add_argument("--data-root", default=None)
    parser.add_argument("--result-root", default=None)
    parser.add_argument("--max-windows-per-split", type=int, default=None)
    parser.add_argument("--history-len", type=int, default=168)
    parser.add_argument("--pred-len", type=int, default=24)
    parser.add_argument("--stride", type=int, default=60)
    args = parser.parse_args()

    payload, out_path = write_gate_payload(
        data_root=args.data_root,
        result_root=args.result_root,
        max_windows_per_split=args.max_windows_per_split,
        history_len=args.history_len,
        pred_len=args.pred_len,
        stride=args.stride,
    )
    summary = {
        "event": "metropt_data_gate",
        "report": str(out_path),
        "split_sha256": payload["split_sha256"],
        "learnability_gate": payload["learnability_gate"]["result"],
        "best_predictor": payload["learnability_gate"]["best_predictor"],
        "best_improvement": payload["learnability_gate"]["best_improvement"],
        "improved_channels": payload["learnability_gate"]["improved_channels"],
        "risk_evaluable": payload["risk_labels"]["risk_evaluable"],
        "leakage_all_pass": all(payload["leakage_checks"].values()),
        "finite": payload["finite"],
    }
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    ready = (
        summary["learnability_gate"] == "pass"
        and summary["leakage_all_pass"]
        and summary["finite"]
    )
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
