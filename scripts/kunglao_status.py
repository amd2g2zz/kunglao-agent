#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao-status — disk-rendered TUI status panel (#287 observability).

Read-only renderer: builds a status panel from DISK state only —

  claim-register.yaml       → claims board (counts by status)
  runs/worker-status-*.md   → active workers (id / claim / step / status / heartbeat)
  .convergence_ledger.jsonl → convergence progress (open-count trend, last 10 rows)
  runs/logs/kunglao-*.jsonl → recent event stream (last 15 events)

Creates NO new state source. Stdlib only (no yaml, no rich) — a minimal
line-based claim-status parser keeps the zero-dependency contract. Missing
pieces render as empty sections, never crash; malformed lines are skipped.

ANSI colors are optional: --no-color or a non-TTY stdout degrades to plain
text (byte-identical modulo the escapes).

CLI entry: scripts/kunglao-status.py is a thin wrapper around main() here
(module name has no hyphen, so tests can `from kunglao_status import ...`).

Usage: python scripts/kunglao-status.py <workspace> [--no-color]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

CLAIM_RE = re.compile(r"claim\s*:?\s+([A-Za-z0-9][\w.-]*)")
STEP_RE = re.compile(r"step\s*:?\s+(\S+)")
LEDGER_NAME = ".convergence_ledger.jsonl"
EVENT_LIMIT = 15
TREND_LIMIT = 10


def _worker_protocol():
    """hooks/lib_kunglao.py — THE worker-status protocol owner (#444), by
    path under the unique name lib_kunglao_hooks (bare `import lib_kunglao`
    is ambiguous under pytest — scripts/lib_kunglao.py shares the name).
    CLAIM_RE / STEP_RE below are display-only field extraction, not liveness
    parsing, so they stay local."""
    import importlib.util
    name = "lib_kunglao_hooks"
    lib = sys.modules.get(name)
    if lib is None:
        path = Path(__file__).resolve().parent.parent / "hooks" / "lib_kunglao.py"
        spec = importlib.util.spec_from_file_location(name, path)
        lib = importlib.util.module_from_spec(spec)
        sys.modules[name] = lib
        spec.loader.exec_module(lib)
    return lib


def _bold(s: str, color: bool) -> str:
    return f"\x1b[1m{s}\x1b[0m" if color else s


def _claim_statuses(text: str) -> list[str]:
    """Minimal line-based status extraction from claim-register.yaml.

    Block-scoped: a `status:` line counts only inside a `- id:` claim block
    (one status per claim). No YAML dependency (stdlib-only contract).
    """
    statuses: list[str] = []
    in_claim = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- id:"):
            in_claim = True
        elif in_claim and s.startswith("status:"):
            statuses.append(s.split(":", 1)[1].strip().strip("'\""))
            in_claim = False
    return statuses


def _claims_board(ws: Path, color: bool) -> list[str]:
    p = ws / "claim-register.yaml"
    if not p.exists():
        return ["  (no claim-register.yaml)"]
    counts = Counter()
    for st in _claim_statuses(p.read_text(encoding="utf-8", errors="replace")):
        counts[st.upper() or "UNKNOWN"] += 1
    lines = [f"  {st}: {counts[st]}" for st in sorted(counts)]
    lines.append(f"  TOTAL: {sum(counts.values())}")
    return lines


def _worker_lines(ws: Path, color: bool) -> list[str]:
    """runs/worker-status-*.md → id / claim / step / status / heartbeat.

    Status comes from the canonical worker-liveness protocol
    (hooks/lib_kunglao.parse_worker_status, #444): the LAST `status:` token
    decides the worker's state; a missing status file is skipped, never
    fatal. Heartbeat time = file mtime (the file is appended on every worker
    step).
    """
    runs = ws / "runs"
    if not runs.is_dir():
        return ["  (no runs/)"]
    parse_status = _worker_protocol().parse_worker_status
    out: list[str] = []
    for p in sorted(runs.glob("worker-status-*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        wid = p.stem.removeprefix("worker-status-")
        status = parse_status(text)
        claim = CLAIM_RE.search(text)
        step = STEP_RE.search(text)
        row = (f"  {wid:<8} claim={claim.group(1) if claim else '-'}  "
               f"step={step.group(1) if step else '-'}  status={status or '?'}  "
               f"heartbeat={mtime.strftime('%H:%M:%S')} UTC")
        out.append(row)
    return out or ["  (no worker status files)"]


def _open_trend(ws: Path) -> list[int]:
    """Last TREND_LIMIT open_count values from the convergence ledger,
    oldest-first. Malformed / non-snapshot rows are skipped (D2 contract)."""
    p = ws / LEDGER_NAME
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    opens: list[int] = []
    for line in lines[-TREND_LIMIT:]:
        try:
            row = json.loads(line)
            oc = row.get("open_count")
            if isinstance(oc, int):
                opens.append(oc)
        except (ValueError, AttributeError, TypeError):
            continue
    return opens


def _convergence_lines(ws: Path, color: bool) -> list[str]:
    opens = _open_trend(ws)
    if not opens:
        return ["  (no .convergence_ledger.jsonl yet)"]
    trend = " -> ".join(str(n) for n in opens)
    return [f"  open trend (last {len(opens)} rows): {trend}"]


def _hhmmss(ts: str) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts).strftime("%H:%M:%S")
    except ValueError:
        return ts[11:19] if len(ts) >= 19 else ts


def _recent_events(ws: Path, limit: int = EVENT_LIMIT) -> list[dict]:
    """Last `limit` events across all runs/logs/kunglao-*.jsonl, chronological."""
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return []
    events: list[dict] = []
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except (ValueError, AttributeError, TypeError):
                continue
    return events[-limit:]


def _event_line(ev: dict, color: bool) -> str:
    parts = [f"  [{_hhmmss(str(ev.get('ts', '')))}]",
             str(ev.get("actor", "?")), str(ev.get("action", "?"))]
    for key in ("claim", "tool", "artifact"):
        v = ev.get(key)
        if v:
            parts.append(f"{key}={v}")
    if ev.get("exit") is not None:
        parts.append(f"exit={ev['exit']}")
    det = ev.get("detail")
    if det:
        parts.append(f"detail={str(det)[:60]}")
    return " ".join(parts)


def render_status(ws: Path, *, color: bool) -> str:
    """Render the full panel from disk state. Pure: no writes, no clock reads
    beyond file mtimes, byte-identical modulo ANSI between color modes."""
    ws = Path(ws)
    parts = [_bold("kunglao status", color) + f" - {ws}"]
    parts.append(_bold("claims", color))
    parts.extend(_claims_board(ws, color))
    parts.append(_bold("active workers", color))
    parts.extend(_worker_lines(ws, color))
    parts.append(_bold("convergence progress", color))
    parts.extend(_convergence_lines(ws, color))
    parts.append(_bold("recent events", color))
    events = _recent_events(ws)
    if events:
        parts.extend(_event_line(ev, color) for ev in events)
    else:
        parts.append("  (no kunglao-*.jsonl events yet)")
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="kunglao-status — disk-rendered observability panel")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--no-color", action="store_true",
                    help="plain text output (no ANSI escapes)")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    if not ws.is_dir() or not (ws / "claim-register.yaml").is_file():
        print(f"ERROR: no workspace state at {ws} (claim-register.yaml missing)",
              file=sys.stderr)
        return 2
    color = (not args.no_color) and sys.stdout.isatty()
    print(render_status(ws, color=color))
    return 0


if __name__ == "__main__":
    sys.exit(main())
