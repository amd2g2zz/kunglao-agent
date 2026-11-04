# Spec Delta

## Purpose

Defines how a rollout's refusal, surrender, and evidence-backed exhaustion are classified, recorded, and kept visible to reward and measurement, so an abandoned task is never mistaken for a censored environment or a learning result.

## ADDED Requirements

### Requirement: Surrender is a distinct outcome
An abandoned or refused rollout on an authorized target that lacks evidence of an environment wall MUST be recorded as `surrender`, not as `censored_env` or `infra`.

#### Scenario: Refusal without a wall
- **WHEN** a rollout on an authorized target stops or refuses without a session-bound environment-wall record
- **THEN** the outcome is `surrender`, not `censored_env`

#### Scenario: Evidence-backed wall
- **WHEN** a session-bound blocker records an environment wall (for example a captcha verify-wall)
- **THEN** the outcome may be `censored_env` and the sample is excluded from strategy learning

### Requirement: Out-of-scope refusals are a legitimate class
A refusal on a target outside the authorized engagement scope MUST be recorded as `refusal_out_of_scope`, distinct from surrender, and MUST NOT be counted as a capability failure.

#### Scenario: Out-of-scope target
- **WHEN** the target is outside the authorized engagement scope and the agent refuses
- **THEN** the outcome is `refusal_out_of_scope`, not `surrender`

### Requirement: Authorization context rides the dispatch
Every dispatch on an authorized target MUST carry the engagement/authorization context. A policy refusal on such a task MUST be classified as surrender, never as a legitimate terminal state.

#### Scenario: Authorized task refused
- **WHEN** the dispatch carries authorization context and the agent refuses on policy grounds
- **THEN** the outcome is `surrender`, not a terminal state

### Requirement: Route exhaustion is evidenced
A negative or impossible claim MUST carry a route-attempt ledger naming the declared routes for the claim kind, each attempt's command or artifact, the fixed budget, and reproducibility. Without the ledger the claim MUST be `UNVERIFIED-WITH-GAP` and MUST NOT count as exhaustion.

#### Scenario: Negative claim without a ledger
- **WHEN** a negative or impossible claim carries no route-attempt ledger
- **THEN** the claim is `UNVERIFIED-WITH-GAP` and no capability gap is recorded

#### Scenario: Evidenced exhaustion
- **WHEN** the ledger covers the declared routes under the fixed budget
- **THEN** the result is a capability-gap record that feeds the method library, never a learning verdict on its own

### Requirement: Surrender and refusal are observable
Every refusal or surrender MUST emit a registered rollout event so settlement and measurement can see it.

#### Scenario: Refusal event
- **WHEN** a rollout refuses or surrenders
- **THEN** a registered telemetry row records the outcome, the claim, and the route-attempt count
