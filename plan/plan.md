# kst_light_v2 主工程迁移与第三、四章对比实验建设规划

> **供后续智能体执行：** 必须逐 Phase、逐 Task 执行。所有状态均使用 checkbox（`- [ ]` / `- [x]`）追踪，完成一项立即写回本文件，不批量补记。

本规划以 kst_light_v2 仓库根为唯一主工程（下文仓库内路径均为相对路径），把旧工程 `new_work` 中可复用的源码与原始数据迁移进来，并在统一协议、统一 evaluator、统一环境下重新产生全部正式对比结果。正式结果一律不允许从旧工程搬运。

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

- [ ] **Phase V2-X0 完成：两个外部数据集在 v2 冻结环境下端到端可跑，模型可学习性信号已取得**

**定位与边界：** 本 Phase 不是正式外部验证（那仍是 V2-P06 的职责），而是在投入矩阵建设（V2-P01）之前，先确认 FD004/TEP 两个通道在 v2 冻结环境下端到端可跑、`kst_light_v2` 可学习，并取得训练耗时/资源信号。结论权限与 MetroPT H2 pilot 相同：仅接线与模型选择证据，`formal_comparison_eligible: false`，不得进入论文正式表格。

**已核实的现状（2026-09-24）：** registry 中 `kst_light` 与 `kst_light_v2` 并存（旧 ID 被静默接受）；`configs/ch3/*.yaml` 无代码消费，实际单跑入口是 `code/run_experiment.py` 纯 CLI；该 CLI 硬编码 AutoDL 默认路径且不走 `resolve_runtime_paths`；`_create_tep` 仅加载 fault-free 数据；本机无 CUDA，正式单 seed 需 AutoDL。

#### Task V2-X0-T01：run_experiment.py 路径治理

- [x] **Task V2-X0-T01 完成：入口脚本零硬编码路径，默认解析走 KST_* 契约**

**文件：**
- 修改：`code/run_experiment.py`
- 修改：`code/tests/ch3/test_portability_policy.py`（删除 `code/run_experiment.py` 的 4 条 allowlist 豁免）

- [x] 以 portability 测试为失败测试驱动：先删除 4 条 allowlist 豁免，运行 `PYTHONPATH=code python -m pytest code/tests/ch3/test_portability_policy.py -q` 确认转红。
- [x] 将 `--data-root`/`--output-dir` 默认值从 `/root/autodl-tmp/...` 改为 None，经 `resolve_runtime_paths` 解析（`KST_DATA_ROOT`/`KST_RESULT_ROOT` → 仓库相对 `dataset/`、`results/` 默认）。
- [x] 重跑 portability 测试确认转绿；运行 `python code/run_experiment.py --help` 确认可在仓库根正常解析。

**验收：** `code/run_experiment.py` 零机器路径命中；portability 全绿；全量 pytest 无回归。

#### Task V2-X0-T02：external 配置模型身份修正

- [ ] **Task V2-X0-T02 完成：external 两个配置指向 kst_light_v2**

**文件：**
- 修改：`configs/ch3/fd004_external.yaml`、`configs/ch3/tep_external.yaml`

- [ ] 两个配置 `model: kst_light` → `model: kst_light_v2`（registry 已含该 ID）。
- [ ] 验证：`grep -rn "model: kst_light$" configs/ch3/fd004_external.yaml configs/ch3/tep_external.yaml` 无输出。
- [ ] `configs/ch3/metropt_main.yaml` 的修正仍归 V2-P01-T01，本 Task 不动。

**验收：** external 配置不再指向旧模型 ID；后续任何人都无法用这两个配置静默跑出旧模型。

#### Task V2-X0-T03：最小 AutoDL 预检（通过后 P03 视为完成）

- [ ] **Task V2-X0-T03 完成：远端 checkout 干净、SHA 与本机一致、dry-run 通过**

