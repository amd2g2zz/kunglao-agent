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
import locale
import os
import shutil
import sys
import tempfile
from pathlib import Path

from _path_hygiene import ensure_on_path, ensure_scripts_path  # #671 authority

SKILL_DIR = Path(__file__).resolve().parent.parent
# #671: module-level membership via the hygiene authority. Order-faithful to
# the two bare inserts this replaces: hooks/ ends up AHEAD of scripts/ (the
# lib_kunglao ambiguity — #568 lesson), so scripts/ is ensured first
# (position-stable) and hooks/ move-to-front LAST lands it in front.
ensure_scripts_path()
# #770: position-stable membership (front=True reordered shared-name twins);
ensure_on_path(SKILL_DIR / "hooks")

RC_ALLOW = 0
RC_BLOCK = 2

# #686: opt-in decision-flow trace. stderr is already the block channel, so
# debug lines are additive and only appear when the env var is set — zero
# effect on the exit contract otherwise. Exists because the #686 failure
# (silent allow on must-block writes) was misattributed to the rule layer
# for days with no in-tree way to see where the decision died.
_DEBUG = os.environ.get("KUNGLAO_WG_DEBUG") == "1"


def _dbg(msg: str) -> None:
    if _DEBUG:
        print(f"wg-debug: {msg}", file=sys.stderr)

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


def _parse_payload_text(text: str) -> dict:
    """JSON-parse the decoded stdin text; non-dict JSON degrades to {}.

    #686: a list/scalar payload used to reach main() and crash on
    payload.get() with an AttributeError traceback (rc=1 class); treat it
    like every other unparseable payload — "not a file-writing tool call"."""
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _read_payload() -> dict:
    """Claude Code hands the hook one JSON object on stdin.

    #686: stdin is read as BYTES and decoded through an explicit charset
    chain — utf-8 (the Claude Code wire format), then the host locale (the
    shape every locale-defaulting caller emits, e.g. a cp936/GBK Windows
    host), then utf-8 with replacement so the JSON structure survives when
    neither fits. Reading through the text layer used to raise
    UnicodeDecodeError on the locale step (any non-ASCII byte, e.g. the
    em-dash in fact bodies, GBK-encoded by the parent), which the bare
    except swallowed into {} — main() then returned RC_ALLOW before the
    target was ever known: every must-block carrier write sailed through
    with rc=0 and empty stderr on cp936 hosts (Linux is utf-8 end-to-end,
    so CI never saw it). Bytes + chain cannot raise on content."""
    try:
        buf = getattr(sys.stdin, "buffer", None)
        raw = buf.read() if buf is not None else sys.stdin.read()
    except Exception:  # noqa: BLE001 — unreadable stdin is unadjudicable
        return {}
    if not raw.strip():
        return {}
    if isinstance(raw, str):  # detached/replaced stdin with no buffer
        return _parse_payload_text(raw)
    text = None
    for enc in ("utf-8", locale.getpreferredencoding(False)):
        try:
            text = raw.decode(enc)
            _dbg(f"payload decoded as {enc} ({len(raw)} bytes)")
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
        _dbg(f"payload decoded via utf-8 replacement ({len(raw)} bytes) — "
             f"charset mismatch, structure may degrade")
    return _parse_payload_text(text)


