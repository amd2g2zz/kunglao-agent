# distill-spine

## ADDED Requirements

### Requirement: four-product-schemas
The spine SHALL validate playbook/1 and decision-entry/1 documents (usage cards ride harvest manifests; lessons stay in rollup), rejecting malformed products at the T-pass inlet.

#### Scenario: malformed playbook rejected
- **WHEN** a playbook missing steps[].tool_ref enters the T-pass
- **THEN** it is rejected with a named violation and never lands

### Requirement: fixed-order-tpass
The T-pass SHALL run de_case -> promote_form -> tag -> verify -> dedup in fixed order; a product skipping a stage is a contract violation.

#### Scenario: unverified product never lands
- **WHEN** verify fails for a playbook (fixture replay misses milestones)
- **THEN** the product is archived (not landed) with the failure evidence

### Requirement: source-trust-gate
A source whose falsified products accumulate (default >=2) SHALL be batch-demoted (its landed products' trust drops) and blacklisted from future mining; rejection of WRONG sources is wholesale, dissimilar-but-sound sources are never rejected for dissimilarity.

#### Scenario: falsification batch-demotes
- **WHEN** a second product from source S is falsified
- **THEN** all landed products with source S carry demoted trust and S is blacklisted

### Requirement: adaptive-retention
Retention detail SHALL be a function of the four signals (corroboration, source trust, verification strength, reconstruction telemetry) — first-of-kind products retain rich detail; multi-corroborated compress to skeleton.

#### Scenario: corroboration compresses
- **WHEN** a second corroborating source merges into an existing product
- **THEN** its retention may drop to skeleton and the merge is recorded
