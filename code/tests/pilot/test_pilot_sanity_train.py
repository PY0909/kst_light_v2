"""CH34-S03-T02: LI+TCN validation-only learnability sanity trainer contracts."""

import json
import math
import sys
from pathlib import Path

import pytest
import torch
import yaml

from kaf_profiti.experiments.pilot_runner import (
    PilotRunner,
    _persistence_score,
    build_model,
    load_matrix,
    pilot_sanity_train,
)
from kaf_profiti.industrial.batch import IndustrialBatch


def _sanity_matrix(tmp_path, models=None):
    payload = {
        "matrix_id": "tiny_sanity_point",
        "dataset": "metropt3_chrono_502030_v2",
        "seed": 2026,
        "split_seed": 2026,
        "mask_seed": 2026,
        "history_len": 10,
        "pred_len": 3,
        "stride": 1,
        "epochs": 50,
        "batch_size": 4,
        "hidden_dim": 8,
        "conditions": [
            {
                "condition_id": "point_mixed_030",
                "missing_mode": "mixed",
                "target_missing_rate": 0.30,
            },
        ],
        "models": models or [
            {"model_id": "li_tcn", "head_type": "linear", "family": "baseline", "priority": 1},
        ],
    }
    path = tmp_path / "point.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return load_matrix(path)


class _ListLoader:
    def __init__(self, batches):
        self._batches = batches

    def __iter__(self):
        return iter(self._batches)

    def __len__(self):
        return len(self._batches)


def _make_batch(num_sensors, history_len, pred_len, context_dim, batch_size, seed):
    generator = torch.Generator().manual_seed(seed)
    x = torch.randn(batch_size, history_len, num_sensors, generator=generator)
    y = torch.randn(batch_size, pred_len, num_sensors, generator=generator)
    return IndustrialBatch(
        X_obs=x,
        T_obs=torch.arange(history_len, dtype=torch.float32).repeat(batch_size, 1),
        M_obs=torch.ones(batch_size, history_len, num_sensors),
        T_q=torch.arange(1, pred_len + 1, dtype=torch.float32).repeat(batch_size, 1),
        Y_q=y,
        M_q=torch.ones(batch_size, pred_len, num_sensors),
        context=torch.randn(batch_size, context_dim, generator=generator),
        y_flat=y.reshape(batch_size, -1),
        mq_flat=torch.ones(batch_size, pred_len * num_sensors),
        query_channel_ids=torch.arange(num_sensors).repeat(pred_len),
        rul=torch.rand(batch_size, generator=generator) * 100.0,
        unit_id=torch.arange(batch_size),
    )


class _SanityProvider:
    def __init__(self, spec):
        self._spec = spec
        self.num_sensors = 4
        self.context_dim = 3
        self.model_options = {}

    def protocol_fingerprint(self):
        return {
            "mechanism": self._spec.missing_mode,
            "requested_rate": self._spec.target_missing_rate,
            "split_sha256": "s" * 64,
        }

    def loaders(self, batch_size, generator_seed=None):
        spec = self._spec
        return {
            "train": _ListLoader(
                [
                    _make_batch(
                        self.num_sensors, spec.history_len, spec.pred_len,
                        self.context_dim, batch_size, seed=1,
                    ),
                    _make_batch(
                        self.num_sensors, spec.history_len, spec.pred_len,
                        self.context_dim, batch_size, seed=2,
                    ),
                ]
            ),
            "valid": _ListLoader(
                [
                    _make_batch(
                        self.num_sensors, spec.history_len, spec.pred_len,
                        self.context_dim, batch_size, seed=3,
                    )
                ]
            ),
        }


def _factory(spec, data_root, result_root):
    return _SanityProvider(spec)


def _runner(tmp_path):
    return PilotRunner(
        [_sanity_matrix(tmp_path)], tmp_path / "result", profile="metropt3"
    )


def test_persistence_score_uses_masked_query_micro_contract():
    batch = _make_batch(2, 3, 2, 1, 1, seed=11)
    batch.X_obs[:, -1, :] = torch.tensor([[1.0, 2.0]])
    batch.Y_q = torch.tensor([[[1.5, 2.5], [100.0, 200.0]]])
    batch.y_flat = batch.Y_q.reshape(1, -1)
    batch.mq_flat = torch.tensor([[1.0, 1.0, 0.0, 0.0]])
    score = _persistence_score(_ListLoader([batch]), "cpu")

    assert score["metric_space"] == "standardized"
    assert score["aggregation"] == "masked_query_micro"
    assert score["valid_count"] == 2
    assert score["value"] == pytest.approx(0.5)


