## Context

`scripts/convergence_check.py` decides "should I dispatch right now?" and is the executable form of the convergence loop. Since commit c3be3c6, `_pq_ids()` and `_unverified_primary_questions()` extract question IDs via `q.get("id")`, which only matches the canonical dict form documented in `templates/task_spec.yaml` (`- id: q1 / q: ... / need: ...`). The legacy one-key mapping (`- q1: sample family`) — which the pre-regression code handled via `q.keys()` — now yields an empty ID set. Because `_orphan_terminal_claims()` treats an empty ID set as "feature unused", the M2 completeness gates silently stop firing: an unattended run with an orphan terminal claim or an unanswered mandatory question returns `CONVERGED` / exit 0. Tests `tests/test_convergence_completeness.py` RED1/RED2 encode the intended M2 behavior and currently fail (4 failures).

Consumers of the decision: `hooks/worker_pulse.py` (accepts returncodes 0–4, fails open), `hooks/worker_budget.py`, `rules/kunglao-convergence-loop.md` (0=CONVERGED … 4=BLOCKED). Only `convergence_check.py` itself consumes `_pq_ids` / `_unverified_primary_questions` — no other module imports them. `scripts/acceptance_check.py` writes the plain-string form (`- q1`) into task_spec fixtures, so that form is real usage, not hypothetical.

## Goals / Non-Goals

**Goals:**
- One canonical parse of `primary_questions` at the load boundary; a single parsed representation feeds `_pq_ids`, `_unverified_primary_questions`, the orphan check, and the note-layer check.
- Normalize the approved legacy one-key mapping (and preserve the top-level mapping + plain-string forms) so historical workspaces get the M2 gates they were written for.
- Any non-empty malformed / mixed-with-malformed / unrecognized shape yields a machine-readable non-zero `INVALID` result with the reason — never a silent empty set.
- Deterministic tests for each fixture shape in `tests/test_convergence_completeness.py` (kept in that file so the focused command covers them).

**Non-Goals:**
- Not changing the `need` semantics or the satisfaction rules of `_unverified_primary_questions` (already covered by M2).
- Not touching other task_spec readers (`digest_build.py`, `acceptance_check.py`) — they have their own tolerance and no reported bug.
- Not adding a new exit code: hooks contract stays 0–4.

## Decisions

**D1. Normalize the legacy one-key mapping instead of rejecting it.**
The issue allows either. Normalizing is safer for unattended runs: a historical workspace whose task_spec uses `- q1: family` is a *working* config (it used to work before c3be3c6); rejecting it would turn today's silent false-CONVERGED into a hard BLOCK for every legacy workspace. Rejection is reserved for genuinely unrecognizable shapes. The mapping value is a free-text description, not a `need` enum, so it normalizes to `need=None` (which requires a PROVEN answering claim — the same satisfaction rule the pre-regression code applied, since `q.get("id")`-era string keys also had `need=None`).

**D2. New decision `INVALID` reusing `EXIT_BLOCKED` (4).**
A distinct decision name keeps output machine-readable (`d["decision"] == "INVALID"`), while reusing exit 4 keeps `hooks/worker_pulse.py`'s `returncode in (0,1,2,3,4)` gate working without touching hooks (out of scope). BLOCKED semantics ("escalate with specifics") fit: an invalid task spec needs human intervention. The `action` carries the reason and a new `pq_parse_error` JSON field carries it machine-readably. Alternatives considered: a new exit code 5 — rejected because worker_pulse would stop parsing the JSON (fail-open is acceptable but worse), and the task scope forbids hook edits.

**D3. `INVALID` is checked before the rest of the decision matrix.**
If the convergence target itself is unparseable, dispatching more claims against it is wrong even when open claims exist — the run cannot converge by construction. Escalation (exit 4) tells the orchestrator/user to fix the spec. This is the fail-closed reading of the issue's "must not yield CONVERGED" and its "unattended RE run" concern.

**D4. Mixed-format lists normalize per item; any invalid item fails the whole list.**
`[q1, {id: q2, need: ...}, {q3: text}]` is a legitimate mix of accepted forms → normalized to `{q1, q2, q3}` (deterministic). `[q1, 42]` → `INVALID` with item index in the reason — never silently reduced to `{q1}`, which would re-create the same class of bug (partial question set treated as complete).

**D5. Duplicate question ids are malformed.**
A duplicated mandatory question id is a config error (two answers can't be distinguished); deduping silently would hide it. Deterministic rejection with the duplicate named in the reason.

**D6. Explicit empty (`[]`, `{}`, key absent) stays "feature unused".**
`primary_questions: []` is the documented way to opt out (the M2 gate then skips the orphan check — existing behavior, existing tests depend on it). Only NON-EMPTY malformed input is escalated.

## Risks / Trade-offs

- [Legacy one-key value contains a real `need` word] → It normalizes to `need=None` → requires PROVEN. Pre-regression behavior was identical; a `need` in the description was never honored by this file. Documented in D1.
- [Top-level mapping `{q1: family}` value ignored] → Pre-regression behavior ignored values too (string-key iteration). Preserved exactly; only the ID set matters to the gates.
- [A future spec field on `primary_questions` items (e.g. new `need` value) rejected as non-string] → Parse only requires `id`; unknown extra keys are ignored, so forward-compatible additions don't break parsing. Only malformed `id`/shape fails.
- [`INVALID` blocks dispatch in open-claim workspaces] → Intended fail-closed behavior (D3); the action message tells the operator exactly what to fix.

## Migration Plan

1. Ship parse + `INVALID` path; legacy and canonical workspaces behave identically to pre-regression intent (gates fire).
2. No data migration: task_spec files are unchanged on disk; parsing is purely read-side.
3. Rollback: revert to the pre-fix commit restores current behavior; no workspace state is modified by this change (read-only script + tests).

## Open Questions

- None blocking. (Whether to eventually *warn* on legacy mapping usage rather than silently accept — future docs/cleanup issue, not this one.)
