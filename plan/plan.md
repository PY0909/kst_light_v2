# kst_light_v2 主工程迁移与第三、四章对比实验建设规划

> **供后续智能体执行：** 必须逐 Phase、逐 Task 执行。所有状态均使用 checkbox（`- [ ]` / `- [x]`）追踪，完成一项立即写回本文件，不批量补记。

本规划以 kst_light_v2 仓库根为唯一主工程（下文仓库内路径均为相对路径），把旧工程 `new_work` 中可复用的源码与原始数据迁移进来，并在统一协议、统一 evaluator、统一环境下重新产生全部正式对比结果。正式结果一律不允许从旧工程搬运。

> **计划版本说明（2026-09-24）：** 本文件前面的 V2-P00～V2-X0 条目保留为已执行工作的审计记录；文末新增的 **“V2-ROADMAP-2026-09-24（权威后续路线）”** 覆盖旧的未完成后续阶段。后续执行只按该权威路线推进，旧条目不得与新路线混合勾选。每个新 Task 完成后立即在权威路线中更新 checkbox，并记录命令、run_id、commit 与产物路径。

---

## 1. 总体结论

`kst_light_v2` 已具备"修复后的主模型、pilot runner、部分配置矩阵和六个单模型 pilot 结果"，但尚未达到可启动正式对比实验的状态。主要阻塞项：

1. v2 没有 Git 仓库与 GitHub 远端绑定，无法冻结代码身份。
2. v2 缺少 `compare_code/`（概率基线工厂与代码指纹的组成部分）和 MetroPT 原始数据。
3. 既有六个 `kst_light_v2` 结果是模型选择/pilot 证据，不是公平对比结果。
4. 结果目录同时存在 `results/runs/` 与代码默认的 `results/pilot/<dataset>/runs/` 两种结构，且 [pilot_runner.py](../code/kaf_profiti/experiments/pilot_runner.py) 的 `pilot_root` 默认值为 `pilot/fd004`，MetroPT 实验若不显式传参会落错目录。
5. `configs/ch3/` 下三个 YAML 仍使用旧模型 ID `kst_light`，不能作为 `kst_light_v2` 的正式对比矩阵。

因此先执行 V2-P00～V2-P03 的迁移、冻结与接线验证（含 V2-X0 外部数据集单 seed 接线 pilot，插在 V2-P00 与 V2-P01 之间执行），再按 V2-P04～V2-P09 依次产生正式结果。任一 Phase 的完成门禁未通过，禁止进入下一 Phase。

## 2. 当前工程状态与已核实资产

以下事实已于 2026-09-24 核实：

| 项目 | 状态 | 位置 |
|---|---|---|
| Git 仓库 | 不存在（`.git` 缺失，无 `.gitignore`） | 仓库根 |
| 主模型代码 | 存在，`kaf_profiti` 包 | `code/kaf_profiti/` |
| 实验入口 | 存在 | `code/run_experiment.py`、`code/run_pilot_matrix.py`、`code/run_scheme_b_matrix.py` |
| pilot runner | 存在，`pilot_root` 默认 `pilot/fd004` | `code/kaf_profiti/experiments/pilot_runner.py` |
| 模型注册 | `kafnet`、`kafnet_gaussian`、`kaf_profiti_marginal`、`mtan`、`tpatchgnn`、`grafiti` 等为 `not_implemented` | `code/kaf_profiti/experiments/registry.py` |
| 点预测配置 | `configs/ch3/metropt_main.yaml` 仍为 `model: kst_light`（旧模型） | `configs/ch3/` |
| 外部数据集配置 | `fd004_external.yaml`、`tep_external.yaml` 均仍为 `model: kst_light` | `configs/ch3/` |
| 概率矩阵 | 存在，含 6 个概率 baseline + `kst_probflow` | `configs/pilot/metropt3/probabilistic_matrix.yaml` |
| 既有结果 | 六个 `kst_light_v2` 条件 run（random@0.00/0.30/0.70、low_rate@0.30、block_offline@0.30、mixed@0.30） | `results/runs/` |
| 环境定义 | Conda：`environment.yml`（env 名 `kst_probflow`，python 3.12，pytorch 2.5.1）；另有 `requirement.txt` | 仓库根 |
| 测试 | 存在 `code/tests/`（含 `ch3/`、`pilot/` 子目录） | `code/tests/` |
| 缓存残留 | 多处 `__pycache__/*.pyc`（py39/310/311 混杂）、`.DS_Store`、`code/code.zip` | `code/`、`plan/`、`docs/` 等 |

### 迁移源（仅此表允许出现仓库外路径）

| 源路径（new_work 内） | 用途 | 去向 |
|---|---|---|
| `compare_code/TCN-Gaussian/`、`compare_code/probabilistic_baselines/` | 概率与点预测基线源码 | `compare_code/` |
| `dataset/metropt+3+dataset/MetroPT3(AirCompressor).csv`（208 MB） | MetroPT-3 原始数据 | `dataset/metropt+3+dataset/` |
| `dataset/metropt+3+dataset/Data Description_Metro.pdf` | 数据说明（不参与训练） | 同上，可选 |
| `dataset/CMAPSSData/`（43 MB） | C-MAPSS FD001–FD004 原始数据（FD004 外部验证与测试依赖） | `dataset/CMAPSSData/` |
| `dataset/dataverse_files/`（1.3 GB，四份 RData） | TEP fault-free + faulty 原始数据（TEP 外部验证与测试依赖） | `dataset/dataverse_files/` |
| `ProFITi-main/`、`KAFNet-main/` | 第三方上游参考（不进 import 路径） | `vendor/` |

## 3. 当前实验状态与结论权限

| 结果组 | 位置 | 内容 | 结论权限 |
|---|---|---|---|
| H2 六条件 pilot | `results/runs/` | `kst_light_v2` 单模型 × 六缺失条件，配方 `m2_tune_lr3e4_cosine_ep80` | 仅模型选择证据：判断可学习性、缺失机制敏感性、耗时与配方；不得进入正式对比表，不得与 baseline 混合统计 |
| 旧工程 baseline 结果 | 未迁移 | `new_work` 的 `li_tcn`、`GRU-D`、`ODE-RNN` 等 | 不得进入 v2 任何正式表格 |
| 旧 venv 产物 | 未迁移 | 旧虚拟环境生成的结果 | 标记 `legacy_venv_artifact`，不得与 Conda 结果合并 |

复制 `compare_code/` 后代码指纹将改变，既有 v2 manifest 可能不再满足 resume 身份要求；正式比较一律重新运行。

## 4. 必须先解决的缺口

| 问题 | 影响 | 解决阶段 |
|---|---|---|
| 无 Git 仓库与 `.gitignore` | 无法冻结代码身份；208 MB CSV 超 GitHub 100 MB 单文件限制，直接 init 有污染风险 | V2-P00 |
| 缺 `compare_code/` | 概率基线无法运行；代码指纹与实验身份不完整 | V2-P00 |
| 缺 MetroPT 原始数据与 v2 版 `data_gate.json` | 无法训练；`raw_data_sha256` 不能沿用旧值 | V2-P00 |
| `__pycache__`、`.DS_Store`、`code.zip` 残留 | 仓库噪声；跨 Python 版本 `.pyc` 混杂 | V2-P00 |
| `pilot_root` 默认 `pilot/fd004` | MetroPT 结果可能写入错误目录且不易察觉 | V2-P00 |
| 结果目录双结构（`results/runs/` vs `results/pilot/<dataset>/runs/`） | 两类结果格式不能混合统计 | V2-P00～P01 |
| `configs/ch3/*.yaml` 仍为 `model: kst_light` | registry 中 `kst_light` 与 `kst_light_v2` 并存，旧 ID 会被静默接受跑错模型而不报错 | V2-X0（external 两个）/ V2-P01（metropt_main） |
| `run_experiment.py` 硬编码 AutoDL 默认路径（portability allowlist 4 条豁免） | 绕过 `KST_*` 环境变量契约，本机误跑会写错位置 | V2-X0 |
| TEP 协议仅加载 fault-free（`_create_tep`），风险标签全负类 | 不具备正式外部验证资格 | V2-X0 明确边界，V2-P06 集成 faulty |
| 六个 H2 结果未归档、聚合脚本可扫描到 | pilot 结果可能误入正式表格 | V2-P01 |
| registry 中 KAFNet 系列为 `not_implemented` | 不能在论文中标记为已完成对比模型 | V2-P07 前置适配 |
| 外部验证（FD004/TEP）无独立阶段与门禁 | 赶工时易降低公平性标准（如 TEP 用 fault-free 顶替 faulty） | V2-P06 |
| 旧 venv 环境产物 | 环境身份混乱，结果不可合并 | V2-P02 |

## 5. 本轮固定科学合同

**数据与窗口（MetroPT-3 主验证）：**

```
dataset    = metropt3_chrono_502030_v2
history_len = 168
pred_len    = 24
stride      = 60
```

**外部验证（见 V2-P06，窗口参数以 `configs/ch3/` 修正后的 YAML 为准）：**

```
FD004: dataset=cmapss_fd004, history_len=50,  pred_len=10, stride=1,  按 engine 划分
TEP:   dataset=tep,           history_len=96,  pred_len=24, stride=12, 按 simulation run 划分；必须有 faulty 数据，禁止 fault-free fallback
```

**种子：**

```
单种子阶段: seed = 2026
恒定:       split_seed = 2026, mask_seed = 2026
多种子阶段: seed ∈ {2026, 2027, 2028}
```

**缺失条件（MetroPT-3）：**

