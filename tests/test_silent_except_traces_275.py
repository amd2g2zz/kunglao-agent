# -*- coding: utf-8 -*-
"""tests/test_silent_except_traces_275.py — issue 275 batch-2: the four
worst silent-swallow files leave exactly ONE trace per fail-open handler.

Policy (issue 275): fail-open keeps its never-raise/continue/return
behavior, but every handler must leave one observable trace — here a
rate-limited stderr WARN naming the operation + reason (the
_zof_warn pattern of issue 276: once per op until the reason changes).
A comment alone does NOT satisfy the AST gate (batch-1 pinned ruling).

These tests pin, per file:
  - the WARN fires ONCE on repeat failures with the same reason;
  - the surrounding behavior is UNCHANGED vs the pre-change shape (same
    return value, same state, never raises);
  - the ledger ratchet end-state: zero silent handlers in the top-4
    and their entries deleted from scripts/silent_except_baseline.yaml.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import silent_except_lint as sel  # noqa: E402
import convergence_check as ct  # noqa: E402
import heartbeat_tick as ht  # noqa: E402
import statusline_snapshot as sls  # noqa: E402
import backtrack_loop as bl  # noqa: E402

# The batch-2 targets: file -> the ledger count this batch must clear.
TOP4 = {
    "scripts/convergence_check.py": 10,
    "scripts/heartbeat_tick.py": 9,
    "scripts/statusline_snapshot.py": 10,
    "scripts/backtrack_loop.py": 9,
}

_MODULES = (ct, ht, sls, bl)


@pytest.fixture
def quiet_warn(monkeypatch):
    """Fresh rate-limit + sidecar state per test: WARN assertions are
    per-test."""
    for mod in _MODULES:
        monkeypatch.setattr(mod, "_WARN_LAST", {}, raising=False)
    monkeypatch.setattr(sls, "_DEGRADED", {}, raising=False)
    yield


def _boom(*a, **k):
    raise RuntimeError("boom")


# ----------------------------------------------------------------- helper

def test_every_module_has_the_rate_limited_warn_helper(quiet_warn):
    for mod in _MODULES:
        assert callable(getattr(mod, "warn", None)), mod.__name__


def test_warn_line_shape_names_module_op_reason(capsys, quiet_warn):
    ht.warn("op_x", "ValueError: boom")
    err = capsys.readouterr().err
    assert ("[kunglao-agent] heartbeat_tick WARN (fail-open): "
            "op_x: ValueError: boom") in err


def test_warn_rate_limits_per_op_until_reason_changes(capsys, quiet_warn):
    ct.warn("op", "r1")
    ct.warn("op", "r1")   # same op + reason -> suppressed
    ct.warn("op2", "r1")  # different op -> fires
    ct.warn("op", "r2")   # reason changed -> fires
    lines = [ln for ln in capsys.readouterr().err.splitlines()
             if "WARN (fail-open)" in ln]
    assert len(lines) == 3


# -------------------------------------------------------- heartbeat_tick

def test_module_emit_nameerror_traces_sidecar_not_stderr(capsys,
                                                         quiet_warn):
    """The module-level emit (issue 534) can never resolve `ws` — the
    import-time fail-open records the sidecar (hook-embedded importers
    keep stderr empty, token-zero) and main() drains it into the tick
    report."""
    spec = importlib.util.spec_from_file_location(
        "kunglao_275_tick_fresh", SCRIPTS / "heartbeat_tick.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    err = capsys.readouterr().err
    assert err == "", "import-time degradation must stay off stderr"
    assert "module_emit" in mod._DEGRADED


def test_module_emit_sidecar_drains_into_tick_report(quiet_warn, tmp_path,
                                                     monkeypatch):
    """main() is the sidecar's consumer: the degraded face lands in
    runs/.heartbeat-tick.json. Uses a tick-less drain probe: the report
    dict is built before the heavy steps, so assert the drain logic by
    calling main against a workspace where the first subprocess step
    records the failure but the report still carries the sidecar."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    monkeypatch.setattr(ht, "_DEGRADED",
                        {"module_emit": "NameError: name 'ws' is not defined"})
    rc = ht.main([str(ws)])
    report = json.loads(
        (ws / "runs" / ".heartbeat-tick.json").read_text(encoding="utf-8"))
    assert rc in (0, 1)
    assert report.get("degraded") == {
        "module_emit": "NameError: name 'ws' is not defined"}


