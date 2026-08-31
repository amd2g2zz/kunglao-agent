# Tasks — issue-495-failure-transducer

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/495` branch `v012/issue-495-failure-transducer` off `origin/dev` 5e185a2
- [x] 1.2 必读:plan(R2 Task 2 / 验收方法 A / 双轨迹重演风险行)/ issue #495 / #498 目标架构 / failure_analysis_gate.py 全文 / test_failure_lessons.py / issue-444 SDD 三件套 / pytest.ini / devkit Gate 5 契约

## 2. SDD

- [x] 2.1 proposal.md(轨迹1 证据 + 四机制缺口 + 改动面)
- [x] 2.2 design.md(D1 协议 v2 / D2 升格 / D3 梯级 1 fail-open / D4 provenance / D5 验收映射 / R1-R5)
- [x] 2.3 tasks.md(本文件)

## 3. RED(先写,必须红)

- [x] 3.1 `tests/test_failure_analysis_transducer.py` — 三产物记录 / 升格 + DAG 边 / 幂等 / 部分产物不解锁(4 例)
- [x] 3.2 梯级 1 注入 candidates + 留痕 + fail-open(2 例)
- [x] 3.3 provenance:缺 source / 非法枚举 / novel 前置(3 例)
- [x] 3.4 BLOCKED 收紧:瞬态失败×2 + 判死宣告(无三产物)仍 BLOCKED + missing_artifacts 诊断;补齐产物后 OK_COVERED(2 例)
- [x] 3.5 CLI 接线:缺 source 拒绝 / 全链路 record→升格(2 例)
- [x] 3.6 确认 RED:全部 13 例 failed(9×TypeError / 2×旧语义误判 OK_COVERED / 2×CLI unrecognized,非 collect error),commit 6670d05

## 4. GREEN

- [x] 4.1 `SOURCE_VALUES` + `record_analysis` 扩参(closure 保留规则对齐 #41)
- [x] 4.2 `_promote_obstacle_claim` + `_next_claim_id`(幂等判重键 obstacle_for;claim_deps.yaml 写边)
- [x] 4.3 `_analysis_covers` 收紧(missing_artifacts 诊断 + `_print_blocked` 第 4/5 问)
- [x] 4.4 梯级 1 接线(`_ladder_candidates` fail-open;method_ladder_query 留痕)
- [x] 4.5 CLI 三旗(--validated-capability / --identified-obstacle / --source;--library 透传)
- [x] 4.6 既有测试契约迁移:test_failure_lessons._record 助手带三产物默认值;key-set 断言更新;taxonomy cleared-fixture 补产物
- [x] 4.7 docstring v2.0.0(三问 + 三产物 + provenance 用法样例)

## 5. 门禁(REFACTOR 后)

- [x] 5.1 `uv run ruff check .` 零 finding
- [x] 5.2 快速门(域三文件)41 passed;全仓快速门对照基线零新增失败(基线 8 failed / 2240 passed,post-fix 地板 7)
- [x] 5.3 `uv run python devkit/quality_gates.py 1 3 4 5` → ALL-PASS(worktree 本地副本)
- [x] 5.4 Gate 5:`.subagent-review/2026-08-19-495.json`(五字段,verified_by=pending-495-reviewer,待 Task 3 reviewer 回填)

## 6. 产出

- [x] 6.1 `.review/RUNBOOK.md`(改动清单 / 测试映射 / 门禁结果 / 兼容性 / 自认风险 / 复现命令)— 永不提交