```
random@0.00   random@0.30   random@0.70
low_rate@0.30 block_offline@0.30   mixed@0.30（中心条件）
```

**第三章点预测矩阵（6 模型 × 6 条件 = 36 单种子 run）：**

```
li_tcn  ff_gru  masked_tcn  gru_d  ode_rnn  kst_light_v2
```

**第四章概率矩阵（`configs/pilot/metropt3/probabilistic_matrix.yaml`，单条件 mixed@0.30）：**

```
tcn_gaussian  patchtst_gaussian  gru_d_gaussian  ode_rnn_gaussian  grafiti_gaussian  profiti  kst_probflow
```

其中 `grafiti_gaussian` 为适配实现、`profiti` 为 adapted_profiti、`kst_probflow` 为本文概率主模型；KAFNet 系列（`kafnet`、`kafnet_gaussian`、`kaf_profiti_marginal`）在完成适配前不得列为已完成对比模型。

**统一训练配方：** 矩阵 YAML 必须显式记录 `epochs / batch_size / learning_rate / weight_decay / scheduler / grad_clip_norm / selection_metric`，所有模型一致；第三章以 validation MAE 选 checkpoint，第四章只以 validation CRPS 或 validation NLL 选 checkpoint。禁止任何形式的 test 集选择（模型、阈值、超参数、calibrator）。

**指标：**

```
第三章: MAE、RMSE、训练时间、推理时间、参数量
第四章: MAE、RMSE、NLL、CRPS、PICP、MPIW、训练时间、推理时间、参数量
风险:   AUROC、AUPRC、Brier、ECE、Precision、Recall、F1（test 单一类别时输出 null，不填 0）
```

**路径与环境：** 运行时路径只从环境变量解析，配置与代码禁止出现机器绝对路径：

```
KST_PROJECT_ROOT  = kst_light_v2 仓库根
KST_DATA_ROOT     = kst_light_v2/dataset
KST_RESULT_ROOT   = kst_light_v2/results
```

**证据级别：** 每次 run 的 evidence status 只允许 `interface_only / smoke_passed / full_completed / formal_validated`；只有 `formal_validated` 可进入论文表图。

**Git 冻结点（tag）：**

```
v0.1-freeze           V2-P00 完成后
v0.2-ch3-single-seed  V2-P05 完成后
v0.3-ch4-single-seed  V2-P08 完成后
v1.0-paper-freeze     V2-P09 完成后
```

## 6. Phase 总览

| Phase | 代码任务 | 实验任务 | 完成门禁 |
|---|---|---|---|
| **V2-P00 工程迁移与 Git 冻结** | `.gitignore`、缓存清理、`compare_code/`、数据迁移、pilot_root 修复、data gate | 不跑正式训练 | clean commit + tag `v0.1-freeze` + push GitHub；`git status --porcelain` 为空 |
| **V2-X0 外部数据集接线 pilot** | `run_experiment.py` 路径治理；external 配置模型 ID 修正；AutoDL 最小预检 | FD004/TEP 各 1 次 `kst_light_v2` 单 seed（TEP 允许 sanity 降级） | 全量测试无回归；结果仅作接线/可学习性证据，`formal_comparison_eligible: false` |
| **V2-P01 公平点预测矩阵** | 修正 `configs/ch3/metropt_main.yaml` 模型 ID；新建 6×6 矩阵；归档 H2 结果 | 不跑训练 | 矩阵含 6 模型与统一配方字段；聚合扫描不到归档结果 |
| **V2-P02 本机 Conda 接线验证** | 依赖确认、测试修复 | 全量 pytest、dry-run、CPU smoke、一致性检查 | 全部测试通过；六模型 split/normalization/mask 一致 |
| **V2-P03 AutoDL 环境预检** | 远端 checkout、环境核对 | 无训练；SHA 跨机比对 | 远端 SHA 与本机一致；dry-run 通过（可与 P04 合并在有卡实例执行） |
| **V2-P04 中心条件单种子** | GPU preflight、CUDA smoke | mixed@0.30 × 6 模型 = 6 runs | `completed=6、nonfinite=0、fairness_mismatch=0、test_count_error=0`，三类 SHA 一致 |
| **V2-P05 第三章六条件单种子** | 结果下载与聚合 | 其余 5 条件 × 6 模型 = 30 runs | 36 runs 全部 `formal_validated`；tag `v0.2-ch3-single-seed` |
| **V2-P06 外部数据集单种子** | FD004/TEP 配置 v2 化、TEP faulty 门禁 | 2 数据集 × 4 代表模型 = 8 runs | TEP 无 faulty 数据则显式 skip，不得用 fault-free 顶替 |
| **V2-P07 第四章概率单种子** | KAFNet 适配（如论文需要）；概率矩阵 smoke | 6 baseline + `kst_probflow` = 7 runs | NLL/CRPS/区间指标来自同一概率头；checkpoint 由 validation 选出 |
| **V2-P08 风险校准** | calibration 模块接线 | validation-only Platt/isotonic + 一次 test 评估 | 校准参数、阈值、数据范围与 run_id 可追溯；无 test 泄漏 |
| **V2-P09 多种子正式实验与冻结** | 统计汇总、表图重建 | 3 seeds 全矩阵；只汇总已冻结结果 | 表图一键重建；每个正文数字可追溯到 run、seed、checkpoint、代码版本；tag `v1.0-paper-freeze` |

## 7. 执行与勾选规则

1. Phase 必须按 `V2-P00 → V2-P09` 顺序执行；前一 Phase 完成门禁未通过，禁止启动后一 Phase。
2. 每完成一个 checkbox step，执行智能体立即在本文件把 `- [ ]` 改为 `- [x]`；Task 完成框只有验证命令通过、产物存在且验收条件满足后才能勾选。
3. Phase 完成框只有该 Phase 全部必做 Task 均为 `[x]` 时才能勾选。
4. 仓库内部链接与文件引用一律使用相对路径；代码、配置、测试和脚本不得写死机器路径、账号、主机、IP 或端口，运行时路径优先级固定为 `CLI > environment > config > repository-relative default`。
5. `results/` 与 `dataset/` 不进入 Git；`result` 原始 metrics、mask、prediction、checkpoint 只允许程序生成，不得手工改数值。
6. smoke、tuning、formal 必须分别标记；任何限 batch、1 epoch 或调试结果不得进入正式输出。
7. 本计划不预填实验结果；结论只能消费 `formal_validated` artifact。
8. 每次只修改当前 Task 声明的文件；工作区其他未跟踪文件视为用户资产，不得还原或覆盖。
9. 正式 run 的 manifest 必须齐备：Git SHA、dirty flag、`raw_data_sha256`、split/mask/protocol/evaluator SHA、`code_fingerprint`、`matrix_sha`、`recipe_version`、环境版本、硬件、命令与 checkpoint。

## 8. 计划文件与代码边界

| 路径 | 职责 |
|---|---|
| `plan/plan.md` | 本规划（唯一执行真源，checkbox 状态写回此处） |
| `.gitignore` | 屏蔽数据、结果、缓存与压缩包 |
| `configs/ch3/*.yaml` | 点预测与外部验证矩阵（可移植参数，无机器路径） |
| `configs/pilot/metropt3/probabilistic_matrix.yaml` | 第四章概率矩阵 |
| `code/kaf_profiti/experiments/registry.py` | 模型注册与 `not_implemented` 状态治理 |
| `code/kaf_profiti/experiments/pilot_runner.py` | 训练评估 runner（含 pilot_root 修复） |
| `compare_code/` | 迁移后的基线源码（参与代码指纹） |
| `dataset/` | 原始数据（gitignore，只登记 SHA） |
| `results/` | 全部 run 产物（gitignore，只登记 SHA 与 run_id） |
| `archive/` | H2 pilot 与旧工程遗留证据（`formal_comparison_eligible: false`） |

---

## 9. 分阶段任务明细

### V2-P00：工程迁移与 Git 冻结

- [x] **Phase V2-P00 完成：v2 成为可复现、可推送的干净仓库，身份链齐备**

#### Task V2-P00-T01：创建 .gitignore 并清理缓存产物

- [x] **Task V2-P00-T01 完成：ignore 规则生效，缓存零残留**

**文件：**
- 创建：`.gitignore`
- 删除：全部 `__pycache__/`、`*.pyc`、`.DS_Store`、`.pytest_cache/`、`code/code.zip`

- [x] 写入并验证以下忽略规则（关键项：`dataset/`、`results/`、`archive/`——MetroPT CSV 208 MB，超 GitHub 100 MB 单文件限制，严禁入库）：

```gitignore
dataset/
results/
archive/
vendor/
__pycache__/
*.pyc
.DS_Store
.pytest_cache/
*.zip
```

- [x] 执行清理：`find . -name '__pycache__' -type d -not -path './.git/*' -exec rm -rf {} +`、`find . -name '.DS_Store' -not -path './.git/*' -delete`、`rm -f code/code.zip`。
- [x] 验证：`find . \( -name '__pycache__' -o -name '.DS_Store' \) -not -path './.git/*' | wc -l` 输出 `0`。

**验收：** ignore 规则生效（`git check-ignore dataset/ results/` 返回命中）；清理后无缓存残留。

#### Task V2-P00-T02：迁移 compare_code

- [x] **Task V2-P00-T02 完成：compare_code 可导入且参与代码指纹**

**文件：**
- 创建：`compare_code/TCN-Gaussian/`
- 创建：`compare_code/probabilistic_baselines/`

