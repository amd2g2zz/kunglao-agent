# Add DEAD to status_defs.TERMINAL + dead-letter quarantine (#36)

## Summary
Claims whose `promotion_attempts >= 3` (poison / exhausted) currently have no
dedicated terminal status. They linger as OPEN and the convergence loop keeps
re-ranking them every tick — wasting dispatch slots and cost on claims that
will not close. Worse, real workspaces carry dirty status literals like `PASS-`
that are neither terminal nor a recognized intermediate, leaving the state
machine undefined. This change adds `DEAD` to `status_defs.TERMINAL` (the
single source of truth from #34, so the fix propagates to every consumer),
provides an explicit `mark_dead` writer + `blockers/dead-letter-<claim>.md`
quarantine artifact, a `scan` for exhausted-but-not-DEAD claims, a
`detect_dirty_statuses` check for non-enum literals, and surfaces a
`quarantined=N` flag in the worker pulse.

## Motivation
- **Observed in real `claim-register.yaml`**: ~85 claims, zero in DEAD/POISON,
  but `promotion_attempts >= 3` OPEN claims exist (dangling) and a `PASS-`
  dirty literal sits alongside the terminal enum — the state machine has no
  branch for either.
- **Cost leak**: the convergence loop (`convergence_check` → `priority` →
  dispatch-top) re-ranks a dangling exhausted claim every tick; an
  orchestrator following the loop spins a worker on a claim that has already
  failed promotion 3×.
- **Root cause**: there was no terminal status meaning "this claim is closed
  because it is poison, do not retry". #34 reserved the operating manual for
  adding one (status_defs docstring :49-64); #59 exercised the manual for
  SUPERSEDED. This change exercises it for DEAD.

## What Changes
- `scripts/status_defs.py`: add `"DEAD"` to `TERMINAL` (7 → 8 values) and
  update the docstring count + an operating-manual "landed" note for #36.
  DEAD is NOT added to `PARTIAL_STATUSES` or `IN_PROGRESS_STATUSES`.
- `scripts/dead_letter.py` (new):
  - `mark_dead(workspace, claim_id, reason)` — writes `status: DEAD` +
    `dead_at` + `dead_reason` to claim-register.yaml (mirrors the STALE write
    pattern in claim_expiry.py:93-100) and creates
    `blockers/dead-letter-<claim>.md` (failure history + exit reason).
  - `scan(workspace)` — lists claims with `promotion_attempts >= 3` that are
    not yet terminal (the dangling set).
  - `detect_dirty_statuses(workspace)` — lists claims whose status literal is
    not in the legal enum (catches `PASS-`).
  - CLI entry: `scan` (default) / `--mark C-NN` / `--dirty`.
- `scripts/test_dead_letter.py` (new): RED-first TDD.
- `hooks/worker_pulse.py`: append `quarantined=N` to the flags group in
  `_build_pulse` (N = count of DEAD claims, via a dead_letter scan).
- `scripts/test_status_defs.py`: contract test
  `test_terminal_is_7_valued_with_superseded` → 8-valued
  (rename + add DEAD).

## Capabilities

### Modified Capabilities
- `status-defs`: `TERMINAL` gains its 8th member `DEAD`; the read-side
  consumers (`convergence_check._open_claims`, `priority._is_open`,
  `claim_expiry`, etc.) pick it up automatically via the single source of
  truth — no per-consumer edit.

### New Capabilities
- `dead-letter-quarantine`: explicit DEAD writer + quarantine artifact +
  dangling/dirty-status detection for the DLQ.

## Impact
- `scripts/status_defs.py` (UPDATE, ~3 lines): one set literal + docstring.
- `scripts/dead_letter.py` (CREATE, ~110 lines): `mark_dead` / `scan` /
  `detect_dirty_statuses` / `main`.
- `scripts/test_dead_letter.py` (CREATE): 5 RED→GREEN tests.
- `scripts/test_status_defs.py` (UPDATE): contract test 7→8 valued.
- `hooks/worker_pulse.py` (UPDATE, ~6 lines): `quarantined` flag.
- No convergence_check / priority edit needed — DEAD ∈ TERMINAL propagates.
- No `LedgerLineType` change (DEAD is a claim status, not a ledger row kind —
  operating-manual step 3).
- Customer/incident anchor: real claim-register audit (85 claims, dangling
  exhausted + `PASS-` dirty value); referenced by plan
  `issue-36-dlq-dead-letter.plan.md`.
