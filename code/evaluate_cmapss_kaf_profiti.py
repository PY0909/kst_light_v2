#!/usr/bin/env python
import argparse
import json
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from kaf_profiti.industrial.batch import IndustrialCollator
from kaf_profiti.industrial.cmapss import CMapssWindowDataset
from kaf_profiti.models.kaf_profiti import KAFProFITi, KAFProFITiConfig


def load_checkpoint(path: str, device: str):
    try:
        return torch.load(path, map_location=device, weights_only=False)
    except TypeError:
        return torch.load(path, map_location=device)


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate KAFNet-ProFITi on C-MAPSS")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--subset", default=None, choices=["FD001", "FD002", "FD003", "FD004"])
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--history-len", type=int, default=None)
    parser.add_argument("--pred-len", type=int, default=None)
    parser.add_argument("--stride", type=int, default=None)
    parser.add_argument("--async-mode", default=None, choices=["none", "random", "low_rate", "block_offline", "mixed"])
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--nsamples", type=int, default=20)
    parser.add_argument("--max-eval-batches", type=int, default=20)
    return parser.parse_args()


def main():
    args = parse_args()
    checkpoint = load_checkpoint(args.checkpoint, args.device)
    saved_args = checkpoint.get("args", {})
    config_dict = checkpoint["config"]
    config_dict["device"] = args.device
    config = KAFProFITiConfig(**config_dict)
    model = KAFProFITi(config)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    subset = args.subset or saved_args.get("subset", "FD001")
    history_len = args.history_len or int(saved_args.get("history_len", 50))
    pred_len = args.pred_len or int(saved_args.get("pred_len", 10))
    stride = args.stride or int(saved_args.get("stride", 1))
    async_mode = args.async_mode or saved_args.get("async_mode", "mixed")
    seed = args.seed if args.seed is not None else int(saved_args.get("seed", 42))
    dataset = CMapssWindowDataset(
        args.data_dir,
        subset=subset,
        split="test",
        history_len=history_len,
        pred_len=pred_len,
        stride=stride,
        async_mode=async_mode,
        seed=seed,
    )
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=0,
        collate_fn=IndustrialCollator(),
    )

    totals = {"nll": 0.0, "mse": 0.0, "mae": 0.0, "crps": 0.0}
    count = 0
    with torch.no_grad():
        for batch_idx, batch in enumerate(loader):
            if args.max_eval_batches and batch_idx >= args.max_eval_batches:
                break
            batch = batch.to(torch.device(args.device))
            hidden = model.distribution(batch)
            nll = model.flow_head.nll(batch.y_flat, hidden, batch.mq_flat).mean()
            samples = model.flow_head.sample(hidden, batch.mq_flat, nsamples=args.nsamples)
            mean = samples.mean(dim=1)
            totals["nll"] += float(nll.cpu())
            totals["mse"] += float(model.flow_head.masked_mse(batch.y_flat, mean, batch.mq_flat).cpu())
            totals["mae"] += float(model.flow_head.masked_mae(batch.y_flat, mean, batch.mq_flat).cpu())
            totals["crps"] += float(model.flow_head.crps(batch.y_flat, samples, batch.mq_flat).cpu())
            count += 1
    metrics = {key: value / max(count, 1) for key, value in totals.items()}
    metrics["batches"] = count
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
