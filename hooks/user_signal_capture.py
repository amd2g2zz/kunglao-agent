#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hooks/user_signal_capture.py — UserPromptSubmit 面（user-signal 捕获
+ 运营者观察流，事件唤醒拓扑 wiring）。

每个用户 prompt：观察行落账（纯记录，issue 434 的 observation stream：
operator intent as an observation — NO gating，永不阻塞）→ 捕获 → 分类
（只路由，不做使用资格过滤）→ 路由处理 → 落账。fail-open 双笼：任何
异常 rc=0 静默——用户输入永不阻塞会话。

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
    """Pure delegation to scripts/ws_layout.py (#863 Family C). The import
    rides the scripts_on_path() authority — in the DEPLOYED shape
    (uv run python <deployed>/hooks/user_signal_capture.py) sys.path has
    the hooks dir only, so a bare import would ModuleNotFoundError and the
    main() cage would swallow it into a silent no-op (reviewer round 2)."""
    with scripts_on_path():
        from ws_layout import resolve_payload_ws
        return resolve_payload_ws(payload)


def process_event(payload: dict) -> int:
    prompt = payload.get("prompt")
    if not prompt or not isinstance(prompt, str):
        return 0
    ws = _resolve_workspace(payload)
    if ws is None:
        return 0
    try:
        with scripts_on_path():
            import json as _json

            import kunglao_log
            # operator observation stream (event-wakeup topology): one row
            # per operator prompt, PURE RECORDING — the decision faces read
            # intent from the ledger; this face never gates anything.
            kunglao_log.emit(
                ws, actor="operator", action="operator_observation",
                detail=_json.dumps(
                    {"text_digest": prompt[:200]},
                    ensure_ascii=False))
            import user_signal
            user_signal.ingest(ws, prompt)
    except Exception:  # noqa: BLE001 — FAIL_OPEN 双笼：永不阻塞用户输入
        return 0
    return 0


def main_with_payload(payload: dict) -> int:
    """Payload face (tests / programmatic dispatch): same recording +
    routing path as the stdin face, zero output (pure observation)."""
    return process_event(payload)


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
