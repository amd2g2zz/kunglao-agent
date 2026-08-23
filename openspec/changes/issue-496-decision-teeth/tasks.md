# Tasks — issue-496-decision-teeth

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/496` branch `v012/issue-496-decision-teeth` off `origin/dev` 4b07bba
- [x] 1.2 必读: plan(Task 2 / Patterns / 验收 A)/ issue #496 + 评论区(#499 已裁决: priority_ratio 唯一权威)/ #498 目标架构 / failure_analysis_gate.py(#495 三产物)/ dispatch_gate.py(#447/#452/#495 切片)/ worker_budget.py(check_priority + agenttype #310)/ priority_ratio.py(EvidenceView)
- [x] 1.3 边界判定: 不改 failure_analysis_gate 记录面;SKILL.md 不动(冲突热点,标记文档进 references/dispatch-protocol.md)

## 2. SDD

- [x] 2.1 proposal.md(三牙: top-1 强制 / 类型化事实消费 / strategy novelty)
- [x] 2.2 design.md(D1 top1 复制 agenttype 模式 / D2 能力看牌 / D3 障碍 leverage 钉住 / D4 strategy 接口 / D5 验收映射 / R1-R5)
- [x] 2.3 tasks.md(本文件)

## 3. RED(先写,必须红)

- [x] 3.1 `tests/test_decision_teeth.py` — 新 API 一律函数体内引用(非 import 期),保证 collect 成功、逐条 test failed
- [x] 3.2 确认 RED: `uv run python -m pytest -q tests/test_decision_teeth.py` — 13 failed / 4 passed(4 个 green-on-arrival: top-1 静默 guard、failure-blocked 切片 guard、2 个 PIN 钉住测试,钉的是 #495 以来 ratio 的自然消费,见 design D3),commit `test: RED decision teeth gates (#496)` = 98c46ec
- [x] 3.3 RED 哈希 98c46ec 已记录(本文件 + RUNBOOK / PR body)

## 4. GREEN

- [x] 4.1 `scripts/priority_ratio.py`: EvidenceView 四新字段(validated_capabilities / identified_obstacles / strategy_failures / claim_strategy)+ from_workspace 读 analyses/ 与 runs/strategy-log.jsonl(逐文件 fail-open)+ TOOL_FAMILIES / tool_families_from_tools / tool_families_from_text / capability_switch_violation 纯函数 + novelty 消费 strategy 失败
- [x] 4.2 `hooks/dispatch_gate.py`: `_top1_enforcement`(复用 worker_budget.check_priority,单一排名源)/ `_capability_guard`(含 obstacle_for 父链)/ `_log_strategy_dispatch`;main 接线顺序 must-stop → failure-blocked → top1 → capability → strategy-log
- [x] 4.3 `references/dispatch-protocol.md`: 三个 prompt 标记声明语义(additive)
- [x] 4.4 快速门: `uv run python -m pytest -q -m "not load_sensitive" tests/test_dispatch*.py tests/test_worker_budget.py tests/test_scorer_authority.py tests/test_priority_ratio.py tests/test_decision_teeth.py` — 全绿

## 5. 门禁与产出

- [x] 5.1 `uv run ruff check .` 零红
- [x] 5.2 `uv run python devkit/quality_gates.py 1 3 4 5` ALL-PASS(Gate 5: `.subagent-review/2026-08-19-496.json` 五字段,verified_by=pending-496-reviewer)
- [x] 5.3 `.review/RUNBOOK.md`(改动清单 / 测试映射 / 自认风险 / 复现命令)— 永不 commit
