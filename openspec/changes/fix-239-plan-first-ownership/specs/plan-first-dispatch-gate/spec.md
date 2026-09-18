# Spec Delta — plan-first dispatch gate (issue #239)

## MODIFIED Requirements

### Requirement: Plan-first SHALL gate execution, not the first dispatch

The worker_budget `plan` pre_check gate MUST pass the FIRST dispatch of a
claim (no prior approved dispatch recorded in the claim's approval-point
anchor log `runs/.dispatch-anchor-<KEY>.jsonl`) without requiring any
pre-existing plan file or in-prompt plan reference. A RE-dispatch of a claim
with at least one prior approved dispatch MUST require the plan reference:
either an on-disk `runs/plan-<KEY>*.md` with content and worker-session
provenance (an issued dispatch anchor cited, or a `dispatch-anchor:` line
with an mtime after the first issued dispatch), or a plan path for THAT
claim referenced in the dispatch prompt (re-dispatch continuity). The
current dispatch's own KUNGLAO_DISPATCH_CONTEXT nonce and context-file nonce
MUST NOT count as a prior dispatch.

#### Scenario: first dispatch of a fresh claim passes without a plan

- **WHEN** claim C-001 has never been approved for dispatch (no anchor log)
  and no `runs/plan-C001*.md` exists and the dispatch prompt carries no plan
  reference
- **THEN** the `plan` gate passes and the dispatch is not rejected on
  plan-first grounds

#### Scenario: re-dispatch beyond the planning round without a plan reference

- **WHEN** a first dispatch of C-001 was approved (anchor log has a row), no
  worker-authored plan exists, and the re-dispatch prompt references no plan
  path for C-001
- **THEN** the `plan` gate REJECTS with the re-dispatch repair path

#### Scenario: ghostwritten plan does not satisfy a re-dispatch

- **WHEN** a plan file for C-001 exists but carries no issued dispatch anchor
  citation and its mtime predates the first issued dispatch
- **THEN** the `plan` gate REJECTS the re-dispatch (plan-author provenance,
  #57 gate 3: the plan must be authored in the worker's session)

#### Scenario: worker-authored plan satisfies a re-dispatch

- **WHEN** the worker wrote `runs/plan-C001-strings.md` during the planning
  round citing its dispatch anchor (`dispatch-anchor: <issued ts>`) and the
  claim is re-dispatched
- **THEN** the `plan` gate passes
