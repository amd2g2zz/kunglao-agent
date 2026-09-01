#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tuition_refit.py — #823-P4 Platt 系数重拟合面（只提案不生效）。

从 ledger 的 rho_pair 行收集 (ρ, z_self) 对 → rho_verifier.fit_platt
重拟合 → optimizer_core.make_proposal 产出 θ 提案（schema opt-proposal-v1，
θ 键 ⊆ PARAM_NAMES——宪法隔离继承 optimizer_core.CONSTITUTIONAL_KEYS）。
对数 < MIN_PAIRS 时明确 insufficient，不产提案。全部离线，零 API。
"""
from __future__ import annotations

import subprocess

import optimizer_core
import rho_verifier

MIN_PAIRS = 10
_PLATT_W_BOUNDS = (0.0, 10.0)   # PARAM_SPEC platt_w
_PLATT_B_BOUNDS = (-5.0, 5.0)   # PARAM_SPEC platt_b


def _git_sha() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=10, encoding="utf-8", errors="replace")
        return (r.stdout or "").strip() or "unknown"
    except Exception:  # noqa: BLE001 — sha 缺失不阻塞提案
        return "unknown"


def _clamp(v: float, bounds) -> float:
    lo, hi = bounds
    return min(hi, max(lo, v))


def collect(ws):
    """(ρ, z_self) 对（单一来源：rho_verifier.pairs_from_ledger）。"""
    return rho_verifier.pairs_from_ledger(ws)


def refit(ws, out_path=None):
    """重拟合并产出提案。返回 {ok, proposal?, fit?, n_pairs} / {ok:False,...}。"""
    pairs = collect(ws)
    if len(pairs) < MIN_PAIRS:
        return {"ok": False, "reason": "insufficient_pairs",
                "n_pairs": len(pairs)}
    w, b = rho_verifier.fit_platt(pairs)
    theta_old = optimizer_core.default_theta()
    theta_new = dict(theta_old)
    theta_new["platt_w"] = _clamp(w, _PLATT_W_BOUNDS)
    theta_new["platt_b"] = _clamp(b, _PLATT_B_BOUNDS)
    evidence = {"source": "ledger rho_pair", "n_pairs": len(pairs),
                "fit": {"w": round(w, 6), "b": round(b, 6)},
                "constitution": "inherited optimizer_core isolation"}
    prop = optimizer_core.make_proposal(theta_old, theta_new, evidence,
                                        base_sha=_git_sha())
    if out_path is not None:
        optimizer_core.write_proposal(out_path, prop)
    return {"ok": True, "proposal": prop,
            "fit": {"w": round(w, 6), "b": round(b, 6)},
            "n_pairs": len(pairs)}
