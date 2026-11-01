# -*- coding: utf-8 -*-
"""tests/test_log_levels_944.py — the log-level taxonomy (#944).

The audit (2026-11-01) found the runtime log sample 100% warn (3820
rows): the level taxonomy never existed (kunglao_log's schema is
event-based, warn is the only severity API), amplified by probe-absence
storms (rho_verifier / route_capability / infeasible_signal = 1036
rows), per-process startup-state warnings (learning_seal UNSEALED = 511
rows), and success paths logging nothing.

The pins:

  WRAPPER   severity support in the LOG WRAPPER (stderr prefix carries
            the severity; the severity classifies which rows are
            written/selected) — the core event schema stays unchanged
            (NO level field: the telemetry rows are the event source,
            the log wrapper is the operator diagnostics face);
  DEMOTION  the three probe faces' EXPECTED-absence warns demoted to
            DEBUG (stderr-only, never a ledger row) while REAL
            degradation (exists but unreadable/corrupt) stays WARN —
            the distinguishing case pinned per face;
  ONCE      startup-once config warnings: UNSEALED-class warnings emit
            once per WORKSPACE STATE (workspace-state-keyed persisted
            marker), never per process — rate-limiting is not the fix;
  MILESTONE INFO milestones land via the #915 telemetry face (no new
            log stream): the loop's lap boundary, the ΔP arbiter's
            commit/discard decisions, DISTILL research completion —
            plus the operator-facing milestone selection;
  ERROR     log-then-raise at ONE guard boundary (the loop entry's
            used-workspace refusal logs the refusal then raises; the
            fail-closed wall itself keeps raising).

The audit's honest-gap warns (q_cells settlement no-pending etc.) are
NOT touched here — they stay WARN.
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

import distill  # noqa: E402
import kunglao_log  # noqa: E402
import loop as loop913  # noqa: E402
import route_capability  # noqa: E402
import rho_verifier  # noqa: E402
import infeasible_signal  # noqa: E402
from loop_worker import mock_worker  # noqa: E402
from rlvr import learning_seal as seal  # noqa: E402
from settlement import draft_commit, per_dispatch  # noqa: E402
from state import telemetry  # noqa: E402 — the #915 face

TAG = "test_log_levels_944"


# ------------------------------------------------------------ fixtures

@pytest.fixture(autouse=True)
def _reset_kunglao_log(monkeypatch, tmp_path):
    """Fresh process-local logging state per test (the once-markers and
    dedupe dicts are module globals shared across the suite)."""
    monkeypatch.setattr(kunglao_log, "_WARN_LAST", {})
    monkeypatch.setattr(kunglao_log, "_LEVEL_LAST", {})
    monkeypatch.setattr(kunglao_log, "_ONCE_MEMO", {"key": None, "state": {}})
    monkeypatch.setattr(kunglao_log, "_WARN_WS_OVERRIDE", [])
    monkeypatch.setattr(kunglao_log, "_PRUNED_DAY", [])


@pytest.fixture(autouse=True)
def _seal_state(monkeypatch, tmp_path):
    """Default seal posture: unarmed, per-process notice armed."""
    monkeypatch.setattr(seal, "KEY_PATH", tmp_path / "absent.key")
    monkeypatch.setattr(seal, "_NOTICE", {"shown": False})
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})


@pytest.fixture(autouse=True)
def _isolated_store_root(monkeypatch, tmp_path):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))


def _log_rows(ws) -> list[dict]:
    return kunglao_log._all_rows(Path(ws))


def _rows_of_action(ws, action: str) -> list[dict]:
    return [r for r in _log_rows(ws) if r.get("action") == action]


def _new_process_state() -> None:
    """Wipe every process-local dedupe/once slot — simulates a SECOND
    process arriving in the same workspace state."""
    kunglao_log._WARN_LAST.clear()
    kunglao_log._LEVEL_LAST.clear()
    kunglao_log._ONCE_MEMO.update(key=None, state={})


# ------------------------------------------------- 1. the level wrapper

def test_stderr_prefixes_carry_the_severity(capsys):
    kunglao_log.debug("probe_op", "optional file absent")
    kunglao_log.info("milestone_op", "milestone reached")
    kunglao_log.warn("failopen_op", "degraded")
    kunglao_log.error("guard_op", "refused")
    err = capsys.readouterr().err
    assert f"[kunglao-agent] {TAG} DEBUG: probe_op: optional file absent" \
        in err, err
    assert f"[kunglao-agent] {TAG} INFO: milestone_op: milestone reached" \
        in err, err
    # warn keeps its exact legacy face (the existing pins depend on it)
    assert f"[kunglao-agent] {TAG} WARN (fail-open): failopen_op: " \
        f"degraded" in err, err
    assert f"[kunglao-agent] {TAG} ERROR: guard_op: refused" in err, err


def test_wrapper_dedupe_is_per_level_and_reason(capsys):
    kunglao_log.debug("op_x", "reason a")
    kunglao_log.debug("op_x", "reason a")  # same (DEBUG, op, reason): silent
    kunglao_log.debug("op_x", "reason b")  # changed reason: re-fires
    kunglao_log.warn("op_x", "reason a")   # a different level never collides
    err = capsys.readouterr().err
    assert err.count("DEBUG: op_x: reason a") == 1
    assert err.count("DEBUG: op_x: reason b") == 1
    assert err.count("WARN (fail-open): op_x: reason a") == 1


def test_severity_classifies_rows_written_core_schema_has_no_level(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    kunglao_log.set_warn_workspace(ws)
    kunglao_log.debug("dbg_op", "expected absence")   # never persisted
    kunglao_log.info("inf_op", "milestone")
    kunglao_log.warn("wrn_op", "real degradation")
    kunglao_log.error("err_op", "guard refusal")
    rows = _log_rows(ws)
    by_action = {r["action"]: r for r in rows}
    # DEBUG is the demotion target: stderr-only, NO ledger row
    assert not any("dbg_op" in str(r.get("detail")) for r in rows), rows
    # INFO/WARN/ERROR persist under their own action words (the
    # classification rides the action vocabulary, not a level field)
    assert set(by_action) == {"info", "warn", "error"}, rows
    assert by_action["info"]["actor"] == "telemetry"
    for r in rows:
        assert "level" not in r, "the core event schema must gain no level"
    assert kunglao_log.severity_of(by_action["info"]) == "INFO"
    assert kunglao_log.severity_of(by_action["warn"]) == "WARN"
    assert kunglao_log.severity_of(by_action["error"]) == "ERROR"
    # the event face (a plain producer row) is severity-None: it is an
    # event, not a diagnostic
    kunglao_log.emit(ws, "telemetry", "verify", detail="a producer row")
    assert kunglao_log.severity_of(_rows_of_action(ws, "verify")[0]) is None


def test_tail_selects_by_severity(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    kunglao_log.set_warn_workspace(ws)
    kunglao_log.info("inf_op", "one")
    kunglao_log.warn("wrn_op", "two")
    kunglao_log.emit(ws, "telemetry", "verify", detail="event row")
    warn_rows = kunglao_log.tail(ws, 10, level="WARN")
    assert [r["action"] for r in warn_rows] == ["warn"]
    info_rows = kunglao_log.tail(ws, 10, level="INFO")
    assert [r["action"] for r in info_rows] == ["info"]
    event_rows = kunglao_log.tail(ws, 10, level=None)
    assert {r["action"] for r in event_rows} == {"info", "warn", "verify"}
    with pytest.raises(ValueError):
        kunglao_log.tail(ws, 10, level="LOUD")  # a typo'd level never
        # reads as an honest empty selection


def test_cli_tail_level_selection(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    kunglao_log.set_warn_workspace(ws)
    kunglao_log.info("inf_op", "one")
    kunglao_log.warn("wrn_op", "two")
    rc = kunglao_log.main(["--tail", str(ws), "20", "--level", "WARN"])
    out = capsys.readouterr().out
    assert rc == 0
    selected = [json.loads(line) for line in out.splitlines()]
    assert [r["action"] for r in selected] == ["warn"]


# --------------------------------------- 2. probe-absence demotion

def test_route_capability_expected_absence_debugs_corrupt_still_warns(
        tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    kunglao_log.set_warn_workspace(ws)
    # EXPECTED absence: the evidence probes face a fresh workspace —
    # no optional file exists yet, which is the normal pre-signal state
    state = route_capability.load_workspace_state(ws)
    err = capsys.readouterr().err
    assert "route_capability DEBUG: load_workspace_state" in err, err
    assert "WARN (fail-open)" not in err, err
    assert _rows_of_action(ws, "warn") == []
    assert state["mem_gate_verdict"] is None
    # REAL degradation: the file EXISTS but is corrupt — still WARN
    ev = ws / "evidence"
    ev.mkdir()
    (ev / "apk_mem_gate.json").write_text("{not json", encoding="utf-8")
    route_capability.load_workspace_state(ws)
    err += capsys.readouterr().err
    assert "route_capability WARN (fail-open): load_workspace_state" in err
    warn_rows = _rows_of_action(ws, "warn")
    assert any("load_workspace_state" in str(r.get("detail"))
               for r in warn_rows)


def test_rho_verifier_missing_mission_ledger_debugs_corrupt_still_warns(
        tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    kunglao_log.set_warn_workspace(ws)
    # EXPECTED absence: no runs/mission_ledger.yaml yet — the cockpit
    # persistence probe degrades honestly, the sample still lands
    out = rho_verifier.sample_and_pair(ws)
    assert out["backend"] == "deterministic"
    err = capsys.readouterr().err
    assert "rho_verifier DEBUG: sample_and_pair" in err, err
    assert "WARN (fail-open)" not in err, err
    assert _rows_of_action(ws, "warn") == []
    # REAL degradation: the ledger exists but is corrupt — still WARN
    runs = ws / "runs"
    runs.mkdir(exist_ok=True)
    (runs / "mission_ledger.yaml").write_text(
        "mission:\n  - [unclosed", encoding="utf-8")
    rho_verifier.sample_and_pair(ws)
    err += capsys.readouterr().err
    assert "rho_verifier WARN (fail-open): sample_and_pair" in err
    assert _rows_of_action(ws, "warn")


def test_infeasible_missing_index_debugs_unreadable_still_warns(
        tmp_path, capsys):
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    kunglao_log.set_warn_workspace(ws)
    # EXPECTED absence: no facts/_INDEX.md on a fresh workspace
    infeasible_signal.evaluate(ws, persist=False)
    err = capsys.readouterr().err
    assert "infeasible_signal DEBUG: _terminal_count" in err, err
    assert "WARN (fail-open)" not in err, err
    # REAL degradation: the index path exists but cannot be read
    (ws / "facts" / "_INDEX.md").mkdir()  # a directory at the file path
    infeasible_signal.evaluate(ws, persist=False)
    err += capsys.readouterr().err
    assert "infeasible_signal WARN (fail-open): _terminal_count" in err
    assert _rows_of_action(ws, "warn")


# --------------------------------- 3. startup-once config warnings

def test_warn_once_stateful_is_state_keyed_not_process_keyed(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    kunglao_log.set_warn_workspace(ws)
    assert kunglao_log.warn_once_stateful(
        "cfg_op", "config degraded", state_key="unarmed:missing") is True
    _new_process_state()  # a SECOND process arrives
    assert kunglao_log.warn_once_stateful(
        "cfg_op", "config degraded", state_key="unarmed:missing") is False
    # the workspace STATE changes: the notice re-arms (a state-keyed
    # marker, not a rate limit — a new state is a new warning)
    assert kunglao_log.warn_once_stateful(
        "cfg_op", "config degraded", state_key="unarmed:short:5") is True
    marker = ws / "runs" / ".warn-once-state.json"
    raw = json.loads(marker.read_text(encoding="utf-8"))
    assert raw == {"cfg_op": "unarmed:short:5"}


def test_warn_once_stateful_without_a_workspace_falls_back_per_process(
        tmp_path, capsys):
    # no workspace resolvable: the honest fallback is the per-process
    # warn face (dedupe-limited), never silence
    kunglao_log.set_warn_workspace(None)
    assert kunglao_log.warn_once_stateful(
        "cfg_op", "config degraded", state_key="s") is True
    assert kunglao_log.warn_once_stateful(
        "cfg_op", "config degraded", state_key="s") is False  # dedupe
    assert "WARN (fail-open): cfg_op: config degraded" \
        in capsys.readouterr().err


def test_unarmed_notice_once_per_workspace_state(tmp_path, monkeypatch,
                                                 capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    kunglao_log.set_warn_workspace(ws)
    key = tmp_path / "learning.key"  # absent: unarmed, key-missing state
    monkeypatch.setattr(seal, "KEY_PATH", key)
    seal.sign_row({"a": 1})
    assert capsys.readouterr().err.count("UNSEALED") == 1
    # a SECOND process in the SAME workspace state does not re-warn
    monkeypatch.setattr(seal, "_NOTICE", {"shown": False})
    _new_process_state()
    seal.sign_row({"b": 2})
    assert capsys.readouterr().err.count("UNSEALED") == 0
    # the config state CHANGES (key now present but short): re-warn
    key.write_bytes(b"short")
    monkeypatch.setattr(seal, "_NOTICE", {"shown": False})
    _new_process_state()
    seal.sign_row({"c": 3})
    assert capsys.readouterr().err.count("UNSEALED") == 1
    marker = json.loads(
        (ws / "runs" / ".warn-once-state.json").read_text(encoding="utf-8"))
    assert marker["learning_seal"].startswith("unarmed:key-short:")


# ------------------------------- 4. INFO milestones via #915 telemetry

def _run_loop(ws: Path, *, laps: int):
    return loop913.run_loop(ws, laps=laps, seed=0, spawn_slots=1,
                            worker=mock_worker)


def test_lap_boundary_lands_as_telemetry_rows(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _run, ws2 = _run_loop(ws, laps=3)
    events_rows = telemetry.events(ws2)
    lap_rows = [r for r in events_rows
                if r["event"] == "loop.LAP_BOUNDARY"]
    assert [r["lap"] for r in lap_rows] == [1, 2, 3]


def test_arbiter_commit_and_discard_decisions_persist(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _run, ws2 = _run_loop(ws, laps=2)
    events_rows = telemetry.events(ws2)
    # the ΔP arbiter's COMMIT disposition persists (the rollup path)
    assert any(r["event"] == "settlement.SETTLE_COMMITTED"
               for r in events_rows)
    # the DISCARD disposition persists too — driven directly here (the
    # audited rollback face; the marker makes the DECISION visible)
    dws = tmp_path / "discard-ws"
    dws.mkdir()
    priced = {"schema": draft_commit.DRAFT_SCHEMA,
              "rollout_id": "ro-d", "dispatch_id": "d-1",
              "batch_id": per_dispatch.batch_id("ro-d"),
              "spend": 1.0, "credit": 0.5,
              "verdicts": {k: True for k in per_dispatch.VERDICT_LAYERS}}
    draft_commit.land_draft(dws, priced, ts="2026-10-31T00:00:01Z")
    receipt = draft_commit.discard_drafts(dws, "ro-d", reason="negative dp",
                                          ts="2026-10-31T00:00:02Z")
    assert receipt["appended"] is True
    assert any(r["event"] == "settlement.SETTLE_DISCARDED"
               for r in telemetry.events(dws))


def test_distill_completion_lands_milestone_row(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()

    class _Clock:
        def __init__(self) -> None:
            self._n = 0

        def tick(self) -> str:
            self._n += 1
            return f"2026-10-31T00:{self._n // 60:02d}:{self._n % 60:02d}Z"

    clock = _Clock()

    def rec(**over):
        base = {"approach": "unpack then trace the dispatcher",
                "planning_pattern": "static triage before dynamic confirm",
                "success_markers": ["dispatcher resolved"],
                "failure_markers": ["vm deadlock"],
                "motives": ["why: the shelf has no unpack rung"],
                "constraints": ["offline only"]}
        base.update(over)
        return {k: v for k, v in base.items() if v is not None}

    calls: list[list[str]] = []

    def fetch(queries: list[str]) -> list[dict]:
        calls.append(list(queries))
        return [{"origin": "web",
                 "provenance": {"url": "https://example.test/a",
                                "date": "2026-10-31"},
                 "text": "doc", "query": queries[0]}]

    out = distill.research(ws, "gap x", max_depth=2, sources=("web",),
                           clock=clock, web_fetch=fetch,
                           extract_fn=lambda doc: rec())
    done = [r for r in telemetry.events(ws)
            if r["event"] == "distill.DISTILL_COMPLETE"]
    assert len(done) == 1, telemetry.events(ws)
    assert done[0]["detail"]["rounds_run"] == out["rounds_run"]
    assert done[0]["detail"]["converged"] == out["converged"]


def test_milestones_selection_is_the_operator_info_face(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _run, ws2 = _run_loop(ws, laps=2)
    ms = telemetry.milestones(ws2)
    assert ms, "the operator-facing INFO selection is not empty"
    assert {r["event"] for r in ms} <= set(telemetry.MILESTONE_CODES)
    assert any(r["event"] == "loop.LAP_BOUNDARY" for r in ms)
    assert any(r["event"] == "settlement.SETTLE_COMMITTED" for r in ms)
    # the selection is deterministic from the ledger alone
    assert ms == telemetry.milestones(ws2)


# -------------------------- 5. ERROR log-then-raise at the loop entry

def test_loop_entry_refusal_logs_error_then_raises(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    _run_loop(ws, laps=1)                      # a clean first run
    capsys.readouterr()                        # drop the first run's noise
    with pytest.raises(loop913.LoopError):
        _run_loop(ws, laps=1)                  # the used-workspace refusal
    err = capsys.readouterr().err
    assert "[kunglao-agent] loop ERROR:" in err, err
    error_rows = _rows_of_action(ws, "error")
    assert error_rows, "the refusal logged BEFORE the raise"
    assert "already carries" in str(error_rows[-1].get("detail"))
    assert kunglao_log.severity_of(error_rows[-1]) == "ERROR"
