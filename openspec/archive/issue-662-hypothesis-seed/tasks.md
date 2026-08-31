## 1. Setup

- [x] 1.1 Worktree `D:/kunglao-issue-662-hypothesis-seed` branch `issue-662-hypothesis-seed` off origin/dev (`63975fe`)
- [x] 1.2 Baseline: anomaly tests 13/13 green inherited from #663 merge

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md
- [x] 2.2 design.md (D1-D8)
- [x] 2.3 specs/hypothesis-driven-investigation/spec.md
- [x] 2.4 tasks.md
- [ ] 2.5 `openspec validate issue-662-hypothesis-seed` PASS

## 3. RED tests (`tests/test_hypothesis_seeder.py`)

- [ ] 3.1 RED1: seed creates one scaffold per PQ (marker/status/competitor_group/C-PENDING/candidates=[])
- [ ] 3.2 RED2: idempotent — second run no-op; marker survives HypothesisStore rewrite
- [ ] 3.3 RED3: no task_spec → [] no crash
- [ ] 3.4 RED4: malformed task_spec → [] no crash
- [ ] 3.5 RED5: build_digest seeds then sec_g lists the scaffold
- [ ] 3.6 RED6: convergence DRAIN → BLOCKED naming H-id with open hypothesis at close
- [ ] 3.7 RED7: hypothesis refuted/superseded → DRAIN clean
- [ ] 3.8 RED8: scaffold shape per D1/D3 (C-PENDING + empty candidates)

## 4. Implementation (`scripts/hypothesis_seeder.py`)

- [ ] 4.1 `seed_from_task_spec(ws) -> list[dict]` per design D1
- [ ] 4.2 idempotency check via body marker `pq:<qid>` (design D2)
- [ ] 4.3 next-free H-NNN allocation
- [ ] 4.4 scaffold write via `HypothesisStore` (construct Hypothesis + `_write`)
- [ ] 4.5 `kunglao_log` event per write (design D6)
- [ ] 4.6 CLI `<ws> [--json]`, exit 0/2

## 5. digest wiring (`scripts/digest_build.py`)

- [ ] 5.1 seeder call before `build_sec_g`, fail-open (design D4)

## 6. convergence DRAIN gate (`scripts/convergence_check.py`)

- [ ] 6.1 `Event.OPEN_HYPOTHESIS_AT_CLOSE` enum member
- [ ] 6.2 `_DecideInputs.open_hypotheses()` lazy+cached (HypothesisStore.list_open, fail-open on layer error)
- [ ] 6.3 predicate `_open_hypothesis_at_close`
- [ ] 6.4 action builder `_act_open_hypothesis` (BLOCKED, names H-ids + adjudication paths)
- [ ] 6.5 `_EVENT_PREDICATES` + `STAGE_PROBES[State.DRAIN]` insert between NOTE_LAYER_GAP and DISCOVERY_UNCONSUMED + `TRANSITIONS` row
- [ ] 6.6 decide() output: `open_hypotheses` + `open_hypothesis_count`

## 7. Docs + validation

- [ ] 7.1 CHANGELOG.md v0.1.3 Round 3 append
- [ ] 7.2 openspec archive fold-in: `openspec/changes/issue-663-anomaly-detection/` → `openspec/archive/` (post-#666-merge move, plan §10.3)
- [ ] 7.3 `openspec validate issue-662-hypothesis-seed` PASS (re-run)
- [ ] 7.4 pytest: new tests GREEN; anomaly + schema_rev suites still 13/13

## 8. PR + merge

- [ ] 8.1 mint review evidence + commit (quality gate ruff + review_gate)
- [ ] 8.2 push via Git Data API (smart-HTTP blocked in this env) + `gh pr create` base dev, body "Closes #662"
- [ ] 8.3 squash-merge + delete branch
