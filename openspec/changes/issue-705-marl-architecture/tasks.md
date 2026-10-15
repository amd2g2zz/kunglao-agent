# tasks — issue-705-marl-architecture

## 1. Agent-conditioned Q (agent-conditioned-q-705)

- [ ] `arm_key(..., agent_type=None)`: additive 5th dim; falsy agent →
      the byte-identical 4-dim key
- [ ] `agent_of_action(action_key)`: fifth segment or None for legacy
- [ ] `cell_posterior`: 5-dim key addresses the agent cell; the 4-dim
      same-arm cell stays in the anchor (no forced pooling into local)
- [ ] `record_dispatch_observation`: thread `agent_type` from envelope
      meta into the arm key
- [ ] RED: different agent types produce different posteriors; legacy
      4-dim key byte-identical

## 2. Knowledge transfer (knowledge-transfer-705)

- [ ] `scripts/rlvr/marl.py`: `signature_class`, `record_negative`,
      `negative_pools`, `broadcast_solution`
- [ ] `cell_posterior(..., negative_pool=)` + `sample_method_family(
      ..., negative_pools=)`: failure mass rides the anchor under the
      one SHRINK_CAP, additive receipt block
- [ ] RED: agent B's cold cell inherits agent A's mass through the
      anchor; negative knowledge is class-scoped (other classes blind);
      broadcast writes the method and never the answer text

## 3. Agent-level credit (agent-credit-705)

- [ ] `observe_settlement(..., credit_kind="solve")`: solve updates the
      Beta; verification records a row excluded from the fold
- [ ] `fold()`: rows carrying `credit_kind: "verification"` contribute
      to neither success, failure, nor n_pending
- [ ] `strategy_store.warm_pools`: same admission filter
- [ ] RED: solve credit moves the posterior; verification credit does not

## 4. Verification

- [ ] three spec deltas registered; `openspec validate
      issue-705-marl-architecture` exit 0
- [ ] `tests/test_marl_architecture_705.py` green with `-n 2`
- [ ] legacy suites green: `test_action_space_539`, `test_q_cells_429`,
      `test_ws2_tiebreaker_545`, `test_feature_prior_460b`
- [ ] comment/formal-code/deploy lints clean; deploy manifest re-emitted
