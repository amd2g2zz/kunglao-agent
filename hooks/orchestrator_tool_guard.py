#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""orchestrator_tool_guard.py — PreToolUse/Bash + MCP host-channel guard.

Two faces on ONE hook file (one registry file, two matcher rows):

  Bash face (#608): WARN posture, target-based arming (#532 write_guard
  precedent — "nobody dispatched, so nothing was armed" applies to the
  orchestrator's own shell too):
    - command's COMMAND POSITION hits an analysis binary AND
    - cwd is NOT inside a .wt-* worker worktree
  → exit 0 with additionalContext (the corrective guidance) + one durable
  kunglao_log event. Workers inside .wt-* pass silently — they are the ones
  SUPPOSED to run these tools.

  MCP host-channel face (#601): REJECT posture. The main agent calling
  mcp__ghidra__* / mcp__x64dbg__* / mcp__frida__* / mcp__ida__* directly
  bypassed the dispatch corridor (the prohibition existed only as prose,
  rules §7.5 VM-ONLY). Same target-based arming: workers in .wt-* pass;
  everyone else gets rc=2 (block) + stderr REJECT + a durable trace row.

#57 gate 2 (orchestrator-overreach, framework-layer): per the owner ruling
violations REJECT with no opt-out, so the Bash face posture upgrades from
#608's WARN to REJECT — a worker-exclusive analysis binary at a command
position outside a .wt-* worktree is the orchestrator doing a worker's job
(the #601 precision fix removed the false-positive classes that motivated
the WARN). The face also closes the wrapper bypasses: `sh -c 'jadx ...'`,
`nohup floss ...`, `timeout 60 jadx ...`, `env V=x jadx ...`,
`xargs apktool ...` previously matched the wrapper's own command word and
slipped past; wrapper words are now unwrapped and the nested command word is
matched instead (#601 argument-text precision is preserved — `grep floss`
still does not fire because the FIRST real command word ends the walk).

#601 precision fix on the Bash face: the #608 regex matched the WHOLE
command text, so `grep floss`, `cat .../floss-raw.txt` and `cd .../jadx/bin`
(compound) all tripped — 160 WARN/25min in the field, alarm fatigue drowned
real signals, and the emit recorded only the first token so post-hoc triage
could not tell true from false. Now: split on &&/||/;/|/newline, skip
env-assignment prefix tokens, match the segment's COMMAND WORD (basename,
quote/parens stripped, .bat/.exe/.cmd suffix stripped) against the binary
set; the emit row's matched_rule carries the hit (additive kunglao_log
schema field).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from _path_hygiene import scripts_on_path  # #671 sys.path hygiene authority

# Analysis binaries only the dispatched workers should invoke (worker_budget's
# VM_TOOLS covers the dynamic-analysis family on the Agent face; this list is
# the static/decompile face seen in the #608 incident). #601: a frozenset
# matched at the COMMAND POSITION (see _segment_command_words) instead of a
# whole-text regex — same members, no more argument-text false positives.
ANALYSIS_BINARIES = frozenset({
    "jadx", "apktool", "baksmali", "ghidra", "ghidrarun", "analyzeheadless",
    "idat64", "ida64", "frida", "frida-server", "strings3", "diec", "floss",
})

# #601 MCP host-channel namespaces — the main agent must not call these
# directly (samples execute only in the VM; workers reach them through the
# dispatch corridor, orchestrator_tool_guard passes .wt-* cwd). Mirrors the
# worker-face HOST_FORBIDDEN_TOOLS posture (worker_budget_core.py) but on the
# namespace level and for the host side. #57 gate 2: mcp__ida__* joins — a
# decompiler corridor exactly like mcp__ghidra__*.
_MCP_HOST_CHANNEL_RES = tuple(re.compile(p) for p in (
    r"^mcp__ghidra__", r"^mcp__x64dbg__", r"^mcp__frida__", r"^mcp__ida__",
))

# segment split: && || ; | newline (single & = background separator too)
_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||;|\||\n|&")
# env-assignment prefix token: FOO=bar (skipped when scanning for the command
# word; `FOO=1 PATH=/x jadx ...` still attributes jadx)
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# executable suffix noise on the command word
_EXE_SUFFIX_RE = re.compile(r"\.(bat|exe|cmd)$", re.IGNORECASE)

