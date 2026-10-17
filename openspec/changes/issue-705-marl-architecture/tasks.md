# tasks — issue-705-marl-architecture

## 1. Agent-conditioned Q (agent-conditioned-q-705)

- [x] `arm_key(..., agent_type=None)`: additive 5th dim; falsy agent →
      the byte-identical 4-dim key
- [x] `agent_of_action(action_key)`: fifth segment or None for legacy
- [x] `cell_posterior`: 5-dim key addresses the agent cell; the 4-dim
      same-arm cell stays in the anchor (no forced pooling into local)
- [x] `record_dispatch_observation`: thread `agent_type` from envelope
      meta into the arm key
- [x] RED: different agent types produce different posteriors; legacy
      4-dim key byte-identical

## 2. Knowledge transfer (knowledge-transfer-705)

- [x] `scripts/rlvr/marl.py`: `signature_class`, `record_negative`,
      `negative_pools`, `broadcast_solution`
- [x] `cell_posterior(..., negative_pool=)` + `sample_method_family(
      ..., negative_pools=)`: failure mass rides the anchor under the
      one SHRINK_CAP, additive receipt block
- [x] RED: agent B's cold cell inherits agent A's mass through the
      anchor; negative knowledge is class-scoped (other classes blind);
      broadcast writes the method and never the answer text

## 3. Agent-level credit (agent-credit-705)

- [x] `observe_settlement(..., credit_kind="solve")`: solve updates the
      Beta; verification records a row excluded from the fold
- [x] `fold()`: rows carrying `credit_kind: "verification"` contribute
      to neither success, failure, nor n_pending
- [x] `strategy_store.warm_pools`: same admission filter
- [x] RED: solve credit moves the posterior; verification credit does not

## 4. Verification

- [x] three spec deltas registered; `openspec validate
      issue-705-marl-architecture` exit 0
- [x] `tests/test_marl_architecture_705.py` green with `-n 2`
- [x] legacy suites green: `test_action_space_539`, `test_q_cells_429`,
      `test_ws2_tiebreaker_545`, `test_feature_prior_460b`
- [x] comment/formal-code/deploy lints clean; deploy manifest re-emitted
