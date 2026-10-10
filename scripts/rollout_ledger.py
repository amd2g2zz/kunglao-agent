# -*- coding: utf-8 -*-
"""rollout_ledger.py — the #420 Phase-2 adapter shim.

The implementation body lives in ``rlvr.ledger`` (issue #420 Phase 2:
consolidation into the unified RLVR package, per scripts/rlvr/README.md).
This module is the explicit re-export surface only — no logic — so every
existing importer (scripts/ siblings by bare import, tests, hooks with
scripts/ on sys.path) keeps working unchanged. The package is the truth;
the shim is the compat surface.
"""
from __future__ import annotations

from rlvr.ledger import (  # noqa: F401 — the compat surface
    KIND_HYBRID_DISTILL,
    KIND_SELF_DISTILL,
    KIND_TASK,
    LEDGER_REL,
    LOCK_REL,
    ROLLOUT_KINDS,
    SCHEMA,
    fold,
    kinds,
    pending_settlement,
    read,
    record,
    register_kind,
    row_schema_lint,
    settle,
    settled,
    warn,
)

__all__ = [
    "SCHEMA", "LEDGER_REL", "LOCK_REL",
    "KIND_TASK", "KIND_SELF_DISTILL", "KIND_HYBRID_DISTILL", "ROLLOUT_KINDS",
    "register_kind", "kinds",
    "row_schema_lint", "warn",
    "read", "fold", "settled",
    "pending_settlement", "record", "settle",
]


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
