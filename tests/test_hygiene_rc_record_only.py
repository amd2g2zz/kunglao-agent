#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_hygiene_rc_record_only.py — the record-only fix batch.

Pins the record-only contract of the code-hygiene RC batch: fail-open
handlers keep their exact return shape (zero decision-behavior change)
but leave ONE rate-limited stderr WARN naming the operation + reason.

Tiers covered:
  A. data-loss tier: write/read failures recorded (rollup due-queue,
     retry counter, claim operation label, journal read, log-reader
     drop counting)
  B. gate silent-pass tier: the #417 record-only pins were FLIPPED by
     the owner ruling 2026-09-28 — a gate ERROR now REJECTS with the
     cause (see tests/test_gate_failclosed.py); the warn stays pure
     telemetry and the freeze tests still pin verdict identity across
     warn patch-out
  B(6): eval telemetry parse-failure recording (eval_loop_runner)
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import kunglao_log
import rollup
import tc_journal
import worker_budget_gates as gates
import worker_budget_sinks as sinks


def _stderr(capsys) -> str:
    return capsys.readouterr().err


def _noop_warn(_op, _reason) -> None:
    return None


# ---------------------------------------------------------------------------
# A1 — rollup due-queue write failure is recorded, return shape unchanged
# ---------------------------------------------------------------------------

