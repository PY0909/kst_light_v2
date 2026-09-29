"""V2-CH4-CODE-T03: chapter-4 leakage gates and prediction-artifact identity.

Three guards: (1) validation-only tuning is structurally unable to touch the
test loader; (2) checkpoint selection ignores test targets (two runs with
identical train/valid but different test labels select identical
checkpoints); (3) the prediction artifact carries forecast/query times,
unit ids, a median quantile, and is cryptographically linked to the run's
checkpoint and protocol identity, which the formal validator enforces.
"""

import copy
import json
import sys
from pathlib import Path

import torch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "code"))

from kaf_profiti.industrial.batch import IndustrialBatch  # noqa: E402

B, H, P, N = 2, 4, 2, 3


class _TripwireTestLoader:
    """Iterable that fails the moment the test split is touched."""

    def __iter__(self):
        raise AssertionError("test loader was iterated outside the single formal evaluation")


def _make_window(index: int, y_scale: float = 1.0) -> IndustrialBatch:
    y = torch.full((P, N), float(index) * y_scale)
    return IndustrialBatch(
        X_obs=torch.zeros(H, N),
        T_obs=torch.arange(H, dtype=torch.float32),
        M_obs=torch.ones(H, N),
        T_q=(torch.arange(P, dtype=torch.float32) + H) * (index + 1),
        Y_q=y,
        M_q=torch.ones_like(y),
        context=torch.zeros(2),
        y_flat=y.reshape(-1),
        mq_flat=torch.ones_like(y.reshape(-1)),
        query_channel_ids=torch.arange(N).repeat(P),
        rul=0.0,
        unit_id=index,
        window_id=f"w{index}",
    )


def _loader(count: int, y_scale: float = 1.0):
    from kaf_profiti.industrial.batch import IndustrialCollator
    from torch.utils.data import DataLoader

    class _Set(torch.utils.data.Dataset):
        def __len__(self):
            return count

        def __getitem__(self, index):
            return _make_window(index, y_scale)

    return DataLoader(_Set(), batch_size=2, collate_fn=IndustrialCollator())


def _spec(track="point", model_id="kst_flow_v2", epochs=1):
    from kaf_profiti.experiments.pilot_runner import PilotRunSpec

    return PilotRunSpec(
        key="k", track=track, matrix_name="m", dataset="d", model_id=model_id,
        head_type="flow" if track == "probabilistic" else "mlp",
        family="ours", condition_id="c", missing_mode="mixed",
        target_missing_rate=0.3, seed=2026, split_seed=2026, mask_seed=2026,
        history_len=H, pred_len=P, stride=1, epochs=epochs, batch_size=2,
        hidden_dim=4,
    )


def test_tune_mode_never_touches_test_loader():
    """The validation-only trainer receives a tripwire loader under the
    'test' key; touching it in any way fails the test immediately."""

    from run_pilot_matrix import _formal_tune_run

    class _TinyModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.dummy = torch.nn.Parameter(torch.zeros(1))

        def loss(self, batch):
            return batch.y_flat.pow(2).mean() + self.dummy * 0.0

        def predict_point(self, batch):
            return torch.zeros_like(batch.y_flat)

    class _MetaProvider:
        num_sensors = N
        context_dim = 2
        model_options = {}

        class bundle:  # noqa: N801
            split_info = {}

    provider = _MetaProvider()
    provider.model_options = {"patch_lens": (2,)}
    result = _formal_tune_run(
        _spec(track="probabilistic"), provider, "cpu",
        loaders={"train": _loader(4), "valid": _loader(4), "test": _TripwireTestLoader()},
    )
    assert result["best_valid_score"] is not None
    assert result["test_evaluation_count"] == 0


