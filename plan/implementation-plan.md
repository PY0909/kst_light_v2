# 论文代码与实验全景审计及 Phase 1–9 建设规划

## 2026-09-20 方案 B 架构重构入口

用户已确认采用方案 B。设计合同与逐阶段 TDD 实施计划已经冻结：

- 架构设计：`docs/plans/2026-09-20-kst-flow-scheme-b-design.md`
- 实施计划：`docs/superpowers/plans/2026-09-20-kst-flow-scheme-b-implementation.md`

执行顺序固定为 P0 身份隔离 → P1 缺失特征 → P2 分层 KAF 编码器 → P3 点预测与互斥跨变量模块 → P4 第三章验证 → P5 同分布联合流 → P6 样本风险与验证集校准 → P7 正式多 seed 实验和文档对齐。新模型 ID 为 `kst_light_v2` 和 `kst_flow_v2`；`kst_light`、`kst_probflow` 及其已验签 artifact 保持 legacy 身份。

现有 CH4-S06 在执行 KST 主模型前新增硬门禁：必须先完成方案 B 的 P5 分布一致性测试和无 test smoke，证明 NLL、采样、分位数、区间来自同一 `ProFITiFlowHead`。旧 `LowRankCopulaFlowHead` 的 NLL 不使用相关因子而采样使用相关因子，不能满足该门禁，也不能作为新第四章联合概率模型的正式结果。

## 0.论文第一章、第二章规划

本部分规划计算机硕士毕业论文《面向工业设备异步多传感器的概率状态预测与风险评估方法研究》前两章的资料整理、论证设计、起草和验收步骤。第一章回答“为什么要研究、别人怎么做、本文要解决什么”；第二章回答“后文依赖哪些定义、理论和评价工具”。两章均不预写实验结果，也不把当前某一版代码状态写成已成立的学术结论。

### 0.1 交付物、依据与边界

**目标交付物：**

- `chapters/01_绪论.md`：包含 1.1—1.5 的可审阅初稿。
- `chapters/02_相关理论与技术基础.md`：包含 2.1—2.6 的可审阅初稿。
- `plan/evidence-map.md`：补充前两章的段落级 `citation slot`。
- `plan/chapter-blueprints/chapter-01-blueprint.md` 与 `plan/chapter-blueprints/chapter-02-blueprint.md`：记录各段作用、论点、证据、过渡和禁止内容。
- `plan/review/chapter-01-02-review.md`：记录内容、证据、引用、术语和跨章接口审查结果。

**必读依据：**

| 文件 | 用途 |
|---|---|
| `docs/毕业论文研究边界与总体方案.md` | 锁定总命题、三个研究问题、三项创新、章节职责和可声称边界 |
| `3.2_结构框架.md` | 锁定 1.1—1.5 与 2.1—2.6 的标题及顺序 |
| `docs/文献阅读.md` | 提取已有研究现状素材，不直接整段搬入论文 |
| `docs/文献汇总表.md` | 核查真实性、优先级、DOI 和待 CNKI 复核项 |
| `plan/evidence-map.md` | 建立文献—论点—引用位置的可追溯关系 |
| `plan/chapter-blueprints/literature-review-blueprint.md` | 复用按方法范式综合比较的论证方式 |
| `开题报告_2_3_6对应修改建议.md`、`补充建议.md` | 核对研究意义、研究内容、创新表述及学术风险 |

**写作边界：**

- 第一章只展开研究场景、方法版图、目标缺口、研究问题和预期创新，不展开网络层、损失函数或参数设置。
- 第二章只介绍后文真正使用的定义、原理和指标，不按作者或年份重复第一章的研究现状。
- 创新点固定为“规整表示—概率状态预测—风险转换与校准”三项；统一实验协议是支撑性工作，不单独冒充算法创新。
- 实验完成前使用“提出、构建、旨在、拟验证”，不使用“显著提升、优于、证明了”等结果性表述。
- 第一章说明“别人怎么做、还缺什么”，第二章说明“理论怎样工作、本文为何需要它”，第三至第五章才说明“本文如何实现并验证”。

---

### CH12-P00：冻结前两章写作合同

#### Task CH12-P00-T01：锁定题目、任务与问题链

- [ ] 以“概率状态预测为主任务、风险评估为辅助任务”作为唯一口径，区分未来连续状态预测、RUL 回归和故障分类。
- [ ] 固定研究问题一：如何在不把填充值误认为真实观测的前提下形成异步多传感器规整表示。
- [ ] 固定研究问题二：如何建模未来多个时间点、多个传感器的概率分布及相关结构。
- [ ] 固定研究问题三：如何将预测分布转为不依赖测试集调参、可解释的校准风险信息。
- [ ] 固定第三至第五章与三项创新的一一映射，任何新增内容先判断属于主创新、支撑工作还是可选增强。
- [ ] 建立术语表，至少统一“异步观测、观测掩码、规整表示、未来查询、概率状态预测、相关结构、预测区间、风险分数、概率校准”的中英文名称、符号和首次出现位置。

**完成门禁：**题目、主辅任务、三个问题、三项创新和三个验证章节完全对齐，同一概念没有多个未定义别名。

#### Task CH12-P00-T02：建立章节级证据与作用矩阵

- [ ] 为 1.1—1.4 和 2.1—2.5 分别记录“本节问题—核心论点—所需证据—后续章节接口”。
- [ ] 将 `plan/evidence-map.md` 的证据拆到具体位置，例如“1.2.2-P3 连续时间路线”或“2.5-P2 严格适当评分”。
- [ ] 每个事实性判断至少对应 1 条可核验文献；关键研究缺口优先由 2 篇及以上文献共同支持。
- [ ] 区分证据用途：工程综述支持场景和价值，原始方法论文支持机制与适用条件，数据集或协议资料支持数据特征和规则。
- [ ] 标记 `docs/文献汇总表.md` 中待 CNKI 复核的条目；未复核前不使用其未确认的页码、DOI 或过强结论。
- [ ] 新增或删除引用时，同步更新 `docs/文献汇总表.md`、`docs/文献阅读.md` 参考文献列表及正文编号。

**完成门禁：**每个预定段落均有明确作用和证据位，不存在“先写结论、以后再找文献”的段落。

---

### CH12-P01：建立第一章段落蓝图

#### Task CH12-P01-T01：设计 1.1 研究背景及研究意义

- [ ] 第 1 段由预测性维护和设备全寿命管理切入，说明连续状态预测相对于事后故障识别的价值。
- [ ] 第 2 段聚焦多传感器异步采样、局部缺失、通道离线和工况变化造成的数据矛盾。
- [ ] 第 3 段说明点预测无法完整表达未来状态不确定性和多变量协同变化。
- [ ] 第 4 段说明概率输出仍需风险转换、验证集校准和阈值策略，才能服务运维决策。
- [ ] 理论意义落在“观测过程—未来分布—风险决策”的连续建模；实践价值落在可解释的状态区间、风险来源和预警依据。

**禁止写法：**不用“随着人工智能飞速发展”作空泛开场；不把本文写成纯故障分类或纯 RUL 回归；不用无来源的行业数字制造紧迫性。

#### Task CH12-P01-T02：设计 1.2 工业设备状态预测与风险评估研究现状

- [ ] **1.2.1 工业设备状态预测与剩余寿命研究现状：**按 PHM/状态监测、退化与 RUL、规则采样深度预测、不确定性 RUL 四类路线综合叙述；先承认其价值，再限定其输入假设和输出目标。
- [ ] **1.2.2 不规则时间序列与异步缺失建模研究现状：**按插值/填充、缺失感知递归、连续时间/状态空间、注意力/图结构、预对齐/时间核聚合组织；分别说明优势、前提与在工业长历史、多通道、异质采样和连续离线并存时的权衡。
- [ ] **1.2.3 概率预测、不确定性量化与风险评估研究现状：**按独立参数分布/分位数、生成式分布、相关结构、预测区间校准、异常检测与概率校准组织；明确未来值分布、异常分数和校准风险概率不是同一层输出。
- [ ] 每个方法类段落使用“类别定义—代表方法—已解决问题—适用假设—本文场景下的剩余缺口”的连续论证，并综合 2—4 项相关工作。
- [ ] 1.2 末尾用一个综合段将三类现状分别导向 1.3.1—1.3.3，不在每篇文献后重复“仍有不足”。

**完成门禁：**1.2 是按方法范式形成的比较性综述，而非按作者或年份排列的摘要；所有局限均限定在本文数据条件或任务条件内。

#### Task CH12-P01-T03：设计 1.3—1.5 的收束链

- [ ] **1.3 工业异步多传感器状态预测面临的主要问题：**依次设置 **1.3.1 异步采样与缺失观测导致的信息不完整问题**、**1.3.2 多传感器联合概率建模与相关结构表达不足**、**1.3.3 风险评估中概率输出与校准能力不足**；每个问题按“场景条件—现有处理—未满足需求—所需研究能力”展开。
- [ ] **1.4 本文主要研究内容与创新点（研究内容）：**先说明统一数据和实验协议这一支撑工作，再按规整表示、概率预测、风险校准三层说明输入、问题、方法主张和验证方式。
- [ ] **1.4 本文主要研究内容与创新点（创新点）：**每项创新按“具体缺口—改变的信息流或概率/决策关系—可拆分证据—可声称边界”表述，不以模块数量、模型命名或顺序拼接作为创新性。
- [ ] **1.5 论文组织结构：**每章用 1—2 句说明解决的问题、主要工作及与前后章的关系，第三至第五章职责与三项创新一一对应。
- [ ] 规划一张“工业观测问题—三层研究内容—章节证据”技术路线图，放在 1.4 或 1.5；图中不展开具体网络内部结构。

**完成门禁：**1.1 的场景矛盾在 1.2 获得文献支持，在 1.3 转化为三个问题，在 1.4 对应三项研究机制，在 1.5 落到三个验证章节。

---

### CH12-P02：起草与审查第一章

#### Task CH12-P02-T01：按论证依赖顺序完成初稿

- [ ] 先写 1.3 的三个研究问题，锁定全章收束终点。
- [ ] 再写 1.2.1—1.2.3，使每类现状只导出一个首要缺口，避免同一不足跨节重复。
- [ ] 完成 1.1，只保留能够为 1.2 和 1.3 提供场景依据的背景信息。
- [ ] 完成 1.4，将每个问题转为一项方法主张和一组预定实验判据。
- [ ] 最后写 1.5，使章节安排总结已锁定逻辑，不重复摘要或研究内容。
- [ ] 每完成一节，立即回填蓝图状态、实际引用号和尚缺证据，不在整章写完后集中补引用。

#### Task CH12-P02-T02：执行第一章专项审查

- [ ] 检查“现有方法、多数研究、普遍存在”等表述是否有证据并限定适用范围。
- [ ] 检查是否先承认已有方法的价值，再说明本文任务下的边界，删除“完全无法、彻底解决”等绝对化语句。
- [ ] 检查三个问题、三项创新和三个实验章是否一一对应，是否误把数据协议、指标数量或模型拼接写成创新。
- [ ] 检查是否出现未冻结模型名、当前代码状态、单 seed 数值、smoke test 或尚无正式证据的胜负结论。
- [ ] 检查 1.5 与 `3.2_结构框架.md` 的六章标题、顺序和职责是否一致。

**完成门禁：**第一章可用“现实矛盾—文献缺口—研究问题—创新点—验证章节”矩阵逐项追溯，且没有无证据的普遍性断言。

---

### CH12-P03：建立第二章定义、公式与接口蓝图

#### Task CH12-P03-T01：建立符号表和理论—后文映射

- [ ] 统一传感器数、历史长度、预测长度、批大小、观测值、时间戳、观测掩码、时间间隔、工况变量、历史表示、未来查询集、未来目标和风险标签的符号、维度与取值域。
- [ ] 为每个符号指定首次定义小节和后续使用章节，禁止同一符号跨章表示不同概念。
- [ ] 建立接口矩阵：2.1 支撑第三、四章任务形式化；2.2—2.3 支撑第三章；2.4 支撑第四章；2.5 的概率与区间指标支撑第四章，风险与校准指标支撑第五章。
- [ ] 将必需公式先整理成“公式名—输入—输出—适用条件—后文用途”清单，再起草解释性正文。

**完成门禁：**第二章每个定义、公式和指标均能指向后文的具体用途；没有后续用途的教科书式内容不纳入。

#### Task CH12-P03-T02：设计 2.1—2.3 异步观测与规整表示基础

- [ ] **2.1 工业设备状态预测与多元时间序列建模：**定义历史窗口、预测窗口、多变量未来目标和条件工况；区分状态预测、RUL 回归和故障分类，建立本文主任务的数学边界。
- [ ] **2.2 异步观测与缺失时间序列建模基础：**定义事件序列、对齐张量、mask 和 `delta_t`；区分不等间隔采样、通道间异步和数值缺失，以及原生异步和人工构造缺失。
- [ ] 在 2.2 明确缺失类型不默认作为模型输入；仅在采集日志或受控模拟可可靠区分来源时使用，否则只使用可观测的时间、mask 和通道信息。
- [ ] **2.3 异步时间序列规整表示学习方法：**介绍插值/填充、缺失感知更新、时间核或预对齐、多尺度聚合和变量交互的基本思路，重点解释为何不能把填充值等同真实观测。
- [ ] 为 2.1—2.3 规划历史—未来窗口图、值—时间—mask 对应表、事件序列到规整表示的概念流程图。

**完成门禁：**读者能够区分值缺失、时间不规则和传感器异步，并理解为什么观测过程本身需要被编码。

#### Task CH12-P03-T03：设计 2.4 条件生成式概率预测方法

- [ ] 从条件概率 `p(Y_future | H, Q, C)` 出发，解释历史表示 `H`、未来查询 `Q`、工况 `C` 和未来多变量目标 `Y_future` 的关系。
- [ ] 区分点预测、参数化边际分布、分位数预测、自回归分解、生成式密度建模和相关结构，说明各自能回答的不确定性问题。
- [ ] 介绍条件归一化流所需的最小原理：可逆变换、基分布、变量变换公式、Jacobian 行列式和条件信息，不扩展与第四章无关的流模型谱系。
- [ ] 说明边际分布、预测区间和联合/相关结构的层次差异，不因模型能够采样就直接宣称其学习了有效联合分布。
- [ ] 将联合概率表述绑定到后续证据：训练似然与采样分布一致，相关参数参与优化，并有多变量评分和受控消融支持。

**完成门禁：**2.4 足以支撑第四章的概率定义、损失与采样流程，但不提前介绍本文具体网络组件。

#### Task CH12-P03-T04：设计 2.5 概率预测、区间校准与风险评估指标

- [ ] 按证据层级组织指标：MAE/RMSE 衡量点预测；NLL/CRPS 衡量边际分布；Energy Score 衡量多变量联合质量；PICP/MPIW 衡量区间；AUROC/AUPRC/Precision/Recall/F1 衡量风险排序和决策；ECE 衡量概率校准。
- [ ] 对每个指标给出公式、变量、聚合单位、优劣方向和成立条件；重点说明 NLL 的分布族、标准化空间、有效目标分母和 mask 归一化。
- [ ] 说明 PICP 与 MPIW 必须联合解释：覆盖率达到目标时，区间越窄才越有效。
- [ ] 说明类别不平衡时 AUPRC 与 Precision/Recall 的意义，以及测试集不同时含正负类时 AUROC/AUPRC/F1 应报告 `null`。
- [ ] 定义验证集校准和阈值选择原则：校准器、报警阈值、超参数和 checkpoint 均不得依据测试集标签选择。
- [ ] 在节末规划“研究主张—指标—可支持结论—不可支持结论”表，防止用点误差证明概率质量或用 AUROC 证明概率校准。

**完成门禁：**任一后文章节的结论均能在 2.5 找到定义清晰、边界正确的评价工具，且不存在测试集参与选择的口子。

---

### CH12-P04：起草与审查第二章

#### Task CH12-P04-T01：按概念依赖顺序完成初稿

- [ ] 先完成符号表和 2.1，使后续公式共享同一组对象与维度。
- [ ] 再写 2.2—2.3，先定义异步观测，再介绍规整表示；未区分时间不规则和数值缺失前不引入编码方法。
- [ ] 完成 2.4，从条件分布展开到边际、区间和相关结构，并设置训练与采样一致性检查点。
- [ ] 完成 2.5，从“需要证明哪类主张”反向选择指标，不堆积指标缩写。
- [ ] 最后写 **2.6 本章小结**：第一段概括已建立的理论工具，第二段过渡到第三章的数据协议和规整表示。
- [ ] 每完成一节，核对公式符号、文献依据和后文用途，未定义符号不得带入下一节。

#### Task CH12-P04-T02：执行第二章专项审查

- [ ] **定义审查：**核心概念在首次使用时定义，观测值、填充值、预测值和样本值使用可区分符号。
- [ ] **维度审查：**对历史输入、变量级表示、未来查询、预测目标和采样输出进行形状推演，保证目标展开顺序与查询顺序一致。
- [ ] **公式审查：**逐项检查条件概率、NLL、CRPS、Energy Score、PICP、MPIW、F1 和 ECE 的变量、分母、范围与优劣方向。
- [ ] **边界审查：**2.2 不要求所有数据集提供缺失类型；2.4 不把采样能力等同联合建模证据；2.5 不允许测试集参与选择。
- [ ] **去重审查：**以作者、年份和研究不足为主的综述句移回第一章；第二章只保留定义或原理所需来源引用。

**完成门禁：**独立阅读第二章即可理解后文符号、核心机制和指标；同时它既不是第一章综述的重复版，也不是第三至第五章方法细节的提前展开。

---

### CH12-P05：前两章联合统稿与验收

#### Task CH12-P05-T01：建立章间接口并消除重复

- [ ] 将第一章三个问题逐项映射到第二章理论工具及第三至第五章验证章节，每个问题只保留一个首要对应关系。
- [ ] 检查第一章对应内容是否强调研究版图与缺口，第二章对应内容是否转为定义、机理和适用条件，删除跨章复制的句子。
- [ ] 检查第二章末尾是否自然引出第三章事件序列、统一张量协议和规整表示，但未提前声称效果。
- [ ] 核对六章标题、三项创新名称、数据集名称、模型显示名和代码 ID；论文层优先使用机制名称，正式版本冻结后才统一使用唯一模型名。

#### Task CH12-P05-T02：完成引用、学术性与可追溯验收

- [ ] 按正文首次出现顺序排列参考文献编号，确保编号连续、正文与文后一一对应，不使用 `[1-3]` 或 `[1,2,3]` 合并引用。
- [ ] 逐句检查原文是否支持引用主张；仅阅读摘要时，不写超出摘要的机制细节或结论。
- [ ] 统一中英文缩写，首次出现采用“中文全称（英文全称，缩写）”，后文只使用统一缩写。
- [ ] 扫描“显著、有效证明、全面解决、必然、首次”等高风险词，无直接证据时改为带条件的机制性表述。
- [ ] 检查每个图、表和公式均在正文被引用并解释，图题、表题、符号和单位完整。
- [ ] 将审查结果写入 `plan/review/chapter-01-02-review.md`，每项标记“通过、需修改或缺证据”并注明文件位置。

**联合完成门禁：**

1. 第一章每个研究缺口均有文献边界支持，并对应一项研究问题、一项方法主张和一个主要验证章节。
2. 第二章每个理论单元均有后文用途，核心公式的符号、分母、条件和优劣方向明确。
3. 两章之间无大段重复，与 `3.2_结构框架.md` 和总体方案的标题、术语、职责和论证顺序一致。
4. 全部引用真实可追溯、编号连续且与文后条目一一对应；待 CNKI 复核项未被写成已完全核验。
5. 未引用 smoke test、单 seed、无 `run_id`/checkpoint 或测试集调参结果，也未以结果性语言预支尚未验证的创新。

### 0.2 推荐执行顺序

```text
CH12-P00 冻结口径与证据
  -> CH12-P01 第一章段落蓝图
  -> CH12-P02 第一章起草与审查
  -> CH12-P03 第二章定义/公式/接口蓝图
  -> CH12-P04 第二章起草与审查
  -> CH12-P05 两章联合统稿与引用冻结
```

不建议从 1.1 顺写到 2.6。第一章应先锁定 1.3 的研究问题，再用 1.2 建立文献证据，最后回写 1.1 和 1.4—1.5；第二章应先锁定符号和后文接口，再按 2.1—2.5 的概念依赖顺序写作。







## 1. 总体结论

当前仓库已经具备“主模型原型、统一数据协议、训练评估入口、部分基线和结果表骨架”，但尚未达到可直接支撑最终论文结论的状态。

本次覆盖 201 个 Python 文件、40,116 行代码；全部通过 AST 语法解析。代码规模如下：

| 代码根目录      | 文件数 | 行数   | 定位                 |
| --------------- | ------ | ------ | -------------------- |
| `code/`         | 33     | 6,795  | 当前主工程           |
| `compare_code/` | 10     | 2,132  | 独立对比模型工程     |
| `KAFNet-main/`  | 36     | 6,227  | KAFNet 上游参考代码  |
| `ProFITi-main/` | 122    | 24,962 | ProFITi 上游参考代码 |

当前只有 KST ProbFlow 和 TCN-Gaussian 各一个 seed 的完整 MetroPT-3 训练。它们可作为“协议修正前探索结果”，不能直接作为最终论文主表证据。正式大规模实验必须等 Phase 1–4 的规范、数据协议和概率定义通过验收后再开始。

## 2. 当前已有代码及作用

当前执行主链路为：

```
实验配置
→ 数据协议与 train/valid/test 划分
→ 固定缺失 mask
→ IndustrialBatch
→ 模型 registry
→ 训练及 best-validation-CRPS checkpoint
→ validation 校准
→ test 评估
→ metrics/config/history/predictions/calibration 等产物
```

| 模块         | 当前作用                                              | 关键入口                                                     |
| ------------ | ----------------------------------------------------- | ------------------------------------------------------------ |
| 统一实验入口 | 训练、验证、best checkpoint、校准、测试和结果保存     | [run_experiment.py (line 653)](/Users/ppy/研/00提交资料汇总/new_work/code/run_experiment.py:653) |
| 数据协议     | MetroPT-3、C-MAPSS、TEP 数据划分及窗口构造            | [datasets.py (line 41)](/Users/ppy/研/00提交资料汇总/new_work/code/kaf_profiti/experiments/datasets.py:41) |
| 工业数据适配 | 读取数据、归一化、窗口、时间、上下文和标签            | [industrial/](/Users/ppy/研/00提交资料汇总/new_work/code/kaf_profiti/industrial/__init__.py) |
| 批处理接口   | 把不同数据集统一成模型所需的 `IndustrialBatch`        | [batch.py (line 9)](/Users/ppy/研/00提交资料汇总/new_work/code/kaf_profiti/industrial/batch.py:9) |
| 缺失模拟     | random、low-rate、block-offline、mixed 模式           | [missing.py (line 9)](/Users/ppy/研/00提交资料汇总/new_work/code/kaf_profiti/industrial/missing.py:9) |
| 固定 mask    | 生成、保存、复用 train/valid/test `.npz`              | [masks.py (line 12)](/Users/ppy/研/00提交资料汇总/new_work/code/kaf_profiti/experiments/masks.py:12) |
| 主模型编码器 | KAF 编码、频域注意力、多尺度 patch 表示               | [kafnet_encoder.py (line 197)](/Users/ppy/研/00提交资料汇总/new_work/code/kaf_profiti/models/kafnet_encoder.py:197) |
| 主模型       | 动态传感器图、查询适配、概率头、分位数头和风险头      | [kst_probflow.py (line 214)](/Users/ppy/研/00提交资料汇总/new_work/code/kaf_profiti/models/kst_probflow.py:214) |
| 旧联合模型   | KAFNet 编码器与 ProFITi flow 的早期组合               | [kaf_profiti.py (line 34)](/Users/ppy/研/00提交资料汇总/new_work/code/kaf_profiti/models/kaf_profiti.py:34) |
| 模型注册     | 维护模型名、类别和启用状态                            | [registry.py (line 16)](/Users/ppy/研/00提交资料汇总/new_work/code/kaf_profiti/experiments/registry.py:16) |
| 指标         | MAE、RMSE、NLL、CRPS、PICP、MPIW、风险指标            | [metrics.py (line 15)](/Users/ppy/研/00提交资料汇总/new_work/code/kaf_profiti/experiments/metrics.py:15) |
| 风险重评估   | Platt calibration 和不同 validation 阈值策略          | [evaluate_risk_calibration.py (line 342)](/Users/ppy/研/00提交资料汇总/new_work/code/evaluate_risk_calibration.py:342) |
| 结果表       | 生成 Table 1–7 CSV 骨架                               | [tables.py (line 22)](/Users/ppy/研/00提交资料汇总/new_work/code/kaf_profiti/experiments/tables.py:22) |
| TCN 基线     | 独立 Gaussian TCN 训练评估流程                        | [train_tcn_gaussian.py (line 281)](/Users/ppy/研/00提交资料汇总/new_work/compare_code/TCN-Gaussian/train_tcn_gaussian.py:281) |
| 统一基线原型 | PatchTST、ODE-RNN、tPatchGNN、ProFITi、KAFNet         | [models.py (line 126)](/Users/ppy/研/00提交资料汇总/new_work/compare_code/probabilistic_baselines/baselines/models.py:126) |
| 旧脚本       | 早期 MetroPT/C-MAPSS 独立训练评估，未完全遵守统一协议 | [train_metropt_kaf_profiti.py (line 72)](/Users/ppy/研/00提交资料汇总/new_work/code/train_metropt_kaf_profiti.py:72) |

`KAFNet-main/` 和 `ProFITi-main/` 应继续视为上游参考，不应把其中“存在的代码”直接算作本项目已完成的模型集成或实验结果。

## 3. 当前主模型结构

```
MultiScaleKAFEncoder
→ DynamicSensorGraphBlock
→ QueryConditionAdapter
→ LowRankCopulaFlowHead
  + QuantileHead
  + supervised RiskHead
```

编码器、多尺度表示、动态图、查询条件、分位数头和风险头均已有实现。当前最关键问题在概率头：[NLL 路径 (line 79)](/Users/ppy/研/00提交资料汇总/new_work/code/kaf_profiti/models/kst_probflow.py:79)没有使用 low-rank factors，而[采样路径 (line 94)](/Users/ppy/研/00提交资料汇总/new_work/code/kaf_profiti/models/kst_probflow.py:94)使用 Gaussian 低秩噪声；训练采用独立 Student-t 边际，采样采用另一种相关分布。因此现阶段不能使用“经过联合似然训练的低秩 copula”这一强表述。

## 4. 当前实验状态

| 数据集/模型                          | 训练级别                | 当前结果                                                     | 结论权限             |
| ------------------------------------ | ----------------------- | ------------------------------------------------------------ | -------------------- |
| MetroPT-3 / KST ProbFlow / seed 2026 | 完整 50 epochs          | MAE 0.4135；RMSE 1.1804；NLL -0.1566；CRPS 0.3392；固定 Platt/q95 后 F1 0.8214、ECE 0.0043 | 探索性单 seed        |
| MetroPT-3 / TCN-Gaussian / seed 2026 | 完整 50 epochs          | MAE 0.5001；RMSE 1.1355；NLL 25.8702；CRPS 0.3905；固定 Platt/q95 后 F1 0.3137、ECE 0.0478 | 探索性单 seed        |
| MetroPT-3 / PatchTST                 | 1 epoch、每阶段 1 batch | metrics 被写为 `completed`                                   | 仅 smoke，不得入论文 |
| C-MAPSS FD001 / ProFITi              | 1 epoch、每阶段 1 batch | metrics 被写为 `completed`                                   | 仅 smoke，不得入论文 |

KST 原始结果见 [metrics_seed2026.json (line 1)](/Users/ppy/研/00提交资料汇总/new_work/result/metropt3_chrono502030_mskaf_20260609_084658/metrics/metropt3_chrono_502030/kst_probflow/metrics_seed2026.json:1)。

KST 与 TCN 的 train/valid/test mask 已验证完全一致，公平性这一点成立；但名义 `missing_rate=0.3` 的实际缺失率分别约为 64.70%、64.63%、64.66%。原因是 30% 随机删除又与低频采样、连续离线相乘，因此当前结果不能描述为“30% 缺失实验”。

两次完整运行的 predictions 和 checkpoints 没有保存在当前本地结果目录，已有 JSON 还引用旧机器绝对路径，限制了 bootstrap、案例图、事件分析及重新评估。

## 5. 必须先解决的缺口

| 问题                                                         | 影响                           | 解决阶段   |
| ------------------------------------------------------------ | ------------------------------ | ---------- |
| Low-rank factors 不参与 NLL，训练和采样分布不一致            | 联合概率建模结论不成立         | Phase 3    |
| mask 按窗口独立生成，重叠窗口同一时刻可能拥有不同观测状态    | 数据协议不物理一致             | Phase 2    |
| `missing_rate` 不等于实际缺失率                              | 缺失鲁棒性横轴错误             | Phase 2    |
| MetroPT 已计算真实 `relative_time`，样本却使用 `arange`      | 时间戳创新缺少真实输入         | Phase 2    |
| MetroPT/TEP context 与目标传感器列重叠，并绕过 mask          | 可能发生上下文旁路             | Phase 2    |
| 主入口只有方向选择和 validation normal quantile，没有 Platt  | 文档、主程序和结果表口径不一致 | Phase 3    |
| 风险重评估输出 `best_official_strategy_by_test_f1`           | 构成测试集策略选择             | Phase 3    |
| 主模型风险头与基线 mean/scale 风险不是同一风险定义           | 风险横向比较不公平             | Phase 3、7 |
| MetroPT 文档声称包含 pre-fault，代码只标记未来窗口与故障区间相交 | 标签定义不一致                 | Phase 2    |
| TEP 默认只加载 fault-free 数据，风险标签全为负类             | 无法验证故障风险               | Phase 2、8 |
| 指标按 batch 等权平均，最后小 batch 会造成偏差               | 汇总统计不严格                 | Phase 3    |
| Energy Score、有效 Lead Time、统计检验和图形管线缺失         | 第四、五章证据不完整           | Phase 3、9 |
| registry 将已能运行的基线仍标为 `not_implemented`            | 代码治理与实际状态不一致       | Phase 4    |
| smoke 与 formal 都可写成 `completed`                         | 调试结果可能误进论文           | Phase 4    |
| 缺 Git SHA、dirty 状态、数据哈希、环境、schema 和评估 RNG    | 结果不可完整复现               | Phase 4    |
| 无 `pyproject.toml`、统一格式化/静态检查/CI                  | 工程质量门禁缺失               | Phase 1    |

## 6. 后续需要建设的代码模块

| 计划模块                                                     | 作用                                                         |
| ------------------------------------------------------------ | ------------------------------------------------------------ |
| `experiments/config.py`、`experiments/paths.py`              | 唯一配置模型、路径解析、CLI/env/config 合并；彻底消除硬编码  |
| `experiments/manifest.py`、`experiments/artifacts.py`        | 保存 Git、环境、数据/mask 哈希、硬件、状态级别和 artifact schema |
| 重构 `experiments/masks.py`                                  | 全局时间线 mask、目标实际缺失率、重叠一致性、元数据验证      |
| `industrial/time_features.py`、`industrial/context_policy.py` | 真实时间戳、`delta_t`、上下文可见性和泄漏检查                |
| `models/joint_distribution.py`                               | 数学一致的低秩联合分布；或明确降级为独立边际模型             |
| 扩展 `industrial/risk.py` 和统一 calibration 模块            | 数据集特定风险标签、分布派生风险、辅助风险头及固定 Platt/q95 |
| `experiments/accumulators.py`、`statistics.py`、`profiling.py` | 全局指标、Energy Score、事件/时间块 bootstrap、效应量、显存和效率 |
| `models/lightweight_head.py`、`models/ablation.py`           | 第三章轻量头和第三、四章受控消融开关                         |
| `kaf_profiti/baselines/`                                     | 将现有基线接入统一接口，并补 GRU-D、mTAN、GraFITi            |
| `analysis/figures.py` 及升级后的 `tables.py`                 | 从结果自动生成论文表格、曲线、校准图、案例图和消融图         |
| 新增协议、泄漏、路径、artifact、formal-run 测试              | 阻止路径写死、数据泄漏、smoke 混入正式结果等回归             |

