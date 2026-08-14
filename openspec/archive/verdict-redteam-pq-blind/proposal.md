# verdict-redteam-pq-blind
## What
Rewrite `agents/verdict-redteam.md` to replace the old "maliciousness + attribution" blind-verify scope with "primary-question coverage + correctness" blind-verify scope. The verdict-redteam agent now independently judges whether each `task_spec.primary_questions` entry has a PROVEN-FULL fact answering it, and whether there are unresolved contradictions in the evidence -- instead of independently re-deriving threat classification and actor attribution (which is no longer kunglao-agent's scope).
## Why
kunglao-agent verifies RE analysis correctness/completeness against `task_spec.primary_questions` -- NOT threat classification or attribution. The old verdict-redteam independently re-derived maliciousness + attribution; that scope is being removed concurrently in #106. The new verdict-redteam must independently re-derive primary-question COVERAGE + CORRECTNESS, maintaining the maker-checker BLIND invariant (never reads verdict-scorer's conclusion).
## Scope
- `agents/verdict-redteam.md`: full rewrite (84 lines -> new contract)
  - Inputs: `task_spec.yaml` + `facts/*.md` raw evidence (NOT `evidence/verdict.json`)
  - Output: own verdict on PQ coverage + correctness per primary_question
  - BLIND framing sentence preserved with updated scope wording
  - CONFIRMED / REFUTED / DIFF semantics unchanged
- `tests/test_verdict_redteam_contract.py` (new): contract assertions
  - (a) agent markdown contains BLIND invariant ("WITHOUT reading" + "verdict.json")
  - (b) banned terms (maliciousness, attribution) are absent
- `scripts/verdict-compare.py`: NOT in scope (file does not exist)
## NOT in scope
- `agents/verdict-scorer.md` (concurrent issue #106)
- SKILL.md / DESIGN.md (separate issues)
## Acceptance
- `grep -ic "maliciousness\|attribution" agents/verdict-redteam.md` returns 0
- `test_verdict_redteam_contract.py` passes
- pytest full suite: no new failures (baseline 2 known failures)
- openspec validate verdict-redteam-pq-blind PASS
