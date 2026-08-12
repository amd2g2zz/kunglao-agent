# hooks-status-defs-import — Fix hooks/ local TERMINAL_STATUS / PARTIAL_STATUSES copies (Issue #95)

## Defect

`hooks/worker_budget.py` defines a local 5-value `TERMINAL_STATUS = {'PROVEN', 'VERIFIED', 'NEGATIVE', 'REFUTED', 'DEFERRED'}` that never imports from `scripts/status_defs.py` (the single source of truth per #34). Similarly, `hooks/state_anchor.py` defines a local `_PARTIAL_STATUSES` copy. The guard in `test_status_defs.py::test_consumer_has_no_own_status_set` only scans `scripts/`, not `hooks/`, so the drift goes undetected.

## Consequence

- `check_tier_gate` in worker_budget.py treats DEAD/SUPERSEDED/STALE claims as open (not in the 5-value TERMINAL_STATUS), incorrectly blocking dispatch when evidence_tier=0 (D2/F1 from absorption-research-round2.md).
- Any future addition to `status_defs.TERMINAL` (like DEAD in #36, SUPERSEDED in #59) silently misses hooks consumers.

## Fix direction

1. `hooks/worker_budget.py`: import `TERMINAL` from `status_defs`, remove local 5-value copy. The existing `sys.path.insert(0, str(_SKILL_ROOT / 'scripts'))` pattern (used for priority import) already makes scripts/ importable.
2. `hooks/state_anchor.py`: import `PARTIAL_STATUSES` from `status_defs`, remove local `_PARTIAL_STATUSES` copy. Same sys.path pattern.
3. Expand the grep guard in `test_status_defs.py` to scan `hooks/` in addition to `scripts/`.
4. `TERMINAL_CLAIM_STATUSES` in worker_budget.py (line 343) is a DIFFERENT concept (worker self-promotion guard — intentionally excludes VERIFIED) and must NOT be changed.

## Non-goals

- Do NOT modify `scripts/status_defs.py` (only consumers change their import source).
- Do NOT introduce new status values.
- Do NOT change the semantic meaning of any existing set.
