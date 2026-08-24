# -*- coding: utf-8 -*-
"""rollup.py - terminal-transition write loop (#524).

When a claim moves to a terminal state (PROVEN / VERIFIED / NEGATIVE /
REFUTED / DEFERRED / STALE / SUPERSEDED / DEAD - see status_defs.TERMINAL),
three write-side effects must fire in order so the closed-loop signals
land on durable storage and the workspace git checkpoint catches the transition:

  1. outcome_capture.capture(workspace)
        runs/*.md (verify-note / verify-redteam) -> OUTCOME rows on the
        .convergence_ledger.jsonl (#35). MUST run first so a verify-redteam
        run sitting in the workspace gets captured BEFORE aggregate_lessons
        reads the ledger for the NEGATIVE red-team CONFIRMED gate.
  2. failure_analysis_gate.aggregate_lessons(workspace, library, queue)
        analyses/failure-*.yaml with a closed-loop outcome -> global lessons
        library; everything else -> /reflect queue (#41).
  3. _checkpoint_commit(workspace, claim_id, terminal_status)
        shared #534 hook for workspace git checkpoint. Imported lazily so
        #524 ships even if #534 isn't merged yet (returns a no-op stub).

The rollup is IDEMPOTENT on the (claim_id, terminal_status) pair:
  - First call: appends an operator_action row (action=rollup) to the ledger.
  - Subsequent calls with same (cid, status): fired=False, reason=already-rolled-up.

Callers (convergence_check, priority, retraction writers) invoke
run_rollup() right after promoting a claim to a terminal status. This is
the SINGLE write-side trigger so lessons/outcome/checkpoint cannot drift
out of sync with the claim register.

Usage:
  python rollup.py <workspace> <claim-id> --status PROVEN

Exit codes:
  0 = OK (fired or already-rolled-up)
  2 = rejected (not-terminal, unknown claim, missing register)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path

# scripts/ is on sys.path via conftest in pytest runs; for CLI invocations
# we add it explicitly so `python rollup.py <ws> ...` works.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402

from status_defs import LedgerLineType, TERMINAL  # noqa: E402
import outcome_capture as _oc  # noqa: E402
import failure_analysis_gate as _fag  # noqa: E402

LEDGER_NAME = ".convergence_ledger.jsonl"


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_register(workspace: Path) -> tuple[list, dict, Path]:
    p = workspace / "claim-register.yaml"
    if not p.exists():
        return [], {}, p
    reg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return reg.get("claims") or [], reg, p


def _append_ledger(workspace: Path, entry: dict) -> None:
    """#584: stdlib WatchedFileHandler (rotation-safe reopen — external
    rotation of the ledger no longer kills the writer). Line format is a
    CONTRACT (external_kicker._ledger_last_snapshot reads it): json.dumps
    ensure_ascii=False + newline, byte-identical to the hand-rolled writer."""
    import logging
    from logging.handlers import WatchedFileHandler
    p = workspace / LEDGER_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    handler = WatchedFileHandler(p, mode="a", encoding="utf-8", delay=True)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger(f"kunglao.ledger.{workspace.name}")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        logger.info(json.dumps(entry, ensure_ascii=False))
    finally:
        logger.removeHandler(handler)
        handler.close()


def _rolled_up(workspace: Path, claim_id: str, terminal_status: str) -> bool:
    """Idempotency guard: has this (claim, status) pair already been rolled up?"""
    p = workspace / LEDGER_NAME
    if not p.exists():
        return False
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (row.get("type") == LedgerLineType.OPERATOR_ACTION
                and row.get("action") == "rollup"
                and row.get("claim_id") == claim_id
                and row.get("terminal_status") == terminal_status):
            return True
    return False


NOTES_DUE_FILE = "runs/notes-due.yaml"


def _queue_notes_due(workspace: Path, claim_id: str, terminal_status: str) -> bool:
    """#628: append the durable-note obligation to runs/notes-due.yaml when
    the terminal claim has no notes/<id>.md. Idempotent (no duplicate entry
    per claim). Returns True when queued. The note itself is NEVER written
    here — judge-then-revise first, the queue is only the reminder."""
    notes_dir = workspace / "notes"
    if (notes_dir / f"{claim_id}.md").exists():
        return False
    due_path = workspace / NOTES_DUE_FILE
    try:
        data = yaml.safe_load(due_path.read_text(encoding="utf-8")) if due_path.exists() else None
        entries = (data or {}).get("due") or []
        if any(e.get("claim_id") == claim_id for e in entries):
            return False
        entries.append({"claim_id": claim_id, "terminal": terminal_status,
                        "queued_ts": utc_now_iso()})
        due_path.parent.mkdir(parents=True, exist_ok=True)
        due_path.write_text(yaml.safe_dump({"due": entries}, allow_unicode=True),
                            encoding="utf-8")
        return True
    except OSError:
        return False  # fail-open: the rollup's other steps must not block


def _checkpoint_commit(workspace: Path, claim_id: str, terminal_status: str) -> str:
    """Shared #534 workspace-git checkpoint hook.

    Imported lazily so #524 ships independently of #534. When #534 lands,
    `workspace_git.checkpoint_commit(workspace, event, payload)` is invoked;
    until then we return a no-op stub. Tests patch this attribute directly.
    """
    try:
        mod = import_module("workspace_git")
        return mod.checkpoint_commit(
            workspace, event="claim_terminal",
            payload={"claim_id": claim_id, "status": terminal_status},
        )
    except (ImportError, AttributeError):
        return "no-op"


def run_rollup(workspace: Path, claim_id: str, terminal_status: str,
               lessons_library: Path | None = None,
               reflect_queue: Path | None = None) -> dict:
    """Fire the terminal-transition write loop.

    Returns a per-step status dict:
      - fired=False, reason='not-terminal'    status not in TERMINAL
      - fired=False, reason='no-register'     register missing
      - fired=False, reason='unknown-claim'   claim id not in register
      - fired=False, reason='already-rolled-up'  idempotent no-op
      - fired=True, with per-phase counters  all phases ran
    """
    status_upper = (terminal_status or "").upper()
    if status_upper not in TERMINAL:
        return {"fired": False, "reason": "not-terminal",
                "terminal_status": status_upper}

    claims, _reg, reg_path = _load_register(workspace)
    if not reg_path.exists():
        return {"fired": False, "reason": "no-register"}
    claim = next((c for c in claims if c.get("id") == claim_id), None)
    if claim is None:
        return {"fired": False, "reason": "unknown-claim",
                "claim_id": claim_id}

    if _rolled_up(workspace, claim_id, status_upper):
        return {"fired": False, "reason": "already-rolled-up",
                "claim_id": claim_id, "terminal_status": status_upper}

    # Step 1: capture any runs/*.md -> OUTCOME rows (MUST run before aggregate
    # so a verify-redteam row gets read by the NEGATIVE red-team-CONFIRMED gate).
    captured = _oc.capture(workspace)

    # Step 2: aggregate analyses -> lessons library / reflect queue.
    agg_res = _fag.aggregate_lessons(
        workspace,
        library=lessons_library,
        reflect_queue=reflect_queue,
    )

    # Step 2.5 (#628): queue the durable-note obligation — terminal claim
    # without a notes/<id>.md entry goes to runs/notes-due.yaml. Nothing
    # auto-WRITES the note (judge-then-revise doctrine, 2026-08-20 ruling):
    # the queue only makes the obligation impossible to forget; the Stop-face
    # completion gate refuses closure while entries remain.
    notes_queued = _queue_notes_due(workspace, claim_id, status_upper)

    # Step 3: workspace git checkpoint commit (shared mount with #534).
    ck = _checkpoint_commit(workspace, claim_id, status_upper)

    _append_ledger(workspace, {
        "type": LedgerLineType.OPERATOR_ACTION,
        "action": "rollup",
        "actor": "orchestrator",
        "claim_id": claim_id,
        "terminal_status": status_upper,
        "captured_outcomes": captured,
        "lessons_written": agg_res.get("lessons_written", 0),
        "lessons_skipped": agg_res.get("lessons_skipped", 0),
        "queue_added": agg_res.get("queue_added", 0),
        "checkpoint_commit": ck,
        "ts": utc_now_iso(),
    })

    return {
        "fired": True,
        "claim_id": claim_id,
        "terminal_status": status_upper,
        "captured_outcomes": captured,
        "lessons_aggregate": agg_res.get("lessons_written", 0),
        "lessons_skipped": agg_res.get("lessons_skipped", 0),
        "queue_added": agg_res.get("queue_added", 0),
        "checkpoint_commit_called": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rollup.py",
        description="claim terminal transition -> outcome/lessons/checkpoint write loop (#524)",
    )
    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("claim_id", help="claim id (e.g. C-001)")
    parser.add_argument("--status", required=True,
                        help="terminal status (PROVEN/VERIFIED/NEGATIVE/REFUTED/...)")
    parser.add_argument("--library", default=None,
                        help="global lessons library dir (default: failure_analysis_gate default)")
    parser.add_argument("--reflect-queue", default=None,
                        help="/reflect queue JSON path (default: failure_analysis_gate default)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would happen without writing")
    args = parser.parse_args(argv)

    ws = Path(args.workspace)
    if not (ws / "claim-register.yaml").exists():
        print(f"FAIL: no claim-register.yaml under {ws}", file=sys.stderr)
        return 2

    if args.dry_run:
        if (args.status or "").upper() not in TERMINAL:
            print(f"REJECTED: {args.status!r} is not a terminal status", file=sys.stderr)
            return 2
        print(f"dry-run: would rollup {args.claim_id} ({args.status})")
        return 0

    res = run_rollup(ws, args.claim_id, args.status,
                     lessons_library=Path(args.library) if args.library else None,
                     reflect_queue=Path(args.reflect_queue)
                     if args.reflect_queue else None)
    if not res.get("fired"):
        reason = res.get("reason", "unknown")
        if reason == "not-terminal":
            print(f"REJECTED: {args.status!r} is not a terminal status", file=sys.stderr)
            return 2
        if reason == "unknown-claim":
            print(f"REJECTED: claim {args.claim_id} not found", file=sys.stderr)
            return 2
        if reason == "already-rolled-up":
            print(f"rollup {args.claim_id} ({res.get('terminal_status')}): "
                  f"already-rolled-up - idempotent no-op")
            return 0
        print(f"FAIL: {reason}", file=sys.stderr)
        return 2

    print(f"rollup {args.claim_id} ({res['terminal_status']}): "
          f"fired - captured={res['captured_outcomes']} "
          f"lessons={res['lessons_aggregate']} "
          f"checkpoint={res['checkpoint_commit_called']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())