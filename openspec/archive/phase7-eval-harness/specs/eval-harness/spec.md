# Spec Delta — phase7-eval-harness
## ADDED Requirements
### Requirement: Eval harness oracle self-check
The eval harness self-validates via 10 known-answer oracle cases covering core orchestrator behaviors (leverage/discriminator/novelty/cost/dispatchable/determinism). The oracle is deterministic and must pass 10/10.
#### Scenario: oracle 10/10
- WHEN oracle_selfcheck runs
- THEN all 10 cases pass (terminal_leverage_zero, downstream_leverage_high, competitor_group_disc_top, answers_question_disc_mid, else_disc_floor, tier_cost_penalty, saturated_novelty_low, fresh_novelty_high, impossible_claim_excluded, deterministic_pure)
### Requirement: Three-arm configuration + fault injection taxonomy
Three arms (A mechanisms-on / B mechanisms-off / C single-agent) and five fault-injection types (throttle/implicit_fail/explicit_fail/impossible/adversarial) are defined. impossible fault is verified (claim with no dispatchable path is excluded).
#### Scenario: impossible fault detected
- WHEN a claim depends on a never-terminal parent
- THEN inject_fault("impossible") confirms it is excluded from top_actions
