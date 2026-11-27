# -*- coding: utf-8 -*-
"""Dispatch-face spans at the two production write points.

Every RELEASED dispatch face rides one start/completed pair into
runs/face-spans.jsonl: the start row at the dispatch release tail
(worker_budget_sinks.pre_check - after the claims txn and the worker
registration), the end row at the round closure
(round_closure._kernel_faces). Both rows key on the ONE dispatch
ledger id - the id the claims txn writes into the launch stash - so a
consumer can correlate the pair and join it to the dispatch ledger.

The span is never closure evidence (the face-span family gotcha); a span
write failure never disturbs the release or the closure (CAGE_FACE);
``usage`` stays ``"unknown"`` (no token accounting in this slice).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "tests",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import worker_budget as wb  # noqa: E402  (hooks on pytest pythonpath)
import round_closure  # noqa: E402
from _factories import write_worker_status  # noqa: E402
from _rl_e2e import round_now  # noqa: E402


ENV = (
    '{"kunglao_dispatch": {"version": 1, "claim": "C-001", "tier": 1, '
    '"tools": ["grep"], "agent": "w-test", '
    '"method_family": "static-decompile"}}'
)


def _dispatch_ws(tmp_path: Path) -> Path:
    """A workspace where the full pre_check battery passes on C-001 (the
    test_worker_budget._healthy_ws shape: fresh heartbeat, plan file,
    live deadline, OPEN tier-0 claim) - the dispatch gets RELEASED."""
    ws = tmp_path / "ws-dispatch-face"
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    prev = (now_dt - timedelta(minutes=5)).isoformat(timespec="seconds").replace("+00:00", "Z")
    (ws / "runs" / ".heartbeat.json").write_text(
        json.dumps(
            {
                "last_tick_ts": now,
                "activity_ts": now,
                "started_ts": prev,
                "tick_history": [prev, now],
            }
        ),
        encoding="utf-8",
    )
    (ws / "runs" / ".heartbeat.log").open("a", encoding="utf-8").write(
        json.dumps({"ts": prev, "actor": "tick"})
        + "\n"
        + json.dumps({"ts": now, "actor": "tick"})
        + "\n"
    )
    (ws / "runs" / "plan-C001-strings.md").write_text(
        "goal: strings\nsteps:\nfallback:\n", encoding="utf-8"
    )
    (ws / "analysis_state.txt").write_text(
        f"deadline_ts: {int(time.time()) + 3600}\n", encoding="utf-8"
    )
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(
            {
                "claims": [
                    {
                        "id": "C-001",
                        "status": "OPEN",
                        "promotion_attempts": 0,
                        "evidence_tier_attempted": 0,
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (ws / "claim_deps.yaml").write_text("deps: {}\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"vm_detonation": "allowed"}, sort_keys=False), encoding="utf-8"
    )
    return ws


def _paths_for(ws: Path) -> dict:
    return {
        "workspace": str(ws),
        "state": ws / "analysis_state.txt",
        "register": ws / "claim-register.yaml",
        "deps": ws / "claim_deps.yaml",
        "task_spec": ws / "task_spec.yaml",
    }


def _dispatch_payload() -> dict:
    return {
        "tool_input": {
            "name": "w-test",
            "description": "",
            "prompt": ENV + "\nfacts-snapshot: 1 facts\n",
        }
    }


def _release_dispatch(ws: Path) -> int:
    """Drive the REAL pre_check battery to the ALLOW tail."""
    return wb.pre_check(_dispatch_payload(), _paths_for(ws))


def _rows(ws: Path) -> list[dict]:
    path = ws / "runs" / "face-spans.jsonl"
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _launch_doc(ws: Path) -> dict:
    return json.loads((ws / "runs" / "dispatch-launch-C-001.json").read_text(encoding="utf-8"))


def _close_round(ws: Path, session: str = "sess-face") -> None:
    """The real SubagentStop round-closure face (worker step rows +
    kernel faces), mirroring the _rl_e2e harness shape."""
    from rlvr import step_ledger as sl

    for i in range(2):
        row = sl.build_step_row(
            session_id=session,
            tool="Bash",
            tool_input={"command": f"round-step-{i}"},
            tool_response={"stdout": "ok"},
            ts=round_now(i).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        sl.record_step(ws, row)
    rc = round_closure.main_with_payload(
        {
            "cwd": str(ws),
            "session_id": session,
            "transcript_path": str(ws / "runs" / f"transcript-{session}.jsonl"),
        }
    )
    assert rc == 0, f"round_closure rc={rc}"


def test_release_tail_writes_dispatch_start_span(tmp_path):
    """The ALLOW tail lands ONE start row keyed on the dispatch ledger
    id - the same id the claims txn wrote into the launch stash - with
    the face-span/1 vocabulary (role, gen_ai.operation.name) and usage
    unknown (no token accounting in this slice)."""
    ws = _dispatch_ws(tmp_path)
    rc = _release_dispatch(ws)
    assert rc == 0, "the healthy dispatch must be released"
    stash = _launch_doc(ws)
    assert stash.get("dispatch_id"), "the claims txn wrote no dispatch id"

    start = [r for r in _rows(ws) if r.get("event") == "start"]
    assert len(start) == 1, _rows(ws)
    row = start[0]
    assert row["schema"] == "face-span/1"
    assert row["gen_ai.operation.name"] == "dispatch"
    assert row["role"] == "orchestrator"
    assert row["dispatch_id"] == stash["dispatch_id"]
    assert row["claim"] == "C-001"
    assert row["agent"] == "w-test"
    assert row["usage"] == "unknown"
    assert row["parent_span_id"] is None
    assert row["span_id"] and row["trace_id"]


def test_round_closure_pairs_start_with_completed_end_row(tmp_path):
    """One released face then one round closure: the closure row pairs
    with the start row (same trace_id + span_id + dispatch_id) and the
    pair's events read [start, completed]."""
    ws = _dispatch_ws(tmp_path)
    assert _release_dispatch(ws) == 0
    stash = _launch_doc(ws)
    _close_round(ws)

    rows = _rows(ws)
    start = {r["span_id"]: r for r in rows if r.get("event") == "start"}
    end = {r["span_id"]: r for r in rows if r.get("event") == "completed"}
    assert len(start) == 1 and len(end) == 1, rows
    sid = next(iter(start))
    assert sid in end
    assert end[sid]["trace_id"] == start[sid]["trace_id"]
    assert end[sid]["dispatch_id"] == stash["dispatch_id"] == start[sid]["dispatch_id"]
    assert end[sid]["claim"] == start[sid]["claim"] == "C-001"
    assert end[sid]["schema"] == "face-span/1"
    assert end[sid]["gen_ai.operation.name"] == "dispatch"
    assert end[sid]["usage"] == "unknown"
    assert end[sid]["attempt_id"] == stash["attempt_id"]


