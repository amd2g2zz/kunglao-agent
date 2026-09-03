#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_failopen_emit.py — #569 AUDIT: FAIL_OPEN paths must emit.

Scope (issue #569):
  1. hooks/dispatch_gate.py::_top1_enforcement — two FAIL_OPEN faces:
     a) `from worker_budget import check_priority` raises (scorer wiring
        unavailable); the gate returns None silently (never REJECTs).
     b) check_priority() itself raises (audit crash); the gate returns
        None silently.
     Both faces must leave a `top1_fail_open` trace in the unified log so
     post-mortem can see the gate was bypassed (a silent bypass is the
     exact observability gap #569 closes).
  2. scripts/kunglao-decide.py::_conservative_blocked — the script-level
     catch-all that returns BLOCKED when decide() itself raises. Must
     emit a `decide_fail_open` trace with the exception type + message
     in detail.

#459 contract (this file anchors): emit failure NEVER changes the decision
face's exit code (fail-open — observability must not gate decisions).
Reuses _event_rows / _top1_ws from tests/test_decision_teeth.py.
"""
from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))  # _top1_ws

import kunglao_log  # noqa: E402

from test_decision_teeth import _event_rows, _top1_ws  # noqa: E402


def _load_kunglao_decide():
    """kunglao-decide.py is hyphenated (CLI name) so Python's import system
    can't load it directly; use spec_from_file_location under a dotted alias."""
    path = REPO_ROOT / "scripts" / "kunglao-decide.py"
    spec = importlib.util.spec_from_file_location("kunglao_decide", str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kunglao_decide"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _kunglao_log_calls(monkeypatch):
    """Return a list capturing every kunglao_log.emit call made after this
    point; the seam mirrors tests/test_event_stream_adoption.py."""
    calls: list[dict] = []

    def _fake(ws, actor, action, **kw):
        calls.append({"ws": ws, "actor": actor, "action": action, **kw})

    monkeypatch.setattr(kunglao_log, "emit", _fake)
    return calls


# =========================================================================
# ① dispatch_gate FAIL_OPEN faces
# =========================================================================

class TestTop1FailOpenEmit:
    """#569: the two FAIL_OPEN returns in _top1_enforcement must both leave
    a top1_fail_open trace so the audit log shows when the gate was bypassed
    instead of REJECTing."""

    def test_top1_scorer_unavailable_emits(self, tmp_path, monkeypatch):
        """Face (a): worker_budget cannot be imported (ImportError) — the
        gate fails open (returns None) AND emits top1_fail_open."""
        # Sabotage: hide worker_budget. The hook does
        #   `sys.path.insert(0, str(SKILL_DIR / "hooks"))` then
        #   `from worker_budget import check_priority`
        # so removing it from sys.modules (and blocking re-import) is enough
        # to force the ImportError branch.
        monkeypatch.delitem(sys.modules, "worker_budget", raising=False)
        blocker = types.ModuleType("worker_budget")
        blocker.__spec__ = None  # signal ImportError on next import
        monkeypatch.setitem(sys.modules, "worker_budget", blocker)

        ws = _top1_ws(tmp_path)
        # capture in-process emit so the test does not depend on the jsonl
        # being flushed at teardown
        calls = _kunglao_log_calls(monkeypatch)

        import dispatch_gate as dg
        # fresh import in case the module already cached worker_budget
        importlib.reload(dg)
        try:
            rc = dg._top1_enforcement(ws, "C-2", "[T1 tools=grep] claim C-2")
        finally:
            # restore real worker_budget for subsequent tests in this process
            monkeypatch.delitem(sys.modules, "worker_budget", raising=False)

        assert rc is None, (
            f"FAIL_OPEN face must return None (no REJECT); got {rc!r}")
        rows = [c for c in calls if c["action"] == "top1_fail_open"]
        assert rows, (
            f"top1_fail_open must be emitted on scorer-unavailable; "
            f"got {calls}")
        assert rows[-1]["claim"] == "C-2", (
            f"detail must name the bypassed claim; got {rows[-1]}")
        assert rows[-1]["actor"] == "hook:dispatch_gate", (
            f"actor must identify the source hook; got {rows[-1]}")

    def test_top1_audit_crash_emits(self, tmp_path, monkeypatch):
        """Face (b): worker_budget imports fine but check_priority() raises —
        gate fails open (returns None) AND emits top1_fail_open."""
        import worker_budget as wb  # the real one

        def _boom(*a, **kw):
            raise RuntimeError("simulated audit crash")

        monkeypatch.setattr(wb, "check_priority", _boom)

        ws = _top1_ws(tmp_path)
        calls = _kunglao_log_calls(monkeypatch)

        import dispatch_gate as dg
        # ensure worker_budget is the live reference inside dg
        importlib.reload(dg)
        rc = dg._top1_enforcement(ws, "C-3", "[T1 tools=grep] claim C-3")

        assert rc is None, (
            f"audit-crash FAIL_OPEN must return None; got {rc!r}")
        rows = [c for c in calls if c["action"] == "top1_fail_open"]
        assert rows, (
            f"top1_fail_open must be emitted on audit crash; got {calls}")
        assert rows[-1]["claim"] == "C-3"
        # detail must surface the exception class so the post-mortem can
        # distinguish audit_crash from scorer_unavailable without re-reading
        # the code
        detail = rows[-1].get("detail") or ""
        assert "RuntimeError" in detail, (
            f"detail must carry the exception class; got {detail!r}")

    def test_top1_fail_open_via_subprocess(self, tmp_path):
        """Hook-side subprocess shape: sabotage worker_budget by replacing
        hooks/worker_budget.py with a stub that raises ImportError, run the
        gate, and assert the jsonl carries top1_fail_open (the same shape
        #459's TestDispatchGateRejectEmit uses for top1_reject)."""
        root = tmp_path / "r1"
        ws = _top1_ws(root)
        # Sabotage the import by hiding worker_budget from sys.modules inside
        # the subprocess. Run the gate's _top1_enforcement directly via a tiny
        # driver that does the sabotage in-process; the driver lives in
        # tmp_path (not scripts/) so the test does not pollute the repo.
        driver = tmp_path / "_failopen_driver.py"
        driver.write_text(
            "import sys, importlib.util\n"
            f"_dg_spec = importlib.util.spec_from_file_location("
            f"'dispatch_gate', {str(REPO_ROOT / 'hooks' / 'dispatch_gate.py')!r})\n"
            "dg = importlib.util.module_from_spec(_dg_spec)\n"
            "sys.modules['dispatch_gate'] = dg\n"
            "_dg_spec.loader.exec_module(dg)\n"
            "sys.modules.pop('worker_budget', None)\n"
            "import types\n"
            "blocker = types.ModuleType('worker_budget')\n"
            "blocker.__spec__ = None\n"
            "sys.modules['worker_budget'] = blocker\n"
            "import pathlib\n"
            f"ws = pathlib.Path({str(ws)!r})\n"
            "rc = dg._top1_enforcement(ws, 'C-2', 'test prompt')\n"
            "sys.exit(0 if rc is None else 1)\n",
            encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(driver)],
            capture_output=True, text=True, timeout=60,
            cwd=str(REPO_ROOT), errors="replace")
        assert r.returncode == 0, (
            f"driver must observe FAIL_OPEN return None; "
            f"rc={r.returncode} stderr={r.stderr!r}")
        rows = [e for e in _event_rows(ws) if e.get("action") == "top1_fail_open"]
        assert rows, (
            f"subprocess path must leave top1_fail_open in the jsonl; "
            f"rows={_event_rows(ws)}")
        assert any(e.get("claim") == "C-2" for e in rows)


# =========================================================================
# ② kunglao-decide FAIL_OPEN face
# =========================================================================

class TestDecideFailOpenEmit:
    """#569: _conservative_blocked must emit decide_fail_open before returning
    the BLOCKED dict — the audit needs to know the script took the exception
    path (the BLOCKED shape alone is identical to a healthy BLOCKED)."""

    def test_conservative_blocked_emits(self, tmp_path, monkeypatch):
        kd = _load_kunglao_decide()
        ws = tmp_path / "ws"
        ws.mkdir(parents=True)
        calls = _kunglao_log_calls(monkeypatch)

        exc = RuntimeError("simulated decide crash")
        out = kd._conservative_blocked(ws, exc)

        # the BLOCKED contract must be unchanged
        assert out["decision"] == "BLOCKED"
        assert "error" in out and "RuntimeError" in out["error"], (
            f"error field must carry the exception; got {out!r}")

        # AND the audit must see it
        rows = [c for c in calls if c["action"] == "decide_fail_open"]
        assert rows, (
            f"_conservative_blocked must emit decide_fail_open; got {calls}")
        assert rows[-1]["actor"] == "kunglao-decide", (
            f"actor must identify the source script; got {rows[-1]}")
        detail = rows[-1].get("detail") or ""
        assert "RuntimeError" in detail and "simulated decide crash" in detail, (
            f"detail must carry the exception class + message; got {detail!r}")

    def test_decide_emit_failure_does_not_break_blocked_shape(
            self, tmp_path, monkeypatch):
        """#459 parity: emit failure must NEVER raise out of _conservative_blocked
        — the BLOCKED dict is the contract, the emit is observability only."""
        kd = _load_kunglao_decide()

        def _boom(*a, **kw):
            raise RuntimeError("log write failed")

        monkeypatch.setattr(kunglao_log, "emit", _boom)
        ws = tmp_path / "ws"
        ws.mkdir(parents=True)
        out = kd._conservative_blocked(ws, ValueError("simulated"))
        assert out["decision"] == "BLOCKED", (
            f"emit crash must not corrupt the BLOCKED contract; got {out!r}")
        assert "ValueError" in out["error"]

    def test_decide_fail_open_via_subprocess(self, tmp_path):
        """Subprocess shape: run a driver that calls _conservative_blocked
        on a fresh workspace, then check the jsonl. Driver lives in
        tmp_path to avoid polluting the repo scripts/ directory."""
        ws = tmp_path / "ws"
        ws.mkdir(parents=True)
        driver = tmp_path / "_failopen_decide_driver.py"
        driver.write_text(
            "import sys, pathlib, importlib.util\n"
            f"_spec = importlib.util.spec_from_file_location("
            f"'kunglao_decide', {str(REPO_ROOT / 'scripts' / 'kunglao-decide.py')!r})\n"
            "kd = importlib.util.module_from_spec(_spec)\n"
            "sys.modules['kunglao_decide'] = kd\n"
            "_spec.loader.exec_module(kd)\n"
            f"ws = pathlib.Path({str(ws)!r})\n"
            "out = kd._conservative_blocked(ws, RuntimeError('driver'))\n"
            "import json; json.dump(out, sys.stdout)\n",
            encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(driver)],
            capture_output=True, text=True, timeout=60,
            cwd=str(REPO_ROOT), errors="replace")
        assert r.returncode == 0, (
            f"driver must succeed; rc={r.returncode} stderr={r.stderr!r}")
        rows = [e for e in _event_rows(ws) if e.get("action") == "decide_fail_open"]
        assert rows, (
            f"subprocess path must leave decide_fail_open in the jsonl; "
            f"rows={_event_rows(ws)}")