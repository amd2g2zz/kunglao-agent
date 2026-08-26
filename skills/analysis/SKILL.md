---
name: kunglao-agent:analysis
description: >-
  Enter the kunglao-agent convergence loop on an initialized workspace:
  dispatch specialist workers, verify evidence byte-by-byte, and drive the
  fact base to PROVEN convergence. The workspace must already be initialized
  (see /kunglao-agent:init).
arguments: [workspace]
argument-hint: <workspace> (alias analyze) — no args → guided workspace prompt
---

# kunglao-agent:analysis — convergence loop

Enters the convergence-driven reverse-engineering loop on an initialized
workspace. The loop dispatches specialist workers (static first), has an
independent verifier re-derive every fact blind from raw evidence, and uses
mechanical gates to decide when the analysis is done. The deliverable is a
fact base where every claim is byte-anchored, independently verified, and
evidence-indexed.

The workspace must already exist and be initialized (see
`/kunglao-agent:init`); a workspace that is not initialized is refused work.

## Stale-workspace gate (#748, machine-checkable)

Before entering the loop, run:

```
kunglao check-stale <workspace>
```

This emits a JSON envelope `{status, rc, workspace_stamp, skill_version, advice}`.
Three terminal outcomes:

- `status="current"` + `rc=0` → proceed with the loop.
- `status="stale"` + `rc=5` → **refuse**. Workspace template stamp is older than
  the active skill version, so the gates added in v0.1.2 / v0.1.3
  (`completion_gate`, `violation_capture`, `_path_hygiene`,
  `orchestrator_tool_guard`) would silently not register, producing the
  #717 三层闸门 escape pattern. **Direct the operator to**
  `/kunglao-agent:upgrade <workspace>` and **stop**. The user must
  explicitly run upgrade; do not auto-fix.
- `status="no-stamp"` + `rc=5` → refuse and direct to
  `/kunglao-agent:init <workspace>` first.

The gate runs in <50ms and produces a parseable contract — agents should
call it once at entry rather than reasoning about stamps themselves.

## Heartbeat self-check (#754, machine-checked)

After the stale gate passes — and before any dispatch — run:

```
kunglao analysis <workspace>
```

One command, three machine steps: the #748 stale gate → durable `/loop`
reconcile → continuous-tick verify. Exit contract (never proceed on failure):

- `rc=0` — entry is clear: the durable schedule is registered in
  `<workspace>/.claude/scheduled_tasks.json` and the heartbeat verifies with
  the continuous-tick standard (>=2 consecutive ticks, gaps <= 2x interval,
  last tick <= 35 min). Enter the loop.
- `rc=5` — identical to check-stale refusal (#748): stale or missing stamp.
- `rc=6` + stderr `heartbeat verify failed — run /kunglao-agent:resume for
  re-arm guidance` — monitoring is NOT verifiably alive (a lone registration
  tick counts as dead: that was the #754 blind spot). Direct to
  `/kunglao-agent:resume`; do not hand-wave a dispatch through.

The durable reconcile inside this command is idempotent: if Claude Code's
7-day durable-schedule cap expired and removed the entry, it is re-created
here automatically (`loop_registered` still only flips true when the loop
prompt body really executes). Machine self-check replaces remembering — the
user should never need to know what a heartbeat is to reach this fix.

## No arguments

An empty `$ARGUMENTS` never enters the loop and never guesses the cwd:
print the guided workspace prompt and WAIT — one question, enumerated
candidates, never guess, no bare argparse-style error dump.

- Ask for the workspace path (one question; enumerate known candidates if
  any are visible).
- If the cwd already looks initialized (`claim-register.yaml` present),
  propose exactly the cwd as the candidate and CONFIRM it — never silently
  run on it.

A missing workspace is the zero-args case: `analysis` takes exactly one
positional argument, so there is no separate partial-argument flow.

## Flow

1. **Phase 0 environment probe** — run `python <SKILL_DIR>/scripts/env_check.py <workspace>`; enter with OVERALL=PASS; degraded rows (marked `T3-restricted:` in the output and listed under `degraded` in `runs/.env-check.json`) enter the loop FLAGGED — they restrict T3 dynamic work, they do not block entry. Re-run Phase 0 after fixing any blocking row.
2. **Read the operative contract** — load the full orchestration contract
   from `skills/kunglao-agent/SKILL.md` (Phases 1-5: activate → dispatch →
   verify → completion transaction → delivery) and follow it exactly.
3. **Convergence loop** — each tick is one mechanical decision (DISPATCH /
   DISPATCH_VERIFIER / SATURATED / BLOCKED / CONVERGED) driven by
   `scripts/convergence_check.py`; run `scripts/convergence_health.py` every
   3rd turn.
4. **Delivery** — the loop exits 0 on CONVERGED and builds the report from
   `claim-register.yaml` + `facts/` + `evidence/_index.json`.

## Examples

- `/kunglao-agent:analysis ~/cases/synth-dropper`
- `/kunglao-agent analysis ~/cases/synth-dropper` (main skill, subcommand form)
