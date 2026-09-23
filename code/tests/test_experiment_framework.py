import json
import os
from pathlib import Path

import numpy as np
import pytest
import torch

import run_experiment as run_experiment_module
from kaf_profiti.experiments.datasets import create_protocol_datasets
from kaf_profiti.experiments.masks import MaskedWindowDataset, generate_or_load_masks
from kaf_profiti.experiments.metrics import expected_calibration_error, safe_binary_metrics
from kaf_profiti.experiments.registry import create_model, get_model_spec, list_model_specs
from kaf_profiti.experiments.tables import build_tables
from run_experiment import ExperimentConfig, run_experiment
from evaluate_risk_calibration import (
    build_risk_calibration_strategies,
    fit_platt_calibrator,
    normal_quantile_threshold,
)


DATA_ROOT = Path(os.environ.get("KST_DATA_ROOT", "/root/autodl-tmp/dataset"))


def test_binary_risk_metrics_ignore_non_finite_scores():
    labels = np.array([0, 1, 0, 1, 1])
    scores = np.array([0.1, np.nan, 0.2, np.inf, 0.9])

    metrics = safe_binary_metrics(labels, scores)
    ece = expected_calibration_error(labels, scores)

    assert metrics["auroc"] is not None
    assert metrics["auprc"] is not None
    assert metrics["f1"] is not None
    assert np.isfinite(ece)


def test_binary_risk_metrics_report_inverted_orientation():
    labels = np.array([0, 0, 1, 1])
    scores = np.array([0.9, 0.8, 0.2, 0.1])

    metrics = safe_binary_metrics(labels, scores)

    assert metrics["auroc"] == pytest.approx(0.0)
    assert metrics["auroc_inverse"] == pytest.approx(1.0)
    assert metrics["risk_orientation"] == "direct"
    assert metrics["risk_orientation_selection"] == "disabled"
    assert metrics["risk_inverse_would_help"]
    assert metrics["selected_auroc"] == pytest.approx(0.0)

    selected = safe_binary_metrics(labels, scores, allow_orientation_selection=True)

    assert selected["risk_orientation"] == "inverted"
    assert selected["risk_orientation_selection"] == "enabled"
    assert selected["selected_auroc"] == pytest.approx(1.0)
    assert selected["best_f1"] == pytest.approx(1.0)
    assert selected["best_f1_threshold"] == pytest.approx(0.8)


def test_risk_calibration_uses_validation_scores_without_test_selection():
    labels = np.zeros(4, dtype=np.float32)
    scores = np.array([0.80, 0.85, 0.90, 0.95], dtype=np.float32)

    calibration = run_experiment_module._fit_risk_calibration(
        labels,
        scores,
        quantile=0.75,
    )

    assert calibration["risk_calibration_source"] == "validation_normal_quantile"
    assert calibration["risk_orientation"] == "inverted"
    assert calibration["risk_threshold"] == pytest.approx(0.1625)


def test_risk_calibration_defaults_to_alarm_budget_when_validation_has_two_classes():
    labels = np.array([0, 0, 0, 1, 1], dtype=np.float32)
    scores = np.array([0.10, 0.20, 0.60, 0.70, 0.95], dtype=np.float32)

    calibration = run_experiment_module._fit_risk_calibration(
        labels,
        scores,
        quantile=0.5,
    )

    assert calibration["risk_calibration_source"] == "validation_normal_quantile"
    assert calibration["risk_threshold_source"] == "validation_normal_quantile"
    assert calibration["risk_threshold"] == pytest.approx(0.20)
    assert calibration["risk_alarm_budget"] == pytest.approx(0.5)


def test_conformal_qhat_is_nonnegative_and_validation_only():
    y = np.array([0.0, 1.0, 2.0, 3.0])
    lower = np.array([-1.0, 0.5, 2.5, 2.7])
    upper = np.array([0.5, 1.5, 3.0, 2.8])
    mask = np.ones_like(y)

    qhat = run_experiment_module._fit_conformal_qhat(y, lower, upper, mask, alpha=0.25)

    assert qhat >= 0.0
    assert qhat == pytest.approx(0.5)


