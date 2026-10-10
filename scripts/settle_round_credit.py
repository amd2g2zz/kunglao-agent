#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""settle_round_credit.py - #634: the LIVE round-credit settlement feed.

The dispatch observations (worker_budget_sinks -> q_cells) accumulate as
pending mass; ``rlvr.scalar.settle_round_credit`` - the ONE face that
grades the issue-433 ladder credit and banks it into the matching Q cell
(#462 W5) - had NO live caller (only compat re-exports and the eval
harness). This CLI is that caller, wired as the registry mechanism
``credit_settle`` (channel: tick): per pass it assembles one round per
TERMINAL claim (``dispatch_id`` = the claim id - the dispatch ALLOW
tail's echo / ``observe_settlement``'s match key) plus the fact-artifact
rows (``rlvr.scalar.fact_artifacts``) and runs the settlement.

Idempotent at any wall-clock distance: the identity-ts freeze plus the
settlement-presence guard inside settle_round_credit dedupe record and
settle (re-runs are byte-identical no-ops). No terminal claim -> no work.

Eager-banking note (#462 W5, by design): the FIRST successful settlement
of a dispatch banks its then-current ladder value into the Q cell; the
late-cite amendment path refines the LEDGER only (the observation log is
append-only, so re-banking would double-count). The ladder grades what
EXISTS - verified-but-uncited facts read as trace, and a missing pending
dispatch row is the honest gap (a rate-limited warn, never a fabricated
bucket).

Usage:
  python settle_round_credit.py <workspace> [--json]
Exit codes: 0 ok (including nothing-to-do) / 2 usage / 3 not a workspace.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def terminal_claims(ws: Path) -> list[str]:
    """Claim ids whose register status is terminal (the settlement set).

    Tolerant read: unreadable/invalid register -> empty set (nothing to
    settle is never an error for this telemetry face)."""
    import yaml

    from status_defs import TERMINAL
    try:
        doc = yaml.safe_load(
            (ws / "claim-register.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    out: list[str] = []
    for c in (doc or {}).get("claims") or []:
        if not isinstance(c, dict) or not c.get("id"):
            continue
        if str(c.get("status") or "").upper() in TERMINAL:
            out.append(str(c["id"]))
    return out


def run(ws: Path, *, dry_run: bool = False) -> dict:
    """Assemble + settle one pass. Telemetry posture: any failure inside
    degrades to an error field, never a crash (the tick must not die).
    dry_run assembles and grades only — no ledger rows, no Q-cell bank."""
    claims = terminal_claims(ws)
    if not claims:
        return {"settled": 0, "rounds": 0,
                "reason": "no terminal claims - nothing to settle"}
    dispatches = [{"dispatch_id": cid, "round": i + 1}
                  for i, cid in enumerate(claims)]
    try:
        from rlvr.scalar import fact_artifacts
        artifacts = fact_artifacts(ws)
        if dry_run:
            from rlvr.scalar import round_credit
            doc = round_credit(dispatches, artifacts, [])
            return {"settled": 0, "rounds": len(dispatches),
                    "artifacts": len(artifacts), "dry_run": True,
                    "would_settle": len(doc.get("rows") or []),
                    "untraced": len(doc.get("untraced") or []),
                    "rewards": [r.get("r") for r in doc.get("rows") or []]}
        from rlvr.scalar import settle_round_credit
        res = settle_round_credit(ws, dispatches, artifacts, [])
    except Exception as exc:  # noqa: BLE001 - telemetry face, never a gate
        return {"settled": 0, "rounds": len(dispatches),
                "error": f"{type(exc).__name__}: {exc}"}
    return {"settled": int(res.get("settled") or 0),
            "rounds": len(dispatches), "artifacts": len(artifacts),
            "untraced": len(res.get("untraced") or []),
            "unattributed_waste": res.get("unattributed_waste", 0)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="#634 live round-credit settlement feed")
    ap.add_argument("workspace")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="assemble + grade only; no ledger rows, no bank")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    if not (ws / "claim-register.yaml").is_file():
        print(f"settle_round_credit: not a kunglao workspace: {ws}",
              file=sys.stderr)
        return 3
    out = run(ws, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print("settle_round_credit: " + ", ".join(
            f"{k}={v}" for k, v in out.items()))
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)

    force_utf8()
    sys.exit(main())
