# -*- coding: utf-8 -*-
"""dead_letter.py - DEAD status + quarantine for poison / exhausted claims (#36).

A claim whose `promotion_attempts >= 3` has exhausted the convergence loop's
patience — it will not close, but without a terminal status it lingers as
OPEN and is re-ranked every tick, wasting dispatch slots and cost. DEAD is
the terminal status for such claims. It lives in `status_defs.TERMINAL`
(single source of truth from #34), so `convergence_check._open_claims` and
`priority._is_open` exclude DEAD claims automatically — no per-consumer edit.

This script provides the explicit writer + quarantine artifact + diagnostics:
  - record_dispatch_failure(ws, claim_id) (#234): the live promotion_attempts
    writer (the dispatch-failure path). At the 3-strike threshold it
    escalates to the charter MUST-ASK lane (blockers/must-ask-<claim>.md +
    the must_ask event, status untouched) — DEAD is one explicit --mark
    decision away, never a synchronous hook-time flip (review F6).
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


from harness_common import utc_now_z as utc_now_iso  # #863 Family F: single source (was a local def)

# The 3-strike threshold (#36 family, same value as
# hooks/worker_budget_core.MAX_PROMOTION_ATTEMPTS #520 — cross-linked by
# comment, not import: scripts must not import hooks). #234 gave the family
# its live writer: record_dispatch_failure counts dispatch failures up to
# this threshold, then escalates to the charter must-ask lane (review F6);
# DEAD stays the explicit --mark face.
DLQ_ATTEMPTS = 3


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
        if attempts >= DLQ_ATTEMPTS:
            out.append(c.get("id"))
    return out


def count_dead(workspace: Path) -> int:
    """Number of claims already in DEAD status (the quarantined count).

    Used by worker_pulse's `quarantined=N` flag. Read-only.
    """
    claims, _, _ = _load_reg(workspace)
    return sum(1 for c in claims if (c.get("status") or "").upper() == "DEAD")


def record_dispatch_failure(workspace: Path, claim_id: str) -> dict:
    """Count one dispatch failure on a claim; at DLQ_ATTEMPTS route to the DLQ.

    #234: promotion_attempts was seeded at obstacle promotion
    (failure_analysis_gate.py:577) but had NO live writer anywhere — #146
    removed it from the arming predicate precisely because it never fired.
    This is that writer: the dispatch-failure path (hooked from
    hooks/worker_budget_sinks.post_check, the Agent PostToolUse completion
    sink) calls it when a finished worker's terminal status is
    failed/blocked/error.

    - non-terminal claim: promotion_attempts += 1 (register rewrite);
      at >= DLQ_ATTEMPTS the claim escalates to the charter MUST-ASK lane
      (review F6): blockers/must-ask-<claim>.md + the `must_ask` event —
      the claim KEEPS its non-terminal status so the ask gate
      (find_ladder_exhaustion, pa >= 3) HARD_PAUSEs the orchestrator
      instead of the loop self-resolving. mark_dead (DEAD + dead-letter
      artifact) stays the EXPLICIT post-mortem face (--mark); the DLQ
      route survives, the synchronous auto-DEAD does not. An escalation
      artifact-write failure never raises (review r2 LOW): it warns and
      reports must_ask.escalated=False with the reason — the strike still
      counts.
    - terminal claim: explicit no-op {"incremented": False, "reason":
      "terminal ..."} — a settled claim must not accrue strikes.
    - missing claim: {"incremented": False, "reason": ...} — explicit,
      never raises, never a silent no-op.
    """
    claims, reg, p = _load_reg(workspace)
    claim = next((c for c in claims if c.get("id") == claim_id), None)
    if claim is None:
        return {"incremented": False,
                "reason": f"claim {claim_id} not found"}
    status = (claim.get("status") or "").upper()
    if status in TERMINAL_WITH_RETRACTED:
        return {"incremented": False,
                "reason": f"claim {claim_id} terminal ({status}) - a "
                          f"settled claim does not accrue strikes"}
    try:
        attempts = int(claim.get("promotion_attempts") or 0)
    except (TypeError, ValueError):
        attempts = 0
    attempts += 1
    claim["promotion_attempts"] = attempts
    _write_reg(p, reg)
    out: dict = {"incremented": True, "claim_id": claim_id,
                 "attempts": attempts}
    if attempts >= DLQ_ATTEMPTS:
        out["must_ask"] = _escalate_must_ask(workspace, claim_id, attempts)
    return out


def _escalate_must_ask(workspace: Path, claim_id: str, attempts: int) -> dict:
    """Strike DLQ_ATTEMPTS -> the charter must-ask lane (review F6), NOT a
    synchronous DEAD flip.

    The charter's 工具/资源耗尽 row (agent-three-state-charter.md): ladder
    exhaustion at promotion_attempts >= 3 stays must-ask — the orchestrator
    MUST NOT self-resolve further. Flipping the claim DEAD inside the
    PostToolUse hook would preempt that ask: the claim would leave
    open_ids before the ask-gate tick, and the ask lane would only ever
    see a post-mortem DEAD claim. So the escalation writes the must-ask
    blocker artifact (surfaces via convergence _active_blockers) + the
    `must_ask` structured event, and leaves the status untouched. The DLQ
    remains one explicit decision away: `dead_letter.py <ws> --mark C-NN`.

    Never raises (review r2 LOW — record_dispatch_failure's contract): a
    failed artifact write (OSError shapes — missing/permission/blocker
    path being a file) warns to stderr and reports {"escalated": False,
    "reason": ...}; the strike itself still counts. A broken log write
    was already fail-open.
    """
    try:
        bdir = Path(workspace) / "blockers"
        bdir.mkdir(parents=True, exist_ok=True)
        artifact = bdir / f"must-ask-{claim_id}.md"
        artifact.write_text(
            f"# MUST-ASK: 3-strike dispatch exhaustion on {claim_id}\n\n"
            f"- promotion_attempts: {attempts} (threshold {DLQ_ATTEMPTS})\n"
            f"- charter row: 工具/资源耗尽 — 梯爬完 -> must-ask "
            f"(agent-three-state-charter.md, HARD_PAUSE; the orchestrator must "
            f"NOT self-resolve further)\n"
            f"- next Type-D blocker signal HARD_PAUSEs via "
            f"find_ladder_exhaustion (ask_for_direction_gate)\n"
            f"- explicit DLQ (post-mortem decision): "
            f"python dead_letter.py <ws> --mark {claim_id}\n"
            f"- strike note: strikes do not decay — progress between failures "
            f"does not forgive them; resetting is an explicit orchestrator "
            f"decision\n"
            f"- failure history: see analyses/failure-{claim_id}.yaml\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"[kunglao-agent] #234 must-ask escalation WARN: artifact "
              f"write failed ({type(exc).__name__}: {exc}) — strike "
              f"counted, escalation surface not written", file=sys.stderr)
        return {"escalated": False, "claim_id": claim_id,
                "reason": f"artifact write failed "
                          f"({type(exc).__name__}: {exc})"}
    try:
        import kunglao_log
        kunglao_log.emit(workspace, actor="dead_letter",
                         action="must_ask", claim=claim_id,
                         detail=f"promotion_attempts={attempts} "
                                f"(dispatch-failure 3-strike) — charter "
                                f"工具/资源耗尽 row: must-ask, not auto-DEAD")
    except Exception:  # noqa: BLE001 — logging never breaks the writer
        pass
    return {"escalated": True, "claim_id": claim_id,
            "artifact": str(artifact)}


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
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
