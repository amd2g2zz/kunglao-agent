# Tasks — issue-497-decision-grammar-v2

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/497` branch `v012/issue-497-decision-grammar-v2` off `origin/dev` 4b07bba
- [x] 1.2 必读:plan(R2 Task 2 / 验收方法 A / 风险"双轨迹重演测试过度拟合"行)/ issue #497 / #498 目标架构 / charter + ask_for_direction_gate.py 全文 / plan_drift_detector.py + 硬禁止#4 两载体 / #495 落地字段(failure_analysis_gate.py)/ issue-444 SDD 模板 / pytest.ini / devkit Gate 5 契约

## 2. SDD

- [x] 2.1 proposal.md(双轨迹证据 + 三机制根因 + 四改动面)
- [x] 2.2 design.md(D1 拆组+梯耗尽 / D2 TYPE_E 证据判据 / D3 事件流窗口 / D4 WARN+白名单 / D5 验收映射 / R1-R6)
- [x] 2.3 tasks.md(本文件)

## 3. RED(先写,必须红)

- [x] 3.1 `tests/test_ask_for_direction_v2.py` — TYPE_D blocker 降级/梯耗尽/回归(6 例)
- [x] 3.2 TYPE_E 判死:zh+en 参数化无证据拦截 + obstacle REFUTED / analysis outcome REFUTED 放行(5 例)
- [x] 3.3 plan-stall:单发拦截 / 动作清窗 / 无冒号零回归 / 3-strike 不污染(6 例)
- [x] 3.4 双轨迹重演(行为等价类):轨迹1 判死链 / 轨迹2 搁浅链(2 例)
- [x] 3.5 `tests/test_plan_drift_stale_plan.py` — WARN 触发 / 不触发 / 不升级 / 与硬漂移共存(7 例)
- [x] 3.6 确认 RED:34 例中 23 failed(新行为全红;11 例回归守护绿),commit cc8239e(重放验证: 独立 worktree 检出该哈希,23 failed / 11 passed 复现)

## 4. GREEN

- [x] 4.1 `TYPE_D_BLOCKER_PATTERNS` 拆组 + `find_ladder_exhaustion`(#495 字段消费)
- [x] 4.2 `TYPE_E_PATTERNS` + `find_death_evidence` + check() 分支
- [x] 4.3 plan-stall:声明/动作事件 + 轮次窗口 + 计数器前缀过滤
- [x] 4.4 `plan_drift_detector.find_stale_plan_on_new_evidence` + WARN 输出路径
- [x] 4.5 charter v2(授权边界行改态 / 判死+搁浅两行 / Type E 字母 / 执行器行 / 变更记录)
- [x] 4.6 硬禁止#4 白名单:rules + SKILL.md 两载体同步翻转
- [x] 4.7 docstring 更新(两脚本头部契约)

## 5. 门禁(REFACTOR 后)

- [x] 5.1 `uv run ruff check .` 零 finding
- [x] 5.2 快速门(域文件)`uv run python -m pytest -q -m "not load_sensitive" tests/test_ask_for_direction*.py tests/test_plan_drift*.py` 全绿
- [x] 5.3 `uv run python devkit/quality_gates.py 1 3 4 5` → ALL-PASS(worktree 本地副本)
- [x] 5.4 Gate 5:`.subagent-review/2026-08-19-497.json`(五字段,verified_by=pending-497-reviewer,待 Task 3 reviewer 回填)

## 6. 产出

- [x] 6.1 `.review/RUNBOOK.md`(改动清单 / 测试映射 / 门禁结果 / 自认风险)— 永不提交