def test_persistence_score_uses_locf_not_zero_filled_history():
    """A masked last history step must fall back to the last observed value."""

    batch = _make_batch(2, 3, 2, 1, 1, seed=11)
    batch.X_obs = torch.tensor([[[5.0, 6.0], [7.0, 0.0], [0.0, 9.0]]])
    # masks.py zero-fills masked history; channel 0's last step is masked.
    batch.M_obs = torch.tensor([[[1.0, 1.0], [1.0, 1.0], [0.0, 1.0]]])
    batch.Y_q = torch.tensor([[[8.0, 9.0], [7.0, 9.0]]])
    batch.y_flat = batch.Y_q.reshape(1, -1)
    batch.mq_flat = torch.ones(1, 4)
    score = _persistence_score(_ListLoader([batch]), "cpu")

    # LOCF persistence = [7, 9, 7, 9]; zero-filled last row would give [0, 9, 0, 9].
    assert score["valid_count"] == 4
    assert score["value"] == pytest.approx(0.25)
def test_sanity_trainer_runs_validation_only_and_reports_flags(tmp_path):
    """The sanity trainer scores init + N epochs and never loads test."""

    spec = _runner(tmp_path).expand()[0]
    provider = _SanityProvider(spec)
    torch.manual_seed(spec.seed)
    model = build_model(spec, provider.num_sensors, provider.context_dim, {}, device="cpu")
    # No "test" key is ever handed to the trainer.
    loaders = provider.loaders(spec.batch_size)

    outcome = pilot_sanity_train(model, loaders, spec, provider, device="cpu", epochs=5)

    assert outcome["epochs_run"] == 5
    assert len(outcome["history"]) == 6  # epoch 0 baseline + 5 training epochs
    assert outcome["history"][0]["epoch"] == 0
    for flag in ("finite", "updated", "validation_improved"):
        assert isinstance(outcome[flag], bool)
    assert outcome["finite"] is True
    assert math.isfinite(outcome["init_valid_mae"])
    assert math.isfinite(outcome["best_valid_mae"])


