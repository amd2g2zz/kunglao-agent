#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""planning_actions.py — the policy tier's escrow/revoke attribution face.

The guardrail on candidate-set changes: every settleable action (the
``policy.*`` registry entries, ActionSpec.settleable) must be
REVERSIBLE and ATTRIBUTABLE. A supersede that later refutes is revoked
against the step that PROPOSED it — never against a verifier or
consumer step — the same escrow/revoke discipline evidence credit
rides (scripts/rlvr/step_ledger.py).

This module is the recording half only:

  - record(ws, action, step_ref, ...)  one planning-action/1 row in
    runs/planning-actions.jsonl, carrying the producing step_ref, the
    optional claim reference, and the sampling propensity (policy
    actions are CHOSEN, so the propensity rides beside the choice —
    the same column the transition ledger carries);
  - revoke(ws, action_id, reason)      one planning-revoke/1 row naming
    the action and its producing step (the revoke target is resolved
    from the recorded action — the caller cannot point it elsewhere);
  - read_actions(ws)                   the row read face.

Refusals are explicit: an action outside the settleable tier, a
missing action id, or an already-revoked action return None with ONE
warn trace (fail-open — the caller degrades, never crashes). The
consumption face (pricing revoked planning actions, closing their
escrow) belongs to the settlement channel and lands with the
controller; this slice records and attributes only.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from _common import utc_now_z
from kunglao_log import warn

PLANNING_LEDGER_REL = "runs/planning-actions.jsonl"
ACTION_SCHEMA = "planning-action/1"
REVOKE_SCHEMA = "planning-revoke/1"


def record(ws, action: str, *, step_ref: str, claim_ref: str = "",
           propensity: float | None = None,
           detail: str = "") -> dict | None:
    """Append one planning-action/1 row. Returns the row, or None on
    refusal (non-settleable action, empty step_ref, illegal propensity)
    with ONE warn each — fail-open, never raises into the caller.

    ``propensity`` is the sampling probability of this action under the
    acting policy; it must lie in [0, 1] when given (absent = the row
    predates propensity logging, same additive-column posture as the
    transition ledger)."""
    from action_space import ACTIONS  # lazy: registry single-source, no cycle
    if str(action) not in ACTIONS or not ACTIONS[str(action)].settleable:
        warn("planning_actions.record",
             f"refused {action!r}: not a settleable policy-tier action")
        return None
    if not str(step_ref or "").strip():
        warn("planning_actions.record",
             f"refused {action!r}: empty step_ref — a planning action "
             f"must name its producing step")
        return None
    prop: float | None = None
    if propensity is not None:
        try:
            prop = float(propensity)
        except (TypeError, ValueError):
            warn("planning_actions.record",
                 f"refused {action!r}: propensity {propensity!r} is not "
                 f"numeric")
            return None
        if not 0.0 <= prop <= 1.0:
            warn("planning_actions.record",
                 f"refused {action!r}: propensity {prop} outside [0, 1]")
            return None
    row = {
        "schema": ACTION_SCHEMA,
        "ts": utc_now_z(),
        "id": uuid.uuid4().hex[:12],
        "action": str(action),
        "step_ref": str(step_ref),
        "claim_ref": str(claim_ref or ""),
        **({"propensity": prop} if prop is not None else {}),
        **({"detail": str(detail)} if detail else {}),
    }
    try:
        p = Path(ws) / PLANNING_LEDGER_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row
    except OSError as exc:  # telemetry, never the producer — but loud
        warn("planning_actions.record", f"{type(exc).__name__}: {exc}")
        return None


def _rows(ws, schema: str) -> list[dict]:
    p = Path(ws) / PLANNING_LEDGER_REL
    if not p.is_file():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8",
                            errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("schema") == schema:
            out.append(row)
    return out


def read_actions(ws) -> list[dict]:
    """All planning-action/1 rows, oldest first; absent ledger = []."""
    return _rows(ws, ACTION_SCHEMA)


def revoke(ws, action_id: str, *, reason: str = "") -> dict | None:
    """Append one planning-revoke/1 row against a RECORDED action. The
    revoke names the action's producing step_ref (resolved from the
    ledger — the caller never points the revoke target). One revoke per
    action: a second revoke, or an unknown id, is refused with ONE warn
    (None — fail-open)."""
    prior = [r for r in _rows(ws, ACTION_SCHEMA)
             if str(r.get("id") or "") == str(action_id)]
    if not prior:
        warn("planning_actions.revoke",
             f"refused revoke of {action_id!r}: no such planning action")
        return None
    already = [r for r in _rows(ws, REVOKE_SCHEMA)
               if str(r.get("action_id") or "") == str(action_id)]
    if already:
        warn("planning_actions.revoke",
             f"refused revoke of {action_id!r}: already revoked "
             f"(one revoke per action)")
        return None
    src = prior[-1]
    row = {
        "schema": REVOKE_SCHEMA,
        "ts": utc_now_z(),
        "id": uuid.uuid4().hex[:12],
        "action_id": str(action_id),
        "action": "revoke",
        "step_ref": str(src.get("step_ref") or ""),
        "reason": str(reason or ""),
    }
    try:
        p = Path(ws) / PLANNING_LEDGER_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row
    except OSError as exc:
        warn("planning_actions.revoke", f"{type(exc).__name__}: {exc}")
        return None


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="planning_actions — record and revoke settleable "
                    "policy-tier actions (the candidate-set controls)")
    ap.add_argument("workspace", help="workspace root (runs/)")
    ap.add_argument("--list", action="store_true",
                    help="print the recorded planning actions")
    ap.add_argument("--revoke", metavar="ACTION_ID",
                    help="revoke a recorded planning action against its "
                         "producing step")
    ap.add_argument("--reason", default="",
                    help="revocation reason (with --revoke)")
    a = ap.parse_args(argv)
    if a.list:
        for r in read_actions(a.workspace):
            revoked = any(
                x.get("action_id") == r.get("id")
                for x in _rows(a.workspace, REVOKE_SCHEMA))
            print(f"{r['id']} {r['action']} step={r['step_ref']} "
                  f"claim={r.get('claim_ref') or '-'} "
                  f"propensity={r.get('propensity', '-')} "
                  f"{'REVOKED' if revoked else 'active'}")
        return 0
    if a.revoke:
        row = revoke(a.workspace, a.revoke, reason=a.reason)
        if row is None:
            return 1
        print(f"REVOKED {row['action_id']} against step {row['step_ref']}")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    import sys
    sys.exit(main())
