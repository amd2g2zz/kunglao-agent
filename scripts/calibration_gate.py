# -*- coding: utf-8 -*-
"""calibration_gate — delivery-time calibration check (#204).

Every delivered claim must carry `confidence` (0..1) and a `falsifier`
(the evidence that would overturn the claim). Absence = incomplete, and
the completion transaction treats it as such. P0 checks presence +
range only; score-vs-outcome calibration lands in P2 (recall receipts).
"""
from __future__ import annotations


def check_claim(claim: dict) -> tuple[bool, str]:
    cid = claim.get("id", "?")
    conf = claim.get("confidence")
    if conf is None:
        return (False, f"claim {cid} missing confidence — cannot deliver un-calibrated claim")
    try:
        f = float(conf)
    except (TypeError, ValueError):
        return (False, f"claim {cid} confidence {conf!r} is not numeric")
    if not 0.0 <= f <= 1.0:
        return (False, f"claim {cid} confidence {f} out of range [0,1]")
    falsifier = claim.get("falsifier")
    if not falsifier or not str(falsifier).strip():
        return (False, f"claim {cid} missing falsifier — cannot deliver un-falsifiable claim")
    return (True, f"claim {cid} calibrated (confidence={f})")


def check_register(register: dict) -> tuple[bool, list[str]]:
    problems = []
    for c in register.get("claims") or []:
        if (c.get("status") or "").upper() in ("PROVEN", "VERIFIED"):
            ok, reason = check_claim(c)
            if not ok:
                problems.append(reason)
    return (not problems, problems)
