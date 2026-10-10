# -*- coding: utf-8 -*-
"""Issue 1-F9 + 4-L6 — the obstacle invalidation face + read-time
probe re-certification.

Lens findings:

  1-F9 — obstacles are non-retractable attribution: an env entry
  repaired mid-run keeps ``ob=missing_env_entry`` in every future state
  signature and keeps feeding the termination floor's family decay.
  Fix: the additive retraction marker (``retracted: true`` + ts +
  reason, written INTO the row file — history stays on disk, the
  Phase-1 "a row is history" posture preserved), the
  ``missing_env_entry`` ↔ env-state sweep keyed on the additive
  optional ``env_key``, and ``read()``/``face()`` excluding retracted
  rows.

  4-L6 — probe certification is marker-shape substrings and ``read()``
  never re-checks. Fix: ``read()`` re-runs the marker check when the
  cited artifact still exists; present-but-shapeless → excluded (ONE
  warn); artifact gone → the row stays (history posture).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import kunglao_log  # noqa: E402
from rlvr import obstacles  # noqa: E402

PROBE_ARTIFACT = ("$ adb shell dumpsys package com.target\n"
                  "rc=0\n"
                  "output: package not found\n")


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _warn_recorder(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        obstacles, "warn",
        lambda op, reason, **kw: calls.append((str(op), str(reason))))
    return calls


def _artifact(ws: Path, rel: str = "runs/probe-dump.txt",
              text: str = PROBE_ARTIFACT) -> str:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return rel


def _record(ws, **kw) -> dict:
    out = obstacles.record(
        ws, kind=kw.pop("kind", "missing_env_entry"),
        cause=kw.pop("cause", "env entry adb missing on host"),
        evidence_path=kw.pop("evidence_path",
                             _artifact(ws, kw.pop("rel", None)
                                       or "runs/probe-dump.txt")),
        method_family=kw.pop("method_family", "dynamic-trace"), **kw)
    assert out["appended"], out["errors"]
    row = out["row"]
    row["_path"] = out["path"]  # the registry-relative file (test-only key)
    return row


def _row_file(ws: Path, row: dict) -> Path:
    return ws / row["_path"]


# ---------------------------------------------------------------- 1-F9

def test_env_key_rides_the_row(tmp_path) -> None:
    ws = _ws(tmp_path)
    row = _record(ws, env_key="adb")
    assert row["env_key"] == "adb"
    on_disk = json.loads(
        _row_file(ws, row).read_text("utf-8"))
    assert on_disk["env_key"] == "adb"


def test_sweep_retracts_repaired_entry(tmp_path, monkeypatch) -> None:
    ws = _ws(tmp_path)
    row = _record(ws, env_key="adb")
    (ws / "runs" / "env-state.json").write_text(json.dumps({
        "per_capability": {"adb": {"status": "pass",
                                   "last_probe_ts": "2026-10-11T00:00:00Z",
                                   "detail": "device present"}},
        "written_by": "env_state_probe",
    }), encoding="utf-8")
    calls = _warn_recorder(monkeypatch)
    retracted = obstacles.sweep_stale_obstacles(ws)
    assert [r["id"] for r in retracted] == [row["id"]]
    assert len(calls) == 1
    on_disk = json.loads(_row_file(ws, row).read_text("utf-8"))
    assert on_disk["retracted"] is True
    assert on_disk["retracted_reason"]
    # the face sees current truth: the repaired entry stops feeding it
    assert obstacles.face(ws)["present"] is False
    assert obstacles.face(ws)["count"] == 0


def test_sweep_skips_failing_and_unkeyed_rows(tmp_path) -> None:
    ws = _ws(tmp_path)
    keyed = _record(ws, env_key="adb")
    unkeyed = _record(ws, rel="runs/probe-dump2.txt")
    (ws / "runs" / "env-state.json").write_text(json.dumps({
        "per_capability": {"adb": {"status": "fail",
                                   "last_probe_ts": "2026-10-11T00:00:00Z",
                                   "detail": "still down"}},
    }), encoding="utf-8")
    assert obstacles.sweep_stale_obstacles(ws) == []
    rows = {r["id"] for r in obstacles.read(ws)}
    assert {keyed["id"], unkeyed["id"]} <= rows


def test_retract_manual_and_read_excludes(tmp_path) -> None:
    ws = _ws(tmp_path)
    row = _record(ws, kind="tool_limit",
                  cause="frida attach refuses",
                  rel="runs/probe-dump.txt")
    assert obstacles.retract(ws, row["id"], "superseded by OBS re-probe")
    on_disk = json.loads(_row_file(ws, row).read_text("utf-8"))
    assert on_disk["retracted"] is True
    assert on_disk["retracted_reason"] == "superseded by OBS re-probe"
    assert obstacles.read(ws) == []
    # unknown id: False, never a raise
    assert obstacles.retract(ws, "OBS-999", "nope") is False


def test_retracted_history_stays_on_disk(tmp_path) -> None:
    ws = _ws(tmp_path)
    row = _record(ws, env_key="adb")
    obstacles.retract(ws, row["id"], "env repaired")
    p = _row_file(ws, row)
    assert p.is_file()
    doc = json.loads(p.read_text("utf-8"))
    assert doc["kind"] == "missing_env_entry"  # the attribution survives
    assert doc["retracted_ts"]


# ---------------------------------------------------------------- 4-L6

def test_read_recheck_drops_shapeless_artifact(tmp_path, monkeypatch) -> None:
    ws = _ws(tmp_path)
    row = _record(ws)
    # the artifact is REWRITTEN after the row lands: markers stripped
    (ws / row["evidence_path"]).write_text(
        "the operator says the env entry is gone, trust me\n",
        encoding="utf-8")
    calls = _warn_recorder(monkeypatch)
    assert obstacles.read(ws) == []
    assert len(calls) == 1 and "4-L6" in calls[0][1]


def test_read_keeps_gone_artifact(tmp_path) -> None:
    """History posture pin: scratch cleanup under runs/ must not erase
    the attribution from state."""
    ws = _ws(tmp_path)
    row = _record(ws)
    (ws / row["evidence_path"]).unlink()
    rows = obstacles.read(ws)
    assert [r["id"] for r in rows] == [row["id"]]


def test_read_keeps_certified_artifact(tmp_path) -> None:
    ws = _ws(tmp_path)
    row = _record(ws)
    rows = obstacles.read(ws)
    assert [r["id"] for r in rows] == [row["id"]]
