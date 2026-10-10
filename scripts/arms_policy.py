#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arms_policy.py — the comparison-arm-set policy (owner rulings 2026-10-10).

Exploration entropy is the learning loop's fuel; with LLM sampling
temperature OFF the table (owner: "温度在我们这边无效"), the arm set is the
only comparison surface. The optimum is derived from three constraints —
the per-arm sample floor (~3 observations), the 3-slot dispatch pool
(WORKER_CAP=3 -> waves), and the (context x arm) matrix — and it is
FALSIFIABLE, not dogma: measure the separation-efficiency curve
(k=3/5/8) with the multi-arm eval matrix (#569) + policy_compare's SNIPS,
then tune under #295 governance (replay evidence only).

  MIN_COMPARISON_ARMS = 3      the admission floor (#109 gate): below 3
                               there is no adjudication structure (2 arms
                               resolve to a tie, not a comparison).
  DEFAULT_COMPARISON_ARMS = 5  the ACTIVE working point: ~3 observations
                               per arm within a mission's run budget
                               (~12-20 runs), 2 waves on the 3-slot pool.
  MAX_COMPARISON_ARMS = 8      the ACTIVE budget ceiling: past 8 the
                               marginal entropy of a candidate is below its
                               sample dilution; the #539 4-dim arm key
                               (family|recipe|verif|tier) bounds the
                               (context x arm) matrix.
  LIBRARY_MAX_COMPARISON_ARMS = 16
                               the CANDIDATE-LIBRARY ceiling (max-ROI
                               split, owner-approved 2026-10-10): library
                               slots consume NO run budget — breadth is
                               nearly free — while the ACTIVE set pays
                               dilution per arm. Keep the library wide (16)
                               and PROMOTE into the active set via
                               novelty/rotation; past 16 the extras are
                               correlated repeats the novelty face would
                               weed anyway.

Max-ROI shape: wide library + small active set. The ACTIVE ceiling is the
one that should adapt to cost (future refinement: min(8, run_budget/3)
once a per-round run budget is declared); the LIBRARY ceiling only moves
with register-economy carrying cost.

Consumers: hooks/dispatch_gate.py (the #109 floor via the guarded
single-source import), rlvr.expansion.admit (the pool ceiling clamp),
hypothesis_bridge.family_live_arms + the mint library-cap warn, tests.
"""
from __future__ import annotations

MIN_COMPARISON_ARMS = 3
DEFAULT_COMPARISON_ARMS = 5
MAX_COMPARISON_ARMS = 8
LIBRARY_MAX_COMPARISON_ARMS = 16
