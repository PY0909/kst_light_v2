# P04 条件轴失效复盘（42 个 run 作废）

- 日期：2026-09-14
- 事件：CH2.5-P04-T01/T02 的 42 个点预测 pilot run 全部作废（AutoDL RTX 3090 单轮约 14.4 小时 GPU），另含此前两轮中断修复（`c7b9114` 设备接线、`19461c0` 种子+DataLoader）。作废由用户在审阅指标后发现，非由任何自动化检查发现。
- 结论：六个缺失条件对训练输入**零生效**。所有 run 使用同一份 `mixed@0.30` history mask；查询段未被人工掩蔽本身符合未来状态预测的统一评测合同，不能作为缺陷。

## 1. 根因（技术）

| # | 缺陷 | 位置 | 后果 |
|---|------|------|------|
| A | full-run 的 provider 工厂硬编码 smoke 常量 `mechanism="mixed", requested_rate=0.30`，`spec.missing_mode/target_missing_rate` 被解析进 spec、写进 manifest，但数据路径从未消费 | `pilot_runner.py` `_build_provider` | 六个条件共用一套 mask bundle；同种子下确定性基线跨条件 bit 级相同 |
| B（原误判） | `TimelineMaskedWindowDataset.__getitem__` 只对历史段做 `M_obs/X_obs` 替换，查询段未切片到 `M_q` | `masks.py` | 这是正确的预测评测合同：人工缺失只改变历史可观测信息；`M_q`、future target 与 valid_count 必须跨条件一致，确保 MAE/RMSE 比较的是同一批未来目标 |

两个根因叠加的表观信号（用户观察，全部核实）：

1. 5 个基线跨 6 条件指标 bit 级相同；kst_light 差异仅第 4 位小数且方向随机（CUDA 非确定性归约核噪声，非条件效应）。
2. valid_count 恒 5,703,810 = 27,161 窗口 × 10 步 × 21 传感器满额；这在统一未来目标评测下是正确且必需的公平性信号。
3. protocol 目录只有一套 mask bundle（`mixed_0.30_seed2026`），而矩阵设计需要 6 个唯一 history mask 条件。
4. RMSE≈0.99 / MAE≈0.83，标准化数据下常数预测理论 MAE≈0.80——模型整体处于均值预测水平（训练动力学另见 §4）。

## 2. 防线逐层失守分析

| 防线 | 为什么没拦住 |
|------|--------------|
| 单元测试（15 项 runner 测试） | 全部注入 fake trainer + stub `provider_factory`，真实 `_build_provider` 的条件接线**零断言**。`SMOKE_MAIN_*` 常量名暗示 smoke 用途，却被 full 路径默认复用——没有任何测试区分两者 |
| smoke（T02–T04） | 按设计只用主条件（mixed 0.30）验证"代码能跑"，不验证"条件轴有差异"——smoke 通过与条件接线正确无关 |
| 环境/公平性预检（T05） | 比对的是"两机一致"，不是"条件有差异"。所有 run 一致地用同一份错数据，跨机 SHA 比对反而全过 |
| validate-only 验收（T01/T02 勾选依据） | 只核完整性/闭合/去重/公平 SHA/test_count——**一致性检查检测不了系统性错误**。缺一条反向断言：不同条件必须产生不同 history mask SHA 且历史可观测率符合设置（query 侧则相反，必须逐字节恒定） |
| 免费信号被忽略 | (a) mask bundle 数量：实际 1 套 vs 设计 5 套，预检输出里 `mask_bundles_fingerprinted` 就有这个数；(b) 42 run 指标跨条件零方差——按流程要到 T03 汇总才有人看，太晚；(c) 计划条款"dry-run 人工复核条件与执行顺序"被勾选时只核了 key 字符串，未核数据层差异 |

## 3. 整改措施（落实为代码与清单，不是口号）

1. **防护回归测试（永久）**：新增 `code/tests/pilot/test_pilot_condition_axis.py`，在真实 FD004 数据上断言——矩阵条件 → provider 指纹的 mechanism/rate 匹配；不同条件产生不同 history mask bundle SHA；`random@0.00` 的历史 `M_obs` 全 1；历史可观测率随 random 缺失率单调下降（000 > 030 > 070）；所有条件的 `Y_q/M_q` 与 valid count 保持一致。
2. **运行时断言**：`execute()` 在拿到 provider 后校验指纹的 mechanism/requested_rate 与 spec 一致，未来任何工厂接线错误在第一个 run 即失败，而非 42 个 run 之后。
3. **manifest 可追溯性**：run manifest 增加 `protocol_sha`（split/normalization/三 split history mask SHA），T03 汇总时跨 run 校验同条件同 SHA、异条件异 SHA，并校验 query target identity 跨条件相同。
4. **验收条款修订**：P04-T01/T02、P05-T01/T02 的 validate-only 清单增加 `condition_axis_effective` 检查项；通用规则写入本文件——**任何批量 run 的验收必须同时检查实验轴确实改变模型输入，以及评测目标集合不被实验轴改变；完整性/一致性检查不能替代**。
5. **30 秒预检习惯**：批量执行前（或首批 run 完成后）人工核对"设计上的 artifact 数量"：本例为 history mask bundle 文件数 = 6 个唯一条件，且各条件 valid count 完全相同。

## 4. 附带发现（修复后重看，不在本轮阻塞）

- 训练动力学异常：train_loss 1.01→0.55 但 valid_score 自 epoch 3 起恶化（0.831→0.906），best checkpoint 在 epoch 3——stride=1 高度重叠窗口下的记忆化。条件轴修复后此现象可能仍在，属任务难度/正则问题，T03 汇总必须如实呈现，不得挑选性描述。

## 5. 处置

- 本机 `result/pilot/fd004/runs/` 已删除（2026-09-14）；AutoDL 侧同目录必须在重跑前删除，否则 resume 会因 matrix SHA 未变误判旧 manifest 已验证而跳过重跑。
- timeline mask artifact schema 升级为 v3，文件名前缀为 `v3_`；旧 v2 bundle 仅作为不可复用历史证据保留，预检不会把它纳入当前协议指纹。
- T01/T02 勾选撤销，progress.md 补记无效判定与本复盘引用。
- 修复走 commit→push→AutoDL pull→重跑预检（code 指纹变化）→重跑 42 run。