第一、二章主要需要文献和术语治理；第三至第五章需要上述实验代码；第六章不得再引入新模型或新实验，只汇总 Phase 5–8 已形成的证据。

## 7. Phase 1–9 顺序规划

各 Phase 必须通过验收门禁后才能进入下一阶段，禁止跳过 Phase 2–4 直接批量训练。

| Phase                             | 代码任务                                                     | 实验任务                                                     | 完成门禁                                                     |
| --------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ | ------------------------------------------------------------ |
| **Phase 1：工程与路径治理**       | 建立 `pyproject.toml`、统一配置/路径模块、恢复唯一规划真源、清除绝对路径和固定主机端口、建立 lint/type/test 命令 | 不跑正式训练，仅运行单元测试                                 | 源码、脚本和内部文档无环境相关硬编码；单命令可从任意工作目录启动 |
| **Phase 2：数据协议修正**         | 全局 mask、实际缺失率控制、真实时间与 `delta_t`、context policy、标签定义、TEP faulty protocol | 对每个数据集做协议审计 smoke                                 | 实际缺失率误差不超过 1 个百分点；重叠窗口一致；train-only 归一化；无旁路泄漏 |
| **Phase 3：科学计算正确性**       | 重写或降级概率头；统一风险定义；全局指标累加；Energy Score；固定 Platt/q95；删除 test-F1 选择 | 合成数据分布、校准和指标测试                                 | factors 影响 NLL 且有梯度；NLL 与 sampling 同分布；test label 不进入任何选择 |
| **Phase 4：统一实验平台与基线**   | 单一 trainer/evaluator、四级模型状态、resume、manifest、完整 artifact writer、formal/smoke guard；接入并核验全部基线 | 每个模型 × 数据集执行端到端 smoke                            | `interface → smoke → full → formal` 状态明确；formal 模式禁止限 batch 和少 epoch |
| **Phase 5：第三章表示实验**       | 轻量预测头、时间/mask/通道/context/多尺度消融                | MetroPT-3，seeds 2026/2027/2028；缺失率 0/10/30/50/70%；random/low-rate/block/mixed | 只使用轻量头证明表示贡献，生成第三章表图及 mean±std          |
| **Phase 6：第四章概率预测实验**   | 完整 KST、独立 Gaussian、marginal、无相关结构、无查询适配等变体 | MetroPT-3 全基线三 seeds；预测长度、rank、patch 尺度敏感性   | MAE/RMSE/NLL/CRPS/PICP/MPIW/Energy Score 完整；联合结论须由多变量评分支持 |
| **Phase 7：第五章风险实验**       | 分布派生风险和辅助 RiskHead 分开报告；事件级报警与 Lead Time | 固定 `platt_validation_normal_q95`；风险来源、校准、阈值和缺失鲁棒性消融 | 正式策略预先固定；AUROC/AUPRC/F1/ECE、事件级 CI 和时间线案例可追溯 |
| **Phase 8：跨数据集验证**         | 完善 C-MAPSS FD004 与 TEP faulty 适配                        | FD004 为主要辅助验证；TEP 为过程工业增强验证；FD001 可作补充 | 按 engine/run 分割；至少核心模型三 seeds；不跨数据集直接比较风险绝对值 |
| **Phase 9：统计、图表与论文冻结** | 自动表图、事件/时间块 bootstrap、效应量、效率报告、artifact 校验和 CI | 只汇总已冻结结果，不再用 test 调参                           | Table 1–7 和全部图可一键重建；每个正文数字可追溯到 run、seed、checkpoint 和代码版本 |

## 8. 正式实验最低矩阵

- MetroPT-3 主实验：KST、TCN、PatchTST、GRU-D、ODE-RNN、mTAN、GraFITi/tPatchGNN、ProFITi、KAFNet及必要消融，统一 seeds `2026/2027/2028`。
- 缺失鲁棒性：选择至少 5 个核心模型，实际缺失率 `0/10/30/50/70%`；不同机制单独报告，不能都混入一个 `mixed=30%` 标签。
- 第三章：相同轻量头、相同训练预算，只比较表示；不得借完整概率头或 RiskHead 证明表示创新。
- 第四章：完整概率主表、查询/边际/相关结构消融、预测长度与相关秩敏感性。
- 第五章：风险来源对照、Platt 与未校准对照、固定 q95、事件级 Lead Time、故障时间线和风险缺失鲁棒性。
- 统计：MetroPT 使用时间块或事件级 bootstrap，C-MAPSS 使用 engine，TEP 使用 simulation run；不能仅用 3 个 seed 做不可靠的 Wilcoxon 显著性结论。
- 效率：统一 batch、硬件、warm-up 和测量区间，报告参数量、训练时间、单样本/单 batch 推理、峰值显存。
- 每次正式运行必须保留 mean、samples、risk、targets、query mask、真实时间、事件/设备 ID、config、manifest、history、best/final checkpoint。

## 9. 后续代码规范

1. **禁止硬编码路径和链接。** 新旧代码、脚本和内部文档不得出现 `/Users/...`、`/home/...`、`/root/...`、固定 IP、账号、SSH 端口或实例地址。
2. 配置优先级统一为 `CLI > environment > config > repository-relative default`；正式运行必须显式解析并记录配置。
3. Markdown 仓库内部链接使用相对路径；运行时服务地址通过环境变量或 SSH alias；稳定 DOI/公开数据链接只放在文献或数据来源定义中。
4. artifact 内可以记录已解析环境信息用于溯源，但其他代码不得依赖其中的旧机器绝对路径，应使用 run 目录相对定位和内容哈希。
5. 增加自动硬编码扫描测试；出现绝对路径、密钥、主机或端口即阻止合并。
6. 公共 API 使用类型标注；科学公式、张量形状和数据协议必须有准确 docstring；禁止裸 `except` 和无说明 fallback。
7. 随机性同时固定 Python、NumPy、PyTorch、CUDA、DataLoader 和评估采样 RNG；正式 manifest 记录全部 seed。
8. 测试分为 unit、integration、protocol、leakage、artifact、formal-run；缺少外部数据时明确 `skip`，不能以 `FileNotFoundError` 作为正常结果。
9. 预测 run 的 evidence status 只允许 `interface_only`、`smoke_passed`、`full_completed`、`formal_validated`；只有 `formal_validated` 可进入预测结果表图。效率 profile 使用独立的 `profile_validation_status`，只能进入预注册效率输出，不能冒充预测 formal run。
10. `result/` 原始 metrics 永不手改；表格和图片必须由代码从冻结 artifact 生成。
11. 所有复用的上游实现记录仓库、版本、commit、许可证及本地改动；KAFNet 参考代码在正式复用前需完成许可证核验。
12. 正式实验要求 Git SHA、dirty flag、数据哈希、split/mask 哈希、环境版本、硬件、命令、配置、schema version 和 checkpoint 全部齐备。

## 10. 当前验证与文件状态

- 201 个 Python 文件、40,116 行全部通过 AST 解析，无语法错误。
- 主测试使用仓库实际数据路径运行：2026-09-02 复跑 `52 passed，0 failed`（本地 venv，`KST_DATA_ROOT` 指向仓库 `dataset/`）。此前 `46 passed，6 failed` 的 6 项失败均因本地缺少 TEP `dataverse_files`，该数据已于 2026-09-01 补齐（四份 RData，约 1.3 GB，含 faulty training/testing），失败已消除。
- 概率基线纯模型测试：`5 passed`；TCN 纯模型测试：`2 passed`。
- 对比工程完整集成测试仍受固定 `/home/work/...` 路径影响，已列入 Phase 1。
- `.codegraph/` 当前已有数据库文件，但状态查询为 `0 files / 0 nodes / 0 edges`，因此没有可用于本次审计的结构索引；原始只读审计阶段未执行初始化或重建索引。
- 原始只读审计阶段未修改代码、数据或 `result/` 指标；随后仅按用户要求创建并扩展本规划文档。工作区原有的删除、修改和其他未跟踪文件均保持原状。



## 11. 第三章实验任务计划

> **供后续智能体执行：** 必须逐 Phase、逐 Task 执行；推荐使用 `subagent-driven-development`，也可使用 `executing-plans`。所有状态均使用 checkbox（`- [ ]` / `- [x]`）追踪。

**目标：** 完成第三章“工业异步多传感器观测建模与规整表示实验”的全部代码、正式实验、统计、表格、图片和证据交付。

**已锁定方案 A：** MetroPT-3 完成全部主对比、数据协议、鲁棒性、消融、敏感性与效率实验；C-MAPSS FD004 和 TEP 各选择 4 个代表模型完成外部有效性验证。

**架构边界：** 第三章使用共享数据协议、共享缺失 mask 和独立点预测轻量头评价表示质量。不得调用 `ProFITiFlowHead`、`LowRankCopulaFlowHead`、`QuantileHead` 或 `RiskHead` 生成第三章结论；这些模块属于第四、第五章。

**技术栈：** Python 3.12、PyTorch、NumPy、pandas、scikit-learn、pytest、YAML/JSON、matplotlib/seaborn；AutoDL RTX 3090 仅用于正式训练。

### 11.1 执行与勾选规则

本节所称“自动勾选”，是指后续执行智能体在一项工作通过对应验证后立即把状态写回本文件，而不是等待整批完成后补记。P14-T05 才创建的 updater 只承担最终 D5 关闭事务，不追溯替代前序逐项写回。

1. Phase 必须按 `CH3-P00 -> CH3-P14` 顺序执行；前一 Phase 的完成门禁未通过，禁止启动后一 Phase。
2. P00 至 P13 以及 P14-T01 至 P14-T04 每完成一个 checkbox step，执行智能体立即在本文件把对应 `- [ ]` 改为 `- [x]`；不得等到 Phase 结束后批量勾选。
3. 每个 Task 都有独立“Task 完成”框；只有测试命令通过、产物存在且验收条件满足后才能勾选，“代码已写但未验证”保持未勾选。
4. Phase 完成框只有在该 Phase 下全部必做 Task 均为 `[x]` 时才能勾选。
5. P14-T05 updater 只允许原子关闭“最终 apply step、D5、本 Task、Phase P14”四个 marker；除这四项外若仍有必做框未勾选，或任一证据无效，必须拒绝更新。
6. 每次只修改当前 Task 声明的文件；工作区其他删除、修改和未跟踪文件均视为用户资产，不得还原或覆盖。
7. 所有仓库内部链接和文件引用使用相对路径；代码、配置、测试和脚本不得写死机器路径、账号、主机、IP 或端口。
8. 运行时路径只从 CLI、环境变量或未提交的本机配置解析，优先级固定为 `CLI > environment > config > repository-relative default`。
9. `result/` 中原始 metrics、mask、prediction、checkpoint 和 profile repeats 只允许程序生成，不得手工改数值。
10. smoke、tuning、formal 与 profile 必须分别标记；任何限 batch、1 epoch 或调试结果不得进入第三章正式输出。
11. 本计划不预填实验结果；预测结论只能消费真实 `formal_validated` artifact，`profile_validation_status=validated` 只允许进入 Ch3-T7 和 Ch3-F4 的效率字段。

**与第 7 节 Phase 1–9 的编号映射（避免执行时混淆两套编号）：**

- CH3-P01 ≈ Phase 1（工程与路径治理，第三章范围）；CH3-P02/P03 ≈ Phase 2（数据协议修正）。
- CH3-P04–P07 ≈ Phase 4（统一实验平台与基线，point-only 子集）；CH3-P08–P11 ≈ Phase 5（第三章表示实验）。
- CH3-P12 ≈ Phase 8（跨数据集验证的第三章部分）；CH3-P13/P14 ≈ Phase 9（统计、图表与冻结的第三章部分）。
- Phase 3、Phase 6、Phase 7 属于第四、第五章，不在本节执行范围；本节所有“Phase 完成门禁”均指 CH3-Pxx。

**D0-D5 门禁唯一含义：**

- D0：实验协议锁定，数据、模型、指标、预算、seed 和禁止项无未决内容。
- D1：方法—实验追溯锁定，每个机制都有实验、表图和允许结论。
- D2：表图数据合同锁定，Ch3-T1..T8、Ch3-F1..F5 的字段和来源完整。
- D3：正式结果完整，P08-P12 的 expected formal keys 与 validated keys 完全一致，18 个 expected profile keys 独立闭合，统计输入可用。
- D4：结果交付无污染，P13 表图可重建且不含 mock、fixture、smoke、规划提示或手填数字。
- D5：同行评审与冻结通过，blocking/major finding 为零且 freeze 二次验签成功。

P07 只关闭“工程 preflight”，不得提前勾选 D3；D3、D4、D5 分别在 P13、P14 由机器证据关闭。

### 11.2 第三章证据边界与正式矩阵

| 实验族 | 回答的问题 | 数据集 | 正式模型/变体 | 重复 | 指标 |
|---|---|---|---|---|---|
| E0 数据协议 | 结论是否依赖泄漏、插值或不一致 mask | MetroPT-3；FD004/TEP 做协议核验 | native sparse、linear interpolation、forward fill、masked input | seeds 2026/2027/2028 | 实际缺失率、MAE、RMSE、mask 一致性 |
| E1 主对比 | 规整表示是否优于合理表示基线 | MetroPT-3 | LI+TCN、FF+GRU、Masked TCN、GRU-D、ODE-RNN、KST-Light | 3 seeds | MAE、RMSE、参数量、训练/推理时间 |
| E4 缺失鲁棒性 | 表示在缺失加剧和不同机制下是否稳定 | MetroPT-3 | LI+TCN、GRU-D、ODE-RNN、KST-Light | 3 seeds | MAE、RMSE、相对退化率 |
| E5-A 消融 | 每个表示模块是否有独立贡献 | MetroPT-3 | full、w/o time、delta、mask、channel、context、multiscale、cross-sensor | 3 seeds | MAE、RMSE、相对退化率 |
| E5-S 敏感性 | 表示超参数是否稳定 | MetroPT-3 | history、hidden、patch、time dim、head type | seed 2026 扫描；中心配置 3 seeds | MAE、RMSE、参数量、推理时间 |
| E1-X 外部有效性 | 表示是否可迁移到不同工业场景 | FD004、TEP | LI+TCN、GRU-D、ODE-RNN、KST-Light | 3 seeds | MAE、RMSE、相对退化率、效率 |
| E6 统计与效率 | 结果是否稳定且计算代价可接受 | 三数据集；效率主表用 MetroPT-3 | 预注册成对比较与 E1 六模型 | block/engine/run bootstrap | mean±std、95% CI、参数量、训练/推理时间 |

**固定正式配置：**

- MetroPT-3：`dataset=metropt3_chrono_502030`、`history_len=168`、`pred_len=24`、`stride=60`。
- FD004：`dataset=cmapss_fd004`、`history_len=50`、`pred_len=10`、`stride=1`。
- TEP：`dataset=tep`、`history_len=96`、`pred_len=24`、`stride=12`，必须接入 faulty runs 后才能进入正式外部验证。
- TEP 数据可用性已关闭（2026-09-02 验证）：`dataverse_files/` 下四份 RData 齐全且可被现有读取器解析——`faulty_training` 5,000,000 行 × 55 列、`faulty_testing` 9,600,000 行 × 55 列，本地 `KST_DATA_ROOT` 下 `code/tests/test_tep_data.py` 6/6 通过。剩余义务：正式执行前把四份 RData 传输到执行机数据根并登记 raw SHA（见 CH3-P08-T02 与 CH3-P12-T02），仍禁止 fault-free fallback。
- 核心 seeds：`2026`、`2027`、`2028`。
- `split_seed=2026` 对 FD004 engine 划分和 TEP simulation-run 划分保持固定；`seed` 控制模型初始化、DataLoader 和该次重复的 mask，任何模型在相同数据集/设置/seed 下必须复用同一 mask SHA。
- 主设置：实际缺失率为 `0.30` 的 matched-mixed 协议，允许误差不超过 1 个百分点。
- 缺失率扫描：random 模式 `0.00/0.10/0.30/0.50/0.70`。
- `0.00` 是相对退化率的预注册 reference；论文 3.6.4 主文可重点展示 `0.10/0.30/0.50/0.70`，但不得删除 0% 原始结果。
- 机制扫描：random、low_rate、block_offline、mixed 均匹配实际缺失率 `0.30 +/- 0.01`。
- 模型选择：第三章统一以 validation MAE 选择 checkpoint，test 只评估一次冻结配置。

### 11.3 A 方案充分性与工作量边界

**判定：** A 方案足以形成研究生毕业论文第三章的完整实验证据链，但这是有条件的“足够”，不是只跑 MetroPT-3 主表即可。必须同时完成协议审计、公平基线、三 seed、鲁棒性、逐模块消融、敏感性、效率、FD004/TEP 外部验证、相关性统计和可追溯冻结；任一关键证据族缺失时，只能把相应结论降级，不能仍声称第三章全部完成。

- 方案 A 的优势是“主数据集做深、两个工业场景做外部验证”，比在三个数据集上浅跑大量模型更符合第三章验证表示方法的研究问题。
- A 只覆盖第三章“表示质量”；它不能替代第四章联合概率预测和第五章风险校准实验，因此只选择 A 不等于整篇论文实验完成。
- TEP 必须包含 faulty runs 并按 simulation run 隔离；若正式执行时仍只有 fault-free 数据，TEP 行不能标为外部验证完成。faulty 数据已在本机确认齐全可读（2026-09-02），因此该风险从“数据不可得”降级为“传输与 hash 登记”——执行机上的 raw SHA 必须与本地登记值一致，不一致即阻塞，不得静默改用 fault-free。
- GRU-D 与 ODE-RNN 必须通过来源、公式、时间输入和行为测试的 fidelity gate；简化代理模型不能用正式模型名进入论文。
- 计划共有 198 个 formal matrix expected rows；按规范化配置哈希复用 E0/E1、E1/E4、E1/消融和 E1/敏感性中的相同运行后，预计最多 165 个唯一正式训练 run。敏感性另有 14 个 factor-view 展示单元映射到其中 12 个 matrix rows，效率另有 18 条 profile 记录；二者均不增加正式训练 run 数。实际 GPU 预算必须由 P07 的实测 epoch 时间推导，不在规划阶段虚构耗时。
- 显示名称统一为 `KST-Light`，代码 ID 统一为 `kst_light`；旧指南中的 `KSTProbFlowLight` 或 `kst_probflow_light` 不得进入新配置、artifact 或论文表格。

### 11.4 计划文件与代码边界

| 路径 | 计划职责 |
|---|---|
| `plan/experiment-protocol.md` | 锁定第三章数据、模型、指标、预算和泄漏规则 |
| `plan/review/method-experiment-traceability.md` | 创新一到模块、实验、表图和允许结论的映射 |
| `plan/stage-gates.md` | D0-D5 证据门禁状态 |
| `tables/table-schema.md` | 第三章表格字段、聚合和来源契约 |
| `figures/data-manifest.md` | 第三章图片数据源、脚本和导出文件登记 |
| `configs/ch3/*.yaml` | 只保存可移植的算法与实验设置，不保存机器绝对路径 |
| `code/kaf_profiti/experiments/runtime_paths.py` | CLI/env/config 路径解析与路径审计 |
| `code/kaf_profiti/experiments/masks.py` | timeline-first mask、窗口切片、实际缺失率和 schema v2 |
| `code/kaf_profiti/industrial/*.py` | 真实时间、`delta_t`、上下文策略和数据集样本字段 |
| `code/kaf_profiti/experiments/ch3/` | 第三章配置、模型、基线、runner、metrics、artifact、聚合和作图 |
| `code/run_ch3_experiment.py` | 单次第三章训练/评估 CLI |
| `code/run_ch3_matrix.py` | formal 矩阵展开、失败隔离、恢复和状态汇总 |
| `code/build_ch3_outputs.py` | 从冻结 artifact 生成第三章表图 |
| `code/tests/ch3/` | 第三章 unit/integration/protocol/leakage/formal-guard 测试 |

`code/build_tables.py` 及其 legacy Table 1-7 不属于第三章冻结管线；第三章正式输出只认 Ch3-T1..T8 与 Ch3-F1..F5。

---

### CH3-P00：锁定实验协议与证据合同

- [x] **Phase CH3-P00 完成：D0、D1、D2 文档门禁全部通过**

#### Task CH3-P00-T01：建立第三章实验协议

- [x] **Task CH3-P00-T01 完成：实验协议通过范围、泄漏和正式运行条件检查**

**文件：**
- 创建：`plan/experiment-protocol.md`
- 修改：`plan/stage-gates.md`（若不存在则创建）
- 参考：`3.2_结构框架.md:47`、`docs/毕业论文研究边界与总体方案.md:349`

- [x] 写入数据集角色：MetroPT-3 为完整主验证，FD004/TEP 为 4 模型外部验证。
- [x] 写入上述固定窗口、seeds、缺失设置、checkpoint 选择和 formal 判定条件。
- [x] 写入公平性规则：同 split、同 mask、同目标、同训练预算、train-only normalization。
- [x] 写入第三章禁止项：概率头、风险头、test 调参、手工改 metrics、smoke 入表。
- [x] 在 `plan/stage-gates.md` 建立 D0-D5 checkbox，并把 D0 保持未勾选直至本 Phase 全部完成。
- [x] 运行 `rg -n 'LowRankCopulaFlowHead|ProFITiFlowHead|RiskHead|test_best' plan/experiment-protocol.md`；预期仅在“禁止项”上下文出现。

**验收：** 协议中不存在未决模型、未决数据划分或未决指标；方案 A 的训练边界可直接转换为配置。

#### Task CH3-P00-T02：建立方法—实验追溯表

- [x] **Task CH3-P00-T02 完成：第三章每项机制均映射到实验和允许结论**（2026-09-02 复核：产物存在，`rg` 验证真实时间/delta_t/多尺度/工况/跨传感器五类机制均有记录，验收通过）

**文件：**
- 创建：`plan/review/method-experiment-traceability.md`

- [x] 建立字段 `Contribution | Method module | Experiment | Table/Figure | Allowed claim | Evidence status`。
- [x] 为真实时间、mask、delta_t、通道身份、工况、多尺度、跨传感器交互分别建立一行。
- [x] 把 E0、E1、E4、E5、E6 分别映射到第三章 3.6.2-3.6.6。
- [x] 为每行写出结论降级规则；当结果不支持时只能描述为设计或无显著改善。
- [x] 运行 `rg -n '真实时间|delta_t|多尺度|工况|跨传感器' plan/review/method-experiment-traceability.md`；预期五类机制均有记录。

**验收：** 第三章每个创新性机制至少有一个主实验或消融，且没有实验支撑的强结论被删除或降级。

#### Task CH3-P00-T03：建立表格与图片数据合同

- [x] **Task CH3-P00-T03 完成：8 张表与 5 张图均有数据来源合同**

**文件：**
- 创建：`tables/table-schema.md`
- 创建：`figures/data-manifest.md`

- [x] 在 `tables/table-schema.md` 定义 Ch3-T1 数据协议、Ch3-T2 主对比、Ch3-T3 缺失率、Ch3-T4 缺失机制、Ch3-T5 消融、Ch3-T6 敏感性、Ch3-T7 效率、Ch3-T8 外部验证。
- [x] 每张表写明主键、指标、单位、聚合规则、artifact 来源和允许结论。
- [x] 在 `figures/data-manifest.md` 定义 Ch3-F1 mask/时间线、Ch3-F2 鲁棒性曲线、Ch3-F3 消融效应、Ch3-F4 效率 Pareto、Ch3-F5 外部验证图。
- [x] 要求每张图同时输出 SVG 与 300 dpi PNG，数据只能来自聚合 CSV。
- [x] 运行 `rg -n 'Ch3-T[1-8]|Ch3-F[1-5]' tables/table-schema.md figures/data-manifest.md`；预期 8 张表和 5 张图编号完整。

**验收：** 所有计划实验都有落表位置，所有表图都能反向追溯到真实 run artifact。

#### Task CH3-P00-T04：完成协议自审并关闭 D0-D2

- [x] **Task CH3-P00-T04 完成：D0-D2 已记录验证证据并关闭**

**文件：**
- 修改：`plan/stage-gates.md`
- 修改：`plan/implementation-plan.md`

- [x] 扫描占位词：`rg -n 'T[B]D|T[O]DO|待[定]|稍后实[现]|视情[况]' plan/experiment-protocol.md plan/review/method-experiment-traceability.md tables/table-schema.md figures/data-manifest.md`；预期无输出。
- [x] 检查三个数据集、七个核心模型/变体族、三 seeds、五缺失率、四机制均有明确归属。
- [x] 勾选 D0、D1、D2，并记录审核日期和审核命令。
- [x] 立即勾选本 Task 和 Phase CH3-P00，不批量修改其他 Phase 状态。

**验收：** 任何执行智能体无需重新决定实验范围即可进入代码阶段。

---

### CH3-P01：可移植路径、配置和运行身份

- [ ] **Phase CH3-P01 完成：第三章代码不依赖机器绝对路径或固定远程地址**

#### Task CH3-P01-T01：实现统一运行时路径解析

- [x] **Task CH3-P01-T01 完成：路径优先级和 formal 路径检查测试通过**

**文件：**
- 创建：`code/kaf_profiti/experiments/runtime_paths.py`
- 创建：`code/tests/ch3/test_runtime_paths.py`

**API 合同：**

```python
@dataclass(frozen=True)
class RuntimePaths:
    project_root: Path
    data_root: Path
    output_root: Path

def resolve_runtime_paths(
    data_root: str | None,
    output_root: str | None,
    environ: Mapping[str, str],
    *,
    require_existing_data: bool = False,
) -> RuntimePaths: ...
```

- [x] 先写失败测试：CLI 覆盖环境变量，环境变量覆盖仓库相对默认值。
- [x] 写失败测试：解析结果必须为规范化 `Path`，不存在的 data root 在 formal 模式报明确错误。
- [x] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_runtime_paths.py -q`；预期因模块不存在而失败。
- [x] 实现上述 API；环境变量只使用 `KST_PROJECT_ROOT`、`KST_DATA_ROOT`、`KST_RESULT_ROOT`。
- [x] 重跑同一测试；预期全部通过。

**验收：** 新代码和 tracked YAML 无任何机器相关默认路径，运行时仍可在本机和 AutoDL 解析到各自目录。

#### Task CH3-P01-T02：建立第三章配置 schema

- [x] **Task CH3-P01-T02 完成：配置 schema、三数据集 YAML 与依赖验证通过**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/__init__.py`
- 创建：`code/kaf_profiti/experiments/ch3/config.py`
- 创建：`code/tests/ch3/test_ch3_config.py`
- 创建：`configs/ch3/metropt_main.yaml`
- 创建：`configs/ch3/fd004_external.yaml`
- 创建：`configs/ch3/tep_external.yaml`
- 修改：`requirement.txt`

**API 合同：**

```python
@dataclass(frozen=True)
class Ch3ExperimentConfig:
    experiment_id: str
    dataset: str
    model: str
    seed: int
    split_seed: int
    mask_seed: int
    history_len: int
    pred_len: int
    stride: int
    missing_mode: str
    target_missing_rate: float
    epochs: int
    batch_size: int
    hidden_dim: int
    head_type: str
    run_level: str
    max_train_batches: int | None
    max_eval_batches: int | None
```

- [x] 写失败测试：非法 seed、缺失率、head、run level、非正窗口长度必须拒绝。
- [x] 写失败测试：formal 配置不允许 `epochs < 2`、`max_train_batches > 0` 或 `max_eval_batches > 0`。
- [x] 运行配置测试并确认失败。
- [x] 在 `requirement.txt` 固定加入 `PyYAML==6.0.2`，由 `yaml.safe_load` 解析 YAML，禁止自制字符串解析器。
- [x] 实现 `from_yaml()`、CLI override 合并、`validate()` 和 `to_dict()`。
- [x] 将 `run_level` 固定为 `smoke/tuning/formal/profile`；tuning 禁止构造 test loader，formal 禁止 batch 截断并要求 `split_seed=2026`。
- [x] YAML 只保存相对配置与算法参数，不出现 data/output/remote 地址。
- [x] 重跑配置测试；预期全部通过。

**验收：** 三个数据集配置可加载，所有正式配置通过 schema，所有 smoke 限制无法伪装为 formal。

#### Task CH3-P01-T03：增加硬编码与内部链接质量门禁

- [x] **Task CH3-P01-T03 完成：新增代码、配置和文档零硬编码命中**

**文件：**
- 创建：`code/tests/ch3/test_portability_policy.py`
- 修改：`plan/implementation-plan.md`（只更新执行状态）

- [x] 写测试扫描 `code/`、`compare_code/`、`configs/ch3/` 和第三章新增文档中的机器路径、固定主机、账号和端口。
- [x] 写测试扫描第三章新增 Markdown 的仓库内部链接，要求全部使用相对路径。
- [x] 将当前遗留命中列为显式 allowlist，附文件、原因和 Phase 清除期限；新增文件不允许进入 allowlist。
- [x] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_portability_policy.py -q`。

**验收：** 第三章新增文件零硬编码；遗留命中可枚举且不会扩散。

---

### CH3-P02：timeline-first 缺失协议与实际缺失率

- [ ] **Phase CH3-P02 完成：所有窗口复用全局观测过程，实际缺失率符合标签**

#### Task CH3-P02-T01：定义缺失协议与 mask artifact schema v2

- [ ] **Task CH3-P02-T01 完成：mask schema v2、确定性与加载校验测试通过**

**文件：**
- 修改：`code/kaf_profiti/industrial/missing.py`
- 修改：`code/kaf_profiti/experiments/masks.py`
- 创建：`code/tests/ch3/test_missing_protocol.py`

**API 合同：**

```python
@dataclass(frozen=True)
class MissingProtocolConfig:
    mode: str
    target_rate: float
    tolerance: float = 0.01
    seed: int = 2026
    schema_version: int = 2

@dataclass(frozen=True)
class TimelineMask:
    dataset: str
    split: str
    values: np.ndarray
    shape: tuple[int, ...]
    unit_offsets: tuple[tuple[str, int, int], ...]
    realized_rate: float
    config: MissingProtocolConfig
    sha256: str
```

- [ ] 写失败测试：random 的 realized rate 必须落入目标 `+/- 0.01`。
- [ ] 写失败测试：同 config/seed 生成值与 SHA 完全一致，不同 seed 的 SHA 不同。
- [ ] 写失败测试：加载 artifact 时 shape、schema、dataset、split 或 config 不匹配必须拒绝。
- [ ] 运行测试确认失败。
- [ ] 实现 schema v2 元数据、哈希、验证和向后兼容只读加载；旧 v1 mask 不允许成为 formal artifact。
- [ ] 重跑测试确认通过。

**验收：** `missing_rate=0.30` 在 metrics 中代表实际约 30%，不再代表混合机制中的单个随机删除参数。

#### Task CH3-P02-T02：按原始 timeline/设备/run 生成 mask

- [ ] **Task CH3-P02-T02 完成：重叠窗口、单位边界和 split 边界测试通过**

**文件：**
- 修改：`code/kaf_profiti/experiments/masks.py`
- 修改：`code/kaf_profiti/experiments/datasets.py`
- 创建：`code/tests/ch3/test_timeline_mask_slicing.py`

- [ ] 写失败测试：MetroPT 重叠窗口同一 global row/sensor 的 mask 必须一致。
- [ ] 写失败测试：C-MAPSS 不同 engine、TEP 不同 simulation run 的 mask 状态互不串联。
- [ ] 写失败测试：train/valid/test 使用不同命名空间，任何 mask 不跨 split 边界。
- [ ] 实现 MetroPT 按 split 全局行、C-MAPSS 按 engine、TEP 按 run 生成 timeline mask，再按 `windows` 切片。
- [ ] 为每个窗口保存 `source_start`、`unit_id` 和 mask bundle SHA 关联信息。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_timeline_mask_slicing.py -q`；预期全部通过。

**验收：** 任意两个重叠窗口可由原始索引复原一致观测过程。

#### Task CH3-P02-T03：实现 matched-mechanism 缺失率控制

- [ ] **Task CH3-P02-T03 完成：四种机制的实际缺失率均在预设容差内**

**文件：**
- 修改：`code/kaf_profiti/industrial/missing.py`
- 创建：`code/tests/ch3/test_matched_missing_mechanisms.py`

- [ ] 写参数化失败测试覆盖 random、low_rate、block_offline、mixed 的目标率 0.30。
- [ ] 固定 low-rate 的周期分布、block 的长度/通道选择分布和 mixed 的组合规则。
- [ ] 实现确定性校准循环，只在生成器参数上匹配目标率，不读取 labels 或 test 结果。
- [ ] 当 0.01 容差无法达到时抛出错误，不静默保存错误标签的 mask。
- [ ] 运行 matched mechanism 测试；预期四种模式 realized rate 均在 `[0.29, 0.31]`。

**验收：** 机制比较改变缺失结构而非缺失总量，E4 可解释。

#### Task CH3-P02-T04：生成缺失协议审计报告

- [ ] **Task CH3-P02-T04 完成：E0 mask 审计 artifact 通过 schema 验证**

**文件：**
- 创建：`code/audit_ch3_masks.py`
- 计划生成：`result/ch3_protocol_audit/mask_audit.json`

- [ ] CLI 接收 dataset、config、data root、output root，不含机器默认路径。
- [ ] 输出每 split 的 shape、requested rate、realized rate、最长离线段、通道保留率、SHA 和重叠一致性计数。
- [ ] 在仓库数据上运行 MetroPT random 0.30 审计。
- [ ] 在仓库数据上运行 MetroPT 四机制 matched 0.30 审计。
- [ ] schema 验证器确认 `overlap_conflicts=0` 且所有 rate 在容差内。

**验收：** E0 的 mask 统计拥有独立、可引用的真实 artifact。

---

### CH3-P03：真实时间、delta_t 与上下文防旁路

- [ ] **Phase CH3-P03 完成：最终 batch 明确携带真实时间和基于最终 mask 的观测间隔**

#### Task CH3-P03-T01：MetroPT 使用窗口内真实相对秒数

- [ ] **Task CH3-P03-T01 完成：MetroPT 真实时间轴测试通过**

**文件：**
- 修改：`code/kaf_profiti/industrial/metropt.py`
- 修改：`code/tests/test_metropt_data.py`

- [ ] 先写失败测试：`T_obs[0] == 0`、`T_q[0] > T_obs[-1]`，且二者均来自 `relative_time`。
- [ ] 写失败测试：同一原始时间戳在重叠窗口中换算后的时间差保持一致。
- [ ] 先运行 `test -n "${KST_DATA_ROOT:-}"`；预期退出码 0，再运行 `PYTHONPATH=code python -m pytest code/tests/test_metropt_data.py -q` 并确认新增测试失败。
- [ ] 将 `torch.arange` 替换为以窗口起点归零的真实相对秒数，不构造伪 per-channel 时间戳。
- [ ] 重跑测试，预期新增测试通过且原 MetroPT 测试不退化。

**验收：** 论文可准确表述为“真实公共时间轴上的通道级稀疏异步观测”。

#### Task CH3-P03-T02：从最终 mask 计算真实 delta_t

- [ ] **Task CH3-P03-T02 完成：三数据集 delta_t 形状、单位和数值测试通过**

**文件：**
- 修改：`code/kaf_profiti/industrial/metropt.py`
- 修改：`code/kaf_profiti/industrial/cmapss.py`
- 修改：`code/kaf_profiti/industrial/tep.py`
- 修改：`code/kaf_profiti/industrial/batch.py`
- 修改：`code/kaf_profiti/experiments/masks.py`
- 创建：`code/tests/ch3/test_delta_t.py`

**API 合同：**

```python
def time_since_last_observation(times: Tensor, mask: Tensor) -> Tensor:
    """Return [L, N] elapsed time; observed entries are zero."""
```

- [ ] 写失败测试：连续观测位置为 0，缺失位置按真实时间累计，首次观测前从窗口起点累计。
- [ ] 写失败测试：`MaskedWindowDataset` 覆盖 mask 后重新计算 delta_t，不使用底层样本旧值。
- [ ] 给三个 sample dataclass 与 `IndustrialBatch` 增加 `delta_t`，并在 `.to()`、collator 中完整透传。
- [ ] 实现上述函数，MetroPT 用秒、C-MAPSS 用 cycle、TEP 用 sample step；在 manifest 记录单位。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_delta_t.py code/tests/test_cmapss_data.py code/tests/test_metropt_data.py -q`。

**验收：** 三个数据集 batch 均有有限、非负、形状为 `[B,L,N]` 的 delta_t。

#### Task CH3-P03-T03：锁定上下文可见性策略

- [ ] **Task CH3-P03-T03 完成：上下文无法旁路 mask 或读取未来信息**

**文件：**
- 创建：`code/kaf_profiti/industrial/context_policy.py`
- 修改：`code/kaf_profiti/industrial/metropt.py`
- 修改：`code/kaf_profiti/industrial/tep.py`
- 创建：`code/tests/ch3/test_context_leakage.py`

- [ ] 将 context 分为 `exogenous_always_observed` 与 `derived_from_observed` 两类，默认使用后者。
- [ ] 写失败测试：当 context 列与 sensor 列重叠时，被 mask 的值不得通过 context 保留原值。
- [ ] 写失败测试：context 只能使用历史窗口，不能读取 future 或 test normalization statistics。
- [ ] 实现 observed-only mean/last 聚合；分母为有效观测数，空通道使用 train-only 常数并记录 missing indicator。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_context_leakage.py -q`。

**验收：** MetroPT 的 COMP/DV_eletric/MPG 和 TEP 的 XMV 不再绕过人工缺失进入模型。

#### Task CH3-P03-T04：完成数据协议回归测试

- [ ] **Task CH3-P03-T04 完成：完整数据协议回归结果已记录到阶段门禁**

**文件：**
- 修改：`code/tests/test_experiment_framework.py`
- 修改：`code/tests/test_tep_data.py`

- [ ] 增加 train-only normalization、split 无重叠、window 不越界、timestamp 单调、mask SHA 复用测试。
- [ ] TEP 数据不存在时使用明确 skip marker；存在时运行 faulty/fault-free 协议测试。
- [ ] 先运行 `test -n "${KST_DATA_ROOT:-}"`；预期退出码 0，再运行 `PYTHONPATH=code python -m pytest code/tests/ -q`。
- [ ] 记录通过数、skip 数和失败原因到 `plan/stage-gates.md`。

**验收：** 非 TEP 测试全部通过；TEP 有数据则全部通过，无数据则只产生声明清楚的 skip。

---

### CH3-P04：KST-Light、轻量点预测头与受控消融 API

- [ ] **Phase CH3-P04 完成：KST-Light 只输出点预测，七类消融可独立启停**

**前置依赖：** CH3-P01 配置 schema、CH3-P03 的真实时间、`delta_t` 和 context policy 全部通过。

#### Task CH3-P04-T01：建立 history-only 输入与共享轻量头合同

- [ ] **Task CH3-P04-T01 完成：history-only 类型边界、Linear/MLP 头及梯度测试通过**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/types.py`
- 创建：`code/kaf_profiti/models/lightweight_head.py`
- 创建：`code/tests/ch3/test_lightweight_head.py`

**API 合同：**

```python
@dataclass(frozen=True)
class Ch3HistoryBatch:
    X_obs: Tensor
    T_obs: Tensor
    M_obs: Tensor
    delta_t: Tensor
    context: Tensor

class LightweightForecastHead(nn.Module):
    def __init__(self, hidden_dim: int, pred_len: int, head_type: Literal["linear", "mlp"]): ...
    def forward(self, z_var: Tensor) -> Tensor: ...  # [B,N,H] -> [B,P,N]
```

- [ ] 先写失败测试：`Ch3HistoryBatch` 字段精确等于上述五项，不含 target、RUL、risk 或 test 指标。
- [ ] 写失败测试：Linear/MLP 对 `[2,7,16]` 均输出 `[2,5,7]`，数值与梯度有限。
- [ ] 写失败测试：非法 head、非三维表示或 hidden 维不匹配均抛出含实际 shape 的 `ValueError`。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_lightweight_head.py -q`；预期因模块不存在而失败。
- [ ] 实现共享 per-sensor 头：Linear 为 `Linear(H,P)`，MLP 为 `Linear(H,H)-ReLU-Linear(H,P)`；不得做 sensor mean pooling。
- [ ] 重跑同一命令；预期全部通过。

**验收：** 轻量头不接查询适配器，不产生 scale、sample、quantile 或 risk，输出与 `Y_q` 一一对齐。

#### Task CH3-P04-T02：实现七类单因素消融配置

- [ ] **Task CH3-P04-T02 完成：七项消融逐一生效且默认路径不退化**

**文件：**
- 创建：`code/kaf_profiti/models/ablation.py`
- 修改：`code/kaf_profiti/models/kafnet_encoder.py`
- 修改：`code/kaf_profiti/experiments/ch3/config.py`
- 创建：`code/tests/ch3/test_encoder_ablation.py`
- 修改：`code/tests/ch3/test_ch3_config.py`

**API 合同：**

```python
@dataclass(frozen=True)
class EncoderAblation:
    time: bool = False
    delta: bool = False
    mask: bool = False
    channel: bool = False
    context: bool = False
    multiscale: bool = False
    cross_sensor: bool = False

    @classmethod
    def from_name(cls, name: str) -> "EncoderAblation": ...
```

- [ ] 固定名称 `none/time/delta/mask/channel/context/multiscale/cross_sensor`；formal 配置只允许 `none` 或一个开关为真。
- [ ] 固定语义：`time` 改用归一化顺序索引并跳过 learned time embedding；`delta` 跳过 delta projection；`mask` 保留 zero-filled X 但内部传全 1 mask。
- [ ] 固定语义：`channel` 跳过通道身份位置编码；`context` 跳过 FiLM；`multiscale` 只保留 global KAF；`cross_sensor` 同时跳过 FreqBlock 和动态图。
- [ ] delta 注入固定为 `log1p(delta_t.clamp_min(0)).mean(dim=1).unsqueeze(-1)` 后经线性层投影。
- [ ] 先写失败测试：名称可往返、formal 多开关被拒绝、七项均保持 `[B,N,H]` 和有限梯度。
- [ ] 用 forward hook 写失败测试，证明开关确实跳过对应模块，且不原地修改任何输入。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_encoder_ablation.py code/tests/ch3/test_ch3_config.py -q`；预期失败。
- [ ] 实现最小分支控制并重跑；随后运行 `PYTHONPATH=code python -m pytest code/tests/test_model_components.py -q`。

**验收：** 每个变体只移除一个声明机制；`none` 与原编码器默认数值路径一致。

#### Task CH3-P04-T03：提取共享动态图并实现 KST-Light

- [ ] **Task CH3-P04-T03 完成：KST-Light 前向、反传、存取和禁止头测试通过**

**文件：**
- 创建：`code/kaf_profiti/models/sensor_graph.py`
- 创建：`code/kaf_profiti/models/kst_light.py`
- 修改：`code/kaf_profiti/models/kst_probflow.py`
- 修改：`code/kaf_profiti/models/__init__.py`
- 创建：`code/tests/ch3/test_kst_light.py`
- 修改：`code/tests/test_model_components.py`

**API 合同：**

```python
@dataclass(frozen=True)
class KSTLightConfig:
    num_sensors: int
    context_dim: int
    pred_len: int
    hidden_dim: int
    te_dim: int
    kernel_count: int
    n_layers: int
    n_heads: int
    preconv_dim: int
    patch_lens: tuple[int, ...]
    graph_layers: int
    head_type: Literal["linear", "mlp"]
    ablation: EncoderAblation

class KSTLight(nn.Module):
    def encode_variables(self, history: Ch3HistoryBatch) -> Tensor: ...
    def forward(self, history: Ch3HistoryBatch) -> Tensor: ...
```

- [ ] 先写失败测试：表示为 `[B,N,H]`、预测为 `[B,P,N]`、masked MAE 可反传且参数梯度有限。
- [ ] 写失败测试：模型对象和 `state_dict` 不含 `adapter/flow_head/quantile_head/risk_head`。
- [ ] 写失败测试：`cross_sensor` 同时跳过 encoder 交互和动态图；保存重载后预测逐元素一致。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_kst_light.py -q`；预期失败。
- [ ] 将 `DynamicSensorGraphBlock` 原样移到 `sensor_graph.py`，旧概率模型改为导入共享类，行为不变。
- [ ] 实现 `KSTLight`，重跑新测试与 `code/tests/test_model_components.py`。

**验收：** KST-Light 科学模块只有 encoder、graph、lightweight head，第三章不依赖概率模型文件构造模型。

#### Task CH3-P04-T04：建立第三章专用模型 registry 与静态边界门禁

- [ ] **Task CH3-P04-T04 完成：专用 registry 和禁止头 AST 扫描通过**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/model_registry.py`
- 修改：`code/kaf_profiti/experiments/ch3/__init__.py`
- 创建：`code/tests/ch3/test_ch3_model_registry.py`

- [ ] 定义 `Ch3ModelSpec(model_id, display_name, required_input_protocol, implemented, provenance_id)`。
- [ ] P04 只启用 `kst_light`；P06 再增加五个正式基线，未知或未实现 ID 必须明确拒绝。
- [ ] 写失败测试：第三章 runner 不调用全局 `experiments.registry.create_model()`。
- [ ] 写 AST 失败测试：`experiments/ch3/` 与 `kst_light.py` 不得实例化四个禁止头。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_ch3_model_registry.py -q`；预期失败后实现并重跑。

**验收：** 第三章模型创建路径与第四、第五章 registry 分离。

---

### CH3-P05：独立 point-only runner、artifact schema 与 formal/smoke guard

- [ ] **Phase CH3-P05 完成：单 run 与矩阵 runner 可训练、恢复、校验并生成 point-only artifact**

**前置依赖：** CH3-P04 全部通过。

#### Task CH3-P05-T01：实现四种 history-only 输入协议

- [ ] **Task CH3-P05-T01 完成：四种协议数值、方向性和目标隔离测试通过**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/input_protocols.py`
- 修改：`code/kaf_profiti/experiments/ch3/config.py`
- 创建：`code/tests/ch3/test_input_protocols.py`

```python
def apply_input_protocol(
    history: Ch3HistoryBatch,
    protocol: Literal["native_sparse", "linear_interpolation", "forward_fill", "masked_input"],
    train_fill: Tensor,
) -> Ch3HistoryBatch: ...
```

- [ ] `native_sparse` 保留真实时间、mask、delta；linear 只在历史观测之间插值；forward fill 只沿过去方向；masked input 使用 zero-fill+mask 和规则索引。
- [ ] 边界与全空通道只能使用 train-only 归一化均值；四种适配均不得接收 `Y_q/M_q`。
- [ ] 先写手工数组失败测试，覆盖首段、尾段、内部缺失、全空通道和不规则时间。
- [ ] 写失败测试：任意改变 target 后适配输出不变，且输入未被原地修改。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_input_protocols.py -q`；预期失败后实现并重跑。

**验收：** 插值和填充无法读取 forecast start 之后的任何值。

#### Task CH3-P05-T02：实现全局点指标和可复现效率计时

- [ ] **Task CH3-P05-T02 完成：全局 MAE/RMSE 与 CUDA 计时测试通过**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/metrics.py`
- 创建：`code/tests/ch3/test_ch3_metrics.py`

- [ ] 定义 `masked_mae_loss()` 与累积 absolute-error sum、squared-error sum、valid-count 的 `PointMetricAccumulator`。
- [ ] 写失败测试：两个不同大小 batch 的结果等于拼接后全局计算，不等于 batch 指标等权平均。
- [ ] 写失败测试：mask=0 与非有限位置被排除；有效位置为零必须报错。
- [ ] 定义 CUDA 前后同步的 `profile_inference()`，返回全部 repeat 原始毫秒值而非只返回均值。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_ch3_metrics.py -q`；预期失败后实现并重跑。

**验收：** 第三章指标模块只产生 MAE、RMSE、有效位置数和效率字段。

#### Task CH3-P05-T03：定义 point-only artifact schema v1

- [ ] **Task CH3-P05-T03 完成：artifact writer、SHA、相对路径和 validator 测试通过**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/artifacts.py`
- 创建：`code/kaf_profiti/experiments/ch3/profile_artifacts.py`
- 创建：`code/tests/ch3/test_ch3_artifacts.py`
- 创建：`code/tests/ch3/test_ch3_profile_artifacts.py`

**固定目录：**

```text
result/ch3/runs/<run_id>/
  manifest.json
  config/resolved.json
  splits/split.json
  masks/mask-ref.json
  metrics/valid.json
  metrics/test.json
  predictions/test.npz
  checkpoints/best.pt
  checkpoints/last.pt
  history.jsonl
result/ch3/run-index.jsonl

result/ch3/profiles/<profile_id>/
  manifest.json
  benchmark.json
result/ch3/profile-index.jsonl
```

- [ ] 预测 run manifest 分开记录 `run_level=smoke/tuning/formal`、`execution_status=created/running/succeeded/failed/interrupted` 和 evidence status。
- [ ] 预测 evidence status 只允许 `interface_only/smoke_passed/full_completed/formal_validated`；预测聚合器还必须要求 `run_level=formal`。
- [ ] profile manifest 固定 `run_level=profile`，使用独立 `profile_validation_status=created/validated/rejected`；只保存冻结 source checkpoint 引用和 benchmark，不生成 test prediction 或获得 `formal_validated`。
- [ ] 定义 `EfficiencyProfileRef`：`profile_id/source_run_id/source_formal_key/source_checkpoint_sha/benchmark_config_sha/batch_sequence_sha/device_fingerprint/raw_repeats_sha` 必填，路径全部相对 result root。
- [ ] metrics 固定含 dataset、model、variant、seed、split/mask/config/code/protocol SHA、realized rate、MAE、RMSE、valid count、参数量和时间。
- [ ] `predictions/test.npz` 固定含 `y_true/y_pred/target_mask/window_id/unit_id/source_start/T_q`，并可在 `allow_pickle=False` 下读取。
- [ ] 所有持久化路径相对 result root；运行时可采集硬件与版本，但不得让代码依赖已解析的机器路径。
- [ ] 写失败测试：缺文件、错误 shape/SHA、绝对路径、概率/风险字段、重复 run/profile ID、profile 伪装 formal 或 manifest/index 状态不一致均拒绝。
- [ ] 使用临时文件加原子 rename 写 manifest；预测 run 与 profile 分别只有在各自 validator 通过后，才带锁追加对应 index。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_ch3_artifacts.py code/tests/ch3/test_ch3_profile_artifacts.py -q`；预期失败后实现并重跑。

**验收：** 任一 `formal_validated` run 或 `profile_validation_status=validated` profile 均可由各自 index 定位并复核；两类 artifact 不能相互冒充。

#### Task CH3-P05-T04：实现 formal eligibility 与状态转换门禁

- [ ] **Task CH3-P05-T04 完成：smoke/tuning/profile 无法冒充 formal**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/guards.py`
- 修改：`code/kaf_profiti/experiments/ch3/config.py`
- 创建：`code/tests/ch3/test_run_level_guards.py`

- [ ] smoke 可限 epoch/batch，终态只能 `smoke_passed`；tuning 禁止构造 test loader；profile 只读冻结 checkpoint。
- [ ] formal 必须使用核心 seed、fixed split seed、schema v2 mask、完整 loader、validation MAE checkpoint、一次 test 和 clean Git SHA。
- [ ] formal CLI 只允许覆盖 data/output root、device、run ID、seed 和 resume；科学配置来自 tracked YAML。
- [ ] 写参数化失败测试覆盖限 batch、少 epoch、非法 seed、dirty Git、旧 mask、test 选模和额外 CLI 科学覆盖。
- [ ] `--validate-only` 只输出 eligibility，不创建成功 artifact。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_run_level_guards.py -q`；预期失败后实现并重跑。

**验收：** 文件改名或字段手改不能把非正式运行变成 `formal_validated`。

#### Task CH3-P05-T05：实现独立单 run trainer/evaluator 与 CLI

- [ ] **Task CH3-P05-T05 完成：单 run 训练、恢复、一次 test 和 CLI 测试通过**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/runner.py`
- 创建：`code/run_ch3_experiment.py`
- 创建：`configs/ch3/metropt_smoke.yaml`
- 创建：`code/tests/ch3/test_ch3_runner.py`
- 创建：`code/tests/ch3/test_ch3_cli.py`

- [ ] 固定 Python、NumPy、PyTorch、CUDA、DataLoader RNG；checkpoint 同时保存 RNG 状态。
- [ ] loss 固定 masked MAE；每 epoch 只训练/验证；按 validation MAE 保存 best；best 冻结后 test loader 只遍历一次。
- [ ] 写 synthetic 失败测试：两个 epoch 选中更低 validation MAE，test spy 访问计数为 1。
- [ ] 写失败测试：resume 只接受相同 config/scientific/protocol hash；异常只写 `failure.json`，不写成功 manifest。
- [ ] CLI 固定支持 `--config/--data-root/--output-root/--run-id/--seed/--run-level/--resume/--validate-only`。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_ch3_runner.py code/tests/ch3/test_ch3_cli.py -q`；预期失败后实现并重跑。
- [ ] 运行 formal `--validate-only`；预期 JSON 为 eligible 且未创建 run。

**验收：** runner 源码不存在 distribution/sample/NLL/CRPS/quantile/risk 调用，也不复用 `code/run_experiment.py`。

#### Task CH3-P05-T06：实现规范化 run identity 与失败隔离矩阵 runner

- [ ] **Task CH3-P05-T06 完成：矩阵展开、去重、失败隔离和恢复测试通过**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/matrix.py`
- 创建：`code/run_ch3_matrix.py`
- 创建：`code/tests/ch3/test_ch3_matrix_runner.py`

```python
@dataclass(frozen=True, order=True)
class FormalRunKey:
    dataset: str
    model: str
    variant: str
    seed: int
    condition_key: str
```

- [ ] `condition_key` 由规范化科学配置生成，不含 experiment family、run ID、时间戳、机器路径或执行顺序；同一科学运行可被多个表格族引用。
- [ ] 写失败测试：配置顺序不改变 key/hash，失败条目不中断后续条目，未通过 validator 的残缺目录不能被 resume 跳过。
- [ ] 写失败测试：同 key 已有 formal artifact 时记录 `source_run_id` 而不重复训练；绝对路径、非法 seed/model 或 smoke 限制进入 formal 矩阵时拒绝。
- [ ] `--dry-run` 只生成 matrix manifest；`--continue-on-error` 记录每条终态；`--resume` 只跳过已验证 run。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_ch3_matrix_runner.py -q`；预期失败后实现并重跑。

**验收：** matrix manifest 能重建 expected、new、reused、failed 和 completed keys，单次失败不会损坏整批。

---

### CH3-P06：五类公平基线与 fidelity gate

- [ ] **Phase CH3-P06 完成：LI+TCN、FF+GRU、Masked TCN、GRU-D、ODE-RNN 接入统一 point-only 接口**

**前置依赖：** CH3-P05 全部通过。

#### Task CH3-P06-T01：建立 baseline 公共合同和 preprocessing 映射

- [ ] **Task CH3-P06-T01 完成：五模型公共 shape、协议映射和禁止头测试通过**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/baselines/__init__.py`
- 创建：`code/kaf_profiti/experiments/ch3/baselines/base.py`
- 创建：`code/tests/ch3/test_baseline_contract.py`

- [ ] 固定输出 `[B,P,N]`，禁止实现 distribution/sample/NLL/CRPS/risk。
- [ ] 固定映射：`li_tcn -> linear_interpolation`、`ff_gru -> forward_fill`、`masked_tcn -> masked_input`、`gru_d/ode_rnn -> native_sparse`。
- [ ] 写失败测试：错误 input protocol 在构造前拒绝；静态扫描 baseline 包不导入概率/风险头。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_baseline_contract.py -q`；预期失败后实现并重跑。

**验收：** baseline 只在表示/预处理上不同，使用同一 loss、target 和 evaluator。

#### Task CH3-P06-T02：适配 LI+TCN 与 Masked TCN

- [ ] **Task CH3-P06-T02 完成：共享 causal TCN 的两种输入路径测试通过**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/baselines/tcn.py`
- 创建：`code/tests/ch3/test_li_tcn.py`
- 创建：`code/tests/ch3/test_masked_tcn.py`

- [ ] 从 `compare_code/TCN-Gaussian` 提取 causal TCN backbone，删除 Gaussian scale/sample/NLL。
- [ ] LI+TCN 只接 dense linear interpolation；Masked TCN 精确接 `concat(X*M,M,context)` 且不插值。
- [ ] 写失败测试：非 dense LI 输入拒绝、相同 zero-filled value 不同 mask 使 Masked TCN 表示不同、两者 shape/梯度有限。
- [ ] 写 future-target 扰动测试，证明 causal backbone 与 adapter 均不读取 target。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_li_tcn.py code/tests/ch3/test_masked_tcn.py -q`；预期失败后实现并重跑。

**验收：** 两模型共享相同 TCN 容量和 point decoder，唯一主要差异为输入协议。

#### Task CH3-P06-T03：实现 FF+GRU

- [ ] **Task CH3-P06-T03 完成：单向 GRU 与 forward-fill 边界测试通过**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/baselines/gru.py`
- 创建：`code/tests/ch3/test_ff_gru.py`

- [ ] 使用单向 GRU encoder 和 point decoder，不得使用双向或 future context。
- [ ] 写失败测试：首段/全空用 train-only fill，后续只用最近历史值，输出与梯度有限。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_ff_gru.py -q`；预期失败后实现并重跑。

**验收：** 任一时刻填充值不依赖其后的历史观测或预测目标。

#### Task CH3-P06-T04：实现标准 GRU-D 衰减

- [ ] **Task CH3-P06-T04 完成：GRU-D 公式、单调衰减和 train-mean 隔离测试通过**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/baselines/grud.py`
- 创建：`code/tests/ch3/test_grud.py`

```text
gamma_x = exp(-relu(W_x * delta_t + b_x))
gamma_h = exp(-relu(W_h * delta_t + b_h))
x_hat = M*x + (1-M)*(gamma_x*x_last + (1-gamma_x)*train_mean)
h = GRUCell(concat(x_hat,M), gamma_h*h)
```

- [ ] 写失败测试：观测/缺失位置严格符合公式，delta 增大时 gamma 不增大。
- [ ] 写失败测试：首次观测前、全空通道有限；改变 valid/test 均值不改变 train mean。
- [ ] 使用 P03 基于最终 mask 的 `delta_t`，不得在模型内用规则索引重算。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_grud.py -q`；预期失败后实现并重跑。

**验收：** GRU-D 公式、输入和论文来源在 fidelity 记录中一一对应。

#### Task CH3-P06-T05：实现非代理版 ODE-RNN

- [ ] **Task CH3-P06-T05 完成：ODE solver、事件更新、真实时间和依赖测试通过**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/baselines/ode_rnn.py`
- 创建：`code/tests/ch3/test_ode_rnn.py`
- 修改：`requirement.txt`

- [ ] 在 `requirement.txt` 固定加入 `torchdiffeq==0.2.5`；使用 `odeint`，formal solver 固定 `dopri5`、`rtol=1e-4`、`atol=1e-5`。
- [ ] 每个真实观测时刻先按非负 dt 演化 hidden，再仅对有观测事件执行 GRUCell update；全空时刻只演化。
- [ ] 写失败测试：规则/不规则间隔产生不同 hidden，dt=0 不演化，负 dt 拒绝，全空时刻不调用观测更新。
- [ ] 写 shape、有限值、梯度和 target 扰动测试。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_ode_rnn.py -q`；预期失败后实现并重跑。

**验收：** 现有 Euler 简化实现只能作为参考，未通过本 Task 不得以 `ODE-RNN` 名称进入正式表。

#### Task CH3-P06-T06：完成来源、行为 fidelity 和 registry 接入

- [ ] **Task CH3-P06-T06 完成：六模型 registry、来源追溯和全模型 smoke 测试通过**

**文件：**
- 修改：`code/kaf_profiti/experiments/ch3/model_registry.py`
- 创建：`plan/review/ch3-baseline-fidelity.md`
- 创建：`code/tests/ch3/test_all_ch3_models.py`
- 修改：`code/tests/ch3/test_ch3_model_registry.py`

- [ ] registry 精确包含 `kst_light/li_tcn/ff_gru/masked_tcn/gru_d/ode_rnn`，显示名与论文表一致。
- [ ] 为每个基线记录论文、公开实现/算法来源、版本或 commit、许可证、本地改动和未实现差异。
- [ ] 参数化测试六模型接受同一 synthetic history，输出同 shape；相同 seed 初始参数一致。
- [ ] fidelity 文档逐项核对插值方向、TCN causality、GRU 方向、GRU-D 公式和 ODE solver。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_ch3_model_registry.py code/tests/ch3/test_all_ch3_models.py -q`。
- [ ] 运行既有 compare tests，确认参考工程不退化；第三章运行时不得从 `compare_code/` 动态导入。

**验收：** 六模型均 `implemented=True` 且通过 fidelity gate；代理实现不得使用正式名称。

---

### CH3-P07：unit、integration、protocol、leakage 与 formal preflight

- [ ] **Phase CH3-P07 完成：正式矩阵具备可复现、可预算且不可越过的工程前置门禁**

**前置依赖：** CH3-P00 至 CH3-P06 全部通过；本 Phase 不勾选 D3。

#### Task CH3-P07-T01：关闭 synthetic unit 与 integration gate

- [ ] **Task CH3-P07-T01 完成：六模型端到端 synthetic smoke 及 artifact 验证通过**

**文件：**
- 创建：`code/tests/ch3/fakes.py`
- 创建：`code/tests/ch3/test_unit_gate.py`
- 创建：`code/tests/ch3/test_runner_integration.py`

- [ ] 参数化检查六模型、两种 head、八种消融状态和四种输入协议的 shape、有限值、backward、state round-trip。
- [ ] 用 train/valid/test 各至少两 batch 的 synthetic bundle 跑六模型 1 epoch，输出到 pytest `tmp_path`。
- [ ] 验证每个 run 的 manifest、metrics、prediction、history、best/last checkpoint 和 run-index。
- [ ] 验证 smoke evidence status 只能为 `smoke_passed`，所有 synthetic unit tests 零 skip/xfail。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_unit_gate.py code/tests/ch3/test_runner_integration.py -q`。

**验收：** 六模型走同一 trainer、loss、validation MAE checkpoint 与 writer。

#### Task CH3-P07-T02：关闭 protocol 与 leakage gate

- [ ] **Task CH3-P07-T02 完成：split/mask/normalization/target 公平性和泄漏测试通过**

**文件：**
- 创建：`code/tests/ch3/test_protocol_gate.py`
- 创建：`code/tests/ch3/test_ch3_leakage_gate.py`

- [ ] 检查同 dataset/condition/seed 六模型的 split、mask、normalization、target SHA 相同，不同 seed mask SHA 不同。
- [ ] 扰动 valid/test 值，确认 train statistics/fill/split/mask 不变；扰动 target，确认 history adapter 和模型输入不变。
- [ ] test spy 在训练期访问即报错；冻结 best 后访问次数严格为 1。
- [ ] 检查 timeline overlap、unit/run 边界、delta 单位、context policy 和 checkpoint metric 均进入 manifest。
- [ ] 运行 protocol、timeline、delta、context 和 leakage 测试全集；TEP 缺数据只能明确 skip，MetroPT/FD004 不得跳过。

**验收：** future value、test statistics、test label 和被 mask context 均无进入训练或选模的路径。

#### Task CH3-P07-T03：关闭禁止头、可移植性和 formal guard

- [ ] **Task CH3-P07-T03 完成：AST、路径、formal 配置和 SHA 门禁通过**

**文件：**
- 创建：`code/tests/ch3/test_forbidden_ch3_features.py`
- 创建：`code/tests/ch3/test_formal_preflight.py`

- [ ] AST 扫描第三章包、baseline 和 KST-Light，禁止实例化/调用四个禁止头及概率风险指标。
- [ ] 扫描 tracked 配置/文档/代码，新增内容不得含机器绝对路径、账号、主机、IP 或固定端口。
- [ ] 验证 formal seed、窗口、完整 loader、mask schema、clean Git 和 CLI override 白名单。
- [ ] 验证 scientific/protocol/config/split/mask SHA 为 64 位小写十六进制且矩阵内语义一致。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_forbidden_ch3_features.py code/tests/ch3/test_formal_preflight.py code/tests/ch3/test_run_level_guards.py code/tests/ch3/test_portability_policy.py -q`。

**验收：** 第三章边界与 formal 资格由自动门禁执行。

#### Task CH3-P07-T04：执行六模型真实 MetroPT smoke

- [ ] **Task CH3-P07-T04 完成：六个真实 smoke artifact 均通过 validator 且不具备正式资格**

**文件：**
- 创建：`configs/ch3/preflight_smoke.yaml`
- 修改：`plan/stage-gates.md`

- [ ] 先运行 `test -n "${KST_DATA_ROOT:-}"` 和 `test -n "${KST_RESULT_ROOT:-}"`；两者预期退出码 0。
- [ ] 用 `run_ch3_matrix.py --run-level smoke` 执行六模型、seed 2026、1 epoch、各 2 train/eval batches。
- [ ] 预期 6/6 status 为 `smoke_passed`，artifact validator 零错误，run-index 无重复。
- [ ] 运行 formal `--validate-only`；预期 tracked formal 配置 eligible，且不创建 formal run。
- [ ] 记录命令、run IDs、manifest SHA、通过数和日期；明确 smoke 永不被 P13 聚合。

**验收：** 真实数据链路可运行，且 smoke 无法进入正式证据。

#### Task CH3-P07-T05：执行等预算 validation-only 超参数选择并冻结配置

- [ ] **Task CH3-P07-T05 完成：六模型的冻结配置只由 validation MAE 选择**

**文件：**
- 创建：`configs/ch3/tuning/e1_learning_rate.yaml`
- 创建：`configs/ch3/frozen/model_hparams.yaml`
- 创建：`code/tests/ch3/test_tuning_guard.py`
- 计划生成：`result/ch3/tuning/e1-selection.json`

- [ ] 六模型固定 `hidden_dim=64`、MLP point head 和同一数据协议；每模型只扫描 `lr=1e-3/3e-4/1e-4`，seed 2026、最多 15 epoch、patience 5。
- [ ] tuning runner 只构造 train/valid loader；任何 test dataset 访问立即失败，tuning artifact 永不具备 formal 资格。
- [ ] 每模型以最低 validation MAE 选择；并列时按较小学习率的预注册顺序决胜，不读取 test、训练时间或参数量。
- [ ] 将六个选定学习率及共享架构写入 `configs/ch3/frozen/model_hparams.yaml`，保存 selection report SHA；P08-P12 formal 配置只能引用该冻结文件。
- [ ] 写测试：候选数不是 18、选择器读取 test、缺失候选或冻结配置与 selection report 不一致时失败。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_tuning_guard.py -q`，再执行 tuning matrix 并验证 18/18 `run_level=tuning`。

**验收：** 正式训练开始前六模型配置已经冻结；后续不得因 test 排名重新选择学习率。

#### Task CH3-P07-T06：实测 GPU 预算并锁定执行顺序

- [ ] **Task CH3-P07-T06 完成：165 个唯一 formal run 的预算和恢复策略由实测数据生成**

**文件：**
- 创建：`configs/ch3/preflight_profile.yaml`
- 创建：`code/estimate_ch3_budget.py`
- 创建：`code/tests/ch3/test_ch3_budget.py`
- 修改：`plan/stage-gates.md`

- [ ] 在同一目标 GPU 上为六模型各运行 2 个完整 profile epoch，保存每 epoch 时间、峰值显存和 batch throughput；profile 不评估 test。
- [ ] 预算公式固定为 `median_epoch_sec * formal_epochs * new_run_count / 3600 * 1.15`，其中 15% 为 I/O/恢复余量。
- [ ] 分别输出 P08=12、P09=15、P10=84、P11=30、P12=24 个新训练的 GPU-hour 估算及总计 165。
- [ ] 单卡按 Phase 串行执行，单 run 失败不终止矩阵；每个成功 run 立即校验和同步结果。
- [ ] 写测试：缺任一模型 profile、用 smoke 时间代替或 run 计数不等于 165 时预算命令失败。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_ch3_budget.py -q`，再生成 `result/ch3/preflight/budget.json`。
- [ ] 若实测总预算超过可用 GPU 资源，按以下预注册顺序缩减范围，每执行一级必须写范围变更记录（含触发的实测数字、新 expected counts、对结论的影响），并同步更新本文件与 matrix YAML 的 expected counts；禁止静默少跑：
  1. E5-S 敏感性：10 个 off-center 配置减为 5 个（每 factor 只保留一个离中心最远的取值），新训练 9→5；
  2. E4 random 缺失率扫描：5 点减为 3 点（保留预注册 reference `0.00`、主设置 `0.30`、极端 `0.70`），新训练 84→60；
  3. E1-X 外部验证：FD004/TEP 各由 4 模型减为 2 模型（保留 `li_tcn` 基线与 `kst_light`），新训练 24→12，外部有效性结论相应降级为“双模型证据”；
  4. 最后手段：seeds 3→2，且必须在论文局限性一节显式声明统计功效下降。
- [ ] 缩减决策只依据 `budget.json` 的实测总时长与可用资源上限，不得依据任何中间实验结果方向选择缩减对象。

**验收：** GPU 时间来自目标硬件实测而非主观估计；若资源不足，必须按上述阶梯形成范围变更记录，不能静默少跑 seed/模型/条件。

#### Task CH3-P07-T07：执行全量 preflight 并关闭 Phase

- [ ] **Task CH3-P07-T07 完成：全测试、真实 smoke、冻结超参数、预算和 eligibility 证据已登记**

**文件：**
- 修改：`plan/stage-gates.md`
- 修改：`plan/implementation-plan.md`（只更新当前 Task/Phase 状态）

- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/ -q`；预期 synthetic 测试零失败。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ -q`；预期既有非数据缺失测试不退化。
- [ ] 核验 6 个 smoke、18 个 tuning、冻结超参数、1 份 budget、formal eligibility、baseline fidelity 和 portability 报告的 SHA。
- [ ] 在 stage gates 新增 `CH3 engineering preflight=passed`，但 D3、D4、D5 全部保持未勾选。
- [ ] 立即勾选本 Task 与 Phase CH3-P07，不批量勾选 P08 以后任务。

**验收：** 后续只需消费已锁定配置并运行正式矩阵，不再重新决定科学范围。

---

### CH3-P08：E0 数据协议有效性正式实验

- [ ] **Phase CH3-P08 完成：三数据集协议审计通过，MetroPT-3 E0 的 12 个 run 全部 formal validated**

**前置依赖：** CH3-P00 至 CH3-P07 全部完成；运行前 `KST_DATA_ROOT` 与 `KST_RESULT_ROOT` 已由环境提供。

#### Task CH3-P08-T01：锁定四协议 × 三 seed 的 E0 矩阵

- [ ] **Task CH3-P08-T01 完成：E0 dry-run 精确展开 12 个唯一正式条件**

**文件：**
- 创建：`configs/ch3/matrices/e0_protocol.yaml`
- 创建：`code/tests/ch3/test_e0_protocol_matrix.py`

**矩阵：** `kst_light + mlp` × `native_sparse/linear_interpolation/forward_fill/masked_input` × seeds `2026/2027/2028`，MetroPT `168/24/60`，matched-mixed `0.30 +/- 0.01`，共 `4×3=12`。

- [ ] 四协议使用 P07 冻结的同一 KST-Light、head、优化预算、split、target 和原始 mask。
- [ ] 同 seed 四协议的 split、raw-mask、normalization、target SHA 一致；adapter 输出 window ID 和 target shape 一致。
- [ ] native sparse 条件必须与 P09 的 KST-Light 主条件具有同一 `FormalRunKey`，为后续复用保留科学身份。
- [ ] 写矩阵测试：expected=12、unique=12、非法协议/seed/路径拒绝，metrics schema 无概率或风险字段。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_e0_protocol_matrix.py -q`。
- [ ] 运行 `PYTHONPATH=code python code/run_ch3_matrix.py --matrix configs/ch3/matrices/e0_protocol.yaml --run-level formal --dry-run`；预期 `expected=12,new=12,reused=0`。

**验收：** tracked YAML 无运行时路径，12 个 condition key 无重复且全部通过 eligibility。

#### Task CH3-P08-T02：生成三数据集协议审计 artifact

- [ ] **Task CH3-P08-T02 完成：MetroPT/FD004/TEP × 三 seeds 的 9 条协议审计通过**

**文件：**
- 创建：`code/audit_ch3_protocols.py`
- 创建：`code/tests/ch3/test_ch3_protocol_audit.py`
- 计划生成：`result/ch3/protocol-audit/e0-protocol-audit.json`

- [ ] 前置条件：四份 TEP RData 已传输到执行机 `KST_DATA_ROOT/dataverse_files/`（本机 2026-09-02 已验证四份齐全可读：faulty_training 5,000,000×55、faulty_testing 9,600,000×55），先把四份文件的 SHA256 登记到审计 artifact，再开始审计；任一文件缺失或 SHA 与登记值漂移即失败。本机 SHA256 基线（2026-09-02 登记，同步保存于 `dataset/dataverse_files/SHA256SUMS.txt`）：

  | 文件 | SHA256 |
  |---|---|
  | TEP_FaultFree_Testing.RData | `4f45afafa469793eeb7203fb9ed10ed0b1724c73c9c95537f15a0889ade0ebd4` |
  | TEP_FaultFree_Training.RData | `12d1055b852763fac09ef36bd7c9612a800c8bf7b6f75f344d12119206f9e940` |
  | TEP_Faulty_Testing.RData | `c2f1aabc77498efda4d5f9ad81ecc829e2fcd98752b84cf5b2a06558cabacc36` |
  | TEP_Faulty_Training.RData | `058df8bd90c5f575f44d2f6085bdd3bc3662e3e9cc25a50e34af42be3748952b` |
- [ ] 审计 MetroPT `168/24/60` chronological 50/20/30、FD004 `50/10/1` engine split、TEP `96/24/12` composite-run split。
- [ ] 每条保存 source file SHA、unit/run IDs、window counts、normalization SHA、mask SHA、requested/realized rate、overlap conflicts 和 boundary violations。
- [ ] MetroPT 不跨时间 split；FD004 不跨 engine；TEP 不跨 `faultNumber:simulationRun`。
- [ ] normalization 只来自 train unit；train/valid/test mask namespace 独立；overlap conflicts 必须为 0。
- [ ] TEP 审计要求 faulty training/testing；只有 fault-free 数据时命令失败而非 skip 为通过。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_ch3_protocol_audit.py -q`。
- [ ] 运行 `PYTHONPATH=code python code/audit_ch3_protocols.py --config configs/ch3/metropt_main.yaml --config configs/ch3/fd004_external.yaml --config configs/ch3/tep_external.yaml --seed 2026 --seed 2027 --seed 2028 --require-tep-faulty`。

**验收：** 9/9 审计条目 schema 有效，各 split 实际缺失率在 `[0.29,0.31]`。

#### Task CH3-P08-T03：执行 E0 的 12 个正式 run

- [ ] **Task CH3-P08-T03 完成：12 个 E0 run 均有完整 point-only artifact**

**文件：**
- 读取：`configs/ch3/matrices/e0_protocol.yaml`
- 计划生成：`result/ch3/runs/<run_id>/...`

- [ ] 审核 dry-run manifest 和 GPU 预算后，以单卡串行、resume、continue-on-error 模式启动矩阵。
- [ ] 每 run 只按 validation MAE 更新 best；冻结后 test 只评估一次。
- [ ] `predictions/test.npz` 增加 `forecast_start/forecast_end/time_block_id/n_valid/absolute_error_sum/squared_error_sum`。
- [ ] 运行 `PYTHONPATH=code python code/run_ch3_matrix.py --matrix configs/ch3/matrices/e0_protocol.yaml --run-level formal --resume --continue-on-error`。
- [ ] 对失败条目查明原因并只恢复该 key；不得换 seed、缩短数据或降低实际缺失率。
- [ ] validator 检查 12/12 `formal_validated`、MAE/RMSE 有限、valid count > 0、test count=1。

**验收：** 不预设 native sparse 必须最优；结果方向只由真实 artifact 决定。

#### Task CH3-P08-T04：关闭 E0 coverage gate

- [ ] **Task CH3-P08-T04 完成：E0 expected keys 与 validated keys 完全相等**

**文件：**
- 修改：`plan/stage-gates.md`
- 修改：`plan/implementation-plan.md`（只更新本 Task/Phase）

- [ ] 运行 E0 `--validate-only`；预期 12/12、duplicate=0、orphan=0、nonformal=0。
- [ ] 锁定协议相对误差 `100*(metric_protocol/metric_native_sparse-1)`，按相同 seed 成对计算。
- [ ] 登记 matrix ID、12 个 manifest SHA、审计 artifact SHA、命令和日期。
- [ ] 若结论不支持 native sparse 优势，只更新 allowed-claim 状态，不修改结果或追加 test 驱动实验。

**验收：** E0 可进入 P13 聚合；D3 仍保持未勾选。

---

### CH3-P09：E1 MetroPT-3 六模型正式主对比

- [ ] **Phase CH3-P09 完成：18 个逻辑主对比单元全部覆盖，其中 15 个新训练、3 个复用 E0**

#### Task CH3-P09-T01：锁定六模型 × 三 seed 主矩阵

- [ ] **Task CH3-P09-T01 完成：E1 dry-run 为 18 个逻辑条目、15 个新 run、3 个复用**

**文件：**
- 创建：`configs/ch3/matrices/e1_metropt_main.yaml`
- 创建：`code/tests/ch3/test_e1_metropt_matrix.py`

**矩阵：** `li_tcn/ff_gru/masked_tcn/gru_d/ode_rnn/kst_light` × 3 seeds，MetroPT `168/24/60`，matched-mixed 0.30，共 18 个逻辑单元。

- [ ] 六模型引用同一 frozen hyperparameter 文件，使用同 split/mask/target/normalization、batch、最大 epoch、early-stop 规则和 validation MAE checkpoint。
- [ ] baseline required-input protocol 与 P06 映射一致；GRU-D/ODE-RNN 使用真实 delta/time。
- [ ] KST-Light 三条件必须由 config hash 复用 P08 native sparse 三 run，记录 `source_run_id`，不得再训练。
- [ ] 运行矩阵单测与 `--dry-run`；预期 `expected=18,unique=18,new=15,reused=3`。

**验收：** 六模型均为 point-only formal 配置，复用由科学 signature 而非文件名判断。

#### Task CH3-P09-T02：执行 15 个新增主对比 run

- [ ] **Task CH3-P09-T02 完成：E1 的 18 个逻辑单元全部解析到 formal artifact**

**文件：**
- 读取：`configs/ch3/matrices/e1_metropt_main.yaml`

- [ ] 运行 `PYTHONPATH=code python code/run_ch3_matrix.py --matrix configs/ch3/matrices/e1_metropt_main.yaml --run-level formal --resume --continue-on-error`。
- [ ] 15 个新模型条件完整训练；3 个 KST-Light 条件验证并复用 E0 source run。
- [ ] 每 seed 六模型的 split/mask/normalization/target SHA 完全一致，realized rate 在 `[0.29,0.31]`。
- [ ] metrics 保存 MAE、RMSE、参数量、train time、batch/sample inference time；禁止 NLL/CRPS/区间/风险字段。
- [ ] 任一失败保持 failed，不得以 smoke、较短窗口或额外 seed 替代。

**验收：** 18/18 逻辑条目 formal validated，prediction window IDs 在同 seed 六模型间完全对齐。

#### Task CH3-P09-T03：完成 point-only 与公平性审计

- [ ] **Task CH3-P09-T03 完成：E1 coverage、字段、checkpoint 与 timing 口径审计通过**

**文件：**
- 修改：`code/tests/ch3/test_e1_metropt_matrix.py`
- 修改：`plan/stage-gates.md`

- [ ] 运行 E1 tests 和 `--validate-only`；预期 coverage=18/18、orphan/duplicate/nonformal=0。
- [ ] 检查 checkpoint selector 精确为 validation MAE，test evaluation count=1。
- [ ] 参数量由模型实例统计；训练/推理时间记录 batch、precision、设备和计时范围。
- [ ] 锁定相对主基线 `li_tcn`：`100*(metric_model/metric_li_tcn-1)`，只在同 seed 内成对。
- [ ] 不用 test 排名再调参，不要求 KST-Light 必须排名第一。

**验收：** E1 可直接进入 P13，不在本 Phase 手工生成表格。

---

### CH3-P10：E4 缺失率与缺失机制鲁棒性

- [ ] **Phase CH3-P10 完成：108 个逻辑单元、96 个唯一 E4 条件全部覆盖，新增训练 84 个**

#### Task CH3-P10-T01：锁定 random 五缺失率矩阵

- [ ] **Task CH3-P10-T01 完成：缺失率 dry-run 精确展开 60 条**

**文件：**
- 创建：`configs/ch3/matrices/e4_missing_rates.yaml`
- 创建：`code/tests/ch3/test_e4_robustness_matrix.py`

- [ ] 矩阵为 `li_tcn/gru_d/ode_rnn/kst_light` × rates `0/0.1/0.3/0.5/0.7` × 3 seeds，mode=random，共 60。
- [ ] rate 0 实际率必须为 0；其余误差不超过 0.01；同 seed+rate 四模型共享 mask SHA。
- [ ] reference 固定同 model+seed 的 random 0%；分母非有限或不大于 0 时 validator 失败。
- [ ] 运行单测和 `--dry-run`；预期 `expected=60,new=60,reused=0`。

**验收：** 五点曲线的 split、target、normalization 和训练预算不随 rate 改变。

#### Task CH3-P10-T02：执行 60 个 random-rate 正式 run

- [ ] **Task CH3-P10-T02 完成：四模型每个 seed 都有完整五点曲线**

- [ ] 运行 rate matrix formal/resume/continue-on-error。
- [ ] 逐 run 验证 requested/realized rate、validation MAE checkpoint、一次 test、有限 MAE/RMSE。
- [ ] 固定 `relative_mae_pct=100*(MAE_rate/MAE_rate0-1)` 与对应 RMSE 定义。
- [ ] 高缺失率失败不得通过修改 mask 参数、目标率或 test 范围规避。
- [ ] 运行 `--validate-only`；预期 60/60 formal validated。

**验收：** 不预设误差曲线单调，异常方向保留并在 P14 评审。

#### Task CH3-P10-T03：锁定四种 matched 机制及复用关系

- [ ] **Task CH3-P10-T03 完成：48 个机制逻辑条目映射到 24 个复用和 24 个新 run**

**文件：**
- 创建：`configs/ch3/matrices/e4_missing_mechanisms.yaml`
- 修改：`code/tests/ch3/test_e4_robustness_matrix.py`

- [ ] 矩阵为四模型 × `random/low_rate/block_offline/mixed` × 3 seeds，均 target 0.30，共 48。
- [ ] random 0.30 复用 rate scan 的 12 条；mixed 0.30 复用 E1 对应四模型的 12 条；low_rate/block 各新增 12。
- [ ] 四机制只改变缺失结构，不改变总量；生成器不能读取 label、future target 或 test metric。
- [ ] low-rate 周期、block 长度/通道分布、mixed 组合规则全部来自锁定配置。
- [ ] 运行 dry-run；预期 `expected=48,reused=24,new=24` 且每个 alias 有 source run。

**验收：** 复用由相同 signature 证明，不能按 run 名猜测。

#### Task CH3-P10-T04：执行 24 个新增机制 run

- [ ] **Task CH3-P10-T04 完成：48 个 matched-mechanism 单元全部可解析**

- [ ] 运行 mechanism matrix formal/resume/continue-on-error，实际只新增 low_rate/block 的 24 个训练。
- [ ] 每 split realized rate 在 `[0.29,0.31]`，overlap conflicts=0，同 mechanism+seed 四模型 mask SHA 相同。
- [ ] 机制相对指标 reference 固定 random 0.30：`100*(metric_mode/metric_random030-1)`。
- [ ] 不因某机制表现差而修改生成规则或删除该行。
- [ ] 运行 `--validate-only`；预期 48/48 logical coverage。

**验收：** 24 个复用与 24 个新增的来源关系全部进入 matrix manifest。

#### Task CH3-P10-T05：关闭 E4 总 coverage gate

- [ ] **Task CH3-P10-T05 完成：108 逻辑行、96 唯一条件、84 新训练计数一致**

**文件：**
- 修改：`plan/stage-gates.md`
- 修改：`plan/implementation-plan.md`

- [ ] 联合 validate rate 60 与 mechanism 48；跨表 random 0.30 重合 12，故 E4 unique=96。
- [ ] mechanism mixed 12 复用 P09，故本 Phase 新训练 `60+24=84`。
- [ ] expected 与 validated key 集合完全一致；不得把 3 seeds 当作 Wilcoxon 的足够样本。
- [ ] 登记两个 matrix ID、coverage report、mask audit 和 SHA 后勾选本 Phase。

**验收：** P13 可从 matrix manifests 自动得到 E4 全矩阵，不需重新编码组合。

---

### CH3-P11：E5-A 消融、E5-S 敏感性与 E6 效率

- [ ] **Phase CH3-P11 完成：24 条消融、12 个敏感性 run 和 18 条效率 benchmark 全部通过**

#### Task CH3-P11-T01：锁定并执行八变体消融

- [ ] **Task CH3-P11-T01 完成：24/24 消融单元 formal validated，新增训练 21 个**

**文件：**
- 创建：`configs/ch3/matrices/e5a_ablation.yaml`
- 创建：`code/tests/ch3/test_e5_ablation_matrix.py`

- [ ] 变体为 full、wo_time、wo_delta、wo_mask、wo_channel、wo_context、wo_multiscale、wo_cross_sensor × 3 seeds，共 24。
- [ ] full 三 run 复用 E1 KST-Light；其余 21 新训练，每个配置恰好一个 ablation flag。
- [ ] `wo_mask` 不得恢复真值；`wo_time/wo_delta` 分离；所有变体共享 head、split、mask、target 和预算。
- [ ] dry-run 预期 `24/3/21`；执行 formal matrix并验证 24/24。
- [ ] 相对退化按同 seed full：`100*(metric_variant/metric_full-1)`；消融优于 full 也必须保留。

**验收：** manifest 保存实际生效开关列表，forward-hook 单测证明每个变体真实生效。

#### Task CH3-P11-T02：锁定并执行 OFAT 敏感性

- [ ] **Task CH3-P11-T02 完成：14 个展示单元映射到 12 个 run，其中新增 9 个**

**文件：**
- 创建：`configs/ch3/matrices/e5s_sensitivity.yaml`
- 创建：`code/tests/ch3/test_e5_sensitivity_matrix.py`

**中心：** history 168、hidden 64、patch `[12,24,48]`、time dim 10、MLP head。

| factor | 预注册 values |
|---|---|
| history | `96/168/336` |
| hidden | `32/64/128` |
| patch | `[6,12,24] / [12,24,48] / [24,48,96]` |
| time dim | `5/10/20` |
| head | `linear/mlp` |

- [ ] 非中心值只跑 seed 2026；中心复用 E1 三 seeds；每个 off-center 只改一个 factor。
- [ ] 14 个 factor-view 去重为 10 个配置，中心加 seed27/28 后共 12 run；复用 3、新增 9。
- [ ] dry-run 预期 `factor_view=14,unique_runs=12,reused=3,new=9`。
- [ ] 执行 formal matrix并验证 12/12；非中心单 seed 只做描述性比较，不声称显著性或显示 `±0`。
- [ ] 不根据 test 表现追加取值或改变中心配置。

**验收：** 14/14 展示单元均能引用唯一 source run，中心不被重复训练。

#### Task CH3-P11-T03：实现统一冻结 checkpoint 效率 benchmark

- [ ] **Task CH3-P11-T03 完成：18 条效率 benchmark 使用同设备、batch 和 batch 序列**

**文件：**
- 创建：`configs/ch3/matrices/e6_efficiency.yaml`
- 创建：`code/kaf_profiti/experiments/ch3/benchmark.py`
- 创建：`code/tests/ch3/test_ch3_efficiency_benchmark.py`

- [ ] 六模型 × 三 seeds，共 18；不重新训练，逐条引用 E1 best checkpoint 与 source run。
- [ ] 唯一键固定为 `(source FormalRunKey, source_checkpoint_sha, benchmark_config_sha, device_fingerprint)`；expected keys 恰好为 E1 六模型 × 三 seeds，禁止按时间或“最新”选择重复 profile。
- [ ] 固定 FP32、batch 128、warm-up 10 batches、measure 50 batches、5 repeats；同一预加载 test batch 顺序串行执行。
- [ ] CUDA 计时前后同步，计时区间不含数据加载/磁盘写入；保存 5 个原始 repeat。
- [ ] 保存参数总数/可训练数、原 E1 train time/epochs/batches、batch/sample latency、峰值显存和 device fingerprint。
- [ ] 每条 benchmark 通过 profile artifact validator 后原子登记到 `result/ch3/profile-index.jsonl`；保存 manifest、benchmark config、batch sequence 和 raw repeats SHA。
- [ ] 写测试：source checkpoint/SHA 缺失、expected key 重复/缺失、设备不一致、repeat 数不为 5、手填参数量或计时含 I/O 时拒绝。
- [ ] 执行 profile matrix 并验证 18/18 `run_level=profile` 且 `profile_validation_status=validated`；P13 只允许 Ch3-T7 和 Ch3-F4 消费，不能当预测 formal run。

**验收：** 训练时间来自完整 E1 history，推理延迟可由原始 repeat 重新计算。

#### Task CH3-P11-T04：关闭 P11 coverage gate

- [ ] **Task CH3-P11-T04 完成：消融 24、敏感性 12、效率 18 均完整**

**文件：**
- 修改：`plan/stage-gates.md`
- 修改：`plan/implementation-plan.md`

- [ ] 联合 validate 三矩阵：ablation 24/24、sensitivity 12/12、efficiency 18/18。
- [ ] 本 Phase 新 formal training=`21+9=30`，新 profile benchmark=18，计数与总预算一致。
- [ ] 所有相对 reference 存在且按 seed 成对；无 probability/risk head 或指标。
- [ ] 登记 manifests、coverage 和 SHA；不在本 Phase 手工冻结表图。

**验收：** 三类输入可直接交给 P13；结果方向不作为完成条件。

---

### CH3-P12：E1-X FD004 与 TEP faulty 外部有效性

- [ ] **Phase CH3-P12 完成：FD004 和 TEP 各四模型 × 三 seeds，共 24 个 external run 全部通过**

#### Task CH3-P12-T01：锁定并执行 FD004 engine-level 矩阵

- [ ] **Task CH3-P12-T01 完成：FD004 的 12 个 run formal validated**

**文件：**
- 创建：`configs/ch3/matrices/e1x_fd004.yaml`
- 创建：`code/tests/ch3/test_e1x_external_matrix.py`

- [ ] 矩阵为 `li_tcn/gru_d/ode_rnn/kst_light` × 3 seeds，FD004 `50/10/1`，matched-mixed 0.30，共 12。
- [ ] `split_seed=2026` 固定 80/20 train/valid engines，official test 独立；任何窗口不跨 engine。
- [ ] normalization 只来自 train engines；同 seed 四模型共享 split/mask/target/normalization SHA。
- [ ] RUL 只保留 unit metadata，不启用 RUL/probability/risk head；formal 不得限 engine/batch 或截断 official test。
- [ ] 运行 test、dry-run、formal matrix和 validate-only；预期 12/12、new=12。
- [ ] `predictions/test.npz` 固定 `bootstrap_unit_id=engine_id`。

**验收：** FD004 MAE/RMSE 与效率有限，checkpoint 只由 validation MAE 选择。

#### Task CH3-P12-T02：建设 TEP faulty-run 可移植缓存

- [ ] **Task CH3-P12-T02 完成：faulty training/testing 可按复合 run 流式读取并通过 hash 校验**

**文件：**
- 创建：`code/kaf_profiti/industrial/tep_cache.py`
- 修改：`code/kaf_profiti/industrial/tep.py`
- 修改：`code/kaf_profiti/experiments/datasets.py`
- 创建：`code/tests/ch3/test_tep_faulty_cache.py`

- [ ] 从 `KST_DATA_ROOT` 解析两份 faulty RData（本机 2026-09-02 已验证齐全可读：faulty_training 5,000,000×55、faulty_testing 9,600,000×55）；缓存根由 CLI/env 决定，不进入 tracked 配置。
- [ ] 两份 faulty RData 的 raw SHA256 必须与 CH3-P08-T02 登记值一致；不一致即失败，不得重新登记覆盖。
- [ ] 使用 NumPy memmap/索引按列流式转换，缓存 key 为 raw source SHA；不得每次 formal run 全量复制 pandas frame。
- [ ] index 记录 `faultNumber:simulationRun`、row offsets、sample 范围、列 schema、raw/cache SHA；缓存写完校验后原子发布。
- [ ] train/valid 在每个 faultNumber 内按 composite run、固定 split seed 80/20；official faulty testing 只作 test。
- [ ] normalization 仅流式累积 train runs；formal 禁止 `max_runs_per_fault/sample_range/fault subset`。
- [ ] 写失败测试：raw hash 漂移、cache 不完整、跨 run window、fault-free fallback 或只用 simulationRun 作 key 均拒绝。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_tep_faulty_cache.py code/tests/test_tep_data.py -q`，再构建并审计缓存。

**验收：** test 中存在正 faultNumber，所有窗口只属于一个 composite run，缓存可在多次 run 间复用。

#### Task CH3-P12-T03：锁定 TEP faulty 外部矩阵

- [ ] **Task CH3-P12-T03 完成：TEP dry-run 精确展开 12 个合格条件**

**文件：**
- 创建：`configs/ch3/matrices/e1x_tep_faulty.yaml`
- 修改：`code/tests/ch3/test_e1x_external_matrix.py`

- [ ] 矩阵为四模型 × 3 seeds，TEP `96/24/12`，faulty training/testing，matched-mixed 0.30，共 12。
- [ ] unit key 必须 `faultNumber:simulationRun`；split seed 固定；mask 不读取 fault label 或注入时刻。
- [ ] formal 配置不得限 fault/run/sample/batch；train normalization 不读 valid/test。
- [ ] TEP 本章只做未来过程变量点预测，不输出风险指标，不用故障标签监督模型。
- [ ] 运行 TEP data/cache tests、protocol audit 和 dry-run；任一 faulty source 不可用则本 Task 保持未勾选。

**验收：** expected=12、新训练=12，source/cache/split SHA 全部进入 manifest。

#### Task CH3-P12-T04：执行 TEP faulty 的 12 个正式 run

- [ ] **Task CH3-P12-T04 完成：TEP faulty 四模型三 seeds 均 formal validated**

- [ ] 以 resume/continue-on-error 执行 `e1x_tep_faulty.yaml`。
- [ ] 四模型同 seed 共享 split/mask/target/normalization SHA，realized rate 在 `[0.29,0.31]`。
- [ ] checkpoint 只由 validation MAE 选择，test 只评估一次，prediction 的 bootstrap unit 为 composite run。
- [ ] 读取/内存/缺 run 失败保持失败；不得改用 fault-free、抽样子集或缩短 official test。
- [ ] 运行 validate-only；预期 12/12、duplicate/orphan/nonformal=0。

**验收：** 不跨 MetroPT/FD004/TEP 直接比较原始 MAE/RMSE 量级。

#### Task CH3-P12-T05：关闭外部验证 coverage gate

- [ ] **Task CH3-P12-T05 完成：FD004 12/12、TEP 12/12，总计 24/24**

**文件：**
- 修改：`plan/stage-gates.md`
- 修改：`plan/implementation-plan.md`

- [ ] 联合 validate 两矩阵；expected/validated=24/24，本 Phase new formal training=24。
- [ ] relative metric 只在数据集内相对同 seed LI+TCN 计算；FD004 用 engine、TEP 用 composite run bootstrap。
- [ ] 无 probability/risk head、risk metric 或 test 调参；外部结果不支持迁移优势时降低论文结论。
- [ ] 登记两个 matrix IDs、24 个 run manifest SHA 和 protocol/cache audit SHA。

