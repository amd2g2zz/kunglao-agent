# tasks — fix-233-negative-exits

## 1. RED (TDD)

- [x] 1.1 tests/test_completion_gate.py: RED — oracle item with
  `closed_by: "app only trusts system certs"` (no claim id) → exit 1 with a
  NAMED INVALID_CLOSURE reason.
- [x] 1.2 RED — citation of an OPEN claim → exit 1 named reason.
- [x] 1.3 RED — citation of a settled (terminal, non-REFUTED) obstacle claim
  → exit 1 (path-scoped standard unmet); REFUTED obstacle claim passes.
- [x] 1.4 RED — DEFERRED claim without the task-scoped markers → exit 1;
  with wake_condition + infeasible_ladder → passes.
- [x] 1.5 RED — valid citation (terminal claim id) passes exit 0; prose
  `closed_by` ("verifier", "commit 0001") fails.
- [x] 1.6 RED — unverifiable citation (no workspace / no register / unknown
  id) fails fail-closed.

## 2. GREEN

- [x] 2.1 scripts/completion_gate.py: CLAIM_ID_RE grammar + citation
  verification (`_closure_defects`) wired into judge()'s item loop; exit 1
  reason names each INVALID_CLOSURE with cause.
- [x] 2.2 Import `status_defs.TERMINAL` (literal fallback for standalone face).

## 3. Prose pinning

- [x] 3.1 `find_death_evidence` docstring: pin path-scoped vs task-scoped
  sentences.
- [x] 3.2 references/contracts/agent-three-state-charter.md: pin the two
  sentences in the 判死宣告 row.

## 4. Re-pin existing tests (documented contract change)

- [x] 4.1 tests/test_completion_gate.py `_all_closed_oracle` → register +
  terminal citations.
- [x] 4.2 tests/test_intent_aware_completion.py, test_gate_layers_717.py,
  test_heartbeat_off.py, test_summary_fake_826.py,
  test_failopen_tiering_103.py, test_notes_fake_834.py,
  test_notes_closure_762.py → same re-pin.

## 5. Verification

- [x] 5.1 `uv run python -m pytest -q` full suite green.
- [x] 5.2 `openspec validate fix-233-negative-exits` exits 0.
- [x] 5.3 REVIEW-NOTES-233.md written; changes staged (no commit — review gate).
