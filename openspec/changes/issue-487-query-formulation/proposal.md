## Why
Issue #487 (owner finding 2026-10-01): the online-distillation flow (#458/#474) jumps from
shelf-miss trigger straight to mixed-source retrieval — the query is whatever fragments the
trigger carried (a worker vocabulary token like `crypto:decode`). Without first ENUMERATING
AND SUMMARIZING the current problem, search/recall matching and coverage are structurally
poor. The raw material for a problem representation already sits in every workspace (the
environment snapshot: die/apkid probe evidence; the obstacle registry: `runs/obstacles/`;
the tried-and-failed marker itself) — nothing consumes it before retrieval.

## What Changes
New module `scripts/query_formulation.py` (mechanical, stdlib-only, no LLM / no network —
the #474 engine discipline):

- `formulate_problem(ws, trigger)` → `query-formulation/1`: 3–5 typed facets
  (format_family / technique / tool / error_signature), every term carrying provenance
  (source file + field) from the environment snapshot and the obstacle registry (read
  through `rlvr.obstacles`, the sanctioned reader).
- Per-facet retrieval over the local re-library (`references/re-library/`), each facet
  independently, recorded as the `distill-coverage/1` matrix (per-facet hit/miss + hit
  cards + verdicts).
- Empty-facet disambiguation: ONE reformulation pass (the facet re-worded from its
  provenance terms); still-empty → `corpus-lack` verdict — the real shelf-miss; the act
  proceeds exactly as today (web face, T/L spine #478 unchanged).
- Wire-in: the e2e distill act starts with formulation — the dispatch prompt carries the
  facets + coverage matrix, and the `distill_result` audit row's detail carries the
  coverage matrix; the production closure stamps formulation + coverage into
  `runs/distill-trigger.json` so the orchestrator's dispatch prompt consumes the same
  object; `online_distill.formulate_for_trigger` is the engine-side delegate (fail-open).
- Fixture `tests/fixtures/query-formulation-487/`: a fixture corpus where good
  formulation beats fragment queries, with the hit-rate comparison pinned in a test.

No budget semantics change (formulation spends nothing); no vocabulary growth (the three
distill words carry the coverage in `detail`); no spine/landing change.
