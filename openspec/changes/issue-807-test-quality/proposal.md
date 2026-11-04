# Issue #807 — test quality rail: de-bloat + measured 70% coverage floor (amends #564)

## Why

The suite is 744 files / ~10,332 test functions with sub-70% measured coverage
and bloat classes the owner's 2026-10-23 planning session flagged: tests that
assert only mock-call shapes, duplicated goldens of CI-regenerated files, pins
on dead symbols, and parameter-redundant duplicates. The #564 policy made
coverage OBSERVATION-only; this card amends it to a scoped, enforced floor.

## What Changes

1. **Inventory tool** (`scripts/test_inventory.py`): AST-based classifier over
   `tests/` producing per-class counts for the four bloat classes
   (mock-shape-only, generated-file goldens, dead-code pins,
   parameter-redundant). Inventory output committed as evidence BEFORE any
   deletion (evidence-before-deletion discipline, #807 Face 1).
2. **De-bloat**: delete only provably-redundant or dead-subject tests; every
   removal names the surviving test that inherits the protection obligation.
   Net test-function delta must go DOWN. No blanket deletes.
3. **Measured floor**: measured set = `scripts/` + `hooks/` sources (the same
   `--cov=scripts --cov=hooks` scope the release-check integration leg already
   uses). Baseline recorded, floor = 70.0 minimum, enforced in CI via
   `scripts/coverage_floor.py check` against a monotone ratchet file
   `coverage-floor.json` (hygiene-baseline / #520 precedent; floor can only
   move UP — enforced by a guard test pin AND a CI base-ref comparison).
4. **#564 amendment**: `tests/test_coverage_policy_564.py` updated (not
   deleted): policy text "observation-only" → "observation at pytest.ini
   level; enforced floor on the measured set in CI (#807)". The raw
   `--cov-fail-under` ban everywhere remains (enforcement is ratchet-file
   based, which is strictly stronger because it cannot silently move down).

## Capabilities

### Modified: testing
- Coverage policy: OBSERVATION → enforced floor on the measured set.
- New artifacts: `coverage-floor.json`, `scripts/coverage_floor.py`,
  `scripts/test_inventory.py`, CI floor + ratchet-monotone steps in
  release-check.yml.

## Impact

- Specs: `specs/testing/spec.md`
- Code: `.github/workflows/release-check.yml`, `tests/test_coverage_policy_564.py`,
  `tests/test_coverage_floor_ratchet_807.py` (new), pytest.ini / pyproject.toml
  policy comments.
- NOT touched: scripts/rlvr/*, dispatch_gate.py, heartbeat/mechanisms
  (parallel agents' surfaces); no existing coverage expectation lowered.

## Invariants cited

- **INV-006 (iron-log append-tolerance)**: ratchet file follows the same
  one-way ledger semantics — writes that would lower the recorded floor are
  refused by guard test + CI comparison (append/raise-only).
- #463 Gate framework: Gate 4 (mutation validity) REMAINS the primary
  effectiveness metric; the floor is a scoped hygiene rail under it, not a
  replacement (#564 semantics preserved, amended not reverted).
