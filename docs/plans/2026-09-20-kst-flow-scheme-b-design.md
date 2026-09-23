# KST-Flow 方案 B 架构设计

> 状态：已确认，作为 `kst_light_v2` 与 `kst_flow_v2` 的实现合同
>
> 日期：2026-09-20
>
> 适用范围：第三章规整表示、第四章联合概率预测、第五章风险转换与校准

## 1. 决策摘要

采用方案 B：先修复异步缺失感知的多尺度表示，再以同一变量级表示分别支撑点预测和联合概率预测。跨变量模块采用互斥设计，频域线性注意力（FLA）是默认主路径，缺失感知动态图仅作为对照候选；第四章使用 ProFITi 风格的三角条件流；第五章从该流的联合样本计算越界概率，并只在验证集拟合校准器。

完整数据流为：

```text
X_obs * M_obs, T_obs, M_obs, context
  -> MissingnessFeatures(delta_t, freshness, block_length, observed_ratio)
  -> MissingnessAwareMultiScaleKAFEncoder
       mask-normalized pre-convolution
       KAF temporal kernels
       patch content + position + scale + recency tokens
       hierarchical gated aggregation
  -> CrossVariableBlock(mode = fla | missing_graph | identity)
  -> z_var [B, N, D]
       ├─ KST-Light-v2: last-observation residual point decoder
       └─ KST-Flow-v2: QueryConditionAdapter -> triangular conditional flow
             -> joint samples [B, S, H, N]
             -> quantiles / intervals / risk probabilities
             -> validation-only Platt or isotonic calibration
```

旧模型 ID `kst_light` 和 `kst_probflow` 保持可导入、可验签，用于复现已完成的 pilot。新实现必须使用 `kst_light_v2` 和 `kst_flow_v2`，不能把旧 artifact 混入新模型的聚合结果。

## 2. 目标与非目标

### 2.1 目标

1. 让编码器显式区分真实观测、填充值、长时间未更新和连续离线，避免卷积把填充值当成实测值传播。
2. 给多尺度 patch 保留位置、尺度和新鲜度身份，避免无身份 softmax 池化丢失时序结构。
3. 为第三章提供可独立验证的点预测模型，为第四章提供训练密度与采样分布一致的联合概率模型。
4. 使分位数、区间和风险全部来自同一个联合样本源，形成可追溯的概率链。
5. 保持统一 split、normalization、missing mask、seed、风险标签和 validation-only 选择规则。

### 2.2 非目标

1. 不同时堆叠 FLA 和动态图；二者回答同一跨变量交互问题，默认堆叠会混淆消融归因。
2. 不把独立 `QuantileHead` 作为主分布的一部分，也不把直接分类式 `RiskHead` 作为第五章主风险路径。
3. 不根据 test 指标选择结构、超参数、校准器或报警阈值。
4. 不将当前单 seed 结果写成模型优越性或统计显著性证据。
5. 不直接复制外部仓库代码。外部方法用于机制参考；引入实现前必须记录来源、许可证和本仓库改写边界。

## 3. 当前实现证据与问题

### 3.1 已证实的工程事实

- `MultiScaleKAFEncoder` 已包含时间核、多尺度 patch 和 `FreqBlock`，具备方案 B 的基础骨架。
- 当前 patch token 只包含均值、标准差、斜率、缺失率和时间跨度；跨 patch 聚合前没有位置、尺度和新鲜度身份。
- 当前 `pre_conv` 直接作用于输入值，未使用 mask 归一化，缺失填充值会影响局部卷积。
- 当前 `KSTLight` 是编码器加线性或 MLP 头，没有动态图；它适合作为第三章旧版基线，不应原地改变科学语义。
- 当前 `KSTProbFlow` 同时使用动态图、低秩概率头、独立分位数头和直接风险头，输出来源分裂。

### 3.2 必须修复的概率缺陷

当前 `LowRankCopulaFlowHead.nll()` 只使用 `loc` 和 `scale`，低秩 `factors` 不参与似然；`sample()` 却使用 `factors` 产生相关噪声。因此训练分布与采样分布不一致，不能作为联合 copula flow 证据。`attention_diag_floor` 也没有进入有效计算。

主路径改用仓库现有 `ProFITiFlowHead` 的三角可逆变换及其 Jacobian 似然。实现门禁必须证明：同一组参数同时决定 NLL、采样、分位数和区间；固定生成器时采样可复现；联合参数获得非零有限梯度。

### 3.3 现有实验的解释边界

