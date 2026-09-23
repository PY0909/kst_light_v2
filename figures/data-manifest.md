# 第三章图片数据清单

> 合同版本：CH3-D2-v1
> 适用计划：[第三章实验任务计划](../plan/implementation-plan.md#11-第三章实验任务计划)
> 上游协议：[第三章实验协议](../plan/experiment-protocol.md)
> 表格合同：[第三章表格数据合同](../tables/table-schema.md)
> 机制路由：[方法—实验追溯表](../plan/review/method-experiment-traceability.md)

## 1. 总体数据与导出合同

1. 每张图只能读取本清单指定的一个聚合 source CSV。生成图的代码不得直接读取 raw metrics、prediction、NPZ、checkpoint、mask、profile index 或“最新”目录；source CSV 的生成步骤才可读取经过 validator 审核的 catalog。
2. 所有 source CSV 由运行时解析的 result root 下的 `ch3/outputs/csv/` 生成；本文的路径仅是相对结果根的逻辑位置，不含机器绝对路径、账号、主机或远程链接。
3. source CSV 的每条展示记录至少含 `provenance_id`、`source_artifact_sha`、`protocol_sha`、`unit`、预注册排序键和证据状态。预测图只接受 `run_level=formal + evidence_status=formal_validated`；效率图另须满足 profile 的 validated 状态。
4. source CSV 必须使用固定排序并保留完整预注册行。不得根据误差、显著性、速度或视觉效果选择行、实例、时间窗或模型；空数据、缺 CI、缺 provenance、非法 SHA、mock、smoke、tuning、fixture 或手填数值均使构建失败。
5. 每图必须同时导出 SVG 与 300 dpi PNG 到运行时解析的 `ch3/outputs/figures/`；PNG 的 dpi metadata 不低于 299。SVG 不得引用外部文件，导出时移除时间 metadata，使相同输入可确定性重建。
6. 图例、线型、marker、色板、坐标单位和子图顺序在实现前冻结。图注只说明测量对象与条件，不根据预期结果写结论；灰度打印仍须可区分。

## 2. Ch3-F1 观测 mask 与真实时间线（E0）

| 字段 | 合同 |
|---|---|
| source CSV | `Ch3-F1-mask-timeline.csv` |
| 数据范围 | MetroPT-3，seed 2026，test split 的首个预注册时间块；使用真实时间与 E0 的四种 history-only 协议 mask 语义，不按误差选择案例 |
| 主键与排序 | `(protocol, block_index, window_id, channel_id, timestamp)`；protocol 固定为 native sparse、linear interpolation、forward fill、masked input |
| 必需列 | protocol、block_index、window_id、channel_id、timestamp_seconds、observed_flag、display_value_flag、raw_mask_sha、adapter_config_sha、output_mask_sha、provenance_id、source_artifact_sha、protocol_sha、unit |
| 图形与坐标 | 四个协议面板共享真实时间横轴；纵轴为通道或观测状态，不以预测误差作为视觉编码 |
| 允许结论 | 仅展示四协议的时间和 mask 输入语义以及同一预注册块的观测规整方式；不宣称任一协议优于另一协议 |
| 证据门槛 | E0 formal artifact 与 protocol audit 均已验证；否则不生成图 |

## 3. Ch3-F2 缺失鲁棒性曲线（E4）

| 字段 | 合同 |
|---|---|
| source CSV | `Ch3-F2-robustness.csv` |
| 数据范围 | MetroPT-3 E4；四模型、random 0%/10%/30%/50%/70% 缺失率，以及 matched 30% 的四种缺失机制 |
| 主键与排序 | `(panel, model, condition_order)`；模型顺序为 LI+TCN、GRU-D、ODE-RNN、KST-Light；rate 和 mechanism 使用协议固定顺序 |
| 必需列 | panel、model、condition、condition_order、mae_mean、mae_ci_low、mae_ci_high、rmse_mean、rmse_ci_low、rmse_ci_high、realized_rate、relative_degradation_mean、relative_degradation_ci_low、relative_degradation_ci_high、provenance_id、source_artifact_sha、protocol_sha、unit |
| 图形与坐标 | 缺失率面板画 MAE/RMSE 均值线与 95% CI；机制面板保持 matched 30% 并显示相对 random 的退化及 CI；误差指标轴标明标准化空间 |
| 允许结论 | 仅描述给定缺失率或缺失机制下的 point-only 相对退化；不要求曲线单调，不能把图作为联合概率或风险证据 |
| 证据门槛 | E4 全部预注册 formal records 和公平性 hash 均通过；否则不生成图 |

## 4. Ch3-F3 受控消融效应（E5-A）

| 字段 | 合同 |
|---|---|
| source CSV | `Ch3-F3-ablation-effects.csv` |
| 数据范围 | MetroPT-3 E5-A，full 与 wo_time、wo_delta、wo_mask、wo_channel、wo_context、wo_multiscale、wo_cross_sensor 的同 seed 配对比较 |
| 主键与排序 | `(variant_order, seed)`；full 只作 reference，七个消融按固定预注册顺序展示 |
| 必需列 | variant、variant_order、relative_degradation_mean、relative_degradation_ci_low、relative_degradation_ci_high、mae_delta_mean、rmse_delta_mean、paired_seed_count、provenance_id、source_artifact_sha、protocol_sha、unit |
| 图形与坐标 | 以 full 为零基线的水平或点区间图；横/纵轴使用相对误差百分比，正值表示误差变差，并明确 95% CI |
| 允许结论 | 仅支持单因素模块对点预测表示的消融贡献；无改善或改善方向相反时按追溯表降级，不外推为概率、风险或决策能力 |
| 证据门槛 | 所有开关 manifest、同 seed 配对和 E5-A formal artifact 已验证；否则不生成图 |

## 5. Ch3-F4 效率 Pareto（E6）

| 字段 | 合同 |
|---|---|
| source CSV | `Ch3-F4-efficiency-pareto.csv` |
| 数据范围 | MetroPT-3 E1 六模型的冻结 checkpoint 与 E6 profile；RMSE 由 E1 formal 聚合提供，延迟/显存由对应 validated profile 提供 |
| 主键与排序 | `(model, seed)` 后按固定模型顺序聚合；不得按 Pareto 前沿或速度重排 |
| 必需列 | model、rmse_mean、rmse_ci_low、rmse_ci_high、sample_latency_seconds_mean、sample_latency_seconds_ci_low、sample_latency_seconds_ci_high、parameter_count、peak_memory_mib_mean、source_run_id、source_checkpoint_sha、benchmark_config_sha、profile_id、provenance_id、source_artifact_sha、protocol_sha、unit |
| 图形与坐标 | RMSE-推理延迟散点图；x 轴为 sample latency（seconds），y 轴为标准化空间 RMSE，参数量采用明确标记编码，延迟 CI 可视化 |
| 允许结论 | 只报告同一 E1 配置下的预测误差与计算开销关系；不以效率结果证明任一表示机制有效 |
| 证据门槛 | E1 formal 与 E6 validated profile 均存在，且 source run ID、checkpoint SHA、seed、benchmark config SHA 的双 provenance 完整；否则不生成图 |

## 6. Ch3-F5 外部有效性（E1-X）

| 字段 | 合同 |
|---|---|
| source CSV | `Ch3-F5-external-validity.csv` |
| 数据范围 | FD004 与 faulty TEP 的 E1-X；每个数据集包含 LI+TCN、GRU-D、ODE-RNN、KST-Light 三 seed 正式预测聚合 |
| 主键与排序 | `(dataset, model, seed)`；数据集顺序为 FD004、TEP，模型使用固定主对比顺序 |
| 必需列 | dataset、model、relative_mae_to_li_tcn_mean、relative_mae_to_li_tcn_ci_low、relative_mae_to_li_tcn_ci_high、relative_rmse_to_li_tcn_mean、relative_rmse_to_li_tcn_ci_low、relative_rmse_to_li_tcn_ci_high、bootstrap_unit_type、provenance_id、source_artifact_sha、protocol_sha、unit |
| 图形与坐标 | FD004 与 TEP 分面；仅画各数据集内相对 LI+TCN 的误差比值及 95% CI，参考线为 1.0 |
| 允许结论 | 仅限定 E1 point-only 比较在两个外部数据集中的范围；禁止跨数据集合并原始 MAE/RMSE 或将其外推为风险能力 |
| 证据门槛 | FD004 engine 与 TEP `faultNumber:simulationRun` 自然单位 bootstrap、全部 expected formal rows 与公平性记录均已验证；否则不生成图 |

## 7. 编号、消费与 QA 边界

1. Ch3-F1 至 Ch3-F5 连续、无重号、无缺号，每张图只消费本清单唯一 source CSV。
2. Ch3-F1 至 Ch3-F3、Ch3-F5 只消费 formal prediction aggregation；Ch3-F4 是唯一可消费 validated profile 的图，并且只能读取由 Ch3-T7 双 provenance 聚合生成的 source CSV，不能直接扫描 profile index。
3. 构建前校验 source CSV 非空、列完整、排序键完整、CI/单位/provenance/SHA 完整；构建后校验 SVG、PNG、PNG dpi、无外部 SVG 引用和可复现哈希。人工 QA 只检查标签、误差条、遮挡和灰度可读性，不改变数据或选例。

Ch3-F1 至 Ch3-F5 编号连续、无重号、无缺号。验证命令：

```bash
rg -n 'Ch3-F[1-5]' figures/data-manifest.md
```

预期：5 张图编号全部出现且各自有独立小节与唯一 source CSV。