def test_noop_breaker_write_failure_warns_once_and_keeps_state(capsys,
                                                               quiet_warn,
                                                               tmp_path):
    """State write fails (path is a directory): the breaker state machine
    returns the SAME verdict shape as pre-change, and the WARN fires once."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "runs" / ".heartbeat-noop.json").mkdir()  # unwritable seam
    first = ht.noop_breaker(ws, "h1")
    second = ht.noop_breaker(ws, "h1")
    err = capsys.readouterr().err
    assert first == {"tripped": False, "consecutive_noop": 1, "threshold": 6}
    assert second == first, "repeat call must behave identically"
    assert err.count("WARN (fail-open): noop_breaker_state_write:") == 1


# ------------------------------------------------------- convergence_check

def test_append_ledger_failure_warns_once(capsys, quiet_warn, tmp_path):
    """Ledger side channel fails: the decision is untouched (None return),
    the failure is visible exactly once."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".convergence_ledger.jsonl").mkdir()  # open(.., "a") fails
    d = {"decision": "DISPATCH", "open_count": 1,
         "open_claims": [{"id": "C-1"}], "partial_count": 0,
         "active_workers": 0, "active_blockers": []}
    assert ct._append_ledger(ws, d) is None
    assert ct._append_ledger(ws, d) is None
    err = capsys.readouterr().err
    assert err.count("WARN (fail-open): ledger_append:") == 1


def test_record_operator_action_failure_warns_once(capsys, quiet_warn,
                                                   tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".convergence_ledger.jsonl").mkdir()
    ct.record_operator_action(ws, "defer", claim_id="C-1")
    ct.record_operator_action(ws, "defer", claim_id="C-1")
    err = capsys.readouterr().err
    assert err.count("WARN (fail-open): operator_action:") == 1


def test_decision_snapshot_emit_failure_warns_once(capsys, quiet_warn,
                                                   monkeypatch, tmp_path):
    """The issue 287 contract: a crashed decision-snapshot emit never blocks the
    decision — and is no longer invisible."""
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setitem(sys.modules, "kunglao_log", None)
    ct._emit_decision_snapshot(ws, {"decision": "CONVERGED"})
    ct._emit_decision_snapshot(ws, {"decision": "CONVERGED"})
    err = capsys.readouterr().err
    assert err.count("WARN (fail-open): decision_snapshot:") == 1


# ---------------------------------------------------- statusline_snapshot

def test_mission_state_read_failure_traces_sidecar(capsys, quiet_warn,
                                                   tmp_path):
    """Absent mission ledger -> the zeros face is unchanged, the
    degradation rides the snapshot sidecar (NOT stderr: the snapshot write
    is hook-embedded, token-zero), named exactly once (keyed by op)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "runs" / "mission_ledger.yaml").mkdir()
    first = sls._mission_state(ws)
    second = sls._mission_state(ws)
    err = capsys.readouterr().err
    assert first["total"] == 0 and first["v_m"] == 0.0
    assert second == first
    assert "mission_state_read" in sls._DEGRADED
    assert err == "", "absent-source degradation must stay off stderr"


def test_snapshot_sidecar_names_absence_degradations_token_zero(
        capsys, quiet_warn, tmp_path):
    """build_snapshot on a bare (idle) workspace: the absent-file faces all
    degrade normally, the snapshot names them in the "degraded" sidecar,
    and BOTH streams stay empty (the token-zero contract, real build)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    snap = sls.build_snapshot(ws)
    err = capsys.readouterr()
    assert snap["state"] == "down"  # pre-change face: no heartbeat -> down
    assert set(snap["degraded"]) >= {"mission_state_read", "pq_rows_read",
                                     "hooks_declared_read", "audit_age"}
    assert err.out == "" and err.err == ""


