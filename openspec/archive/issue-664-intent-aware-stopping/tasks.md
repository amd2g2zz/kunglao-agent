## 1. Setup

- [x] 1.1 Worktree `D:/kunglao-issue-664-intent-aware-stopping` branch `issue-664-intent-aware-stopping` off origin/dev (`347235b`)
- [x] 1.2 Baseline: 55/55 green inherited (#662 + #663 suites)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md
- [x] 2.2 design.md (D1-D8)
- [x] 2.3 specs/intent-aware-completion/spec.md
- [x] 2.4 tasks.md
- [ ] 2.5 `openspec validate issue-664-intent-aware-stopping` PASS

## 3. RED tests (`tests/test_intent_aware_completion.py`)

- [ ] 3.1 RED1: anchor in task_text absent from PQ text, items closed → (4, INTENT_UNMATCHED), anchors named
- [ ] 3.2 RED2: anchors covered by PQ text → PASS unchanged
- [ ] 3.3 RED3: no workspace_path → skipped, PASS
- [ ] 3.4 RED4: no task_spec / malformed → skipped, no crash
- [ ] 3.5 RED5: precedence — unresolved items + unmatched anchor → exit 1
- [ ] 3.6 RED6: CLI JSON verdict label INTENT_UNMATCHED

## 4. Implementation (`scripts/completion_gate.py`)

- [ ] 4.1 `_intent_unmatched(oracle) -> list[str]` helper per design D2-D4 (fail-open skips)
- [ ] 4.2 judge(): insert exit-4 check after exit-1, before exit-0 (precedence 3>2>1>4>0)
- [ ] 4.3 CLI verdict map: `4: "INTENT_UNMATCHED"`
- [ ] 4.4 module + shim docstring exit-code tables gain the 4 row

## 5. Docs + fold-in

- [ ] 5.1 CHANGELOG.md v0.1.3 Round 3 append
- [ ] 5.2 openspec archive fold-in: `issue-662-hypothesis-seed` → `openspec/archive/`
- [ ] 5.3 `openspec validate` re-run PASS
- [ ] 5.4 pytest: new GREEN; #662+#663 suites + completion-gate suite regression-free

## 6. PR + merge

- [ ] 6.1 mint + commit (ruff + review_gate)
- [ ] 6.2 push via Git Data API + PR (Closes #664)
- [ ] 6.3 squash-merge + delete branch
