#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/incremental_reward.py — potential-based per-act reward + the
transition ledger (issue #539 Phase B, PR-1).

The 2026-10-06 owner ruling reframes kunglao as an external SMDP over a
frozen model: every dispatch→outcome pair must produce a TRANSITION
(s, a, o, s', r) and a per-act INCREMENTAL reward, because the one-shot
settlement credit gives ordinary tool success zero signal (the owner's
attribution gap). This module is pure instrumentation — no behavior
change, no sampling change, no critic.

Reward form (design doc docs/design/external-smdp-phase-b.md §2):

    r_t = ALPHA * [Φ(s') - Φ(s)] - LAMBDA * cost_t
    Φ(s) = W_FACTS * verified_facts_fraction + W_ORACLE * oracle_green_rate

Φ is a potential function — potential-based shaping (Ng, Harada & Russell
1999) preserves the optimal-policy order, so layering it over the
terminal settlement credit cannot corrupt the task objective. All four
coefficients are DOCUMENTED POLICY CONSTANTS (the state.py precedent:
"policy constants, not fitted parameters") — the whole phase adds at
most three; ALPHA/LAMBDA ride at 1.0 until the offline comparison says
otherwise.

The transition ledger is append-only runs/transitions.jsonl — the s'
face the 2026-09-27 quadruple-rejection pin denied; the 2026-10-06
ruling (external SMDP, transition recording authorized) overturns that
pin (see scripts/rlvr/triples.py's docstring pin block for the citation).
"""
from __future__ import annotations

import json

from _common import utc_now_z
from pathlib import Path

from rlvr.state import fact_face, _oracle_status_progress

TRANSITIONS_REL = "runs/transitions.jsonl"
LAUNCH_REL = "runs/dispatch-launch-{claim}.json"
# #550: action-type-scoped stashes — a verify/red-team act keeps its own
# stash so it never clobbers a pending dispatch stash for the same claim
# (the untyped path stays byte-identical for in-flight workspaces).
LAUNCH_REL_TYPED = "runs/dispatch-launch-{claim}--{action_type}.json"

# ---- policy constants (design doc §2; NOT fitted) ------------------------
ALPHA = 1.0          # potential-difference weight
LAMBDA_COST = 1.0    # cost weight
W_FACTS = 0.3        # Φ: verified-facts fraction weight
W_ORACLE = 0.5       # Φ: oracle green-rate weight
COST_TOKENS_DIV = 10_000.0   # normalize: 10k tokens = 1 cost unit
COST_SECONDS_DIV = 3_600.0   # normalize: 1 wall hour = 1 cost unit


def potential(ws) -> float:
    """Φ(s) ∈ [0, 1]: verified-facts fraction + oracle green rate,
    renormalized over PRESENT dims (a missing organ drops its dim —
    the honest-absence doctrine, state.py precedent)."""
    ws = Path(ws)
    parts: list[tuple[float, float]] = []  # (weight, value)
    ff = fact_face(ws)
    if ff["count"] > 0:
        parts.append((W_FACTS, ff["verified"] / ff["count"]))
    oracle = _oracle_status_progress(ws)
    if oracle is not None:
        passed, total = oracle
        parts.append((W_ORACLE, passed / total if total else 0.0))
    if not parts:
        return 0.0
    wsum = sum(w for w, _ in parts)
    return sum(w * v for w, v in parts) / wsum


def incremental_reward(phi_before: float, phi_after: float, *,
                       tokens: float = 0.0, seconds: float = 0.0) -> float:
    """r_t = ALPHA·ΔΦ − LAMBDA·cost. Both terms are bounded: ΔΦ ∈ [−1,1],
    cost normalized to hours-equivalent scale."""
    cost = tokens / COST_TOKENS_DIV + seconds / COST_SECONDS_DIV
    return round(ALPHA * (phi_after - phi_before) - LAMBDA_COST * cost, 6)


def _launch_path(ws: Path, claim: str, action_type: str) -> Path:
    """The stash path for one action type: ""/"dispatch" keeps the
    legacy untyped filename (in-flight workspaces keep working); any
    other type lands the scoped sibling (#550)."""
    if action_type in ("", "dispatch"):
        return ws / LAUNCH_REL.format(claim=claim)
    return ws / LAUNCH_REL_TYPED.format(claim=claim, action_type=action_type)


def verify_credit(verdict: str) -> float:
    """#550: the verifier verdict -> settle credit. verified / CONFIRMED
    bank 1.0 (an adversarial pass that failed to refute IS success);
    refuted, unverified-with-gap, timeout, and everything else bank 0.0
    — an unverifiable verification decided nothing."""
    return 1.0 if str(verdict).strip().lower() == "verified" \
        or str(verdict).strip().upper() == "CONFIRMED" else 0.0


def record_launch(ws, claim: str, action_key: str, phi: float | None = None,
                  s_hash: str = "", propensity: float | None = None,
                  action_type: str = "dispatch",
                  variant: str = "") -> None:
    """Stash the launch-side state at dispatch time — the settle face
    reads it to close the transition. Fail-open telemetry: never raises
    into the dispatch path. #550: action_type scopes the stash (a verify
    act cannot clobber a pending dispatch stash); the variant marker
    (verify | redteam) rides the doc for the row's provenance."""
    try:
        ws = Path(ws)
        p = _launch_path(ws, claim, action_type)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "ts": utc_now_z(),
            "claim": str(claim),
            "a": str(action_key),
            "s": str(s_hash),
            "phi": potential(ws) if phi is None else float(phi),
            "action_type": str(action_type or "dispatch"),
            **({"variant": str(variant)} if variant else {}),
            **({"propensity": float(propensity)}
               if propensity is not None else {}),
        }), encoding="utf-8")
    except OSError as exc:  # telemetry, never the producer — but loud (#275)
        from kunglao_log import warn  # noqa: PLC0415
        warn("incremental_reward.record_launch",
             f"{type(exc).__name__}: {exc}")


def append_transition(ws, claim: str, outcome: str, *,
                      status: str = "", facts: int = 0,
                      tokens: float = 0.0, seconds: float = 0.0,
                      r_settle: float | None = None,
                      done: bool = False,
                      action_type: str = "dispatch",
                      variant: str = "",
                      lift: float | None = None) -> dict | None:
    """Close one transition: read the launch stash, compute Φ(s′) and
    r_t, append the row. Returns the row (None when no launch stash —
    a settle without a recorded launch logs nothing rather than
    inventing a before-state). Fail-open telemetry. #550: the stash is
    action-type-scoped (verify acts close against their own stash) and
    the row carries the additive action_type column plus the o.variant
    provenance marker when set. The optional lift argument rides the
    row as an additive weight column (absent when not supplied)."""
    try:
        ws = Path(ws)
        launch_p = _launch_path(ws, claim, action_type)
        if not launch_p.is_file():
            return None
        launch = json.loads(launch_p.read_text(encoding="utf-8"))
        phi_after = potential(ws)
        r_incr = incremental_reward(
            float(launch.get("phi", 0.0)), phi_after,
            tokens=tokens, seconds=seconds)
        row = {
            "ts": utc_now_z(),
            "dispatch_id": str(claim),
            "action_type": str(launch.get("action_type")
                               or action_type or "dispatch"),
            "s": str(launch.get("s") or ""),
            "a": str(launch.get("a") or ""),
            "o": {"status": str(outcome), "class": str(status),
                  "facts": int(facts),
                  **({"variant": str(variant
                                     or launch.get("variant") or "")}
                     if variant or launch.get("variant") else {})},
            "s_prime_phi": round(phi_after, 6),
            "phi_before": round(float(launch.get("phi", 0.0)), 6),
            "r_incr": r_incr,
            "r_settle": (round(float(r_settle), 6)
                         if r_settle is not None else None),
            "done": bool(done),
            **({"lift": round(float(lift), 6)}
               if lift is not None else {}),
            **({"propensity": launch["propensity"]}
               if launch.get("propensity") is not None else {}),
        }
        out = ws / TRANSITIONS_REL
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        launch_p.unlink(missing_ok=True)  # stash consumed
        return row
    except (OSError, ValueError, TypeError) as exc:  # loud telemetry (#275)
        from kunglao_log import warn  # noqa: PLC0415
        warn("incremental_reward.append_transition",
             f"{type(exc).__name__}: {exc}")
        return None  # telemetry, never the producer


def read_transitions(ws) -> list[dict]:
    """The ledger read face: all rows, oldest first; absent = []."""
    p = Path(ws) / TRANSITIONS_REL
    if not p.is_file():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8",
                            errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows
