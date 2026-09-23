## 文献综述段落蓝图

### 一、引言

- Role: 交代工业异步多传感器状态预测的研究背景、任务边界和文献综述目的。
- Main claim: 工业预测性维护已经从单一故障后诊断转向多传感器状态预测、概率不确定性表达和风险评估，但真实场景的异步缺失观测使传统规则序列建模面临边界。
- Evidence IDs: C01-C10, F01-F05.
- Contrast or transition: 从工业需求过渡到国内外研究现状的四条技术链。
- Forbidden content: 不写成开题报告研究意义的重复，不直接复制用户要求。

### 二、国内外研究现状 P1-P3：工业预测与PHM

- Role: 综合国内机械工程、工业诊断、RUL 与国外 PHM 综述和不确定性研究。
- Main claim: 国内研究重视装备退化机理、多源信息融合和工程诊断可解释性，国外研究更强调 PHM 体系、深度健康监测和不确定性决策，两者共同指向多源状态预测和可信风险评估。
- Evidence IDs: C01-C30, F01-F05.
- Contrast or transition: 从工业任务转入通用时序预测基线。
- Forbidden content: 不逐条罗列每篇 RUL 模型。

### 二、国内外研究现状 P4-P5：规则采样时序预测

- Role: 梳理 PatchTST、TimesNet、iTransformer、FEDformer、DLinear 等规则采样预测方法。
- Main claim: 规则采样模型为工业多变量预测提供强基线，但其同步、完整、等间隔输入假设难以覆盖工业异步观测。
- Evidence IDs: F06-F10.
- Contrast or transition: 引出缺失感知、连续时间和图结构不规则建模。
- Forbidden content: 不把通用基线直接说成适用于全部工业异步场景。

### 二、国内外研究现状 P6-P8：异步缺失与规整表示

- Role: 讨论 GRU-D、BRITS、SAITS、Neural ODE、Latent ODE、mTAN、NCDSSM、RAINDROP、GraFITi、Temporal Graph ODEs、KAFNet、ProFITi。
- Main claim: 相关研究已从插补恢复走向事件结构、连续时间和图结构建模，但在工业多传感器联合概率输出和风险评估衔接上仍不充分。
- Evidence IDs: F11-F22.
- Contrast or transition: 从表示学习转向联合概率预测。
- Forbidden content: 不把插补类方法描述成完全错误，只限定其适用边界。

### 二、国内外研究现状 P9-P11：联合概率预测、校准与风险

- Role: 综合 DeepAR、normalizing flow、TACTiS、严格适当评分规则、一致性预测、神经网络校准和异常检测。
- Main claim: 概率预测能够提供区间和分布质量评价，异常检测能够提供风险识别参考，但未来状态分布到工业风险概率之间仍需要单独建模和校准。
- Evidence IDs: F23-F33.
- Contrast or transition: 引出公开数据集和统一实验协议。
- Forbidden content: 不将异常检测分数直接等同于概率风险。

### 二、国内外研究现状 P12：数据集与评价协议

- Role: 说明 C-MAPSS、MetroPT-3、TEP 与统一缺失、划分、风险标签和评价指标的必要性。
- Main claim: 多数据集能覆盖航空发动机、空气压缩机和过程工业，但采样频率、故障标签和风险尺度不同，必须统一协议并分别解释风险含义。
- Evidence IDs: F34-F37.
- Contrast or transition: 进入结论。
- Forbidden content: 不把不同数据集结果解释为同一风险尺度的绝对比较。

### 三、结论

- Role: 提炼已有研究贡献、不足和本论文切入点。
- Main claim: 现有研究在工业预测、异步建模和概率预测上各有积累，但统一规整表示、联合概率预测和校准风险评估仍存在可研究空间。
- Evidence IDs: 全部主题组。
- Contrast or transition: 进入拟研究内容。
- Forbidden content: 不写成空泛创新点。

### 四、拟研究内容

- Role: 将文献空白转化为论文拟研究内容。
- Main claim: 本文拟围绕异步事件化数据协议、工况感知规整表示、KAFNet-ProFITi 联合概率预测和风险校准评估开展研究。
- Evidence IDs: C01-C10, F16-F22, F23-F37.
- Contrast or transition: 进入参考文献。
- Forbidden content: 不写实验结果，不承诺尚未完成的性能提升。
