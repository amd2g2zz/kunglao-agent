## 1. Setup

- [x] 1.1 Worktree `D:/kunglao-issue-662-hypothesis-seeding` branch `issue-662-hypothesis-seeding` off origin/dev (`a0cb8bd`)
- [x] 1.2 Baseline: run existing test suites (red accounts green)

## 2. OpenSpec artifacts (SDD)

- [x] 2.1 proposal.md (gap audit table + gap-closure nature)
- [x] 2.2 design.md (D1-D8)
- [x] 2.3 specs/hypothesis-driven-investigation/spec.md
- [ ] 2.4 tasks.md (this file)

## 3. RED tests (`tests/test_hypothesis_contradiction_gate.py`)

- [ ] 3.1 RED10: explicit PROVEN fact reference in hypothesis body → annotated BLOCKED message
- [ ] 3.2 RED11: candidate negated by PROVEN fact conclusion → annotated BLOCKED message
- [ ] 3.3 RED12: open hypothesis no contradiction → generic BLOCKED message (no annotation)
- [ ] 3.4 RED13: hypothesis body mentions PROVEN fact but fact not PROVEN → no annotation (fail-open)
- [ ] 3.5 RED14: empty PROVEN fact index → no annotation (fail-open)

## 4. Implementation (`scripts/convergence_check.py`)

- [ ] 4.1 `_scan_proven_facts(workspace) -> dict[str, str]` — lightweight _INDEX line scan, same pattern as `_partial_facts`, fail-open, returns `{fact_id: conclusion}`.
- [ ] 4.2 `_detect_contradiction(hyp: Hypothesis, proven: dict) -> str | None` — Path A (explicit fact ID in body) + Path B (candidate negation heuristic); returns annotation snippet or None.
- [ ] 4.3 `_act_open_hypothesis` upgrade — call `_scan_proven_facts`, iterate open hyps, call `_detect_contradiction`, format annotated message.

## 5. Anchor safety verification

- [ ] 5.1 Confirm all `decide_anchor_619ebd3.json` fixtures have `open_hypotheses: []` (code grep)
- [ ] 5.2 Run `pytest tests/test_decide_regression_anchor.py` — must stay green without re-pin

## 6. Quality gates

- [ ] 6.1 `pytest tests/test_hypothesis_contradiction_gate.py -v` — 5 tests GREEN
- [ ] 6.2 `pytest tests/test_hypothesis_seeder.py tests/test_digest_sec_g_528.py tests/test_decide_regression_anchor.py -v` — all GREEN
- [ ] 6.3 ruff check scripts/convergence_check.py — no new violations

## 7. Handoff

- [ ] 7.1 Commit with structured message: `feat(#662): annotate PROVEN-fact contradictions in OPEN_HYPOTHESIS_AT_CLOSE message`
- [ ] 7.2 Report staged sha + commit chain to orchestrator for Data API push + PR creation