def test_normal_quantile_threshold_uses_validation_normal_scores_only():
    labels = np.array([0, 0, 0, 1, 1], dtype=np.float32)
    scores = np.array([0.10, 0.20, 0.60, 0.70, 0.95], dtype=np.float32)

    threshold = normal_quantile_threshold(labels, scores, quantile=0.5)

    assert threshold == pytest.approx(0.20)


def test_risk_calibration_strategies_are_validation_only_and_finite():
    valid_labels = np.array([0, 0, 0, 1, 1, 1], dtype=np.float32)
    valid_scores = np.array([0.05, 0.10, 0.20, 0.45, 0.70, 0.90], dtype=np.float32)
    test_labels = np.array([0, 1, 1], dtype=np.float32)
    test_scores = np.array([0.15, 0.40, 0.80], dtype=np.float32)

    platt = fit_platt_calibrator(valid_labels, valid_scores)
    strategies = build_risk_calibration_strategies(
        valid_labels,
        valid_scores,
        test_labels,
        test_scores,
    )

    assert np.isfinite(platt.transform(test_scores)).all()
    assert {item["strategy"] for item in strategies} >= {
        "raw_validation_best_f1",
        "raw_validation_normal_q90",
        "raw_validation_normal_q95",
        "platt_validation_best_f1",
        "platt_validation_normal_q95",
    }
    assert all(not item["uses_test_labels_for_threshold"] for item in strategies)
    assert all(item["threshold_source"] == "validation" for item in strategies)


def test_prediction_writer_streams_npy_arrays(tmp_path):
    writer = run_experiment_module.PredictionNpyWriter(
        tmp_path,
        seed=2026,
        total_examples=3,
        nsamples=2,
        query_count=4,
    )
    writer.write(
        mean=np.ones((2, 4), dtype=np.float32),
        samples=np.ones((2, 2, 4), dtype=np.float32),
        risk=np.array([0.1, 0.2], dtype=np.float32),
    )
    writer.write(
        mean=np.zeros((1, 4), dtype=np.float32),
        samples=np.zeros((1, 2, 4), dtype=np.float32),
        risk=np.array([0.3], dtype=np.float32),
    )
    writer.close()

    mean = np.load(tmp_path / "mean_seed2026.npy", mmap_mode="r")
    samples = np.load(tmp_path / "samples_seed2026.npy", mmap_mode="r")
    risk = np.load(tmp_path / "risk_seed2026.npy", mmap_mode="r")

    assert mean.shape == (3, 4)
    assert samples.shape == (3, 2, 4)
    assert risk.shape == (3,)
    assert float(risk[-1]) == pytest.approx(0.3)


def test_prediction_writer_fixed_suffix_and_finite_guard(tmp_path):
    writer = run_experiment_module.PredictionNpyWriter(
        tmp_path,
        seed=2026,
        total_examples=1,
        nsamples=2,
        query_count=3,
        suffix="_fixed",
    )
    writer.write(
        mean=np.array([[1.0, np.nan, np.inf]], dtype=np.float32),
        samples=np.array([[[1.0, np.nan, 3.0], [np.inf, -np.inf, 6.0]]], dtype=np.float32),
        risk=np.array([np.nan], dtype=np.float32),
    )
    writer.close()

    mean = np.load(tmp_path / "mean_seed2026_fixed.npy")
    samples = np.load(tmp_path / "samples_seed2026_fixed.npy")
    risk = np.load(tmp_path / "risk_seed2026_fixed.npy")

    assert np.isfinite(mean).all()
    assert np.isfinite(samples).all()
    assert np.isfinite(risk).all()


def test_registry_enables_only_kaf_profiti_joint():
    specs = {spec.name: spec for spec in list_model_specs()}

    assert specs["kaf_profiti_joint"].status == "enabled"
    assert specs["kst_probflow"].status == "enabled"
    # CH2.5-P02 lifted the probabilistic baselines to pilot_ready; pilot-ready
    # models are constructed through the baseline factories, never through
    # create_model, which still gates on status == "enabled".
    assert specs["tcn_gaussian"].status == "pilot_ready"
    assert specs["patchtst_gaussian"].status == "pilot_ready"
    assert get_model_spec("kaf_profiti_joint").display_name == "KAFNet + ProFITi Joint Flow"
    with pytest.raises(NotImplementedError):
        create_model("tcn_gaussian", num_sensors=15, context_dim=3, device="cpu")