def test_run_sanity_train_selects_li_tcn_and_writes_isolated_manifest(tmp_path):
    runner = _runner(tmp_path)
    key = "metropt3_chrono_502030_v2|point|li_tcn|linear|point_mixed_030|2026"

    manifest = runner.run_sanity_train(epochs=3, provider_factory=_factory)

    assert manifest["run_level"] == "sanity_train"
    assert manifest["run_id"] == key
    assert manifest["test_evaluation_count"] == 0
    assert manifest["epochs"] == 50  # configured matrix epochs, untouched
    assert manifest["sanity_epochs"] == 3
    assert manifest["finite"] is True
    assert manifest["updated"] is True
    assert isinstance(manifest["validation_improved"], bool)
    assert manifest["persistence_baseline"]["metric_space"] == "standardized"
    assert manifest["persistence_baseline"]["aggregation"] == "masked_query_micro"
    assert manifest["persistence_baseline"]["valid_count"] > 0
    assert manifest["beat_naive"] is not None

    # Isolated under sanity/, never under runs/.
    sanity_dir = tmp_path / "result" / "pilot" / "metropt3" / "sanity" / key
    runs_dir = tmp_path / "result" / "pilot" / "metropt3" / "runs"
    assert (sanity_dir / "manifest.json").is_file()
    assert (sanity_dir / "history.json").is_file()
    assert not (sanity_dir / "predictions.json").exists()
    assert not (sanity_dir / "checkpoint.pt").exists()
    assert not runs_dir.exists()

    # The manifest must not look like a resumable complete pilot run.
    manifest_on_disk = json.loads((sanity_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_on_disk["run_level"] == "sanity_train"
    assert manifest_on_disk["test_evaluation_count"] == 0


def test_sanity_train_rejects_when_li_tcn_point_mixed_030_missing(tmp_path):
    runner = _runner(tmp_path)
    matrix = _sanity_matrix(tmp_path)
    matrix.raw["models"] = [{"model_id": "gru_d", "head_type": "linear", "family": "baseline", "priority": 1}]
    # Rebuild a runner over a matrix that lacks li_tcn.
    path = tmp_path / "no_li.yaml"
    path.write_text(yaml.safe_dump(matrix.raw), encoding="utf-8")
    runner = PilotRunner([load_matrix(path)], tmp_path / "result", profile="metropt3")

    with pytest.raises(ValueError, match="exactly one li_tcn"):
        runner.run_sanity_train(epochs=2, provider_factory=_factory)


def test_run_sanity_train_selects_requested_model_and_isolates_output(tmp_path):
    """model_id selects the sanity spec; only that model's sanity dir is written."""

    models = [
        {"model_id": "li_tcn", "head_type": "linear", "family": "baseline", "priority": 1},
        {"model_id": "gru_d", "head_type": "linear", "family": "baseline", "priority": 2},
    ]
    runner = PilotRunner(
        [_sanity_matrix(tmp_path, models=models)], tmp_path / "result", profile="metropt3"
    )
    gru_d_key = "metropt3_chrono_502030_v2|point|gru_d|linear|point_mixed_030|2026"
    li_tcn_key = "metropt3_chrono_502030_v2|point|li_tcn|linear|point_mixed_030|2026"

    manifest = runner.run_sanity_train(epochs=2, provider_factory=_factory, model_id="gru_d")

    assert manifest["model_id"] == "gru_d"
    assert manifest["run_id"] == gru_d_key
    assert manifest["sanity_epochs"] == 2
    assert manifest["test_evaluation_count"] == 0
    sanity_root = tmp_path / "result" / "pilot" / "metropt3" / "sanity"
    assert (sanity_root / gru_d_key / "manifest.json").is_file()
    assert (sanity_root / gru_d_key / "history.json").is_file()
    # The default gate model is untouched unless explicitly requested.
    assert not (sanity_root / li_tcn_key).exists()


def test_run_sanity_train_rejects_when_requested_model_missing(tmp_path):
    models = [{"model_id": "li_tcn", "head_type": "linear", "family": "baseline", "priority": 1}]
    runner = PilotRunner(
        [_sanity_matrix(tmp_path, models=models)], tmp_path / "result", profile="metropt3"
    )

    with pytest.raises(ValueError, match="exactly one ode_rnn"):
        runner.run_sanity_train(epochs=2, provider_factory=_factory, model_id="ode_rnn")


def test_cli_sanity_mode_honors_model_ids_and_gate_flags(tmp_path, monkeypatch, capsys):
    """--model-id reaches run_sanity_train per model; a failed gate flag exits 1."""

    import run_pilot_matrix as cli

    calls = []

    class _FakeRunner:
        def __init__(self, **kwargs):
            pass

        def run_sanity_train(self, epochs, model_id):
            calls.append((epochs, model_id))
            return {
                "run_id": f"sanity|{model_id}",
                "finite": True,
                "updated": True,
                # The second model fails the gate on purpose.
                "validation_improved": model_id != "ode_rnn",
            }

    monkeypatch.setattr(cli, "PilotRunner", _FakeRunner)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_pilot_matrix.py", "--profile", "metropt3", "--matrix", "point",
            "--mode", "sanity", "--model-id", "li_tcn", "--model-id", "ode_rnn",
            "--epochs", "5",
        ],
    )

    assert cli.main() == 1
    assert calls == [(5, "li_tcn"), (5, "ode_rnn")]
    printed = capsys.readouterr().out
    assert "sanity|li_tcn" in printed
    assert "sanity|ode_rnn" in printed


def test_naive_floor_reference_reads_data_gate_when_present(tmp_path):
    runner = _runner(tmp_path)
    diagnostics = tmp_path / "result" / "pilot" / "metropt3" / "diagnostics"
    diagnostics.mkdir(parents=True)
    (diagnostics / "data_gate.json").write_text(
        json.dumps(
            {
                "floors": {
                    "valid": {
                        "persistence": {"mae": 0.915894, "std_micro": {"mae": 0.402354}}
                    }
                },
                "learnability_gate": {"result": "pass"},
            }
        ),
        encoding="utf-8",
    )

    reference = runner._naive_floor_reference()

    assert reference["available"] is True
    assert reference["persistence_mae_raw"] == 0.915894
    assert reference["persistence_mae_std_micro"] == 0.402354
