# Design — dlq-dead-letter (#36)

## Design Decisions

### D1. DEAD lives in the single source of truth (status_defs.TERMINAL)

`TERMINAL` is the set every consumer imports (#34). Adding `"DEAD"` once
propagates to `convergence_check._open_claims`, `priority._is_open`,
`claim_expiry`, `failure_analysis_gate`, `stale_blocker_prune`,
`plan_drift_detector`, `kunglao_record`, `progress_report` — all of which test
`status not in TERMINAL`. The grep guard
`test_consumer_has_no_own_status_set` prevents any consumer from drifting.
This mirrors #59's SUPERSEDED landing exactly (read-side fix via one set).

DEAD MUST NOT appear in `PARTIAL_STATUSES` or `IN_PROGRESS_STATUSES` — a DEAD
claim needs no further work and is not in-flight. The contract tests pin this.

### D2. mark_dead writes the three-field status pattern (mirror STALE)

`claim_expiry.py:93-100` is the established pattern for writing a claim
status: set `status`, plus a `<state>_at` ISO timestamp and a
`<state>_reason` string. `mark_dead` mirrors it:

```
c["status"] = "DEAD"
c["dead_at"] = utc_now_iso()
c["dead_reason"] = reason or "promotion_attempts exhausted (DLQ)"
```

then dumps the register back (yaml.safe_dump, sort_keys=False,
allow_unicode=True — same as claim_expiry's `_write_yaml`). The function
returns `{"marked": True, "claim_id", "status": "DEAD"}` on success, or
`{"marked": False, "reason": "claim <id> not found"}` when the claim is
absent (explicit REJECT, never a silent no-op).

### D3. Quarantine artifact — blockers/dead-letter-<claim>.md

The artifact records WHY the claim was killed, so the failure history is
auditable without re-deriving it from the ledger. It is written under
`blockers/` (the existing blocker directory; `convergence_check._active_blockers`
already scans this dir, but the artifact filename prefix `dead-letter-` is
distinct from real blockers and carries the exit reason inline). Fields:
status / dead_at / dead_reason / promotion_attempts / a pointer to the
failure-analysis file. `mark_dead` creates `blockers/` if missing
(`mkdir(parents=True, exist_ok=True)`).

### D4. scan — the dangling set

`scan(workspace)` returns claim ids where `promotion_attempts >= 3` AND
`status` is not terminal. This is the "should-have-been-DEAD" set — the
diagnostic that surfaces dangling claims so the orchestrator (or operator)
can decide to `mark_dead` them. It is read-only: scan never auto-promotes
claims to DEAD (auto-promotion is out of scope; the operating manual
separates "detect" from "act"). Claims already DEAD short-circuit on the
TERMINAL check, so they are never re-reported.

### D5. detect_dirty_statuses — the enum linter

`detect_dirty_statuses(workspace)` returns claim ids whose `status` literal is
not in the legal set:
`TERMINAL ∪ {"OPEN", "IN_PROGRESS", "PARTIALLY-VERIFIED", "PARTIAL",
"PARTIALLY_VERIFIED", "STAMP", "UNVERIFIED"}`. This catches `PASS-`
(observed in the real register) and any other typo. It is a report-only
linter — it never rewrites the register. The legal set is computed from
`status_defs.TERMINAL` (single source) plus the non-terminal literals
declared in `status_defs` (ACTIVE_STATUSES, PARTIAL_STATUSES,
IN_PROGRESS_STATUSES) plus the two legacy pseudo-statuses STAMP/UNVERIFIED
used by `convergence_check.NON_PROVEN_ANSWER`.

### D6. worker_pulse quarantined flag

`_build_pulse` assembles a compact flags line
(`stuck=...; failure-blocked=...; partial=N; blockers=...`). The DLQ adds
`quarantined=N` where N is the count of DEAD claims in the register. The
pulse already shells out to convergence_check/priority; for quarantined it
runs `dead_letter.py <ws>` and parses the scan line, OR — cheaper — counts
DEAD claims directly. The minimal, in-tree implementation imports
`dead_letter` as a sibling module and counts DEAD in the register (no extra
subprocess). The flag is appended only when N > 0 (matches the existing
"omit zero" style of the partial/blockers flags).

### D7. No convergence_check / priority edit

`_open_claims` and `_is_open` both define open as
`status not in TERMINAL and status not in IN_PROGRESS_STATUSES`. Once DEAD ∈
TERMINAL, both exclude it automatically — zero code change, exactly the #34
design intent and the #59 precedent. This is verified by the
`test_dead_excluded_from_open` test.

## File layout

| File | Action | Purpose |
|---|---|---|
| `scripts/status_defs.py` | UPDATE | `TERMINAL` += `"DEAD"` (7→8) + docstring count + #36 landed note |
| `scripts/dead_letter.py` | CREATE | `mark_dead` / `scan` / `detect_dirty_statuses` / `main` CLI |
| `scripts/test_dead_letter.py` | CREATE | RED→GREEN TDD (5 tests) |
| `scripts/test_status_defs.py` | UPDATE | contract test 7→8 valued (rename + DEAD) |
| `hooks/worker_pulse.py` | UPDATE | `quarantined=N` flag in `_build_pulse` |

## Out of scope
- Auto-promotion of exhausted claims to DEAD (scan reports; `mark_dead` is
  explicit). Issue scope is "DEAD status + quarantine", not "auto-killer".
- DEAD → revive / poison-recovery path (separate issue).
- New `LedgerLineType` (DEAD is a claim status — operating-manual step 3).
- Extending convergence_check's JSON with a `quarantined` field (the pulse
  derives the count in-tree; convergence_check JSON change is not required
  for this issue).