- [ ] 执行 V2-P03-T01 全部步骤（checkout `v0.1-freeze`、`git status --porcelain` 为空、设置三个 `KST_*` 环境变量、MetroPT/CMAPSS/TEP 数据 SHA 核验、Conda 环境与 `environment.yml` 一致、dry-run、跨机 SHA 比对）。
- [ ] 完成后在本文件将 V2-P03 的 Task V2-P03-T01 与 Phase V2-P03 一并勾选，并注明"由 V2-X0-T03 代为完成"。

**验收：** AutoDL 具备与 v0.1-freeze 一致的代码、数据与环境身份；CMAPSSData 与 dataverse_files 已随数据迁移在位。

#### Task V2-X0-T04：FD004 单 seed pilot

- [ ] **Task V2-X0-T04 完成：FD004 可学习性门禁 + 全量单 seed run 完成**

**文件：**
- 计划生成：`results/pilot/fd004/`（sanity）与 run 产物目录（记录实际位置到 progress）

- [ ] 本机 CPU 快速门禁：`PYTHONPATH=code python code/diagnostics/fd004_learnability_sanity.py --rate 0.3`（内置约 6 epochs）；不可学习则停下分析，不带病上 GPU。
- [ ] AutoDL 全量单 seed（按 `fd004_external.yaml` 显式传全参，禁止依赖 CLI 默认）：`--dataset cmapss_fd004 --model kst_light_v2 --seed 2026 --split-seed 2026 --missing-mode mixed --missing-rate 0.3 --history-len 50 --pred-len 10 --stride 1 --epochs 80 --batch-size 128 --hidden-dim 64` 及该配置其余字段。
- [ ] 记录到 progress.md：learnability 结论、test MAE/RMSE、训练/推理耗时、峰值显存、实际配方（含 CLI 默认补全的字段如 lr/weight_decay/scheduler）。

**验收：** 产生 1 个 FD004 × `kst_light_v2` 单 seed run；耗时与可学习性信号已登记，可支撑 V2-P01 配方决策与 GPU 预算估算。

#### Task V2-X0-T05：TEP 接线 pilot（fault-free 限定）

- [ ] **Task V2-X0-T05 完成：TEP 通道接线验证完成，边界已声明**

- [ ] 声明边界（写入 progress.md）：当前 `_create_tep` 仅支持 fault-free 数据、风险标签全负类，故本 pilot 不评估任何风险指标，结论仅限"通道可跑 + 点预测可学习性观察"；faulty 集成仍归 V2-P06，届时必须接入 faulty runs 并按 simulation run 隔离。
- [ ] AutoDL 单 seed：`--dataset tep --model kst_light_v2 --seed 2026 --missing-mode mixed --missing-rate 0.3 --history-len 96 --pred-len 24 --stride 12 --epochs 50 --batch-size 128 --hidden-dim 64` 及该配置其余字段。
- [ ] 若全量 50 epochs 时长不可接受，允许降级为短 epoch sanity（如 10–15 epochs）并在 progress.md 记录降级原因与实际 epoch 数。

**验收：** TEP 通道产生 ≥1 个 run（或明确记录的降级 sanity）；无任何风险指标被输出或引用。

#### Task V2-X0-T06：结果归档与配方反馈

- [ ] **Task V2-X0-T06 完成：结论权限已标注，配方建议已反馈 P01**

- [ ] 两个数据集的 run 产物统一落 `results/`（runtime paths 解析），不与 MetroPT H2 结果混放。
- [ ] progress.md 登记：`formal_comparison_eligible: false`、run_id 清单、发现的问题清单（适配缺陷、数据异常、超时项）。
- [ ] 给 V2-P01 的书面建议：统一配方是否需要为 FD004/TEP 调整 epochs/lr；若需要，在 V2-P01-T01 建矩阵时一并固定。

**验收：** V2-P01 启动时无需重新探索两个外部数据集的基本盘。

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
