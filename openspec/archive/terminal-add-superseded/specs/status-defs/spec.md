## ADDED Requirements

### Requirement: SUPERSEDED SHALL be a member of status_defs.TERMINAL
The `status_defs.TERMINAL` set is the single source of truth for "claim is closed, needs no more work". It MUST include `"SUPERSEDED"` so any consumer testing `status not in TERMINAL` treats a superseded claim as closed. SUPERSEDED is already a specced status (references/schema.md, guardrails C3) written to claim-register.yaml when a claim is closed by replacement; this requirement closes the code-spec gap.

#### Scenario: SUPERSEDED recognized as terminal
- **WHEN** `status_defs.TERMINAL` is inspected
- **THEN** `"SUPERSEDED"` MUST be a member of the set

### Requirement: priority.rank_claims SHALL exclude SUPERSEDED claims from dispatchable output
`priority._is_open` defines open as `status not in TERMINAL and status not in IN_PROGRESS_STATUSES`. Because SUPERSEDED is terminal after REQ-001, `rank_claims` MUST NOT include any SUPERSEDED claim in its dispatchable list — an orchestrator dispatching the top claim must never be sent a claim that was closed by supersession.

#### Scenario: a register whose only claim is SUPERSEDED yields zero dispatchable
- **GIVEN** a claim-register with exactly one claim whose `status` is `SUPERSEDED`
- **WHEN** `priority.rank_claims` runs against that register
- **THEN** the dispatchable list MUST be empty (`n_dispatchable == 0`)

### Requirement: convergence_check SHALL exclude SUPERSEDED claims from the open count
`convergence_check._open_claims` uses the same `status not in TERMINAL` test. A superseded claim MUST NOT appear in `open_claims`, so the DISPATCH decision reflects only genuinely unfinished work and the loop can reach CONVERGED once every remaining claim is terminal.

#### Scenario: a register whose only claim is SUPERSEDED is CONVERGED
- **GIVEN** a claim-register with exactly one claim whose `status` is `SUPERSEDED`, no partial facts, no active workers
- **WHEN** `convergence_check` evaluates that register
- **THEN** `open_count` MUST be 0 and the decision MUST be CONVERGED (exit 0)
