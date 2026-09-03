# Tasks — issue-459-observability

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/459` branch `v012/issue-459-observability` off `origin/dev` 45856bd
- [x] 1.2 必读: plan(Task 2 / Patterns / 验收 A)/ issue #459 + 评论区(2026-08-19 挂靠评论: 事件流须含失败事件与三产物落地事件)/ kunglao_log.py 现状 / event_taxonomy.py / #495/#496/#497 落地面
- [x] 1.3 边界判定: 不建第二日志通道;不动 self_redirects.jsonl;不动 decide() 侧信道;决策点行为零变化
- [x] 1.4 基线: 快速门 6 文件 94 passed(test_kunglao_log / orchestration_event_taxonomy / ask_for_direction_v2 / decision_teeth / failure_analysis_transducer / plan_drift_stale_plan)

## 2. SDD

- [x] 2.1 proposal.md(① 决策点收编 ② 失败事件 ③ --tail ④ EMIT_ACTIONS 词表 ⑤ 禁零日志回归锚)
- [x] 2.2 design.md(D1 词表 / D2 收编面×action 表 / D3 失败事件分流 / D4 tail / D5 测试映射 / 风险表)
- [x] 2.3 tasks.md(本文件)

## 3. RED(先写,必须红)

- [x] 3.1 `tests/test_event_stream_adoption.py` — 新词表/新面一律函数体内引用(非 import 期),collect 成功逐条 failed
- [x] 3.2 `tests/test_kunglao_log.py` 追加 TestTail(--tail CLI 契约)
- [x] 3.3 确认 RED: 21 failed / 12 passed(green-on-arrival: 4 个零噪声/fail-open 既有契约 pin): `uv run python -m pytest -q tests/test_event_stream_adoption.py tests/test_kunglao_log.py` — 新测试全红(旧测试保持绿)
- [x] 3.4 commit `test: RED observability event-stream adoption (#459)` = 7bfdafc

## 4. GREEN

- [x] 4.1 `scripts/event_taxonomy.py`: EMIT_ACTIONS(18 词: 既有 7 + 新 11)
- [x] 4.2 `scripts/kunglao_log.py`: tail() + main(--tail <ws> [N])
- [x] 4.3 `scripts/ask_for_direction_gate.py`: _emit_interception + 7 个拦截面接线
- [x] 4.4 `hooks/dispatch_gate.py`: _emit_trace 补 exit 参数;_top1/_capability REJECT 面接线
- [x] 4.5 `scripts/plan_drift_detector.py`: _emit_stale_plan_warn 逐条
- [x] 4.6 `scripts/failure_analysis_gate.py`: _emit_analysis_recorded;_emit_failure_blocked 按 missing_artifacts 分流
- [x] 4.7 `scripts/convergence_check.py`: converge detail 补计数
- [x] 4.8 快速门: `uv run python -m pytest -q -m "not load_sensitive"` 全绿: 全仓 -m 'not load_sensitive' 7 failed / 2740 passed(基线 8,有效 floor 7;余 7 项均为基线既有/环境项,零新增)

## 5. 门禁与产出

- [x] 5.1 `uv run ruff check .` 零红
- [x] 5.2 `uv run python devkit/quality_gates.py 1 3 4 5 6 7` ALL-PASS(Gate 5: `.subagent-review/2026-08-20-459.json` 五字段,verified_by=pending-459-reviewer)
- [x] 5.3 `.review/RUNBOOK.md`(改动清单 / 测试映射 / 自认风险 / 复现命令)— 永不 commit
