# -*- coding: utf-8 -*-
"""Issue 1-F3 — the launch-stash schema wall.

The audit's lens-1 report caught the live shape: an orchestrator session
parked a full dispatch envelope (``status: PARKED_NOT_LAUNCHED``,
carrying a wake plan) in the namespace ``incremental_reward`` owns, and
``append_transition`` — which validates nothing about the stash and
unlinks it after consume — would happily consume the parked envelope as
launch state (phi=0.0) and delete the wake plan on a settle.

The wall: ``record_launch`` stamps ``schema: "dispatch-launch/1"``;
``append_transition`` refuses (None + ONE warn, stash LEFT INTACT) any
stash doc carrying a foreign ``schema`` or a ``status`` field. Legacy
stashes carrying neither field settle byte-identically (the back-compat rule).
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
from rlvr import incremental_reward as ir  # noqa: E402


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _warn_recorder(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        kunglao_log, "warn",
        lambda op, reason, **kw: calls.append((str(op), str(reason))))
    return calls


def _write_stash(ws: Path, claim: str, doc: dict,
                 action_type: str = "redteam") -> Path:
    p = ir._launch_path(ws, claim, action_type)
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


def test_record_launch_stamps_schema(tmp_path) -> None:
    ws = _ws(tmp_path)
    doc = ir.record_launch(ws, "C-1", "static", phi=0.25)
    assert doc is not None
    assert doc["schema"] == ir.LAUNCH_SCHEMA
    on_disk = json.loads(
        ir._launch_path(ws, "C-1", "dispatch").read_text("utf-8"))
    assert on_disk["schema"] == ir.LAUNCH_SCHEMA


def test_parked_envelope_refused_and_preserved(tmp_path, monkeypatch) -> None:
    """The live 1-F3 shape: the orchestrator's PARKED envelope (wake plan
    inside) must never be consumed as launch state, and the wake plan
    must survive the refused settle."""
    ws = _ws(tmp_path)
    parked = {
        "schema": "dispatch-envelope/2",
        "status": "PARKED_NOT_LAUNCHED",
        "claim": "C-4",
        "wake_plan": {"at": "2026-10-11T09:00:00Z", "arm": "dynamic"},
    }
    p = _write_stash(ws, "C-4", parked)
    calls = _warn_recorder(monkeypatch)
    row = ir.append_transition(ws, "C-4", "SUCCESS",
                               action_type="redteam")
    assert row is None
    assert p.is_file(), "the parked envelope (wake plan) must survive"
    assert json.loads(p.read_text("utf-8"))["status"] \
        == "PARKED_NOT_LAUNCHED"
    assert len(calls) == 1 and "1-F3" in calls[0][1]


def test_foreign_schema_refused_and_preserved(tmp_path, monkeypatch) -> None:
    ws = _ws(tmp_path)
    foreign = {"schema": "something-else/9", "claim": "C-1", "phi": 0.9}
    p = _write_stash(ws, "C-1", foreign)
    calls = _warn_recorder(monkeypatch)
    row = ir.append_transition(ws, "C-1", "SUCCESS", action_type="redteam")
    assert row is None
    assert p.is_file()
    assert len(calls) == 1


def test_status_bearing_stash_refused(tmp_path, monkeypatch) -> None:
    """The wall keys on the field, not the value: ANY ``status``-bearing
    doc is an envelope shape, never launch state."""
    ws = _ws(tmp_path)
    envelope = {"claim": "C-9", "status": "PARKED_NOT_LAUNCHED",
                "wake_plan": {"at": "x"}}
    p = _write_stash(ws, "C-9", envelope)
    calls = _warn_recorder(monkeypatch)
    row = ir.append_transition(ws, "C-9", "SUCCESS", action_type="redteam")
    assert row is None
    assert p.is_file()
    assert len(calls) == 1


def test_legacy_schemaless_stash_still_settles(tmp_path) -> None:
    """Back-compat pin: a pre-change stash (no schema, no status) settles
    byte-identically — in-flight workspaces are never broken."""
    ws = _ws(tmp_path)
    legacy = {"ts": "2026-10-10T00:00:00Z", "claim": "C-1",
              "a": "static", "s": "abc", "phi": 0.1,
              "action_type": "redteam"}
    _write_stash(ws, "C-1", legacy)
    row = ir.append_transition(ws, "C-1", "SUCCESS", action_type="redteam",
                               r_settle=1.0)
    assert row is not None
    assert row["phi_before"] == 0.1


def test_stamped_stash_settles(tmp_path) -> None:
    ws = _ws(tmp_path)
    doc = ir.record_launch(ws, "C-2", "dynamic", phi=0.3)
    row = ir.append_transition(ws, "C-2", "SUCCESS",
                               attempt_id=str((doc or {}).get("attempt_id")))
    assert row is not None
    assert row["a"] == "dynamic"
