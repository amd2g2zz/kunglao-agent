# primary-questions-schema-normalization

## Why

A mapping-shaped `primary_questions` config (e.g. the legacy one-key mapping `- q1: sample family`) is silently treated as an EMPTY question set: `_pq_ids()` and `_unverified_primary_questions()` only accept an `id`-keyed dict, so the M2 completeness gates (orphan terminal claims, unanswered mandatory questions, note-layer sign-off) are skipped and `decide()` returns `CONVERGED` / exit code 0 on an unattended RE run — a FALSE COMPLETION signal. Regression introduced by commit c3be3c6 (historical `q.keys()` extraction replaced by `q.get("id")`).

## What Changes

- ONE canonical parse of `primary_questions` at the task-spec load boundary, with a SINGLE parsed representation shared by `_pq_ids()`, `_unverified_primary_questions()`, the orphan check and the note-layer check.
- Accepted forms, normalized deterministically: canonical `{id: ..., need: ...}` dict (template form), plain string, approved legacy one-key mapping (`{qid: description}`), and explicit empty list/mapping (= feature unused).
- Malformed, mixed-with-malformed, or unrecognized NON-EMPTY `primary_questions` NEVER silently translate to an empty set: `decide()` returns decision `INVALID` (exit code 4, non-zero) with the parsing reason in `action` and a new `pq_parse_error` diagnostic field.
- Explicit deterministic tests for every fixture shape: canonical / string / legacy one-key / empty list / malformed / mixed.

## Capabilities

### New Capabilities
- `primary-questions-schema-normalization`: canonical parsing of `task_spec.yaml#primary_questions` plus an `INVALID` result for non-empty malformed question sets, so non-empty invalid schemas, orphan terminal claims, and unanswered/non-PROVEN mandatory questions can never yield `CONVERGED` or exit code 0.

### Modified Capabilities
- (none — `openspec/specs/` has no main specs yet; this change ships its own delta spec like prior changes)

## Impact

- `scripts/convergence_check.py`: one new parse function `_parse_primary_questions()`; `_pq_ids()`, `_unverified_primary_questions()`, `decide()` refactored to use it; `decide()` gains the `INVALID` decision path and `pq_parse_error` field. `_orphan_terminal_claims()` and `_note_layer_gaps()` signatures unchanged (they already take the normalized ID set).
- `tests/test_convergence_completeness.py`: new RED5+ fixture-shape tests (same file, so the focused command covers them).
- Exit-code contract unchanged for hooks: `INVALID` reuses `EXIT_BLOCKED` (4) — `hooks/worker_pulse.py` already accepts returncodes 0–4.
- No new script files; `scripts/` count unchanged.
