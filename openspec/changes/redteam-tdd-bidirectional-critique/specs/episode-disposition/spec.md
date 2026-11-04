# Spec Delta

## Purpose

Defines the single evidence-backed disposition every rollout ends in, and how reward, measurement, learning, and settlement consume it — replacing three unconnected taxonomies and making refusal, exhaustion, and censoring distinguishable.

## ADDED Requirements

### Requirement: Every episode ends in exactly one disposition
Each rollout MUST end in exactly one disposition from the closed set `SOLVED`, `OUT_OF_SCOPE`, `CENSORED_ENV`, `ATTEMPTED_EXHAUSTED`, `INFRA`, `FAILED`, `SURRENDER`. Reward, measurement, learning, and settlement MUST read that object. The legacy session ladder is mapped through the published legacy→disposition table; act-level outcomes remain per-act and aggregate into the episode disposition, never the reverse.

#### Scenario: One disposition per episode
- **WHEN** a rollout terminates
- **THEN** exactly one disposition row exists and every consumer reads it

#### Scenario: Act outcomes aggregate
- **WHEN** a consumer needs an act-level class
- **THEN** it reads the per-act record, which aggregates into the episode disposition

### Requirement: Dispositions follow a total precedence
Dispositions MUST be assigned by this total order, first match wins: `SOLVED` > `OUT_OF_SCOPE` > `CENSORED_ENV` > `ATTEMPTED_EXHAUSTED` > `INFRA` > `FAILED` > `SURRENDER`. A later disposition MUST NOT override an earlier one.

#### Scenario: Solved without an action record
- **WHEN** an episode has an oracle or verifier pass and no recorded strategic action
- **THEN** the disposition is `SOLVED`, not `SURRENDER`

#### Scenario: Out-of-scope refusal without an action record
- **WHEN** an authorized-scope check excludes the target and no strategic action is recorded
- **THEN** the disposition is `OUT_OF_SCOPE`, not `SURRENDER`

### Requirement: Each disposition has an evidence gate
`SOLVED` requires an oracle or verifier pass; `OUT_OF_SCOPE` an authorization scope that excludes the target; `CENSORED_ENV` a session-bound and corroborated environment wall; `ATTEMPTED_EXHAUSTED` a route-attempt ledger covering the declared routes under the fixed budget; `INFRA` an environment refusal of the act (`BLOCKED`); `FAILED` an execution failure (crash, timeout kill, liveness loss, nonzero exit) or an unverified completion claim; `SURRENDER` an in-scope authorized episode that ends unfinished, not solved, not exhausted, and not wall-censored. A disposition whose gate is unmet MUST fall to the next disposition in the precedence order, and the fall MUST be recorded.

#### Scenario: Missing evidence
- **WHEN** the claimed disposition's evidence gate is not satisfied
- **THEN** the episode falls to the next disposition in the precedence order and the fall is recorded

#### Scenario: Crash is not surrender
- **WHEN** an authorized episode ends from a crash, timeout kill, liveness loss, or nonzero exit with no wall and no complete ledger
- **THEN** the disposition is `FAILED`, not `SURRENDER`

### Requirement: Strategic action is recorded before termination
An in-scope authorized episode that ends unfinished without a recorded `FIGHT`, `BYPASS`, or `INVEST` action (and is not `SOLVED`, and no earlier disposition's gate in the total order is met) MUST be classified `SURRENDER`; a recorded action carries its propensity on the disposition object.

#### Scenario: No recorded strategic action
- **WHEN** an in-scope authorized episode ends unfinished without a recorded strategic action and without a solve
- **THEN** the disposition is `SURRENDER`

#### Scenario: Recorded strategic action
- **WHEN** the episode records `FIGHT`, `BYPASS`, or `INVEST` with a propensity
- **THEN** the action and its propensity ride the disposition object

### Requirement: Stopping is externally checkable
Only the route-attempt ledger's exhaustion, a corroborated environment wall, or the declared budget MAY terminate a rollout. Surrogate early-stop signals MUST NOT terminate.

#### Scenario: Early-stop signal alone
- **WHEN** only an early failure signal suggests stopping while declared routes remain
- **THEN** the rollout MUST NOT terminate on that signal

#### Scenario: Ledger or budget exhaustion
- **WHEN** the ledger covers the declared routes or the budget is exhausted
- **THEN** termination is legitimate and the disposition is evidence-backed

### Requirement: Dispositions drive reward, measurement, and learning
The reward, measurement, and learning faces MUST treat each disposition as follows: `SOLVED` earns positive credit; `ATTEMPTED_EXHAUSTED` yields a capability-gap record and no strategy credit; `SURRENDER` stays in the capability denominator and is a failure outcome for strategic-action learning (its credit stays within the declared [0,1] rails, 0.0 without reproducible evidence); `CENSORED_ENV` is explicit censoring (excluded from strategy learning, reported as a censoring rate); `OUT_OF_SCOPE` and `INFRA` are reported separately with no strategy signal; `FAILED` is an execution failure reported separately with no strategic-choice signal.

#### Scenario: Exhausted
- **WHEN** the disposition is `ATTEMPTED_EXHAUSTED`
- **THEN** a capability-gap row is recorded and no learning verdict is produced

#### Scenario: Censored
- **WHEN** the disposition is `CENSORED_ENV`
- **THEN** the episode enters no strategy learning and the censoring rate is reported

#### Scenario: Surrender
- **WHEN** the disposition is `SURRENDER`
- **THEN** the episode counts in the capability denominator and enters strategic-action learning as a failure outcome within the [0,1] credit rails

### Requirement: Censoring cannot absorb a refusal or an abandonment
`CENSORED_ENV` MUST require session-bound and corroborated environment-wall evidence. A refusal or abandonment without that evidence MUST NOT be recorded as censored.

#### Scenario: Refusal without a wall
- **WHEN** an authorized-target episode refuses or abandons without wall evidence
- **THEN** the disposition is `SURRENDER`, never `CENSORED_ENV`

### Requirement: Authorization decides surrender versus out-of-scope
The dispatch MUST carry the authorization context declared in `task_spec`; a refusal on an authorized target is `SURRENDER`, while a refusal on an out-of-scope target is `OUT_OF_SCOPE`.

#### Scenario: Authorized refusal
- **WHEN** the authorization context covers the target and the agent refuses
- **THEN** the disposition is `SURRENDER`

#### Scenario: Out-of-scope refusal
- **WHEN** the target is outside the declared authorization
- **THEN** the disposition is `OUT_OF_SCOPE`

### Requirement: Every disposition is observable
Every disposition MUST emit a registered telemetry event carrying the episode id, claim, disposition, and the evidence references.

#### Scenario: Disposition event
- **WHEN** a disposition is recorded
- **THEN** a registered event row carries the disposition and its evidence references
