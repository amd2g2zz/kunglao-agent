# -*- coding: utf-8 -*-
"""state_signature.py — the #420 Phase-2 adapter shim.

The implementation body lives in ``rlvr.state`` (issue #420 Phase 2:
consolidation into the unified RLVR package, per scripts/rlvr/README.md).
This module is the explicit re-export surface only — no logic — so every
existing bare-name importer keeps working unchanged.
"""
from __future__ import annotations

from rlvr.state import (  # noqa: F401 — the compat surface
    BUDGET_BUCKET_EDGES,
    COST_EVENTS_REL,
    FACT_BUCKET_EDGES,
    SCHEMA,
    SITUATION_SCHEMA,
    SITUATIONS_REL,
    TERMINAL_FACT_STATUSES,
    W_BUDGET,
    W_CHAIN,
    W_FACTS,
    W_SIDES,
    _now,
    _oracle_status_progress,
    _probe_signal_progress,
    append_snapshot,
    budget_bucket,
    budget_fraction,
    chain_progress,
    claim_pattern,
    fact_bucket,
    fact_face,
    phase,
    read_situations,
    signature_hash,
    signature_str,
    snapshot,
    v_anchor,
    v_from_workspace,
    warn,
)

__all__ = [
    "SCHEMA", "SITUATIONS_REL", "SITUATION_SCHEMA",
    "TERMINAL_FACT_STATUSES",
    "FACT_BUCKET_EDGES", "BUDGET_BUCKET_EDGES",
    "W_CHAIN", "W_FACTS", "W_BUDGET", "W_SIDES",
    "COST_EVENTS_REL",
    "fact_face", "fact_bucket", "claim_pattern", "budget_fraction",
    "budget_bucket", "chain_progress", "phase",
    "snapshot", "signature_str", "signature_hash",
    "v_anchor", "v_from_workspace",
    "append_snapshot", "read_situations",
    "_now", "_probe_signal_progress", "_oracle_status_progress",
    "warn",
]


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
