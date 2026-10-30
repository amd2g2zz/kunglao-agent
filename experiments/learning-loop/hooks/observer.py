# -*- coding: utf-8 -*-
"""hooks/observer.py — observation-only tool-call capture (#885).

The hook face that SURVIVES the construction-style refactoring: where
the interception hooks (dispatch_gate's PreToolUse blocking, the
completion gate, the violation capture — all removed by #886) decided
and blocked, this face only WATCHES. Every worker tool call lands as
ONE ``observer-call/1`` row in the consolidated TELEMETRY ledger (the
``runs/telemetry.jsonl`` WHAT-WAS-OBSERVED family — audit, never the
learning feed: the rows carry no credit, no arm key, no signature, so
the fold stays blind to them by construction).

The telemetry posture, verbatim: capture is FAIL-OPEN — a broken
capture path (unwritable workspace, unserializable detail) never
raises into the caller and never blocks; it leaves exactly ONE
rate-limited warn and a named ``reason`` on the returned receipt. The
boundary still validates STRUCTURE loudly (a blank worker id or a
non-mapping detail is a caller bug — ValueError, the episode_schema
posture); the environment's failures are the only fail-open leg.

No decision semantics exist here: the receipt carries no block/verdict
field — observation only.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

_HERE = Path(__file__).resolve().parent.parent          # learning-loop/
_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
for _p in (_HERE, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from kunglao_log import warn  # noqa: E402 — the ONE canonical warn
from rlvr import consolidated_ledger as _cl  # noqa: E402

#: the row stamp — every captured call names its schema (the audit face)
SCHEMA = "observer-call/1"

_SOURCE = "observer"


def _fail(field: str, why: str) -> ValueError:
    return ValueError(f"observer.{field}: {why}")


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(field, "must be a non-empty string")
    return value


def _now() -> str:
    from harness_common import utc_now_z  # noqa: PLC0415 — lazy
    return utc_now_z()


def observe_tool_call(ws, *, worker_id: str, tool: str,
                      rollout_id: str | None = None,
                      step_id: str | None = None,
                      detail: Mapping[str, Any] | None = None,
                      ts: str | None = None) -> dict:
    """Capture ONE worker tool call as observation telemetry. Never
    blocks, never decides; returns the capture receipt
    (``{observed, reason, worker_id, tool}``)."""
    worker_v = _non_empty(worker_id, "worker_id")
    tool_v = _non_empty(tool, "tool")
    rid = None if rollout_id is None else _non_empty(rollout_id,
                                                     "rollout_id")
    sid = None if step_id is None else _non_empty(step_id, "step_id")
    doc = None
    if detail is not None:
        if not isinstance(detail, Mapping):
            raise _fail("detail", "must be a mapping")
        doc = dict(detail)
    try:
        row = {
            "schema": SCHEMA,
            "ts": ts or _now(),
            "source": _SOURCE,
            "worker_id": worker_v,
            "tool": tool_v,
            "rollout_id": rid,
            "step_id": sid,
            "detail": doc,
        }
        appended = _cl.append(ws, "telemetry", row)
    except Exception as exc:  # noqa: BLE001 — telemetry never blocks
        warn("hooks.observer.observe_tool_call",
             f"{type(exc).__name__}: {exc} — capture degraded, caller "
             f"unaffected")
        return {"observed": False,
                "reason": f"error:{type(exc).__name__}",
                "worker_id": worker_v, "tool": tool_v}
    return {"observed": bool(appended),
            "reason": None if appended else "write-failed",
            "worker_id": worker_v, "tool": tool_v}


def observed_calls(ws) -> list[dict]:
    """The observation read face — every captured call, oldest first
    (append order; the tolerant consolidated read)."""
    return _cl.read(ws, "telemetry", schema_prefix="observer-call")