def test_failed_worker_face_rides_a_failed_end_row(tmp_path):
    """A worker that ends on a failure outcome closes the face with a
    ``failed`` event row - the pair still correlates on the same id."""
    ws = _dispatch_ws(tmp_path)
    assert _release_dispatch(ws) == 0
    write_worker_status(ws, "C-001", "failed")
    _close_round(ws)

    rows = _rows(ws)
    start = [r for r in rows if r.get("event") == "start"]
    failed = [r for r in rows if r.get("event") == "failed"]
    assert len(start) == 1 and len(failed) == 1, rows
    assert failed[0]["span_id"] == start[0]["span_id"]
    assert failed[0]["dispatch_id"] == start[0]["dispatch_id"]


def test_span_write_failure_never_blocks_release_nor_closure(tmp_path):
    """CAGE_FACE: an unwritable span sink never turns a released dispatch
    into anything else, and never disturbs the round closure."""
    ws = _dispatch_ws(tmp_path)
    (ws / "runs" / "face-spans.jsonl").mkdir()
    assert _release_dispatch(ws) == 0
    register = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    assert register["claims"][0]["status"] == "IN_PROGRESS", (
        "the release must still commit the claims txn"
    )
    write_worker_status(ws, "C-001", "done")
    _close_round(ws)
