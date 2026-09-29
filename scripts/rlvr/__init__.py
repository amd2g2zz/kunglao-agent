# -*- coding: utf-8 -*-
"""rlvr — the unified RLVR package surface (issue 420).

THE one import point: ``import rlvr`` (scripts/ is on pythonpath for
tests, tools, and hooks alike). This ``__init__`` carries the ONE export
map — a single ``__all__`` plus explicit submodule re-exports — so the
public surface is enumerable in one file and drift against it is a test
failure, not folklore. Design: ``scripts/rlvr/README.md``.

Modules (phase-gated per the README; the top-level scripts stay thin
adapters until their Phase-2 consolidation wave):

- ``rlvr.posteriors`` — the DTS posterior store (Discounted Thompson
  Sampling, issue 428,
  v0.1.6 W2-T1): append-only ``runs/posterior-store.jsonl``, fold/read
  face applying the γ decay, pseudo-count priors, outcome-adaptive
  schedule with EX-2-calibrated defaults.

- ``rlvr.q_cells`` — the Q cell registry keyed ``(signature_hash,
  method_family)`` with hierarchy shrinkage toward the global anchor
  (issue 429 section 4, W2-T2).
"""
from __future__ import annotations

from . import ledger
from . import posteriors
from . import q_cells
from . import reward
from . import scalar
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
    normal_gamma_update,
    merge_normal_gamma_posts,
    round_credit,
    scalar_observations,
    settle_round_credit,
    settle_workspace_scalars,
    tuples as experience_tuples,
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

__all__ = [
    "ledger",
    "posteriors",
    "q_cells",
    "reward",
    "scalar",
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
]
