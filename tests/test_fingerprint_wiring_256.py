# -*- coding: utf-8 -*-
"""tests/test_fingerprint_wiring_256.py — issue 256 fingerprint wiring.

The A4 thrash circuit (scripts/zero_output_fingerprint.py) was
built-but-unwired: record_action had zero production callers and the
gate was absent from the production dispatch battery. This file pins the
wiring on the real trigger path:

  - post_check (Agent PostToolUse = a worker action completed) records
    every tool the completed worker actually invoked against its
    (tool-family, claim) fingerprint;
  - the zerooutput gate sits in the pre_check checks battery, so a
    tripped circuit rejects a dispatch that would REPEAT the tripped
    (claim, tool-family) — other claims/families pass;
  - the gate derives belief freshness ITSELF: a belief move after the
    trip makes the ledger stale = reset, so the documented repair can
    never deadlock the loop;
  - a broken recorder is VISIBLE (rate-limited stderr WARN), never
    silently swallowed, while post_check liveness is never sacrificed
    (rc stays 0).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import zero_output_fingerprint as zf  # noqa: E402

# The production dispatch battery lives in worker_budget_sinks.pre_check;
# loaded by-path under an isolated name (the 762 convention, same shape
# as test_canary_gates) so shared-name twins cannot reorder under us.
import importlib.util as _ilu
_sinks_path = REPO_ROOT / "hooks" / "worker_budget_sinks.py"
_spec = _ilu.spec_from_file_location("fingerprint_wiring_sinks", _sinks_path)
sinks = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(sinks)


# ---------- shared seam: capture kunglao_log.emit in-process ----------------

@pytest.fixture
def events(monkeypatch):
    """Capture every kunglao_log.emit call (lazy imports hit the module
    attr — same convention as test_observability_birth_880)."""
    import kunglao_log

    calls = []

    def _fake(ws, actor, action, **kw):
        calls.append({"ws": ws, "actor": actor, "action": action, **kw})

    monkeypatch.setattr(kunglao_log, "emit", _fake)
    return calls


# ---------- fixtures: a dispatched worker that just completed ----------------

_TOOL = "mcp__ghidra__decompile"
_NO_PROGRESS_RESULT = f"used {_TOOL}; done"


def _fp(tool: str, cid: str) -> str:
    """The fingerprint the recorder actually stores (family-collapsed)."""
    return zf.fingerprint(zf.tool_family(tool), cid)


def _dispatch_payload(claim: str = "C-001", tools: str = "grep") -> dict:
    """A conforming dispatch envelope (the pre_check input face). Built
    with json.dumps — brace-escaped f-strings have already eaten one
    JSON brace once in this file's history."""
    envelope = json.dumps({"kunglao_dispatch": {
        "version": 1, "claim": claim, "tier": 1, "tools": [tools],
        "agent": "w-test"}})
    return {"tool_input": {
        "name": "w-test",
        "description": "",
        "prompt": f"{envelope}\nfacts-snapshot: 1 facts",
    }}


def _seed_worker(ws: Path) -> None:
    """A dispatched worker entry for C-001 (what pre_check's
    register_worker writes at the approval point)."""
    import time
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "runs").mkdir(exist_ok=True)
    (ws / "facts").mkdir(exist_ok=True)
    (ws / "facts" / "_INDEX.md").write_text(
        "F001 | OPEN | C-001 | x\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: OPEN\n", encoding="utf-8")
    (ws / "analysis_state.txt").write_text(
        "[active_workers]\n"
        "worker_id=w-test | claim_id=C-001 | dispatched_at=%d | tier=1 | "
        "tools=grep\n[/active_workers]\n" % (int(time.time()) - 90),
        encoding="utf-8")


def _completion_payload() -> dict:
    return {"tool_input": {"name": "w-test", "description": "",
                           "prompt": "dispatch prompt"},
            "tool_result": _NO_PROGRESS_RESULT}


def _paths(ws: Path) -> dict:
    return {
        "workspace": str(ws),
        "state": ws / "analysis_state.txt",
        "register": ws / "claim-register.yaml",
        "deps": ws / "claim_deps.yaml",
        "task_spec": ws / "task_spec.yaml",
    }


def _state(ws: Path) -> dict:
    return json.loads(
        (ws / "runs" / "zero-output-fingerprint.json").read_text(
            encoding="utf-8"))


# ---------- 1. the real trigger path: post_check records --------------------

