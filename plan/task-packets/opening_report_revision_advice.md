# Task Packet

## Scope

根据 `3.2_结构框架.md` 与 `开题报告_2_3_6对应修改建议.md`，审阅初稿开题报告并形成可操作修改建议。

## Files Read

- `24810511012_彭玥_开题报告.docx`
- `3.2_结构框架.md`
- `开题报告_2_3_6对应修改建议.md`
- `补充建议.md`
- `统一对比实验方案.md`
- `KAFNet-ProFITi工业异步传感器状态预测缝合方案.md`

## Files Allowed To Edit

- `开题报告修改建议_基于3.2结构框架.md`
- `plan/project-overview.md`
- `plan/outline.md`
- `plan/progress.md`
- `plan/task-packets/opening_report_revision_advice.md`

## Required Skills

- research-writing workflow
- writing-core
- peer-review
- documents read/review

## Required Artifacts

- 一份 Markdown 修改建议
- 轻量过程记录

## Rejection Checks

- 不直接重写 Word 初稿。
- 修改建议必须对应第 2、3.1、3.3、6 节和新版 3.2 结构。
- 明确指出现稿与新版结构不一致的地方。

## Validation Commands

- 文本抽取：`textutil -convert txt -output /private/tmp/kaiti_report_extracted.txt 24810511012_彭玥_开题报告.docx`
- 内容检查：`sed` / `rg`
