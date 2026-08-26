# Design: 知识沉淀闭环 K1+K2 (#762)

## D1 — 用户裁决（2026-08-27，原文）

> "有价值内容写 notes/——之前修过还是没用"

现场取证（live-run workspace）：notes/ 只有 README；`runs/notes-due.yaml` 不存在
（#628 交付的队列零积累）；用户引用的三段高价值内容全躺在
`runs/worker-status-C-302.md` / `C-102.md` —— 遥测文件，claim 关闭后无任何消费者。
结论：#628/#528 修了"怎么写 note"，没修"谁触发、谁检查、谁产出"——本波把
三处断链接上。

## D2 — 三处断链（代码锚）

| 断链 | 锚 | 现状 |
|---|---|---|
| rollup 无机械触发 | scripts/rollup.py:117 `_queue_notes_due`；skills/kunglao-agent/SKILL.md L58 "claim terminal triggers rollup" 是唯一触发契约 | `run_rollup(` 除 rollup.py 自身+测试外全仓零调用 |
| notes_due 零消费 | scripts/completion_gate.py:105 定义；hooks/completion_gate.py grep `notes` 零命中 | Stop gate 不知道欠账存在 |
| 沉淀通道缺失 | scripts/notes_writer.py（#528 write_note/supersedes）无 worker 面 | plan_vs_actual/bonus/假设改写困在 runs/*.md |

守门命令（改动前后各跑一次，防破坏 #628/#528 既有测试锚点）：
`grep -rn 'notes_due\|notes-due\|notes_writer' tests/ hooks/ scripts/ --include='*.py'`
—— 命中面：test_closure_contract_628_629 / test_coldstart_digest_528 /
test_notes_supersedes_528 / test_write_guard_supersedes_528 /
hooks/write_guard.py(264,299) / scripts/{rollup,completion_gate,notes_writer}.py。
全部保持语义不变。

## D3 — K1a：reconciliation sweep（无状态），不用 transition 状态文件

选择：**每个 tick 扫 claim-register 全量终态 claim**，对"终态 且 无 ledger
rollup 行"者补跑 run_rollup，而不是维护 last-seen 状态做非终态→终态边沿检测。

理由：
1. rollup 本身对 (claim_id, terminal_status) 幂等（`_rolled_up` ledger 守卫，
   #524 契约），重复扫是 no-op —— 边沿检测的状态文件是多一份漂移源（#597 教训：
   单点已够，别加第二份拷贝状态）。
2. reconciliation 顺带修复存量欠账（升级后的首个 tick 把历史上漏 rollup 的
   终态 claim 补齐入队）—— 正是现场"队列零积累"的反向修复路径。
3. RETRACTED 不在 status_defs.TERMINAL（#331 retraction domain owner 导出
   `TERMINAL_WITH_RETRACTED`），sweep 集合 = TERMINAL ∪ {RETRACTED}，从
   retract_claim 导入，不留本地拷贝。

API 形态（任务书要求 CLI 保持兼容）：

```
scripts/rollup.py 新增：
  pending_terminal_claims(ws) -> list[tuple[str, str]]     # (cid, STATUS) 未 rollup 者
  rollup_terminal_claim(ws, cid, status) -> dict           # run_rollup + kunglao_log 事件
  sweep_terminal_claims(ws) -> dict                        # 逐个补跑 + fail-open + 汇总
CLI 追加 --sweep-terminal 模式；既有 <ws> <cid> --status X 路径逐字节不变。
heartbeat_tick.run("rollup.py", ws, "--sweep-terminal")    # report["rollup_sweep"]
```

- **fail-open**：sweep 内部 per-claim try/except；汇总进 report["rollup_sweep"]，
  rc 不入 selfcheck/renew/heartbeat 的 alert 权重（同 monitor/#620 advisory 冻结面）；
  tick 侧 run() 本身兜底一切异常。
- **事件记录**：新增 EMIT_ACTIONS 受控词 `rollup_sweep`（sorted 插入，唯一发射面），
  fired 时逐 claim emit(actor="rollup", claim=cid)，sweep 尾部一条汇总。直接
  run_rollup 的既有晋升路径保持静默（发射面只挂在新 sweep face，blast radius 零）。

## D4 — K1b：Stop-face 只拦 would-be-PASS 点

process_event 在 `judge(oracle) == 0` 之后追加 notes 检查（与 #664 exit-4 同模式：
item 级问题、unsigned defer、intent unmatched 全部严格优先，notes 欠账只挡最终放行，
不挡中途 Block，不造死锁）：

```
code == 0 → owed = cg.notes_due(ws)   # 自身已 fail-open：缺/corrupt → []
            owed → {"decision": "block",
                    "reason": "NOTES_DUE: durable result notes owed (#628/#762)
                               — write notes/<id>.md ... for: C-302, C-102"}
                   return 5   （NOTES_DUE；shim-face 专用码，judge 保持 workspace-pure）
            空   → return 0 放行
owed 计算再包一层 try/except → []（双保险，Stop 关键路径 fail-open 优先）
```

- judge-then-revise 语义不变：orchestrator 补写 notes/<id>.md 后，
  notes_due() drop 已写条目 → 下次 Stop 放行。queue 条目本身不清（审计留存）。
- second-stop sanctioned-PASS 路径在 notes 检查之前返回 0（用户放行的第二次 stop
  不被机械欠账二次劫持——用户裁决优先于机械门）。

## D5 — K2：worker 沉淀契约（文本面 + 单点机械面）

- agents/kunglao-worker.md 新增"知识沉淀"段：claim 收尾（翻转 done 行前）必须写
  `notes/<claim-id>.md`，内容三通道任选或组合：(a) plan_vs_actual 偏差与教训
  (b) bonus 发现 (c) 假设改写。frontmatter 走 NotesWriter 契约
  （id=stem / claim_id / status: note / verify_status: pending；纠正已有 stamped
  note 必须带 supersedes）。DONE 行模板追加 `| notes: notes/<id>.md`。
- 机械面单点在 hooks/lib_kunglao.py（#444 AC-1 唯一解析点）：`NOTES_RE` +
  `parse_declared_notes()`；iter_worker_states 行加 `notes` 键；
  scan_done_artifact_violations 对 done 文件中**声明了的** note 路径做存在性校验
  （kind="declared-note-missing"）。opt-in 与 artifacts 一致：没有 notes 行/
  `notes: none` 的 legacy done 豁免——欠账本身的强制在 Stop gate（D4），
  liveness 层只负责"引用必须真实"。
- references/operational-mechanics.md 交付清单（W-15 类教训条目旁）插 notes 校验项。

## D6 — K3 留缝（不做实现）

scripts/notes_writer.py 增 `note_supersedes_hypothesis(...)` 占位接口，body 只
raise NotImplementedError + TODO 注释指向 Wave 3（J3/H2 → #759/#761 落地后接线）。
不写死任何实现形状，避免把 Wave 3 的判 settlements 提前焊死。

## Fail-open 边界总表

| 路径 | 故障 | 行为 |
|---|---|---|
| tick → rollup.py 子进程崩溃 | rc -1 记入 report["rollup_sweep"].rc | tick 继续，alert 权重不含 |
| sweep 内部单 claim 异常 | errors 列表收集，其余继续 | CLI exit 2（tick 只记录） |
| notes-due.yaml 缺失（legacy ws） | notes_due → [] | 不拦 |
| notes-due.yaml corrupt / due: 非法形态 | notes_due 加固 → [] | 不拦 |
| shim 读 queue 异常 | 双保险 catch → [] | 不拦（Stop 关键路径） |
