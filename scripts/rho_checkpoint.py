#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rho_checkpoint.py — P2 ρ progress signal + V/D/ETA (#823, N-arm).

ρ (rho): continuous per-round progress score over (task_spec PQ set,
trajectory prefix), decomposed per PQ — the LLM-as-a-Verifier checkpoint
(arXiv:2607.05391) mirrored mechanically:
  - logprob path: the verifier returns a distribution over discrete
    grades; ρ = Σ p·grade (scoring-token expectation).
  - two-stage degradation (closed models, paper §B.6): the verifier is
    asked to state the grade distribution verbally; same expectation.
Both paths collapse into rho_from_distribution.

V/D/ETA first-order signals:
  V(s) = σ(w·x+b) — Platt calibration fit over A1's (score, outcome)
  pairs; before any fit, V falls back to the replay priors through the
  chain feature bucket → depth bucket → global → uninformative (0.5,
  widest error bar).
  D(t) — difficulty, updated on three triggers only: t0 prior /
  capability_flip (validated capability lowers difficulty) / wear
  (strategy failures raise it).
  ETA = remaining budget × enumeration coefficient.

SHADOW POSTURE: everything here records signals, nothing intercepts.
The only side effect is the kunglao_log emit (action "rho_checkpoint",
registered in event_taxonomy.EMIT_ACTIONS). decide() attaches these as
an extra `value_signals` key — flag off → the key never appears and the
decision dict is byte-identical.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import yaml

import kunglao_log
import value_config
import value_replay

PRIORS_FILE = "runs/value-priors.yaml"
_GLOBAL_KEY = "*|*"


# ---------- V = σ(w·x+b) ----------

def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def fit_platt(pairs: list[dict], epochs: int = 2000, lr: float = 0.5) -> tuple[float, float]:
    """Deterministic full-batch gradient descent for σ(w·score+b) ≈ outcome.

    stdlib-only stand-in for logistic regression — the heaviest "training"
    the #823 doctrine allows. Returns (w, b)."""
    w, b = 0.0, 0.0
    if not pairs:
        return w, b
    for _ in range(epochs):
        gw = gb = 0.0
        for p in pairs:
            x, y = float(p["score"]), float(p["outcome"])
            err = sigmoid(w * x + b) - y
            gw += err * x
            gb += err
        n = len(pairs)
        w -= lr * gw / n
        b -= lr * gb / n
    return w, b


def _band(n: int) -> float:
    """Error bar: 1/√n clamped to [0.05, 0.5] — wide until n justifies trust."""
    if n <= 0:
        return 0.5
    return min(0.5, max(0.05, 1.0 / math.sqrt(n)))


def v_from_priors(priors: dict, depth: str, family: str) -> tuple[float, str, float]:
    """Fallback chain: feature bucket → depth bucket → global → uninformative."""
    buckets = (priors or {}).get("buckets") or {}
    for key, source in ((f"{depth}|{family}", "feature_bucket"),
                        (f"{depth}|*", "depth_bucket"),
                        (_GLOBAL_KEY, "global")):
        b = buckets.get(key)
        if isinstance(b, dict) and isinstance(b.get("p_complete"), (int, float)):
            return float(b["p_complete"]), source, _band(int(b.get("n") or 0))
    return 0.5, "uninformative", 0.5


# ---------- ρ progress signal ----------

def rho_from_distribution(grade_probs: list[tuple[float, float]]) -> float:
    """Expectation over (grade, probability) pairs — the shared form of the
    logprob path and the two-stage verbal path."""
    total_p = sum(p for _, p in grade_probs)
    if total_p <= 0:
        return 0.0
    return sum(g * p for g, p in grade_probs) / total_p


def rho_sequence(per_checkpoint: list[dict]) -> list[float]:
    """ρ per checkpoint: mean of per-PQ grades at that checkpoint.

    Progress trajectory → non-decreasing sequence; idle trajectory → flat.
    (Monotonicity is a property of the trajectory, asserted by tests on
    synthetic inputs; the function itself never smooths or clamps.)"""
    out = []
    for cp in per_checkpoint:
        grades = [float(v.get("grade", 0.0)) for v in (cp or {}).values()
                  if isinstance(v, dict)]
        out.append(sum(grades) / len(grades) if grades else 0.0)
    return out


