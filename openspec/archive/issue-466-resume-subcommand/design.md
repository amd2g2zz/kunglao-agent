# Design: resume subcommand (issue #466)

Requirement source: issue #466 body + comments (data-age contract, three
main state files, code-audit disposition). Architecture constraint: #498
decision-loop spine — resume is a CONSUMER of the decision machine, never
a second decision surface.

## D1 — Read-only diagnose + advise (scope split vs #39)

| | external_kicker (#39) | kunglao_resume (#466) |
|---|---|---|
| trigger | OS cron, presence-independent | human/orchestrator in a fresh session |
| target | the DYING session | the CRASHED workspace |
| writes | settings, prompt file, spawns `claude -p` | NONE |
| output | a replacement session | a brief + exit code |

resume calls `convergence_check.decide(ws)` directly and NEVER
`convergence_check.main()` — main() appends to
`.convergence_ledger.jsonl` and emits a `kunglao_log` event (writes).
Same reason it never calls `heartbeat_tick` or `hook_activation.renew`.

## D2 — Exit codes (the triage contract)

| rc | name | meaning | reachable when |
|---|---|---|---|
| 0 | RC_RESUMABLE | state coherent, liveness alive, next step actionable | heartbeat alive AND register present AND decision not in {BLOCKED, INVALID} |
| 1 | RC_MANUAL | state present, one manual step before the loop may continue | heartbeat dead/stale/missing (re-arm advice), OR register missing while other state exists, OR decision BLOCKED/INVALID (both exit 4 in `convergence_check.VERDICTS`) |
| 2 | RC_NO_STATE | nothing to resume | none of claim-register.yaml / .convergence_ledger.jsonl / facts/_INDEX.md / runs/ exists (or the path does not exist at all) |

rc 1 collects ALL reasons into `manual_reasons` (never just the first).

## D3 — State sources and degradation matrix (issue req 1 + comments 2/3)

| # | source | class | missing behavior | stale rule |
|---|---|---|---|---|
| 1 | claim-register.yaml | claims | CRITICAL → flag + rc 1 (counts untrustworthy; decide() withheld) | OPEN/PARTIAL claim `last_activity_*` > 24 h (`claim_expiry` line) → claim STALE note |
| 2 | facts/_INDEX.md | facts | DEGRADE — partial count unknown, flag | age display only |
| 3 | .convergence_ledger.jsonl | events | DEGRADE — last snapshot unknown, flag | age display only |
| 4 | runs/worker-status-*.md | workers | DEGRADE — no in-flight workers | in-progress file older than `external_kicker.FRESH_WORKER_MINUTES` (20) → STALE note |
| 5 | task_spec.yaml | value | DEGRADE — decide() reports INVALID on its own | age display only |
| 6 | analysis_state.txt | narrative | DEGRADE — flag (F4: LLM self-description, never an event) | age display only |
| 7 | global_plan.txt | plan | DEGRADE — flag; >1 `global_plan*` variant → D1-family warning (pointer fix is #446's) | mtime ≥ 2 days → PLAN-STALE warning (issue comment: plan_drift_detector blind spot) |
| 8 | progress.txt | narrative | DEGRADE — flag (supplementary narrative; event log is the source) | age display only |
| 9 | blockers/ | blockers | DEGRADE — no active blockers | age display only |
| 10 | runs/.heartbeat.json | liveness | CRITICAL → STALE flag + rc 1 + re-arm advice | dead per `external_kicker.session_is_dead(..., 35)` |
| 11 | .hook_state.json | activation | DEGRADE — activation unknown flag | `expires_at` in the past → EXPIRED flag (mirrors `is_active` parse) |
| 12 | runs/logs/kunglao-*.jsonl | eventlog | DEGRADE — last structured event unknown | age display only |

The two CRITICAL rows are the only ones that move the exit code — every
other missing source degrades with an explicit flag so the brief is still
useful (issue negative-acceptance: ≥3 missing-source drills).

### Heartbeat staleness line: 35 min, not 2x cron period

The issue comment proposed "liveness 类超 2× 心跳周期" (2 × 5-min tick =
10 min). Resume uses 35 min instead, because 35 IS the repo-wide
mechanical liveness line (`heartbeat.py` check, `worker_budget.
check_heartbeat_alive` v1.9.28 — the gate that would reject the next
dispatch). Resume's job is to predict whether the loop can CONTINUE, so
it must use the same predicate the enforcing gate uses; a 10-min line
would false-STALE every legitimate quick restart, and sub-TTL dead
detection is already owned by the kicker (DEFAULT_STALE_MINUTES=10).
The 2x-period sensitivity is kept as data-age DISPLAY (age is always
shown), not as an rc trigger.

## D4 — Reuse map (no new parsing — issue req 2 "不重复造解析")

| resume needs | reused from | why |
|---|---|---|
| decision / open counts / partials / workers / blockers | `convergence_check.decide(ws)` | #443 state machine — the single sanctioned decision surface; resume renders its output verbatim |
| in-progress workers (stale-worker annotation), blockers, last ledger snapshot | `external_kicker._in_progress_workers / _blocker_ids / _ledger_last_snapshot` | the #45 fired-predicate readers — already the recovery-grade parsers. Review-F3 correction: `_register_open_ids` / `_partial_fact_ids` are NOT reused — open/partial counts come from `decide()` (row above), never re-read from the register |
| claim dicts (status counts) | `digest_build._claims` | digest's yaml parse (mechanical summary face, #498 cold-start) |
| heartbeat dead/live | `external_kicker.session_is_dead` | #39 D1 — the single dead-session definition |
| claim activity age | `claim_expiry.last_activity_for` + `status_defs.ACTIVE_STATUSES` | the claim-expiry owner |
| activation state | `hook_activation.read_state` + `HOOK_STATE_FILE` | the activation owner |
| event-log location | `kunglao_log.log_path` parent + `kunglao-*.jsonl` glob | #287 observability owner (no read API exists; last-line ts read is the only new code, tolerated and documented) |
| worker-status parse | via kicker's readers (hooks/lib_kunglao #444) | worker-liveness protocol owner |

## D5 — Next-step advice is a LOOKUP, not a computation

`NEXT_STEP_BY_DECISION` maps each `decide()` decision name to one action
line mirrored from the convergence-loop rule §3 table (DISPATCH →
dispatch priority.py top claim; DISPATCH_VERIFIER → independent verifier,
no PROVEN without sign-off; SATURATED → poll all workers; BLOCKED →
self-recovery ladder then human; CONVERGED → handoff checklist; INVALID →
fix task_spec schema). The decision itself always comes from
`cc.decide()`; if the register is missing the decision is withheld
(`decision: null`) rather than approximated.

## D6 — Routing (#456 single-source discipline)

`skills/subcommands.yaml` gains the `resume` record with all six D4
fields (invocation / argument-hint / zero-args / missing-args / example /
next-step). The three render surfaces update in the same commit:
root `SKILL.md` menu block + Routing bullet + Next-steps line,
new `skills/resume/SKILL.md` (frontmatter argument-hint equal to the
registry hint, a "## No arguments" guided-prompt section, never-guess
guard), README Command Reference row, `skills/help/SKILL.md` table row.
`tests/test_subcommand_zeroarg_ux.py` registry assertions widen to the
four-command set — the existing menu/hint/README tests iterate the
registry, so they enforce the new surfaces with no new mechanism.

## D7 — Zero-args and negative paths

- bare `/kunglao-agent:resume` → guided workspace prompt (one question,
  enumerated candidates, never guess the cwd, never a bare argparse
  dump) — same shape as analysis.
- CLI `kunglao_resume.py <path-that-does-not-exist>` → rc 2 + guidance
  naming `/kunglao-agent:init`.
- state present but heartbeat stale → brief annotates STALE, rc 1, and
  the advice names the #461 re-arm chain (init bootstrap /
  `hook_activation --wire-up` + `--heartbeat-on` + CronCreate accepted
  via `heartbeat_loop_prompt.py --verify`).

## Testing design

`tests/test_kunglao_resume.py` (RED first): rc triage (empty / armed /
stale-heartbeat / blocked), crash-drill fidelity (pre-crash `decide()`
output == resume's embedded decision + counts), read-only contract
(byte-level: file set + mtimes + ledger line count unchanged), ≥3
missing-source degradation drills, data-age STALE rules (heartbeat /
worker / claim / plan), JSON + text render, router four-command surface,
kunglao.py `resume` delegation. Fixtures reuse the
`test_convergence_completeness._make_ws` shape (claim-register +
task_spec primary_questions + facts/_INDEX.md + runs/).
