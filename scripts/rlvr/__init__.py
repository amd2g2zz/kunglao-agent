# -*- coding: utf-8 -*-
"""rlvr — the unified RLVR package surface (issue #420).

Phase-gated per the package README: this ``__init__`` is THE one import
point. Until the #420 Phase-2 consolidation lands, the package carries
the W2-T2 action-value layer only; the full export map (README face map)
grows as the #428/#429 kernel modules land, and Phase 2 re-mints it once
against the consolidated modules. Import direction stays one-way:
everything in this package may import ``kunglao_log``/``state_signature``
sibling scripts; nothing in scripts/ or hooks/ imports the package the
other way round.
"""
from rlvr import q_cells  # noqa: F401  (the #429 §4 Q-cell layer)

__all__ = ["q_cells"]
