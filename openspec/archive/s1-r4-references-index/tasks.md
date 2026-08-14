# Tasks — references/INDEX.md navigation index (#115)

## Phase 1: RED (test first)

- [x] T1: Write `tests/test_references_index.py` with 5 assertions (exists, coverage, no ghosts, non-empty columns, count).
- [x] T2: Run test — confirm 1 failure (INDEX.md missing).

## Phase 2: GREEN (implement)

- [x] T3: Read all 48 `*.md` files in `references/` to determine purpose and trigger.
- [x] T4: Create `references/INDEX.md` with two tables (top-level + re-library), 48 entries.
- [x] T5: Run test — confirm 5 passed.

## Phase 3: VERIFY

- [x] T6: Run full suite — confirm no regressions (same 2 pre-existing failures).
- [x] T7: Stage all new files.

## Phase 4: SDD

- [x] T8: Create openspec change artifacts (proposal.md, design.md, tasks.md).
- [x] T9: Validate openspec change.
