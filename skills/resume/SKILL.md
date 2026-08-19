---
name: kunglao-agent:resume
description: >-
  Crash/reboot breakpoint recovery for a kunglao-agent workspace: a
  READ-ONLY brief of where the analysis stood (health, open claims,
  partial facts, in-flight workers, breakpoint timeline) plus the next
  action taken from convergence_check. Use after a system reboot, a
  crashed session, or any "where was this analysis?" moment. Never writes
  — re-arming a dead heartbeat is advised, not performed (#461 chain).
arguments: [workspace]
argument-hint: <workspace> — no args → guided workspace prompt
---

# kunglao-agent:resume — crash/reboot breakpoint recovery (issue #466)

Run after a crash, reboot, or dead session to rebuild the breakpoint from
mechanical state — never from the dying session's narrative. The brief is
produced by `scripts/kunglao_resume.py` (also `python scripts/kunglao.py
resume <workspace> [--json]`) and covers:

- **health** — claim-register presence, heartbeat liveness
  (`runs/.heartbeat.json`), activation TTL (`.hook_state.json`), blockers
- **state summary** — open claims / PARTIAL facts / in-flight workers /
  last ledger snapshot; the decision comes VERBATIM from
  `convergence_check.decide()` (the #443 state machine — resume never
  recomputes it)
- **data age** — every state source with a per-class STALE rule
  (heartbeat 35-min gate line, worker 20 min, claim 24 h via
  claim_expiry, plan 2 days)
- **breakpoint timeline** — oldest datable signal → newest, the newest
  labelled the crash point
- **next step** — a lookup of the decision (dispatch / verify / poll /
  self-recover / deliver), plus manual reasons when present

## Exit codes

| rc | verdict | meaning |
|---|---|---|
| 0 | RESUMABLE | state coherent, heartbeat alive — follow the next step |
| 1 | NEEDS-MANUAL | a manual step first: dead heartbeat (re-arm), missing claim-register, or BLOCKED/INVALID decision |
| 2 | NO-STATE | nothing to resume — initialize with `/kunglao-agent:init` |

## Read-only contract

resume starts no heartbeat, renews no TTL, dispatches nothing, and writes
no file. When the heartbeat is dead the brief advises the #461 re-arm
chain (`hook_activation --wire-up` + `--heartbeat-on` + CronCreate of the
heartbeat loop, accepted via `heartbeat_loop_prompt.py --verify`);
executing it is the operator's/init's job — resume never duplicates the
wire-up. This is the split against `scripts/external_kicker.py` (#39):
the kicker recovers the DYING session and writes; resume diagnoses the
CRASHED workspace and only reads.

## No arguments

An empty `$ARGUMENTS` never guesses the cwd and never dumps a bare
argparse error: print the guided workspace prompt and WAIT — one
question, enumerate known candidate workspaces (recent `~/cases/*`
paths) if available, and only proceed on an explicit answer. A cwd
candidate may be PROPOSED but must be explicitly confirmed — never
silently run against it. Never guess.

- Ask for the workspace path (one question; enumerate candidates when
  known).
- Consume `$ARGUMENTS` when present: `/kunglao-agent:resume <workspace>`.
- With the workspace known, run
  `python scripts/kunglao_resume.py <workspace>` (add `--json` for the
  machine-readable brief) and relay the brief, its exit code, and the
  next step. rc 1 → surface the manual reasons and the re-arm advice
  BEFORE any other action. rc 2 → point the operator at
  `/kunglao-agent:init <workspace> [--type ...]`.

## Boundaries

- resume does not repair: missing/corrupt sources are flagged
  (degradation matrix, design D3), never silently defaulted.
- The global_plan active-pointer fix belongs to #446; resume only warns
  when plan variants coexist.
- `analysis_state.txt` / `progress.txt` are data-age rows only — LLM
  self-descriptions are never events (research F4).