def resolve_workspace(payload: dict) -> Path | None:
    """cwd (or the target's ancestor) that carries kunglao workspace markers."""
    try:
        from _path_hygiene import load_hooks_lib  # #770 canonical twin bind
        _rw = load_hooks_lib().resolve_workspace
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
    Leg 3 (notes_writer #528): supersedes-chain adjudication of the note
    post-image — a correction without `supersedes:`, a pointer at a
    nonexistent note, or an inherited verify_status stamp is blocked.
    """
    violations: list[str] = []
    from lint_facts import lint_index, lint_workspace
    if carrier == CARRIER_INDEX:
        leg = [f"lint[{code}] {msg}"
               for sev, code, msg in lint_index(shadow / "facts" / "_INDEX.md")
               if sev == "error"]
        _dbg(f"adjudicate[{carrier}] lint_index leg: {len(leg)} violation(s)")
        return leg
    if carrier in (CARRIER_FACT, CARRIER_NOTE, CARRIER_REGISTER):
        errors, _warnings = lint_workspace(shadow)
        if carrier == CARRIER_REGISTER:
            # #820: register writes are adjudicated by the proven-gate leg
            # and the transition checks themselves. Workspace-wide fact lint
            # is the audit face — it never blocks a register write again
            # (豆包: F001/F002 连坐 F007/F010 的病理面)。
            added = []
        else:
            # #820: lint violations attribute to their own file (lint_facts
            # messages start with "<file>: "); only the target's own
            # violations block this write. One dirty legacy fact can no
            # longer deadlock every future write.
            target_name = rel.name
            added = [f"lint[{code}] {msg}" for _sev, code, msg in errors
                     if msg.split(":", 1)[0] == target_name]
        violations += added
        _dbg(f"adjudicate[{carrier}] lint_workspace leg: {len(added)} "
             f"violation(s) attributed to target")
    if carrier in (CARRIER_FACT, CARRIER_NOTE):
        from write_gate import audit_workspace
        target_rel = rel.as_posix()
        target_name = Path(target_rel).name
        n_gate = 0
        for v in audit_workspace(shadow):
            # Only violations attributable to THE FILE BEING WRITTEN block
            # this call — pre-existing violations elsewhere in the workspace
            # are the auditor's job, not this write's.
            if Path(str(v.get("file", ""))).name == target_name:
                n_gate += 1
                violations.append(
                    f"write_gate[{v.get('rule')}] {v.get('detail')}")
        _dbg(f"adjudicate[{carrier}] write_gate leg: {n_gate} violation(s) "
             f"attributable to {target_name}")
    if carrier == CARRIER_NOTE:
        try:
            from notes_writer import check_write
            pending_text = (shadow / rel).read_text(
                encoding="utf-8", errors="replace")
            msgs = list(check_write(shadow / "notes", pending_text, rel.name))
            violations += [f"supersedes[{i}] {msg}" for i, msg in enumerate(
                msgs, start=1)]
            _dbg(f"adjudicate[{carrier}] supersedes leg: {len(msgs)} "
                 f"violation(s)")
        except Exception as exc:  # noqa: BLE001 — checker crash = fail closed
            violations.append(
                f"supersedes[?] adjudication crashed "
                f"({type(exc).__name__}: {exc}); fail-closed.")
    if carrier == CARRIER_REGISTER:
        # #819: evidence-gated ->PROVEN. Evidence lives in runs/*.md of the
        # REAL workspace (not the shadow — this tool call does not write
        # evidence). Fail-closed: a crashed gate blocks the write.
        try:
            from register_proven_gate import check_register_transitions
            try:
                old_text = (ws / "claim-register.yaml").read_text(
                    encoding="utf-8")
            except OSError:
                old_text = None
            new_text = (shadow / "claim-register.yaml").read_text(
                encoding="utf-8")
            res = check_register_transitions(ws, new_text, old_text)
            violations += [f"proven-gate: {v}" for v in res["violations"]]
            for wv in res["waivers"]:
                # waiver usage is observable (#532 item 5): one ledger row per
                # exemption consumed, with the stated justify
                try:
                    import kunglao_log
                    kunglao_log.emit(ws, actor="hook",
                                     action="proven_waiver_used",
                                     claim=str(wv.get("claim_id", "")),
                                     detail=str(wv.get("justify", ""))[:2000])
                except Exception:  # noqa: BLE001 — logging must not break the gate
                    pass
            _dbg(f"adjudicate[{carrier}] proven-gate leg: "
                 f"{len(res['violations'])} violation(s), "
                 f"{len(res['waivers'])} waiver(s)")
        except Exception as exc:  # noqa: BLE001 — gate crash = fail closed
            violations.append(
                f"proven-gate: adjudication crashed "
                f"({type(exc).__name__}: {exc}); fail-closed.")
    # #820: an active per-file waiver (runs/write-guard-waivers.yaml, written
    # by scripts/write_guard_unlock.py unlock) exempts the TARGET's own lint
    # violations for migration-mode rewrites. Only lint-leg violations are
    # waived; R1/R2 stamps, supersedes, and the proven gate are never waived.
    # Every consumption is observable (ledger row), mirroring proven_waiver_used.
    if carrier in (CARRIER_FACT, CARRIER_NOTE) and violations:
        try:
            import yaml as _yaml
            _wp = ws / "runs" / "write-guard-waivers.yaml"
            _wdata = (_yaml.safe_load(_wp.read_text(encoding="utf-8")) or {}) \
                if _wp.is_file() else {}
            waiver = _wdata.get(rel.name) if isinstance(_wdata, dict) else None
        except Exception:  # noqa: BLE001 — waiver store unreadable → no waiver
            waiver = None
        if waiver:
            kept = [v for v in violations if not v.startswith("lint[")]
            used = len(violations) - len(kept)
            if used:
                violations = kept
                try:
                    import kunglao_log
                    kunglao_log.emit(ws, actor="hook",
                                     action="write_guard_waiver_used",
                                     artifact=rel.name,
                                     detail=(f"{used} lint violation(s) "
                                             f"waived: "
                                             f"{str(waiver.get('reason', ''))[:300]}"))
                except Exception:  # noqa: BLE001 — logging never breaks gate
                    pass
    _dbg(f"adjudicate[{carrier}] total: {len(violations)} violation(s)")
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
        _dbg("exit ALLOW rc=0 — no tool_input.file_path "
             "(not a file-writing tool call, or unparseable payload)")
        return RC_ALLOW  # not a file-writing tool call
    target = Path(raw_target)
    _dbg(f"payload tool={payload.get('tool_name')!r} target={target.as_posix()}")
    ws = resolve_workspace(payload)
    _dbg(f"resolve_workspace -> {ws}")
    if ws is None:
        # Unresolvable workspace: only fail closed when the path SHAPE says
        # contract carrier (looks_like_carrier) — otherwise this hook would
        # block every edit in every non-kunglao repo the user opens.
        llc = looks_like_carrier(target)
        _dbg(f"looks_like_carrier -> {llc}")
        if llc:
            reason = ("write_guard: BLOCK — contract-carrier write in an "
                      "unresolvable workspace (no claim-register.yaml + facts/ "
                      "ancestor). #532 posture is fail-closed: a write we cannot "
                      "adjudicate is a write we do not allow.")
            print(reason, file=sys.stderr)
            _emit_block(None, payload, target.as_posix(), reason)
            _dbg("exit BLOCK rc=2 — unresolvable workspace, carrier shape")
            return RC_BLOCK
        return RC_ALLOW
    carrier = carrier_of(ws, target)
    _dbg(f"carrier_of -> {carrier}")
    if carrier is None:
        _dbg("exit ALLOW rc=0 — target is not one of the four carriers")
        return RC_ALLOW
    text, reason = post_image(payload, target)
    _img = "unadjudicable" if text is None else f"{len(text)} chars"
    _dbg(f"post_image -> {_img}" + (f" ({reason})" if text is None else ""))
    if text is None:
        detail = (f"write_guard: BLOCK — cannot reconstruct the post-image "
                  f"({reason}); fail-closed on the {carrier} carrier.")
        print(detail, file=sys.stderr)
        _emit_block(ws, payload, target.as_posix(), detail)
        _dbg("exit BLOCK rc=2 — post-image unadjudicable")
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
            _dbg(f"exit BLOCK rc=2 — adjudication crashed "
                 f"({type(exc).__name__}: {exc})")
            return RC_BLOCK
    if violations:
        # #820: surface the repair surface — this write is blocked only by
        # its own violations; other files' violations are audit info (the
        # repair/unlock targets), never blockers here.
        try:
            from collections import Counter
            from lint_facts import lint_workspace as _lw
            real_errors, _w2 = _lw(ws)
            cnt = Counter(m.split(":", 1)[0] for _s, _c, m in real_errors
                          if ":" in m)
            other = [f"{k}x{n}" for k, n in sorted(cnt.items()) if k != rel.name]
        except Exception:  # noqa: BLE001 — audit info must never crash the gate
            other = []
        audit = ("workspace audit (#820): blocked only by own violations; "
                 "other-file violations do not block unrelated writes"
                 + (" - repair surface: " + ", ".join(other) if other else ""))
        joined = "\n  - ".join(violations)
        detail = (f"write_guard: BLOCK — {len(violations)} write-side violation(s) "
                  f"on {rel.as_posix()}:\n  - {joined}\n{audit}")
        print(detail, file=sys.stderr)
        _emit_block(ws, payload, rel.as_posix(), detail)
        _dbg(f"workspace audit: {other}")
        _dbg(f"exit BLOCK rc=2 — {len(violations)} violation(s)")
        return RC_BLOCK
    if carrier == CARRIER_REGISTER:
        # #880: the write passed every gate and WILL land — claim transitions
        # in the post-image settle here (claim_settled rows + negative-sample
        # lesson burns). Fail-open: observability never moves the ALLOW.
        try:
            from register_proven_gate import emit_settlements
            try:
                old_text = (ws / "claim-register.yaml").read_text(
                    encoding="utf-8")
            except OSError:
                old_text = None
            n = emit_settlements(ws, text, old_text)
            if n:
                _dbg(f"settlement leg: {n} claim_settled row(s)")
        except Exception as exc:  # noqa: BLE001 — never moves the ALLOW
            _dbg(f"settlement leg crashed (fail-open): {type(exc).__name__}")
    _dbg("exit ALLOW rc=0 — adjudication clean")
    return RC_ALLOW


if __name__ == "__main__":
    sys.exit(main())
