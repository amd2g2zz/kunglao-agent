# -*- coding: utf-8 -*-
"""#718 regression: the five traceless events of the sample-incident-01 0.1.2
closeout, replayed as fixtures. Each event left ZERO mechanical trace in
the incident; after #718 each lands in runs/logs/ or the tick report.

  1. sed tamper      `sed -i 's/verify_status: pending-verifier/
                      verify_status: passes/'` — bypassed write_guard (Bash
                      face), zero trace  → violation_capture hook + watch
  2. traceback       gate script crash swallowed by FAIL_OPEN          →
                      violation_capture env_incident
  3. out-of-band     ANY unwitnessed disk transition of a verify stamp
     stamp flip      (not just sed — heredoc, editor, python -c)       →
                      verify_status_watch reconcile flags unwitnessed
  4. silent vocab    closeout window produced no events at all         →
                      vocabulary words registered + wired
  5. self-report     .violation-log.md prose as the only record        →
                      mechanical record is now the floor, prose is bonus
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).parent
SCRIPTS = _HERE.parent / "scripts"
HOOKS = _HERE.parent / "hooks"
sys.path.insert(0, str(SCRIPTS))

# The incident sed, verbatim shape.
INCIDENT_SED = ("sed -i "
                "'s/verify_status: pending-verifier/verify_status: passes/' "
                "notes/N-101-q2-answer.md")

TRACEBACK_OUTPUT = (
    "running selfcheck...\n"
    "Traceback (most recent call last):\n"
    '  File "scripts/hooks_selfcheck.py", line 88, in main\n'
    "    raise HookWiringSelfcheckError(detail)\n"
    "HookWiringSelfcheckError: 2 mismatch(es)\n"
)


def _load_hook():
    import importlib.util
    name = "violation_capture_hook_718"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, HOOKS / "violation_capture.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _ws(tmp: Path) -> Path:
    (tmp / "runs" / "logs").mkdir(parents=True)
    return tmp


def _events(ws: Path) -> list[dict]:
    rows = []
    for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# 1+2: the capture hook — sed tamper + traceback, recorded mechanically
# ---------------------------------------------------------------------------

def test_incident_sed_is_captured(tmp_path):
    """The EXACT sed from the incident must produce one violation_sed_tamper
    event with the command prefix recorded."""
    hook = _load_hook()
    ws = _ws(tmp_path)
    payload = json.dumps({"cwd": str(ws), "tool_input": {"command": INCIDENT_SED},
                          "tool_response": {"stdout": "", "stderr": ""}})
    rc = hook.main(io.StringIO(payload))
    assert rc == 0, "recorder must never block (WARN posture)"
    rows = _events(ws)
    tamper = [r for r in rows if r["action"] == "violation_sed_tamper"]
    assert tamper, "the incident sed must be recorded"
    assert "verify_status" in tamper[0]["detail"]


def test_traceback_is_captured_as_env_incident(tmp_path):
    hook = _load_hook()
    ws = _ws(tmp_path)
    payload = json.dumps({"cwd": str(ws),
                          "tool_input": {"command": "python scripts/hooks_selfcheck.py ws"},
                          "tool_response": {"stdout": TRACEBACK_OUTPUT, "stderr": ""}})
    rc = hook.main(io.StringIO(payload))
    assert rc == 0
    rows = _events(ws)
    inc = [r for r in rows if r["action"] == "env_incident"]
    assert inc and "HookWiringSelfcheckError" in inc[0]["detail"]


def test_benign_bash_records_nothing(tmp_path):
    hook = _load_hook()
    ws = _ws(tmp_path)
    payload = json.dumps({"cwd": str(ws),
                          "tool_input": {"command": "grep -r verify_status notes/"},
                          "tool_response": {"stdout": "ok", "stderr": ""}})
    assert hook.main(io.StringIO(payload)) == 0
    # grep MENTIONS the field but is not an in-place rewrite; no traceback
    assert _events(ws) == [], "read-only mention of the field must not fire"


def test_perl_and_python_rewrite_idioms_captured(tmp_path):
    """r1-718 review H2: perl -pi -e and python -c open(...,'w') rewrites of
    carrier fields are the SAME tamper class as the incident sed — the first
    INPLACE_RE missed both. All three idioms must fire."""
    hook = _load_hook()
    cases = [
        "perl -pi -e 's/verify_status: pending/verify_status: passes/' notes/N-1.md",
        ("python -c \"import re; t=open('notes/N-1.md').read(); "
         "open('notes/N-1.md','w').write(t.replace('verify_status: pending',"
         "'verify_status: passes'))\""),
        "sed -i '' 's/answers_question: q1/answers_question: q2/' notes/N-2.md",
    ]
    for cmd in cases:
        ws = _ws(tmp_path / f"case{hash(cmd) % 9999}")
        payload = json.dumps({"cwd": str(ws),
                              "tool_input": {"command": cmd},
                              "tool_response": {"stdout": "", "stderr": ""}})
        assert hook.main(io.StringIO(payload)) == 0
        tamper = [r for r in _events(ws)
                  if r["action"] == "violation_sed_tamper"]
        assert tamper, f"tamper idiom must fire: {cmd}"


def test_benign_noncarrier_rewrite_silent(tmp_path):
    """sed on a non-carrier file (no carrier field name) stays silent."""
    hook = _load_hook()
    ws = _ws(tmp_path)
    payload = json.dumps({"cwd": str(ws),
                          "tool_input": {"command": "sed -i 's/foo/bar/' README.md"},
                          "tool_response": {"stdout": "", "stderr": ""}})
    assert hook.main(io.StringIO(payload)) == 0
    assert _events(ws) == []


def test_no_workspace_still_exit_zero(tmp_path):
    """Fail-open: a non-kunglao cwd records nothing and never fails."""
    hook = _load_hook()
    payload = json.dumps({"cwd": str(tmp_path / "not-a-ws"),
                          "tool_input": {"command": INCIDENT_SED},
                          "tool_response": {"stdout": "", "stderr": ""}})
    assert hook.main(io.StringIO(payload)) == 0


def test_vocabulary_words_registered():
    """The hook's action words must be in EMIT_ACTIONS (CI anchor would also
    catch this, but the regression pins it directly)."""
    import event_taxonomy as et
    for word in ("violation_sed_tamper", "env_incident",
                 "verify_status_change"):
        assert word in et.EMIT_ACTIONS, word


def test_hook_registered_by_wire_up():
    """register_hooks must carry the PostToolUse/Bash entry, and the file
    must be in WIRE_UP_HOOK_FILES (selfcheck parity)."""
    import wire_up_settings
    assert "violation_capture.py" in wire_up_settings.WIRE_UP_HOOK_FILES
    import hook_activation as ha
    src = (Path(ha.__file__).parent / "hook_activation.py").read_text(
        encoding="utf-8")
    assert '_ensure(post, "Bash", "violation_capture.py")' in src


# ---------------------------------------------------------------------------
# 3: the watch — out-of-band stamp flip flagged UNWITNESSED
# ---------------------------------------------------------------------------

def _note(ws: Path, name: str, status: str) -> None:
    (ws / "notes").mkdir(exist_ok=True)
    (ws / "notes" / name).write_text(
        f"---\nid: N-1\nclaim_id: C-1\nverify_status: {status}\n"
        f"type: answer-note\n---\n\nbody\n", encoding="utf-8")


def test_first_pass_is_baseline_no_events(tmp_path):
    import verify_status_watch as vsw
    ws = _ws(tmp_path)
    _note(ws, "N-1.md", "pending-verifier")
    report = vsw.reconcile(ws)
    assert report["notes_scanned"] == 1
    assert report["changes"] == [], "baseline pass must not emit changes"
    assert _events(ws) == []


def test_outofband_flip_flagged_unwitnessed(tmp_path):
    """The incident shape: between two reconciles, the stamp flips on disk
    with NO mechanical event naming the note → unwitnessed: true."""
    import verify_status_watch as vsw
    ws = _ws(tmp_path)
    _note(ws, "N-101-q2-answer.md", "pending-verifier")
    vsw.reconcile(ws)                       # baseline
    _note(ws, "N-101-q2-answer.md", "passes")   # the sed out-of-band
    report = vsw.reconcile(ws)
    assert len(report["changes"]) == 1
    c = report["changes"][0]
    assert c["from"] == "pending-verifier" and c["to"] == "passes"
    assert c["unwitnessed"] is True
    rows = _events(ws)
    ev = [r for r in rows if r["action"] == "verify_status_change"]
    assert ev and "UNWITNESSED" in ev[0]["detail"]


def test_witnessed_flip_not_flagged(tmp_path):
    """A flip WITH a matching verify event in the stream is witnessed —
    the normal kunglao_verify flow must not raise tamper noise. r1-718 H1:
    the REAL emitter shape is claim=<C-id> + artifact=<F-id> (fact id, NOT
    a note path) — the join must run through the note's claim_id."""
    import verify_status_watch as vsw
    import kunglao_log
    ws = _ws(tmp_path)
    _note(ws, "N-2.md", "pending-verifier")
    vsw.reconcile(ws)
    # the REAL kunglao_verify emit shape (scripts/kunglao_verify.py:896)
    kunglao_log.emit(ws, actor="orchestrator", action="verify",
                     claim="C-1", artifact="F-101", exit=0,
                     detail="L1=pass L2=pass overall=VERIFIED")
    _note(ws, "N-2.md", "passes")
    report = vsw.reconcile(ws)
    assert report["changes"] and report["changes"][0]["unwitnessed"] is False, (
        "a legit verify (claim join) must count as witness")


