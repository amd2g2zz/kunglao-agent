# Heartbeat Bootstrap — dispatch 生命周期联动 + init 自活 + cron 注册 HARD (#461)

## Why

Issue #461(v0.1.2 release-blocker,挂靠 #498 A 类"循环断链";2026-08-19
升级评论)的根因是**观察脊柱的手动性**:

- 2026-08-18 实录:另一会话 spawn ghidra-light worker(C-409)后,监视/
  心跳/事件全无。现场:`.hook_state.json` 仅 2/10 hooks 激活、phase=IDLE
  (worker 在飞无人翻转)、TTL 30min 无续期者、统一日志零 dispatch 事件。
- 三层根因:① spawn ≠ 生命周期事件(派发不激活/不续期/不翻 phase/不记
  事件);② 续期无主体(orchestrator 不跑循环时 30min 静默睡眠);③
  cron(/loop)注册失败静默 — `heartbeat_loop_prompt.py` 只打印 prompt
  退出 0,CronCreate 没人验收,"monitoring started" 是自claim。

## What Changes

- **派发联动(核心主张)**:`hooks/worker_budget.py` pre_check 在全部
  gate 通过后调用 `scripts/hook_activation.py` 新增的
  `dispatch_linkage(workspace)`(复用既有 `update_state`/`renew`/
  `write_state`,不另起机制):① renew TTL(30min 过期的 `--renew` 由
  派发事件自动触发);② 激活集补全(dispatch_gate + worker_pulse,
  user_override off 不强arm);③ phase 翻 DISPATCH(状态机语汇中的
  "RUNNING");④ dispatch 事件写入既有统一日志 `runs/logs/kunglao-*.jsonl`
  (`kunglao_log.emit`,#459 目标;不新建第四套活性表示 — #446 F 类红线)。
- **init 集成**:`scripts/kunglao-init.py` 每个成功路径(exit 0 前
  最后一步)执行 `--wire-up`(`hook_activation.register_hooks`,#445
  唯一注册入口)+ `--heartbeat-on`(`heartbeat_register`),幂等;
  `--no-hooks`/plugin seam 跳过,`--hooks-json` 只跳 wire-up(操作员
  拥有 hook 目标文件)。SKILL.md 手动 6 步链 → init 后自活。
- **cron 注册失败 = HARD**:`runs/.heartbeat.json` 增加 loop 标记
  `loop_registered`(heartbeat_loop_prompt 首动作
  `--heartbeat-on --loop-registered` — prompt 体被执行即 CronCreate
  接受的证明);`heartbeat_loop_prompt.py <ws> --verify` 检测标记,
  未注册 → exit 非 0 + stderr 明确指引,不再静默。
- **兼容**:`check_heartbeat_alive` 陈旧心跳拒绝路径零改动(回归锚);
  `heartbeat_register` 重注册保留已证明的 `loop_registered=true`。

## Impact

- **代码**:`scripts/hook_activation.py`(DISPATCH_HOOKS +
  dispatch_linkage + CLI `--loop-registered`)、`scripts/heartbeat.py`
  (loop 标记 + `mark_loop_registered`)、`scripts/heartbeat_loop_prompt.py`
  (`--verify` HARD + prompt 首动作)、`scripts/kunglao-init.py`
  (`bootstrap_observability` + 3 个 exit-0 调用点)、
  `hooks/worker_budget.py`(pre_check 联动 + 事件)、
  `skills/kunglao-agent/SKILL.md`(Phase 1 additive 注记)。
- **测试**:新增 `tests/test_heartbeat_bootstrap.py`(init 自活 /
  派发联动四效果 / cron HARD verify / 陈旧心跳回归锚)。
- **不做**:不改 `check_heartbeat_alive` 语义(陈旧仍拒);不改
  `failure_analysis_gate.py` / `priority*.py`(#495/#499 领地);不建
  第四套活性表示;rejected dispatch 不发事件(那是 #459 观测面);
  dispatch_gate.py 休眠 WARN 不在本变更(#478 已覆盖部署半边)。

需求源: issue #461 + 2026-08-19 升级评论(github.com/amd2g2zz/kunglao-agent/issues/461)
架构约束: #498 决策循环一体化(A 类循环断链)
