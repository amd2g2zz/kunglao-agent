# -*- coding: utf-8 -*-
"""tests/test_dispatch_telemetry_740.py — the completion row closes the
dispatch loop (issue 740, Face 4).

RC1 live evidence: 36 dispatch events with ``exit=None`` ×35 — the
dispatch row records the start and nothing records the completion, so
verify loops could not close on evidence and the session re-discussed
settled work. The investigation verdict: ABSENT, not unjoinable — the
completion face already exists (the round-closure hook emits
``lifecycle_completed`` at exactly the right point, from the already-
deployed hook) and the settle face already computes the wall time and
holds the attempt id. Only the ENRICHMENT was missing.

The fix, reusing the vocabulary (no new EMIT_ACTIONS):

  - ``settle_step`` returns additive telemetry keys (claim, attempt_id,
    wall_s, outcome, duration_ms) — the whitelists are untouched;
  - the round-closure emit carries claim / duration_ms / exit (0 =
    settled, 1 = blocked) + attempt_id/step_id/outcome in the detail;
  - a non-worker stop (no pending step) stays SILENT — the designed
    posture: only real dispatch completions emit the completion row.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (SCRIPTS, ROOT / "hooks"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from rlvr import incremental_reward as ir  # noqa: E402
import round_closure  # noqa: E402

TS = "2026-10-17T08:00:00Z"


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    # the workspace MARKER (claim register) — without it
    # _resolve_workspace returns None and the whole hook silently skips
    (ws / "claim-register.yaml").write_text(
        "claims: []\n", encoding="utf-8")
    return ws


def _tool_rows(ws: Path, session: str, n: int) -> list[str]:
    """n hash-only step-record/1 rows for one session (the 690 fixture
    shape — the aggregation input)."""
    from rlvr import step_ledger as sl
    ids = []
    for i in range(n):
        row = sl.build_step_row(
            session_id=session, tool="Bash",
            tool_input={"command": f"step-{i}"},
            tool_response={"stdout": "x"},
            ts=TS)
        assert sl.record_step(ws, row) is not None
        ids.append(row["call_id"])
    return ids


def _launch(ws: Path, claim: str) -> None:
    ir.record_launch(ws, claim, "static-first",
                     branch_budget={"wall_s": 3600, "retries": 2})


def _payload(ws: Path, session: str) -> dict:
    return {"cwd": str(ws), "session_id": session,
            "transcript_path": str(ws / "transcript.jsonl")}


def _lifecycle_rows(ws: Path) -> list[dict]:
    logdir = ws / "runs" / "logs"
    rows: list[dict] = []
    if not logdir.is_dir():
        return rows
    for p in sorted(logdir.glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("action") == "lifecycle_completed":
                rows.append(r)
    return rows


# ---------- 1. the completion row carries the four fields -------------------

def test_completion_row_carries_claim_duration_exit_attempt(
        tmp_path, capsys) -> None:
    ws = _ws(tmp_path)
    _launch(ws, "C-5")
    _tool_rows(ws, "sess-9", 3)
    rc = round_closure.main_with_payload(_payload(ws, "sess-9"))
    capsys.readouterr()
    assert rc == 0
    rows = _lifecycle_rows(ws)
    assert len(rows) == 1
    row = rows[0]
    assert row.get("claim") == "C-5"
    assert "duration_ms" in row          # the key rides (value may be
    #                                     None for hash-only tool rows)
    assert row.get("exit") == 0
    detail = json.loads(row.get("detail") or "{}")
    assert detail.get("attempt_id"), "the stash attempt id rides the detail"
    assert detail.get("step_id")


# ---------- 2. the non-worker stop stays silent ------------------------------

def test_non_worker_stop_row_stays_plain(tmp_path, capsys) -> None:
    """The closure-row contract: ONE row per SubagentStop (the
    between-turns wake topology reads it) — a non-worker stop's row
    stays PLAIN (no claim/exit enrichment), byte-shape as before."""
    ws = _ws(tmp_path)
    rc = round_closure.main_with_payload(_payload(ws, "sess-none"))
    capsys.readouterr()
    assert rc == 0
    rows = _lifecycle_rows(ws)
    assert len(rows) == 1
    row = rows[0]
    assert row.get("actor") == "subagent:stop"
    assert row.get("claim") is None                # plain: no enrichment
    detail = json.loads(row.get("detail") or "{}")
    assert "claim" not in detail and "exit" not in detail


# ---------- 3. the settle receipt returns the telemetry keys -----------------

def test_settle_step_returns_telemetry_keys(tmp_path) -> None:
    from rlvr import step_grain
    ws = _ws(tmp_path)
    _launch(ws, "C-7")
    _tool_rows(ws, "sess-7", 2)
    receipt = step_grain.settle_step(ws, "sess-7")
    assert receipt is not None
    assert receipt.get("claim") == "C-7"
    assert receipt.get("attempt_id")
    assert receipt.get("outcome") == "completed"
    assert isinstance(receipt.get("wall_s"), (int, float))
    assert "duration_ms" in receipt      # the key rides (value may be
    #                                     None for hash-only tool rows)


# ---------- 4. a blocked outcome exits one -----------------------------------

def test_blocked_outcome_exits_one(tmp_path) -> None:
    from rlvr import step_grain
    ws = _ws(tmp_path)
    _launch(ws, "C-9")
    _tool_rows(ws, "sess-9", 1)
    receipt = step_grain.settle_step(ws, "sess-9", outcome="blocked")
    assert receipt is not None
    assert receipt.get("outcome") == "blocked"
    assert receipt.get("exit") == 1