def test_protocol_splits_match_metropt_and_cmapss_rules():
    metro = create_protocol_datasets(
        "metropt3",
        DATA_ROOT,
        seed=2026,
        history_len=12,
        pred_len=3,
        stride=50_000,
        async_mode="none",
    )
    cmapss = create_protocol_datasets(
        "cmapss_fd001",
        DATA_ROOT,
        seed=2026,
        history_len=30,
        pred_len=5,
        stride=50,
        async_mode="none",
    )

    assert metro.split_info["split_rule"] == "first_month_80_20_then_remaining_months"
    assert metro.split_info["train_end"] <= "2020-02-24T00:00:00"
    assert metro.split_info["test_start"] == "2020-03-01T00:00:00"
    assert len(metro.train) > 0 and len(metro.valid) > 0 and len(metro.test) > 0
    train_units = set(cmapss.split_info["train_engine_ids"])
    valid_units = set(cmapss.split_info["valid_engine_ids"])
    assert cmapss.split_info["split_rule"] == "engine_id_80_20_official_test"
    assert train_units
    assert valid_units
    assert train_units.isdisjoint(valid_units)


def test_metropt_chrono_602020_split_is_time_ordered_and_isolated():
    metro = create_protocol_datasets(
        "metropt3_chrono_602020",
        DATA_ROOT,
        seed=2026,
        history_len=12,
        pred_len=3,
        stride=50_000,
        async_mode="none",
    )
    split = metro.split_info
    total_rows = split["train_rows"] + split["valid_rows"] + split["test_rows"]

    assert split["split_rule"] == "chronological_60_20_20_no_overlap"
    assert split["normalization_source"] == "train_only"
    assert split["window_cross_boundary"] is False
    assert split["row_ratios"] == [0.6, 0.2, 0.2]
    assert split["train_end"] < split["valid_start"]
    assert split["valid_end"] < split["test_start"]
    assert split["train_rows"] / total_rows == pytest.approx(0.6, rel=1e-3)
    assert split["valid_rows"] / total_rows == pytest.approx(0.2, rel=1e-3)
    assert split["test_rows"] / total_rows == pytest.approx(0.2, rel=1e-3)
    assert len(metro.train) > 0 and len(metro.valid) > 0 and len(metro.test) > 0


def test_metropt_chrono_502030_split_keeps_fault_positive_test_windows():
    metro = create_protocol_datasets(
        "metropt3_chrono_502030",
        DATA_ROOT,
        seed=2026,
        history_len=12,
        pred_len=3,
        stride=50_000,
        async_mode="none",
    )
    split = metro.split_info
    total_rows = split["train_rows"] + split["valid_rows"] + split["test_rows"]

    assert split["split_rule"] == "chronological_50_20_30_fault_evaluable_no_overlap"
    assert split["normalization_source"] == "train_only"
    assert split["window_cross_boundary"] is False
    assert split["row_ratios"] == [0.5, 0.2, 0.3]
    assert split["train_end"] < split["valid_start"]
    assert split["valid_end"] < split["test_start"]
    assert split["train_rows"] / total_rows == pytest.approx(0.5, rel=1e-3)
    assert split["valid_rows"] / total_rows == pytest.approx(0.2, rel=1e-3)
    assert split["test_rows"] / total_rows == pytest.approx(0.3, rel=1e-3)
    assert split["valid_fault_rows"] > 0
    assert split["test_fault_rows"] > 0
    assert split["test_has_two_risk_classes"] is True


def test_metropt_protocol_normalization_does_not_explode_constant_train_channels():
    metro = create_protocol_datasets(
        "metropt3",
        DATA_ROOT,
        seed=2026,
        history_len=12,
        pred_len=3,
        stride=50_000,
        async_mode="none",
    )

    sample = metro.test[0]

    assert torch.isfinite(sample.X_obs).all()
    assert torch.isfinite(sample.Y_q).all()
    assert sample.X_obs.abs().max() < 100.0
    assert sample.Y_q.abs().max() < 100.0


