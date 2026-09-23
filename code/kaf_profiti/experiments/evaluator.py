"""Unified Chapter 3/4 evaluator and artifact helpers (CH34-S02-T04)."""

import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

import torch

from kaf_profiti.experiments.accumulators import GlobalMetricAccumulator


def evaluate_batches(batches: Iterable[Mapping[str, torch.Tensor]], track: str, nsamples: int = 100, interval_level: float = 0.95) -> Dict[str, object]:
    """Aggregate point/probability metrics from precomputed batch mappings.

    Each mapping contains ``target``, ``prediction``, ``mask`` and, for a
    probabilistic track, optional ``nll_sum``, ``crps_sum`` and ``samples``.
    All denominators are valid target positions; masked/non-finite targets are
    excluded by ``GlobalMetricAccumulator``.
    """
    accumulator = GlobalMetricAccumulator()
    alpha = (1.0 - float(interval_level)) / 2.0
    for batch in batches:
        target = batch["target"]
        prediction = batch["prediction"]
        mask = batch["mask"]
        accumulator.update_point(target, prediction, mask)
        if track == "probabilistic":
            count = float(((mask > 0) & target.isfinite() & prediction.isfinite()).sum())
            if "nll_sum" in batch:
                accumulator.update_nll(float(batch["nll_sum"]), count)
            if "crps_sum" in batch:
                accumulator.update_crps(float(batch["crps_sum"]), count)
            samples = batch.get("samples")
            if samples is not None:
                lower = torch.quantile(samples, alpha, dim=1)
                upper = torch.quantile(samples, 1.0 - alpha, dim=1)
                valid = (mask > 0) & target.isfinite() & lower.isfinite() & upper.isfinite()
                accumulator.update_interval_sums(
                    "main",
                    float(((target >= lower) & (target <= upper) & valid).sum()),
                    float(torch.where(valid, upper - lower, torch.zeros_like(upper)).sum()),
                    float(valid.sum()),
                )
    return accumulator.point_only_result() if track == "point" else accumulator.result()


def _channel_error_metrics(
    target: torch.Tensor,
    prediction: torch.Tensor,
    mask: torch.Tensor,
    query_channel_ids: torch.Tensor,
    target_columns,
    scale: Optional[torch.Tensor] = None,
) -> Dict[str, Dict[str, object]]:
    """Return per-channel MAE/RMSE without aggregating unlike physical units."""

    result: Dict[str, Dict[str, object]] = {}
    for channel_id, column in enumerate(target_columns):
        channel_positions = query_channel_ids == channel_id
        valid = (
            (mask[:, channel_positions] > 0)
            & target[:, channel_positions].isfinite()
            & prediction[:, channel_positions].isfinite()
        )
        diff = torch.where(
            valid,
            prediction[:, channel_positions] - target[:, channel_positions],
            torch.zeros_like(prediction[:, channel_positions]),
        )
        if scale is not None:
            diff = diff * scale[channel_id]
        count = int(valid.sum())
        result[str(column)] = {
            "mae": float(diff.abs().sum()) / count if count else None,
            "rmse": math.sqrt(float(diff.pow(2).sum()) / count) if count else None,
            "valid_count": count,
        }
    return result