# #57 gate 2 wrapper words — a preceding token that is NOT the command word.
# Plain wrappers: consume the word (plus its own leading flags) and keep
# walking. Flagged wrappers (timeout / nice / ionice / stdbuf) additionally
# consume their option operands (numeric or -flag tokens) before the real
# command word. Shell words recurse into the -c payload (the nested command
# string is one token; it is split and walked like a fresh segment).
_WRAPPER_WORDS = frozenset({
    "nohup", "command", "exec", "time", "env", "xargs",
    "sudo", "doas", "pkexec",
})
_FLAGGED_WRAPPER_WORDS = frozenset({"timeout", "nice", "ionice", "stdbuf"})
_SHELL_WORDS = frozenset({"sh", "bash", "dash", "ksh", "zsh"})
# sudo/doas option tokens whose NEXT token is an operand value (-u user)
_WRAPPER_VALUE_FLAGS = frozenset({"-u", "-g", "--user", "--group"})

CTX = ("[kunglao #608 maker-checker / #57 gate 2] The ORCHESTRATOR does not "
       "analyze — decompile/strings/emulation is WORKER-EXCLUSIVE. Repair: "
       "dispatch a worker for this claim (kunglao-worker or a specialist) "
       "and let it run this binary inside its .wt-* worktree — the "
       "dispatch_gate guards the Agent face, so this shell call bypassed the "
       "dispatch corridor. REJECTED — no opt-out (#57 ruling).")

_MCP_REJECT_CTX = ("[kunglao #601 VM-ONLY] {tool} is a host-channel MCP tool: "
                   "the sample would execute on the HOST. Dynamic analysis "
                   "belongs to a dispatched worker inside the VM corridor "
                   "(.wt-* worktree; x64dbg via connect_remote to the VM, "
                   "frida via the VM-resident frida-server). REJECTED — "
                   "dispatch a worker instead. (Recorded in runs/logs/.)")


def _in_worker_worktree(cwd: str) -> bool:
    p = Path(cwd)
    return any(part.startswith(".wt-") for part in p.parts)


def _normalize_command_word(token: str) -> str:
    """One candidate token -> normalized command word (quote/paren strip,
    basename, .bat/.exe/.cmd suffix strip, lowercase)."""
    w = token.strip("()!\"'")
    w = w.replace("\\", "/").rsplit("/", 1)[-1]
    w = _EXE_SUFFIX_RE.sub("", w)
    return w.lower()


def _unwrap_segment(tokens: list[str]) -> list[str]:
    """#57 gate 2: candidate command words of one segment with wrapper words
    unwrapped. The walk STOPS at the first real command word (preserving the
    #601 argument-text precision — `grep floss` still attributes `grep`).
    `sh -c '<payload>'` recurses into the payload string, split like a fresh
    segment."""
    words: list[str] = []
    i = 0
    while i < len(tokens):
        if _ENV_ASSIGN_RE.match(tokens[i]):
            i += 1  # env assignments (leading or after `env`) are not words
            continue
        w = _normalize_command_word(tokens[i])
        if w in _SHELL_WORDS and i + 1 < len(tokens) \
                and tokens[i + 1].strip() == "-c":
            payload = " ".join(tokens[i + 2:]).strip().strip("'\"")
            for sub in _SEGMENT_SPLIT_RE.split(payload):
                sub_tokens = sub.strip().split()
                if sub_tokens:
                    words.extend(_unwrap_segment(sub_tokens))
            return words  # nothing after the -c payload within this segment
        if w in _FLAGGED_WRAPPER_WORDS:
            i += 1
            while i < len(tokens) and (
                    tokens[i].startswith("-")
                    or tokens[i].replace(".", "", 1).isdigit()):
                i += 1
            continue
        if w in _WRAPPER_WORDS:
            i += 1
            while i < len(tokens) and tokens[i].startswith("-"):
                if tokens[i] in _WRAPPER_VALUE_FLAGS and i + 1 < len(tokens):
                    i += 1  # consume the flag's operand value too
                i += 1
            continue
        if w:
            words.append(w)
        return words  # first real command word ends the walk
    return words


