# Tasks — issue-498-trajectory-replay

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/498` 分支 `v012/issue-498-trajectory-replay` (基 `origin/dev` 1341596, 已含全部 19 件落地)
- [x] 1.2 必读: issue #498 验收段(端到端双轨迹重演)/ plan R2 验收方法 D / 五器官源码(#495 #496 #497 #461 #443+#466)/ 各件既有测试(test_ask_for_direction_v2 / test_failure_analysis_transducer / test_decision_teeth / test_heartbeat_bootstrap)

## 2. SDD

- [x] 2.1 proposal.md(单级负例齐而轨迹接力缺 + 只增测试零器官改动)
- [x] 2.2 design.md(D1 e2e 纪律 / D2 判死链四步表 / D3 搁浅+看牌两段 / D4 心跳 seam / D5 命名映射 / R1-R4)
- [x] 2.3 tasks.md(本文件)

## 3. RED(文件不存在即红)

- [x] 3.1 SDD commit → RED 哈希(该哈希下 `tests/test_trajectory_replay.py` 不存在, `pytest tests/test_trajectory_replay.py` 红: file not found; runpy/subprocess 断言文件缺失)
- [x] 3.2 四场景冒烟预验(bash heredoc 逐场景跑真 CLI, 确认可组装后才写 GREEN — 四场景全通, 无器官缺陷发现)

## 4. GREEN(组装)

- [x] 4.1 `tests/test_trajectory_replay.py` — 轨迹1 判死链全链(ask 拦 + fag BLOCKED + record 三产物 → 障碍升格 + decide DISPATCH + resume next_step)
- [x] 4.2 轨迹2 plan-stall(动作史 → 里程碑+下一步 → 零动作 → rc=1)+ 能力成就落 validated_capability → dispatch_gate REJECT capability
- [x] 4.3 心跳自活 e2e(hermetic init → .heartbeat.json 存在新鲜 + loop_registered 键 + 零 hook_activation; --verify rc=1 + stderr 指引)
- [x] 4.4 看牌变体(disproof 出示 → 放行 + stderr CAPABILITY (disproof recorded) + 统一日志 capability_switch)

## 5. 门禁

- [x] 5.1 `uv run ruff check .` 零 finding
- [x] 5.2 快检 `uv run python -m pytest -q -m "not load_sensitive" tests/test_trajectory_replay.py` + 相邻面(test_ask_for_direction_v2 / test_failure_analysis_transducer / test_decision_teeth)全绿
- [x] 5.3 `uv run python devkit/quality_gates.py 1 3 4 5 6 7` → ALL-PASS(worktree 本地副本)
- [x] 5.4 Gate 5 JSON: `.subagent-review/2026-08-20-498.json`(verified_by=pending-498-reviewer)

## 6. 产出

- [x] 6.1 `.review/RUNBOOK.md`(RED 哈希 / 测试映射 / 门禁结果 / 自认风险)— 永不提交
- [x] 6.2 零器官改动核验(git diff 不含 scripts/ 与 hooks/)
