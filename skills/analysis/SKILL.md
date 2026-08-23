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

1. **Phase 0 environment probe** — run `python <SKILL_DIR>/scripts/env_check.py <workspace>`; enter the loop only with `OVERALL=PASS`.
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
