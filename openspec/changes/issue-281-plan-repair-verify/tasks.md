# tasks — issue-281-plan-repair-verify

## 1. RED (TDD)

- [x] 1.1 tests/test_plan_repair_verify_281.py (fast): the opening drift
  REJECT opens an episode silently — state file carries fingerprint
  (TYPE:claim_id items + classes), rounds=0, no PLAN_REPAIR output, exit
  codes unchanged (rc 1 / rc 2 pinned across the window).
- [x] 1.2 fast: un-repaired drift escalates exactly once — after
  PLAN_REPAIR_WINDOW_ROUNDS subsequent drift rounds, a
  plan_repair_overdue event row (detail JSON carries items/rounds/window)
  + a stderr line; further rounds never re-emit; verified never fires
  without a repair.
- [x] 1.3 fast: repair-landed path — amendment lands (plan file updated),
  next round closes the episode with plan_repair_verified (event + stdout
  line), no overdue ever; a late repair after overdue still closes the
  loop; a fingerprint change on one round closes the old episode verified
  and opens a fresh one; a post-close new drift gets a fresh window
  (rounds reset).
- [x] 1.4 fast: fail-open — an unreadable state file leaves the verdict
  untouched, annotates on stderr, fires no events; a clean workspace
  writes no state at all; the tick cannot raise out of check().
- [x] 1.5 fast: registration + cross-face sync — both words in
  event_taxonomy.EMIT_ACTIONS (sorted + unique), the window constant is
  the named literal 3, the sinks drift guidance names the escalation and
  the same number.

## 2. GREEN (implementation)

- [x] 2.1 scripts/plan_drift_detector.py: PLAN_REPAIR_WINDOW_ROUNDS = 3,
  episode state file runs/plan-repair-state.json, repair_fingerprint,
  plan_repair_tick (open / advance / overdue-once / verified-close /
  fingerprint-change re-open), fail-open wrapper; two call sites in
  check() (clean and drift exits).
- [x] 2.2 scripts/event_taxonomy.py: plan_repair_overdue +
  plan_repair_verified registered (sorted, unique, adopted-faces comment).
- [x] 2.3 hooks/worker_budget_sinks.py: the drift guidance names the
  bounded-window verification (literal number, pinned by tests).
- [x] 2.4 templates/CLAUDE.md.base.tmpl: the global_plan.txt carrier row
  names the verification (prose contract points at the mechanical face).
- [x] 2.5 tests/_tiers.py: the new module registered fast.

## 3. Verification

- [x] 3.1 the new suite green under -n 8 from the worktree.
- [x] 3.2 regression: plan_drift_detector suites, worker_budget
  sinks/gates, trace_identity, event-taxonomy consumers, full fast tier.
- [x] 3.3 ruff on touched files; comment_hygiene_lint from root;
  deploy_manifest --write/--verify (template hash refreshed);
  openspec validate.

## 4. Review round 1 (adversarial) resolutions

- [x] 4.1 HIGH flip-flop defeat: the disjoint-fingerprint verified branch
  is gone — the window counter is cumulative and fingerprint-independent
  (every drift round advances it; rotation cannot reset the window) and
  plan_repair_verified fires ONLY on a genuinely clean round. Pinned by
  the review probe itself: 9 rounds alternating ORPHAN_CLAIM:C-2 /
  STALE_PLAN_ENTRY:C-9 -> overdue at rounds 3/6/9, zero verified rows
  (test_alternating_disjoint_shapes_escalate).
- [x] 4.2 LOW re-escalation cadence: overdue re-fires at each multiple of
  the window (test_overdue_re_escalates_every_window).
- [x] 4.3 LOW torn reads: state writes are tmp + os.replace atomic.
- [x] 4.4 MEDIUM adversarial writes: accepted and documented (design.md
  decision 2 + spec scenario) — write_guard's contract is the four
  carriers only (a runs/ JSON has no checker class there), the face is
  additive observability, the verdict never depends on the state, and
  the runs/.retry-counter.yaml forgery-class precedent applies.
- [x] 4.5 NOTE golden regen annotation appended to the sentinel comment
  block in tests/test_renderer_unify.py.
- [x] 4.6 SDD refreshed for the new semantics (proposal / design / spec
  scenarios: rotation-supersedes-silently, cumulative counter, cadence,
  verified-only-clean).
