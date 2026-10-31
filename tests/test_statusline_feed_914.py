# -*- coding: utf-8 -*-
"""tests/test_statusline_feed_914.py — the rl-v2 statusline feed face (#914).

The session statusline must reflect the rl-v2 architecture (owner
directive 2026-10-30): the OLD loop's state face (branch/cost/session)
is retired as the loop's data source. This suite pins the feed face
(``experiments/learning-loop/state/statusline_feed.py``):

  1. the data contract — ``feed(ws)`` renders the loop state from the
     unified ledger ALONE: lap/rollout ids, current task (the belief
     snapshot's current_goal) + method family, P(s) level + trend,
     pool stats, trust band, current phase tag. ``loop-statusline/1``.
  2. determinism — the same ledger fixture renders a byte-identical
     feed dict (content hash; NO wall clock in the content).
  3. the fail-closed wall — a garbage ledger row raises at the face
     (the renderer still fails-open on an absent/invalid feed; that
     half is pinned in test_statusline_loop_914.py).
  4. the honest degraded view — a missing/incomplete ledger reads the
     STABLE empty face (all-None segments, zero pool), never a crash,
     never a placeholder value the producer never computed.
  5. materialization — ``write_feed(ws)`` lands the feed atomically at
     ``runs/.loop-statusline.json`` (the policy-state precedent: the
     producer subsystem writes, the statusline snapshot reads as pure
     disk observation — the deployed scripts tree cannot import the
     experiments tree, so the FILE is the only bridge).
  6. the loop wiring — the #913 loop's belief seam materializes the
     feed once per lap (the production write trigger).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import loop as loop913  # noqa: E402
from rlvr import learning_seal as seal  # noqa: E402
from rlvr import q_cells  # noqa: E402
from state import progress, statusline_feed  # noqa: E402


@pytest.fixture(autouse=True)
def _unarmed_seal(monkeypatch, tmp_path):
    """The suite's default seal posture (the 903/913/915 posture): rows
    pass through unsigned."""
    monkeypatch.setattr(seal, "KEY_PATH", tmp_path / "absent.key")
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})


@pytest.fixture(autouse=True)
def _isolated_store_root(monkeypatch, tmp_path):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))


_REF = "evidence/F001.md#L4-L6"


def _sub(gid: str, status: str) -> progress.Subgoal:
    return progress.Subgoal(id=gid, status=status,
                            evidence_refs=(_REF,), confidence=0.8)


def _action_row(ws, *, rid: str = "ro-1", kind: str = "assign_step",
                target: str = "[triage] map the surface",
                params: dict | None = None) -> dict:
    row = q_cells.append_action(
        ws, kind, rid, target,
        step_id=f"{rid}-s01",
        params=params if params is not None
        else ({"method_family": "static-scan", "tier": 1,
               "phase": "triage"} if kind == "assign_step" else None),
        ts="2026-01-01T00:00:00Z")
    return row["row"]


# ---------------------------------------------------- 1. the contract

def test_feed_schema_and_full_shape(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _action_row(ws)
    doc = statusline_feed.feed(ws)
    assert doc["schema"] == "loop-statusline/1"
    for key in ("lap", "laps", "rollout_id", "task", "method_family",
                "phase", "p_level", "p_trend", "pool", "trust_band"):
        assert key in doc, f"feed field {key} missing"
    # every segment sources from the ledger alone: the fixture ledger
    # carries an action row but no telemetry/transition rows yet.
    assert doc["lap"] is None
    assert doc["laps"] == []
    assert doc["rollout_id"] == "ro-1"
    assert doc["method_family"] == "static-scan"
    assert doc["phase"] == "triage"
    assert doc["p_level"] is None
    assert doc["p_trend"] is None
    assert doc["pool"] == {"episodes": 0}
    assert doc["trust_band"] is None


def test_feed_lap_and_p_from_the_ledger(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _action_row(ws)
    # the P trajectory rides the state face's OWN rows (telemetry's
    # single source): two transitions, rising then falling.
    progress.record_transition(ws, before=[], after=[_sub("g1", "UNVERIFIED")],
                               claim="C-1")
    progress.record_transition(
        ws, before=[_sub("g1", "UNVERIFIED")],
        after=[_sub("g1", "PROVEN")], claim="C-1")
    from state import telemetry
    telemetry.emit(ws, "terminator", "TERM_WATCHDOG_ARMED", lap=3,
                   rollout_id="ro-1")
    doc = statusline_feed.feed(ws)
    assert doc["laps"] == [3]
    assert doc["lap"] == 3
    w_unv = progress.status_weight("UNVERIFIED")
    w_pro = progress.status_weight("PROVEN")
    # the P series is the ΔP cumsum: born-at-floor banks 0, the climb
    # banks w_pro - w_unv.
    assert doc["p_level"] == pytest.approx(round(w_pro - w_unv, 6))
    assert doc["p_trend"] == "rising"


def test_feed_trend_reads_the_last_delta(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    progress.record_transition(ws, before=[], after=[_sub("g1", "UNVERIFIED")])
    progress.record_transition(
        ws, before=[_sub("g1", "UNVERIFIED")],
        after=[_sub("g1", "PROVEN")])
    progress.record_transition(
        ws, before=[_sub("g1", "PROVEN")], after=[_sub("g1", "REFUTED")])
    doc = statusline_feed.feed(ws)
    assert doc["p_trend"] == "falling"


def test_feed_task_from_belief_goal(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _action_row(ws, kind="select_task",
                target="recover the license check")
    doc = statusline_feed.feed(ws)
    assert doc["task"] == "recover the license check"


def test_feed_trust_band_from_latest_observation(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    q_cells.append_observation(ws, "sig", "static-scan", 0.5,
                               source="settlement",
                               confidence_band="ROUND_CREDIT",
                               ts="2026-01-01T00:00:00Z")
    doc = statusline_feed.feed(ws)
    assert doc["trust_band"] == "ROUND_CREDIT"


def test_feed_latest_action_row_wins(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _action_row(ws, rid="ro-1", params={"method_family": "static-scan",
                                        "phase": "triage"})
    _action_row(ws, rid="ro-2", params={"method_family": "debugger",
                                        "phase": "extract"})
    doc = statusline_feed.feed(ws)
    assert doc["rollout_id"] == "ro-2"
    assert doc["method_family"] == "debugger"
    assert doc["phase"] == "extract"


# ---------------------------------------------------- 2. determinism

def test_feed_deterministic_content_hash_no_ts(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _action_row(ws)
    progress.record_transition(ws, before=[], after=[_sub("g1", "UNVERIFIED")])
    a = statusline_feed.feed(ws)
    b = statusline_feed.feed(ws)
    da = json.dumps(a, sort_keys=True, ensure_ascii=False)
    db = json.dumps(b, sort_keys=True, ensure_ascii=False)
    assert da == db, "same ledger fixture must render a byte-identical feed"
    assert "ts" not in a, "no wall clock in the feed content"


def test_write_feed_byte_identical_and_atomic(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _action_row(ws)
    p1 = statusline_feed.write_feed(ws)
    first = p1.read_bytes()
    p2 = statusline_feed.write_feed(ws)
    assert p1 == p2 == ws / "runs" / ".loop-statusline.json"
    assert p2.read_bytes() == first, "materialized feed is content-stable"
    doc = json.loads(p2.read_text(encoding="utf-8"))
    assert doc == statusline_feed.feed(ws)


# ------------------------------------------------ 3. the fail-closed wall

def test_wall_non_mapping_action_params_raise(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    row = dict(_action_row(ws))
    row["params"] = "garbage"  # schema-valid JSON, garbage shape
    with open(ws / "runs" / "experience.jsonl", "a",
              encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
    with pytest.raises(ValueError):
        statusline_feed.feed(ws)


def test_wall_non_finite_p_delta_raises(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    progress.record_transition(ws, before=[], after=[_sub("g1", "UNVERIFIED")])
    path = ws / "runs" / "experience.jsonl"
    rows = [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows[-1]["fingerprint"] = "delta_p=nan"  # schema-valid JSON, poison
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        statusline_feed.feed(ws)


# ------------------------------------------------ 4. the degraded view

def test_degraded_view_stable_empty(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    doc = statusline_feed.feed(ws)
    assert doc == {
        "schema": "loop-statusline/1",
        "lap": None, "laps": [], "rollout_id": None, "task": None,
        "method_family": None, "phase": None, "p_level": None,
        "p_trend": None, "pool": {"episodes": 0}, "trust_band": None,
    }


# ------------------------------------------------ 5. the loop wiring

def test_loop_belief_seam_materializes_the_feed(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    loop913.run_loop(ws, laps=1)
    p = ws / "runs" / ".loop-statusline.json"
    assert p.is_file(), "the belief seam must materialize the feed"
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["schema"] == "loop-statusline/1"
    assert doc == statusline_feed.feed(ws)
    assert doc["lap"] == 1, "one lap ran; the feed must show it"
    assert doc["rollout_id"], "the lap's rollout id rides the feed"
