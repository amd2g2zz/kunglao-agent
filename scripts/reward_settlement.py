# -*- coding: utf-8 -*-
"""reward_settlement.py — the #420 Phase-2 adapter shim.

The implementation body lives in ``rlvr.reward`` (issue #420 Phase 2:
consolidation into the unified RLVR package, per scripts/rlvr/README.md).
This module is the explicit re-export surface only — no logic — so every
existing importer (scripts/ siblings by bare import, tests, hooks with
scripts/ on sys.path) keeps working unchanged. The package is the truth;
the shim is the compat surface.
"""
from __future__ import annotations

from rlvr.reward import (  # noqa: F401 — the compat surface
    BANDS,
    NEUTRAL_BAND,
    ORACLE_STATUS_REL,
    POLARITY_ALPHA_BANDS,
    POLARITY_BETA_BANDS,
    RULES_REL,
    RULES_SCHEMA,
    classify,
    emit_unified_rows,
    load_rules,
    polarity_of,
    prior_observations,
    repo_rules_path,
    resolve_library,
    rollup_face,
    self_distill_signals,
    settle_workspace,
    snapshot_lessons,
    task_signals,
    warn,
)

__all__ = [
    "RULES_REL", "RULES_SCHEMA", "BANDS", "NEUTRAL_BAND",
    "POLARITY_ALPHA_BANDS", "POLARITY_BETA_BANDS", "ORACLE_STATUS_REL",
    "repo_rules_path", "load_rules", "classify", "settle_workspace",
    "polarity_of", "prior_observations",
    "task_signals", "self_distill_signals", "emit_unified_rows",
    "rollup_face", "snapshot_lessons", "resolve_library", "warn",
]


if __name__ == "__main__":  # pragma: no cover — library module; tick face via rollup
    print(__doc__)
