"""CH34-S02-T04: unified evaluator and prediction artifact contracts."""

import json
from pathlib import Path

import pytest
import torch

from kaf_profiti.experiments.evaluator import (
    artifact_sha256,
    build_artifact_manifest,
    evaluate_batches,
    metrics_from_prediction_payload,
    validate_artifact_manifest,
    validate_prediction_metadata,
    write_prediction_artifact,
)


def _batches(sizes=(2, 3)):
    target = torch.tensor([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0], [9.0, 10.0]])
    prediction = target + torch.tensor([[1.0, -1.0], [2.0, 0.0], [-1.0, 2.0], [0.5, -0.5], [1.5, 1.0]])
    mask = torch.ones_like(target)
    offset = 0
    for size in sizes:
        yield {"target": target[offset:offset + size], "prediction": prediction[offset:offset + size], "mask": mask[offset:offset + size]}
        offset += size


def test_point_metrics_are_batch_size_invariant_and_global():
    one = evaluate_batches(list(_batches((5,))), "point")
    split = evaluate_batches(list(_batches((1, 1, 3))), "point")
    assert one == split
    assert one["nll"] is None and one["crps"] is None
    assert one["probabilistic_metrics"] == "not_applicable"


def test_invalid_targets_do_not_enter_point_denominator():
    batches = list(_batches((5,)))
    batches[0]["target"][0, 0] = float("nan")
    batches[0]["mask"][0, 1] = 0
    result = evaluate_batches(batches, "point")
    assert result["valid_count"] == 8
    assert result["mae"] == pytest.approx(8.5 / 8)


def test_probability_metrics_use_same_samples_and_interval_level():
    target = torch.tensor([[0.0, 1.0], [2.0, 3.0]])
    prediction = torch.tensor([[0.1, 1.1], [2.1, 3.1]])
    mask = torch.ones_like(target)
    samples = torch.stack([prediction - 0.5, prediction + 0.5], dim=1)
    result = evaluate_batches([{
        "target": target, "prediction": prediction, "mask": mask,
        "samples": samples, "nll_sum": 4.0, "crps_sum": 2.0,
    }], "probabilistic", nsamples=2, interval_level=0.95)
    assert result["nll"] == pytest.approx(1.0)
    assert result["crps"] == pytest.approx(0.5)
    assert result["picp"] == pytest.approx(1.0)
    assert result["mpiw"] == pytest.approx(0.95, abs=1e-6)


def test_point_nsamples_null_and_probabilistic_nsamples_match_manifest():
    point_manifest = {"track": "point", "interval_level": 0.95, "nsamples": 20}
    validate_prediction_metadata(
        point_manifest,
        {"track": "point", "interval_level": 0.95, "nsamples": None},
    )
    with pytest.raises(ValueError, match="point prediction"):
        validate_prediction_metadata(
            point_manifest,
            {"track": "point", "interval_level": 0.95, "nsamples": 20},
        )

    probabilistic_manifest = {"track": "probabilistic", "interval_level": 0.95, "nsamples": 20}
    validate_prediction_metadata(
        probabilistic_manifest,
        {"track": "probabilistic", "interval_level": 0.95, "nsamples": 20},
    )
    with pytest.raises(ValueError, match="nsamples"):
        validate_prediction_metadata(
            probabilistic_manifest,
            {"track": "probabilistic", "interval_level": 0.95, "nsamples": None},
        )


def test_prediction_artifact_round_trip_and_content_sha(tmp_path):
    artifact = tmp_path / "runs" / "key" / "predictions.json"
    payload = {"window_id": ["w0", "w1"], "target": [[1.0], [2.0]], "mask": [[1.0], [1.0]], "prediction": [[1.1], [1.9]]}
    sha = write_prediction_artifact(artifact, payload)
    manifest = build_artifact_manifest(
        {"key": "dataset|point|model||condition|2026", "seed": 2026},
        {"predictions": "runs/key/predictions.json"}, tmp_path,
    )
    assert manifest["run_id"] == manifest["key"]
    assert manifest["test_evaluation_count"] == 1
    assert manifest["artifact_sha256"]["predictions"] == sha
    validate_artifact_manifest(manifest, tmp_path)
    assert json.loads(artifact.read_text(encoding="utf-8")) == payload
    artifact.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_artifact_manifest(manifest, tmp_path)


def test_artifact_manifest_rejects_absolute_and_parent_paths(tmp_path):
    for relative in ("/tmp/out.json", "../out.json"):
        with pytest.raises(ValueError, match="result-root-relative"):
            validate_artifact_manifest({"artifacts": {"prediction": relative}, "artifact_sha256": {"prediction": "x"}}, tmp_path)


def test_prediction_payload_recomputes_global_channel_and_physical_metrics():
    payload = {
        "schema_version": 1,
        "track": "point",
        "window_id": ["w0", "w1"],
        "target": [[1.0, 2.0], [3.0, 4.0]],
        "prediction": [[2.0, 1.0], [1.0, 6.0]],
        "mask": [[1.0, 1.0], [1.0, 0.0]],
        "query_channel_ids": [0, 1],
        "target_columns": ["sensor_a", "sensor_b"],
        "normalization": {"mean": [10.0, 20.0], "std": [2.0, 4.0]},
        "timing": {"inference_seconds": [0.1, 0.2, 0.15]},
    }

    metrics = metrics_from_prediction_payload(payload)

    assert metrics["valid_count"] == 3
    assert metrics["mae"] == pytest.approx(4.0 / 3.0)
    assert metrics["rmse"] == pytest.approx((6.0 / 3.0) ** 0.5)
    assert metrics["per_channel_standardized"]["sensor_a"]["mae"] == pytest.approx(1.5)
    assert metrics["per_channel_physical"]["sensor_a"]["mae"] == pytest.approx(3.0)
    assert metrics["per_channel_physical"]["sensor_b"]["mae"] == pytest.approx(4.0)
    assert metrics["inference_time_sec"] == pytest.approx(0.15)
    assert metrics["inference_time_raw_repeats"] == [0.1, 0.2, 0.15]
