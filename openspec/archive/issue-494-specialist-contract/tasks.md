# Tasks — issue-494-specialist-contract

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/494` branch `v012/issue-494-specialist-contract` off `origin/dev` 59806b9(#492 Gate 6 标记已在)
- [x] 1.2 必读:plan(R2 Task 2 / 验收方法 A)/ issue #494 + #462 原文 / kunglao-worker.md 模板(12 plan + 6 status + 2 tool-reuse)/ 7 specialist 的 #492 最小块 / devkit/agents_lint.py 标记文法 / tools/_INDEX.yaml 工具名 / hooks/lib_kunglao.py #444 canonical 语义

## 2. SDD

- [x] 2.1 proposal.md(#462 证据 + 三改动面 + 7 文件清单)
- [x] 2.2 design.md(D1 骨架+领域实例化 / D2 工具名可解析 / D3 token 断言纪律 / D4 status 命名标准化 / D5 验收映射 / R1-R5)
- [x] 2.3 tasks.md(本文件)

## 3. RED(先写,必须红)

- [x] 3.1 `tests/test_specialist_contract_expansion.py` — span 提取复用 agents_lint(`_marker_spans` + `_COMMENT_RE`,零第二解析点)
- [x] 3.2 plan span 断言:`runs/worker-status-{agent}` / plan / expected / done + 每 agent 领域 token
- [x] 3.3 status span 断言:#444 三词 / `artifacts:` / heartbeat / `lib_kunglao`
- [x] 3.4 tool span 断言:`scripts/re` / `_INDEX.yaml` / re-library(5 RE)或 `references/`(2 非 RE)/ issue / shim / 工具名行 ≥3 全可解析(_INDEX ∪ scripts)
- [x] 3.5 确认 RED + commit(哈希记 §5;重放 = 检出 1f6e7bf 的 tests/ 跑本文件,77 failed / 0 passed)

## 4. GREEN(span 内 additive,零重写)

- [x] 4.1 ghidra-light.md 三 span 扩写(反编译目标 + pseudo-C / static-ghidra.json artifacts / ghidra-recon 等域工具)
- [x] 4.2 go-symbols.md 三 span 扩写(unstrip 序列 + 四产物 / go-buildinfo-carve 等)
- [x] 4.3 floss-filter.md 三 span 扩写(数据驱动阈值 + top-K / strings-classify 等)
- [x] 4.4 pefile-signature.md 三 span 扩写(Authenticode+packer 双产物 / pe-analyze 等)
- [x] 4.5 verdict-scorer.md 三 span 扩写(PQ 清单 + verdict 结构 / 门输出只读消费)
- [x] 4.6 kunglao-init-worker.md 三 span 扩写(intake 顺序 + toolchain 门 / kunglao-init.py 等 CLI)
- [x] 4.7 kunglao-redteam.md 三 span 扩写(攻击计划 + verify-redteam 产物 / disasm-constant-check 等)
- [x] 4.8 既有 prose / frontmatter / triggers 零改动核验(diff 只增不改)

## 5. 门禁(REFACTOR 后)

- [x] 5.1 RED 哈希:记录于 PR body(重放:检出该哈希的 tests/ 跑新测试文件全红)
- [x] 5.2 `uv run ruff check .` 零 finding
- [x] 5.3 快速门 `uv run python -m pytest -q -m "not load_sensitive" tests/test_agents_lint.py tests/test_specialist_gate.py tests/test_specialist_contract_expansion.py` 全绿(既有路由不破)
- [x] 5.4 `uv run python devkit/quality_gates.py 1 3 4 5 6` → ALL-PASS(worktree 本地副本)
- [x] 5.5 Gate 5:`.subagent-review/2026-08-20-494.json`(五字段,verified_by=pending-494-reviewer,待 reviewer 回填)

## 6. 产出

- [x] 6.1 `.review/RUNBOOK.md`(改动清单 / 测试映射 / 门禁结果 / 自认风险)— 永不提交
