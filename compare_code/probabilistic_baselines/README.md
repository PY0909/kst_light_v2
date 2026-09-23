# Unified Probabilistic Baselines

This directory adds five comparison baselines for the industrial probabilistic
forecasting task:

```text
patchtst_gaussian
ode_rnn
tpatchgnn
profiti
kafnet
```

The training entry point is:

```text
/home/work/new_work/compare_code/probabilistic_baselines/train_baseline.py
```

## Scope

The implementations are local PyTorch adaptations for the existing project
protocols. They are designed for fair comparison under the same data split,
missing mask, risk label rule, validation-only Platt calibration, and
validation-normal q95 alarm threshold.

Supported datasets:

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

TEP requires the Dataverse files under the configured `--data-root`.

## MetroPT-3 Unified Risk Protocol

For risk comparison, use:

```text
dataset = metropt3_chrono_502030
same dataset split
same seed
same missing mask
same risk label rule
q = 0.95
Platt calibration fitted on validation only
best-valid checkpoint selected by validation CRPS
```

The resulting metrics JSON contains:

```text
compare_risk_protocol = same_split_seed_mask_label_platt_validation_normal_q95_best_valid
risk_calibration_strategy = platt_validation_normal_q95
calibration_uses_test_labels = false
```

## Smoke Test

```bash
cd /home/work/new_work
PYTHONPATH=/home/work/new_work/code:/home/work/new_work/compare_code/probabilistic_baselines \
TMPDIR=/tmp /root/anaconda3/envs/torch23/bin/python -m pytest \
  /home/work/new_work/compare_code/probabilistic_baselines/tests -q
```

## Train on MetroPT-3

Replace `patchtst_gaussian` with any supported baseline model name.

```bash
cd /home/work/new_work
PYTHONPATH=/home/work/new_work/code:/home/work/new_work/compare_code/probabilistic_baselines \
TMPDIR=/tmp CUDA_VISIBLE_DEVICES=0 /root/anaconda3/envs/torch23/bin/python -u \
  /home/work/new_work/compare_code/probabilistic_baselines/train_baseline.py \
  --dataset metropt3_chrono_502030 \
  --model patchtst_gaussian \
  --seed 2026 \
  --missing-rate 0.3 \
  --missing-mode mixed \
  --history-len 168 \
  --pred-len 24 \
  --stride 60 \
  --data-root /home/work/new_work/dataset \
  --output-dir /home/work/new_work/result \
  --run-id metropt3_chrono502030_patchtst_gaussian_$(date +%Y%m%d_%H%M%S) \
  --epochs 50 \
  --batch-size 128 \
  --max-train-batches 0 \
  --max-eval-batches 0 \
  --nsamples 100 \
  --device cuda \
  --hidden-dim 64 \
  --levels 2 \
  --n-heads 4 \
  --patch-len 24 \
  --patch-stride 12 \
  --lr 1e-3 \
  --weight-decay 1e-4 \
  --lambda-point 0.1 \
  --sample-clip 30.0
```

## Train on C-MAPSS FD004

```bash
PYTHONPATH=/home/work/new_work/code:/home/work/new_work/compare_code/probabilistic_baselines \
TMPDIR=/tmp CUDA_VISIBLE_DEVICES=0 /root/anaconda3/envs/torch23/bin/python -u \
  /home/work/new_work/compare_code/probabilistic_baselines/train_baseline.py \
  --dataset cmapss_fd004 \
  --model ode_rnn \
  --seed 2026 \
  --missing-rate 0.3 \
  --missing-mode mixed \
  --history-len 50 \
  --pred-len 10 \
  --stride 1 \
  --data-root /home/work/new_work/dataset \
  --output-dir /home/work/new_work/result \
  --run-id cmapss_fd004_ode_rnn_$(date +%Y%m%d_%H%M%S) \
  --epochs 80 \
  --batch-size 128 \
  --max-train-batches 0 \
  --max-eval-batches 0 \
  --nsamples 100 \
  --device cuda \
  --hidden-dim 64 \
  --levels 2 \
  --risk-threshold 30
```

## Train on TEP

```bash
PYTHONPATH=/home/work/new_work/code:/home/work/new_work/compare_code/probabilistic_baselines \
TMPDIR=/tmp CUDA_VISIBLE_DEVICES=0 /root/anaconda3/envs/torch23/bin/python -u \
  /home/work/new_work/compare_code/probabilistic_baselines/train_baseline.py \
  --dataset tep \
  --model tpatchgnn \
  --seed 2026 \
  --missing-rate 0.3 \
  --missing-mode mixed \
  --history-len 50 \
  --pred-len 10 \
  --stride 10 \
  --data-root /home/work/new_work/dataset \
  --output-dir /home/work/new_work/result \
  --run-id tep_tpatchgnn_$(date +%Y%m%d_%H%M%S) \
  --epochs 50 \
  --batch-size 128 \
  --max-train-batches 0 \
  --max-eval-batches 0 \
  --nsamples 100 \
  --device cuda \
  --hidden-dim 64
```