class TestPostCheckRecording:
    def test_post_check_records_worker_actions(self, tmp: Path):
        """THE issue acceptance, part 1 (recording): two identical
        no-progress worker completions through the REAL post_check path
        land a recorded streak of 2 on the (tool, claim) fingerprint.
        The worker entry is re-seeded between completions — production
        re-dispatches (and re-registers) before each completion."""
        ws = tmp / "ws"
        for _ in range(2):
            _seed_worker(ws)
            rc = sinks.post_check(_completion_payload(), _paths(ws))
            assert rc == 0
        state = _state(ws)
        fp = _fp(_TOOL, "C-001")
        assert state["streaks"][fp] == 2
        assert state["belief_hash"] == zf.belief_hash(ws)

    def test_third_identical_action_emits_break_telemetry(self, tmp: Path,
                                                          events):
        """THE issue acceptance, part 2 (telemetry): the fingerprint
        reaching ZERO_OUTPUT_N through post_check completions fires
        exactly one zero_output_break row from the real trigger path —
        actor, tool, and streak attributed."""
        ws = tmp / "ws"
        for _ in range(zf.ZERO_OUTPUT_N):
            _seed_worker(ws)
            assert sinks.post_check(
                _completion_payload(), _paths(ws)) == 0
        rows = [e for e in events if e["action"] == "zero_output_break"]
        assert len(rows) == 1, f"expected exactly one break, got {rows}"
        assert rows[0]["actor"] == "zero_output_fingerprint"
        assert rows[0]["tool"] == _TOOL
        assert f"streak={zf.ZERO_OUTPUT_N}" in rows[0]["detail"]

    def test_unclaimed_worker_not_recorded(self, tmp: Path):
        """Scope discriminator (claim-granularity v1, mirrors
        _emit_tool_calls): an Agent completion with no dispatched-worker
        entry must not touch the fingerprint state."""
        ws = tmp / "ws"
        ws.mkdir(parents=True)
        (ws / "runs").mkdir()
        rc = sinks.post_check(_completion_payload(), _paths(ws))
        assert rc == 0
        assert not (ws / "runs" / "zero-output-fingerprint.json").exists()

    def test_recorder_crash_fails_open_but_visible(self, tmp: Path,
                                                   monkeypatch, capsys):
        """Liveness first: a crashing recorder never breaks post_check —
        but the fault is VISIBLE, not silently swallowed."""
        ws = tmp / "ws"
        _seed_worker(ws)

        def _boom(ws_path, tool, target_type):
            raise RuntimeError("recorder exploded")

        monkeypatch.setattr(zf, "record_action", _boom)
        rc = sinks.post_check(_completion_payload(), _paths(ws))
        captured = capsys.readouterr()
        assert rc == 0, "recorder fault must not break post_check"
        assert "zero-output" in captured.err, captured.err
        assert "recorder" in captured.err, captured.err

    def test_noop_recorder_is_detectable(self, tmp: Path, monkeypatch,
                                         capsys):
        """Adversarial: a record_action that returns without a streak
        payload (the silent no-op) must be detected — the wiring treats
        a wrong return shape as a recorder fault with a visible WARN,
        never as success."""
        ws = tmp / "ws"
        _seed_worker(ws)
        monkeypatch.setattr(zf, "record_action",
                            lambda ws_path, tool, target_type: None)
        rc = sinks.post_check(_completion_payload(), _paths(ws))
        captured = capsys.readouterr()
        assert rc == 0
        assert "zero-output" in captured.err, captured.err
        assert "recorder" in captured.err, captured.err

    def test_recorder_warn_is_rate_limited_per_ws_reason(self, tmp: Path,
                                                         monkeypatch,
                                                         capsys):
        """A persistently broken recorder must not print one WARN per
        completion: same ws + same reason -> the second completion is
        silent; a DIFFERENT reason on the same ws warns again."""
        ws = tmp / "ws"
        _seed_worker(ws)
        monkeypatch.setattr(zf, "record_action",
                            lambda ws_path, tool, target_type: None)
        sinks.post_check(_completion_payload(), _paths(ws))
        sinks.post_check(_completion_payload(), _paths(ws))
        captured = capsys.readouterr()
        warn_lines = [ln for ln in captured.err.splitlines()
                      if "zero-output fingerprint recorder WARN" in ln]
        assert len(warn_lines) == 1, captured.err
        # the reason changes (no-op -> crash): the new reason warns
        monkeypatch.setattr(
            zf, "record_action",
            lambda ws_path, tool, target_type: (_ for _ in ()).throw(
                RuntimeError("now crashing")))
        _seed_worker(ws)
        rc = sinks.post_check(_completion_payload(), _paths(ws))
        captured2 = capsys.readouterr()
        assert rc == 0
        assert "now crashing" in captured2.err, captured2.err

    def test_partial_recording_says_so(self, tmp: Path, monkeypatch,
                                       capsys):
        """No total-failure mislabel: when the recorder faults on the
        SECOND of two invoked tools, the WARN must report what landed
        (1 of 2) and name the tool where counting stopped."""
        ws = tmp / "ws"
        _seed_worker(ws)
        payload = {"tool_input": {"name": "w-test", "description": "",
                                  "prompt": "dispatch prompt"},
                   "tool_result": ("used mcp__ghidra__decompile and "
                                   "mcp__x64dbg__connect_remote; done")}

        def _half(ws_path, tool, target_type):
            if tool == "mcp__x64dbg__connect_remote":  # sorted second
                raise RuntimeError("boom")
            return {"fingerprint": "x", "streak": 1, "circuit_broken": False,
                    "inject": None}

        monkeypatch.setattr(zf, "record_action", _half)
        rc = sinks.post_check(payload, _paths(ws))
        captured = capsys.readouterr()
        assert rc == 0
        assert "1/2 tools recorded" in captured.err, captured.err
        assert "at tool=mcp__x64dbg__connect_remote" in captured.err, \
            captured.err

    def test_mentioned_not_invoked_tool_not_recorded(self, tmp: Path):
        """The recorder's scan is invocation-shaped: a tool name inside
        another token (ripgrep; rev-frida2) is prose, not an invocation,
        and must not accrue a streak."""
        ws = tmp / "ws"
        _seed_worker(ws)
        payload = {"tool_input": {"name": "w-test", "description": "",
                                  "prompt": "dispatch prompt"},
                   "tool_result": ("used ripgrep and planned rev-frida2 "
                                   "attachments; done")}
        rc = sinks.post_check(payload, _paths(ws))
        assert rc == 0
        assert not (ws / "runs" / "zero-output-fingerprint.json").exists()

    def test_invoked_tool_word_boundary_still_records(self, tmp: Path):
        """Positive control for the tightened scan: a standalone
        KNOWN_TOOLS invocation still records."""
        ws = tmp / "ws"
        _seed_worker(ws)
        payload = {"tool_input": {"name": "w-test", "description": "",
                                  "prompt": "dispatch prompt"},
                   "tool_result": "used vmr-shell to detonate; done"}
        rc = sinks.post_check(payload, _paths(ws))
        assert rc == 0
        state = _state(ws)
        fp = _fp("vmr-shell", "C-001")
        assert state["streaks"][fp] == 1


