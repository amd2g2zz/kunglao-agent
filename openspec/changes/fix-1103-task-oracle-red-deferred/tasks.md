# Tasks — fix-1103-task-oracle-red-deferred

## 1. Red test (test-first)

- [x] 1.1 Add `TestOracleRedDeferred` to `tests/test_rollout_ledger_366.py`:
      `classify("task", [claim_terminal=DEFERRED, oracle_verdict=fail])`
      must land SETTLED_RED / `task/oracle-red`, reward 0.0, both signal
      refs in `evidence_refs`; plus a dual-signal-shape pin. Verify:
      run the class, both cases fail with `assert 'NEUTRAL' ==
      'SETTLED_RED'` (red evidence
      `.claude/PRPs/relay/evidence/1103-task-oracle-red/red.txt`).

## 2. Rules table (GREEN)

- [x] 2.1 `references/contracts/reward-rules.yaml`: add DEFERRED to
      `task/oracle-red` claim_terminal `in`, `version: 5`, append the
      version 5 description paragraph. Verify: the red class flips
      green.
- [x] 2.2 Sync `version == 4` pins to 5 in
      `tests/test_scalar_settlement_379.py`,
      `tests/test_phi_tree_796.py`,
      `tests/test_round_credit_alignment_433.py`. Verify: those files
      pass under pytest.

## 3. Verification

- [x] 3.1 Run the verification set
      (`uv run pytest tests/test_rollout_ledger_366.py
      tests/test_scalar_interval_390.py tests/test_scalar_settlement_379.py
      tests/test_gap_notes_391.py tests/test_phi_tree_796.py
      tests/test_round_credit_alignment_433.py -q`) — all green
      (evidence `green.txt`: `163 passed in 6.48s`).

## 4. Relay hand-off

- [x] 4.1 Append the leg's final entry to
      `.claude/PRPs/relay/1103-task-oracle-red.md` (Legs log + Current
      state). Verify: the notes file names the evidence paths and the
      reviewer's entry point.
