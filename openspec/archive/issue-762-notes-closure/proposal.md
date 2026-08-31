# Proposal: 知识沉淀闭环 K1+K2 — rollup 机械触发 / gate 消费欠账 / worker 沉淀契约 (#762)

## Why

知识沉淀链路存在三处断链（2026-08-27 现场取证，代码锚齐全）：

1. **rollup 无机械触发** — `scripts/rollup.py` 的 `_queue_notes_due`（#628 交付）
   在 claim 终态时写 `runs/notes-due.yaml`，但 rollup 本身只靠 SKILL 契约一句话
   （skills/kunglao-agent/SKILL.md L58 "claim terminal triggers rollup"）；
   heartbeat_tick / reconcile_workers / kunglao_record 全都不调用
   （grep：`run_rollup(` 除 rollup.py 自身与测试外零命中）。
   现场 live-run 工作区：notes/ 只有 README、notes-due.yaml 不存在（队列零积累）。
2. **notes_due 零消费者** — `scripts/completion_gate.py:105 notes_due()` 已定义
   （读 notes-due.yaml、drop 已写的），docstring 说 "the Stop-face shim consumes"
   —— 但 `hooks/completion_gate.py` grep notes 零命中，实际没接。
3. **沉淀通道缺失** — `scripts/notes_writer.py`（#528）有 write_note/supersedes
   链契约，但没有路径把 worker-status 里高价值内容（plan_vs_actual 偏差 /
   bonus 发现 / 假设改写）转成 notes/。现场三段高价值内容全躺在
   runs/worker-status-C-302.md / C-102.md（遥测文件，claim 关闭后无消费者）。

用户裁决（2026-08-27，原文）：**"有价值内容写 notes/——之前修过还是没用"**。

## What Changes

- **K1a（T1）**: heartbeat_tick 的 tick 链挂 rollup 机械扫——每个 tick 跑一次
  `rollup.py --sweep-terminal`，对所有"终态且无 ledger rollup 行"的 claim 补跑
  write loop（outcomes → lessons → notes-due 入队 → checkpoint）。幂等由既有
  `_rolled_up` ledger 守卫保证；advisory 面（不进 rc/alert，fail-open）+ 遥测事件。
- **K1b（T2）**: `hooks/completion_gate.py::process_event` 在 would-be-PASS 点
  （judge 返回 0 之后，与 #664 intent 检查同模式）消费 `notes_due(ws)`；
  非空 → exit 5 NOTES_DUE block，stderr 列欠账 claim id + 写 notes 指导。
- **K2（T3）**: agents/kunglao-worker.md 增"知识沉淀"契约段——claim 收尾必须写
  `notes/<claim-id>.md`（偏差教训 / bonus 发现 / 假设改写三通道）；DONE 行模板加
  `notes: notes/<id>.md` 字段；hooks/lib_kunglao.py 单点解析同步 + 存在性校验；
  references/operational-mechanics.md 交付清单加 notes 项。

## Out of scope

K3（hypothesis↔note 接线）归 Wave 3 #759/#761 落地后的接线 PR；本波只在
notes_writer 留 TODO 注释级薄接口缝（T4），不写死实现。

## 安全面

- tick 新步骤 advisory-only：rollup 崩不崩 tick（run() 兜底 + rc 不入 alert 权重）
- Stop gate 只在 item 级问题清零后才因 notes 欠账拦截（不制造新死锁面）；
  notes-due 缺失/损坏一律 fail-open（legacy workspace 不拦）
- 不动真实用户 workspace；worker 契约是文本面，机械校验仅"声明了就要存在"
