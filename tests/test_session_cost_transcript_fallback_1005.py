# -*- coding: utf-8 -*-
"""tests/test_session_cost_transcript_fallback_1005.py — a session killed
by the wall cap must still report what it consumed (issue 1005, instrument
half ②).

The runner reads its cost face from the session's own stdout result line,
and the wall-cap kill (SIGKILL to the process group) is exactly the case
where that line never arrives: 25 of the 30 session rows in the real eval
artifacts carry an empty session_cost, and the reports then drop those
sessions from the cost account while still counting their failures.
Measured against the CLI on this machine: the kill cannot be negotiated —
the CLI exits on SIGTERM without writing its cost row — so no dollar
figure exists for a hard-killed session. What the session transcript DOES
carry is every usage row and, when the CLI got to flush one, its own
cumulative cost-state number.

Faces pinned here:
  (a) the transcript dir for a workspace is the resolved cwd with '/' and
      '.' mapped to '-' (measured, macOS /tmp symlink included);
  (b) the session transcript is the newest file written at or after the
      launch whose rows carry this workspace as cwd — an earlier run in
      the same dir, or a moved session, is not it;
  (c) the usage face: orchestrator and worker token sums, from the usage
      rows, the two populations kept apart;
  (d) the CLI's own cumulative cost face is read off the last cost-state
      row;
  (e) end-to-end through the launch adapter: a killed session reports a
      non-empty cost harvested from the transcript;
  (f) a killed session whose transcript carries no cost-state row reports
      its tokens and NAMES the reason its dollars are absent — never a
      silent zero;
  (g) the stdout report keeps precedence when it arrives;
  (h) no transcript for the window -> the session_cost shape is untouched
      (None), so nothing is fabricated where nothing was measured;
  (i) malformed transcript lines are skipped, not fatal.

The session stub is TEST-ONLY and drives the runner's own session-command
seam: it writes the transcript faces a real session would have left, then
either overruns the wall cap or exits. No model call is ever made."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import eval_loop_runner as lr  # noqa: E402

CLI_USD = 5.0254438
MODEL = "test-model"

# TEST-ONLY session stub (module docstring): writes the transcript layout a
# real session leaves behind, then behaves per the K1005_* env.
_STUB_SRC = '''
import json, os, time
from pathlib import Path

cost_state = os.environ.get("K1005_COST_STATE") == "1"
stdout_face = os.environ.get("K1005_STDOUT", "none")
overrun = os.environ.get("K1005_OVERRUN") == "1"
write = os.environ.get("K1005_WRITE", "1") == "1"
ws = Path.cwd().resolve()


def usage(sidechain, inp, out, cache=0, cache_write=0):
    return json.dumps({
        "type": "assistant", "isSidechain": sidechain, "cwd": str(ws),
        "timestamp": "2026-11-25T00:00:00.000Z",
        "message": {"role": "assistant", "model": "test-model",
                    "usage": {"input_tokens": inp, "output_tokens": out,
                              "cache_read_input_tokens": cache,
                              "cache_creation_input_tokens": cache_write}}})


if write:
    proj = (Path(os.environ["HOME"]) / ".claude" / "projects" /
            str(ws).replace("/", "-").replace(".", "-"))
    proj.mkdir(parents=True, exist_ok=True)
    rows = [usage(False, 1200, 90, 7000)]
    if cost_state:
        rows.append(json.dumps({"type": "cost-state", "sessionId": "sess-1",
                                "totalCostUSD": 5.0254438,
                                "modelUsage": {}}))
    (proj / "sess-1.jsonl").write_text("\\n".join(rows) + "\\n")
    side = proj / "sess-1" / "subagents"
    side.mkdir(parents=True, exist_ok=True)
    (side / "agent-a.jsonl").write_text(usage(True, 40, 777) + "\\n")
if stdout_face == "json":
    print(json.dumps({"total_cost_usd": 2.5,
                      "usage": {"input_tokens": 10,
                                "output_tokens": 3}}))
elif stdout_face == "junk":
    print("not json at all")
if overrun:
    time.sleep(30)
'''


def _usage_row(*, sidechain: bool, inp: int, out: int, cache: int = 0,
               cache_write: int = 0, cwd: str | None = None) -> str:
    row = {"type": "assistant", "isSidechain": sidechain,
           "timestamp": "2026-11-25T00:00:00.000Z",
           "message": {"role": "assistant", "model": MODEL,
                       "usage": {"input_tokens": inp,
                                 "output_tokens": out,
                                 "cache_read_input_tokens": cache,
                                 "cache_creation_input_tokens": cache_write}}}
    if cwd is not None:
        row["cwd"] = cwd
    return json.dumps(row, ensure_ascii=False)


def _cost_state_row(usd: float) -> str:
    return json.dumps({"type": "cost-state", "sessionId": "sess-1",
                       "totalCostUSD": usd, "modelUsage": {}},
                      ensure_ascii=False)


def _mangled(workspace: Path) -> str:
    return str(Path(workspace).resolve()).replace("/", "-").replace(
        ".", "-")


def _session_dir(projects: Path, workspace: Path) -> Path:
    d = projects / _mangled(workspace)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_tx(directory: Path, name: str, rows: list[str], *,
              workers: dict[str, list[str]] | None = None,
              mtime: float | None = None) -> Path:
    tx = directory / name
    tx.write_text("\n".join(rows) + "\n", encoding="utf-8")
    if workers:
        side = directory / tx.stem / "subagents"
        side.mkdir(parents=True, exist_ok=True)
        for fname, wrows in workers.items():
            (side / fname).write_text("\n".join(wrows) + "\n",
                                      encoding="utf-8")
    if mtime is not None:
        os.utime(tx, (mtime, mtime))
    return tx


def _launch(tmp_path, monkeypatch, **flags) -> dict:
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("K1005_COST_STATE",
                       "1" if flags.get("cost_state") else "0")
    monkeypatch.setenv("K1005_OVERRUN", "1" if flags.get("overrun") else "0")
    monkeypatch.setenv("K1005_WRITE", "0" if flags.get("write") is False
                       else "1")
    monkeypatch.setenv("K1005_STDOUT", flags.get("stdout_face", "none"))
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    stub = tmp_path / "k1005_stub_session.py"
    stub.write_text(_STUB_SRC, encoding="utf-8")
    return lr.launch_session(ws, "RUN THE LOOP", budget_usd=5.0,
                             wall_cap_s=1.0 if flags.get("overrun") else 30.0,
                             session_cmd=f'"{sys.executable}" "{stub}"')


# ------------------------------------------------------------------- (a)
def test_projects_dir_maps_the_resolved_workspace_path(tmp_path):
    # Arrange
    ws = tmp_path / "runs" / "ws-1"
    ws.mkdir(parents=True)

    # Act
    got = lr.claude_projects_dir(ws, projects_root=tmp_path / "projects")

    # Assert: the resolved path, separators and dots folded to '-' — the
    # rule the CLI itself uses (verified against a symlinked /tmp cwd).
    assert got.name == _mangled(ws)
    assert got.parent == tmp_path / "projects"


# ------------------------------------------------------------------- (b)
def test_session_transcript_is_the_newest_written_after_launch(tmp_path):
    # Arrange: an earlier run in the same dir, then this one.
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    cwd = str(ws.resolve())
    d = _session_dir(tmp_path / "projects", ws)
    _write_tx(d, "prev.jsonl", [_usage_row(sidechain=False, inp=1, out=1,
                                           cwd=cwd)],
              mtime=time.time() - 600.0)
    started = time.time() - 5.0
    current = _write_tx(d, "sess-1.jsonl",
                        [_usage_row(sidechain=False, inp=2, out=2,
                                    cwd=cwd)],
                        mtime=started + 1.0)

    # Act
    got = lr.session_transcript(ws, started,
                               projects_root=tmp_path / "projects")

    # Assert
    assert got == current


def test_session_transcript_ignores_rows_from_another_workspace(tmp_path):
    # Arrange: the right dir shape, but the rows name a different cwd (a
    # resumed or moved session is not this run's transcript).
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    d = _session_dir(tmp_path / "projects", ws)
    _write_tx(d, "sess-1.jsonl",
              [_usage_row(sidechain=False, inp=1, out=1,
                          cwd=str(tmp_path / "elsewhere"))],
              mtime=time.time())

    # Act / Assert
    assert lr.session_transcript(ws, time.time() - 5.0,
                                 projects_root=tmp_path / "projects") is None


def test_session_transcript_is_absent_when_the_dir_is_missing(tmp_path):
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)

    # Act / Assert
    assert lr.session_transcript(ws, time.time() - 5.0,
                                 projects_root=tmp_path / "nope") is None


# ------------------------------------------------------------------- (c+d)
def test_transcript_usage_sums_orchestrator_and_worker_rows(tmp_path):
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    d = _session_dir(tmp_path / "projects", ws)
    tx = _write_tx(d, "sess-1.jsonl",
                   [_usage_row(sidechain=False, inp=100, out=7, cache=900),
                    _cost_state_row(CLI_USD)],
                   workers={"agent-a.jsonl": [
                       _usage_row(sidechain=True, inp=50, out=300),
                       _usage_row(sidechain=True, inp=20, out=100,
                                  cache_write=5)]})

    # Act
    usage = lr.transcript_usage(tx)

    # Assert: the two populations stay apart — the orchestrator rows are
    # the main file's, the worker rows come from beside it.
    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 7
    assert usage["cache_read_input_tokens"] == 900
    assert usage["worker_input_tokens"] == 70
    assert usage["worker_output_tokens"] == 400
    assert usage["worker_cache_creation_input_tokens"] == 5


def test_transcript_usage_reads_the_last_cost_state_number(tmp_path):
    # Arrange: the CLI rewrites its cumulative cost face; the last row is
    # the session total.
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    d = _session_dir(tmp_path / "projects", ws)
    tx = _write_tx(d, "sess-1.jsonl",
                   [_cost_state_row(1.5),
                    _usage_row(sidechain=False, inp=1, out=1),
                    _cost_state_row(CLI_USD)])

    # Act / Assert
    assert lr.transcript_usage(tx)["total_cost_usd"] == pytest.approx(
        CLI_USD)


def test_transcript_usage_without_a_cost_state_row_has_no_number(tmp_path):
    # Arrange: the hard-kill shape — usage rows, no cost-state row.
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    d = _session_dir(tmp_path / "projects", ws)
    tx = _write_tx(d, "sess-1.jsonl",
                   [_usage_row(sidechain=False, inp=10, out=3)])

    # Act / Assert
    usage = lr.transcript_usage(tx)
    assert usage["total_cost_usd"] is None
    assert usage["cost_state_rows"] == 0
    assert usage["output_tokens"] == 3


# ------------------------------------------------------------------- (i)
def test_malformed_transcript_lines_are_skipped(tmp_path):
    # Arrange
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    d = _session_dir(tmp_path / "projects", ws)
    tx = _write_tx(d, "sess-1.jsonl",
                   ["{ broken", "", _usage_row(sidechain=False, inp=11,
                                               out=4)],
                   workers={"agent-a.jsonl": [
                       "nope", _usage_row(sidechain=True, inp=0, out=6)]})

    # Act
    usage = lr.transcript_usage(tx)

    # Assert
    assert usage["input_tokens"] == 11
    assert usage["worker_output_tokens"] == 6


# ------------------------------------------------------------------- (e)
def test_killed_session_reports_cost_harvested_from_the_transcript(
        tmp_path, monkeypatch):
    # Act: the stub leaves the transcript a running session leaves, then
    # overruns the one-second wall cap.
    rec = _launch(tmp_path, monkeypatch, cost_state=True, overrun=True)

    # Assert: the wall cap fired, the session's own stdout carried
    # nothing, and the cost face is no longer empty.
    assert rec["timed_out"] is True
    cost = rec["session_cost"]
    assert cost is not None, "the killed session's consumption must be " \
                             "harvested, not left blank"
    assert cost["total_cost_usd"] == pytest.approx(CLI_USD)
    assert cost["cost_source"] == "transcript-cost-state"
    assert cost["transcript_usage"]["worker_output_tokens"] == 777


# ------------------------------------------------------------------- (f)
def test_killed_session_without_cost_state_names_why_it_has_no_number(
        tmp_path, monkeypatch):
    # Act
    rec = _launch(tmp_path, monkeypatch, cost_state=False, overrun=True)

    # Assert: dollars are absent because the CLI never wrote them — the
    # row says so, while the tokens it did write are still booked.
    cost = rec["session_cost"]
    assert cost["total_cost_usd"] is None, "no CLI cost face exists for a " \
                                           "hard kill: never invent one"
    assert "cost-state" in cost["cost_unavailable_reason"]
    assert cost["transcript_usage"]["output_tokens"] == 90
    assert cost["transcript_usage"]["worker_output_tokens"] == 777


# ------------------------------------------------------------------- (g)
def test_stdout_cost_report_keeps_precedence_over_the_transcript(
        tmp_path, monkeypatch):
    # Act: a completed session whose transcript carries a different cost
    # face than its own report.
    rec = _launch(tmp_path, monkeypatch, cost_state=True, overrun=False,
                  stdout_face="json")

    # Assert
    cost = rec["session_cost"]
    assert cost["total_cost_usd"] == pytest.approx(2.5)
    assert cost["cost_source"] == "cli-result"
    assert "transcript_usage" not in cost


def test_silent_stdout_falls_back_to_the_transcript(tmp_path, monkeypatch):
    """The other half of the precedence face: a session that exits 0 with
    output the parser could not read (a wrapper swallowing stdout) still
    gets its cost from the transcript."""
    # Act
    rec = _launch(tmp_path, monkeypatch, cost_state=True, overrun=False,
                  stdout_face="junk")

    # Assert
    assert rec["returncode"] == 0
    assert rec["session_cost"]["total_cost_usd"] == pytest.approx(CLI_USD)
    assert rec["session_cost"]["cost_source"] == "transcript-cost-state"


# ------------------------------------------------------------------- (h)
def test_no_transcript_leaves_the_cost_face_absent(tmp_path, monkeypatch):
    # Act: the session overruns the cap and writes no transcript at all.
    rec = _launch(tmp_path, monkeypatch, overrun=True, write=False)

    # Assert: nothing was measured, so nothing is reported — the shape
    # stays exactly the pre-change one.
    assert rec["timed_out"] is True
    assert rec["session_cost"] is None
