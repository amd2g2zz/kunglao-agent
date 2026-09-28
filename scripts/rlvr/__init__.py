# -*- coding: utf-8 -*-
"""rlvr — the unified RLVR package surface (issue 420).

THE one import point: ``import rlvr`` (scripts/ is on pythonpath for
tests, tools, and hooks alike). This ``__init__`` carries the ONE export
map — a single ``__all__`` plus explicit submodule re-exports — so the
public surface is enumerable in one file and drift against it is a test
failure, not folklore. Design: ``scripts/rlvr/README.md``.

Modules (phase-gated per the README; the top-level scripts stay thin
adapters until their Phase-2 consolidation wave):

- ``rlvr.posteriors`` — the γ Discounted-TS posterior store (issue 428,
  v0.1.6 W2-T1): append-only ``runs/posterior-store.jsonl``, fold/read
  face applying the γ decay, pseudo-count priors, outcome-adaptive
  schedule with EX-2-calibrated defaults.

SEAM (W2-T2, parallel maker): ``rlvr.q_cells`` — the Q cell
registry keyed ``(signature_hash, method_family)`` with hierarchy
shrinkage toward the global anchor — joins this export map when its
branch lands; do not import it before it exists.
"""
from __future__ import annotations

from . import posteriors
from .posteriors import (
    ADAPTIVE_EMA_LAMBDA_DEFAULT,
    GAMMA_FLOOR_DEFAULT,
    GAMMA_UNIT,
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
    "posteriors",
    # posteriors faces (issue 428)
    "ADAPTIVE_EMA_LAMBDA_DEFAULT",
    "GAMMA_FLOOR_DEFAULT",
    "GAMMA_UNIT",
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
