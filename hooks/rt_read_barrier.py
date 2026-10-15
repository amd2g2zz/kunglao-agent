#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rt_read_barrier.py — blind-act blindness (red-team + settler), MECHANICALLY enforced.

Two blind identity families ride ONE barrier — same deny faces, same
posture, mechanical identity in both (never prompt-enforced).

RED-TEAM acts (issue-652): agents/kunglao-redteam.md allowedTools is (Read, Glob, Grep, Bash, …)
and the act rides DEFAULT_RACK (scripts/e2e/llm_faces.py) because the RT
dispatch declares no tools= — nothing denied facts/F<NNN>*.md, notes/,
runs/verification-<claim>.md or runs/worker-status-*.md. Blindness was
prompt-enforced and self-reported; facts/_INDEX.md was explicitly allowed
and names the exact target fact ids — one Read call from the forbidden
conclusion. A contaminated CONFIRMED then feeds the promotion gate as
"independent" evidence.

SETTLEMENT acts (issue-687): the settler settles credit over the
producer's own output — a reward-hacking surface unless isolated. It
rides the same barrier PLUS the policy's learning faces (method-family
and q-cell logs): a grader that knows which arm produced a step can
shape credit per arm and corrupt the learning signal. The builder-side
twin (the input-doc contract) lives in scripts/rlvr/settlement_scorer.py;
this file is the ACT-side face.

