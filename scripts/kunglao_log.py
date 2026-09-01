#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao_log — structured JSONL event log (#287 observability).

One JSON object per line, appended to runs/logs/kunglao-<YYYY-MM-DD>.jsonl
under the workspace. Worker, orchestrator, and hook events share ONE schema:

  ts          ISO8601 UTC timestamp (auto, Z suffix)
  actor       who did it (worker / orchestrator / hook / ...)
  action      what happened (dispatch / tool_call / artifact_written / verify / ...)
              — #459: emit-side words come from the controlled vocabulary
              event_taxonomy.EMIT_ACTIONS (CI-anchored, unregistered = red)
  claim       claim id the event concerns (or null)
  tool        tool name for tool events (or null)
  artifact    artifact id / path written or read (or null)
  duration_ms integer milliseconds the action took (or null)
  exit        integer exit / verdict code (or null)
  detail      free-text detail (or null)

Design contract:
  - stdlib only (json / os / sys / datetime / pathlib).
  - deterministic output: sort_keys + compact separators + ensure_ascii=False.
  - NEVER raises on write failure — emit degrades to a stderr warning and
    returns; logging must never break analysis.

#459 read side: `kunglao_log.py --tail <ws> [N]` prints the most recent N
events (default 20, merged across all day files, JSON lines) — the minimal
answer to "诊断不可解释": one command reconstructs what just happened.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

RC_USAGE = 64  # bad invocation (missing workspace / N < 1) — fail fast
DEFAULT_TAIL = 20

_REPO_SHA: str | None = None
_REPO_SHA_RESOLVED = False


def _repo_sha() -> str | None:
    """Cached git SHA of the running checkout (subprocess, #818 batch-1).

    None on any failure (not a repo / git missing / timeout) — logging must
    never block analysis."""
    global _REPO_SHA, _REPO_SHA_RESOLVED
    if _REPO_SHA_RESOLVED:
        return _REPO_SHA
    _REPO_SHA_RESOLVED = True
    try:
        import subprocess
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(__file__).resolve().parent.parent),
            capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace")
        sha = out.stdout.strip() if out.returncode == 0 else ""
        _REPO_SHA = sha or None
    except Exception:
        _REPO_SHA = None
    return _REPO_SHA


def log_path(ws: Path) -> Path:
    """runs/logs/kunglao-<date>.jsonl — one file per UTC day."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return Path(ws) / "runs" / "logs" / f"kunglao-{day}.jsonl"


def _utc_now() -> str:
    """ISO8601 UTC with Z suffix — same convention as kunglao_record.utc_now."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def emit(ws, actor: str, action: str, *, claim: str | None = None,
         tool: str | None = None, artifact: str | None = None,
         duration_ms: int | None = None, exit: int | None = None,
         detail: str | None = None,
         arm: str | None = None, epoch: int | None = None,
         hypothesis_ref: str | None = None,
         version: str | None = None) -> None:
    """Append one structured event line. Never raises — write failure degrades
    to a stderr warning so logging can never break analysis.

    #818 batch-1: arm/epoch/hypothesis_ref per #823 attribution contract;
    version auto-fills with the checkout git SHA when omitted (None on
    failure). Absent optional fields are explicit null keys — stable schema,
    old consumers use .get()."""
    event = {
        "ts": _utc_now(),
        "actor": actor,
        "action": action,
        "claim": str(claim) if claim is not None else None,
        "tool": str(tool) if tool is not None else None,
        "artifact": str(artifact) if artifact is not None else None,
        "duration_ms": int(duration_ms) if duration_ms is not None else None,
        "exit": int(exit) if exit is not None else None,
        "detail": str(detail) if detail is not None else None,
        "arm": str(arm) if arm is not None else None,
        "epoch": int(epoch) if epoch is not None else None,
        "hypothesis_ref": str(hypothesis_ref) if hypothesis_ref is not None else None,
        "version": str(version) if version else _repo_sha(),
    }
    line = json.dumps(event, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False) + "\n"
    p = log_path(ws)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as exc:
        print(f"[kunglao_log] warning: cannot write {p}: {exc}", file=sys.stderr)


def tail(ws, n: int = DEFAULT_TAIL) -> list[dict]:
    """The most recent n events across ALL day files, chronological order.

    Read-only: creates/modifies nothing. Day files sort by name (= date), so
    file order is stream order; within a file, append order is stream order.
    Unparseable lines are skipped (same tolerance event_taxonomy applies).
    n <= 0 returns [] (the CLI rejects it earlier; the function degrades)."""
    logs = Path(ws) / "runs" / "logs"
    rows: list[dict] = []
    if not logs.is_dir():
        return rows
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-n:] if n > 0 else []


def main(argv: list[str] | None = None) -> int:
    """Read-only diagnostic CLI. `--tail <ws> [N]` → JSON lines on stdout."""
    ap = argparse.ArgumentParser(
        prog="kunglao_log.py",
        description="unified event log (sink read side)")
    ap.add_argument("--tail", metavar="WORKSPACE", default=None,
                    help="print the most recent N events of this workspace "
                         f"(default {DEFAULT_TAIL}), JSON lines, read-only")
    ap.add_argument("n", nargs="?", type=int, default=DEFAULT_TAIL,
                    help=f"how many events (default {DEFAULT_TAIL})")
    args = ap.parse_args(argv)
    if args.tail is None:
        ap.print_help(sys.stderr)
        return RC_USAGE
    ws = Path(args.tail)
    if not ws.is_dir():
        print(f"FAIL: workspace not found: {ws}", file=sys.stderr)
        return RC_USAGE
    if args.n < 1:
        print(f"FAIL: N must be >= 1 (got {args.n})", file=sys.stderr)
        return RC_USAGE
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    for row in tail(ws, args.n):
        # canonical form = the emit serialization (sort_keys, compact,
        # ensure_ascii=False) so tail output round-trips with the file bytes
        print(json.dumps(row, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