def test_mask_npz_roundtrip_and_dataset_wrapper(tmp_path):
    bundle = create_protocol_datasets(
        "cmapss_fd001",
        DATA_ROOT,
        seed=2026,
        history_len=12,
        pred_len=3,
        stride=120,
        async_mode="none",
    )
    mask_path = tmp_path / "cmapss_fd001_missing_0.3_seed2026.npz"

    masks_a = generate_or_load_masks(
        mask_path,
        num_windows=len(bundle.train),
        history_len=12,
        num_sensors=21,
        missing_rate=0.3,
        seed=2026,
        mode="mixed",
    )
    masks_b = generate_or_load_masks(
        mask_path,
        num_windows=len(bundle.train),
        history_len=12,
        num_sensors=21,
        missing_rate=0.3,
        seed=2026,
        mode="mixed",
    )
    wrapped = MaskedWindowDataset(bundle.train, masks_a)
    sample = wrapped[0]

    assert mask_path.exists()
    assert masks_a.dtype == np.uint8
    assert np.array_equal(masks_a, masks_b)
    assert torch.equal(sample.M_obs, torch.tensor(masks_a[0], dtype=torch.float32))
    assert torch.all(sample.X_obs[sample.M_obs == 0] == 0)


def test_run_experiment_writes_unified_outputs(tmp_path):
    run_id = "20260608_120000"
    config = ExperimentConfig(
        dataset="cmapss_fd001",
        model="kaf_profiti_joint",
        seed=2026,
        missing_rate=0.3,
        history_len=12,
        pred_len=3,
        stride=120,
        data_root=str(DATA_ROOT),
        output_dir=str(tmp_path),
        epochs=1,
        batch_size=2,
        max_train_batches=1,
        max_eval_batches=1,
        nsamples=3,
        device="cpu",
        run_id=run_id,
    )

    metrics = run_experiment(config)
    metrics_path = (
        tmp_path
        / run_id
        / "metrics"
        / "cmapss_fd001"
        / "kaf_profiti_joint"
        / "metrics_seed2026.json"
    )
    samples_path = (
        tmp_path
        / run_id
        / "predictions"
        / "cmapss_fd001"
        / "kaf_profiti_joint"
        / "samples_seed2026.npy"
    )
    history_path = (
        tmp_path
        / run_id
        / "training_history"
        / "cmapss_fd001"
        / "kaf_profiti_joint"
        / "history_seed2026.json"
    )
    mask_path = (
        tmp_path
        / run_id
        / "masks"
        / "cmapss_fd001"
        / "cmapss_fd001_missing_0.3_seed2026.npz"
    )

    assert metrics["status"] == "completed"
    assert metrics["run_id"] == run_id
    assert metrics_path.exists()
    assert samples_path.exists()
    assert history_path.exists()
    assert mask_path.exists()
    loaded = json.loads(metrics_path.read_text())
    history = json.loads(history_path.read_text())
    assert loaded["dataset"] == "cmapss_fd001"
    assert loaded["model"] == "kaf_profiti_joint"
    assert loaded["missing_rate"] == 0.3
    assert loaded["mae"] is not None
    assert loaded["rmse"] is not None
    assert loaded["picp"] is not None
    assert loaded["history_path"] == str(history_path)
    assert len(history) == 1
    assert history[0]["epoch"] == 1
    assert history[0]["train_loss"] is not None
    assert history[0]["valid_nll"] is not None
    assert history[0]["train_batches"] == 1
    assert history[0]["valid_batches"] == 1
    assert history[0]["epoch_time_sec"] >= 0
    assert loaded["metrics_path"] == str(metrics_path)
    assert loaded["prediction_dir"] == str(samples_path.parent)
    assert loaded["calibration_split"] == "validation"
    assert loaded["calibration_uses_test_labels"] is False
    assert loaded["checkpoint_selection"] == "best_valid"
    assert loaded["checkpoint_path"] == loaded["best_checkpoint_path"]
    assert loaded["final_checkpoint_path"].endswith("/checkpoint_seed2026.pt")
    assert loaded["best_checkpoint_path"].endswith("/checkpoint_seed2026_best.pt")
    assert loaded["best_epoch"] == 1
    assert loaded["best_valid_metric_name"] == "valid_crps"
    assert loaded["calibration_path"].endswith("/calibration_seed2026.json")
    assert loaded["risk_threshold_source"].startswith("validation")
    assert loaded["best_f1_source"] == "same_split_diagnostic_only"
    assert loaded["top_error_source"] == "test_diagnostic_only"


