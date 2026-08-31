# Tasks — issue-446-governance-fg

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/446` branch `v012/issue-446-governance-fg` off `origin/dev` 59806b9
- [x] 1.2 必读:plan(R2 Task 2 / 验收方法 A)/ issue #446 正文 + 2026-08-19 两条细化评论 / re_pin_references.py / quality_gates.py GATES 模式 / githooks/pre-commit / rules/kunglao-convergence-loop.md / agent-three-state-charter.md
- [x] 1.3 现状 grep:4-gate 措辞余量(评论区 6 处中 quality_gates.py:3/:5 与 pre-commit:2/:4/:9 已被 #492 修;余量 = devkit/README.md×5、devkit/docs/README.md×2、quality_gates.md×6、quality_roadmap.md×4、unit_test_spec.md×1、release-check.yml×3,合计 21 行[口径:基点 4bd9102,scan_gate_count_claims 正则全 face 扫描,2026-08-20 F1 修正:原记 18 漏计 quality_gates.md×3],另 README.md:70 id 列表过期)

## 2. SDD

- [x] 2.1 proposal.md(F+G 范围 + 漂移余量实测 + 不做面)
- [x] 2.2 design.md(D1 Gate 7 挂点 / D2 扫描面 / D3 number-free 语义 / D4 staged-content 重钉检测 / D5 WARN / D6 符号锚 / D7 活性台账 / D8 风险)
- [x] 2.3 tasks.md(本文件)

## 3. RED(先写,必须红)

- [x] 3.1 `tests/test_doc_sync.py` — 计数声明扫描(4-gate/The 4 Gates/4 门/N-gate 大小写 / 干净树过 / 面外不扫)+ Gate 7 注册(GATES[7] "Doc Sync" / _gate7 存在 / pre-commit 模板门列表 == 注册表-{2})+ references 重钉(md 无 yaml → rc=2;stale pin → rc=2;新文件无 pin → rc=2;重钉后 → rc=0)+ 新脚本登记 WARN(未登记 → WARN 且 rc=0;已登记 → 无 WARN)+ 输出 GBK 控制台安全
- [x] 3.2 `tests/test_decision_surface_anchor.py` — CHARTER_SOURCE/CHARTER_STATES 声明 / _CHARTER_STATE 值域锁步 / charter↔code 互指存在 / taxonomy↔code 类名锁步(UNCLASSIFIED↔未分类)
- [x] 3.3 确认 RED + commit(哈希记 §6)

## 4. GREEN

- [x] 4.1 `devkit/doc_sync.py`(扫描 + staged 重钉 + WARN 三检查,rc 0/1/2,编码安全输出)
- [x] 4.2 `devkit/quality_gates.py` Gate 7 注册 + docstring 门语义段("Doc Sync" 名入 docstring — lockstep 测试要求)
- [x] 4.3 `devkit/githooks/pre-commit` 门列表两处 `1 3 4 5 6 7` + 头注释 Gate 7 行
- [x] 4.4 漂移余量修复(21 行 number-free 化 + devkit/README.md:70 id 列表改 hook 模板指向)
- [x] 4.5 `scripts/error_response.py` 锚常量(CHARTER_SOURCE/CHARTER_STATES;行为零改动)
- [x] 4.6 `references/agent-three-state-charter.md` 执行器表 +1 行
- [x] 4.7 `references/_INDEX.md` lessons 条目 + `skills/kunglao-agent/SKILL.md` 一行 pointer
- [x] 4.8 `uv run python scripts/re_pin_references.py` 重钉 `_INDEX.yaml`
- [x] 4.9 `mechanisms-status.md`(SKILL.md MUST 逐条 implemented/pending,grep 佐证)

## 5. 门禁(REFACTOR 后)

- [x] 5.1 `uv run ruff check .` 零 finding
- [x] 5.2 快速门 `uv run python -m pytest -q -m "not load_sensitive" tests/test_doc_sync.py tests/test_decision_surface_anchor.py tests/test_devkit_quality_gates.py tests/test_agents_lint.py tests/test_subagent_review.py tests/test_replay_gate.py tests/test_error_response.py`
- [x] 5.3 `uv run python devkit/quality_gates.py 1 3 4 5 6 7` → ALL-PASS(worktree 本地副本)
- [x] 5.4 Gate 5:`.subagent-review/2026-08-20-446.json`(五字段,verified_by=pending-446-reviewer,待 reviewer 回填)

## 6. 产出

- RED 哈希:`4bd9102`(tests + doc_sync 骨架;重放:`git checkout 4bd9102 -- tests/ devkit/doc_sync.py` 后跑两个新测试文件 → 22 failed / 14 passed[负对照])
- 漂移修复余量清单:见 1.3;修复面 = devkit/README.md、devkit/docs/{README,quality_gates,quality_roadmap,unit_test_spec}.md、.github/workflows/release-check.yml
- 活性台账:design.md §D7
- spec-实现 gap 台账:`openspec/changes/issue-446-governance-fg/mechanisms-status.md`
- RUNBOOK:`.review/RUNBOOK.md`(永不提交)
