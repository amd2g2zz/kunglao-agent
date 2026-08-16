# Design — isolation-first dispatch contract (#88)

## Context

The "dispatch looks different / zombie workers" regression was first misdiagnosed as a harness subagent→agent-team migration. Official docs (agent teams, v2.1.178+): agent teams are experimental + opt-in (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`); subagents remain the default model and are inherently isolated. The machine-level root cause was the env flag being globally set in `~/.claude/settings.json`; it is removed (2026-08-12). The durable gaps are contract hygiene, not migration:

1. `SKILL.md` §1 still routes work "through `Task` dispatches" — the `Task` tool no longer exists; `Agent` is the only dispatch tool. Stale references exist repo-wide (11 files, inventory in proposal).
2. Background workers don't exit on delivery. A delivered-but-unstopped worker holds a slot forever — the actual zombie root cause, independent of agent teams.
3. The isolation-first rule (no agent team, workers = isolated subagents, deliverables = files, delivery = TaskStop) exists only as a user correction, not contract text — the experimental feature could silently change the dispatch model again. **Scope correction (user, 2026-08-12: "SendMessage我不认为有问题")**: SendMessage orchestrator↔worker pings are NOT the problem and NOT a team feature — the original scope over-applied the isolation constraint by banning SendMessage; the corrected contract bans only team features (teammates, shared task list, mailbox, worker↔worker messaging) and retains SendMessage pings.

Constraints: this is a contract-hygiene change, not a migration — the kunglao dispatch model (orchestrator + isolated subagent workers via the Agent tool) is unchanged. Hooks are subprocess commands: they receive a JSON payload and emit guidance; they cannot invoke Agent/TaskStop tools.

## Goals / Non-Goals

**Goals:**
- `Agent` becomes the only dispatch tool in every contract/code/agent-definition surface; repo-wide grep shows zero stale `Task` tool references.
- Isolation-first is a hard rule in `SKILL.md` §dispatch + §1, `references/cold-start-contract.md`, `references/operational-mechanics.md`: no agent team, workers are isolated subagents that never message each other, deliverables = files, delivery = TaskStop; SendMessage orchestrator↔worker pings (heartbeat active-ping) remain the sanctioned channel.
- Heartbeat active-ping keeps the v1.9.20/21 SendMessage smart-ping; file state (`worker-status-*.md`, `[active_workers]`) remains the accounting source of truth; TaskStop-on-delivery is enforced by a hard rule with a mechanical delivery-moment reminder.

**Non-Goals:**
- No change to the dispatch model itself (no team migration, no new agent types, no new transport).
- No rewrite of `DESIGN.md` (architecture history; its "严禁 SendMessage 死 worker" guidance is already consistent with the new rule), `references/re-library/*` (Win32 `SendMessageW` is unrelated), or incident narratives that describe past SendMessage usage.
- No new harness/hook runtime capability: hooks cannot execute TaskStop; we do not attempt to invent a hook that could.
- No change to `memory/`, `rules/`, `templates/`, `eval/`.

## Decisions

### D1. TaskStop-on-delivery: hard rule + worker_pulse delivery-moment reminder (hybrid)

The issue allows either a mechanical hook or a SKILL.md rule ("prefer the simplest that enforces"). Analysis of feasibility: Claude Code command hooks (PreToolUse/PostToolUse/Stop) are subprocesses that read a JSON payload and print guidance — they have **no Agent-tool access**, so no hook can execute TaskStop. Full mechanical enforcement is therefore impossible; the question is only where the mechanical leverage is cheapest and most effective.

- **Enforcement = hard rule** in `SKILL.md` §"The dispatch contract": "A worker that has delivered (`status: done` + artifacts verified) MUST be TaskStop'd by the orchestrator before any further dispatch/verify action." Plus a delivery checklist in `references/operational-mechanics.md` (new "Delivery = TaskStop" subsection): on delivery confirmation → TaskStop the background agent → then dispatch verifier / update registry.
- **Mechanical aid = `hooks/worker_pulse.py` extension**: the pulse already fires PostToolUse on Agent — i.e., at the exact moment a worker's dispatch call returns, the moment the orchestrator is most likely to forget the stop. When the completed worker's status file shows a final state (`done` / `blocked`), the pulse output adds a `TASKSTOP: W-<n> delivered — TaskStop now` line. Cost ~15 lines; RED-testable.
- **Accounting is already mechanical**: `scripts/reconcile_workers.py` rebuilds `[active_workers]` from status files — a `status: done` worker is not counted active, so the slot-accounting half self-heals; what remains is the actual background-process stop, which only the orchestrator can do.

Alternatives considered:
- *Rule only, no mechanical aid* — rejected: the zombie pattern is recurring (multiple sessions), and the pulse fires at precisely the moment the rule is most likely to be forgotten. The pulse reminder is the simplest thing that adds a mechanical nudge without pretending to enforce what a hook cannot.
- *worker_budget REJECT on "delivered but still running"* — rejected: the budget gate cannot reliably observe liveness (no Agent-tool access; the PostToolUse payload covers only the just-completed call), and a dispatch-time rejection is the wrong point — the stop belongs at delivery, not at the next dispatch.
- *PostToolUse hook that emits a Stop-hook block* — rejected: cannot target a specific background agent; would deadlock the session (the orchestrator's stop would be blocked, not the worker's).

### D2. Heartbeat active-ping retained: SendMessage orchestrator→worker, file state = accounting source of truth

The v1.9.20/21 SendMessage active-ping is **kept as-is** — it is the sanctioned orchestrator→worker channel, and worker SendMessage replies count as liveness signals (smart-ping protocol: `[ping HH:MM] step? stuck? eta?`). What the contract adds is the explicit isolation boundary and the file-state accounting discipline (already mechanically true; now written down):

```
EACH TICK, for each active worker:
  ping worker via SendMessage (orchestrator -> worker, smart-ping)     # channel retained
  age_min = now - worker-status-<id>.md mtime
  if age_min <= threshold:  continue                                  # fresh — alive
  liveness = TaskOutput(task_id, block=false)                         # READ-ONLY cross-check
  # strike on: no status-file append / artifact touch / SendMessage reply within threshold
  if strikes >= 3:  TaskStop + log + redispatch                       # unchanged
  # slot accounting: [active_workers] rebuilt by reconcile_workers.py from status files
```

Per-tick procedure text lives in `references/operational-mechanics.md`, `references/guardrails.md` §6.1a/§6f.1, `scripts/heartbeat_loop_prompt.py` (generated /loop prompt), `scripts/active_intervention.py` (workaround channel = `## orchestrator_response` in `heartbeat_actions.md`, already parsed), `scripts/kunglao-monitor.py` — none of which SHALL instruct agent-team setup or worker↔worker messaging. **`kunglao-monitor.py` runs as a background process** (user, 2026-08-12: "monitor应该在后台运行，否则会堵住loop定时re任务和其它任务"): the loop tick never blocks on monitor output — monitor results are advisory; scheduled tick actions (re-dispatch, verify) proceed without them.

Rationale: the original file-only D2 was the over-application of the isolation constraint that the user corrected ("SendMessage我不认为有问题"); the team features (teammates/mailbox/shared task list) are what break isolation, and banning them is the whole point of the rule. SendMessage to/from one's own subagent is the documented continuation channel, not a team feature.

### D3. Isolation-first hard rule: four landing points, one consistent text

The rule lands as one canonical statement, reworded only for context, in:

1. `SKILL.md` §1 (Tool-use boundary) — new bullet: kunglao tasks NEVER use agent teams (never set `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`; no teammates, no team setup — teammates are separate Claude instances sharing a task list and mailbox, which breaks subagent isolation); workers are isolated subagents that report only to the orchestrator and never message each other; SendMessage orchestrator↔worker pings (heartbeat active-ping) remain allowed.
2. `SKILL.md` §"The dispatch contract" — new subsection: isolation-first + delivery semantics (workers = isolated subagents, no team features; deliverables = files; delivery = TaskStop; heartbeat ping = SendMessage with file-state accounting).
3. `references/cold-start-contract.md` Phase 0 — isolation-first statement with the cautionary note: the machine-level flag was the 2026-08-12 root cause, already removed; never re-enable; a session with team directories / teammates means the contract is violated.
4. `references/operational-mechanics.md` — heartbeat section documents the retained SendMessage ping + file-state accounting (D2) + new "Delivery = TaskStop" section (D1).

`agents/kunglao-redteam.md` L105 ("Then SendMessage to the orchestrator") becomes: the red-team verdict is delivered via its report file under `runs/`, received by the orchestrator through the dispatch return (final report) — the reliable channel for an isolated subagent; SendMessage remains permitted, not instructed.

### D4. Stale `Task` tool reference cleanup: exact edits, keep payload robustness

- `SKILL.md` L305 "through `Task` dispatches" → "through `Agent` dispatches"; L307 table header "Analysis (delegate via Task)" → "Analysis (delegate via Agent)".
- `hooks/dispatch_gate.py` L6/L18 docstring/comment: "Task tool" → "Agent tool". L110-111: keep the payload-shape robustness (the `prompt`/`description`/`task`/`input` field fallbacks are still valid for Agent tool inputs), drop the "Older Task-based dispatches" framing.
- `references/guardrails.md` L23 "delegate to a `Task` worker" → "`Agent` worker"; L63 "fresh `Task` agent" → "fresh `Agent`".
- `.claude/commands/opsx/archive.md` L65 + `.claude/skills/openspec-archive-change/SKILL.md` L69: "use Task tool" → "use Agent tool" (the `subagent_type` parameter is Agent-tool syntax).
- `agents/*.md` (10 files): remove `disallowedTools: - Task` (dead tool name; disallowing a nonexistent tool has no effect — removal is safe and makes the grep criterion achievable).

### D5. Scope boundary of the isolation-first rule

In scope: team-feature prohibitions — `references/operational-mechanics.md` (heartbeat tick loop documents the retained SendMessage ping + file-state accounting), `references/guardrails.md` (§6.1a smart-ping full text, §6f.1 watchdog, mid-course-correction lines), `scripts/heartbeat_loop_prompt.py` (generated /loop prompt keeps the SendMessage ping step), `scripts/active_intervention.py` (option (a) text — `## orchestrator_response` in `heartbeat_actions.md`, unchanged), `scripts/kunglao-monitor.py` helper text, `agents/kunglao-redteam.md` (verdict via `runs/` report file + dispatch return; SendMessage not instructed). The rule names the banned surface: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` never enabled, no teammates spawned, no team setup, no worker↔worker messaging. Out of scope: `DESIGN.md` (architecture history), `references/re-library/*` (Win32 `SendMessageW` is unrelated), incident narratives describing past SendMessage use (history, not instructions). SendMessage itself is NOT in scope as a banned transport — the user correction (2026-08-12) confirmed it is not the problem; only team features are.

### D6. RED-first test strategy: `tests/test_dispatch_contract.py`

- `test_no_stale_task_tool_references`: repo-wide grep over `SKILL.md`, `references/`, `hooks/`, `scripts/`, `agents/`, `.claude/` for precise stale patterns (`Task tool`, `` `Task` ``, `- Task` as a tool entry) → zero hits; `TaskStop`/`TaskList`/`task_spec`/`task-oracle` are legit and excluded by pattern design.
- `test_skill_dispatch_contract_isolation_first`: `SKILL.md` contains the no-agent-team marker, the SendMessage-ping-allowed marker, and the TaskStop-on-delivery marker in §1 and the dispatch contract.
- `test_cold_start_contract_isolation_first` / `test_operational_mechanics_isolation_first`: the two references contain the same markers; `operational-mechanics.md` contains the "Delivery = TaskStop" checklist and keeps the SendMessage ping (no team features anywhere).
- `test_worker_pulse_taskstop_reminder`: feed `worker_pulse` a fixture dispatch-completion payload with a `status: done` fixture file → output contains the `TASKSTOP:` reminder.
- `test_heartbeat_prompt_sendmessage_allowed`: `scripts/heartbeat_loop_prompt.py` output KEEPS the SendMessage ping step and contains no agent-team markers.
- `test_redteam_agent_no_team_features`: `agents/kunglao-redteam.md` has no `- Task` disallowedTools entry and no agent-team wording.
- Baseline: pre-existing failures (`test_acceptance_overall_passes`, `test_skill_lte_500_lines`) unchanged.

## Risks / Trade-offs

- **worker_pulse reminder noise** → fires only on dispatch completion AND only when the worker's status file shows a final state; otherwise silent (mirrors the existing narrow-fire philosophy).
- **Removing `- Task` from agent definitions** → if the harness ever reintroduces a `Task` tool, the defs would not list it as disallowed. Mitigation: the contract names `Agent` as the only dispatch tool, and `test_no_stale_task_tool_references` keeps the surface clean; a reintroduced `Task` would be caught by the isolation-first rule review.
- **Grep-based test brittleness** (matches the English word "task") → test patterns are precise (`Task tool`, backtick-`` `Task` ``, tool-entry `- Task`), documented in the test; false positives are failures the test author fixes by pattern refinement, not by loosening the contract.
- **`heartbeat_loop_prompt.py` is consumed at runtime by `/loop`** → the prompt must stay self-contained after the change; the test asserts its output shape.
- **Hooks cannot enforce TaskStop mechanically** → accepted, documented in D1; enforcement is the hard rule, the pulse is the nudge, `reconcile_workers.py` already self-heals accounting.

## Migration Plan

1. SDD commit: this change's proposal/design/spec/tasks (one commit).
2. RED: `tests/test_dispatch_contract.py` written first, fails.
3. GREEN: contract text edits (D3, D1 rule), stale-ref cleanup (D4), heartbeat SendMessage-ping + file-state accounting documentation (D2, D5), worker_pulse reminder (D1).
4. Verify: full `tests/` + `scripts/` suites — no new failures beyond the pre-existing two; `openspec validate` "is valid".
5. PR + orchestrator verification (maker-checker); no merge by the maker. No data migration; rollback = revert the single branch.

## Open Questions

None blocking. The issue explicitly delegates the rule-vs-hook decision for TaskStop-on-delivery to the design (D1: hybrid — rule + delivery-moment reminder, the maximum mechanical leverage a hook can provide).
