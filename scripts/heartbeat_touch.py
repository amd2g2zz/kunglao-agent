#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""heartbeat_touch.py — lightweight heartbeat file updater (#534).

Companion to heartbeat_tick.py: a one-shot, no-side-effects touch of the
heartbeat timestamp. The orchestrator uses this when a tick is unnecessary
but freshness must be renewed (e.g. between major dispatches). Emits a
structured observability event on invocation (the #534 contract — every
top-20 module must write to runs/logs/).

Usage: python heartbeat_touch.py <workspace>
"""
from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

# #534: observability lifeline — module-level emit on load.
import kunglao_log  # noqa: E402


def utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _resolve_ws(arg: str | None) -> Path:
    if arg:
        return Path(arg).resolve()
    cwd = Path(os.getcwd())
    for cand in (cwd, cwd / "malware-analysis-workspace"):
        if (cand / "claim-register.yaml").exists() or (cand / "analysis_state.txt").exists():
            return cand.resolve()
    print(f"ERROR: no workspace found under cwd ({cwd}); pass the workspace "
          f"explicitly: python {Path(sys.argv[0]).name} <workspace>",
          file=sys.stderr)
    sys.exit(2)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    ws = _resolve_ws(args[0] if args else None)
    heartbeat_file = ws / "runs" / ".heartbeat.json"
    heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": utc_now(), "touch": True}
    heartbeat_file.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False) + "\n",
        encoding="utf-8")
    # #534: emit the structured event (workspace is now in scope)
    kunglao_log.emit(ws, actor="heartbeat_touch", action="dispatch",
                     detail="heartbeat touched")
    print(f"heartbeat_touch: {heartbeat_file} updated -> {payload['ts']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
