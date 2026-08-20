#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""write_guard.py — PreToolUse Edit/Write gate on the four contract carriers (#532).

WHY: every write-side checker already existed on dev and none of them had a
mechanical caller. lint_facts' only production caller was migrate_facts.py;
write_gate R1/R2 had zero hook callers; compare_register_change_proven_gate
had zero callers. All 8 registered hooks sat on Agent/Bash/Stop matchers, so
an agent editing facts/F001.md directly hit ZERO gates. The 2026-08-20
external workspace audit reproduced 3 imitation facts, a ghost claim cite
(`q1`), and a self-stamped verdict through exactly this hole.

Scope — the FOUR contract carriers, and nothing else:
    facts/**.md            schema + claim existence (L-1) + R1/R2/W-2 stamps
    notes/**.md            R1 maker-checker stamp re-verification + L-6 mix
    claim-register.yaml    status-change legality (lint-side ghost/claim refs)
    facts/_INDEX.md        row-shape validation (L-2/W-4 format drift)

Method — POST-IMAGE ADJUDICATION: the hook reconstructs what the file WOULD
contain after the tool call (Write -> tool_input.content; Edit -> current text
with old_string->new_string applied), materializes it into a throwaway shadow
workspace under tempfile, and runs the UNMODIFIED existing checkers against
that shadow. No checker learns a new "pending write" API and no real file is
touched before the verdict.

Posture — FAIL CLOSED, and NOT activation-gated. Unlike the Agent-matcher
hooks (which sleep outside a 30-min activation TTL), the write face is armed
whenever the target is a carrier: the failure mode this hook exists to stop is
precisely "nobody dispatched, so nothing was armed" (#533 F-H2). An
unadjudicable carrier write (no resolvable workspace, checker import failure,
checker raise) BLOCKS.

Exit contract (Claude Code PreToolUse):
    0  allow  — non-carrier target, or every checker clean
    2  block  — stderr carries the reason, which Claude Code feeds back to
                the model; every block also lands in kunglao_log (#532 item 5)

Wiring (register_hooks / hook_activation --wire-up, PreToolUse):
    matcher "Edit|Write|MultiEdit" -> this file (uv run --project <skill_root>).
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "hooks"))

RC_ALLOW = 0
RC_BLOCK = 2

# The four contract carriers. Resolved by carrier_of(); the INDEX constant
# exists because facts/_INDEX.md must beat the generic facts/** rule.
CARRIER_FACT = "fact"
CARRIER_NOTE = "note"
CARRIER_REGISTER = "register"
CARRIER_INDEX = "index"

# What the shadow workspace must carry for the checkers to reach their
# evidence. Keep this list minimal and explicit: a shadow that copies runs/
# wholesale would make every hook fire O(workspace size).
_SHADOW_TREES = ("facts", "notes", "references")
_SHADOW_FILES = ("claim-register.yaml", "analysis_state.txt")
_SHADOW_RUNS_GLOBS = ("*-verify-*.md", "verify-*.json")


def _read_payload() -> dict:
    """Claude Code hands the hook one JSON object on stdin."""
    try:
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001 — unreadable stdin is unadjudicable
        return {}
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def resolve_workspace(payload: dict) -> Path | None:
    """cwd (or the target's ancestor) that carries kunglao workspace markers."""
    try:
        from lib_kunglao import resolve_workspace as _rw
    except Exception:  # noqa: BLE001 — degrade to the local walk below
        _rw = None
    if _rw is not None:
        try:
            ws = _rw(payload)
        except Exception:  # noqa: BLE001 — never trust an imported resolver blindly
            ws = None
        if ws is not None:
            return Path(ws)
    target = (payload.get("tool_input") or {}).get("file_path")
    start = Path(target).resolve().parent if target else Path(
        payload.get("cwd") or ".").resolve()
    try:
        for cand in (start, *start.parents):
            if (cand / "claim-register.yaml").exists() and (cand / "facts").is_dir():
                return cand
    except OSError:
        return None
    return None


def carrier_of(ws: Path, target: Path) -> str | None:
    """Which contract carrier does `target` belong to? None = out of scope."""
    try:
        rel = Path(target).resolve().relative_to(Path(ws).resolve())
    except (ValueError, OSError):
        return None
    parts = rel.parts
    if rel.as_posix() == "facts/_INDEX.md":
        return CARRIER_INDEX
    if rel.as_posix() == "claim-register.yaml":
        return CARRIER_REGISTER
    if parts and parts[0] == "facts" and rel.suffix == ".md":
        return CARRIER_FACT
    if parts and parts[0] == "notes" and rel.suffix == ".md":
        return CARRIER_NOTE
    return None


def looks_like_carrier(target: Path) -> bool:
    """Path-SHAPE heuristic used when no workspace resolves: block only when
    the path claims to be a contract carrier (otherwise this hook would block
    every edit in every non-kunglao repo the user happens to open)."""
    parts = Path(target).parts
    name = Path(target).name
    return "facts" in parts or "notes" in parts or name == "claim-register.yaml"


def post_image(payload: dict, target: Path) -> tuple[str | None, str]:
    """The text the file WOULD hold after this tool call.

    Returns (text, reason). text=None means the post-image is not
    reconstructible -> the caller must fail closed with `reason`."""
    ti = payload.get("tool_input") or {}
    tool = str(payload.get("tool_name") or "")
    if tool == "Write":
        content = ti.get("content")
        if not isinstance(content, str):
            return None, "Write payload carries no string `content`"
        return content, ""
    if tool in ("Edit", "MultiEdit"):
        try:
            current = target.read_text(encoding="utf-8")
        except OSError as exc:
            return None, f"cannot read current text of {target.name}: {exc}"
        edits = ti.get("edits")
        if not isinstance(edits, list):
            edits = [{"old_string": ti.get("old_string"),
                      "new_string": ti.get("new_string"),
                      "replace_all": bool(ti.get("replace_all"))}]
        text = current
        for e in edits:
            old, new = e.get("old_string"), e.get("new_string")
            if not isinstance(old, str) or not isinstance(new, str):
                return None, "Edit payload carries a non-string old/new_string"
            if old not in text:
                return None, f"old_string not present in {target.name}"
            text = text.replace(old, new) if e.get("replace_all") else \
                text.replace(old, new, 1)
        return text, ""
    return None, f"unsupported tool_name {tool!r} on a contract carrier"


def build_shadow(ws: Path, target: Path, text: str, root: Path) -> Path:
    """Materialize <ws> into <root>/shadow with `target` replaced by `text`."""
    shadow = root / "shadow"
    shadow.mkdir(parents=True, exist_ok=True)
    for tree in _SHADOW_TREES:
        src = ws / tree
        if src.is_dir():
            shutil.copytree(src, shadow / tree, dirs_exist_ok=True)
    for name in _SHADOW_FILES:
        src = ws / name
        if src.is_file():
            shutil.copy2(src, shadow / name)
    runs_src, runs_dst = ws / "runs", shadow / "runs"
    if runs_src.is_dir():
        runs_dst.mkdir(parents=True, exist_ok=True)
        seen: set[Path] = set()
        for pattern in _SHADOW_RUNS_GLOBS:
            for p in runs_src.glob(pattern):
                if p.is_file() and p not in seen:
                    seen.add(p)
                    shutil.copy2(p, runs_dst / p.name)
    rel = Path(target).resolve().relative_to(Path(ws).resolve())
    dst = shadow / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8")
    return shadow


def adjudicate(ws: Path, shadow: Path, carrier: str, rel: Path) -> list[str]:
    """Run every wired checker against the shadow. [] = allow.

    Leg 1 (lint_facts): schema + claim existence (L-1) + _INDEX rows (L-2).
    Leg 2 (write_gate R1/R2): stamp re-verification — scoped to THE FILE
    BEING WRITTEN, so one dirty legacy fact cannot deadlock every future
    write (the whole-workspace audit stays on the write_gate.py CLI face).
    """
    violations: list[str] = []
    from lint_facts import lint_index, lint_workspace
    if carrier == CARRIER_INDEX:
        violations += [f"lint[{code}] {msg}"
                       for sev, code, msg in lint_index(shadow / "facts" / "_INDEX.md")
                       if sev == "error"]
        return violations
    if carrier in (CARRIER_FACT, CARRIER_NOTE, CARRIER_REGISTER):
        errors, _warnings = lint_workspace(shadow)
        violations += [f"lint[{code}] {msg}" for _sev, code, msg in errors]
    if carrier in (CARRIER_FACT, CARRIER_NOTE):
        from write_gate import audit_workspace
        target_rel = rel.as_posix()
        target_name = Path(target_rel).name
        for v in audit_workspace(shadow):
            # Only violations attributable to THE FILE BEING WRITTEN block
            # this call — pre-existing violations elsewhere in the workspace
            # are the auditor's job, not this write's.
            if Path(str(v.get("file", ""))).name == target_name:
                violations.append(
                    f"write_gate[{v.get('rule')}] {v.get('detail')}")
    return violations


def _emit_block(ws: Path | None, payload: dict, artifact: str, detail: str) -> None:
    """Every enforcement action is observable (#532 item 5 / E-1/E-2).

    Never raises: kunglao_log.emit already degrades to a stderr warning, and
    an unavailable logger must not turn a legitimate BLOCK into a crash."""
    if ws is None:
        return
    try:
        import kunglao_log
        kunglao_log.emit(ws, actor="hook", action="write_blocked",
                         tool=str(payload.get("tool_name") or ""),
                         artifact=artifact, exit=RC_BLOCK, detail=detail[:2000])
    except Exception as exc:  # noqa: BLE001 — logging must never break the gate
        print(f"write_guard: warning: cannot emit event: {exc}", file=sys.stderr)


def main() -> int:
    payload = _read_payload()
    ti = payload.get("tool_input") or {}
    raw_target = ti.get("file_path")
    if not raw_target:
        return RC_ALLOW  # not a file-writing tool call
    target = Path(raw_target)
    ws = resolve_workspace(payload)
    if ws is None:
        # Unresolvable workspace: only fail closed when the path SHAPE says
        # contract carrier (looks_like_carrier) — otherwise this hook would
        # block every edit in every non-kunglao repo the user opens.
        if looks_like_carrier(target):
            reason = ("write_guard: BLOCK — contract-carrier write in an "
                      "unresolvable workspace (no claim-register.yaml + facts/ "
                      "ancestor). #532 posture is fail-closed: a write we cannot "
                      "adjudicate is a write we do not allow.")
            print(reason, file=sys.stderr)
            _emit_block(None, payload, target.as_posix(), reason)
            return RC_BLOCK
        return RC_ALLOW
    carrier = carrier_of(ws, target)
    if carrier is None:
        return RC_ALLOW
    text, reason = post_image(payload, target)
    if text is None:
        detail = (f"write_guard: BLOCK — cannot reconstruct the post-image "
                  f"({reason}); fail-closed on the {carrier} carrier.")
        print(detail, file=sys.stderr)
        _emit_block(ws, payload, target.as_posix(), detail)
        return RC_BLOCK
    rel = Path(target).resolve().relative_to(Path(ws).resolve())
    with tempfile.TemporaryDirectory(prefix="kunglao-writeguard-") as tmp:
        try:
            shadow = build_shadow(ws, target, text, Path(tmp))
            violations = adjudicate(ws, shadow, carrier, rel)
        except Exception as exc:  # noqa: BLE001 — checker crash = fail closed
            detail = (f"write_guard: BLOCK — adjudication crashed "
                      f"({type(exc).__name__}: {exc}); fail-closed.")
            print(detail, file=sys.stderr)
            _emit_block(ws, payload, rel.as_posix(), detail)
            return RC_BLOCK
    if violations:
        joined = "\n  - ".join(violations)
        detail = (f"write_guard: BLOCK — {len(violations)} write-side violation(s) "
                  f"on {rel.as_posix()}:\n  - {joined}")
        print(detail, file=sys.stderr)
        _emit_block(ws, payload, rel.as_posix(), detail)
        return RC_BLOCK
    return RC_ALLOW


if __name__ == "__main__":
    sys.exit(main())
