# Task Packet

## Scope

落实毕业论文文献阅读报告与文献汇总计划，输出 Markdown 文献阅读报告、文献汇总表和现有文献核验与增补建议。

## Files Read

- `/Users/ppy/研/23管科谭海锋_文献阅读报告.pdf`
- `24810511012_彭玥_开题报告.doc`
- `3.2_结构框架.md`
- `统一对比实验方案.md`
- `开题报告修改建议_基于3.2结构框架.md`

## Files Edited

- `文献阅读报告.md`
- `文献汇总表.md`
- `现有文献核验与增补建议.md`
- `plan/task-packets/literature_reading_report.md`
- `plan/progress.md`

## Required Skills

- using-research-writing
- paper-orchestration
- literature-review
- nature-academic-search
- writing-core
- verification

## Evidence Inputs

- 样本文献阅读报告的三专题结构
- 开题报告现有 31 条参考文献
- 新版毕业论文结构
- 统一实验方案中的 baseline、数据集和指标口径

## Required Artifacts

- 三专题文献阅读报告
- 所有文献汇总表
- 现有文献核验和增补建议

## Rejection Checks

- 不编造文献。
- 每条英文核心文献必须给 DOI、arXiv、OpenReview、PMLR、NeurIPS、UCI、NASA 或 Dataverse 等可追溯链接。
- 中文文献无法公开核验时必须标记需 CNKI 复核。
- 不将无法核验的 tPatchGNN 写入正式核心文献。

## Validation Commands

- `python3` + `pypdf` 提取样本 PDF 文本
- `textutil` 提取开题报告参考文献
- `rg` 检查文件中是否存在待补占位符和断裂编号