def test_watch_self_event_never_witnesses(tmp_path):
    """r1-718 H1 anti-laundering: the watch's OWN verify_status_change
    event must not witness a SECOND flip — else a repeat tamper passes."""
    import verify_status_watch as vsw
    ws = _ws(tmp_path)
    _note(ws, "N-5.md", "pending-verifier")
    vsw.reconcile(ws)                    # baseline
    _note(ws, "N-5.md", "passes")        # first tamper → event (unwitnessed)
    vsw.reconcile(ws)
    _note(ws, "N-5.md", "fails")         # second tamper, only self-events
    report = vsw.reconcile(ws)           #   in the stream since
    assert report["changes"], "second flip must surface"
    assert report["changes"][0]["unwitnessed"] is True, (
        "the watch's own prior event must not launder a repeat tamper")


def test_stable_stamp_no_change(tmp_path):
    import verify_status_watch as vsw
    ws = _ws(tmp_path)
    _note(ws, "N-3.md", "passes")
    vsw.reconcile(ws)
    assert vsw.reconcile(ws)["changes"] == []


# ---------------------------------------------------------------------------
# 4: tick wiring — the watch has a mechanical caller
# ---------------------------------------------------------------------------

def test_tick_report_carries_verify_watch(tmp_path, monkeypatch):
    import heartbeat_tick
    ws = _ws(tmp_path)
    _note(ws, "N-4.md", "passes")
    calls = {}

    def fake_run(script: str, ws_, *extra):
        calls[script] = True
        return {"rc": 0, "stdout": "{}", "stderr": ""}

    monkeypatch.setattr(heartbeat_tick, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["heartbeat_tick.py", str(ws)])
    rc = heartbeat_tick.main()
    assert rc == 0
    assert "verify_status_watch.py" in calls, (
        "the tick must invoke the watch — its only mechanical caller")
    report = json.loads((ws / "runs" / ".heartbeat-tick.json").read_text(
        encoding="utf-8"))
    assert "verify_watch" in report