- [x] 从迁移源 `new_work/compare_code/` 复制两个目录到 `compare_code/`，排除 `.DS_Store`、`__pycache__/`、`.pytest_cache/`、`*.pyc`。
- [x] 验证目录形态：`ls compare_code/` 输出 `TCN-Gaussian  probabilistic_baselines`。
- [x] 验证可导入：在 Conda 环境中 `python -c "import sys; sys.path.insert(0, 'compare_code'); import probabilistic_baselines"` 无异常（具体导入路径以 `code/kaf_profiti/experiments/` 中基线工厂的实现为准）。

**验收：** `compare_code/` 齐备且无缓存文件；概率基线工厂可解析到该目录。

#### Task V2-P00-T03：迁移 MetroPT 原始数据并重生成 data gate

- [x] **Task V2-P00-T03 完成：数据 SHA 已登记，v2 data_gate.json 重新生成**

**文件：**
- 创建：`dataset/metropt+3+dataset/MetroPT3(AirCompressor).csv`
- 重新生成：v2 版 `data_gate.json`（由程序写入 `results/protocol/` 对应位置）

- [x] 复制 CSV（208 MB）到 `dataset/metropt+3+dataset/`；`Data Description_Metro.pdf` 可选保留。
- [x] 重新计算并登记 `raw_data_sha256` 与 `raw_data_bytes`；不得沿用旧工程 `data_gate.json` 的任何字段。
- [x] 由程序重新生成 v2 `data_gate.json`，记录新工程路径、代码指纹与结果根目录。
- [x] 验证：`shasum -a 256 "dataset/metropt+3+dataset/MetroPT3(AirCompressor).csv"` 与 data_gate 登记值一致。

**验收：** 数据在位、SHA 一致、data_gate 为 v2 现算值。

#### Task V2-P00-T04：归档第三方上游参考

- [x] **Task V2-P00-T04 完成：vendor 目录归档且不进入 import 路径**

**文件：**
- 创建：`vendor/ProFITi-main/`
- 创建：`vendor/KAFNet-main/`

- [x] 从迁移源复制 `ProFITi-main/`、`KAFNet-main/` 到 `vendor/`（已被 gitignore，仅本机归档）。
- [x] 确认 `vendor/` 不加入任何 Python import 路径、不被任何配置引用为模型来源。
- [x] 在 `plan/progress.md` 登记"原始实现 / 改写实现 / 适配实现"三类的边界说明。

**验收：** vendor 仅作来源保存与一致性核查用途；registry 中 `kafnet` 系列仍为 `not_implemented`，未被虚假启用。

#### Task V2-P00-T05：统一结果根目录并修复 pilot_root 隐患

- [x] **Task V2-P00-T05 完成：pilot_root 显式传参 + 启动断言生效**

**文件：**
- 修改：`code/kaf_profiti/experiments/pilot_runner.py`
- 创建：`code/tests/pilot/test_pilot_root_guard.py`（如目录结构不合适则放 `code/tests/`）
- 创建：`.env.example`（记录三个环境变量的本机建议值，实际值不入库）

- [x] 排查 [pilot_runner.py](../code/kaf_profiti/experiments/pilot_runner.py) 中 `pilot_root: str = "pilot/fd004"` 默认值的所有调用点；MetroPT 链路必须显式传 `pilot_root="pilot/metropt3"`。
- [x] 增加启动断言：runner 初始化时校验 `result_root / pilot_root` 与数据集标识一致，不一致立即抛错，禁止静默写入。
- [x] 写失败测试：以默认 `pilot/fd004` 运行 MetroPT 实验必须报错；显式传参后路径解析正确。
- [x] 运行 `PYTHONPATH=code python -m pytest code/tests/pilot/test_pilot_root_guard.py -q`，先失败后通过。
- [x] 确认唯一正式结果根目录为 `$KST_RESULT_ROOT`（即 `results/`），废弃 `result/`（单数）等旧命名。

**验收：** MetroPT 结果只会落入 `results/pilot/metropt3/runs/`；错误 pilot_root 会被断言拦截。

#### Task V2-P00-T06：全量测试、clean commit、tag 与 GitHub 推送

- [x] **Task V2-P00-T06 完成：v0.1-freeze 已推送 GitHub**

**文件：**
- 创建：`.git/`（`git init`）
- 参考：`environment.yml`、`requirement.txt`

- [x] 确认 Conda：`conda env list` 含 `kst_probflow`；`which python` 指向 Conda 而非旧 venv。
- [x] 运行 `PYTHONPATH=code python -m pytest code/tests/ -q`；记录通过/失败数，失败项修复或显式标记 skip 原因（缺外部数据时用 skip marker，不得以 `FileNotFoundError` 充当正常结果）。
- [x] `git init` 并绑定远端：`git remote add origin https://github.com/PY0909/kst_light_v2.git`。
- [x] `git add` 后检查 `git status --porcelain`，确认 `dataset/`、`results/`、`vendor/` 均未被跟踪。
- [x] 创建 clean commit，打 tag `v0.1-freeze`，push 含 tag。
- [x] 验证：`git status --porcelain | wc -l` 输出 `0`；`git tag` 含 `v0.1-freeze`。

**验收：** 仓库干净、远端可达、tag 已推送。此 Phase 完成前不启动任何正式 GPU 训练。

---

### V2-X0：FD004 / TEP 单 seed 接线 pilot（V2-P01 前置）

**Phase 状态（2026-09-25）：** 原 T03～T06（AutoDL 预检、FD004/TEP 全量单 seed pilot、归档与配方反馈）已删除，其职责由权威路线 V2-ROADMAP-2026-09-24 的 C0 节（V2-X0-CLOSE-T01～T03）承担：收尾深度降为单 batch CUDA smoke，全量单 seed 不再是进入 V2-LITE 的前置条件。本段只保留 T01、T02 审计记录，不再设独立 Phase 完成门禁。

**定位与边界：** 本 Phase 不是正式外部验证（那仍是 V2-P06 的职责），而是在投入矩阵建设（V2-P01）之前，先确认 FD004/TEP 两个通道在 v2 冻结环境下端到端可跑、`kst_light_v2` 可学习，并取得训练耗时/资源信号。结论权限与 MetroPT H2 pilot 相同：仅接线与模型选择证据，`formal_comparison_eligible: false`，不得进入论文正式表格。

**已核实的现状（2026-09-24）：** registry 中 `kst_light` 与 `kst_light_v2` 并存（旧 ID 被静默接受）；`configs/ch3/*.yaml` 无代码消费，实际单跑入口是 `code/run_experiment.py` 纯 CLI；该 CLI 硬编码 AutoDL 默认路径且不走 `resolve_runtime_paths`；`_create_tep` 仅加载 fault-free 数据；本机无 CUDA，正式单 seed 需 AutoDL。

#### Task V2-X0-T01：run_experiment.py 路径治理

- [x] **Task V2-X0-T01 完成：入口脚本零硬编码路径，默认解析走 KST_* 契约**

**文件：**
- 修改：`code/run_experiment.py`
- 修改：`code/tests/ch3/test_portability_policy.py`（删除 `code/run_experiment.py` 的 4 条 allowlist 豁免）

