"""CH34-S02-T01: dataset-profile runner contracts and scheduling filters."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from kaf_profiti.experiments.pilot_runner import PilotRunner, load_matrix
from kaf_profiti.experiments import pilot_runner as pilot_runner_module


def _matrix(tmp_path, dataset="metropt3_chrono_502030_v2"):
    payload = {
        "matrix_id": "tiny_point",
        "dataset": dataset,
        "seed": 2026,
        "split_seed": 2026,
        "mask_seed": 2026,
        "history_len": 4,
        "pred_len": 2,
        "stride": 1,
        "epochs": 1,
        "batch_size": 2,
        "hidden_dim": 4,
        "conditions": [
            {"condition_id": "c0", "missing_mode": "random", "target_missing_rate": 0.0},
            {"condition_id": "c1", "missing_mode": "random", "target_missing_rate": 0.3},
        ],
        "models": [
            {"model_id": "li_tcn", "head_type": "linear", "family": "baseline", "priority": 1},
            {"model_id": "kst_light", "head_type": "linear", "family": "ours", "priority": 2},
        ],
    }
    path = tmp_path / "matrix.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return load_matrix(path)


class _Provider:
    num_sensors = 1
    context_dim = 1
    model_options = {}

    def __init__(self, spec, *args, **kwargs):
        self.spec = spec
        self._fingerprint = {
            "dataset": spec.dataset, "mechanism": spec.missing_mode,
            "requested_rate": spec.target_missing_rate,
            "split_sha256": "s" * 64, "normalization_sha256": "n" * 64,
            "mask_sha": {"train": "a" * 64, "valid": "b" * 64, "test": "c" * 64},
        }

    def protocol_fingerprint(self):
        return dict(self._fingerprint)

    def loaders(self, batch_size, **kwargs):
        return {}


def _trainer(model, batches, spec, provider, device="cpu"):
    return {
        "history": [{"epoch": 1}],
        "metrics": {"mae": 1.0},
        "checkpoint_bytes": b"checkpoint",
        "predictions": {"schema_version": 1},
    }


def _factory(spec, data_root, result_root):
    return _Provider(spec)


def _run_dir(runner, key):
    return runner.result_root / runner.pilot_root / "runs" / key


def _manifest(runner, key):
    path = _run_dir(runner, key) / "manifest.json"
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_profile_metropt3_places_artifacts_under_profile_root(tmp_path):
    runner = PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="metropt3")
    summary = runner.execute(trainer=_trainer, gate=False, provider_factory=_factory)
    assert summary["completed_count"] == 4
    assert (tmp_path / "result" / "pilot" / "metropt3" / "runs").is_dir()
    assert not (tmp_path / "result" / "metropt3").exists()


def test_profile_rejects_matrix_dataset_mismatch(tmp_path):
    with pytest.raises(ValueError, match="expects dataset"):
        PilotRunner([_matrix(tmp_path, dataset="cmapss_fd004")], tmp_path / "result", profile="metropt3")


def test_filters_preserve_canonical_keys_and_matrix_sha(tmp_path):
    runner = PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="metropt3")
    canonical = runner.expand()
    report = runner.dry_run(family="baseline", condition_ids=["c0"])
    assert report["keys"] == [canonical[0].key]
    assert report["canonical_total"] == 4
    assert report["shared_artifacts"] == runner.dry_run()["shared_artifacts"]
    with pytest.raises(ValueError, match="unknown condition"):
        runner.dry_run(condition_ids=["unknown"])


def test_gate_is_scoped_to_same_condition_but_baseline_is_canonical(tmp_path):
    runner = PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="metropt3")
    runner.execute(
        trainer=_trainer, gate=False, provider_factory=_factory,
        family="baseline", condition_ids=["c0"],
    )
    ours_c0 = runner.execute(
        trainer=_trainer, provider_factory=_factory,
        family="ours", condition_ids=["c0"],
    )
    assert ours_c0["completed_count"] == 1
    ours_c1 = runner.execute(
        trainer=_trainer, provider_factory=_factory,
        family="ours", condition_ids=["c1"],
    )
    assert ours_c1["completed_count"] == 0
    assert ours_c1["failed"]
    assert "c1" in ours_c1["errors"][ours_c1["failed"][0]]


def test_invalid_profile_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="../escape")


def test_resume_rejects_manifest_copied_from_another_scientific_key(tmp_path):
    runner = PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="metropt3")
    runner.execute(trainer=_trainer, gate=False, provider_factory=_factory)
    baseline_specs = [spec for spec in runner.expand() if spec.family == "baseline"]
    target, source = baseline_specs
    shutil.rmtree(_run_dir(runner, target.key))
    shutil.copytree(_run_dir(runner, source.key), _run_dir(runner, target.key))

    verified = runner._verified_specs(
        [target], provider_factory=_factory, validate_protocol=True
    )
    assert target.key not in verified


def test_resume_checks_every_manifest_identity_field(tmp_path):
    runner = PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="metropt3")
    runner.execute(
        trainer=_trainer, gate=False, provider_factory=_factory,
        family="baseline", condition_ids=["c0"],
    )
    spec = next(
        spec for spec in runner.expand()
        if spec.family == "baseline" and spec.condition_id == "c0"
    )
    path, original = _manifest(runner, spec.key)
    replacements = {
        "key": "foreign-key",
        "run_level": "smoke",
        "matrix": "foreign-matrix",
        "track": "probabilistic",
        "model_id": "gru_d",
        "head_type": "mlp",
        "family": "ours",
        "condition_id": "c1",
        "missing_mode": "block",
        "target_missing_rate": 0.7,
        "seed": 2027,
        "split_seed": 2027,
        "mask_seed": 2027,
        "dataset": "cmapss_fd004",
    }
    for field, replacement in replacements.items():
        tampered = dict(original)
        tampered[field] = replacement
        path.write_text(json.dumps(tampered), encoding="utf-8")
        assert spec.key not in runner._verified_specs(
            [spec], provider_factory=_factory, validate_protocol=True
        ), field
    path.write_text(json.dumps(original), encoding="utf-8")


@pytest.mark.parametrize("sha_mode", ["missing", "partial"])
def test_resume_requires_sha_for_every_listed_artifact(tmp_path, sha_mode):
    runner = PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="metropt3")
    runner.execute(
        trainer=_trainer, gate=False, provider_factory=_factory,
        family="baseline", condition_ids=["c0"],
    )
    spec = next(spec for spec in runner.expand() if spec.family == "baseline" and spec.condition_id == "c0")
    path, manifest = _manifest(runner, spec.key)
    if sha_mode == "missing":
        manifest["artifact_sha256"] = {}
    else:
        manifest["artifact_sha256"] = {
            "checkpoint": manifest["artifact_sha256"]["checkpoint"]
        }
    path.write_text(json.dumps(manifest), encoding="utf-8")

    assert spec.key not in runner._verified_specs(
        [spec], provider_factory=_factory, validate_protocol=True
    )


def test_resume_requires_prediction_artifact(tmp_path):
    runner = PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="metropt3")
    runner.execute(
        trainer=_trainer, gate=False, provider_factory=_factory,
        family="baseline", condition_ids=["c0"],
    )
    spec = next(
        spec for spec in runner.expand()
        if spec.family == "baseline" and spec.condition_id == "c0"
    )
    path, manifest = _manifest(runner, spec.key)
    manifest["artifacts"].pop("predictions")
    manifest["artifact_sha256"].pop("predictions")
    path.write_text(json.dumps(manifest), encoding="utf-8")

    assert spec.key not in runner._verified_specs(
        [spec], provider_factory=_factory, validate_protocol=True
    )


@pytest.mark.parametrize("escaped", ["/tmp/outside.json", "../outside.json"])
def test_resume_rejects_artifact_paths_outside_result_root(tmp_path, escaped):
    runner = PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="metropt3")
    runner.execute(
        trainer=_trainer, gate=False, provider_factory=_factory,
        family="baseline", condition_ids=["c0"],
    )
    spec = next(spec for spec in runner.expand() if spec.family == "baseline" and spec.condition_id == "c0")
    path, manifest = _manifest(runner, spec.key)
    manifest["artifacts"]["metrics"] = escaped
    path.write_text(json.dumps(manifest), encoding="utf-8")

    assert spec.key not in runner._verified_specs(
        [spec], provider_factory=_factory, validate_protocol=True
    )


def test_completed_baseline_without_checkpoint_does_not_unlock_ours(tmp_path):
    runner = PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="metropt3")

    def no_checkpoint(model, batches, spec, provider, device="cpu"):
        return {
            "history": [], "metrics": {"mae": 1.0},
            "checkpoint_bytes": b"", "predictions": {"schema_version": 1},
        }

    summary = runner.execute(
        trainer=no_checkpoint, provider_factory=_factory, condition_ids=["c0"]
    )
    ours_key = next(
        spec.key for spec in runner.expand()
        if spec.family == "ours" and spec.condition_id == "c0"
    )
    assert ours_key in summary["failed"]
    assert "baseline-first gate blocked" in summary["errors"][ours_key]


def test_dry_run_and_execute_use_same_protocol_verification(tmp_path):
    runner = PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="metropt3")
    runner.execute(
        trainer=_trainer, gate=False, provider_factory=_factory,
        family="baseline", condition_ids=["c0"],
    )

    def drifted_factory(spec, data_root, result_root, **kwargs):
        provider = _Provider(spec)
        provider._fingerprint["split_sha256"] = "x" * 64
        return provider

    report = runner.dry_run(
        family="baseline", condition_ids=["c0"], provider_factory=drifted_factory
    )
    summary = runner.execute(
        trainer=_trainer, gate=False, provider_factory=drifted_factory,
        family="baseline", condition_ids=["c0"],
    )
    assert report["verified_complete"] == 0
    assert report["expected_new"] == 1
    assert summary["completed_count"] == 1
    assert summary["skipped"] == 0


def test_provider_adapter_with_fingerprint_never_disables_protocol_validation(tmp_path):
    runner = PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="metropt3")
    first = runner.execute(
        trainer=_trainer, gate=False, provider_factory=_factory,
        family="baseline", condition_ids=["c0"],
    )
    assert first["completed_count"] == 1
    spec = next(spec for spec in runner.expand() if spec.family == "baseline" and spec.condition_id == "c0")
    path, manifest = _manifest(runner, spec.key)
    manifest["protocol_sha"]["split_sha256"] = "z" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")

    second = runner.execute(
        trainer=_trainer, gate=False, provider_factory=_factory,
        family="baseline", condition_ids=["c0"],
    )
    assert second["completed_count"] == 1
    assert second["skipped"] == 0


def test_force_rerun_reports_verified_runs_as_rerun_not_skipped(tmp_path):
    runner = PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="metropt3")
    runner.execute(trainer=_trainer, gate=False, provider_factory=_factory)
    summary = runner.execute(
        trainer=_trainer, gate=False, provider_factory=_factory, force_rerun=True
    )
    assert summary["completed_count"] == 4
    assert summary["skipped"] == 0
    assert summary["rerun_verified"] == 4


def test_kwargs_provider_factory_receives_profile_root_and_is_cached_per_condition(tmp_path):
    calls = []

    def kwargs_factory(spec, data_root, result_root, **kwargs):
        calls.append((spec.condition_id, kwargs.get("pilot_root")))
        return _Provider(spec)

    runner = PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="metropt3")
    summary = runner.execute(
        trainer=_trainer, gate=False, provider_factory=kwargs_factory
    )
    assert summary["completed_count"] == 4
    assert calls == [("c0", "pilot/metropt3"), ("c1", "pilot/metropt3")]


def test_empty_smoke_group_is_rejected_without_overwriting_report(tmp_path):
    runner = PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="metropt3")
    report_path = tmp_path / "result" / "pilot" / "metropt3" / "smoke" / "probabilistic_baselines_smoke.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text('{"sentinel": true}', encoding="utf-8")
    with pytest.raises(ValueError, match="no models"):
        runner.run_smoke("probabilistic_baselines")
    assert json.loads(report_path.read_text(encoding="utf-8")) == {"sentinel": True}


def test_smoke_provider_uses_a_condition_from_the_matrix(monkeypatch, tmp_path):
    captured = {}

    class CapturingProvider:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(pilot_runner_module, "RealProtocolProvider", CapturingProvider)
    runner = PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="metropt3")
    spec = runner._smoke_models("point_baselines")[0]
    pilot_runner_module._build_smoke_provider(
        spec, runner.data_root, runner.result_root, pilot_root=runner.pilot_root
    )
    assert captured["mechanism"] == spec.missing_mode
    assert captured["requested_rate"] == spec.target_missing_rate


def test_smoke_prefers_real_central_condition_when_matrix_defines_it(tmp_path):
    matrix = _matrix(tmp_path)
    matrix.raw["conditions"].append(
        {"condition_id": "center", "missing_mode": "mixed", "target_missing_rate": 0.3}
    )
    runner = PilotRunner([matrix], tmp_path / "result", profile="metropt3")
    selected = runner._smoke_models("point_baselines")
    assert len(selected) == 1
    assert selected[0].condition_id == "center"


def test_cli_reuses_runner_profile_and_smoke_group_sources():
    import run_pilot_matrix as cli

    assert cli.PROFILE_DATASETS is pilot_runner_module.PROFILE_DATASETS
    assert cli.SMOKE_GROUPS is pilot_runner_module.SMOKE_GROUPS


def test_code_fingerprint_reuses_content_hashes_until_source_metadata_changes(
    monkeypatch, tmp_path
):
    source = tmp_path / "code" / "module.py"
    source.parent.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    pilot_runner_module._CODE_FINGERPRINT_CACHE.clear()
    real_sha = pilot_runner_module._sha256_file
    calls = []

    def recording_sha(path):
        calls.append(path)
        return real_sha(path)

    monkeypatch.setattr(pilot_runner_module, "_sha256_file", recording_sha)
    first = pilot_runner_module._code_fingerprint(tmp_path)
    second = pilot_runner_module._code_fingerprint(tmp_path)
    assert first == second
    assert calls == [source]

    source.write_text("value = 200\n", encoding="utf-8")
    third = pilot_runner_module._code_fingerprint(tmp_path)
    assert third != first
    assert calls == [source, source]
