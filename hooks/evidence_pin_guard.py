#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evidence_pin_guard.py — #652 5-F3: freeze checker-consumed evidence.

RED: evidence/** was maker-writable via Write/Edit/Bash while BOTH checker
faces consume evidence/replay-<claim>.json as ground truth (the e2e
verifier gate; convergence's replay-equivalence face —
scripts/replay_equivalence.py). A maker could pre-place or overwrite the
artifact a checker compares against, after the checker's act started or
after it consumed the bytes.

POLICY (scripts/evidence_pin.py owns the store): a checker-consumed
artifact is sha-pinned at consumption (runs/evidence-pins.json). This hook
— PreToolUse Write|Edit|MultiEdit + PreToolUse Bash — REFUSES every later
mutation of a pinned path (rc=2):

  - Write/Edit/MultiEdit: file_path resolves to a pinned relpath;
  - Bash: the command text carries a mutation idiom (redirect, rm, mv, cp,
    sed -i, tee, truncate, dd of=) over a pinned path or one of its
    ancestor dirs. Reads (sha256sum/cmp/grep/cat) stay open — the RT and
    verifier acts compare bytes through Bash.

REPAIR (the audited supersede): a legitimate replacement unpins first —
`python3 scripts/evidence_pin.py <ws> unpin <relpath> --reason <why>` —
then rewrites, then re-runs the checker so the new bytes are re-consumed
(e2e: checkpoints pins at act-land / unpins at act-launch, reason =
re-verification round).

Arming is TARGET-based (#532 precedent): no pin store / no pins -> exit 0.
Fail-open on unreadable payloads; a REJECT always leaves a durable
runs/logs row (action=evidence_pin_blocked).
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
from pathlib import Path

from _path_hygiene import scripts_on_path  # #671 sys.path hygiene authority

#: the pin store (single source: scripts/evidence_pin.py owns the format)
PIN_FILE_REL = ("runs", "evidence-pins.json")

_WRITE_FACES = ("Write", "Edit", "MultiEdit")

#: Bash mutation idioms over one path (the path placeholder is substituted
#: as a regex-escaped literal with a boundary suffix). Reads are absent by
#: construction — the checker faces compare bytes through Bash.
_BASH_MUTATION_TEMPLATES = (
    r">{1,2}\s*['\"]?{path}{bound}",          # redirection (covers cat >)
    r"\brm\b[^;&|]*['\"]?{path}{bound}",
    r"\bsed\b[^;&|]*\s-i\b[^;&|]*['\"]?{path}{bound}",
    r"\btee\b[^;&|]*['\"]?{path}{bound}",
    r"\btruncate\b[^;&|]*['\"]?{path}{bound}",
    r"\bdd\b[^;&|]*of=['\"]?{path}{bound}",
    r"\b(mv|cp|install)\b[^;&|]*['\"]?{path}{bound}",
)

#: destructive verbs that also deny over an ANCESTOR dir of a pinned path
#: (removing evidence/ removes the pinned artifact inside it)
_BASH_ANCESTOR_TEMPLATES = (
    r"\brm\b[^;&|]*['\"]?{path}{bound}",
    r"\b(rmdir|mv|truncate)\b[^;&|]*['\"]?{path}{bound}",
)

CTX_TEMPLATE = (
    "[kunglao #652 evidence-pin] {rel} is PINNED (a checker consumed its "
    "bytes — sha256 recorded in runs/evidence-pins.json). A rewrite after "
    "consumption invalidates the verification it fed. Repair path: if the "
    "replacement is legitimate (usually a new verification round), supersede "
    "EXPLICITLY and audited — `python3 scripts/evidence_pin.py <ws> unpin "
    "{rel} --reason '<why>'` — then rewrite, then re-run the checker so the "
    "new bytes are re-consumed. REJECTED — do not overwrite a consumed "
    "artifact.")


def resolve_workspace(payload: dict) -> Path | None:
    """Workspace markers (claim-register.yaml / .hook_state.json) under cwd
    or cwd/malware-analysis-workspace — the deployed convention."""
    cwd = Path(payload.get("cwd") or payload.get("workspace") or ".")
    for base in (cwd / "malware-analysis-workspace", cwd):
        if (base / "claim-register.yaml").exists() \
                or (base / ".hook_state.json").exists():
            return base
    return None


def _load_pins(ws: Path) -> dict:
    """{relpath: row}; {} when missing. Corrupt store -> warn + {} (the
    corruption is a loud check() violation elsewhere; the hook must never
    wedge every Bash call of a workspace)."""
    p = ws.joinpath(*PIN_FILE_REL)
    if not p.is_file():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        pins = doc.get("pins")
        return dict(pins) if isinstance(pins, dict) else {}
    except (OSError, json.JSONDecodeError, AttributeError) as exc:
        warn("evidence_pin_guard", f"pin store unreadable: {p}: {exc}")
        return {}


def _rel_of(target: str, ws: Path, cwd: str) -> str | None:
    """The ws-relative posix path of `target` (absolute or cwd-relative),
    or None when it resolves outside the workspace."""
    if not str(target or "").strip():
        return None
    t = Path(str(target))
    base = t if t.is_absolute() else (Path(cwd or ".") / t)
    try:
        return base.resolve().relative_to(ws.resolve()).as_posix()
    except (ValueError, OSError):
        return None


def _match_pinned_path(cmd: str, rel: str, ws: Path) -> str | None:
    """The mutation idiom hit for `rel` in `cmd`, else None. Matches the
    ws-relative path, its ./ form and its absolute form; ancestor dirs are
    matched with destructive verbs only (removing evidence/ removes the
    pinned file inside)."""
    variants = [rel, "./" + rel, str((ws / rel).resolve())]
    for tmpl in _BASH_MUTATION_TEMPLATES:
        for v in variants:
            if re.search(tmpl.replace("{path}", re.escape(v))
                            .replace("{bound}", r"(?![\w./-])"), cmd):
                return f"mutation idiom over {rel}"
    ancestors = []
    parts = rel.split("/")
    for i in range(1, len(parts)):
        a = "/".join(parts[:i])
        ancestors += [a, "./" + a, str((ws / a).resolve())]
    for tmpl in _BASH_ANCESTOR_TEMPLATES:
        for v in ancestors:
            if re.search(tmpl.replace("{path}", re.escape(v))
                            .replace("{bound}", r"(?![\w./-])"), cmd):
                return f"destructive verb over {v} (contains pinned {rel})"
    return None


def _emit(ws: Path | None, rel: str, tool: str, detail: str) -> None:
    """Durable trail (fail-open — the REJECT never depends on logging)."""
    try:
        if ws:
            with scripts_on_path():  # #671 scoped membership
                import kunglao_log  # noqa: E402
                kunglao_log.emit(ws, "evidence_pin", "evidence_pin_blocked",
                                 tool=tool or None, detail=detail, exit=2,
                                 matched_rule=rel)
    except Exception as exc:  # noqa: BLE001
        warn("_emit", f"{type(exc).__name__}: {exc}")


def evaluate(payload: dict) -> tuple[int, str, str | None]:
    """(rc, stderr, additionalContext). Freeze posture: rc=2 + repair path."""
    ws = resolve_workspace(payload)
    if ws is None:
        return 0, "", None  # no workspace, no pins — nothing armed
    pins = _load_pins(ws)
    if not pins:
        return 0, "", None  # target-based arming: no pins, no guard
    tool = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    cwd = str(payload.get("cwd") or ws)

    rel_hit: str | None = None
    if tool in _WRITE_FACES:
        rel = _rel_of(str(tool_input.get("file_path") or ""), ws, cwd)
        if rel and rel in pins:
            rel_hit = rel
    elif tool == "Bash":
        cmd = str(tool_input.get("command") or "")
        if cmd:
            for rel in sorted(pins):
                if _match_pinned_path(cmd, rel, ws):
                    rel_hit = rel
                    break
    if rel_hit is None:
        return 0, "", None

    _emit(ws, rel_hit, tool,
          f"{tool} targeted pinned evidence artifact {rel_hit}")
    err = (f"REJECT evidence_pin_guard: {rel_hit} is pinned (checker-consumed "
           f"— #652). Supersede explicitly before rewriting.")
    return 2, err, CTX_TEMPLATE.format(rel=rel_hit)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0  # fail-open: a broken payload must never block tool calls
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
