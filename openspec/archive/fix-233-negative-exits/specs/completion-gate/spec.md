# completion-gate delta — fix-233-negative-exits

## ADDED Requirements

### Requirement: Closure citation protocol (#233)

Every `closed_by` value on a task-oracle `open_items` entry MUST cite at least
one claim id matching the mechanical claim-id grammar; free-text closures
MUST be rejected with a named reason.

#### Scenario: prose closure rejected

- **WHEN** an oracle item carries `closed_by: "app only trusts system certs"`
- **THEN** the completion gate returns exit 1 naming the item with an
  INVALID_CLOSURE reason stating no claim id was cited

#### Scenario: valid citation passes

- **WHEN** an oracle item carries `closed_by: "C-2 REFUTED obstacle"` where
  C-2 is a terminal claim in the workspace claim-register.yaml
- **THEN** the completion gate resolves the item and may return exit 0

### Requirement: Terminality + scope standards for cited claims

The cited claim MUST be terminal (status_defs.TERMINAL); a closure citing an
obstacle claim (origin: failure-obstacle) MUST have that claim REFUTED
(path-scoped standard); a closure citing a DEFERRED claim MUST carry the
task-scoped DEFERRED standard markers (non-empty wake_condition and
infeasible_ladder). Unverifiable citations (no workspace_path, no
claim-register.yaml, unknown claim id) MUST be rejected — fail-closed.

#### Scenario: OPEN claim citation rejected

- **WHEN** `closed_by` cites a claim whose register status is OPEN
- **THEN** the gate returns exit 1 naming the claim as non-terminal

#### Scenario: obstacle claim not REFUTED rejected

- **WHEN** `closed_by` cites a failure-obstacle claim with status OPEN or
  DEFERRED
- **THEN** the gate returns exit 1 stating the path-scoped standard (REFUTED)
  is unmet

#### Scenario: unverifiable citation rejected

- **WHEN** the oracle has no workspace_path or the workspace has no
  claim-register.yaml or the cited id is absent from the register
- **THEN** the gate returns exit 1 with an unverifiable-citation reason
