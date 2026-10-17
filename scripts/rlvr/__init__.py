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

from . import censored_review
from . import compose
from . import consolidated_ledger
from . import constants_ref
from . import crystallize
from . import expansion
from . import feature_prior
from . import hypotheses
from . import incremental_reward
from . import invariants
from . import l1_planner
from . import l1_value
from . import ledger
from . import liveness
from . import marl
from . import meta_arms
from . import obstacles
from . import policy_compare
from . import posteriors
from . import prediction_ledger
from . import priors
from . import q_cells
from . import recipe_arms
from . import refutation_fold
from . import reward
from . import scalar
from . import settlement_scorer
from . import source_reliability
from . import state
from . import step_credit
from . import step_grain
from . import step_ledger
from . import strategy_store
from . import termination
from . import triples
from . import verification_debt
from . import winrate

__all__ = [
    "censored_review",
    "compose",
    "consolidated_ledger",
    "constants_ref",
    "crystallize",
    "expansion",
    "feature_prior",
    "hypotheses",
    "incremental_reward",
    "invariants",
    "l1_planner",
    "l1_value",
    "ledger",
    "marl",
    "meta_arms",
    "obstacles",
    "policy_compare",
    "posteriors",
    "prediction_ledger",
    "priors",
    "q_cells",
    "recipe_arms",
    "refutation_fold",
    "scalar",
    "source_reliability",
    "state",
    "step_credit",
    "step_grain",
    "step_ledger",
    "strategy_store",
    "termination",
    "verification_debt",
]
