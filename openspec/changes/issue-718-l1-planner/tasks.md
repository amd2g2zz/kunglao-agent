# tasks — issue-718-l1-planner

## 1. RED tests

- [x] `tests/test_l1_planner_718.py`:
  `test_rollout_return_computed_at_terminal` (the return exists after
  the first settlement, is the discounted SUM — never the mean — keys
  the dispatch-time signature, telescopes at γ=1, replays idempotently),
  `test_l1_value_updated_from_rollout_return` (± masses, cold Beta(1,1),
  terminal path end to end, sampled value follows the evidence),
  `test_planner_consumes_value_plus_cost_plus_knowledge` (learned V
  moves the choice; the cost model overrules; park is the 0-ratio
  baseline; the knowledge query feeds reuse; the vocabulary is closed),
  `test_solved_claim_reused_not_redispatched` (certified reuse wins;
  a superior-ratio re-attempt flips it; register = lifecycle;
  nothing known = no reuse candidate),
  `test_step_credit_flows_to_l2_only` (the return never reads step
  credit; the L1 bank never writes the q-cell store),
  `test_advisory_face_dormant_until_learned` ({} while empty; drags only
  answer-bearing claims), plus the rank integration pin, the seed
  contract pin and the action-vocabulary pin

## 2. The rollout return + the L1 value function

- [x] `scripts/rlvr/l1_value.py`: `compute_rollout_return` (pure,
  γ-parameterized; `transitions_sum` / `terminal` reported raw),
  `record_terminal_return` (reads the claim's transitions, appends ONE
  `l1-value-obs/1` row keyed to the dispatch-time signature; no
  signature -> no row + ONE warn), `record_observation` (the boundary:
  closed action vocabulary, finite return, fail-open I/O),
  `fold` / `cell_posterior` / `sample_value` (the q_cells DTS
  recurrence; the #428 adaptive schedule imported; ± masses),
  `state_signature_of`, `seed_state` (f(store, round)), `value_table`
  + CLI

## 3. The terminal wiring

- [x] `scripts/rlvr/scalar.py`: `_bank_q_cell_credit` returns the bank
  dict (the matched dispatch row's signature rides it); new
  `_bank_l1_rollout_return` called on the same first-settlement tick
  (`settle_round_credit`), fail-open + lazy import

## 4. The planner + the knowledge seam

- [x] `scripts/rlvr/l1_planner.py`: `candidate` (validated boundary;
  park is the only zero-cost action), `plan` (DTS draw per candidate,
  argmax value/cost, deterministic tie-break, park fallback),
  `plan_for_claim` (dispatch + park always; reuse on solved),
  `knowledge_query` (register / facts index / cross-task store, each
  fail-open; `answer_strength` = answer faces only),
  `advisory_factors` ({} while the store is empty; the dispatch share
  otherwise; deterministic per (store, round))

## 5. The additive rank consumption

- [x] `scripts/priority_ratio.py`: `priority_ratio` applies the advisory
  factors (0 < f < 1) multiplicatively before the sort and adds the
  per-claim `planner` feed; `_emit_rank_feeds` gains the additive
  `planner` payload block (absent -> payload byte-identical)
- [x] `scripts/rlvr/__init__.py`: the two modules + their faces in the
  one export map

## 6. Registration + docs

- [x] `scripts/README.md` catalog rows; `scripts/rlvr/README.md` face
  map section
- [x] `openspec/changes/issue-718-l1-planner/` (this change)
- [x] Baseline re-emits (`comment_hygiene_lint --emit-baseline`,
  `formal_code_lint --emit-baseline`, `deploy_manifest.py --write`)

## 7. Validation

- [x] `uv run python -m pytest tests/test_l1_planner_718.py -q -n 2` — 10
  passed
- [x] settle/credit regression batch (712 / 597 / 634 / 433 / 438 / 379)
- [x] rank regression batch (12 / 688 / 157 / priority_ratio / 218 / 9 /
  scorer-authority) — byte-identity of the empty-store path intact
- [x] `npx openspec validate issue-718-l1-planner --strict`
