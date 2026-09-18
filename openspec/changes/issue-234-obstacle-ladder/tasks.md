# tasks — issue-234-obstacle-ladder

## 1. RED (TDD)

- [x] 1.1 tests/test_obstacle_ladder.py (fast): ladder_defects — all-levels
  covered is [], missing levels named, unknown family for a known class
  defects, two same-family rungs -> family-repeat defect (ladder INVALID).
- [x] 1.2 fast: FAMILY_FALLBACK — unknown/absent obstacle class walks the
  generic enumeration; instrument annotation never filters.
- [x] 1.3 fast: settlement_blocker — obstacle claim + no ladder file /
  gapped ladder / empty inventory -> NAMED reasons; non-obstacle origin ->
  None (gate silent); walked ladder + inventory + minted siblings -> None.
- [x] 1.4 fast: mint_sibling_claims — one sibling per inventory entry with
  origin=obstacle-alternative, obstacle_for=parent, answers_question
  inherited, depends_on edge in claim_deps.yaml; idempotent re-mint;
  sibling is priority_ratio.is_open (TS rank pool).
- [x] 1.5 fast: dead_letter.record_dispatch_failure — increments on a
  non-terminal claim; explicit no-op on terminal / missing claim; at 3
  strikes routes to DLQ (DEAD + dead-letter artifact).
- [x] 1.6 fast: claim_migrator — obstacle claim -> PROVEN without walked
  ladder REJECTED with the named TARGET LADDER GATE reason; with ladder +
  inventory + minted siblings the gate passes (register modified).
- [x] 1.7 tests/test_obstacle_ladder_integration.py (integration leg):
  post_check dispatch-failure face — failed worker status increments the
  claim; done stays silent; hook face fails open on garbage input.

## 2. GREEN

- [x] 2.1 scripts/target_ladder.py: levels, class enumerations, fallback,
  ladder_defects, load_ladder, settlement_blocker, mint_sibling_claims,
  CLI (--check / --mint).
- [x] 2.2 scripts/kunglao_record.py: fail-closed TARGET LADDER GATE block
  in claim_migrator (obstacle-origin PROVEN only; ImportError = BLOCKED).
- [x] 2.3 scripts/dead_letter.py: record_dispatch_failure (+ DLQ route).
- [x] 2.4 hooks/worker_budget_sinks.py: post_check fail-open wiring.

## 3. Registry + verification

- [x] 3.1 tests/_tiers.py: test_obstacle_ladder -> FAST_MODULES;
  test_obstacle_ladder_integration stays on the integration leg (default).
- [x] 3.2 uv run python -m pytest tests/test_failure_analysis*.py -q
- [x] 3.3 fast tier full: -m "fast and not docs" -n auto --dist loadgroup -q
- [x] 3.4 uv run ruff check on every touched file — "All checks passed!"
- [x] 3.5 GitNexus impact (repo kunglao-agent, fresh index @ 6e8cec2):
  post_check LOW (3 impacted, d=1 main; no processes), claim_migrator LOW
  (5 impacted, d=1 main, d=2 kunglao.cmd_record; no processes),
  mark_dead LOW (d=1 main). detect-changes CLI cannot map a linked-worktree
  diff (it maps the main checkout) — changed-symbol mapping done by hand:
  post_check, claim_migrator, dead_letter.scan/mark_dead/DLQ_ATTEMPTS.
- [x] 3.6 results: test_failure_analysis*.py 13 passed; targeted family
  (dead_letter/dlq/infeasible/lessons/registry) 34 passed; adjacent
  (completion_gate #233, register_proven_gate, priority_ratio, retract,
  refutation, status_defs) 117 passed; claim_migrator/worker_budget
  adjacent 140 passed; fast tier full 2986 passed / 2 failed -> catalog
  fixed (declaration_scan 16 passed), t0 flake passes standalone
  (pre-existing load flake, unrelated); tier census full-collection
  6 passed 1 skipped; new tests 25 fast + 6 integration = 31 passed.

## 4. Adversarial review r2 (verdict BLOCK addressed)

- [x] 4.1 F1: hook-side backstop `compare_register_change_proven_gate`
  runs settlement_blocker for every newly-PROVEN claim (register text it
  already read; fail-closed import). Tests: backstop bypass rejected /
  walked-absent (fast), post_check rc=2 with TARGET LADDER GATE (integration).
- [x] 4.2 F2: obstacle_class pinned on the parent claim at promotion
  (`--obstacle-class`, closure-backfill preserve); settlement + mint
  cross-check the artifact's declared class (unpinned / undeclared /
  mismatch = fail-closed defect). Tests: tamper / unpinned / undeclared.
- [x] 4.3 F3: mint guarded on parent existence + failure-obstacle origin +
  walked-valid ladder (against the claim-pinned class) + non-empty
  inventory; explicit refusal receipt; idempotency marker case-insensitive.
  Tests: ghost parent / wrong origin / gapped ladder refusals.
- [x] 4.4 F4: `_origin_from_register` regex deleted; settlement_blocker
  derives origin + siblings from ONE yaml parse of the caller's register
  text (file read only when no text supplied).
- [x] 4.5 F5: transcript fallback anchored to the transcript's own closing
  `status:` line; entry-missing path warns when a claim dispatch was
  expected, silent for non-claim Agent calls. Tests: quoted-fragment
  no-strike, closing-failed strike, warn / silent paths.
- [x] 4.6 F6: strike-3 escalates to the charter must-ask lane
  (blockers/must-ask-<claim>.md + `must_ask` event, status untouched);
  mark_dead stays the explicit --mark face. Tests: fast + integration
  no-DEAD assertions; DLQ_ATTEMPTS == LADDER_EXHAUSTION_MIN_ATTEMPTS pin.
