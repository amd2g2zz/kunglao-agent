# plan-drift-terminal delta — issue-674-676-677-template-hygiene

## ADDED Requirements

### Requirement: Terminal claims are exempt from ORPHAN_CLAIM

`plan_drift_detector` SHALL NOT report `ORPHAN_CLAIM` for a
claim-register claim whose status is in the canonical TERMINAL set: the
rendered plan face carries the open thread only, so a terminal claim is
structurally unrepresentable there and its absence re-fired after every
re-render, blocking dispatch forever. Every other drift class SHALL keep
auditing terminal claims unchanged.

#### Scenario: a rendered face with terminal claims checks clean

- **WHEN** `plan_drift_detector --active-only` checks a render-marker
  `global_plan.txt` against a register holding terminal and
  non-terminal claims
- **THEN** no `ORPHAN_CLAIM` row names a terminal claim, and a re-render
  of the face keeps the same clean verdict

#### Scenario: frontier claims still drift

- **WHEN** the same check finds a NON-terminal register claim absent from
  the plan
- **THEN** `ORPHAN_CLAIM` still fires for that claim with its fix text

#### Scenario: the reality check on PROVEN claims is untouched

- **WHEN** a register claim at status PROVEN has no corroborated verify
  record
- **THEN** `UNVERIFIED_EVIDENCE` still fires for it even though the same
  claim is exempt from `ORPHAN_CLAIM`

#### Scenario: next-step sections still flag terminal claims

- **WHEN** a plan's next-step section still lists a claim whose status is
  terminal
- **THEN** `STALE_NEXT_STEP` still fires for that claim
