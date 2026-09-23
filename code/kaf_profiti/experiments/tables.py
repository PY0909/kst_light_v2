import json
from pathlib import Path
from typing import Dict, List

import pandas as pd

from .registry import list_model_specs


def _read_metrics(results_dir: Path) -> List[Dict[str, object]]:
    rows = []
    for path in sorted(results_dir.rglob("metrics_seed*.json")):
        rows.append(json.loads(path.read_text()))
    return rows


def _write_csv(path: Path, rows: List[Dict[str, object]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def build_tables(results_dir) -> None:
    results_dir = Path(results_dir)
    tables_dir = results_dir / "tables"
    metrics = _read_metrics(results_dir)
    datasets = sorted({row["dataset"] for row in metrics})
    specs = list_model_specs()

    split_rows = []
    for split_path in sorted(results_dir.rglob("*_split_seed*.json")):
        split = json.loads(split_path.read_text())
        split_rows.append(
            {
                "dataset": split.get("dataset"),
                "seed": split.get("seed"),
                "run_id": split.get("run_id"),
                "train_windows": split.get("train_windows"),
                "valid_windows": split.get("valid_windows"),
                "test_windows": split.get("test_windows"),
                "num_sensors": split.get("num_sensors"),
                "split_rule": split.get("split_rule"),
            }
        )
    _write_csv(tables_dir / "table1_dataset_split.csv", split_rows)

    table2 = []
    for dataset in datasets:
        dataset_rows = [row for row in metrics if row["dataset"] == dataset]
        run_keys = sorted(
            {
                (row.get("seed"), row.get("run_id", "legacy"))
                for row in dataset_rows
            },
            key=lambda item: (str(item[1]), str(item[0])),
        )
        for spec in specs:
            for seed, run_id in run_keys or [(None, None)]:
                row = next(
                    (
                        item
                        for item in dataset_rows
                        if item.get("model") == spec.name
                        and item.get("seed") == seed
                        and item.get("run_id", "legacy") == run_id
                    ),
                    None,
                )
                if row is None:
                    table2.append(
                        {
                            "dataset": dataset,
                            "model": spec.name,
                            "seed": seed,
                            "run_id": run_id,
                            "mae": None,
                            "rmse": None,
                            "nll": None,
                            "crps": None,
                            "status": spec.status,
                        }
                    )
                else:
                    table2.append(
                        {
                            "dataset": dataset,
                            "model": spec.name,
                            "seed": seed,
                            "run_id": row.get("run_id", run_id),
                            "mae": row.get("mae"),
                            "rmse": row.get("rmse"),
                            "nll": row.get("nll"),
                            "crps": row.get("crps"),
                            "status": row.get("status"),
                        }
                    )
    _write_csv(tables_dir / "table2_main_forecasting.csv", table2)

    _write_csv(
        tables_dir / "table3_risk_prediction.csv",
        [
            {
                "dataset": row.get("dataset"),
                "model": row.get("model"),
                "seed": row.get("seed"),
                "run_id": row.get("run_id"),
                "auroc": row.get("auroc"),
                "auprc": row.get("auprc"),
                "f1": row.get("f1"),
                "ece": row.get("ece"),
                "lead_time": row.get("lead_time"),
                "status": row.get("status"),
            }
            for row in metrics
        ],
    )
    _write_csv(
        tables_dir / "table4_missing_robustness.csv",
        [
            {
                "dataset": row.get("dataset"),
                "model": row.get("model"),
                "seed": row.get("seed"),
                "run_id": row.get("run_id"),
                "missing_rate": row.get("missing_rate"),
                "mae": row.get("mae"),
                "nll": row.get("nll"),
                "auroc": row.get("auroc"),
                "status": row.get("status"),
            }
            for row in metrics
        ],
    )
    ablation_models = {"kafnet", "kafnet_gaussian", "kaf_profiti_marginal", "kaf_profiti_joint"}
    _write_csv(
        tables_dir / "table5_ablation.csv",
        [row for row in table2 if row.get("model") in ablation_models],
    )
    _write_csv(
        tables_dir / "table6_efficiency.csv",
        [
            {
                "dataset": row.get("dataset"),
                "model": row.get("model"),
                "seed": row.get("seed"),
                "run_id": row.get("run_id"),
                "num_params": row.get("num_params"),
                "train_time_sec": row.get("train_time_sec"),
                "infer_time_ms_per_batch": row.get("infer_time_ms_per_batch"),
                "gpu_memory_mb": row.get("gpu_memory_mb"),
                "status": row.get("status"),
            }
            for row in metrics
        ],
    )
    _write_csv(
        tables_dir / "table7_statistical_test.csv",
        [
            {
                "dataset": row.get("dataset"),
                "model": row.get("model"),
                "seed": row.get("seed"),
                "run_id": row.get("run_id"),
                "status": row.get("status"),
                "p_value": None,
            }
            for row in metrics
        ],
    )