def test_write_snapshot_emit_failure_warns_once_and_snapshot_lands(
        capsys, quiet_warn, monkeypatch, tmp_path):
    """Snapshot write + emit fail-open: the file still lands (return value
    unchanged), the emit fault is visible exactly once."""
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setitem(sys.modules, "kunglao_log", None)
    out1 = sls.write_snapshot(ws)
    out2 = sls.write_snapshot(ws)
    err = capsys.readouterr().err
    assert out1.exists() and out2 == out1
    assert err.count("WARN (fail-open): snapshot_emit:") == 1


# ---------------------------------------------------------- backtrack_loop

def test_scene_sniff_failure_warns_once_and_degrades(capsys, quiet_warn,
                                                     monkeypatch, tmp_path):
    import tool_tiers
    import plan_stages
    monkeypatch.setattr(tool_tiers, "scene_for", _boom)
    monkeypatch.setattr(plan_stages, "should_review",
                        lambda ws: {"due": False})
    ws = tmp_path / "ws"
    ws.mkdir()
    first = bl.scene_operation_key(ws, "C-1")
    second = bl.scene_operation_key(ws, "C-1")
    err = capsys.readouterr().err
    assert first == ("generic-binary", "(unlabeled)")
    assert second == first
    assert err.count("WARN (fail-open): scene_sniff:") == 1
    # missing claim-register.yaml takes the second fail-open arm
    assert err.count("WARN (fail-open): register_read:") == 1


def test_policy_due_gate_source_failure_warns_once(capsys, quiet_warn,
                                                   monkeypatch, tmp_path):
    import mission_stall
    monkeypatch.setattr(mission_stall, "stall_mission", _boom)
    ws = tmp_path / "ws"
    ws.mkdir()
    due = bl.policy_due(ws)
    bl.policy_due(ws)
    err = capsys.readouterr().err
    assert due == {"due": False, "why": []}
    assert err.count("WARN (fail-open): mission_stall_gate:") == 1


def test_settlement_retro_emit_failure_warns_and_returns_doc(
        capsys, quiet_warn, monkeypatch, tmp_path):
    """Both emit arms (detector + retro_report) fail-open: the retro .md
    still lands and is returned, each fault visible exactly once."""
    monkeypatch.setattr(bl.kunglao_log, "emit", _boom)
    ws = tmp_path / "ws"
    ws.mkdir()
    doc = bl.settlement_retro(ws, "C-1", to="VERIFIED")
    doc2 = bl.settlement_retro(ws, "C-1", to="VERIFIED")
    err = capsys.readouterr().err
    assert doc.exists() and doc2.exists()
    assert err.count("WARN (fail-open): detector_emit:") == 1
    assert err.count("WARN (fail-open): retro_report_emit:") == 1


# ------------------------------------------------------------ ledger gate

def test_top4_files_have_zero_silent_handlers():
    """Ratchet end-state: the batch-2 targets carry zero silent handlers."""
    counts, _ = sel.scan_counts(ROOT)
    for rel in TOP4:
        assert counts.get(rel, 0) == 0, f"{rel} still has silent handlers"


def test_ledger_top4_entries_deleted():
    """The honest inventory only shrinks: cleared entries are DELETED."""
    doc = yaml.safe_load(
        (ROOT / "scripts" / "silent_except_baseline.yaml").read_text(
            encoding="utf-8")) or {}
    files = doc.get("files") or {}
    for rel in TOP4:
        assert rel not in files, f"stale ledger entry: {rel}"
