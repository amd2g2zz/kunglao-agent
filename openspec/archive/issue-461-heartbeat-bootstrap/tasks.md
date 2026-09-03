# Tasks — issue-461-heartbeat-bootstrap

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/461` branch `v012/issue-461-heartbeat-bootstrap` off `origin/dev` 5e185a2
- [x] 1.2 必读:plan R2 / issue #461 + 升级评论 / hook_activation.py / worker_budget.check_heartbeat_alive / kunglao-init.py / SKILL.md Phase 1(手动 6 步链)/ kunglao_log.py / wire_up_settings.py(#445/#410 边界)

## 2. SDD

- [x] 2.1 proposal.md(三层根因 + 四项改动面)
- [x] 2.2 design.md(D1 联动落点 / D2 init bootstrap / D3 loop 标记+verify / D4 兼容 / D5 验收映射 / R1-R5)
- [x] 2.3 tasks.md(本文件)

## 3. RED(先写,必须红)

- [x] 3.1 `tests/test_heartbeat_bootstrap.py` — init 自活 5 例 / 派发联动 7 例(含陈旧心跳回归锚)/ cron HARD verify 6 例
- [x] 3.2 确认 RED:uv run python -m pytest -q tests/test_heartbeat_bootstrap.py → 16 failed / 2 passed(2 例为回归锚,pin 既有行为),commit **a77fe10**

## 4. GREEN(最小实现)

- [x] 4.1 `scripts/heartbeat.py`:LOOP_MARKER_KEY + heartbeat_register(loop_registered 保留)+ mark_loop_registered
- [x] 4.2 `scripts/hook_activation.py`:DISPATCH_HOOKS + dispatch_linkage(update_state/renew/write_state 复用)+ CLI `--loop-registered`
- [x] 4.3 `scripts/heartbeat_loop_prompt.py`:prompt 首动作 `--heartbeat-on --loop-registered` + `--verify` HARD(exit 非 0 + stderr 指引)
- [x] 4.4 `scripts/kunglao-init.py`:bootstrap_observability + initialize()/resume/F1 三处 exit-0 接线(--no-hooks/plugin 跳过;--hooks-json 只跳 wire-up)
- [x] 4.5 `hooks/worker_budget.py`:pre_check 批准点调用 dispatch_linkage + kunglao_log 事件(import 守卫 fail-open)
- [x] 4.6 `skills/kunglao-agent/SKILL.md`:Phase 1 additive 注记(init 自活 + 派发自动续期 + --verify)
- [x] 4.7 快速门:18/18 绿 + 相关 16 文件 254 passed / 1 skipped(1 failed 为基线预存换行转换,stash 对照确认)+ 全量快速门(见 RUNBOOK)

## 5. 门

- [x] 5.1 uv run ruff check . → 零 finding
- [x] 5.2 uv run python devkit/quality_gates.py 1 3 4 5 → ALL-PASS
- [x] 5.3 Gate 5:.subagent-review/2026-08-19-461.json(五字段,verified_by=pending-461-reviewer)

## 6. 产出

- [x] 6.1 `.review/RUNBOOK.md`(改动清单 / 测试映射 / 门禁尾行 / 兼容性 / 自认风险 / 复现命令)— 永不提交
