#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""adversarial_gate — mechanical teeth for verdict-scorer sign-off.

A redteam challenge that has not been resolved BLOCKS the signature.
This gate is the mechanism behind that sentence.

It is MECHANICAL, not discretionary: the scorer has no override path,
exactly like check_proven_gate has no override for promotion_attempts.

Anti-forgery posture: the gate consumes the
ORCHESTRATOR-SUMMARY of the claim's adversarial ledger and
authenticates it with the orchestrator-side key before trusting any
field in it. A worker that reverse-engineered the whole validation
stack still cannot mint a passing summary without the key.

Returns (allowed, verdict, reason) — mirrors
blind_gate.check_proven_gate's (allowed, effective_status, reason):
  allowed=True  verdict=SIGNED   sign-off may proceed
  allowed=False verdict=BLOCKED  signature refused (see reason)
"""
from __future__ import annotations

from pathlib import Path

import challenge_ledger as cl

SIGNED = "SIGNED"
BLOCKED = "BLOCKED"


def check_adversarial_gate(
    claim_id: str,
    ws: Path,
    *,
    key: bytes,
    summary: dict | None = None,
    opened_hint: bool = False,
    opened_max_rounds: int | None = None,
) -> tuple[bool, str, str]:
    """Signature-gate check for a claim's adversarial state.

    claim_id:     the claim about to be signed (e.g. 'C-12')
    ws:           workspace root (runs/challenges/ lives under it)
    key:          the orchestrator-side HMAC key (review_gate precedent —
                  lives only in orchestrator process context)
    summary:      optional pre-computed orchestrator summary; when omitted,
                  the gate computes it itself (orchestrator-side usage).
    opened_hint:  orchestrator-side register view ("this claim opened an
                  adversarial loop"): a worker deleting
                  runs/challenges/<claim>/ otherwise flips the gate to
                  'never opened' — the register cross-check makes
                  deletion block instead.
    opened_max_rounds:  monotonic anchor — the register's highest
                  round count ever observed for this claim. The ledger's
                  rounds count may never be LOWER: truncating rounds or
                  rolling back the head to resurrect a stale all-clear
                  is caught by the mismatch. The orchestrator updates
                  the register monotonically after every adversarial
                  act; only a higher value sticks.

    An unopened ledger (no runs/challenges/<claim>/ AND no opened_hint)
    is transparent: sign-off proceeds — the adversarial loop never
    opened for this claim.
    """
    led_dir = Path(ws) / "runs" / "challenges" / claim_id
    if not led_dir.is_dir():
        if opened_hint:
            return (False, BLOCKED,
                    "adversarial ledger deleted while the claim register "
                    "records an opened loop — deletion is tampering")
        return (True, SIGNED, "no adversarial ledger — loop never opened")

    if summary is None:
        summary = cl.summary(ws, claim_id, key=key)

    # anti-forgery: authenticate BEFORE trusting any field;
    # ws+claim enable the freshness check (stale all-clear replay dies)
    if not cl.authenticate_summary(summary, key=key, ws=ws, claim=claim_id):
        return (False, BLOCKED,
                "adversarial summary failed authentication — forged or "
                "minted with the wrong key (the trust root is the "
                "orchestrator key, not the ledger state)")

    if not summary.get("chain_ok", False):
        return (False, BLOCKED,
                f"adversarial ledger chain broken: "
                f"{summary.get('chain_why', '?')} — tamper evidence")

    # monotonic round anchor — the register remembers the high-
    # water mark; a ledger whose rounds fell below it was truncated or
    # rolled back.
    if opened_max_rounds is not None:
        seen = int(summary.get("rounds", 0))
        if seen < int(opened_max_rounds):
            return (False, BLOCKED,
                    f"adversarial ledger truncated: register recorded "
                    f"{opened_max_rounds} rounds but the ledger now shows "
                    f"{seen} — rollback/truncation is tampering")

    open_ids = summary.get("open_challenges", [])
    if open_ids:
        return (False, BLOCKED,
                f"open adversarial challenges unresolved: "
                f"{', '.join(open_ids)} — redteam opposition must be "
                f"rebutted or arbitrated before sign-off")

    return (True, SIGNED, "adversarial state clean — sign-off may proceed")
