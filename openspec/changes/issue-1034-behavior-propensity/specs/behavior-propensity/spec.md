## ADDED Requirements

### Requirement: Preserve estimator attribution

The SNIPS estimator SHALL associate each included importance weight with the reward from the same decision and SHALL refuse non-finite or invalid inputs.

#### Scenario: A preceding target weight is zero
- **WHEN** a decision with reward zero has zero target weight and the following decision with reward one has positive weight
- **THEN** the value is one and effective sample size is one, regardless of decision order

#### Scenario: Probability is unavailable or non-finite
- **WHEN** a decision has an unavailable, non-finite, zero or negative behavior propensity, or non-finite target weight or reward
- **THEN** it contributes no weight and cannot alter another decision's reward

### Requirement: Honest propensity provenance

OPE SHALL use only a propensity describing the actual executed action under the declared information set and candidate support.

#### Scenario: Probability cannot be reconstructed
- **WHEN** the sampler's randomization, support or executed action cannot establish the recorded behavior probability
- **THEN** the probability is unknown and the decision is excluded and counted

#### Scenario: Insufficient overlap
- **WHEN** eligible decisions lack adequate effective sample size or support overlap
- **THEN** the evaluator reports insufficient evidence without a ranking
