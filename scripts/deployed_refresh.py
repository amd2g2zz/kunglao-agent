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
        sha_of = dm._sha
    except Exception as exc:  # noqa: BLE001 — degraded detail only
        return f"deployed_refresh(skipped: manifest unavailable {exc!r})"

    known_shas = {e.get("sha256") for e in entries.values()}
    dests = set(entries)
    backup_dir = None
    modified: list[str] = []
    pruned: list[str] = []

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
    for sub in (".claude/hooks", ".claude/agents"):
        base = ws / sub
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(ws).as_posix()
            if rel in dests:
                continue
            if not prune_orphans:
                continue
            import hashlib
            h = hashlib.sha256(_norm(f.read_bytes())).hexdigest()
            if h in known_shas:
                continue  # recognizable variant of a manifest source
            obdir = ws / "runs" / "deploy-backup-orphan"
            obdir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, obdir / f.name)
            try:
                f.unlink()
            except OSError:
                continue
            pruned.append(rel)

    parts = [f"manifest={len(entries)}"]
    if modified:
        parts.append(f"overwritten_modified={len(modified)}")
    if pruned:
        parts.append(f"pruned_orphans={len(pruned)}")
    return "deployed_refresh(" + ",".join(parts) + ")"


def item(ws: Path, dry: bool) -> str:
    """Migration-item face (#783 T3/T4)."""
    if dry:
        return "deployed_refresh(dry)"
    try:
        return refresh(ws)
    except Exception as exc:  # noqa: BLE001 — WARN-only posture
        return f"deployed_refresh(warn: {exc!r})"
