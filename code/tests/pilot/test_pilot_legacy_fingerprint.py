"""Resume compatibility for audited historical pilot artifacts."""

import json

import pytest
import yaml

from kaf_profiti.experiments.pilot_runner import (
    LEGACY_CODE_FINGERPRINTS,
    PilotRunner,
    _legacy_fingerprint_allowed,
    load_matrix,
)

LEGACY_S04 = "f44952ed50f6801b092b9a9e6f29d5c34b5519da6a55d24373c7ce2ac41571d1"
LEGACY_T01 = "fdd06602a6f90de74da0c963d8d948d6040a8281f375d0949f1dad02eca6eb8d"


def _matrix(tmp_path, model_id="li_tcn", family="baseline", condition="point_mixed_030", missing="mixed", rate=0.3):
    payload = {
        "matrix_id": "tiny_legacy_point",
        "dataset": "metropt3_chrono_502030_v2",
        "seed": 2026,
        "split_seed": 2026,
        "mask_seed": 2026,
        "history_len": 8,
        "pred_len": 3,
        "stride": 1,
        "epochs": 2,
        "batch_size": 2,
        "hidden_dim": 8,
        "conditions": [
            {"condition_id": condition, "missing_mode": missing, "target_missing_rate": rate},
        ],
        "models": [
            {"model_id": model_id, "head_type": "linear", "family": family, "priority": 1},
        ],
    }
    path = tmp_path / f"{model_id}_{family}_{condition}.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return load_matrix(path)


def _spec(tmp_path, **kwargs):
    return PilotRunner([_matrix(tmp_path, **kwargs)], tmp_path / "result", profile="metropt3").expand()[0]


def test_legacy_fingerprints_are_scoped_not_global(tmp_path):
    """Only the audited fingerprint/run-level/condition combination resumes."""

    mixed_baseline = _spec(tmp_path)
    assert mixed_baseline.condition_id == "point_mixed_030"
    s04_manifest = {
        "code_fingerprint": LEGACY_S04,
        "run_level": "pilot",
        "status": "completed",
        "key": mixed_baseline.key,
        "run_id": mixed_baseline.key,
    }
    assert _legacy_fingerprint_allowed(s04_manifest, mixed_baseline) is True

    # The same legacy fingerprint must not resume a different condition.
    random_spec = _spec(tmp_path, condition="point_random_030", missing="random")
    assert _legacy_fingerprint_allowed(s04_manifest, random_spec) is False

    # T01 fingerprint covers baseline runs on the extension conditions only.
    t01_manifest = dict(s04_manifest, code_fingerprint=LEGACY_T01, key=random_spec.key, run_id=random_spec.key)
    assert _legacy_fingerprint_allowed(t01_manifest, random_spec) is True

    ours_spec = _spec(tmp_path, model_id="kst_light", family="ours", condition="point_random_000", missing="random", rate=0.0)
    ours_manifest = dict(t01_manifest, key=ours_spec.key, run_id=ours_spec.key)
    assert _legacy_fingerprint_allowed(ours_manifest, ours_spec) is False


def test_unknown_fingerprint_is_rejected(tmp_path):
    spec = _spec(tmp_path)
    manifest = {
        "code_fingerprint": "0" * 64,
        "run_level": "pilot",
        "status": "completed",
        "key": spec.key,
        "run_id": spec.key,
    }
    assert _legacy_fingerprint_allowed(manifest, spec) is False
    assert "0" * 64 not in LEGACY_CODE_FINGERPRINTS


def test_legacy_tampering_still_fails_verification(tmp_path):
    """A legacy fingerprint must not bypass identity or artifact checks."""

    runner = PilotRunner([_matrix(tmp_path)], tmp_path / "result", profile="metropt3")
    spec = runner.expand()[0]
    run_dir = tmp_path / "result" / "pilot" / "metropt3" / "runs" / spec.key
    run_dir.mkdir(parents=True)
    artifacts = {
        "history": "history.json",
        "metrics": "metrics.json",
        "checkpoint": "checkpoint.pt",
        "predictions": "predictions.json",
    }
    contents = {
        "history.json": "[]",
        "metrics.json": "{}",
        "checkpoint.pt": "weights",
        "predictions.json": "{}",
    }
    import hashlib

    shas = {}
    for name, relative in artifacts.items():
        (run_dir / relative).write_text(contents[relative], encoding="utf-8")
        shas[name] = hashlib.sha256(contents[relative].encode()).hexdigest()
    manifest = {
        **runner._manifest_identity(spec),
        "run_id": spec.key,
        "status": "completed",
        "test_evaluation_count": 1,
        "shared_artifacts": runner._shared_artifacts(),
        "artifacts": {
            name: str((run_dir / relative).relative_to(tmp_path / "result"))
            for name, relative in artifacts.items()
        },
        "artifact_sha256": shas,
        "checkpoint_sha256": shas["checkpoint"],
        "code_fingerprint": LEGACY_S04,
        "protocol_sha": None,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # Identity tampering must still be rejected despite the audited legacy fingerprint.
    manifest["seed"] = 1999
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert runner._verified_specs([spec], validate_protocol=False) == {}

    # With identity restored the audited legacy artifact verifies.
    manifest["seed"] = spec.seed
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert spec.key in runner._verified_specs([spec], validate_protocol=False)