第三章单 seed 结果中，FF+GRU 平均 MAE 为 0.2293，KST-Light MLP 为 0.2775，KST-Light Linear 为 0.2893；block-offline 是最难条件。这说明当前 KST-Light 没有建立性能优势，不能据此继续扩大旧结构。该结果只用于定位架构缺口和设置改进门禁，不能作为多 seed 结论。

## 4. 输入、输出与形状合同

| 名称 | 形状 | 含义 |
|---|---:|---|
| `X_obs` | `[B, L, N]` | 归一化后的历史值；无观测位置的数值不得单独表达观测真实性 |
| `T_obs` | `[B, L]` 或 `[B, L, N]` | 历史时间戳，进入模型前统一到数据协议定义的时间单位 |
| `M_obs` | `[B, L, N]` | 观测掩码，1 表示真实观测 |
| `context` | `[B, C]` | 只含协议允许的工况变量 |
| `missing_features` | `[B, L, N, F_m]` | `delta_t`、freshness、连续缺失长度、局部观测率等可观测特征 |
| `z_var` | `[B, N, D]` | 每个传感器的规整历史表示 |
| `query_hidden` | `[B, H*N, D]` | 按 horizon-major、sensor-minor 顺序展开的未来查询表示 |
| `point_mean` | `[B, H, N]` | 点预测，采用最近观测值加预测增量 |
| `joint_samples` | `[B, S, H, N]` | 来自同一条件流的联合样本 |
| `risk_sensor` | `[B, H, N]` | 各传感器、各预测步的越界概率 |
| `risk_device` | `[B]` 或 `[B, H]` | 预注册聚合规则得到的设备风险 |

目标展平和还原必须由一个公共函数控制，禁止各头自行定义顺序。目标 mask 为 `[B, H, N]`，所有损失先按有效元素求和，再除以有效目标数。

## 5. 缺失感知特征

`MissingnessFeatures` 只使用预测时可获得的历史信息，输出至少包括：

- `delta_t`：当前位置距同一传感器上一次真实观测的时间差；窗口内从未观测时使用有界哨兵并设置 `has_history=0`。
- `freshness = exp(-delta_t / tau)`：`tau` 为可配置正值，记录在 scientific identity 中。
- `block_length`：截至当前位置连续缺失步数，经 `log1p` 和窗口长度归一化。
- `observed_ratio`：局部 patch 内真实观测比例。
- `has_history`：窗口内是否存在过真实观测。

所有递推只沿历史方向计算。测试必须通过“改变未来 mask 不影响历史特征”的因果性检查。数值特征使用 train-only 统计量或确定性归一化，不从 validation/test 拟合尺度。

## 6. 缺失感知多尺度 KAF 编码器

### 6.1 Mask-normalized pre-convolution

普通卷积替换为归一化卷积：

\[
\tilde{x}=\frac{\operatorname{Conv}_{w,\,bias=0}(x\odot m)}
{\operatorname{Conv}_{\mathbf 1}(m)+\epsilon}+b,
\]

其中 mask 分支使用固定全 1 卷积核统计同一感受野内的有效支持数，数值卷积在归一化前不加偏置，偏置只在归一化后加入。无有效观测的窗口输出零值和 `has_value=0`。测试要求填充值从 0 改为任意有限常数时，只要 `M_obs=0`，编码输出保持一致。

### 6.2 Patch token

每个 patch token 由以下信息相加或拼接后投影到 `D` 维：

```text
content = KAF(values, times, mask) + projected masked statistics
identity = position_embedding + scale_embedding + recency_embedding
token = LayerNorm(content + identity)
```

位置表示 patch 在历史窗口中的相对起止位置；尺度表示对应 `patch_len`；新鲜度表示 patch 末端距该变量最后观测的时间。全局 token 与局部 token 分层聚合，先在同一尺度内进行 mask-aware pooling，再通过门控融合各尺度和全局分支。空 patch 不参与 softmax 分母。

### 6.3 跨变量模块

统一接口：

```python
z_out, diagnostics = block(z_var, sensor_freshness, sensor_available)
```

允许三种模式：

- `fla`：默认主路径，复用并抽取现有 `FreqBlock`。
- `missing_graph`：候选消融，邻接计算加入节点可用性和陈旧度惩罚。
- `identity`：无跨变量交互消融。

缺失感知图邻接为：

\[
A_{ij}=\operatorname{softmax}_j\left(\frac{q_i k_j^\top}{\sqrt D}+b_{ij}
-\beta\log(1+\Delta t_j)+\log a_j\right),
\]

