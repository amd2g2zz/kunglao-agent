# Design — cleanup-routing-module

## Approach

Pure deletion + spec/doc prose removal. No new code. The "test" is negative-space verification: after removal, the suite collects without ERROR and no routing symbols remain.

## Files touched

| File | Action |
|---|---|
| `scripts/method_router.py` | delete |
| `scripts/method_topk.py` | delete |
| `scripts/method_router_register.py` | delete |
| `tests/test_method_router.py` | delete (pre-existing collection ERROR — method-graph.yaml missing) |
| `tests/test_method_topk.py` | delete |
| `specs/phase-4/contract.md` | remove routing sections |
| `SKILL.md` | remove routing prose if present |
| `DESIGN.md` | remove routing prose if present |

## Verification (TDD gate for a deletion)

1. Before (baseline): `test_method_router.py` errors at collection (known).
2. After (green): `pytest` collects clean; `git grep -iE "method_router|method_topk" scripts/ tests/` empty.

## Risk

Low — module is dead (not imported by production path; only by its own tests). Deletion cannot break runtime.
