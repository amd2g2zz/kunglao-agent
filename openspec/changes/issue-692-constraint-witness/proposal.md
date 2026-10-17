# Proposal — issue-692-constraint-witness

## Why

`not_done` counterexamples are integrity-protected at intake (R1 non-empty,
append-only after `--stamp-dispatch`, rewording refused, delivery
restatement) but nothing mechanically checked the deliverable against them
at settlement time. If a task demands "pure-algorithm offline" and the
`not_done` row forbids a browser/JSRPC runtime, an outcome-only oracle that
judges "request accepted" lets a degraded solution pass green, bank reward,
and be learned as a good method — reward hacking the system cannot see.

## What changes

- `constraint-witness/1` schema inside `<ws>/goal-operationalization.yaml`:
  a `constraint_witness.witnesses` mapping binding every `not_done` row
  1:1 to exactly one of `check: <command>` (exit 0 = the constraint holds
  at the delivered workspace) or `none: <reason>` (explicitly
  unwitnessable).
- `scripts/goal_operationalization.py` gains lint R6: a `not_done` row
  with no witness (or a malformed/orphaned witness entry) is refused —
  the validator exits non-zero, `--stamp-dispatch` refuses to freeze, and
  the witness block freezes with the constitution (post-dispatch
  withdrawal/weakening refused).
- `scripts/e2e/constraint_witness.py` evaluates the declared block against
  the delivered workspace and composes the joint verdict; the e2e ORACLE
  checkpoint in `scripts/e2e/checkpoints.py` now runs
  `verdict = witness AND outcome` — a tripped check turns the oracle RED
  even when the outcome checker is green.
- Fail-open + warn posture at settlement: a pre-contract workspace (no
  file / no block / unreadable YAML) evaluates to `UNDECLARED` with a
  warning and never blocks the outcome leg; an unrunnable check (spawn
  error / timeout) is an errored entry with a warning. Only a check that
  ran and exited non-zero is a witness-side RED. The hard refusal lives at
  intake (the lint) and at the dispatch gate (convergence re-validates the
  document on every decide).
- Operator-facing surfaces updated: skill pre-registration step, heartbeat
  constitution fill list, init draft scaffold, state template, e2e runbook
  C6-pre-1, scripts README catalog row.
- Local-only demonstration at
  `experiments/blocked-path-units/degraded-jsrpc/` (gitignored): a
  green-outcome degraded solution turned RED by its witness check.

## Non-goals

- The workspace case-set production oracle (`scripts/oracle_runner.py` /
  `oracle_cadence.py` reward channel) keeps its per-case semantics; the
  witness leg composes at status level there only if a follow-up card asks
  for it — this change lands the joint verdict at the e2e ORACLE
  checkpoint (the runbook's final verdict face) plus the intake lint.
- No new oracle case file format: the witness block lives in the
  goal-operationalization document, not in `oracle/cases/*.yaml`.
- No auto-derivation of witnesses — a witness is declared, never inferred.
