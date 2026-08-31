## Proposal: heartbeat 触发面自主化 + gap 告警（#618/#795 机制面）

- Issue: #618 / #795
- Wave: W4（CORE-ALGO-BLUEPRINT §9 提醒→hook 换算表兑现件）
- Status: proposed

## Why

#618 实锤：`external_kicker.build_crontab_line` 只打印 crontab 行，`register_daemon`
不存在——无人值守活性仍依赖 agent 记得跑或人工装 cron。#830 已建 durable 侧车
（runs/.heartbeat.log），但**既有 hooks/heartbeat_touch.py 只写 .heartbeat.json
缓存，从不写侧车**——hook 触发再多，durable 活性面仍是空的。#795 裁决的慢 tick
dead-man 依赖"有东西在跑 tick"，而 tick 的调度器是纸面的。

## What Changes

1. **hook 触达 durable 侧车**：hooks/heartbeat_touch.py 在缓存更新后追加写
   runs/.heartbeat.log（actor="hook"），带 60s 最小间隔去重（防 hook 高频刷屏侧车；
   与 #830 单一事实源契约一致——单文件、append-only）。fail-open，永不阻塞工具调用。
2. **Stop 面注册**：heartbeat_touch 增加 Stop 事件槽（会话每轮结束必跳一次）——
   register_hooks_deployed 对该文件并排发 PreToolUse/Bash + Stop 两条注册。
3. **gap 告警**：scripts/heartbeat.py 增 `gap_alarm()`——读侧车 newest ts，超
   STALE_MINUTES 阈值即告警；convergence_check.decide() 标注 `decision["heartbeat_gap"]`
   并 emit `heartbeat_gap` 事件（EMIT_ACTIONS 字母序注册）。无人值守下死寂可判。
4. **daemon 取舍（proposal 记录）**：register_daemon/schtasks 自动安装**本卡不做**——
   hook 面 + gap 告警已覆盖"会话内无人值守"；死会话恢复仍走 external_kicker 手工
   cron（残留已记 Residuals）。取舍依据：调度器安装是 OS 权限面（schtasks 需管理
   员/策略），自动安装有宿主污染风险，与 hook 无上下文不会忘的主交付正交。

## Impact

- Assets: hooks/heartbeat_touch.py · scripts/heartbeat.py · scripts/hook_activation.py ·
  scripts/convergence_check.py · scripts/event_taxonomy.py
- 既有契约：wire-up 计数锚从 registry 对派生（部署面 +1 条目，锚自动跟随）；
  #830 侧车单写者契约不变（新增写者复用 append_tick_log）；#634 noop_breaker 不重叠
  （它管 noop 循环熔断，本卡管活性侧车与死寂告警）
- Residuals: 跨会话 dead-man（OS 调度器）仍需人工 cron；register 自动化留后继卡
