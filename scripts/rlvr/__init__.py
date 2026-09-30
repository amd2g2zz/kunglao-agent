# -*- coding: utf-8 -*-
"""rlvr — the unified RLVR package surface (issue 420).

THE one import point: ``import rlvr`` (scripts/ is on pythonpath for
tests, tools, and hooks alike). This ``__init__`` carries the ONE export
map — a single ``__all__`` plus explicit submodule re-exports — so the
public surface is enumerable in one file and drift against it is a test
failure, not folklore. Design: ``scripts/rlvr/README.md``.

Modules (issue #420 Phase 2 — the consolidation wave LANDED; the
top-level scripts are now thin re-export adapters, per the README face
map):

- ``rlvr.ledger`` — THE unified rollout ledger (U1): append-only
  ``runs/rollout-ledger.jsonl``, fold/settle/settled faces, the kinds
  open enum. Body moved from scripts/rollout_ledger.py.

- ``rlvr.reward`` — the ONE deterministic settlement engine (U2/U3):
  signals -> band -> reward under the versioned rules table, the prior
  feed polarity face. Body moved from scripts/reward_settlement.py.

- ``rlvr.scalar`` — two-level settlement: the tier engine, round
  credit, the Normal-Gamma observation feed, the settlement v3
  validator. Body moved from scripts/scalar_settlement.py.

- ``rlvr.priors`` — the on-demand cross-workspace aggregate Beta prior
  (issue 137, U4 consumer). Body moved from scripts/compute_priors.py.

- ``rlvr.state`` — the canonical state signature + deterministic V(s)
  anchor (issue 396 recording face). Body moved from
  scripts/state_signature.py.

- ``rlvr.triples`` — the (s, a, r) extraction view + read-only Q
  report. Body moved from scripts/experience_triples.py.

- ``rlvr.winrate`` — the #156 win-rate read-side aggregation. Body
  moved from scripts/winrate_curve.py (CLI + HTML rendering stay with
  the script adapter).

- ``rlvr.liveness`` — the heartbeat continuity core (THE shared
  #754 verdict + the #830 durable sidecar faces). Body moved from
  scripts/heartbeat.py (CLI faces stay with the script adapter).

- ``rlvr.posteriors`` — the DTS posterior store (Discounted Thompson
  Sampling, issue 428, v0.1.6 W2-T1): append-only
  ``runs/posterior-store.jsonl``, fold/read face applying the γ decay,
  pseudo-count priors, outcome-adaptive schedule with EX-2-calibrated
  defaults.

- ``rlvr.q_cells`` — the Q cell registry keyed ``(signature_hash,
  method_family)`` with hierarchy shrinkage toward the global anchor
  (issue 429 section 4, W2-T2).

- ``rlvr.compose`` — the strategy compose single-point (issue 431,
  W2-T3): the learned state as words the LLM sees, one round-strategy
  object per decision event + the fading card library.

- ``rlvr.obstacles`` — the obstacle/1 attribution registry (issue 461
  Phase 1): intervention-born failure-cause objects as
  ``runs/obstacles/OBS-<n>.json`` evidence files, read tolerantly into
  the canonical state signature's ob= segment (attribution enters as
  state — never a verdict, never a gate).
"""
from __future__ import annotations

