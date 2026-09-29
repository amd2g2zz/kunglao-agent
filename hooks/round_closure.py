#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hooks/round_closure.py — SubagentStop wiring (event-wakeup topology,
issue 434): the round-closure event feed + the kernel closure faces.

Between-turns wakes come from worker completion notifications — but the
closure itself left no ledger row the decision faces could consume (the
lifecycle pipe existed with no live producer on this event). This hook
appends ONE closure event row per SubagentStop: a lifecycle_completed
transition (kunglao_log.emit_lifecycle — the established subagent
lifecycle face) carrying the session identity in detail.

Since issue 462 the closure event is ALSO the production host of the
kernel's round-closure faces (#429 §6: Stop(worker) IS the round
closure): W1 composes + versions ONE round-strategy object per decision
event (the compose single-point's host), and W6 builds + drains the T2
unblocking-value priority queue (no longer eval-only).

Pure-closure posture, fail-open double cage: any error -> rc 0, silent.
A closure observation must never disturb the subagent's own stop path.
"""
from __future__ import annotations
# The canonical warn — ONE implementation (process-wide dedupe per
# (op, reason) + the ledger face). The stderr-only fallback is the
# partial-deploy lifeline; production imports kunglao_log.
try:
    from _path_hygiene import ensure_scripts_path as _esp406
    _esp406()
    from kunglao_log import warn
except Exception:  # noqa: BLE001 — fail-open lifeline, never block the hook
    def warn(op: str, reason: str) -> None:
        print(f"[kunglao-agent] WARN (fail-open): {op}: {reason}",
              file=sys.stderr)
import json
import sys
from pathlib import Path

from _path_hygiene import scripts_on_path  # #671 sys.path hygiene authority

CLOSURE_ACTOR = "subagent:stop"


def _resolve_workspace(payload: dict) -> Path | None:
    """Workspace markers (claim-register.yaml / .hook_state.json) under
    cwd or cwd/malware-analysis-workspace — the deployed convention."""
    cwd = Path(payload.get("cwd") or payload.get("workspace") or ".")
    for base in [cwd / "malware-analysis-workspace", cwd]:
        if (base / "claim-register.yaml").exists() \
                or (base / ".hook_state.json").exists():
            return base
    return None


def process_event(payload: dict) -> int:
    """Resolve the workspace, append the closure row, run the kernel
    closure faces, rc 0."""
    ws = _resolve_workspace(payload)
    if ws is None:
        return 0
    detail = {
        "session_id": payload.get("session_id"),
        "transcript": payload.get("transcript_path"),
        "source": "SubagentStop",
    }
    try:
        with scripts_on_path():
            import kunglao_log
            kunglao_log.emit_lifecycle(
                ws, CLOSURE_ACTOR, "completed",
                detail=json.dumps(detail, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 — recorder, never blocks
        warn("round_closure", f"{type(exc).__name__}: {exc}")
    _kernel_faces(ws)
    return 0


def _kernel_faces(ws: Path) -> None:
    """Issues #462 W1+W6: the production round-closure kernel faces.

    Stop(worker) IS the round-closure event (#429 §6), so this hook now
    hosts what until now fired only from eval_loop_runner:

      - W6: the T2 unblocking-value priority queue builds AND drains
        here (verification_ladder.round_close + drain_t2_queue) — a
        production round consumes its queue head, not just the eval
        loop. NOTE the on-disk queue is written TWICE per closure in
        two ordered shapes: round_close persists the full ``{queue}``
        snapshot, then drain overwrites with ``{dispatched, remaining}``
        — a consumer must tolerate both shapes at that path (the final
        state after a closure is the drained one).
      - W1: the compose single-point composes + versions ONE
        round-strategy object per decision event
        (rlvr.compose.compose + write_strategy; tick = the round axis —
        priority_ratio.round_index, machine-independent, never a wall
        clock). Compose dedups by content_hash, so repeated stops on an
        unchanged workspace re-write nothing — the per-decision-event
        invariant is "per SubagentStop with marker-resolved workspace,
        deduped by content" (#462 recorded scope).

    Fail-open double cage: each face is wrapped separately — a kernel
    failure is one rate-limited warn and never disturbs the subagent's
    own stop path."""
    try:
        with scripts_on_path():
            import priority_ratio  # the round axis (machine-independent)
            from rlvr import compose
            obj = compose.compose(ws, tick=priority_ratio.round_index(ws))
            compose.write_strategy(ws, obj)
    except Exception as exc:  # noqa: BLE001 — kernel face, never blocks
        warn("round_closure_compose", f"{type(exc).__name__}: {exc}")
    try:
        with scripts_on_path():
            import verification_ladder
            verification_ladder.round_close(ws)
            verification_ladder.drain_t2_queue(ws)
    except Exception as exc:  # noqa: BLE001 — kernel face, never blocks
        warn("round_closure_t2", f"{type(exc).__name__}: {exc}")


def main_with_payload(payload: dict) -> int:
    return process_event(payload)


def main(stdin_stream=None) -> int:
    """SubagentStop entry: JSON payload on stdin. FAIL_OPEN on every
    error face — rc 0, silent."""
    try:
        stream = stdin_stream if stdin_stream is not None else sys.stdin
        data = stream.read()
        payload = json.loads(data) if data else {}
    except (json.JSONDecodeError, OSError, ValueError):
        return 0
    try:
        return process_event(payload)
    except Exception:  # noqa: BLE001 — body-level fail-open
        return 0


if __name__ == "__main__":
    sys.exit(main())
