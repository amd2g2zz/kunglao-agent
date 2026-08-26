# Design: 心跳自治 (#754)

## D1 — 用户裁决（2026-08-27，原文）

> "等人说就很蠢，不知道心跳机制的用户根本到不了提示"

推论: 心跳的注册/验证必须机械自检（init 写 durable 注册 + analysis 入口机器 verify），
不能依赖用户理解 CronCreate/session-only/durable 这些概念。

## D2 — 连续性判定（单一函数，三消费方）

`scripts/heartbeat.py::evaluate_tick_continuity(state, now=None) -> (alive, detail)`：

```
hist = state[tick_history]                      # 缺字段/not list → LEGACY REJECT（严格模式）
parse → 有效 ts 升序
len < 2          → SINGLE-TICK REJECT           # 即使很新（35min 盲区即 bug，裁决不留过渡期）
任一相邻间隔 > 2*interval_min → GAP REJECT      # interval 读 state.interval_min，默认 5
最后 tick > 35min（STALE_MINUTES, liveness_policy）→ STALE REJECT
else ALIVE       # detail 含条数 + 最新 ts + cadence 上限
```

消费方与 fail-closed 一致性:
- hooks/worker_budget_sinks.check_heartbeat_alive（dispatch gate，ws→skill 回退定位逻辑保留，
  判定换成共享函数）
- scripts/heartbeat.py.heartbeat_check（--heartbeat-check）
- scripts/heartbeat_loop_prompt.verify_loop（#609 检查段替换为同一函数；红灯文案前缀
  保持 `LOOP NOT TICKING (HARD, ...)` 兼容既有 stderr 断言）

写入端（追加而非伪造）:
- heartbeat_register: 注册 = 第一个 tick（history=[now]，重置——旧条目不迁移，
  下一个真实 tick ≤10min 内自然恢复连续性）
- hook_activation.renew: 刷 last_tick_ts 时同拍追加（cron tick 与 dispatch 自动 renew 都走它）
- scripts/heartbeat_touch.py: 修复破坏性覆写（原实现整个 write_text 丢掉
  last_tick_ts/loop_registered）→ 合并既有 state + 追加 history，原子写
- hooks/heartbeat_touch.py 不追加（activity 高频，会挤掉真 tick；tick_ts vs activity_ts
  E2.3 语义分界保持）

追加规整: 先丢窗口外（> STALE_MINUTES 旧条目）再 cap 最近 12 条（TICK_HISTORY_CAP），
保证任意相邻对都在同一生命期内。

## D3 — legacy 文件严格模式的代价裁决

无 tick_history 的旧文件直接 REJECT（含 detail 教学行）。理由：过渡兼容 = 留盲区
（旧格式正是事故现场的文件形状）。测试侧受影响的 "healthy fixture" 全部补双 tick history
（全命中点核查清单见 tasks.md），不改生产代码语义。

## D4 — durable cron 落盘（loop_scheduler.py）

`<ws>/.claude/scheduled_tasks.json`。Claude Code durable cron 的恢复源（CronCreate(durable:true)
写、session 启动 resume）。本仓库无法离线核对官方 schema 细节，因此：

- 读取容忍三种形态：bare 数组 / {"jobs":[...]} / 损坏文件（损坏 → 备份 .corrupt 后重建）
- 我方条目 canonical 字段 `{id:"kunglao-heartbeat", name, cron:"*/5 * * * *",
  prompt:<build_prompt 输出>, durable:true, createdAt}`；upsert 按 id 替换自身，
  其余条目逐字保留（多人共用 workspace 安全）
- 幂等：重复 init 重写同一条目（prompt/ws 变化时同步刷新）

红线辨析（#593）：loop_registered 定义为"prompt 体真执行过"的证明，载体是心跳文件；
scheduler 注册表只是调度意图的持久化，不含任何 tick 证据。init 写后者 ≠ 伪造前者
（test_handoff_preserves_red_lines 锚死：hb.loop_registered 仍非 true、.hook_state.json 仍不生）。

`--no-hooks` / plugin seam：工程层显式 opt-out（#478 pin 同理延伸）→ 不写 scheduled_tasks.json。

#618 crontab 路线不做：Claude Code durable cron 是正路，register_daemon 是重复机制。

## D5 — analysis 入口（kunglao.py analysis 子命令）

复用 #748 的 check-stale 挂载点模式，顺序:

```
cmd_analysis(ws):
  1. _gate_stale_workspace(ws)            rc!=0 → return rc（5）
  2. loop_scheduler.upsert_durable_loop   幂等老化重建（analysis 入口若条目缺失→自动回建）
  3. heartbeat_loop_prompt.verify_loop    非 0 → stderr
     "heartbeat verify failed — run /kunglao-agent:resume for re-arm guidance"
     + RC_HEARTBEAT_VERIFY_FAIL=6
  ok → rc0 打印 go-ahead
```

verify 通过 cmd_analysis 内部 `import heartbeat_loop_prompt as hlp; hlp.verify_loop(...)`
延迟导入调用——monkeypatch hlp.verify_loop 即可测失败路径。SKILL.md 在 Stale-workspace gate
节之后增 heartbeat 自检契约段（失败文案与本 rc 契约写进文档，机器自检替代人记忆）。