# ---------- 2. the gate in the production battery ----------------------------

class TestProductionBatteryRegistration:
    def test_zerooutput_gate_registered_in_production_battery(self):
        """Structural pin (the 57 precedent): the zerooutput gate is wired
        into the pre_check checks battery — the list that decides which
        gates actually run in production — exactly once, WITH the
        dispatched claim/tool context (scoping inputs). Direct calls in
        test files alone (the old test-only face) do not count."""
        src = _sinks_path.read_text(encoding="utf-8")
        battery_head = ("('zerooutput', "
                        "check_zero_output_circuit(paths.get('workspace')")
        assert battery_head in src, \
            "the zerooutput gate must sit in the pre_check battery"
        assert "cid, tools))" in src, \
            "the battery call must carry the dispatched claim/tool context"
        assert src.count("check_zero_output_circuit(") == 1

    def test_tripped_circuit_rejects_matching_dispatch_e2e(self, tmp: Path,
                                                           capsys):
        """A tripped (claim, tool-family) REJECTs the dispatch that would
        REPEAT it. The trip uses the grep family so the dispatch below
        reaches the zerooutput gate with sibling gates still passing on
        minimal paths (the plan-first e2e precedent)."""
        ws = tmp / "ws"
        ws.mkdir(parents=True)
        (ws / "runs").mkdir()
        for _ in range(zf.ZERO_OUTPUT_N):
            zf.record_action(ws, "grep", "C-001")
        rc = sinks.pre_check(_dispatch_payload("C-001", "grep"), _paths(ws))
        captured = capsys.readouterr()
        assert rc == 2, captured.err
        assert "REJECT zerooutput" in captured.err, captured.err
        # the manual escape hatch is named (review round 2)
        assert "zero-output-fingerprint.json" in captured.err, captured.err

    def test_stale_state_after_belief_move_passes(self, tmp: Path, capsys):
        """THE deadlock fix (review round 2 CRITICAL): trip the circuit,
        then move the workspace belief WITHOUT any record_action in
        between — the gate must treat the ledger as stale (= reset) and
        PASS the would-repeat dispatch. Reset must not require a
        successful dispatch; that would invert the fail-open doctrine."""
        ws = tmp / "ws"
        ws.mkdir(parents=True)
        (ws / "runs").mkdir()
        for _ in range(zf.ZERO_OUTPUT_N):
            zf.record_action(ws, "grep", "C-001")
        # belief moves outside the recorder (register rewrite)
        (ws / "claim-register.yaml").write_text(
            "claims:\n  - id: C-001\n    status: OPEN\n", encoding="utf-8")
        rc = sinks.pre_check(_dispatch_payload("C-001", "grep"), _paths(ws))
        captured = capsys.readouterr()
        assert rc == 0, captured.err

    def test_dispatch_of_other_claim_passes_despite_tripped(self, tmp: Path,
                                                            capsys):
        """Scoping fix (review round 2 HIGH): a tripped C-001/grep
        fingerprint must not lock unrelated claims out of the workspace —
        a conforming C-999 dispatch of the same tool passes."""
        ws = tmp / "ws"
        ws.mkdir(parents=True)
        (ws / "runs").mkdir()
        for _ in range(zf.ZERO_OUTPUT_N):
            zf.record_action(ws, "grep", "C-001")
        rc = sinks.pre_check(_dispatch_payload("C-999", "grep"), _paths(ws))
        captured = capsys.readouterr()
        assert rc == 0, captured.err

    def test_same_claim_different_family_passes(self, tmp: Path, capsys):
        """Family granularity: C-001 tripped on the vmr-shell family; a
        C-001 dispatch of a DIFFERENT tool family (grep) passes — the
        guidance's 'different action family' repair is true."""
        ws = tmp / "ws"
        ws.mkdir(parents=True)
        (ws / "runs").mkdir()
        for _ in range(zf.ZERO_OUTPUT_N):
            zf.record_action(ws, "vmr-shell", "C-001")
        rc = sinks.pre_check(_dispatch_payload("C-001", "grep"),
                             _paths(ws))
        captured = capsys.readouterr()
        assert rc == 0, captured.err

    def test_fresh_workspace_fails_open(self, tmp: Path, capsys):
        """No circuit state -> the gate passes (never deadlocks the
        loop) — the dispatch flows to the rest of the battery."""
        ws = tmp / "ws"
        ws.mkdir(parents=True)
        (ws / "runs").mkdir()
        payload = {"tool_input": {
            "name": "w-test",
            "description": "",
            "prompt": ('{"kunglao_dispatch": {"version": 1, '
                       '"claim": "C-001", "tier": 1, "tools": ["grep"], '
                       '"agent": "w-test"}}\n'
                       'facts-snapshot: 1 facts'),
        }}
        rc = sinks.pre_check(payload, _paths(ws))
        captured = capsys.readouterr()
        assert rc == 0, captured.err

    def test_reject_fixes_carries_zerooutput_guidance(self):
        """The REJECT carries an executable repair path in the
        additionalContext channel (the 270 dual channel), naming
        failure_analysis."""
        fix = sinks.REJECT_FIXES["zerooutput"]["additionalContext"]
        assert "failure_analysis" in fix


# ---------- 3. the recorder's own posture ------------------------------------

class TestRecorderPosture:
    def test_recording_is_nonblocking_shadow_semantics(self, tmp: Path):
        """Recording itself never blocks: record_action counting the
        tripping action returns the inject hint but post_check keeps
        rc 0 — only the NEXT dispatch face enforces."""
        ws = tmp / "ws"
        _seed_worker(ws)
        for _ in range(zf.ZERO_OUTPUT_N - 1):
            sinks.post_check(_completion_payload(), _paths(ws))
            _seed_worker(ws)  # re-register for the next completion
        rc = sinks.post_check(_completion_payload(), _paths(ws))
        assert rc == 0
        state = _state(ws)
        fp = _fp(_TOOL, "C-001")
        assert state["streaks"][fp] >= zf.ZERO_OUTPUT_N

    def test_module_posture_note_is_graduated(self):
        """The module docstring must not keep claiming the shadow
        posture ("does NOT block anything") now that the gate is in the
        production battery — comment rot is how gates look dead."""
        doc = (REPO_ROOT / "scripts" / "zero_output_fingerprint.py"
               ).read_text(encoding="utf-8")
        assert '"""' in doc
        assert "does NOT block anything" not in doc
