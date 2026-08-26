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

Exit codes: 0 ok/already/dry-run · 3 unreadable origin version (run init)
· 4 iron-rule violation.

Spec: openspec/changes/issue-726-kunglao-upgrade/{proposal,design}/.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Callable

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import template_version  # noqa: E402
from hook_activation import ALWAYS_ARMED_HOOKS, always_arm, register_hooks  # noqa: E402

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

MigrationFn = Callable[[Path, bool], list[str]]


# --------------------------------------------------------------------------
# migration items (design D3 — declarative, each idempotent by construction)
# --------------------------------------------------------------------------

def _item_hooks_rewire(ws: Path, dry: bool) -> str:
    if not dry:
        register_hooks(ws)
    return "hooks_rewire"


def _item_always_armed_repair(ws: Path, dry: bool) -> str:
    if not dry:
        always_arm(ws)
    return f"always_armed_repair({','.join(ALWAYS_ARMED_HOOKS)})"


def _item_template_stamp_refresh(ws: Path, dry: bool) -> str:
    if not dry:
        written = template_version.stamp_workspace(ws)
        return f"template_stamp_refresh({','.join(written) or 'noop'})"
    return "template_stamp_refresh"


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


# Linear registry: every version that needs a migration step beyond
# "re-stamp" (the stamp refresh itself is carried by the LAST migration).
MIGRATIONS: list[tuple[str, MigrationFn]] = [
    ("0.1.3", migrate_to_0_1_3),
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


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def upgrade(ws: Path, dry_run: bool = False) -> int:
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
        return RC_OK

    if dry_run:
        print(f"kunglao-upgrade: dry-run {origin} -> {target}")
        for v, fn in plan:
            for item in fn(ws, dry=True):
                print(f"  [{v}] {item}")
        return RC_OK

    pre = user_data_digest(ws)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    snap_path = ws / "runs" / f"upgrade-snapshot.{ts}.json"
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text(json.dumps(_framework_snapshot(ws), indent=2,
                                    ensure_ascii=False) + "\n",
                         encoding="utf-8")

    applied = 0
    for v, fn in plan:
        for item in fn(ws, dry=False):
            applied += 1
            print(f"  [{v}] {item} ok")
            _emit(ws, "upgrade_item", item)

    post = user_data_digest(ws)
    if pre != post:
        changed = sorted(k for k in set(pre) | set(post)
                         if pre.get(k) != post.get(k))
        print(f"kunglao-upgrade: IRON RULE VIOLATION — user data changed "
              f"({len(changed)} file(s): {changed[:5]}...). Snapshot kept: "
              f"{snap_path}", file=sys.stderr)
        return RC_IRON_RULE

    # stamp to target even when no migration entry exists for the gap
    # (forward stamps ride the last migration's refresh; belt & braces):
    template_version.stamp_workspace(ws, version=target)
    _emit(ws, "upgrade", f"{origin}->{target} items={applied}")
    print(f"kunglao-upgrade: {origin} -> {target} "
          f"({applied} item(s), snapshot {snap_path.name})")
    return RC_OK


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="kunglao-upgrade — workspace framework-scaffold "
                    "migration (#726); user data is byte-invariant")
    p.add_argument("workspace", help="workspace root")
    p.add_argument("--dry-run", action="store_true",
                   help="print the migration plan, write nothing")
    a = p.parse_args(argv)
    return upgrade(Path(a.workspace), a.dry_run)


if __name__ == "__main__":
    sys.exit(main())
