# -*- coding: utf-8 -*-
"""dead_letter.py - DEAD status + quarantine for poison / exhausted claims (#36).

A claim whose `promotion_attempts >= 3` has exhausted the convergence loop's
patience — it will not close, but without a terminal status it lingers as
OPEN and is re-ranked every tick, wasting dispatch slots and cost. DEAD is
the terminal status for such claims. It lives in `status_defs.TERMINAL`
(single source of truth from #34), so `convergence_check._open_claims` and
`priority._is_open` exclude DEAD claims automatically — no per-consumer edit.

This script provides the explicit writer + quarantine artifact + diagnostics:
  - mark_dead(ws, claim_id, reason): writes status=DEAD (+ dead_at, dead_reason,
    mirroring the STALE write pattern in claim_expiry.py) and creates
    blockers/dead-letter-<claim>.md with the exit reason.
  - scan(ws): reports claims with promotion_attempts>=3 that are NOT yet
    terminal (the dangling set). Read-only.
  - detect_dirty_statuses(ws): flags status literals outside the legal enum
    (e.g. the observed `PASS-` dirty value). Read-only.

Usage:
  python dead_letter.py <workspace>                  # scan: report exhausted-but-not-DEAD
  python dead_letter.py <workspace> --mark C-NN      # mark_dead: DEAD + dead-letter artifact
  python dead_letter.py <workspace> --dirty          # detect dirty status literals
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from status_defs import (
    ACTIVE_STATUSES,
    PARTIAL_STATUSES,
    IN_PROGRESS_STATUSES,
)
# #331: RETRACTED is a legal terminal status (retraction domain owner:
# retract_claim.py). It must be legal for --dirty AND excluded from scan() —
# a retracted claim is withdrawn, not exhausted; surfacing it would induce
# mark_dead to overwrite RETRACTED -> DEAD.
from retract_claim import TERMINAL_WITH_RETRACTED

# Legacy pseudo-statuses used by convergence_check.NON_PROVEN_ANSWER — not in
# status_defs (they describe "claimed-but-unverified", not a claim lifecycle
# state) but a dirty-status linter must recognize them as legal literals.
_LEGACY_PSEUDO = {"STAMP", "UNVERIFIED"}
_LEGAL_STATUSES = (
    TERMINAL_WITH_RETRACTED | ACTIVE_STATUSES | PARTIAL_STATUSES
    | IN_PROGRESS_STATUSES | _LEGACY_PSEUDO
)


def utc_now_iso() -> str:
    """ISO-8601 UTC with a trailing Z (matches claim_expiry's STALE timestamp)."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_reg(workspace: Path) -> tuple[list, dict, Path]:
    """Return (claims, full_register, path). Empty register if file missing."""
    p = workspace / "claim-register.yaml"
    if not p.exists():
        return [], {}, p
    reg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return reg.get("claims") or [], reg, p


def _write_reg(p: Path, reg: dict) -> None:
    p.write_text(
        yaml.safe_dump(reg, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def scan(workspace: Path) -> list:
    """Ids of claims with promotion_attempts>=3 that are NOT yet terminal.

    The dangling set — claims the DLQ should consider killing. Read-only.
    Claims already DEAD (or any terminal status) short-circuit and are excluded.
    RETRACTED is excluded too (#331): retraction is a terminal verdict, not
    execution exhaustion — the DLQ must never overwrite it with DEAD.
    """
    claims, _, _ = _load_reg(workspace)
    out = []
    for c in claims:
        status = (c.get("status") or "UNKNOWN").upper()
        if status in TERMINAL_WITH_RETRACTED:
            continue
        try:
            attempts = int(c.get("promotion_attempts") or 0)
        except (TypeError, ValueError):
            attempts = 0
        if attempts >= 3:
            out.append(c.get("id"))
    return out


def count_dead(workspace: Path) -> int:
    """Number of claims already in DEAD status (the quarantined count).

    Used by worker_pulse's `quarantined=N` flag. Read-only.
    """
    claims, _, _ = _load_reg(workspace)
    return sum(1 for c in claims if (c.get("status") or "").upper() == "DEAD")


def mark_dead(workspace: Path, claim_id: str, reason: str = "") -> dict:
    """Set claim DEAD + write blockers/dead-letter-<claim>.md quarantine artifact.

    Mirrors the STALE write pattern (claim_expiry.py: status + <state>_at +
    <state>_reason). Returns {"marked": True, "claim_id", "status": "DEAD"} on
    success, or {"marked": False, "reason": ...} when the claim is absent
    (explicit REJECT — never a silent no-op, never raises).
    """
    claims, reg, p = _load_reg(workspace)
    claim = next((c for c in claims if c.get("id") == claim_id), None)
    if claim is None:
        return {"marked": False, "reason": f"claim {claim_id} not found"}

    dead_at = utc_now_iso()
    dead_reason = reason or "promotion_attempts exhausted (DLQ)"
    claim["status"] = "DEAD"
    claim["dead_at"] = dead_at
    claim["dead_reason"] = dead_reason
    _write_reg(p, reg)

    bdir = workspace / "blockers"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / f"dead-letter-{claim_id}.md").write_text(
        f"# Dead Letter: {claim_id}\n\n"
        f"- status: DEAD\n"
        f"- dead_at: {dead_at}\n"
        f"- dead_reason: {dead_reason}\n"
        f"- promotion_attempts: {claim.get('promotion_attempts')}\n"
        f"- failure history: see analyses/failure-{claim_id}.yaml\n",
        encoding="utf-8",
    )
    return {"marked": True, "claim_id": claim_id, "status": "DEAD"}


def detect_dirty_statuses(workspace: Path) -> list:
    """Ids of claims whose status literal is outside the legal enum.

    Catches dirty values like `PASS-`. Read-only — never rewrites the register.
    The legal set is computed from status_defs (single source) plus the
    STAMP/UNVERIFIED legacy pseudo-statuses.
    """
    claims, _, _ = _load_reg(workspace)
    dirty = []
    for c in claims:
        status = (c.get("status") or "").strip()
        if not status:
            continue
        if status not in _LEGAL_STATUSES:
            dirty.append(c.get("id"))
    return dirty


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="dead_letter.py",
        description="DLQ — DEAD status + quarantine for poison / exhausted claims (#36)",
    )
    parser.add_argument("workspace", help="workspace root (contains claim-register.yaml)")
    parser.add_argument("--mark", metavar="C-NN", help="mark claim DEAD (writes dead-letter artifact)")
    parser.add_argument("--reason", default="", help="exit reason recorded in the dead-letter artifact")
    parser.add_argument("--dirty", action="store_true", help="detect dirty status literals (e.g. PASS-)")
    args = parser.parse_args()

    ws = Path(args.workspace)

    if args.mark:
        r = mark_dead(ws, args.mark, reason=args.reason)
        if r.get("marked"):
            print(f"MARKED DEAD: {r['claim_id']} (blockers/dead-letter-{r['claim_id']}.md)")
            return 0
        print(f"REJECTED: {r.get('reason')}", file=sys.stderr)
        return 1

    if args.dirty:
        dirty = detect_dirty_statuses(ws)
        print(f"{len(dirty)} dirty status value(s): {dirty}")
        return 1 if dirty else 0

    exhausted = scan(ws)
    print(f"{len(exhausted)} exhausted-but-not-DEAD claim(s): {exhausted}")
    return 1 if exhausted else 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
