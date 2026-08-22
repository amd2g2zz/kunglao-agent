#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/kunglao_export.py — workspace export tool (#540, D5)

Zones:
- contract_carriers: 契约载体 (全部 dotfiles)
- evidence: evidence/, pcap+frida scripts (reproduce 锚)
- scratch: free-zone (excluded by default, --include-scratch)

Manifest:
- version stamp (#536)
- per-file sha256
- allows roundtrip integrity check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
import time
from pathlib import Path

# Manifest version — pairs with #536
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
    """Classify path into zone: carrier|evidence|scratch|other."""
    rel = str(path)
    # Scratch check first (excluded zones)
    for pat in SCRATCH_PATTERNS:
        if rel.startswith(pat) or f"/{pat}" in rel:
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
    manifest = {
        "version": MANIFEST_VERSION,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "workspace": str(ws.name),
        "zones": {"carrier": [], "evidence": [], "scratch": [], "other": []},
    }
    for p in sorted(ws.rglob("*")):
        if not p.is_file():
            continue
        # Skip .git
        if ".git" in p.parts:
            continue
        zone = classify(p)
        if zone == "scratch" and not include_scratch:
            continue
        rel = str(p.relative_to(ws))
        manifest["zones"][zone].append({
            "path": rel,
            "sha256": sha256_file(p),
            "size": p.stat().st_size,
        })
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
