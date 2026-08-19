# Proposal: /kunglao-agent:resume — crash/reboot breakpoint recovery (issue #466)

## Why

System reboots, session crashes, and unresumable sessions lose the
orchestration context of a running analysis. The workspace state files
survive (that is the whole point of the mechanical-state design), but
nothing aggregates them for a FRESH session:

- `scripts/external_kicker.py` (#39) handles the DYING session — an OS cron
  detects deadness and spawns a replacement `claude -p`. It is
  presence-independent and writes (settings re-registration, prompt
  staging, process spawn). It does not produce a human/orchestrator-facing
  brief, and it is not the right tool when a HUMAN is back at the keyboard
  asking "where was this analysis?".
- The router surface (`skills/subcommands.yaml`, #456 single source) has
  only init / analysis / help. Its RUNBOOK anticipated that adding a
  command requires three render surfaces to stay in sync.
- The state sources exist but have no cold consumer: claim-register.yaml,
  facts/_INDEX.md, .convergence_ledger.jsonl, runs/worker-status-*.md,
  task_spec.yaml, analysis_state.txt, global_plan.txt, progress.txt,
  blockers/, runs/.heartbeat.json (#461), .hook_state.json,
  runs/logs/kunglao-*.jsonl.

## What Changes

1. New read-only module `scripts/kunglao_resume.py` + `resume` subcommand
   on `scripts/kunglao.py`: input a workspace, output a resume brief —
   (a) health (claim-register presence, heartbeat liveness, activation
   TTL, blockers), (b) mechanical state summary (open claims / PARTIAL
   facts / in-flight workers / last ledger snapshot), (c) breakpoint
   timeline (oldest signal → newest = crash point), (d) next-step advice
   taken VERBATIM from `convergence_check.decide()` (the #443 state
   machine — resume never recomputes a decision), (e) data-age table with
   per-class STALE rules. Output text or `--json`; exit 0 resumable /
   1 needs-manual / 2 no-state.
2. Routing: `resume` registered in `skills/subcommands.yaml` (the #456
   single source) with argument-hint `<workspace>`; the three render
   surfaces updated (root SKILL.md menu, `skills/resume/SKILL.md`,
   README Command Reference); the registry assertion widened to the
   four-command set.
3. Degradation contract: every state source declares its missing-item
   behavior (DEGRADE-with-flag vs CRITICAL) and its data-age STALE rule
   (design.md D3/D4). Two CRITICAL rows can move the exit code; every
   other missing source degrades with an explicit flag in the brief.

## Boundaries (NOT doing)

- resume does NOT start the heartbeat, does NOT renew the activation TTL,
  does NOT dispatch, and writes NOTHING (read-only). Issue requirement 3
  ("恢复即重武装") is satisfied by ADVICE, not action: a dead heartbeat
  yields rc 1 plus the canonical #461 re-arm chain (init bootstrap /
  `hook_activation --wire-up` + `--heartbeat-on` + CronCreate). The issue
  comment itself assigns re-arm scope to #461 (merged, fa08fd3: init
  heartbeat bootstrap); duplicating that wire-up inside resume would
  violate the "resume 路径不重复 wire-up" boundary and re-create a second
  writer where init is the single armed entry.
- resume does not fix the global_plan pointer (single-source violation
  detection only; the pointer fix is #446's, already landed).
- resume does not read or trust the narrative files
  (analysis_state.txt / progress.txt) as events — F4 ("an LLM saying done
  is not an event"); they appear only as data-age rows.

## Impact

- Files added: `scripts/kunglao_resume.py`, `skills/resume/SKILL.md`,
  `tests/test_kunglao_resume.py`, this openspec change.
- Files edited: `scripts/kunglao.py` (new subcommand, additive),
  `skills/subcommands.yaml`, `SKILL.md` (menu + routing, additive),
  `README.md` (table row), `skills/help/SKILL.md` (table row),
  `tests/test_subcommand_zeroarg_ux.py` (registry set + hints loop),
  `tests/test_cli_matrix.py` (CLI registry row).
- Risk: SKILL.md is a cross-wave hotspot — edits are strictly additive
  (one menu block line-pair, one routing bullet, one next-step line).
