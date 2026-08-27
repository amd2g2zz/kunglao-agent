# Operational mechanics (heartbeat, dispatch prose, VM-channel)

Load this when you need the HOW behind worker monitoring, self-cap-safe
dispatch prose, or the x64dbg VM-channel launch sequence. SKILL.md carries
the principles; this file carries the mechanics.

## Heartbeat registration & the #754 continuous-tick standard

The heartbeat's liveness verdict is CONTINUITY-based and single-sourced in
`scripts/heartbeat.py::evaluate_tick_continuity` — shared verbatim by three
consumers: the dispatch gate (`hooks/worker_budget_sinks.check_heartbeat_alive`),
`heartbeat_check` (--heartbeat-check), and `heartbeat_loop_prompt --verify`.
Alive requires >= 2 recorded ticks (runs/.heartbeat.json `tick_history`,
35-min rolling window, cap 12), adjacent gaps <= 2x interval_min, newest
<= 35 min. A LONE registration tick is dead — that was the live-run incident
(#754): last_tick_ts == started_ts with no cron behind it still passed the
old 35-min window. Legacy files without tick_history REJECT by design; one
real touch/tick rebuilds history.

Registration is DURABLE: init upserts `.claude/scheduled_tasks.json`
(`scripts/loop_scheduler.py`, id kunglao-heartbeat — Claude Code's own
resume source for durable schedules; session-only CronCreate dies with the
process). Claude Code caps durable schedules at 7 days; re-run init or
`kunglao analysis <ws>` (the entry gate re-creates it idempotently), or
re-register directly with loop_scheduler.py. Red line semantics unchanged:
`scheduled_tasks.json` carries scheduling intent only — `loop_registered`
flips true solely when the /loop prompt body executes its first action.

## Active workers heartbeat (the tick loop)

The orchestrator is a daemon (convergence-loop behavior #4). **Workers are
launched in the BACKGROUND and never awaited inline (#704)** — a foreground
Task call that blocks until the worker finishes kills this whole loop
(parallelism → 1, pings never fire, stuck workers invisible). Dispatch and
keep moving; completion is discovered by the tick below, not by waiting.
Each tick,
enumerate ALL workers (not just the last-dispatched) and act per row:

| Worker | age_min | status | ping_sent | pings | action |
|---|---|---|---|---|---|
| W-48 | 2 | in-progress | 18:05 | 0 | - |
| W-47 | 12 | done | 18:00 | 2 | remove |

```
EACH TICK:
  for each worker in registry:
    age_min = (now - worker-status-<id>.md mtime)
    if age_min > 5 and status != 'done':
      bump ping_count
      SendMessage(worker, "Ping ${ping_count}/3...")   # orchestrator->worker ping — sanctioned channel (v1.9.20, #88)
      record ping_time
    # liveness cross-check: read-only TaskOutput(task_id, block=false)
    # strikes accumulate on: no status-file append / artifact touch / SendMessage reply
    if ping_count >= 3:
      TaskStop + log + redispatch
    if status == 'done' or status == 'blocked':
      TaskStop the delivered worker FIRST (Delivery = TaskStop, below)   # #88 D1
      dispatch verifier AND remove from registry
  # slot accounting: [active_workers] rebuilt by reconcile_workers.py from status files
```

**CRITICAL**: enumerate ALL workers, not just the last-dispatched. W-46 sat
idle 34 min while the orchestrator focused on W-47 — the bug. The heartbeat
table forces every worker visible on every tick. Do NOT short-circuit.

### Worker-side discipline (what workers do on each ping)

A long-running task (30-min frida trace, 1-hour Qiling emulation) must
**append a status line every few minutes**, not just at the end:
```
[14:00] step: started F048 trace | status: in-progress
[14:05] step: frida attached, hooks installed | status: in-progress
[14:10] step: 1000 events captured, dumping to JSON | status: in-progress
[14:15] step: 5000 events, BP pending | status: in-progress
[14:30] step: BP hit, capturing state | status: done
```
If the worker is silent for 5+ min, the orchestrator's ping will land. The
worker responds by appending one line confirming it's still working.

### Why 3 strikes — increasing ping intervals (backoff)

1 ping = transient hiccup (network, Git hook). 2 pings = probably stuck.
3 strikes = certain dead; kill + redispatch.

**The ping intervals INCREASE mildly, they are not fixed-5-min** (2026-08-05,
user correction — fixed 5-min pings long tasks too often; aggressive backoff
5→15→30 waits too long). Use a gentle escalation per silence age:

| strike | silence since last status | action |
|---|---|---|
| 1 | 5 min (kunglao-worker) / 10 min (specialist) | first ping (confirm working) |
| 2 | 10 min since last status | second ping (probably stuck? verify artifacts touched) |
| 3 | 15 min since last status | third ping + active_intervention; if still silent + no artifacts + still running → TaskStop + redispatch |

**ANY response resets the strike counter to 0** (2026-08-05, user
correction): a status-file update, a SendMessage reply, or any artifact
touch = the worker is alive and working — its strikes reset. Strikes count
CONSECUTIVE silence only, never cumulative. A worker that replies to
ping-2/3 is back at 0/3, not 2/3. (The log records the reset.)

First-ping thresholds per agent class (§"Specialist bootstrap tolerance");
the strike spacing escalates gently (5 → 10 → 15 min of silence), giving
long VM/emulation phases room without long waits for genuinely-stuck
workers.

**Worker rule — append status at every state change AND at least every
~5 min during long tasks.** The status file is the orchestrator's ONLY
liveness signal. If you're working, write.

## Delivery = TaskStop (D1, #88)

A worker that has delivered MUST be stopped by the orchestrator — a
delivered-but-unstopped background worker holds a slot forever (the actual
zombie root cause, independent of agent teams). Delivery confirmation = the
worker's status file shows a final state (`status: done` / `status: blocked`)
AND its artifacts (`facts/F<NNN>.md` / `runs/<ts>-<task>.md`) are verified.

**Delivery checklist — on delivery confirmation, in order:**
1. Confirm the final status (`done` / `blocked`) in `runs/worker-status-<id>.md`.
2. Verify the artifacts exist and are readable (facts/F<NNN>.md, runs/ report).
3. Verify the durable result note `notes/<claim-id>.md` exists for each closed
   claim (worker sedimentation contract, #762): the DONE line declares it via
   `| notes:` and `lib_kunglao.scan_done_artifact_violations` flags
   declared-but-absent references. A closure that skipped the note resurfaces
   as a completion-gate **NOTES_DUE** block (runs/notes-due.yaml owes until
   the note lands).
4. **TaskStop the background worker** — before any further dispatch /
   verifier / registry action.
5. Then: dispatch the verifier, merge the worktree branch, update
   claim-register.yaml.

Mechanical aid: `hooks/worker_pulse.py` injects a
`TASKSTOP: W-<n> delivered — TaskStop now` reminder at the delivery moment
(PostToolUse on Agent, when the completed dispatch's worker status file shows
a final state). Slot accounting self-heals: `scripts/reconcile_workers.py`
excludes `done` workers from `[active_workers]`.

## kunglao-monitor runs in the background (2026-08-12)

`scripts/kunglao-monitor.py` (M5 MONITOR) runs as a BACKGROUND process. Its
output (TickOutput) is advisory: it never blocks the loop's scheduled tick
actions — re-dispatch / verify / TaskStop NEVER wait on monitor output. The
tick proceeds on file state (`worker-status-*.md` freshness,
`.heartbeat.json`), and the monitor's `next` verdict is a suggestion, not a
gate. Do not design the tick loop around monitor results, and never block a
scheduled action waiting for the monitor process to produce output.

## Liveness thresholds single source (#597, 2026-08-24)

Every liveness/staleness minutes constant (worker stuck 20, heartbeat stale
35, activation/env-state TTL 30, kicker dead-session + renewal margin 10)
lives in ONE module — `scripts/liveness_policy.py` — with the per-value
rationale attached to each number. Consumers import; they never restate a
number. When debugging "why did X fire at N minutes", read the rationale
comment next to the constant there — not this file, and not the consumer's
local history (pre-#597 copies were the drift source).

## Subagent-model switch caveat (A4, #317)

**Operator note, not a code defect**: after switching `SUBAGENT_MODEL` (the
subagent model env setting) to a GLM-family model, the proxy layer may reject
subagent sessions with `400 [1210]` — on both fresh sessions and resume. The
dispatch chain then fails at the transport level, indistinguishable from a
kunglao bug at first glance. Check step for the run manual: after ANY
subagent-model switch, smoke-test one dispatch (e.g. `/kunglao-agent verify
<fact_id>` or a trivial claim dispatch) and confirm the subagent session
starts; only then enter the convergence loop. If 400 [1210] appears, revert
the model setting — it is a proxy-side rejection, not a kunglao defect.

## Specialist bootstrap tolerance + dual-probe protocol (v1.9.29, 2026-08-05)

**Incident (C-332, 2026-08-05):** a freshly-dispatched verdict-scorer was
killed as "B1c dead" after 6 minutes with no status file. Its final output
revealed it was mid-bootstrap (had confirmed 3 evidence files and was about
to write status). **`TaskOutput "running"` cannot distinguish "alive and
working" from "alive and wedged"** — the status file is the only reliable
signal, but specialist agents (verdict-scorer, ghidra-light, floss-filter)
have long read-heavy bootstrap phases (8+ evidence JSONs, Ghidra import)
BEFORE their first status write. The generic 5-min silence threshold
misclassifies normal specialist bootstrap as death.

**Rule — thresholds are agent-class-dependent:**
- **kunglao-worker / generic**: 5 min silence → ping; 15 min → intervention;
  20+ min → backtrack/B1c. (These write status first by §1c.)
- **Specialists (verdict-scorer, ghidra-light, floss-filter, pefile-signature,
  go-symbols)**: **10 min** bootstrap tolerance before the
  first ping (their pre-status read/import phase is legitimately long);
  20 min → intervention; 30+ min → B1c. **Ping before kill — always.**
  A specialist killed mid-bootstrap loses its read work.

**Dual-probe on EVERY heartbeat tick (not just when silence is noticed):**
1. **ENUMERATE ALL running agents FIRST** — `TaskOutput` (or equivalent) returns the
   full list of background agents. A worker whose `TaskOutput` shows `completed`
   but **still appears in the running-agents list** is a **CANDIDATE**, not a
   zombie: its main task finished but a child (cleanup, SendMessage delivery,
   VM-session teardown) may still be closing out NORMALLY. **DO NOT TaskStop
   on this signal alone** — apply the 3-strike rule (v1.9.29 §"Why 3 strikes"):
   ping once (confirm it's finishing), ping twice if still listed, only
   TaskStop after **3 unanswered pings across 3+ ticks** with the agent still
   in the list AND no artifacts touched. "Completed output but still listed"
   is a **flag to ping**, never a kill trigger. (2026-08-05: C-331/C-333 were
   killed too aggressively on this signal; the correct read is
   completed-but-finishing, which cleanup-then-exit resolves in 1-2 ticks.)
2. `TaskOutput(task_id, block=false)` — process alive? (running / not_ready)
3. `SendMessage [ping HH:MM] step? stuck? eta?` — actually working?
   (status files lag; a silent worker is a signal to intervene, never a
   reason to idle)
4. If status file exists but hasn't advanced 5+ min AND the ping goes
   unanswered for one full tick → `active_intervention.py`
5. Only escalate to B1c (kill+redispatch) after: ping unanswered across
   TWO ticks + `TaskOutput` still "running" + no artifacts touched.
   **The worker's last action (from its transcript) is evidence — check it
   before killing.**

**Anti-pattern (this incident):** killing a worker because it was quiet
during its documented bootstrap phase. The fix is threshold-by-class +
ping-before-kill + last-action-check, NOT a shorter kill trigger.

## Self-cap-safe dispatch prose (v1.8.2)

**Problem**: `hooks/worker_budget.py::detect_self_cap()` scans every dispatch
description for time-cap phrasing and rejects if found (unless
`task_spec.time_budget_minutes > 0`, default 0 = "no budget, until convergence").
If the orchestrator absorbs prose patterns from the skill body that *look like*
time caps, it will self-reject its own dispatches and the loop dies.

**The `_SELF_CAP_RE` patterns the orchestrator must NEVER write into a dispatch
description** (verbatim from `worker_budget.py`, IGNORECASE):

| # | Pattern (regex form) | Examples that TRIGGER the gate |
|---|---|---|
| 1 | `\b(?:cap\|hard\s*cap\|wall[- ]?clock\s*cap\|max(?:imum)?\|limit)[a-z ]{0,15}\d+\s*(?:min(?:ute)?s?\|sec(?:ond)?s?\|hour\|day)s?` | "cap 5 min", "hard cap 30s", "wall-clock cap 1 hour", "maximum 60 minutes", "limit 10 min" |
| 2 | `\b\d+\s*(?:m\|min(?:ute)?s?\|s\|sec(?:ond)?s?\|h\|hour\|day)s?\s+(?:cap\|window\|timeout\|budget\|wall[- ]?clock\|deadline\|limit)` | "30 min cap", "5 min window", "60s timeout", "1 hour budget", "15 min deadline" |
| 3 | `\b(?:run\|execute\|emulate\|sleep\|idle)\s+for\s+\d+\s*(?:min\|sec\|hour\|day)` | "run for 30 min", "execute for 1 hour", "idle for 5 min", "sleep for 60 sec" |
| 4 | `\bstop\s+after\s+\d+\s*(?:min\|sec\|hour)` | "stop after 30 min", "stop after 60 sec" |

**Negation allowlist** (these phrases suppress the gate):
- "no self-cap" / "no time cap" / "no budget"
- "without a time cap" / "without time cap"
- "until done" / "until closed" / "until convergence"
- "don't stop for" / "don't stop after"

If the dispatch description must mention a time interval (ping cadence,
watchdog timeout), include one of the negation phrases. Example:
`[T1 tools=grep,xxd] claim C-040 ... heartbeat until done (no self-cap)` —
the parenthetical neutralizes any time-cap pattern elsewhere in the description.

**Safe paraphrase table** — prose in the skill body that LOOKS like a cap but
isn't cap-intent; use the paraphrase column in dispatches instead:

| Original (in skill body) | Safe paraphrase for dispatch |
|---|---|
| "every ~5 min" (heartbeat tick) | "on each heartbeat tick" |
| "Interval: 15 min T3, 5 min T2" | "use the tier-based interval from §6b.2" |
| "30-min frida trace" | "long-running frida trace" |
| "1 hour" + "long task" | "long task (no self-cap)" |
| "wait 5 min" | "heartbeat until done" |
| "stop after 30 min" | "TaskStop on 3-strike silence (no self-cap)" |
| "5-min interval between pings" | "ping with §6f.1 cadence" |
| "30s window" | "freshness window per §6f.1" |
| "5 min cap" / "max 1 hour" | "tier-driven cadence (no self-cap)" |

**Why this exists**: the skill body is **read** by the orchestrator; the
dispatch description is **written** by the orchestrator. The body teaches the
*concept* (heartbeat cadence); the dispatch must use the *paraphrase* (because
`_SELF_CAP_RE` matches surface form, not intent). Reading the body without
this section = paraphrastic absorption = self-reject.

## VM-channel launch sequence (before any x64dbg MCP call)

The MCP bridge at `http://<VM_IP>:8745/mcp` is an in-VM service, but its
`start_session` / `connect_to_session` tools bind to whatever lockfile the MCP
process finds in its working directory — typically a stale host-downloaded
x64dbg copy that is NOT the live VM x64dbg. **The only reliable first call is
`mcp__x64dbg__connect_remote`.** Use this sequence for every dynamic RE engagement:

```
# Step 1 — confirm VM-side x64dbg is installed + configured for ZMQ bind
#   VM_IP: env discovery (KUNGLAO_VM_HOST / vmr-shell discover_vm_ip.sh) — DHCP
#   lease changes every snapshot revert; never reuse a cached address.
#   Path: <VM_X64DBG_DIR>\release\x64\x64dbg.exe
#   Plugin: <VM_X64DBG_DIR>\release\x64\plugins\x64dbg-automate.dp64
#   ZMQ deps: <VM_X64DBG_DIR>\release\x64\plugins\libzmq-mt-4_3_5.dll
#   (<VM_X64DBG_DIR>/<VM_SAMPLES_DIR> are VM-provisioning examples — locate the
#   live install via vmr-shell)
#   [XAutomate] in x64dbg.ini: BindAddress=0.0.0.0, ReqRepPort=69BA (27066), PubSubPort=69BB (27067)
#   If not installed → do NOT STOP. Per convergence-loop behavior #1, self-recover:
#     L1: try connect_remote anyway (the bind may already be live from a prior session)
#     L2: read the vmr-shell skill for the x64dbg install script, run it via vmr-shell
#     L3: dispatch a T2 worker to install + relaunch, while you keep dispatching static claims
#     Only after L1-L3 fail: escalate to user with a specific ask.
#   NEVER fall back to a host-side x64dbg install (Hard prohibition #5).

# Step 2 — launch VM-side x64dbg with the target PE via vmr-shell
vmr-shell exec-cmd 'start "x64dbg" "<VM_X64DBG_DIR>\release\x64\x64dbg.exe" "<VM_SAMPLES_DIR>\<sha>.exe"'

# Step 3 — confirm ZMQ ports listening on the VM
vmr-shell exec-cmd 'netstat -an | findstr :27066'
vmr-shell exec-cmd 'netstat -an | findstr :27067'

# Step 4 — connect from host via MCP — this is THE entry point
mcp__x64dbg__connect_remote(host=<VM_IP>, req_rep_port=27066, pub_sub_port=27067)
mcp__x64dbg__get_debugger_status   # must show "paused" before any further call

# Step 5 — drive the VM-resident x64dbg via set_breakpoint / step_into / read_memory etc.
```

**Anti-patterns (refused by `HOST_FORBIDDEN_TOOLS` if attempted anyway):**
- `mcp__x64dbg__start_session(...)` — spawns x64dbg in MCP server's CWD, NOT our VM-resident install.
- `mcp__x64dbg__connect_to_session(...)` — binds a stale host-downloaded x64dbg lockfile. Symptom: `set_breakpoint` returns 0 hits on a known address.
- `list_sessions` returning empty ≠ bridge broken; it just means no lockfile. Re-prove liveness via `connect_remote` + `get_debugger_status` returning `paused`.

**Why this section exists even though `HOST_FORBIDDEN_TOOLS` rejects host
calls:** the hook is a safety net; this section is the entry steer. Workers
that read it before any x64dbg call pick the right tool on the first try
instead of leaking host-channel attempts.

## VM-worker session cleanup (v1.9.29, 2026-08-05) — zombie root cause

**Incident (C-331 + C-333, 2026-08-05):** two VM-session workers showed
`completed` TaskOutput (facts written, all deliverables landed) but **stayed
in the running-agents list** — each a zombie holding a slot. the #88 enumeration (TaskStop)
catches them, but the ROOT CAUSE is that **VM-session
workers leak subtasks**: x64dbg `connect_remote` handles / vmr-server
sessions / background VM polls are not released when the worker's main task
finishes.

**Root-cause rule — VM workers MUST clean up before done:**
1. **`mcp__x64dbg__disconnect`** (or close the remote) BEFORE writing the
   final `status: done` line. A worker that ends a VM session without
   disconnecting leaks the debugger handle into a subtask.
2. **Close vmr-server sessions / VM polls** the same way — any background
   child that outlives the main task turns the agent into a zombie.
3. If the session ends abnormally (plugin desync / reconnect loop), the
   worker's LAST action must still be cleanup: disconnect attempt → save
   data → report. Never leave a `go`-loop or reconnect-retry child running
   when the fact is written.
4. Orchestrator double-check at every tick (#88): a worker whose
   TaskOutput reads `completed` but still appears in the running list is a
   zombie — TaskStop immediately, then **note in the ping-log which
   cleanup step it missed** so the pattern accumulates evidence.

**Anti-pattern:** writing `status: done` while an x64dbg/VM child is still
attached. The fact is done; the SESSION is not — finish the session first.

## Worker self-drive (moved from SKILL.md §4.1, #226)

A worker's "I can't" is not the end — LEARN → TRY → ESCALATE, three-tier
self-drive (kunglao-worker.md §6d):

1. **LEARN (#761 J5 — internal-first two-tier ladder)**: look it up —
   INTERNAL first: `python <SKILL_DIR>/scripts/references_recall.py` → read the
   hit files under `references/re-library/`; context7 for library APIs. Only
   when that is unsatisfied escalate OUTWARD to `WebSearch`: same-family
   precedent / known solution / error-signature search.
2. **TRY**: retry with ≥2 different methods using what you found.
3. **ESCALATE**: only when all attempts fail, report a blocker — the blocker
   MUST carry the lookup record (what sources were checked / what methods
   were tried / where it is stuck).

WebSearch is freely available to workers, and is EXTERNAL INPUT (#761 J5
evidence discipline): a URL-derived statement entering a fact must record the
source URL + retrieval date (UTC) in the fact's `derivation:` field, and a
WebSearch-only finding may not directly back PROVEN status until an
independent verifier blind-checks it against the sample's own artifacts. A
worker that reports "I can't" without lookup evidence = failure (W-27).
Workers MUST mark uncertain evidence `confidence: low` + `unverified-part` —
silent conclusions are forbidden (anti analysis-error).
