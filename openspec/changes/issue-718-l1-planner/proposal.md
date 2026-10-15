# Proposal — issue-718-l1-planner

## Why

The orchestration layer has NO learner. Measured state on dev:

- the only learned object on the EXECUTION side is the L2 cell —
  `(signature_hash, arm_key)` Beta posteriors updated by per-dispatch /
  per-step credit (the ranker's case posteriors are outcome-updated
  heuristics, not the credit-attributed execution learner);
- no rollout-level return is computed, stored, or consumed anywhere
  (`runs/transitions.jsonl` rows carry per-step shaped rewards, but
  nothing sums them; the round-credit ladder settles per dispatch and
  stops there);
- claim selection / worker assignment / stopping are decided by
  heuristics (`priority_ratio` Thompson on case posteriors + worth) and
  the LLM, with zero credit attribution.

The highest-leverage decisions (WHAT to do, WHEN, WHO) therefore sit
outside the learning loop — the single biggest architectural gap of the
milestone. The owner ruling (2026-10-16) puts a planner above the
workers: three signals, three consumers — step credit (immediate) feeds
the L2 preference tables; the rollout return (terminal) feeds the L1
value function; verified knowledge (post-settlement) enters the
substrate and is queried BEFORE dispatch.

## What Changes

1. **The rollout return exists** (`rlvr.l1_value`): at the claim-
   terminal first settlement — the same tick that banks the L2 ladder
   credit (`scalar.settle_round_credit` → `_bank_l1_rollout_return`) —
   the planner computes `R(τ) = Σ γ^t·r_t` (the discounted SUM,
   terminal-dominated; γ=1.0 shipped, the exact telescope) over the
   claim's transition chain plus the terminal ladder credit, and stores
   ONE append-only observation row `runs/l1-value-log.jsonl`
   {state_signature, action_kind, return, steps, components}. NOT the
   mean: average-reward is a different objective that would flatten the
   sparse terminal reward toward zero.

2. **The L1 value function** (`rlvr.l1_value`): (state_signature,
   action_kind) Beta cells folded from those returns — positive return
   mass banks success, negative mass banks failure, 0.0 banks nothing —
   with the q_cells DTS machinery mirrored (the #428 adaptive schedule
   imported, the γ-discounted read face, `sample_value` draws,
   `seed_state` = f(store, round)). Failure patterns (long streaks, no
   progress) are INPUT FEATURES of the canonical state signature — the
   claim pattern and the attributed-obstacle inventory already ride it —
   never triggers.

3. **The planner** (`rlvr.l1_planner`): action selection is a POLICY,
   not a rule. Given candidates over the ruling's action vocabulary
   (dispatch / park / split / verify / reuse), `plan` samples one DTS
   draw per candidate's (state, action_kind) cell and picks the argmax
   of **value / cost** — doing nothing costs 0, so cheapness alone can
   never win (park's ratio is 0.0 by construction and is the honest
   fallback when no candidate has positive marginal value).

4. **The knowledge seam** (`l1_planner.knowledge_query`): the facts
   index (verified answers), the claim register (lifecycle) and the
   cross-task posterior store (`strategy_store` rows carrying the claim
   id) — graded into a knowledge strength. A solved claim gets the
   near-zero-cost `reuse` action (`plan_for_claim`); re-attempt wins
   exactly when its value/cost ratio beats the replay's — a comparison,
   not a prohibition.

5. **Additive advisory consumption** (`priority_ratio`): while the L1
   value store is empty the rank path is byte-identical (dormant face);
   afterwards, claims with a verified answer on record are dragged by
   the planner's dispatch SHARE of their candidate ratios, and the
   `rank_feeds` payload gains the additive `planner` block. The existing
   ranker (case posteriors, worth, downstream) is untouched.

6. **Signal separation stays absolute**: the step-credit stream writes
   only the L2 q-cell store; the rollout return writes only the L1
   store; neither face reads the other's rows.

## Non-goals

- Replacing the ranker/decide path — the planner ships ADVISORY first
  (reweight/propose; the surfaces consume the factors), exactly like the
  L2 sampler's P_LLM ⊗ Q posture.
- A learned stopping rule / budget scheduler — `park` is an available
  action whose value is the do-nothing baseline; the learned policy is
  the consumer.
- Re-keying anything: the canonical state signature (`state-sig/2`) is
  reused bit-for-bit; no L2 cell moves.
- Wiring the planner's receipt into the live dispatch gate (a later
  card consumes the receipt; this card makes the signal exist and shows
  the advisory consumption).
