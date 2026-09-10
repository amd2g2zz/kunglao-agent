# -*- coding: utf-8 -*-
"""Thompson rank face (issue 218) — statusline + tick-report visibility for the
ranker's rank_feeds event, and the emit-failure marker.

Coverage map (issue 218 acceptance):
  - snapshot rank field: the latest rank_feeds event -> top action's claim id +
    sampled score + age/staleness; absent-and-marked (never crashed) when no
    ranking run exists
  - fail-open visibility: a crashed kunglao_log.emit leaves the marker
    (runs/.rank-emit-fail.json) observable as the snapshot health bit, while
    the ranking result stays byte-identical (the silent fail-open contract)
  - renderer: the rank chip renders fresh / stale / emit-broken faces; absent
    data = hidden segment; a snapshot without the rank keys still renders
  - single source: the snapshot delegates to scripts/rank_face.py, the one
    computation the tick report reads too
  - the rank_feeds payload/schema is untouched by the marker write
"""
from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
RENDERER = SCRIPTS / "statusline_render.mjs"
sys.path.insert(0, str(SCRIPTS))

import kunglao_log  # noqa: E402
import priority_ratio as pr  # noqa: E402
import rank_face  # noqa: E402
import statusline_snapshot as sls  # noqa: E402

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _make_ws(tmp_path: Path) -> Path:
    """Minimal kunglao workspace (the statusline suites' shared shape)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "analysis_state.txt").write_text(
        "# analysis_state\nproject_type=windows\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def _touch_heartbeat(ws: Path) -> None:
    (ws / "runs" / ".heartbeat.json").write_text(json.dumps({
        "started_ts": _iso(datetime.now(timezone.utc) - timedelta(seconds=60)),
        "last_tick_ts": _iso(datetime.now(timezone.utc)),
    }), encoding="utf-8")


def _seed_rank_event(ws: Path, *, ranked_order=("C-2", "C-1"),
                     scores: dict | None = None, age_s: int = 0) -> Path:
    """One emit-shaped rank_feeds row in today's day file."""
    if scores is None:
        scores = {cid: 0.5 for cid in ranked_order}
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log = ws / "runs" / "logs" / f"kunglao-{day}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": _iso(datetime.now(timezone.utc) - timedelta(seconds=age_s)),
        "actor": "priority_ratio", "action": "rank_feeds",
        "detail": json.dumps({
            "feeds": {cid: {"thompson_sample": "sample"} for cid in ranked_order},
            "scores": scores, "ranked_order": list(ranked_order),
            "input_fingerprint": {"claims_hash": "a", "evidence_hash": "b",
                                  "rng_base": 1, "fingerprint": "c"},
        }, sort_keys=True, ensure_ascii=False),
    }
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
    return log


def _rank_inputs(ws: Path):
    claims = [
        {"id": "C-1", "status": "OPEN", "promotion_attempts": 0,
         "statement": "one", "answers_question": "pq-a"},
        {"id": "C-2", "status": "OPEN", "promotion_attempts": 1,
         "statement": "two"},
    ]
    return (claims, {"depends_on": {}, "competitor_groups": {}},
            pr.EvidenceView(terminal_fact_claims=frozenset({"C-1"}),
                            verified_fact_count=1, ws=Path(ws)))


def _run_rank(ws: Path, seed: int = 7):
    claims, deps, ev = _rank_inputs(ws)
    return pr.priority_ratio(claims, deps, ev, rng=random.Random(seed))


# ===========================================================================
# 1. producer — snapshot rank field + fail-open health bit
# ===========================================================================

