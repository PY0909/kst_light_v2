# 第三章表格数据合同

> 合同版本：CH3-D2-v1
> 适用计划：[第三章实验任务计划](../plan/implementation-plan.md#11-第三章实验任务计划)
> 上游协议：[第三章实验协议](../plan/experiment-protocol.md)
> 机制路由：[方法—实验追溯表](../plan/review/method-experiment-traceability.md)

## 1. 通用生成规则

1. 所有表格由 `code/build_ch3_outputs.py` 从 formal catalog 与独立 profile catalog 聚合生成；任何单元格不得手工填写、不得从 legacy `code/build_tables.py` 的 Table 1-7 复制。
2. MAE/RMSE 为 train normalization 标准化空间内的全局点指标，由 absolute-error sum、squared-error sum 与有效点数计算；论文引用时必须注明标准化空间口径。
3. 相对指标统一为 `100 * (metric_condition - metric_reference) / metric_reference`，正值表示误差变差；reference 必须在相同 model、seed 和数据集内配对。
4. 三 seed 聚合：先计算每 seed 全量有效目标点估计，再报告算术 mean、sample std（`ddof=1`）与 95% CI；CI 由分层成对 bootstrap 产生（10000 次重采样、bootstrap seed 2026、percentile `[2.5%, 97.5%]`，重采样单位按协议第 7 节）。
5. 单 seed 条件只报告点估计，不显示标准差、显著性标记或 `±0`。
6. 每个数值必须可追溯到 `run_id -> prediction/metrics -> checkpoint -> resolved config -> split/mask/protocol/code hash`；表格产物同时导出机读 CSV 到 `result/ch3/outputs/csv/`。
7. 生成器从运行时解析的 result root 写入输出；本文中的 `result/ch3/...` 仅表示相对结果根的 artifact 逻辑位置，不构成机器路径或远程链接。
8. 表格原始 CSV 固定保存未格式化数值与 `provenance_id`；Markdown 表才可格式化三 seed 的 `mean ± std [95% CI]`。固定排序由本合同定义，不能按 test 排名重排。

## 2. 字段、单位与输出命名约定

| 字段类别 | 原始 CSV 单位或编码 | 展示规则 |
|---|---|---|
| MAE、RMSE | train-normalization 标准化空间单位 | 原始 CSV 保留全精度；正文和 Markdown 标注“标准化空间” |
| 相对误差/相对退化 | percent，正值表示误差变差 | 必须给出同 seed、同数据集、同 reference 的配对定义 |
| 请求/实际缺失率 | fraction；展示时可格式化为 percent | 不得以请求率代替实际率 |
| 参数量 | count | 不对确定性参数量伪造 std 或 CI |
| 完整训练时间、延迟 | seconds；latency 同时记录 batch/sample 口径 | 仅 Ch3-T7/F4 可使用 profile latency 字段 |
| 峰值显存 | MiB | 仅 Ch3-T7 可直接使用 profile 字段 |

| 表格 | 固定输出 CSV | 固定行排序 |
|---|---|---|
| Ch3-T1 | `Ch3-T1-data-protocol.csv` | protocol、seed |
| Ch3-T2 | `Ch3-T2-main-comparison.csv` | 固定模型顺序、seed |
| Ch3-T3 | `Ch3-T3-missing-rate.csv` | 固定模型顺序、rate、seed |
| Ch3-T4 | `Ch3-T4-missing-mechanism.csv` | 固定模型顺序、mechanism、seed |
| Ch3-T5 | `Ch3-T5-ablation.csv` | full 后固定消融顺序、seed |
| Ch3-T6 | `Ch3-T6-sensitivity.csv` | factor、预注册 value、seed |
| Ch3-T7 | `Ch3-T7-efficiency.csv` | 固定模型顺序、seed |
| Ch3-T8 | `Ch3-T8-external-validity.csv` | dataset、固定模型顺序、seed |

## 3. Ch3-T1 数据协议有效性（E0）

| 字段 | 合同 |
|---|---|
| 回答的问题 | 结论是否依赖泄漏、插值或不一致 mask |
| 主键 | `(protocol, seed)`，protocol ∈ {`native_sparse`, `linear_interpolation`, `forward_fill`, `masked_input`}，seed ∈ {2026, 2027, 2028} |
| 行数 | 4 协议 × 3 seeds = 12 |
| 指标列 | requested/realized missing rate、MAE、RMSE、同 seed 相对 `native_sparse` 的相对误差 |
| 聚合 | 每协议三 seed mean±std 与 95% CI；相对列按同 seed 配对 |
| artifact 来源 | `configs/ch3/matrices/e0_protocol.yaml` 展开 formal catalog + `result/ch3/protocol-audit/e0-protocol-audit.json` |
| 允许结论 | 仅陈述各 history-only 协议在同一 KST-Light、同一预算下的公平性差异；不预设 native sparse 最优，方向由真实 artifact 决定 |
| 章节路由 | 3.6.2 |

## 4. Ch3-T2 MetroPT-3 主对比（E1）

| 字段 | 合同 |
|---|---|
| 回答的问题 | 规整表示是否优于合理表示基线 |
| 主键 | `(model, seed)`，model ∈ {`li_tcn`, `ff_gru`, `masked_tcn`, `gru_d`, `ode_rnn`, `kst_light`} |
| 行数 | 6 模型 × 3 seeds = 18（其中 `kst_light` 3 行复用 E0 `native_sparse` source run，标注 `source_run_id`） |
| 指标列 | MAE、RMSE、同 seed 相对 `li_tcn` 的相对误差、参数量、完整训练时间 |
| 聚合 | 三 seed mean±std 与 95% CI；相对列同 seed 配对 |
| artifact 来源 | `configs/ch3/matrices/e1_metropt_main.yaml` 展开 formal catalog；训练时间取 formal run history，推理效率字段不进本表（归 Ch3-T7） |
| 允许结论 | 统一轻量头、统一预算下的 point-only 表示总体比较；不要求 `kst_light` 排名第一 |
| 章节路由 | 3.6.3 |

## 5. Ch3-T3 缺失率鲁棒性（E4 random 扫描）

| 字段 | 合同 |
|---|---|
| 回答的问题 | 缺失加剧时表示是否稳定 |
| 主键 | `(model, rate, seed)`，model ∈ {`li_tcn`, `gru_d`, `ode_rnn`, `kst_light`}，rate ∈ {0.00, 0.10, 0.30, 0.50, 0.70}（random 模式） |
| 行数 | 4 模型 × 5 缺失率 × 3 seeds = 60 |
| 指标列 | realized rate、MAE、RMSE、同 model+seed 相对 rate 0.00 的相对退化率 |
| 聚合 | 每 (model, rate) 三 seed mean±std；reference 为同 model+seed 的 random 0% 条件，分母非有限或不大于 0 时该行标记协议失败而非省略 |
| artifact 来源 | `configs/ch3/matrices/e4_missing_rates.yaml` 展开 formal catalog |
| 允许结论 | 缺失率上升下的相对退化比较；不预设曲线单调，异常方向保留并移交评审 |
| 章节路由 | 3.6.4 |

## 6. Ch3-T4 缺失机制鲁棒性（E4 matched 机制）

| 字段 | 合同 |
|---|---|
| 回答的问题 | 相同缺失总量下，缺失结构（机制）是否改变表示稳定性 |
| 主键 | `(model, mechanism, seed)`，mechanism ∈ {`random`, `low_rate`, `block_offline`, `mixed`}，均 matched 实际缺失率 0.30 ± 0.01 |
| 行数 | 4 模型 × 4 机制 × 3 seeds = 48（random 12 行复用 Ch3-T3 来源、mixed 12 行复用 E1 来源，均标注 `source_run_id`） |
| 指标列 | realized rate、MAE、RMSE、同 model+seed 相对 `random` 0.30 的相对误差 |
| 聚合 | 每 (model, mechanism) 三 seed mean±std 与 95% CI |
| artifact 来源 | `configs/ch3/matrices/e4_missing_mechanisms.yaml` 展开 formal catalog + 复用 manifest |
| 允许结论 | 缺失机制结构对表示的影响；不得因某机制表现不利而删除该行 |
| 章节路由 | 3.6.4 |

## 7. Ch3-T5 受控消融（E5-A）

| 字段 | 合同 |
|---|---|
| 回答的问题 | 每个表示模块是否有独立贡献 |
| 主键 | `(variant, seed)`，variant ∈ {`full`, `wo_time`, `wo_delta`, `wo_mask`, `wo_channel`, `wo_context`, `wo_multiscale`, `wo_cross_sensor`} |
| 行数 | 8 变体 × 3 seeds = 24（`full` 3 行复用 E1 `kst_light` source run） |
| 指标列 | MAE、RMSE、同 seed 相对 `full` 的相对退化率及 95% CI |
| 聚合 | 每变体三 seed mean±std；相对列同 seed 配对 |
| artifact 来源 | `configs/ch3/matrices/e5a_ablation.yaml` 展开 formal catalog + 变体生效开关 manifest |
| 允许结论 | 单因素模块贡献；消融优于 `full` 的结果必须保留并按追溯表降级规则写作 |
| 章节路由 | 3.6.5 |

## 8. Ch3-T6 超参数敏感性（E5-S）

| 字段 | 合同 |
|---|---|
| 回答的问题 | 表示超参数在预注册取值范围内是否稳定 |
| 主键 | `(factor, value, seed)`，factor ∈ {`history`, `hidden`, `patch`, `time_dim`, `head`} |
| 行数 | 14 个 factor-view 展示单元，映射到 12 个 formal run（中心配置三 seed 复用 E1；off-center 仅 seed 2026） |
| 指标列 | MAE、RMSE、参数量、完整训练时间（仅描述正式训练开销，不读取 profile latency） |
| 聚合 | 中心配置三 seed mean±std；off-center 只报告 seed 2026 单点点估计 |
| artifact 来源 | `configs/ch3/matrices/e5s_sensitivity.yaml` 展开 formal catalog |
| 允许结论 | 仅描述性比较；off-center 单 seed 不作显著性表述、不显示伪造离散度 |
| 章节路由 | 3.6.6 |

## 9. Ch3-T7 效率（E6）

| 字段 | 合同 |
|---|---|
| 回答的问题 | 各表示方法的计算代价是否可接受 |
| 主键 | `(model, seed)`，对应 E1 六模型 × 3 seeds 的冻结 checkpoint |
| 行数 | 18 条独立 profile 记录 |
| 指标列 | 参数总数/可训练参数数、完整训练时间（联接 E1 source run）、batch/sample inference latency（5 次 repeat 汇总）、峰值显存、device fingerprint |
| 聚合 | 每模型三 seed mean±std；latency 可由原始 repeat 重算 |
| artifact 来源 | `result/ch3/profile-index.jsonl` 中的 validated profile catalog 与匹配的 E1 formal source run 一对一联接；profile 提供 latency/显存/repeats，formal source run 提供完整训练时间、checkpoint SHA 与预测 provenance |
| 允许结论 | 计算开销比较；profile 证据不得进入 Ch3-T1 至 Ch3-T6、Ch3-T8 的任何单元格 |
| 章节路由 | 3.6.6（计算开销部分） |

## 10. Ch3-T8 外部有效性（E1-X）

| 字段 | 合同 |
|---|---|
| 回答的问题 | 表示是否可迁移到不同工业场景 |
| 主键 | `(dataset, model, seed)`，dataset ∈ {`cmapss_fd004`, `tep`}，model ∈ {`li_tcn`, `gru_d`, `ode_rnn`, `kst_light`} |
| 行数 | 2 数据集 × 4 模型 × 3 seeds = 24 |
| 指标列 | MAE、RMSE、同数据集同 seed 相对 `li_tcn` 的相对误差 |
| 聚合 | 每 (dataset, model) 三 seed mean±std 与 95% CI；FD004 按 engine、TEP 按 `faultNumber:simulationRun` 重采样 |
| artifact 来源 | `configs/ch3/matrices/e1x_fd004.yaml` 与 `configs/ch3/matrices/e1x_tep_faulty.yaml` 展开 formal catalog |
| 允许结论 | 各数据集内的外部有效性；不跨数据集比较原始 MAE/RMSE 量级，外部结果不支持时降低迁移结论 |
| 章节路由 | 不新增机制路由，仅限定 E1 比较的外部范围 |

## 11. 证据消费边界与编号完整性

1. Ch3-T1 至 Ch3-T6、Ch3-T8 只从 `run_level=formal + evidence_status=formal_validated` 的预测聚合记录读取，禁止 profile、smoke、tuning、fixture、mock、legacy Table 1-7 或手填值。
2. Ch3-T7 是唯一可直接消费 `run_level=profile + profile_validation_status=validated` 的表；每个效率字段必须以 source run ID、checkpoint SHA、seed 和 benchmark config SHA 与 E1 formal 记录形成双 provenance。
3. formal/profile 数据源缺少 required seed、预注册 key、hash、相对路径或公平性记录时，整张表构建失败，不能用其他 run 补格或删除不利行。

Ch3-T1 至 Ch3-T8 编号连续、无重号、无缺号。验证命令：

```bash
rg -n 'Ch3-T[1-8]' tables/table-schema.md
```

预期：8 张表编号全部出现且各自有独立小节。
