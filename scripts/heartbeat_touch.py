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

import json
import sys

# #534: observability lifeline — module-level emit on load.
import kunglao_log  # noqa: E402
# #863 Family C: workspace resolution is single-sourced in ws_layout
# (the #228 strict family: arg wins, probe, exit 2 — never guess).
from ws_layout import resolve_strict as _resolve_ws  # noqa: E402


from harness_common import utc_now_z as utc_now  # #863 Family F: single source (was a local def)


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
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
