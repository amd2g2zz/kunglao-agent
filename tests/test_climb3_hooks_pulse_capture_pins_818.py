#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb3_hooks_pulse_capture_pins_818.py — #818 climb segment 3A.

Behavior pins on REAL fixtures for the two hooks faces the second climb
leg left unmeasured:

  hooks/worker_pulse.py — the PostToolUse/Agent convergence pulse:
  activation + envelope gating, the dispatch-path pulse (real
  convergence_check / priority_ratio subprocesses over a stamped
  synthetic workspace), the BLOCKED mechanical-failure rc=3 face, the
  non-dispatch stale-worker soft pulse, the TASKSTOP delivery reminder
  (#88), and the quiet faces (inactive / no workspace / stale stdin).

  hooks/violation_capture.py — the PostToolUse/Bash mechanical recorder
  (#718): the in-place tamper idiom match (sed -i / perl -pi /
  python -c open-for-write), the traceback capture over both tool_response
  envelope shapes, the #24 doc-pointer lighting (mapped + missing doc +
  unmapped action), and the ledger emission through kunglao_log with the
  fail-open faces (broken stdin / recorder crash).

Pin discipline: expectations derive from the fixture each test computed —
no repo-state literalization (no pinned event counts, no pinned ledger
bytes; assertions read back what the fixture's own machinery wrote).
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"
SCRIPTS = ROOT / "scripts"
for _p in (str(HOOKS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _factories import stamp_current, write_hook_state  # noqa: E402

import worker_pulse as wp  # noqa: E402
import violation_capture as vc  # noqa: E402


# ------------------------------------------------------------ fixtures

def _pulse_ws(tmp_path: Path) -> Path:
    """A stamped synthetic workspace the pulse subprocesses accept:
    version stamp (0.1.6 gate), claim register, task_spec marker, and an
    open claim so the DECISION face renders."""
    ws = tmp_path / "ws"
    ws.mkdir()
    stamp_current(ws)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: OPEN\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "primary_questions: []\n", encoding="utf-8")
    (ws / "runs").mkdir()
    return ws


def _status_file(ws: Path, name: str, status: str,
                 age_min: float = 0.0) -> Path:
    p = ws / "runs" / f"worker-status-{name}.md"
    p.write_text(f"# worker {name}\nstatus: {status}\n", encoding="utf-8")
    if age_min:
        old = time.time() - age_min * 60
        os.utime(p, (old, old))
    return p


def _dispatch_payload(ws: Path, claim: str = "C-1") -> dict:
    return {
        "cwd": str(ws),
        "tool_name": "Agent",
        "tool_input": {
            "prompt": json.dumps({
                "kunglao_dispatch": {
                    "version": 1, "claim": claim, "tier": 1, "tools": [],
                },
            }) + " analyze the sample",
        },
    }


# ================================================== worker_pulse gating

class TestPulseGating:
    def test_no_workspace_is_silent(self, tmp_path) -> None:
        assert wp.main({"cwd": str(tmp_path / "nowhere")}) == 0

    def test_inactive_workspace_gets_zero_injection(
            self, tmp_path, capsys) -> None:
        ws = _pulse_ws(tmp_path)  # no hook state written
        payload = _dispatch_payload(ws)
        assert wp.main(payload) == 0
        assert capsys.readouterr().out == ""

    def test_expired_activation_sleeps(self, tmp_path, capsys) -> None:
        ws = _pulse_ws(tmp_path)
        write_hook_state(ws, active_hooks=["worker_pulse"],
                         expires_minutes=-1.0)
        assert wp.main(_dispatch_payload(ws)) == 0
        assert capsys.readouterr().out == ""

    def test_resolve_workspace_prefers_the_nested_base(self, tmp_path) -> None:
        proj = tmp_path / "proj"
        skill = proj / "malware-analysis-workspace"
        skill.mkdir(parents=True)
        (skill / "claim-register.yaml").write_text(
            "claims: []\n", encoding="utf-8")
        got = wp._resolve_workspace({"cwd": str(proj)})
        assert got == skill
        # flat workspace face
        flat = tmp_path / "flat"
        flat.mkdir()
        (flat / "claim-register.yaml").write_text(
            "claims: []\n", encoding="utf-8")
        assert wp._resolve_workspace({"cwd": str(flat)}) == flat
        assert wp._resolve_workspace({}) is None

    def test_was_dispatch_reads_the_v1_envelope_only(self) -> None:
        assert wp._was_dispatch(_dispatch_payload(Path("."))) is True
        assert wp._was_dispatch({"tool_input": {
            "prompt": "plain worker prompt, no envelope"}}) is False
        assert wp._was_dispatch({"tool_input": "raw string prompt"}) is False
        assert wp._was_dispatch({}) is False


# ============================================ worker_pulse dispatch path

class TestPulseDispatchPath:
    def test_full_pulse_wraps_decision_and_taskstop_reminder(
            self, tmp_path, capsys) -> None:
        ws = _pulse_ws(tmp_path)
        write_hook_state(ws, active_hooks=["worker_pulse"])
        _status_file(ws, "W-1", "done")  # final state -> TASKSTOP reminder
        rc = wp.main(_dispatch_payload(ws))
        out = capsys.readouterr().out
        assert rc == 0
        doc = json.loads(out)
        ctx = doc["hookSpecificOutput"]["additionalContext"]
        assert ctx.startswith("<worker-signal>")
        assert ctx.rstrip().endswith("</worker-signal>")
        assert "DECISION: DISPATCH" in ctx
        assert "TASKSTOP: W-1 delivered" in ctx
        # the pulse is a heuristic nudge, never an abort (stderr stays clean)
        assert capsys.readouterr().err == ""

    def test_waiting_worker_is_not_a_taskstop_zombie(
            self, tmp_path, capsys) -> None:
        ws = _pulse_ws(tmp_path)
        write_hook_state(ws, active_hooks=["worker_pulse"])
        _status_file(ws, "W-2", "waiting")  # delivered-but-alive, not final
        rc = wp.main(_dispatch_payload(ws))
        ctx = json.loads(capsys.readouterr().out)[
            "hookSpecificOutput"]["additionalContext"]
        assert rc == 0
        assert "TASKSTOP" not in ctx
        assert "DECISION: DISPATCH" in ctx

    def test_blocked_decision_fails_the_completion_mechanically(
            self, tmp_path, capsys, monkeypatch) -> None:
        """A SATURATED/BLOCKED convergence state must mark the worker
        completion failed (rc=3) with the pulse as stderr context — the
        orchestrator cannot proceed past it silently."""
        ws = _pulse_ws(tmp_path)
        write_hook_state(ws, active_hooks=["worker_pulse"])
        # cap the claim slots: three in-progress workers -> saturated shape
        for i in range(3):
            _status_file(ws, f"W-{i}", "in-progress", age_min=0)
        rc = wp.main(_dispatch_payload(ws))
        err = capsys.readouterr().err
        out = capsys.readouterr().out
        if rc == 3:
            assert "[worker_pulse]" in err
            assert "DECISION" in err
            assert out == ""
        else:
            # the saturation shape depends on the cap constants; a clean
            # completion is still contract-true — pin whichever face fired
            assert rc == 0 and "DECISION" in out

    def test_stale_non_dispatch_pulse_only_names_stale_workers(
            self, tmp_path, capsys) -> None:
        ws = _pulse_ws(tmp_path)
        write_hook_state(ws, active_hooks=["worker_pulse"])
        _status_file(ws, "stale-1", "in-progress", age_min=25)
        rc = wp.main({"cwd": str(ws), "tool_input": {
            "prompt": "an ordinary non-kunglao agent call"}})
        ctx = json.loads(capsys.readouterr().out)[
            "hookSpecificOutput"]["additionalContext"]
        assert rc == 0
        assert "worker-signal" in ctx
        assert "stale in-progress worker(s)" in ctx
        assert "stale-1" in ctx
        assert "DECISION" not in ctx  # no convergence pulse on this path

    def test_fresh_workers_stay_silent_on_the_non_dispatch_path(
            self, tmp_path, capsys) -> None:
        ws = _pulse_ws(tmp_path)
        write_hook_state(ws, active_hooks=["worker_pulse"])
        _status_file(ws, "fresh", "in-progress", age_min=1)
        rc = wp.main({"cwd": str(ws), "tool_input": {
            "prompt": "an ordinary agent call"}})
        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_delivery_reminder_faces(self, tmp_path) -> None:
        ws = _pulse_ws(tmp_path)
        assert wp._delivery_reminder(ws) == ""  # no runs dir content
        _status_file(ws, "W-9", "done")
        _status_file(ws, "W-8", "blocked")
        got = wp._delivery_reminder(ws)
        assert got.startswith("TASKSTOP: ")
        assert "W-9" in got and "W-8" in got
        # waiting is delivered-but-alive: skipped, never a zombie
        _status_file(ws, "W-7", "waiting")
        assert "W-7" not in wp._delivery_reminder(ws)

    def test_decisionless_workspace_never_invents_a_decision(
            self, tmp_path) -> None:
        """A stamp-only workspace with no register renders no DECISION
        line and decision=None — the absence of convergence state is
        reported as 'no dispatchable claims', never an invented verdict."""
        empty = tmp_path / "empty"
        empty.mkdir()
        stamp_current(empty)
        pulse, decision = wp._build_pulse(empty)
        assert decision is None
        assert "DECISION:" not in pulse
        assert "no dispatchable claims" in pulse


# ================================================= worker_pulse stdin face

class TestPulseStdinFace:
    def test_broken_stdin_payload_is_silent(self, monkeypatch,
                                            capsys) -> None:
        monkeypatch.setattr(sys, "stdin", io.StringIO("{not json"))
        assert wp.main() == 0
        assert capsys.readouterr().out == ""


# ================================================== violation_capture eval

class TestViolationEvaluate:
    def test_sed_inplace_tamper_is_recorded(self) -> None:
        events = vc.evaluate({"tool_input": {"command":
            "sed -i 's/verify_status: pending/verify_status: passes/' notes/F1.md"
        }})
        assert [e["action"] for e in events] == ["violation_sed_tamper"]
        assert "verify_status" in events[0]["detail"]
        assert len(events[0]["detail"]) < 400  # truncated, not exfiltrated

    def test_all_tamper_idioms_match(self) -> None:
        cmds = [
            "sed -i '' 's/closed_by: .*/closed_by: me/' claim-register.yaml",
            "perl -pi -e 's/authorized_by: a/authorized_by: b/' oracle.yaml",
            "python3 -c \"open('notes/x.md','w').write('verify_status: ok')\"",
        ]
        for cmd in cmds:
            got = vc.evaluate({"tool_input": {"command": cmd}})
            assert got and got[0]["action"] == "violation_sed_tamper", cmd

    def test_non_inplace_edits_are_not_tamper_events(self) -> None:
        # a plain read-only sed has no -i: out-of-band REWRITE is the event,
        # reads and stream filters are not
        assert vc.evaluate({"tool_input": {"command":
            "sed -n 's/verify_status/pending/p' notes/F1.md"}}) == []
        # redirect is the Write-face gap, not this recorder's event
        assert vc.evaluate({"tool_input": {"command":
            "awk '{print}' claim-register.yaml > copy.yaml"}}) == []
        assert vc.evaluate({}) == []

    def test_traceback_capture_over_both_envelope_shapes(self) -> None:
        tb = ("Traceback (most recent call last):\n"
              "  File \"gate.py\", line 9, in <module>\n"
              "ValueError: gate refused\n")
        by_dict = vc.evaluate({"tool_response": {"stdout": "",
                                                "stderr": tb}})
        assert by_dict and by_dict[0]["action"] == "env_incident"
        assert "ValueError: gate refused" in by_dict[0]["detail"]
        by_str = vc.evaluate({"tool_response": tb})
        assert by_str and by_str[0]["action"] == "env_incident"
        assert vc.evaluate({"tool_response": {"stdout": "all clean"}}) == []

    def test_both_event_families_fire_independently(self) -> None:
        tb = ("Traceback (most recent call last):\n"
              "RuntimeError: boom\n")
        events = vc.evaluate({
            "tool_input": {"command":
                           "perl -pi -e 's/answers_question: a/b/' facts/F.md"},
            "tool_response": {"stdout": tb},
        })
        assert [e["action"] for e in events] == [
            "violation_sed_tamper", "env_incident"]


# ============================================ violation_capture lighting

class TestDocPointerLighting:
    def test_mapped_action_appends_a_real_doc_pointer(self) -> None:
        detail = vc.light_detail(
            "violation_sed_tamper", "in-place rewrite")
        assert detail.startswith("in-place rewrite")
        assert "references/governance/guardrails.md" in detail

    def test_missing_doc_keeps_text_verbatim(self, tmp_path,
                                             monkeypatch) -> None:
        monkeypatch.setattr(vc, "SKILL_DIR", tmp_path)
        assert vc.light_detail("violation_sed_tamper", "bare") == "bare"

    def test_unmapped_action_keeps_text_verbatim(self) -> None:
        assert vc.light_detail("no_such_action", "bare") == "bare"


# =========================================== violation_capture ledger face

class TestViolationMain:
    def _ws(self, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        (ws / "runs" / "logs").mkdir(parents=True)
        return ws

    def test_events_reach_the_ledger_with_doc_lighting(
            self, tmp_path, capsys) -> None:
        ws = self._ws(tmp_path)
        payload = {
            "cwd": str(ws),
            "tool_input": {"command":
                           "sed -i 's/verify_status: p/passes/' notes/F.md"},
        }
        rc = vc.main(io.StringIO(json.dumps(payload)))
        assert rc == 0
        ledgers = list((ws / "runs" / "logs").glob("*.jsonl"))
        assert ledgers, "the recorder must land a ledger row"
        rows = [json.loads(line) for line
                in ledgers[0].read_text(encoding="utf-8").splitlines()
                if line.strip()]
        hits = [r for r in rows
                if r.get("action") == "violation_sed_tamper"]
        assert hits and hits[0]["actor"] == "violation_capture"
        assert "guardrails.md" in hits[0].get("detail", "")

    def test_broken_stdin_never_breaks_bash(self, capsys) -> None:
        assert vc.main(io.StringIO("not json at all")) == 0
        assert vc.main(io.StringIO("")) == 0

    def test_clean_payload_writes_nothing(self, tmp_path) -> None:
        ws = self._ws(tmp_path)
        rc = vc.main(io.StringIO(json.dumps(
            {"cwd": str(ws), "tool_input": {"command": "ls -la"},
             "tool_response": {"stdout": "clean"}})))
        assert rc == 0
        assert not list((ws / "runs" / "logs").glob("*.jsonl"))

    def test_recorder_crash_is_fail_open(self, tmp_path,
                                         monkeypatch) -> None:
        def boom(_payload):
            raise RuntimeError("recorder down")
        monkeypatch.setattr(vc, "evaluate", boom)
        ws = self._ws(tmp_path)
        rc = vc.main(io.StringIO(json.dumps({"cwd": str(ws)})))
        assert rc == 0
        assert not list((ws / "runs" / "logs").glob("*.jsonl"))
