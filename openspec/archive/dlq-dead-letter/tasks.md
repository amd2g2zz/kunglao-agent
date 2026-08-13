# Tasks — dlq-dead-letter (#36)

## 1. Setup
- [x] 1.1 Worktree `wt36` on branch `dlq-dead-letter` off `dev` f0d44b4 (one issue / one PR / one branch / one worktree)
- [x] 1.2 Baseline confirmed: `scripts/` 144 passed; `tests/` 222 passed + 6 pre-existing failures (acceptance, skill-lte-500, 4 convergence-completeness)

## 2. OpenSpec artifacts (SDD)
- [x] 2.1 `openspec new change dlq-dead-letter`
- [x] 2.2 proposal.md (why: dangling exhausted claims + `PASS-` dirty literal; single-source TERMINAL fix)
- [x] 2.3 design.md (D1 single-source / D2 STALE-mirror write / D3 quarantine artifact / D4 scan / D5 dirty linter / D6 pulse flag / D7 no convergence edit)
- [x] 2.4 specs/status-defs/spec.md (5 requirements, each with scenarios)
- [x] 2.5 tasks.md
- [ ] 2.6 `openspec validate dlq-dead-letter` PASS

## 3. RED tests (write first, must fail)
- [ ] 3.1 `scripts/test_dead_letter.py` — 5 RED tests:
  - `test_dead_excluded_from_open` — DEAD claim → `convergence_check._open_claims` == `[]`
  - `test_mark_dead_writes_artifact` — exhausted OPEN claim → DEAD + `blockers/dead-letter-C-2.md`
  - `test_mark_dead_rejects_unknown` — unknown id → `marked: False`, no write
  - `test_scan_finds_exhausted_open` — attempts=3 OPEN → `["C-3"]`; DEAD → `[]`
  - `test_detect_dirty_statuses` — `PASS-` → `["C-4"]`; clean → `[]`
- [ ] 3.2 `scripts/test_status_defs.py` — contract test 7→8 valued (rename `test_terminal_is_7_valued_with_superseded` → `test_terminal_is_8_valued_with_superseded_and_dead`, add DEAD)
- [ ] 3.3 Run pytest; confirm the 5 new RED FAIL and the renamed contract test FAIL (DEAD absent).

## 4. GREEN — implement
- [ ] 4.1 `scripts/status_defs.py`: add `"DEAD"` to `TERMINAL` (7→8); update docstring count (7→8) + add a "#36 landed" note after the SUPERSEDED note; confirm DEAD not in PARTIAL/IN_PROGRESS.
- [ ] 4.2 `scripts/dead_letter.py` (CREATE): `mark_dead` / `scan` / `detect_dirty_statuses` / `main` CLI; `from status_defs import TERMINAL, ACTIVE_STATUSES, PARTIAL_STATUSES, IN_PROGRESS_STATUSES`.
- [ ] 4.3 `hooks/worker_pulse.py`: append `quarantined=N` flag in `_build_pulse` (count DEAD in the register, in-tree import; omit when 0).
- [ ] 4.4 Run pytest; confirm all RED now PASS.

## 5. Full suite + validate
- [ ] 5.1 `pytest scripts/ -q` — 144 baseline + new tests pass (contract test updated, not a new failure).
- [ ] 5.2 `pytest tests/ -q` — 222 baseline + new tests pass; 6 pre-existing failures unchanged.
- [ ] 5.3 `openspec validate dlq-dead-letter` — PASS.
- [ ] 5.4 Spot-check: `grep -rn "DEAD" scripts/ hooks/` — DEAD defined once in status_defs.TERMINAL; referenced via imports.

## 6. Commit (no push / PR — orchestrator handles merge)
- [ ] 6.1 SDD commit: `sdd(dlq-dead-letter): ... (#36)`.
- [ ] 6.2 Impl commit: `feat(dlq): DEAD status + dead-letter quarantine (#36)`.
