# Proposal — fix-1103-task-oracle-red-deferred

## Why

The `task/oracle-red` rule never matches real failure data: a failed task
rollout records `claim_terminal=DEFERRED` (the convergence gate defers the
claim; NEGATIVE/REFUTED never occur in recorded data), so a real
oracle-fail settles NEUTRAL under `task/pending` instead of
SETTLED_RED `task/oracle-red` (issue 1103). The red side of the task
settlement is dead on arrival.

## What Changes

- `references/contracts/reward-rules.yaml` — add `DEFERRED` to
  `task/oracle-red.requires[claim_terminal].in` (was `[NEGATIVE, REFUTED]`);
  the rule keeps its dual-signal shape (oracle_verdict=fail AND
  claim_terminal). No reward values or polarities change.
- Rules file `version: 4` -> `5`; the description gains the version 5
  paragraph documenting the DEFERRED join.
- Version pins in three test files that assert `version == 4` rise to 5
  (`test_scalar_settlement_379.py`, `test_phi_tree_796.py`,
  `test_round_credit_alignment_433.py`).
- New red-then-green test: `classify("task", [claim_terminal=DEFERRED,
  oracle_verdict=fail])` must land SETTLED_RED / `task/oracle-red`,
  reward 0.0, with both signal refs in `evidence_refs`.

### Acceptance

- `uv run pytest tests/test_rollout_ledger_366.py
  tests/test_scalar_interval_390.py tests/test_scalar_settlement_379.py
  tests/test_gap_notes_391.py -q` is all green.
- Before the rules change the new classify case failed with
  `assert 'NEUTRAL' == 'SETTLED_RED'` (red evidence:
  `.claude/PRPs/relay/evidence/1103-task-oracle-red/red.txt`); after it,
  `163 passed` (green evidence: `green.txt`).

## Capabilities

### New Capabilities

- `reward-settlement` — the deterministic, machine-signal-only settlement
  of task rollout rows (the reward-rules.yaml contract's task-kind face:
  failure settlement requires the oracle verdict AND the claim terminal).

### Modified Capabilities

(none — `openspec/specs/` is empty; this change adds the first delta for
`reward-settlement`.)

## Impact

- `references/contracts/reward-rules.yaml` (rules table, version bump).
- No `.py` symbol changes — the engine (`rlvr/reward.py classify`) is
  data-driven and reads the table unchanged.
- Downstream: rows with claim_terminal=DEFERRED + oracle_verdict=fail now
  settle SETTLED_RED (reward 0.0, negative polarity) — they feed the beta
  count of the prior feed instead of nothing. No historical backfill
  (out of scope per pipeline decision).
