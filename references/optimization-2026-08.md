# kunglao-agent 背景知识（2026-08 安全重组外移）

> 本文件收纳 SKILL.md 中"背景知识/契约细节"类内容，SKILL.md 只留操作指针。
> 安全重组原则：只外移不删除、只重组不重写、契约零改动（v1.9.23）。

## How a search session usually goes（迭代形状）

You start with 1-2 seed questions (e.g. "is this packed?" / "where's
the entry point?"). A search operator returns partial matches + new
questions. Each iteration expands the frontier. Around iteration 4-5
you should have a candidate answer. Around iteration 8 you have
confirmation. Past that, you're in the diminishing-returns zone —
stop and report.

A successful search:
- iteration 1: 1 cheap operator (byte-grep) confirms hypothesis
- iteration 3: 2 operators chained (byte-grep + side-channel YARA)
- iteration 5: 1 medium-cost operator (ghidra-light decompile) on a
  narrowed region
- iteration 8: cross-validate with a different operator (constraint
  solver / taint-trace)
- iteration 10+: stop. You have the answer or you're not asking the
  right question.

That is the shape of a successful search. Your job is to recognize
this shape when you're in the middle of it, and to not panic when
iteration 3 looks nothing like iteration 8.

## §6.1a 智能 ping 协议详细版（v1.9.21）

Pings must be SHORT and STRUCTURED so the reply is machine-parseable
and feeds kunglao-agent's own improvement loop. Request format — one line,
three asks: `[ping HH:MM] step? stuck? eta?` — worker replies with
exactly: `step=<one line current action> | stuck=<none|what> | eta=<min>`.
The orchestrator appends each reply to `<ws>/runs/.ping-log.jsonl` as
`{ts, worker, step, stuck, eta}`. The log is the improvement signal:
- repeated `stuck=infra` across workers → infra blocker (dispatch env-fix)
- repeated `stuck=X` on one claim → backtrack_gate
- `eta` drift >2× on two consecutive pings → worker likely looping (intervene)
- per-worker `step` delta between pings ≈ 0 while `eta` grows → spinning
Aggregate the log every 3rd tick (`python scripts/convergence_health.py` +
`.ping-log.jsonl` view) to catch system-level drift, not just per-worker
liveness.

## §6.3 closeout checklist 详细版（v1.9.17，过早收敛防）

`CONVERGED` (no OPEN claims) means the CLAIM LOOP is done — NOT that the
analysis is complete. Before declaring the session finished or writing "分析
完成", walk this checklist; ANY unmet item means the session continues:

1. **Verifier sign-off** — every note with `verify_status: pending` has a
   completed independent-verifier run (runs/*-verify-*.md with VERDICT).
   Maker-checker is structural: orchestrator self-reproduction ≠ sign-off.
2. **Notes coverage** — every key fact family (decryption / protocol /
   command surface / negative findings / infra observations) has a note
   citing it. "9 facts but 1 note" is a red flag.
3. **Verdict re-scored** — evidence/verdict.json (or verdict-v2) reflects
   the LATEST facts. New evidence that contradicts the verdict's premises
   (e.g. "infra unrecoverable" disproven by decryption) REQUIRES a
   verdict-scorer re-run.
4. **Report written** — the deliverable (main.md / hr-report brief) exists
   and cites the fact base; convergence said "write the report" — write it.
5. **Dynamic validation considered** — if static analysis hit a wall that
   dynamic can cross (sealed C2 targets, live config sources, in-memory
   payload), record WHY dynamic was skipped (user constraint / VM down) —
   or get user authorization. "Static is done" is not "dynamic is done".

A CONVERGED claim loop with unchecked items is NOT a finished analysis —
it is a stalled delivery pipeline. When in doubt, err toward continuing.

## §1d.2 worktree 源码挂载注意

Worker worktrees (`git worktree add`) check out only committed files — any
gitignored source dirs (`mal-recon/*/work/` JAR decompile output, `javap/`,
`.venv/`) are ABSENT from the worktree. When dispatching a worker that needs
such sources, state the main-repo path explicitly in the dispatch prompt
(e.g. "sources at `<WORKSPACE_ROOT>/samples/<YYYY-MM-DD>/mal-recon/<sha>/work/sources/` —
worktree lacks it, use the main-repo copy"). Workers that hit a missing path
must fall back to the main-repo copy and record the substitution in their
status file, never block on it.

## §1d.3 superseded-path 禁行声明（v1.9.19）

When a dispatch was stopped and RE-dispatched because the worker followed a
superseded method (e.g. VM detonation replaced by Docker+jdb-mcp), the NEW
dispatch prompt MUST open with an explicit prohibition of the dead path:
`⚠️ 唯一合法路径：<new method>. 严禁 <old method>——上一 worker 因走 <old method> 被终止`.
Workers inherit stale context from the killed predecessor; without the
explicit ban they re-walk the dead path (observed: C-010 worker "reverting
VM snapshot" 40 min after VM path was cancelled).

## Case book（完整故事 → references/case-book.md）

Five real failure modes, one line each. Full stories + v1.9 fix mapping →
`references/case-book.md`.
- **Case 1** — idling when slots are free. Open claims + free slots → dispatch.
- **Case 2** — calling analysis tools directly. Delegate; orchestrator verifies only.
- **Case 3** — re-issuing the same failed dispatch. First failure → backtrack decision.
- **Case 4** — asking the user "should I dispatch?". Default: dispatch the next open claim.
- **Case 5** — stale plan vs reality. Re-plan/decompose/abandon → run `plan_drift_detector.py`.
