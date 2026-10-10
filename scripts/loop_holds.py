#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""loop_holds.py - #635: explicit loop-hold directives (the brief's holds).

Operator/orchestrator-authored holds ride the composed registration brief
("T2 stopped by owner - do not auto-resume" class directives): a standing
instruction the next firing must see WITHOUT re-deriving it from scattered
state. Append-only list at runs/.loop-holds.json ([{"ts", "text"}]); the
cadence advisor and heartbeat_loop_prompt's situation brief read it.

Usage:
  python loop_holds.py <workspace> add "<text>"
  python loop_holds.py <workspace> list
  python loop_holds.py <workspace> clear <index>
  python loop_holds.py <workspace> clear --all
Exit codes: 0 ok / 2 usage / 3 not a workspace / 4 bad index.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HOLDS_REL = Path("runs") / ".loop-holds.json"


def _load(ws: Path) -> list[dict]:
    try:
        doc = json.loads((ws / HOLDS_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [e for e in doc if isinstance(e, dict)] if isinstance(
        doc, list) else []


def _save(ws: Path, rows: list[dict]) -> None:
    p = ws / HOLDS_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n",
                 encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="#635 loop-hold directives")
    ap.add_argument("workspace")
    ap.add_argument("cmd", choices=("add", "list", "clear"))
    ap.add_argument("arg", nargs="?", default=None,
                    help="add: the hold text; clear: index")
    ap.add_argument("--all", action="store_true",
                    help="clear: remove every hold")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    if not (ws / "claim-register.yaml").is_file():
        print(f"loop_holds: not a kunglao workspace: {ws}", file=sys.stderr)
        return 3
    rows = _load(ws)
    if args.cmd == "add":
        if not args.arg:
            print("loop_holds: add requires the hold text", file=sys.stderr)
            return 2
        rows.append({"ts": datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"), "text": args.arg})
        _save(ws, rows)
        print(f"OK: hold added ({len(rows)} active)")
        return 0
    if args.cmd == "list":
        for i, e in enumerate(rows):
            print(f"  [{i}] {e.get('ts')} {e.get('text')}")
        print(f"loop_holds: {len(rows)} hold(s)")
        return 0
    # clear
    if args.all or args.arg == "--all":
        _save(ws, [])
        print(f"OK: cleared {len(rows)} hold(s)")
        return 0
    try:
        idx = int(str(args.arg))
        del rows[idx]
    except (TypeError, ValueError, IndexError):
        print(f"loop_holds: bad index {args.arg!r} (have {len(rows)})",
              file=sys.stderr)
        return 4
    _save(ws, rows)
    print(f"OK: cleared hold [{idx}] ({len(rows)} left)")
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)

    force_utf8()
    sys.exit(main())
