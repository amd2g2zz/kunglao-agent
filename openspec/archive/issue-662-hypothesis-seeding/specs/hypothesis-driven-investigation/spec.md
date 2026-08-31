## ADDED Requirements

### Requirement: OPEN_HYPOTHESIS_AT_CLOSE annotates PROVEN-fact contradictions

When the DRAIN stage reaches `OPEN_HYPOTHESIS_AT_CLOSE` and one or more hypotheses have `status: open`, the action builder SHALL, per open hypothesis, detect whether a PROVEN fact contradicts it and annotate the BLOCKED message accordingly.

#### Scenario: explicit PROVEN fact reference in hypothesis body
- **GIVEN** `hypotheses/H-001.md` body contains `F003` and `facts/_INDEX.md` has `F003 | PROVEN | C-003 | uses AES-GCM not RC4`
- **WHEN** DRAIN reaches `OPEN_HYPOTHESIS_AT_CLOSE`
- **THEN** the BLOCKED message includes `Contradicted: H-001 by F003 (conclusion: uses AES-GCM not RC4)`

#### Scenario: candidate negated by PROVEN fact conclusion
- **GIVEN** `H-001.md` has `candidates: [AES, RC4]` and `facts/_INDEX.md` has `F005 | PROVEN | C-005 | payload uses RC4 cipher, not AES`
- **WHEN** DRAIN reaches `OPEN_HYPOTHESIS_AT_CLOSE`
- **THEN** the BLOCKED message includes `Contradicted: H-001 by F005 (conclusion: payload uses RC4 cipher, not AES)`

#### Scenario: open hypothesis with no contradiction
- **GIVEN** `H-001.md` is open with no PROVEN fact references and `candidates: []`
- **WHEN** DRAIN reaches `OPEN_HYPOTHESIS_AT_CLOSE`
- **THEN** the BLOCKED message is the generic form: `Cannot CONVERGE: 1 open hypothesis(ies) H-001 — adjudicate before delivery.`

#### Scenario: hypothesis layer unreadable
- **WHEN** `hypotheses/` is absent or `HypothesisStore` raises
- **THEN** the gate does not fire (fail-open; existing behavior)

#### Scenario: PROVEN facts unreadable
- **GIVEN** `hypotheses/H-001.md` is open and `facts/_INDEX.md` is absent
- **WHEN** contradiction scan runs
- **THEN** no annotation is produced; generic BLOCKED message fires (fail-open per design D7)

### Requirement: Backward compatibility — no anchor regression

The frozen regression anchor `tests/decide_anchor_619ebd3.json` MUST remain byte-for-byte identical after this change. All anchor fixtures have `open_hypotheses: []`; `_act_open_hypothesis` is not invoked in any anchor test case. This requirement is verified by the existing `test_decide_regression_anchor.py` suite without modification.
