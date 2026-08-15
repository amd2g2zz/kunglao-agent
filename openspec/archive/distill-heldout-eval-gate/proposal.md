# Proposal — gate memory distillation behind held-out evaluation and rollback (#82)

## Why

The distillation script explicitly calls its core step a stub (`memory/scripts/distill.py` L23-L25: "Replace with an LLM call when the orchestrator is wired up"), and its write path (L115-L148) emits a templated longterm entry directly into production memory with no candidate state, no held-in/held-out score, no independent evaluator, no promotion condition, no rollback, retirement, or expiry record. The moment rule generation is wired, directly treating a distillation as a production rule can preserve noisy observations, reward an overfit rule, or make future prompts worse with no objective way to detect or roll back the regression.

## What Changes

- **Candidate-first distillation** (`memory/scripts/distill.py`): the pipeline's durable output becomes an immutable `CANDIDATE` record in `memory/candidates/`, carrying source content hashes, generator/candidate versions, and a snapshot reference. Production `longterm/` is untouched until promotion. There is no path from staging to production that skips the candidate.
- **Candidate lifecycle** (new `memory/scripts/evaluate.py` + `memory/scripts/promote.py`): `CANDIDATE → EVALUATED → PROMOTED | REJECTED | EXPIRED`, plus `RETIRED` for promoted rules. State transitions are append-only rows in `memory/lifecycle-journal.jsonl`; candidate files are immutable and content-addressed.
- **Isolated candidate lab**: evaluation runs only in the lab with evaluator-owned scoring. Hidden fixtures (held-in/held-out cases and their oracles) and policy invariants are hash-pinned in `memory/candidates/corpus/manifest.json` and are not writable by the candidate.
- **Promotion gate**: promote only when ALL of — a complete evaluator receipt (per the #81 receipt contract), predefined held-out gain ≥ threshold, no safety-case regression, source-hash lineage intact, and an independently produced score. Any violation → `REJECTED` with a journal row; production rules unchanged.
- **Rollback / retirement / expiry**: `memory/rules-registry.json` snapshots every active rule set (byte backup + per-file digests); rollback restores the exact prior rule set and records action/reason/digests. Expired candidates are never promotable; retired rules are archived with a reason.
- **Failure semantics**: generation or evaluation failure produces a reproducible failure receipt and keeps raw staging evidence; staging is cleared only after the candidate record is durably verified AND a completed receipt exists.
- **BREAKING**: `--promote-direct`-style immediate longterm writing is removed — distill output is a candidate by default, never a production rule.

## Capabilities

### New Capabilities

- `distill-heldout-eval-gate`: candidate-first distillation lifecycle — immutable candidate records, evaluator-owned held-in/held-out scoring in an isolated lab, the promotion gate, rollback to last-known-good, retirement/expiry, reproducible failure receipts, and source-evidence retention.

### Modified Capabilities

(none — `openspec/specs/` has no existing memory-capability spec; this change introduces the first)

## Impact

- `memory/scripts/distill.py` — candidate production and failure semantics (default path reworked; `--threshold` / `--force` / `--dry-run` kept).
- New: `memory/scripts/evaluate.py`, `memory/scripts/promote.py`, `memory/candidates/` (records + `receipts/` + `corpus/`), `memory/rules-registry.json`, `memory/rules-backup/`, `memory/lifecycle-journal.jsonl`.
- Tests: new `tests/test_distill_candidate_gate.py` (RED first) covering duplicate candidates, stale/expired candidates, evaluator failure, forged-success receipts, and source-evidence retention.
- Interface contract with #81 (`executable-l2-evaluation`, in flight on wt81 — its spec is ground truth): #82 CONSUMES the #81 receipt schema and evaluator-ownership model. Score production stays with the evaluator (hidden oracle); #82 never re-implements scoring, never writes `eval/fixtures/`, never edits #81-owned files. Dependency direction: #82 depends on #81's receipts.
- Not touched by this issue: `scripts/kunglao_eval.py`, `eval/fixtures/`, `scripts/kunglao_verify.py`, `memory/scripts/forget.py`, `memory/scripts/recall.py`.
- Related: extends outcome capture (#35) and lesson storage (#41); the current stub synthesis in distill.py remains the template generator until LLM wiring (its OUTPUT is what becomes a candidate).
