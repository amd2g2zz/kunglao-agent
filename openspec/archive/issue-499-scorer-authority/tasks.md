# Tasks — issue-499-scorer-authority

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/499` branch `v012/issue-499-scorer-authority` off origin/dev 5e185a2
- [x] 1.2 必读:plan(Patterns to Mirror / Task 2 流水 / 验收方法 A)/ issue #499 / specs/phase-4/contract.md §1 / priority_ratio.py / priority.py / worker_pulse.py:55,244 / worker_budget.py:55-62,172-201 / openspec/changes/issue-444-worker-liveness/(镜像)
- [x] 1.3 穷尽 consumer grep(priority_ratio + priority 全仓:hooks/scripts/skills/references/rules/tests;结论入 proposal + issue #499 评论)

## 2. SDD

- [x] 2.1 proposal.md(双评分证据 + 权威判据 = spec 血统 + consumer 矩阵)
- [x] 2.2 design.md(D1 双 live 面同源 / D2 caller 侧过滤 / D3 降级=声明面 / D4 文本翻面清单 / D5 判别性 fixture / R1-R6)
- [x] 2.3 tasks.md(本文件)

## 3. RED(先写,必须红)

- [x] 3.1 tests/test_scorer_authority.py 六测(pulse e2e 判别 / failure-blocked+terminal 过滤 / check_priority 方向 / deprecated 面 / 静态 live 面 / subprocess 目标)
- [x] 3.2 确认 RED:quick 门 6 failed(pulse 推 C-A、审计方向反、常量缺失、静态面旧文本),commit "test: RED live path scores via priority_ratio (#499)" 哈希记录

## 4. GREEN

- [x] 4.1 hooks/worker_pulse.py:next-up 子进程切 priority_ratio.py + shape 适配(claim_id/action/score)+ caller 过滤(failure_blocked + cc open 集)+ docstring 行 26
- [x] 4.2 hooks/worker_budget.py:import 面切 priority_ratio(+retract_claim.TERMINAL_WITH_RETRACTED);check_priority 加 ws 参数,BLOCKED 预过滤 + EvidenceView;调用点传 workspace;注释 55-62 更新
- [x] 4.3 scripts/priority.py:docstring 降级 + DEPRECATED/AUTHORITY 常量(API 零改动)
- [x] 4.4 指示文本翻面:SKILL.md ×7 / rules ×3 / heartbeat_loop_prompt ×2 + test_heartbeat_off.py:133 / convergence_check docstring 6,17 / references ×7 / scripts/README.md:43 / test_convergence_rules_file.py vocab +1
- [x] 4.5 快速门:tests/test_scorer_authority.py + 相关域(test_priority_ratio / test_worker_budget / test_dispatch_contract / test_rank_claims / test_heartbeat_off / test_convergence_rules_file / test_orchestration_priority_cost / test_hook_registry_singlesource)全绿

## 5. 门 + 产出

- [x] 5.1 uv run ruff check .(零 finding)
- [x] 5.2 uv run python devkit/quality_gates.py 1 3 4 5(ALL-PASS;域路径 commit 前置 .subagent-review/2026-08-19-499.json,verified_by=pending-499-reviewer)
- [x] 5.3 .review/RUNBOOK.md(改动清单/测试映射/门禁尾行/自认风险/复现命令)
- [x] 5.4 issue #499 评论:consumer 核实结论 + 处置对照(处置要求 1-4 逐条)