def test_rollup_notes_due_write_failure_warns(tmp_path, monkeypatch, capsys):
    (tmp_path / "notes").mkdir()

    def _raiser(self, *a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", _raiser)
    rollup._WARN_LAST.clear()
    ok = rollup._queue_notes_due(tmp_path, "C-914", "FAILED")
    assert ok is False  # return shape unchanged
    err = _stderr(capsys)
    assert "notes_due_queue_write" in err
    assert "OSError" in err
    assert "disk full" in err


def test_rollup_notes_due_success_no_warn(tmp_path, capsys):
    (tmp_path / "notes").mkdir()
    ok = rollup._queue_notes_due(tmp_path, "C-914b", "FAILED")
    assert ok is True
    assert "notes_due_queue_write" not in _stderr(capsys)


# ---------------------------------------------------------------------------
# A2/B5 — worker_budget_gates gate-error sites: FLIPPED fail-closed by the
# owner ruling 2026-09-28 (was: record-only keep-passing). The warn stays;
# the verdict now REJECTS with the cause. Freeze assertions pin verdict
# identity across warn patch-out (warn remains pure telemetry).
# ---------------------------------------------------------------------------

def test_check_workers_lt_3_scan_failure_warn_and_frozen_verdict(
        monkeypatch, capsys):
    class _BoomLib:
        @staticmethod
        def scan_active_workers(_ws):
            raise RuntimeError("scan exploded")

    monkeypatch.setattr(gates, "load_hooks_lib", lambda: _BoomLib)

    gates._WARN_LAST.clear()
    live = gates.check_workers_lt_3({"workspace": "/tmp/ws"})
    assert live[0] is False  # FAIL_CLOSED: the error no longer passes
    assert "RuntimeError" in live[1] and "ACTIVE-WORKERS GATE" in live[1]
    err = _stderr(capsys)
    assert "gate_error:active_workers_scan" in err
    assert "RuntimeError" in err

    # Freeze: with the warn patched out the verdict is byte-identical —
    # the warn is pure telemetry, never a verdict input.
    monkeypatch.setattr(gates, "warn", _noop_warn)
    frozen = gates.check_workers_lt_3({"workspace": "/tmp/ws"})
    assert frozen == live


def test_reset_retry_counter_write_failure_warns(tmp_path, monkeypatch, capsys):
    key = gates._retry_key("w1", "C-1")
    monkeypatch.setattr(gates, "read_retry_counter", lambda _ws: {key: 1})

    def _boom(_path, _counters):
        raise OSError("readonly fs")

    monkeypatch.setattr(gates, "_write_retry_counter", _boom)
    gates._WARN_LAST.clear()
    ok = gates.reset_retry_counter(tmp_path, "w1", "C-1")
    assert ok is False
    err = _stderr(capsys)
    assert "retry_counter_write" in err
    assert "OSError" in err


def test_set_claim_operation_read_failure_warns(tmp_path, monkeypatch, capsys):
    reg = tmp_path / "claim-register.yaml"
    reg.write_text("claims:\n  C-1:\n    status: active\n", encoding="utf-8")

    def _raiser(self, *a, **k):
        raise OSError("reg vanished")

    monkeypatch.setattr(Path, "read_text", _raiser)
    gates._WARN_LAST.clear()
    ok = gates.set_claim_operation(tmp_path, "C-1", ["probe"], "probe")
    assert ok is False
    err = _stderr(capsys)
    assert "claim_operation_label_write" in err
    assert "OSError" in err


def test_check_rotation_experiment_gate_error_frozen(monkeypatch, capsys):
    def _boom(_ws):
        raise KeyError("flags corrupted")

    monkeypatch.setattr(gates, "load_rotation_flags", _boom)
    gates._WARN_LAST.clear()
    live = gates.check_rotation_experiment(
        {"workspace": "/tmp/ws"}, "C-7", "no marker prompt")
    assert live[0] is False  # FAIL_CLOSED flip (owner ruling 2026-09-28)
    assert "reject: rotation gate error" in live[1]
    assert "KeyError" in live[1]
    assert "gate_error:rotation_check" in _stderr(capsys)

    monkeypatch.setattr(gates, "warn", _noop_warn)
    frozen = gates.check_rotation_experiment(
        {"workspace": "/tmp/ws"}, "C-7", "no marker prompt")
    assert frozen == live


# ---------------------------------------------------------------------------
# B5 — worker_budget_sinks env-caps vocabulary failure: FLIPPED fail-closed
# (owner ruling 2026-09-28; was record-only keep-passing in #417)
# ---------------------------------------------------------------------------

def test_check_env_premise_vocab_failure_frozen(monkeypatch, capsys):
    def _boom(_tier, _tools):
        raise TypeError("vocab broken")

    monkeypatch.setattr(sinks, "_env_caps_needed", _boom)
    sinks._B3_WARN_LAST.clear()
    live = sinks.check_env_premise({"workspace": "/tmp/ws"}, 0, tools=["adb"])
    assert live[0] is False  # FAIL_CLOSED flip: the error no longer passes
    assert "ENV-PREMISE GATE" in live[1]
    assert "TypeError" in live[1]
    assert "gate_error:env_caps_vocab" in _stderr(capsys)

    monkeypatch.setattr(sinks, "warn", _noop_warn)
    frozen = sinks.check_env_premise({"workspace": "/tmp/ws"}, 0, tools=["adb"])
    assert frozen == live


# ---------------------------------------------------------------------------
# A3 — kunglao_log reader: count-and-warn, return values unchanged
# (day-file names are unique per test to dodge cross-test (op, reason)
# rate-limit suppression within the process)
# ---------------------------------------------------------------------------

def test_all_rows_counts_corrupt_rows_and_warns(tmp_path, capsys):
    logs = tmp_path / "runs" / "logs"
    logs.mkdir(parents=True)
    good = json.dumps({"type": "x", "n": 1})
    (logs / "kunglao-2099-01-01.jsonl").write_text(
        good + "\n{not json}\n" + good + "\n", encoding="utf-8")
    rows = kunglao_log._all_rows(tmp_path)
    assert len(rows) == 2  # return values unchanged
    err = _stderr(capsys)
    assert "jsonl_drop:kunglao-2099-01-01.jsonl" in err
    assert "1 unparseable row(s) skipped" in err


def test_all_rows_unreadable_day_file_warns(tmp_path, monkeypatch, capsys):
    logs = tmp_path / "runs" / "logs"
    logs.mkdir(parents=True)
    (logs / "kunglao-2099-02-02.jsonl").write_text('{"a": 1}\n', encoding="utf-8")

    real_read = Path.read_text

    def _raiser(self, *a, **k):
        if self.name == "kunglao-2099-02-02.jsonl":
            raise OSError("permission denied")
        return real_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", _raiser)
    rows = kunglao_log._all_rows(tmp_path)
    assert rows == []  # unchanged shape
    err = _stderr(capsys)
    assert "day_file_read:kunglao-2099-02-02.jsonl" in err
    assert "permission denied" in err


def test_iter_jsonl_default_stays_silent():
    """Freeze: without `source`, the Family K reader is byte-identical
    silent (every pre-existing caller keeps zero new stderr output)."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        rows = list(kunglao_log.iter_jsonl(['{"a": 1}', "junk", "", "null"]))
    assert rows == [{"a": 1}, None]
    assert buf.getvalue() == ""


def test_iter_jsonl_source_warns_once_per_read():
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        rows = list(kunglao_log.iter_jsonl(
            ['{"a": 1}', "junk", "junk2"], source="f.jsonl"))
    assert rows == [{"a": 1}]
    err = buf.getvalue()
    assert "jsonl_drop:f.jsonl" in err
    assert "2 unparseable row(s) skipped" in err


# ---------------------------------------------------------------------------
# A4 — tc_journal read failure is recorded
# ---------------------------------------------------------------------------

def test_tc_journal_read_failure_warns(tmp_path, monkeypatch, capsys):
    p = tmp_path / "runs" / "tc-journal.jsonl"
    p.parent.mkdir(parents=True)
    p.write_text('{"dispatch_id": "d1"}\n', encoding="utf-8")

    real_read = Path.read_text

    def _raiser(self, *a, **k):
        if self.name == "tc-journal.jsonl":
            raise OSError("EIO")
        return real_read(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", _raiser)
    tc_journal._WARN_LAST.clear()
    assert tc_journal.read(tmp_path) == []
    err = _stderr(capsys)
    assert "journal_read" in err
    assert "EIO" in err


# ---------------------------------------------------------------------------
# B(6) — eval telemetry parse failures recorded (returns unchanged)
# ---------------------------------------------------------------------------

def test_session_cost_corrupt_json_warns(capsys):
    import eval_loop_runner as lr
    # corrupt line FIRST: the parser returns at the first cost-shaped
    # line, so a trailing corrupt line would never be reached
    out = lr._session_cost(
        '{"total_cost_usd": broken}\n{"total_cost_usd": 1.5}')
    assert out == {"total_cost_usd": 1.5, "input_tokens": None,
                   "output_tokens": None}
    assert "session_cost_parse" in _stderr(capsys)


def test_session_cost_all_corrupt_returns_none(capsys):
    import eval_loop_runner as lr
    # payload differs from the sibling test: _boot.warn rate-limits on
    # identical (op, reason) pairs, so an identical corrupt line would
    # be suppressed rather than re-printed (the designed behavior)
    assert lr._session_cost('{"usage": broken,}') is None
    assert "session_cost_parse" in _stderr(capsys)


def test_chain_layer_paths_missing_ground_truth_warns(tmp_path, capsys):
    import eval_loop_runner as lr
    assert lr.chain_layer_paths(tmp_path) == []
    assert "chain_layer_paths_read" in _stderr(capsys)


def test_extract_checker_gap_missing_evidence_warns(tmp_path, capsys):
    import eval_loop_runner as lr
    gap = lr.extract_checker_gap({"verdict": "FAIL", "failures": [],
                                  "evidence": str(tmp_path / "nope.json")})
    assert gap["static_missing"] == []
    assert gap["replay"] is None
    assert "gap_evidence_read" in _stderr(capsys)


def test_iter_jsonl_telemetry_corrupt_warns(tmp_path, capsys):
    import eval_loop_runner as lr
    p = tmp_path / "t.jsonl"
    p.write_text('{"k": 1}\nbroken\n', encoding="utf-8")
    rows = lr._iter_jsonl(p)
    assert rows == [{"k": 1}]
    assert "telemetry_jsonl_parse" in _stderr(capsys)


def test_factor_face_bad_ledger_warns(tmp_path, capsys):
    import eval_loop_runner as lr
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "mission_ledger.yaml").write_text("mission: [broken\n",
                                              encoding="utf-8")
    triple = lr._factor_face(tmp_path)
    assert triple == (0, 0, 0.0)  # shape unchanged
    assert "factor_ledger_read" in _stderr(capsys)


def test_convergence_face_bad_json_warns(tmp_path, monkeypatch, capsys):
    import eval_loop_runner as lr

    class _Proc:
        returncode = 0
        stdout = '{"decision": not-valid-json'
        stderr = ""

    monkeypatch.setattr(lr.subprocess, "run", lambda *a, **k: _Proc())
    converged, decision = lr._convergence_face(tmp_path)
    assert converged is False
    assert "UNREADABLE" in decision  # frozen decision shape
    assert "convergence_face_parse" in _stderr(capsys)


def test_tuition_cost_failure_warns(tmp_path, monkeypatch, capsys):
    import eval_loop_runner as lr

    def _boom(_ws):
        raise KeyError("no cost state")

    monkeypatch.setattr(lr.tuition_curve, "cost_state", _boom)
    monkeypatch.setattr(lr, "_convergence_face",
                        lambda _ws: (False, "UNREADABLE (stub)"))
    monkeypatch.setattr(lr, "_factor_face", lambda _ws: (0, 0, 0.0))
    monkeypatch.setattr(lr, "_oracle_face", lambda _ws: (0, 0))
    monkeypatch.setattr(lr, "count_snapshot_rows", lambda _ws: 0)
    harvested = lr.harvest(tmp_path, baseline_rounds=0)
    assert harvested["tokens_cost"] == 0.0
    assert "tuition_cost_read" in _stderr(capsys)


# ---------------------------------------------------------------------------
# freeze — gate verdict identity is pinned independently of warn plumbing
# (verdicts flipped fail-closed by the owner ruling 2026-09-28; the freeze
# now pins REJECT-identity across warn patch-out)
# ---------------------------------------------------------------------------

def test_gate_verdict_freeze_warn_is_pure_telemetry(monkeypatch):
    """The warn patch-out changes NOTHING about returned verdicts. Since
    the 2026-09-28 ruling the gate-error verdict is REJECT with the
    cause carried in the reason — the warn stays pure telemetry."""
    class _BoomLib:
        @staticmethod
        def scan_active_workers(_ws):
            raise RuntimeError("x")

    def _boom(_tier, _tools):
        raise ValueError("y")

    monkeypatch.setattr(gates, "load_hooks_lib", lambda: _BoomLib)
    monkeypatch.setattr(sinks, "_env_caps_needed", _boom)

    with monkeypatch.context() as m:
        m.setattr(gates, "warn", _noop_warn)
        m.setattr(sinks, "warn", _noop_warn)
        v1 = gates.check_workers_lt_3({"workspace": "/tmp/ws"})
        v2 = sinks.check_env_premise({"workspace": "/tmp/ws"}, 0, tools=[])
    assert v1[0] is False and "RuntimeError" in v1[1]
    assert v2[0] is False and "ValueError" in v2[1]