其中 `a_j` 表示传感器是否有历史观测。无历史节点不能成为有效消息源。图模式只有在三个 seed 的 validation 聚合中满足以下全部条件才可替代 FLA：宏平均 MAE 相对改善至少 2%，block-offline 条件改善，不存在持续退化条件，并且相对简单 MHA/FLA 的计算增量可接受。

## 7. 第三章点预测路径

点预测采用 last-value residual decoder：

\[
\hat y_{t+h,i}=x^{last}_{t,i}+g(z_i,q_{h,i},c),
\]

其中 `x_last` 由历史 mask 计算，并同时把 freshness、`has_history` 提供给解码器，使模型能够识别陈旧锚点。窗口内从未观测的传感器使用 train-only 中心值作为锚点并显式设置 `has_history=0`。

第一阶段损失为 masked Huber：

\[
\mathcal L_{point}=\frac{\sum m^y\operatorname{Huber}(y,\hat y)}{\sum m^y}.
\]

模型 ID 固定为 `kst_light_v2`。第三章只用该路径评价规整表示，不引入流或风险损失。

## 8. 第四章联合概率路径

`QueryConditionAdapter` 将 `z_var`、未来时间、传感器身份和 context 组合成 `[B,H*N,D]` 条件。`ProFITiFlowHead` 使用固定的查询顺序建立三角条件分解，训练目标为：

\[
\mathcal L_{stage2}=\mathcal L_{joint\_nll}+\lambda_{point}\mathcal L_{point},
\quad \lambda_{point}\in\{0.05,0.1,0.2\}.
\]

`lambda_point` 只根据 validation NLL、CRPS、Energy Score 和 MAE 的预注册排序规则选择。联合样本经同一反变换得到均值、分位数、95% 区间、CRPS 和 Energy Score。独立 `QuantileHead` 不进入新主路径。

模型 ID 固定为 `kst_flow_v2`。旧 `kst_probflow` 保持 legacy 状态，不能在新的第四章表格中标为方案 B。

## 9. 第五章样本风险与校准

风险源只来自 `joint_samples`。对预注册上下界 `l_{h,i},u_{h,i}`：

\[
p_{h,i}=\frac{1}{S}\sum_s \mathbb{I}
\left(y^{(s)}_{h,i}<l_{h,i}\ \lor\ y^{(s)}_{h,i}>u_{h,i}\right).
\]

设备级概率使用预注册聚合规则，例如 horizon 内最大传感器风险或“任一越界”的样本频率。聚合规则、阈值和标签定义写入 config 与 manifest。

训练完成后冻结预测器。Platt 与 isotonic 只在 validation 拟合和选择；test 只执行一次冻结评估。若 validation 或 test 不同时包含正负类，对应 AUROC、AUPRC 或 F1 按既有协议报告 `null`，不更换数据切分补齐类别。

## 10. 训练阶段与选择规则

| 阶段 | 可训练部分 | 目标 | 选择依据 |
|---|---|---|---|
| Stage 1 | 编码器、跨变量模块、点解码器 | masked Huber | validation macro MAE，兼看各缺失机制 |
| Stage 2 | `kst_flow_v2`；可从 Stage 1 初始化 | joint NLL + `lambda_point` Huber | validation NLL/CRPS/Energy Score/MAE 预注册规则 |
| Stage 3 | 仅校准器 | validation risk labels | validation ECE/Brier 与预注册 tie-break |

优化器从现有固定 AdamW 起步，学习率候选 `{1e-4, 2e-4, 5e-4, 1e-3}`，weight decay 候选 `{1e-5, 1e-4}`。先在中心条件单 seed 上筛选公共优化配置，再冻结配置进入结构消融；禁止为某个基线或 test 条件单独调参。使用 validation early stopping、梯度裁剪 1.0，并记录 scheduler、patience、best epoch 和完整 history。

## 11. 评价与消融矩阵

### 11.1 第三章最小消融

1. `legacy_kst_light`：历史参照，不与新 scientific key 混合。
2. `v2_without_missing_features`。
3. `v2_without_mask_normalized_conv`。
4. `v2_without_patch_identity`。
5. `v2_identity_cross_variable`。
6. `v2_fla`：默认完整模型。
7. `v2_missing_graph`：候选替代路径。

先在 MetroPT-3 中心条件做 validation-only 单 seed 筛选。完整模型通过门禁后，在 random 0/30/70、low-rate 30、block-offline 30 和 mixed 30 上运行 seeds 2026/2027/2028。主表报告 mean±std、有效样本数和每条件结果；单 seed pilot 单独标为历史诊断。

