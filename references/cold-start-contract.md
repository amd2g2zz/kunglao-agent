
**Heuristic**: are you cold-starting a fresh iteration? If yes, read 9 files in order. If not (mid-iteration), skip this file.
# Cold-Start Contract (DESIGN §13)

## Cold start vs mid-iteration

**Cold start (round 0 only)**: read 9 files in full, in order. Build full mental model.

**Mid-iteration (round 1+)**: do NOT re-read the full 9 files. Instead:
1. Check `<workspace>/claim-register.yaml` `last_read_at` — the freshness signal (a `scripts/update_state_freshness.py` design never shipped; `last_read_at` + `.convergence_ledger.jsonl` timestamps carry this role): which files have changed since the last read?
2. Re-read ONLY the changed files. If none changed, skip all 9 files.
3. Verify `claim-register.yaml` `last_read_at` is current (orchestrator must track its own read time; if older than 5 min, re-read).

**Heuristic: don't re-read what hasn't changed.** Re-reading task_spec.yaml every round wastes ~30K tokens of context.

## The 9-file read (cold start only)

0. **`task_spec.yaml`** — value function (primary_questions, scope, constraints, depth, success_criteria)
1. **`claim-register.yaml`** — all claims (C-NN + boundary_type + source + promotion_attempts + evidence_tier_attempted + status + competitor_group)
2. **`analysis_state.txt`** — structured segments: current_task / VERIFIED-FACTS LEDGER / IOC REGISTER / GATE STATUS / active_workers / in_flight intents / deadline_ts
3. **`global_plan.txt`** + **`claim_deps.yaml`** — current plan DAG + dependency/competitor graph
4. **`progress.txt`** — human log (append-only): narrative timeline / decision rationale for the human reader; the VERIFIED-FACTS LEDGER lives in `analysis_state.txt`, facts in `facts/` — machines never ingest `progress.txt` as state
5. **`<malware-veri-notes>/scripts/lint-notes.py`** output — error check (C5). Status counts come from _INDEX.md, NOT lint.
6. **`blockers/`** — if non-empty, read each blocker-*.md
7. **`facts/_INDEX.md`** — status count source. Format: `F<id> | <status> | <claim_id> | <conclusion>`. O(1) all-passes check via `scripts/update_index.py count_by_status`.
8. **`runs/digest.md`** — mechanical digest (#528, the 9th file): `## sec_g` lists the OPEN hypotheses (hyp_id / claim_id / competitor_group / candidates) so a fresh session re-hydrates the same undecided claim motivations and competitor groups it had before the restart. Read via the `kunglao-resume` read-only face — the cold-start session READS the digest, it never writes it. Only `open` hypotheses appear: decided ones (refuted/superseded) stay in the notes/facts trail and are never duplicated. If the digest build failed, cold start degrades to the 8 files above — a broken hypotheses layer never blocks a restart.

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
- **Mechanical enforcement (#233, 2026-08-13)**: the narrative ban now has a
  mechanical path, in two layers:
  1. `scripts/env_check.py` — Phase 0 gate. Check ① FAILs when the flag is
     set in process/User/Machine scope; `OVERALL=PASS` is required before
     analysis, and the snapshot `runs/.env-check.json` records the verdict.
  2. `hooks/env_check_gate.py` — PreToolUse matcher=Agent hard gate. Reads
     `os.environ` directly (zero IO, no activation check by design) and
     REJECTs (exit 2 + stderr + additionalContext: problem / alternative /
     fix) EVERY Agent dispatch while the flag is set in a kunglao workspace.
  A dispatch that did fire means both layers were missing or bypassed —
  treat it as the #88 violation: stop, unset the flag, restart the session.
  Registered first in the PreToolUse Agent list by `hook_activation.py
--wire-up` (THE canonical registration entry, #445).
- **Settings rewrites can flip the flag back (#317, #314 A5 — operator note,
  not a code defect)**: editors / toolchain rewrites of settings.json have
  repeatedly reset the `env` block to
  `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`. Symptom: env_check ① FAIL +
  `env_check_gate` hard-REJECTs every dispatch. Check step for the run
  manual: after ANY settings.json rewrite, re-run
  `scripts/env_check.py <ws>` and confirm ① `[PASS]` before the first
  dispatch; a blocked dispatch means the flag flipped — unset it, restart
  the session, re-run env_check.
- **Phase 0 MUST run `--wire-up`** (hooks were silently absent from settings.json
  in multiple sessions — settings rewrites drop the hooks section; PostToolUse
  `remove_worker` never fires → zombie `[active_workers]` → false `3>=3` dispatch
  rejection + dead worker_pulse). `--wire-up` is idempotent and preserves other
  settings keys, then self-checks the wiring (#445). Verify: re-run prints
  `+ selfcheck PASS (layer=project)`; a `FAIL:` line means the write landed
  on a layer that does not fire — fix before dispatching.
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


## Dynamic channel matrix (#698)

`KUNGLAO_CHANNEL` picks the agent's execution control plane for dynamic
debugging — five equivalent first-class choices, environment self-selects:

| Channel | Drives | Probe (dynamic tasks only) |
|---|---|---|
| `vmr` (default) | VMware VM, any guest OS; snapshot/revert is its irreplaceable value | dual-port liveness (9876 + frida) |
| `ssh` | any ssh-reachable box (bare metal / cloud VM / mac / iOS / docker host) | capability: real `ssh -o BatchMode=yes ... true`; optional docker-over-ssh |
| `docker` | local or remote daemon (`DOCKER_HOST`); `KUNGLAO_DOCKER_CONTAINER` execution target | capability: `docker version` + optional `docker exec <c> true` |
| `adb` | Android emulator / real device | capability: `adb devices` + frida liveness |
| `local` | host static analysis ONLY | none — policy channel |

Gate contract: **dynamic tasks → HARD** (tri-state failure details, backend
named); **static-only tasks → WARN, zero probes** ("dynamic channel
unchecked"); **`local` + dynamic task → REJECT** ("local channel forbids
dynamic analysis — switch KUNGLAO_CHANNEL to vmr/ssh/docker/adb").
Execution layer: vmr-shell skill (snapshots), ssh-mcp (`npm i -g ssh-mcp`;
run-command / sftp-upload / sftp-download) with CLI ssh fallback; docker
and adb flow through the existing skill layer.
