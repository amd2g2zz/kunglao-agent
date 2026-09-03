#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hooks/user_signal_capture.py — UserPromptSubmit 面（#868）。

每个用户 prompt：捕获 → 分类（只路由，不做使用资格过滤）→ 路由处理
→ 落账。fail-open 双笼：任何异常 rc=0 静默——用户输入永不阻塞会话。

状态分类：咨询注入面（fail-open）。结构门语义（终态裁决）由
scripts/dual_gate.py 承担，本 shim 只做捕获与路由。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from _path_hygiene import scripts_on_path  # #671 hygiene authority

SKILL_DIR = Path(__file__).resolve().parent.parent


def _resolve_workspace(payload: dict) -> Path | None:
    cwd = Path(payload.get("cwd") or payload.get("workspace") or ".")
    for base in [cwd / "malware-analysis-workspace", cwd]:
        if ((base / "claim-register.yaml").exists()
                or (base / ".hook_state.json").exists()):
            return base
    return None


def process_event(payload: dict) -> int:
    prompt = payload.get("prompt")
    if not prompt or not isinstance(prompt, str):
        return 0
    ws = _resolve_workspace(payload)
    if ws is None:
        return 0
    try:
        with scripts_on_path():
            import user_signal
            user_signal.ingest(ws, prompt)
    except Exception:  # noqa: BLE001 — FAIL_OPEN 双笼：永不阻塞用户输入
        return 0
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
    except Exception:  # noqa: BLE001 — FAIL_OPEN body-level
        return 0


if __name__ == "__main__":
    sys.exit(main())