def _segment_command_words(cmd: str) -> list[str]:
    """#601 precision + #57 wrapper unwrap: the COMMAND WORD of every segment
    (&&/||/;/|/newline split), with wrapper words unwrapped so the nested
    binary is attributed. Empty segments contribute nothing."""
    words: list[str] = []
    for seg in _SEGMENT_SPLIT_RE.split(cmd):
        tokens = seg.strip().split()
        if tokens:
            words.extend(_unwrap_segment(tokens))
    return words


def _match_analysis_binary(cmd: str) -> str | None:
    """First analysis binary found at a (unwrapped) COMMAND POSITION, else
    None."""
    for w in _segment_command_words(cmd):
        if w in ANALYSIS_BINARIES:
            return w
    return None


def _mcp_matched_rule(tool: str) -> str:
    """Namespace glob for the trace row's matched_rule (mcp__ghidra__*)."""
    parts = tool.split("__")
    if len(parts) >= 2:
        return f"mcp__{parts[1]}__*"
    return tool


def _emit(ws: str, action: str, rule: str, tool: str, detail: str,
          exit_code: int) -> None:
    """Durable trail (fail-open — the WARN/REJECT never depends on logging
    succeeding). matched_rule rides the #601 additive schema field."""
    try:
        if ws:
            with scripts_on_path():  # #671 scoped membership
                import kunglao_log  # noqa: E402
                kunglao_log.emit(Path(ws), "orchestrator", action,
                                 tool=tool or None, detail=detail,
                                 exit=exit_code, matched_rule=rule)
    except Exception:
        pass


def evaluate(payload: dict) -> tuple[int, str, str | None]:
    """(rc, stderr, additionalContext). Both faces REJECT outside .wt-*
    (#601 MCP host-channel face; #57 gate 2 upgraded the Bash face from the
    #608 WARN posture — orchestrator overreach is framework-layer)."""
    cwd = payload.get("cwd") or ""
    tool = str(payload.get("tool_name") or "")
    cmd = (payload.get("tool_input") or {}).get("command") or ""

    # ---- #601 MCP host-channel face -------------------------------------
    for ns_re in _MCP_HOST_CHANNEL_RES:
        if ns_re.search(tool):
            if _in_worker_worktree(cwd):
                return 0, "", None  # worker face — dispatch filters govern
            rule = _mcp_matched_rule(tool)
            detail = f"main-agent direct call to host-channel MCP: {tool}"
            _emit(cwd, "orchestrator_mcp_reject", rule, tool, detail, 2)
            err = (f"REJECT orchestrator_tool_guard: {tool} is VM-ONLY "
                   f"(host-channel). Dispatch a worker; never run the "
                   f"sample on the host.")
            return 2, err, _MCP_REJECT_CTX.format(tool=tool)

    # ---- #57 gate 2 Bash face (REJECT) with #601 command-position
    #      precision + wrapper unwrap --------------------------------------
    if not cmd:
        return 0, "", None
    matched = _match_analysis_binary(cmd)
    if matched is None:
        return 0, "", None
    if _in_worker_worktree(cwd):
        return 0, "", None  # workers dispatch analysis tools freely
    # durable trail (fail-open — the REJECT never depends on logging
    # succeeding)
    _emit(cwd, "orchestrator_tool_violation", matched, None,
          f"bash analysis-binary outside worker worktree "
          f"(command position: {matched}; #57 gate 2 REJECT)", 2)
    err = (f"REJECT orchestrator_tool_guard: {matched} is worker-exclusive "
           f"(#57 gate 2 orchestrator-overreach). Dispatch a worker for "
           f"this claim instead.")
    return 2, err, CTX


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0  # fail-open: a broken payload must never block Bash
    rc, err, ctx = evaluate(payload)
    if err:
        print(err, file=sys.stderr)
    if rc == 2:
        # #601 REJECT face — mirror dispatch_gate._reject_with_guidance:
        # exit 2 blocks the tool call, additionalContext carries the fix.
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": ctx or ""}}))
        return rc
    if ctx:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": ctx}}))
    return rc


if __name__ == "__main__":
    sys.exit(main())
