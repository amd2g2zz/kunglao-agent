#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_common.py — THE shared leaf-utility module (the dedup home the
owner's consolidation ruling names). A leaf by contract: numpy + stdlib
ONLY — never imports any repo module, so every importer family
(settlement, state, kernel, hooks) can depend on it without crossing
its isolation walls. Duplicated helpers migrate here; the
formal_code_lint ledger shrinks as they do."""
from __future__ import annotations

import time
from collections.abc import Iterable

import numpy as np


def seq_sum(values: Iterable[float]) -> float:
    """Input-order float64 reduction — the settlement determinism axiom
    ("float sums in input order") as a numpy primitive.

    np.add.accumulate is strictly left-to-right IEEE-754 double addition;
    the prepended 0.0 seed makes it bit-identical to a Python in-order
    sum for every finite input, and — unlike builtin sum(), which
    switched floats to Neumaier compensation in 3.12 — identical on
    every interpreter. np.sum / np.add.reduce are FORBIDDEN on this
    path: pairwise summation reorders the bits, and the pins in the
    bit-exact suites are the wall. THE canonical implementation (the
    per-module redeclarations are retired).
    """
    arr = np.asarray(list(values), dtype=np.float64)
    if arr.size == 0:
        return 0.0
    return float(np.add.accumulate(np.concatenate(([0.0], arr)))[-1])


def utc_now_z() -> str:
    """THE canonical UTC timestamp face: ISO-8601 Z, second precision —
    one format everywhere a wall-clock stamp is written."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