def test_checkpoint_selection_ignores_test_targets():
    """Two full evaluations with identical train/valid but wildly different
    test targets must select identical checkpoints — test labels never enter
    training, early stopping, or checkpoint selection."""

    from kaf_profiti.experiments.pilot_runner import pilot_train_and_evaluate

    class _TinyModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.weight = torch.nn.Parameter(torch.zeros(1))

        def predict_point(self, batch):
            return self.weight.expand_as(batch.y_flat) + batch.y_flat * 0.0

        def loss(self, batch):
            return (self.predict_point(batch) - batch.y_flat).abs().mean()

    class _MetaProvider:
        num_sensors = N
        context_dim = 2
        model_options = {}

        class bundle:  # noqa: N801
            split_info = {}

    def run(test_scale: float):
        torch.manual_seed(2026)
        model = _TinyModel()
        loaders = {
            "train": _loader(4),
            "valid": _loader(4),
            "test": _loader(4, y_scale=test_scale),
        }
        spec = _spec(epochs=2)
        return pilot_train_and_evaluate(model, loaders, spec, _MetaProvider(), device="cpu")

    first = run(test_scale=1.0)
    second = run(test_scale=1e6)  # test targets exploded: irrelevant to selection
    assert first["checkpoint_selection"] == second["checkpoint_selection"]
    assert first["valid_selection_score"] == second["valid_selection_score"]
    assert torch.equal(
        torch.frombuffer(bytearray(first["checkpoint_bytes"]), dtype=torch.uint8),
        torch.frombuffer(bytearray(second["checkpoint_bytes"]), dtype=torch.uint8),
    )


