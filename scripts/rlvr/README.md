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
├── reward.py            # reward_settlement (U2/U3) — band/reward engine
├── scalar.py            # scalar_settlement — tiers, tuples, Normal-Gamma,
│                        #   round credit, trajectory validator
├── priors.py            # compute_priors (U4 feed consumer) — aggregate prior
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
| `register_kind()`, `kinds()` | `rlvr.ledger` (the open-enum API) |
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

### liveness — from `scripts/heartbeat.py` (continuity core) + `scripts/liveness_policy.py` (constants)

| current face | final home |
|---|---|
| `evaluate_tick_continuity()` | `rlvr.liveness` (THE shared verdict; gate / check / verify keep consuming the same function) |
| `append_tick()`, `TICK_HISTORY_KEY`, `TICK_HISTORY_CAP` | `rlvr.liveness` |
| `gap_alarm()`, `newest_sidecar_ts()`, `append_tick_log()`, `heartbeat_log_path()` | `rlvr.liveness` (the #830 durable sidecar faces) |
| `heartbeat_register()`, `heartbeat_check()`, `heartbeat_off()`, `mark_loop_registered()` | stay CLI faces of the heartbeat script adapter; the package provides the judgment core they call |
| `liveness_policy.*` constants (`STALE_MINUTES`, `CONTINUITY_WINDOW_*`, `TICK_INTERVAL_DEFAULT_MIN`, ...) | `scripts/liveness_policy.py` stays THE constant source (the #597 adjudication); `rlvr.liveness` re-exports, never redefines |

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
