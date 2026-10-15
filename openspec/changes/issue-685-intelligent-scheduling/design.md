# design — issue-685-intelligent-scheduling

## Verified anchors (branch feat/685-intelligent-scheduling off dev 4918ad1f)

| Question | Actual | Drift |
|---|---|---|
| Where the fixed cron lives | `scripts/loop_scheduler.py` writes the durable entry (`*/5 * * * *`); `scripts/heartbeat.py` registers `interval_min: 5`; `scripts/cadence_advisor.py` holds FLOOR/CEIL/STEP/EVAL_EVERY_TICKS; `scripts/liveness_policy.py` holds `TICK_INTERVAL_DEFAULT_MIN` | none — the constants stay, re-framed as priors/fallbacks |
| The watchdog predicate that already exists | `scripts/loop_watchdog.py` — fires guidance only on missed events (heartbeat-gap / stuck-worker / step-failure); the loop prompt already declares the event-wakeup topology | reused; the card adds the recorded DECISION, not a second predicate |
| The action vocabulary | `scripts/action_space.py` — four levels, `ActionSpec` metadata, the registry single source; the claim-category table moved here verbatim | extended: `ActionSpec.scheduling` flag + the scheduling five |
| Propensity recording precedents | `scripts/planning_actions.py` (escrow/revoke, propensity in [0,1], refused loudly outside); `scripts/e2e/checkpoints.py` (`_stamp_ope_propensity`: declared -> pi = 1.0, sampled -> MC propensity, uniform -> 1/K); `scripts/priority_ratio.py::_view_stats` (rank-time entropy/propensity/k as pure readouts) | the scheduling decisions join the same discipline |
| Existing top-k utilities | `rlvr.compose.schedule_cards`, `query_formulation._hits_for`, `references_recall` — all DETERMINISTIC score sorts, no sampler, no propensity; no Gumbel anywhere before this card | deliberately not reused: a deterministic top-k cannot supply a sampling probability |
| The three-budget sources | tokens: `tuition_curve.cost_state` (the mission ledger's own spend reader); tool_calls: `rlvr.step_ledger` step-record/1 rows (one row IS one tool call); verify_calls: `signals_stream.penalty_counts` verify count | wired as one `budget_face` triple |
| The budget face in the decision view | `scripts/decision_view.py` — `budget` face keys {tokens, tool_calls, verify_calls, accounted} shipped as honest nulls while cost stays diagnostic-only upstream | unchanged by this card; the scheduling decision reads the same three sources directly |
| Null-review evidence | `tests/test_liveness_triad_682.py` pins the current cadence behavior (busy -> floor, quiet -> +5) — the advisor path is untouched by this card | none |

## Decision 1: the scheduling five are actions in the registry, not a parallel list

The wake vocabulary rides `action_space.ACTIONS` with a `scheduling` flag; `intelligent_scheduling.SCHEDULING_ACTIONS` is derived from the flagged subset (registry order), never a hand-kept twin. `none` (the null action) is a first-class member: cost 0, value 0 — the one registry entry whose cost is zero BY DESIGN (the do-nothing baseline). An action_space change arrives with the usual metadata obligations (precondition / proof power / consumer / estimator signature stub).

## Decision 2: k = min(free_slots, f(entropy)) is derived, never triggered

`f_entropy(h) = max(1, ceil(h))` over the frontier PQ entropy in bits; the slot monitor's own ledger supplies free_slots; `adapt_k` returns the min, with two documented edges: unknown entropy -> the conservative floor (1), no slot room -> 0 (the forced-null case). Nothing branches on a threshold — an amount is derived from two state quantities, and both inputs plus the derived k ride every decision record. The demand function is the LEARNED quantity's seat: the observed (cost, progress) pair — the signal stream this module writes — updates the priors; this card ships the flat day-one priors.

## Decision 3: Gumbel top-k WITHOUT replacement is the sampler; the propensity is exact

The ordered top-k of Gumbel-perturbed logits is, by the Gumbel-max lemma, an exact Plackett-Luce draw: sequential softmax over the remaining candidates. The logged propensity is the product of those terms — the decision's true sampling probability, so IPS/DR weights are computable from the log alone. No deterministic top-k utility from elsewhere in the tree is reused because none of them samples (they cannot name a probability); the Gumbel machinery is small, pure, and seeded by an injected rng so replay is exact. The full-batch probability is what the row's `propensity` carries; each selected member also carries its own sequential term.

## Decision 4: the null-action baseline protocol

The do-nothing action must be measurable, or no timer action's value claim means anything. The protocol every future timer action is measured under:

1. **Identity**: the null action is `orchestration.none` — cost 0, value 0 by definition; a nonzero cost/value on it is a spec violation.
2. **Same-point pairing**: every decision row carries the chosen action's propensity AND the null action's propensity at that same decision point (`null_propensity`), computed under the same candidate logits. A timer action is never compared against a null propensity from a different state mix.
3. **Off-policy evaluation**: value estimates are IPS/DR weights over the signal stream rows (`1/propensity`), the same discipline the dispatch-receipt propensity already feeds (`rlvr.policy_compare` reads the propensity column). Rows without a propensity are excluded from the estimate, never zero-filled.
4. **Claim ordering**: a timer action earns "worth scheduling" only when its estimated value beats the do-nothing estimate on the same decision-point population; below the comparison protocol's sample floor the honest verdict is UNDECIDED, not green.
5. **Forced states still record**: k = 0 (no slot room) or a declared action still writes the null baseline beside the choice — absence of a decision is itself a decision point.

## Decision 5: the cron demotion is an ARMED watchdog, default-safe

Every record carries `watchdog: {role: "watchdog", armed: true, interval_min: N, mode: event_first|poll_fallback}`. The polling fallback interval comes from the armed cadence interval when a source exists, else the historical policy default — the demotion can never silently change the polling cadence (default-safe). `mode` is event-first when the event wake (`wake_on`) rides the selection, otherwise the poll fallback carries the next wake. The cron path itself (`loop_scheduler` / `heartbeat`) is NOT edited by this card: demotion is semantic (the decision rides the action pipeline), deletion is explicitly out of scope.

## Decision 6: one decision, two write faces, both fail-open

`runs/.scheduling-decision.json` is the read seam (briefs/views); one `kind=scheduling` row on `runs/signals.jsonl` is the evaluable face (the estimators read the stream, never memory). Both writes fail open behind the canonical warn: a recording failure never blocks the caller's wake path, and a refused input (unknown declared action, unknown logits name) raises at the API boundary before either write.

## Process disclosure

The GitNexus index is not present in this worktree; impact analysis ran as a mechanical call-site survey: `action_space.ACTIONS` consumers are `priority_ratio` (claim-category table + weights loader), `planning_actions` (the `settleable` gate — the new entries are non-settleable, so it still refuses them) and two test modules; the `ActionSpec` change is additive (new defaulted field, new keyword) and the registry addition is appended at the orchestration level with the count pin updated in the same change. No existing function's behavior changes; `tests/test_action_space_12.py`'s frozen rank capture still passes byte-for-byte.