class TestSnapshotRankFace:
    def test_rank_field_reads_latest_rank_feeds_event(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _seed_rank_event(ws, ranked_order=("C-1", "C-2"),
                         scores={"C-1": 0.42, "C-2": 0.91})
        _seed_rank_event(ws, ranked_order=("C-2", "C-1"),
                         scores={"C-1": 0.42, "C-2": 0.734123})
        snap = sls.build_snapshot(ws)
        assert snap["rank"]["claim"] == "C-2"          # latest run wins
        assert snap["rank"]["score"] == pytest.approx(0.734123)
        assert snap["rank"]["stale"] is False
        assert snap["rank"]["ts"]
        assert 0 <= snap["rank"]["age_s"] < 120
        assert snap["rank_log"] == {"ok": True, "error": None, "ts": None}

    def test_rank_absent_and_marked_without_runs(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        snap = sls.build_snapshot(ws)                  # must not raise
        assert snap["rank"] == {"claim": None, "score": None, "ts": None,
                                "age_s": None, "stale": True}
        assert snap["rank_log"]["ok"] is True

    def test_rank_stale_past_the_budget(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _seed_rank_event(ws, age_s=int(rank_face.RANK_STALE_MINUTES * 60) + 600)
        snap = sls.build_snapshot(ws)
        assert snap["rank"]["claim"] == "C-2"          # stale, still named
        assert snap["rank"]["stale"] is True
        assert snap["rank"]["age_s"] > rank_face.RANK_STALE_MINUTES * 60

    def test_empty_ranking_run_is_fresh_not_absent(self, tmp_path):
        """A successful run that found no dispatchable claim: no claim to
        show, but the log itself is alive (not the absent face)."""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _seed_rank_event(ws, ranked_order=(), scores={})
        snap = sls.build_snapshot(ws)
        assert snap["rank"]["claim"] is None
        assert snap["rank"]["stale"] is False
        assert snap["rank_log"]["ok"] is True


class TestRankEmitFailOpen:
    def test_emit_crash_marks_the_snapshot_and_keeps_the_rank(
            self, tmp_path, monkeypatch):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        baseline = _run_rank(ws)
        marker = ws / "runs" / ".rank-emit-fail.json"
        assert not marker.exists()                     # a clean emit leaves none
        assert sls.build_snapshot(ws)["rank_log"]["ok"] is True

        def _boom(*args, **kwargs):
            raise RuntimeError("emit exploded")

        monkeypatch.setattr(kunglao_log, "emit", _boom)
        crashed = _run_rank(ws)
        assert [(a.claim_id, a.score, dict(a.feeds)) for a in crashed] == \
            [(a.claim_id, a.score, dict(a.feeds)) for a in baseline]
        assert marker.exists()
        doc = json.loads(marker.read_text(encoding="utf-8"))
        assert doc["error"] == "RuntimeError"
        assert doc["ts"]
        snap = sls.build_snapshot(ws)
        assert snap["rank_log"] == {"ok": False, "error": "RuntimeError",
                                    "ts": doc["ts"]}

    def test_later_success_clears_the_marker(self, tmp_path, monkeypatch):
        """Marker semantics = LAST attempt: the health bit recovers by
        itself once the emit path works again."""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        marker = ws / "runs" / ".rank-emit-fail.json"
        real_emit = kunglao_log.emit
        state = {"boom": True}

        def _maybe_boom(*args, **kwargs):
            if state["boom"]:
                raise RuntimeError("emit exploded")
            return real_emit(*args, **kwargs)

        monkeypatch.setattr(kunglao_log, "emit", _maybe_boom)
        _run_rank(ws)
        assert marker.exists()
        assert sls.build_snapshot(ws)["rank_log"]["ok"] is False
        state["boom"] = False
        _run_rank(ws)
        assert not marker.exists()
        assert sls.build_snapshot(ws)["rank_log"]["ok"] is True

    def test_marker_write_leaves_the_rank_feeds_payload_byte_identical(
            self, tmp_path, monkeypatch):
        """The emit payload is built BEFORE the crash face — the marker
        write must never perturb it (replayability intact)."""
        ws = _make_ws(tmp_path)
        captured: list = []
        real_emit = kunglao_log.emit
        state = {"boom": True}

        def _capture(*args, **kwargs):
            captured.append(kwargs.get("detail"))
            if state["boom"]:
                raise RuntimeError("emit exploded")
            return real_emit(*args, **kwargs)

        monkeypatch.setattr(kunglao_log, "emit", _capture)
        _run_rank(ws)                                  # recorded, then crashed
        state["boom"] = False
        _run_rank(ws)                                  # recorded + written
        assert len(captured) == 2
        assert captured[0] == captured[1]


# ===========================================================================
# 2. single source — the same face feeds the tick report
# ===========================================================================

class TestSingleSourceRankFace:
    def test_snapshot_delegates_to_the_shared_rank_face(self):
        assert sls._rank_face is rank_face.face

    def test_snapshot_and_face_computation_agree(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _seed_rank_event(ws, ranked_order=("C-2",), scores={"C-2": 0.61})
        snap = sls.build_snapshot(ws)
        face = rank_face.face(ws)
        assert snap["rank"]["claim"] == face["rank"]["claim"] == "C-2"
        assert snap["rank"]["score"] == face["rank"]["score"]
        assert snap["rank"]["stale"] == face["rank"]["stale"] is False
        assert snap["rank_log"] == face["rank_log"]

    def test_tick_report_carries_the_rank_face(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _seed_rank_event(ws, ranked_order=("C-2",), scores={"C-2": 0.61})
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "heartbeat_tick.py"), str(ws)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=180)
        out = ws / "runs" / ".heartbeat-tick.json"
        assert out.exists(), (
            f"tick must write the report; rc={r.returncode} "
            f"stderr={r.stderr[-300:]}")
        report = json.loads(out.read_text(encoding="utf-8"))
        face = rank_face.face(ws)
        assert report["rank"]["claim"] == face["rank"]["claim"] == "C-2"
        assert report["rank"]["score"] == face["rank"]["score"]
        assert report["rank_log"]["ok"] is True


# ===========================================================================
# 3. renderer — the rank chip is a pure view over the snapshot
# ===========================================================================

def _snap(**over) -> dict:
    snap = {"schema": 2, "state": "analyzing",
            "color": {"hue": 140, "sat": 72, "light": 55},
            "v_hist": [0.1, 0.3], "v_norm": 0.3,
            "pq": {"answered": 1, "total": 2, "blocked": 0},
            "h_bits": 1.3, "h_trend": "falling",
            "health": {"oracle": True, "retro": True, "dormant": True},
            "now": {"claim": None, "op": None}}
    snap.update(over)
    return snap


def _write_snapshot(ws: Path, snap: dict) -> Path:
    p = ws / "runs" / ".kunglao-statusline.json"
    p.write_text(json.dumps(snap), encoding="utf-8")
    return p


def _run_renderer(ws: Path) -> subprocess.CompletedProcess:
    payload = json.dumps({"workspace": {"current_dir": str(ws)},
                          "model": {"display_name": "t"}})
    env = dict(os.environ)
    env["KUNGLAO_STATUSLINE_HUD"] = ""      # deterministic, no HUD passthrough
    return subprocess.run(["node", str(RENDERER)], input=payload,
                          capture_output=True, text=True, timeout=30,
                          cwd=str(ws.parent), env=env)


def _rank_field(stale: bool = False, claim: str = "C-2",
                score: float = 0.734) -> dict:
    return {"claim": claim, "score": score,
            "ts": _iso(datetime.now(timezone.utc)), "age_s": 3.0,
            "stale": stale}


@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
class TestRankRenderer:
    def test_fresh_rank_chip_renders(self, tmp_path):
        ws = _make_ws(tmp_path)
        _write_snapshot(ws, _snap(rank=_rank_field(),
                                  rank_log={"ok": True, "error": None,
                                            "ts": None}))
        r = _run_renderer(ws)
        assert r.returncode == 0, r.stderr
        out = ANSI_RE.sub("", r.stdout)
        assert "R:C-2 0.73" in out
        idx = r.stdout.find("R:C-2")
        assert color_prefix(r.stdout, idx) == "\x1b[36m"   # cyan = working

    def test_stale_rank_chip_is_amber(self, tmp_path):
        ws = _make_ws(tmp_path)
        _write_snapshot(ws, _snap(rank=_rank_field(stale=True),
                                  rank_log={"ok": True, "error": None,
                                            "ts": None}))
        r = _run_renderer(ws)
        assert r.returncode == 0, r.stderr
        assert "R:C-2 0.73" in ANSI_RE.sub("", r.stdout)
        idx = r.stdout.find("R:C-2")
        assert color_prefix(r.stdout, idx) == "\x1b[33m"   # amber = stall-suspect

    def test_emit_broken_marker_is_red(self, tmp_path):
        ws = _make_ws(tmp_path)
        _write_snapshot(ws, _snap(rank=_rank_field(),
                                  rank_log={"ok": False, "error": "RuntimeError",
                                            "ts": _iso(datetime.now(timezone.utc))}))
        r = _run_renderer(ws)
        assert r.returncode == 0, r.stderr
        out = ANSI_RE.sub("", r.stdout)
        assert "R✖" in out
        idx = r.stdout.find("R✖")
        assert color_prefix(r.stdout, idx) == "\x1b[31m"   # red = broken

    def test_absent_rank_is_hidden_not_broken(self, tmp_path):
        ws = _make_ws(tmp_path)
        _write_snapshot(ws, _snap())            # no rank / rank_log keys at all
        r = _run_renderer(ws)
        assert r.returncode == 0, r.stderr
        assert "ReferenceError" not in r.stderr
        out = ANSI_RE.sub("", r.stdout)
        assert out.strip(), "the line still renders"
        assert "R:" not in out
        assert "R✖" not in out


def color_prefix(stdout: str, idx: int, window: int = 12) -> str:
    """The ANSI color that opens the segment ending at `idx`."""
    return stdout[max(0, idx - window):idx]