**验收：** P08-P12 全部正式运行输入齐备，但 D3 要等 P13 的全局 coverage/统计校验后才能关闭。

---

### CH3-P13：正式结果聚合、相关性 bootstrap 与第三章表图

- [ ] **Phase CH3-P13 完成：D3/D4 关闭，8 张表、5 张图和统计来源可从真实 artifact 重建**

**唯一输入边界：** 预测目录只读 `result/ch3/run-index.jsonl`、P08-P12 matrix manifests 和协议审计，并强制 `run_level=formal + evidence_status=formal_validated`；效率目录只读 `result/ch3/profile-index.jsonl`，并强制 `run_level=profile + profile_validation_status=validated`。两类目录分别建 catalog，禁止互相补格；也禁止用 `rglob`、mtime、“最新 run”、legacy `metrics_seed*.json`、mock 或 smoke 补格。

#### Task CH3-P13-T01：锁定输出与统计 schema

- [ ] **Task CH3-P13-T01 完成：统计方法、表格列、图片来源和依赖全部预注册**

**文件：**
- 创建：`configs/ch3/outputs.yaml`
- 创建：`code/kaf_profiti/experiments/ch3/output_schema.py`
- 创建：`code/tests/ch3/test_output_schema.py`
- 修改：`requirement.txt`
- 修改：`tables/table-schema.md`
- 修改：`figures/data-manifest.md`

**固定设置：** confidence 0.95、bootstrap resamples 10000、bootstrap seed 2026、seed std `ddof=1`、required seeds `[2026,2027,2028]`；预测指标为 strict formal only，效率字段为独立 strict profile only。

- [ ] 在 `requirement.txt` 固定加入 `matplotlib==3.9.2`、`seaborn==0.13.2` 和 `Pillow==11.0.0`。
- [ ] 定义 `FormalPredictionSourceRef`，至少含 family、run ID、dataset/model/variant/seed/condition、相对路径及 manifest/config/checkpoint/prediction/split/mask/code/protocol SHA。
- [ ] 定义 `EfficiencyProfileRef`，至少含 profile ID、source formal run/key、source checkpoint SHA、benchmark config SHA、batch sequence SHA、device fingerprint、raw repeats SHA 和相对路径。
- [ ] 定义 `AggregateMetricRecord`，至少含 mean、sample std、CI、CI method、bootstrap unit/count/resamples 和 provenance ID。
- [ ] 写失败测试：非法 confidence/resamples、重复 seed、绝对路径、缺 SHA、非法 SHA、单 seed std 非 null、formal/profile 类型交叉均拒绝。
- [ ] 在 table schema 锁定 Ch3-T1..T8 的主键、列、单位、reference、排序和允许结论；在 figure manifest 锁定 Ch3-F1..F5 的唯一 source CSV。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_output_schema.py -q`；预期失败后实现并重跑。

**验收：** P13 运行时不得重新选择统计方法、reference、表格列或图片案例。

#### Task CH3-P13-T02：构建 strict formal/profile catalogs 与全局 coverage

- [ ] **Task CH3-P13-T02 完成：198 个 formal matrix rows、14 个 sensitivity factor-views、165 个唯一 source run 和 18 个 profile 完整**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/aggregation.py`
- 创建：`code/tests/ch3/test_formal_run_catalog.py`

**计划输出：** `aggregates/run-catalog.csv`、`aggregates/profile-catalog.csv`、`provenance.csv`、`rejected-runs.csv`、`coverage-report.json`。

- [ ] 每个逻辑 evidence row 保留 experiment family；多个 family 可通过 alias 指向同一 FormalRunKey/source run。
- [ ] 同一 FormalRunKey 出现两个不同 formal source run 时失败，禁止“最新覆盖”；合法 alias 必须同 SHA 并记录 source run。
- [ ] `EfficiencyProfileKey` 固定为 `(source FormalRunKey, source_checkpoint_sha, benchmark_config_sha, device_fingerprint)`；expected keys 为 E1 六模型 × 三 seeds，missing/duplicate 均为零，18 条 profile 不参与 165 个 formal source 去重。
- [ ] formal catalog 拒绝 profile/smoke/tuning/fixture，profile catalog 拒绝 formal/smoke/tuning/fixture；两者都拒绝 manifest/index 不一致、hash 漂移、绝对/逃逸路径、expected 缺失或未计划 key。
- [ ] 检查 formal matrix rows=`12+18+108+24+12+24=198`、unique formal sources=165、sensitivity factor-views=14、efficiency profiles=18。
- [ ] profile lineage 的消费白名单只有 Ch3-T7 和 Ch3-F4：T7 直接按 source run ID、checkpoint SHA、seed 和 benchmark config SHA 联接并保存双 provenance；F4 只能读取由 T7 合同生成的双 provenance aggregate，不得直接扫描 profile index。
- [ ] `rejected-runs.csv` 只用于审计，任何后续表图不得消费。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_formal_run_catalog.py -q`。
- [ ] 对两个 index 执行 strict catalogs；预期 `formal_missing=0,formal_duplicate=0,profile_missing=0,profile_duplicate=0,invalid_hash=0,cross_level=0`。

**验收：** 每个预测输入精确追溯到 formal run，每个效率输入精确追溯到 profile 及其 source checkpoint；两套 coverage 和计数独立闭合。

#### Task CH3-P13-T03：实现充分统计量与分层成对 bootstrap

- [ ] **Task CH3-P13-T03 完成：全局指标、自然相关单元、CI 和多重比较测试通过**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/statistics.py`
- 创建：`code/tests/ch3/test_ch3_statistics.py`
- 创建：`code/tests/ch3/test_ch3_bootstrap.py`

```python
@dataclass(frozen=True)
class WindowSufficientStats:
    window_id: str
    bootstrap_unit_id: str
    n_valid: int
    absolute_error_sum: float
    squared_error_sum: float
```

- [ ] 固定 `MAE=sum(abs_error)/sum(n)`、`RMSE=sqrt(sum(square_error)/sum(n))`，禁止窗口或 batch 等权平均。
- [ ] 每 seed 先计算全体有效目标点估计；三 seed mean 为算术均值，std 用 `ddof=1`。
- [ ] MetroPT block 秒数固定为 `24 * stride * train_median_interarrival_seconds`，锚定 test 起点；不得用 test error/label 选 block。
- [ ] FD004 bootstrap unit 为完整 engine；TEP 为 `faultNumber:simulationRun`；每个 seed 内有放回抽 unit，再对三 seed 估计取均值。
- [ ] 模型/消融/reference 使用同步抽样的 paired bootstrap；unit/window 集不一致立即失败。
- [ ] 相对退化统一 `100*(metric_condition-metric_reference)/metric_reference`，正值表示误差变差。
- [ ] 预注册 contrast 的双侧 bootstrap p 值使用 `2*min(P(delta<=0),P(delta>=0))`，同一表内用 Holm 校正；不以 3 seeds 运行 Wilcoxon。
- [ ] 写公式测试证明全局充分统计量不同于窗口等权平均；写零有效位、非法 reference、错误 unit、paired 不对齐和确定性 CI 失败测试。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_ch3_statistics.py code/tests/ch3/test_ch3_bootstrap.py -q`。

**验收：** 95% CI 反映时间块/engine/run 相关性；效应方向、相对变化和校正 p 均可复算。

#### Task CH3-P13-T04：生成 Ch3-T1 至 Ch3-T8

- [ ] **Task CH3-P13-T04 完成：恰好生成 8 个 CSV、8 个 Markdown 且每行可追溯**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/output_tables.py`
- 创建：`code/tests/ch3/test_ch3_tables.py`

| 编号 | 文件 stem | 正式内容 |
|---|---|---|
| Ch3-T1 | `Ch3-T1-data-protocol` | 三数据集 split、窗口、时间单位、normalization、目标/实际缺失率、mask SHA |
| Ch3-T2 | `Ch3-T2-main-comparison` | E1 六模型 MAE/RMSE mean±std、block CI、参数量 |
| Ch3-T3 | `Ch3-T3-missing-rate` | 五缺失率、实际率、MAE/RMSE、相对 0% 退化与 CI |
| Ch3-T4 | `Ch3-T4-missing-mechanism` | matched 30% 四机制、相对 random 退化与 CI |
| Ch3-T5 | `Ch3-T5-ablation` | full 与七个 w/o、paired delta、CI、Holm-adjusted p |
| Ch3-T6 | `Ch3-T6-sensitivity` | factor/value、seed 数、中心标记、误差、参数、时间 |
| Ch3-T7 | `Ch3-T7-efficiency` | 参数、train time、batch/sample latency、显存、硬件与 repeats |
| Ch3-T8 | `Ch3-T8-external-validity` | FD004/TEP 分数据集误差、自然单元 CI、相对 LI+TCN |

- [ ] CSV 保存未格式化数值；Markdown 才格式化 `mean ± std [95% CI]`；每行带 provenance ID。
- [ ] 单 seed sensitivity 的 std 为 null，不显示 `±0`；参数量不伪造 std/CI。
- [ ] FD004/TEP 不跨数据集平均或按原始误差混合排序；固定行顺序不随 test 排名变化。
- [ ] Ch3-T7 是唯一直接读取 profile catalog 的表；按双 provenance 联接 E1 formal 的误差/训练历史与 profile 的延迟/显存，其余表一律拒绝 profile。
- [ ] 写失败测试：缺 formal cell/seed/provenance、T1-T6/T8 混入 profile、T7 混入未验证 profile、legacy 列或半张表时整体构建失败。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_ch3_tables.py -q`。

**验收：** 没有空占位、随机示例值、手工数字或 legacy Table 1-7 混入。

#### Task CH3-P13-T05：生成 Ch3-F1 至 Ch3-F5 和 source CSV

- [ ] **Task CH3-P13-T05 完成：5 个 source CSV、5 个 SVG、5 个 300 dpi PNG 通过视觉/数据 QA**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/output_figures.py`
- 创建：`code/tests/ch3/test_ch3_figures.py`

| 编号 | source CSV | 图形合同 |
|---|---|---|
| Ch3-F1 | `Ch3-F1-mask-timeline.csv` | seed 2026、首个预注册 MetroPT block、真实时间和四机制 mask，不按误差挑案例 |
| Ch3-F2 | `Ch3-F2-robustness.csv` | 缺失率 MAE/RMSE 均值线与 95% CI；机制另面板 |
| Ch3-F3 | `Ch3-F3-ablation-effects.csv` | full 对七消融的 paired 相对退化与 CI |
| Ch3-F4 | `Ch3-F4-efficiency-pareto.csv` | RMSE—推理延迟 Pareto，参数量为明确编码并显示 latency CI |
| Ch3-F5 | `Ch3-F5-external-validity.csv` | FD004/TEP 分面，只画数据集内相对 LI+TCN 比值 |

- [ ] 执行本 Task 时使用 `research-writing-assistant:figures-python`；每图只读对应 source CSV，不直接读 raw metrics/NPZ。
- [ ] source CSV 带 provenance ID 和 SHA；Ch3-F4 从已验证的 T7 双 provenance 聚合生成，不直接扫描 profile index；图同时导出 SVG 与 PNG，PNG dpi metadata 不低于 299。
- [ ] 固定色板、线型、marker、轴单位、图例和 SVG hashsalt；移除时间 metadata 与外部文件引用。
- [ ] 写失败测试：source 缺 CI/provenance/unit/sort key、文件为空、编号不全、低 dpi、mock/smoke 或未验证 profile 来源均拒绝。
- [ ] 相同输入在两个临时目录重建，比较 source CSV、SVG 和去 metadata 后 PNG pixel hash。
- [ ] 人工检查 5 张图的标签、误差条、遮挡、颜色区分与论文灰度可读性，并把 QA 结论写入 figure manifest。

**验收：** 图只陈述测量内容，不按期望结论挑数据或视觉放大微小差异。

#### Task CH3-P13-T06：建立一键候选构建与原子发布

- [ ] **Task CH3-P13-T06 完成：同一 formal/profile 输入两次构建得到相同 candidate bundle**

**文件：**
- 创建：`code/build_ch3_outputs.py`
- 创建：`code/kaf_profiti/experiments/ch3/output_manifest.py`
- 创建：`code/tests/ch3/test_build_ch3_outputs.py`

- [ ] candidate ID 由排序后的 source manifest SHA、protocol SHA 和 output config SHA 派生，不用时间戳。
- [ ] 构建先写临时目录，校验 8 表/5图/aggregate/provenance 后原子发布到 `result/ch3/outputs/<candidate_id>/`。
- [ ] 已存在 candidate 只允许验证完全相同内容，不提供覆盖选项；manifest 所有路径相对 result root。
- [ ] 写端到端失败测试：缺 cell、hash mismatch、fixture、duplicate、低 dpi 或少表图时非零退出且不留半成品。
- [ ] 运行 P13 测试全集后执行 `PYTHONPATH=code python code/build_ch3_outputs.py --config configs/ch3/outputs.yaml --matrix-config-root configs/ch3/matrices --strict`。
- [ ] 预期输出 `formal_sources=165,matrix_rows=198,sensitivity_views=14,profiles=18,rejected=0,missing=0,cross_level=0,tables=8,svg=5,png=5`。
- [ ] 在全新临时输出根重建并比较 bundle SHA；预期一致。

**验收：** 第三章所有数值表图可由一个命令从完整 artifact 确定性重建。

#### Task CH3-P13-T07：关闭 D3 与 D4

- [ ] **Task CH3-P13-T07 完成：正式 coverage 和结果交付去污染门禁均有机器证据**

**文件：**
- 修改：`plan/stage-gates.md`
- 修改：`plan/implementation-plan.md`

- [ ] D3 分别检查 198 个 expected/validated formal matrix keys、14 个 sensitivity factor-views、165 个 source runs、18 个独立 profiles、hash 和自然 bootstrap unit 全部通过；profile 不计入 formal 数量。
- [ ] D4 扫描输出，禁止 `PLANNING DATA/待真实实验替换/实验目的/讨论提示/表位`、mock、fixture、smoke 和手填来源。
- [ ] 检查 Ch3-T1..T8、Ch3-F1..F5 无缺号/重号，图片双格式，provenance 闭合。
- [ ] 在 stage gates 记录 candidate ID、bundle SHA、coverage report SHA、构建/复建命令和日期。
- [ ] 只有 validator 退出码 0 后勾选 D3、D4、本 Task 与 Phase；D5 保持未勾选。

**验收：** P14 可审查一个固定 candidate，不需要重新发现或选择结果。

---

### CH3-P14：证据交付、同行评审与不可覆盖冻结

- [ ] **Phase CH3-P14 完成：D5 关闭，第三章结果已冻结且每个报告值可追溯**

#### Task CH3-P14-T01：生成闭合证据包并复核 D3/D4

