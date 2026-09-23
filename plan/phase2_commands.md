# Phase 2 执行命令（在本地 Mac 终端逐条执行）

## Command 1: 上传代码包

```bash
scp -P 31092 /tmp/new_work_phase2.tar.gz root@connect.nmb2.seetacloud.com:/root/autodl-tmp/
```

## Command 2: 上传已有结果包（checkpoint + mask）

```bash
scp -P 31092 /tmp/existing_results.tar.gz root@connect.nmb2.seetacloud.com:/root/autodl-tmp/
```

## Command 3: SSH 登录 + 解压 + 安装依赖 + 运行测试

```bash
ssh -p 31092 root@connect.nmb2.seetacloud.com
```

然后在服务器上执行：

```bash
# 解压
cd /root/autodl-tmp
tar -xzf new_work_phase2.tar.gz
tar -xzf existing_results.tar.gz
rm new_work_phase2.tar.gz existing_results.tar.gz

# 安装依赖
pip install -r requirement.txt

# 验证环境
python3 -c "import torch; print(f'PyTorch {torch.__version__}, CUDA: {torch.cuda.is_available()}')"
python3 -c "import numpy, pandas, sklearn; print('numpy/pandas/sklearn OK')"

# 运行测试
python3 -m pytest code/tests/ -q

# 验证推理链路（无GPU时用CPU，只确认不报错）
python3 code/run_experiment.py \
  --dataset metropt3_chrono_502030 \
  --model kst_probflow \
  --seed 2026 \
  --missing-rate 0.3 \
  --missing-mode mixed \
  --history-len 168 \
  --pred-len 24 \
  --stride 60 \
  --data-root /root/autodl-tmp/dataset \
  --output-dir /root/autodl-tmp/result \
  --run-id phase2_smoke_test \
  --epochs 0 \
  --batch-size 4 \
  --nsamples 10 \
  --device cpu \
  --checkpoint /root/autodl-tmp/result/metropt3_chrono502030_mskaf_20260609_084658/checkpoints/metropt3_chrono_502030/kst_probflow/checkpoint_seed2026_best.pt
```