- [x] 以 portability 测试为失败测试驱动：先删除 4 条 allowlist 豁免，运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_portability_policy.py -q` 确认转红。
- [x] 将 `--data-root`/`--output-dir` 默认值从机器绝对路径改为 None，经 `resolve_runtime_paths` 解析（`KST_DATA_ROOT`/`KST_RESULT_ROOT` → 仓库相对 `dataset/`、`results/` 默认）。
- [x] 重跑 portability 测试确认转绿；运行 `python code/run_experiment.py --help` 确认可在仓库根正常解析。

**验收：** `code/run_experiment.py` 零机器路径命中；portability 全绿；全量 pytest 无回归。

#### Task V2-X0-T02：external 配置模型身份修正

- [x] **Task V2-X0-T02 完成：external 两个配置指向 kst_light_v2**

**文件：**
- 修改：`configs/ch3/fd004_external.yaml`、`configs/ch3/tep_external.yaml`

- [x] 两个配置 `model: kst_light` → `model: kst_light_v2`（registry 已含该 ID）。
- [x] 验证：`grep -rn "model: kst_light$" configs/ch3/fd004_external.yaml configs/ch3/tep_external.yaml` 无输出。
- [x] `configs/ch3/metropt_main.yaml` 的修正仍归 V2-P01-T01，本 Task 不动。

**验收：** external 配置不再指向旧模型 ID；后续任何人都无法用这两个配置静默跑出旧模型。

---

### V2-P01：建立 v2 公平点预测矩阵

- [ ] **Phase V2-P01 完成：v2 专用 6×6 点预测矩阵就绪，pilot 结果已隔离**

#### Task V2-P01-T01：修正 ch3 配置的模型身份并新建正式矩阵

- [ ] **Task V2-P01-T01 完成：v2 矩阵含 6 模型 × 6 条件与统一配方字段**

**文件：**
- 修改：`configs/ch3/metropt_main.yaml`（现 `model: kst_light`，改指 `kst_light_v2` 或弃用后新建）
- 创建：v2 正式点预测矩阵 YAML（建议 `configs/ch3/metropt_v2_point_matrix.yaml`）

- [ ] 矩阵模型固定为 `li_tcn、ff_gru、masked_tcn、gru_d、ode_rnn、kst_light_v2`。
- [ ] 固定第 5 节数据合同：`metropt3_chrono_502030_v2`、168/24/60、`seed=split_seed=mask_seed=2026`、六缺失条件、中心条件 `mixed@0.30`。
- [ ] 显式记录统一配方字段：`epochs / batch_size / learning_rate / weight_decay / scheduler / grad_clip_norm / selection_metric`；`selection_metric` 固定 validation MAE。
- [ ] 核验 `configs/ch3/fd004_external.yaml`、`configs/ch3/tep_external.yaml` 已由 V2-X0-T02 修正为 `kst_light_v2`（实验本体在 V2-P06 执行）。
- [ ] 验证：`grep -rn "model: kst_light$" configs/` 无输出（排除 `kst_light_v2` 命中）。

**验收：** 任何 ch3 配置都不再指向旧模型 ID；矩阵可直接被 runner 展开。

#### Task V2-P01-T02：归档既有 H2 pilot 结果并隔离聚合扫描

- [ ] **Task V2-P01-T02 完成：H2 结果移出正式扫描路径并打标**

**文件：**
- 移动：`results/runs/` 下六个 H2 run → `archive/h2_pilot_kst_light_v2/`
- 创建：`archive/h2_pilot_kst_light_v2/README.md`（含 `legacy_only: true`、`formal_comparison_eligible: false`、定位说明）

- [ ] 移动六个 run 目录，保持原始文件不改动。
- [ ] README 写明其仅可用于可学习性判断、缺失机制敏感性、耗时估计与配方选择。
- [ ] 运行聚合/汇总入口，确认扫描结果不含任何归档 run（以聚合脚本实际输出为准核对 run 数）。

**验收：** 正式结果链从零开始；归档可追溯但不可混入统计。

---

### V2-P02：本机 Conda 接线验证

- [ ] **Phase V2-P02 完成：六模型在本机同一协议下接线正确**

#### Task V2-P02-T01：环境确认与全量测试

- [ ] **Task V2-P02-T01 完成：Conda 环境下全量测试通过**

- [ ] `which python` 与 `python -c "import sys; print(sys.executable)"` 指向 Conda `kst_probflow` 环境。
- [ ] 旧 venv 产物一律标记 `legacy_venv_artifact`，不与 Conda 结果合并。
- [ ] 运行 `PYTHONPATH=code python -m pytest code/tests/ -q`；记录通过/skip/失败数到 `plan/progress.md`。

**验收：** 无失败项；skip 项均有明确原因。

#### Task V2-P02-T02：dry-run 与 CPU smoke

- [ ] **Task V2-P02-T02 完成：六模型 CPU 单 batch smoke 通过**

- [ ] v2 点预测矩阵 dry-run（不训练，仅展开与校验）。
- [ ] 六模型各执行一次 CPU 单 batch smoke。
- [ ] `li_tcn`、`ode_rnn`、`kst_light_v2` 各执行一次短 sanity（少量 epoch）。
- [ ] 确认 `compare_code` 在本机可导入（对应概率基线工厂）。

**验收：** 六模型均能前向、反传、保存 checkpoint，输出 shape 正确。

#### Task V2-P02-T03：公平性一致性检查

- [ ] **Task V2-P02-T03 完成：split/normalization/mask 一致性核验通过**

- [ ] 六模型使用同一 split（比对 split SHA）。
- [ ] 六模型使用同一 normalization（train-only 统计量）。
- [ ] 同条件模型使用同一 mask（比对 mask SHA）。
- [ ] prediction shape、test evaluation 次数（每 run 恰好一次）、无 test target 泄漏逐项检查。
- [ ] 检查结果写入 `plan/progress.md`。

**验收：** 本机不产生论文正式指标，但接线、协议与可学习性验证全部通过。

---

### V2-P03：AutoDL 环境预检

- [ ] **Phase V2-P03 完成：跨机身份一致**

#### Task V2-P03-T01：远端 checkout 与环境核对

- [ ] **Task V2-P03-T01 完成：远端 clean checkout 且 SHA 与本机一致**

- [ ] 远端 `git clone`/`checkout v0.1-freeze`；`git status --porcelain` 为空。
- [ ] 设置 `KST_PROJECT_ROOT / KST_DATA_ROOT / KST_RESULT_ROOT`。
- [ ] 校验远端 MetroPT CSV 的 `raw_data_sha256` 与 data_gate 一致。
- [ ] 核对 Conda/依赖版本与 `environment.yml` 一致。
- [ ] 运行 dry-run 与不依赖 GPU 的 preflight（可用 `code/check_pilot_environment.py`）。
- [ ] 比对本机与远端的 matrix SHA / protocol SHA / raw data SHA。

**说明：** 无卡实例仅用于环境准备；若数据盘、SSH 与依赖已稳定，本 Phase 可直接在有卡实例中先执行。本 Phase 不产生论文正式结果，不生成正式训练 manifest。

---

### V2-P04：中心条件单种子对比（mixed@0.30）

- [ ] **Phase V2-P04 完成：中心条件 6 runs 通过 go/no-go**

#### Task V2-P04-T01：GPU preflight 与 CUDA smoke

- [ ] **Task V2-P04-T01 完成：GPU preflight 与 CUDA smoke 通过**

- [ ] 生成 GPU preflight 报告。
- [ ] 执行 CUDA 单 batch smoke（覆盖六模型）。
- [ ] 核验中心条件 mask：`mixed@0.30` 的 mask SHA 同条件跨模型一致。

#### Task V2-P04-T02：先跑 5 个 baseline，再跑 kst_light_v2

- [ ] **Task V2-P04-T02 完成：中心条件 6 runs 全部 formal_validated**

- [ ] 顺序执行 `li_tcn、ff_gru、masked_tcn、gru_d、ode_rnn` 的 mixed@0.30 各 1 run。
- [ ] 核验 5 个 baseline 的 manifest、protocol SHA、artifact SHA。
- [ ] 执行 `kst_light_v2` mixed@0.30 1 run。
- [ ] 下载全部结果回本机。

#### Task V2-P04-T03：中心条件 go/no-go 检查

- [ ] **Task V2-P04-T03 完成：go/no-go 全项通过**

- [ ] `completed = 6`；`nonfinite = 0`；`fairness_mismatch = 0`；`test_count_error = 0`。
- [ ] `protocol_sha`、`evaluator_sha`、`code_fingerprint` 六 run 一致。
- [ ] checkpoint 均来自 validation 选择。
- [ ] 结果与判定写入 `plan/progress.md`；不通过则停下修复，禁止带病扩展到六条件。

---

### V2-P05：第三章六条件正式单种子实验

- [ ] **Phase V2-P05 完成：36 runs 完整，第三章分析解冻**

#### Task V2-P05-T01：执行其余 5 条件 × 6 模型（30 runs）

- [ ] **Task V2-P05-T01 完成：30 runs 全部完成并回传**

- [ ] 中心条件通过后执行 `random@0.00 / random@0.30 / random@0.70 / low_rate@0.30 / block_offline@0.30`。
- [ ] 失败 run 单独隔离重跑，不覆盖已完成 run。

#### Task V2-P05-T02：36-run 完整性检查与汇总

- [ ] **Task V2-P05-T02 完成：检查清单全过，汇总表生成**

- [ ] 每模型每条件均有 manifest。
- [ ] 全部 run 同 split SHA、同 normalization SHA；同条件同 mask SHA。
- [ ] test evaluation 每 run 恰好一次；无 non-finite loss；checkpoint 来源为 validation。
- [ ] MAE、RMSE、训练时间、推理时间、参数量均有记录。
- [ ] 归档的 H2 pilot 与旧 venv 结果未进入聚合。
- [ ] 打 tag `v0.2-ch3-single-seed`。

#### Task V2-P05-T03：第三章分析产物

- [ ] **Task V2-P05-T03 完成：缺失强度/机制分析与对比表图生成**

- [ ] 缺失强度分析（random@0.00→0.70）与缺失机制分析（同 0.30 四机制）。
- [ ] baseline 与 `kst_light_v2` 对比表与图；全部数字可追溯到 run_id。

---

### V2-P06：外部数据集单种子验证（FD004 / TEP）

- [ ] **Phase V2-P06 完成：外部验证有独立门禁，不以降标方式完成**

#### Task V2-P06-T01：外部配置 v2 化与协议门禁

- [ ] **Task V2-P06-T01 完成：FD004/TEP 配置指向 kst_light_v2 且划分协议锁定**

**文件：**
- 修改：`configs/ch3/fd004_external.yaml`、`configs/ch3/tep_external.yaml`（V2-P01-T01 已改模型 ID，此处核验协议）

- [ ] FD004 按 engine 划分、TEP 按 simulation run 划分；`split_seed=2026` 固定。
- [ ] train-only normalization；不同 unit/run 的 mask 互不串联。
- [ ] TEP 数据门禁：必须有 faulty 数据并可被现有读取器解析；缺失则该数据集整条显式 skip 并在 progress 登记原因，禁止 fault-free fallback 顶替。

#### Task V2-P06-T02：执行外部单种子实验

- [ ] **Task V2-P06-T02 完成：每数据集 4 代表模型 run 完成**

- [ ] 代表模型固定为 `li_tcn、gru_d、ode_rnn、kst_light_v2`（与第三章口径一致）。
- [ ] 每数据集 4 runs；指标与第三章对齐（MAE、RMSE、效率）。
- [ ] 外部验证汇总写入 progress；不跨数据集直接比较指标绝对值。

---

### V2-P07：第四章概率单种子实验

- [ ] **Phase V2-P07 完成：6 概率 baseline + kst_probflow 通过一致性检查**

#### Task V2-P07-T01：（条件）KAFNet 系列适配前置阶段

- [ ] **Task V2-P07-T01 完成：KAFNet 系列适配完成，或论文口径正式排除**

- [ ] 若论文必须包含 `kafnet / kafnet_gaussian / kaf_profiti_marginal / kaf_profiti_joint`：基于 `vendor/KAFNet-main/` 完成统一数据接口、mask 接口、evaluator 接口、manifest 身份、单 batch smoke 与一次中心条件单种子 run；与其他模型同 split、mask、normalization、test evaluator。
- [ ] 若论文不包含：在 progress 中登记排除口径，registry 保持 `not_implemented`，论文不得声称已完成 KAFNet 对比。
- [ ] registry 状态与实际能力一致（`grafiti_gaussian` 标注为适配实现、`profiti` 标注为 adapted）。

#### Task V2-P07-T02：概率矩阵接线与 smoke

- [ ] **Task V2-P07-T02 完成：概率矩阵 dry-run 与 smoke 通过**

- [ ] `configs/pilot/metropt3/probabilistic_matrix.yaml` dry-run。
- [ ] 7 个概率模型各一次 CPU/GPU 单 batch smoke。

#### Task V2-P07-T03：先跑 6 个概率 baseline，再跑 kst_probflow

- [ ] **Task V2-P07-T03 完成：7 runs 完成且检查通过**

- [ ] mixed@0.30 单条件；`tcn_gaussian、patchtst_gaussian、gru_d_gaussian、ode_rnn_gaussian、grafiti_gaussian、profiti` 依次执行并通过 artifact 与 evaluator 检查。
- [ ] `kst_probflow` 最后执行。
- [ ] checkpoint 选择只用 validation CRPS 或 validation NLL；禁止 test NLL/CRPS/MAE 调参。
- [ ] 核验 NLL、CRPS、PICP、MPIW 来自同一概率输出头；采样结果、预测区间与 checkpoint 身份一致。
- [ ] 指标齐备：MAE、RMSE、NLL、CRPS、PICP、MPIW、训练时间、推理时间、参数量。

---

### V2-P08：风险校准与风险指标

- [ ] **Phase V2-P08 完成：校准链无 test 泄漏，风险指标可追溯**

#### Task V2-P08-T01：validation-only 校准与一次 test 评估

- [ ] **Task V2-P08-T01 完成：校准参数、阈值与 run_id 全部可追溯**

- [ ] 只用 validation 拟合 Platt 或 isotonic calibration；保存校准参数、校准数据范围与对应 run_id。
- [ ] 报警阈值不使用 test label 搜索；策略预先固定并记录。
- [ ] test 只做一次最终评估，输出 AUROC、AUPRC、Brier、ECE、Precision、Recall、F1。
- [ ] test split 单一类别时对应指标输出 `null`，不填 0。
- [ ] 完成后打 tag `v0.3-ch4-single-seed`。

---

### V2-P09：多种子正式实验与论文冻结

- [ ] **Phase V2-P09 完成：三种子证据链闭合，论文表图一键重建**

#### Task V2-P09-T01：三种子扩展

- [ ] **Task V2-P09-T01 完成：3 seeds 全矩阵完成**

- [ ] 顺序：中心条件 3 seeds → 第三章六条件 3 seeds → 第四章概率 3 seeds →（如包含）KAFNet/ProFITi 消融 3 seeds → 外部数据集 3 seeds。
- [ ] 单种子阶段结论仅视为方向性；论文最终数字以本 Phase 均值为准。

#### Task V2-P09-T02：统计汇总与冻结

- [ ] **Task V2-P09-T02 完成：表图重建通过，v1.0-paper-freeze 已打标**

- [ ] 汇总均值、标准差与置信区间；Bootstrap 单位与数据集匹配（MetroPT 用时间块/事件、FD004 用 engine、TEP 用 simulation run）；不以 3 seeds 做不可靠的显著性检验结论。
- [ ] 效率对比统一 batch、硬件、warm-up 与测量区间。
- [ ] 全部表图由代码从冻结 artifact 重建；每个正文数字可追溯到 run、seed、checkpoint 与代码版本。
- [ ] 打 tag `v1.0-paper-freeze` 并推送。

---

## 10. 推荐执行顺序

```text
V2-P00 迁移与 Git 冻结（.gitignore -> 清理 -> compare_code -> 数据+data gate -> vendor -> pilot_root 修复 -> 测试+clean commit+tag v0.1-freeze+push）
  -> V2-X0 外部数据集接线 pilot（run_experiment 路径治理 -> external 配置 ID -> AutoDL 最小预检（代 P03） -> FD004 单 seed -> TEP 单 seed -> 归档与配方反馈）
  -> V2-P01 点预测矩阵（配置 v2 化 -> H2 结果归档）
  -> V2-P02 本机 Conda 接线验证（环境 -> 全量测试 -> dry-run/smoke -> 一致性检查）
  -> V2-P03 AutoDL 预检（checkout -> SHA 跨机比对 -> dry-run）
  -> V2-P04 中心条件 mixed@0.30（GPU preflight -> 5 baseline -> kst_light_v2 -> go/no-go）
  -> V2-P05 第三章六条件 36 runs -> tag v0.2-ch3-single-seed
  -> V2-P06 FD004/TEP 外部单种子（TEP faulty 门禁）
  -> V2-P07 第四章概率 7 runs（KAFNet 适配先行或正式排除）
  -> V2-P08 风险校准 -> tag v0.3-ch4-single-seed
  -> V2-P09 三种子正式实验 -> 统计汇总 -> tag v1.0-paper-freeze