### 11.2 第四章与第五章门禁

- 分布合同：NLL 有限、sample 有限、Jacobian 有限、联合参数有梯度。
- 同源合同：均值、分位数、区间和风险使用相同 checkpoint、同一采样器和同一查询顺序。
- 概率指标：NLL、CRPS、Energy Score、PICP、MPIW；点指标只作为辅助。
- 风险指标：Brier、ECE、AUROC、AUPRC、Precision、Recall、F1，并保留类别成立条件。
- 采样稳定性：正式指标至少使用 `nsamples=100`，另以 50/200 做有限敏感性检查。

## 12. Artifact、身份与迁移

新 scientific key 至少包含：

```text
model_id, recipe_version, encoder_version, cross_variable_mode,
missing_feature_version, patch_lens, tau, flow_order,
lambda_point, seed, dataset, split_sha, normalization_sha,
mask_sha, target_schema_sha, evaluator_sha, code_sha
```

新 manifest 使用 `recipe_version: scheme_b_v1`。registry 和 runner 遇到 `kst_light_v2`/`kst_flow_v2` 时必须拒绝缺少这些字段的配置。旧 artifact 继续由旧 key 验签，汇总器按 `recipe_version` 分组；不得通过重命名目录、覆盖 manifest 或继承旧 checkpoint 伪装成 v2 结果。

如果从 `kst_light_v2` 初始化 `kst_flow_v2`，manifest 同时记录 source checkpoint SHA、source scientific key 和加载报告。只允许加载编码器及跨变量模块的形状匹配参数。

## 13. 外部方法来源与许可证边界

| 方法 | 用途 | 来源 | 采用边界 |
|---|---|---|---|
| KAFNet | 时间核与频域变量交互参考 | [论文](https://arxiv.org/abs/2508.01971)、[仓库](https://github.com/zhouziyu02/KAFNet) | 仓库未确认明确许可证；只依据论文机制和本仓库既有实现改写 |
| ProFITi | 三角条件流 | [AAAI 论文](https://ojs.aaai.org/index.php/AAAI/article/view/35494)、[仓库](https://github.com/yalavarthivk/ProFITi) | MIT；保留来源说明，复用前核对具体文件头 |
| t-PatchGNN | 异步 patch 与图交互参考 | [论文](https://proceedings.mlr.press/v235/zhang24bw.html)、[仓库](https://github.com/usail-hkust/t-PatchGNN) | 未确认明确许可证；只借鉴论文机制 |
| Hi-Patch | 分层 patch 聚合参考 | [论文](https://proceedings.mlr.press/v267/luo25r.html)、[仓库](https://github.com/qianlima-lab/Hi-Patch) | 许可证未确认；只借鉴论文机制 |
| TACTiS-2 | 联合概率预测评价参考 | [论文](https://arxiv.org/abs/2310.01327)、[仓库](https://github.com/ServiceNow/TACTiS) | Apache-2.0；若复用代码需保留通知 |
| HyperIMTS | 缺失感知变量关系参考 | [论文](https://proceedings.mlr.press/v267/li25bl.html) | 只用于设计对照与论证 |

## 14. 失败判据与回退

1. mask invariance、因果性或查询顺序测试失败：停止训练，修复数据合同。
2. `kst_light_v2` 在三个 seed 的中心条件和 block-offline 上均未优于旧 KST-Light，且仍明显落后 FF+GRU：保留修复后的输入合同，缩减结构复杂度，优先检查优化和 patch 聚合，不进入动态图扩展。
3. 动态图未满足第 6.3 节全部门禁：正式模型固定为 FLA，动态图只保留负结果消融。
4. 联合流出现 NLL/sample 不一致、非有限 Jacobian 或联合参数无梯度：第四章正式 run 不启动。
5. 校准器只改善 test 而不改善 validation：判为无效，不发布该校准结论。
6. 显存超出 RTX 3090 24GB：先降低 batch 并使用梯度累积，保持 query order、样本数和模型宽度；任何降配都形成新 scientific key。

## 15. 设计验收

方案 B 的实现只有同时满足以下条件才可用于论文正式表格：

- v2 模型身份与 legacy 身份完全隔离；
- 缺失填充值不影响 masked 位置的编码结果；
- patch 位置、尺度和新鲜度可被测试观测；
- FLA 与动态图在单次运行中互斥；
- 第四章似然、采样、区间和风险来自同一条件流；
- 风险校准只使用 validation；
- 三个 seed、统一协议和 artifact 验签全部通过。
