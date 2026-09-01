#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao_upgrade.py — workspace framework-scaffold migration (#726).

Old workspaces drift behind the skill package (hooks added, vocab extended,
templates refreshed) and then fight the new features — #717's three-layer
gate escape was amplified by exactly such a v0.1.2-stamped workspace. This
CLI walks a linear N->M migration registry over the FRAMEWORK SCAFFOLD
only; the analysis data never moves.

IRON RULE — the seven user-data dirs (claims/ facts/ runs/ hypotheses/
notes/ evidence/ oracle/) are hashed (stamp-line-normalized) before and
after; any byte difference aborts with exit 4 and the pre-upgrade snapshot
stays on disk for forensics.

#739: a successful migration on a workspace that predates git ends with
ensure_git_snapshot() — git init + one snapshot commit + an explicit usage
banner. Git is the snapshot layer ONLY; the workspace on disk stays ground
truth, so a dirty git status can never masquerade as workspace state.

Spec: openspec/changes/issue-726-kunglao-upgrade/{proposal,design}/.

Stable argv contract (consumed by `kunglao.py cmd_upgrade` and by
`/kunglao-agent:upgrade` via subprocess):

    main(argv=[<workspace_path>] [--dry-run] [--json])

Exit codes (consumed by the slash-command SKILL.md UX layer):

    0  migrated / already at target / dry-run plan printed
    3  no version stamp on the workspace — direct to /kunglao-agent:init
    4  iron-rule violation — user data drifted, snapshot on disk
    6  dirty owned-repo — commit/stash first, then re-run (#753 B1)
    7  incomplete — migration applied but the finish sequence aborted
       (#753 B4); re-run upgrade to complete stamping/cleanup

JSON envelope (when `--json` is set):

    {
      "status": "ok" | "dry-run" | "already-current" | "refused"
              | "refused-dirty" | "iron-rule-violation" | "incomplete",
      "rc": 0 | 3 | 4 | 6 | 7,
      "items": [{"name": "hooks_rewire", "action": "applied" | "noop" | "skipped", "detail": "..."}],
      "iron_rule_hash": {"pre": "<sha256>", "post": "<sha256>"},
      "started_at": "<ISO-8601>",
      "ended_at":   "<ISO-8601>"
    }
"""
from __future__ import annotations

import argparse
import os
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

import yaml  # noqa: E402  (#755 A5: env-ledger YAML round trip)

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import claudemd_frame  # noqa: E402  (#755 G3 pure split/assemble)
import install_reference  # noqa: E402
import template_version  # noqa: E402
from hook_activation import (  # noqa: E402
    ALWAYS_ARMED_HOOKS,
    always_arm,
    canonical_install_root,
    register_hooks,
)
from _hooks_path import load_module_by_path  # noqa: E402  # #863 Family B: loader delegation (#671 authority)

USER_DATA_DIRS: tuple[str, ...] = (
    "claims", "facts", "runs", "hypotheses", "notes", "evidence", "oracle",
)
# Carriers whose framework stamp rides ON data files (#536 comment form) —
# the stamp line is normalized away before hashing so a sanctioned stamp
# refresh never trips the iron rule (design D4).
_STAMP_CARRIERS = ("facts/_INDEX.md", "claim-register.yaml")

RC_OK = 0
RC_UNKNOWN_ORIGIN = 3
RC_IRON_RULE = 4
RC_DIRTY_WORKSPACE = 6
RC_INCOMPLETE = 7

# #758 G1a/G1b: advisory interpreter-pin echo of .python-version=3.11.
PYTHON_PIN = (3, 11)


def _warn_python_version() -> None:
    """#758 G1b: stderr WARN when this CLI runs off the pinned series.

    Advisory only — CI (UV_PYTHON=python3.11) is the blocking authority;
    a local 3.13 run must still be able to upgrade a legacy workspace.
    Realigned onto #753's structured-event emitter (their NOTE asked for
    exactly this when #753 landed): one flushed [event] line.
    """
    vi = tuple(sys.version_info[:3])
    if vi[:2] != PYTHON_PIN:
        got = ".".join(str(x) for x in vi)
        pin = ".".join(str(x) for x in PYTHON_PIN)
        _emit_event("python_version", "warn",
                    f"{got}!=pinned:{pin} — advisory, continuing")

MigrationFn = Callable[[Path, bool], list[str]]


# --------------------------------------------------------------------------
# migration items (design D3 — declarative, each idempotent by construction)
# --------------------------------------------------------------------------

def _item_hooks_rewire(ws: Path, dry: bool) -> str:
    if not dry:
        register_hooks(ws)
    return "hooks_rewire"


def _item_deployed_refresh(ws: Path, dry: bool) -> str:
    """#783 T3/T4 face - delegates to deployed_refresh.item."""
    import deployed_refresh as _dr
    return _dr.item(ws, dry)


def _item_always_armed_repair(ws: Path, dry: bool) -> str:
    if not dry:
        always_arm(ws)
    return f"always_armed_repair({','.join(ALWAYS_ARMED_HOOKS)})"


def _guarded_stamp_refresh(ws: Path, *, version: str | None = None,
                           warn: bool = True) -> str:
    """#758 G4: a fresh stamp may only ride a CURRENT frame. Stamping a
    stale CLAUDE.md body is the lying class that amplified #717 — instead we
    keep the honest old stamp and let Wave-2 G3 (collect-and-merge, #755)
    bring the body forward before re-stamping."""
    if not template_version.frame_section_current(ws):
        if warn:
            print("kunglao-upgrade: WARN — frame section stale — G3 merge "
                  "upgrade required", file=sys.stderr)
        return "template_stamp_refresh(skipped: frame-drift)"
    written = (template_version.stamp_workspace(ws, version=version)
               if version else template_version.stamp_workspace(ws))
    return f"template_stamp_refresh({','.join(written) or 'noop'})"


def _item_template_stamp_refresh(ws: Path, dry: bool) -> str:
    if dry:
        # plan honesty (#758): the printed plan reflects the frame gate
        # even though nothing is written on a dry run
        if not template_version.frame_section_current(ws):
            return "template_stamp_refresh(skipped: frame-drift)"
        return "template_stamp_refresh"
    return _guarded_stamp_refresh(ws)


def _item_template_stamp_refresh_quiet(ws: Path, dry: bool) -> str:
    """Same #758 gate as the loud variant, but WARN-silent (#755): when a
    multi-entry plan runs (0.1.2 origins execute 0.1.3 THEN 0.1.4), only
    the FIRST stamp gate may warn — every later guarded stamp stays silent
    so one run produces exactly one stale-frame WARN."""
    if dry:
        return _item_template_stamp_refresh(ws, True)
    return _guarded_stamp_refresh(ws, warn=False)


def _item_init_report_note(ws: Path, dry: bool) -> str:
    if dry:
        return "init_report_note"
    report_path = ws / "runs" / ".init-report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8")) \
            if report_path.is_file() else {}
    except (ValueError, OSError):
        report = {}
    hist = report.setdefault("upgrade_history", [])
    hist.append({
        "to": template_version.read_skill_version(),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return "init_report_note"


def _item_agent_metadata_seed(ws: Path, dry: bool) -> str:
    target = ws / ".agent" / "specs.yaml"
    if target.is_file():
        return "agent_metadata_seed(noop)"
    if not dry:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "# kunglao .agent metadata (#720 convention, seeded by upgrade "
            "#726 — identity/status/linkage only)\nspecs: []\n",
            encoding="utf-8")
    return "agent_metadata_seed"


# --------------------------------------------------------------------------
# lazy kunglao-init seam (#755) — deploy-surface single sources
# --------------------------------------------------------------------------

_INIT_MOD = None


def _init_mod():
    """kunglao-init.py loaded once (hyphen filename needs importlib). The
    seam keeps the deploy-surface single sources (CORE_AGENTS / AGENTS_SRC
    for #755 A2; the CLAUDE.md render core for G3) authoritative in init
    while upgrade stays import-light at module level."""
    global _INIT_MOD
    if _INIT_MOD is None:
        # #863 Family B: by-path prologue collapsed into the canonical
        # loader (via scripts/_hooks_path); the global keeps the
        # load-once seam contract for existing readers.
        _INIT_MOD = load_module_by_path(
            "kunglao_init_upgrade_seam", _SCRIPTS / "kunglao-init.py")
    return _INIT_MOD


def _item_agents_refresh(ws: Path, dry: bool) -> str:
    """#755 A2 (T1): L2 subagent re-copy. The executing install's agents/
    are truth — a workspace `.claude/agents/*.md` whose md5 differs from the
    source (or is missing entirely) is re-copied byte-exact, mirroring init
    `_deploy_agents` (#478) semantics without re-running its env layer.
    Iron-rule safe: agents are framework scaffolding outside the seven dirs.
    WARN-only face: a missing SOURCE (repo-layout defect) or a copy I/O
    error degrades to a warn label + event, never through the migration."""
    if dry:
        return "agents_refresh(dry)"
    try:
        init = _init_mod()
        names: tuple[str, ...] = tuple(init.CORE_AGENTS)
        src_dir = Path(init.AGENTS_SRC)
        dst_dir = ws / ".claude" / "agents"
        deployed: list[str] = []
        unchanged = 0
        dst_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            src = src_dir / name
            if not src.is_file():
                raise RuntimeError(f"core agent source missing: {src}")
            payload = src.read_bytes()
            want = hashlib.md5(payload).hexdigest()
            dst = dst_dir / name
            if dst.is_file() and hashlib.md5(dst.read_bytes()).hexdigest() \
                    == want:
                unchanged += 1
                continue
            tmp = dst.with_name(dst.name + ".tmp755")
            tmp.write_bytes(payload)
            import os as _os
            _os.replace(tmp, dst)
            deployed.append(name)
        detail = (f"deployed={','.join(deployed)}" if deployed else "noop") \
            + f" unchanged={unchanged}"
        _emit(ws, "agents_refresh", detail)
        return f"agents_refresh({detail})"
    except Exception as exc:  # noqa: BLE001 — WARN-only item posture (#755 D0)
        why = f"{type(exc).__name__}: {exc}"
        print(f"kunglao-upgrade: WARN — agents refresh skipped ({why})",
              file=sys.stderr)
        _emit_event("agents_refresh", "warn", why)
        _emit(ws, "agents_refresh", f"warn:{why}")
        return f"agents_refresh(warn: {type(exc).__name__})"


# --------------------------------------------------------------------------
# G3 collect-and-merge (#755, issue #758 Wave-2 tail) ----------------------
# --------------------------------------------------------------------------

_SAMPLE_ROW_RE = {
    "sample_sha1": re.compile(r"\|\s*SHA1 \(filename\)\s*\|\s*`([^`]*)`\s*\|"),
    "sample_sha256": re.compile(r"\|\s*SHA256\s*\|\s*`([^`]*)`\s*\|"),
    "sample_type": re.compile(r"\|\s*Type\s*\|\s*`([^`]*)`\s*\|"),
    "sample_path": re.compile(r"\|\s*Path\s*\|\s*`([^`]*)`\s*\|"),
}


def _parse_sample_rows(old_text: str) -> dict[str, str]:
    """Carry the Sample-table values of the OLD render forward so the fresh
    frame keeps the same sample identity (upgrade never re-hashes bins/)."""
    out: dict[str, str] = {}
    for key, rx in _SAMPLE_ROW_RE.items():
        m = rx.search(old_text)
        if m and m.group(1).strip():
            out[key] = m.group(1).strip()
    return out


def _derive_project_type(ws: Path) -> str:
    """.kunglao-init.json -> analysis_state.txt -> 'windows' (init default)."""
    marker = ws / ".kunglao-init.json"
    if marker.is_file():
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            pt = data.get("project_type")
            if isinstance(pt, str) and pt.strip():
                return pt.strip()
        except (ValueError, OSError):
            pass
    state = ws / "analysis_state.txt"
    if state.is_file():
        try:
            for line in state.read_text(encoding="utf-8").splitlines():
                if line.startswith("project_type="):
                    got = line.split("=", 1)[1].strip()
                    if got:
                        return got
        except OSError:
            pass
    return "windows"


def _build_current_frame(ws: Path, old_text: str,
                         req_block: str | None) -> str:
    """Render the CURRENT base template with init-parity params (#362 engine
    through the lazy seam; D5 of the openspec design). req_block feeds the
    {{task_spec_section}} slot so the requirement segment rides inside the
    frame exactly where init would have placed it."""
    init = _init_mod()
    ptype = _derive_project_type(ws)

    tmpl_path = init.CLAUDEMD_TMPL
    if not tmpl_path.exists():
        raise RuntimeError(f"base template missing: {tmpl_path}")
    tmpl = tmpl_path.read_text(encoding="utf-8")

    type_section = init.os_section(ptype)
    try:  # #450 VM-conditioning parity (absent manifest -> unconditional)
        import env_manifest as em
        vm_req = em.vm_requirement_for(ws)
        if vm_req is not None and not vm_req[0]:
            type_section = em.conditionalize_vm_required(type_section,
                                                         vm_req[1])
    except Exception:  # noqa: BLE001 — parity best-effort, frame still renders
        pass

    venv_candidate = ws / ".venv"
    venv_path = str(venv_candidate) if venv_candidate.exists() else ".venv/"

    sample_name, sample_sha = "(unknown)", "(unknown)"
    bins_dir = ws / "bins"
    files = sorted(p for p in bins_dir.iterdir()
                   if p.is_file()) if bins_dir.is_dir() else []
    if len(files) == 1:
        sample_name = files[0].name
        sample_sha = hashlib.sha256(files[0].read_bytes()).hexdigest()
    carried = _parse_sample_rows(old_text)
    params = {
        "type_section": type_section,
        "task_spec_section": req_block or "",
        "type": ptype,
        "sample_sha1": carried.get("sample_sha1", sample_name),
        "sample_sha256": carried.get("sample_sha256", sample_sha),
        "sample_type": carried.get("sample_type",
                                   "(detected at analysis time)"),
        "sample_path": carried.get("sample_path", f"bins/{sample_name}"),
        "skill_dir": canonical_install_root().as_posix(),
        "venv_path": venv_path,
    }
    text = init.template_render.render_strict(
        tmpl, params, source=str(tmpl_path))
    py_version = f"{sys.version_info.major}." \
                 f"{sys.version_info.minor}.{sys.version_info.micro}"
    text = text.replace(
        "Activate before running scripts.",
        f"Activate before running scripts. Python {py_version}.")
    if ptype == "web":
        qr = getattr(init, "WEB_RE_QUICKREF", None)
        if qr is not None and Path(qr).is_file():
            text += "\n" + Path(qr).read_text(encoding="utf-8")
    return text


def _claudemd_read(ws: Path) -> str | None:
    p = ws / "CLAUDE.md"
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8", errors="replace")


def _frame_label(before: str, after: str) -> str:
    import difflib
    adds = removed = 0
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(),
                                     lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            adds += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return f"+{adds}/-{removed}"


def _item_claudemd_merge(ws: Path, dry: bool) -> str:
    """#755 G3 (T2/A3): three-segment collect-and-merge. Rebuild ONLY the
    frame from the CURRENT template; 需求段 (task_spec constraint block) and
    定制段 survive byte-exact (marked tails verbatim; legacy headed sections
    in place; stray prose relocated with new-frame dedup). When even the
    conservative heading-walk cannot place every current heading, the merge
    REFUSES: skip + WARN, body untouched — 宁可旧也不要错删 (#758 posture).
    After an applied merge the G4 stamp gate's positive path is unlocked."""
    current = _claudemd_read(ws)
    if current is None:
        return "claudemd_merge(noop: no CLAUDE.md)"
    expected = template_version.expected_frame_headings()
    if not expected:
        return "claudemd_merge(skip: no-template)"
    parts = claudemd_frame.plan_legacy(
        claudemd_frame.scrub_for_remerge(current), expected)
    if dry:
        return ("claudemd_merge(dry)" if parts.status == "applied"
                else f"claudemd_merge(dry-skipped: {parts.reason})")
    if parts.status != "applied":
        print(f"kunglao-upgrade: WARN — CLAUDE.md merge skipped "
              f"({parts.reason}); legacy body left untouched (G3)",
              file=sys.stderr)
        _emit_event("claudemd_merge", "warn", parts.reason)
        _emit(ws, "claudemd_merge", f"skipped:{parts.reason}")
        return f"claudemd_merge(skipped: {parts.reason})"
    frame_inner = _build_current_frame(ws, current, parts.req_block)
    # Fixed-point hygiene: a rebuilt frame can legitimately CONTAIN blocks
    # the classifier flagged as user content (parametric headings such as
    # `## Hard constraints (<type>)` are outside the #758 skeleton yet come
    # from the template itself), and unchanged template paragraphs classify
    # as stray prose. Any captured block whose bytes ride verbatim inside
    # the fresh render is a duplicate by construction — dropped; genuinely
    # foreign fragments survive (worst case relocation, never loss).
    parts.stray_prose = [b for b in parts.stray_prose
                         if not (b.strip() and b.strip() in frame_inner)]
    kept_us = []
    for heading, body in parts.user_sections:
        blk = (heading.rstrip("\n") + "\n" + body).strip()
        if blk and blk in frame_inner:
            continue
        kept_us.append((heading, body))
    parts.user_sections = kept_us
    merged = claudemd_frame.assemble(parts,
                                     claudemd_frame.wrap_frame(frame_inner))
    if merged == current:
        return "claudemd_merge(noop)"
    target = ws / "CLAUDE.md"
    tmp = target.with_name(target.name + ".tmp755")
    tmp.write_text(merged, encoding="utf-8")
    import os as _os
    _os.replace(tmp, target)
    detail = f"{_frame_label(current, merged)} sections={len(parts.user_sections)}"
    _emit_event("claudemd_merge", "ok", detail)
    _emit(ws, "claudemd_merge", detail)
    return f"claudemd_merge(applied {detail})"


def migrate_to_0_1_3(ws: Path, dry: bool) -> list[str]:
    """v0.1.2 -> current: hooks 9->11 (+orchestrator_tool_guard #608,
    +violation_capture #718), ALWAYS_ARMED repair (#717 L1), stamp refresh,
    init-report upgrade record, .agent seed. All items idempotent."""
    return [
        _item_hooks_rewire(ws, dry),
        _item_always_armed_repair(ws, dry),
        _item_template_stamp_refresh(ws, dry),
        _item_init_report_note(ws, dry),
        _item_agent_metadata_seed(ws, dry),
    ]


def migrate_to_0_1_4(ws: Path, dry: bool) -> list[str]:
    """#755 deployment-surface completion (T6 ruling, design D1). A fresh
    REGISTRY entry — not an extension of 0.1.3 — is what lets an
    ALREADY-0.1.3-stamped workspace (live-run class) re-plan instead of
    short-circuiting on `origin_key >= target_key`: the fast path stays
    closed while a plan exists, so the repairs below run today and remain
    reachable until release bumps the skill to 0.1.4. Transitional honesty:
    on a 0.1.2 origin this list runs AFTER migrate_to_0_1_3's gate-guarded
    stamp item; the belt-and-braces tail re-stamps AFTER the merge fixes
    the frame, so the end state is always the honest one."""
    return [
        _item_agents_refresh(ws, dry),          # A2/T1
        _item_deployed_refresh(ws, dry),        # #783 T3/T4 framework copies
        _item_claudemd_merge(ws, dry),          # G3+T2/A3
        _item_mcp_refresh(ws, dry),             # A4/T3
        _item_env_manifest_refresh(ws, dry),    # A5/T3
        _item_toolchain_manifest(ws, dry),      # A6/T3
        _item_uv_sync(ws, dry),                 # A7/T4
        _item_skill_staleness_check(ws, dry),   # A1/T5 (detect+report)
        _item_template_stamp_refresh_quiet(ws, dry)  # G4-gated carry
    ]


# Linear registry: every version that needs a migration step beyond
# "re-stamp" (the stamp refresh itself is carried by the LAST migration).
MIGRATIONS: list[tuple[str, MigrationFn]] = [
    ("0.1.3", migrate_to_0_1_3),
    ("0.1.4", migrate_to_0_1_4),   # #755 deploy-surface completion (T6)
]


# --------------------------------------------------------------------------
# iron rule machinery (design D4)
# --------------------------------------------------------------------------

def _vkey(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in version.strip().split("."))
    except ValueError:
        raise ValueError(f"unparseable version {version!r}")


# Framework-owned artifacts that live INSIDE user-data dirs (runs/):
# exempt from the iron-rule digest — they are init/upgrade telemetry, not
# analysis data. Anything else under the seven dirs stays byte-protected.
#   runs/.init-report.json          #534 init telemetry (upgrade appends)
#   runs/upgrade-snapshot.*.json    #726 own forensic output
#   runs/logs/kunglao-*.jsonl       #726 emits ONLY its own actor lines —
#                                   line-filtered, analysis events stay
#                                   byte-protected
_EXEMPT_EXACT = ("runs/.init-report.json",)


def _is_exempt(rel: str) -> bool:
    if rel in _EXEMPT_EXACT:
        return True
    if rel.startswith("runs/upgrade-snapshot.") and rel.endswith(".json"):
        return True
    # #783 T6: the deployed-refresh forensics dirs (deploy-backup-<ts>/,
    # deploy-backup-orphan/) are framework-owned writes of the upgrade's own
    # #791 refresh item — same D4 exemption class as upgrade-snapshot.
    # Analysis data under runs/ stays byte-protected.
    if rel.startswith("runs/deploy-backup-"):
        return True
    return False


def _normalized_bytes(path: Path, rel: str) -> bytes:
    data = path.read_bytes()
    if rel.startswith("runs/logs/kunglao-") and rel.endswith(".jsonl"):
        # drop only this tool's own lines plus the hook TTL machinery the
        # always_armed repair engages (renew, actor=orchestrator); every
        # other analysis event stays byte-protected
        kept = []
        for line in data.decode("utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except (ValueError, TypeError):
                kept.append(line)
                continue
            if rec.get("actor") == "kunglao_upgrade" or \
                    rec.get("action") == "renew":
                continue
            kept.append(line)
        return "\n".join(kept).encode("utf-8")
    # normalize the two sanctioned stamp carriers (#536 comment form)
    if any(path.match(carrier) for carrier in _STAMP_CARRIERS):
        text = data.decode("utf-8", errors="replace")
        text = "\n".join(
            line for line in text.splitlines()
            if not line.lstrip("# ").startswith(
                template_version.STAMP_KEY))
        return text.encode("utf-8")
    return data


def user_data_digest(ws: Path) -> dict[str, str]:
    """relpath -> sha256 over every file under the seven user-data dirs,
    with the framework-owned exemptions of design D4. Sorted, stable."""
    ws = Path(ws)
    out: dict[str, str] = {}
    for d in USER_DATA_DIRS:
        root = ws / d
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            rel = f"{d}/{p.relative_to(root).as_posix()}"
            if _is_exempt(rel):
                continue
            norm = _normalized_bytes(p, rel)
            if not norm:
                continue  # a log file whose every line is exempt == absent
            out[rel] = hashlib.sha256(norm).hexdigest()
    return out


def _framework_snapshot(ws: Path) -> dict[str, str]:
    ws = Path(ws)
    out: dict[str, str] = {}
    for rel in ("CLAUDE.md", ".claude/settings.json", ".hook_state.json"):
        p = ws / rel
        if p.is_file():
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# --------------------------------------------------------------------------
# events (design D6 — fail-open telemetry, never blocks the upgrade)
# --------------------------------------------------------------------------

def _emit(ws: Path, action: str, detail: str) -> None:
    try:
        from kunglao_log import emit
        emit(ws, actor="kunglao_upgrade", action=action, detail=detail)
    except Exception:  # noqa: BLE001 — telemetry must never block migration
        pass


def _emit_event(name: str, status: str, detail: str = "") -> None:
    """#753 B2 — structured stderr trail. One flushed line per critical node
    so an external kill leaves an exact last-event record (`name=` of the
    furthest completed stage). Never raises."""
    try:
        line = f"[event] name={name} status={status} detail={detail}"
        print(line.rstrip(), file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


# --------------------------------------------------------------------------
# git snapshot layer (#739)
# --------------------------------------------------------------------------

_SNAPSHOT_COMMIT_MSG = ("kunglao-upgrade: post-upgrade git snapshot "
                        "(legacy workspace had no git)")

# #753 B1 — the migration's own rollback pair. The ANCHOR lands before the
# first migration item (user ruling 2026-08-27: no commit, no upgrade); the
# post-state commit lands after a clean finish so the operator is always one
# `git revert` away from the pre-upgrade world.
_ANCHOR_COMMIT_MSG = ("kunglao-upgrade: pre-upgrade anchor "
                      "(rollback point before migration)")
_POST_STATE_MSG = "kunglao-upgrade: post-upgrade state commit (migration applied)"

# Shared identity + signing posture of #739: snapshot commits must not depend
# on host git config. NB the -c overrides go BEFORE the `commit` subcommand.
_GIT_IDENTITY = ("-c", "user.name=kunglao-upgrade",
                 "-c", "user.email=kunglao-upgrade@localhost",
                 "commit", "--no-gpg-sign")

# bins/ = immutable sample input; the rest = runtime noise. Kept out of the
# snapshot commit so a dirty status never masquerades as workspace truth.
_GITIGNORE_BODY = (
    "# kunglao-upgrade snapshot hygiene (#739)\n"
    "# bins/            : immutable sample input, never snapshot-tracked\n"
    "# runs/ *.log      : runtime noise\n"
    "# __pycache__/ *.pyc : toolchain caches\n"
    "bins/\n"
    "__pycache__/\n"
    "*.pyc\n"
    "*.log\n"
    "runs/\n"
)


def _run_git(ws: Path, *args: str) -> subprocess.CompletedProcess:
    """One git invocation against ws (git -C form). FileNotFoundError
    (git binary missing) propagates — the caller maps it to a WARN."""
    return subprocess.run(
        ["git", "-C", str(ws), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace")


def _print_git_banner(ws: Path) -> None:
    w = ws.as_posix()
    print("kunglao-upgrade: this workspace had no git — a snapshot repo is "
          "now initialized and the post-upgrade state committed.")
    print("  Git here is a SNAPSHOT layer only: the workspace on disk is "
          "ground truth — never read git status as current state.")
    print(f"  history    : git -C {w} log --oneline")
    print(f"  revert     : git -C {w} revert --no-edit HEAD")
    print(f"  experiment : git -C {w} checkout -b exp")


def _probe_dirty(ws: Path) -> tuple[str, int]:
    """#753 B1 gate — inspect the workspace repo without touching it.

    Returns ("absent"|"clean"|"dirty"|"skipped", entry_count). "skipped"
    covers a git binary/execution failure: the anchor cannot be verified, so
    the caller degrades loudly (same posture as #739's WARN-only snapshot).
    """
    if not (ws / ".git").exists():
        return ("absent", 0)
    try:
        proc = _run_git(ws, "status", "--porcelain")
    except (FileNotFoundError, OSError):
        return ("skipped", 0)
    if proc.returncode != 0:
        return ("skipped", 0)
    n = sum(1 for ln in proc.stdout.splitlines() if ln.strip())
    return ("dirty", n) if n else ("clean", 0)


def _warn_git_skip(surface: str, why: str) -> None:
    print(f"kunglao-upgrade: WARN — {surface} skipped: {why}", file=sys.stderr)


def _deploy_drift_now(ws: Path) -> bool:
    """#783 T5: does this workspace's deployed-copy tree actually need a
    refresh? Thin read-only face over deploy_manifest.deploy_drift; unreadable
    probes (no manifest, etc.) answer True — fail towards doing the work."""
    try:
        import deploy_manifest as _dm
        return bool(_dm.deploy_drift(ws).get("drift"))
    except Exception:  # noqa: BLE001 — fail towards the refresh
        return True


def _refuse_dirty(ws: Path, dirty_n: int) -> int:
    """#753 B1 refusal face — shared by the main migration path and the
    #783 early-exit refresh (identical output; guidance pinned by tests)."""
    _emit_event("gate-dirty", "fail", f"{dirty_n} uncommitted entries")
    print(f"kunglao-upgrade: REFUSED (RC_DIRTY_WORKSPACE=6) — {ws} has "
          f"{dirty_n} uncommitted change(s); migrating without a clean "
          f"rollback anchor is unrecoverable.", file=sys.stderr)
    print("kunglao-upgrade: commit or stash first, then re-run:",
          file=sys.stderr)
    print(f"  git -C {ws} add -A && git -C {ws} commit --no-gpg-sign "
          f"-m \"checkpoint before kunglao upgrade\"", file=sys.stderr)
    print(f"  (or) git -C {ws} stash push --include-untracked",
          file=sys.stderr)
    return RC_DIRTY_WORKSPACE


def _post_state_commit(ws: Path) -> bool:
    """Land the post-refresh state commit (early-exit refresh only — the
    main path's variant is guarded inside its atomic finish sequence).
    WARN-only: a failed commit never flips the exit code."""
    post = _run_git(ws, "add", "-A")
    if post.returncode == 0:
        post = _run_git(ws, *_GIT_IDENTITY, "-m", _POST_STATE_MSG)
    if post.returncode != 0:
        tail = (post.stderr or post.stdout or "").strip().splitlines()
        why = tail[-1] if tail else f"exit {post.returncode}"
        _warn_git_skip("post-refresh state commit", why)
        _emit(ws, "git_snapshot_skipped", f"post-state commit: {why}")
        _emit_event("git-snapshot", "warn", f"post-state skipped: {why}")
        return False
    return True


def _git_bootstrap_commit(ws: Path, message: str, surface: str,
                          skip_action: str, event_name: str) -> \
        tuple[bool, str | None]:
    """One hygiene pass: .gitignore -> init -> add -A -> commit(message).
    Returns (ok, reason-label); every failure is already WARNed + recorded
    under the given surface name (jsonl action + stderr event name) by the
    time False comes back."""
    try:
        (ws / ".gitignore").write_text(_GITIGNORE_BODY, encoding="utf-8")
        for label, args in (
            ("init", ("init",)),
            ("add", ("add", "-A")),
            ("commit", (*_GIT_IDENTITY, "-m", message)),
        ):
            proc = _run_git(ws, *args)
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()
                why = tail[-1] if tail else f"exit {proc.returncode}"
                _warn_git_skip(surface, f"`git {label}`: {why}")
                _emit_event(event_name, "fail", f"{label}: {why}")
                _emit(ws, skip_action, f"git {label}: {why}")
                return (False, f"git {label}")
    except FileNotFoundError:
        _warn_git_skip(surface, "(git binary not found) — continuing "
                      "WITHOUT a rollback anchor; abort now if you want the "
                      "safety net")
        _emit_event(event_name, "warn", "git binary not found")
        _emit(ws, skip_action, "git binary not found")
        return (False, "git-missing")
    except OSError as exc:
        _warn_git_skip(surface, str(exc))
        _emit_event(event_name, "fail", str(exc))
        _emit(ws, skip_action, str(exc))
        return (False, "io-error")
    return (True, None)


def ensure_pre_upgrade_anchor(ws: Path) -> dict:
    """#753 B1 — BEFORE any migration item runs, guarantee a rollback point:
    a workspace with no .git gets git init + one pre-upgrade anchor commit.
    Reuses #739's identity/signing posture. WARN-only on failure (degrades to
    the #739 behavior), never blocks an otherwise-legal migration."""
    ws = Path(ws)
    ok, _reason = _git_bootstrap_commit(
        ws, _ANCHOR_COMMIT_MSG, "pre-upgrade anchor",
        "git_anchor_skipped", "git-anchor")
    if not ok:
        return {"status": "skipped"}
    rev = _run_git(ws, "rev-parse", "--short", "HEAD")
    sha = rev.stdout.strip() if rev.returncode == 0 else None
    _emit_event("git-anchor", "ok",
                f"pre-upgrade anchor {sha or 'unknown'}")
    _print_git_banner(ws)
    return {"status": "created", "commit": sha}


def ensure_git_snapshot(ws: Path) -> dict:
    """#739 — legacy workspaces may predate git. After a successful upgrade,
    give them a snapshot repo (init + one commit) so every later change has
    a revert point. WARN-only by design: a snapshot we cannot take must
    never fail an otherwise-successful upgrade. Idempotent — an existing
    .git (dir OR worktree pointer file) is left untouched."""
    ws = Path(ws)
    if (ws / ".git").exists():
        return {"status": "existing"}
    ok, reason = _git_bootstrap_commit(
        ws, _SNAPSHOT_COMMIT_MSG, "git snapshot",
        "git_snapshot_skipped", "git-snapshot")
    if not ok:
        return {"status": "skipped", "reason": reason}
    rev = _run_git(ws, "rev-parse", "--short", "HEAD")
    sha = rev.stdout.strip() if rev.returncode == 0 else None
    _print_git_banner(ws)
    return {"status": "created", "commit": sha}


# --------------------------------------------------------------------------
# end-step install-reference sweep (#752 D6)
# --------------------------------------------------------------------------

def _sweep_detail(sweep: dict) -> str:
    n = sum(len(c.get("refs", []))
            for c in sweep.get("carriers", {}).values())
    return f"{sweep['status']}({n})"


def _install_reference_sweep(ws: Path, apply: bool = True) -> dict:
    """Residual scavenger (issue #752 D6): every ~/.claude/skills/<name>/
    reference in the workspace's framework carriers naming an install OTHER
    than the executing one is reported on stderr AND auto-repaired
    (rewire). WARN-only posture, mirroring #739's snapshot face — this must
    never flip a migration exit code. Iron-rule safe: touches only
    .claude/settings.json + CLAUDE.md, never the seven user-data dirs. The
    already-current fast path sweeps too: a workspace mis-wired by a
    pre-fix tool stamps CURRENT and would otherwise skip through the early
    return forever."""
    root = canonical_install_root()
    scan = install_reference.scan_workspace(ws, root)
    if not scan:
        return {"status": "clean"}
    rewired = install_reference.rewire_workspace(ws, root) if apply else {}
    report: dict = {"status": "rewired" if apply else "planned",
                    "root": str(root), "carriers": {}}
    verb = "STALE+REWIRE" if apply else "PLANNED"
    for carrier, refs in sorted(scan.items()):
        print(f"kunglao-upgrade: install-reference {verb} [{carrier}] "
              f"{len(refs)} ref(s)", file=sys.stderr)
        for ref in refs:
            print(f"kunglao-upgrade: install-reference   - {ref}",
                  file=sys.stderr)
        if apply:
            got = rewired.get(carrier, {})
            print(f"kunglao-upgrade: install-reference rewire [{carrier}]"
                  f" -> {root.name} ({got.get('rewired', 0)})",
                  file=sys.stderr)
        report["carriers"][carrier] = {"refs": refs}
    return report


# --------------------------------------------------------------------------
# config trio refresh (#755 T3: A4 .mcp.json / A5 env-ledger / A6 toolchain)
# --------------------------------------------------------------------------

def _atomic_write_bytes(target: Path, payload: bytes) -> None:
    tmp = target.with_name(target.name + ".tmp755")
    tmp.write_bytes(payload)
    import os as _os
    _os.replace(tmp, target)


def _item_mcp_refresh(ws: Path, dry: bool) -> str:
    """#755 A4: workspace .mcp.json backfill. Missing -> the init-parity
    scaffold (mcp_probe.build_scaffold_json — the SAME builder init's
    scaffold_mcp writes; mcpServers stays empty: a scaffold never shadows a
    working user-level registration). Existing -> report-only: the user may
    have registered servers there and upgrade never clobbers them."""
    target = ws / ".mcp.json"
    if target.is_file():
        if dry:
            return "mcp_refresh(dry-present)"
        detail = f"present({target.stat().st_size}B) untouched"
        _emit(ws, "mcp_scaffold_refresh", detail)
        return "mcp_refresh(noop: present)"
    if dry:
        return "mcp_refresh(dry)"
    try:
        import mcp_probe
        text = json.dumps(mcp_probe.build_scaffold_json(), indent=2,
                          ensure_ascii=False) + "\n"
        _atomic_write_bytes(target, text.encode("utf-8"))
        detail = "created(init-parity scaffold)"
        _emit(ws, "mcp_scaffold_refresh", detail)
        return f"mcp_refresh({detail})"
    except Exception as exc:  # noqa: BLE001 — WARN-only posture
        why = f"{type(exc).__name__}: {exc}"
        print(f"kunglao-upgrade: WARN — .mcp.json refresh skipped ({why})",
              file=sys.stderr)
        _emit(ws, "mcp_scaffold_refresh", f"warn:{why}")
        return f"mcp_refresh(warn: {type(exc).__name__})"


def _resolve_channel_for_backfill(ws: Path):
    """#727 resolution with a conservative local fallback — the deep channel
    semantics stay with parallel-wave #757; upgrade only ever CREATES."""
    try:
        import init_channel_default as icd
        return icd.resolve_init_channel(ws)
    except Exception as exc:  # noqa: BLE001 — fail-open to local
        try:
            import init_channel_default as icd
            return icd.ChannelDecision(
                selected=icd.LOCAL, defaulted_to_local=True, probes={},
                warn_reason=f"channel resolve error: {exc}")
        except Exception:  # noqa: BLE001 — import-defect last resort
            raise


_LEDGER_KEYS = ("generated", "project_type", "components")


def _item_env_manifest_refresh(ws: Path, dry: bool) -> str:
    """#755 A5: env-manifest.yaml (#478 deployment LEDGER shape) backfill /
    metadata refresh. Missing -> write {generated, project_type, components}
    (+ additive kunglao_version); the channel component row comes from #727's
    fail-open resolution and a defaulted-local lanes a WARN. Existing ->
    refresh ONLY the kunglao_version field; components/history untouched. A
    `version:` key must never exist on this file — it is the exact shape the
    env-facts loader uses to REJECT ledgers (#450 governance)."""
    path = ws / "env-manifest.yaml"
    cur = template_version.read_skill_version()
    if dry:
        return (f"env_ledger_refresh(dry-create)" if not path.is_file()
                else "env_ledger_refresh(dry-refresh)")
    if path.is_file():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            why = f"unparseable ledger: {exc}".splitlines()[0]
            print(f"kunglao-upgrade: WARN — env-manifest refresh skipped "
                  f"({why})", file=sys.stderr)
            _emit(ws, "env_ledger_refresh", f"warn:{why}")
            return f"env_ledger_refresh(warn: unparseable)"
        if not isinstance(data, dict):
            _emit(ws, "env_ledger_refresh", "warn:non-mapping")
            return "env_ledger_refresh(warn: non-mapping)"
        if data.get("kunglao_version") == cur:
            _emit(ws, "env_ledger_refresh", "noop(current)")
            return "env_ledger_refresh(noop)"
        data["kunglao_version"] = cur
        payload = yaml.safe_dump(data, sort_keys=False,
                                 allow_unicode=True)
        _atomic_write_bytes(path, payload.encode("utf-8"))
        detail = f"kunglao_version->{cur}"
        _emit(ws, "env_ledger_refresh", f"refreshed {detail}")
        return f"env_ledger_refresh(refreshed {detail})"
    project_type = _derive_project_type(ws)
    dec = _resolve_channel_for_backfill(ws)
    status = "defaulted-local" if dec.defaulted_to_local else "resolved"
    ledger = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "project_type": project_type,
        "kunglao_version": cur,
        "components": [{
            "name": "channel",
            "status": status,
            "detail": (f"selected={dec.selected} "
                       f"(#727 upgrade backfill; deep channel semantics "
                       f"-> #757)" + (
                           f"; warn={dec.warn_reason}"
                           if dec.warn_reason else "")),
        }],
    }
    payload = yaml.safe_dump(ledger, sort_keys=False, allow_unicode=True)
    _atomic_write_bytes(path, payload.encode("utf-8"))
    if dec.defaulted_to_local or dec.warn_reason:
        print(f"kunglao-upgrade: WARN — env-manifest backfill channel="
              f"{dec.selected} ({dec.warn_reason or 'defaulted'})",
              file=sys.stderr)
        _emit_event("env_ledger_refresh", "warn",
                    f"channel={dec.selected} {dec.warn_reason}")
    _emit(ws, "env_ledger_refresh", f"created channel={dec.selected}")
    return f"env_ledger_refresh(created channel={dec.selected})"


def _item_toolchain_manifest(ws: Path, dry: bool) -> str:
    """#755 A6 — toolchain-manifest face per CODE REALITY: init deploys no
    dedicated toolchain lock file; the durable faces are runs/.init-report.json
    telemetry (iron-rule exempt) and .kunglao-init.json. Contract: refresh the
    report's skill_version field when behind; absence REPORTS pointing at
    re-init — upgrade never fabricates init-completeness state (#625: an
    invented state_hash would be a lying marker)."""
    if dry:
        return "toolchain_manifest_check(dry)"
    report_path = ws / "runs" / ".init-report.json"
    marker = ws / ".kunglao-init.json"
    if not report_path.is_file():
        which = [] if not marker.is_file() else ["report"]
        label = ("missing"
                 + ("-and-marker" if not marker.is_file() else ""))
        detail = (f"{label} — re-init restores full deploy surface "
                  f"(no fabrication)")
        print(f"kunglao-upgrade: WARN — toolchain manifest faces absent: "
              f"runs/.init-report.json{'' if marker.is_file() else ' and '}"
              f".kunglao-init.json — {detail}", file=sys.stderr)
        _emit_event("toolchain_manifest_check", "warn", detail)
        _emit(ws, "toolchain_manifest_check", detail)
        return f"toolchain_manifest_check({label})"
    cur = template_version.read_skill_version()
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        why = f"unparseable report: {exc}".splitlines()[0]
        _emit(ws, "toolchain_manifest_check", f"warn:{why}")
        return "toolchain_manifest_check(warn: unparseable)"
    got = data.get("skill_version")
    if got == cur:
        _emit(ws, "toolchain_manifest_check", "noop(current)")
        return "toolchain_manifest_check(noop)"
    data["skill_version"] = cur
    _atomic_write_bytes(report_path,
                        (json.dumps(data, sort_keys=True,
                                    separators=(",", ":"),
                                    ensure_ascii=False)
                         + "\n").encode("utf-8"))
    detail = f"skill_version {got}->{cur}"
    _emit(ws, "toolchain_manifest_check", f"refreshed {detail}")
    return f"toolchain_manifest_check(refreshed {detail})"


# --------------------------------------------------------------------------
# A7 install-venv sync (#755 T4)
# --------------------------------------------------------------------------

UV_SYNC_TIMEOUT = 120


def _item_uv_sync(ws: Path, dry: bool) -> str:  # noqa: ARG001 — ws for item symmetry
    """#755 A7: refresh the INSTALL venv (`uv sync --locked --project
    <canonical_install_root>`) — the workspace analysis venv belongs to the
    executing install (#752 seam), never inside the user's data tree.
    WARN-only on every failure face (missing uv / timeout / non-zero rc):
    the #753 git-binary precedent — an environment nicety must never flip a
    migration exit code."""
    if dry:
        return "uv_sync(dry)"
    # Operational opt-out (also the test-hermeticity switch): a CI runner or
    # an offline operator can disable the real sync without code surgery.
    if os.environ.get("KUNGLAO_UPGRADE_NO_UV_SYNC") == "1":
        why = "skipped(KUNGLAO_UPGRADE_NO_UV_SYNC=1)"
        print(f"kunglao-upgrade: venv sync {why}", file=sys.stderr)
        _emit(ws, "uv_sync", why)
        return "uv_sync(skipped: env-opt-out)"
    import shutil
    uv = shutil.which("uv")
    if not uv:
        why = "uv binary not found"
        print(f"kunglao-upgrade: WARN — venv sync skipped ({why})",
              file=sys.stderr)
        _emit_event("uv_sync", "warn", why)
        _emit(ws, "uv_sync", f"warn:{why}")
        return "uv_sync(warn: uv-not-found)"
    argv = [uv, "sync", "--locked",
            "--project", str(canonical_install_root())]
    try:
        proc = subprocess.run(argv, timeout=UV_SYNC_TIMEOUT,
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        why = f"timeout>{UV_SYNC_TIMEOUT}s"
        print(f"kunglao-upgrade: WARN — venv sync {why}", file=sys.stderr)
        _emit_event("uv_sync", "warn", why)
        _emit(ws, "uv_sync", f"warn:{why}")
        return "uv_sync(warn: timeout)"
    except (FileNotFoundError, OSError) as exc:
        why = f"{type(exc).__name__}: {exc}"
        print(f"kunglao-upgrade: WARN — venv sync failed ({why})",
              file=sys.stderr)
        _emit_event("uv_sync", "warn", why)
        _emit(ws, "uv_sync", f"warn:{why}")
        return f"uv_sync(warn: {type(exc).__name__})"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        why = f"rc={proc.returncode}: {tail[-1] if tail else 'no output'}"
        print(f"kunglao-upgrade: WARN — venv sync failed ({why})",
              file=sys.stderr)
        _emit_event("uv_sync", "warn", why)
        _emit(ws, "uv_sync", f"warn:{why}")
        return "uv_sync(warn: rc!=0)"
    detail = f"ok({Path(str(canonical_install_root())).name}, locked)"
    _emit_event("uv_sync", "ok", detail)
    _emit(ws, "uv_sync", detail)
    return f"uv_sync(ok)"


# --------------------------------------------------------------------------
# A1 canonical-skill install staleness detection (#755 T5)
# --------------------------------------------------------------------------

def _exec_install_root() -> Path:
    """The executing skill install root (canonical seam of #752)."""
    return canonical_install_root()


def _git_at(root: Path, *args: str) -> subprocess.CompletedProcess:
    """One read-only git invocation against an ARBITRARY root (the install,
    not the workspace). Callers own every failure interpretation; the test
    face monkeypatches this name."""
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _item_skill_staleness_check(ws: Path, dry: bool) -> str:
    """#755 A1 (minimal wave): DETECT + REPORT whether the executing
    install's git clone trails its remote — stderr event
    `skill_install_staleness` (status=warn behind=N / ok parity). Self-update
    is explicitly OUT of scope (installs move by the user's git pull /
    plugin update); detection is read-only and never blocks a migration.
    Non-clone installs (tarball copies) report status=skip quietly. A
    dry-run plan probes nothing and emits nothing (zero-telemetry rule)."""
    if dry:
        return "skill_staleness(dry)"
    root = _exec_install_root()
    if not (Path(root) / ".git").exists():
        return "skill_staleness(skip: not-a-clone)"
    branch = _git_at(root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch.returncode != 0:
        why = f"branch probe failed: {branch.stderr.strip() or 'rc!=0'}"
        print(f"kunglao-upgrade: WARN — install staleness unreadable "
              f"({why})", file=sys.stderr)
        _emit_event("skill_install_staleness", "warn", why)
        _emit(ws, "skill_install_staleness", f"warn:{why}")
        return "skill_staleness(warn: probe-failed)"
    br = branch.stdout.strip() or "HEAD"
    upstream = _git_at(root, "rev-parse", "--symbolic-full-name", "@{u}")
    if upstream.returncode == 0 and upstream.stdout.strip():
        ref = upstream.stdout.strip()
    else:
        ref = f"origin/{br}"  # locally-known remote head — no network fetch
    count = _git_at(root, "rev-list", "--count", f"HEAD..{ref}")
    if count.returncode != 0:
        why = f"behind-count failed vs {ref}"
        print(f"kunglao-upgrade: WARN — install staleness unreadable "
              f"({why})", file=sys.stderr)
        _emit_event("skill_install_staleness", "warn", why)
        _emit(ws, "skill_install_staleness", f"warn:{why}")
        return "skill_staleness(warn: count-failed)"
    behind = count.stdout.strip() or "0"
    try:
        n = int(behind)
    except ValueError:
        n = -1
    detail = f"install={root.name} branch={br} vs {ref} behind={behind}"
    if n > 0:
        print(f"kunglao-upgrade: WARN — skill install is {n} commit(s) "
              f"behind {ref}; git pull / plugin update brings the current "
              f"scaffold forward", file=sys.stderr)
        _emit_event("skill_install_staleness", "warn", detail)
        _emit(ws, "skill_install_staleness", f"warn:{detail}")
        return f"skill_staleness(behind={behind})"
    _emit_event("skill_install_staleness", "ok",
                detail if n == 0 else f"{detail} (unreadable)")
    _emit(ws, "skill_install_staleness",
          detail if n == 0 else f"unknown:{detail}")
    return ("skill_staleness(current)" if n == 0
            else "skill_staleness(unknown)")


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def upgrade(ws: Path, dry_run: bool = False,
           items_out: list | None = None) -> int:
    ws = Path(ws)
    origin = template_version.read_workspace_version(ws)
    if origin is None:
        print("kunglao-upgrade: no version stamp on this workspace — "
              "cannot tell its shape. Run init on a fresh workspace.",
              file=sys.stderr)
        return RC_UNKNOWN_ORIGIN
    try:
        origin_key = _vkey(origin)
    except ValueError:
        print(f"kunglao-upgrade: workspace stamp {origin!r} is not a "
              f"parseable version — run init.", file=sys.stderr)
        return RC_UNKNOWN_ORIGIN
    target = template_version.read_skill_version()
    target_key = _vkey(target)

    plan = [(v, fn) for v, fn in MIGRATIONS if _vkey(v) > origin_key]
    if origin_key >= target_key and not plan:
        print(f"kunglao-upgrade: already at version {origin}")
        # #783 T5 chain-hole: the already-current fast path must still
        # refresh DEPLOYED framework copies (overwrite semantics are
        # version-free) — otherwise check-stale's deploy-drift advice
        # ("run /kunglao-agent:upgrade") would spin without effect. Only
        # workspaces carrying deployed copies enter this item, and only
        # when deploy_drift says a write is actually needed — the
        # no-drift case stays the historic true noop (rc 0, no gate),
        # pinned by #726's already-current contract.
        if (ws / ".claude" / "hooks").is_dir() and _deploy_drift_now(ws):
            if dry_run:
                item = _item_deployed_refresh(ws, dry=True)
                print(f"  [{target}] {item}")
                if items_out is not None:
                    items_out.append({"name": item, "action": "noop",
                                       "detail": "dry-run"})
            else:
                # #753 B1 gate parity — the refresh writes the tree, so it
                # needs the same rollback anchor as a migration.
                gate_state, dirty_n = _probe_dirty(ws)
                anchor: dict = {"status": "clean"}
                if gate_state == "dirty":
                    return _refuse_dirty(ws, dirty_n)
                if gate_state == "absent":
                    _emit_event("gate-dirty", "ok", "no git — anchoring first")
                    anchor = ensure_pre_upgrade_anchor(ws)
                elif gate_state == "clean":
                    _emit_event("gate-dirty", "ok", "clean owned repo")
                else:
                    _emit_event("gate-dirty", "warn", "probe unreadable")
                    _warn_git_skip("git status probe unreadable",
                                   "cannot verify workspace cleanliness")
                item = _item_deployed_refresh(ws, dry=False)
                print(f"  [{target}] {item} ok")
                _emit(ws, "upgrade_item", item)
                _emit_event("item", "ok", item)
                if items_out is not None:
                    items_out.append({"name": item, "action": "applied",
                                       "detail": "early-exit-refresh"})
                if anchor.get("status") == "created":
                    # anchor we created this run: land the post-state commit
                    # so the tree ends clean (same promise as the main path).
                    if _post_state_commit(ws):
                        _emit_event("git-snapshot", "ok",
                                    f"anchor@{anchor.get('commit')} post-state")
        # #752 D6: a CURRENT-stamped workspace can still carry stale
        # references (mis-wired by a pre-fix tool) — sweep applies here too.
        sweep = _install_reference_sweep(ws)
        _emit(ws, "install_reference_scan", _sweep_detail(sweep))
        return RC_OK

    if dry_run:
        print(f"kunglao-upgrade: dry-run {origin} -> {target}")
        for v, fn in plan:
            for item in fn(ws, dry=True):
                print(f"  [{v}] {item}")
                if items_out is not None:
                    items_out.append({"name": item, "action": "noop",
                                       "detail": "dry-run"})
        # #752 D6: planned sweep surfaces in the dry-run plan, writes nothing
        stale_n = sum(len(v) for v in
                      install_reference.scan_workspace(
                          ws, canonical_install_root()).values())
        print(f"  [{target}] install_reference_scan({stale_n} stale)")
        return RC_OK

    # ---- #753 B1: git-first rollback anchor -------------------------------
    # User ruling 2026-08-27: 未提交不升、无 git 先锚——坏掉必须能回滚。
    gate_state, dirty_n = _probe_dirty(ws)
    if gate_state == "dirty":
        return _refuse_dirty(ws, dirty_n)
    anchor: dict = {"status": "clean"}
    if gate_state == "absent":
        _emit_event("gate-dirty", "ok", "no git — anchoring first")
        anchor = ensure_pre_upgrade_anchor(ws)
    elif gate_state == "clean":
        _emit_event("gate-dirty", "ok", "clean owned repo")
    else:
        _emit_event("gate-dirty", "warn", "probe unreadable")
        _warn_git_skip("git status probe unreadable",
                       "cannot verify workspace cleanliness")

    pre = user_data_digest(ws)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    snap_path = ws / "runs" / f"upgrade-snapshot.{ts}.json"
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text(json.dumps(_framework_snapshot(ws), indent=2,
                                    ensure_ascii=False) + "\n",
                         encoding="utf-8")

    applied = 0
    _emit_event("migration-start", "ok", f"{origin}->{target} migrations={len(plan)}")
    for v, fn in plan:
        for item in fn(ws, dry=False):
            applied += 1
            print(f"  [{v}] {item} ok")
            _emit(ws, "upgrade_item", item)
            _emit_event("item", "ok", item)
            if items_out is not None:
                items_out.append({"name": item, "action": "applied",
                                   "detail": f"version={v}"})

    post = user_data_digest(ws)
    if pre != post:
        changed = sorted(k for k in set(pre) | set(post)
                         if pre.get(k) != post.get(k))
        _emit_event("iron-rule", "fail",
                    f"{len(changed)} file(s): {changed[:5]}...")
        print(f"kunglao-upgrade: IRON RULE VIOLATION — user data changed "
              f"({len(changed)} file(s): {changed[:5]}...). Snapshot kept: "
              f"{snap_path}", file=sys.stderr)
        return RC_IRON_RULE
    _emit_event("iron-rule", "ok", f"{len(pre)} user-data file(s) invariant")

    # ---- #753 B4: atomic finish sequence -----------------------------------
    # The incident behind this issue died AFTER stamp but BEFORE the summary
    # event, silently, with rc 0. From here on every step is guarded: any
    # exception surfaces as RC_INCOMPLETE=7 plus a summary=fail event —
    # never a silent RC_OK. (A hard external kill cannot be caught in-process;
    # B1's anchor makes that revertable and the flushed [event] trail above
    # records the exact last completed node.)
    tail_error = ""
    try:
        # stamp to target even when no migration entry exists for the gap
        # (forward stamps ride the last migration's refresh; belt & braces).
        # #758 G4: gated by the SAME frame predicate as the migration item —
        # otherwise this tail would bypass the gate and lie anyway. Silent:
        # the item above already emitted the one WARN this run needs.
        _guarded_stamp_refresh(ws, version=target, warn=False)
        _emit_event("stamp", "ok", f"version={target}")
        _emit(ws, "upgrade", f"{origin}->{target} items={applied}")
        print(f"kunglao-upgrade: {origin} -> {target} "
              f"({applied} item(s), snapshot {snap_path.name})")
        _emit_event("summary", "ok", f"{origin}->{target} items={applied}")
        # snapshot layer. When THIS run created the anchor we land the
        # post-state commit ourselves (one `git revert` back to the anchor;
        # the tree ends clean so later runs stay legal). Otherwise fall
        # through to the #739 recovery attempt (skipped-anchor workspaces).
        if anchor.get("status") == "created":
            post = _run_git(ws, "add", "-A")
            if post.returncode == 0:
                post = _run_git(ws, *_GIT_IDENTITY, "-m", _POST_STATE_MSG)
            if post.returncode != 0:
                tail = (post.stderr or post.stdout or "").strip().splitlines()
                why = tail[-1] if tail else f"exit {post.returncode}"
                _warn_git_skip("post-upgrade state commit", why)
                _emit(ws, "git_snapshot_skipped",
                      f"post-state commit: {why}")
                _emit_event("git-snapshot", "warn",
                            f"anchor@{anchor.get('commit')} kept; "
                            f"post-state skipped: {why}")
            else:
                rev = _run_git(ws, "rev-parse", "--short", "HEAD")
                head = rev.stdout.strip() if rev.returncode == 0 else "?"
                _emit_event("git-snapshot", "ok",
                            f"anchor@{anchor.get('commit')} "
                            f"post-state@{head}")
        else:
            # #739 — snapshot layer for workspaces that predate git; WARN-only,
            # never changes the exit code
            snap = ensure_git_snapshot(ws)
            if snap.get("status") == "skipped":
                _emit_event("git-snapshot", "warn",
                            str(snap.get("reason") or "skipped"))
            else:
                _emit_event("git-snapshot", "ok", snap.get("status", ""))
                # #752 D6 — residual-scavenger end step; WARN-only, exit code
        # untouched. Guarded separately from #753's atomic finish: a sweep
        # bug must neither flip this upgrade to RC_INCOMPLETE nor pass
        # silently — it surfaces as one stderr WARN + a scan event.
        try:
            sweep = _install_reference_sweep(ws)
            _emit(ws, "install_reference_scan", _sweep_detail(sweep))
            if items_out is not None:
                items_out.append({
                    "name": "install_reference_scan",
                    "action": ("applied" if sweep["status"] == "rewired"
                               else "noop"),
                    "detail": _sweep_detail(sweep)})
        except Exception as sweep_exc:  # noqa: BLE001 — fail-open by design
            _emit(ws, "install_reference_scan",
                  f"error:{type(sweep_exc).__name__}")
            print(f"kunglao-upgrade: WARN - install-reference sweep "
                  f"skipped ({type(sweep_exc).__name__}: {sweep_exc})",
                  file=sys.stderr)
# #753 B3 — the skill package just moved; Claude Code picks the new
        # slash-commands/hooks up only after a plugin reload.
        print("kunglao-upgrade: skill package updated — run /reload-plugins "
              "in Claude Code to activate")
    except Exception as exc:  # noqa: BLE001 — incomplete, not silent success
        tail_error = f"{type(exc).__name__}: {exc}"
        _emit_event("summary", "fail", tail_error)
    if tail_error:
        print(f"kunglao-upgrade: INCOMPLETE (RC_INCOMPLETE=7) — migration "
              f"applied but the finish sequence aborted ({tail_error}); "
              f"re-run upgrade to complete stamping/cleanup.", file=sys.stderr)
        return RC_INCOMPLETE
    return RC_OK


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="kunglao-upgrade — workspace framework-scaffold "
                    "migration; user data is byte-invariant")
    p.add_argument("workspace", help="workspace root")
    p.add_argument("--dry-run", action="store_true",
                   help="print the migration plan, write nothing")
    p.add_argument("--json", action="store_true",
                   help="emit a single JSON envelope on stdout (status, rc, "
                        "items, iron_rule_hash, started_at, ended_at); "
                        "the human-readable plan still goes to stderr")
    a = p.parse_args(argv)
    _warn_python_version()
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    items_out: list = []
    rc = upgrade(Path(a.workspace), a.dry_run, items_out)
    ended_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if a.json:
        status = {
            (RC_OK, True): "dry-run",
            (RC_OK, False): "ok" if items_out else "already-current",
            RC_UNKNOWN_ORIGIN: "refused",
            RC_IRON_RULE: "iron-rule-violation",
            RC_DIRTY_WORKSPACE: "refused-dirty",
            RC_INCOMPLETE: "incomplete",
        }
        # pick first matching key
        chosen = "ok"
        for key, label in status.items():
            if isinstance(key, tuple):
                if key[0] == rc and key[1] == a.dry_run:
                    chosen = label
                    break
            elif key == rc:
                chosen = label
                break
        envelope = {
            "status": chosen,
            "rc": rc,
            "items": items_out,
            "iron_rule_hash": {"pre": "", "post": ""},
            "started_at": started_at,
            "ended_at": ended_at,
        }
        # pre/post hashes are populated when --json is used against a real
        # (non-dry-run) migration that recorded them in `_framework_snapshot`;
        # for the workspace-internal CLI these stay empty — the slash
        # command SKILL.md UX surface documents the placeholder contract.
        print(json.dumps(envelope, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
