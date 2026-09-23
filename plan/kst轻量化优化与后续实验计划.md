# KST 模型轻量化优化与后续实验计划

更新日期：2026-09-21  
适用模型：`kst_light_v2`，后续复用到 `kst_flow_v2`  
主数据集：MetroPT-3，协议 `metropt3_chrono_502030_v2`  
实验环境：conda 环境 `torch23`，单卡 CUDA

## 1. 当前基线

当前已完成一次 MetroPT-3、seed=2026 的 `kst_light_v2` 完整训练。该结果是 pilot 基线，不作为三 seed 正式结论。

| 项目 | 当前值 |
|---|---:|
| 参数量 | 252,384（约 25.24 万） |
| hidden_dim | 64 |
| n_layers | 2 |
| n_heads | 2 |
| kernel_count | 4 |
| preconv_dim | 16 |
| patch_lens | `[12, 24, 48]` |
| 跨变量模块 | FLA |
| 最优 validation MAE | 0.25514 |
| test MAE | 0.28210 |
| test RMSE | 0.62410 |
| 训练时间 | 2716.07 秒，约 45.3 分钟 |

基线结果目录：

```text
result/pilot/metropt3/runs/metropt3_chrono_502030_v2|point|kst_light_v2|residual|point_mixed_030|2026/
```

参数分布约为：KAF 编码器 177,867，FLA 跨变量模块 52,096，query adapter 18,196，decoder 4,225。由此确定优化优先级：先处理数据管线和 FLA/编码器宽度，保留缺失感知、freshness/recency、层次 patch 和 residual head。

## 2. 优化目标与证据边界

本计划同时优化三个目标，但不把它们混为一个指标：

1. **训练时长**：每 epoch 时间、总训练秒数、GPU 利用率和数据等待比例。
2. **模型规模**：可训练参数量、checkpoint 大小和推理显存。
3. **预测质量**：validation MAE/RMSE 以及有限性检查。

结构和超参数只能依据 validation 结果筛选；test 只在结构冻结后做一次最终评估。所有变体固定数据划分、归一化统计量、缺失 mask、seed、batch size、epoch、优化器和 checkpoint 选择规则。每次只改变一个因素，避免无法归因。

TSMixer、PatchTSMixer、Tiny Time Mixers、PatchTST 和 FFN-free/Sparse-VQ 只能作为设计启发，论文中的加速或压缩比例不能直接移植为 MetroPT-3 结论，必须通过本项目实验重新测量。

## 3. 阶段一：训练管线基准

### 3.1 目标

在模型完全不变的情况下，确认训练时间是否主要受数据加载和 CPU/GPU 同步影响。这一阶段不改变参数量，不改变模型指标。

### 3.2 固定配置

阶段一只使用一个训练管线配置：

```text
num_workers=4
pin_memory=True
persistent_workers=True
non_blocking=True
```

该配置作为后续结构实验的统一训练配方，不再执行 `num_workers=0/2/8` 对照，也不加入 AMP 变体。这样可以把阶段一的目标限定为确认固定的 GPU 数据管线可正常工作。

### 3.3 记录和判定

每个 run 必须记录：`run_id`、seed、模型 ID、代码 commit、数据协议 SHA、`num_workers`、每 epoch 秒数、总训练秒数、峰值显存、validation MAE/RMSE。

完成阶段一的条件是：`num_workers=4` 运行稳定、训练指标有限、GPU 设备链路有效，并且日志记录了每 epoch 时间和总训练时间。若 GPU 利用率仍低，先检查数据预取和 batch 拷贝，再进入结构压缩。

## 4. 阶段二：单因素结构压缩

### 4.1 顺序

保持阶段一选出的训练配方，按以下顺序运行 validation-only 或短训练筛选：

| 编号 | 单一变化 | 预期作用 | 风险 |
|---|---|---|---|
| A0 | 当前配置 | 结构基线 | 无 |
| A1 | `preconv_dim=8` | 减少卷积通道 | 低 |
| A2 | `kernel_count=3` | 减少 KAF 特征 | 低到中 |
| A3 | `hidden_dim=48` | 同时降低多处线性层开销 | 中 |
| A4 | `hidden_dim=32` | 进入更小模型规模 | 中到高 |
| A5 | `n_layers=1` | 减少一层 FreqBlock | 中 |
| A6 | `patch_lens=[12,24]` | 减少 patch 分支计算 | 中 |

不要在同一 run 中同时改变 hidden、层数、patch 和 kernel 数。A1/A2 若几乎不损失 validation MAE，再与 A3/A5 组合形成候选；组合实验必须重新命名并重新记录完整配置。

### 4.2 必要代码准备

正式跑 FLA 压缩前，补充以下可追溯配置字段，并写入 manifest：

```text
encoder_mlp_ratio
cross_variable_rank
cross_variable_mlp_ratio
```

当前部分 `FreqBlock` 的 `rank=64`、`mlp_ratio=4` 在模型内部固定，不能直接将未记录的硬编码变体作为正式结果。

## 5. 阶段三：FLA 低成本变体

### 5.1 变体

在 A0 或阶段二最优候选上，每次只改变一个 FLA 参数：

| 编号 | `cross_variable_rank` | `cross_variable_mlp_ratio` |
|---|---:|---:|
| F0 | 64 | 4 |
| F1 | 32 | 4 |
| F2 | 64 | 2 |
| F3 | 32 | 2 |

优先运行 F2，再运行 F1；F3 只在两者均无明显退化时运行。重点观察 validation MAE、每 epoch 时间和参数量，而不是只看 checkpoint 大小。

