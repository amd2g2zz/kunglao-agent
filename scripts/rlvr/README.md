# rlvr — the unified RLVR package surface (issue #420)

Owner direction (2026-09-27, issue #420 re-triage): the RLVR surface —
reward settlement, scalar settlement, the rollout ledger, prior
computation, experience triples, the state signature, and heartbeat
liveness — has no unified module design. Exports are scattered
(`settled()`, `tuples()`, `scalar_observations()`, `prior_observations()`,
`experience_tuple`, each module re-deriving its own faces) and the
statistical math is hand-rolled. This document declares the unified
package surface; execution is **phase-gated**:

- **Phase 1 (PR #420 wave 1)** — numpy dependency via uv lock, this design,
  the bit-exact pin framework (`tests/test_rlvr_bitexact.py`), and the
  numpy pattern-setter adoption in two self-contained spots
  (Normal-Gamma pooling internals; winrate curve aggregation).
- **Phase 2 (LANDED, #420 follow-up)** — consolidation into this
  package: the eight face modules (ledger / reward / scalar / priors /
  triples / winrate / state / liveness) carry the implementation
  bodies, thin adapters stay at the old import paths, the remaining
  hand-rolled math (Beta aggregation loops, prior-feed counts, the
  v_anchor weighted mean, the Q-report per-cell means, the q_cells
  family-mass and sampling-weight reductions) moved onto the numpy
  pattern bit-exactly, and the export map in `rlvr/__init__.py` gained
  the `q_cells` and `compose` faces. All pins in
  `tests/test_rlvr_bitexact.py` held without re-minting.

## The package

```
scripts/rlvr/
├── __init__.py          # THE one import point + one export map
├── ledger.py            # rollout_ledger (U1) — append-only settlement ledger
├── consolidated_ledger.py  # #721 the 4-file consolidation core —
│                        #   experience/settlement/telemetry under runs/ +
│                        #   knowledge under the guarded root; append()
│                        #   (flock, stamp-refusing) / read() (legacy-first,
│                        #   stamp filter) / liveness() / migrate()
│                        #   (append-only, bytes-archived, idempotent)
├── reward.py            # reward_settlement (U2/U3) — band/reward engine
├── scalar.py            # scalar_settlement — tiers, tuples, Normal-Gamma,
│                        #   round credit, trajectory validator
├── priors.py            # compute_priors (U4 feed consumer) — aggregate prior
├── probe_face.py        # #956 the mechanical V(s) probe-face contract —
│                        #   run_probe(unit_dir, ws) through the unit-local
│                        #   probe.py shim (checker.py's trust boundary,
│                        #   mirrored) + probe_delta (the #954 ΔV seam);
│                        #   fail-closed, deterministic, oracle-locked
├── direction.py         # #954 the direction face (Type-3) — Beta
│                        #   posterior (α, β) per direction over the shared
│                        #   runs/direction-state.jsonl (sibling rows to the
│                        #   #958 censor rows), per-step credit =
│                        #   probe_face.probe_delta (the ΔV seam), racing
│                        #   elimination gated on posterior collapse (no
│                        #   failure evidence -> never eliminated);
│                        #   KUNGLAO_DIRECTION=1, default OFF
├── triples.py           # experience_triples — (s, a, r) CSV view + Q report
├── winrate.py           # winrate_curve — read-side aggregation face
├── state.py             # state_signature — canonical state + V(s) anchor
├── posteriors.py        # DTS posterior store, Discounted Thompson
#                        #   Sampling (issue 428) —
│                        #   append-only runs/posterior-store.jsonl + fold/read
│                        #   γ decay + pseudo-count priors + γ schedules
├── liveness.py          # heartbeat continuity — evaluate_tick_continuity core
├── obstacles.py         # obstacle/1 attribution registry (issue 461
│                        #   Phase 1) — intervention-born failure-cause
│                        #   objects as runs/obstacles/OBS-<n>.json,
│                        #   read into the state signature's ob= segment
├── termination.py      # option-death estimator (issue 461 Phase 2) —
│                        #   the learned "when to quit": Beta per
│                        #   (obstacle-kind, method-family), floor-
│                        #   not-delete sampler verdicts (PARK posture)
├── expansion.py        # discovery-layer operator (issue #546 WS4/L3) —
│                        #   trigger over sanctioned faces (obstacles K +
│                        #   collapsed arms), feature-keyed novelty (the
│                        #   anti-renaming wall), verifier-gated admission
│                        #   scoring, runs/expansion/E-<n>.json receipts
├── family_playbook.py  # #960 the Type-2 transfer store — family playbook
│                        #   kunglao-playbook/1 schema (parse/serialize
│                        #   byte-stable, hard line budget 60, capacity
│                        #   culling 宁缺毋滥), operator-local root
│                        #   (KUNGLAO_PLAYBOOK_ROOT), session_block()
│                        #   whole-file init injection (no retrieval)
├── playbook_distill.py # #960 the terminal distillation call — ONE
│                        #   frozen-model call per rollout terminal
│                        #   (claude -p bench seam, stub-injectable),
│                        #   mechanical patch gate (evidence-ref
│                        #   existence vs ws, shape, budget), fail-closed
│                        #   (unchanged playbook on any fault)
├── pricing.py           # issue-760 pricing face — the unknown-set
│                        #   projection (undecided PQs + open obstacles,
│                        #   pure view over existing keys) + the
│                        #   information-gain price (bits x value, decayed
│                        #   by the issue-800 dispatch-ledger repeat
│                        #   count) + probe-price/1 telemetry emit +
│                        #   the issue-801 consumption account face
└── README.md            # this document
```

One import point: `import rlvr` (scripts/ is on pythonpath for tests,
tools, and hooks alike). `rlvr/__init__.py` carries the ONE export map —
a single `__all__` plus explicit submodule re-exports — so the public
surface is enumerable in one file and drift against it is a test
failure, not folklore.

### posteriors — DTS store (Discounted Thompson Sampling; landed W2-T1, issue 428)

| face | home |
|---|---|
| `SCHEMA`, `STORE_REL`, `LOCK_REL`, `row_schema_lint()` | `rlvr.posteriors` (append-only store, ledger-isomorphic with rollout_ledger) |
| `record()`, `read()` | `rlvr.posteriors` (loud-result writes; schema-enforced fail-open reads) |
| `fold()`, `PosteriorView` | `rlvr.posteriors` (THE γ decay face — replay `(α,β) ← γ·(α,β)+obs` in input order; raw counts never rewritten) |
| `gamma_constant()`, `OutcomeAdaptiveGamma`, `default_schedule()` | `rlvr.posteriors` (declared schedules; defaults = EX-2-calibrated constants) |
| `GAMMA_FLOOR_DEFAULT`, `ADAPTIVE_EMA_LAMBDA_DEFAULT`, `PRIOR_ALPHA/BETA_DEFAULT` | `rlvr.posteriors` (measured in experiments/ex2-gamma-calibration.md) |

## Face map: final home of every current public face

Phase 2 moves implementation bodies here; the top-level scripts stay as
**thin adapters** (explicit re-export shims, no logic) so every existing
importer — `hooks/` inserts scripts/ on sys.path; scripts consume
siblings by bare import; tests import by module name — keeps working
unchanged. No import cycles: the dependency direction inside the package
is `liveness` ← (nothing), `ledger` ← `reward`/`scalar`, `state` ←
`triples`, everything ← `kunglao_log`/`harness_common` (never the
reverse). `kunglao_log` stays never-raises and outside the package.

### ledger — from `scripts/rollout_ledger.py`

| current face | final home |
|---|---|
| `SCHEMA`, `LEDGER_REL`, `LOCK_REL` | `rlvr.ledger` (re-exported) |
| `KIND_TASK`, `KIND_SELF_DISTILL`, `KIND_HYBRID_DISTILL`, `ROLLOUT_KINDS` | `rlvr.ledger` |
| `REWARD_RAIL_BOUNDED`, `REWARD_RAIL_PROVENANCE`, `REWARD_RANGE_BOUNDED`, `KIND_REWARD_RAILS`, `reward_rail_of()`, `reward_range_of()` | `rlvr.ledger` (the issue-1007 per-kind reward-unit declaration) |
| `register_kind()`, `kinds()` | `rlvr.ledger` (the open-enum API; `register_kind(kind, note, rail)` records the unit) |
| `read()`, `fold()`, `settled()` | `rlvr.ledger` — `settled` stays THE one prior/settlement read interface (U4) |
| `pending_settlement()`, `record()`, `settle()` | `rlvr.ledger` |
| `row_schema_lint()`, `warn()` | `rlvr.ledger` (warn stays module-local rate-limited stderr) |

### reward — from `scripts/reward_settlement.py`

| current face | final home |
|---|---|
| `RULES_REL`, `RULES_SCHEMA`, `BANDS`, `POLARITY_ALPHA_BANDS`, `POLARITY_BETA_BANDS` | `rlvr.reward` |
| `load_rules()`, `repo_rules_path()` | `rlvr.reward` |
| `classify()` (signals → settlement document) | `rlvr.reward` |
| `settle_workspace()` | `rlvr.reward` |
| `polarity_of()`, `prior_observations()` | `rlvr.reward` (the U4 prior feed) |
| `bounded_reward_rows()`, `bounded_prior_observations()` | `rlvr.reward` (the issue-1007 `[0,1]`-only read face: provenance rows excluded + reported, never read as rewards) |
| `task_signals()`, `self_distill_signals()`, `emit_unified_rows()`, `rollup_face()` | `rlvr.reward` (adapter faces over machine surfaces only) |
| `snapshot_lessons()`, `resolve_library()` | `rlvr.reward` |

### scalar — from `scripts/scalar_settlement.py`

| current face | final home |
|---|---|
| `TIER_*`, `MEASURED_TIERS`, `NG_MU0/KAPPA0/A0/B0`, `OUTPUT_RAILS` | `rlvr.scalar` (documented policy constants) |
| `outcome_dim()`, `difficulty_dim()`, `evidence_dim()`, `cost_dim()`, `_probe_progress()`, `extract_dimensions()` | `rlvr.scalar` |
| `classify_tier()` | `rlvr.scalar` (the tier engine) |
| `extract_tuple()` — the `experience_tuple` birth certificate | `rlvr.scalar` (the tuple is a settlement-DOCUMENT field; the read face is `tuples()`) |
| `settle_workspace_scalars()` | `rlvr.scalar` |
| `tuples()` | `rlvr.scalar` (the tuple-store read view) |
| `round_credit()`, `settle_round_credit()` | `rlvr.scalar` |
| `scalar_observations()` | `rlvr.scalar` (the Normal-Gamma observation feed) |
| `normal_gamma_update()`, `merge_normal_gamma_posts()`, `_ng_from_stats()` | `rlvr.scalar` (THE Normal-Gamma math; numpy-backed per the pattern below) |
| `fact_artifacts()` | `rlvr.scalar` |
| `question_claims()` — the issue-433 citation chokepoint's claim-provenance half | `rlvr.scalar` |
| `clamp_credit()`, `rail_of()`, `resolve_citations()`, `oracle_lock()`, `validate_verdict_doc()`, `resolvable_registry()`, `apply_trajectory_settlement()` | `rlvr.scalar` (settlement v3 validator) |
| `KIND_ROUND_CREDIT`, `BAND_ROUND_CREDIT`, `RULE_*`, `TRACE_CANONICAL`, `FAIL_CREDIT_CAP`, `ORACLE_PASS_LOCK`, `ROUND_CREDIT_FULL`, `DEMOTION_*` (the issue-433 value ladder) | `rlvr.scalar` |

### priors — from `scripts/compute_priors.py`

| current face | final home |
|---|---|
| `RESULT_SCHEMA`, `BASE_ALPHA`, `BASE_BETA` | `rlvr.priors` |
| `compute_priors()` | `rlvr.priors` (pure; reads named workspaces, writes nothing) |
| `_case_bank_obs()`, `_posteriors_obs()`, `_rollout_ledger_obs()`, `_scalar_ledger_obs()` | `rlvr.priors` (private per-source folds) |

### triples — from `scripts/experience_triples.py`

| current face | final home |
|---|---|
| `TRIPLES_REL`, `CSV_HEADER`, `Q_REPORT_SCHEMA` | `rlvr.triples` |
| `extract()` | `rlvr.triples` (regenerates runs/triples.csv; never re-scores) |
| `read_csv()` | `rlvr.triples` |
| `q_report()` | `rlvr.triples` (read-only Q estimator arithmetic) |

### winrate — from `scripts/winrate_curve.py` (read-side aggregation)

| current face | final home |
|---|---|
| `SCHEMA`, `DEFAULT_WINDOW` | `rlvr.winrate` |
| `face()`, `scored_stream()`, `claim_pq_map()`, `family_of()`, `case_bank_summary()`, `oracle_summary()` | `rlvr.winrate` |
| `_cumulative()`, `_windowed()`, `_rate()` | `rlvr.winrate` (numpy-backed per the pattern below) |
| `summarize()` | `rlvr.winrate` |
| `render_html()`, `main()` | stay with the script adapter (CLI + template rendering are not package surface) |

### state — from `scripts/state_signature.py`

| current face | final home |
|---|---|
| `SCHEMA`, `TERMINAL_FACT_STATUSES`, `FACT_BUCKET_EDGES`, `BUDGET_BUCKET_EDGES`, `W_CHAIN/W_FACTS/W_BUDGET/W_SIDES` | `rlvr.state` |
| `snapshot()`, `signature_str()`, `signature_hash()` | `rlvr.state` (the Q-table key faces; state-sig/2 carries the ob= attribution segment, issue 461 Phase 1) |
| `v_anchor()`, `v_from_workspace()` | `rlvr.state` (deterministic V(s); the empirical correction stays the documented v0.2 seam; obstacles carry NO V term — attribution is evidence, not progress) |
| `append_snapshot()`, `read_situations()` | `rlvr.state` (the situation snapshot stream) |
| `fact_face()`, `fact_bucket()`, `claim_pattern()`, `budget_fraction()`, `budget_bucket()`, `chain_progress()`, `phase()` | `rlvr.state` |
| `obstacle_face()` | `rlvr.state` (lazy delegation to the obstacles face below) |

### obstacles — the issue-461 attribution registry (Phase 1)

| face | home |
|---|---|
| `SCHEMA`, `KINDS`, `OBSTACLES_REL`, `CAUSE_MAX` | `rlvr.obstacles` (obstacle/1 over runs/obstacles/OBS-<n>.json — runs/, not evidence/: the evidence-index pipeline sweeps evidence/ as raw evidence and an obstacle row is a derivation from its probe artifact) |
| `validate_obstacle()` | `rlvr.obstacles` (structural + artifact-existence + probe-marker shape; pure) |
| `record()` | `rlvr.obstacles` (loud-result fail-open; exclusive-create mint; CLI `record` subcommand) |
| `read()`, `face()` | `rlvr.obstacles` (tolerant parsed-n-sorted read; {present, count, kinds} digest consumed by `rlvr.state.obstacle_face`) |
| `main()` | `rlvr.obstacles` (CLI face — the worker protocol's sanctioned producer; shares the library validation path) |

Recording-only: no dispatch/gate/settlement face imports this module
(the 396 freeze wall, extended with full-module-string checks); no
gate reads the registry — attribution is evidence, never a verdict,
never an obstacle claim.

### termination — the issue-461 option-death estimator (Phase 2)

| face | home |
|------|------|
| `SCHEMA`, `DEATH_THRESHOLD`, `ARM_FLOOR`, `PRIOR_ALPHA/BETA` | `rlvr.termination` (option-death/1 report; policy constants — mean rule 0.75, floor 0.1; ADR-001 posture, never runtime-tuned) |
| `report(ws, snap=None)` | `rlvr.termination` (the deterministic cell-level receipt: deaths/alpha/beta/p_dead/dead per (kind, family) sorted, per-family alive mass, post-replay gamma; no wall clock; fail-open reads) |
| `verdicts(ws, families, snap=None)` | `rlvr.termination` (the sampler-threading face: state-conditioned per-family verdicts; ZERO-REGISTRY RULE — no obstacle rows = {} so hosts thread no kwarg; base cell Beta(1, 1+alive) never dead) |
| `option_dead(ws, family, snap=None)` | `rlvr.termination` (the single-family decision face — always answers; kind-conditioning is the foreign-snapshot guard, the live floor is family-global) |
| `main()` | `rlvr.termination` (CLI `report` subcommand — offline diagnostic; live faces are library calls consumed by the sampler hosts) |
| `_death_multiplier()` | `rlvr.q_cells` (the sampler-side duck-typed verdict application: weight x multiplier, additive receipt block, malformed -> 1.0 fail-open; the sampler never imports the termination/obstacles faces — the import wall) |

### l1_value + l1_planner — the L1 layer (the orchestration learner)

| face | home |
|------|------|
| `compute_rollout_return()`, `ROLLOUT_GAMMA` | `rlvr.l1_value` (the return: `R(τ) = Σ γ^t·r_t` — the discounted SUM, terminal-dominated; γ=1.0 shipped, the exact telescope; never the mean) |
| `record_terminal_return()`, `record_observation()` | `rlvr.l1_value` (the `l1-value-obs/1` append face; called from `scalar.settle_round_credit`'s first-settlement tick; no dispatch-time signature -> no row, ONE warn) |
| `fold()`, `ValueFold`, `ValueCounts`, `cell_posterior()`, `sample_value()`, `seed_state()` | `rlvr.l1_value` (the (state_signature, action_kind) Beta cells + the q_cells DTS machinery mirrored; the #428 adaptive schedule imported; `seed_state` = f(store, round)) |
| `value_table()`, `main()` | `rlvr.l1_value` (CLI `--table` — the offline cell table; the live faces are library calls) |
| `candidate()`, `Candidate`, `plan()`, `plan_for_claim()` | `rlvr.l1_planner` (the policy: one DTS draw per candidate, argmax value/cost — park is the 0-ratio baseline; reuse joins on solved knowledge; no trigger rules exist) |
| `knowledge_query()` | `rlvr.l1_planner` (register / facts index / cross-task store, each fail-open; `answer_strength` = the answer faces only — lifecycle is not an answer) |
| `advisory_factors()` | `rlvr.l1_planner` (the rank path's additive consumption: {} while the value store is empty — byte identity — else the dispatch share per claim) |
| `ACTION_KINDS`, `VALUE_SCALE`, `REUSE_COST`, `PARK_COST` | `rlvr.l1_planner` / `rlvr.l1_value` (the closed action vocabulary + documented policy constants — never runtime-tuned) |

### liveness — from `scripts/heartbeat.py` (continuity core) + `scripts/liveness_policy.py` (constants)

| current face | final home |
|---|---|
| `evaluate_tick_continuity()` | `rlvr.liveness` (THE shared verdict; gate / check / verify keep consuming the same function) |
| `append_tick()`, `TICK_HISTORY_KEY`, `TICK_HISTORY_CAP` | `rlvr.liveness` |
| `gap_alarm()`, `newest_sidecar_ts()`, `append_tick_log()`, `heartbeat_log_path()` | `rlvr.liveness` (the #830 durable sidecar faces) |
| `heartbeat_register()`, `heartbeat_check()`, `heartbeat_off()`, `mark_loop_registered()` | stay CLI faces of the heartbeat script adapter; the package provides the judgment core they call |
| `liveness_policy.*` constants (`STALE_MINUTES`, `CONTINUITY_WINDOW_*`, `TICK_INTERVAL_DEFAULT_MIN`, ...) | `scripts/liveness_policy.py` stays THE constant source (the #597 adjudication); `rlvr.liveness` re-exports, never redefines |


## Reward units (issue 1007): `round_credit` is a provenance sum, not a [0,1] reward

The `rollout-ledger/1` schema carries **two reward units**, declared per
row kind (`rlvr.ledger.KIND_REWARD_RAILS` is the machine face; the
contract page is `references/contracts/reward-rules.yaml` → `reward_units`):

| unit | kinds | field | range |
|---|---|---|---|
| `bounded` | `task`, `self_distill`, `hybrid_distill`, `hypothesis` | `reward` | `[0,1]` |
| `provenance` | `round_credit` | `credit_units` | unbounded (credit units) |
| `signed` | `mainline_decision`, `method_memory`, `strategy_memory` | `reward` | unbounded (signed ΔV / attributed reward) |

- **Bounded** rows are settlement scalars (v1 bands, v2 tier scalars, the
  v4 hypothesis sign indicator). The `[0,1]` rail is enforced by
  `scalar.clamp_credit` / `rail_of` on the settlement path and by
  `ledger.row_schema_lint` at the write and read boundaries (a bounded
  settlement outside the rail is refused at `ledger.settle`, never
  written-then-hidden).
- **Provenance** rows are the per-dispatch round credit:
  `r_i = (full-credit cited artifacts) × 1.0 + (one trace total per
  demotion class present) × 0.01 − attributed waste`. The observed
  `2.01` is exactly `2 × 1.0` (two credited artifacts) `+ 1 × 0.01` (one
  demotion class) `− 0` waste — a formula result in credit units, not a
  rail violation. The value is deliberately **not clamped** (clamping
  would erase the difference between citing one and two artifacts). New
  settlements carry `reward_rail: provenance` + `credit_units`; the kind
  declaration is authoritative, so legacy rows without the markers read
  correctly too.
- **Signed** rows are pre-existing attribution carriers: the
  `mainline_decision` situation-stream replay settles a signed ΔV, and
  the review-bridge `method_memory` / `strategy_memory` rows carry signed
  step / mission rewards. Neither a `[0,1]` scalar nor a credit sum; they
  are declared here so every registered kind has a unit and the bounded
  consumer excludes them too.

**The consumer rule.** Any consumer that expects `[0,1]` must call
`rlvr.ledger.reward_rail_of(row)` and exclude every non-bounded row
(provenance and signed) explicitly, reporting the exclusion. The prior
feed is the first such consumer:

```python
from rlvr import reward

split = reward.bounded_reward_rows(ws)
#   split["rows"]     -> bounded-rail settled rows only
#   split["excluded"] -> [{"rollout_id", "kind", "rail", "reward"}, ...]
doc = reward.bounded_prior_observations(ws)   # {alpha, beta, excluded}
```

`reward.prior_observations` now counts only bounded-rail rows, and
`compute_priors` reports every excluded row under
`sources.rollout_ledger.excluded` (additive-when-present: the key appears
only when a provenance row exists). A `2.01` is named, never silently
read as a reward. `scalar.scalar_observations` already filters
`kind=task` explicitly.

Two more converted faces:

- `rlvr.strategy_store.PosteriorStrategyStore` — the γ-ladder EMA reads
  only bounded-rail rows; non-bounded rows are excluded and named by
  `decayed_exclusions()` (`{rollout_id, kind, rail, reward}`), never
  clamped into a maximum outcome.
- `scripts/decision_view.py` `just_settled` — the display face carries
  `reward_rail` next to `reward`, so a `2.01` is labelled `provenance`.

## The compact index (modules the face map above doesn't cover)

The face map above covers the consolidation wave's homes. Every other
module carries its full contract in its own docstring — this index is
the one-line pointer (name — the docstring's opening line):

- `authorization` — rlvr/authorization.py — the engagement authorization scope:
  `task_spec.authorization` (exact `targets` / `excluded` / `authorization_ref`)
  copied into the dispatch envelope; `authorized_target()` is the ONE scope
  decision (no globs, fail closed on an absent/malformed block), and the
  classifier's OUT_OF_SCOPE gate reads it.
- `censored_review` — rlvr/censored_review.py — the censored-outcome fairness review
- `consolidated_ledger` — rlvr/consolidated_ledger.py — the 4-file ledger consolidation core (#721).
- `distill_dgate` — rlvr/distill_dgate.py — the D-gate three-question note lint (issue #365).
- `distill_rollout` — rlvr/distill_rollout.py — the distill-rollout/1 settlement rows + reward bands + strategy priors (issue #365).
- `distill_score` — rlvr/distill_score.py — the 0-1 scoring face + the scored playbook view (issue #365).
- `episode_pool` — rlvr/episode_pool.py — the memory pool's physical layer (`runs/episodes/`) + the three policy gates (issue #824).
- `episode_schema` — rlvr/episode_schema.py — the episode schema `episode/1` + summary caps + fail-closed validator (issue #824).
- `pool_indexer` — rlvr/pool_indexer.py — the pool's derived views: value table + playbook (issue #824).
- `constants_ref` — rlvr.constants_ref — the reference hash constant tables (entropy
- `crystallize` — crystallize.py — the settlement writes knowledge back.
- `expansion` — rlvr/expansion.py — the discovery-layer operator (issue #546, WS4 /
- `hypotheses` — rlvr.hypotheses — layer-scoped hypotheses + counterexample refinement
- `incremental_reward` — rlvr/incremental_reward.py — potential-based per-act reward + the
- `invariants` — rlvr.invariants — the invariant-pruning operator (entropy reduction).
- `interruption` — rlvr/interruption.py — the interruption classifier (#955 link 1):
  terminal / censored_env / agent_death, mechanical over session returncode +
  timed_out + active env-class blocker files + liveness at exit; agent-death
  prose stays owned by the #447/#497 Type E gate.
- `censoring` — rlvr/censoring.py — censored posterior semantics (#955 links 4/5):
  censored rows update NOTHING, per-direction trailing censor streaks, the
  freeze-at-K predicate, and the #954 integration seam
  (posterior_observations filter over runs/direction-state.jsonl).
- `direction` — rlvr/direction.py — the oracle-probe density direction face (#954,
  Type-3): Beta posterior per direction over the shared direction-state rows,
  step credit = probe_face.probe_delta (the ΔV seam), racing elimination gated
  on posterior collapse (zero failure evidence never eliminates), flag-gated
  KUNGLAO_DIRECTION=1 loop faces (default OFF).
- `disposition` — rlvr/disposition.py — the episode disposition algebra (#988):
  one evidence-gated disposition per episode (SOLVED / OUT_OF_SCOPE /
  CENSORED_ENV / ATTEMPTED_EXHAUSTED / INFRA / FAILED / SURRENDER) under a
  total precedence, plus the published legacy session-ladder map; the
  `disposition/1` row (`build_row` / `validate_row` / `write_row`) lands one
  JSON object per episode under `runs/disposition/`, mirrors it into the
  unified TELEMETRY ledger, and emits the registered
  `disposition_recorded` event. Re-writing the identical row is idempotent;
  a divergent rewrite is refused.
- `disposition_reward` — rlvr/disposition_reward.py — the disposition reward
  face (#986): classification evidence normalization (an authorized refusal is
  SURRENDER, out-of-scope is OUT_OF_SCOPE, CENSORED_ENV needs BOTH session-bound
  and corroborated wall legs, a timeout is FAILED), the consumer mapping
  (`reward_for`: SOLVED oracle lock; SURRENDER 0.0 inside [0,1] with a
  strategic-action failure outcome, TRACE floor with reproducible evidence;
  ATTEMPTED_EXHAUSTED capability gap; CENSORED_ENV excluded from strategy
  learning; OUT_OF_SCOPE / INFRA / FAILED reported separately), and the bounded
  `disposition-signal/1` choice signal (`settle_disposition` /
  `settle_workspace`) through the unified TELEMETRY ledger plus the registered
  `disposition_signal` event. `rlvr.episode_settle.settle_mission` is the
  mission-terminal call site.
- `disposition_measure` — rlvr/disposition_measure.py — the read-only
  measurement face over the disposition rows + telemetry mirror: the declared
  denominator table (capability = SOLVED + SURRENDER, censoring rate over all
  valid rows, exhausted -> `capability-gap/1` carrying the route-ledger ref,
  OUT_OF_SCOPE / INFRA / FAILED reported separately), strategy-learning
  inputs excluding CENSORED_ENV, process metrics (steps / cost / dead-end
  rate / route-pruning quality) joined per run and per arm only where the
  sources exist (explicit None + coverage otherwise), and `learning_claim`
  refusing single-episode verdicts in favour of pre/post or ablation deltas
  with uncertainty.
- `disposition_producer` — rlvr/disposition_producer.py — THE runtime writer
  the algebra shipped without (#988): one evidence-gated row per TERMINAL
  claim at the mission boundary, assembled from faces the workspace already
  carries (authorization block, the canonical verification surface resolved
  through verifier_integrity — the trust mirror is excluded by its own marker
  and a PROVEN status without a resolved PASS is completion_claimed/FAILED —
  the interruption wall, the route ledger, the claim's transitions, the
  strategic-action row). A missing authorization block or an ambiguous
  multi-target scope writes NO rows and warns once; the ts is derived
  (settlement stamp, else latest transition) so a re-settle rebuilds the
  identical row. `rlvr.episode_settle.settle_mission` calls it before the
  choice-signal face.
- `parking` — rlvr/parking.py — the PARKED claim state + the minimal escrow stub
  (#955 link 3, escrow_design: #667): provisional mass -> runs/parked-mass.jsonl,
  register status via the ws_yaml single-writer seam, park/unpark round trip.
- `marl` — marl.py — the MARL knowledge-transfer protocol (#705).
- `meta_arms` — meta_arms.py — the #524 P0 learning structure: 12 families -> 3 meta-arms,
- `phi_tree` — rlvr/phi_tree.py — the Φ-tree economy (#796): decisive mass on the
  closure hypothesis tree (tree_phi/settle_resolution/clawback/elimination_credit/
  reconcile_claim; signed negative face; #760-complementary, #799-sealed).
- `policy_compare` — rlvr/policy_compare.py — the offline policy comparison (issue #539 PR-2).
- `prediction_ledger` — rlvr/prediction_ledger.py — the prediction ledger.
- `reward_signal` — rlvr/reward_signal.py — the A1 learning signal `R = completion + milestone progress − cost` + the settlement hook (issue #824).
- `rollout_timer` — rlvr/rollout_timer.py — the per-rollout learned deadline
  timer: `arm` computes `budget = clamp(base x coeff, 15m, 480m)` from the
  comparable-family median and ONE global coefficient, persists a
  `rollout-timer/1` row and returns the one-shot wake contract (cron derived
  from the deadline, off :00/:30, plus the graceful wrap-up prompt); `cancel`
  retires an early finish and a canceled timer never fires; `fire` records the
  deadline and returns the graceful-stop contract; `learn` moves the bounded
  coefficient table (early x0.9, timeout x1.25, on time x0.98, infra/aborted
  no update, coeff clamp [0.5, 4.0]) and audits every decision as a
  `rollout-budget/1` row. One global coefficient; the bucket key is recorded
  but a split waits for n>=5. A deadline stop carries `stop_reason: deadline`
  and is excluded from strategic learning without adding a disposition.
- `route_ledger` — rlvr/route_ledger.py — the route-attempt ledger (#988):
  `runs/rt-tests/<claim>/routes.json` with the per-claim-kind `routes:`
  declaration from `references/schemas/machine_check_map.yaml`, per-attempt
  machine command + content-addressed artifact (sha256 re-derived by the
  validator), the fixed `ROUTE_ATTEMPT_BUDGET` policy constant, and the
  classifier-facing `routes`/`attempted`/`budget`/`budget_exhausted` record;
  a missing, malformed or non-reproducible ledger can never claim
  ATTEMPTED_EXHAUSTED.
- `recipe_arms` — recipe_arms.py — issue #695: tool-chain recipe arms (the learned
- `refutation_fold` — rlvr/refutation_fold.py — the refutation fold (deterministic).
- `settlement_scorer` — rlvr/settlement_scorer.py — the BLIND settlement entry (issue-687).
- `source_reliability` — rlvr/source_reliability.py — the learned source-reliability Betas.
- `step_credit` — rlvr/step_credit.py — step-level ladder credit (#712): dense reward
- `step_grain` — rlvr/step_grain.py — the settlement grain (#690): step := one
- `step_ledger` — rlvr/step_ledger.py — the shadow experience substrate (the online
- `stopping` — rlvr/stopping.py — the externally checkable stop checker (#988):
  `may_terminate(record)` is pure and True only for route-ledger exhaustion,
  a corroborated session-bound wall, or a spent declared budget; stagnation /
  early-failure-prediction / effort surrogates never terminate. The
  loop-facing call site (`e2e/checkpoints._tick_prelude`) refuses the idle
  circuit breaker unless the checker passes (refusal recorded as
  `stop_refused`).
- `strategic_action` — rlvr/strategic_action.py — the recorded route choice
  (#988): one `strategic-action/1` row per episode (FIGHT/BYPASS/INVEST
  derived from the action_space STRATEGIC registry) carrying its propensity,
  written through the unified experience ledger + the
  `strategic_action_recorded` event; an absent action reads as SURRENDER.
  The same module owns the dispatch-DECLARATION face (issue-1005 S5): the
  dispatch gate's ALLOW tail appends one declaration row per dispatch —
  `{claim, route, propensity, declared, trace_id, ts}`, a declared route
  or the explicit gap (`declared: false`, `route: null`) — APPEND history,
  last row is the live face; `absence_disposition` maps the gap toward
  SURRENDER through the disposition algebra's own vocabulary, and
  `disposition_fields` speaks both faces of the stamp.
- `strategy_store` — strategy_store.py — the REAL compose store adapter (kernel W2-T4 seam,
- `verification_debt` — rlvr/verification_debt.py — the verification-debt face (deterministic).

New modules: add the file, add the `from . import` line in
`__init__.py` (the facade test enforces it), add one row here.

## The determinism wall (settlement settlement receipts)

The settlement determinism axiom is preserved verbatim: float sums run
in input order; a settled receipt must reproduce bit-exactly. The pins
in `tests/test_rlvr_bitexact.py` ARE the wall:

- **Beta prior means** over a synthetic multi-source workspace
  (case bank + posterior ledger + settled rollout rows + tier scalars),
  including the aggregate `alpha`/`beta`/`mean` and the per-source
  decomposition.
- **Normal-Gamma pooled parameters** from the exact-recovery pattern
  (`merge_normal_gamma_posts([p1, p2, p3])` vs
  `normal_gamma_update(all_observations)` pinned independently — the
  two differ by 1 ulp today and must keep differing by exactly that
  same structure, i.e. reproduce bit-exactly).
- **A settled reward receipt** (band, rule_id, reward, evidence_refs)
  plus a settled tier receipt (tier scalar).
- **Continuity window verdicts** — `(alive, detail)` pairs for the
  healthy, stalled, stale, and single-tick histories.

Pins are written against the CURRENT hand-rolled implementations and
pass on them; the numpy migration must reproduce them bit-exact or the
pin fails. A pin failure is a **STOP**, never a tolerance tweak; a new
sealed segment requires an owner ruling (issue #420 constraint section).

Encoding: every pinned float is stored as `float.hex()` — exact,
repr-stable, and interpreter-independent.

## NumPy policy (the pattern the two adoptions set)

numpy enters the RLVR surface under four rules (no scipy: every
distribution value on this surface is closed-form — Beta means are
`alpha/(alpha+beta)`, the Normal-Gamma posterior is the conjugate
update; DTS Beta sampling stays stdlib `betavariate`):

1. **Ordered float reductions go through `_seq_sum`** —
   `np.add.accumulate` over a float64 array with an explicit `0.0`
   seed: strictly left-to-right IEEE-754 double addition, bit-identical
   to the hand-rolled in-order sum and, unlike builtin `sum()`, stable
   across interpreters (builtin `sum()` switched floats to Neumaier
   compensation in 3.12; the pinned surface must not depend on that
   switch). `np.sum`/`np.add.reduce` are FORBIDDEN on the settlement
   path: pairwise summation changes bits.
2. **Elementwise ops preserve the pinned semantics** — where a pin
   rides on libm `pow(x, 2)` rounding (`** 2` on scalars/arrays), the
   code keeps the Python `** 2` form; `np.square`/`x*x` is an IEEE
   multiply (platform-independent but 1-ulp different from libm pow on
   some inputs). Integer aggregation (counts, cumsum) may vectorize
   freely — integers are exact.
3. **No numpy floats escape a module boundary** — every value crossing
   a receipt/JSON/ledger boundary is converted with `float()`/`int()`
   (json cannot serialize np.float64; a leaked numpy scalar is a bug).
4. **numpy is a hard dependency** (`pyproject.toml`, uv-locked);
   import at module top — no guarded degrade path, because the pins
   have no degrade path.

## Direct-execution bootstrap (the repeated `__package__` block)

Face modules that can be run as a file (`python scripts/rlvr/<m>.py`)
carry, BEFORE their sibling imports, the same three-line prologue:

```python
if __package__ in (None, ""):
    # direct-path execution: the package parent (scripts/) is NOT on
    # sys.path (path[0] is scripts/rlvr/) — insert it before the sibling
    # imports (the q_cells direct-execution pattern)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

Why it cannot move into `_common`: the block must run while `scripts/`
is still unreachable from `sys.path` — importing the leaf to learn the
path is the very problem it solves. It is therefore a DOCUMENTED,
per-file pattern, not a consolidated helper: the `code` line is
identical in every carrier (expansion, obstacles, policy_compare,
censored_review, termination, q_cells); only the explanatory comment
varies. Every face module that grows a direct CLI face copies the guard
ahead of the first sibling import. Under pytest and under `import rlvr`
the block is inert (`__package__` is `"rlvr"`), and `scripts/` arrives
on `sys.path` by the harness instead.

## Phase 2 execution notes (recorded now, executed after the gate)

- Move bodies per the face map; leave explicit re-export shims at
  `scripts/rollout_ledger.py`, `reward_settlement.py`,
  `scalar_settlement.py`, `compute_priors.py`, `experience_triples.py`,
  `state_signature.py`, and the continuity core in `heartbeat.py`.
  Importers (rollup, gap_notes, eval_loop_runner, statusline_snapshot,
  compute_priors' source folds, kunglao_resume/monitor, hooks/
  worker_budget_*) are updated only where it costs nothing — the shim
  is the compat surface, the package is the truth.
- `tests/test_scalar_settlement_379.py` import allowlist gains `numpy`
  (deliberate, reviewed — the U3 wall is "no model-call path", and
  numpy is not one).
- Deploy manifest regen after the script set changes (rlvr/__init__.py
  + package modules join the tree).
- Hand-rolled math moves: Beta loops (aggregate priors), Normal-Gamma
  pooling, winrate window/cumulative aggregation, Q-report per-cell
  means — each landing green against `tests/test_rlvr_bitexact.py`.
- The D1 TF-IDF/k-means clustering named in issue #420 has no home in
  v0.1.6's surface; it joins the package only if/when its face lands.
