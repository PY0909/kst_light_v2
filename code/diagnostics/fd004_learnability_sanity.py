"""FD004 pilot diagnostic step 3: learnability floor + local short-training repro.

For one condition (random@0.00 or random@0.30) this script:

  A. dumps one train batch's input statistics (non-zero fraction, std, target
     statistics, X_obs[-1] vs Y_q[0] correlation) to verify the model actually
     receives informative history;
  B. evaluates four cheap predictors on the same train/valid/test loaders the
     pilot used — zero, per-channel train mean, last-observed-value
     (persistence), and per-channel linear trend fit on observed history —
     establishing the reasonable lower bound for the task;
  C. runs a faithful local repro of the pilot training loop (imported from
     pilot_runner) for a few epochs on CPU and prints the per-epoch history so
     it can be compared directly with the AutoDL history.json curves.

Usage:
  python diagnostics/fd004_learnability_sanity.py --rate 0.00 --epochs 6
  python diagnostics/fd004_learnability_sanity.py --rate 0.30 --epochs 6
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import torch
from torch.utils.data import DataLoader

CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT))

from kaf_profiti.experiments.datasets import create_protocol_datasets
from kaf_profiti.experiments.masks import (
    TimelineMaskConfig,
    TimelineMaskedWindowDataset,
    generate_or_load_timeline_masks,
)
from kaf_profiti.experiments.pilot_runner import _train_one_epoch, _valid_score
from kaf_profiti.experiments.runtime_paths import resolve_runtime_paths
from kaf_profiti.industrial.batch import IndustrialCollator

HISTORY_LEN = 50
PRED_LEN = 10
STRIDE = 1
SEED = 2026
SPLIT_SEED = 2026
BATCH_SIZE = 128
NUM_SENSORS = 21


def build_protocol(rate: float, mask_dir: Path, data_root: Path):
    bundle = create_protocol_datasets(
        "cmapss_fd004", data_root, seed=SEED, history_len=HISTORY_LEN,
        pred_len=PRED_LEN, stride=STRIDE, async_mode="none", split_seed=SPLIT_SEED,
    )
    datasets = {}
    mask_info = {}
    for split in ("train", "valid", "test"):
        window_dataset = getattr(bundle, split)
        lengths = {int(unit): len(group) for unit, group in window_dataset._units.items()}
        config = TimelineMaskConfig(
            dataset="cmapss_fd004", split=split, mechanism="random",
            requested_rate=rate, mask_seed=SEED,
            source_split_sha256=bundle.split_info["split_sha256"],
        )
        mask_bundle = generate_or_load_timeline_masks(
            mask_dir / f"{split}.npz", config, lengths, bundle.num_sensors
        )
        datasets[split] = TimelineMaskedWindowDataset(window_dataset, mask_bundle)
        mask_info[split] = {
            "sha": mask_bundle.content_sha256[:12],
            "realized_rate": round(mask_bundle.realized_rate, 4),
        }
    return bundle, datasets, mask_info


def make_loaders(datasets, batch_size, eval_batch=512):
    collator = IndustrialCollator()
    return {
        "train": DataLoader(
            datasets["train"], batch_size=batch_size, shuffle=True, collate_fn=collator
        ),
        "valid": DataLoader(
            datasets["valid"], batch_size=eval_batch, shuffle=False, collate_fn=collator
        ),
        "test": DataLoader(
            datasets["test"], batch_size=eval_batch, shuffle=False, collate_fn=collator
        ),
    }


# --------------------------------------------------------------------------
# A. batch statistics
# --------------------------------------------------------------------------


def batch_statistics(datasets):
    collator = IndustrialCollator()
    loader = DataLoader(datasets["train"], batch_size=256, shuffle=False, collate_fn=collator)
    batch = next(iter(loader))
    x, m, y = batch.X_obs, batch.M_obs, batch.Y_q
    print("== A. train batch statistics (first 256 windows) ==")
    print(f"  M_obs mean (observed fraction): {m.mean():.4f}")
    print(f"  X_obs nonzero fraction:        {(x != 0).float().mean():.4f}")
    print(f"  X_obs std (observed cells):    {x[m > 0].std():.4f}")
    print(f"  Y_q mean/std:                  {y.mean():.4f} / {y.std():.4f}")
    last_obs = forward_fill_last(x, m)
    future_first = y[:, 0, :]
    corr = torch.cat(
        [torch.corrcoef(torch.stack([last_obs[:, n], future_first[:, n]]))[0, 1:2]
         for n in range(NUM_SENSORS)]
    )
    print(f"  corr(last-observed, Y_q[0]) per channel: mean={corr.mean():.4f} "
          f"min={corr.min():.4f} max={corr.max():.4f}")
    err = (last_obs.unsqueeze(1) - y).abs()
    print(f"  persistence |last - Y| MAE (all 10 steps): {err.mean():.4f}")
    print(f"  zero-predictor |Y| MAE:                     {y.abs().mean():.4f}")


def forward_fill_last(x, m):
    """Last observed value per (window, channel): [B, N]."""
    value = torch.zeros(x.shape[0], x.shape[2])
    for l in range(x.shape[1]):
        observed = m[:, l] > 0
        value = torch.where(observed, x[:, l], value)
    return value


# --------------------------------------------------------------------------
# B. cheap predictors
# --------------------------------------------------------------------------


def evaluate_predictor(name, predict_fn, loaders):
    print(f"  -- {name}")
    out = {}
    for split in ("train", "valid", "test"):
        abs_sum = sq_sum = count = 0.0
        for batch in loaders[split]:
            pred = predict_fn(batch)                      # [B, P, N]
            errors = (pred - batch.Y_q).abs() * batch.M_q
            sq = ((pred - batch.Y_q) ** 2) * batch.M_q
            abs_sum += float(errors.sum())
            sq_sum += float(sq.sum())
            count += float(batch.M_q.sum())
        out[split] = {"mae": abs_sum / count, "mse": sq_sum / count}
        print(f"     {split:5s} MAE={out[split]['mae']:.4f}  MSE={out[split]['mse']:.4f}")
    return out


def predictor_floors(loaders):
    print("== B. cheap predictor floors (masked MAE/MSE, normalized scale) ==")
    results = {}

    results["zero"] = evaluate_predictor(
        "zero predictor (predict 0)", lambda b: torch.zeros_like(b.Y_q), loaders
    )

    channel_mean = None
    total = torch.zeros(NUM_SENSORS)
    count = torch.zeros(NUM_SENSORS)
    for batch in loaders["train"]:
        total = total + (batch.Y_q * batch.M_q).sum(dim=(0, 1))
        count = count + batch.M_q.sum(dim=(0, 1))
    channel_mean = total / count.clamp_min(1.0)
    results["channel_mean"] = evaluate_predictor(
        "per-channel train mean",
        lambda b: channel_mean.unsqueeze(0).unsqueeze(0).expand_as(b.Y_q),
        loaders,
    )

    def window_mean(batch):
        observed = batch.X_obs * batch.M_obs
        counts = batch.M_obs.sum(dim=1).clamp_min(1.0)
        mean = observed.sum(dim=1) / counts                     # [B, N]
        return mean.unsqueeze(1).expand(-1, batch.Y_q.shape[1], -1)

    results["window_mean"] = evaluate_predictor(
        "per-channel window mean (realistic floor)", window_mean, loaders
    )

    def persistence(batch):
        last = forward_fill_last(batch.X_obs, batch.M_obs)        # [B, N]
        return last.unsqueeze(1).expand(-1, batch.Y_q.shape[1], -1)

    results["persistence"] = evaluate_predictor("last-observed value (persistence)", persistence, loaders)

    def linear_trend(batch):
        x = batch.X_obs.clone()
        m = batch.M_obs
        t = batch.T_obs.to(torch.float64).unsqueeze(-1).expand(-1, -1, NUM_SENSORS)
        xd = x.to(torch.float64) * m
        big = t.abs().max().item() + 1.0
        tc = t / big                                              # centered/scaled time
        count = m.to(torch.float64)
        s_t = (count * tc).sum(dim=1)
        s_y = (count * xd).sum(dim=1)
        s_tt = (count * tc * tc).sum(dim=1)
        s_ty = (count * tc * xd).sum(dim=1)
        denom = (count.sum(dim=1) * s_tt - s_t * s_t).clamp_min(1e-12)
        slope = (count.sum(dim=1) * s_ty - s_t * s_y) / denom
        intercept = (s_y - slope * s_t) / count.sum(dim=1).clamp_min(1.0)
        future_t = batch.T_q.to(torch.float64).unsqueeze(-1).expand(-1, -1, NUM_SENSORS) / big
        pred = intercept.unsqueeze(1) + slope.unsqueeze(1) * future_t
        fallback = forward_fill_last(batch.X_obs, batch.M_obs).to(torch.float64).unsqueeze(1)
        enough = count.sum(dim=1) >= 3
        pred = torch.where(enough.unsqueeze(1), pred, fallback.expand_as(pred))
        return pred.to(torch.float32)

    results["linear_trend"] = evaluate_predictor("per-channel linear trend on observed history", linear_trend, loaders)
    return results


# --------------------------------------------------------------------------
# C. faithful short training repro
# --------------------------------------------------------------------------


def short_training(loaders, epochs):
    from kaf_profiti.baselines.point import create_point_baseline

    print(f"== C. li_tcn local training repro ({epochs} epochs, CPU, AdamW lr=1e-3 wd=1e-4, batch={BATCH_SIZE}) ==")
    torch.manual_seed(SEED)
    model = create_point_baseline(
        "li_tcn", num_sensors=NUM_SENSORS, context_dim=3,
        pred_len=PRED_LEN, hidden_dim=64,
    )
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
    history = []
    for epoch in range(1, epochs + 1):
        loss = _train_one_epoch(model, loaders["train"], optimizer, torch.device("cpu"))
        score = _valid_score(model, loaders["valid"], torch.device("cpu"), "point")
        history.append({"epoch": epoch, "train_loss": round(loss, 6), "valid_score": round(score, 6)})
        print(f"  epoch {epoch:2d}  train_loss={loss:.6f}  valid_mae={score:.6f}")
    return history


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate", type=float, required=True, choices=[0.0, 0.3])
    parser.add_argument("--epochs", type=int, default=6)
    parser.add_argument("--data-root", default=None, help="defaults to KST_DATA_ROOT / repo dataset")
    parser.add_argument("--result-root", default=None, help="defaults to KST_RESULT_ROOT / repo result")
    args = parser.parse_args()

    paths = resolve_runtime_paths(args.data_root, args.result_root, os.environ)
    data_root = paths.data_root
    output_root = paths.output_root

    with tempfile.TemporaryDirectory() as tmp:
        _, datasets, mask_info = build_protocol(args.rate, Path(tmp), data_root)
    print(f"condition random@{args.rate:.2f}  masks={json.dumps(mask_info)}")
    print(f"windows: train={len(datasets['train'])} valid={len(datasets['valid'])} test={len(datasets['test'])}")
    print(f"data_root={data_root}  result_root={output_root}")

    batch_statistics(datasets)
    loaders = make_loaders(datasets, BATCH_SIZE)
    floors = predictor_floors(loaders)
    history = short_training(loaders, args.epochs)

    payload = {
        "rate": args.rate,
        "mask_info": mask_info,
        "predictor_floors": floors,
        "training_history": history,
    }
    out_dir = output_root / "pilot" / "fd004" / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"learnability_random_{int(args.rate*100):03d}.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved: {out_path}")


if __name__ == "__main__":
    main()
