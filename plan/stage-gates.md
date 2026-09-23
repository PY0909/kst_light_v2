# 第三章实验阶段门禁

> 适用计划：[第三章实验任务计划](implementation-plan.md#11-第三章实验任务计划)  
> 实验协议：[第三章实验协议](experiment-protocol.md)  
> 当前状态：D0-D2 已关闭；D3-D5 未关闭

## 1. 状态更新规则

1. 门禁只由对应 Phase 指定的 validator 和证据关闭，不以代码存在、命令启动或人工目测代替。
2. checkbox 是结构化状态的镜像：只有 `status=closed` 时允许 `[x]`；`open` 或 `stale` 必须为 `[ ]`。
3. 每个 state transition evidence record 至少记录 `gate_id/check_id/previous_status/new_status/depends_on/input_sha_set/command/exit_code/evidence_relpath/evidence_sha256/checked_at_utc/supersedes`。
4. gate-specific validator 每次运行都重新计算排序后的 canonical `input_sha_set`。它与已关闭记录不一致时，必须把该 gate 改为 `stale`、恢复 `[ ]`、追加 stale record，并按依赖图递归标记全部下游 gate；命令以非零退出码阻断继续执行。
5. `stale` gate 重新关闭时生成新 evidence record，`supersedes` 指向旧记录 SHA；旧记录保留，不覆盖或删除。
6. 关闭 gate 前要求全部 `depends_on` 为 `closed`、`input_sha_set` 非空、validator 退出码为 0，且 registry、checkbox 与 evidence record 在同一变更中一致。
7. D0-D5 不允许提前、批量或推测性勾选。原始 metrics、prediction、mask、checkpoint 和 profile repeats 不得为关闭门禁而手工修改。
8. 本文件只记录门禁和证据身份，不抄录或手工维护实验指标数值。

## 2. 机器状态注册表

以下 YAML 是门禁状态唯一结构化记录。D0-D2 的闭合输入和证据见第 3 节；D3-D5 仍为初始 open 状态。

```yaml
schema_version: ch3-gates-v1
gates:
  D0:
    check_id: ch3.d0.protocol
    status: closed
    depends_on: []
    input_sha_set:
      - "sha256=a4f852395340f46f4cf8066f5d2099e7bfef98736b2af19c4efa881084156efa path=plan/experiment-protocol.md"
    supersedes: []
  D1:
    check_id: ch3.d1.traceability
    status: closed
    depends_on: [D0]
    input_sha_set:
      - "sha256=a4f852395340f46f4cf8066f5d2099e7bfef98736b2af19c4efa881084156efa path=plan/experiment-protocol.md"
      - "sha256=aa4d9731196da6a2ec0d174aaf1dc656a0f0640017ba8ed65a4b75fc63793114 path=plan/review/method-experiment-traceability.md"
    supersedes: []
  D2:
    check_id: ch3.d2.output_contract
    status: closed
    depends_on: [D0, D1]
    input_sha_set:
      - "sha256=38f31084c9584b6a2c35690f017ff33b60601d75e4804080d357374b059d6a6a path=figures/data-manifest.md"
      - "sha256=a4f852395340f46f4cf8066f5d2099e7bfef98736b2af19c4efa881084156efa path=plan/experiment-protocol.md"
      - "sha256=aa4d9731196da6a2ec0d174aaf1dc656a0f0640017ba8ed65a4b75fc63793114 path=plan/review/method-experiment-traceability.md"
      - "sha256=d071c73ac3e1625796879632778a56c59c3c71326d0e5dab79d48750755fd7b0 path=tables/table-schema.md"
    supersedes: []
  D3:
    check_id: ch3.d3.formal_coverage
    status: open
    depends_on: [D0, D1, D2]
    input_sha_set: []
    supersedes: []
  D4:
    check_id: ch3.d4.output_decontamination
    status: open
    depends_on: [D3]
    input_sha_set: []
    supersedes: []
  D5:
    check_id: ch3.d5.review_freeze
    status: open
    depends_on: [D3, D4]
    input_sha_set: []
    supersedes: []
```

依赖图固定为 `D0 -> D1 -> D2 -> D3 -> D4 -> D5`，并保留 D3 到 D5 的直接依赖。任何协议 SHA 漂移至少使 D0-D5 全部 stale；D3 candidate 输入漂移使 D3-D5 stale；仅 review/freeze 输入漂移使 D5 stale。

## 3. 状态迁移证据记录

| gate_id | check_id | previous_status | new_status | depends_on | input_sha_set | command | exit_code | evidence_relpath | evidence_sha256 | checked_at_utc | supersedes |
|---|---|---|---|---|---|---|---:|---|---|---|---|
| D0 | ch3.d0.protocol | open | closed | 无 | `a4f852395340f46f4cf8066f5d2099e7bfef98736b2af19c4efa881084156efa` | `bash plan/tests/test_validate_ch3_p00.sh`；`LC_ALL=C.UTF-8 LANG=C.UTF-8 bash plan/scripts/validate_ch3_p00.sh` | 0 | `plan/review/ch3-p00-t04-gate-validation.md` | `b2c3fbc9020a163e93400f70a3711f09a2a6b68a2c0462057b3412b0bb373dac` | 2026-09-04T06:26:03Z | 无 |
| D1 | ch3.d1.traceability | open | closed | D0 | `a4f852395340f46f4cf8066f5d2099e7bfef98736b2af19c4efa881084156efa`；`aa4d9731196da6a2ec0d174aaf1dc656a0f0640017ba8ed65a4b75fc63793114` | `bash plan/tests/test_validate_ch3_p00.sh`；`LC_ALL=C.UTF-8 LANG=C.UTF-8 bash plan/scripts/validate_ch3_p00.sh` | 0 | `plan/review/ch3-p00-t04-gate-validation.md` | `b2c3fbc9020a163e93400f70a3711f09a2a6b68a2c0462057b3412b0bb373dac` | 2026-09-04T06:26:03Z | 无 |
| D2 | ch3.d2.output_contract | open | closed | D0、D1 | `38f31084c9584b6a2c35690f017ff33b60601d75e4804080d357374b059d6a6a`；`a4f852395340f46f4cf8066f5d2099e7bfef98736b2af19c4efa881084156efa`；`aa4d9731196da6a2ec0d174aaf1dc656a0f0640017ba8ed65a4b75fc63793114`；`d071c73ac3e1625796879632778a56c59c3c71326d0e5dab79d48750755fd7b0` | `bash plan/tests/test_validate_ch3_p00.sh`；`LC_ALL=C.UTF-8 LANG=C.UTF-8 bash plan/scripts/validate_ch3_p00.sh` | 0 | `plan/review/ch3-p00-t04-gate-validation.md` | `b2c3fbc9020a163e93400f70a3711f09a2a6b68a2c0462057b3412b0bb373dac` | 2026-09-04T06:26:03Z | 无 |

## 4. 门禁总览

- [x] **D0：实验协议锁定**
- [x] **D1：方法—实验追溯锁定**
- [x] **D2：表格与图片数据合同锁定**
- [ ] **D3：正式结果完整**
- [ ] **D4：结果交付无污染**
- [ ] **D5：同行评审与冻结通过**

## 5. D0：实验协议锁定

**关闭 Phase：** CH3-P00，由 Task CH3-P00-T04 统一验证和关闭。  
**当前状态：** 已关闭。CH3-P00-T04 已验证 T01-T03、协议范围、占位词、禁止项和输入 SHA；证据记录见第 3 节。

**必需条件：**

- `plan/experiment-protocol.md` 锁定 MetroPT-3、FD004、TEP 的角色、划分、窗口、seeds、缺失设置和训练边界。
- 六模型主对比、四模型鲁棒性/外部验证、E0/E1/E4/E5/E1-X/E6、指标和统计单位均无未决内容。
- 公平性、防泄漏、point-only 边界、formal 资格和 artifact 追溯要求完整。
- CH3-P00-T01、T02、T03 的完成框和所有必做步骤均已验证并勾选。
- CH3-P00-T04 的范围、占位词和一致性检查退出码为 0，并登记协议 SHA。

## 6. D1：方法—实验追溯锁定

**关闭 Phase：** CH3-P00，由 Task CH3-P00-T04 统一验证和关闭。  
**当前状态：** 已关闭。追溯表机制、实验路由、允许结论与降级规则已由 CH3-P00-T04 验证；证据记录见第 3 节。

**必需条件：**

- `plan/review/method-experiment-traceability.md` 存在，字段为 `Contribution | Method module | Experiment | Table/Figure | Allowed claim | Evidence status`。
- 真实时间、mask、`delta_t`、通道身份、工况、多尺度和跨传感器交互均映射到实验与表图。
- 每项机制都有证据缺失时的结论降级规则，不保留无实验或局限说明支撑的强结论。
- 追溯表验证命令、退出码和文件 SHA 已登记。

## 7. D2：表格与图片数据合同锁定

**关闭 Phase：** CH3-P00，由 Task CH3-P00-T04 统一验证和关闭。  
**当前状态：** 已关闭。8 张表与 5 张图的数据合同、唯一 source CSV、输出格式和 profile 白名单已由 CH3-P00-T04 验证；证据记录见第 3 节。

**必需条件：**

- `tables/table-schema.md` 完整定义 Ch3-T1 至 Ch3-T8 的主键、字段、单位、聚合、来源和允许结论。
- `figures/data-manifest.md` 完整定义 Ch3-F1 至 Ch3-F5 的 source CSV、脚本、SVG 和 300 dpi PNG。
- 所有表图只能消费有 provenance 的聚合数据；无 mock、手填值或 legacy Table 1-7 入口。
- 表图编号和数据合同验证命令、退出码及文件 SHA 已登记。

## 8. D3：正式结果完整

**关闭 Phase：** CH3-P13，由 Task CH3-P13-T07 关闭。  
**当前状态：** 未关闭。

**必需条件：**

- P08-P12 的 198 个 expected formal matrix keys 与 validated keys 完全一致，映射到 165 个唯一 formal source runs。
- 14 个 sensitivity factor-views 全部可解析；18 个效率 profile 在独立 catalog 中完整且不计入 formal run 数。
- formal/profile 无缺失、重复、orphan、cross-level、非法 hash、绝对路径或未计划 key。
- MetroPT-3、FD004、TEP 的 bootstrap unit 分别为预注册时间块、engine、`faultNumber:simulationRun`。
- coverage report、catalog、protocol/config/code SHA 和验证命令已绑定同一 candidate 输入。

## 9. D4：结果交付无污染

**关闭 Phase：** CH3-P13，由 Task CH3-P13-T07 与 D3 同批关闭。  
**当前状态：** 未关闭。

**必需条件：**

- Ch3-T1 至 Ch3-T8、Ch3-F1 至 Ch3-F5 编号完整、无重号和缺号，图片同时具有 SVG 与 300 dpi PNG。
- 所有表格和 figure source 可从 formal/profile catalogs 确定性重建，每个数值具有闭合 provenance。
- candidate bundle 不含 mock、fixture、smoke、tuning、规划提示、手填数字或 legacy 输出。
- 同一输入在全新临时输出根重建得到相同 bundle SHA，且发布过程不留下半成品。

## 10. D5：同行评审与冻结通过

**关闭 Phase：** CH3-P14，由 Task CH3-P14-T05 原子关闭。  
**当前状态：** 未关闭。

**必需条件：**

- D3、D4、evidence bundle、两份 reviewer decision 和 freeze 均绑定同一 candidate SHA。
- 方法统计与复现 artifact 两个不同 reviewer ID 均为 approved，open blocking/major finding 数为 0。
- freeze bundle 不可覆盖，manifest 无机器绝对路径或固定远程地址，并在新进程二次验签通过。
- 最终 gate report 字段、证据 SHA、review SHA、freeze manifest SHA 和 verify report SHA 完整有效。
- updater 只原子修改最终 apply step、D5、Task CH3-P14-T05 和 Phase CH3-P14 四个 marker；其他必做框必须已勾选。
