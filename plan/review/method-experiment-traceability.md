# 第三章方法—实验追溯表

## 使用边界

本表锁定第三章“观测过程感知的规整表示”的证据路径。当前只登记设计和预注册接口；截至本表建立时，没有可消费的第三章 formal artifact，也没有可写入论文的结果方向。现有 `kst_probflow` 中可见的编码器和动态图实现仅用于识别可迁移的表示机制，不能作为第三章证据来源。第三章的正式实现与证据必须来自后续 P03 的数据协议、P04 的 KST-Light 与单因素消融、P05 的 point-only runner 及其 formal artifact。

第三章只消费 point-only 的 MAE、RMSE、同 seed 成对相对退化和效率字段。任何强结论均须由相应预注册矩阵的完整 formal artifact、固定的公平性记录和 P13 聚合共同支持；缺任一项时，结论只能停留在设计/预注册范围，或表述为无明显改善。后续章节专属输出不得作为本表机制的证据。

## 机制追溯主表

| Contribution | Method module | Experiment | Table/Figure | Allowed claim | Evidence status | 结论降级规则 |
|---|---|---|---|---|---|---|
| 真实时间 | P03-T01 预注册的 `code/kaf_profiti/industrial/metropt.py` 中窗口起点归零的 `T_obs`/`T_q`；KST-Light 复用 P04 的 history-only 时间输入。现有 `code/kaf_profiti/models/kafnet_encoder.py` 的 `_time_embedding` 仅为机制参照。 | E0 四种 history-only 协议核验时间语义；E5-A 的 `wo_time`；E4 检查缺失条件下的相对退化。 | Ch3-T1、Ch3-T5；Ch3-F1、Ch3-F3。 | 仅当配对 MAE/RMSE 与相对退化的 formal 结果支持时，可称真实时间输入对该数据协议下的点预测表示有贡献。 | 预注册、无 formal artifact；待 P03、P04、P05 与 E0/E4/E5-A 完成。 | 若时间接口未实现、协议审计失败或消融未改善，只表述真实时间为设计输入；不得称其改善预测。 |
| mask | P05-T01 预注册的 `code/kaf_profiti/experiments/ch3/input_protocols.py` 四协议；P04-T02 的 `wo_mask`。现有 `KAFNetEncoder.encode`/`MultiScaleKAFEncoder.encode` 接收 `M_obs`，仅为接口参照。 | E0 比较 native sparse、线性插值、前向填充和 masked input；E5-A 的 `wo_mask`；E4 的缺失率与机制扫描。 | Ch3-T1、Ch3-T3、Ch3-T4、Ch3-T5；Ch3-F1、Ch3-F2、Ch3-F3。 | 仅当 formal 对比支持时，可称保留观测/缺失区分在给定协议下避免把填充值当作观测，并对点预测表示有贡献。 | 预注册、无 formal artifact；待 P05 输入协议与 E0/E4/E5-A 完成。 | 若 adapter 行为或公平性核验不成立，或结果无明显改善，只记录为输入协议设计；不得宣称 mask 带来性能收益。 |
| delta_t | P03-T02 预注册的 `time_since_last_observation(times, mask)`、`IndustrialBatch.delta_t` 与 P04-T01 的 `Ch3HistoryBatch.delta_t`；由最终 mask 和真实时间计算。 | E5-A 的 `wo_delta`；E1 中要求 GRU-D、ODE-RNN 与 KST-Light使用同源时间/间隔；E4 检查缺失加剧时的相对退化。 | Ch3-T1、Ch3-T2、Ch3-T3、Ch3-T4、Ch3-T5；Ch3-F1、Ch3-F2、Ch3-F3。 | 仅当来源、单位、形状与消融的 formal 证据均通过时，可称观测间隔信息对该点预测表示有独立贡献。 | 预注册、无 formal artifact；待 P03 delta_t 测试、P04 消融与 E1/E4/E5-A 完成。 | 若 `delta_t` 未基于最终 mask 重算、测试失败或消融未改善，只描述为预注册输入字段；不得作贡献结论。 |
| 通道身份 | P04-T02 预注册的 `wo_channel`；P04 KST-Light 将从现有 `code/kaf_profiti/models/kafnet_encoder.py` 的 `PositionalEncoding` 明确迁移为可开关的通道身份路径。 | E0 数据协议审计确认通道级语义；E5-A 的 `wo_channel`；E1 统一轻量头主对比。 | Ch3-T1、Ch3-T2、Ch3-T5；Ch3-F1、Ch3-F3。 | 仅当单因素消融的 point-only 结果支持时，可称通道身份有助于区分变量级表示。 | 预注册、无 formal artifact；待 P04 可开关实现、P05 artifact 与 E1/E5-A 完成。 | 若该开关不可核验或结果无明显改善，只保留为编码设计；不得推广为所有传感器都受益。 |
| 工况 | P03-T03 预注册的 `code/kaf_profiti/industrial/context_policy.py` observed-only context；P04-T02 的 `wo_context`。现有编码器的 `context_proj` 仅为机制参照，正式路径必须满足防旁路合同。 | E0 协议核验工况可见性；E5-A 的 `wo_context`；E1 主对比与 E4 鲁棒性作为同一设计范围的补充。 | Ch3-T1、Ch3-T2、Ch3-T3、Ch3-T4、Ch3-T5；Ch3-F1、Ch3-F2、Ch3-F3。 | 仅当 context 不旁路观测/未来且 formal 消融支持时，可称工况条件注入改善给定运行状态下的点预测表示。 | 预注册、无 formal artifact；待 P03 context policy、P04 消融与 E0/E1/E4/E5-A 完成。 | 若可见性审计失败，整项比较无效；若通过审计但无明显改善，只报告已检验的设计范围。 |
| 多尺度 | P04-T02 的 `wo_multiscale` 与 KST-Light；其表示接口以现有 `MultiScaleKAFEncoder._local_representation`、`_kaf_pool`、`merge_gate` 的全局/局部聚合为参照。 | E5-A 的 `wo_multiscale`；E5-S 对 history 与 patch 组合的 OFAT 扫描；E4 检查不同缺失条件的相对退化。 | Ch3-T3、Ch3-T4、Ch3-T5、Ch3-T6；Ch3-F2、Ch3-F3。 | 仅当消融与预注册敏感性均支持时，可称多尺度历史聚合在所测历史长度和 patch 组合下有表示贡献。 | 预注册、无 formal artifact；待 P04 多尺度开关、P05 runner 与 E4/E5-A/E5-S 完成。 | 若消融无明显改善，只报告该设置下未观察到增益；若仅单 seed 敏感性结果可用，只作描述性比较。 |
| 跨传感器交互 | P04-T03 预注册的 `code/kaf_profiti/models/sensor_graph.py` 与 P04-T02 的 `wo_cross_sensor`；现有 `code/kaf_profiti/models/kst_probflow.py` 的 `DynamicSensorGraphBlock` 仅为图交互机制参照。 | E5-A 的 `wo_cross_sensor`；E1 主对比和 E4 鲁棒性只作为同一 point-only 表示范围的补充。 | Ch3-T2、Ch3-T3、Ch3-T4、Ch3-T5；Ch3-F2、Ch3-F3。 | 仅当受控消融的 MAE/RMSE 与相对退化支持时，可称变量间消息传递对点预测表示有贡献。 | 预注册、无 formal artifact；待 P04 图模块/消融、P05 artifact 与 E1/E4/E5-A 完成。 | 若图模块未实现、开关未生效或消融无明显改善，只描述为待检验的表示设计；不得扩展为联合结构或决策能力结论。 |

