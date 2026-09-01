#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cost_input_capture.py — PostToolUse 成本输入捕获 (#873)。

缺口0：cost_events.jsonl 的写入方在仓库内不存在——cost_gate.py 只读，
docstring 声明的 "written by PostToolUse hook" 是纸面。本 hook 补上输入端：
  - tool_response 含 "COST WARNING: session total ~$<float>"
    （COST CRITICAL 同构）→ 追加 {"ts","amount","source"} 到
    <ws>/cost_events.jsonl（schema 与 cost_gate 解析器逐字段一致）
  - 无匹配 / ws 未解析 / IO 异常 → 静默不写（FAIL_OPEN，永不打断工具流）

口径边界（proposal 声明）：Claude Code 不暴露 per-call 计费遥测——amount
是会话累计 session total（PostToolUse 文本解析口径），非增量。

Wiring (scripts/hook_activation.py 部署表): PostToolUse/Edit|Write|MultiEdit|Agent。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

COST_RE = re.compile(
    r"COST (?:WARNING|CRITICAL): session total ~\$([0-9]+(?:\.[0-9]+)?)")
COST_EVENTS = "cost_events.jsonl"


def resolve_ws(payload: dict) -> Path | None:
    cwd = Path(payload.get("cwd") or ".")
    for base in (cwd, cwd / "malware-analysis-workspace", cwd.parent):
        if (base / "runs").is_dir():
            return base
    return None


def extract_amount(text: str) -> float | None:
    m = COST_RE.search(text or "")
    return float(m.group(1)) if m else None


def process_event(payload: dict) -> int:
    """Testable core。恒返 0——recorder 是 FAIL_OPEN 面，永不阻塞工具流。"""
    text = str(payload.get("tool_response") or "")
    amount = extract_amount(text)
    if amount is None:
        return 0
    ws = resolve_ws(payload)
    if ws is None:
        return 0
    try:
        row = {"ts": datetime.now(timezone.utc).isoformat(
                   timespec="seconds").replace("+00:00", "Z"),
               "amount": amount,
               "source": str(payload.get("tool_name") or "unknown")}
        with (ws / COST_EVENTS).open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return 0


def main(stdin_stream=None) -> int:
    try:
        stream = stdin_stream if stdin_stream is not None else sys.stdin
        data = stream.read()
        payload = json.loads(data) if data else {}
    except (json.JSONDecodeError, OSError, ValueError):
        return 0
    try:
        return process_event(payload)
    except Exception:  # noqa: BLE001 — FAIL_OPEN at the body level
        return 0


if __name__ == "__main__":
    sys.exit(main())
