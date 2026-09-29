"""V2-CH3-CODE-T03: formal point-matrix execution wiring and result validator.

The executor (``run_pilot_matrix.py --config``) expands the authoritative
matrix, enforces baseline-first gating per (protocol, condition), resumes
verified completed runs, writes PilotRunner-shaped manifests with the formal
identity chain, and supports a test-free smoke mode. ``validate_results.py``
checks the expected 66-key coverage plus key/fairness/finite/test-count/
parameter-and-timing fields over the produced run tree.
"""

import json
import sys
from pathlib import Path

import pytest
import torch

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "code"))

from kaf_profiti.experiments.formal_matrix import (  # noqa: E402
    expand_formal_matrix,
    load_formal_matrix,
)
from run_pilot_matrix import (  # noqa: E402
    _formal_execute_keys,
    _formal_profile_for,
)
from validate_results import validate_formal_results  # noqa: E402

FD001_PRESENT = (REPO_ROOT / "dataset" / "CMAPSSData" / "train_FD001.txt").is_file()


def _matrix():
    return load_formal_matrix(REPO_ROOT / "configs" / "ch3" / "point_matrix.yaml")


def _fd001_keys(matrix):
    return [key for key in expand_formal_matrix(matrix) if key.protocol == "cmapss_fd001"]


class _FakeProvider:
    num_sensors = 21
    context_dim = 3

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def model_options(self):
        return {}

    def protocol_fingerprint(self):
        return {
            "dataset": "cmapss_fd001",
            "split_sha256": "fake-split-sha",
            "normalization_sha256": "fake-norm-sha",
            "mask_sha": {"train": "m1", "valid": "m2", "test": "m3"},
        }


def _fake_result(spec):
    return {
        "history": [{"epoch": 1, "train_loss": 0.5, "valid_score": 0.4}],
        "metrics": {"point": {"mae": 0.25, "rmse": 0.5, "valid_count": 10},
                    "probabilistic": {}},
        "checkpoint_bytes": b"fake-checkpoint",
        "predictions": {"parameter_count": 1234},
        "train_time_sec": 1.5,
        "inference_time_sec": 0.02,
        "model_class": "FakeModel",
        "model_config": {"hidden_dim": spec.hidden_dim},
        "optimizer_config": {"lr": 1e-3, "weight_decay": 1e-4,
                             "scheduler": "cosine", "grad_clip_norm": 1.0},
        "training_command_hash": "hash",
        "checkpoint_selection": "best_valid",
        "device": "cpu",
    }


def test_optimizer_config_honors_matrix_recipe_for_baselines():
    """V2-CH3-SINGLE-T01 fix: the frozen matrix recipe must reach the optimizer
    for EVERY model, not only the v2 own models (the historical pilot default
    lr=1e-3 must never silently override the frozen recipe)."""

    from kaf_profiti.experiments.pilot_runner import PilotRunSpec, _optimizer_config

    baseline_spec = PilotRunSpec(
        key="k", track="point", matrix_name="m", dataset="metropt3_chrono_502030_v2",
        model_id="li_tcn", head_type="linear", family="baseline",
        condition_id="point_mixed_030", missing_mode="mixed", target_missing_rate=0.3,
        seed=2026, split_seed=2026, mask_seed=2026, history_len=168, pred_len=24,
        stride=60, epochs=80, batch_size=128, hidden_dim=64,
        learning_rate=0.0003, weight_decay=0.0001, scheduler="cosine",
        patience=0, grad_clip_norm=1.0,
    )
    config = _optimizer_config(baseline_spec)
    assert config["lr"] == 3e-4
    assert config["weight_decay"] == 1e-4
    assert config["grad_clip_norm"] == 1.0
    assert config["scheduler"] == "cosine"
    assert config["patience"] == 0

    # legacy pilot specs (no recipe fields) keep their historical defaults
    legacy = baseline_spec.__class__(**{**baseline_spec.__dict__,
                                        "learning_rate": None, "weight_decay": None,
                                        "scheduler": None, "patience": None,
                                        "grad_clip_norm": None})
    legacy_config = _optimizer_config(legacy)
    assert legacy_config["lr"] == 1e-3
    assert legacy_config["weight_decay"] == 1e-4


