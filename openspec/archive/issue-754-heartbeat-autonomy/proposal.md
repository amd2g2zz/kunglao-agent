# Proposal: 心跳自治 — durable cron / 连续 tick 判活 / verify 挂 analysis 入口 (#754)

## Why

live-run 现场实证：`last_tick_ts == started_ts`（一生只 tick 一次 = 注册时刻）、CronList 空、
`scheduled_tasks.json` 不存在——cron 从未真正存在，但 `check_heartbeat_alive` 的 35min 窗口内
dispatch gate 放行。单次注册 tick 就能领活，是 35min 盲区。

根因链（吸收 #616 讨论；#618 crontab 路线裁决不做——Claude Code durable cron 是正路）：
1. init 只打印 handoff prompt 等人执行 CronCreate（#593 红线：init 不伪造 loop_registered）；
   不知道心跳机制的用户根本到不了提示。
2. Claude Code CronCreate 默认 session-only（进程死 cron 死）；durable 形态落盘
   `<ws>/.claude/scheduled_tasks.json`。
3. 判活只看"最近一次" last_tick_ts ≤ 35min，不查连续性——一次性的注册 tick 也算活。

## What Changes

- **E2 连续 tick 判活（T1）**: `.heartbeat.json` 增 `tick_history`（追加、35min 滚动窗口内保留
  最近 N=12 条）；判活升级为共享判定 `evaluate_tick_continuity`：
  ≥2 个有效 tick 且相邻间隔 ≤ 2×interval_min 且最后 tick ≤ 35min。缺 history 字段的旧文件
  直接 REJECT（严格模式裁决，不留过渡盲区），detail 指导跑一次 heartbeat_touch 建历史。
  dispatch gate（worker_budget_sinks）、--heartbeat-check（heartbeat.py）、--verify #609
  （heartbeat_loop_prompt.py）三处共用同一判定函数。
- **E1 durable cron 路径（T2）**: 新 `scripts/loop_scheduler.py` 把 /loop 注册以 durable 条目
  upsert 进 `<ws>/.claude/scheduled_tasks.json`（幂等：按 job id 替换自身条目，不动他人条目）；
  init 的 emit_activation_handoff 改为 init 自己写该文件并打印"已注册 durable /loop（5m）+
  7 天上限提示"。#593 红线精确语义辨析：写 scheduler 注册 ≠ 伪造 tick —— loop_registered
  仍只在 prompt 首次真执行时翻 true，heartbeat 文件内容不被 init 触碰。
- **E3 verify 挂 analysis 入口（T3）**: `kunglao.py` 增 `analysis` 入口命令（复用 #748
  stale-gate 挂载点模式）：stale gate → durable loop 条目老化重建（幂等 upsert）→
  heartbeat_loop_prompt --verify；非零 → stderr "heartbeat verify failed — run
  /kunglao-agent:resume for re-arm guidance" + rc=6。SKILL.md 契约写明：analysis 进 loop 前
  机器自检，不靠人记得。

## 铁律

- #593: init 不伪造 loop_registered（本次把"伪造"精确定义为心跳文件内容的变更；
  scheduler 注册表写入不在其列）
- #618 的 crontab/register_daemon 路线不做
- 不动真实 ~/.claude 与用户 workspace

## 安全面

- 35min 盲区消除：一次性 tick 无法再领取 dispatch 资格
- durable 注册使重启/换会话后 monitoring 可恢复，且 analysis 入口自愈重建
