#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rt_read_barrier.py — #652 5-F2: red-team blindness, MECHANICALLY enforced.

RED: agents/kunglao-redteam.md allowedTools is (Read, Glob, Grep, Bash, …)
and the act rides DEFAULT_RACK (scripts/e2e/llm_faces.py) because the RT
dispatch declares no tools= — nothing denied facts/F<NNN>*.md, notes/,
runs/verification-<claim>.md or runs/worker-status-*.md. Blindness was
prompt-enforced and self-reported; facts/_INDEX.md was explicitly allowed
and names the exact target fact ids — one Read call from the forbidden
conclusion. A contaminated CONFIRMED then feeds the promotion gate as
"independent" evidence.

THE BARRIER (two faces, one file — the orchestrator_tool_guard pattern):

  Face A — PreToolUse(Read|Glob|Grep|Bash) + Agent: when the call comes
  from a RED-TEAM act, the maker faces are denied with rc=2 + repair
  guidance. Identity is MECHANICAL — Claude Code puts `agent_type` (and
  `agent_id`) into the hook payload of every subagent tool call (verified
  live on 2.1.270), so a dispatch via the Agent tool is identified without
  any self-report. Denied for RT acts:
    - facts/           (every fact file, _INDEX.md included — it names ids)
    - notes/           (results layer)
    - runs/verification-*.md   (verifier records — the maker face)
    - runs/worker-status-*.md  (worker self-reports)
    - runs/*-verify-note.md    (the gate-conformant mirror of the above)
    - evidence/verdict.json    (the verdict-scorer's conclusion)
    - Agent/Task       (re-delegating the read to a helper subagent would
                        launder it through a different agent identity)
  Allowed and untouched: evidence/** (the RT act's working face), bins/,
  task_spec.yaml, claim-register.yaml, and the RT act's own artifact.

  Face B — UserPromptSubmit: the e2e RT act runs as the TOP-LEVEL agent of
  its own `claude -p` session (no agent_type), so its dispatch prompt IS
  the identity: a prompt carrying the v1 dispatch envelope with an
  RT-class `agent` arms that session (runs/.rt-blind-arm.json, keyed by
  session_id, TTL-bounded). The armed session's tool calls then ride the
  same deny list. Arming only ever RESTRICTS the arming session. When
  agent_type is present it is authoritative — a worker subagent inside an
  armed session keeps its own identity.

POSTURE: rc=2 REJECT + repair path (the #57 gate posture — a de-blinded
verifier feeds the promotion gate, which is framework-layer). Fail-open on
unreadable payloads; every REJECT leaves a durable runs/logs row
(action=rt_read_blocked). Bash matching is a path-token heuristic (documented
residual: a determined act could encode paths programmatically).
"""
from __future__ import annotations

# The canonical warn — ONE implementation (process-wide dedupe + ledger).
try:
    from _path_hygiene import ensure_scripts_path as _esp406
    _esp406()
    from kunglao_log import warn
except Exception:  # noqa: BLE001 — fail-open lifeline, never block the hook
    def warn(op: str, reason: str) -> None:
        print(f"[kunglao-agent] WARN (fail-open): {op}: {reason}",
              file=sys.stderr)
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _path_hygiene import load_hooks_lib, scripts_on_path  # #671 / #863

#: the red-team agent family — substring-matched against agent_type /
#: dispatch meta.agent (mirrors blind_gate.VERIFIER_AGENT_MARKERS'
#: redteam member across plugin-namespaced and bare agent ids).
REDTEAM_AGENT_MARKERS = ("kunglao-redteam", "redteam", "red-team", "red_team")

#: armed-session store (machine channel: runs/).
ARM_FILE_REL = ("runs", ".rt-blind-arm.json")
#: an armed session expires with the longest act budget class (Luby 2*1800s)
#: plus slack — never a permanent lock.
ARM_TTL_MINUTES = 240

#: search-root dirs an RT act may not sweep (content search == read)
_DENY_SEARCH_ROOTS = ("facts", "notes", "runs")

#: runs/ basenames that are maker faces
_RUNS_DENY_PREFIXES = ("verification-", "worker-status-")
_RUNS_DENY_SUFFIXES = ("-verify-note.md",)

#: single-file denials that live outside the deny dirs
_DENY_FILES = {
    "evidence/verdict.json": "the verdict-scorer's conclusion",
}
_FACT_INDEX = "facts/_INDEX.md"

#: Bash token heuristics (path-shaped; see the docstring's residual note)
_BASH_DIR_RES = (
    re.compile(r"(?<![\w-])facts(?=[/\s'\");:|&]|$)"),
    re.compile(r"(?<![\w-])notes(?=[/\s'\");:|&]|$)"),
)
_BASH_SUBSTRINGS = ("verification-", "worker-status-", "-verify-note",
                    "evidence/verdict.json")
#: Bash string variants needed for the token scan (normalized)
_BASH_TOOL = "Bash"
_READ_TOOL = "Read"
_SEARCH_TOOLS = ("Glob", "Grep")
_DISPATCH_TOOLS = ("Agent", "Task")

_CTX_TEMPLATE = (
    "[kunglao #652 red-team barrier] {face} is a MAKER face — an RT act "
    "derives its answer independently from raw evidence, never by reading "
    "the conclusion (blindness is now mechanical, not prompt-enforced). "
    "Allowed working faces: evidence/** (excluding evidence/verdict.json), "
    "bins/, task_spec.yaml, claim-register.yaml, runs/verify-redteam-*.md. "
    "Repair: re-scope the read to evidence/ or to the raw target material. "
    "REJECTED — do not read {face}.")
_DISPATCH_CTX = (
    "[kunglao #652 red-team barrier] an RT act may not dispatch helper "
    "subagents — a differently-identified helper would launder the maker "
    "faces past the barrier. Attack from raw evidence yourself. REJECTED.")


def resolve_workspace(payload: dict) -> Path | None:
    """Workspace markers (claim-register.yaml / .hook_state.json) under cwd
    or cwd/malware-analysis-workspace — the deployed convention."""
    cwd = Path(payload.get("cwd") or payload.get("workspace") or ".")
    for base in (cwd / "malware-analysis-workspace", cwd):
        if (base / "claim-register.yaml").exists() \
                or (base / ".hook_state.json").exists():
            return base
    return None


def _norm_rel(path) -> str:
    s = str(path or "").replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]
    return s.strip("/")


def _face_of(rel: str) -> str | None:
    """The maker-face description for a ws-relative path, else None."""
    rel = _norm_rel(rel)
    if not rel:
        return None
    if rel == _FACT_INDEX:
        return "facts/_INDEX.md (names the exact fact ids/titles)"
    if rel in _DENY_FILES:
        return f"{rel} ({_DENY_FILES[rel]})"
    if rel.startswith("facts/"):
        return "facts/ (maker conclusions)"
    if rel.startswith("notes/"):
        return "notes/ (results layer)"
    if rel.startswith("runs/"):
        base = rel[len("runs/"):]
        if base.startswith(_RUNS_DENY_PREFIXES) \
                or base.endswith(_RUNS_DENY_SUFFIXES):
            return f"runs/{base}"
    return None


def _deny_search_root(rel: str) -> str | None:
    """A Glob/Grep search root the RT act may not sweep: the workspace root
    (unscoped == cwd == ws) or any dir that contains maker faces."""
    rel = _norm_rel(rel)
    if rel == "":
        return "the workspace root (unscoped search sweeps the maker faces)"
    for d in _DENY_SEARCH_ROOTS:
        if rel == d or rel.startswith(d + "/"):
            return f"{d}/ (content search reaches maker faces)"
    face = _face_of(rel)
    return face


def _deny_pattern(pat: str) -> str | None:
    """A Glob/Grep pattern that itself names a maker face."""
    p = str(pat or "").replace("\\", "/").lower()
    if not p:
        return None
    if ".." in p:
        return "a '../' pattern (escapes the scoped root)"
    if re.search(r"(?<![\w-])facts(?=[/]|$)", p) or "facts/" in p:
        return "a pattern naming facts/"
    if re.search(r"(?<![\w-])notes(?=[/]|$)", p) or "notes/" in p:
        return "a pattern naming notes/"
    for token in ("verification-", "worker-status-", "-verify-note"):
        if token in p:
            return f"a pattern naming {token}*"
    if "verdict.json" in p:
        return "a pattern naming evidence/verdict.json"
    return None


def _rel_of(target, ws: Path, cwd: str) -> str | None:
    """ws-relative posix path of an absolute-or-cwd-relative tool target."""
    if not str(target or "").strip():
        return None
    t = Path(str(target))
    base = t if t.is_absolute() else (Path(cwd or ".") / t)
    try:
        return base.resolve().relative_to(ws.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def _deny_for_tool(tool: str, tool_input: dict, ws: Path, cwd: str) -> str | None:
    """The maker-face description this call would read, else None."""
    if tool == _READ_TOOL:
        rel = _rel_of(tool_input.get("file_path"), ws, cwd)
        return _face_of(rel) if rel is not None else None
    if tool in _SEARCH_TOOLS:
        root = tool_input.get("path")
        if not str(root or "").strip():
            return _deny_search_root("")
        rel = _rel_of(root, ws, cwd)
        if rel is None:
            return None  # root outside the workspace — no maker face there
        return _deny_search_root(rel) or _deny_pattern(tool_input.get("pattern")) \
            or _deny_pattern(tool_input.get("glob"))
    if tool == _BASH_TOOL:
        cmd = str(tool_input.get("command") or "")
        if not cmd:
            return None
        for rx in _BASH_DIR_RES:
            m = rx.search(cmd)
            if m:
                return f"{m.group(0).strip()}/ (path token in the command)"
        for token in _BASH_SUBSTRINGS:
            if token.replace("\\", "/") in cmd.replace("\\", "/"):
                return f"{token} (path token in the command)"
        return None
    return None


# ---------- identity -------------------------------------------------------

def _matches_redteam(agent: str) -> bool:
    a = str(agent or "").lower()
    return any(m in a for m in REDTEAM_AGENT_MARKERS)


def _arm_path(ws: Path) -> Path:
    return ws.joinpath(*ARM_FILE_REL)


def _load_arms(ws: Path) -> dict:
    p = _arm_path(ws)
    if not p.is_file():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        sessions = doc.get("sessions")
        return dict(sessions) if isinstance(sessions, dict) else {}
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        warn("rt_read_barrier", f"arm store unreadable: {p}: {exc}")
        return {}


def _fresh_sessions(sessions: dict, now: datetime) -> dict:
    cutoff = now - timedelta(minutes=ARM_TTL_MINUTES)
    out = {}
    for sid, row in sessions.items():
        try:
            ts = datetime.fromisoformat(str((row or {}).get("ts", ""))
                                        .replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue  # unparsable arm = expired arm (fail toward expiry)
        if ts >= cutoff:
            out[sid] = row
    return out


def arm_session(ws: Path, session_id: str, *, claim: str = "",
                agent: str = "") -> None:
    now = datetime.now(timezone.utc)
    sessions = _fresh_sessions(_load_arms(ws), now)
    sessions[str(session_id)] = {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "claim": str(claim or ""), "agent": str(agent or "")}
    p = _arm_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 1, "sessions": sessions},
                            indent=2) + "\n", encoding="utf-8")


def is_redteam_call(payload: dict) -> bool:
    """Mechanical RT identity: the subagent `agent_type` when present
    (authoritative), else the UserPromptSubmit-armed session."""
    agent = str(payload.get("agent_type") or payload.get("agent_name") or "")
    if agent.strip():
        return _matches_redteam(agent)
    sid = str(payload.get("session_id") or "")
    if not sid:
        return False
    ws = resolve_workspace(payload)
    if ws is None:
        return False
    return sid in _fresh_sessions(_load_arms(ws),
                                  datetime.now(timezone.utc))


# ---------- faces ----------------------------------------------------------

def _emit(ws: Path | None, face: str, tool: str, detail: str) -> None:
    """Durable trail (fail-open — the REJECT never depends on logging)."""
    try:
        if ws:
            with scripts_on_path():  # #671 scoped membership
                import kunglao_log  # noqa: E402
                kunglao_log.emit(ws, "rt_barrier", "rt_read_blocked",
                                 tool=tool or None, detail=detail, exit=2,
                                 matched_rule=face)
    except Exception as exc:  # noqa: BLE001
        warn("_emit", f"{type(exc).__name__}: {exc}")


def evaluate(payload: dict) -> tuple[int, str, str | None]:
    """(rc, stderr, additionalContext). rc=2 REJECT + repair path when the
    caller is an RT act and the target is a maker face."""
    if not is_redteam_call(payload):
        return 0, "", None
    ws = resolve_workspace(payload)
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    cwd = str(payload.get("cwd") or (ws or "."))

    if tool in _DISPATCH_TOOLS:
        _emit(ws, "agent-dispatch", tool, "RT act attempted a helper dispatch")
        err = ("REJECT rt_read_barrier: an RT act may not dispatch helper "
               "subagents (#652 — identity laundering).")
        return 2, err, _DISPATCH_CTX

    if ws is None:
        return 0, "", None  # faces are workspace-relative; nothing to match
    face = _deny_for_tool(tool, tool_input, ws, cwd)
    if face is None:
        return 0, "", None
    _emit(ws, face, tool, f"RT act read attempt on {face}")
    err = (f"REJECT rt_read_barrier: {face} is a maker face — an RT act "
           f"derives its answer from raw evidence, never from the conclusion.")
    return 2, err, _CTX_TEMPLATE.format(face=face)


def main_face_user_prompt(payload: dict) -> int:
    """Face B: arm the session when its prompt IS an RT dispatch. Recorder
    only — never blocks a prompt (rc 0 always)."""
    try:
        prompt = str(payload.get("prompt") or "")
        sid = str(payload.get("session_id") or "")
        if not prompt or not sid:
            return 0
        ws = resolve_workspace(payload)
        if ws is None:
            return 0
        lib = load_hooks_lib()
        _tier, _tools, claim, meta = lib.parse_dispatch_json(prompt)
        agent = str((meta or {}).get("agent") or "")
        if _matches_redteam(agent):
            arm_session(ws, sid, claim=claim or "", agent=agent)
    except Exception as exc:  # noqa: BLE001 — recorder, never blocks
        warn("rt_read_barrier.arm", f"{type(exc).__name__}: {exc}")
    return 0


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0  # fail-open: a broken payload must never block tool calls
    if str(payload.get("hook_event_name") or "") == "UserPromptSubmit":
        return main_face_user_prompt(payload)
    rc, err, ctx = evaluate(payload)
    if err:
        print(err, file=sys.stderr)
    if rc == 2:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": ctx or ""}}))
        return rc
    return rc


if __name__ == "__main__":
    sys.exit(main())
