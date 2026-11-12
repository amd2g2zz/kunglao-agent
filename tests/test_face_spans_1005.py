"""Terminal traces have an operator consumer; ledger remains authoritative."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from test_production_terminal_1005 import terminal_workspace
from rlvr import episode_pool, episode_settle, production_terminal as terminal


def test_terminal_spans_have_correlated_start_end_and_real_reader(tmp_path):
    ws = terminal_workspace(tmp_path)
    assert terminal.settle_stop(ws)["status"] == "completed"
    proc = subprocess.run([sys.executable, "-m", "rlvr.production_terminal", str(ws)],
                          text=True, capture_output=True, timeout=60,
                          env=dict(os.environ, PYTHONPATH=str(
                              Path(__file__).resolve().parents[1] / "scripts")))
    assert proc.returncode == 0, proc.stderr
    read = json.loads(proc.stdout)
    assert read["checkpoint"]["status"] == "completed"
    assert read["episodes"] == 1 and read["pending_rollouts"] == 0
    assert len({r["trace_id"] for r in read["spans"]}) == 1
    for operation in ("settlement", "mission_terminal"):
        rows = [r for r in read["spans"] if r["gen_ai.operation.name"] == operation]
        assert [r["event"] for r in rows] == ["start", "completed"]
        assert rows[0]["span_id"] == rows[1]["span_id"]
        assert all(r["role"] == "orchestrator" and r["usage"] == "unknown" for r in rows)
    settlement = next(r for r in read["spans"]
                      if r["gen_ai.operation.name"] == "settlement")
    mission = next(r for r in read["spans"]
                  if r["gen_ai.operation.name"] == "mission_terminal")
    assert settlement["parent_span_id"] == mission["span_id"]


def test_ledger_failure_cannot_be_certified_by_an_existing_span(tmp_path, monkeypatch):
    ws = terminal_workspace(tmp_path)
    (ws / "runs" / "face-spans.jsonl").write_text(json.dumps({"event": "completed"}) + "\n")
    monkeypatch.setattr(episode_settle, "settle_mission",
                        lambda _: (_ for _ in ()).throw(OSError("injected")))
    with pytest.raises(OSError):
        terminal.settle_stop(ws)
    assert terminal.inspect(ws)["checkpoint"]["status"] == "retry"
    assert episode_pool.list_episodes(ws) == []


def test_span_write_failure_preserves_real_settlement(tmp_path):
    ws = terminal_workspace(tmp_path)
    (ws / "runs" / "face-spans.jsonl").mkdir()
    assert terminal.settle_stop(ws)["status"] == "completed"
    assert len(episode_pool.list_episodes(ws)) == 1
    assert terminal.settle_stop(ws)["episodes_written"] == 0
