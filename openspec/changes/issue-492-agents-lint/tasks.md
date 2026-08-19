# Tasks — issue-492-agents-lint

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/492` branch `v012/issue-492-agents-lint` off `origin/dev` c5cb1ae
- [x] 1.2 必读:plan(R2 Task 2 / 验收方法 A)/ issue #492 + #462 拆件关系 / 结构化声明教义(memory)/ agents/ 全部 8 文件 / subagent_review.py DOMAIN_PREFIXES 先例 / quality_gates.py GATES 注册模式 / kunglao-worker.md 模板基准 / issue-497 SDD 镜像

## 2. SDD

- [x] 2.1 proposal.md(#462 证据 + 三改动面 + 8 文件实测数)
- [x] 2.2 design.md(D1 通道二选一 / D2 lint 语义 / D3 Gate 6 vs 子检查 / D4 drift 三载体 / D5 验收映射 / R1-R5)
- [x] 2.3 tasks.md(本文件)

## 3. RED(先写,必须红)

- [x] 3.1 `tests/test_agents_lint.py` — lint_text 纯函数(缺失×3 参数化 / 空心 / 存根 / 空行不计 / 弹性空白 / 裸复制 / 围栏豁免 / 边界 2 行过)
- [x] 3.2 lint_dir fail-closed(缺目录 / 零 .md)+ 真仓集成(8 文件全过)
- [x] 3.3 CLI --json(violations 带 file+element,rc 契约)
- [x] 3.4 Gate 接线(GATES[6] 注册 / pre-commit 模板 `1 3 4 5 6` / quality_gates docstring 无 stale 门数)
- [x] 3.5 确认 RED + commit(哈希记本文件 §5)

## 4. GREEN

- [x] 4.1 `devkit/agents_lint.py`(标记文法 + span 计数 + 围栏豁免 + fail-closed + --json)
- [x] 4.2 `devkit/quality_gates.py` Gate 6 注册 + docstring 门数派生表述
- [x] 4.3 `devkit/githooks/pre-commit` 门列表 1 3 4 5 6(两处)+ 头注释全列
- [x] 4.4 agents/kunglao-worker.md 三标记贴既有节(零新 prose)
- [x] 4.5 其余 7 agent 文件尾追加最小契约块(现有 prose 提炼,不重写)
- [x] 4.6 tests/test_devkit_quality_gates.py docstring 门数描述同步(行为不动)

## 5. 门禁(REFACTOR 后)

- [x] 5.1 RED 哈希:记录于 PR body(重放:检出该哈希的 tests/ 跑新测试文件全红)
- [x] 5.2 `uv run ruff check .` 零 finding
- [x] 5.3 快速门(域文件)`uv run python -m pytest -q -m "not load_sensitive" tests/test_agents_lint.py tests/test_subagent_review.py tests/test_devkit_quality_gates.py` 全绿
- [x] 5.4 `uv run python devkit/quality_gates.py 1 3 4 5 6` → ALL-PASS(worktree 本地副本)
- [x] 5.5 Gate 5:`.subagent-review/2026-08-19-492.json`(五字段,verified_by=pending-492-reviewer,待 reviewer 回填)

## 6. 产出

- [x] 6.1 `.review/RUNBOOK.md`(改动清单 / 测试映射 / 门禁结果 / 自认风险)— 永不提交
