#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deployed_refresh.py — #783 T3/T4 framework-copy refresh + orphan guard.

upgrade-side half of the deployment inversion:
  * refresh: bring every manifest-declared workspace copy to the current
    skill content (overwrite semantics). Locally modified copies are backed
    up under runs/deploy-backup-<ts>/ BEFORE being clobbered.
  * orphan guard (double-confirm, D4): a file living in the deployed trees
    that is NEITHER a manifest destination NOR byte-equal (newline-normalized)
    to any manifest source is unknown scaffolding — copied to
    runs/deploy-backup-orphan/ then removed. Anything recognizable is never
    touched.
No-op on dry runs. Never raises into the migration (degrades to a warn
detail) — mirrors agents_refresh posture.
"""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from kunglao_log import warn  # canonical warn (single implementation)


def _norm(b: bytes) -> bytes:
    CR, LF = bytes((13,)), bytes((10,))
    return b.replace(CR + LF, LF).replace(CR, LF)


def refresh(ws: Path, *, dry: bool = False,
            prune_orphans: bool = True) -> str:
    ws = Path(ws)
    if dry:
        return "deployed_refresh(dry)"
    try:
        import deploy_manifest as dm
        entries = {e["dest"]: e for e in dm.build_entries()}
    except Exception as exc:  # noqa: BLE001 — degraded detail only
        return f"deployed_refresh(skipped: manifest unavailable {exc!r})"

    known_shas = {e.get("sha256") for e in entries.values()}
    dests = set(entries)
    backup_dir = None
    modified: list[str] = []
    pruned: list[str] = []

    # issue 467 (manifest-vs-imports gate): the never-raise migration
    # contract stands — a gap between the deployed code's hard imports
    # and the serving env project's manifest surfaces as a warn + a
    # dep_gap detail part, never as an exception into the migration.
    dep_gap = _dep_gap_detail()
    if dep_gap:
        warn("dep_surface_gate", dep_gap)

    def _backup(f: Path, rel_dest: str) -> None:
        nonlocal backup_dir
        if backup_dir is None:
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            backup_dir = ws / "runs" / f"deploy-backup-{stamp}"
            backup_dir.mkdir(parents=True, exist_ok=True)
        rel = rel_dest.split("/", 1)[-1]
        tgt = backup_dir / rel
        tgt.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, tgt)

    for dest, e in sorted(entries.items()):
        src = Path(__file__).resolve().parent.parent / e["src"]
        if not src.is_file():
            continue
        dst = ws / dest
        want = _norm(src.read_bytes())
        if not dst.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            continue
        have = dst.read_bytes()
        if _norm(have) == want:
            continue
        _backup(dst, dest)
        shutil.copy2(src, dst)
        modified.append(dest)

    # ---- orphan guard (double-confirm) ----
    # 0.1.6 sweep: every manifest-DEPLOYED tree is scanned (hooks, agents,
    # references, scripts, templates, tools) — "every superseded file
    # REMOVED" (owner directive) is not hooks/agents-only. Unknown
    # scaffolding is backed up under runs/deploy-backup-orphan/ then
    # removed; recognizable (sha-known) variants survive.
    if prune_orphans:
        for f in _scan_orphans(ws, dests, known_shas):
            rel = f.relative_to(ws).as_posix()
            obdir = ws / "runs" / "deploy-backup-orphan"
            obdir.mkdir(parents=True, exist_ok=True)
            # keep the subpath under the deployed tree so same-basename
            # orphans in different directories never overwrite each other's
            # backup before the source is unlinked (reviewer r1-016sweep)
            bak = obdir / rel.removeprefix(".claude/")
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, bak)
            try:
                f.unlink()
            except OSError:
                continue
            pruned.append(rel)

    # #783 T5: (re)stamp the digest carrier — the workspace-side witness the
    # check-stale third criterion reads. Computed over the entries this run
    # deployed (build_entries), so refresh and deploy faces always agree.
    # the carrier also records the source head hash (the update identity);
    # the refresh re-records it, and the detail names it.
    carrier_digest = None
    carrier_head = None
    try:
        carrier = dm.write_carrier(ws, list(entries.values()))
        carrier_digest = carrier["deployed_digest"]
        carrier_head = carrier.get("source_head")
    except Exception as exc:  # noqa: BLE001 — WARN-only posture
        warn("carrier_write", f"carrier write failed ({exc!r})")

    parts = [f"manifest={len(entries)}"]
    if modified:
        parts.append(f"overwritten_modified={len(modified)}")
    if pruned:
        parts.append(f"pruned_orphans={len(pruned)}")
    if dep_gap:
        parts.append(f"dep_gap={dep_gap}")
    if carrier_digest:
        parts.append(f"carrier={carrier_digest[:8]}")
    if carrier_head:
        parts.append(f"head={carrier_head[:8]}")  # identity witness
    return "deployed_refresh(" + ",".join(parts) + ")"


def _scan_orphans(ws: Path, dests: set, known_shas: set) -> list[Path]:
    """The double-confirm orphan rule, shared by the standalone refresh
    (backup-then-remove) and the transaction's outright prune: a file
    living in a deployed tree that is NEITHER a manifest destination NOR a
    newline-normalized byte-variant of a manifest source is unknown
    scaffolding. Ordered for deterministic trails; NESTED deployed roots
    (a manifest may declare dests at .claude/templates and
    .claude/templates/state) each rglob the same subtree, so each file is
    visited once per covering root — dedupe by rel path so the caller
    unlinks exactly once."""
    import hashlib
    orphans: list[Path] = []
    seen_rels: set[str] = set()
    deployed_roots = sorted({str(Path(dest).parent) for dest in dests})
    for sub in deployed_roots:
        base = ws / sub
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(ws).as_posix()
            if rel in dests or rel in seen_rels:
                continue
            h = hashlib.sha256(_norm(f.read_bytes())).hexdigest()
            if h in known_shas:
                continue  # recognizable variant of a manifest source
            seen_rels.add(rel)
            orphans.append(f)
    return orphans


def prune_outright(ws: Path) -> list[str]:
    """The upgrade transaction's REMOVE step: delete every
    manifest-unknown file in the deployed trees OUTRIGHT — no backup step.
    The transaction guarantees the pre-migration git snapshot BEFORE any
    mutation, so the backup face of refresh() is redundant here; git
    restores anything the scan got wrong. Returns the removed workspace-
    relative paths; raises on manifest unavailability or removal failure
    so the transaction rolls back (fail-loud, never a half-pruned tree)."""
    ws = Path(ws)
    import deploy_manifest as dm
    entries = {e["dest"]: e for e in dm.build_entries()}
    known_shas = {e.get("sha256") for e in entries.values()}
    removed: list[str] = []
    for f in _scan_orphans(ws, set(entries), known_shas):
        f.unlink(missing_ok=True)
        removed.append(f.relative_to(ws).as_posix())
    return removed


def _dep_gap_detail() -> str:
    """The issue-467 gap string ('' when the env covers the surface) —
    computed against the EXECUTING tree and the hook env resolution, the
    same pair the hook commands will use at runtime."""
    try:
        import dep_surface_gate as dsg
        env_root = dsg.framework_env_root()
        if env_root is None:
            return ""
        report = dsg.check(
            surface_root=Path(__file__).resolve().parent.parent,
            env_root=env_root)
        if report["ok"]:
            return ""
        mods = ",".join(m["module"] for m in report["missing"])
        return (f"env {env_root} lacks {mods} "
                f"— update the skill package at that root")
    except Exception as exc:  # noqa: BLE001 — never raises into the migration
        warn("dep_surface_gate", f"gate check failed ({exc!r})")
        return ""


def item(ws: Path, dry: bool) -> str:
    """Migration-item face (#783 T3/T4)."""
    if dry:
        return "deployed_refresh(dry)"
    try:
        return refresh(ws)
    except Exception as exc:  # noqa: BLE001 — WARN-only posture
        return f"deployed_refresh(warn: {exc!r})"
