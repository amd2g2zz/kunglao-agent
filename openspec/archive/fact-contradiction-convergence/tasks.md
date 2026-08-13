## 1. Setup

- [x] 1.1 Create branch `fact-contradiction-convergence` off `dev` (one issue one PR one branch one worktree)
- [x] 1.2 Confirm baseline test counts before changes (scripts/ 144 passed; tests/ 6 pre-existing failures recorded)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: a2b5e25c problem 2, F035/F040 same-topic contradiction)
- [x] 2.2 spec.md (REQ: same-topic multi-PROVEN needs supersedes/CONFLICT; empty-state no-crash; claim_migrator downgrade; backstop)
- [x] 2.3 design.md (D1-D6: verdict-not-status, topic key, conclusion diff, link resolution, wire points, CLI)
- [x] 2.4 tasks.md
- [x] 2.5 `openspec validate fact-contradiction-convergence` PASS

## 3. RED tests (write first, must fail)

- [x] 3.1 RED1: two PROVEN facts, same topic (same claim_id / overlapping sample_refs), different conclusions, no supersedes → `check_proven_contradiction` returns not-allowed; `scan_conflicts` reports the pair
- [x] 3.2 RED2: same pair WITH `supersedes: F<other>` (and separately `superseded_by:`) → allowed
- [x] 3.3 RED3: two PROVEN facts, different claim_ids + disjoint sample_refs → allowed
- [x] 3.4 RED4: empty facts dir / missing _INDEX.md / empty index → scan_conflicts == [] and check allowed, no crash
- [x] 3.5 a2b5e25c backtest: F035/F040 fixture (same routing claim, different conclusions, PROVEN, no links) → CONFLICT; add `supersedes: F035` to F040 → passes
- [x] 3.6 edge: same topic + same conclusion (converged) → allowed; link via line-level `superseded_by:` key → resolved; `F-035` vs `F035` id forms normalized

## 4. Gate implementation (scripts/fact_contradiction_gate.py)

- [x] 4.1 `_topic_key(fact_row, fact_text)` — claim_id from index row; sample_refs/cites from fenced-yaml or line-level frontmatter
- [x] 4.2 `scan_conflicts(index_path, facts_dir) -> list[dict]` — group PROVEN rows by topic; pairs with differing conclusions + no supersedes link → conflict dicts {fact_a, fact_b, topic, conclusion_a, conclusion_b}
- [x] 4.3 `check_proven_contradiction(claim_id, facts_dir) -> (bool, str)` — locate fact via `blind_gate.find_fact_file`, scan, report conflicts naming the pair
- [x] 4.4 `_supersedes_links(fact_text) -> set[str]` — supersedes/superseded_by extraction, F-id normalization
- [x] 4.5 CLI: `python fact_contradiction_gate.py <ws>` prints conflicts, exit 0 clean / 1 conflict

## 5. Wire into claim_migrator (kunglao_record.py)

- [x] 5.1 PROVEN branch: after BLIND gate, run contradiction check; on conflict `effective_status = STAMP`, message gains `[CONFLICT GATE: <pair> (needs-resolution)]`
- [x] 5.2 RED1-3 + backtest GREEN via claim_migrator (integration tests pass)

## 6. Backstop (hooks/worker_budget.py)

- [x] 6.1 `compare_register_change_proven_gate`: for each newly-PROVEN claim, contradiction check joins `violations` (BLIND-style)
- [x] 6.2 Hook-side integration test GREEN (direct register write blocked on contradiction)

## 7. Docs + validation

- [x] 7.1 `references/schema.md`: `supersedes:`/`superseded_by:` convention line under facts/_INDEX.md section
- [x] 7.2 `python -m pytest scripts/` full pass (no new failures)
- [x] 7.3 `python -m pytest tests/` — new tests GREEN, 6 pre-existing failures unchanged
- [x] 7.4 `openspec validate fact-contradiction-convergence` PASS

## 8. PR + merge + cleanup

- [ ] 8.1 Commit (SDD first, then impl+tests), push branch, open PR to `dev` (body: Closes #47)
- [ ] 8.2 Squash-merge to dev, close issue #47
- [ ] 8.3 Remove worktree + delete branch; update master-plan.md delta
