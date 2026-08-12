# #144: D1/D5/D13/C10 Verify-Only Closure

## D1: Three contract sources no mechanical arbitration
- **Status**: COVERED. `check_global_rule_subset.py` (#99) validates
  global rules → SKILL.md direction. SKILL.md is canonical when they disagree
  (explicitly stated in SKILL.md header). No further action needed.

## D5: Convergence exit codes advisory
- **Status**: COVERED. All 5 exit codes (0/1/2/3/4) are mechanically
  gated by convergence_check.py → orchestrator decision table. Exit code 64
  (F14) documented in #127. No ungated exit codes remain.

## D13: Hook FAIL_OPEN/CLOSED rationale undocumented
- **Status**: NEEDS DOC (table below). Two-tier classification from #98
  provides the mechanism; this table documents the rationale.

| Hook | Fail Strategy | Rationale |
|---|---|---|
| worker_budget | FAIL_CLOSED | Over-dispatching workers wastes resources + violates ≤3 constraint |
| worker_pulse | FAIL_OPEN | Pulse is advisory; missing pulse shouldn't block work |
| dispatch_gate | FAIL_CLOSED | Gate exists to prevent bad dispatches; bypass defeats purpose |
| stuck_gate | FAIL_OPEN | Stuck detection is advisory; false positive shouldn't block |
| cost_gate | FAIL_OPEN | Cost is informational (behavior #3); never a stop reason |

## C10: Deterministic state machine precondition
- **Status**: COVERED. Two-tier exception classification (#98) provides
  event-driven degradation. Stronger hard-precondition not worth the
  complexity — current design handles edge cases via tier fallback.
