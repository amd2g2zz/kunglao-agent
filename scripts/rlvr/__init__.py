# -*- coding: utf-8 -*-
"""rlvr — the RLVR package surface.

The real consumption shape is submodule-direct (``from rlvr.marl import
record_negative``): this ``__init__`` keeps one ``from . import`` line
per submodule (so ``rlvr.<submodule>`` resolves after a bare
``import rlvr``) and ``__all__`` enumerates exactly the submodule names
with at least one external consumer — enforced by
tests/test_rlvr_facade_756.py (drift IS a test failure). Design:
``scripts/rlvr/README.md``.

Submodule design notes live in the README face map; the per-module
detail is each module's own docstring.
"""

from . import attribution
from . import censored_review
from . import commit_semantics
from . import compose
from . import consolidated_ledger
from . import belief
from . import constants_ref
from . import crystallize
from . import distill_dgate
from . import distill_lifecycle
from . import distill_rollout
from . import distill_score
from . import episode_pool
from . import episode_schema
from . import expansion
from . import feature_prior
from . import hypotheses
from . import incremental_reward
from . import invariants
from . import l1_planner
from . import key_freeze
from . import l1_value
from . import ledger
from . import learning_seal
from . import liveness
from . import marl
from . import meta_context
from . import meta_policy
from . import meta_retrieval
from . import meta_arms
from . import obstacles
from . import phi_tree
from . import playbook
from . import policy_compare
from . import pool_indexer
from . import pool_scheduler
from . import posteriors
from . import pricing
from . import prediction_ledger
from . import priors
from . import q_cells
from . import recipe_arms
from . import refutation_fold
from . import reward
from . import reward_signal
from . import scalar
from . import settlement_scorer
from . import settlement_wire
from . import signal_guard
from . import source_reliability
from . import state
from . import step_credit
from . import step_grain
from . import step_ledger
from . import step_record
from . import strategy_store
from . import termination
from . import triples
from . import verification_debt
from . import winrate

__all__ = [
    "attribution",
    "belief",
    "censored_review",
    "commit_semantics",
    "compose",
    "consolidated_ledger",
    "constants_ref",
    "crystallize",
    "distill_dgate",
    "distill_lifecycle",
    "distill_rollout",
    "distill_score",
    "episode_pool",
    "expansion",
    "feature_prior",
    "hypotheses",
    "incremental_reward",
    "invariants",
    "l1_planner",
    "key_freeze",
    "l1_value",
    "ledger",
    "learning_seal",
    "marl",
    "meta_arms",
    "meta_context",
    "meta_policy",
    "meta_retrieval",
    "obstacles",
    "phi_tree",
    "playbook",
    "policy_compare",
    "posteriors",
    "pricing",
    "prediction_ledger",
    "priors",
    "q_cells",
    "recipe_arms",
    "refutation_fold",
    "reward",
    "scalar",
    "settlement_wire",
    "source_reliability",
    "state",
    "step_credit",
    "step_grain",
    "step_ledger",
    "step_record",
    "strategy_store",
    "termination",
    "verification_debt",
    "winrate",
]
