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
    # #754 E2: a touch IS a tick. The old implementation OVERWROTE the whole
    # state file (losing last_tick_ts / interval_min / loop_registered /
    # tick_history) — a touch could silently unregister monitoring while
    # claiming to refresh it. Merge into the existing state instead and
    # append the shared continuous-tick history.
    from heartbeat import append_tick, append_tick_log  # noqa: E402 (#754 single writer)
    now_str = utc_now()
    try:
        state = json.loads(heartbeat_file.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            state = {}
    except (json.JSONDecodeError, OSError):
        state = {}
    state["last_tick_ts"] = now_str
    payload = append_tick({**state, "ts": now_str, "touch": True})
    tmp = heartbeat_file.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False) + "\n",
        encoding="utf-8")
    tmp.replace(heartbeat_file)  # F2 atomicity discipline, same as the hook
    # #830: a touch IS a tick - land it in the durable sidecar too.
    append_tick_log(ws, "touch")
    # #534: emit the structured event (workspace is now in scope)
    kunglao_log.emit(ws, actor="heartbeat_touch", action="dispatch",
                     detail="heartbeat touched")
    print(f"heartbeat_touch: {heartbeat_file} merged+tick -> {now_str}")
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # #811 入口 UTF-8 保险
    force_utf8()
    sys.exit(main())
