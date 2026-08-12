
**Heuristic**: are you cold-starting a fresh iteration? If yes, read 8 files in order. If not (mid-iteration), skip this file.
# Cold-Start Contract (DESIGN §13)

## Cold start vs mid-iteration

**Cold start (round 0 only)**: read 8 files in full, in order. Build full mental model.

**Mid-iteration (round 1+)**: do NOT re-read the full 8 files. Instead:
1. Check `<workspace>/claim-register.yaml` `last_read_at` — the freshness signal (a `scripts/update_state_freshness.py` design never shipped; `last_read_at` + `.convergence_ledger.jsonl` timestamps carry this role): which files have changed since the last read?
2. Re-read ONLY the changed files. If none changed, skip all 8 files.
3. Verify `claim-register.yaml` `last_read_at` is current (orchestrator must track its own read time; if older than 5 min, re-read).

**Heuristic: don't re-read what hasn't changed.** Re-reading task_spec.yaml every round wastes ~30K tokens of context.

## The 8-file read (cold start only)

0. **`task_spec.yaml`** — value function (primary_questions, scope, constraints, depth, success_criteria)
1. **`claim-register.yaml`** — all claims (C-NN + boundary_type + source + promotion_attempts + evidence_tier_attempted + status + competitor_group)
2. **`analysis_state.txt`** — structured segments: current_task / VERIFIED-FACTS LEDGER / IOC REGISTER / GATE STATUS / active_workers / in_flight intents / deadline_ts
3. **`global_plan.txt`** + **`claim_deps.yaml`** — current plan DAG + dependency/competitor graph
4. **`progress.txt`** — structured sections: VERIFIED-FACTS LEDGER / decision rationale (append-only)
5. **`<malware-veri-notes>/scripts/lint-notes.py`** output — error check (C5). Status counts come from _INDEX.md, NOT lint.
6. **`blockers/`** — if non-empty, read each blocker-*.md
7. **`facts/_INDEX.md`** — status count source. Format: `F<id> | <status> | <claim_id> | <conclusion>`. O(1) all-passes check via `scripts/update_index.py count_by_status`.

## Why fixed

Each round is a cold start. No reliance on prior-round context. Round 100 has the same judgment quality as round 1 — this is what makes the loop long-horizon capable.

## task_spec change detection (v1.6)

Compare `task_spec.yaml` to `task_spec_snapshot.yaml` (written after each re-plan). If diff → §9 rule 4(c) triggers: new primary_question → new PRIMARY claims; scope shrink → claims out; constraint loosen → scan DEFERRED claims for re-activation. Update snapshot after.

## Phase 0 SETUP — hook + heartbeat activation compact text (moved verbatim from SKILL.md, 2026-08-06)

> Rationale and gate semantics for the Phase 0 hook/heartbeat activation
> commands, which remain in SKILL.md §"Phase 0 SETUP".

- **Isolation-first hard rule (#88)**: kunglao-agent never uses agent teams —
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is never enabled, no teammates are
  spawned, no team setup is performed. Workers are isolated subagents that
  report only to the orchestrator and never message each other; SendMessage
  orchestrator↔worker pings (heartbeat active-ping) remain the sanctioned
  channel.
- **Root-cause cautionary note (2026-08-12)**: the machine-level env flag
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` was the root cause of the
  misdiagnosed dispatch regression (zombie workers / "dispatch looks
  different"). It was set globally in `~/.claude/settings.json`, is REMOVED,
  and SHALL NOT be re-enabled. A session showing team directories or
  teammates means the isolation-first contract is violated.
- **Phase 0 MUST run `--wire-up`** (hooks were silently absent from settings.json
  in multiple sessions — settings rewrites drop the hooks section; PostToolUse
  `remove_worker` never fires → zombie `[active_workers]` → false `3>=3` dispatch
  rejection + dead worker_pulse). `--wire-up` is idempotent and preserves other
  settings keys. Verify: re-run prints `(0 entries)`.
- **Every heartbeat tick MUST run `--reconcile`** — ground-truth rebuild of
  `[active_workers]` from `.wt-*/` worker-status files (last status line ==
  in-progress). Self-heals accounting even when hooks are unwired. This is the
  v1.9.18 fix for "槽位空出来没补充" (zombie count blocking dispatch) and
  "心跳没生效" (worker_pulse never fired).
- Activation **expires after 30 minutes** — renew on every heartbeat tick:
  `hook_activation.py <ws> --renew`. Expired = hooks sleep (no enforcement).
- **v1.9.28 mechanical gate (root-cause fix for recurring 'dispatch without
  monitoring')**: `worker_budget.py::check_heartbeat_alive` runs on EVERY
  dispatch and REJECTS if `.heartbeat.json` is missing or STALE (>35 min).
  This is NOT a soft "orchestrator should self-schedule" instruction (those
  lost to context-forgetting across v1.9.12/13/18/25/26 — every recurrence
  was 'dispatched a task, forgot the heartbeat cron'). It is a hook-enforced
  precondition: no live heartbeat = no dispatch. The `--heartbeat-on` +
  `heartbeat_loop_prompt.py` (CronCreate) steps above are therefore
  MANDATORY before the first dispatch, not optional.
- **ONLY the orchestrator may activate/renew. Subagents are forbidden**
  (a subagent renewing would let a stray worker keep the gates alive).
- `dispatch_gate` (PreToolUse) fires only on re-dispatch of a failure-blocked
  claim (attempts>0, no failure_analysis) — narrow by design, silent otherwise.
- `worker_pulse` (PostToolUse, v1.9.8) injects a convergence snapshot after
  every worker completion — you get "where are we / what's next" WITHOUT
  having to remember convergence_check. It's a heuristic nudge, not a gate:
  you still decide. If the pulse disagrees with your read, re-run
  `convergence_check.py` manually — the scripts are the source of truth.
