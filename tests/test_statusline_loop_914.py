# -*- coding: utf-8 -*-
"""tests/test_statusline_loop_914.py — the rl-v2 loop segments ride the
statusline pipeline (#914).

The pipeline is FIXED (issue #142/#212 architecture — extend, never
reinvent): the loop-side feed face materializes
``runs/.loop-statusline.json``; ``statusline_snapshot.py`` embeds it as
the ``loop`` section (pure disk observation — the deployed scripts tree
cannot import the experiments tree, so the FILE is the bridge, the
components/policy faces' posture); ``statusline_render.mjs`` renders
the loop segments from ``snap.loop`` as a dumb view.

Pins:
  1. snapshot embedding — a well-formed feed file rides verbatim;
     absent / corrupt / wrong-schema files are the HIDDEN face (None),
     never a crash, never a fabricated section.
  2. renderer segments — lap chip, P(s) level + trend arrow, phase tag,
     pool count, trust band; absent loop section = no loop segments and
     the line still renders (fail-open); a degraded (all-None) loop
     section renders NO placeholder segments.
  3. fabrication guards — ``lap: null`` must never render ``L0`` and
     ``p_level: null`` must never render ``P0.00`` (the Number(null)
     trap the rank chip already pinned).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
RENDERER = SCRIPTS / "statusline_render.mjs"
sys.path.insert(0, str(SCRIPTS))

import statusline_snapshot as sls  # noqa: E402

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

FULL_FEED = {
    "schema": "loop-statusline/1",
    "lap": 2,
    "laps": [1, 2],
    "rollout_id": "ro-task-lap2",
    "task": "recover the license check",
    "method_family": "static-scan",
    "phase": "extract",
    "p_level": 1.2,
    "p_trend": "rising",
    "pool": {"episodes": 3},
    "trust_band": "ROUND_CREDIT",
}


def _make_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "analysis_state.txt").write_text(
        "# analysis_state\nproject_type=windows\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def _write_feed_file(ws: Path, doc: dict | None) -> None:
    if doc is None:
        (ws / "runs" / ".loop-statusline.json").write_text(
            "{not json at all", encoding="utf-8")
        return
    (ws / "runs" / ".loop-statusline.json").write_text(
        json.dumps(doc), encoding="utf-8")


def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _write_snapshot(ws: Path, snap: dict, age_s: int = 0) -> None:
    p = ws / "runs" / ".kunglao-statusline.json"
    p.write_text(json.dumps(snap), encoding="utf-8")
    if age_s:
        old = time.time() - age_s
        os.utime(p, (old, old))


def _run_renderer(ws: Path) -> subprocess.CompletedProcess:
    """Drive the renderer subprocess against a fixture workspace (the
    #142 helper's shape; HUD + clock seams pinned deterministic)."""
    payload = json.dumps(
        {"workspace": {"current_dir": str(ws)}, "model": {"display_name": "t"}})
    env = dict(os.environ)
    env["KUNGLAO_STATUSLINE_NOW_MS"] = str(int(time.time() * 1000))
    return subprocess.run(
        ["node", str(RENDERER)], input=payload, capture_output=True,
        text=True, timeout=30, cwd=str(ws.parent), env=env)


# ------------------------------------------------- 1. snapshot embedding

class TestSnapshotEmbedding:
    def test_loop_section_rides_the_snapshot(self, tmp_path):
        ws = _make_ws(tmp_path)
        _write_feed_file(ws, FULL_FEED)
        snap = sls.build_snapshot(ws)
        assert snap["loop"] == FULL_FEED, \
            "the feed rides verbatim — single source, no re-derivation"

    def test_absent_feed_is_the_hidden_face(self, tmp_path):
        ws = _make_ws(tmp_path)
        snap = sls.build_snapshot(ws)
        assert snap["loop"] is None

    def test_corrupt_feed_is_the_hidden_face(self, tmp_path):
        ws = _make_ws(tmp_path)
        _write_feed_file(ws, None)
        snap = sls.build_snapshot(ws)
        assert snap["loop"] is None

    def test_wrong_schema_feed_is_the_hidden_face(self, tmp_path):
        ws = _make_ws(tmp_path)
        _write_feed_file(ws, {**FULL_FEED, "schema": "loop-statusline/0"})
        snap = sls.build_snapshot(ws)
        assert snap["loop"] is None

    def test_non_mapping_feed_is_the_hidden_face(self, tmp_path):
        ws = _make_ws(tmp_path)
        (ws / "runs" / ".loop-statusline.json").write_text(
            "[1, 2, 3]", encoding="utf-8")
        snap = sls.build_snapshot(ws)
        assert snap["loop"] is None


# --------------------------------------------------- 2. renderer segments

@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
class TestRendererLoopSegments:
    @pytest.fixture(autouse=True)
    def _no_hud(self, monkeypatch):
        monkeypatch.setenv("KUNGLAO_STATUSLINE_HUD", "")

    def _run(self, ws: Path) -> subprocess.CompletedProcess:
        return _run_renderer(ws)

    def _base_snap(self) -> dict:
        return {
            "schema": 2, "state": "analyzing",
            "color": {"hue": 140, "sat": 72, "light": 55},
            "v_hist": [0.1, 0.4], "v_norm": 0.4,
            "pq": {"answered": 1, "total": 5, "blocked": 0},
        }

    def test_full_loop_renders_all_segments(self, tmp_path):
        ws = _make_ws(tmp_path)
        _write_snapshot(ws, {**self._base_snap(), "loop": FULL_FEED})
        r = self._run(ws)
        assert r.returncode == 0, r.stderr
        line = _strip_ansi(r.stdout.rstrip("\n").split("\n")[-1])
        assert "L2·ro-task-lap2" in line, line
        assert "P1.20↑" in line, line
        assert "[extract]" in line, line
        assert "static-scan" in line, line
        assert "pool3" in line, line
        assert "T:ROUND_CREDIT" in line, line

    def test_trend_arrows_map_the_closed_table(self, tmp_path):
        ws = _make_ws(tmp_path)
        _write_snapshot(ws, {**self._base_snap(),
                             "loop": {**FULL_FEED, "p_trend": "falling",
                                      "p_level": 0.4}})
        r = self._run(ws)
        line = _strip_ansi(r.stdout.rstrip("\n").split("\n")[-1])
        assert "P0.40↓" in line, line

    def test_no_loop_section_still_renders(self, tmp_path):
        ws = _make_ws(tmp_path)
        _write_snapshot(ws, self._base_snap())
        r = self._run(ws)
        assert r.returncode == 0, r.stderr
        line = _strip_ansi(r.stdout.rstrip("\n").split("\n")[-1])
        assert "analyzing" in line, "the base line survives"
        assert "L2" not in line and "pool" not in line, line

    def test_degraded_loop_section_renders_no_placeholders(self, tmp_path):
        ws = _make_ws(tmp_path)
        _write_feed_file(ws, {
            "schema": "loop-statusline/1", "lap": None, "laps": [],
            "rollout_id": None, "task": None, "method_family": None,
            "phase": None, "p_level": None, "p_trend": None,
            "pool": {"episodes": 0}, "trust_band": None,
        })
        _write_snapshot(ws, self._base_snap())
        r = self._run(ws)
        assert r.returncode == 0, r.stderr
        line = _strip_ansi(r.stdout.rstrip("\n").split("\n")[-1])
        assert "L0" not in line, "Number(null) must never fabricate L0"
        assert "P0.00" not in line, "Number(null) must never fabricate P0"
        assert "pool0" not in line
        assert "T:" not in line

    def test_garbage_loop_section_never_kills_the_line(self, tmp_path):
        ws = _make_ws(tmp_path)
        _write_feed_file(ws, {"schema": "loop-statusline/1",
                              "lap": "two", "p_level": "high",
                              "pool": "three", "rollout_id": 42})
        _write_snapshot(ws, self._base_snap())
        r = self._run(ws)
        assert r.returncode == 0, r.stderr
        line = _strip_ansi(r.stdout.rstrip("\n").split("\n")[-1])
        assert "analyzing" in line, "garbage segments never kill the line"
