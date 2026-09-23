# TCN-Gaussian Baseline

This directory contains an independent TCN-Gaussian baseline for the industrial
probabilistic forecasting protocols in `/home/work/new_work/code`.

The implementation follows the standard causal dilated residual TCN design used
by Bai, Kolter, and Koltun's TCN work, but the code here is a local PyTorch
implementation for this project rather than a vendored copy.

Reference implementation and paper:

- Code: `https://github.com/locuslab/TCN`
- Paper: `https://arxiv.org/abs/1803.01271`

## Model

```text
[X_obs, M_obs, context]
  -> causal dilated residual TCN
  -> final hidden state
  -> diagonal Gaussian head
  -> mean, scale for future sensors
```

The model outputs independent Gaussian distributions for each future
time-channel query point. It is intended as a regular-sampling baseline with
mask channels, not as an irregular-event model.

## Supported Datasets

The baseline reuses the project dataset protocols:

```text
metropt3
metropt3_chrono_602020
metropt3_chrono_502030
cmapss_fd001
cmapss_fd002
cmapss_fd003
cmapss_fd004
tep
```

## Smoke Test

```bash
PYTHONPATH=/home/work/new_work/code:/home/work/new_work/TCN-Gaussian \
TMPDIR=/tmp /root/anaconda3/bin/conda run -n torch23 python -m pytest \
  /home/work/new_work/TCN-Gaussian/tests -q
```

## Train on MetroPT-3

```bash
PYTHONPATH=/home/work/new_work/code:/home/work/new_work/TCN-Gaussian \
TMPDIR=/tmp CUDA_VISIBLE_DEVICES=0 /root/anaconda3/bin/conda run -n torch23 python -u \
  /home/work/new_work/TCN-Gaussian/train_tcn_gaussian.py \
  --dataset metropt3_chrono_502030 \
  --seed 2026 \
  --missing-rate 0.3 \
  --missing-mode mixed \
  --history-len 168 \
  --pred-len 24 \
  --stride 60 \
  --data-root /home/work/new_work/dataset \
  --output-dir /home/work/new_work/result \
  --run-id metropt3_chrono502030_tcn_gaussian_$(date +%Y%m%d_%H%M%S) \
  --epochs 50 \
  --batch-size 128 \
  --max-train-batches 0 \
  --max-eval-batches 0 \
  --nsamples 100 \
  --device cuda \
  --hidden-dim 64 \
  --levels 5 \
  --kernel-size 3 \
  --dropout 0.1 \
  --lr 1e-3 \
  --weight-decay 1e-4
```

## Train on C-MAPSS FD004

```bash
PYTHONPATH=/home/work/new_work/code:/home/work/new_work/TCN-Gaussian \
TMPDIR=/tmp CUDA_VISIBLE_DEVICES=0 /root/anaconda3/bin/conda run -n torch23 python -u \
  /home/work/new_work/TCN-Gaussian/train_tcn_gaussian.py \
  --dataset cmapss_fd004 \
  --seed 2026 \
  --missing-rate 0.3 \
  --missing-mode mixed \
  --history-len 50 \
  --pred-len 10 \
  --stride 1 \
  --data-root /home/work/new_work/dataset \
  --output-dir /home/work/new_work/result \
  --run-id cmapss_fd004_tcn_gaussian_$(date +%Y%m%d_%H%M%S) \
  --epochs 80 \
  --batch-size 128 \
  --max-train-batches 0 \
  --max-eval-batches 0 \
  --nsamples 100 \
  --device cuda \
  --hidden-dim 64 \
  --levels 4 \
  --kernel-size 3 \
  --dropout 0.1 \
  --risk-threshold 30
```

## Train on TEP

```bash
PYTHONPATH=/home/work/new_work/code:/home/work/new_work/TCN-Gaussian \
TMPDIR=/tmp CUDA_VISIBLE_DEVICES=0 /root/anaconda3/bin/conda run -n torch23 python -u \
  /home/work/new_work/TCN-Gaussian/train_tcn_gaussian.py \
  --dataset tep \
  --seed 2026 \
  --missing-rate 0.3 \
  --missing-mode mixed \
  --history-len 96 \
  --pred-len 24 \
  --stride 24 \
  --data-root /home/work/new_work/dataset \
  --output-dir /home/work/new_work/result \
  --run-id tep_tcn_gaussian_$(date +%Y%m%d_%H%M%S) \
  --epochs 50 \
  --batch-size 128 \
  --max-train-batches 0 \
  --max-eval-batches 0 \
  --nsamples 100 \
  --device cuda \
  --hidden-dim 64 \
  --levels 5 \
  --kernel-size 3 \
  --dropout 0.1
```

## Outputs

Results are saved in the same run-level layout as the main project:

```text
{output_dir}/{run_id}/
  metrics/{dataset}/tcn_gaussian/metrics_seed{seed}.json
  checkpoints/{dataset}/tcn_gaussian/checkpoint_seed{seed}.pt
  checkpoints/{dataset}/tcn_gaussian/checkpoint_seed{seed}_best.pt
  training_history/{dataset}/tcn_gaussian/history_seed{seed}.json
  predictions/{dataset}/tcn_gaussian/mean_seed{seed}.npy
  predictions/{dataset}/tcn_gaussian/samples_seed{seed}.npy
  predictions/{dataset}/tcn_gaussian/risk_seed{seed}.npy
```
