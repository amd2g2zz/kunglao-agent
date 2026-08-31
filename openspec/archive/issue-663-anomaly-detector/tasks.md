# Tasks — issue-663-anomaly-detector (gap-fill)

## 1. Setup

- [x] 1.1 Worktree `D:/codebase/kunglao-issue-663-anomaly-detector` branch `issue-663-anomaly-detector` off `origin/dev` c09f36c
- [x] 1.2 必读:`scripts/progress_report.py`(132 行,本次修改目标)、`scripts/anomaly_detector.py:332-374`(_write_anomaly_note 写出 notes/ frontmatter 形态)、`openspec/changes/issue-449-init-needs-first/{proposal,tasks}.md`(三件套结构模板)、issue #663 验收 4 条

## 2. SDD

- [x] 2.1 proposal.md(三件套精简,Why 引用 issue 验收 #3 + 已知主 PR #666 已就位 / What Changes 限 progress_report.py + 1 个新测试文件 / Impact 含契约 additive 标注 / 不做列三条)
- [x] 2.2 tasks.md(本文件)
- [x] 2.3 无 design.md(本卡为单文件单行 additive,无架构决策——已记 proposal "不做" 段;沿用 anomaly_detector.py 的 fail-open 双通道 frontmatter 解析约定)

## 3. RED (先写, 必须红)

- [x] 3.1 `tests/test_progress_report_663.py::test_anomaly_count_three_yaml_block` — 三个 note 含 `boundary_type: anomaly` YAML 块 + 一个普通 note → 输出含 `## Anomalies: 3`(红→绿)
- [x] 3.2 `test_anomaly_count_zero_no_notes_dir` — 无 notes/ → 计数 0 且不抛(红→绿)
- [x] 3.3 `test_anomaly_count_mixed_frontmatter_forms` — YAML 块 + line-level 两种 frontmatter 都被识别(红→绿)
- [x] 3.4 确认 RED: `uv run python -m pytest -q tests/test_progress_report_663.py` 3 例全红(2dcf8ac 提交信息含原始输出摘要)

## 4. GREEN

- [x] 4.1 `scripts/progress_report.py` 加 `_count_anomaly_notes(workspace) -> int` helper(双通道 frontmatter 解析,无 notes/ → 0;所有 IO 异常 fail-open)
- [x] 4.2 `report()` 在 Blockers 行后插 `## Anomalies: {n} observation notes (notes/*.md with boundary_type: anomaly)`;整段 try/except 兜底返回 0
- [x] 4.3 快速门: `uv run python -m pytest -q tests/test_progress_report_663.py` 3 例全绿(068ddac)

## 5. 验证

- [x] 5.1 `uv run python devkit/quality_gates.py` 7 门 — Gate 2 = 7 failed (基线 c09f36c 已知红: probe_tiers×2 + ledger 5;**未新增**失败);Gate 1/3/4/5/6/7 全 PASS
- [x] 5.2 `tests/test_anomaly_detector.py` 仍全绿(15/15 相关测试全绿: 本卡 3 + anomaly_detector 9 + progress_txt 3)
- [x] 5.3 手工跑 `python scripts/progress_report.py /tmp/progress-smoke` 确认 `## Anomalies: 1 observation notes` 出现在输出中

## 6. 产出

- [x] 6.1 三段 commit: ① 47f87e1 docs(工件) ② 2dcf8ac test(RED) ③ 068ddac feat(GREEN);(本任务卡范围外,不自行 push / mint review gate / merge)
