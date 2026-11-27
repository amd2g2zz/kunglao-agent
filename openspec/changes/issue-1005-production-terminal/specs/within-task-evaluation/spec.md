## ADDED Requirements

### Requirement: Reproducible paired mock evaluation

The development-only evaluator SHALL compare supported strategies on paired synthetic environments and disclose unconnected production paths and unsupported ablations.

#### Scenario: Deterministic replay

- **WHEN** the evaluator runs the same seed and configuration into separate empty directories
- **THEN** it emits reproducible traces and metrics including failures and unfinished work

#### Scenario: Declared strategy metadata

- **WHEN** S5 metadata is added to otherwise identical inputs while the proposed view-only decision is pending
- **THEN** posterior inputs do not change and historical frequency is not presented as behavior probability
