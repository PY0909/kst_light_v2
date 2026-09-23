#!/bin/bash
# Phase 2 AutoDL 环境搭建脚本
# 在本地 Mac 执行，需要输入 AutoDL 密码

set -e

AUTODL_HOST="connect.nmb2.seetacloud.com"
AUTODL_PORT="31092"
AUTODL_USER="root"
AUTODL_PATH="/root/autodl-tmp"
LOCAL_TAR="/tmp/new_work_phase2.tar.gz"

echo "============================================"
echo "Phase 2: 实验环境搭建"
echo "============================================"

# Step 1: 重新打包（确保最新）
echo ""
echo "[Step 1/6] 打包代码..."
cd "/Users/ppy/研/00提交资料汇总/new_work"
tar --exclude='__pycache__' --exclude='.DS_Store' --exclude='*.pyc' \
    --exclude='.pytest_cache' --exclude='code/code.zip' \
    -czf "$LOCAL_TAR" code/ compare_code/ dataset/ requirement.txt
echo "  打包完成: $(ls -lh $LOCAL_TAR | awk '{print $5}')"

# Step 2: 上传
echo ""
echo "[Step 2/6] 上传到 AutoDL（需要输入密码）..."
scp -P "$AUTODL_PORT" "$LOCAL_TAR" "${AUTODL_USER}@${AUTODL_HOST}:${AUTODL_PATH}/"

# Step 3: 解压
echo ""
echo "[Step 3/6] 解压代码..."
ssh -p "$AUTODL_PORT" "${AUTODL_USER}@${AUTODL_HOST}" << 'ENDSSH'
cd /root/autodl-tmp
echo "  解压前目录内容:"
ls -la
tar -xzf new_work_phase2.tar.gz
rm new_work_phase2.tar.gz
echo "  解压后:"
ls -la code/ compare_code/ dataset/ requirement.txt
ENDSSH

# Step 4: 安装依赖
echo ""
echo "[Step 4/6] 安装 Python 依赖..."
ssh -p "$AUTODL_PORT" "${AUTODL_USER}@${AUTODL_HOST}" << 'ENDSSH'
cd /root/autodl-tmp
pip install -r requirement.txt 2>&1 | tail -5
echo ""
echo "=== 验证关键包 ==="
python3 -c "import torch; print(f'PyTorch {torch.__version__}, CUDA available: {torch.cuda.is_available()}')"
python3 -c "import numpy; print(f'NumPy {numpy.__version__}')"
python3 -c "import pandas; print(f'Pandas {pandas.__version__}')"
python3 -c "import sklearn; print(f'Scikit-learn {sklearn.__version__}')"
ENDSSH

# Step 5: 运行测试
echo ""
echo "[Step 5/6] 运行 pytest..."
ssh -p "$AUTODL_PORT" "${AUTODL_USER}@${AUTODL_HOST}" << 'ENDSSH'
cd /root/autodl-tmp
python3 -m pytest code/tests/ -q 2>&1
ENDSSH

# Step 6: 验证推理链路
echo ""
echo "[Step 6/6] 验证 checkpoint 推理..."
ssh -p "$AUTODL_PORT" "${AUTODL_USER}@${AUTODL_HOST}" << 'ENDSSH'
cd /root/autodl-tmp
echo "  检查已有 checkpoint..."
ls -la result/*/checkpoints/**/*.pt 2>/dev/null || echo "  无已有checkpoint，跳过推理验证（需正常开机后执行）"
ENDSSH

echo ""
echo "============================================"
echo "Phase 2.1-2.3 环境验证完成。"
echo "确认 5 个 Task 状态后，正常开机 GPU 模式跑实验。"
echo "============================================"