def test_formal_worker_resolution():
    from run_pilot_matrix import _resolve_formal_workers

    assert _resolve_formal_workers("cuda", "auto") == 4
    assert _resolve_formal_workers("cpu", "auto") == 0
    assert _resolve_formal_workers("cuda", "2") == 2
    assert _resolve_formal_workers("cpu", 0) == 0


def test_formal_profile_mapping_covers_six_protocols():
    assert _formal_profile_for("metropt3_chrono_502030_v2") == "metropt3"
    assert _formal_profile_for("cmapss_fd001") == "fd001"
    assert _formal_profile_for("cmapss_fd002") == "fd002"
    assert _formal_profile_for("cmapss_fd003") == "fd003"
    assert _formal_profile_for("cmapss_fd004") == "fd004"
    assert _formal_profile_for("tep_faulty") == "tep_faulty"


def test_execute_writes_verified_manifests_and_resumes(tmp_path: Path):
    matrix = _matrix()
    keys = _fd001_keys(matrix)
    assert len(keys) == 6

    calls = []

    def run_fn(spec, provider, device):
        calls.append(spec.key)
        assert provider.protocol_fingerprint()["dataset"] == "cmapss_fd001"
        return _fake_result(spec)

    summary = _formal_execute_keys(
        matrix, keys, result_root=tmp_path, data_root=tmp_path,
        device="cpu", run_fn=run_fn,
        provider_factory=lambda **kwargs: _FakeProvider(**kwargs),
    )
    assert summary["failed"] == [] and summary["gate_blocked"] == []
    assert summary["executed"] == 6 and summary["resumed"] == 0
    # baseline-first ordering within the condition group
    assert calls[-1].split("|")[2] == "kst_light_v2"

    manifest_dir = tmp_path / "pilot" / "fd001" / "runs"
    manifests = list(manifest_dir.glob("*/manifest.json"))
    assert len(manifests) == 6
    manifest = json.loads(
        (manifest_dir / keys[0].scientific_key / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "completed"
    assert manifest["run_id"] == keys[0].scientific_key
    assert manifest["test_evaluation_count"] == 1
    assert manifest["matrix_id"] == matrix.matrix_id
    assert manifest["matrix_sha256"] == matrix.matrix_sha256
    assert manifest["protocol_sha"]["split_sha256"] == "fake-split-sha"
    assert manifest["parameter_count"] == 1234
    assert manifest["train_seconds"] == 1.5
    assert manifest["inference_time_sec"] == 0.02
    for name in ("history", "metrics", "checkpoint", "predictions"):
        assert manifest["artifacts"][name]
        assert manifest["artifact_sha256"][name]

    # a second pass resumes: nothing re-executed
    second = _formal_execute_keys(
        matrix, keys, result_root=tmp_path, data_root=tmp_path,
        device="cpu", run_fn=run_fn,
        provider_factory=lambda **kwargs: _FakeProvider(**kwargs),
    )
    assert second["executed"] == 0 and second["resumed"] == 6


def test_ours_only_execution_sees_group_baselines(tmp_path: Path):
    """V2-CH3-SINGLE-T02 fix: gating must consult the FULL matrix expansion —
    running only the ours key (e.g. --family ours) must still find the five
    verified baseline references of its group instead of blocking on an
    execution-filtered empty group."""

    matrix = _matrix()
    keys = _fd001_keys(matrix)

    def run_fn(spec, provider, device):
        return _fake_result(spec)

    # first pass: baselines only, ours excluded from the list
    baselines = [k for k in keys if k.family == "baseline"]
    first = _formal_execute_keys(
        matrix, baselines, result_root=tmp_path, data_root=tmp_path,
        device="cpu", run_fn=run_fn,
        provider_factory=lambda **kwargs: _FakeProvider(**kwargs),
    )
    assert first["executed"] == 5 and first["gate_blocked"] == []

    # second pass: ONLY the ours key in the execution list
    ours = [k for k in keys if k.family == "ours"]
    second = _formal_execute_keys(
        matrix, ours, result_root=tmp_path, data_root=tmp_path,
        device="cpu", run_fn=run_fn,
        provider_factory=lambda **kwargs: _FakeProvider(**kwargs),
    )
    assert second["gate_blocked"] == []
    assert second["executed"] == 1


def test_apply_tuning_overrides_and_write_tuning_artifact(tmp_path: Path):
    """V2-CH3-SINGLE-T03: tuning candidates are validation-only — the spec
    override applies, the artifact is eligibility=tuning_only with
    test_evaluation_count=0, and it lives outside the runs/ tree."""

    from run_pilot_matrix import _apply_tuning_overrides, _write_tuning_run

    matrix = _matrix()
    keys = _fd001_keys(matrix)
    ours_key = next(k for k in keys if k.family == "ours")
    protocol_block = matrix.protocols[ours_key.protocol]
    condition = protocol_block["conditions"][0]
    from run_pilot_matrix import _formal_spec
    spec = _formal_spec(ours_key, matrix, protocol_block, condition)
    tuned = _apply_tuning_overrides(spec, {"hidden_dim": "48", "learning_rate": "0.0001"})
    assert tuned.hidden_dim == 48 and tuned.learning_rate == 1e-4
    assert tuned.key == spec.key and tuned.seed == spec.seed  # identity untouched

    provider = _FakeProvider()
    result = {
        "history": [{"epoch": 1, "train_loss": 0.5, "valid_score": 0.4}],
        "checkpoint_bytes": b"tune-ckpt",
        "best_valid_score": 0.4,
        "best_epoch": 1,
        "train_time_sec": 3.0,
        "model_class": "KSTLightV2",
        "optimizer_config": {"lr": 1e-4},
        "parameter_count": 999,
    }
    manifest_path = _write_tuning_run(
        tmp_path, tuned, matrix, provider, result, "cpu", tuning_id="h48_lr1e4",
    )
    assert "tuning" in str(manifest_path) and "runs" not in str(manifest_path).split("tuning")[0].split("pilot")[-1]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_level"] == "tuning"
    assert manifest["eligibility"] == "tuning_only"
    assert manifest["evidence_status"] == "full_completed"
    assert manifest["test_evaluation_count"] == 0
    assert manifest["tuning_id"] == "h48_lr1e4"
    assert manifest["best_valid_score"] == 0.4
    assert manifest["matrix_sha256"] == matrix.matrix_sha256
    assert not (manifest_path.parent / "metrics.json").exists()
    assert not (manifest_path.parent / "predictions.json").exists()

    with pytest.raises(ValueError, match="unknown tuning override"):
        _apply_tuning_overrides(spec, {"nonexistent_field": "1"})


def test_prediction_detail_cap_keeps_full_test_metrics(monkeypatch):
    """V2-CH3-SINGLE-T03 review fix: on huge test sets (TEP 710k windows) the
    per-window detail dump is capped to keep the artifact on disk, while the
    top-level metrics stay full-test-set (accumulator over every batch)."""

    import torch
    from kaf_profiti.experiments.pilot_runner import (
        PilotRunSpec,
        _test_prediction_artifact,
    )

    class _MetaProvider:
        num_sensors = 3

        class bundle:  # noqa: N801 - minimal shape for evaluation metadata
            split_info = {}

    class _OnesModel(torch.nn.Module):
        def predict_point(self, batch):
            return batch.y_flat + 1.0

    spec = PilotRunSpec(
        key="k", track="point", matrix_name="m", dataset="d", model_id="li_tcn",
        head_type="linear", family="baseline", condition_id="c",
        missing_mode="mixed", target_missing_rate=0.3, seed=2026,
        split_seed=2026, mask_seed=2026, history_len=8, pred_len=2, stride=1,
        epochs=1, batch_size=4, hidden_dim=4,
    )

    def _loader():
        from kaf_profiti.industrial.batch import IndustrialCollator
        from torch.utils.data import DataLoader

        class _Window(torch.utils.data.Dataset):
            def __init__(self, offset, count):
                self.offset, self.count = offset, count

            def __len__(self):
                return self.count

            def __getitem__(self, index):
                from kaf_profiti.industrial.batch import IndustrialBatch

                base = self.offset + index
                y = torch.full((2, 3), float(base))
                return IndustrialBatch(
                    X_obs=torch.zeros(8, 3), T_obs=torch.arange(8, dtype=torch.float32),
                    M_obs=torch.ones(8, 3), T_q=torch.arange(2, dtype=torch.float32),
                    Y_q=y, M_q=torch.ones_like(y), context=torch.zeros(2),
                    y_flat=y.reshape(-1), mq_flat=torch.ones_like(y.reshape(-1)),
                    query_channel_ids=torch.arange(3).repeat(2),
                    rul=0.0, unit_id=base, window_id=f"w{base}",
                )

        return DataLoader(
            _Window(0, 12), batch_size=4,
            collate_fn=IndustrialCollator(),
        )

    monkeypatch.setenv("KST_PREDICTION_DETAIL_CAP", "5")
    metrics, payload = _test_prediction_artifact(
        _OnesModel(), _loader(), "cpu", spec, _MetaProvider(),
    )
    # detail capped at 5 of 12 windows, flagged truncated
    assert len(payload["window_id"]) == 5
    # identity fields follow the same cap on the point track too
    assert len(payload["T_q"]) == 5 and len(payload["unit_id"]) == 5
    assert payload["detail_truncated"] is True
    assert payload["full_test_windows"] == 12
    # but the top-level metrics cover the FULL 12-window set (MAE == 1.0)
    assert metrics["mae"] == pytest.approx(1.0)
    assert metrics["detail_windows_stored"] == 5
    assert metrics["metrics_basis"] == "full_test_set"

    # with the cap above the set size, behaviour is unchanged (full detail)
    monkeypatch.setenv("KST_PREDICTION_DETAIL_CAP", "100")
    metrics2, payload2 = _test_prediction_artifact(
        _OnesModel(), _loader(), "cpu", spec, _MetaProvider(),
    )
    assert len(payload2["window_id"]) == 12
    assert payload2["detail_truncated"] is False
    assert metrics2["mae"] == pytest.approx(1.0)


def test_trainer_metrics_carry_full_test_basis(monkeypatch):
    """Integration guard: pilot_train_and_evaluate must keep the full-test-set
    globals when the replayable detail is capped (the artifact-level unit test
    alone missed the trainer's re-derivation)."""

    import torch
    from kaf_profiti.experiments.pilot_runner import (
        PilotRunSpec,
        pilot_train_and_evaluate,
    )

    monkeypatch.setenv("KST_PREDICTION_DETAIL_CAP", "3")

    class _MetaProvider:
        num_sensors = 3

        class bundle:  # noqa: N801
            split_info = {}

    class _OnesModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.dummy = torch.nn.Parameter(torch.zeros(1))

        def predict_point(self, batch):
            return batch.y_flat + 1.0

        def loss(self, batch):
            return (batch.y_flat + 1.0 - batch.y_flat).pow(2).mean() + self.dummy * 0.0

    from kaf_profiti.industrial.batch import IndustrialCollator
    from torch.utils.data import DataLoader

    class _Window(torch.utils.data.Dataset):
        def __len__(self):
            return 8

        def __getitem__(self, index):
            from kaf_profiti.industrial.batch import IndustrialBatch

            y = torch.full((2, 3), float(index))
            return IndustrialBatch(
                X_obs=torch.zeros(4, 3), T_obs=torch.arange(4, dtype=torch.float32),
                M_obs=torch.ones(4, 3), T_q=torch.arange(2, dtype=torch.float32),
                Y_q=y, M_q=torch.ones_like(y), context=torch.zeros(2),
                y_flat=y.reshape(-1), mq_flat=torch.ones_like(y.reshape(-1)),
                query_channel_ids=torch.arange(3).repeat(2),
                rul=0.0, unit_id=index, window_id=f"w{index}",
            )

    loader = DataLoader(_Window(), batch_size=4, collate_fn=IndustrialCollator())
    spec = PilotRunSpec(
        key="k", track="point", matrix_name="m", dataset="d", model_id="li_tcn",
        head_type="linear", family="baseline", condition_id="c",
        missing_mode="mixed", target_missing_rate=0.3, seed=2026,
        split_seed=2026, mask_seed=2026, history_len=4, pred_len=2, stride=1,
        epochs=1, batch_size=4, hidden_dim=4,
    )
    result = pilot_train_and_evaluate(
        _OnesModel(), {"train": loader, "valid": loader, "test": loader},
        spec, _MetaProvider(), device="cpu",
    )
    metrics = result["metrics"]
    assert metrics["metrics_basis"] == "full_test_set"
    assert metrics["detail_windows_stored"] == 3
    assert metrics["mae"] == pytest.approx(1.0)     # full 8-window set
    assert metrics["valid_count"] == 8 * 6          # not the 3-window subset


def test_baseline_first_gate_blocks_ours(tmp_path: Path):
    matrix = _matrix()
    keys = _fd001_keys(matrix)

    def failing_baselines(spec, provider, device):
        if spec.family == "baseline":
            raise RuntimeError("baseline exploded")
        return _fake_result(spec)

    summary = _formal_execute_keys(
        matrix, keys, result_root=tmp_path, data_root=tmp_path,
        device="cpu", run_fn=failing_baselines,
        provider_factory=lambda **kwargs: _FakeProvider(**kwargs),
    )
    assert len(summary["failed"]) == 5
    assert len(summary["gate_blocked"]) == 1
    assert "kst_light_v2" in summary["gate_blocked"][0]
    # the ours run was never attempted
    ours_dir = tmp_path / "pilot" / "fd001" / "runs"
    ours_keys = [d.name for d in ours_dir.glob("*kst_light_v2*")] if ours_dir.exists() else []
    assert ours_keys == []


@pytest.mark.skipif(not FD001_PRESENT, reason="FD001 raw data not present")
def test_formal_smoke_real_fd001_li_tcn(tmp_path: Path):
    from run_pilot_matrix import _formal_smoke

    matrix = _matrix()
    keys = [k for k in _fd001_keys(matrix) if k.model_id == "li_tcn"]
    report = _formal_smoke(matrix, keys, result_root=tmp_path, data_root=REPO_ROOT / "dataset",
                           device="cpu")
    entry = report["entries"][0]
    assert entry["model_id"] == "li_tcn"
    assert entry["loss_finite"] is True
    assert entry["params_changed"] is True
    assert entry["valid_point_finite"] is True
    assert entry["test_loader_touched"] is False
    assert report["test_metric_count"] == 0
    # smoke never creates run directories
    assert list((tmp_path / "pilot" / "fd001").glob("runs/*")) == []


def _fabricate_run(root: Path, key, matrix, *, protocol_sha=None, mae=0.25,
                   test_count=1, status="completed"):
    profile = _formal_profile_for(key.protocol)
    run_dir = root / "pilot" / profile / "runs" / key.scientific_key
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "history.json").write_text(json.dumps(
        [{"epoch": 1, "train_loss": 0.5, "valid_score": 0.4}]), encoding="utf-8")
    metrics = {"point": {"mae": mae, "rmse": 0.5, "valid_count": 10}, "probabilistic": {}}
    (run_dir / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    (run_dir / "predictions.json").write_text(json.dumps({"parameter_count": 1234}), encoding="utf-8")
    (run_dir / "checkpoint.pt").write_bytes(b"fake-checkpoint")
    manifest = {
        "status": status,
        "run_id": key.scientific_key,
        "matrix_id": matrix.matrix_id,
        "matrix_sha256": matrix.matrix_sha256,
        "test_evaluation_count": test_count,
        "protocol_sha": protocol_sha or {
            "dataset": key.protocol,
            "split_sha256": f"split-{key.protocol}",
            "normalization_sha256": f"norm-{key.protocol}",
            "mask_sha": {"train": "m1", "valid": "m2", "test": "m3"},
        },
        "parameter_count": 1234,
        "train_seconds": 1.0,
        "inference_time_sec": 0.01,
        "artifacts": {
            "history": "history.json", "metrics": "metrics.json",
            "checkpoint": "checkpoint.pt", "predictions": "predictions.json",
        },
        "artifact_sha256": {},
    }
    import hashlib

    for name, relative in manifest["artifacts"].items():
        manifest["artifact_sha256"][name] = hashlib.sha256(
            (run_dir / relative).read_bytes()
        ).hexdigest()
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_validator_passes_fabricated_fd001_group(tmp_path: Path):
    matrix = _matrix()
    for key in _fd001_keys(matrix):
        _fabricate_run(tmp_path, key, matrix)
    verdict = validate_formal_results(matrix, tmp_path, protocols={"cmapss_fd001"})
    assert verdict["expected"] == 6
    assert verdict["completed"] == 6
    assert verdict["missing"] == [] and verdict["failed"] == []
    assert verdict["fairness_mismatch"] == 0


def test_validator_condition_and_model_filters_scope_expected_keys(tmp_path: Path):
    matrix = _matrix()
    keys = [k for k in _fd001_keys(matrix) if k.family == "baseline"]
    for key in keys:
        _fabricate_run(tmp_path, key, matrix)
    verdict = validate_formal_results(
        matrix, tmp_path, protocols={"cmapss_fd001"},
        condition_ids={"point_mixed_030"}, model_ids={k.model_id for k in keys},
    )
    assert verdict["expected"] == 5
    assert verdict["completed"] == 5
    assert verdict["missing"] == []


def test_validator_flags_missing_fairness_nonfinite_and_test_count(tmp_path: Path):
    matrix = _matrix()
    keys = _fd001_keys(matrix)
    for key in keys:
        _fabricate_run(tmp_path, key, matrix)
    # 1) missing run
    (tmp_path / "pilot" / "fd001" / "runs" / keys[2].scientific_key / "manifest.json").unlink()
    verdict = validate_formal_results(matrix, tmp_path, protocols={"cmapss_fd001"})
    assert verdict["completed"] == 5 and len(verdict["missing"]) == 1

    # restore, then break fairness: one model sees a different split sha
    _fabricate_run(tmp_path, keys[2], matrix)
    drifted = {"dataset": "cmapss_fd001", "split_sha256": "DRIFT",
               "normalization_sha256": "n", "mask_sha": {}}
    _fabricate_run(tmp_path, keys[4], matrix, protocol_sha=drifted)
    verdict = validate_formal_results(matrix, tmp_path, protocols={"cmapss_fd001"})
    assert verdict["fairness_mismatch"] >= 1

    # restore, then non-finite metric
    _fabricate_run(tmp_path, keys[4], matrix)
    _fabricate_run(tmp_path, keys[1], matrix, mae=float("inf"))
    verdict = validate_formal_results(matrix, tmp_path, protocols={"cmapss_fd001"})
    assert verdict["nonfinite"] >= 1

    # restore, then wrong test count
    _fabricate_run(tmp_path, keys[1], matrix)
    _fabricate_run(tmp_path, keys[0], matrix, test_count=0)
    verdict = validate_formal_results(matrix, tmp_path, protocols={"cmapss_fd001"})
    assert verdict["test_count_errors"] >= 1
