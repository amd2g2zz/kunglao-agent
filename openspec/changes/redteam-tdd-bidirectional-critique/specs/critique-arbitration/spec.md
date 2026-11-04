# Spec Delta

## Purpose

Defines the limited critic lane and its two-stage arbitration, ensuring that only evidence-backed, oracle-validated and orchestrator-accepted critiques can affect behavior or settlement.

## ADDED Requirements

### Requirement: Critique lane is limited to material kinds
The critic face MAY comment only on `method-detour`, `roi`, `drift`, and `stagnation`. It MUST stay silent by default and MUST NOT report cosmetic, speculative, or non-material issues.

#### Scenario: Cosmetic observation
- **WHEN** the observation is cosmetic or does not indicate a material method or ROI problem
- **THEN** no critique is emitted

#### Scenario: Material drift
- **WHEN** evidence shows obvious drift or stagnation (repeated same-class failure or zero progress over the observation window)
- **THEN** a critique of kind `drift` or `stagnation` may be emitted

### Requirement: Every critique carries evidence and impact
A critique MUST carry a falsifier or evidence and MUST state its expected impact. A critique without this bar MUST be suppressed to telemetry (`critique_suppressed`) and MUST NOT surface as a finding.

#### Scenario: Critique without evidence
- **WHEN** a critique has no falsifier or evidence
- **THEN** it is suppressed to telemetry and cannot trigger any adjustment

#### Scenario: Evidence-backed critique
- **WHEN** a critique names its evidence and expected impact
- **THEN** it proceeds to arbitration

### Requirement: Two-stage arbitration gates every critique
The oracle MUST deterministically validate the critique's evidence and threshold. The orchestrator MUST then adjudicate accept or reject and MUST record the decision. Only accepted critiques MAY trigger an adjustment.

#### Scenario: Oracle rejects the critique
- **WHEN** the oracle finds the evidence missing or the threshold unmet
- **THEN** the critique is rejected and no adjustment occurs

#### Scenario: Orchestrator rejects the critique
- **WHEN** the oracle validates the evidence but the orchestrator adjudicates reject
- **THEN** the rejection is recorded and no adjustment occurs

#### Scenario: Accepted critique
- **WHEN** the oracle validates the evidence and the orchestrator records accept
- **THEN** the critique may adjust method selection or planning

### Requirement: Unarbitrated critiques are inert in settlement
Settlement MUST ignore critiques that lack an arbitration decision or whose decision is reject. Only an accepted critique MAY enter settlement, and the settlement row MUST carry its arbitration reference.

#### Scenario: Unarbitrated critique reaches settlement
- **WHEN** a settlement pass encounters a critique with no arbitration decision
- **THEN** the critique contributes nothing to credit or demotion

#### Scenario: Accepted critique in settlement
- **WHEN** the settlement pass encounters an accepted critique referencing its arbitration row
- **THEN** the critique's effect is applied and traceable to that decision

### Requirement: Arbitration criteria and effects are deterministic and bounded
The oracle MUST apply the per-kind policy-constant criteria (drift repeat count, stagnation window, ROI cost ratio, detour step ratio), and an accepted critique MUST apply only the bounded sampler-weight demotion, never a free-form credit change.

#### Scenario: ROI critique without a named cheaper path
- **WHEN** an ROI critique does not name a cheaper registered path with the same outcome class
- **THEN** the oracle rejects it

#### Scenario: ROI cost ratio below the threshold
- **WHEN** the measured cost ratio is below the policy constant
- **THEN** the oracle rejects the ROI critique

#### Scenario: Accepted critique effect is bounded
- **WHEN** a critique is accepted
- **THEN** the only effect is the bounded sampler-weight demotion recorded with its arbitration id