from . import compose
from . import ledger
from . import liveness
from . import obstacles
from . import posteriors
from . import priors
from . import q_cells
from . import reward
from . import scalar
from . import state
from . import triples
from . import winrate
from .ledger import (
    KIND_HYBRID_DISTILL,
    KIND_SELF_DISTILL,
    KIND_TASK,
    LEDGER_REL,
    LOCK_REL,
    ROLLOUT_KINDS,
    SCHEMA as LEDGER_SCHEMA,
    fold as fold_rollout,
    kinds as rollout_kinds,
    pending_settlement,
    read as read_rollouts,
    record as record_rollout,
    register_kind as register_rollout_kind,
    row_schema_lint as ledger_row_schema_lint,
    settle as settle_rollout,
    settled as settled_rollouts,
)
from .reward import (
    BANDS as REWARD_BANDS,
    POLARITY_ALPHA_BANDS,
    POLARITY_BETA_BANDS,
    RULES_SCHEMA,
    classify as classify_signals,
    load_rules,
    polarity_of,
    prior_observations,
    settle_workspace as settle_workspace_rewards,
)
from .scalar import (
    MEASURED_TIERS,
    OUTPUT_RAILS,
    classify_tier,
    extract_tuple,
    merge_normal_gamma_posts,
    normal_gamma_update,
    round_credit,
    scalar_observations,
    settle_round_credit,
    settle_workspace_scalars,
    tuples as experience_tuples,
)
from .priors import (
    BASE_ALPHA as PRIOR_BASE_ALPHA,
    BASE_BETA as PRIOR_BASE_BETA,
    RESULT_SCHEMA as PRIOR_RESULT_SCHEMA,
    compute_priors,
)
from .state import (
    BUDGET_BUCKET_EDGES,
    FACT_BUCKET_EDGES,
    SCHEMA as STATE_SCHEMA,
    TERMINAL_FACT_STATUSES,
    W_BUDGET,
    W_CHAIN,
    W_FACTS,
    append_snapshot,
    obstacle_face,
    signature_hash,
    signature_str,
    snapshot as state_snapshot,
    v_anchor,
    v_from_workspace,
)
from .triples import (
    CSV_HEADER,
    Q_REPORT_SCHEMA,
    TRIPLES_REL,
    extract as extract_triples,
    q_report,
    read_csv as read_triples_csv,
)
from .winrate import (
    DEFAULT_WINDOW as WINRATE_DEFAULT_WINDOW,
    SCHEMA as WINRATE_SCHEMA,
    face as winrate_face,
    scored_stream,
    summarize as summarize_winrate,
)
from .liveness import (
    CONTINUITY_WINDOW_HOURS,
    CONTINUITY_WINDOW_TICKS,
    STALE_MINUTES,
    TICK_HISTORY_CAP,
    TICK_HISTORY_KEY,
    TICK_INTERVAL_DEFAULT_MIN,
    append_tick,
    evaluate_tick_continuity,
    gap_alarm,
    heartbeat_log_path,
    newest_sidecar_ts,
    reset_continuity_baseline,
)
from .posteriors import (
    ADAPTIVE_EMA_LAMBDA_DEFAULT,
    GAMMA_FLOOR_DEFAULT,
    PRIOR_ALPHA_DEFAULT,
    PRIOR_BETA_DEFAULT,
    SCHEMA as POSTERIOR_SCHEMA,
    STORE_REL as POSTERIOR_STORE_REL,
    OutcomeAdaptiveGamma,
    PosteriorView,
    default_schedule,
    fold as fold_posteriors,
    gamma_constant,
    read as read_posteriors,
    record as record_posterior,
    row_schema_lint as posterior_row_schema_lint,
)
from .q_cells import (
    SHRINK_CAP,
    CellCounts,
    Fold as QCellFold,
    InMemoryStore,
    cell_posterior,
    cell_table,
    default_store,
    fold as fold_q_cells,
    observe,
    q_cells_seed_state,
    record_dispatch_observation,
    reindex,
    sample_method_family,
)
from .compose import (
    CARD_SCHEMA,
    SEGMENT_CONSTITUTION,
    SEGMENT_STRATEGY,
    SCHEMA as STRATEGY_SCHEMA,
    compose as compose_strategy,
    load_cards,
    mint_card,
    render_card_block,
    schedule_cards,
    validate_strategy,
    write_strategy,
)
from .obstacles import (
    CAUSE_MAX,
    KINDS as OBSTACLE_KINDS,
    OBSTACLES_REL,
    SCHEMA as OBSTACLE_SCHEMA,
    face as obstacle_digest,
    read as read_obstacles,
    record as record_obstacle,
    validate_obstacle,
)