def test_run_experiment_uses_distinct_mask_path_for_metropt_chrono_602020(tmp_path):
    run_id = "20260609_chrono_602020"
    config = ExperimentConfig(
        dataset="metropt3_chrono_602020",
        model="kaf_profiti_joint",
        seed=2026,
        missing_rate=0.3,
        history_len=12,
        pred_len=3,
        stride=200_000,
        data_root=str(DATA_ROOT),
        output_dir=str(tmp_path),
        epochs=1,
        batch_size=2,
        max_train_batches=1,
        max_eval_batches=1,
        nsamples=3,
        device="cpu",
        run_id=run_id,
    )

    metrics = run_experiment(config)

    assert metrics["dataset"] == "metropt3_chrono_602020"
    assert metrics["status"] == "completed"
    assert "/masks/metropt3_chrono_602020/" in metrics["mask_path"]
    assert metrics["mask_path"].endswith(
        "/metropt3_chrono_602020_missing_0.3_seed2026.npz"
    )
    split = json.loads(Path(metrics["split_path"]).read_text())
    assert split["split_rule"] == "chronological_60_20_20_no_overlap"


def test_run_experiment_supports_kst_probflow_outputs(tmp_path):
    run_id = "20260608_kst_smoke"
    config = ExperimentConfig(
        dataset="cmapss_fd001",
        model="kst_probflow",
        seed=2026,
        missing_rate=0.3,
        history_len=12,
        pred_len=3,
        stride=120,
        data_root=str(DATA_ROOT),
        output_dir=str(tmp_path),
        epochs=1,
        batch_size=2,
        max_train_batches=1,
        max_eval_batches=1,
        nsamples=3,
        device="cpu",
        run_id=run_id,
        hidden_dim=16,
        te_dim=5,
        n_layers=1,
        n_heads=2,
        preconv_dim=4,
        patch_lens="6,12",
        graph_layers=1,
        copula_rank=4,
        lambda_point=0.5,
        lambda_quantile=0.2,
        lambda_risk=0.05,
        sample_clip=30.0,
    )

    metrics = run_experiment(config)
    metrics_path = (
        tmp_path
        / run_id
        / "metrics"
        / "cmapss_fd001"
        / "kst_probflow"
        / "metrics_seed2026.json"
    )

    assert metrics["status"] == "completed"
    assert metrics["model"] == "kst_probflow"
    assert metrics["quantile_picp"] is not None
    assert metrics["risk_source"] == "risk_head"
    assert metrics["calibration_split"] == "validation"
    assert metrics["calibration_uses_test_labels"] is False
    assert metrics["risk_orientation_selection"] == "disabled"
    assert metrics["best_f1_source"] == "same_split_diagnostic_only"
    assert metrics["top_error_source"] == "test_diagnostic_only"
    assert metrics_path.exists()


def test_checkpoint_only_run_writes_fixed_outputs(tmp_path):
    train_run_id = "20260608_120001"
    train_config = ExperimentConfig(
        dataset="cmapss_fd001",
        model="kaf_profiti_joint",
        seed=2026,
        missing_rate=0.3,
        history_len=12,
        pred_len=3,
        stride=120,
        data_root=str(DATA_ROOT),
        output_dir=str(tmp_path),
        epochs=1,
        batch_size=2,
        max_train_batches=1,
        max_eval_batches=1,
        nsamples=3,
        device="cpu",
        run_id=train_run_id,
    )
    train_metrics = run_experiment(train_config)
    checkpoint_path = train_metrics["checkpoint_path"]
    eval_run_id = "20260608_120002"
    eval_config = ExperimentConfig(
        dataset="cmapss_fd001",
        model="kaf_profiti_joint",
        seed=2026,
        missing_rate=0.3,
        history_len=12,
        pred_len=3,
        stride=120,
        data_root=str(DATA_ROOT),
        output_dir=str(tmp_path),
        epochs=0,
        batch_size=2,
        max_train_batches=0,
        max_eval_batches=1,
        nsamples=3,
        device="cpu",
        checkpoint=checkpoint_path,
        run_id=eval_run_id,
    )

    metrics = run_experiment(eval_config)

    metrics_path = (
        tmp_path
        / eval_run_id
        / "metrics"
        / "cmapss_fd001"
        / "kaf_profiti_joint"
        / "metrics_seed2026_fixed.json"
    )
    samples_path = (
        tmp_path
        / eval_run_id
        / "predictions"
        / "cmapss_fd001"
        / "kaf_profiti_joint"
        / "samples_seed2026_fixed.npy"
    )
    assert metrics["status"] == "completed_from_checkpoint_fixed"
    assert metrics["run_id"] == eval_run_id
    assert metrics["checkpoint_path"] == checkpoint_path
    assert metrics["checkpoint_selection"] == "provided_checkpoint"
    assert metrics["final_checkpoint_path"] == checkpoint_path
    assert metrics["best_checkpoint_path"] == checkpoint_path
    assert metrics["sample_clip"] == 20.0
    assert metrics["attention_diag_floor"] == 0.05
    assert metrics["nonfinite_sample_rows"] == 0
    assert metrics["finite_metric_positions"] > 0
    assert metrics["calibration_split"] == "validation"
    assert metrics["calibration_uses_test_labels"] is False
    assert metrics["calibration_path"].endswith("/calibration_seed2026_fixed.json")
    assert metrics_path.exists()
    assert samples_path.exists()
    assert np.isfinite(np.load(samples_path)).all()


