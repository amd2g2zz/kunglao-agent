# -*- coding: utf-8 -*-
"""experience_triples.py — the #420 Phase-2 adapter shim.

The implementation body lives in ``rlvr.triples`` (issue #420 Phase 2:
consolidation into the unified RLVR package, per scripts/rlvr/README.md).
This module is the explicit re-export surface only — no logic — so every
existing bare-name importer keeps working unchanged.
"""
from __future__ import annotations

from rlvr.triples import (  # noqa: F401 — the compat surface
    CSV_HEADER,
    Q_REPORT_SCHEMA,
    TRIPLES_REL,
    _last_signal,
    _strategy_arm_by_claim,
    extract,
    q_report,
    read_csv,
)

__all__ = [
    "TRIPLES_REL", "CSV_HEADER", "Q_REPORT_SCHEMA",
    "extract", "read_csv", "q_report",
    "_last_signal", "_strategy_arm_by_claim",
]


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
