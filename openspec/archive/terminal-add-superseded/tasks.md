# Tasks — terminal-add-superseded

## 1. RED — contract + behavior tests
- [ ] Add `tests/test_terminal_superseded.py` with three RED tests:
  - `test_superseded_in_terminal` — `assert "SUPERSEDED" in status_defs.TERMINAL`
  - `test_priority_skips_superseded` — claim-register with one SUPERSEDED claim; `rank_claims` returns `n_dispatchable == 0`
  - `test_convergence_excludes_superseded` — same register; `_open_claims` returns `[]` and decision is CONVERGED
- [ ] Run pytest; confirm all three FAIL (status quo bug).

## 2. GREEN — one-line fix
- [ ] `scripts/status_defs.py`: add `"SUPERSEDED"` to the `TERMINAL` set literal.
- [ ] Run pytest; confirm all three now PASS.

## 3. Full suite
- [ ] `pytest scripts/` — 144 baseline unchanged.
- [ ] `pytest tests/` — prior pass count + 3 new, 6 pre-existing failures unchanged.

## 4. Validate + ship
- [ ] `openspec validate terminal-add-superseded` — PASS.
- [ ] Commit SDD + RED + GREEN.
- [ ] PR `terminal-add-superseded` → dev; closes #59.
