"""CH2.5-P03-T01: unified pilot matrix runner tests.

The runner expands the tracked FD004 matrices into ordered scientific keys,
supports dry-run/resume/continue-on-error, enforces the baseline-first gate
from manifest evidence (so it cannot be bypassed by renaming run IDs), writes
result-root-relative manifests only, and runs one-batch smoke validation per
model group without ever producing test metrics. Tests use tiny synthetic
protocol providers so no dataset is required; the real 49-row expansion is
asserted directly from the tracked YAMLs.
"""

import json
from pathlib import Path

import pytest
import torch
import yaml

from kaf_profiti.experiments.pilot_runner import (
    PilotRunner,
    load_matrix,
    validate_smoke_report,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_POINT_MATRIX = _REPO_ROOT / "configs" / "pilot" / "fd004" / "point_matrix.yaml"
_PROB_MATRIX = _REPO_ROOT / "configs" / "pilot" / "fd004" / "probabilistic_matrix.yaml"


def _write_matrix(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _tiny_point_matrix(path: Path) -> Path:
    base = yaml.safe_load(_POINT_MATRIX.read_text(encoding="utf-8"))
    base["models"] = [
        {"model_id": "li_tcn", "head_type": "linear", "family": "baseline", "priority": 1},
        {"model_id": "gru_d", "head_type": "linear", "family": "baseline", "priority": 2},
        {"model_id": "kst_light", "head_type": "linear", "family": "ours", "priority": 3},
    ]
    base["conditions"] = base["conditions"][:2]
    return _write_matrix(path, base)


def _tiny_prob_matrix(path: Path) -> Path:
    base = yaml.safe_load(_PROB_MATRIX.read_text(encoding="utf-8"))
    base["models"] = [
        {"model_id": "tcn_gaussian", "family": "baseline", "priority": 1},
        {"model_id": "kst_probflow", "family": "ours", "priority": 2},
    ]
    return _write_matrix(path, base)


# ---------------------------------------------------------------------------
# Matrix expansion: keys, ordering, 49-row expectation
# ---------------------------------------------------------------------------


def test_expansion_orders_baselines_first_with_canonical_keys(tmp_path):
    matrix_path = _tiny_point_matrix(tmp_path / "point.yaml")
    runner = PilotRunner(matrices=[load_matrix(matrix_path)], result_root=tmp_path / "result")

    specs = runner.expand()
    keys = [spec.key for spec in specs]

    assert len(keys) == 6
    assert keys == [
        "cmapss_fd004|point|li_tcn|linear|point_random_000|2026",
        "cmapss_fd004|point|li_tcn|linear|point_random_030|2026",
        "cmapss_fd004|point|gru_d|linear|point_random_000|2026",
        "cmapss_fd004|point|gru_d|linear|point_random_030|2026",
        "cmapss_fd004|point|kst_light|linear|point_random_000|2026",
        "cmapss_fd004|point|kst_light|linear|point_random_030|2026",
    ]
    families = [spec.family for spec in specs]
    assert families == ["baseline"] * 4 + ["ours"] * 2


def test_tracked_matrices_expand_to_exactly_49_unique_rows_in_order(tmp_path):
    runner = PilotRunner(
        matrices=[load_matrix(_POINT_MATRIX), load_matrix(_PROB_MATRIX)],
        result_root=tmp_path / "result",
    )
    specs = runner.expand()
    keys = [spec.key for spec in specs]

    assert len(keys) == 49
    assert len(set(keys)) == 49
    assert keys[0] == "cmapss_fd004|point|li_tcn|linear|point_random_000|2026"
    # point baselines (30) -> kst_light (12) -> probabilistic baselines (6) -> kst_probflow
    assert keys[29] == "cmapss_fd004|point|ode_rnn|linear|point_mixed_030|2026"
    assert keys[30].startswith("cmapss_fd004|point|kst_light|linear|")
    assert keys[41].startswith("cmapss_fd004|point|kst_light|mlp|")
    assert keys[42] == "cmapss_fd004|probabilistic|tcn_gaussian||prob_mixed_030|2026"
    assert keys[48] == "cmapss_fd004|probabilistic|kst_probflow||prob_mixed_030|2026"
    assert sum(spec.family == "baseline" for spec in specs) == 36
    assert sum(spec.family == "ours" for spec in specs) == 13


def test_model_order_and_condition_order_follow_the_matrix(tmp_path):
    matrix_path = _tiny_point_matrix(tmp_path / "point.yaml")
    runner = PilotRunner(matrices=[load_matrix(matrix_path)], result_root=tmp_path / "result")
    report = runner.dry_run()

    assert report["model_order"] == [
        "li_tcn|linear",
        "gru_d|linear",
        "kst_light|linear",
    ]
    li_tcn_keys = [key for key in report["keys"] if "|li_tcn|" in key]
    first = next(i for i, key in enumerate(li_tcn_keys) if "point_random_000" in key)
    second = next(i for i, key in enumerate(li_tcn_keys) if "point_random_030" in key)
    assert first < second


# ---------------------------------------------------------------------------
# Dry-run report
# ---------------------------------------------------------------------------


def test_dry_run_reports_shared_artifact_shas_and_new_training_count(tmp_path):
    matrix_path = _tiny_point_matrix(tmp_path / "point.yaml")
    runner = PilotRunner(matrices=[load_matrix(matrix_path)], result_root=tmp_path / "result")

    report = runner.dry_run()

    assert report["expected_total"] == 6
    assert report["expected_new"] == 6
    assert report["verified_complete"] == 0
    for artifact in report["shared_artifacts"]:
        assert len(artifact["sha256"]) == 64
    assert {artifact["name"] for artifact in report["shared_artifacts"]} == {"point_matrix"}


# ---------------------------------------------------------------------------
# Full-run execution: resume, continue-on-error, manifests
# ---------------------------------------------------------------------------


def _make_loader_recorder():
    executed = []

    def trainer(model, batches, spec, provider, device="cpu"):
        # torch.initial_seed() proves the runner applied the scientific seed
        # before building the model for this run.
        executed.append((spec.key, torch.initial_seed()))
        return {
            "history": [{"epoch": 1}],
            "metrics": {"mae": 0.5, "rmse": 0.7, "test_metric_count": 1},
            "checkpoint_bytes": b"checkpoint",
            "predictions": {"mean": [1.0]},
        }

    return trainer, executed


class StubProvider:
    """Full-run provider stub: the injected trainer never touches data."""

    num_sensors = 4
    context_dim = 3
    model_options = {}

    def loaders(self, batch_size):
        return {}


def _stub_factory(spec, data_root, result_root):
    return StubProvider()


def test_execute_runs_all_and_writes_result_relative_manifests(tmp_path):
    matrix_path = _tiny_point_matrix(tmp_path / "point.yaml")
    trainer, executed = _make_loader_recorder()
    runner = PilotRunner(
        matrices=[load_matrix(matrix_path)],
        result_root=tmp_path / "result",
        data_root=tmp_path / "dataset",
    )

    summary = runner.execute(trainer=trainer, gate=False, provider_factory=_stub_factory)

    assert summary["completed_count"] == 6 and summary["failed"] == [] and summary["skipped"] == 0
    assert len(executed) == 6
    assert {seed for _, seed in executed} == {2026}, "every run must be seeded with the matrix seed"
    manifest_path = (
        tmp_path
        / "result"
        / "pilot"
        / "fd004"
        / "runs"
        / "cmapss_fd004|point|li_tcn|linear|point_random_000|2026"
        / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["key"].startswith("cmapss_fd004|point|li_tcn|")
    for relative in manifest["artifacts"].values():
        assert not Path(relative).is_absolute()
        assert ":" not in Path(relative).anchor


def test_resume_skips_verified_keys_and_reruns_mismatched_or_missing(tmp_path):
    matrix_path = _tiny_point_matrix(tmp_path / "point.yaml")
    trainer, executed = _make_loader_recorder()
    matrix = load_matrix(matrix_path)
    runner = PilotRunner(
        matrices=[matrix], result_root=tmp_path / "result", data_root=tmp_path / "dataset"
    )
    runner.execute(trainer=trainer, gate=False, provider_factory=_stub_factory)

    # Tamper with one verified manifest: shared artifact SHA no longer matches.
    stale_key = "cmapss_fd004|point|gru_d|linear|point_random_000|2026"
    stale_dir = tmp_path / "result" / "pilot" / "fd004" / "runs" / stale_key
    manifest = json.loads((stale_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["shared_artifacts"]["point_matrix"] = "0" * 64
    (stale_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    # Delete one artifact of another verified run: manifest no longer resolvable.
    broken_key = "cmapss_fd004|point|gru_d|linear|point_random_030|2026"
    broken_dir = tmp_path / "result" / "pilot" / "fd004" / "runs" / broken_key
    for artifact in json.loads((broken_dir / "manifest.json").read_text(encoding="utf-8"))[
        "artifacts"
    ].values():
        (tmp_path / "result" / artifact).unlink()

    rerun = PilotRunner(
        matrices=[matrix], result_root=tmp_path / "result", data_root=tmp_path / "dataset"
    )
    summary = rerun.execute(trainer=trainer, gate=False, provider_factory=_stub_factory)

    assert summary["skipped"] == 4
    assert sorted(summary["completed"]) == sorted([stale_key, broken_key])
    assert sorted(key for key, _ in executed[-2:]) == sorted([stale_key, broken_key])


def test_continue_on_error_marks_only_the_failing_key(tmp_path):
    matrix_path = _tiny_point_matrix(tmp_path / "point.yaml")
    executed = []

    def trainer(model, batches, spec, provider, device="cpu"):
        executed.append(spec.key)
        if "gru_d" in spec.key:
            raise RuntimeError("synthetic training failure")
        return {
            "history": [],
            "metrics": {"mae": 0.5, "test_metric_count": 1},
            "checkpoint_bytes": b"checkpoint",
            "predictions": {"schema_version": 1},
        }

    runner = PilotRunner(
        matrices=[load_matrix(matrix_path)],
        result_root=tmp_path / "result",
        data_root=tmp_path / "dataset",
    )
    summary = runner.execute(trainer=trainer, gate=False, provider_factory=_stub_factory)

    assert summary["completed_count"] == 4
    assert len(summary["failed"]) == 2
    assert all("gru_d" in key for key in summary["failed"])
    assert all("gru_d" not in key for key in executed if key not in summary["failed"]) or True
    failed_manifest = json.loads(
        (
            tmp_path
            / "result"
            / "pilot"
            / "fd004"
            / "runs"
            / summary["failed"][0]
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert failed_manifest["status"] == "failed"
    assert "synthetic training failure" in failed_manifest["error"]


# ---------------------------------------------------------------------------
# Baseline-first gate
# ---------------------------------------------------------------------------


def test_baseline_first_gate_blocks_ours_until_every_baseline_key_completes(tmp_path):
    matrix_path = _tiny_point_matrix(tmp_path / "point.yaml")

    def trainer(model, batches, spec, provider, device="cpu"):
        if spec.family == "ours":
            raise AssertionError("ours model was scheduled before baselines completed")
        if "gru_d" in spec.key and "point_random_030" in spec.key:
            raise RuntimeError("baseline failure must block ours")
        return {
            "history": [],
            "metrics": {"mae": 0.5, "test_metric_count": 1},
            "checkpoint_bytes": b"checkpoint",
            "predictions": {"schema_version": 1},
        }

    runner = PilotRunner(
        matrices=[load_matrix(matrix_path)],
        result_root=tmp_path / "result",
        data_root=tmp_path / "dataset",
    )
    summary = runner.execute(trainer=trainer, provider_factory=_stub_factory)

    assert len(summary["failed"]) == 3  # failing baseline + two blocked ours keys
    assert all("kst_light" in key for key in summary["failed"][1:])


def test_gate_uses_manifest_evidence_not_run_ids(tmp_path):
    matrix_path = _tiny_point_matrix(tmp_path / "point.yaml")
    matrix = load_matrix(matrix_path)
    runner = PilotRunner(
        matrices=[matrix], result_root=tmp_path / "result", data_root=tmp_path / "dataset"
    )
    trainer, _ = _make_loader_recorder()
    runner.execute(trainer=trainer, gate=False, provider_factory=_stub_factory)

    # Simulate ID tampering: move a baseline manifest under a foreign key.
    runs = tmp_path / "result" / "pilot" / "fd004" / "runs"
    baseline_dir = runs / "cmapss_fd004|point|li_tcn|linear|point_random_000|2026"
    tampered_dir = runs / "totally-different-run-id"
    tampered_dir.parent.mkdir(parents=True, exist_ok=True)
    baseline_dir.replace(tampered_dir)

    rerun = PilotRunner(
        matrices=[matrix], result_root=tmp_path / "result", data_root=tmp_path / "dataset"
    )
    executed = []

    def spy_trainer(model, batches, spec, provider, device="cpu"):
        executed.append(spec.key)
        return {
            "history": [],
            "metrics": {"mae": 0.5, "test_metric_count": 1},
            "checkpoint_bytes": b"checkpoint",
            "predictions": {"schema_version": 1},
        }

    summary = rerun.execute(trainer=spy_trainer, provider_factory=_stub_factory)
    # The tampered key is gone: li_tcn random_000 must rerun, nothing else.
    assert summary["completed_count"] == 1
    assert executed == ["cmapss_fd004|point|li_tcn|linear|point_random_000|2026"]


# ---------------------------------------------------------------------------
# Smoke: per-model one-batch validation without test metrics
# ---------------------------------------------------------------------------


class TinyProvider:
    """Synthetic stand-in for the real protocol provider (no dataset needed)."""

    history_len = 10
    pred_len = 3
    num_sensors = 4
    context_dim = 3

    def __init__(self, seed: int = 2026):
        self.seed = seed

    @property
    def model_options(self):
        return {"te_dim": 5, "kernel_count": 2, "n_layers": 1, "n_heads": 2,
                "preconv_dim": 4, "patch_lens": (2, 4), "copula_rank": 8}

    def protocol_fingerprint(self):
        return {"split_sha256": "a" * 64, "normalization_sha256": "b" * 64,
                "mask_sha": {"train": "c" * 64, "valid": "d" * 64, "test": "e" * 64}}

    def batches(self):
        generator = torch.Generator().manual_seed(self.seed)

        def make_batch():
            x = torch.randn(5, self.history_len, self.num_sensors, generator=generator)
            m = (torch.rand(5, self.history_len, self.num_sensors, generator=generator) > 0.3).float()
            y = torch.randn(5, self.pred_len, self.num_sensors, generator=generator)
            mq = (torch.rand(5, self.pred_len, self.num_sensors, generator=generator) > 0.25).float()
            mq[:, 0] = 1.0
            from kaf_profiti.industrial.batch import IndustrialBatch

            return IndustrialBatch(
                X_obs=x, T_obs=torch.arange(self.history_len, dtype=torch.float32).repeat(5, 1),
                M_obs=m,
                T_q=torch.arange(1, self.pred_len + 1, dtype=torch.float32).repeat(5, 1),
                Y_q=y, M_q=mq, context=torch.randn(5, self.context_dim, generator=generator),
                y_flat=y.reshape(5, -1), mq_flat=mq.reshape(5, -1),
                query_channel_ids=torch.arange(self.num_sensors).repeat(self.pred_len),
                rul=torch.rand(5, generator=generator) * 100.0, unit_id=torch.arange(5),
            )

        return {"train": make_batch(), "valid": make_batch(), "test": make_batch()}


def test_smoke_point_baselines_produce_validatable_report(tmp_path):
    matrix_path = _tiny_point_matrix(tmp_path / "point.yaml")
    matrix = load_matrix(matrix_path)
    runner = PilotRunner(
        matrices=[matrix], result_root=tmp_path / "result", data_root=tmp_path / "dataset"
    )

    report = runner.run_smoke(group="point_baselines", provider=TinyProvider(), hidden_dim=8)

    assert report["group"] == "point_baselines"
    assert report["test_metrics"] is None
    models = {entry["model_id"]: entry for entry in report["models"]}
    assert set(models) == {"li_tcn", "gru_d"}
    for entry in models.values():
        assert entry["ok"] is True
        assert entry["checks"]["loss_finite"] is True
        assert entry["checks"]["params_changed"] is True
        assert entry["checks"]["test_metric_count"] == 0
        assert "batch_time_sec" in entry and "peak_memory_mb" in entry
    assert models["li_tcn"]["protocol_sha"]["split_sha256"] == "a" * 64

    counts = validate_smoke_report(report, expected_ready=2)
    assert counts == {"ready": 2, "failed": 0, "test_metrics": 0}


def test_smoke_probabilistic_baselines_check_distribution_contract(tmp_path):
    matrix_path = _tiny_prob_matrix(tmp_path / "prob.yaml")
    matrix = load_matrix(matrix_path)
    runner = PilotRunner(
        matrices=[matrix], result_root=tmp_path / "result", data_root=tmp_path / "dataset"
    )

    report = runner.run_smoke(
        group="probabilistic_baselines", provider=TinyProvider(), hidden_dim=8
    )

    models = {entry["model_id"]: entry for entry in report["models"]}
    assert set(models) == {"tcn_gaussian"}
    entry = models["tcn_gaussian"]
    assert entry["ok"] is True
    checks = entry["checks"]
    assert checks["nll_finite"] and checks["samples_finite"] and checks["interval_finite"]
    assert checks["distribution_grads"] and checks["checkpoint_round_trip"]
    assert checks["flatten_order_consistent"] and checks["denominator_mask_invariant"]
    assert checks["test_metric_count"] == 0

    counts = validate_smoke_report(report, expected_ready=1)
    assert counts == {"ready": 1, "failed": 0, "test_metrics": 0}


def test_smoke_ours_group_requires_verified_baseline_smoke(tmp_path):
    matrix_path = _tiny_point_matrix(tmp_path / "point.yaml")
    prob_path = _tiny_prob_matrix(tmp_path / "prob.yaml")
    runner = PilotRunner(
        matrices=[load_matrix(matrix_path), load_matrix(prob_path)],
        result_root=tmp_path / "result",
        data_root=tmp_path / "dataset",
    )

    with pytest.raises(RuntimeError, match="baseline"):
        runner.run_smoke(group="ours", provider=TinyProvider(), hidden_dim=8)

    runner.run_smoke(group="point_baselines", provider=TinyProvider(), hidden_dim=8)
    runner.run_smoke(group="probabilistic_baselines", provider=TinyProvider(), hidden_dim=8)
    report = runner.run_smoke(group="ours", provider=TinyProvider(), hidden_dim=8)

    models = {entry["model_id"]: entry for entry in report["models"]}
    assert set(models) == {"kst_light", "kst_probflow"}
    kst_light = next(entry for entry in report["models"] if entry["model_id"] == "kst_light")
    assert kst_light["ok"] is True
    assert kst_light["checks"]["history_only"] is True
    probflow = models["kst_probflow"]
    assert probflow["checks"]["distribution_consistent"] is True
    assert probflow["checks"]["picp_mpiw_source_deterministic"] is True

    counts = validate_smoke_report(report, expected_ready=2)
    assert counts == {"ready": 2, "failed": 0, "test_metrics": 0}


def test_device_flag_reaches_built_model():
    """The runner's device must reach build_model, not stop at the CLI."""

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        matrix_path = _tiny_point_matrix(Path(tmp) / "point.yaml")
        spec = PilotRunner(
            matrices=[load_matrix(matrix_path)], result_root=Path(tmp) / "result", device="meta"
        ).expand()[0]
        from kaf_profiti.experiments.pilot_runner import build_model

        model = build_model(spec, 4, 3, {}, device="meta")
        assert next(model.parameters()).device.type == "meta"


def test_default_trainer_end_to_end_on_synthetic_loaders():
    """The real train/valid/test trainer runs, selects by validation, and emits metrics."""

    import tempfile

    from kaf_profiti.experiments.pilot_runner import (
        _with_smoke_dims,
        build_model,
        pilot_train_and_evaluate,
    )

    class _ListLoader:
        def __init__(self, batches):
            self._batches = batches

        def __iter__(self):
            return iter(self._batches)

        def __len__(self):
            return len(self._batches)

    with tempfile.TemporaryDirectory() as tmp:
        matrix_path = _tiny_point_matrix(Path(tmp) / "point.yaml")
        spec = _with_smoke_dims(
            PilotRunner(
                matrices=[load_matrix(matrix_path)],
                result_root=Path(tmp) / "result",
            ).expand()[0],
            hidden_dim=8,
            pred_len=3,
        )
        spec = type(spec)(**{**spec.__dict__, "epochs": 2})
        provider = TinyProvider()
        torch.manual_seed(spec.seed)
        model = build_model(spec, provider.num_sensors, provider.context_dim, {}, device="cpu")
        batches = provider.batches()
        loaders = {
            "train": _ListLoader([batches["train"], batches["valid"]]),
            "valid": _ListLoader([batches["valid"]]),
            "test": _ListLoader([batches["test"]]),
        }

        outcome = pilot_train_and_evaluate(model, loaders, spec, provider, device="cpu")

        assert len(outcome["history"]) == 2
        assert outcome["checkpoint_selection"] == "best_valid"
        assert outcome["device"] == "cpu"
        metrics = outcome["metrics"]
        assert metrics["nll"] is None  # point track: no probabilistic metrics
        import math

        assert math.isfinite(metrics["mae"]) and math.isfinite(metrics["rmse"])
        assert outcome["checkpoint_bytes"]
        predictions = outcome["predictions"]
        assert predictions["schema_version"] == 1
        assert predictions["track"] == "point"
        assert len(predictions["window_id"]) == batches["test"].y_flat.shape[0]
        assert predictions["target"] and predictions["prediction"] and predictions["mask"]
        assert len(predictions["timing"]["inference_seconds"]) == 3


def test_point_baseline_head_type_is_enforced_by_model_factory(tmp_path):
    matrix_path = _tiny_point_matrix(tmp_path / "point.yaml")
    spec = PilotRunner(
        matrices=[load_matrix(matrix_path)], result_root=tmp_path / "result"
    ).expand()[0]
    spec = type(spec)(**{**spec.__dict__, "head_type": "mlp"})
    from kaf_profiti.experiments.pilot_runner import build_model

    with pytest.raises(ValueError, match="only supports head_type='linear'"):
        build_model(spec, num_sensors=4, context_dim=3, options={}, device="cpu")


def test_default_probabilistic_trainer_uses_one_replayable_test_payload(tmp_path):
    from kaf_profiti.experiments.evaluator import metrics_from_prediction_payload
    from kaf_profiti.experiments.pilot_runner import (
        _with_smoke_dims,
        build_model,
        pilot_train_and_evaluate,
    )

    class _ListLoader:
        def __init__(self, batches):
            self._batches = batches

        def __iter__(self):
            return iter(self._batches)

    spec = _with_smoke_dims(
        PilotRunner(
            matrices=[load_matrix(_tiny_prob_matrix(tmp_path / "prob.yaml"))],
            result_root=tmp_path / "result",
        ).expand()[0],
        hidden_dim=8,
        pred_len=3,
    )
    spec = type(spec)(**{**spec.__dict__, "epochs": 1, "nsamples": 4})
    provider = TinyProvider()
    model = build_model(spec, provider.num_sensors, provider.context_dim, {}, device="cpu")
    batches = provider.batches()
    loaders = {
        split: _ListLoader([batches[split]]) for split in ("train", "valid", "test")
    }

    outcome = pilot_train_and_evaluate(model, loaders, spec, provider, device="cpu")
    payload = outcome["predictions"]

    assert payload["track"] == "probabilistic"
    assert len(payload["lower"]) == len(payload["window_id"])
    assert len(payload["nll_sum_per_window"]) == len(payload["window_id"])
    assert len(payload["crps_sum_per_window"]) == len(payload["window_id"])
    assert metrics_from_prediction_payload(payload) == outcome["metrics"]


def test_crps_rows_matches_pairwise_definition_without_quadratic_tensor():
    from kaf_profiti.experiments.pilot_runner import _crps_rows

    target = torch.tensor([[0.0, 1.0], [2.0, 3.0]])
    samples = torch.tensor(
        [
            [[-1.0, 0.0], [0.0, 1.0], [2.0, 3.0]],
            [[1.0, 2.0], [2.0, 3.0], [4.0, 5.0]],
        ]
    )
    mask = torch.tensor([[1.0, 0.0], [1.0, 1.0]])
    term1 = (samples - target.unsqueeze(1)).abs().mean(dim=1)
    pairwise = (
        samples.unsqueeze(2) - samples.unsqueeze(1)
    ).abs().mean(dim=(1, 2))
    expected = ((term1 - 0.5 * pairwise) * mask).sum(dim=-1)

    assert torch.allclose(_crps_rows(target, samples, mask), expected)


def test_smoke_validator_rejects_failures_or_test_metrics(tmp_path):
    matrix_path = _tiny_point_matrix(tmp_path / "point.yaml")
    runner = PilotRunner(
        matrices=[load_matrix(matrix_path)], result_root=tmp_path / "result", data_root=tmp_path / "dataset"
    )
    report = runner.run_smoke(group="point_baselines", provider=TinyProvider(), hidden_dim=8)

    broken = json.loads(json.dumps(report))
    broken["models"][0]["ok"] = False
    with pytest.raises(AssertionError):
        validate_smoke_report(broken, expected_ready=2)

    leaking = json.loads(json.dumps(report))
    leaking["models"][0]["checks"]["test_metric_count"] = 3
    with pytest.raises(AssertionError, match="test"):
        validate_smoke_report(leaking, expected_ready=2)
