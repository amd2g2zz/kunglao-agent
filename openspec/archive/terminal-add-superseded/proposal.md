# Add SUPERSEDED to status_defs.TERMINAL

## Summary
`SUPERSEDED` is a specced claim status (guardrails C3, references/schema.md) written to `claim-register.yaml` when a claim is closed via supersession, but it was never added to `status_defs.TERMINAL`. Both dispatch-path consumers — `priority._is_open()` and `convergence_check._open_claims()` — define "open" as `status not in TERMINAL and status not in IN_PROGRESS_STATUSES`, so they count SUPERSEDED claims as OPEN. After a failure-blocked gate on a superseded claim clears, convergence flips BLOCKED → DISPATCH (exit 1) instead of CONVERGED, and `priority.py` ranks the superseded claim as the sole dispatchable claim — an orchestrator following convergence → priority → dispatch-top spins a worker on an already-closed claim.

## Motivation
- **Customer incident (a2b5e25c, C-019)**: observed live — `convergence_check.py` returned `DISPATCH` with `open_claims=[{id:C-019, status:SUPERSEDED}]` after failure-analysis cleared C-019's blocked state. C-019 is closed (`superseded_by: C-037/C-038/C-039`) but the dispatch path does not recognize it as terminal.
- **Root cause**: indirect regression from #47 (fact-contradiction, PR #52) which added the `supersedes`/`superseded_by` frontmatter convention and the CONFLICT gate. The SUPERSEDED *status* was specced and is written to the register, but the TERMINAL set at `scripts/status_defs.py:62` was never updated to include it.
- **Impact**: the convergence loop (v1.9 core mechanic) cannot reach CONVERGED while any superseded claim exists; every tick re-dispatches it. T0 regression in the orchestrator's core loop.

## What Changes
- `scripts/status_defs.py`: add `"SUPERSEDED"` to the `TERMINAL` set (single source of truth; `test_consumer_has_no_own_status_set` grep guard already prevents consumer drift).
- No other file changes: `priority._is_open()` and `convergence_check._open_claims()` both import `TERMINAL` from `status_defs`, so the fix propagates automatically.

## Scope
- **In**: one-line TERMINAL addition + RED/GREEN tests proving SUPERSEDED is excluded from the open set by both `priority.rank_claims` and `convergence_check._open_claims`.
- **Out**: reading the `superseded_by` field in the dispatch path (status field is the gate — YAGNI); adding DEAD (belongs to #36); changing the contradiction gate's STAMP semantics; backfilling historical claims (read-side fix needs no migration).
