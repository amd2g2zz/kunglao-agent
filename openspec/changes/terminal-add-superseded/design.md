# Design — Add SUPERSEDED to TERMINAL

## Context
`status_defs.TERMINAL` is the single source of truth for "claim is closed, needs no more work". The two dispatch-path consumers define "open" identically by set-membership:

- `priority.py:64-68` — `_is_open(c)` returns `c.status not in TERMINAL and c.status not in IN_PROGRESS_STATUSES`; `rank_claims` skips non-open claims at `:151`.
- `convergence_check.py:123-130` — `_open_claims` appends a claim only when the same condition holds.

`SUPERSEDED` matches neither set, so it falls through as open. `grep -rni supersede scripts/` confirms no script reads `superseded_by` or treats SUPERSEDED specially — the field is purely informational today.

## D1 — Read-side fix (extend TERMINAL), not write-side
The SUPERSEDED status is already written correctly (orchestrator-side, when a claim is closed by replacement). The bug is purely that the terminal set does not recognize it. Adding it to TERMINAL is the minimal correct fix: both consumers read this single set, so the fix propagates with one edit.

Rejected:
- **Read `superseded_by` in dispatch path** — unnecessary; the status field already captures "closed", `superseded_by` records *which* claim replaced this one (informational). Reading it duplicates the status check (YAGNI).
- **SUPERSEDED-aware branch in `_is_open`** — special-casing one status when general set-membership works is worse than extending the set.
- **Write DEFERRED instead of SUPERSEDED** — loses semantics; SUPERSEDED is a positive closure by replacement, DEFERRED is a cap-forced defer.

## D2 — No migration
Historical SUPERSEDED claims in existing workspaces become correctly terminal the moment the fix lands (read-side). No backfill, no ledger rewrite.

## D3 — Test surface (RED → GREEN)
1. `test_superseded_in_terminal`: `"SUPERSEDED" in status_defs.TERMINAL` — contract test locking the regression.
2. `test_priority_skips_superseded`: claim-register with one SUPERSEDED claim → `rank_claims` returns `n_dispatchable == 0`.
3. `test_convergence_excludes_superseded`: same register → `_open_claims` returns `[]` and decision is CONVERGED.

GREEN = add `"SUPERSEDED"` to TERMINAL; all three flip.

## D4 — Interaction with #36 (DLQ/DEAD)
#36 adds `DEAD` to the same TERMINAL set. Independent statuses, same set literal. Shipping #59 first means #36 branches from updated dev and includes SUPERSEDED; no conflict as long as #36 adds DEAD to the post-#59 line.

## D5 — No schema change
`SUPERSEDED` is already a recognized status in `references/schema.md` and `references/guardrails.md` (C3 two-way supersedes integrity). This change closes the code-spec gap; it does not introduce a new status. No schema.md edit required.
