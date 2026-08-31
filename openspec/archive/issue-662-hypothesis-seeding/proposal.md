## Why — Gap Audit Result

Issue #662 acceptance criteria vs origin/dev a0cb8bd state (2026-08-25):

| # | Acceptance Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Every `primary_question` has >=1 H-NN before any C-NN dispatch | **SATISFIED (conventional)** | Mechanism: `digest_build.build_digest` (line 243-244) calls `seed_from_task_spec` before `build_sec_g` — mechanical ordering within the cold-start digest cycle. Test `test_red5_digest_seeds_then_lists`钉死 this ordering. Dispatch side (priority.py / dispatch_gate / hooks) does NOT inspect hypotheses; the "before any C-NN" guarantee is **contractual** (orchestrator LLM reads digest before dispatching). Design spec D4 calls this "mechanically enforced at every cold-start digest build." |
| 2 | Hypotheses surface in cold-start digest | **SATISFIED** | `digest_build.sec_g` calls `build_sec_g` (origin/dev: line 248) after seeder. Tests: `test_digest_sec_g_528.py` (11 tests), `test_coldstart_digest_528.py` (cold-start wiring), `test_hypothesis_seeder.py` (8 tests incl. red5). |
| 3 | A hypothesis contradicted by PROVEN fact -> flag in convergence_check | **GAP** | `convergence_check` has `OPEN_HYPOTHESIS_AT_CLOSE` (line 799-801) — fires on ANY open hypothesis at close, including those contradicted by PROVEN facts. But there is **no dedicated detection** of "open hypothesis candidate vs PROVEN fact" contradiction with a specific annotation (e.g., "contradicted by F-NN: adjudicate as refuted"). The gate is a **generic block**, not a targeted contradiction flag. Full scan of origin/dev: `fact_contradiction_gate.py` only detects fact-vs-fact PROVEN contradictions (#47); no hypothesis-vs-PROVEN-fact detection exists anywhere. |

**Conclusion**: Standards 1 and 2 are met by the PR #667 implementation. Standard 3 has one code gap: the convergence_check action message for `OPEN_HYPOTHESIS_AT_CLOSE` does not annotate which open hypothesis has a PROVEN fact contradicting its candidate set, leaving the analyst to discover the contradiction manually. This fix closes the gap with a string/anchor-level scan (fail-open, no NLP, no heavy dependencies).

## What Changes

**`scripts/convergence_check.py`** — `_act_open_hypothesis` action builder:

1. List all PROVEN facts from `facts/_INDEX.md` (lightweight line scan, same pattern as `_partial_facts`, fail-open).
2. For each open hypothesis, scan its `.md` body text for PROVEN fact references.
3. If the hypothesis body explicitly references a PROVEN fact (marker: `refutes H-NNN` / `F<id>` / `contradicts`), annotate the BLOCKED message with `"contradicted by F-NNN"`.
4. If no explicit contradiction marker found but the hypothesis has `candidates: [...]` that are ruled out by a PROVEN fact (keyword heuristic: if a PROVEN fact conclusion directly negates a candidate string), annotate with `"likely contradicted — F-NNN: <conclusion snippet>"`.
5. Output message format: `Cannot CONVERGE: {n} open hypothesis(ies) {ids} — adjudicate before delivery. Contradicted: H-NNN by F-NNN (refuting_fact_id: F-NN).`

**No changes to**: `hypothesis_seeder.py`, `digest_build.py`, `hypothesis_store.py`, state machine, anchor tests.

## Scope Boundaries

- **IN scope**: annotation in `OPEN_HYPOTHESIS_AT_CLOSE` action message only; fail-open string scan; backward-compatible with empty contradiction cases.
- **OUT of scope**: automatic hypothesis adjudication (refute/supersede write-back); fact_contradiction_gate extension; NLP; heavy semantic analysis.
- **Anchor safety**: `_act_open_hypothesis` message format change is additive only — all existing anchor test fixtures have `open_hypotheses: []` (no open hypotheses), so `_act_open_hypothesis` is never called in the anchor suite. Zero anchor re-pin required.

## Related

- Issue #662 (this closes the last acceptance gap)
- #528 (hypothesis storage + rehydrate — already closed)
- #147 (fact-vs-fact contradiction gate — orthogonal)
- `openspec/changes/issue-662-hypothesis-seed/` (original design, unchanged)