def metrics_from_prediction_payload(payload: Mapping[str, Any]) -> Dict[str, object]:
    """Recompute every reported test metric from a persisted prediction payload."""

    track = str(payload["track"])
    target = torch.tensor(payload["target"], dtype=torch.float64)
    prediction = torch.tensor(payload["prediction"], dtype=torch.float64)
    mask = torch.tensor(payload["mask"], dtype=torch.float64)
    if target.shape != prediction.shape or target.shape != mask.shape or target.ndim != 2:
        raise ValueError("target, prediction, and mask must have the same 2-D shape")
    window_ids = list(payload["window_id"])
    if len(window_ids) != target.shape[0] or len(set(window_ids)) != len(window_ids):
        raise ValueError("window_id must be unique and aligned with prediction rows")
    query_channel_ids = torch.tensor(payload["query_channel_ids"], dtype=torch.long)
    if query_channel_ids.ndim != 1 or query_channel_ids.numel() != target.shape[1]:
        raise ValueError("query_channel_ids must align with flattened query positions")
    target_columns = list(payload["target_columns"])
    if not target_columns or int(query_channel_ids.max()) >= len(target_columns):
        raise ValueError("target_columns do not cover query_channel_ids")

    accumulator = GlobalMetricAccumulator()
    accumulator.update_point(target, prediction, mask)
    if track == "probabilistic":
        row_counts = torch.tensor(payload["score_count_per_window"], dtype=torch.float64)
        nll_sums = torch.tensor(payload["nll_sum_per_window"], dtype=torch.float64)
        crps_sums = torch.tensor(payload["crps_sum_per_window"], dtype=torch.float64)
        if not (len(row_counts) == len(nll_sums) == len(crps_sums) == target.shape[0]):
            raise ValueError("probabilistic score contributions must align with windows")
        positive = row_counts > 0
        score_count = float(row_counts[positive].sum())
        if score_count <= 0:
            raise ValueError("probabilistic payload contains no valid target positions")
        accumulator.update_nll(float(nll_sums[positive].sum()), score_count)
        accumulator.update_crps(float(crps_sums[positive].sum()), score_count)
        lower = torch.tensor(payload["lower"], dtype=torch.float64)
        upper = torch.tensor(payload["upper"], dtype=torch.float64)
        if lower.shape != target.shape or upper.shape != target.shape:
            raise ValueError("prediction interval bounds must align with targets")
        valid = (mask > 0) & target.isfinite() & lower.isfinite() & upper.isfinite()
        accumulator.update_interval_sums(
            "main",
            float(((target >= lower) & (target <= upper) & valid).sum()),
            float(torch.where(valid, upper - lower, torch.zeros_like(upper)).sum()),
            float(valid.sum()),
        )
        metrics = accumulator.result()
    elif track == "point":
        metrics = accumulator.point_only_result()
    else:
        raise ValueError(f"unknown prediction track: {track!r}")

    metrics["per_channel_standardized"] = _channel_error_metrics(
        target, prediction, mask, query_channel_ids, target_columns
    )
    normalization = payload.get("normalization")
    if normalization is not None:
        scale = torch.tensor(normalization["std"], dtype=torch.float64)
        if scale.numel() != len(target_columns):
            raise ValueError("normalization std does not align with target columns")
        metrics["per_channel_physical"] = _channel_error_metrics(
            target, prediction, mask, query_channel_ids, target_columns, scale=scale
        )
    else:
        metrics["per_channel_physical"] = None

    repeats = [float(value) for value in payload.get("timing", {}).get("inference_seconds", [])]
    metrics["inference_time_raw_repeats"] = repeats
    metrics["inference_time_sec"] = statistics.median(repeats) if repeats else None
    train_repeats = [
        float(value) for value in payload.get("timing", {}).get("train_seconds", [])
    ]
    metrics["train_time_raw_repeats"] = train_repeats
    metrics["train_time_sec"] = statistics.median(train_repeats) if train_repeats else None
    metrics["parameter_count"] = payload.get("parameter_count")
    return metrics


def artifact_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_prediction_artifact(path: Path, payload: Mapping[str, Any]) -> str:
    """Write canonical JSON prediction artifact and return its content SHA."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return artifact_sha256(path)


def validate_prediction_metadata(manifest: Mapping[str, Any], payload: Mapping[str, Any], metrics: Optional[Mapping[str, Any]] = None) -> None:
    """Validate track-specific prediction metadata contracts.

    Point runs intentionally carry ``manifest.nsamples`` as the shared matrix
    setting but emit no samples, so ``predictions.nsamples`` must be ``None``.
    Probabilistic runs must emit the configured sample count.
    """

    track = manifest.get("track")
    if payload.get("track") != track:
        raise ValueError("prediction track does not match manifest")
    if payload.get("interval_level") != manifest.get("interval_level"):
        raise ValueError("prediction interval_level does not match manifest")
    if track == "point":
        if payload.get("nsamples") is not None:
            raise ValueError("point prediction artifact must have nsamples=null")
    elif track == "probabilistic":
        if payload.get("nsamples") != manifest.get("nsamples"):
            raise ValueError("probabilistic prediction nsamples does not match manifest")
    else:
        raise ValueError(f"unknown prediction track: {track!r}")
    if metrics is not None and payload.get("parameter_count") != metrics.get("parameter_count"):
        raise ValueError("prediction parameter_count does not match metrics")
def validate_artifact_manifest(manifest: Mapping[str, Any], result_root: Path) -> None:
    """Validate relative artifact paths and content hashes for round-trips."""
    artifacts = manifest.get("artifacts", {})
    hashes = manifest.get("artifact_sha256", {})
    if set(artifacts) != set(hashes):
        raise ValueError("artifact names and hashes differ")
    root = Path(result_root).resolve()
    for name, relative in artifacts.items():
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"artifact path is not result-root-relative: {relative}")
        path = (root / relative_path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"artifact escapes result root: {relative}") from exc
        if not path.is_file() or artifact_sha256(path) != hashes[name]:
            raise ValueError(f"artifact hash mismatch: {name}")


def build_artifact_manifest(identity: Mapping[str, Any], artifacts: Mapping[str, str], result_root: Path, protocol_sha: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Build the common run manifest with one test evaluation and content SHAs."""
    root = Path(result_root).resolve()
    manifest = dict(identity)
    manifest.update({
        "run_id": identity["key"],
        "test_evaluation_count": 1,
        "protocol_sha": dict(protocol_sha or {}),
        "artifacts": dict(artifacts),
        "artifact_sha256": {},
    })
    for name, relative in artifacts.items():
        path = (root / relative).resolve()
        if path.is_file():
            manifest["artifact_sha256"][name] = artifact_sha256(path)
    validate_artifact_manifest(manifest, root)
    return manifest
