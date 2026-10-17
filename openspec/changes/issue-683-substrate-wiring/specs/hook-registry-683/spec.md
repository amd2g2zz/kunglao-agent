# hook-registry-683 delta — issue-683-substrate-wiring

## ADDED Requirements

### Requirement: One hook registry drives every reader and writer

The `(event, matcher, hook file)` row table SHALL be the single source
from which both the self-check's expected file set
(`WIRE_UP_HOOK_FILES`) and the deployed writer's table
(`hook_activation._DEPLOYED_WIRING`) derive — two hand-maintained
registry lists SHALL NOT exist. Every file the deployed writer
registers SHALL be a member of the derived file set, and the canonical
`register_hooks` SHALL register every deployed-wiring row (event +
matcher + file).

#### Scenario: the two registry views cannot drift

- **WHEN** the wiring row table and the registry file set are compared
- **THEN** their hook-file sets are equal, and `step_record_capture.py`
  and `cost_input_capture.py` are members of both

#### Scenario: a fresh wire-up writes the substrate hooks

- **WHEN** `register_hooks` runs against a scratch workspace
- **THEN** the workspace settings contain `step_record_capture.py` and
  `cost_input_capture.py` command entries, and every deployed-wiring row
  is present under its event with its matcher

#### Scenario: a deployed row the canonical writer cannot reach fails

- **WHEN** a row exists in the wiring table whose (event, matcher) the
  canonical writer never writes
- **THEN** the contract test reports the exact unreachable row instead
  of passing (the pre-#683 drift shape is loud)

### Requirement: Registry growth forces the deliberate subset tables to update

Importing `hooks_selfcheck` or `external_kicker` SHALL raise when the
derived registry contains a file neither its include nor its skip table
accounts for — a registry growth cannot silently leave a subset
checking or re-registering a stale file set.

#### Scenario: growth without a table update raises at import

- **WHEN** a hook file joins the wiring table without joining
  `_KONG_SKIP_FILES` or `_KICKER_SKIP_FILES`
- **THEN** `derive_hook_subset` raises a `ValueError` naming the
  unaccounted file on the next import of the consumer
