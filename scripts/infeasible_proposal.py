#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""infeasible_proposal.py - #815 early-stop wiring.

Blueprint 7.3 proposal semantics: INFEASIBLE is a CLAIM requiring evidence,
not a property of the V-curve. Recovery ladder L1/L2/L3 complete + attempt
inventory non-empty + wake_condition non-empty + signal already run ->
file DEFERRED; anything missing -> REJECT with ZERO register change
(fail-closed structural gate).

DEFERRED is in status_defs.TERMINAL -> every consumer auto-excludes the
claim from dispatch, zero consumer edits. Audit artifact
runs/infeasible-proposal-<claim>.md freezes the attempt inventory
(clawback interface reserved: artifact carries the claim anchor; P4
settlement reconciles against it).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

import kunglao_log

LADDER_LEVELS = ("L1", "L2", "L3")
SIGNAL_STATE = "runs/infeasible-state.json"


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_reg(ws: Path):
    p = ws / "claim-register.yaml"
    if not p.exists():
        return [], {}, p
    reg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return reg.get("claims") or [], reg, p


def _write_reg(p: Path, reg: dict) -> None:
    p.write_text(
        yaml.safe_dump(reg, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _load_ladder(ws: Path, claim_id: str):
    """runs/infeasible-ladder-<claim>.yaml -> dict, or None."""
    p = ws / "runs" / f"infeasible-ladder-{claim_id}.yaml"
    if not p.exists():
        return None
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def ladder_gaps(ladder: dict | None) -> list:
    """Missing recovery-ladder levels: [] only when L1+L2+L3 all covered."""
    if not isinstance(ladder, dict):
        return list(LADDER_LEVELS)
    seen = set()
    for a in ladder.get("attempts") or []:
        if isinstance(a, dict):
            seen.add(str(a.get("level") or "").strip().upper())
    return [lv for lv in LADDER_LEVELS if lv not in seen]


def _inventory_empty(ladder: dict) -> bool:
    inv = (ladder or {}).get("inventory")
    return not isinstance(inv, list) or len(inv) == 0


def file_proposal(ws, claim_id: str, wake_condition: str = "",
                  ladder: dict | None = None) -> dict:
    """File an INFEASIBLE proposal: DEFERRED with wake_condition, gated on
    the recovery ladder + attempt inventory + signal precondition.

    Fail-closed: any missing requirement -> {"filed": False, "reason"} with
    ZERO register mutation. Returns {"filed": True, claim_id, status} on
    success.
    """
    ws = Path(ws)
    if not (ws / SIGNAL_STATE).exists():
        return {"filed": False,
                "reason": "infeasible signal precondition: " + SIGNAL_STATE
                          + " missing - run the doomed-trajectory signal "
                            "before filing (no V-curve = no verdict)"}

    ladder_data = ladder if ladder is not None else _load_ladder(ws, claim_id)
    gaps = ladder_gaps(ladder_data)
    if gaps:
        return {"filed": False,
                "reason": "recovery ladder incomplete - missing: "
                          + ",".join(gaps) + " (walk L1/L2/L3 first)"}
    if _inventory_empty(ladder_data):
        return {"filed": False,
                "reason": "attempt inventory empty - list what was tried "
                          "and why each approach failed"}
    if not str(wake_condition or "").strip():
        return {"filed": False,
                "reason": "wake_condition required - a PARK/DEFERRED claim "
                          "must say what would revive it"}

    claims, reg, p = _load_reg(ws)
    claim = next((c for c in claims if c.get("id") == claim_id), None)
    if claim is None:
        return {"filed": False, "reason": f"claim {claim_id} not found"}
    status = (claim.get("status") or "").upper()
    if status in ("PROVEN", "VERIFIED", "NEGATIVE", "REFUTED", "DEFERRED",
                  "STALE", "SUPERSEDED", "DEAD"):
        return {"filed": False,
                "reason": f"claim {claim_id} already terminal ({status}) - "
                          f"INFEASIBLE never overwrites a terminal state"}

    now = utc_now_iso()
    claim["status"] = "DEFERRED"
    claim["deferred_at"] = now
    claim["deferred_reason"] = "infeasible"
    claim["wake_condition"] = wake_condition.strip()
    claim["infeasible_ladder"] = f"runs/infeasible-ladder-{claim_id}.yaml"
    _write_reg(p, reg)

    audit = ws / "runs" / f"infeasible-proposal-{claim_id}.md"
    inv_rows = "\n".join(
        f"- tried: {i.get('tried')} - failed: {i.get('failed_because')}"
        for i in ladder_data.get("inventory") or [])
    att_rows = "\n".join(
        f"- {a.get('level')}: {a.get('action')} -> {a.get('outcome')}"
        for a in ladder_data.get("attempts") or [])
    audit.write_text(
        f"# INFEASIBLE proposal: {claim_id}\n\n"
        f"- filed_at: {now}\n- wake_condition: {wake_condition.strip()}\n"
        f"- ladder: {claim['infeasible_ladder']}\n\n"
        f"## recovery ladder\n{att_rows}\n\n"
        f"## attempt inventory\n{inv_rows}\n\n"
        f"(clawback anchor: claim {claim_id} - P4 settlement reconciles "
        f"against this artifact)\n",
        encoding="utf-8")
    kunglao_log.emit(ws, actor="infeasible_proposal",
                     action="infeasible_filed",
                     claim=claim_id,
                     detail=f"wake={wake_condition.strip()}")
    return {"filed": True, "claim_id": claim_id, "status": "DEFERRED"}


def wake(ws, claim_id: str, reason: str = "") -> dict:
    """Revive an infeasible-DEFERRED claim back to OPEN (explicit face).

    REJECT (no mutation) for: non-DEFERRED, DEFERRED without
    deferred_reason=infeasible, terminal claims, empty reason.
    """
    ws = Path(ws)
    if not str(reason or "").strip():
        return {"woken": False, "reason": "wake reason required"}
    claims, reg, p = _load_reg(ws)
    claim = next((c for c in claims if c.get("id") == claim_id), None)
    if claim is None:
        return {"woken": False, "reason": f"claim {claim_id} not found"}
    status = (claim.get("status") or "").upper()
    if status != "DEFERRED":
        return {"woken": False,
                "reason": f"claim {claim_id} is {status or 'UNKNOWN'} - "
                          f"only infeasible-DEFERRED claims wake"}
    if (claim.get("deferred_reason") or "") != "infeasible":
        return {"woken": False,
                "reason": f"claim {claim_id} is DEFERRED for "
                          f"'{claim.get('deferred_reason')}' - not infeasible"}
    now = utc_now_iso()
    claim["status"] = "OPEN"
    claim["woken_at"] = now
    claim["wake_reason"] = reason.strip()
    _write_reg(p, reg)
    kunglao_log.emit(ws, actor="infeasible_proposal",
                     action="infeasible_woken",
                     claim=claim_id, detail=f"reason={reason.strip()}")
    return {"woken": True, "claim_id": claim_id, "status": "OPEN"}


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="infeasible_proposal.py",
        description="#815 early-stop: gated INFEASIBLE proposal + wake face")
    parser.add_argument("workspace")
    parser.add_argument("--file", metavar="C-NN")
    parser.add_argument("--wake", metavar="C-NN")
    parser.add_argument("--wake-condition", default="")
    parser.add_argument("--reason", default="")
    args = parser.parse_args()
    ws = Path(args.workspace)
    if args.file:
        r = file_proposal(ws, args.file, wake_condition=args.wake_condition)
        print(r)
        return 0 if r["filed"] else 1
    if args.wake:
        r = wake(ws, args.wake, reason=args.reason)
        print(r)
        return 0 if r["woken"] else 1
    parser.print_help()
    return 2


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
