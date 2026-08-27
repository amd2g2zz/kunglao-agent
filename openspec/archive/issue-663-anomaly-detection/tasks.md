## 1. Setup

- [ ] 1.1 Create branch `issue-663-anomaly-detection` off `dev` (one issue one PR one branch one worktree)
- [ ] 1.2 Confirm baseline test counts before changes (`scripts/` passed; `tests/` known failures recorded)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (why: v0.1.3 milestone review — human-anomaly gap)
- [x] 2.2 spec.md (REQ: anomaly score 0-1, DRAIN event, threshold, fail-open baseline, co-resident note, backward compat)
- [x] 2.3 design.md (D1-D10: max-of-three sub-scores, baseline sourcing, schema bump, state machine integration, fail-open semantics, CLI/perf/test strategy)
- [x] 2.4 tasks.md (this file)
- [ ] 2.5 `openspec validate issue-663-anomaly-detection` PASS

## 3. RED tests (write first, must fail)

- [ ] 3.1 RED1: `score_fact` on a fact with common API call + populated baseline → returns score in `[0.0, 0.3]`
- [ ] 3.2 RED2: `score_fact` on a fact with rare syscall + populated baseline → returns score in `[0.7, 1.0]`
- [ ] 3.3 RED3: `score_fact` with empty baseline corpus → returns `0.0`, no crash
- [ ] 3.4 RED4: `score_fact` with malformed fact body → returns `0.0` (fail-open per D5), no crash
- [ ] 3.5 RED5: `scan_anomalies` on a workspace with ≥ 1 high-score fact → returns ≥ 1 anomaly dict with `fact_id` + `score` + `top_dimension`
- [ ] 3.6 RED6: `scan_anomalies` on workspace with all low-score facts → returns `[]`, no `ANOMALY_DETECTED` event
- [ ] 3.7 RED7 (integration): `convergence_check.decide()` with anomalies present → DRAIN verdict is `BLOCKED` with reason naming the fact(s)
- [ ] 3.8 RED8 (integration): `claim_migrator` does NOT downgrade to STAMP on anomaly alone (co-resident note is the right intervention, per design D8)
- [ ] 3.9 RED9 (schema): `lint_fact` accepts `boundary_type: anomaly` without error and reports `active_schema_rev: 2`

## 4. Gate implementation (`scripts/anomaly_detector.py`)

- [ ] 4.1 `score_fact(fact_text, baseline_corpus) -> float` per design D1 (max-of-three sub-scores)
- [ ] 4.2 `_lexical_rarity_score(tokens, baseline) -> float` per D1.1
- [ ] 4.3 `_semantic_unusualness_score(claim_id, conclusion, baseline) -> float` per D1.2
- [ ] 4.4 `_path_unusualness_score(sample_refs, baseline) -> float` per D1.3
- [ ] 4.5 `_load_baseline(operator_path: Path | None = None) -> BaselineCorpus` — RE-library + operator-config + samples (D2)
- [ ] 4.6 `scan_anomalies(index_path, facts_dir, baseline=None, threshold=None) -> list[dict]` — fail-open per D5
- [ ] 4.7 `check_fact_anomaly(fact_id, facts_dir, baseline=None, threshold=None) -> (bool, str)` — single-fact consumer surface
- [ ] 4.8 `_write_anomaly_note(fact_path, score, top_dimension) -> Path` — co-resident note writer (per spec "co-resident note on threshold exceedance")
- [ ] 4.9 CLI: `python scripts/anomaly_detector.py <ws> [--json] [--threshold 0.7]` — exit 0/1/2 per design D6

## 5. State machine integration (`scripts/convergence_check.py`)

- [ ] 5.1 New `Event.ANOMALY_DETECTED` enum value
- [ ] 5.2 New `_act_anomaly(s) -> str` action builder (mirrors `_act_contradiction` shape)
- [ ] 5.3 New `_anomaly_detected(s) -> bool` predicate
- [ ] 5.4 `_DecideInputs` gains `anomalies: list | None` field + `anomaly_reason()` lazy accessor (cached)
- [ ] 5.5 `_scan_anomalies(workspace) -> list[dict]` helper — pure read, lazy + cached
- [ ] 5.6 `STAGE_PROBES[State.DRAIN]` insert `ANOMALY_DETECTED` between `GLOBAL_CONTRADICTION` and `DRAIN_CLEAN`
- [ ] 5.7 `TRANSITIONS[(State.DRAIN, Event.ANOMALY_DETECTED)] = (State.BLOCKED, _act_anomaly)`
- [ ] 5.8 `_human()` output lines for anomaly (mirrors contradiction formatting)

## 6. Schema bump (`scripts/lint_facts.py`)

- [ ] 6.1 `VALID_BOUNDARY_TYPE` add `"anomaly"`
- [ ] 6.2 `EMPTY_GATE_TYPES` add `"anomaly"` (mirrors `"contradiction"`)
- [ ] 6.3 `ACTIVE_SCHEMA_REV = 1` → `ACTIVE_SCHEMA_REV = 2`
- [ ] 6.4 Lint output reports `active_schema_rev: 2`

## 7. Baseline corpus docs (`references/anomaly-baseline.md`)

- [ ] 7.1 Document three baseline sources (RE-library refs / prior samples / operator-config)
- [ ] 7.2 Document `analysis_state.txt` `baseline_corpus:` config + `anomaly_threshold:` config
- [ ] 7.3 Document fail-open behavior (empty baseline → anomaly detection disabled, warn-only)
- [ ] 7.4 `references/_INDEX.yaml` add `anomaly-baseline.md` to references list

## 8. Hook selfcheck + acceptance

- [ ] 8.1 `python scripts/hooks_selfcheck.py` PASS — wiring unchanged (no new hooks added; existing hook chain still valid)
- [ ] 8.2 `python scripts/progress_report.py <ws>` output includes anomaly count
- [ ] 8.3 `python -m pytest scripts/` full pass (no new failures)
- [ ] 8.4 `python -m pytest tests/test_anomaly_detector.py` GREEN
- [ ] 8.5 `python -m pytest tests/` — new tests GREEN, prior 6 failures unchanged
- [ ] 8.6 `python -m pytest tests/test_acceptance.py` — end-to-end PASS (workspace with anomaly → BLOCKED with reason)
- [ ] 8.7 `python -m pytest tests/test_lint_facts.py` — `ACTIVE_SCHEMA_REV` bump reflected in schema-pin output
- [ ] 8.8 `openspec validate issue-663-anomaly-detection` PASS (re-run after code lands)

## 9. Docs + validation

- [ ] 9.1 `CHANGELOG.md` — anomaly detection noted under v0.1.4 (or current target)
- [ ] 9.2 `references/_INDEX.yaml` — anomaly-baseline.md indexed
- [ ] 9.3 `references/schema.md` — `boundary_type: anomaly` documented in frontmatter schema section
- [ ] 9.4 `references/state-mapping.md` — co-resident note pattern documented (no status change)

## 10. PR + merge + cleanup

- [ ] 10.1 Commit (SDD first, then impl+tests), push branch, open PR to `dev` (body: Closes #663)
- [ ] 10.2 Squash-merge to dev, close issue #663
- [ ] 10.3 Move `openspec/changes/issue-663-anomaly-detection/` → `openspec/archive/` (per project convention)
- [ ] 10.4 Remove worktree + delete branch
