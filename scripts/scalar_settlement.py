# -*- coding: utf-8 -*-
"""scalar_settlement.py — the #420 Phase-2 adapter shim.

The implementation body lives in ``rlvr.scalar`` (issue #420 Phase 2:
consolidation into the unified RLVR package, per scripts/rlvr/README.md).
This module is the explicit re-export surface only — no logic — so every
existing importer (scripts/ siblings by bare import, tests, hooks with
scripts/ on sys.path) keeps working unchanged. The package is the truth;
the shim is the compat surface. The import-time side effect
(rl.register_kind("round_credit", ...)) rides with the body.
"""
from __future__ import annotations

from rlvr.scalar import (  # noqa: F401 — the compat surface
    BAND_ROUND_CREDIT,
    CITED_CAP_DEFAULT,
    DEMOTION_CITED_OVER_CAP,
    DEMOTION_REFUTED_INFORMATION,
    DEMOTION_UNCITED_VERIFIED,
    FAIL_CREDIT_CAP,
    KIND_ROUND_CREDIT,
    MEASURED_TIERS,
    NG_A0,
    NG_B0,
    NG_KAPPA0,
    NG_MU0,
    ORACLE_PASS_LOCK,
    OUTPUT_RAILS,
    ROUND_CREDIT_FULL,
    RULE_NEUTRAL,
    RULE_RED,
    RULE_ROUND_CREDIT,
    RULE_TRAJECTORY_CREDIT,
    TIER_BRONZE,
    TIER_GOLD,
    TIER_NEUTRAL,
    TIER_RED,
    TIER_SILVER,
    TIER_TRACE,
    TRACE_CANONICAL,
    _last,
    _ng_from_stats,
    _probe_progress,
    _seq_sum,
    apply_trajectory_settlement,
    clamp_credit,
    classify_tier,
    cost_dim,
    difficulty_dim,
    evidence_dim,
    extract_dimensions,
    extract_tuple,
    fact_artifacts,
    merge_normal_gamma_posts,
    normal_gamma_update,
    oracle_lock,
    outcome_dim,
    question_claims,
    rail_of,
    resolvable_registry,
    resolve_citations,
    round_credit,
    scalar_observations,
    settle_round_credit,
    settle_workspace_scalars,
    tuples,
    validate_verdict_doc,
    warn,
)

__all__ = [
    "KIND_ROUND_CREDIT", "BAND_ROUND_CREDIT", "RULE_ROUND_CREDIT",
    "RULE_NEUTRAL", "RULE_RED",
    "ROUND_CREDIT_FULL", "DEMOTION_UNCITED_VERIFIED",
    "DEMOTION_REFUTED_INFORMATION",
    "CITED_CAP_DEFAULT", "DEMOTION_CITED_OVER_CAP",
    "TIER_GOLD", "TIER_SILVER", "TIER_BRONZE", "TIER_TRACE", "TIER_NEUTRAL",
    "TIER_RED", "MEASURED_TIERS",
    "NG_MU0", "NG_KAPPA0", "NG_A0", "NG_B0", "OUTPUT_RAILS",
    "TRACE_CANONICAL", "FAIL_CREDIT_CAP", "ORACLE_PASS_LOCK",
    "RULE_TRAJECTORY_CREDIT",
    "_last", "_probe_progress", "_ng_from_stats", "_seq_sum",
    "outcome_dim", "difficulty_dim", "evidence_dim", "cost_dim",
    "extract_dimensions", "classify_tier", "extract_tuple",
    "settle_workspace_scalars", "tuples",
    "round_credit", "settle_round_credit", "scalar_observations",
    "normal_gamma_update", "merge_normal_gamma_posts",
    "question_claims", "fact_artifacts",
    "clamp_credit", "rail_of", "resolve_citations", "oracle_lock",
    "validate_verdict_doc", "resolvable_registry",
    "apply_trajectory_settlement", "warn",
]


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