- [ ] **Task CH3-P14-T01 完成：表图—聚合—run—checkpoint—配置追溯链零缺口**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/evidence.py`
- 创建：`code/build_ch3_evidence_bundle.py`
- 创建：`code/tests/ch3/test_ch3_evidence_bundle.py`
- 修改：`plan/stage-gates.md`

**证据包：** `evidence-manifest.json`、run/metric/table/figure provenance CSV、method-experiment traceability CSV、gate report、reproduction commands。

- [ ] 每个表行和 figure-source 行映射 aggregate/provenance IDs；预测链固定为 `claim/table/figure -> aggregate -> formal run+seed -> prediction/metrics -> checkpoint -> config -> manifest -> code/protocol hash`，效率链固定为 `claim/table/figure -> aggregate -> profile -> raw repeats/benchmark -> source formal run+checkpoint -> config/manifest hash`。
- [ ] reproduction commands 只保存仓库相对命令和环境变量名，不保存解析后的机器路径。
- [ ] 写失败测试：任一数字无 provenance、checkpoint 无 SHA、candidate 任一字节漂移、nonformal 来源或 D3/D4 未通过均失败。
- [ ] 对 P13 candidate 运行 evidence builder；预期 `untraced=0,invalid_hash=0,nonformal=0,D3=true,D4=true`。
- [ ] 将证据包 SHA 登记到 stage gates；不得因“看起来完整”手工确认。

**验收：** 第三章每个可报告值均有机器可验证的完整来源链。

#### Task CH3-P14-T02：执行双角色独立同行评审

- [ ] **Task CH3-P14-T02 完成：方法统计与复现 artifact 两类评审记录完整**

**文件：**
- 创建：`plan/review/ch3-peer-review.md`
- 创建：`code/review_ch3_evidence.py`
- 创建：`code/tests/ch3/test_ch3_peer_review.py`

- [ ] 方法统计 reviewer 核对矩阵、公平性、一次 test、自然相关单元、paired bootstrap、mean±std/CI/reference 和结论强度。
- [ ] 复现 artifact reviewer 核对 coverage、hash、checkpoint/config/manifest、路径、一键重建、图格式与 fixture/smoke 隔离。
- [ ] 两个稳定 reviewer ID 必须不同；逐项覆盖 8 表、5 图和方法—实验追溯，不允许只写“整体通过”。
- [ ] finding 固定 severity `blocking/major/minor/note` 和 status `open/resolved/accepted_note`，记录 artifact、位置、证据、required action、rerun scope 和 resolution SHA。
- [ ] 写失败测试：candidate hash 不符、两 reviewer 相同、blocking/major open、resolved 无 SHA/rerun scope 时禁止 approved。
- [ ] 运行 review validator；有 blocking/major 时退出非零且 D5 保持未勾选。

**验收：** 评审结论绑定当前 candidate SHA，不是形式化签字。

#### Task CH3-P14-T03：处理 finding 并重建受影响证据

- [ ] **Task CH3-P14-T03 完成：blocking/major finding 为零，最终 candidate 获双角色批准**

**文件：**
- 修改：仅限 finding `required_action` 明确列出的文件
- 修改：`plan/review/ch3-peer-review.md`
- 修改：`plan/progress.md`

- [ ] 措辞问题只修改 allowed claim/traceability；不得改 metrics。
- [ ] 聚合/作图问题修代码与测试并重跑 P13，生成新 candidate；数据/模型/mask/config 问题只重跑受影响 formal keys。
- [ ] candidate SHA 一旦改变，旧 D3、D4、evidence、review 和 D5 状态全部标为 stale；保留 superseded 记录并重跑 P13-T07、P14-T01、P14-T02，两角色只对新 hash 重新确认。
- [ ] 不删除旧 candidate，不手补 CSV，不用 minor 隐藏会改变数值或结论的问题。
- [ ] 重跑第三章测试、evidence builder 和 review validator；预期 open blocking=0、open major=0、两 decision=approved。

**验收：** 所有修复通过重新生成 artifact 生效，原始结果未被人工修改。

#### Task CH3-P14-T04：创建不可覆盖的 freeze bundle

- [ ] **Task CH3-P14-T04 完成：冻结包创建并在新进程中二次验签通过**

**文件：**
- 创建：`code/kaf_profiti/experiments/ch3/freeze.py`
- 创建：`code/freeze_ch3_evidence.py`
- 创建：`code/tests/ch3/test_ch3_freeze.py`

- [ ] freeze ID 固定为 `ch3-` 加 candidate manifest SHA 前 16 位，不用手填时间戳。
- [ ] 复制候选 tables/figures/figure-data/aggregates/evidence/review 快照到 `result/ch3/frozen/<freeze_id>/`。
- [ ] 大 checkpoint 不重复复制，但以 result-root 相对路径和 SHA 完整登记；freeze 不修改任何 source run。
- [ ] 已存在 target 禁止覆盖；内容完全一致时只 verify 并返回已有 freeze ID。
- [ ] 创建前要求 D3/D4 true、review approved、blocking/major=0；manifest 禁止绝对路径、账号、主机或端口。
- [ ] 写失败测试：gate/review/hash 不符、fixture/smoke、源漂移、同名覆盖或冻结后单字节改动均被检出。
- [ ] 运行 create，再在新进程运行 verify；预期 missing=0、hash mismatch=0、absolute path=0、nonformal=0。

**验收：** 冻结包可审计、不可静默覆盖，source metrics/prediction/checkpoint 保持原值。

#### Task CH3-P14-T05：关闭 D5 并完成最终证据化自动勾选

- [ ] **Task CH3-P14-T05 完成：D5、本 Task、Phase 与最终状态由同一有效 gate report 原子更新**

**文件：**
- 创建：`code/update_ch3_plan_status.py`
- 创建：`code/tests/ch3/test_ch3_gate_status.py`
- 修改：`plan/stage-gates.md`
- 修改：`plan/implementation-plan.md`
- 修改：`plan/progress.md`

- [ ] updater 只接受 allowlist 内的 `check_id`，且 gate report 必含 `command/exit_code/evidence_relpath/evidence_sha256/checked_at_utc/candidate_sha`、D3/D4 report SHA、evidence SHA、两个 reviewer ID/decision、finding counts、freeze ID/manifest SHA 和新进程 `freeze_verify_report_sha`。
- [ ] 默认 `--check` 只显示拟修改 checkbox；显式 `--apply` 才能把指定 `[ ]` 改为 `[x]`，不得改文字、顺序、前序 step 或未知 marker。
- [ ] D5 必须验证 candidate、D3、D4、evidence、两份 review 和 freeze 全部绑定同一 candidate SHA；缺证据、错误 hash、非零退出码、stale 状态、open blocking/major 或 freeze 漂移均拒绝。
- [ ] 检测计划文件并发/未合并改动；有冲突停止，不覆盖用户内容。
- [ ] 写测试：除四个最终 marker 外仍有任一必做框未勾选时拒绝；成功时先在临时文件原子修改四个 marker，经结构校验后替换，其他文本逐字不变。
- [ ] 最终运行第三章测试全集、freeze verify、8表5图编号扫描和全 Section 11 checkbox/ID 校验。
- [ ] 在 stage gates/progress 登记 freeze ID、bundle/review SHA、165 个 formal source runs、18 个 profiles、表图数、验证命令和剩余局限，不抄写或手改指标。
- [ ] **最终 apply step：** 运行 updater `--check`，预期只拟勾选“本 step、D5、本 Task、Phase P14”四项；审核 diff 后执行 `--apply`，四项必须在同一锁和同一原子替换中更新。

**最终验收：**

- D0-D5 均有命令、证据路径和 SHA；Ch3-T1..T8、Ch3-F1..F5 完整。
- 三 seed 项报告 mean±std 与依赖结构正确的 95% CI；单 seed sensitivity 不伪造 std。
- MetroPT/FD004/TEP 分别按时间块/engine/composite run bootstrap。
- 每个预测数字可追溯到 run ID、seed、checkpoint、config、manifest 和 hash；每个效率数字还可追溯到 profile ID、benchmark config 和 raw repeats。
- 无 mock、fixture、smoke、legacy 或手改结果；freeze 在新进程验签成功。

### 11.5 本轮规划能力使用审计（不计入执行 Phase）

- **任务阶段：** S3 Experiments；本轮只规划第三章实验和交付门禁，不撰写结果正文。
- **要求使用：** `using-superpowers`、`using-research-writing`、`paper-orchestration`、`experiment-results-planning`、`writing-plans`、`verification`、`verification-before-completion`。
- **实际使用：** 已按上述技能完成任务路由、实验合同、细粒度 Phase/Task、双重语义复核和完成前验证设计。
- **输入材料：** `AGENTS.md`、当前代码审计结论、现有实验协议/论文结构说明、`plan/implementation-plan.md` 既有第 1 至第 10 节，以及方案 A 的用户选择。
- **未消费材料：** 未读取或改写 `result/` 指标，也未把任何 mock 数值当成实验结果；原因是本轮只做执行规划。
- **本轮产物：** 第 11 节 CH3-P00 至 CH3-P14 的第三章实验执行计划，以及 formal/profile、统计、表图、评审和冻结边界。
- **完成前核验：** 检查 Phase/Task 编号与 checkbox 一致性、198/165/18/14 计数、占位词、Section 11 可移植性、关键门禁语义和 Git 状态。
- **剩余风险：** 尚未执行代码、测试或正式实验；165 个 run 的实际 GPU 预算须在 P07 用目标硬件实测（超预算时按 P07-T06 的预注册缩减阶梯处理），TEP faulty 数据已在本机确认齐全可读（2026-09-02），剩余义务为传输至执行机并核对 SHA，GRU-D/ODE-RNN fidelity gate 未通过前不能进入正式结论。
- **2026-09-02 修订：** 确认 TEP `dataverse_files/` 四份 RData 齐全且本地测试 52/52 通过；据此关闭"TEP 数据不可得"风险，补充数据 SHA 登记义务（P08-T02、P12-T02）、P07-T06 预算超支预注册缩减阶梯、本节与第 7 节 Phase 1–9 的编号映射，并复核关闭 CH3-P00-T02。

---

## 12. CH2.5：FD004 单种子预实验与第三、四章模型跑通计划

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 `subagent-driven-development`（适合独立 Task）或 `executing-plans`（适合当前会话顺序执行）逐项实施。所有执行项使用 checkbox；每一项通过对应验证后立即从 `- [ ]` 更新为 `- [x]`，不得在整批结束后集中补勾。

**目标：** 先在当前数据量最小的 C-MAPSS FD004 上，以单种子和严格共享的数据协议跑通第三章点预测比较与第四章概率预测比较，为后续调参和算法创新提供真实诊断证据。

**执行架构：** 先冻结 FD004 的 engine 级划分、train-only 归一化、timeline-first 人工缺失 mask、目标窗口和评价器，再让不同模型通过预注册 adapter 消费同一份原始观测过程。实验按“基线 smoke -> 基线完整 pilot -> 本文模型完整 pilot”的顺序执行；单种子结果只标记为 `pilot`，不得进入论文 formal 结果、显著性结论或最终表图。

**技术栈：** Python 3.11+、PyTorch、NumPy、pandas、PyYAML、pytest；训练设备为配置解析得到的 CUDA/CPU，数据根、结果根、缓存根和 checkpoint 均由 CLI、环境变量或项目相对路径解析。

**执行位置硬约束：** 本机只执行代码开发、单元/集成测试、矩阵 dry-run、全模型小批量 smoke、schema/可移植性检查和结果重算验证；AutoDL 只在本机门禁通过后执行不截断 train/validation/test 的完整 pilot 训练与最终效率测量。本机 smoke 指标不得与 AutoDL 完整实验指标混合，完整训练时间、推理时间、峰值显存和模型排序只读取同一 AutoDL 硬件环境生成的 artifact。

### 12.1 范围、优先级与勾选规则

1. 本节是短周期预实验轨道，不替代第 11 节 CH3-P00 至 CH3-P14 的正式实验与证据冻结计划。
2. 本节产生的完整训练统一使用 `run_level=pilot` 和 `evidence_status=pilot_validated`；smoke 使用 `run_level=smoke`。两类产物均不得进入第三、四章 formal catalog。
3. 本节只使用 FD004 和 seed `2026`；不执行多 seed、显著性检验、模块消融、额外鲁棒性扫描、跨数据集验证或论文结果写作。
4. 用户明确要求的缺失强度和缺失机制比较属于本轮必做范围：random `0.00/0.30/0.70`；固定实际缺失率 `0.30` 下比较 random、low-rate、block、mixed。
5. random `0.30` 同时服务强度和机制两张逻辑视图，只训练一次。每个点预测配置共有 6 个唯一条件，而不是 7 个。
6. 每个 Phase 只有在全部必做 Task、验证命令和产物检查通过后才能勾选；前一 Phase 未关闭时不得启动后一 Phase。
7. 本节若与旧 README 或旧实验命令冲突，以本节、`plan/experiment-protocol.md` 和可执行测试为准；发现冲突时同步修正文档，不能静默采用旧默认值。
8. 不手工修改 `result/` 中的 metrics、prediction、mask、checkpoint、history、timing 或聚合 CSV；修复只能通过代码重跑生成新 artifact。
9. 本机与 AutoDL 之间只同步版本控制内的代码和配置；数据根、结果根和缓存根由各环境独立解析，计划和配置中不得保存固定连接地址或机器路径。
10. AutoDL 完整运行前必须登记 clean Git commit、依赖锁定摘要、CUDA/PyTorch/GPU 信息和数据/协议 SHA；下载回本机的 artifact 必须与 AutoDL manifest SHA 一致。

### 12.2 固定实验合同

#### 12.2.1 数据集与随机性

- 数据集：`cmapss_fd004`。
- 选择依据：本地原始训练文件约 9.9 MB、测试文件约 6.6 MB，小于 MetroPT-3 与 TEP，适合最先验证全链路。
- 窗口：`history_len=50`、`pred_len=10`、`stride=1`。
- 划分：official train 按 engine ID 固定 80/20 为 train/validation；official test 只作 test；同一 engine 不得跨 split。
- 固定 `split_seed=2026`，模型 seed 和 mask seed 均为 `2026`，但三个字段必须独立保存和校验。
- Python、NumPy、PyTorch、CUDA、DataLoader 和模型初始化 RNG 均从 run seed 派生；DataLoader sampler 顺序保存 SHA。

#### 12.2.2 公平性不变量

所有直接比较模型必须共享：

- 完全相同的 train/validation/test engine ID 和 canonical forecast window ID。
- 完全相同、只由 train engines 计算的 normalization 统计量及其 SHA。
- 完全相同的 timeline-first 原始人工缺失 mask、requested/realized rate 和 mask SHA。
- 完全相同的预测通道、预测时间、target mask、有效目标数和 target schema SHA。
- 完全相同的 batch size、最大 epoch、early-stop/checkpoint 规则、学习率候选预算和评价器版本。
- 完全相同的测试次数规则：最佳 validation checkpoint 冻结后，test evaluator 精确执行一次。

方法允许通过预注册 adapter 获得其必需输入，但 adapter 不能改变原始 mask、目标或可见信息：规则网格模型使用历史内插值/填充和 mask 通道；GRU-D 使用同源 mask 与 `delta_t`；ODE-RNN、GraFITi、ProFITi 和 KST 使用同源事件时间。所有 adapter 只读 history，不能跨 split、engine、窗口末端或 forecast origin 搜索值。

#### 12.2.3 第三章点预测矩阵

点预测配置固定为：

1. `li_tcn`：linear interpolation + TCN + 统一轻量 Linear point head。
2. `ff_gru`：forward fill + GRU + 统一轻量 Linear point head。
3. `masked_tcn`：masked input + TCN + 统一轻量 Linear point head。
4. `gru_d`：原始 mask + `delta_t` + GRU-D + 统一轻量 Linear point head。
5. `ode_rnn`：真实历史时间 + ODE-RNN + 统一轻量 Linear point head。
6. `kst_light/head_type=linear`：本文异步规整表示编码器 + Linear 轻量预测头。
7. `kst_light/head_type=mlp`：本文异步规整表示编码器 + MLP 轻量预测头。

唯一条件为 `random@0.00`、`random@0.30`、`random@0.70`、`low_rate@0.30`、`block_offline@0.30`、`mixed@0.30`。总计 `7 × 6 = 42` 个完整 pilot run；先执行 5 个基线的 30 个 run，再执行本文两个 head 的 12 个 run。

点预测 pilot 只比较 MAE、RMSE、有效目标数、参数量、完整训练时间和冻结 batch 的推理时间。NLL、CRPS、PICP、MPIW 对 point-only 输出记录为 `null/not_applicable`，禁止补造概率分布。

#### 12.2.4 第四章概率预测矩阵

六个对比模型固定为：

1. `tcn_gaussian`：规则卷积概率基线。
2. `patchtst_gaussian`：规则 Transformer 概率基线。
3. `gru_d_gaussian`：GRU-D 编码器 + 统一 diagonal Gaussian head。
4. `ode_rnn_gaussian`：ODE-RNN 编码器 + 统一 diagonal Gaussian head。
5. `grafiti_gaussian`：GraFITi 编码器 + 统一 diagonal Gaussian head。
6. `profiti`：条件 flow 概率基线。

本文模型为 `kst_probflow`。本轮不运行 `kafnet_gaussian`、`kaf_profiti_marginal` 和 `kaf_profiti_joint`，因为它们属于后续概率结构消融，不属于当前“先跑通、后创新”的最小范围。

概率预测只运行中心条件 `mixed@actual 0.30`、seed `2026`，共 6 个基线 run 加 1 个本文模型 run。评价指标固定为 MAE、RMSE、NLL、CRPS、95% PICP、MPIW、完整训练时间、推理时间和参数量；checkpoint 统一由 validation CRPS 选择。

### CH2.5-P00：冻结预实验合同与执行边界

- [x] **Phase CH2.5-P00 完成：FD004、模型集合、49 个唯一 pilot run 和非正式证据边界全部锁定**（2026-09-12 验证：pilot/ch3 全量测试 99 passed；矩阵 dry-run `point=42, probabilistic=7, total=49, duplicate=0`）

#### Task CH2.5-P00-T01：建立 pilot 配置 schema

- [x] **Task CH2.5-P00-T01 完成：pilot/smoke 状态、固定数据参数和禁止项均可机器校验**（2026-09-12：先写失败测试 5 failed，实现后 `code/tests/pilot/test_pilot_config.py` 16 passed）

**文件：**
- 修改：`code/kaf_profiti/experiments/ch3/config.py`
- 创建：`configs/pilot/fd004/common.yaml`
- 创建：`code/tests/pilot/test_pilot_config.py`

- [x] 先写失败测试，要求 `run_level=pilot` 可加载，且 pilot 固定 dataset、split seed、窗口和完整 loader。
- [x] 增加 `pilot` 状态，并显式禁止 `max_train_batches`、`max_eval_batches`、engine 子集和 test-time 配置覆盖。
- [x] 配置只保存数据根/结果根的逻辑名称，不保存解析后的机器路径。
- [x] 运行 `PYTHONPATH=code python -m pytest code/tests/pilot/test_pilot_config.py -q`；预期全部通过。

**验收：** smoke 与 pilot 身份不可混淆，pilot 也不能被 formal catalog 消费。

#### Task CH2.5-P00-T02：锁定两张矩阵及计数

- [x] **Task CH2.5-P00-T02 完成：点预测 42 行、概率预测 7 行且不存在重复科学条件**（2026-09-12：先写失败测试 8 failed，创建矩阵后 `code/tests/pilot/test_pilot_matrix.py` 8 passed；dry-run `point=42, probabilistic=7, total=49, duplicate=0`）

**文件：**
- 创建：`configs/pilot/fd004/point_matrix.yaml`
- 创建：`configs/pilot/fd004/probabilistic_matrix.yaml`
- 创建：`code/tests/pilot/test_pilot_matrix.py`

- [x] 写失败测试，检查模型 ID、head、机制、requested rate、seed、执行优先级和唯一 scientific key。
- [x] point matrix 精确展开 42 行，并验证 random 30% 只出现一次但映射到 intensity/mechanism 两个 view。
- [x] probabilistic matrix 精确展开 7 行，前 6 行为 baseline，最后 1 行为 `kst_probflow`。
- [x] 运行矩阵 dry-run；预期 `point=42,probabilistic=7,total=49,duplicate=0`。

**验收：** 后续 runner 只消费 tracked matrix，不能临时手写命令改变科学参数。

---

### CH2.5-P01：数据泄漏、公平性与缺失协议整改

- [x] **Phase CH2.5-P01 完成：split、normalization、mask、target 和评价聚合均通过防泄漏测试**（2026-09-13：T01–T05 全部完成并验证；target 项由 T01 split 隔离测试（official test 隔离、engine 划分与 run seed 无关）覆盖；全量 `code/tests/` 129 passed）

#### Task CH2.5-P01-T01：分离 split seed 与 run seed

- [x] **Task CH2.5-P01-T01 完成：所有模型共享固定 engine 划分，改变模型 seed 不改变 split**（2026-09-12 验证：先行测试因 `split_identity_sha256` 不存在失败；实现后 `code/tests/pilot/test_fd004_split_leakage.py` 6 passed，全量 `code/tests/` 105 passed；conda 环境 `kaf_profiti` 补装 requirement.txt 钉定的 `PyYAML==6.0.2`）

**文件：**
- 修改：`code/kaf_profiti/experiments/datasets.py`
- 创建：`code/tests/pilot/test_fd004_split_leakage.py`

- [x] 先写测试：train/valid engine ID 不相交、official test 隔离、改变 run seed 后 split SHA 不变。
- [x] `create_protocol_datasets` 显式接收 `split_seed`，FD004 只用该字段生成 engine permutation。
- [x] 保存排序后的 engine ID、窗口边界和 split SHA；禁止模型名称进入 split identity。
- [x] 运行 FD004 split 测试和既有数据集回归测试。

**验收：** 模型和训练随机性不能改变数据划分。

#### Task CH2.5-P01-T02：冻结 train-only normalization

- [x] **Task CH2.5-P01-T02 完成：validation/test 值变化不影响 normalization SHA**（2026-09-12 验证：先行测试因 `_cmapss_stats_artifact` 不存在失败；实现后 `code/tests/pilot/test_fd004_normalization_leakage.py` 5 passed，全量 `code/tests/` 110 passed）

**文件：**
- 修改：`code/kaf_profiti/experiments/datasets.py`
- 修改：`code/kaf_profiti/industrial/cmapss.py`
- 创建：`code/tests/pilot/test_fd004_normalization_leakage.py`

- [x] 先写测试：统计量只消费 train engine 行；修改 validation/test fixture 后统计量逐字节不变。
- [x] normalization artifact 记录 source split、engine ID、列序、count、mean/std 和 SHA。
- [x] train/valid/test dataset 只接收冻结统计量，不在各自构造器内重新估计。
- [x] 检查标准差下限、常量传感器和非有限值处理，并运行测试。

**验收：** validation/test 不参与任何均值、标准差或填充值选择。

#### Task CH2.5-P01-T03：实现 timeline-first 共享 mask

- [x] **Task CH2.5-P01-T03 完成：重叠窗口复用同一观测过程，模型间 mask SHA 完全一致**（2026-09-12 验证：先行测试因 timeline API 缺失失败；实现后 `code/tests/pilot/test_fd004_timeline_masks.py` 6 passed，全量 `code/tests/` 116 passed，旧 per-window mask API 无回归）

**文件：**
- 修改：`code/kaf_profiti/industrial/missing.py`
- 修改：`code/kaf_profiti/experiments/masks.py`
- 创建：`code/tests/pilot/test_fd004_timeline_masks.py`

- [x] 先写测试：相同 engine/cycle 在所有重叠窗口中观测状态一致，split 和 engine 边界不串联。
- [x] mask 在每个 split 的 engine timeline 上生成一次，再按 canonical window indices 切片。
- [x] artifact identity 包含 schema version、dataset、split、engine、mechanism、requested rate、mask seed 和 source split SHA。
- [x] 加载已有 mask 时严格验证 shape、元数据和内容 SHA；不匹配立即失败，不静默复用。
- [x] mask 存于共享 protocol artifact 目录，各模型 manifest 只引用同一相对 artifact 路径和 SHA。
- [x] 运行 timeline mask、重复性和跨模型一致性测试。

**验收：** 模型不能在自己的 run 目录重新采样一份“看似同 seed”的 mask。

#### Task CH2.5-P01-T04：匹配四种机制的实际 30% 缺失率

- [x] **Task CH2.5-P01-T04 完成：random、low-rate、block、mixed realized rate 均处于 [0.29, 0.31]**（2026-09-12 验证：四机制在 FD004 train split 上 realized rate 全部落入 [0.29, 0.31]；`code/tests/pilot/test_matched_missing_rate.py` 6 passed，全量 `code/tests/` 122 passed）

**文件：**
- 修改：`code/kaf_profiti/industrial/missing.py`
- 创建：`code/tests/pilot/test_matched_missing_rate.py`

- [x] 为四种机制定义 deterministic calibration，使 target rate 表示最终实际缺失率而非某个内部删除概率。
- [x] 保留每通道至少一个历史观测的安全约束，并在 artifact 中记录该约束造成的 rate 偏差。
- [x] `block` 的配置展示名映射为 canonical ID `block_offline`，避免同一机制出现两个 scientific key。
- [x] 检查 mask 生成不读取 RUL、未来目标、test metric 或 fault label。
- [x] 运行四机制 realized-rate 与无标签依赖测试。

**验收：** 机制比较只改变缺失结构，不改变缺失总量。

#### Task CH2.5-P01-T05：修正全局指标累加

- [x] **Task CH2.5-P01-T05 完成：指标与 batch size 和最后小 batch 无关**（2026-09-13 验证：三个 evaluator（run_experiment / TCN-Gaussian / probabilistic_baselines）在同一 prediction、不同 batch 划分下 MAE/RMSE/NLL/CRPS/PICP/MPIW 全部一致；`code/tests/pilot/test_metric_accumulators.py` 7 passed，全量 `code/tests/` 129 passed；TCN/baselines 旧独立回归测试因硬编码 `/home/work/new_work/dataset` 数据路径本机不可运行，由本文件两个集成测试替代覆盖，run_experiment 旧回归测试包含于全量套件）

**文件：**
- 创建：`code/kaf_profiti/experiments/accumulators.py`
- 修改：`code/run_experiment.py`
- 修改：`compare_code/TCN-Gaussian/train_tcn_gaussian.py`
- 修改：`compare_code/probabilistic_baselines/train_baseline.py`
- 创建：`code/tests/pilot/test_metric_accumulators.py`

- [x] 先写失败测试：同一 prediction 以不同 batch size 评估得到相同 MAE、RMSE、NLL、CRPS、PICP 和 MPIW。
- [x] 使用 absolute-error sum、squared-error sum、log-score sum、coverage count、width sum 和统一 valid count 全局累计。
- [x] RMSE 最后由全局 squared-error sum 除有效数再开方，禁止平均 batch RMSE。
- [x] 对 point-only 输出强制概率指标为 `null/not_applicable`。
- [x] 运行 accumulator 测试和三个旧 evaluator 回归测试。

**验收：** 评价结果不受 DataLoader 分批方式影响。

---

### CH2.5-P02：统一模型接口与 fidelity 门禁

- [x] **Phase CH2.5-P02 完成：12 个基线/本文配置均有明确实现身份并通过公共接口测试**（2026-09-13 验证：T01 12 passed/141 → T02 23 passed/164 → T03 26 passed/190 全绿；5 个 point 基线 + 6 个概率基线 + KST-Light/KST ProbFlow 均带 implementation/source_identity/requires_time_input/adapter 四元身份并由 registry↔类属性一致性测试锁定）

#### Task CH2.5-P02-T01：建立统一 point/probabilistic 接口

- [x] **Task CH2.5-P02-T01 完成：训练器无需按模型读取不同目标或评价路径**（2026-09-13 验证：`code/tests/pilot/test_model_api.py` 12 passed，全量 `code/tests/` 141 passed；history-only/形状/有限值/梯度/保存恢复检查均含反向用例证明可捕获违规）

**文件：**
- 创建：`code/kaf_profiti/experiments/model_api.py`
- 创建：`code/kaf_profiti/models/lightweight_head.py`
- 创建：`code/tests/pilot/test_model_api.py`

- [x] 定义 history-only 输入、point output、distribution output、masked loss、sample 和 parameter count 合同。
- [x] Linear/MLP 轻量头只接收编码器历史表示，不接收 `Y_q`、`M_q` 或未来 context。
- [x] 对 point baseline 复用同规格轻量头；对 GRU-D/ODE-RNN/GraFITi 概率版复用同规格 diagonal Gaussian head。
- [x] 写 shape、mask、梯度、有限值、保存/恢复和禁止未来输入测试。
- [x] 运行公共接口测试；预期所有注册为 pilot-ready 的模型通过。

**验收：** 模型差异来自编码与概率结构，不来自不同 target 或 evaluator。

#### Task CH2.5-P02-T02：补齐并核验第三章点预测基线

- [x] **Task CH2.5-P02-T02 完成：LI+TCN、FF+GRU、Masked TCN、GRU-D、ODE-RNN 均达到 pilot-ready**（2026-09-13 验证：`code/tests/pilot/test_point_baseline_fidelity.py` 23 passed，全量 `code/tests/` 164 passed；registry 身份字段与模型类属性一致性由专门测试锁定）

**文件：**
- 创建或修改：`code/kaf_profiti/baselines/point.py`
- 创建：`code/tests/pilot/test_point_baseline_fidelity.py`
- 修改：`code/kaf_profiti/experiments/registry.py`

- [x] 为每个 baseline 登记 source identity、实现类型 `faithful/adapted`、必需时间输入和 adapter。（5 个基线均登记为 `adapted` + 纯文本引用来源，无 URL；GRU-D/ODE-RNN/LI+TCN 标记 `requires_time_input=True`）
- [x] GRU-D 必须实现 mask、时间间隔和可学习衰减；ODE-RNN 必须按真实历史时间演化隐藏状态。（GRU-D delta_t 递归逐值核对 + 可学习 per-sensor 衰减梯度检查；ODE-RNN 压缩/拉伸 T_obs 输出敏感性检查）
- [x] TCN/GRU adapter 只在 history 内处理缺失，首段和全空通道使用 train-only fill。（线性插值/前向填充手工规则对照：首段与全空通道用 train-only fill_value，尾部保持最后观测；T_q 扰动不变性覆盖全部 5 个模型）
- [x] 逐模型执行机制测试和一个 batch 的前向/反向测试。（统一接口检查 + 单步 AdamW 更新改变参数，5×2 参数化测试）
- [x] 未通过关键机制测试的模型保持 `interface_only`，不得进入完整 pilot matrix。（本轮 5 个基线全部 `pilot_ready`；registry 状态由测试强制与 point matrix 完全对齐）

**验收：** 名称不能超出实现真实性；简化实现必须在输出中标明 `adapted`。

#### Task CH2.5-P02-T03：补齐并核验第四章六个概率基线

- [x] **Task CH2.5-P02-T03 完成：六个概率 baseline 均通过分布、采样和 fidelity 测试**（2026-09-13 验证：`code/tests/pilot/test_probabilistic_baseline_fidelity.py` 26 passed，全量 `code/tests/` 190 passed；registry 身份字段与模型类属性一致性由专门测试锁定；ProFITi/KST ProbFlow 的 NLL 与 sample 同源由专门测试锁定）

**文件：**
- 修改：`compare_code/TCN-Gaussian/tcn_gaussian/model.py`
- 修改：`compare_code/probabilistic_baselines/baselines/models.py`
- 创建：`code/kaf_profiti/baselines/grud.py`
- 创建：`code/kaf_profiti/baselines/grafiti.py`
- 创建：`code/tests/pilot/test_probabilistic_baseline_fidelity.py`
- 修改：`code/kaf_profiti/experiments/registry.py`

- [x] 核验 TCN-Gaussian、PatchTST-Gaussian、ODE-RNN 和 ProFITi 当前简化实现与计划声明的差异。（TCN-Gaussian 为本仓库自研对照实现、无简化，登记 `faithful`；PatchTST-Gaussian/ODE-RNN-Gaussian/ProFITi 均与原方法有结构差异，登记 `adapted`/`adapted_profiti` + 纯文本引用，无 URL）
- [x] 补齐 GRU-D Gaussian 与 GraFITi Gaussian，并接入统一 distribution API。（GRU-D Gaussian 复用与 point 版完全相同的 `GRUDEncoder` 时间机制；GraFITi Gaussian 实现传感器图 + 真实时间间隔指数衰减传播；`create_probabilistic_baseline` 统一装配概率矩阵 7 个模型）
- [x] diagonal Gaussian 统一 scale 参数化、最小 scale、NLL 分母、sampling shape 和 95% 区间定义。（scale=softplus(raw)+min_scale 0.05；NLL 分母 mask.sum()；sample 为 [B,S,P*N] 且按 mq_flat 置零；95% 区间 mean±Z95·scale，Z95=1.959964；5 个 diagonal 基线 batch_nll 与手写公式逐值一致）
- [x] ProFITi 的 NLL 与 sample 必须来自同一个训练分布；若只能实现简化版则标记 `adapted_profiti`。（登记 `adapted_profiti`；统一 batch_nll = 同一 flow 的 per-row joint NLL 按行有效数重加权，predict_point/interval95/sample_flat 全部由同一 flow 的种子采样导出，确定性复现已测；不再依赖 legacy `_last_hidden` 缓存路径）
- [x] 对所有模型运行有限 NLL、sample moment、mask invariance、梯度和 checkpoint round-trip 测试。（7 个模型全过 `check_gaussian_interface`；另含单步 AdamW 参数更新检查 7 项、GRU-D/GraFITi/ODE-RNN 真实时间敏感性 3 项）

**验收：** 六个 baseline 只有在 `interface + fidelity + smoke` 三层状态明确后才能进入完整 pilot。

---

### CH2.5-P03：本机基线优先 smoke 与 AutoDL 运行资格检查

- [x] **Phase CH2.5-P03 完成：本机 11 个基线和 3 个本文配置 smoke 通过，AutoDL 环境预检通过，但未产生可报告结果**（2026-09-13 验证：T01 runner 13 tests + T02 ready=5 + T03 ready=6 + T04 ready=3 全部 0 test 指标；T05 跨机预检 `identity_sections_match`、RTX 3090 24GB 设备 smoke ok；至今零正式 run，P04 才开始产生结果）

#### Task CH2.5-P03-T01：实现统一 pilot matrix runner

- [x] **Task CH2.5-P03-T01 完成：runner 支持 dry-run、baseline-first、resume 和 continue-on-error**（2026-09-13 验证：`code/tests/pilot/test_pilot_runner.py` 13 passed；全量矩阵 dry-run `expected_total=49, expected_new=49`，模型顺序 11 基线在前、kst_probflow 最后，与 49 行矩阵一致）

**文件：**
- 创建：`code/run_pilot_matrix.py`
- 创建：`code/kaf_profiti/experiments/pilot_runner.py`
- 创建：`code/tests/pilot/test_pilot_runner.py`

- [x] runner 从 tracked YAML 展开，不在代码中写死数据根、结果根、机器地址、账号、端口或远程链接。（展开逻辑只读 `configs/pilot/fd004/*.yaml`；路径全部经 `resolve_runtime_paths` 解析，portability 扫描无新增命中）
- [x] 路径优先级复用 `resolve_runtime_paths`；artifact manifest 内只写 result-root 相对路径。（专门测试断言 manifest 内路径非绝对且无盘符锚点）
- [x] `--dry-run` 输出有序 scientific keys、模型顺序、共享 artifact SHA 和预计新训练数。（CLI 实测输出 49 个有序 key、14 个模型标签、两个矩阵文件 SHA-256、expected_new=49）
- [x] 单个模型失败只标记该 key 失败，整批继续；resume 只跳过 manifest/hash 完全匹配的已验证 key。（测试覆盖：合成失败只影响该 key；共享 SHA 篡改或 artifact 缺失即重跑，完整匹配才跳过 4/6）
- [x] baseline-first gate 在全部基线未完成前拒绝调度 KST-Light 或 KST ProbFlow。（gate 每次从展开矩阵的 scientific key 重算 manifest 证据；测试证明把基线 manifest 移到伪造 run ID 下后该 key 视为缺失、gate 不受欺骗）
- [x] 运行 runner 单元测试和 dry-run；预期顺序与 49 行矩阵一致。（13 passed；dry-run 键序 = point 基线 30 → kst_light 12 → 概率基线 6 → kst_probflow 1）

**验收：** 实验可断点续跑，且无法通过改 run ID 绕过 baseline-first 规则。

#### Task CH2.5-P03-T02：执行第三章五个基线 smoke

- [x] **Task CH2.5-P03-T02 完成：5/5 点预测基线 smoke 通过**（2026-09-13 本机执行：`run_pilot_matrix.py --mode smoke --group point_baselines` → ready=5, failed=0, test_metrics=0；报告 `result/pilot/fd004/smoke/point_baselines_smoke.json`）

- [x] 在本机执行，每个模型使用一个 train batch、一个 validation batch 和一个 test feature-only batch 检查接口；不生成 test 指标。（真实 FD004 + 混合@0.30 timeline mask；test 批只做前向有限性检查，test_metrics 恒为 null）
- [x] 检查 loss 有限且至少一步更新后参数发生变化。（loss_finite + params_changed 逐模型记录，5/5 通过）
- [x] 检查 split/normalization/mask/target SHA 与公共协议一致。（5 个模型记录同一 protocol fingerprint：split_sha256 61c7db91…、normalization_sha256 2cb43b19…、train/valid/test mask bundle SHA 一致；timeline mask 共享工件由 `generate_or_load_timeline_masks` 校验）
- [x] 记录峰值显存、batch 时间和失败堆栈，仅用于预算诊断。（batch_time_sec/peak_memory_mb 逐模型记录；失败模型记录异常类型与消息；不进入任何结论）
- [x] 运行 smoke validator；预期 `ready=5,failed=0,test_metrics=0`。（validate_smoke_report 通过：ready=5, failed=0, test_metrics=0）

**验收：** 五个点预测基线取得完整 pilot 调度资格。

#### Task CH2.5-P03-T03：执行第四章六个基线 smoke

- [x] **Task CH2.5-P03-T03 完成：6/6 概率基线 smoke 通过**（2026-09-13 本机执行：`run_pilot_matrix.py --mode smoke --group probabilistic_baselines` → ready=6, failed=0, test_metrics=0；报告 `result/pilot/fd004/smoke/probabilistic_baselines_smoke.json`；ProFITi 单 batch 10.6s/峰值 15.1GB 为重要预算诊断）

- [x] 在本机对每个模型执行前向、NLL、反向、sampling、checkpoint save/load。（真实 FD004 混合@0.30；checkpoint 为 deepcopy 扰动→恢复→同种子采样复放逐值一致）
- [x] 检查 scale/flow 参数参与梯度，samples、NLL 和区间均为有限值。（distribution_grads 检查 head/flow 命名参数的非常零梯度；nll/samples/interval 有限性 + 区间下≤上逐模型通过，6/6）
- [x] 检查所有模型使用同一 target flatten 顺序和有效位分母。（samples 形状 [B,S,P·N] 与 y_flat 展平序一致 + 掩零位置为零；分母经 mask-invariant NLL 扰动检查；6 模型共享同一 protocol fingerprint）
- [x] 不计算或保存 test 指标，只验证 feature-only inference 接口。（test_metrics 恒为 null，validator 强制 test_metric_count=0）
- [x] 运行 smoke validator；预期 `ready=6,failed=0,test_metrics=0`。（validate_smoke_report 通过）

**验收：** 六个概率基线取得完整 pilot 调度资格。

#### Task CH2.5-P03-T04：执行本文模型 smoke

- [x] **Task CH2.5-P03-T04 完成：KST-Light Linear/MLP 与 KST ProbFlow smoke 通过**（2026-09-13 本机执行：11 个基线 smoke 全部 ready 后调度 ours 组 → ready=3, failed=0, test_metrics=0；报告 `result/pilot/fd004/smoke/ours_smoke.json`）

- [x] 在本机 11 个基线 smoke 全部通过后才调度本文三个配置。（ours 组入口校验两组基线报告 ready=11/failed=0，否则拒绝运行）
- [x] KST-Light 检查 history-only，KST ProbFlow 检查 NLL、sample、PICP/MPIW 所用分布一致。（history_only 经统一扰动检查器验证；flow 的 flow_hidden 两次调用逐值一致 + interval95 种子确定性复现，NLL/sample/区间同源）
- [x] 检查本文模型共享相同协议 SHA，不通过额外 context 或缓存读取目标。（ours 3 项与 11 个基线共享同一 split/normalization/mask SHA；KST-Light/KST ProbFlow 均通过 history-only 检查）
- [x] 运行 smoke validator；预期 `ready=3,failed=0`。（validate_smoke_report 通过：ready=3, failed=0, test_metrics=0）

**验收：** smoke 只证明代码可运行，不产生模型优劣结论。

#### Task CH2.5-P03-T05：同步版本并执行 AutoDL 环境预检

- [x] **Task CH2.5-P03-T05 完成：AutoDL checkout、依赖、数据和本机已验证 commit 完全对应**（2026-09-13 验证：clean commit `67f39df`→比对范围修正 `4e68ac6` 推送，AutoDL checkout 同 commit 且 clean；最终比对 `identity_sections_match`；GPU 预检 RTX 3090 24GB + li_tcn 单批 CUDA smoke ok，报告 `result/pilot/fd004/environment/autodl-preflight-gpu.json`）

**文件：**
- 创建：`code/check_pilot_environment.py`
- 创建：`code/tests/pilot/test_pilot_environment.py`
- 输出：`result/pilot/fd004/environment/autodl-preflight.json`

- [x] 本机测试全集和 smoke 通过后形成 clean commit，并记录 commit SHA；未提交或 dirty 状态不得启动 AutoDL 完整实验。（commit `67f39df`：全量 210 tests + 三组 smoke 全绿后提交；比对范围修正后追加 commit `4e68ac6`）
- [x] AutoDL 拉取同一 commit，安装锁定依赖；禁止直接编辑 AutoDL checkout 后继续训练。（AutoDL `git pull` 至 `4e68ac6`，`git status --porcelain` 为空；依赖按 requirement.txt 安装）
- [x] 通过运行时配置解析 AutoDL 的 data/result/cache root，不把解析值回写到 tracked YAML。（仅 KST_DATA_ROOT/KST_RESULT_ROOT 环境变量，经 resolve_runtime_paths 解析）
- [x] 核验 FD004 原始文件 SHA、Python/PyTorch/CUDA/GPU、可用显存、磁盘空间和依赖摘要。（3 个 FD004 文件 SHA 两机一致；RTX 3090 24135MB / CUDA 可用；磁盘与依赖摘要入报告）
- [x] 在 AutoDL 对一个基线执行单 batch 环境 smoke，只验证设备与数据链路，不保存 test 指标。（li_tcn 单批 CUDA smoke ok=true，loss 有限+参数变化，test_metric_count=0）
- [x] 比较本机与 AutoDL 的 matrix/config/protocol/code SHA；预期除环境和解析路径外完全一致。（`identity_sections_match`：矩阵/协议 mask bundle/code 指纹/数据集 SHA 全一致；依赖版本按计划属环境差异不阻断，比对范围修正记录于 commit `4e68ac6`）

**验收：** AutoDL 预检报告通过后才能启动 P04/P05 的完整实验。

---

### CH2.5-P04：第三章 42 个点预测单种子 pilot

> **2026-09-15 冻结：** 本 Phase 及其后的 CH2.5-P05～P07 不再按 FD004 连续传感器预测任务执行。已完成的 P00～P03 工程门禁继续有效；新的数据集选择、第三章和第四章单种子实验顺序以第 13 节为唯一执行入口。冻结不等于完成，以下 checkbox 保持未勾选，禁止据此继续提交 FD004 完整训练。

- [ ] **Phase CH2.5-P04 完成：30 个基线 run 与 12 个本文 run 全部 pilot validated**

#### Task CH2.5-P04-T01：执行 30 个点预测基线 run

- [ ] **Task CH2.5-P04-T01 完成：五个基线 × 六条件全部完成且共享公平性 SHA**

> 2026-09-14 撤销：首轮 42 run 因条件轴失效全部作废（`_build_provider` 硬编码 mixed@0.30，六条件共用一份 history mask），复盘见 `plan/review/p04-condition-axis-invalid-review.md`。整改后，人工缺失只改变历史 `M_obs/X_obs`，`Y_q/M_q` 与 valid count 在全部条件间保持一致；验收清单新增 `condition_axis_effective` 必查项。

- [ ] dry-run 确认 `expected=30,new=30`，并人工复核条件与执行顺序（含 mask bundle 数 = 条件组合数）。
- [ ] 仅在 AutoDL 执行完整 train/validation/test；本机不得生成可冒充完整实验的同 key run。
- [ ] 按模型独立运行，单个失败不停止其余模型；失败 key 修复后单独 resume。
- [ ] checkpoint 只由 validation MAE 选择，完整 test 只执行一次。
- [ ] 每个 run 保存 run ID、seed、dataset、model、condition、split/mask/normalization/target SHA、history、best checkpoint、prediction、metrics 和环境信息。
- [ ] validate-only 检查 `completed=30,duplicate=0,missing=0,test_count_error=0,condition_axis_effective`；其中 `condition_axis_effective` 必须同时证明不同条件的 history mask SHA 不同/历史可观测率符合设置，且所有条件的 query window ID、`M_q`、target SHA 与 valid count 完全一致。

**验收：** 30 个基线结果齐全后才允许执行本文模型。

#### Task CH2.5-P04-T02：执行 12 个 KST-Light run

- [ ] **Task CH2.5-P04-T02 完成：Linear/MLP × 六条件全部完成且无额外信息输入**

> 2026-09-14 撤销：同 T01，首轮数据作废。

- [ ] baseline-first gate 验证 30/30 后调度 KST-Light。
- [ ] 仅在与 30 个基线相同的 AutoDL 环境执行完整训练和效率测量。
- [ ] Linear 与 MLP 除 head 类型外共享编码器、训练预算、数据和评价配置。
- [ ] checkpoint 只由 validation MAE 选择，完整 test 只执行一次。
- [ ] validate-only 检查 `completed=12,duplicate=0,missing=0,fairness_mismatch=0,condition_axis_effective`；其中不同条件只能改变历史输入 mask，不得改变 query window ID、`M_q`、target SHA 或 valid count。

**验收：** 42 个 point pilot keys 全部闭合；任一缺格时不生成排序结论。

#### Task CH2.5-P04-T03：生成点预测 pilot 汇总

- [ ] **Task CH2.5-P04-T03 完成：强度视图、机制视图和效率视图可从 42 个 artifact 重建**

**文件：**
- 创建：`code/build_pilot_outputs.py`
- 创建：`code/tests/pilot/test_point_pilot_outputs.py`
- 输出：`result/pilot/fd004/summary/point_intensity.csv`
- 输出：`result/pilot/fd004/summary/point_mechanism.csv`
- 输出：`result/pilot/fd004/summary/point_efficiency.csv`

- [ ] 强度视图只读 random 0/30/70；机制视图只读 actual 30% 的四机制。
- [ ] random 30% 两视图引用同一 run ID，不复制或重算训练结果。
- [ ] 聚合前将 AutoDL artifact 同步回本机并核对 manifest SHA；本机只读源结果进行重算与汇总。
- [ ] 输出 MAE、RMSE、valid count、参数量、训练/推理时间和 provenance；概率列固定为空并标记不适用。
- [ ] 单种子只显示原始值和描述性排序，不显示 mean±std、置信区间或显著性标记。
- [ ] 运行输出测试；预期 42/42 source keys 均可追溯。

**验收：** 汇总只能回答“哪些配置值得进入正式多 seed”，不能形成毕业论文最终结论。

---

### CH2.5-P05：第四章 7 个概率预测单种子 pilot

- [ ] **Phase CH2.5-P05 完成：六个概率基线先完成，随后 KST ProbFlow 完成**

#### Task CH2.5-P05-T01：执行六个概率基线 run

- [ ] **Task CH2.5-P05-T01 完成：6/6 baseline 在 mixed actual 30% 下 pilot validated**

- [ ] dry-run 确认 `expected=6,new=6`，KST ProbFlow 不在本批调度列表。
- [ ] 仅在通过 P03-T05 的 AutoDL 环境执行完整 train/validation/test。
- [ ] 所有模型使用相同 split/mask/normalization/target/evaluator SHA 和同一 95% 区间定义。
- [ ] checkpoint 只由 validation CRPS 选择；test 只执行一次。
- [ ] 保存完整 metrics、prediction/sample、history、best checkpoint、参数量和 timing raw repeats。
- [ ] validate-only 检查 `completed=6,nonfinite=0,fairness_mismatch=0,test_count_error=0`。

**验收：** 六个 baseline 完成前禁止启动 KST ProbFlow。

#### Task CH2.5-P05-T02：执行 KST ProbFlow run

- [ ] **Task CH2.5-P05-T02 完成：KST ProbFlow 中心条件单种子 pilot validated**

- [ ] baseline-first gate 核验六个 baseline manifest 和 artifact SHA。
- [ ] 仅在六个基线使用的同一 AutoDL 环境执行，不更换 GPU 型号、精度模式或计时设置。
- [ ] 使用同一 mixed actual 30% mask 和相同预测窗口，不修改超参数以追逐 test 结果。
- [ ] checkpoint 只由 validation CRPS 选择；test 只执行一次。
- [ ] 检查 KST 的 NLL、samples、CRPS 和区间来自同一概率分布接口。
- [ ] validate-only 检查 `completed=1,nonfinite=0,fairness_mismatch=0,test_count_error=0`。

**验收：** 第四章 pilot 共 7/7 完整，且 KST 没有获得额外数据或调参预算。

#### Task CH2.5-P05-T03：生成概率预测 pilot 汇总

- [ ] **Task CH2.5-P05-T03 完成：九项指标与 provenance 从 7 个真实 artifact 重建**

**文件：**
- 修改：`code/build_pilot_outputs.py`
- 创建：`code/tests/pilot/test_probabilistic_pilot_outputs.py`
- 输出：`result/pilot/fd004/summary/probabilistic_main.csv`

- [ ] 输出 MAE、RMSE、NLL、CRPS、95% PICP、MPIW、训练时间、推理时间和参数量。
- [ ] 聚合前将 AutoDL artifact 同步回本机并核对 manifest SHA；效率字段只消费 AutoDL 的统一硬件测量。
- [ ] PICP 与 MPIW 联合展示；PICP 目标为 0.95，不能只按区间宽度排序。
- [ ] 每行记录 run ID、checkpoint SHA、config SHA、protocol SHA 和 evaluator SHA。
- [ ] 单种子不生成标准差、显著性或“显著优于”措辞。
- [ ] 运行输出测试；预期 `rows=7,untraced=0,nonfinite=0`。

**验收：** 表格只用于跑通诊断和下一阶段选择，不直接进入论文正文。

---

### CH2.5-P06：完整性复核与结果解释边界

- [ ] **Phase CH2.5-P06 完成：49 个 pilot run 的协议、公平性、指标和产物均通过复核**

#### Task CH2.5-P06-T01：执行全局 coverage 与泄漏复核

- [ ] **Task CH2.5-P06-T01 完成：49/49 覆盖且所有公平性字段一致**

- [ ] 检查 point 42 行、probabilistic 7 行、总 source run 49，duplicate/orphan/missing 均为 0。
- [ ] 检查 49 个完整 source run 均来自 P03-T05 登记的 AutoDL 环境；本机 smoke 不得进入 coverage。
- [ ] 检查所有模型共用 split、normalization、mask、target-window SHA；输入 adapter 差异均有预注册身份。
- [ ] 检查所有实际缺失率、有效目标数、test evaluation count 和 checkpoint selector。
- [ ] 检查 metrics 与 batch size 无关，并随机抽取一个 run 从 prediction 重算指标。
- [ ] 输出只读 validation report，不手工修改源 artifact。

**验收：** 任一 leakage/fairness/coverage 问题会使对应 Phase 保持未勾选。

#### Task CH2.5-P06-T02：执行路径、链接与可移植性复核

- [ ] **Task CH2.5-P06-T02 完成：新增代码、配置、文档和 manifest 零硬编码命中**

**文件：**
- 修改：`code/tests/ch3/test_portability_policy.py`
- 创建：`code/tests/pilot/test_pilot_portability.py`

- [ ] 扫描新增 Python、YAML、Markdown 和 manifest，禁止机器绝对路径、固定主机、端口、账号、IP 和远程地址。
- [ ] 仓库内部 Markdown 链接全部使用相对路径；代码中的数据/result/checkpoint 引用来自配置或运行时解析。
- [ ] artifact 内部引用使用 result-root 相对路径；移动项目根后 validator 仍可解析。
- [ ] 新增 pilot 文件不得进入 legacy allowlist。
- [ ] 运行 portability 测试与 `git diff --check`。

**验收：** 本节所有链接和路径均可跨本机、AutoDL 或其他执行机迁移。

#### Task CH2.5-P06-T03：形成单种子诊断报告

- [ ] **Task CH2.5-P06-T03 完成：只基于真实 pilot artifact 给出下一阶段诊断，不越界形成论文结论**

**文件：**
- 创建：`plan/review/fd004-single-seed-pilot-review.md`
- 修改：`plan/progress.md`

- [ ] 分别记录点预测强度、点预测机制、概率质量和效率的观察，不跨不同实验目标混排。
- [ ] 报告训练失败、非有限值、过拟合、欠拟合、校准偏差和时间/显存瓶颈。
- [ ] 明确单种子、单数据集、adapted baseline 和未调参带来的限制。
- [ ] 禁止使用“显著提升、证明、普遍优于”等需要正式多 seed 或统计证据的措辞。
- [ ] 将所有判断绑定到 summary 行、run ID 和 checkpoint SHA。

**验收：** 诊断报告足以决定后续动作，同时不会污染论文正式证据。

---

### CH2.5-P07：调参与算法创新决策门禁

- [ ] **Phase CH2.5-P07 完成：基于验证集和工程证据明确下一步，不使用 test 反向选择方案**

#### Task CH2.5-P07-T01：判定是否进入公平调参

- [ ] **Task CH2.5-P07-T01 完成：每个需要调参的模型都有同预算、validation-only 的搜索理由**

- [ ] 只读取训练曲线和 validation 指标判断学习率、正则、容量、early stop 或数值稳定性问题。
- [ ] 所有模型使用相同候选数量和最大训练预算；复杂模型不得获得额外 test 尝试。
- [ ] test 指标只用于描述冻结模型，不参与超参数选择。
- [ ] 若代码/协议仍不稳定，优先修复工程问题，不启动算法创新。

**验收：** 调参计划由 validation 证据驱动，且预算公平。

#### Task CH2.5-P07-T02：定位本文方法的瓶颈层级

- [ ] **Task CH2.5-P07-T02 完成：问题被定位为数据协议、表示编码、轻量头、概率头或优化中的一类或多类**

- [ ] KST-Light 同时落后于多个点预测 baseline 时，先检查表示和输入协议。
- [ ] KST-Light 有竞争力但 KST ProbFlow 的 NLL/CRPS 差时，优先检查概率头与训练目标。
- [ ] MAE/RMSE 良好但 PICP/MPIW 失衡时，优先检查尺度参数和 validation-only 校准。
- [ ] 训练时间或显存成为主要瓶颈时，先做实现 profiling，再决定结构简化。
- [ ] 所有创新候选必须写明目标指标、预期机制、反证条件和后续受控实验。

**验收：** 不因单个 test 数字临时堆叠模块，每项创新都有可证伪假设。

#### Task CH2.5-P07-T03：决定正式实验升级路径

- [ ] **Task CH2.5-P07-T03 完成：形成 keep/fix/drop 决策并映射回第三、四章正式计划**

- [ ] `keep`：接口、fidelity、稳定性和公平性通过，进入多 seed formal 候选。
- [ ] `fix`：有明确实现或优化问题，修复后重复 pilot，不直接进入 formal。
- [ ] `drop`：无法达到 fidelity、数值不可用或研究问题重复，记录理由但不因结果差而删除合格模型。
- [ ] 将第三章正式候选映射到 CH3 E1/E4，将第四章概率候选映射到 Phase 6；不自动勾选原计划中尚未满足的任务。
- [ ] 在 `plan/progress.md` 登记下一阶段矩阵、预算、证据状态和剩余风险。

**最终验收：**

- point pilot 精确 42/42，probabilistic pilot 精确 7/7，总计 49 个唯一 source run。
- 本机完成测试、dry-run 和 14 个模型配置 smoke；AutoDL 完成全部 49 个不截断 pilot run。
- 所有 baseline 均先于本文模型完成；失败 run 有明确状态且不能被空值替代。
- split、normalization、mask、target 和 evaluator 在直接比较内共享 SHA，test 精确评估一次。
- random 0/30/70 回答缺失强度问题；四种 actual 30% 机制回答缺失结构问题。
- 点预测与概率预测指标边界正确，单种子不伪造均值方差、置信区间或显著性。
- 新增代码、配置、文档和 artifact 不写死路径、地址、账号、端口或内部链接。
- 只有完成复核后才规划调参和算法创新；pilot 结果不进入论文 formal 表图。

### 12.3 本轮规划记录

- **任务类型：** experiment + plan；本轮只追加执行计划，不运行训练、不写结果正文。
- **能力使用：** `using-superpowers`、`experiment-results-planning`、`writing-plans`。
- **输入依据：** 当前 FD004 数据规模、现有 dataset/mask/evaluator/registry/baseline 实现、第 11 节第三章 formal 协议，以及用户确认的单种子、强度、机制、六个概率基线和 baseline-first 要求。
- **未修改范围：** 模型、数据集、训练入口、配置、测试、`result/` 和论文正文均未在本轮改动。
- **执行位置：** P00-P02 与 P03-T01 至 T04 在本机完成；P03-T05 完成 AutoDL 环境预检；P04-P05 的完整训练在 AutoDL 完成；P04-T03、P05-T03、P06-P07 在本机读取已验签 artifact 完成。
- **后续起点：** 从 `CH2.5-P00-T01` 开始，按 Phase 顺序逐项执行并即时勾选。

---

## 13. FD004 问题复盘与第三、四章单种子实验重启 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: 使用 `subagent-driven-development`（独立 Task）或 `executing-plans`（当前会话顺序执行）逐项实施。所有步骤使用 checkbox；每通过一项验证立即将对应 `- [ ]` 改为 `- [x]`，不得在 Phase 结束后集中补勾。

**Goal：** 停止在不适配的 FD004 连续传感器预测任务上继续消耗算力，先修正 MetroPT-3 的时间、窗口、预测通道和上下文协议，再按“本机门禁 -> AutoDL 对比模型 -> 本文模型”的顺序完成第三章与第四章单种子诊断实验。

**Architecture：** FD004 当前结果只保留为数据集适配性反例，不进入第三、四章模型排序；MetroPT-3 作为第三、四章单种子主数据集。所有模型消费同一份 chronological split、train-only normalization、真实时间戳、连续片段窗口、timeline-first history mask、历史上下文和 evaluator artifact；CLI 只负责选择矩阵与运行范围，科学配置全部来自 tracked YAML。

**Tech Stack：** Python、PyTorch、pandas、NumPy、PyYAML、pytest；本机负责数据审计、测试、dry-run 和受限 smoke，AutoDL 负责不截断的完整训练与统一硬件计时。

### 13.1 诊断结论与数据集决策

#### 13.1.1 已核实事实

| 证据 | 结果 | 解释 |
|---|---:|---|
| FD004 连续性、窗口边界、engine 隔离、归一化回放、mask SHA | 32/32 checks passed | 当前两次 run 不是由跨 engine、窗口错位、归一化泄漏或条件 mask 复用造成 |
| FD004 LI+TCN `random@0%` test | MAE 0.8282 / RMSE 0.9920 | 与标准化空间零预测器几乎相同 |
| FD004 LI+TCN `random@30%` test | MAE 0.8304 / RMSE 0.9929 | best validation MAE 出现在 epoch 1，随后明显过拟合 |
| FD004 test 零预测器 | MAE 0.8305 / RMSE 0.9927 | 当前学习模型没有超过全局均值预测 |
| FD004 test persistence | MAE 1.0231 / RMSE 1.4016 | 未来传感器受未提供的未来工况切换强烈影响 |
| FD001 当前 21 通道协议 | 6 个 train sensor std `<=1e-5` | 直接复用全部 21 通道会放大准常量通道，不能作为无修改替代品 |
| MetroPT-3 原始数据 | 1,516,948 行；中位采样间隔 10 秒；331 个间隔大于 30 秒 | 数据规模和任务匹配，但窗口必须按连续片段构造 |
| MetroPT-3 当前实现 | `T_obs/T_q=torch.arange(...)` | 真实时间抖动和停机间隔未进入模型，不能直接开始论文实验 |
| MetroPT-3 当前预测目标 | 7 个连续量 + 8 个二值控制/状态量 | 二值控制量不应与连续状态量混为同一回归目标 |
| MetroPT-3 4 分钟 horizon，连续 7 通道 | valid persistence MAE 0.4052，zero MAE 0.9623 | 目标在修正后具备明显可学习性 |
| MetroPT-3 4 分钟 horizon，连续 7 通道 | test persistence MAE 0.4714，zero MAE 0.7592 | 仅作数据适配性诊断，不用于选模型或调参 |

#### 13.1.2 数据集角色冻结

| 数据集 | 本轮角色 | 是否跑第三/四章完整单种子 | 约束 |
|---|---|---|---|
| MetroPT-3 | 第三、四章主数据集 | 是 | 完成 CH34-S01～S03 数据协议门禁后才能训练 |
| FD004 | 数据适配性反例；未来可改做 RUL/风险任务 | 否 | 当前两个 run 保留原始 artifact，不继续补齐 49-run 矩阵 |
| FD001 | 可选的数据加载/接口 smoke | 否 | 未冻结传感器筛选前不得生成模型优劣结论 |
| TEP | 后续外部验证候选 | 否 | 本轮单种子主链路闭合前不展开 |

**决策理由：** “文件最小”只能降低运行成本，不能保证研究任务可辨识。FD004 原生用途是多工况退化/RUL 建模；若未来工况未知，把它改造成未来传感器回归会把不可观测控制切换混入误差。MetroPT-3 是连续工业设备时间序列，且简单 history-only predictor 明显优于零预测，更符合论文的异步多传感器状态预测主题。

### 13.2 本轮固定科学合同

1. 单种子固定为 `seed=2026`，`split_seed=2026`，`mask_seed=2026`；只生成 `run_level=pilot`，不得写成 formal 结论。
2. MetroPT-3 按唯一 timestamp group 做 chronological 50/20/30 划分；任何 source row、timestamp group 或 forecast window 不得跨 split。
3. 名义采样间隔由 train split 中位数计算；连续片段阈值固定为 `3 * train_median_interval`。窗口内出现更大间隔即丢弃该 origin，阈值的解析值与 SHA 写入协议 artifact。
4. 预测通道固定为 7 个连续状态量：`TP2`、`TP3`、`H1`、`DV_pressure`、`Reservoirs`、`Oil_temperature`、`Motor_current`。
5. 历史上下文固定为 8 个二值状态量在 forecast origin 前最后一个观测值：`COMP`、`DV_eletric`、`Towers`、`MPG`、`LPS`、`Pressure_switch`、`Oil_level`、`Caudal_impulses`。不得读取 query 段状态量。
6. 窗口固定为 `history_len=168`、`pred_len=24`、`stride=60`；按 10 秒名义间隔解释为约 28 分钟历史、4 分钟预测、10 分钟采样一个 origin。
7. `T_obs/T_q` 由真实 timestamp 换算，并以 train median interval 缩放；规则采样时相邻差约为 1，时间抖动保留，停机大间隔由片段门禁排除。
8. 连续通道均值/标准差只由 train split 中可用行计算；二值 context 保持 0/1。冻结后 valid/test 只应用，不重新估计。
9. 人工缺失只改变 history 的 `X_obs/M_obs`；`Y_q/M_q`、query timestamp、forecast origin 和 target window ID 跨条件完全不变。
10. 缺失强度为 random `0.00/0.30/0.70`；机制为实际缺失率 0.30 下的 random、low-rate、block-offline、mixed；代码 ID 固定使用 `random`、`low_rate`、`block_offline`、`mixed`，random 0.30 只训练一次，共 6 个唯一条件。
11. 第三章点预测指标为标准化空间全局 MAE/RMSE、valid count、逐传感器 MAE/RMSE、参数量、训练时间和推理时间；原始物理单位逐传感器指标作为辅助，不跨单位求和。
12. 第四章概率指标为 MAE、RMSE、NLL、CRPS、95% PICP、MPIW、valid count、参数量、训练时间和推理时间；PICP 必须与 MPIW 联合解释。
13. checkpoint 只由 validation 指标选择：第三章使用 validation MAE，第四章使用 validation CRPS；冻结 checkpoint 后 test 只完整评估一次。
14. 所有路径由 CLI、`KST_DATA_ROOT`、`KST_RESULT_ROOT`、`KST_CACHE_ROOT` 或项目相对路径解析。tracked Python/YAML/Markdown 和 manifest 禁止出现机器绝对路径、账号、主机、IP、端口或固定远程链接。
15. 先跑对比模型再跑本文模型；任一 baseline gate 未关闭时，runner 必须拒绝同范围的 `kst_light` 或 `kst_probflow`。

---

### CH34-S00：冻结 FD004 路线并固化诊断证据

- [x] **Phase CH34-S00 完成：FD004 停止条件、证据边界和可移植诊断均已登记**（2026-09-15：T01 登记 2 个 diagnostic_only run 与适配性结论；T02 消除两脚本固定路径并新建可移植性门禁；连续性诊断 32/32，全量 pilot 测试 155 passed）

#### Task CH34-S00-T01：登记 FD004 两个 run 的适配性结论

**Files：**
- 创建：`plan/review/fd004-task-suitability-review.md`
- 修改：`plan/progress.md`
- 只读：`result/pilot/fd004/runs/`

- [x] 从两个 manifest 读取 scientific key、condition、seed、protocol SHA、checkpoint SHA 和 metrics，不手工修改任何 artifact。
- [x] 将 `random@0%`、`random@30%` 与 zero/window-mean/persistence floor 放入同一张诊断表。
- [x] 明确区分“代码链路有效”和“数据任务不适配”；不得把性能差归因于已经通过的窗口或 mask 检查。
- [x] 将这两个 run 标记为 `diagnostic_only` 的文档结论，不改写 manifest 中既有字段。
- [x] 在 `plan/progress.md` 记录“CH2.5-P04～P07 已冻结，由第 13 节替代”。

**验收：** 后续 runner 不会把 FD004 两个 run 计入 MetroPT-3 coverage，论文表格构建器也不会读取它们。

#### Task CH34-S00-T02：消除诊断脚本中的固定路径

**Files：**
- 修改：`code/diagnostics/fd004_continuity_diag.py`
- 修改：`code/diagnostics/fd004_learnability_sanity.py`
- 修改：`code/tests/pilot/test_fd004_window_continuity.py`
- 测试：`code/tests/pilot/test_pilot_portability.py`

- [x] 先写失败测试：扫描两个脚本并断言不存在用户目录、固定 data root 或固定 result root。
- [x] 运行 `python -m pytest code/tests/pilot/test_pilot_portability.py -q`；预期在修复前因固定路径失败。
- [x] 为脚本增加 `--data-root`、`--result-root`/`--runs-root` 参数，并复用 `resolve_runtime_paths`；默认值只能来自环境变量或项目相对目录。
- [x] 将诊断输出路径放入解析后的 result root，manifest 引用保持 result-root 相对路径。
- [x] 重跑连续性诊断；预期 `32/32 checks passed`。
- [x] 重跑 portability 测试与 `git diff --check`；预期全部通过。

**验收：** 在本机或 AutoDL 改变项目根后，两个诊断脚本无需改源码即可运行。

---

### CH34-S01：重建 MetroPT-3 数据协议

- [x] **Phase CH34-S01 完成：真实时间、连续片段、7 个连续目标和 8 个历史上下文全部由测试锁定**（2026-09-15：T01–T05 完成，核心协议经审查通过；F01/F02 补丁修正身份链与门禁统计——T05 数据门禁 pass：persistence 相对 zero（标准化零点）改善 **58.16%**、7/7 通道改善、leakage 全过、finite；初版 62.4% 因二次标准化作废；全量 266 passed）

#### Task CH34-S01-T01：实现 timestamp-group split 与连续片段 catalog

**Files：**
- 修改：`code/kaf_profiti/industrial/metropt.py`
- 修改：`code/kaf_profiti/experiments/datasets.py`
- 创建：`code/tests/pilot/test_metropt_protocol.py`

- [x] 先写失败测试：重复 timestamp 的全部 source rows 必须进入同一 split，train/valid/test source row ID 两两不交。
- [x] 先写失败测试：构造一个 10 秒序列并插入 31 秒间隔，任何 history/query 跨该间隔的 origin 均不得进入 window catalog。
- [x] 先写失败测试：split 边界、segment ID、forecast origin、query timestamps 和 row IDs 的 SHA 在同配置下稳定复现。
- [x] 实现按 timestamp group 的 50/20/30 chronological split，再在每个 split 内按 `gap_multiplier=3` 划分 segment。
- [x] window ID 固定由 dataset、split、segment ID、forecast timestamp 和 query timestamp SHA 构成，不包含模型名或 seed。
- [x] 运行 `python -m pytest code/tests/pilot/test_metropt_protocol.py -q`；预期全部通过。

**验收：** 没有窗口跨 split、重复 timestamp group 或大于协议阈值的时间间断。

#### Task CH34-S01-T02：分离连续预测通道与历史运行上下文

**Files：**
- 修改：`code/kaf_profiti/industrial/metropt.py`
- 修改：`code/kaf_profiti/industrial/batch.py`
- 修改：`code/kaf_profiti/experiments/datasets.py`
- 测试：`code/tests/pilot/test_metropt_protocol.py`

- [x] 先写失败测试：`X_obs/Y_q/M_obs/M_q` 最后一维严格为 7，`context` 最后一维严格为 8。
- [x] 先写失败测试：逐个断言 7 个连续通道和 8 个 context 通道的固定顺序；列缺失、重复或顺序漂移均 hard fail。
- [x] 先写失败测试：任意修改 query 段 8 个状态量不得改变模型输入 `X_obs/M_obs/T_obs/context`。
- [x] 将 MetroPT sensor schema 改为 7 个连续目标；context 使用 history 最后 timestamp 的 8 个二值状态值。
- [x] 二值 context 只允许 0/1 且不做 z-score；发现其他值时报告列名、source row ID 并失败。
- [x] 运行目标/上下文隔离测试；预期所有 target perturbation 和 future-context perturbation 检查通过。

**验收：** 模型只预测连续状态量，且所有模型拥有完全相同的 history-only 运行上下文。

#### Task CH34-S01-T03：接入真实时间与数值稳定缩放

**Files：**
- 修改：`code/kaf_profiti/industrial/metropt.py`
- 修改：`code/kaf_profiti/industrial/batch.py`
- 测试：`code/tests/pilot/test_metropt_protocol.py`

- [x] 先写失败测试：输入 `[0s,10s,21s,31s]` 后，`T` 的相邻差必须保留 `[1.0,1.1,1.0]`，不能退化为等距 `arange`。
- [x] 先写失败测试：`T_q[0] > T_obs[-1]`，且两者来自同一 timestamp scale artifact。
- [x] 将 timestamp 相对当前 segment 起点转换为秒，再除以 train median interval；保存原始单位、缩放值和 SHA。
- [x] GRU-D 的 `delta_t`、ODE-RNN 的积分间隔和 KST 时间编码全部消费同一 `T_obs`，不得各自重建规则索引。
- [x] 运行时间敏感性测试：改变合法时间间隔但不改值时，三个时间模型的输出必须发生有限变化。

**验收：** 论文中的“异步/不规则时间”对应真实 timestamp 与共享 mask，不再仅由等距索引伪造。

#### Task CH34-S01-T04：冻结 train-only normalization 与 timeline-first masks

**Files：**
- 修改：`code/kaf_profiti/experiments/datasets.py`
- 修改：`code/kaf_profiti/experiments/masks.py`
- 创建：`code/tests/pilot/test_metropt_condition_axis.py`

- [x] 先写失败测试：改变 valid/test 数值不能改变 normalization SHA；改变 train 数值必须改变 SHA。
- [x] 先写失败测试：6 个条件的 history mask SHA 不同，random 0/30/70 的实际可观测率严格递减。
- [x] 先写失败测试：6 个条件的 window ID、`Y_q/M_q`、target SHA 和 valid count 完全相同。
- [x] 在 segment timeline 上先生成 mask，再由 window catalog 切片；mask 生成器不得读取 fault label、query target 或 test metric。
- [x] 将 split、segment、normalization、mask、target schema 和 evaluator SHA 写入 provider fingerprint。（2026-09-15 F01 更正：身份经分层 SHA 链进入 split_sha256——raw 覆盖 7 连续+8 context 列、window catalog 全量 records、target schema/evaluator/fault windows 显式入 identity；provider fingerprint 记录 split_sha256+normalization+mask_sha，并透传 v2 的 target_schema_sha256/evaluator；运行 seed 已从 split identity 移除）
- [x] 运行 `python -m pytest code/tests/pilot/test_metropt_condition_axis.py -q`；预期全部通过。

**验收：** 实验轴确实改变 history 输入，同时不改变被评价的未来目标集合。

#### Task CH34-S01-T05：建立数据可学习性与风险标签门禁

**Files：**
- 创建：`code/diagnostics/metropt_learnability.py`
- 创建：`code/tests/pilot/test_metropt_learnability.py`
- 输出：`result/pilot/metropt3/diagnostics/data_gate.json`

- [x] 只在 train/validation 上计算 zero、train mean、window mean、persistence 和 linear trend；test floor 只用于最终数据审计描述，不参与协议选择。
- [x] 对 7 个连续通道分别输出 MAE/RMSE，再输出标准化空间全局 micro 指标；禁止跨物理单位聚合原始值误差。
- [x] 数据门禁要求 validation 上至少一个 history-only floor 相对 zero MAE 改善 10% 以上，且至少 5/7 个通道改善。
- [x] 风险标签固定为“query timestamp 与登记 fault interval 有交集”；输出每个 split 的正负 window 数和 label SHA。
- [x] validation 或 test 任一 split 缺少正类/负类时，第四章风险指标标记不可解释并停止风险子任务，但不阻断概率预测主任务。
- [x] 运行诊断两次并比较 JSON 中科学字段；预期 SHA 与指标逐值一致。

**验收：** 只有 `leakage_checks=pass`、`learnability_gate=pass` 和 `finite=true` 才能进入 runner 改造。

---

### CH34-S02：泛化 runner、矩阵与统一评价器

- [x] **Phase CH34-S02 完成：MetroPT-3 的 49 个单种子 key 可选择、可恢复、可验签**（2026-09-17 审查修复后：`--matrix all` dry-run 精确 49 唯一 key；完整 prediction artifact 已接入默认 trainer/resume；本机 14 模型 smoke 共享含 raw/partition/timeline/window/time-scale/realized-rate 的唯一协议指纹；全量 313 passed。尚未训练任何正式 run——S03 起）

#### Task CH34-S02-T01：移除 runner 的 FD004 专用假设

- [x] **Task CH34-S02-T01 完成：runner 已支持 profile/筛选、同范围 baseline-first gate 与严格验签 resume**（T02/T03 配置建立后已完成 MetroPT 42/7/49-key CLI 验收；2026-09-17 全量回归 313 passed）

**Files：**
- 修改：`code/run_pilot_matrix.py`
- 修改：`code/kaf_profiti/experiments/pilot_runner.py`
- 修改：`code/tests/pilot/test_pilot_runner.py`

- [x] 端到端验收：`--profile metropt3` 从 `configs/pilot/metropt3/` 加载真实矩阵；point/probabilistic/all dry-run 分别展开 42/7/49 个 key，profile 结果目录固定为 `pilot/metropt3/`。
- [x] 先写失败测试：`--family baseline|ours`、可重复 `--condition-id` 和可重复 `--model-id` 只能筛选调度范围，不能改变 scientific key 或 matrix SHA。
- [x] 先写失败测试：调度 ours 时，baseline-first gate 只接受同 dataset、track、condition 和 seed 的已验签 baseline manifests。
- [x] 将 `_PILOT_ROOT`、config dir、报告路径和 CLI 文案改为 dataset profile 驱动，不在源码中拼接 FD004。
- [x] resume 必须同时匹配 matrix、data、split、segment、normalization、mask、target、evaluator、code 和 checkpoint artifact SHA。
- [x] 完成 T01 审查整改：manifest 逐字段身份校验；artifact 名称/SHA 完全覆盖和相对路径约束；checkpoint 与完成后重验；dry-run/execute 统一 protocol 校验；custom/`**kwargs` provider 支持；按 condition 缓存；动态 smoke 条件/计数；`force-rerun` 报告语义；profile 单一真源。
- [x] 运行 runner 测试；原 FD004 expansion 与新增 profile/filter/gate/resume/security/cache/smoke 回归共 36 passed；全量 `code/tests/` 287 passed、2 个既有 sklearn deprecation warnings。

**验收：** 可以先运行中心条件，再运行剩余条件，同时完整复用同一 tracked matrix 身份。

#### Task CH34-S02-T02：创建第三章点预测单种子矩阵

- [x] **Task CH34-S02-T02 完成：MetroPT-3 点预测单种子矩阵创建并 dry-run 精确展开 42 个 key**（2026-09-16：point_matrix.yaml 注册 5 baseline + 2 KST-Light head × 6 条件；runner `--profile metropt3 --matrix point --mode dry-run` 精确展开 42 个唯一 key、baseline 排在 ours 前；common.yaml 锁定 MetroPT 协议；test_metropt_matrices.py 7 passed；T01 遗留的 MetroPT CLI 端到端验收框随之关闭）

**Files：**
- 创建：`configs/pilot/metropt3/common.yaml`
- 创建：`configs/pilot/metropt3/point_matrix.yaml`
- 测试：`code/tests/pilot/test_metropt_matrices.py`

- [x] 登记 5 个 baseline：`li_tcn`、`ff_gru`、`masked_tcn`、`gru_d`、`ode_rnn`，统一使用 Linear point head。
- [x] 登记本文模型 `kst_light` 的 Linear 与 MLP 两个轻量头；两者除 head 外共享 encoder、数据和训练预算。
- [x] 登记 6 个唯一条件：random 0/30/70、low-rate 30、block-offline 30、mixed 30；condition ID 固定为 `point_random_000`、`point_random_030`、`point_random_070`、`point_low_rate_030`、`point_block_offline_030`、`point_mixed_030`，random 30 同时属于 intensity/mechanism 两个视图。
- [x] 固定 `seed=2026`、168/24/60、50 epochs、batch 128；不登记 model-specific test override。
- [x] dry-run 断言 point key 精确为 `5*6 + 2*6 = 42`，baseline 排在 ours 前。

**验收：** 42 个 key 的区别只来自模型、head 或预注册 history 缺失条件。

#### Task CH34-S02-T03：创建第四章概率预测单种子矩阵

- [x] **Task CH34-S02-T03 完成：MetroPT-3 概率预测单种子矩阵创建并 dry-run 精确展开 7 个 key**（2026-09-16：probabilistic_matrix.yaml 注册 6 baseline + `kst_probflow`，唯一中心条件 `prob_mixed_030`（mixed@0.30）；runner `--profile metropt3 --matrix probabilistic --mode dry-run` 精确 7 个唯一 key、baseline 在前 KST 最后；test_metropt_matrices.py 概率段 6 项验证通过；点/概率 49 key 无碰撞）

**Files：**
- 创建：`configs/pilot/metropt3/probabilistic_matrix.yaml`
- 测试：`code/tests/pilot/test_metropt_matrices.py`

- [x] 登记 6 个 baseline：TCN-Gaussian、PatchTST-Gaussian、GRU-D-Gaussian、ODE-RNN-Gaussian、GraFITi-Gaussian、ProFITi。
- [x] 登记本文模型 `kst_probflow`，固定中心条件 `prob_mixed_030`（mixed@0.30）。
- [x] 每个 adapted baseline 在 registry/manifest 保留实现身份，不得把本仓库简化实现表述为原论文官方实现。
- [x] 固定 `seed=2026`、168/24/60、50 epochs、batch 128；矩阵声明 `interval_level=0.95` 与 `nsamples=100`，其运行时生效由 T04 统一指标/artifact schema 承载。
- [x] dry-run 断言 probabilistic key 精确为 `6+1=7`，六个 baseline 全部排在 KST ProbFlow 前。

**验收：** 第四章概率比较只有 7 个唯一 source run，不复制第三章点预测结果冒充概率结果。

#### Task CH34-S02-T04：补齐统一指标与 artifact schema

- [x] **Task CH34-S02-T04 完成：统一 evaluator 已接入真实 runner，正式 run 产物可从 prediction artifact 复算**（2026-09-17 审查修复：point/probabilistic 默认 trainer 均生成完整 payload；manifest 强制 prediction artifact 与 `test_evaluation_count=1`；逐通道标准化/物理单位指标、概率贡献、三次推理计时和参数量由同一 payload 复算）
- 修改：`code/kaf_profiti/experiments/evaluator.py`
- 修改：`code/kaf_profiti/experiments/pilot_runner.py`
- 创建：`code/tests/pilot/test_metropt_evaluator.py`

- [x] 先写失败测试：MAE/RMSE 由全局 error sum/count 计算，结果不随 batch size 改变。
- [x] 先写失败测试：NLL/CRPS/PICP/MPIW 使用同一 distribution sample/interval，invalid target 不进入分母。
- [x] 保存标准化全局指标、逐通道标准化指标和逐通道物理单位指标；物理误差只逐通道报告，不跨单位聚合。
- [x] 保存完整 prediction、target、mask、window ID、checkpoint、history、概率区间、逐窗口 NLL/CRPS 贡献、timing raw repeats 和相对路径 manifest；默认 trainer 与 resume 验签均要求 prediction artifact。
- [x] manifest 必须含 `run_id`/scientific key、seed、dataset、model、condition、实际缺失率、全部公平性 SHA 和 `test_evaluation_count=1`。
- [x] 运行 evaluator 测试与 artifact round-trip；T04 专项 5 passed，全量 305 passed。

**验收：** 第三、四章的每个报告数字都可从 prediction artifact 独立重算。

#### Task CH34-S02-T05：执行本机全模型 smoke

- [x] **Task CH34-S02-T05 完成：本机 14 个模型 smoke 全部通过且共享同一协议指纹**（2026-09-17 审查后重跑：point_baselines ready=5、probabilistic_baselines ready=6、ours ready=3，全部 failed=0、test_metrics=0；14 entry 完整协议指纹唯一且与 S01 split SHA 一致；全量 313 passed；portability 与 `git diff --check` 通过）

**Files：**
- 修改：`code/tests/pilot/test_point_baseline_fidelity.py`（未修改：数据集无关合成合同测试，MetroPT 真实维度由 runner 级 smoke 覆盖）
- 修改：`code/tests/pilot/test_probabilistic_baseline_fidelity.py`（未修改：同上）
- 输出：`result/pilot/metropt3/smoke/`（三个报告已生成）

- [x] 先运行全部单元测试：`python -m pytest code/tests/ -q`；预期零失败。（305 passed, 2 warnings）
- [x] 对 5 个点 baseline 运行一个 train batch、一个 validation batch和一个 feature-only test batch；预期 `ready=5, failed=0, test_metrics=0`。
- [x] 对 6 个概率 baseline 运行 forward/NLL/backward/sample/checkpoint round-trip；预期 `ready=6, failed=0, test_metrics=0`。
- [x] baseline smoke 全部通过后，再运行 KST-Light 两个 head 和 KST ProbFlow；预期 `ready=3, failed=0, test_metrics=0`。
- [x] 比较 14 个 smoke entry 的 split/segment/normalization/center-mask/target/evaluator SHA；预期完全一致。（唯一指纹，split_sha256=90650166… 与 data_gate 一致）
- [x] 运行 portability scan 与 `git diff --check`；预期零固定路径、主机、账号、端口或 URL 命中。

**验收：** 本机只证明代码和接口可运行，smoke 指标不得进入任何模型排序。

---

### CH34-S03：AutoDL 环境预检与中心条件学习门禁

- [x] **Phase CH34-S03 完成：同一 clean commit 在 AutoDL 通过数据、设备和 validation-only 学习门禁**（T01 跨机身份一致 + GPU smoke pass；T02 LI+TCN/ODE-RNN 5-epoch sanity 的 finite/updated/validation_improved 与同一 validation-loader LOCF `beat_naive` 全 true。该 gate 是单种子 pilot readiness 信号，不构成一般性协议可学习性证明）

#### Task CH34-S03-T01：冻结版本并核对跨机身份

- [x] 完成 S02 审查修复、本机全量测试、data gate、49-key dry-run、14-entry smoke 与 portability 检查；只暂存允许的代码、配置、测试和计划文档，形成 clean commit 并记录 Git SHA。（freeze commit `7d2a99e`；本机 314 passed；49/49 dry-run；smoke 5/6/3；portability 5 passed）
- [x] 在该 clean commit 上运行 `--profile metropt3 --require-clean` 生成本机 v2 preflight；不得在 commit 前生成报告并把旧 SHA 当作冻结证据。（local-preflight.json 于 `7d2a99e` 生成，SHA256 `018474ab…2576`）
- [x] profile-aware checker 从实际 MetroPT CSV 重算 raw/partition/timeline/window/normalization/time-scale/target/evaluator 身份，并为中心 `mixed@0.30` 生成 mask 身份；不得依赖未同步的本机 `data_gate.json`。（checker 只 import pilot_runner/矩阵；raw=`48f6c4a6`、split=`eb7b957c`；3 个 mask bundle）
- [x] AutoDL 只 checkout 同一 commit，不直接编辑 checkout；数据根、结果根和缓存根只通过环境变量设置，且 `git status --porcelain` 必须为空。（AutoDL checkout `7d2a99e`，dirty_file_count=0）
- [x] 在 AutoDL 运行 `--profile metropt3 --require-clean --require-gpu --smoke`；只执行 LI+TCN 中心条件单 batch CUDA 更新，`test_metric_count=0`。（model=li_tcn、cond=point_mixed_030、device=cuda、ok=true、batch_time=0.364s）
- [x] 比较 local/AutoDL v2 reports：Git commit、MetroPT raw data、两矩阵、split/partition/timeline/window、normalization、time-scale、mask、target、evaluator 和 code SHA 必须一致；路径、环境名和硬件字段不参与身份相等判断。（`compare_reports` → IDENTITY_SECTIONS_MATCH）
- [x] 记录 GPU、CUDA、PyTorch、可用显存、磁盘、报告相对路径与报告文件 SHA；不修改或纳入遗留根目录 `autodl-preflight.json`。（RTX 3090/CUDA 12.4/torch 2.5.1+cu124/24135MB/41.63GB free；autodl-preflight.json SHA256 `2944854b…c336`，遗留根目录资产 mtime 未变、未纳入）
- [x] 只有 clean=true、identity sections match 且 GPU smoke 通过后才勾选本 Task；T02 的 5-epoch validation-only 训练和 CH34-S03 Phase 保持未完成。

**验收：** scientific identity 完全一致且 AutoDL checkout clean，才能开始短训练。 ✅（跨机身份一致，进入 T02 前置条件已满足）

**漂移修复记录（本次执行中新发现并解决）：** 首次跨机比较暴露 9 个协议身份字段漂移（raw/partition/split/timeline×3/window_catalog×3），而 normalization/time-scale/mask/realized_rate/code 全部一致。TZ=UTC/Asia/Shanghai 双跑排除时区假设；组件级二分定位根因：pandas `read_csv` 默认浮点解析（xstrtod）允许 ~1ULP 误差且随构建变化——本机 arm64 默认解析（raw=`27064b05`，split=`90650166`）与 AutoDL x86_64 默认解析（raw=`48f6c4a6`，split=`eb7b957c`=正确舍入值）在全部 7 个连续通道字节不同，ULP 级差异在统计层被冲掉，故既有一致性检查全部通过。修复 `load_metropt_frame_v2` 与 v1 加载器显式 `float_precision="round_trip"`（IEEE754 正确舍入、平台唯一），新增红→绿测试钉死 loader 输出与 round_trip 参照逐字节一致。规范身份链 split=`eb7b957c…`；过期 mask bundle（内嵌旧身份）归档至 `masks_superseded_20260917_default_parse/`；data gate 与 14-entry smoke 在规范解析下重建，全量 314 passed。

#### Task CH34-S03-T02：执行 LI+TCN validation-only 短训练

- [x] 只在 `mixed@0.30` 上运行 LI+TCN 的 5-epoch train/validation sanity，不访问 test target。（AutoDL GPU，device=cuda，sanity_epochs=5，test_evaluation_count=0）
- [x] 保存 `run_level=sanity_train`，与完整 pilot key/目录隔离，不能被 resume 当作完整结果。（独立目录 `result/pilot/metropt3/sanity/`，非 `runs/`，resume 不扫描）
- [x] 检查 loss 有限、参数发生更新、validation MAE 至少一次优于初始化模型，并与 data gate 的 history-only floor 比较。（finite=true、updated=true、validation_improved=true；当时的 raw 0.9159/56.5% 记录已作废。有效口径为同一 validation-loader 的 standardized masked-query LOCF persistence baseline=0.4572，已在 commit `2b47c07` 重跑并生成新 manifest）
- [x] 若 learned model 完全不优于 best naive floor，则停止后续 GPU 调度，进入数据/优化诊断；不得为了过门禁读取 test。（原始 raw-space 56.5% 叙述已作废；修正后的 standardized masked-query LOCF gate 已由新 sanity manifest 确认，li_tcn/ode_rnn `beat_naive=true`×2）
- [x] 若通过，登记固定优化器和训练预算；本轮不进行 learning-rate sweep 或模型特异调参。（固定 AdamW lr=1e-3 weight_decay=1e-4，5 epoch，batch 128）
  - **2026-09-17 修订登记：** 全局梯度裁剪 `grad_clip_norm=1.0` 补入固定训练配方。这不是新增科学配置，而是对齐仓库既有训练入口（`run_experiment.py`、`train_metropt_kaf_profiti.py`、`train_cmapss_kaf_profiti.py` 均为 clip=1.0）——首个 pilot runner 实现遗漏了它。证据：无裁剪时 adapted Euler ODE-RNN 在中心条件发散（梯度范数峰值 ~6.6e7，valid MAE 9.30 vs persistence floor 0.9159，20 epoch 最好 1.10 仍不达标）；clip=1.0 + lr 不变，6 epoch 即 valid MAE 0.747 越过 floor；lr=1e-4 对照更差，故 lr 保持 1e-3。裁剪统一作用于全部模型（baseline 与本文），不引入 per-model 差异；回归测试 `code/tests/pilot/test_grad_clipping.py` 钉死该配方（4 passed）。此次修订改变训练循环 → code SHA 变化，跨机 preflight 与 5-epoch sanity 须在新 commit 上重做，且下轮 sanity 应将 ODE-RNN 纳入（此前只跑 LI+TCN）。

**验收：** `finite=true`、`updated=true`、`validation_improved=true` 后才能启动第三章完整 baseline。 ✅

**执行注记（2026-09-18，修正后）：** AutoDL sanity 重跑使用 commit `2b47c07`、clean=true、CUDA；训练曲线与三标志均通过。新 validation-loader standardized masked-query LOCF persistence baseline=0.4572，LI+TCN best=0.4013、ODE-RNN best=0.3985，二者 `beat_naive=true`，相对改善约 12.2%/12.8%。data_gate 的 raw/all-query floor 仍作为独立参考，不能与该 sanity baseline 混比。
  - **2026-09-18 口径更正：** 上文 beat_naive 引用的 persistence raw 0.9159 为 raw 物理空间基准，与本仓库 run 指标的 standardized 空间（train-split z-score）不匹配——"改善 56.5%"作废。按 data_gate `std_micro` 参考值粗估的改善为 ode_rnn +1.0%、li_tcn +0.3%（5 epoch 触及 floor；跨口径指示值）；修正后的同一 validation-loader LOCF baseline=0.4572，两个重跑 sanity 分别达到 0.3985/0.4013，改善约 12.8%/12.2%，仅表示该 loader 契约下的 gate。完整口径声明见 `plan/CH3-S04-go-no-go.md`；runner 的 beat_naive 基准已在 2026-09-18 代码窗口修正，旧 sanity manifest 已归档。

---

### CH3-S04：第三章中心条件单种子对比

> **训练配置基线（2026-09-17 确立）：** 本 Phase 全部 run（含后续 S05/S06 扩展）使用固定配方 AdamW lr=1e-3 / weight_decay=1e-4 / **全局 grad_clip_norm=1.0** / batch 128。裁剪为仓库既有入口的既定配方恢复（详见 CH34-S03-T02 修订登记），统一作用于所有模型，不构成模型特异调参。执行位置：AutoDL 有卡模式；本机只允许 dry-run/smoke/单 epoch 计时，不产生正式 artifact。

- [x] **Phase CH3-S04 完成：5 个 baseline 先完成，随后 KST-Light 两个 head 完成**（2026-09-18，中心条件 7/7 验签 + go/no-go 结论 go，报告 `plan/CH3-S04-go-no-go.md`）

#### Task CH3-S04-T01：运行 5 个点预测 baseline 的中心条件

- [x] dry-run 筛选 `track=point,family=baseline,condition_id=point_mixed_030`；预期 `expected=5,new=5`。（AutoDL 与本机 dry-run 均 expected_total=5, expected_new=5）
- [x] 在同一 AutoDL 环境依次运行 LI+TCN、FF+GRU、Masked TCN、GRU-D、ODE-RNN；单模型失败不停止其余模型。（同机 RTX 3090 一次会话连续完成 5/5，device=cuda，elapsed 570.9-724.0s/run，failed=[]）
- [x] 每个模型完整使用 train/validation，按最低 validation MAE 保存 best checkpoint，冻结后完整 test 一次。（pilot_train_and_evaluate 按 best_valid 选择 checkpoint 并回载后再评估；5 个 manifest test_evaluation_count=1）
- [x] validator 检查 `completed=5, nonfinite=0, fairness_mismatch=0, test_count_error=0`。（execute completed_count=5/failed=0；轴检查：预测全有限且非全零、protocol_sha/shared_artifacts/code_fingerprint 五 run 完全一致、realized_rate 0.297/0.301/0.304、test MAE 五模型互异 0.2389-0.3501；回传本机后 dry-run 验签 verified_complete=5, expected_new=0）
- [x] 至少一个 learned baseline 必须在 validation 上优于 best naive floor；否则保持 Phase 未勾选并先诊断。（本轮 sanity 旧 manifest 的 raw-space `beat_naive` 已作废；正式 run 的 valid floor 使用 standardized data-gate 参考，sanity gate 以修正后的 loader baseline 为准）

**验收：** 5 个 baseline artifact 全部验签后，baseline-first gate 才允许本文模型运行。 ✅

**执行注记（2026-09-18）：** AutoDL RTX 3090（commit c535097，跨机 preflight `identity_sections_match`，环境 smoke ok）完成 5/5 baseline 中心条件。test MAE 排序：ff_gru 0.2389 < li_tcn 0.2605 < masked_tcn 0.2751 < ode_rnn 0.2989 < gru_d 0.3501，全部低于 test persistence std_micro floor 0.4786（+26.8% ~ +50.1%；口径声明见 `plan/CH3-S04-go-no-go.md`）。sanity 同时纳入 ODE-RNN，满足 2026-09-17 修订登记（2956 行）的纳入要求；grad clip=1.0 下 ODE-RNN 未复现发散（test 0.2989，sanity best 0.3985）。产物已回传本机 `result/pilot/metropt3/runs|sanity/` 并通过 dry-run 验签与轴差异化复核（2026-09-14 教训项：五 model_id 互异、fairness SHA 一致、指标跨模型有差异）。

#### Task CH3-S04-T02：运行 KST-Light Linear/MLP 中心条件

- [x] dry-run 筛选 `track=point,family=ours,condition_id=point_mixed_030`；预期 `expected=2,new=2`。（AutoDL dry-run expected_total=2, expected_new=2：kst_light|linear、kst_light|mlp）
- [x] gate 核对同条件 5/5 baseline manifest、checkpoint 和公平性 SHA。（execute 内建 baseline-first gate 放行；本机 7-run 复核 protocol_sha/shared_artifacts/code_fingerprint 完全一致）
- [x] 运行 KST-Light Linear 与 KST-Light MLP；除 head 外不得更改 encoder、数据、epoch、batch 或优化预算。（同矩阵同条件同 seed，仅 head_type 不同；device=cuda，elapsed 695.8/699.2s）
- [x] checkpoint 只由 validation MAE 选择，test 各完整评估一次。（best_valid 选择；两 manifest test_evaluation_count=1）
- [x] validator 检查 `completed=2, nonfinite=0, fairness_mismatch=0, test_count_error=0`。（completed_count=2/failed=0；轴检查 7-run 全过：预测全有限非全零、7 个 MAE 互异；回传本机 dry-run 验签 verified_complete=7, expected_new=0）

**验收：** 中心条件 7/7 齐全后才能扩展缺失强度与机制。 ✅

**执行注记（2026-09-18）：** 中心条件 7/7 闭合（同机 RTX 3090、c535097、与 baseline 同 protocol_sha）。validation MAE 排序：kst_light|mlp 0.2777 < ff_gru 0.2819 < kst_light|linear 0.2956 < li_tcn 0.3157 < masked_tcn 0.3464 < ode_rnn 0.3552 < gru_d 0.4048——kst_light|mlp validation 全场最优；test MAE 排序（ff_gru 0.2389 < li_tcn 0.2605 < masked_tcn 0.2751 < kst_light|mlp 0.2923 < kst_light|linear 0.2988 < ode_rnn 0.2989 < gru_d 0.3501）与 validation 有排名扰动，留待 T03 go/no-go 诊断，不在单种子 pilot 下过度解读。

#### Task CH3-S04-T03：生成中心条件 go/no-go 报告

- [x] 本机同步 7 个完整 artifact 并校验 manifest/artifact SHA，不手工修改源文件。（dry-run 验签 verified_complete=7, expected_new=0；manifest 身份段/artifact SHA256/checkpoint_sha/protocol_sha 全链校验）
- [x] 输出 validation/test MAE、RMSE、逐传感器误差、参数量、训练/推理时间及相对 best naive 的改善率。（`plan/CH3-S04-go-no-go.md`：主表 + 逐通道表 + 效率表；naive 基准取 std_micro valid 0.4024 / test 0.4786）
- [x] 检查是否存在全模型接近零预测、epoch 1 后持续恶化、单通道支配总误差或 timing 不可比。（四项全过：sd_ratio 0.73-0.84、ode_rnn 后期退化被 best_valid 兜底、通道占比 0.18-0.19 无支配、同机 timing 可比）
- [x] 只给出 `go/fix/stop` 诊断，不报告 mean±std、置信区间、显著性或“证明优于”。（结论 go，单种子边界已在报告声明）
- [x] 只有 `go` 才进入 CH3-S05；`fix` 必须通过 validation-only 重跑，旧 run 保留但不得混入新矩阵。（go，无需 fix；`beat_naive` 基准已在 commit `2b47c07` 修正为同一 validation-loader 的 standardized masked-query LOCF persistence，sanity 已重跑，与正式 data-gate floor 分开）

**验收：** 中心条件单种子 pilot 显示存在可优化信号，且全模型比较口径一致；这支持进入 CH3-S05，不构成 MetroPT 协议的一般性可学习性或多 seed formal 证明。 ✅ 报告：`plan/CH3-S04-go-no-go.md`（2026-09-18，结论 go）

---

### CH3-S05：第三章缺失强度与机制单种子扩展

- [ ] **Phase CH3-S05 完成：第三章 42/42 个唯一 point run 闭合**（T01 baseline 30/30 已完成；待 T02 的 KST-Light 10 个剩余条件 run 及 T03 汇总）

#### Task CH3-S05-T01：运行 baseline 的其余 5 个条件

- [x] **Task CH3-S05-T01 完成：5 个 baseline 覆盖 6 个中心/扩展条件，共 30/30 个有效 run**（2026-09-18：复用 CH3-S04 `point_mixed_030` 的 5 个 baseline，新增 random 0/30/70、low-rate 30、block-offline 30 各 25 个 run；下载归档审计确认 30/30 manifest/artifact SHA、history、condition axis 和 target schema 全通过。新 run 使用 commit `2b47c07`；旧 mixed run 保留原始 fingerprint 并在 evidence index 中区分。ODE-RNN mixed_030 标记为 numerically finite but stability-risk / heavy-tail pathology；不阻塞 T02，需在 T03 暴露 instability flag）

**验收：** baseline 30/30 全部完成，且 manifest/artifact SHA、history 有限性、mask/realized-rate 条件轴、target schema 与模型 identity 检查通过；允许调度本文模型剩余条件。✅

- [x] **Task CH3-S05-T02 完成：KST-Light 两个 head 覆盖剩余 5 个条件，共新增 10/10 个有效 run**（AutoDL commit `7af9d58`；`kst_light|linear` 与 `kst_light|mlp` 各完成 random 0/30/70、low-rate 30、block-offline 30；加上 CH3-S04 `mixed_030` 复用结果，KST-Light 累计 12/12，point 总计 42/42；dry-run `verified_complete=42, expected_new=0`，无失败）

- [x] gate 核对 30/30 baseline 完整且共享协议；预期 `2 heads * 5 remaining conditions = 10` 个新 run。（baseline legacy fingerprint 通过受限 allowlist 验签；25/25 新条件 baseline verified）
- [x] 依次运行 Linear 和 MLP，各自覆盖 random 0/30/70、low-rate 30、block-offline 30；mixed 30 复用 CH3-S04。（10/10 新 run 完成）
- [x] 所有条件保持同 encoder、训练预算、checkpoint selector 和 evaluator；ODE-RNN 等 baseline 的稳定性风险只作为诊断标签传递，不因单种子异常事后改配方或重写 baseline 结果。
- [x] validator 检查 ours 累计 `12/12`、point 总计 `42/42`、duplicate/orphan/missing 均为 0。（full point dry-run：`canonical_total=42, verified_complete=42, expected_new=0`）
- [x] 核对 random 30 在 intensity/mechanism 两个视图指向同一 scientific key 和 run artifact。

**验收：** 42 个点预测单种子 run 全部可追溯，才能生成第三章 pilot 汇总。✅ T02 完成；进入 T03 前须先完成 42-run 汇总输入审计。

#### Task CH3-S05-T03：生成第三章单种子汇总

**Files：**
- 修改：`code/build_pilot_outputs.py`
- 创建：`code/tests/pilot/test_metropt_point_outputs.py`
- 输出：`result/pilot/metropt3/summary/point_intensity.csv`
- 输出：`result/pilot/metropt3/summary/point_mechanism.csv`
- 输出：`result/pilot/metropt3/summary/point_efficiency.csv`

- [ ] 强度表只含 random 0/30/70；机制表只含实际 30% 的四机制。
- [ ] 输出原始单种子指标、相对 0% 退化率、逐通道指标和 provenance；不生成标准差或显著性；同时对每个 run 输出 `instability_flag`、`best_epoch`、`max_residual_or_prediction`、`valid_spike`/late-degradation，并将 ODE-RNN mixed_030 标记为 `numerically finite but stability-risk / heavy-tail pathology`。
- [ ] 效率表只读取同一 AutoDL GPU、FP32、相同 batch 与固定 warm-up/repeats 的 profile。
- [ ] 输出测试断言 42 个 source keys 全部被消费，random 30 不重复训练，所有数字可从 prediction 重算；point track 的 `predictions.nsamples=null` 视为合法，只有 probabilistic track 要求 `predictions.nsamples == manifest.nsamples`。
- [ ] 将结论限制为“是否值得进入多 seed formal”及“下一步应修复哪里”。

**验收：** 第三章单种子阶段闭合，但仍不能替代研究生论文最终多 seed 证据。

---

### CH4-S06：第四章概率预测与风险单种子实验

- [ ] **Phase CH4-S06 完成：6 个概率 baseline 先完成，随后 KST ProbFlow 与 validation-only 风险校准完成**

#### Task CH4-S06-T01：运行 6 个概率 baseline

- [ ] dry-run 筛选 `track=probabilistic,family=baseline,condition_id=prob_mixed_030`；预期 `expected=6,new=6`。
- [ ] 在与第三章相同的 MetroPT split、center mask、target、seed 和 AutoDL 硬件上运行六个 baseline。
- [ ] checkpoint 只由 validation CRPS 选择；NLL、sample、CRPS 和 interval 必须来自同一训练分布。
- [ ] 每个模型保存 `nsamples=100` 的可复算预测 artifact、95% interval、timing raw repeats 和参数量。
- [ ] validator 检查 `completed=6, nonfinite=0, fairness_mismatch=0, test_count_error=0`。

**验收：** 6/6 baseline 完成前，runner 拒绝 KST ProbFlow。

#### Task CH4-S06-T02：运行 KST ProbFlow

- [ ] gate 核对六个 baseline manifest、checkpoint 和所有公平性 SHA。
- [ ] 使用完全相同的 mixed actual 30% condition、seed、窗口、context、训练预算和 evaluator。
- [ ] 不根据 baseline test 排名修改 KST 超参数；本轮只运行 tracked 默认配置。
- [ ] checkpoint 只由 validation CRPS 选择，冻结后 test 完整评估一次。
- [ ] validator 检查 NLL/sample/CRPS/interval 同源，且 `completed=1, nonfinite=0, test_count_error=0`。

**验收：** 概率预测 7/7 source run 齐全且无额外数据或 test 访问优势。

#### Task CH4-S06-T03：执行 validation-only 风险校准诊断

**Files：**
- 修改：`code/evaluate_risk_calibration.py`
- 创建：`code/tests/pilot/test_metropt_risk_calibration.py`
- 输出：`result/pilot/metropt3/summary/risk_calibration.json`

- [ ] 风险标签只由 query timestamp 与登记 fault interval 的交集生成；label artifact 与概率 run 使用同一 window ID。
- [ ] Platt calibration 只拟合 validation logits/labels；阈值只由 validation 确定，禁止搜索 test label。
- [ ] test 只复用冻结 run 保存的 logits/predictions，不重新选择 checkpoint 或再次遍历带 target loader。
- [ ] 输出 AUROC、AUPRC、Brier、ECE，以及 validation 阈值下的 precision/recall/F1；任一 split 单类时对应排序指标为 `null`。
- [ ] 单种子风险结果只作模块可用性诊断，不与没有同构 risk head 的概率 baseline 做不公平排名。

**验收：** calibration provenance 明确显示 fit split 为 validation，test 从未参与参数或阈值选择。

#### Task CH4-S06-T04：生成第四章单种子汇总

**Files：**
- 修改：`code/build_pilot_outputs.py`
- 创建：`code/tests/pilot/test_metropt_probabilistic_outputs.py`
- 输出：`result/pilot/metropt3/summary/probabilistic_main.csv`

- [ ] 输出 7 行 MAE、RMSE、NLL、CRPS、PICP、MPIW、valid count、训练时间、推理时间和参数量。
- [ ] PICP 与 MPIW 联合展示；PICP 接近 0.95 但 MPIW 极宽不能表述为最佳。
- [ ] 每行包含 scientific key、checkpoint SHA、matrix SHA、protocol SHA、distribution identity 和 evaluator SHA。
- [ ] 从 prediction artifact 重算全部 7 行指标；预期 `rows=7, untraced=0, nonfinite=0`。
- [ ] 单种子不生成 mean±std、置信区间、显著性标记或最终论文排名措辞。

**验收：** 第四章概率主表和风险诊断均可复算，且二者的评价边界没有混淆。

---

### CH34-S07：单种子总复核与后续决策

- [ ] **Phase CH34-S07 完成：49 个 MetroPT-3 source run 通过完整性复核，并形成多 seed 前的 keep/fix/drop 决策**

#### Task CH34-S07-T01：执行全局 coverage、泄漏与可移植性复核

- [ ] 检查 point 42 行、probabilistic 7 行、总计 49 个唯一 source run；duplicate/orphan/missing 为 0。
- [ ] 检查 49 个 run 均来自同一 clean commit 和同一 AutoDL 硬件；本机 smoke/sanity 不进入 coverage。
- [ ] 检查 direct comparison 内 split、segment、normalization、condition mask、target、context 和 evaluator SHA 一致。
- [ ] 抽取一个 point run 和一个 probabilistic run，从 prediction artifact 重算全部指标。
- [ ] 扫描新增 Python/YAML/Markdown/manifest；预期无机器绝对路径、账号、主机、IP、端口或固定 URL。
- [ ] 运行 `python -m pytest code/tests/ -q` 与 `git diff --check`；预期零失败。

**验收：** 任一 coverage、泄漏、公平性、可复算或可移植性错误都会使对应 Phase 保持未勾选。

#### Task CH34-S07-T02：形成 validation-driven keep/fix/drop 决策

- [ ] `keep`：接口、fidelity、学习性、稳定性和公平性通过，可进入后续多 seed formal。
- [ ] `fix`：存在明确的数据、优化或概率校准问题；修复只依据 train/validation 证据，使用新 scientific key 重跑。
- [ ] `drop`：实现 fidelity 不足或数值不可用；不得仅因 test 结果差而删除合格 baseline。
- [ ] 分别判断表示编码、Linear/MLP head、概率 head、风险校准和效率瓶颈，不用一个综合分数掩盖问题。
- [ ] 将决策写入 `plan/progress.md`，但不自动启动调参、消融、多 seed 或其他数据集实验。

**验收：** 下一步由验证集和工程证据驱动，不由单次 test 排名反向塑造算法。

### 13.3 单种子运行总量与顺序

| 顺序 | 运行范围 | 完整训练数 | 执行位置 |
|---:|---|---:|---|
| 1 | LI+TCN `mixed@0.30` validation-only sanity | 1 个非报告短训练 | AutoDL |
| 2 | 第三章 5 baseline `mixed@0.30` | 5 | AutoDL |
| 3 | KST-Light Linear/MLP `mixed@0.30` | 2 | AutoDL |
| 4 | 第三章 5 baseline 其余 5 条件 | 25 | AutoDL |
| 5 | KST-Light 两个 head 其余 5 条件 | 10 | AutoDL |
| 6 | 第四章 6 概率 baseline `mixed@0.30` | 6 | AutoDL |
| 7 | KST ProbFlow `mixed@0.30` | 1 | AutoDL |
| 合计 | 第三章 42 + 第四章 7 | 49 个唯一完整 pilot run | AutoDL |

### 13.4 本轮明确不做

- 不继续补跑 FD004 的 47 个剩余 run。
- 不把 FD001 直接替换成论文主数据集。
- 不做多 seed、显著性检验、完整消融、广泛鲁棒性、模型特异超参数搜索或算法创新。
- 不使用 test 选择窗口、通道、context、学习率、checkpoint、缺失机制或风险阈值。
- 不把本机 smoke、AutoDL sanity 或任一单种子结果写成第三、四章最终结论。

### 13.5 后续正式实验边界

第 13 节只负责“数据协议正确、代码跑通、单种子可学习、比较链路公平”。只有 CH34-S07 全部通过后，才另行规划 seeds `2026/2027/2028` 的 formal 重复、bootstrap/置信区间、外部数据集、消融与鲁棒性。正式计划必须复用本节冻结的科学协议，任何协议变更都要生成新版本和新 SHA，不能与本轮 49 个 pilot run 混合。

### CH34-S08：A1 GRU-conditioned Mixer G1-G4

- [x] 新增 `gru_mixer` cross-variable block，保持 mask-safe A1 主分支和 decoder 接口。
- [x] 增加 G1-G4 独立 matrix、variant identity、manifest recipe 字段和参数统计。
- [x] 先通过定向组件/身份测试，再运行完整 `code/tests/`。
- [x] 用 validation MAE 选择 G1/G2 的 hidden size；G1/G2/G3/G4 均未通过 A1 validation 门槛，不进入主模型。
- [x] 记录参数量、validation/test 指标、训练/推理时间和 checkpoint；结果仍标记为单种子 pilot。

### CH34-S09：直接替换 FLA 的 Missingness-Aware Sensor-Token Mixer

- [x] 新增 `missing_sensor_mixer`，保持 mask-safe encoder、query adapter、residual decoder 和 last-value anchor 不变。
- [x] 增加 pre-norm Q/K/V、available source mask、freshness log-age bias、learnable sensor-pair relation bias、gated residual 和 all-missing identity fallback。
- [x] 接入 `CrossVariableConfig`、`KSTLightV2Config`、registry、`PilotRunSpec`、manifest/recipe identity 和 `run_scheme_b_matrix.py`。
- [x] 创建 M1-M4 独立 MetroPT-3 point matrices，未复用或覆盖 A1/F1-F3/G1-G4 key。
- [x] 定向测试 `20 passed`；完整回归 `380 passed, 6 failed`，失败均为缺失 TEP 原始文件。
- [x] 完成 M1-M4 50-epoch CUDA pilot；按 validation MAE 选择 M2，M1/M3/M4 淘汰。四个结果仍标记为单种子 pilot，不能外推多 seed 结论。
- [ ] 在 M2 上执行独立 seeds `2027/2028` 或正式多种子实验；在此之前不得把 M2 写成最终论文主结论。
