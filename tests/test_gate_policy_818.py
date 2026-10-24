# -*- coding: utf-8 -*-
"""tests/test_gate_policy_818.py — the #801 gate-layering authority +
the R2a warn breaker, unit faces on REAL workspaces (issue #818 climb;
counts double: the Wave-0.5 economics tooth).

The five HARD classes block; format/self_health demote to WARN +
telemetry and never block. The bounded-repetition breaker accrues each
demotion to its (gate|class|name) family, trips ONCE at the bound with
the chosen ownership action, then suppresses further same-family rows;
all three ownership choices persist in the state file.
"""
from __future__ import annotations

import json
from pathlib import Path

import gate_policy as gp  # noqa: E402  (hooks/ on pytest path)


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _events(ws: Path) -> list:
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return []
    return [json.loads(ln) for p in sorted(logs.glob("kunglao-*.jsonl"))
            for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _sidecar_rows(ws: Path) -> list:
    p = ws / gp.GATE_REJECTIONS_LOG
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------- the layering decision ----------

def test_five_hard_classes_block_and_demoted_do_not() -> None:
    for hard in gp.HARD_CLASSES:
        assert gp.is_hard(hard) and gp.should_block(hard)
    assert not gp.is_hard(gp.FORMAT_CLASS)
    assert not gp.should_block(gp.FORMAT_CLASS)
    assert not gp.should_block(gp.SELF_HEALTH_CLASS)
    assert not gp.should_block("totally-unknown-class")


# ---------- the breaker action choice ----------

def test_breaker_action_default_and_env_choices(monkeypatch) -> None:
    monkeypatch.delenv(gp.BREAKER_ACTION_ENV, raising=False)
    assert gp._breaker_action() == "circuit-break"
    monkeypatch.setenv(gp.BREAKER_ACTION_ENV, "escalate")
    assert gp._breaker_action() == "escalate"
    monkeypatch.setenv(gp.BREAKER_ACTION_ENV, "downgrade")
    assert gp._breaker_action() == "downgrade"
    monkeypatch.setenv(gp.BREAKER_ACTION_ENV, "rm-rf")
    assert gp._breaker_action() == "circuit-break"   # invalid -> default


# ---------- record_family accrual + trip + suppression ----------

def test_record_family_without_ws_is_a_passthrough() -> None:
    out = gp.record_family(None, "g", gp.FORMAT_CLASS, "n", "m")
    assert out == {"count": 1, "action": None, "tripped": False,
                   "suppressed": 0, "suppress_row": False}


def test_record_family_accrues_then_trips_once_then_suppresses(
        tmp_path) -> None:
    ws = _ws(tmp_path)
    fam = "dispatch_gate|format|bad-json"
    for i in range(1, gp.WARN_FAMILY_BOUND + 1):
        out = gp.record_family(ws, "dispatch_gate", gp.FORMAT_CLASS,
                               "bad-json", f"hit {i}")
        if i < gp.WARN_FAMILY_BOUND:
            assert out["tripped"] is False
            assert out["suppress_row"] is False
    # the tripping call's return carries the PRE-trip accrual snapshot
    # (as-found contract); the trip lives in the persisted state
    assert out["count"] == gp.WARN_FAMILY_BOUND
    state = json.loads(
        (ws / gp.WARN_BREAKER_REL).read_text(encoding="utf-8"))
    fam_state = state["families"][fam]
    assert fam_state["tripped"] is True
    assert fam_state["action"] == "circuit-break"
    # every further same-family accrual is suppressed, observably
    out = gp.record_family(ws, "dispatch_gate", gp.FORMAT_CLASS,
                           "bad-json", "hit beyond")
    assert out["suppress_row"] is True
    assert out["suppressed"] == 1
    out = gp.record_family(ws, "dispatch_gate", gp.FORMAT_CLASS,
                           "bad-json", "again")
    assert out["suppressed"] == 2
    state = json.loads(
        (ws / gp.WARN_BREAKER_REL).read_text(encoding="utf-8"))
    assert state["families"][fam]["suppressed"] == 2
    # the trip is an observable ledger row
    words = [r.get("action") for r in _events(ws)]
    assert "warn_breaker_tripped" in words


def test_trip_escalation_variant_names_the_operator(
        tmp_path, monkeypatch, capsys) -> None:
    ws = _ws(tmp_path)
    monkeypatch.setenv(gp.BREAKER_ACTION_ENV, "escalate")
    for i in range(gp.WARN_FAMILY_BOUND):
        gp.record_family(ws, "write_guard", gp.FORMAT_CLASS, "yaml",
                         f"hit {i}")
    state = json.loads(
        (ws / gp.WARN_BREAKER_REL).read_text(encoding="utf-8"))
    assert state["families"][
        "write_guard|format|yaml"]["action"] == "escalate"
    err = capsys.readouterr().err
    assert "OPERATOR ESCALATION" in err
    rows = [r for r in _events(ws) if r.get("action") == "warn_breaker_tripped"]
    assert rows and "OPERATOR ESCALATION" in rows[-1].get("detail", "")


def test_other_family_is_independent(tmp_path) -> None:
    ws = _ws(tmp_path)
    for i in range(gp.WARN_FAMILY_BOUND):
        gp.record_family(ws, "g1", gp.FORMAT_CLASS, "fam-a", f"hit {i}")
    out = gp.record_family(ws, "g1", gp.FORMAT_CLASS, "fam-b", "other")
    assert out["tripped"] is False and out["count"] == 1


# ---------- warn_sidecar ----------

def test_sidecar_without_ws_allows() -> None:
    assert gp.warn_sidecar(None, "g", gp.FORMAT_CLASS, "m") is True


def test_sidecar_writes_one_row_with_class_and_exit_code(tmp_path) -> None:
    ws = _ws(tmp_path)
    ok = gp.warn_sidecar(ws, "dispatch_gate", gp.FORMAT_CLASS,
                         "invalid JSON", exit_code=0, name="json-parse")
    assert ok is True
    (row,) = _sidecar_rows(ws)
    assert row["gate"] == "dispatch_gate"
    assert row["name"] == "json-parse"
    assert row["gate_class"] == gp.FORMAT_CLASS
    assert row["exit_code"] == 0
    assert row["msg"] == "invalid JSON"
    assert row["ts"].endswith("Z")


def test_sidecar_suppressed_once_family_is_owned(tmp_path) -> None:
    ws = _ws(tmp_path)
    for i in range(gp.WARN_FAMILY_BOUND):
        assert gp.warn_sidecar(ws, "g", gp.FORMAT_CLASS, f"m{i}") is True
    assert gp.warn_sidecar(ws, "g", gp.FORMAT_CLASS, "beyond") is False
    assert len(_sidecar_rows(ws)) == gp.WARN_FAMILY_BOUND


# ---------- demote: the WARN half ----------

def test_demote_returns_zero_and_lands_both_telemetry_faces(
        tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("kunglao_log._WARN_LAST", {}, raising=False)
    ws = _ws(tmp_path)
    rc = gp.demote("dispatch_gate", gp.FORMAT_CLASS, "bad-json",
                   "payload unusable", ws=ws)
    assert rc == 0                                    # never blocks
    (row,) = _sidecar_rows(ws)
    assert row["gate_class"] == gp.FORMAT_CLASS
    words = [r.get("action") for r in _events(ws)]
    assert "gate_warn" in words                       # the registered word


def test_demote_without_ws_still_warns_and_returns_zero(
        monkeypatch, capsys) -> None:
    monkeypatch.setattr("kunglao_log._WARN_LAST", {}, raising=False)
    assert gp.demote("g", gp.SELF_HEALTH_CLASS, "n", "m", ws=None) == 0
    assert "DEMOTED" in capsys.readouterr().err