def test_run_experiment_persists_history_before_final_eval_failure(tmp_path, monkeypatch):
    run_id = "20260608_120003"
    calls = {"count": 0}

    def fake_evaluate(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return (
                {
                    "nll": 1.0,
                    "mae": 1.0,
                    "rmse": 1.0,
                    "crps": 1.0,
                    "picp": 0.9,
                    "mpiw": 1.0,
                    "auroc": None,
                    "auprc": None,
                    "f1": None,
                    "ece": None,
                    "lead_time": None,
                    "infer_time_ms_per_batch": 1.0,
                },
                [],
                [],
                [],
            )
        raise RuntimeError("final eval failed")

    monkeypatch.setattr(run_experiment_module, "_evaluate", fake_evaluate)
    config = ExperimentConfig(
        dataset="cmapss_fd001",
        model="kaf_profiti_joint",
        seed=2026,
        missing_rate=0.3,
        history_len=12,
        pred_len=3,
        stride=120,
        data_root=str(DATA_ROOT),
        output_dir=str(tmp_path),
        epochs=1,
        batch_size=2,
        max_train_batches=1,
        max_eval_batches=1,
        nsamples=3,
        device="cpu",
        run_id=run_id,
    )

    with pytest.raises(RuntimeError, match="final eval failed"):
        run_experiment(config)

    history_path = (
        tmp_path
        / run_id
        / "training_history"
        / "cmapss_fd001"
        / "kaf_profiti_joint"
        / "history_seed2026.json"
    )
    history = json.loads(history_path.read_text())
    assert history_path.exists()
    assert len(history) == 1
    assert history[0]["epoch"] == 1


def test_build_tables_reads_metrics_and_marks_not_implemented(tmp_path):
    metrics_dir = (
        tmp_path / "20260608_120004" / "metrics" / "metropt3" / "kaf_profiti_joint"
    )
    metrics_dir.mkdir(parents=True)
    (metrics_dir / "metrics_seed2026.json").write_text(
        json.dumps(
            {
                "dataset": "metropt3",
                "model": "kaf_profiti_joint",
                "seed": 2026,
                "missing_rate": 0.3,
                "history": 12,
                "horizon": 3,
                "mae": 1.0,
                "rmse": 2.0,
                "nll": 3.0,
                "crps": 4.0,
                "picp": 0.9,
                "mpiw": 1.2,
                "auroc": None,
                "auprc": None,
                "f1": None,
                "ece": None,
                "lead_time": None,
                "train_time_sec": 1.0,
                "infer_time_ms_per_batch": 2.0,
                "num_params": 10,
                "gpu_memory_mb": None,
                "run_id": "20260608_120004",
                "status": "completed",
                "error": None,
            }
        )
    )

    build_tables(tmp_path)

    table2 = tmp_path / "tables" / "table2_main_forecasting.csv"
    table5 = tmp_path / "tables" / "table5_ablation.csv"
    assert table2.exists()
    assert table5.exists()
    text = table2.read_text()
    assert "kaf_profiti_joint" in text
    assert "not_implemented" in text
    assert "20260608_120004" in text
