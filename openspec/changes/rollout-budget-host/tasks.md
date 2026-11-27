# Tasks

## 1. EXP-B1 — the pre-implementation experiment

- [x] 1.1 Write `experiments/scheduler/coeff_sim.py`: 200 synthetic
  rollouts, two log-normal difficulty families, arm/fire/learn driven
  offline with an explicit synthetic clock
- [x] 1.2 Pin coefficient bounds [0.5, 4.0] and budget bounds
  [15, 480] over every value the run ever produced
- [x] 1.3 Pin deadline censoring: every fired outcome face carries
  `stop_reason: deadline` + the strategic exclusion marker; the
  exclusion filter drops every censored face; stop records carry no
  disposition key; the stop reason stays outside the closed outcome
  vocabulary
- [x] 1.4 Pin the one global coefficient chain across buckets, the
  sane-trajectory gate (final coeff strictly inside the bounds,
  clamped-update share small, family base separation)
- [x] 1.5 Run the gate: sane trajectory observed (final coeff
  ~1.21, easy/hard bases 19.6/80.0 min, 0% clamped updates) — the
  wiring may proceed

## 2. RED — the wiring contract

- [x] 2.1 Write `tests/test_timer_host_wiring_1001.py` RED (collection
  error, module absent): dispatch begin+commit → a `rollout-timer/1`
  row exists (armed, rollout_id = the journal id, cron off :00/:30)
  and the wake file publishes
- [x] 2.2 RED: completion → `cancel` (the timer flips canceled, the
  wake slot clears) + `learn` with the classified outcome and the
  audit row (before/after + reason)
- [x] 3 RED: deadline → `fire` + `deadline_stop_record` (first
  production caller) + `stop_reason: deadline` on the stop record +
  the timeout audit row; a pre-deadline and a canceled-never-fired
  wake refuse
- [x] 2.4 RED: the wrap-up prompt contract (GRACEFUL_STEPS in order,
  no rollout-start verb, `may_start_rollout: false` on both the armed
  and the stop contract)
- [x] 2.5 RED: cold start `DEFAULT_BASE_MIN`, the continuous run
  (arm → work → settle → learn → arm-next with the chained coeff),
  no bucket split under the sample floor, the hook delegation, the
  fail-open arm face

## 3. The host faces

- [x] 3.1 `scripts/rlvr/rollout_timer_host.py`: `arm_for_dispatch`,
  `round_close_face`, `deadline_wake_face`, the wake publish/clear
  face, the difficulty family resolution (the gates' feed)
- [x] 3.2 `rlvr/rollout_timer.py`: the ONE addition — the
  `timer_state` public read face (no policy math touched)
- [x] 3.3 `scripts/claims_store.py`: the commit arm (after the
  committed provenance row, fail-open)
- [x] 3.4 `hooks/round_closure.py`: the round-close face after the
  step settlement, own fail-open cage
- [x] 3.5 `scripts/rollout_timer_wake.py`: the CLI executor
  (fire/record/cancel/learn; rc 0 fired / 3 refused / 2 usage)

## 4. Contracts + registration

- [x] 4.1 `skills/kunglao-agent/SKILL.md`: the short rollout-timer
  contract block in the dispatch loop (arm → CronCreate once → early
  CronDelete → deadline wake = wrap-up only)
- [x] 4.2 `scripts/README.md`: the wake CLI row + the claims_store
  arm-face mention
- [x] 4.3 `deploy-manifest.yaml` regenerated (--write) and verified
  (--verify) LAST, after every file settles
- [x] 4.4 CI battery: formal/comment lint clean, ruff clean on every
  touched file, affected suites + the syspath/loader/deploy hygiene
  suites green, `local_gate.py --skip-pytest` ALL GREEN
- [x] 4.5 The facade registers the new submodule
  (`rlvr/__init__.py`: package line + `__all__` entry) — the facade
  test's AST walk sees hooks/round_closure consuming it

## 5. Review-hardening round (adversarial review: 1 HIGH + 2 MED + 3 LOW)

- [x] 5.1 HIGH: the facade registration (4.5)
- [x] 5.2 MED: `claims_store.recover` cancels the armed timer when it
  inverts a COMMITTED journal (cancel-only discard face; no phantom
  learn) + the recover-after-commit pin (timer canceled, no budget
  row, register back to OPEN)
- [x] 5.3 MED: the wake publish face is a per-rollout MAP (no
  cross-rollout clobber at any lifecycle point) + the two-armed-
  rollouts pin (one fires + wraps up, the other's contract survives)
- [x] 5.4 LOW: the round close re-checks the fired state immediately
  before its learn (the decide-then-learn window bails to the censor
  path) + the flip pin
- [x] 5.5 LOW: the median feeds on OBSERVED durations only
  (`DURATION_OUTCOMES` narrows the policy core's duration feed;
  timeout keeps its ×1.25 and its bucket-floor sample) + the
  timeout-heavy-history pin
- [x] 5.6 LOW: the sim drives the REAL host faces (arm/round-close/
  wake through rlvr.rollout_timer_host) and P2 pins the real
  exclusion (one budget row per censored rollout through the real
  censor); the shadowed filter def deleted

## 6. Explicit follow-ups (out of scope here)

- [ ] 6.1 The Stop-hook boundary (timer not due → allow; due → block
  with the wrap-up reason; post-settlement → allow + arm next)
- [ ] 6.2 The event-driven wake path (FileChanged + asyncRewake,
  events.jsonl watcher) — the next slice
- [ ] 6.3 The old monitor-stack removal + the liveness rewrite (the
  removal matrix + consumer audit)
