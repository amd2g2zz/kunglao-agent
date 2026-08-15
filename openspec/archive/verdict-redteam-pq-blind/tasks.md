## Tasks

- [x] 1. Read current `agents/verdict-redteam.md` and understand old contract
- [x] 2. Search for existing tests referencing verdict-redteam; none found
- [x] 3. Confirm `scripts/verdict-compare.py` does NOT exist (skip)
- [x] 4. Run baseline tests (2 known failures, 776 passed)
- [x] 5. Write `tests/test_verdict_redteam_contract.py` (RED)
  - Assert BLIND invariant present ("WITHOUT reading" + "verdict.json")
  - Assert banned terms absent (maliciousness, attribution)
  - Assert primary-questions coverage framing present
- [x] 6. Rewrite `agents/verdict-redteam.md` (GREEN)
  - Replace maliciousness+attribution with PQ coverage+correctness
  - Update frontmatter description
  - Update inputs, scope, output schema
  - Preserve BLIND protocol and maker-checker framing
  - Update provenance
- [x] 7. Verify: `grep -ic "maliciousness\|attribution" agents/verdict-redteam.md` = 0
- [x] 8. Run full test suite: no new failures
- [x] 9. `npx openspec validate verdict-redteam-pq-blind` = RC 0
- [x] 10. Stage changes; confirm no commit/push
