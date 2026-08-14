## Design

### Current state
`agents/verdict-redteam.md` (84 lines) defines a BLIND adversarial checker that independently re-derives **maliciousness + attribution** via Admiralty+ACH+Diamond from `evidence/*.json` files (excluding `evidence/verdict.json`). Output is a JSON verdict with `classification.malicious`, `attribution.verdict`, etc.

### New contract
The agent now reads `task_spec.yaml` (for `primary_questions`) and `facts/*.md` (raw evidence) to independently judge:
1. **Coverage**: For each primary_question, is there at least one PROVEN-FULL fact that answers it?
2. **Correctness**: Do the facts contain unresolved contradictions (same question answered differently by two PROVEN facts)?
3. **Gaps**: Which primary_questions lack any answering fact, or only have PARTIAL answers?

The BLIND invariant is preserved: the agent MUST NOT read `evidence/verdict.json` (verdict-scorer's output). The orchestrator compares verdict-redteam's output against verdict-scorer's afterward.

### Output schema change
Old: `{ classification: { malicious, severity, total, dimensions }, attribution: { verdict, actor, confidence, ... } }`
New: `{ coverage: { [q_id]: { status, answering_facts, gaps } }, contradictions: [...], overall: "PASS|FAIL" }`

### Key invariants preserved
- BLIND protocol (never reads verdict.json)
- Write disallowed (JSON message output only)
- CONFIRMED / REFUTED / DIFF semantics (mapped to per-question coverage status)
- Self-consistency via sequential-thinking

### Key invariants removed
- Admiralty+ACH+Diamond attribution methodology references
- maliciousness classification scoring
- S5 named-actor gate
- scope tiers (full / attribution_family_bool / attribution_family)