THE BARRIER (two faces, one file — the orchestrator_tool_guard pattern):

  Face A — PreToolUse(Read|Glob|Grep|Bash) + Agent: when the call comes
  from a BLIND act (red-team or settler), the maker faces are denied
  with rc=2 + repair guidance. Identity is MECHANICAL — Claude Code puts
  `agent_type` (and `agent_id`) into the hook payload of every subagent
  tool call (verified live on 2.1.270), so a dispatch via the Agent tool
  is identified without any self-report. Denied for every blind act:
    - facts/           (every fact file, _INDEX.md included — it names ids)
    - notes/           (results layer)
    - runs/verification-*.md   (verifier records — the maker face)
    - runs/worker-status-*.md  (worker self-reports)
    - runs/*-verify-note.md    (the gate-conformant mirror of the above)
    - runs/method-family-log.jsonl + runs/q-cell-log.jsonl
                        (the policy learning faces — arm identity and
                        arm values; closed for EVERY blind act)
    - evidence/verdict.json    (the verdict-scorer's conclusion)
    - Agent/Task       (re-delegating the read to a helper subagent would
                        launder it through a different agent identity)
  Allowed and untouched: evidence/** (the blind act's working face), bins/,
  task_spec.yaml, claim-register.yaml, the blind act's own artifact, and
  the blind act's OWN liveness file runs/worker-status-<agent>-<id>.md
  (narrative-free by construction; every foreign worker-status token,
  case alias, and dot-dot path still denies). All path/token comparisons
  are case-FOLDED — the case-insensitive dev filesystem preserves the
  caller's case, so ``Notes/n.md`` must deny like ``notes/n.md``.

  Face B — UserPromptSubmit: an RT or settler act runs as the TOP-LEVEL
  agent of its own `claude -p` session (no agent_type), so its dispatch
  prompt IS the identity: a prompt carrying the v1 dispatch envelope with
  a blind-class `agent` (red-team or settler) arms that session
  (runs/.rt-blind-arm.json, keyed by session_id, TTL-bounded). The armed
  session's tool calls then ride the same deny list. Arming only ever
  RESTRICTS the arming session. When agent_type is present it is
  authoritative — a worker subagent inside an armed session keeps its
  own identity.

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

from _path_hygiene import load_hooks_lib, scripts_on_path  # sys.path hygiene authority

#: the red-team agent family — substring-matched against agent_type /
#: dispatch meta.agent (mirrors blind_gate.VERIFIER_AGENT_MARKERS'
#: redteam member across plugin-namespaced and bare agent ids).
REDTEAM_AGENT_MARKERS = ("kunglao-redteam", "redteam", "red-team", "red_team")

#: the settlement agent family (issue-687) — the blind settler rides the
#: same barrier. Deliberately NOT a blind_gate.VERIFIER_AGENT_MARKERS
#: member: those classify verifier-remediation dispatches (a different
#: contract), while this marker only ever RESTRICTS reads here.
SETTLER_AGENT_MARKERS = ("kunglao-settler", "settler")

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
#: runs/ basenames that are policy LEARNING faces (issue-687): arm
#: identity and arm values — closed for every blind act (a grader that
#: knows the arm can shape credit per arm)
_RUNS_DENY_FILES = ("method-family-log.jsonl", "q-cell-log.jsonl")

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
                    "evidence/verdict.json", "method-family-log",
                    "q-cell-log")
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
    "[kunglao issue-652 red-team barrier] an RT act may not dispatch helper "
    "subagents — a differently-identified helper would launder the maker "
    "faces past the barrier. Attack from raw evidence yourself. REJECTED.")
_SETTLER_CTX = (
    "[kunglao issue-687 blind-settlement barrier] {face} is a producer/"
    "learning face — the settler settles credit from the raw step artifacts "
    "(paths + hashes), the claim/question, and the rules table ONLY. Allowed "
    "working faces: evidence/** (excluding evidence/verdict.json), bins/, "
    "task_spec.yaml, claim-register.yaml, and your OWN status file "
    "runs/worker-status-kunglao-settler-<id>.md (write it with Write; "
    "reads of it are exempt). Repair: re-scope the read to the raw "
    "artifacts named in your input doc. REJECTED — do not read {face}.")
_SETTLER_DISPATCH_CTX = (
    "[kunglao issue-687 blind-settlement barrier] a settler act may not "
    "dispatch helper subagents — a differently-identified helper would "
    "launder the producer/learning faces past the barrier. Settle from the "
    "raw artifacts yourself. REJECTED.")


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


def _face_of(rel: str, *, own_agent: str = "") -> str | None:
    """The maker-face description for a ws-relative path, else None.

    Case-FOLDED comparison (the dev platform's case-insensitive FS
    preserves the caller's case through resolve() — ``Notes/n.md`` is
    ``notes/n.md`` on disk, so a case alias must land on the same
    denial). ``own_agent`` (bare agent name) exempts exactly one face:
    the blind act's OWN liveness file runs/worker-status-<own>-*.md —
    narrative-free by construction (the act itself is the only writer)."""
    rel = _norm_rel(rel)
    if not rel:
        return None
    low = rel.lower()
    if low == _FACT_INDEX:
        return "facts/_INDEX.md (names the exact fact ids/titles)"
    if low in _DENY_FILES:
        return f"{rel} ({_DENY_FILES[low]})"
    if low.startswith("facts/"):
        return "facts/ (maker conclusions)"
    if low.startswith("notes/"):
        return "notes/ (results layer)"
    if low.startswith("runs/"):
        base = low[len("runs/"):]
        if base.startswith(_RUNS_DENY_PREFIXES) \
                or base.endswith(_RUNS_DENY_SUFFIXES):
            if own_agent and base.startswith(f"worker-status-{own_agent}-"):
                return None  # the act's own status file, not a maker face
            return f"runs/{base}"
        if base in _RUNS_DENY_FILES:
            return f"runs/{base} (the policy learning face — arm " \
                   f"identity/values)"
    return None


def _deny_search_root(rel: str, *, own_agent: str = "") -> str | None:
    """A Glob/Grep search root the RT act may not sweep: the workspace root
    (unscoped == cwd == ws) or any dir that contains maker faces."""
    rel = _norm_rel(rel)
    if rel == "":
        return "the workspace root (unscoped search sweeps the maker faces)"
    low = rel.lower()
    for d in _DENY_SEARCH_ROOTS:
        if low == d or low.startswith(d + "/"):
            return f"{d}/ (content search reaches maker faces)"
    return _face_of(rel, own_agent=own_agent)


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
    for token in ("verification-", "worker-status-", "-verify-note",
                  "method-family-log", "q-cell-log"):
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


def _only_own_worker_status(cmd_low: str, own_agent: str) -> bool:
    """True when EVERY worker-status token in the (lowercased) command
    names the act's own liveness file — the one Bash carve-out: an act
    may append to its own status line via a path token that cannot name
    anyone else's narrative. One foreign token and the face denies."""
    if not own_agent:
        return False
    hits = re.findall(r"worker-status-[a-z0-9._-]*", cmd_low)
    return bool(hits) and all(
        h.startswith(f"worker-status-{own_agent}-") for h in hits)


def _deny_for_tool(tool: str, tool_input: dict, ws: Path, cwd: str,
                   *, own_agent: str = "") -> str | None:
    """The maker-face description this call would read, else None."""
    if tool == _READ_TOOL:
        rel = _rel_of(tool_input.get("file_path"), ws, cwd)
        return (_face_of(rel, own_agent=own_agent)
                if rel is not None else None)
    if tool in _SEARCH_TOOLS:
        root = tool_input.get("path")
        if not str(root or "").strip():
            return _deny_search_root("")
        rel = _rel_of(root, ws, cwd)
        if rel is None:
            return None  # root outside the workspace — no maker face there
        return _deny_search_root(rel, own_agent=own_agent) \
            or _deny_pattern(tool_input.get("pattern")) \
            or _deny_pattern(tool_input.get("glob"))
    if tool == _BASH_TOOL:
        cmd = str(tool_input.get("command") or "")
        if not cmd:
            return None
        cmd_low = cmd.replace("\\", "/").lower()
        for rx in _BASH_DIR_RES:
            m = rx.search(cmd_low)
            if m:
                return f"{m.group(0).strip()}/ (path token in the command)"
        for token in _BASH_SUBSTRINGS:
            if token in cmd_low:
                if token == "worker-status-" and _only_own_worker_status(
                        cmd_low, own_agent):
                    continue  # own liveness line only
                return f"{token} (path token in the command)"
        return None
    return None


# ---------- identity -------------------------------------------------------

def _matches_redteam(agent: str) -> bool:
    a = str(agent or "").lower()
    return any(m in a for m in REDTEAM_AGENT_MARKERS)


def _matches_settler(agent: str) -> bool:
    a = str(agent or "").lower()
    return any(m in a for m in SETTLER_AGENT_MARKERS)


def _blind_family(agent: str) -> str | None:
    """The blind family an agent NAME belongs to ("settler" | "redteam"),
    else None. The marker sets are disjoint; settler is checked first
    so a future marker overlap de-fails toward the stricter family."""
    if _matches_settler(agent):
        return "settler"
    if _matches_redteam(agent):
        return "redteam"
    return None


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


def blind_act_class(payload: dict) -> str | None:
    """Mechanical blind-act identity ("settler" | "redteam" | None): the
    subagent `agent_type` when present (authoritative), else the
    UserPromptSubmit-armed session's recorded dispatch agent. An armed
    session is blind BY CONSTRUCTION — a row whose agent is blank or
    unrecognized still denies (the arm only ever RESTRICTS; the family
    merely selects the reject message). None means not a blind act."""
    agent = str(payload.get("agent_type") or payload.get("agent_name") or "")
    if agent.strip():
        return _blind_family(agent)
    sid = str(payload.get("session_id") or "")
    if not sid:
        return None
    ws = resolve_workspace(payload)
    if ws is None:
        return None
    row = _fresh_sessions(_load_arms(ws),
                          datetime.now(timezone.utc)).get(sid)
    if not isinstance(row, dict):
        return None
    return _blind_family(str(row.get("agent") or "")) or "redteam"


def _own_status_agent(payload: dict, ws: Path | None) -> str:
    """The bare agent name whose OWN liveness file this call may touch:
    the subagent's own agent_type, else the armed session's dispatch
    agent. Plugin-qualified ids resolve to their bare segment (the same
    convention the dispatch gate uses). The exemption is restriction-
    loosening for exactly one narrative-free file — never a new read."""
    agent = str(payload.get("agent_type") or payload.get("agent_name") or "")
    if not agent.strip() and ws is not None:
        sid = str(payload.get("session_id") or "")
        row = (_fresh_sessions(_load_arms(ws), datetime.now(timezone.utc))
               .get(sid) if sid else None)
        agent = str((row or {}).get("agent") or "") if isinstance(
            row, dict) else ""
    return agent.strip().rsplit(":", 1)[-1].lower()


# ---------- faces ----------------------------------------------------------

def _emit(ws: Path | None, face: str, tool: str, detail: str) -> None:
    """Durable trail (fail-open — the REJECT never depends on logging)."""
    try:
        if ws:
            with scripts_on_path():  # scoped membership
                import kunglao_log  # noqa: E402
                kunglao_log.emit(ws, "hook:rt_read_barrier", "rt_read_blocked",
                                 tool=tool or None, detail=detail, exit=2,
                                 matched_rule=face)
    except Exception as exc:  # noqa: BLE001
        warn("_emit", f"{type(exc).__name__}: {exc}")


def evaluate(payload: dict) -> tuple[int, str, str | None]:
    """(rc, stderr, additionalContext). rc=2 REJECT + repair path when the
    caller is a blind act (red-team or settler) and the target is a
    denied face; (0, "", None) for everyone else."""
    actor = blind_act_class(payload)
    if actor is None:
        return 0, "", None
    ws = resolve_workspace(payload)
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    cwd = str(payload.get("cwd") or (ws or "."))

    if tool in _DISPATCH_TOOLS:
        _emit(ws, "agent-dispatch", tool,
              f"{actor} act attempted a helper dispatch")
        err = (f"REJECT rt_read_barrier: a blind act ({actor}) may not "
               f"dispatch helper subagents (identity laundering).")
        return 2, err, (_SETTLER_DISPATCH_CTX if actor == "settler"
                        else _DISPATCH_CTX)

    if ws is None:
        return 0, "", None  # faces are workspace-relative; nothing to match
    face = _deny_for_tool(tool, tool_input, ws, cwd,
                          own_agent=_own_status_agent(payload, ws))
    if face is None:
        return 0, "", None
    _emit(ws, face, tool, f"{actor} act read attempt on {face}")
    if actor == "settler":
        err = (f"REJECT rt_read_barrier: {face} is a blind-settlement "
               f"face — the settler settles from raw artifacts, never "
               f"from producer narrative or the learning faces.")
        return 2, err, _SETTLER_CTX.format(face=face)
    err = (f"REJECT rt_read_barrier: {face} is a maker face — an RT act "
           f"derives its answer from raw evidence, never from the conclusion.")
    return 2, err, _CTX_TEMPLATE.format(face=face)


def main_face_user_prompt(payload: dict) -> int:
    """Face B: arm the session when its prompt IS a blind dispatch (red-team
    or settler). Recorder only — never blocks a prompt (rc 0 always)."""
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
        if _blind_family(agent):
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
