#!/usr/bin/env python
import argparse
import json
import time
from pathlib import Path

import torch
from torch.optim import AdamW
from torch.utils.data import DataLoader

from kaf_profiti.industrial.batch import IndustrialCollator
from kaf_profiti.industrial.metropt import MetroPTWindowDataset
from kaf_profiti.models.kaf_profiti import KAFProFITi, KAFProFITiConfig


def parse_args():
    parser = argparse.ArgumentParser(description="Train KAFNet-ProFITi on MetroPT-3")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--history-len", type=int, default=60)
    parser.add_argument("--pred-len", type=int, default=12)
    parser.add_argument("--stride", type=int, default=120)
    parser.add_argument(
        "--async-mode",
        default="mixed",
        choices=["none", "random", "low_rate", "block_offline", "mixed"],
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output-dir", default="/root/autodl-tmp/result")
    parser.add_argument("--hidden-dim", type=int, default=32)
    parser.add_argument("--te-dim", type=int, default=5)
    parser.add_argument("--kernel-count", type=int, default=4)
    parser.add_argument("--n-layers", type=int, default=2)
    parser.add_argument("--n-heads", type=int, default=2)
    parser.add_argument("--flow-layers", type=int, default=2)
    parser.add_argument("--preconv-dim", type=int, default=8)
    parser.add_argument("--lambda-point", type=float, default=0.1)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--max-train-batches", type=int, default=20)
    parser.add_argument("--max-val-batches", type=int, default=10)
    parser.add_argument("--num-workers", type=int, default=0)
    return parser.parse_args()


def run_epoch(model, loader, optimizer, device, max_batches: int, train: bool):
    total_loss = 0.0
    total_batches = 0
    model.train(train)
    context = torch.enable_grad() if train else torch.no_grad()
    with context:
        for batch_idx, batch in enumerate(loader):
            if max_batches and batch_idx >= max_batches:
                break
            batch = batch.to(device)
            if train:
                optimizer.zero_grad(set_to_none=True)
                loss = model.loss(batch, nsamples_for_point=1)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
            else:
                hidden = model.distribution(batch)
                loss = model.flow_head.nll(batch.y_flat, hidden, batch.mq_flat).mean()
            total_loss += float(loss.detach().cpu())
            total_batches += 1
    return total_loss / max(total_batches, 1)


def main():
    args = parse_args()
    torch.manual_seed(args.seed)
    device = torch.device(args.device)
    train_set = MetroPTWindowDataset(
        args.data_dir,
        split="train",
        history_len=args.history_len,
        pred_len=args.pred_len,
        stride=args.stride,
        async_mode=args.async_mode,
        seed=args.seed,
    )
    valid_set = MetroPTWindowDataset(
        args.data_dir,
        split="valid",
        history_len=args.history_len,
        pred_len=args.pred_len,
        stride=args.stride,
        async_mode=args.async_mode,
        seed=args.seed,
    )
    collate = IndustrialCollator()
    train_loader = DataLoader(
        train_set,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        collate_fn=collate,
    )
    valid_loader = DataLoader(
        valid_set,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        collate_fn=collate,
    )

    config = KAFProFITiConfig(
        num_sensors=15,
        context_dim=3,
        hidden_dim=args.hidden_dim,
        te_dim=args.te_dim,
        kernel_count=args.kernel_count,
        n_layers=args.n_layers,
        n_heads=args.n_heads,
        flow_layers=args.flow_layers,
        preconv_dim=args.preconv_dim,
        lambda_point=args.lambda_point,
        device=args.device,
    )
    model = KAFProFITi(config)
    optimizer = AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)

    history = []
    for epoch in range(1, args.epochs + 1):
        train_loss = run_epoch(model, train_loader, optimizer, device, args.max_train_batches, True)
        valid_loss = run_epoch(model, valid_loader, optimizer, device, args.max_val_batches, False)
        record = {"epoch": epoch, "train_loss": train_loss, "valid_nll": valid_loss}
        history.append(record)
        print(json.dumps(record, ensure_ascii=False))

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = output_dir / f"kaf_profiti_metropt_{int(time.time())}.pt"
    torch.save(
        {
            "model_state": model.state_dict(),
            "config": config.to_dict(),
            "args": vars(args),
            "history": history,
        },
        checkpoint,
    )
    print(f"checkpoint={checkpoint}")


if __name__ == "__main__":
    main()
