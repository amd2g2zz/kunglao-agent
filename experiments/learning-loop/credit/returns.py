# -*- coding: utf-8 -*-
"""credit/returns.py — discounted returns over a rollout's rewards.

R_t = r_t + γ·R_{t+1} for the whole step chain in ONE vectorized
pass (the masked outer product of γ powers — no sequential scan, no
interpreter-dependent summation order). The rewards come from the
unified ledger's result rows (``rollout_rewards`` — append order,
pending steps skipped): the (s,a,r) store is the only source, the
#879 charter. Terminal shaping folds the outcome bonus into the last
step BEFORE the discount pass — completion banks +bonus, a rollback
banks −bonus: the terminal step's return flips and propagates
backward at γ (the issue's rollback posture).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from rlvr import q_cells  # noqa: E402 — the ledger read faces

#: the closed terminal vocabulary (the policy Transition names, as
#: the settlement reports them).
TERMINALS = ("completed", "rolled_back")


def _checked_rewards(rewards: np.ndarray) -> np.ndarray:
    arr = np.asarray(rewards, dtype=float)
    if arr.ndim != 1 or arr.size == 0:
        raise ValueError(
            "credit.returns: rewards must be a non-empty 1-d array")
    if not np.all(np.isfinite(arr)):
        raise ValueError(
            "credit.returns: rewards must all be finite")
    return arr


def _checked_gamma(gamma: float) -> float:
    g = float(gamma)
    if not 0.0 < g < 1.0:
        raise ValueError(
            f"credit.returns: gamma must lie in (0, 1), got {gamma!r}")
    return g


def discounted_returns(rewards: np.ndarray, gamma: float) -> np.ndarray:
    """R_t = Σ_{k≥t} γ^(k−t) · r_k — the vectorized reverse recurrence.

    The outer-product form: W[i, j] = γ^(j−i) on the upper triangle,
    R = W @ r. Exact, order-stable, no sequential scan."""
    r = _checked_rewards(rewards)
    g = _checked_gamma(gamma)
    n = r.shape[0]
    power = np.arange(n)[None, :] - np.arange(n)[:, None]
    upper = power >= 0
    weights = np.where(upper, np.power(g, np.where(upper, power, 0)),
                       0.0)
    return weights @ r


def terminal_shaped(rewards: np.ndarray, gamma: float, *, terminal: str,
                    terminal_bonus: float) -> np.ndarray:
    """Fold the outcome bonus into the LAST step, then discount.

    ``terminal`` is the closed vocabulary ``completed`` |
    ``rolled_back``; the bonus is + on completion, − on rollback (the
    magnitude is the caller's policy constant). A bonus of 0.0 is the
    unshaped pass-through. The flip lands on the TERMINAL step's
    return and propagates backward at γ — a large early reward can
    keep early returns positive even on a rollback; the per-step
    advantage carries the shaped trajectory honestly."""
    if terminal not in TERMINALS:
        raise ValueError(
            f"credit.returns: terminal must be one of {TERMINALS}, "
            f"got {terminal!r}")
    r = _checked_rewards(rewards).copy()
    bonus = float(terminal_bonus)
    if not np.isfinite(bonus):
        raise ValueError("credit.returns: terminal_bonus must be finite")
    if terminal == "rolled_back":
        bonus = -bonus
    r[-1] += bonus
    return discounted_returns(r, gamma)


def rollout_rewards(ws, rollout_id: str) -> np.ndarray:
    """One rollout's step rewards from the ledger — append order,
    pending steps (r_t=None) skipped, other rollouts' rows ignored.
    Empty (no priced step yet) is the honest empty array, never a
    fabricated zero."""
    rid = str(rollout_id or "").strip()
    if not rid:
        raise ValueError("credit.returns: rollout_id must be non-empty")
    out: list[float] = []
    for row in q_cells.trajectory_rows(ws):
        if row.get("schema") != q_cells.SCHEMA_RESULT_V2:
            continue
        if str(row.get("rollout_id") or "") != rid:
            continue
        r_t = row.get("r_t")
        if isinstance(r_t, (int, float)) and not isinstance(r_t, bool):
            out.append(float(r_t))
    return np.array(out, dtype=float)
