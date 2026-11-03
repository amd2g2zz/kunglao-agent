# -*- coding: utf-8 -*-
"""tests/test_write_guard_faces_818.py — the PreToolUse write guard's
carrier taxonomy, post-image reconstruction, and the #57 status-first
gate, in the MEASURED leg (issue #818 coverage climb; the hooks gate
chain).

Real fixtures only: tmp workspaces, real worker-status files driving
the liveness scan, real state files. The status-first ladder is the
worker's first-write contract: with a live worker, the first
worker-surface write must be the status sync; compliant syncs record
the session, foreign firsts are blocked with the repair path, and
everything sleeps when no worker is live.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import write_guard as wg  # noqa: E402  (hooks/ on pytest path)


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-1\n    status: OPEN\n", encoding="utf-8")
    return ws


def _worker_live(ws: Path, name="w1") -> None:
    (ws / "runs" / f"worker-status-{name}.md").write_text(
        "[2026-10-24T00:00:00Z] step: x | status: in-progress\n",
        encoding="utf-8")


# ---------- carrier taxonomy ----------

def test_carrier_taxonomy(tmp_path) -> None:
    ws = _ws(tmp_path)
    assert wg.carrier_of(ws, ws / "facts" / "_INDEX.md") == wg.CARRIER_INDEX
    assert wg.carrier_of(ws, ws / "claim-register.yaml") \
        == wg.CARRIER_REGISTER
    assert wg.carrier_of(ws, ws / "facts" / "F001.md") == wg.CARRIER_FACT
    # the taxonomy is pure path-shape (no fs check for the dir itself)
    assert wg.carrier_of(ws, ws / "notes" / "n.md") == wg.CARRIER_NOTE
    (ws / "blockers").mkdir()
    assert wg.carrier_of(ws, ws / "notes" / "n.md") == wg.CARRIER_NOTE
    assert wg.carrier_of(ws, ws / "blockers" / "b.md") \
        == wg.CARRIER_BLOCKER
    assert wg.carrier_of(ws, ws / "runs" / "x.md") is None
    assert wg.carrier_of(ws, tmp_path / "outside.md") is None


def test_carrier_shape_heuristic_without_workspace() -> None:
    assert wg.looks_like_carrier(Path("ws/facts/F001.md")) is True
    assert wg.looks_like_carrier(Path("ws/notes/n.md")) is True
    assert wg.looks_like_carrier(Path("ws/blockers/b.md")) is True
    assert wg.looks_like_carrier(Path("ws/claim-register.yaml")) is True
    assert wg.looks_like_carrier(Path("src/main.py")) is False


# ---------- post-image reconstruction ----------

def test_post_image_write_face(tmp_path) -> None:
    target = tmp_path / "F001.md"
    payload = {"tool_name": "Write",
               "tool_input": {"content": "the new bytes"}}
    text, why = wg.post_image(payload, target)
    assert (text, why) == ("the new bytes", "")
    bad = {"tool_name": "Write", "tool_input": {}}
    text, why = wg.post_image(bad, target)
    assert text is None and "no string `content`" in why


def test_post_image_edit_face_reconstructs(tmp_path) -> None:
    target = tmp_path / "F001.md"
    target.write_text("alpha beta gamma\n", encoding="utf-8")
    payload = {"tool_name": "Edit",
               "tool_input": {"old_string": "beta",
                              "new_string": "BETA"}}
    text, why = wg.post_image(payload, target)
    assert why == "" and text == "alpha BETA gamma\n"
    # a missing old_string fails closed
    payload2 = {"tool_name": "Edit",
                "tool_input": {"old_string": "absent",
                               "new_string": "x"}}
    text, why = wg.post_image(payload2, target)
    assert text is None and "old_string not present" in why
    # non-string edits fail closed
    payload3 = {"tool_name": "Edit",
                "tool_input": {"old_string": None, "new_string": 3}}
    text, why = wg.post_image(payload3, target)
    assert text is None and "non-string" in why
    # an unreadable current file fails closed
    payload4 = {"tool_name": "Edit",
                "tool_input": {"old_string": "a", "new_string": "b"}}
    text, why = wg.post_image(payload4, tmp_path / "void.md")
    assert text is None and "cannot read" in why
    # MultiEdit applies in order over the ON-DISK text (post_image
    # never writes — the reconstruction is pure)
    payload5 = {"tool_name": "MultiEdit",
                "tool_input": {"edits": [
                    {"old_string": "alpha", "new_string": "ALPHA"},
                    {"old_string": "gamma", "new_string": "GAMMA"}]}}
    text, why = wg.post_image(payload5, target)
    assert why == "" and text == "ALPHA beta GAMMA\n"
    # unsupported tool on a carrier is not reconstructible
    text, why = wg.post_image({"tool_name": "Bash", "tool_input": {}},
                              target)
    assert text is None and "unsupported tool_name" in why


# ---------- the #57 status-first gate ----------

def _payload_for(rel: str, sid="sess-1") -> dict:
    return {"session_id": sid, "tool_input": {"file_path": rel}}


def test_status_first_sleeps_without_live_workers(tmp_path) -> None:
    ws = _ws(tmp_path)
    rel = Path("facts") / "F001.md"
    assert wg.status_first_block(ws, _payload_for(str(rel)), rel) is None


def test_status_first_compliant_sync_is_allowed_and_recorded(
        tmp_path) -> None:
    ws = _ws(tmp_path)
    _worker_live(ws)
    rel = Path("runs") / "worker-status-w9.md"
    assert wg.status_first_block(ws, _payload_for(str(rel), "sess-9"),
                                 rel) is None
    state = json.loads(
        (ws / wg.STATUS_FIRST_STATE).read_text(encoding="utf-8"))
    assert state["sess-9"]["target"].endswith("worker-status-w9.md")


def test_status_first_foreign_first_write_is_blocked(tmp_path) -> None:
    ws = _ws(tmp_path)
    _worker_live(ws)
    rel = Path("facts") / "F001.md"
    block = wg.status_first_block(ws, _payload_for(str(rel), "sess-x"), rel)
    assert block is not None
    assert "worker-status" in block and "FIRST" in block
    # the blocked session is now recorded — its NEXT write passes
    assert wg.status_first_block(ws, _payload_for(str(rel), "sess-x"),
                                 rel) is None


def test_status_first_exemptions(tmp_path) -> None:
    ws = _ws(tmp_path)
    _worker_live(ws)
    # no session identity -> cannot judge (fail-open)
    rel = Path("facts") / "F001.md"
    assert wg.status_first_block(ws, {"session_id": "",
                                      "tool_input": {}}, rel) is None
    # orchestrator carriers have their own gate legs
    assert wg.status_first_block(
        ws, _payload_for("claim-register.yaml"),
        Path("claim-register.yaml")) is None
    # outside the worker write surfaces
    assert wg.status_first_block(
        ws, _payload_for("analysis/x.md"), Path("analysis/x.md")) is None


def test_status_first_corrupt_state_reads_empty(tmp_path) -> None:
    ws = _ws(tmp_path)
    _worker_live(ws)
    p = ws / wg.STATUS_FIRST_STATE
    p.write_text("]]] not json", encoding="utf-8")
    rel = Path("facts") / "F001.md"
    # the corrupt state reads as empty: the first write is judged afresh
    assert wg.status_first_block(ws, _payload_for(str(rel), "sess-y"),
                                 rel) is not None


def test_status_first_worker_scan_error_arms_the_guard(
        tmp_path, monkeypatch) -> None:
    ws = _ws(tmp_path)
    from _path_hygiene import load_hooks_lib
    def boom(_ws):
        raise RuntimeError("liveness scan down")
    monkeypatch.setattr(load_hooks_lib(), "scan_active_workers", boom)
    rel = Path("facts") / "F001.md"
    # fail-closed: an unseen workspace is ARMED, the gate judges
    block = wg.status_first_block(ws, _payload_for(str(rel), "sess-z"), rel)
    assert block is not None
    # and the compliant sync still records
    rel2 = Path("runs") / "worker-status-emergency.md"
    assert wg.status_first_block(ws, _payload_for(str(rel2), "sess-z"),
                                 rel2) is None


def test_worker_status_target_shape() -> None:
    assert wg._is_worker_status_target(Path("runs/worker-status-w1.md"))
    assert not wg._is_worker_status_target(Path("worker-status-w1.md"))
    assert not wg._is_worker_status_target(Path("runs/worker-status.md"))
    assert not wg._is_worker_status_target(Path("runs/other.md"))