def test_prediction_artifact_carries_times_units_and_median():
    from kaf_profiti.experiments.pilot_runner import _test_prediction_artifact

    class _Diag(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.dummy = torch.nn.Parameter(torch.zeros(1))

        def predict_point(self, batch):
            return batch.y_flat + 0.5

        def gaussian_params(self, batch):
            mean = (batch.y_flat + 0.5).reshape(batch.Y_q.shape)
            return mean, torch.full_like(mean, 0.2)

        def sample_flat(self, batch, nsamples=8, generator=None):
            mean = (batch.y_flat + 0.5).unsqueeze(1)
            eps = torch.randn(mean.shape[0], nsamples, mean.shape[-1], generator=generator)
            return (mean + eps * 0.2) * batch.mq_flat.unsqueeze(1)

        def batch_nll(self, batch):
            return batch.y_flat.pow(2).mean()

        def interval95_flat(self, batch):
            generator = torch.Generator().manual_seed(7)
            samples = self.sample_flat(batch, nsamples=32, generator=generator)
            return torch.quantile(samples, 0.025, dim=1), torch.quantile(samples, 0.975, dim=1)

    _Diag.gaussian_kind = "diagonal"

    class _MetaProvider:
        num_sensors = N
        context_dim = 2
        model_options = {}

        class bundle:  # noqa: N801
            split_info = {}

    import os

    os.environ["KST_PREDICTION_DETAIL_CAP"] = "100"
    metrics, payload = _test_prediction_artifact(
        _Diag(), _loader(4), "cpu", _spec(track="probabilistic"), _MetaProvider(),
    )
    assert len(payload["T_q"]) == 4          # one query-time row per window
    assert len(payload["T_q"][0]) == P       # each row carries the P query times
    assert len(payload["unit_id"]) == 4
    assert "quantile_median" in payload and len(payload["quantile_median"]) == 4
    assert payload["T_q"][0][0] == float(H)  # forecast origin timeline preserved


def test_formal_write_links_checkpoint_and_protocol_into_predictions(tmp_path: Path):
    from run_pilot_matrix import _formal_spec, _write_formal_run
    from kaf_profiti.experiments.formal_matrix import expand_formal_matrix, load_formal_matrix

    matrix = load_formal_matrix(REPO_ROOT / "configs" / "ch4" / "probabilistic_matrix.yaml")
    key = next(
        k for k in expand_formal_matrix(matrix)
        if k.model_id == "kst_flow_v2" and k.protocol == "cmapss_fd001"
    )
    protocol_block = matrix.protocols[key.protocol]
    condition = protocol_block["conditions"][0]
    spec = _formal_spec(key, matrix, protocol_block, condition)

    class _FakeProvider:
        def protocol_fingerprint(self):
            return {
                "dataset": "cmapss_fd001",
                "split_sha256": "split-x",
                "normalization_sha256": "norm-x",
                "mask_sha": {"train": "m1", "valid": "m2", "test": "m3"},
            }

    result = {
        "history": [{"epoch": 1, "train_loss": 0.5, "valid_score": 0.4}],
        "metrics": {"mae": 0.25, "rmse": 0.5, "nll": 1.0, "crps": 0.4,
                    "picp": 0.95, "mpiw": 0.8, "point": {}, "probabilistic": {}},
        "checkpoint_bytes": b"ckpt-bytes",
        "predictions": {"schema_version": 1, "track": "probabilistic",
                        "window_id": ["w0"], "nsamples": 100},
        "train_time_sec": 1.0,
        "inference_time_sec": 0.01,
        "model_class": "KSTFlowV2",
        "model_config": {},
        "optimizer_config": {},
        "training_command_hash": "h",
        "checkpoint_selection": "best_valid",
        "valid_selection_score": 0.4,
    }
    manifest_path = _write_formal_run(
        tmp_path, spec, matrix, _FakeProvider(), result, "cpu",
    )
    run_dir = manifest_path.parent
    predictions = json.loads((run_dir / "predictions.json").read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert predictions["checkpoint_sha256"] == manifest["checkpoint_sha256"]
    assert predictions["protocol_sha256"]["split_sha256"] == "split-x"
    assert predictions["protocol_sha256"]["mask_sha"]["train"] == "m1"


def test_validator_flags_checkpoint_linkage_mismatch(tmp_path: Path):
    from kaf_profiti.experiments.formal_matrix import expand_formal_matrix, load_formal_matrix
    from validate_results import validate_formal_results

    matrix = load_formal_matrix(REPO_ROOT / "configs" / "ch4" / "probabilistic_matrix.yaml")
    key = next(
        k for k in expand_formal_matrix(matrix)
        if k.model_id == "kst_flow_v2" and k.protocol == "cmapss_fd001"
    )
    profile = "fd001"
    run_dir = tmp_path / "pilot" / profile / "runs" / key.scientific_key
    run_dir.mkdir(parents=True)
    (run_dir / "history.json").write_text(
        json.dumps([{"epoch": 1, "valid_score": 0.4}]), encoding="utf-8")
    metrics = {"mae": 0.25, "rmse": 0.5, "nll": 1.0, "crps": 0.4, "point": {}, "probabilistic": {}}
    (run_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    (run_dir / "checkpoint.pt").write_bytes(b"ckpt")
    import hashlib

    manifest = {
        "status": "completed",
        "run_id": key.scientific_key,
        "matrix_id": matrix.matrix_id,
        "matrix_sha256": matrix.matrix_sha256,
        "test_evaluation_count": 1,
        "protocol_sha": {"dataset": "cmapss_fd001", "split_sha256": "s",
                         "normalization_sha256": "n", "mask_sha": {}},
        "parameter_count": 10,
        "train_seconds": 1.0,
        "inference_time_sec": 0.01,
        "artifacts": {"history": "history.json", "metrics": "metrics.json",
                      "checkpoint": "checkpoint.pt", "predictions": "predictions.json"},
        "artifact_sha256": {
            "history": hashlib.sha256((run_dir / "history.json").read_bytes()).hexdigest(),
            "metrics": hashlib.sha256((run_dir / "metrics.json").read_bytes()).hexdigest(),
            "checkpoint": hashlib.sha256((run_dir / "checkpoint.pt").read_bytes()).hexdigest(),
            "predictions": "will-be-set-below",
        },
        "checkpoint_sha256": hashlib.sha256(b"ckpt").hexdigest(),
    }
    predictions = {
        "track": "probabilistic",
        "checkpoint_sha256": hashlib.sha256(b"DIFFERENT-checkpoint").hexdigest(),
    }
    predictions_bytes = json.dumps(predictions).encode("utf-8")
    (run_dir / "predictions.json").write_bytes(predictions_bytes)
    manifest["artifact_sha256"]["predictions"] = hashlib.sha256(predictions_bytes).hexdigest()
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    verdict = validate_formal_results(
        matrix, tmp_path, protocols={"cmapss_fd001"},
        condition_ids={"prob_mixed_030"},
    )
    assert any("checkpoint linkage" in item for item in verdict["failed"])

    # a matching linkage clears the flag
    predictions["checkpoint_sha256"] = manifest["checkpoint_sha256"]
    predictions_bytes = json.dumps(predictions).encode("utf-8")
    (run_dir / "predictions.json").write_bytes(predictions_bytes)
    manifest["artifact_sha256"]["predictions"] = hashlib.sha256(predictions_bytes).hexdigest()
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    verdict = validate_formal_results(
        matrix, tmp_path, protocols={"cmapss_fd001"},
        condition_ids={"prob_mixed_030"},
    )
    assert not any("checkpoint linkage" in item for item in verdict["failed"])
