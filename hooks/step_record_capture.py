#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""step_record_capture.py — PostToolUse 影子步账捕获（经验底座设计）。

在线离策控制器的经验底座：每个工具调用一行 step-record/1（会话 id、
call id、工具名、输入/输出 sha、读/写集 sha、duration 已知时带上）。
信任边界是 HASH-ONLY——原始命令、输出、文件内容物理上到不了账本。

ZERO DECISION POSTURE：只写经验账本（#721 起为 runs/experience.jsonl；
旧路径 runs/step-ledger.jsonl 仅作迁移归档），永不读回、永不
参与任何决策路径；任何异常 → 静默无行（FAIL_OPEN，永不打断工具流），
退出码恒为 0。

Wiring (scripts/hook_activation.py 部署表):
PostToolUse/Bash|Read|Glob|Grep|Edit|Write|MultiEdit|mcp__*。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from _path_hygiene import ensure_scripts_path as _esp
    _esp()
    from rlvr.step_ledger import build_step_row, record_step
except Exception:  # noqa: BLE001 — the partial-deploy lifeline
    def build_step_row(**kw):
        return None

    def record_step(ws, row):
        return None


def resolve_ws(payload: dict) -> Path | None:
    cwd = Path(payload.get("cwd") or ".")
    for base in (cwd, cwd / "malware-analysis-workspace", cwd.parent):
        if (base / "runs").is_dir():
            return base
    return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:  # noqa: BLE001 — fail-open, exit 0 always
        return 0
    if not isinstance(payload, dict):
        return 0
    ws = resolve_ws(payload)
    if ws is None:
        return 0
    try:
        response = payload.get("tool_response")
        duration = response.get("duration_ms") \
            if isinstance(response, dict) else None
        row = build_step_row(
            session_id=str(payload.get("session_id") or ""),
            tool=str(payload.get("tool_name") or ""),
            tool_input=payload.get("tool_input") or {},
            tool_response=response,
            duration_ms=duration)
        record_step(ws, row)
    except Exception:  # noqa: BLE001 — fail-open, exit 0 always
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
