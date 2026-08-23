# -*- coding: utf-8 -*-
"""tools/_lib/workspace_manifest.py — workspace carrier manifest (#538 item 2).

The disk-side snapshot of "which carriers init materialized". kunglao-resume
(#466) consumes it to diff the current workspace against the init-time
carrier set ("init had N carriers; missing now: {list}") — turning
"没有 ≠ 还没" (absent vs not-yet-decided) into a mechanical judgment.

The carrier list here mirrors docs/workspace-manifest.md (the contract doc)
and scripts/kunglao-init.py SCAFFOLD_DIRS/CARRIER_READMES. The doc owns the
contract; this module owns the snapshot format:

    {
      "schema_rev": "v1",
      "carriers": [
        {"path": "facts", "kind": "dir", "exists": true, "sha256_short": "..."},
        ...
      ]
    }

`writer` provenance is deliberately NOT in the JSON (the doc carries the
narrative; the snapshot stays byte-stable across doc edits).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SCHEMA_REV = "v1"
MANIFEST_NAME = ".workspace-manifest.json"

# Every carrier init must materialize (dir rows match SCAFFOLD_DIRS order;
# file rows match the scaffold stubs). Order is part of the format — stable
# diffs require stable serialization.
CARRIERS = (
    {"path": "facts", "kind": "dir"},
    {"path": "notes", "kind": "dir"},
    {"path": "analyses", "kind": "dir"},
    {"path": "evidence", "kind": "dir"},
    {"path": "blockers", "kind": "dir"},
    {"path": "runs", "kind": "dir"},
    {"path": "runs/logs", "kind": "dir"},
    {"path": "hypotheses", "kind": "dir"},
    {"path": "scratch", "kind": "dir"},  # free-zone: listed so "exists" is answerable, never diff-enforced
    {"path": "claim-register.yaml", "kind": "file"},
    {"path": "facts/_INDEX.md", "kind": "file"},
)


def _sha256_short(p: Path) -> str:
    """12-hex digest: file bytes, or the sorted relative path list of a dir
    (content-agnostic for dirs — the manifest answers existence, not content)."""
    h = hashlib.sha256()
    if p.is_file():
        h.update(p.read_bytes())
    else:
        for child in sorted(
                x.relative_to(p).as_posix() for x in p.rglob("*")):
            h.update(child.encode("utf-8"))
    return h.hexdigest()[:12]


def write_manifest(ws: Path) -> Path:
    """Snapshot the carrier set next to the workspace root; returns the path.

    Idempotent: rewrites the same file (init calls it on every scaffold)."""
    ws = Path(ws)
    rows = []
    for carrier in CARRIERS:
        target = ws / carrier["path"]
        exists = target.exists()
        rows.append({
            "path": carrier["path"],
            "kind": carrier["kind"],
            "exists": exists,
            "sha256_short": _sha256_short(target) if exists else "",
        })
    payload = {"schema_rev": SCHEMA_REV, "carriers": rows}
    out = ws / MANIFEST_NAME
    out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return out


def read_manifest(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_rev") != SCHEMA_REV:
        raise ValueError(
            f"{path}: unsupported manifest schema_rev "
            f"{data.get('schema_rev') if isinstance(data, dict) else type(data).__name__!r}"
            f" (expected {SCHEMA_REV!r})")
    return data


def diff_manifest(ws: Path, manifest: dict) -> dict:
    """Current workspace vs the init-time snapshot: {missing, changed}.

    `missing`: contract carriers the snapshot recorded as existing but that
    are gone now (the resume alarm). `changed`: sha256_short drift on file
    carriers. scratch/ is free-zone — existence drift on it is reported but
    under free_zone_missing so consumers can treat it as informational."""
    ws = Path(ws)
    missing: list[str] = []
    changed: list[str] = []
    free_zone_missing: list[str] = []
    for c in manifest.get("carriers", []):
        target = ws / c["path"]
        if c.get("exists") and not target.exists():
            if c["path"] == "scratch":
                free_zone_missing.append(c["path"])
            else:
                missing.append(c["path"])
        elif (c.get("exists") and c.get("kind") == "file"
              and _sha256_short(target) != c.get("sha256_short")):
            changed.append(c["path"])
    return {
        "missing": sorted(missing),
        "changed": sorted(changed),
        "free_zone_missing": sorted(free_zone_missing),
    }
