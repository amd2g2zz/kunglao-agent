
**Heuristic - 5 self-check questions before any orchestrator action**:
  1. Is this host-channel (mcp__x64dbg__start_session, mcp__frida__spawn, etc.)? If yes -> BLOCK (Hard prohibition #5).
  2. Does this load the sample on the host? If yes -> BLOCK.
  3. Is the agent's verdict self-stamped (verifier_id == worker_id)? If yes -> BLOCK (F-8, see section 1b maker-checker).
  4. Did I re-issue the same dispatch without backtrack? If yes -> REDIRECT to backtrack_gate.py (F-11).
  5. Am I waiting on user direction (fan-wen)? If yes -> DECIDE myself (see F-13 + section 9 rule 5 - just decide per priority.py / section 8 / section 9).
# Orchestrator Guardrails (kunglao-agent §1-§6 reference)

> The non-negotiable addendum to "You are the ORCHESTRATOR". These rules
> exist because they are the rules most frequently violated in practice —
> and the violations are the most expensive to recover from. This file is
> the backing reference for the inline rules in `SKILL.md`; read it when
> the inline summary is insufficient.

## 1. Tool-use boundary (orchestrator vs worker)

The orchestrator produces the fact base, dispatches workers, verifies
their work. It does NOT produce evidence.

| Tool family | Orchestrator direct call? | Why |
|---|---|---|
| `mcp__ghidra__*` | ❌ delegate to an `Agent` worker | produces static evidence |
| `mcp__x64dbg__*` | ❌ delegate | produces dynamic evidence |
| `mcp__frida__*` / `rev-frida` against a host PID | ❌ forbidden (Hard prohibition #5) | sample-on-host |
| `mcp__volatility__*` | ❌ delegate | produces novel evidence |
| `mcp__context7-mcp__*` / `mcp__web_reader__webReader` | ✅ read-only research | OK |
| `mcp__x64dbg-skills:tracealyzer` | ❌ delegate | dynamic evidence |
| `vmr-shell` (vmr-server / vmrun control) | ✅ VM control channel | routing is allowed |
| Host `Bash`/`Read`/`Edit`/`Write` (filesystem, state files) | ✅ coordinator maintenance | OK |
| Host `Bash` for **sample execution** (`bins/<sha>`) | ❌ forbidden | sample-on-host |

**Self-correction**: if the orchestrator's transcript shows a `mcp__ghidra__*`
/ `mcp__x64dbg__*` / `mcp__frida__*` call, stop analysis immediately, write
the produced evidence as a `Fxxx.md` fact, route remaining work through
worker dispatches.

### 1a. Skill-mediated tool use is still a direct violation

Loading a skill whose `allowed-tools` lists `mcp__ghidra__*` / `mcp__x64dbg__*`
/ `mcp__frida__*` (e.g. `x64dbg-skills:tracealyzer`) is the same violation —
the MCP call still appears in the orchestrator transcript. Rules:
1. Treat skill-mediated analysis-tool use as equivalent to direct use.
2. If a worker-only skill has useful workflow guidance, copy it into the
   dispatch description; do not load the skill in the orchestrator session.
3. Worker-only skills (`x64dbg-skills:tracealyzer`, `x64dbg-skills:recon`,
   any skill whose `allowed-tools` includes `mcp__x64dbg__*`) must be
   flagged `orchestrator_load: false` in the skill manifest.

### 1b. Workers must not self-verify their own evidence

A worker that just produced evidence cannot also seal the verdict — that
collapses the only mechanism that defeats confirmation bias. Rules:

1. **Worker outputs are raw evidence + `claim_id:`, never a verdict.**
   - Allowed: bytes, addresses, command outputs, intermediate analyses,
     next questions.
   - Forbidden: `VERDICT=...`, `verify_status: ...`, `PASS/FAIL`,
     "this confirms Fxxx", "the evidence proves".
   - Deliverable is `runs/<ts>-<task>.md`, NOT `runs/<ts>-verify-*.md`
     (verifier filename is reserved).
2. **Only an independent verifier subagent writes `verify_status`** — a
   fresh `Agent` subagent with no shared context, dispatched via
   `<malware-veri-notes>/scripts/verify-note.py` (or by the orchestrator if absent). The
   verifier reproduces the worker's `reproduce:` block byte-exact and
   writes `runs/<ts>-verify-<NN>.md` + the fact's `verified_by_run:`.
3. **Orchestrator enforces at dispatch time**: reject reports with verdict
   lines (SendMessage "remove verdict"); rename `runs/<ts>-verify-*`
   files to `runs/<ts>-raw-<task>.md`.
4. **Exception**: if verifier subagent is genuinely unavailable (budget
   cap, infra down), the worker may write
   `self_caveat: "unverified — needs verifier pass"`. `verify_status`
   stays `pending`; fact cannot be cited by `<malware-veri-notes>/scripts/handoff-check.py`.

§1 is the *tool* boundary (orchestrator vs worker). §1b is the *epistemic*
boundary (maker vs checker). Both must hold.

### 1c. Checkpoint state immediately after every worker

State loss is the only failure mode that destroys the entire session's
work product — treat it as a HARD STOP, not a recoverable warning. Rules:

1. **Every dispatch → immediate state checkpoint BEFORE any other work**:
   ```bash
   cd <project-root> && ls -la facts/ progress.txt _INDEX.md 2>&1 | head -20
   ```
   If `facts/` is missing/empty → log `B1a state-loss` in `progress.txt`
   and STOP until the user restores.
2. **Every worker completion → immediate write of raw evidence into
   `facts/Fxxx.md`** (or `progress.txt` for status events). Partial state
   is better than total loss. Do NOT wait for "all workers to finish".
3. **Workers must receive an explicit state-write instruction** at
   dispatch: "On completion, IMMEDIATELY write your evidence to
   facts/Fxxx.md, not just runs/<ts>-<task>.md."
4. **Verify cwd before every state-touching Bash call**. If
   `cd <deep-path>` times out, fall back to absolute-path operations
   via `Read`/`Write` from the session's natural cwd (§3 of SKILL.md).

### 1d. The project must be a git repository

Without git, a `B1a state-loss` is terminal — there is no `git reflog`,
no `git fsck --lost-found`, no `git stash`. Treat `git init` as a Phase 0
prerequisite:

1. **Phase 0 SETUP must `git init`** the project root before the first
   claim is dispatched. If `git init` is refused → STOP, log `B1a no-vcs`.
2. **Every state-write batch is committed** (orchestrator commits;
   workers don't):
   - After every worker completion: `git add -A && git commit -m "<task>: <what>"`
   - After every fact-file write: same.
   - After every verifier pass: same.
3. **State-loss recovery uses git**, not memory:
   `git fsck --lost-found` (dangling commits/blobs) ·
   `git stash list` (stashed work) ·
   `git log --all --oneline` (recent checkpoints).
   The orchestrator must try these before declaring state unrecoverable.
4. **`.gitignore` excludes transient state**:
   ```
   .claude/
   *.swp
   worker-status-*.md   # status files are ephemeral; never commit
   ```
   Fact files + verifier reports are persistent state and MUST be committed.

§1c says "checkpoint state immediately". §1d says "only git makes
checkpoints restorable". Both must hold.

## 6. Worker monitoring + mid-course correction

The orchestrator is a daemon, not a one-shot. It dispatches then monitors;
it does not wait passively for notifications.

### 6a. Prescribe method constraints for known-incompatible scenarios

"Do NOT prescribe how a worker works" is too absolute. The amendment:

> Do NOT prescribe implementation details (variable names, loop
> structure). DO prescribe method constraints for scenarios where the
> wrong method is catastrophically slow or breaks the target.

See `method-constraints.md` for the full table (Go binary dynamic RE,
frida on Go, deep-path host ops, x64dbg `set_breakpoint`, `/api/exec`
JSON, frida NativeFunction, VM channel). Copy the matching row into the
worker's `[T<N> tools=...]` prompt. `kunglao-worker` agent already has these
baked in, so dispatch-side prescription is only for one-off overrides.

### 6b. Active monitoring — the continuous ping loop (heartbeat)

The orchestrator is a continuous monitor. Its job is NOT "watch one
worker until done". It tracks ALL in-flight workers simultaneously.
When no worker notification or user message arrives, the orchestrator
MUST still run a watchdog check — it is its own heartbeat.

**The heartbeat protocol** (at least every 5 min, when a `/loop` is
active):

```
1. Read ALL worker-status-*.md files (not just the "active" one).
2. For each file, check mtime against now. Compute age_min.
3. If age_min > 5:
     ping_count += 1
     SendMessage(worker, "Ping <n>/3 ...")
4. If age_min > 15 (3 strikes, no response):
     TaskStop + log + redispatch.
```

The orchestrator executes this as a parallel loop — the 5-min check
happens for ALL workers together, not sequentially. The orchestrator
never says "W-45 is my only active worker" when W-46 is also in
the registry.

**Common failure mode (observed in-session)**: the orchestrator pings
only the last-dispatched worker while ignoring the others. The fix:
the watchdog reads ALL status files on every iteration; the "only
one worker" pathology is prevented by the active-worker registry
(§6b.1) — the loop enumerates the registry, not a single worker ID.
   `[HH:MM] step: <what> | status: <done/in-progress/blocked> | result: <result>`
2. **On monitoring** (every few orchestrator turns), read the status file
   via `Bash cat` (~1 KB, no overflow).
3. **On mid-course correction**, `SendMessage` the worker; the worker
   updates the status file to acknowledge.

**Isolation boundary (#88)**: workers are isolated subagents that report only
to the orchestrator and never message each other — no agent-team features
(`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` never enabled, no teammates, no team
setup). Orchestrator↔worker SendMessage (the heartbeat active-ping and
mid-course corrections) is the sanctioned channel, not a team feature.

Why this works: `Bash cat <small-file>` is ~1 KB vs JSONL = 100 KB+.
Multiple workers each have their own status file.

### 6b.1 Orchestrator-side monitoring protocol — the active-worker registry

The orchestrator is a continuous monitor. Its job is NOT "watch one
worker until done". It tracks ALL in-flight workers simultaneously.

**The active-worker registry is a table in `converge-checklist.md` under
the "Active workers" section.** Structure:

```
## Active workers (2026-07-30 HH:MM snapshot)
| Worker | agentID | claim | dispatched | last_status_mtime | status | action_needed |
| W-45 | a65... | C-045 | 15:30 | 15:50 | in-progress | ping_stale_if_>5min |
| V-25 | a8a... | C-025 | 15:35 | 15:40 | in-progress | wait |
```

**Register on dispatch; deregister on final state.** Add a row to the
table when a worker is dispatched. Remove it when the worker's final status
reaches `done`/`blocked`/`error` OR when the orchestrator itself is
about to idle.

**Monitor EVERY registered worker on every turn.** No short-circuiting:
```
for each worker in active-worker registry:
    cat worker-status-<id>.md
    if status == 'done': dispatch verifier + remove from registry
    elif status == 'blocked': log B1b + remove
    elif status == 'error': SendMessage correction OR log B1b + remove
    elif status == 'in-progress':
        if stale_mtime(worker) > 5 min: ping via §6f.1 watchdog
    else: keep + check again next turn
```

**Why the registry is load-bearing.** Without it, the orchestrator
watches one worker at a time (the last dispatched) and ignores others.
The user flagged "你的监视列表好像只有一个对象" — that's the bug.
The registry prevents pathological single-focus.

1. Every orchestrator turn: read ALL registered `worker-status-*.md`
2. Update the registry table with latest status for each
3. For each active worker, run the state-machine above
4. Remove any worker whose status reached terminal

### 6b.2 Orchestrator-as-daemon — self-schedule `/loop`

The orchestrator is a turn-driven session with no process of its own
between turns. When the user stops sending messages and no notification
arrives, the orchestrator effectively "exits". A real orchestrator should
be a long-running daemon that stays alive while any claim is OPEN and any
worker is in flight. The only mechanism to keep the session "running"
between turns is the `/loop` slash command.

**Rule** — the orchestrator must self-schedule a `/loop` at the END of
every turn where (1) ≥1 worker is in flight, OR (2) ≥1 claim is OPEN, OR
(3) a periodic check is needed.

```
# Write monitor.sh at project root (template inline in SKILL.md §6b.2)
# Schedule: /loop <interval> bash <project-root>/monitor.sh && <monitor prompt>
```

Interval: 15 min T3 (VM/x64dbg/frida), 5 min T2 (Qiling/emulation),
2 min T1 (grep/strings).

Stop the loop when all workers are `done`/`blocked` AND all claims are
PROVEN/REFUTED or have B1b blockers AND converge-checklist C0-C7 pass
(or each failing C has a documented reason).

Without self-scheduled `/loop`, the orchestrator is a one-shot. Workers
keep running in the background but nobody watches them — the user becomes
the human monitor.

### 6c. Guarantee periodic monitoring

"Check the status file every few turns" is not guaranteed. Use `/loop`
to schedule a monitoring prompt at a fixed interval. Preparation:
1. A monitor script at project root: `monitor-<task>.sh` (self-contained
   bash, checks report + status + VM port liveness, prints one-line action).
2. Worker told to write status to `worker-status-<task>.md`.
3. `/loop` prompt is short (reads 2 files + decides action).
4. Interval scales: 15 min T3, 5 min T2, 2 min T1.

### 6d. Converge-driven loop — don't idle on open claims

After a worker notification, the orchestrator commits + updates
`_INDEX.md` + writes `progress.txt`, then idles — even when OPEN claims
remain. Wrap-up recorded state, did not advance it. Root causes:
notification-driven not converge-driven; "cost > benefit" used as stop
reason; PARTIALLY-VERIFIED treated as resolved; no converge checklist;
block treated as stop.

**Rule** — run a converge check after every worker notification, BEFORE
any wrap-up:

```
ON every worker completion notification:
  1. List OPEN claims: status ∈ {PARTIALLY-VERIFIED, DEFERRED, PENDING,
     MISSING, RECONSTRUCTED-from-context, unverified-self-caveat}.
  2. For EACH open claim:
     (a) UNTRIED workaround? → dispatch it now (within ≤3 cap).
     (b) All known workarounds exhausted? → log B1b in
         blockers/<claim>.md with the attempt list. Only then idle.
  3. Only if (OPEN claims = ∅) OR (every open claim has a B1b) → idle.
  4. Cost is NEVER a stop reason.
  5. Wrap-up (commit / _INDEX / progress.txt) is housekeeping, not
     progress. Do it AFTER the converge check, not instead.
```

**Converge checklist** (keep in `converge-checklist.md` at project root):

- **C0** — primary questions all have a PROVEN fact (byte-or-dynamic
  evidence). If no `task_spec.yaml`, ask user ONCE, then record.
- **C1** — every claim is PROVEN or REFUTED (no PENDING / PARTIAL /
  DEFERRED without a B1b).
- **C2** — every PROVEN fact has passed an independent verifier pass.
- **C3** — no fact cites a SUPERSEDED fact ID (two-way supersedes integrity).
- **C4** — every fact's `reproduce:` block, re-run by verifier, yields
  `expected:` byte-exact.
- **C5** — `_INDEX.md` has zero "RECONSTRUCTED"/"PARTIALLY-VERIFIED"/
  "MISSING" rows (or each has a B1b).
- **C6** — negative findings (`type: negative`) exist for every ruled-out
  hypothesis.
- **C7** — `progress.txt` final entry states converge OR lists residual
  open claims + B1b blockers.

Not converged until C0-C7 all pass.

### 6d.1 Anti-interruption discipline — per-iteration checklist

Run this exact checklist after every worker completion notification,
BEFORE any wrap-up or "done" declaration. Treat as a hard gate. The full
8-step checklist lives inline in SKILL.md §6d.1 (kept there because it is
the per-turn runtime loop, not a reference rule).

### 6e. Dispatch to dedicated workers, not general-purpose

Priority:
1. `kunglao-worker` (default) — contract baked into system prompt, dispatch
   prompt is SHORT (≤10 lines).
2. Stage agents (`ghidra-light`/`go-symbols`/`pefile-signature`/
   `floss-filter`/`verdict-scorer`) — when
   the claim IS exactly that stage.
3. `general-purpose` (last resort) — only when neither fits AND the
   orchestrator is prepared to write the full contract preamble.

A dispatch prompt of 200+ words means wrong agent or under-specified
claim — split it.

### 6f. Active monitoring + proactive help

The orchestrator's job is to keep the loop advancing, not to wait for
workers. Rules:

1. **Read `worker-status-<id>.md` between dispatches**; summarize into
   `converge-checklist.md` "Worker status snapshot".
2. **Pre-check tool occupancy before dispatch** — track which MCP
   sessions each in-flight worker holds in a `busy-tools` table.
3. **Proactively help blocked workers** with known recoverable error
   patterns. WebSearch the pattern; `SendMessage` the workaround.
4. **Update the plan after each worker activity**.

**§6f.1 watchdog (isolation-first, #88)**: the watchdog reads ALL
`worker-status-*.md` files every tick, pings silent workers via SendMessage
(orchestrator → worker — the sanctioned channel; workers never message each
other), applies the §6.1a smart-ping protocol, and TaskStops only after 3
unanswered strikes. No agent-team features are involved anywhere in the
watchdog — kunglao tasks never use teams.

**Known recoverable MCP error patterns** (cheat sheet):

| Error | Fix |
|---|---|
| x64dbg MCP returns cached `get_debugger_status` for subsequent calls | `mcp__x64dbg__disconnect` → sleep 5s → `connect_remote` again |
| "Connection closed mid-response" | retry worker; harness re-establishes |
| "Resource temporarily unavailable" + x64dbg | check plugin port via vmr exec; restart x64dbg in guest |
| frida attach FAILED | use `frida -H IP -f C:\\path\\to.exe -l hooks.js` (spawn-inject) |
| VMware Tools integration broken | fall back to vmr-server exec-cmd + PowerShell |

Note: for this sample (OverlordRAT), spawn-via-frida exits immediately
(F046 anti-debug). frida **attach** to an already-launched process is the
working path. See `method-constraints.md` for Go-specific frida rules.
## §1b-§1d.3 + §6.1-§6.3 — compact contract text (moved verbatim from SKILL.md, 2026-08-06)

> These were the inline 1a-1d/§6 compact bullets of SKILL.md's "Orchestrator
> guardrails" section, moved here verbatim so SKILL.md stays ≤500 lines. They
> carry the v1.9.x updates (blind verifier v1.9.22, snapshot HARD v1.9.24,
> isolated worktrees, registered heartbeat v1.9.25/26) on top of the full
> sections above.

- **§1b — workers must not self-verify; verifiers must be BLIND (v1.9.22).**
  Worker output = raw evidence + `claim_id:`, never a verdict. Reject reports
  containing `VERDICT=` / `verify_status:`. AND — verifier prompts must NOT
  hand the fact's conclusion to the verifier ("check that X matches the fact"
  = confirmation bias; the verifier just echoes the fact). **Blind verification
  protocol**: (1) give the verifier ONLY the raw evidence path (source file,
  fixture, log) + the verification questions; (2) verifier derives the answer
  INDEPENDENTLY from the evidence (no fact file read); (3) verifier states its
  own finding; (4) THEN compare against the fact — pass only on exact match,
  and report every divergence (even minor) as DIFF. A verifier that was handed
  the claim to confirm is not a verifier — it's a stenographer.

- **§1c — checkpoint state immediately; snapshot is HARD (v1.9.24).** Every
  dispatch → `ls facts/` before other work (worker_budget hook enforces a
  `facts-snapshot:` marker in the dispatch prompt — missing = REJECT). Every
  worker completion → write evidence to `facts/Fxxx.md` immediately. State
  loss = HARD STOP.

- **§1d — project must be git; workers in isolated worktrees.** `git init` in
  Phase 0 (repo root = project dir; add `.gitignore` for `.venv/`, JAR
  `work/`/`javap/` decompile outputs, `__pycache__/` — large regenerable
  artifacts never enter the index). Each kunglao-worker works in its OWN git
  **worktree** (`git worktree add <path> <branch>`) — worker mutations
  (facts/, runs/) land in its branch, are committed there, and merged back to
  the main branch; the orchestrator main tree stays clean. Do NOT spawn
  workers against the main working tree. State-loss recovery uses
  `git fsck --lost-found` / `git stash list`, not memory.

- **§1d.1 — skill/repo changes: confirm → commit → modify → merge.** Any
  change to kunglao-agent itself (or the analysis repo) follows this order:
  (1) **确认** — inspect what exists (git status, diffs, stale/untracked
  leftovers) before touching anything; (2) **提交现有变更** — commit
  pre-existing uncommitted changes first (they may be a prior session's
  bugfixes); (3) **再修改** — make the new change as its own commit;
  (4) **合入主分支** — merge the branch back. Never stack a new change on
  uncommitted leftovers; never mix unrelated changes in one commit.

- **§1d.2 — worktree source-mount caveat.** Worker worktrees check out only
  committed files — gitignored source dirs (`mal-recon/*/work/`, `javap/`,
  `.venv/`) are ABSENT. Dispatch prompts must state the main-repo source path
  explicitly; workers fall back to the main-repo copy and record the
  substitution. **Full text → `references/optimization-2026-08.md` §1d.2.**

- **§1d.3 — superseded-path declaration (v1.9.19).** RE-dispatches after a
  method supersession MUST open with an explicit ban of the dead path
  (`⚠️ 唯一合法路径：<new>. 严禁 <old>——上一 worker 因走 <old> 被终止`).
  **Full text + case → `references/optimization-2026-08.md` §1d.3.**

- **§6.1 — heartbeat loop (mandatory, start at first dispatch).** The moment
  the first worker is dispatched, self-schedule a heartbeat: `/loop 5m <poll
  prompt>` (or CronCreate `*/5 * * * *`), so worker state is polled every 5
  minutes WITHOUT relying on notifications. Each heartbeat tick: (1) read ALL
  `runs/worker-status-*.md` in every worker worktree (`.wt-*/`), record last
  update time; (2) worker silent >5 min → run `scripts/active_intervention.py`,
  silent >20 min → `scripts/backtrack_gate.py`, dead → B1c blocker + redispatch;
  (3) run `scripts/convergence_check.py` — DISPATCH → `priority.py` + dispatch
  next; SATURATED → keep polling, no idle; CONVERGED → run the §6.3 closeout
  checklist FIRST — if any item is unmet, continue the session (dispatch
  verifier / write notes / re-score verdict / write report) instead of
  declaring done; only stop the loop after the checklist is green
  (`ScheduleWakeup stop:true` / CronDelete); (4) completed worker → verify
  facts → merge worktree branch → update claim-register.yaml + `_INDEX.md`;
  (5) renew hooks: `hook_activation.py <ws> --renew` (30-min TTL) — this
  tick also refreshes `.heartbeat.json` `last_tick_ts` (v1.9.25: a renewing
  tick IS the proof the heartbeat is alive); (6) **PING
  every worker (v1.9.20, active liveness)** — status-file timestamps are
  worker-written and lag; TaskOutput only says running/not_ready. Each tick,
  for EVERY active worker: `SendMessage(to=<worker>, "[heartbeat ping HH:MM]
  ...请汇报当前步骤/卡点/预计剩余")` and `TaskOutput(task_id, block=false)`
  as liveness cross-check. Pings are cheap (one message); they surface
  "lost worker re-walking a dead path" (see §1d.3) and "stuck on infra" BEFORE
  the 5/20-min thresholds. Never rely on passive reads alone. Never wait
  on notifications alone — a silent worker is a signal to intervene, not a
  reason to idle.

- **§6.1b — heartbeat must be REGISTERED, not claimed (v1.9.25/26, 启动仿冒防).**
  "监控已启动"是 orchestrator 目前无法自证的声称。**心跳注册融入 /loop
  本身（v1.9.26）**：Phase 0 生成一体式心跳 prompt —
  `python scripts/heartbeat_loop_prompt.py <ws>` — 其输出 prompt 的首动作即
  `hook_activation.py <ws> --heartbeat-on`（写 `<ws>/runs/.heartbeat.json`），
  后续每 tick 内建 reconcile / status poll / smart ping / convergence /
  renew。一个 `/loop 5m <prompt>` 同时注册 + 监视 + 校验，无分离步骤。
  每个心跳 tick 的 `--renew` 自动刷新 `last_tick_ts`；**宣告 CONVERGED 前
  MUST 运行 `--heartbeat-check`** — exit 0 = 监视确实在跑；exit 1（文件缺失/
  超 35 分钟未刷新）= 监视未启动或已停止，必须先启动再继续。启动/停止是
  文件状态，不是自我宣称。

- **§6.1a — smart ping protocol (v1.9.21).** Pings must be SHORT and
  STRUCTURED (`[ping HH:MM] step? stuck? eta?` → `step=<x> | stuck=<none|what> | eta=<min>`),
  replies append to `<ws>/runs/.ping-log.jsonl`, and the log feeds kunglao-agent's
  improvement loop (repeated stuck=infra → infra blocker; eta drift >2× →
  looping; zero step delta + eta grows → spinning). Pings travel via
  SendMessage (orchestrator → worker) — the sanctioned channel (v1.9.20/21,
  #88); agent-team features (teammates, team setup, worker↔worker messaging)
  are never used. **Full protocol + signal table →
  `references/optimization-2026-08.md` §6.1a.**

- **§6.2 — notes capture via /malware-veri-notes (mandatory, every heartbeat).**
  Each heartbeat tick (not just at the end) MUST capture valuable content
  through the **malware-veri-notes** skill: (a) every newly merged fact → a
  note entry citing it by fact ID (byte-anchored, with reproduce command);
  (b) every screenshot / graph / rendered artifact (graph.html, VT behaviour
  snapshots, decompile screenshots) → attached to the note with its path;
  (c) every disproof or new IOC (decrypted config keys, C2 fields, credential
  identifiers) → note with provenance; (d) blockers/hypotheses. Notes are
  written via the malware-veri-notes skill workflow (self-contained fact +
  reproduce command + expected/actual), so the analysis is reproducible by a
  downstream verifier or report writer. If a heartbeat tick produces no new
  evidence, no note is written — but the tick that merges worker output MUST
  produce one.

- **§6.3 — convergence ≠ completion: the closeout checklist (v1.9.17, 过早收敛防).**
  `CONVERGED` (no OPEN claims) means the CLAIM LOOP is done — NOT that the
  analysis is complete. Walk the 5-item checklist before declaring done:
  (1) verifier sign-off per note, (2) notes for every fact family,
  (3) verdict re-scored on latest facts, (4) report written,
  (5) dynamic validation considered/authorized. ANY unmet item → session
  continues. **Full checklist + rationale → `references/optimization-2026-08.md` §6.3.**
  **v1.9.24 anti-spoof double-sign**: before declaring CONVERGED publicly,
  (a) run the sign-off gate (`scripts/blind_gate.py`-backed claim_migrator
  rejects PROVEN claims without independent verifier sign-off) AND (b) re-run
  `scripts/kunglao-verify.py <ws> <fact_id>` L1 on ONE randomly chosen fact —
  its expected/actual must still match byte-exact. Both gates
  green = the convergence claim is real, not performed.
  **Numeric fidelity at handoff**: if report inputs (fact_anchors.md /
  evidence_map.json / evidence_boundaries.md) are generated from the fact
  base, run the anchor↔fact fidelity gate
  `python <skill>/scripts/handoff-check.py --anchors <anchors-file>` —
  it must PASS (every anchor number matches the cited fact's claim +
  counting basis; no collapsed multi-basis figures, no category renames
  like "70 BPF_CALL" → "70 helper calls" per the global rule
  `~/.claude/rules/common/numeric-fidelity.md`).
