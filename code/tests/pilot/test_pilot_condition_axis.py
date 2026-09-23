"""Condition-axis regression guards (P04 invalid-run review, 2026-09-14).

The first 42 point pilot runs were invalidated because two defects made the
six missingness conditions indistinguishable in the data: the full-run
provider factory hardcoded the smoke constants (mixed@0.30) instead of the
spec's condition. Artificial missingness belongs only to history inputs;
therefore ``M_q`` must remain the base dataset query mask in every condition.
These tests pin both contracts, add a runtime mismatch guard in ``execute()``,
require manifests to record the protocol SHA, and verify on the real FD004
protocol that conditions produce distinct history masks while retaining the
same query targets and valid-query count.
"""

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pytest
import torch
import yaml

from kaf_profiti.experiments import pilot_runner
from kaf_profiti.experiments.masks import (
    TimelineMaskBundle,
    TimelineMaskConfig,
    TimelineMaskedWindowDataset,
)
from kaf_profiti.experiments.pilot_runner import (
    PilotRunner,
    _build_provider,
    _build_smoke_provider,
    load_matrix,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_POINT_MATRIX = _REPO_ROOT / "configs" / "pilot" / "fd004" / "point_matrix.yaml"
_DATA_ROOT = Path(os.environ.get("KST_DATA_ROOT", _REPO_ROOT / "dataset"))
_FD004_READY = (_DATA_ROOT / "CMAPSSData" / "train_FD004.txt").exists()

_requires_fd004 = pytest.mark.skipif(
    not _FD004_READY, reason="FD004 raw files not available under KST_DATA_ROOT"
)


def _tiny_matrix(tmp_path: Path) -> Path:
    base = yaml.safe_load(_POINT_MATRIX.read_text(encoding="utf-8"))
    base["models"] = [
        {"model_id": "li_tcn", "head_type": "linear", "family": "baseline", "priority": 1},
        {"model_id": "kst_light", "head_type": "linear", "family": "ours", "priority": 2},
    ]
    base["conditions"] = base["conditions"][:2]  # random@0.00, random@0.30
    path = tmp_path / "point.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Provider factory wiring: full and smoke runs follow their selected specs.
# ---------------------------------------------------------------------------


def _record_factory(monkeypatch):
    recorded = {}

    class Recorder:
        def __init__(self, **kwargs):
            recorded.update(kwargs)

    monkeypatch.setattr(pilot_runner, "RealProtocolProvider", Recorder)
    return recorded


def test_full_run_provider_uses_spec_condition(monkeypatch, tmp_path):
    recorded = _record_factory(monkeypatch)
    matrix = load_matrix(_tiny_matrix(tmp_path))
    spec = PilotRunner(
        matrices=[matrix], result_root=tmp_path / "result"
    ).expand()[0]  # li_tcn @ point_random_000

    assert spec.missing_mode == "random" and spec.target_missing_rate == 0.0
    _build_provider(spec, tmp_path / "dataset", tmp_path / "result")

    assert recorded["mechanism"] == spec.missing_mode
    assert recorded["requested_rate"] == spec.target_missing_rate


def test_smoke_provider_uses_selected_matrix_condition(monkeypatch, tmp_path):
    recorded = _record_factory(monkeypatch)
    matrix = load_matrix(_tiny_matrix(tmp_path))
    spec = PilotRunner(matrices=[matrix], result_root=tmp_path / "result").expand()[0]

    _build_smoke_provider(spec, tmp_path / "dataset", tmp_path / "result")

    assert recorded["mechanism"] == spec.missing_mode
    assert recorded["requested_rate"] == spec.target_missing_rate


# ---------------------------------------------------------------------------
# Input-only masking: the timeline mask must not change query targets
# ---------------------------------------------------------------------------


@dataclass
class _Sample:
    X_obs: torch.Tensor
    T_obs: torch.Tensor
    M_obs: torch.Tensor
    T_q: torch.Tensor
    Y_q: torch.Tensor
    M_q: torch.Tensor
    context: torch.Tensor
    rul: float
    unit_id: int


class _WindowDataset:
    history_len = 4
    pred_len = 2
    num_sensors = 3

    def __init__(self, timeline_rows: int):
        self._timeline_rows = timeline_rows
        span = self.history_len + self.pred_len
        self.windows = [(1, start) for start in range(timeline_rows - span + 1)]
        self._units = {1: [0] * timeline_rows}

    def __len__(self):
        return len(self.windows)

    def __getitem__(self, index: int) -> _Sample:
        unit, start = self.windows[index]
        h, p, n = self.history_len, self.pred_len, self.num_sensors
        return _Sample(
            X_obs=torch.ones(h, n),
            T_obs=torch.arange(h, dtype=torch.float32),
            M_obs=torch.ones(h, n),
            T_q=torch.arange(p, dtype=torch.float32),
            Y_q=torch.full((p, n), 7.0),
            M_q=torch.ones(p, n),
            context=torch.zeros(n),
            rul=1.0,
            unit_id=unit,
        )


def _bundle(timeline: np.ndarray) -> TimelineMaskBundle:
    return TimelineMaskBundle(
        config=TimelineMaskConfig(
            dataset="synthetic",
            split="test",
            mechanism="random",
            requested_rate=0.5,
            mask_seed=2026,
            source_split_sha256="0" * 64,
        ),
        masks={1: timeline.astype(np.uint8)},
        path=Path("synthetic.npz"),
        content_sha256="0" * 64,
        realized_rate=float((timeline == 0).mean()),
        calibration={},
    )


def test_timeline_dataset_masks_history_and_preserves_query_contract(tmp_path):
    timeline = np.array(
        [
            [1, 1, 1],
            [0, 1, 1],
            [1, 0, 1],
            [1, 1, 0],
            [0, 0, 1],
            [1, 0, 0],
            [0, 1, 1],
            [1, 1, 1],
        ]
    )
    inner = _WindowDataset(len(timeline))
    dataset = TimelineMaskedWindowDataset(inner, _bundle(timeline))
    assert len(dataset) == 3  # 8 rows - (history 4 + pred 2) + 1

    sample = dataset[0]
    assert torch.equal(sample.M_obs, torch.tensor(timeline[0:4], dtype=torch.float32))
    assert torch.equal(sample.X_obs, torch.ones(4, 3) * sample.M_obs)
    assert torch.equal(sample.M_q, inner[0].M_q), "artificial missingness must not alter M_q"
    assert torch.equal(sample.Y_q, inner[0].Y_q), "artificial missingness must not alter Y_q"

    sample2 = dataset[2]  # start=2: only history rows 2..5 are masked
    assert torch.equal(sample2.M_obs, torch.tensor(timeline[2:6], dtype=torch.float32))
    assert torch.equal(sample2.M_q, inner[2].M_q)
    assert torch.equal(sample2.Y_q, inner[2].Y_q)


# ---------------------------------------------------------------------------
# Runtime guard + manifest provenance
# ---------------------------------------------------------------------------


class _FingerprintProvider:
    num_sensors = 4
    context_dim = 3
    model_options = {}

    def __init__(self, mechanism: str, rate: float):
        self._fingerprint = {
            "mechanism": mechanism,
            "requested_rate": rate,
            "mask_seed": 2026,
            "split_seed": 2026,
            "split_sha256": "s" * 64,
            "normalization_sha256": "n" * 64,
            "mask_sha": {"train": "a" * 64, "valid": "b" * 64, "test": "c" * 64},
        }

    def loaders(self, batch_size):
        return {}

    def protocol_fingerprint(self):
        return dict(self._fingerprint)


def _ok_trainer(model, batches, spec, provider, device="cpu"):
    return {
        "history": [{"epoch": 1}],
        "metrics": {"mae": 0.5, "rmse": 0.7, "test_metric_count": 1},
        "checkpoint_bytes": b"checkpoint",
        "predictions": {"mean": [1.0]},
    }


def test_execute_rejects_provider_condition_mismatch(tmp_path):
    matrix = load_matrix(_tiny_matrix(tmp_path))
    runner = PilotRunner(
        matrices=[matrix], result_root=tmp_path / "result", data_root=tmp_path / "dataset"
    )
    # Spec condition is random@0.00; the provider claims mixed@0.30 (the
    # exact defect that invalidated the first 42 runs).
    summary = runner.execute(
        trainer=_ok_trainer,
        gate=False,
        provider_factory=lambda spec, data_root, result_root: _FingerprintProvider(
            "mixed", 0.30
        ),
    )

    assert summary["completed_count"] == 0
    assert summary["failed"]
    assert all("condition mismatch" in error for error in summary["errors"].values())


def test_manifest_records_protocol_sha(tmp_path):
    matrix = load_matrix(_tiny_matrix(tmp_path))
    runner = PilotRunner(
        matrices=[matrix], result_root=tmp_path / "result", data_root=tmp_path / "dataset"
    )
    summary = runner.execute(
        trainer=_ok_trainer,
        gate=False,
        provider_factory=lambda spec, data_root, result_root: _FingerprintProvider(
            spec.missing_mode, spec.target_missing_rate
        ),
    )
    assert summary["completed_count"] == 4 and not summary["failed"]

    for spec in runner.expand():
        manifest = json.loads(
            (
                tmp_path / "result" / "pilot" / "fd004" / "runs" / spec.key / "manifest.json"
            ).read_text(encoding="utf-8")
        )
        assert manifest["protocol_sha"]["mechanism"] == spec.missing_mode
        assert manifest["protocol_sha"]["requested_rate"] == spec.target_missing_rate
        assert manifest["protocol_sha"]["mask_sha"]["test"] == "c" * 64
        assert manifest["run_id"] == spec.key
        assert manifest["test_evaluation_count"] == 1
        assert "predictions" in manifest["artifacts"]


# ---------------------------------------------------------------------------
# Real-protocol guard: distinct conditions must differ in history inputs only
# ---------------------------------------------------------------------------


@_requires_fd004
def test_real_matrix_conditions_produce_distinct_protocols(tmp_path):
    conditions = (
        "point_random_000",
        "point_random_030",
        "point_random_070",
        "point_low_rate_030",
    )
    runner = PilotRunner(
        matrices=[load_matrix(_POINT_MATRIX)],
        result_root=tmp_path / "result",
        data_root=_DATA_ROOT,
    )
    specs = {spec.condition_id: spec for spec in runner.expand()}

    providers, shas = {}, {}
    for condition_id in conditions:
        spec = specs[condition_id]
        provider = _build_provider(spec, _DATA_ROOT, tmp_path / "result")
        fingerprint = provider.protocol_fingerprint()
        assert fingerprint["mechanism"] == spec.missing_mode, condition_id
        assert abs(fingerprint["requested_rate"] - spec.target_missing_rate) < 1e-9
        providers[condition_id] = provider
        shas[condition_id] = fingerprint["mask_sha"]["test"]
    assert len(set(shas.values())) == len(conditions), "conditions must not share a bundle"

    history_observation_fractions = {}
    query_mask_sha = None
    for condition_id, provider in providers.items():
        dataset = provider.datasets()["test"]
        bundle = dataset.bundle.masks
        step = max(1, len(dataset) // 40)
        observed = total = 0
        for index in range(0, len(dataset), step):
            sample = dataset[index]
            unit, start = dataset.dataset.windows[index]
            expected_history = bundle[int(unit)][start : start + dataset.history_len]
            assert torch.equal(
                sample.M_obs, torch.tensor(expected_history, dtype=torch.float32)
            ), (condition_id, index)
            base_sample = dataset.dataset[index]
            assert torch.equal(sample.M_q, base_sample.M_q), (condition_id, index)
            assert torch.equal(sample.Y_q, base_sample.Y_q), (condition_id, index)
            mask_bytes = sample.M_q.detach().cpu().numpy().tobytes()
            if query_mask_sha is None:
                query_mask_sha = mask_bytes
            else:
                assert mask_bytes == query_mask_sha, "query mask must be shared across conditions"
            observed += int(sample.M_obs.sum())
            total += sample.M_obs.numel()
        history_observation_fractions[condition_id] = observed / total

    assert history_observation_fractions["point_random_000"] == 1.0
    assert history_observation_fractions["point_random_030"] > history_observation_fractions["point_random_070"]
    assert 0.55 < history_observation_fractions["point_random_030"] < 0.80
    assert 0.15 < history_observation_fractions["point_random_070"] < 0.45