def parse_verifier_response(text: str) -> dict[str, dict] | None:
    """Mechanical parse of the verifier's JSON contract:
    {"per_pq": [{"pq_id": "...", "grade": 0.0..1.0}, ...]}. None on any
    deviation — a malformed verifier answer is no signal at all."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("per_pq"), list):
        return None
    out: dict[str, dict] = {}
    for row in data["per_pq"]:
        if not isinstance(row, dict):
            return None
        pq, grade = row.get("pq_id"), row.get("grade")
        if not isinstance(pq, str) or not isinstance(grade, (int, float)):
            return None
        out[pq] = {"grade": max(0.0, min(1.0, float(grade)))}
    return out


def build_verifier_prompt(pqs: list[str], trajectory_digest: str) -> str:
    """Per-PQ criterion decomposition prompt (paper §3 form). The runner
    pastes this to the verifier model each checkpoint; the reply goes to
    parse_verifier_response."""
    lines = ["Grade CURRENT progress toward each primary question (0.0-1.0).",
             "Grade evidence actually on record, not plans or intent.",
             "", "Trajectory digest:", trajectory_digest, "", "Questions:"]
    lines += [f"- {pq}" for pq in pqs]
    lines += ["", 'Reply with JSON only: {"per_pq": [{"pq_id": "...", "grade": 0.0}]}']
    return "\n".join(lines)


# ---------- D(t) + ETA ----------

def update_difficulty(d_prev: float | None, trigger: str, magnitude: float) -> float:
    """Three triggers only: t0 (set prior) / capability_flip (−magnitude) /
    wear (+magnitude). Clamped to [0, 1]."""
    base = 0.5 if d_prev is None else d_prev
    if trigger == "t0":
        base = magnitude
    elif trigger == "capability_flip":
        base -= magnitude
    elif trigger == "wear":
        base += magnitude
    return max(0.0, min(1.0, float(base)))


def eta_minutes(time_budget_min: float, enumeration_coeff: float) -> float:
    """ETA = remaining budget × enumeration denominator coefficient."""
    return float(time_budget_min) * float(enumeration_coeff)


# ---------- decide() attach (flag-gated, shadow) ----------

def attach_signals(ws: Path, decision: dict) -> dict:
    """Mount point for convergence_check.decide(): flag ON → compute the
    first-order signals from the workspace priors, attach as
    decision["value_signals"], emit one shadow event. Flag OFF → return
    the decision dict untouched (no key, no files)."""
    if not value_config.is_enabled():
        return decision
    priors = {}
    p = Path(ws) / PRIORS_FILE
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            priors = data
    except (OSError, yaml.YAMLError):
        priors = {}
    spec = {}
    try:
        s = yaml.safe_load((Path(ws) / "task_spec.yaml").read_text(encoding="utf-8"))
        if isinstance(s, dict):
            spec = s
    except (OSError, yaml.YAMLError):
        pass
    depth = str(spec.get("depth") or "unknown").strip().lower()
    budget = float(spec.get("time_budget_minutes") or 0.0)
    family = value_replay.dominant_family(ws)  # same bucket derivation as A1 build_priors
    v, source, band = v_from_priors(priors, depth, family)
    difficulty = update_difficulty(None, "t0", v)  # t0 prior until a trigger lands
    eta = eta_minutes(budget, 1.0)
    sig = {"v": round(v, 4), "source": source, "error_band": round(band, 4),
           "d": round(difficulty, 4), "eta_min": round(eta, 1)}
    # #823 A4 canary graduation: doomed-trajectory early-stop signal rides
    # the same flag-gated mount (flag off -> never evaluated, byte-identical)
    try:
        import infeasible_signal
        infeasible = infeasible_signal.evaluate(Path(ws))
        sig["infeasible_candidate"] = infeasible.get("infeasible_candidate", False)
        sig["v_flat_rounds"] = infeasible.get("v_flat_rounds", 0)
    except Exception:
        sig["infeasible_candidate"] = False
    # #823-P2: checkpoint rho sampling + (rho, z) pairing rides the same
    # flag-gated mount, caged: any failure degrades to no-signal (never
    # disturb decide()). Shadow: sample_and_pair records only.
    try:
        import rho_verifier
        rho_verifier.sample_and_pair(ws)
    except Exception:  # noqa: BLE001 - shadow cage: signals never disturb
        pass
    decision["value_signals"] = sig
    kunglao_log.emit(ws, actor="rho_checkpoint", action="rho_checkpoint",
                     detail=json.dumps(sig, sort_keys=True))
    return decision


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
