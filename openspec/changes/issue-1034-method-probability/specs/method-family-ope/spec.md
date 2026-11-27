## ADDED Requirements

### Requirement: Method-family probabilities are bound to executions

The evaluator SHALL join the actual execution, family, candidate support and probability information set to the independent design before admitting a transition to a method-family comparison. Missing or mismatched provenance SHALL be counted and excluded.

#### Scenario: Equal recipe and method probabilities
- **WHEN** a production transition corroborated by a recipe carries the same number as a method receipt
- **THEN** the evaluator records the unavailable method probability and does not weight that transition.

#### Scenario: A claim is reused
- **WHEN** two audited executions share a claim and have separate dispatch IDs
- **THEN** each controlled transition can join only to its own dispatch, and a missing dispatch ID cannot be inferred from the claim.

#### Scenario: Unknown choice mechanism
- **WHEN** an external declaration, override, historical scalar, or mismatched information set lacks a matching method probability
- **THEN** the comparison excludes it and an incomplete preregistered population produces no ranking.

#### Scenario: Actual family selection law
- **WHEN** calibrated over fixed fresh seeds with asymmetric priors, observed history, changed support or posterior modifiers
- **THEN** the observed selection frequency agrees with the average conditional probability within the preregistered sampling tolerance.
