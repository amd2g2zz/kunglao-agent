# cleanup-routing-module

## What

Delete the experimentally-refuted routing module: `scripts/method_router.py`, `scripts/method_topk.py`, `scripts/method_router_register.py`, their tests, and all routing sections in `specs/phase-4/contract.md` + routing prose in SKILL.md / DESIGN.md.

## Why

The routing layer (method_router / method_topk / resource selection) was **experimentally refuted → CUT**. In the gate-telemetry experiment (real worker dispatch on C-401/C-402), the LLM agent self-selected and self-swapped tools throughout (pefile -> xxd -> capstone -> bcrypt_hook) with zero help from the routing layer. Routing value approx 0. The design docs (`docs/refactor/refactor-plan.md` top verdict) already record this CUT; the code on master still carries the dead module.

## Scope

**In**:
- `scripts/method_router.py`, `scripts/method_topk.py`, `scripts/method_router_register.py` (delete)
- `tests/test_method_router.py`, `tests/test_method_topk.py` (delete — the former is the pre-existing collection ERROR)
- `specs/phase-4/contract.md` routing sections (method_router semantics, method-graph node table)
- SKILL.md / DESIGN.md routing prose

**Out**: priority_ratio rewrite (issue #2, depends on this clean baseline).

## Acceptance

- `git grep -iE "method_router|method_topk" scripts/ tests/` empty
- `pytest` 0 ERROR (pre-existing method_router collection error disappears)
- dev branch green
