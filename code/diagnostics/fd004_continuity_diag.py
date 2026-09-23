"""FD004 pilot diagnostic step 1: raw-data continuity and window boundaries.

Checks (independent of the training path):
  1. Raw tables are sorted by (unit, cycle) and each engine's cycles are the
     consecutive run 1..N.
  2. For fixed (engine, start) pairs on train/valid/test splits: the window
     history is exactly rows [start, start+50), the target is
     [start+50, start+60), T_q[0] == T_obs[-1] + 1, and X_obs[-1]/Y_q[0]
     match the correct two rows of the raw table after inverse
     normalization (raw-vs-normalized boundary difference).
  3. Split integrity: train/valid engine sets are disjoint, window lists are
     canonically ordered and never reshuffled across splits, and the official
     test file drives the test split.
  4. Timeline-mask reproducibility: regenerate the random@0.00 / random@0.30
     bundles with the recorded seeds and compare content digests against the
     completed run manifests (cross-environment determinism, torch 2.5.1 on
     AutoDL vs local torch).

Usage: python diagnostics/fd004_continuity_diag.py
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import torch

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))

from kaf_profiti.experiments.datasets import create_protocol_datasets
from kaf_profiti.experiments.masks import (
    TimelineMaskConfig,
    generate_or_load_timeline_masks,
)
from kaf_profiti.experiments.runtime_paths import resolve_runtime_paths

HISTORY_LEN = 50
PRED_LEN = 10
STRIDE = 1
SEED = 2026
SPLIT_SEED = 2026

_COLUMNS = (
    ["unit", "cycle"]
    + [f"setting_{idx}" for idx in (1, 2, 3)]
    + [f"sensor_{idx}" for idx in range(1, 22)]
)


class Report:
    def __init__(self):
        self.entries = []

    def check(self, name, ok, detail=""):
        self.entries.append((name, bool(ok), str(detail)))
        print(f"[{'PASS' if ok else 'FAIL'}] {name} -- {detail}")

    def summary(self):
        failed = [name for name, ok, _ in self.entries if not ok]
        print(f"\n{len(self.entries) - len(failed)}/{len(self.entries)} checks passed")
        if failed:
            print("FAILED:", *failed, sep="\n  - ")
        return len(failed) == 0


def read_raw(split, data_root):
    frame = pd.read_csv(
        data_root / "CMAPSSData" / f"{split}_FD004.txt", sep=r"\s+", header=None
    )
    if frame.shape[1] != 26:
        raise ValueError(f"unexpected column count {frame.shape[1]}")
    frame.columns = _COLUMNS
    return frame


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", default=None, help="defaults to KST_DATA_ROOT / repo dataset")
    parser.add_argument("--result-root", default=None, help="defaults to KST_RESULT_ROOT / repo result")
    parser.add_argument("--runs-root", default=None, help="defaults to <result-root>/pilot/fd004/runs")
    args = parser.parse_args()

    paths = resolve_runtime_paths(args.data_root, args.result_root, os.environ)
    data_root = paths.data_root
    runs_root = (
        Path(args.runs_root)
        if args.runs_root
        else paths.output_root / "pilot" / "fd004" / "runs"
    )

    report = Report()
    torch.manual_seed(SEED)

    raw = {"train": read_raw("train", data_root), "test": read_raw("test", data_root)}

    # -- 1. sorting / cycle continuity ------------------------------------
    for split, frame in raw.items():
        ordered = frame[["unit", "cycle"]].equals(
            frame[["unit", "cycle"]]
            .sort_values(["unit", "cycle"], kind="stable")
            .reset_index(drop=True)
        )
        report.check(f"raw_{split} sorted by (unit,cycle)", ordered)
        bad_units = []
        for unit, group in frame.groupby("unit"):
            cycles = group["cycle"].to_numpy()
            if cycles[0] != 1 or not (np.diff(cycles) == 1).all():
                bad_units.append(int(unit))
        report.check(
            f"raw_{split} cycles consecutive from 1 per engine",
            not bad_units,
            f"{frame['unit'].nunique()} engines, bad={bad_units[:5]}",
        )

    # -- protocol datasets -------------------------------------------------
    bundle = create_protocol_datasets(
        "cmapss_fd004",
        data_root,
        seed=SEED,
        history_len=HISTORY_LEN,
        pred_len=PRED_LEN,
        stride=STRIDE,
        async_mode="none",
        split_seed=SPLIT_SEED,
    )
    info = bundle.split_info
    stats = bundle.train.stats
    sensor_mean = stats["sensor_mean"].numpy()
    sensor_std = stats["sensor_std"].numpy()

    # -- 2. fixed (engine, start) boundary assertions ----------------------
    def normalized_sensors(frame, unit, row_index):
        group = frame[frame["unit"] == unit]
        row = group.iloc[row_index]
        values = np.array([row[f"sensor_{idx}"] for idx in range(1, 22)], dtype=np.float64)
        return (values - sensor_mean) / sensor_std

    fixed_cases = []
    train_ids = set(info["train_engine_ids"])
    valid_ids = set(info["valid_engine_ids"])
    for split in ("train", "valid", "test"):
        dataset = getattr(bundle, split)
        units = sorted({unit for unit, _ in dataset.windows})
        chosen = units[0]
        group_len = int((raw["train" if split != "test" else "test"]["unit"] == chosen).sum())
        fixed_cases.append((split, chosen, 0))                     # first window
        fixed_cases.append((split, chosen, group_len - 60))        # last window
        fixed_cases.append((split, chosen, group_len // 2))        # middle window

    max_boundary_error = 0.0
    for split, unit, start in fixed_cases:
        dataset = getattr(bundle, split)
        if (unit, start) not in dataset.windows:
            report.check(f"window {split}/unit{unit}/start{start} exists", False)
            continue
        index = dataset.windows.index((unit, start))
        sample = dataset[index]
        frame = raw["train" if split != "test" else "test"]

        ok_len = sample.T_obs.numel() == HISTORY_LEN and sample.T_q.numel() == PRED_LEN
        cycles = frame[frame["unit"] == unit]["cycle"].to_numpy()
        t_obs = sample.T_obs.numpy()
        t_q = sample.T_q.numpy()
        ok_hist = np.array_equal(t_obs, cycles[start : start + HISTORY_LEN])
        ok_target = np.array_equal(t_q, cycles[start + HISTORY_LEN : start + HISTORY_LEN + PRED_LEN])
        ok_next = t_q[0] == t_obs[-1] + 1

        expected_hist_last = normalized_sensors(frame, unit, start + HISTORY_LEN - 1)
        expected_target_first = normalized_sensors(frame, unit, start + HISTORY_LEN)
        ok_values = np.allclose(
            sample.X_obs[-1].numpy(), expected_hist_last, atol=1e-4
        ) and np.allclose(sample.Y_q[0].numpy(), expected_target_first, atol=1e-4)

        raw_hist_last = frame[frame["unit"] == unit].iloc[start + HISTORY_LEN - 1][
            [f"sensor_{idx}" for idx in range(1, 22)]
        ].to_numpy(dtype=np.float64)
        raw_target_first = frame[frame["unit"] == unit].iloc[start + HISTORY_LEN][
            [f"sensor_{idx}" for idx in range(1, 22)]
        ].to_numpy(dtype=np.float64)
        inverse_error = max(
            float(np.abs(sample.X_obs[-1].numpy() * sensor_std + sensor_mean - raw_hist_last).max()),
            float(np.abs(sample.Y_q[0].numpy() * sensor_std + sensor_mean - raw_target_first).max()),
        )
        max_boundary_error = max(max_boundary_error, inverse_error)

        report.check(
            f"window {split}/unit{unit}/start{start}",
            ok_len and ok_hist and ok_target and ok_next and ok_values,
            f"hist/target/next/value ok; inverse-transform max err {inverse_error:.3e}",
        )

    report.check(
        "inverse normalization reproduces raw boundary rows (float32 roundtrip)",
        max_boundary_error < 1e-2,
        f"max |denorm - raw| = {max_boundary_error:.3e} (raw scale)",
    )

    # -- 3. split integrity / no reshuffle --------------------------------
    train_ds, valid_ds, test_ds = bundle.train, bundle.valid, bundle.test
    report.check(
        "train/valid engine sets disjoint",
        not (train_ids & valid_ids),
        f"|train|={len(train_ids)} |valid|={len(valid_ids)} |union|={len(train_ids | valid_ids)}",
    )
    train_windows = set(map(tuple, train_ds.windows))
    valid_windows = set(map(tuple, valid_ds.windows))
    report.check(
        "no (unit,start) window appears in both train and valid",
        not (train_windows & valid_windows),
        f"overlap={len(train_windows & valid_windows)}",
    )
    for split, dataset in (("train", train_ds), ("valid", valid_ds), ("test", test_ds)):
        windows = [tuple(w) for w in dataset.windows]
        report.check(
            f"{split} windows canonically ordered (unit,start), no duplicates",
            windows == sorted(windows) and len(set(windows)) == len(windows),
            f"count={len(windows)}",
        )
        correct_units = all(
            (unit in train_ids) if split == "train"
            else (unit in valid_ids) if split == "valid"
            else True
            for unit, _ in windows
        )
        report.check(f"{split} windows only reference {split} engines", correct_units)
    bounds = info["window_bounds"]
    for split, dataset in (("train", train_ds), ("valid", valid_ds), ("test", test_ds)):
        entry = bounds[split]
        report.check(
            f"{split} window bounds match split_info",
            entry["count"] == len(dataset.windows)
            and tuple(entry["first"]) == tuple(dataset.windows[0])
            and tuple(entry["last"]) == tuple(dataset.windows[-1]),
            f"count {entry['count']} first {entry['first']} last {entry['last']}",
        )
    test_units = {unit for unit, _ in test_ds.windows}
    test_file_units = {int(u) for u in raw["test"]["unit"].unique()}
    test_lengths = raw["test"].groupby("unit")["cycle"].max().to_dict()
    unexplained = [
        unit
        for unit in test_file_units - test_units
        if test_lengths[unit] >= HISTORY_LEN + PRED_LEN
    ]
    report.check(
        "test split uses official test-file engines (short engines excluded)",
        test_units <= test_file_units and not unexplained,
        f"{len(test_units)}/{len(test_file_units)} engines windowed; "
        f"absent-but-long-enough={unexplained}",
    )

    # -- 4. timeline-mask bundle reproducibility ---------------------------
    split_sha = info["split_sha256"]
    for condition, rate in (("point_random_000", 0.00), ("point_random_030", 0.30)):
        manifest_path = (
            runs_root / f"cmapss_fd004|point|li_tcn|linear|{condition}|{SEED}" / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = manifest["protocol_sha"]["mask_sha"]
        with tempfile.TemporaryDirectory() as tmp:
            for split in ("train", "valid", "test"):
                dataset = getattr(bundle, split)
                lengths = {
                    int(unit): len(group) for unit, group in dataset._units.items()
                }
                config = TimelineMaskConfig(
                    dataset="cmapss_fd004",
                    split=split,
                    mechanism="random",
                    requested_rate=rate,
                    mask_seed=SEED,
                    source_split_sha256=split_sha,
                )
                mask_bundle = generate_or_load_timeline_masks(
                    Path(tmp) / f"{split}.npz", config, lengths, bundle.num_sensors
                )
                digest = mask_bundle.content_sha256
                report.check(
                    f"{condition} {split} mask digest matches manifest",
                    digest == expected[split],
                    f"local={digest[:12]} manifest={expected[split][:12]} "
                    f"realized_rate={mask_bundle.realized_rate:.4f} "
                    f"engines_in_bundle={len(mask_bundle.masks)}",
                )

    ok = report.summary()
    print(json.dumps({"all_passed": ok}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
