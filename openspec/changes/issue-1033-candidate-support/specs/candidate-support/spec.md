## ADDED Requirements

### Requirement: Preserve currently supported methods

The system SHALL compute current candidate support from positive intake entries and verifiable present evidence, filtered by current registry and workspace authorization, with actual tool availability enforced at the dispatch boundary, independently of historical declaration frequencies. With intake or discovery evidence present, history SHALL only reweight candidates already in that support set. When both sources are absent, the existing history/case/store fallback SHALL remain available subject to current vocabulary and authorization checks; present invalid or withdrawn evidence SHALL NOT activate that fallback.

#### Scenario: Pending first dispatch

- **GIVEN** intake supports registered, currently available methods A and B
- **WHEN** an A dispatch is pending and new evidence motivates B
- **THEN** B remains in current support and can pass the dispatch gate with a recorded reason.

#### Scenario: Settled history and stage change

- **GIVEN** an A dispatch has settled and current evidence changes with the task stage
- **WHEN** current support is reconstructed
- **THEN** history cannot delete a supported B or reinstate a revoked or unavailable candidate.

#### Scenario: New and invalid candidates

- **GIVEN** a new candidate has current verifiable evidence and a valid registry or workspace admission receipt
- **WHEN** support is reconstructed
- **THEN** that candidate is considered, while malformed tokens, missing or revoked receipts, and unavailable candidates receive no support.

#### Scenario: Empty support

- **GIVEN** no intake or currently verifiable candidate exists
- **WHEN** a sample is requested
- **THEN** the system records a gap without assigning mass to the registry.

### Requirement: Dispatch attribution is truthful

The dispatch record SHALL identify the sampled family, actual method family, override reason, candidate set and per-candidate source. It SHALL distinguish conditional sampler weights from behavior propensity and leave unknown behavior probabilities unknown.

#### Scenario: Reasoned override

- **GIVEN** B has current support and the sampler chooses A
- **WHEN** a dispatch declares B with an explicit reason
- **THEN** the worker receives B and the record distinguishes B, A, the reason, support provenance and unknown behavior probability.

#### Scenario: Silent or unsupported override

- **GIVEN** the sampler chooses A
- **WHEN** the dispatch declares a different unsupported family or omits the override reason
- **THEN** the gate rejects the deviation.

#### Scenario: Other escape

- **GIVEN** a valid `other(...)` declaration
- **WHEN** it is dispatched
- **THEN** existing vocabulary validation and quarantine rules apply without inventing candidate mass.

#### Scenario: Deterministic replay

- **GIVEN** identical workspace state and sampler seed
- **WHEN** sampling and reconciliation are repeated
- **THEN** the sampled family, support set and provenance are identical.

#### Scenario: Existing proposal compatibility

- **GIVEN** intake and discovery sources have never been recorded
- **WHEN** valid history, case learning or cross-task-store proposals exist
- **THEN** the existing fallback remains available after current vocabulary and authorization checks.

#### Scenario: Probability boundary

- **GIVEN** the uniform scheduler directly executes its sampled action
- **WHEN** its receipt is recorded
- **THEN** exact 1/K remains known, while an externally declared or overridden action has unknown behavior probability; the learned MC estimator is deferred to #1034.

#### Scenario: Source deletion after intake

- **GIVEN** the intake writer has successfully published a supported source
- **WHEN** that source is deleted after a historical dispatch
- **THEN** the persistent support mode prevents legacy history from restoring its candidate and the dispatch gate rejects it without another current source.

#### Scenario: Small positive support

- **GIVEN** a valid intake candidate has a positive weight below six-decimal display precision
- **WHEN** reconciliation evaluates a reasoned pivot
- **THEN** positive support and its unrounded conditional ratio remain available to the gate.

#### Scenario: Expansion artifact withdrawal

- **GIVEN** an expansion receipt explicitly references an artifact
- **WHEN** that artifact is removed or becomes unreadable
- **THEN** that receipt no longer contributes support, while an independent valid intake or expansion source may retain the same candidate.

#### Scenario: Support marker failure

- **GIVEN** the support-mode marker cannot be persisted
- **WHEN** intake or expansion attempts to publish a source
- **THEN** publication fails visibly before a new source is written.