__all__ = [
    # modules
    "compose",
    "ledger",
    "liveness",
    "obstacles",
    "posteriors",
    "priors",
    "q_cells",
    "reward",
    "scalar",
    "state",
    "triples",
    "winrate",
    # ledger faces (issue 420 Phase 2)
    "KIND_TASK",
    "KIND_SELF_DISTILL",
    "KIND_HYBRID_DISTILL",
    "LEDGER_SCHEMA",
    "LEDGER_REL",
    "LOCK_REL",
    "ROLLOUT_KINDS",
    "register_rollout_kind",
    "rollout_kinds",
    "ledger_row_schema_lint",
    "read_rollouts",
    "fold_rollout",
    "settled_rollouts",
    "pending_settlement",
    "record_rollout",
    "settle_rollout",
    # reward faces (issue 420 Phase 2)
    "REWARD_BANDS",
    "POLARITY_ALPHA_BANDS",
    "POLARITY_BETA_BANDS",
    "RULES_SCHEMA",
    "classify_signals",
    "load_rules",
    "polarity_of",
    "prior_observations",
    "settle_workspace_rewards",
    # scalar faces (issue 420 Phase 2)
    "MEASURED_TIERS",
    "OUTPUT_RAILS",
    "classify_tier",
    "extract_tuple",
    "normal_gamma_update",
    "merge_normal_gamma_posts",
    "round_credit",
    "scalar_observations",
    "settle_round_credit",
    "settle_workspace_scalars",
    "experience_tuples",
    # priors faces (issue 420 Phase 2)
    "PRIOR_RESULT_SCHEMA",
    "PRIOR_BASE_ALPHA",
    "PRIOR_BASE_BETA",
    "compute_priors",
    # state faces (issue 420 Phase 2)
    "STATE_SCHEMA",
    "TERMINAL_FACT_STATUSES",
    "FACT_BUCKET_EDGES",
    "BUDGET_BUCKET_EDGES",
    "W_CHAIN",
    "W_FACTS",
    "W_BUDGET",
    "state_snapshot",
    "signature_str",
    "signature_hash",
    "obstacle_face",
    "v_anchor",
    "v_from_workspace",
    "append_snapshot",
    # triples faces (issue 420 Phase 2)
    "TRIPLES_REL",
    "CSV_HEADER",
    "Q_REPORT_SCHEMA",
    "extract_triples",
    "read_triples_csv",
    "q_report",
    # winrate faces (issue 420 Phase 2)
    "WINRATE_SCHEMA",
    "WINRATE_DEFAULT_WINDOW",
    "winrate_face",
    "scored_stream",
    "summarize_winrate",
    # liveness faces (issue 420 Phase 2)
    "TICK_HISTORY_KEY",
    "TICK_HISTORY_CAP",
    "STALE_MINUTES",
    "CONTINUITY_WINDOW_HOURS",
    "CONTINUITY_WINDOW_TICKS",
    "TICK_INTERVAL_DEFAULT_MIN",
    "append_tick",
    "evaluate_tick_continuity",
    "gap_alarm",
    "heartbeat_log_path",
    "newest_sidecar_ts",
    "reset_continuity_baseline",
    # posteriors faces (issue 428)
    "ADAPTIVE_EMA_LAMBDA_DEFAULT",
    "GAMMA_FLOOR_DEFAULT",
    "PRIOR_ALPHA_DEFAULT",
    "PRIOR_BETA_DEFAULT",
    "POSTERIOR_SCHEMA",
    "POSTERIOR_STORE_REL",
    "OutcomeAdaptiveGamma",
    "PosteriorView",
    "default_schedule",
    "fold_posteriors",
    "gamma_constant",
    "record_posterior",
    "read_posteriors",
    "posterior_row_schema_lint",
    # q_cells faces (issue 420 Phase 2 export-map completion)
    "SHRINK_CAP",
    "CellCounts",
    "QCellFold",
    "InMemoryStore",
    "fold_q_cells",
    "cell_posterior",
    "sample_method_family",
    "q_cells_seed_state",
    "record_dispatch_observation",
    "observe",
    "default_store",
    "cell_table",
    "reindex",
    # compose faces (issue 420 Phase 2 export-map completion; the compose
    # FUNCTION is compose_strategy — the bare name is the module's)
    "STRATEGY_SCHEMA",
    "CARD_SCHEMA",
    "SEGMENT_CONSTITUTION",
    "SEGMENT_STRATEGY",
    "compose_strategy",
    "mint_card",
    "load_cards",
    "schedule_cards",
    "render_card_block",
    "validate_strategy",
    "write_strategy",
    # obstacles faces (issue 461 Phase 1)
    "OBSTACLE_SCHEMA",
    "OBSTACLE_KINDS",
    "OBSTACLES_REL",
    "CAUSE_MAX",
    "validate_obstacle",
    "record_obstacle",
    "read_obstacles",
    "obstacle_digest",
]