```

最关键的一条红线：`new_work` 的旧 baseline 结果一律不得搬入 `kst_light_v2` 当作正式对比结果。迁移只搬"源码和原始数据"，正式结果必须在 v2 的同一代码、同一协议、同一 evaluator 和同一 Conda/AutoDL 环境下重新产生。

## 11. 本轮明确不做

- 不迁移 `new_work` 的 `code/`、`configs/`、`plan/`、`result/`、preflight JSON 与旧 `manifest.json`（如需留档只能进 `archive/` 并标记 `formal_comparison_eligible: false`）。
- 不把六个 H2 pilot 结果写入第三章正式对比表，不与 baseline 混合计算均值。
- 不使用旧 venv 环境产生任何正式结果。
- 不在 Phase 门禁未通过时抢跑后续 Phase；不在论文中使用 `not_implemented` 模型的对比结论。
- 不用 test 集做任何选择（模型、阈值、超参数、calibrator）；不手工修改 `results/` 内的任何程序产物。
- 不在配置或代码中写死机器路径、主机、端口与账号。

---

# V2-ROADMAP-2026-09-24（权威后续路线）

**目标：** 在 `kst_light_v2` 主工程内，以同一数据协议、同一缺失 mask、同一 evaluator 和同一环境身份，依次完成第三章点预测、第四章概率预测、第五章风险评估的代码改造、单 seed 对比、validation-only 调参和多 seed 正式结果。

**架构：** 第三章冻结 `kst_light_v2`（异步规整表示编码器 + 点预测头）；第四章复用同一表示并接入 `kst_flow_v2`（ProFITiFlowHead，NLL/采样/区间）；第五章在概率模型上增加 `kst_probflow_v2`（QuantileHead、RiskHead、数据集风险协议和 validation-only 校准）。每一章先跑对比模型，再只使用 validation 选择本文模型配置，test 只在冻结后评估一次。

**新旧模型 ID 映射（2026-09-25）：** 权威路线下第四章概率主模型为 `kst_flow_v2`，第五章为 `kst_probflow_v2`（待新建，完成注册前 registry 不得标记可用）。旧 ID `kst_probflow`（registry 仍含实现、`configs/pilot/` 概率矩阵仍引用）仅作历史 pilot 审计，不得再作为第四/五章主模型进入新矩阵或正式结果。

**技术栈：** Python 3.12、PyTorch、Conda 环境 `kst_probflow`、pytest、YAML 配置、JSON manifest；路径由 `KST_PROJECT_ROOT`、`KST_DATA_ROOT`、`KST_RESULT_ROOT` 或 CLI 解析，禁止写死本机/AutoDL 路径。

**权威执行顺序：** `V2-X0` 外部接线收尾 → `V2-LITE` 点模型轻量化 → `V2-CH3-CODE` → `V2-CH3-SINGLE` → `V2-CH4-CODE` → `V2-CH4-SINGLE` → `V2-CH5-CODE` → `V2-CH5-SINGLE` → `V2-MULTI` → `V2-FREEZE`。旧计划中的 V2-P01～V2-P09 只作历史索引，不得作为另一条并行路线。

**legacy 配置口径（2026-09-25）：** `configs/pilot/` 为旧 pilot 基础设施，仅供历史审计，权威路线的新矩阵一律落在 `configs/ch3/`、`configs/ch4/`、`configs/ch5/`；其中残留的旧模型 ID 已修正为 `kst_light_v2`，防止误跑旧模型。

## A. 不可改变的科学合同

### A.1 数据协议与章节归属

| protocol_id | 数据集 | 章节用途 | 初始窗口 `(H,P,stride)` | 划分与风险边界 |
|---|---|---|---|---|
| `metropt3_chrono_502030_v2` | MetroPT-3 | 第三、四、五章主验证 | `(168,24,60)` | timestamp-group 50/20/30；segment 内窗口；train-only 归一化 |
| `cmapss_fd001` | C-MAPSS FD001 | 第三、四、五章外部验证 | `(50,10,1)` | engine 不跨 split；forecast-origin RUL 标签 |
| `cmapss_fd002` | C-MAPSS FD002 | 第三、四、五章外部验证 | `(50,10,1)` | 同 FD001 |
| `cmapss_fd003` | C-MAPSS FD003 | 第三、四、五章外部验证 | `(50,10,1)` | 同 FD001 |
| `cmapss_fd004` | C-MAPSS FD004 | 第三、四、五章外部验证 | `(50,10,1)` | 同 FD001；不得把 FD004 代表四个子集 |
| `tep_faulty` | TEP faulty | 第三、四、五章外部验证 | `(96,24,12)` | simulation run 不跨 split；fault-free 只能作辅助，不可顶替 faulty |

FD001、FD002、FD003、FD004 是四个独立正式协议。MetroPT 使用 `random@0.00/0.30/0.70`、`low_rate@0.30`、`block_offline@0.30`、`mixed@0.30` 六条件；其他协议先使用中心条件 `mixed@0.30`，若原始协议不支持人工 mask，必须在 manifest 中标记 `missing_mode=not_applicable`，不能静默改成另一种 mask。

### A.2 随机性、指标和选择规则

```text
单 seed：seed=2026，split_seed=2026，mask_seed=2026
多 seed：seed ∈ {2026, 2027, 2028}
第三章主指标：validation MAE；辅助 RMSE、训练时间、推理时间、参数量
第四章主指标：validation CRPS；辅助 NLL、MAE、RMSE、PICP、MPIW
第五章主指标：预先登记的风险 AUPRC/F1；辅助 AUROC、Brier、ECE、Precision、Recall
```

对比模型必须先于本文模型完成；所有模型复用相同 split、归一化统计量、人工 mask、窗口、seed、评价分母和 test 次数。调参只读取 validation，禁止查看 test 指标决定模型、参数、阈值或校准器。单类别 test 风险指标写 `null`，不得填 0。

### A.3 证据等级与环境切换

| 环境 | 允许操作 | 禁止操作 | 进入下一环境条件 |
|---|---|---|---|
| 本机 Conda | 全量 pytest、dry-run、协议构建、CPU 单 batch/≤1 epoch smoke、manifest/schema 检查、validation-only 小样本接线 | 正式多 epoch 训练、正式 test、使用 venv 产物 | 代码测试通过、工作区 clean、commit SHA 已冻结 |
| AutoDL 无卡 | checkout/数据同步、preflight、dry-run、配置展开、协议/数据 gate、CPU 低成本 smoke | GPU 训练、正式指标结论 | local/remote identity 段匹配、GPU 机器可用 |
| AutoDL 有卡 | CUDA 单 batch smoke、baseline-first 正式训练、validation 调参、冻结后 test、多 seed | 未通过 preflight 或 dirty checkout 时训练 | run manifest 完整、validator 通过并下载结果 |

每次改代码或配置都必须回到本机 Conda 测试并重新 commit；旧 venv 产生物标记为 `legacy_venv_artifact`，不得参与任何汇总。GPU 训练前必须重新生成 local 和 AutoDL preflight，旧 commit 的报告一律 stale。

## B. 代码改造总表

| 代码边界 | 目标 |
|---|---|
| `code/kaf_profiti/industrial/metropt.py`、`cmapss.py`、`tep.py` | 六协议的 split、segment、window、真实时间、目标列、风险标签 |
| `code/kaf_profiti/experiments/datasets.py` | 统一 `ProtocolDataset` 接口，显式传递 `split_seed`、`mask_seed` 和 train-only normalization |
| `code/kaf_profiti/models/kst_light_v2.py` | 第三章点预测编码器/decoder，记录可配置 hidden/layer/kernel/patch/FLA 参数 |
| `code/kaf_profiti/models/kst_flow_v2.py` | 第四章 flow head、NLL、sampling、quantile/interval 计算，固定 point 口径 |
| `code/kaf_profiti/models/kst_probflow_v2.py` | 第五章 probability + quantile + risk 输出，保存风险 score 与标签 |
| `code/kaf_profiti/experiments/probabilistic_adapter.py` | 统一不同 baseline 的 point/distribution/sample 接口，消除 `distribution()` 假设 |
| `code/kaf_profiti/experiments/evaluator.py`、`metrics.py`、`accumulators.py` | 三章统一 metric、分母、finite 检查、test-evaluation 计数 |
| `code/kaf_profiti/industrial/risk_protocol.py` | MetroPT、C-MAPSS、TEP 的风险规则、forecast-origin 标签和阈值来源 |
| `code/run_experiment.py` | CLI/env/config 路径解析、split_seed 透传、chapter/model contract、resume 身份 |
| `code/evaluate_risk_calibration.py` | validation-only Platt/isotonic/calibration artifact 和一次性 test 重评估 |
| `configs/ch3/`、`configs/ch4/`、`configs/ch5/` | 六协议、模型矩阵、搜索空间和 recipe version；无机器绝对路径 |
| `code/tests/ch3/`、`code/tests/ch4/`、`code/tests/ch5/` | 协议、adapter、指标、泄漏、身份和端到端 smoke 测试 |

可从 `new_work` 参考或抽取的模块：`QuantileHead`、`RiskHead`、`evaluator.py`、`metrics.py`、`accumulators.py`、`evaluate_risk_calibration.py` 和 `pilot_runner.py` 的 flow 接线思路。禁止直接覆盖 v2 的完整 encoder、风险协议或带硬编码路径的 `run_experiment.py`；每次迁移都要补 v2 测试并重新计算 code fingerprint。

## C0. V2-X0：外部数据接线收尾（历史已完成项的后续动作）

现有旧条目中 `V2-X0-T01`、`V2-X0-T02` 已完成的 checkbox 保留不改（原 `V2-X0-T03`～`T06` 已于 2026-09-25 删除，职责由本节三项承担）；下面三项是进入 V2-LITE 前必须完成的收尾，不把接线 pilot 当作正式论文结果。

### Task V2-X0-CLOSE-T01：Conda 与跨机身份预检

- [ ] 在本机 `kst_probflow` Conda 环境运行全量 pytest、FD004/TEP dry-run、配置 schema 和 portability 检查；确认 `git status --porcelain` 为空后提交。
- [ ] AutoDL 无卡 checkout 同一 commit，设置 `KST_PROJECT_ROOT`、`KST_DATA_ROOT`、`KST_RESULT_ROOT`，生成 local/AutoDL preflight；比较 commit、code/data/matrix/protocol SHA，环境名和绝对路径按规则忽略。
- [ ] 任何旧 venv 或旧 commit 的 preflight 标记 stale 并重建；未通过身份比较不得开 GPU 训练。

### Task V2-X0-CLOSE-T02：FD004 与 TEP 接线 smoke

- [ ] AutoDL 有卡只运行 `kst_light_v2` 单 batch CUDA smoke，验证 FD004 和 `tep_faulty` 的通道、窗口、loss finite、参数更新和 `test_metric_count=0`。
- [ ] 若 TEP faulty 数据不可用，写入 `blocked_data_gate` 和原因，禁止用 fault-free 结果代替；FD004 smoke 不能代表 FD001–FD003。
- [ ] 结果标记 `interface_only` 或 `smoke_passed`，不进入第三章、第四章或第五章表格。

### Task V2-X0-CLOSE-T03：归档与入口门禁

- [ ] 将旧 venv 结果、旧 preflight、非本协议 pilot 移到 `archive/` 或保留在 ignored result，并写 `formal_comparison_eligible=false`；不修改 metrics JSON。
- [ ] 验证六协议名称、窗口和 model_id 已在配置中可展开；完成后才进入 V2-LITE-T01。

## C. V2-LITE：点模型轻量化与配方冻结

### Task V2-LITE-T01：固定训练管线基线

**文件：** `code/run_experiment.py`、`code/kaf_profiti/experiments/manifest.py`、`code/tests/ch3/test_training_profile.py`。

- [ ] 在 Conda 环境完成 `num_workers=4`、`pin_memory=true`、`persistent_workers=true`、`non_blocking=true` 的 CPU 接口检查。
- [ ] 为 manifest 写入 `epoch_seconds`、`train_seconds`、`peak_gpu_memory_mb`、`num_workers`、`amp_dtype` 和 `parameter_count`。
- [ ] 本机执行 `python -m pytest code/tests/ch3/test_training_profile.py -q`，再执行 ≤1 epoch CPU smoke；产物标记 `smoke_passed`，不写入正式表。
- [ ] AutoDL 有卡只运行一次 CUDA 单 batch，确认 loss finite、参数发生更新、`test_metric_count=0`；下载日志和 manifest。
- [ ] 固定管线 recipe 为 `lite_pipeline_v1`，提交独立 commit。

### Task V2-LITE-T02：单因素结构筛选（validation-only）

**文件：** `code/kaf_profiti/models/kst_light_v2.py`、`configs/ch3/lite_search.yaml`、`code/tests/ch3/test_lite_config.py`。

- [ ] 固定 MetroPT 中心条件、seed=2026、split/mask SHA、batch 和 epoch；只改变一个因素，依次运行 A0、`preconv_dim=8`、`kernel_count=3`、`hidden_dim=48`、`hidden_dim=32`、`n_layers=1`、`patch_lens=[12,24]`。
- [ ] 每个变体只用 validation MAE/RMSE、训练时间和参数量排序；test 计数必须为 0。
- [ ] 为 `encoder_mlp_ratio`、`cross_variable_rank`、`cross_variable_mlp_ratio` 增加显式 config/manifest 字段，禁止用未记录的内部常量产生正式候选。
- [ ] 保留每个失败或退化 artifact；选择不超过三个 Pareto 候选进入 T03，接受条件为参数量至少下降 25%、训练时间至少下降 20%，validation MAE 增幅不超过 2%。

### Task V2-LITE-T03：FLA-lite 变体

**文件：** `code/kaf_profiti/models/kst_light_v2.py`、`configs/ch3/lite_search.yaml`、`code/tests/ch3/test_fla_lite.py`。

- [ ] 在 T02 最优候选上单独运行 F0 `(rank=64, mlp_ratio=4)`、F1 `(32,4)`、F2 `(64,2)`、F3 `(32,2)`。
- [ ] 检查参数量、epoch 时间、finite loss 和 validation MAE；不使用 test 结果裁决。
- [ ] 若 FLA-lite 退化，回退到上一 Pareto 候选并在 manifest 写明 `fallback_reason`；不得覆盖历史 artifact。

### Task V2-LITE-T04：轻量跨变量 Mixer 对照

**文件：** 新建 `code/kaf_profiti/models/light_sensor_mixer.py`，修改 `registry.py`，新增 `code/tests/ch3/test_sensor_mixer.py`。

- [ ] 保留 `M_obs`、freshness、recency/block 和层次 patch 输入，仅替换跨变量模块为共享投影 + gated residual mixer。
- [ ] 注册独立 model_id，不覆盖 `kst_light_v2`；与 FLA-lite 使用同一 protocol/mask/seed/recipe。
- [ ] 仅在 validation MAE 不超过冻结基线 2% 且效率达到 T02 接受条件时保留，否则标记 `rejected_validation_only`。

### Task V2-LITE-T05：冻结第三章编码器配方

**文件：** `configs/ch3/metropt_main.yaml`、`configs/ch3/external_*.yaml`、`plan/progress.md`。

- [ ] 用 validation-only 证据选出唯一 `kst_light_v2` 配方，锁定所有六协议的初始窗口和 recipe version。
- [ ] 在 MetroPT 中心条件完成一次完整单 seed 复核，确认短训练排序没有反转；test 仅在第三章正式单 seed 阶段执行。
- [ ] 更新配置、README/进度记录和 tag `v0.2-lite-freeze`；无卡环境重新生成 preflight。

## D. V2-CH3-CODE：第三章协议与点预测代码

### Task V2-CH3-CODE-T01：统一六协议数据入口

**文件：** `code/kaf_profiti/experiments/datasets.py`、`industrial/metropt.py`、`industrial/cmapss.py`、`industrial/tep.py`、对应测试。

- [ ] 统一返回 `Y_q`、`context`、`T_obs`、`T_q`、`M_obs`、`unit_id`、`window_id`、`risk_label`；窗口不得跨 segment/engine/simulation run。
- [ ] 透传 `split_seed=2026`、`mask_seed=2026`；normalization 只从 train 统计，保存 SHA 和列名。
- [ ] 为 FD001–FD004 分别生成 split/window SHA；为 TEP 新增 `tep_faulty`，缺 faulty 时显式失败而不是 fallback 到 fault-free。
- [ ] 测试重复 timestamp、gap、unit 边界、列维度、mask 重放和 train-only normalization。

### Task V2-CH3-CODE-T02：修复训练入口与点预测契约

**文件：** `code/run_experiment.py`、`code/kaf_profiti/experiments/registry.py`、`code/kaf_profiti/experiments/evaluator.py`。

- [ ] 增加 `chapter=ch3` contract：模型必须提供 `predict_point()` 和点预测 loss；统一 device、batch、checkpoint、test count。
- [ ] 修复 `create_protocol_datasets()` 的 `split_seed` 传递和 CLI/env/config 优先级；运行时只解析环境变量或相对默认值。
- [ ] manifest 写入 `dataset/protocol/mask/normalization/evaluator/code/matrix` SHA、命令、环境和 checkpoint SHA。
- [ ] 测试错误模型能力、路径可移植性、resume 身份和 test 只调用一次。

### Task V2-CH3-CODE-T03：第三章矩阵和 validator

**文件：** `configs/ch3/point_matrix.yaml`、`code/run_pilot_matrix.py`、`code/validate_results.py`、`code/tests/ch3/test_point_matrix.py`。

- [ ] 矩阵模型固定为 `li_tcn`、`ff_gru`、`masked_tcn`、`gru_d`、`ode_rnn`、`kst_light_v2`；所有 recipe 字段显式写出。
- [ ] validator 检查 36 个 MetroPT run、4 个 FD 协议和 TEP 的 key、fairness、finite、test count、参数量和时间字段。
- [ ] dry-run 输出完整 key 集，真实运行前不生成 checkpoint/prediction。

## E. V2-CH3-SINGLE：第三章单 seed 正式实验

### Task V2-CH3-SINGLE-T01：中心条件 baseline-first

- [ ] AutoDL 无卡完成 checkout、data gate、dry-run 和 local/remote identity 比对。
- [ ] AutoDL 有卡先运行六协议中的 MetroPT `mixed@0.30` 五个 baseline；每个 run 使用 seed/split/mask=2026。
- [ ] validator 必须得到 `completed=5`、`nonfinite=0`、`fairness_mismatch=0`、`test_metric_count=1`；失败 run 保留并单独重跑。

### Task V2-CH3-SINGLE-T02：中心条件本文模型与 go/no-go

- [ ] 在同一中心条件和同一 mask 下运行 `kst_light_v2`，只能使用 T02/T03 validation 配方。
- [ ] 记录 validation MAE、test MAE/RMSE、训练/推理时间和参数量；生成 `ch3_central_go_no_go.json`。
- [ ] 只有本文模型在预定义主指标达到 baseline 参照且所有公平性门禁通过，才允许扩展其余条件。

### Task V2-CH3-SINGLE-T03：MetroPT 六条件完整矩阵

- [ ] 在中心条件通过后运行其余五个缺失条件的五 baseline + 本文模型，共 30 runs。
- [ ] 检查每个条件的 mask bundle、split、normalization 和 evaluator SHA 一致；不同缺失机制不得复用错误 mask。
- [ ] 汇总 36 runs 为第三章单 seed表，标记 `formal_validated`，打 tag `v0.2-ch3-single-seed`。

### Task V2-CH3-SINGLE-T04：FD001–FD004 与 TEP 点预测单 seed

- [ ] 每个 C-MAPSS 子集单独运行五 baseline 后运行本文模型；不得只运行 FD004 代表四个子集。
- [ ] `tep_faulty` 先验证 faulty 标签和 simulation-run split，再按同一 baseline-first 顺序运行。
- [ ] 生成六协议点预测汇总；若某协议数据 gate 失败，状态为 `blocked_data_gate`，禁止用其他协议结果替代。

## F. 数据集特定参数调整协议

所有参数调整先在 AutoDL 有卡的 validation-only job 中完成，仍固定 seed=2026；调参 job 不执行 test，artifact 标记 `tuning_only`。每一轮先跑 baseline，再跑本文模型默认配方，之后按下表逐项搜索，最多保留三个候选，最后用完整 validation 集复核一次。

| 数据集 | 第一轮固定值 | 第二轮搜索顺序 | 冻结条件 |
|---|---|---|---|
| MetroPT | `H/P/stride=168/24/60`，hidden=64，layers=2，patch=`12,24,48`，lr=`2e-4` | hidden `{32,48,64}` → layers `{1,2}` → patch `{12,24},{12,24,48}` → lr `{1e-4,2e-4,3e-4}` → FLA rank `{32,64}` | validation MAE 与效率 Pareto；不看 test |
| FD001–FD004 | `50/10/1`，hidden=32，layers=1，patch=`5,10,20`，batch=128 | hidden `{32,48,64}` → lr `{1e-4,2e-4}` → weight decay `{1e-5,1e-4}` → patch `{5,10},{5,10,20}`；FD002/004 可增加 layers=2 复核 | 每个 FD 独立选择；不能把 FD004 参数复制成四个结论 |
| TEP faulty | `96/24/12`，hidden=64，layers=2，patch=`12,24,48`，batch=64 | hidden `{48,64,96}` → layers `{1,2}` → lr `{1e-4,2e-4,3e-4}` → patch `{12,24},{12,24,48}`；检查 simulation-run batch 平衡 | validation MAE/RMSE finite 且故障段不被 mask 泄漏 |

调参停止规则：连续两轮 validation 主指标没有改善且效率不改善即停止；不得因为 test 排名再次打开搜索空间。每个数据集保存 `tuning_manifest.json`，记录候选、选择指标、未使用的 test 字段和最终 recipe SHA。

## G. V2-CH4-CODE：第四章概率模型

### Task V2-CH4-CODE-T01：概率 adapter 与统一 head

**文件：** 新建 `code/kaf_profiti/experiments/probabilistic_adapter.py`，修改 `code/kaf_profiti/models/kst_flow_v2.py`、`code/kaf_profiti/experiments/evaluator.py`。

- [ ] 统一 baseline 输出为 `point_mean`、`distribution/sample`、`quantiles`；适配没有概率输出的模型时明确使用 Gaussian head，并在 manifest 写 `head_type`。
- [ ] 固定 `kst_flow_v2.predict_point()` 与 sample mean 的口径，记录 flow 的 `nll`、samples、quantile levels、interval coverage。
- [ ] 统一计算 MAE、RMSE、NLL、CRPS、PICP、MPIW、时间和参数量，并测试 finite、sample shape 和区间单调性。

### Task V2-CH4-CODE-T02：概率矩阵与模型注册

**文件：** `configs/ch4/probabilistic_matrix.yaml`、`registry.py`、`code/tests/ch4/test_probability_contract.py`。

- [ ] 矩阵固定为 `tcn_gaussian`、`patchtst_gaussian`、`gru_d_gaussian`、`ode_rnn_gaussian`、`grafiti_gaussian`、`profiti`、`kst_flow_v2`；KAFNet 系列只有完成 adapter 后才能加入。
- [ ] 所有模型使用同一中心条件、窗口、mask、seed 和 validation checkpoint 选择指标（CRPS 主、NLL 辅）。
- [ ] dry-run 验证 key、matrix SHA、head type 和 recipe 字段；未实现模型必须报错或显式 skip，不得静默标完成。

### Task V2-CH4-CODE-T03：第四章泄漏与 artifact 门禁

- [ ] 测试 test label 不进入训练、early stopping、flow temperature、区间校准或模型选择。
- [ ] prediction artifact 保存 forecast/query 时间、unit、samples/quantiles、point mean、protocol SHA 和 checkpoint SHA。
- [ ] validator 检查同一 run 的 point/probabilistic 指标来自同一个 checkpoint，test 评估计数为 1。

### Task V2-CH4-CODE-T04：KAFNet/ProFITi 适配决策

**文件：** `compare_code/probabilistic_baselines/`、`code/kaf_profiti/experiments/probabilistic_adapter.py`、`configs/ch4/probabilistic_matrix.yaml`、`code/tests/ch4/test_baseline_adapters.py`。

- [ ] 逐一核对 `kafnet`、`kafnet_gaussian`、`kaf_profiti_marginal`、`kafnet_profiti_joint` 的输入、缺失 mask、输出分布和训练目标；为能满足统一协议的模型写 adapter 和 smoke 测试。
- [ ] adapter 必须显式声明 `implemented`、`head_type`、`supports_sampling` 和 `selection_metric`；未通过 finite、shape 或公平性测试的模型保持 `not_implemented`，不得出现在正式结果表。
- [ ] 若适配完成，将模型加入第四章 baseline-first 矩阵并重新计算 matrix SHA；若未完成，在 `plan/progress.md` 记录排除理由，不用旧工程结果替代。

## H. V2-CH4-SINGLE：第四章单 seed 与本文模型调优

### Task V2-CH4-SINGLE-T01：baseline-first 中心条件

- [ ] AutoDL 有卡先运行六个已实现概率 baseline；每个 baseline 完成后立即运行 validator，失败不阻断其他模型。
- [ ] 仅汇总 validation CRPS/NLL 和 test 一次性指标；生成 baseline reference manifest。

### Task V2-CH4-SINGLE-T02：kst_flow_v2 validation-only 调参

- [ ] 复用第三章冻结 encoder，不改变数据协议；搜索 flow rank `{16,32,64}`、head hidden `{32,64}`、learning rate `{1e-4,2e-4}`、sample count `{50,100}`。
- [ ] 先按 validation CRPS，再按 NLL 和效率保留最多三个候选；禁止读取 test CRPS 选参数。
- [ ] 对 MetroPT、每个 FD 子集和 TEP 分别登记最佳 recipe；数据集间不得未经验证复制参数。

### Task V2-CH4-SINGLE-T03：六协议正式概率单 seed

- [ ] 用 baseline-first 顺序在六协议运行最终 `kst_flow_v2`；每协议至少保留一个完整 baseline 参照和本文模型 artifact。
- [ ] 生成第四章表格所需指标和区间图数据，所有 run 标记 `formal_validated`。
- [ ] 完成后打 tag `v0.3-ch4-single-seed`；未通过 go/no-go 的协议不得进入多 seed。

## I. V2-CH5-CODE：风险、校准与故障协议

### Task V2-CH5-CODE-T01：数据集风险协议

**文件：** 新建 `code/kaf_profiti/industrial/risk_protocol.py`、`industrial/tep.py`，修改 `industrial/cmapss.py`、`industrial/metropt.py`。

- [ ] MetroPT 使用 query timestamp 与 fault interval 交集形成风险标签；阈值和 interval 来源写入 manifest。
- [ ] C-MAPSS 使用 forecast-origin RUL 规则生成风险标签，记录 engine、origin、RUL threshold；不使用未来窗口标签。
- [ ] TEP 使用 faulty simulation/run 的故障区间或已登记 fault class；每个 split 显式记录正负类数量。
- [ ] 测试标签时间边界、split 隔离、单类别输出 null 和风险标签不可被 mask 生成器改写。

### Task V2-CH5-CODE-T02：kst_probflow_v2 与风险 artifact

**文件：** 新建 `code/kaf_profiti/models/kst_probflow_v2.py`，修改 `registry.py`、`evaluator.py`。

- [ ] 在 `kst_flow_v2` 上接入 `QuantileHead`、`RiskHead`；输出 point、samples、quantiles、risk score、risk label、timestamp 和 unit/run identity。
- [ ] 参数化 risk loss 权重、quantile levels、阈值来源；所有值写入 config 和 manifest。
- [ ] 检查 risk score 与预测样本来自同一 checkpoint，避免 evaluator 用另一模型的 prediction。

### Task V2-CH5-CODE-T03：validation-only 校准

**文件：** `code/evaluate_risk_calibration.py`、`code/tests/ch5/test_calibration_protocol.py`。

- [ ] 在 validation 上拟合 Platt 或 isotonic 校准器和 q=0.95 阈值；保存 calibration parameters、输入范围、run_id、protocol SHA。
- [ ] test 只调用一次校准后的预测；校准器不可访问 test label，test 目录不写回训练配置。
- [ ] validator 计算 AUROC、AUPRC、Brier、ECE、Precision、Recall、F1；单类别返回 null 并给出原因。

## J. V2-CH5-SINGLE：第五章六协议单 seed

### Task V2-CH5-SINGLE-T01：risk baseline 与中心条件

- [ ] 先用第四章冻结的 baseline 概率输出生成风险 score，再运行 `kst_probflow_v2`，避免只比较本文模型而无法解释增益。
- [ ] 中心条件完成 validation-only calibration，验证 risk artifact、标签正负类和 test count。

### Task V2-CH5-SINGLE-T02：六协议风险单 seed

- [ ] MetroPT、FD001、FD002、FD003、FD004、TEP faulty 分别运行最终模型和登记的风险 baseline。
- [ ] 每协议保存 risk rule、threshold、calibration、score/label/timestamp/unit 文件；不得合并不同协议的阈值。
- [ ] 生成第五章单 seed 表和风险曲线数据，所有数字可追溯到 run_id、seed、checkpoint、code/protocol SHA。

## K. V2-MULTI：多 seed 正式实验

### Task V2-MULTI-T01：多 seed 前置门禁

- [ ] 六协议第三章、第四章、第五章单 seed 均达到 go/no-go；所有单 seed 结果为 `formal_validated`。
- [ ] 代码、数据、矩阵、协议和 evaluator SHA 冻结；创建 `v2-multiseed-freeze` commit/tag。
- [ ] AutoDL 为每个 seed 建立独立 run_id；禁止复用 checkpoint、mask 或 validation 选择结果。

### Task V2-MULTI-T02：三 seed 运行与统计

- [ ] 对 seed `{2026,2027,2028}` 重跑所有冻结的第三、四、五章矩阵；每个 seed 使用同一 recipe，不跨 seed 调参。
- [ ] 汇总均值、标准差和适配单位的 bootstrap 置信区间：MetroPT 按时间块/事件，C-MAPSS 按 engine，TEP 按 simulation run。
- [ ] 统计训练/推理时间时固定硬件、batch、warm-up 和计时区间；异常 run 不删除，按 validator 规则标记并重跑。

## L. V2-FREEZE：论文表图与最终交付

### Task V2-FREEZE-T01：结果表图流水线

**文件：** `code/build_tables.py`、`code/build_figures.py`、`plan/progress.md`。

- [ ] 只扫描 `formal_validated` artifact；自动排除 pilot、tuning、legacy_venv、blocked 和失败 run。
- [ ] 生成第三章点预测表、第四章概率表、第五章风险表及误差/区间/风险曲线；表中附 dataset/protocol/seed 标识。
- [ ] 每个正文数字记录来源 run_id、checkpoint、commit、matrix/protocol/evaluator SHA；不手工改 CSV/JSON。

### Task V2-FREEZE-T02：最终复核与论文冻结

- [ ] 运行 `python -m pytest code/tests/ -q`、portability 扫描、`git diff --check` 和全量 validator。
- [ ] 检查无绝对路径、无旧 venv 产物、无 test 泄漏、无未实现模型被标为完成；确认 `git status --porcelain` 为空。
- [ ] 创建 `v1.0-paper-freeze` tag；将实验命令、环境报告、表图索引和剩余风险写入 `plan/progress.md`。

## M. 每个 Task 的提交与勾选模板

每个 Task 严格按以下顺序执行，不能先勾选后补证据：

1. `[ ]` 写失败测试或 schema 检查，并在本机 Conda 运行确认失败/暴露缺口。
2. `[ ]` 实现最小代码或配置改动，只触碰 Task 声明的文件。
3. `[ ]` 在本机运行目标测试、全量回归、dry-run 和 `git diff --check`。
4. `[ ]` 如涉及 GPU，先 commit 并生成 local/AutoDL preflight，再开有卡实例；训练结束下载 manifest、日志和结果。
5. `[ ]` validator、身份 SHA、fairness、finite、test count 全部通过后，将该 Step 和 Task checkbox 改为 `[x]`，并在 `plan/progress.md` 记录日期、commit、命令、run_id、设备和产物路径。
6. `[ ]` 每个独立 Task 提交一次小 commit；不得把多个未验证 Phase 合并成一个无法回溯的提交。

**文件清单约定：** Task 声明的"文件"未逐条标注创建/修改时，以仓库现状为准：路径不存在即为新建。

**最终执行红线：** 对比模型先跑，本文模型后调；validation 选型，test 一次；六个协议独立；本机 Conda 负责代码门禁，AutoDL 无卡负责身份/数据门禁，AutoDL 有卡负责正式训练；任何一项门禁失败都停在当前 Task，不用旧结果或另一数据集结果填补。