### 5.2 接受条件

进入正式候选的最低条件为：相对 A0 参数量下降至少 25%，训练总时间下降至少 20%，validation MAE 增幅不超过 1%～2%。若质量和效率互相冲突，保留 Pareto 候选，不使用 test 指标提前裁决。

## 6. 阶段四：轻量跨变量 Mixer

这是结构性替代实验，用于回答性能是否主要来自缺失感知和多尺度编码，而不是 FLA 的复杂交互。

候选结构：

```text
HierarchicalMissingnessKAFEncoder
    -> gated sensor/channel mixer
    -> QueryConditionAdapter
    -> residual decoder
```

实现要求：

- 保留 `M_obs`、freshness、recency/block 和层次 patch 输入。
- 使用共享的小型 sensor-mixing 投影和门控残差。
- 与 FLA 使用同一数据协议、mask、seed、训练配方和评估分母。
- 单独注册模型变体，不能覆盖 `kst_light_v2` 的 artifact 身份。

该阶段可参考 TSMixer/PatchTSMixer 的时间维与变量维混合思想。只有当轻量 Mixer 在 validation 上达到接受条件，才进入完整单种子训练；否则保留 FLA-lite 作为主候选。

## 7. 阶段五：回到 B0-B5 与 `kst_flow_v2`

轻量结构冻结后，恢复方案 B 的消融顺序，每次只改变一个因素：

```text
B0 当前 KST-Light 基准
B1 B0 + 优化器/Huber 配方
B2 B1 + recency/block 缺失特征
B3 B2 + 有序层次 patch
B4a B3 + FLA
B4b B3 + identity 对照
B5 B3 + missing-aware graph 动态图
```

在点预测编码器和跨变量结构冻结前，不启动 `kst_flow_v2` 正式概率实验。点模型确定后，再把同一轻量编码器复用到 `kst_flow_v2`，验证 NLL、采样、区间和风险输出是否来自同源 `ProFITiFlowHead`。

## 8. 运行模板

以下命令是模板，实际 `run_id`、checkpoint 和输出目录必须按运行时生成值填写。先执行 validation-only 或短训练，不直接启动三 seed 正式矩阵。

```bash
conda activate torch23
cd /home/new_work/new_work

python -u code/run_experiment.py \
  --dataset metropt3_chrono_502030_v2 \
  --model kst_light_v2 \
  --seed 2026 \
  --missing-rate 0.3 \
  --missing-mode mixed \
  --data-root /home/new_work/new_work/dataset \
  --output-dir /home/new_work/new_work/result \
  --epochs 5 \
  --batch-size 128 \
  --device cuda \
  --num-workers 4 \
  --progress
```

如果当前入口不接受某个新字段，先完成配置接口、registry、manifest 和测试，再运行实验。不得通过临时修改结果 JSON 伪造配置记录。

## 9. 结果记录表

每个变体在 `result/` 下单独保存，至少包含：

```text
run_id
model_id
recipe_version
seed
dataset
protocol_sha
code_sha
parameter_count
train_seconds
epoch_seconds
peak_gpu_memory_mb
num_workers
amp_dtype
best_validation_mae
best_validation_rmse
test_evaluation_count
checkpoint_path
```

推荐先维护以下汇总表，不填未经运行得到的数字：

| run_id | 变体 | 参数量 | 训练秒数 | 峰值显存 | val MAE | test eval 次数 | 状态 |
|---|---|---:|---:|---:|---:|---:|---|
| 待运行 | T0 (`num_workers=4`) | - | - | - | - | 0 | planned |
| 待运行 | F2 | - | - | - | - | 0 | planned |

## 10. 完成门禁

满足以下条件后，才可宣称轻量化方案完成：

1. 配置字段、模型 registry、manifest 和测试能够重建每个变体。
2. 至少完成 `num_workers=4` 的固定管线验证和一组 FLA-lite 对照，结果有限且 artifact 完整。
3. 选择依据只来自 validation 和效率指标，test 只评估冻结方案。
4. 最佳候选完成一次完整单 seed 训练，确认短训练结果没有反转。
5. 最佳候选完成三 seed 正式训练后，才更新论文结果表。
6. 点模型结构冻结、同源概率头门禁通过后，才启动 `kst_flow_v2`。

如果某阶段失败，保留失败 artifact 和日志，回退到上一阶段已验证候选，不删除或覆盖历史结果。

## 11. 外部方法参考

以下资料用于设计候选结构，不替代本项目在 MetroPT-3 上的验证：

- [TSMixer](https://arxiv.org/abs/2306.09364)：用时间维和变量维 MLP 混合替代部分注意力结构。
- [PatchTSMixer](https://huggingface.co/docs/transformers/en/model_doc/patchtsmixer)：结合 patch、gated attention 和 channel mixing，适合作为 FLA-lite 的设计参考。
- [Tiny Time Mixers](https://arxiv.org/abs/2401.03955)：强调小模型、多分辨率 patch 和通道交互。
- [PatchTST](https://arxiv.org/abs/2211.14730)：patching 和共享 backbone 可减少 token 计算及参数量。
- [Sparse-VQ / FFN-free Transformer](https://arxiv.org/abs/2402.05830)：可参考减少 FFN 的方向，但要保留本项目缺失感知输入并重新验证稳定性。

文献中的参数、MACs 或训练加速比例不能直接写入论文结果表；只有具备本项目 `run_id`、代码 SHA、协议 SHA 和完整 artifact 的结果才可用于本项目结论。
