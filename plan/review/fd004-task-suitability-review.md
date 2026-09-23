# FD004 任务适配性复盘（CH34-S00 冻结登记）

- 日期：2026-09-15
- 状态：`diagnostic_only`
- 目的：登记 FD004 已完成的两个连续传感器预测 run，作为"数据任务不适配"的实证，并把它与已证明的代码链路正确性区分开。

## 1. 结论（TL;DR）

**代码链路有效，数据任务不适配。** FD004 上的"未来连续传感器数值回归"在 `history=50 / pred=10` 设置下近似不可学：21 个传感器在 cycle 层面几乎无时间自相关，学习模型未能稳定超过"零预测 / 全局均值"，因此该任务不能区分模型，也不能支撑缺失强度与机制比较。据此，CH2.5-P04~P07 冻结，改由第 13 节以 MetroPT-3 为主数据集重启第三、四章单种子实验。这两个 run 保留为 `diagnostic_only` 证据，不进入任何第三、四章 formal 结论或模型排序。

## 2. 已核实事实

| 证据 | 结果 | 解释 |
|---|---:|---|
| FD004 连续性 / 窗口边界 / engine 隔离 / mask 可复现 | 32/32 checks passed | 两个 run 不是由跨 engine、窗口错位、归一化泄漏或条件 mask 复用造成 |
| FD004 传感器 cycle 级 lag-1 自相关（21 通道，249 engines 平均） | ≈ 0（−0.012 … +0.021） | 裸传感器瞬时值近白噪声，退化趋势被逐 cycle 噪声淹没 |
| 未来窗口内 lag-1 自回归下限 | MAE ≈ 0.92 | 比常数预测（≈0.76）更差，无时间结构可学 |
| 持久性（last-observed 外推 10 步） | test MAE ≈ 1.023 / RMSE ≈ 1.402 | 未来受未提供的工况切换强烈影响，persistence 不可用 |
| 零预测下限 | test MAE ≈ 0.8305 / RMSE ≈ 0.9927 | 学习模型未稳定超过它 |

## 3. 两个 run 的登记信息

以下全部只读自 `result/pilot/fd004/runs/` 下的 manifest / metrics / checkpoint，未改写任何 artifact。

### 3.1 `point_random_000`（random@0.00）

| 字段 | 值 |
|---|---|
| scientific key | `cmapss_fd004|point|li_tcn|linear|point_random_000|2026` |
| condition / missing_mode / rate | `point_random_000` / random / 0.00 |
| seed / split_seed / mask_seed | 2026 / 2026 / 2026 |
| device / status | cuda / completed |
| split_sha256 | `61c7db91a38f1f350a79ea3632e2456cf247aeffcb5b3c8f24f98746d8345880` |
| normalization_sha256 | `2cb43b19d1d1d382b8440bd5b746c911be5c2ead3bbcfd0e2bf79b5724749f1c` |
| mask_sha (train/valid/test) | `a1ea4503…` / `a1ea4503…` / `dd4d270a…` |
| checkpoint_sha256 | `1b7ca91e408ba46d579246953731b3f3bf1ba009f0301d1802be8084c3d9264c` |
| test MAE / RMSE / valid_count | 0.828211 / 0.992050 / 5703810 |
| 训练动力学 | train loss 1.005→0.950（80 epoch 几乎不动）；valid ~0.829–0.835 平稳，best 约 epoch 5 |

### 3.2 `point_random_030`（random@0.30）

| 字段 | 值 |
|---|---|
| scientific key | `cmapss_fd004|point|li_tcn|linear|point_random_030|2026` |
| condition / missing_mode / rate | `point_random_030` / random / 0.30 |
| seed / split_seed / mask_seed | 2026 / 2026 / 2026 |
| device / status | cuda / completed |
| split_sha256 | `61c7db91…`（同 3.1） |
| normalization_sha256 | `2cb43b19…`（同 3.1） |
| mask_sha (train/valid/test) | `75423b67…` / `72515dae…` / `61cd5017…` |
| checkpoint_sha256 | `f5d3389cb1a641f0730d38471dfb756390b47338c9792e59c312fc0e9c6c96ff` |
| test MAE / RMSE / valid_count | 0.830428 / 0.992914 / 5703810 |
| 训练动力学 | train loss 1.007→0.545（正常下降）；valid 0.831→0.90+ 持续恶化，best 停在 epoch 1（记忆化/过拟合，未学到可泛化规律） |

### 3.3 与 naive floor 同表

| 方法 | test MAE | test RMSE |
|---|---:|---:|
| 学习模型 random@0% | 0.8282 | 0.9920 |
| 学习模型 random@30% | 0.8304 | 0.9929 |
| 零预测 | 0.8305 | 0.9927 |
| 窗口内均值（常数） | ≈0.76 | — |
| 持久性（last-observed 外推） | 1.0231 | 1.4016 |

学习模型与零预测在数值上不可分辨（差异在第二位小数之后），常数预测略优于两者——表明该任务下限即"常数/零预测"，不存在可供模型展现相对优势的信号。

## 4. 代码链路 vs 数据任务不适配的判定

本两 run 指标弱**不能**归结为以下已经验证正确的项：

- 窗口对齐（`Y_q[0]` 确实是 `X_obs[-1]` 的下一周期）；
- train/valid engine 隔离与窗口规范排序；
- train-only 归一化（valid/test 不参与统计量选择）；
- timeline-first mask 的跨环境可复现性（mask 内容 SHA 与 manifest 一致）。

因此结论为：原始 FD004 连续传感器值作为预测目标，在缺失协议下不具备可区分的可学习信号——属**数据/任务适配性**问题，而非工程正确性问题。未来若复用 FD004，应改为 RUL / 健康指数 / 故障风险目标（退化信号更可学，也与论文风险贡献对齐），另立新协议与新 SHA。

## 5. 冻结边界

- CH2.5-P04~P07 冻结，第 13 节为新的第三/四章单种子执行入口。
- 本两个 run 保存于 `result/pilot/fd004/runs/`，标记 `diagnostic_only`，不补跑剩余 47/49 个 run。
- `result/` 下所有 artifact 未作任何手工修改；本文档仅登记既有字段。
