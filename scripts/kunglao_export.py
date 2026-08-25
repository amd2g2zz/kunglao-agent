#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/kunglao_export.py — workspace export tool (#540, D5)

Zones:
- contract_carriers: 契约载体 (全部 dotfiles + named contract files)
- evidence: evidence/, runs/, pcap+frida scripts (reproduce 锚)
- scratch: free-zone (excluded by default, --include-scratch)

Manifest:
- workspace template version stamp (#536 — pairs with template_version.py)
- per-file sha256 (round-trip integrity)
- empty dirs preserved via .gitkeep fallback

verify subcommand: re-hash every archived file, report mismatches.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
import time
from pathlib import Path

# Manifest format version (orthogonal to #536 skill version)
MANIFEST_VERSION = "1.0"

# Contract carrier patterns (#538 + dotfiles)
CARRIER_PATTERNS = [
    ".mcp.json", ".env.example", ".convergence_ledger",
    "CLAUDE.md", "task_spec_snapshot.yaml",
    ".workspace-manifest.json", "_INDEX",
    "template_version.json", "register.yaml",
]

# Evidence patterns
EVIDENCE_DIRS = ["evidence", "runs", ".fact"]
EVIDENCE_EXTS = [".pcap", ".frida.js", ".frida.ts", ".json", ".md", ".yaml"]

# Scratch zone (excluded by default)
SCRATCH_PATTERNS = ["scratch/", "tmp/", ".cache/"]


def sha256_file(p: Path) -> str:
    """Compute sha256 of file."""
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def classify(path: Path) -> str:
    """Classify path into zone: carrier|evidence|scratch|other.

    Platform-stable (#540 CI regression): rel is normalized via .as_posix()
    so Windows separators still match the POSIX-shaped zone patterns, and
    the scratch-zone check applies to RELATIVE paths only — an absolute
    path that merely lives under a system /tmp is not workspace scratch
    (the golden CI failure mode).
    """
    rel = path.as_posix()
    # Scratch check first (excluded zones) — relative workspace paths only
    if not path.is_absolute():
        for pat in SCRATCH_PATTERNS:
            if rel.startswith(pat) or f"/{pat}" in f"/{rel}/":
                return "scratch"
    # Carriers
    for pat in CARRIER_PATTERNS:
        if rel.endswith(pat) or f"/{pat}" in rel or path.name == pat:
            return "carrier"
    # Evidence
    for d in EVIDENCE_DIRS:
        if rel.startswith(f"{d}/") or f"/{d}/" in rel:
            return "evidence"
    if path.suffix in EVIDENCE_EXTS:
        return "evidence"
    return "other"


def build_manifest(ws: Path, include_scratch: bool) -> dict:
    """Build export manifest with sha256 for each file."""
    # Workspace template version stamp (#536). Imported lazily so the
    # script stays a standalone CLI even when template_version is moved.
    try:
        import template_version  # noqa: PLC0415 — stdlib path bootstrap
        skill_version = template_version.read_skill_version()
        ws_version = template_version.read_workspace_version(ws)
        stamp_faults = template_version.verify_stamps(ws)
    except (ImportError, RuntimeError):
        skill_version = ws_version = None
        stamp_faults = {}

    manifest = {
        "version": MANIFEST_VERSION,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "workspace": str(ws.name),
        "skill_version": skill_version,
        "workspace_version": ws_version,
        "stamp_faults": stamp_faults,
        "zones": {"carrier": [], "evidence": [], "scratch": [], "other": []},
        "empty_dirs": [],
    }
    for p in sorted(ws.rglob("*")):
        if ".git" in p.parts:
            continue
        rel = p.relative_to(ws).as_posix() if p != ws else "."
        if p.is_dir():
            # Empty-dir fidelity: a directory with no children tracked. We
            # only record dirs we are about to archive (i.e. inside the
            # zone rules below). The export loop plants a .gitkeep so the
            # archive round-trips faithfully.
            continue
        if not p.is_file():
            continue
        if p.name == ".gitkeep":
            # Empty-dir markers — represented in `empty_dirs` instead,
            # never in zone file lists (avoids manifest/archive drift).
            continue
        zone = classify(Path(rel))
        if zone == "scratch" and not include_scratch:
            continue
        manifest["zones"][zone].append({
            "path": rel,
            "sha256": sha256_file(p),
            "size": p.stat().st_size,
        })

    # Empty-dir pass: a dir with a .gitkeep marker AND no other tracked
    # children is part of the contract surface and must round-trip. We
    # enumerate every dir under ws so a deeply nested empty contract
    # dir is captured (rglob gives the parents even when they are empty).
    for d in sorted(ws.rglob("*")):
        if ".git" in d.parts:
            continue
        if not d.is_dir():
            continue
        marker = d / ".gitkeep"
        if not marker.exists():
            continue
        non_marker_children = [c for c in d.iterdir() if c.name != ".gitkeep"]
        if non_marker_children:
            continue
        manifest["empty_dirs"].append(d.relative_to(ws).as_posix())
    return manifest


def export_workspace(ws: Path, archive: Path, include_scratch: bool = False) -> int:
    """Export workspace with zone classification and manifest."""
    if not ws.exists():
        print(f"workspace not found: {ws}", file=sys.stderr)
        return 1
    manifest = build_manifest(ws, include_scratch)
    manifest["include_scratch"] = include_scratch
    n_files = sum(len(v) for v in manifest["zones"].values())
    print(f"exporting {n_files} files from {ws}")
    print(f"  carriers: {len(manifest['zones']['carrier'])}")
    print(f"  evidence: {len(manifest['zones']['evidence'])}")
    if include_scratch:
        print(f"  scratch: {len(manifest['zones']['scratch'])}")
    with tarfile.open(archive, "w:gz") as tar:
        # Add manifest first
        manifest_bytes = json.dumps(manifest, indent=2).encode()
        manifest_tarinfo = tarfile.TarInfo("MANIFEST.json")
        manifest_tarinfo.size = len(manifest_bytes)
        tar.addfile(manifest_tarinfo, __import__("io").BytesIO(manifest_bytes))
        # Add files
        for zone in ("carrier", "evidence", "scratch"):
            if zone == "scratch" and not include_scratch:
                continue
            for entry in manifest["zones"][zone]:
                src = ws / entry["path"]
                if src.exists():
                    tar.add(src, arcname=f"export/{entry['path']}")
        # Empty-dir fidelity: write a synthetic .gitkeep per recorded dir
        for d in manifest.get("empty_dirs", []):
            ti = tarfile.TarInfo(f"export/{d}/.gitkeep")
            content = b"# kunglao export: empty-dir fidelity marker\n"
            ti.size = len(content)
            tar.addfile(ti, __import__("io").BytesIO(content))
    print(f"archive: {archive}")
    return 0


def verify_manifest(archive: Path) -> int:
    """Verify archive integrity using embedded manifest."""
    with tarfile.open(archive, "r:gz") as tar:
        m = tar.extractfile("MANIFEST.json")
        manifest = json.loads(m.read().decode())
    print(f"manifest version: {manifest.get('version')}")
    print(f"workspace: {manifest.get('workspace')}")
    bad = 0
    for zone, entries in manifest["zones"].items():
        if zone == "scratch" and not manifest.get("include_scratch"):
            continue
        if zone not in ("carrier", "evidence", "scratch"):
            # "other" is never archived by export_workspace (only the three
            # zones above are written) — checking it would always NOT FOUND.
            continue
        for entry in entries:
            member_name = f"export/{entry['path']}"
            try:
                with tarfile.open(archive, "r:gz") as tar:
                    f = tar.extractfile(member_name)
                    if f is None:
                        print(f"  MISSING: {entry['path']}")
                        bad += 1
                        continue
                    actual = hashlib.sha256(f.read()).hexdigest()
                    if actual != entry["sha256"]:
                        print(f"  SHA MISMATCH: {entry['path']}")
                        bad += 1
            except KeyError:
                print(f"  NOT FOUND: {entry['path']}")
                bad += 1
    if bad == 0:
        total = sum(len(v) for k, v in manifest["zones"].items()
                    if k != "scratch" or manifest.get("include_scratch"))
        print(f"OK: {total} files verified")
        return 0
    print(f"FAIL: {bad} files failed verification")
    return 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="workspace export tool (#540)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    
    p_exp = sub.add_parser("export", help="Export workspace")
    p_exp.add_argument("workspace", type=Path)
    p_exp.add_argument("-o", "--output", type=Path, required=True,
                       help="output archive (.tar.gz)")
    p_exp.add_argument("--include-scratch", action="store_true")
    
    p_ver = sub.add_parser("verify", help="Verify archive")
    p_ver.add_argument("archive", type=Path)
    
    args = ap.parse_args()
    if args.cmd == "export":
        sys.exit(export_workspace(args.workspace, args.output, args.include_scratch))
    elif args.cmd == "verify":
        sys.exit(verify_manifest(args.archive))
