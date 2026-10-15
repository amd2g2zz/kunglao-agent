# Design — issue-718-l1-planner

## The one principle

All decisions — L1 planning AND L2 execution — run under the SAME
value/cost criterion, learn through the SAME mechanism (DTS posteriors),
and are settled by their OWN layer's credit stream. Everything below is
a corollary of that principle, not an extra mechanism.

## Policy, not rule (the invariant)

There is NO trigger anywhere in `rlvr.l1_planner`: no "N failures ->
split", no "solved -> skip", no threshold constant that fires an
action. The whole decision is:

    for each candidate: theta ~ Beta(cell posterior of (s, action_kind))
                        value = theta × VALUE_SCALE  (or a KNOWN
                                knowledge hint — never sampled)
                        ratio = value / cost
    chosen = argmax ratio            (park = the 0-ratio baseline)

Failure streaks and no-progress patterns enter through the STATE
FEATURES already carried by the canonical signature (`state-sig/2`:
the claim status-pattern segment and the attributed-obstacle inventory
`ob=`) — if "split after k failures" ever emerges, it emerges from
posterior mass, not from a written rule. Solved knowledge is the `reuse`
candidate's VALUE, never a veto.

## Rollout return semantics (#716)

    R(τ) = Σ γ^t · r_t          the discounted SUM, terminal-dominated

The mean is a DIFFERENT objective (average-reward) which dilutes the
sparse terminal reward (claim PROVEN/REFUTED) toward zero — no
mean-based learning target exists anywhere on this surface. With the
shipped potential-based shaping (`r_t = ALPHA·ΔΦ − LAMBDA·cost`, the
transition ledger's own `r_incr`) the sum telescopes:

    Σ r_t = Φ(s_T) − Φ(s_0) − Σcost + terminal settlement

so the trajectory LENGTH is absorbed by the math and the terminal is
never normalized away. γ = 1.0 is the shipped calibration face (the
exact sum; the telescope pinned by test); the γ parameter exists for
later equal-budget calibration and changing the shipped value follows
the ADR-001 governance procedure. Cross-arm comparison, when it comes,
uses EQUAL BUDGET (pass@k / same-cost), never per-step means —
`compute_rollout_return` reports the raw chain (`transitions_sum`,
`terminal`) beside the total so nothing hides behind the discount.

## Value / cost, not cheapness (doing nothing costs 0)

The criterion is **value per unit cost** (性价比). Park — the do-nothing
baseline — has cost 0 AND value 0, so its ratio is 0.0 by construction:
"find a cheaper action" can never win, and a candidate needs positive
marginal value to be chosen at all (all ratios ≤ 0 -> park). The
boundary enforces the shape: a non-park candidate with cost ≤ 0 is
refused (`ValueError`) — park is the only zero-cost action.

Exploration is expressed the same way everywhere else in the system: a
DTS draw from the cell posterior. A cold cell is the wide Beta(1,1)
(draws around the neutral value 1.0 = prior mean 0.5 × 2); a
settled-bad cell effectively never retried; a settled-good cell
concentrates. No exploration bonus, no count cliff, no phase switch.

## Reuse before dispatch

`solved` claims — a verified answer exists on record — get the `reuse`
action: cost REUSE_COST (0.1 — a read, not a run) with the knowledge
query's graded strength as its value (certified 1.0 / cross-task 0.5 /
weak-terminal 0.3). The re-attempt decision is then the ordinary
comparison: a re-dispatch is chosen exactly when its value/cost ratio
exceeds the replay's with positive marginal value. The test suite pins
BOTH directions (reuse wins by default; a superior-value/cost re-attempt
flips it), so the mechanism provably is not a rule.

The knowledge query grades three faces, each fail-open:

| face | question answered | strength |
|---|---|---|
| register | is the claim closed? (lifecycle) | PROVEN/VERIFIED 1.0, other terminal / partial 0.3 |
| facts index | does a verified answer artifact exist? | PROVEN/VERIFIED 1.0, other terminal 0.3 |
| cross-task store | did another engagement solve this identity? | credit > 0 -> 0.5 |

The rank-side drag keys on the ANSWER faces only (`answer_strength`):
the register reports lifecycle, which the rank frontier already
enforces; the facts/cross-task faces report that an answer EXISTS —
which is what "don't re-run" is about.

## Investment handling (learning state ∈ s)

Nothing here pays for exploration. The L1 cells' posterior width IS the
investment: a state whose cells are wide samples bravely, and the
rollout return at terminal includes the Φ-chain the attempt moved —
because `r_t` carries `ΔΦ − cost`, spending that moves the state
forward is credited by the return itself. The value function is
full-horizon by construction (the return sums the WHOLE claim
trajectory plus the terminal settlement), so the option value of
learning is inside the learning target rather than bolted on as an
exploration bonus or an investment budget.

## L1 / L2 signal separation (no mixing)

| signal | written by | store | consumer |
|---|---|---|---|
| step credit (immediate, step boundary) | `rlvr.step_grain` / `q_cells.observe_step_credit` | `runs/q-cell-log.jsonl` (`credit_kind: step`) | L2 preference tables |
| rollout return (terminal) | `scalar.settle_round_credit` -> `l1_value.record_terminal_return` | `runs/l1-value-log.jsonl` | L1 value function |
| verified knowledge (post-settlement) | the settlement faces | facts / register / cross-task store | knowledge query (reuse) |

The L1 return reads only the transition chain (`rlvr.incremental_reward`
rows) plus the ladder credit; step rows never enter it. The L1 bank
never writes the q-cell store (the #712 terminal residual calibration
remains the L2 face's own correction). Two signals, two stores, two
consumers — pinned by test in both directions.

## The advisory consumption face

`l1_planner.advisory_factors(ws, claim_costs)` returns {} while the
value store is empty — the rank path (`priority_ratio`) then runs the
pre-#718 code path byte-identically (frozen captures untouched). Once
learned, it returns the planner's dispatch SHARE per claim:
`ratio_dispatch / Σ ratio_candidates` over `plan_for_claim`'s set. An
unsolved claim with no answer on record is exactly 1.0 (its only
positive-ratio candidate is the dispatch itself); a claim with a
verified answer is dragged toward its replay's dominance. The factor is
applied multiplicatively to the ranked score and rides the payload as
an additive `planner` block plus a per-claim feed — outputs, outside
`input_fingerprint`, same convention as the #688 view keys.

Why the share and not the raw learned value: the cells are keyed by
(state, action_kind) — a per-STATE component cannot reorder candidates
within one state by construction. The per-claim signal available at L1
is the knowledge comparison; the learned face's consumers are the
planner's own choices (receipts) and, once a later card wires the
receipt, the live decision.

## Failure modes (all fail-open)

- no dispatch-time signature at terminal -> no L1 row + ONE warn (the
  honest gap: a post-terminal state would key the wrong cell);
- unreadable value log -> empty fold (cold prior), never a crash;
- a broken knowledge face -> that face contributes nothing (never
  fabricates knowledge), ONE warn;
- planner failure inside the rank -> `{}` factors, the ranking result
  untouched (the decide fail-open contract).

## Rollout ledger interop

The L1 observation is its own append-only store, keyed by the
dispatch-time state signature and the action kind. It does NOT amend
the rollout ledger: the ledger's settlement face stays the L1/L2 shared
BOOK of what settled, while `runs/l1-value-log.jsonl` is the L1
learning feed (one row per first settlement, idempotent under replay —
the same first-settlement guard that gates the L2 bank).
