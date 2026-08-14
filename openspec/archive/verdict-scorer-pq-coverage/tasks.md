## 1. Test First (RED)

- [ ] 1.1 Create `tests/test_verdict_scorer_contract.py` with assertions: (a) new JSON schema keys present in spec, (b) banned terms absent, (c) frontmatter tools unchanged
- [ ] 1.2 Verify new test FAILS against current `agents/verdict-scorer.md` (banned terms will be found, new schema keys will be missing)

## 2. Rewrite Agent Spec

- [ ] 2.1 Rewrite `agents/verdict-scorer.md` frontmatter description to describe PQ-coverage verifier role (keep name, allowedTools, disallowedTools, isolation unchanged)
- [ ] 2.2 Write new spec body: inputs (task_spec.yaml, claim-register.yaml, facts/*.md, fact_contradiction_gate.py output), PQ-coverage logic, C0a/C0b confidence enforcement, contradiction consumption, output schema v11, self-audit, degraded[], anti-patterns, provenance
- [ ] 2.3 Delete all maliciousness scoring content (6 dims, classification, severity, harness-confound table, precomputed inputs)
- [ ] 2.4 Delete all attribution content (Admiralty, ACH, Diamond, S5 gate, named-actor, attribution_evidence, leads)

## 3. Validate (GREEN)

- [ ] 3.1 Verify `test_verdict_scorer_contract.py` PASSES against rewritten spec
- [ ] 3.2 Verify full test suite: `python -m pytest -q` -- no new failures beyond known 2 (test_acceptance_overall_passes, test_skill_lte_500_lines)
- [ ] 3.3 Verify banned-term grep: `grep -ic "maliciousness\|attribution\|admiralty\|diamond\|\bach\b\|classification\|named_actor" agents/verdict-scorer.md` returns 0
- [ ] 3.4 Verify no "threat actor"/"APT" residue in verdict-scorer.md

## 4. OpenSpec Validation

- [ ] 4.1 Run `openspec validate verdict-scorer-pq-coverage` -- RC=0

## 5. Stage Changes

- [ ] 5.1 `git add` all changed files (agents/verdict-scorer.md, tests/test_verdict_scorer_contract.py, openspec/changes/verdict-scorer-pq-coverage/*)
- [ ] 5.2 Verify `git diff --cached --stat` shows expected files
