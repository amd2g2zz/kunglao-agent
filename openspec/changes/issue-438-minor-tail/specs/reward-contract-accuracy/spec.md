# issue-438-minor-tail — spec delta: reward-contract-accuracy

## ADDED Requirements

### Requirement: Citation-face decode tolerance

The claim-provenance citation read face SHALL degrade to no
claim-provenance citations (the empty set) when the claim register is
missing, unparseable, OR undecodable (invalid UTF-8); it SHALL never
raise past the read. Decode failures are data problems, not
face-killers: the round-credit settlement read that consumes the face
SHALL complete.

#### Scenario: invalid-UTF-8 register

- **WHEN** claim-register.yaml contains bytes that are not valid UTF-8
- **THEN** question_claims returns the empty set and fact_artifacts
  completes, marking answers_question false for every fact

#### Scenario: tolerance matches the sibling idiom

- **WHEN** the register is missing or unparseable YAML
- **THEN** the same empty-set degradation applies — the pre-existing
  behavior is unchanged, with no new warn surface

### Requirement: No stage_milestone declaration in the reward legs

The reward rules table's round_credit.value_ladder.legs SHALL NOT
declare a stage_milestone leg: the leg had no settlement enforcement
face, and milestone artifacts earn full credit through the
cited/used-toward-stage leg (a milestone is stage use by
construction); an unlinked milestone settles as the
exploration-option trace, and the rules note SHALL disclose that
under-credit-only assumption. The in-code ladder description SHALL
match: no enumerated stage-milestone arm presented as a declared leg.
This requirement is scoped to the stage_milestone leg — a general
no-declaration-only-legs guarantee is not mechanically enforced.

#### Scenario: declaration removed, behavior unchanged

- **WHEN** the rules file is loaded
- **THEN** legs carries no stage_milestone key and no settlement value
  changes (no code face ever read the leg)

#### Scenario: milestone artifacts still earn full through citation

- **WHEN** a milestone artifact is linked to a question-bearing claim
- **THEN** it settles full credit via the used-toward-stage leg

### Requirement: README documents the enforced cap

The scalar_settlement.py catalog row in scripts/README.md SHALL
document the current round-credit behavior: the value-ladder
vocabulary (verified = admission ticket, cited-toward-stage = the
value condition) and the per-dispatch cited cap (the constant name,
the demotion reason, the deterministic selection).

#### Scenario: row names the cap

- **WHEN** the scalar_settlement.py README row is read
- **THEN** it names the admission-ticket / value-condition ladder, the
  cited cap, CITED_CAP_DEFAULT, and cited_over_cap
