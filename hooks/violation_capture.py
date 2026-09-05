#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""violation_capture.py — PostToolUse/Bash mechanical violation capture (#718).

WHY: the sample-incident-01 0.1.2 incident's most dangerous events left ZERO trace.
The orchestrator tampered a note with
    sed -i 's/verify_status: pending-verifier/verify_status: passes/'
bypassing write_guard entirely (write_guard guards the Edit/Write TOOL face;
a shell redirect never touches it), and gate scripts crashed with Tracebacks
that nobody recorded. The 45-min closeout window produced NO telemetry at
all (runs/logs carried 3 action words for the whole day: dispatch/write_
blocked/converge). Self-reported .violation-log.md entries are prose — the
five real entries were honest, but nothing MECHANICAL exists, and the whole
file is writable by the same actor it reports on.

This hook is the mechanical floor (#718 P2): it fires on every Bash tool
completion and captures two event families WITHOUT trusting anyone's memory:

  1. SED-TAMPER — the Bash command matches an in-place rewrite of a
     contract-carrier field (sed/perl/python -c writing verify_status,
     answers_question, closed_by, authorized_by, or the ledger/oracle
     files). Emits action `violation_sed_tamper` (WARN posture: exit 0 —
     the write itself is NOT blocked here; the RECORD is the deliverable,
     and the verify-status watch in heartbeat_tick reconciles it against
     the disk).
  2. TRACEBACK — the tool output contains a Python Traceback. Emits
     action `env_incident` with the first exception line. Gate-script
     crashes swallowed by FAIL_OPEN become visible the moment they happen,
     not never.

Posture — FAIL_OPEN, always exit 0, never additionalContext noise: this is
a RECORDER, not a gate. A recorder that blocks is a gate with none of the
adjudication write_guard does; a recorder that crashes must not take the
Bash call down with it.

#24 doc-pointer lighting: each captured event's detail names the
references/ doc that documents the protected pattern (lighting, not
gating — the R4 postmortem showed 4x blind retries where one doc read
would do). No fake pointers: unmapped actions and pointers whose target
is missing from disk keep the text verbatim (tests/
test_doc_pointer_lighting_24.py pins the map honest).

Vocabulary: emits ONLY registered event_taxonomy.EMIT_ACTIONS words
(violation_sed_tamper, env_incident — registered by this same change).

Wiring (register_hooks / hook_activation --wire-up, PostToolUse/Bash):
    matcher "Bash" -> this file, alongside heartbeat_touch (PreToolUse).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from _path_hygiene import scripts_on_path  # #671 sys.path hygiene authority

SKILL_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = SKILL_DIR / "scripts"

# The tamper surface: fields whose VALUE decides gating outcomes. The sed in
# the incident rewrote verify_status; the same class covers the note-answer
# binding and the ledger close fields. Match on the FIELD NAME, not the
# direction of the edit — a sed that *reverts* a tamper is still an
# out-of-band carrier write and must be recorded.
TAMPER_FIELD_RE = re.compile(
    r"verify_status|answers_question|closed_by|authorized_by|"
    r"claim-register\.yaml|task-oracle\.yaml"
)
# In-place rewrite idioms (r1-718 review H2 — all three verified by test):
#   sed -i / sed -i '' / sed --in-place
#   perl -pi -e / perl -pe '>file' is NOT in-place (redirect is a Write face
#     gap, recorded only if the tool_response traceback path fires)
#   python -c 'open(f,"w").write(...)' — no flag idiom; matched by the
#     open-for-write pattern instead
#   awk ... > file is a redirect, not in-place — excluded
INPLACE_SED_PERL_RE = re.compile(
    r"\b(?:sed|perl)\b[^|;&]*"
    r"(?:-{1,2}i(?:nplace)?(?:\s+['\"]?\S*['\"]?)?|-p[iI]\b)"
)
PYTHON_WRITE_RE = re.compile(
    r"python3?\s+-c\b.*open\([^)]*,\s*['\"]w"
)

TRACEBACK_RE = re.compile(
    r"Traceback \(most recent call last\):[\s\S]*?^(\w[\w.]*(?::\s*.*)?)$",
    re.MULTILINE,
)

# #24 doc-pointer lighting — pattern → authoritative doc, each verified to
# exist and cover the pattern:
#   violation_sed_tamper -> guardrails.md §1b ("Only an independent verifier
#     subagent writes verify_status"; verdict lines are forbidden output)
#   env_incident -> error-response-taxonomy.md (mandatory stop / retry-once /
#     ask / escalate classification for action errors)
DOC_POINTERS = {
    "violation_sed_tamper": "references/guardrails.md",
    "env_incident": "references/error-response-taxonomy.md",
}
DOC_POINTER_SUFFIX = (" — this pattern is documented: {ptr}"
                      " — read before retrying")


def light_detail(action: str, detail: str) -> str:
    """Append the verified doc pointer to a warning's text (#24 lighting).

    An unmapped action or a doc missing from disk keeps the text verbatim —
    no fake pointers. Never raises: the recorder's fail-open posture holds.
    """
    ptr = DOC_POINTERS.get(action)
    if not ptr:
        return detail
    try:
        if not (SKILL_DIR / ptr).is_file():
            return detail
    except OSError:
        return detail
    return detail + DOC_POINTER_SUFFIX.format(ptr=ptr)


def _output_text(payload: dict) -> str:
    """Tool output envelope: Claude Code PostToolUse carries tool_response
    (a dict with stdout/stderr or a string); both shapes tolerated."""
    tr = payload.get("tool_response")
    if isinstance(tr, str):
        return tr
    if isinstance(tr, dict):
        parts = []
        for key in ("stdout", "stderr", "output", "content"):
            v = tr.get(key)
            if isinstance(v, str):
                parts.append(v)
        return "\n".join(parts)
    return ""


def evaluate(payload: dict) -> list[dict]:
    """[(action, detail)] — pure; the caller owns emission + fail-open."""
    events: list[dict] = []
    cmd = str((payload.get("tool_input") or {}).get("command") or "")
    if cmd and TAMPER_FIELD_RE.search(cmd) and (
            INPLACE_SED_PERL_RE.search(cmd) or PYTHON_WRITE_RE.search(cmd)):
        # first 200 chars: enough to identify, never enough to exfiltrate a
        # carrier body through the event stream
        events.append({
            "action": "violation_sed_tamper",
            "detail": "in-place rewrite of a contract-carrier field "
                      f"outside the Write/Edit face: {cmd[:200]}",
        })
    out = _output_text(payload)
    if out:
        m = TRACEBACK_RE.search(out)
        if m:
            events.append({
                "action": "env_incident",
                "detail": f"python traceback in Bash output: "
                          f"{m.group(1)[:200]}",
            })
    return events


def main(stdin_stream=None) -> int:
    stream = sys.stdin if stdin_stream is None else stdin_stream
    try:
        payload = json.loads(stream.read() or "{}")
    except json.JSONDecodeError:
        return 0  # fail-open: a broken payload must never break Bash
    try:
        events = evaluate(payload)
    except Exception:  # noqa: BLE001 — recorder, never a blocker
        return 0
    if not events:
        return 0
    cwd = payload.get("cwd") or str(Path.cwd())
    try:
        with scripts_on_path():
            import kunglao_log  # noqa: E402
        ws = None
        for base in (Path(cwd), Path(cwd).parent):
            if (base / "runs").is_dir():
                ws = base
                break
        if ws is not None:
            for ev in events:
                kunglao_log.emit(ws, actor="violation_capture",
                                 action=ev["action"],
                                 detail=light_detail(ev["action"],
                                                     ev["detail"]))
    except Exception:  # noqa: BLE001 — recording must never break Bash
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