## 固定实验路由与产物消费边界

| 实验族 | 固定章节路由 | 机制责任 | 允许消费的未来产物 | 当前状态 |
|---|---|---|---|---|
| E0 数据协议 | 3.6.2 | 固定真实时间、mask、通道身份和工况的输入/可见性语义；不以结果预设任何协议优劣。 | Ch3-T1、Ch3-F1；可为 Ch3-T2 至 Ch3-T6 的公平性前提提供审计边界。 | 预注册、无 formal artifact。 |
| E1 主对比 | 3.6.3 | 在统一轻量头下比较规整表示与预注册基线；仅支持总体 point-only 表示比较。 | Ch3-T2；其冻结 checkpoint 可被 Ch3-T7、Ch3-F4 以双 provenance 联接，且可为 Ch3-T8、Ch3-F5 的外部范围提供同规格参照。 | 预注册、无 formal artifact。 |
| E4 缺失鲁棒性 | 3.6.4 | 检查不同缺失率和缺失机制下的相对退化；不要求曲线满足预定方向。 | Ch3-T3、Ch3-T4、Ch3-F2。 | 预注册、无 formal artifact。 |
| E5-A 受控消融 | 3.6.5 | 识别真实时间、delta_t、mask、通道身份、工况、多尺度和跨传感器交互的单因素表示贡献。 | Ch3-T5、Ch3-F3。 | 预注册、无 formal artifact。 |
| E5-S 敏感性 | 3.6.6 | 只描述 history、hidden、patch、time dim 与轻量头的预注册取值范围；非中心单 seed 不作强比较。 | Ch3-T6。 | 预注册、无 formal artifact。 |
| E6 效率 | 3.6.6（计算开销部分） | 只报告冻结 E1 checkpoint 的参数量、训练/推理开销和资源字段；不判定任一表示机制是否有效。 | Ch3-T7、Ch3-F4；profile 不得进入其他 Ch3-T 或 Ch3-F 产物。 | 预注册、无 validated profile artifact。 |
| E1-X 外部有效性 | 不新增 3.6.2-3.6.6 的机制路由 | 仅限定 E1 已定义的 point-only 比较在 FD004、TEP 上的外部范围；不新增机制贡献。 | Ch3-T8、Ch3-F5。 | 预注册、无 formal artifact。 |

## 结论准入规则

1. E0、E1、E4、E5-A、E5-S 的预测性表述只能读取 P13 聚合的正式 point-only 证据；E6 只能形成效率表述，不能替代 E5-A 的机制消融。
2. Ch3-T1 至 Ch3-T6、Ch3-T8 与 Ch3-F1 至 Ch3-F3、Ch3-F5 只能读取 formal 预测证据；Ch3-T7、Ch3-F4 只允许读取与 E1 冻结来源相联接的已验证 profile。任何尚未达到相应状态的产物都不产生论文结果。
3. 跨传感器交互的论证上限是“对点预测表示的消融贡献”。它不支持后续章节的结构性或决策性结论。
4. 当 formal 覆盖不完整、相同 seed 的公平性记录不一致、机制开关不可验证，或结果无明显改善时，必须按主表的降级规则写作，不得以其他实验族补写强结论。
