#!/usr/bin/env python3
"""build_evidence_index.py — evidence index builder (P1+P3, PRD evidence-integrity-icd203).

Scans the workspace's raw evidence (evidence/ + analysis_artifacts/) and registers it into evidence/_index.json
(authoritative) + _INDEX.md (generated). Derived artifacts (summary.json/correlated.json/verdict.json) are not evidence and are excluded.

Each entry: {eid, path (ws-relative, /), sha256, size, type, source_reliability}.
source_reliability = Admiralty rating (A-F x 1-6), mechanically defaulted by type, overridable via --rel.
Derived artifacts stay out of the index -> the P2 provenance gate rejects facts citing derived artifacts (a derived path not in the index -> invalid).

Usage: python tools/pipelines/build_evidence_index.py <workspace> [--write] [--out FILE] [--rel reliability_map.yaml]

#277 CLI contract: JSON is the default machine output (stdout, or --out FILE);
--write persists evidence/_index.json + _INDEX.md under the workspace. Exit
codes: 0 = success, 2 = operational error (missing workspace / unreadable --rel).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # non-TTY / captured stream without reconfigure (e.g. pytest capsys)

DERIVATION_NAMES = {"summary.json", "correlated.json", "verdict.json",
                    "loop-state.json", ".heartbeat.json", "_index.json"}
SCAN_DIRS = ("evidence", "analysis_artifacts")

# ── ICD-203 Source Reliability (Admiralty A-F × 1-6) ─────────────────
# A = completely reliable, F = unreliable
# 1 = confirmed by other sources, 6 = truth cannot be judged
DEFAULT_RELIABILITY: dict[str, str] = {
    # Direct observation — raw instrument capture, artifact dump
    "capture":   "A1",
    "trace":     "A1",
    "dump":      "A1",
    "pcap":      "A1",
    "binary":    "A1",
    # Tool-derived from artifact (one step removed)
    "decompile": "A2",
    "disasm":    "A2",
    # Tool pattern match (indirect)
    "yara-scan": "B2",
    # Raw instrument output (possibly indirect)
    "json":      "B3",
    # Unstructured text (source varies)
    "text":      "B3",
    # Third-party threat intelligence
    "cti":       "C5",
    # Third-party sandbox execution
    "sandbox":   "D3",
    # Unknown provenance — conservative default
    "other":     "C5",
}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _classify(rel_path: str) -> str:
    name = rel_path.lower()
    # Content/keyword-based classification (order matters: specific → generic)
    if "capture" in name:
        return "capture"
    if "trace" in name:
        return "trace"
    if "dump" in name:
        return "dump"
    if "decompile" in name:
        return "decompile"
    if "disasm" in name:
        return "disasm"
    if "yara" in name:
        return "yara-scan"
    if "cti" in name:
        return "cti"
    if "sandbox" in name:
        return "sandbox"
    # Extension-based fallback
    if name.endswith((".pcap", ".pcapng")):
        return "pcap"
    if name.endswith((".bin", ".exe", ".dll", ".sys", ".so")):
        return "binary"
    if name.endswith(".json"):
        return "json"
    if name.endswith(".txt"):
        return "text"
    return "other"


def _is_derivation(p: Path) -> bool:
    return p.name in DERIVATION_NAMES


def _default_reliability(etype: str) -> str:
    """Return mechanical default Admiralty code for an evidence type."""
    return DEFAULT_RELIABILITY.get(etype, "C5")


def _assign_reliability(entries: list[dict], rel_map: dict | None = None) -> None:
    """Assign source_reliability to each entry.

    Precedence: eid-specific override > type-specific override > mechanical default.
    rel_map format: {"E001": "A1", "by_type": {"json": "B3", ...}}
    """
    rel_map = rel_map or {}
    type_overrides = rel_map.get("by_type", {})
    for e in entries:
        eid = e["eid"]
        etype = e["type"]
        if eid in rel_map:
            e["source_reliability"] = rel_map[eid]
        elif etype in type_overrides:
            e["source_reliability"] = type_overrides[etype]
        else:
            e["source_reliability"] = _default_reliability(etype)


def build_index(ws: Path, rel_map: dict | None = None) -> dict:
    """Scan the ws raw evidence, return {entries: [...]}. Derived artifacts excluded.

    rel_map: optional override dict {"E001": "A1", "by_type": {"cti": "B2"}}.
    """
    ws = ws.resolve()
    entries: list[dict] = []
    for sub in SCAN_DIRS:
        root = ws / sub
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            if _is_derivation(p):
                continue
            # README.md is the #538 carrier stub, not raw evidence — skip
            # it or every scaffolded workspace indexes a fake entry.
            if p.name in ("_INDEX.md", "_index.json", "README.md"):
                continue
            rel = p.relative_to(ws).as_posix()
            entries.append({
                "eid": "",
                "path": rel,
                "sha256": _sha256(p),
                "size": p.stat().st_size,
                "type": _classify(rel),
            })
    entries.sort(key=lambda e: e["path"])
    for i, e in enumerate(entries, 1):
        e["eid"] = f"E{i:03d}"
    _assign_reliability(entries, rel_map)
    return {"entries": entries, "schema": "evidence-index-v1"}


def _render_md(idx: dict) -> str:
    L = ["# Evidence Index", "",
         "| eid | path | sha256(first 12) | size | type | source_reliability |",
         "|---|---|---|---|---|---|"]
    for e in idx["entries"]:
        L.append(
            f"| {e['eid']} | {e['path']} | {e['sha256'][:12]} | {e['size']} "
            f"| {e['type']} | {e.get('source_reliability', '-')} |"
        )
    return "\n".join(L) + "\n"


def build_and_write(ws: Path, rel_map: dict | None = None) -> Path:
    idx = build_index(ws, rel_map=rel_map)
    idx["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_dir = ws / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "_index.json"
    md_path = out_dir / "_INDEX.md"
    json_path.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(idx), encoding="utf-8")
    return json_path


def _load_rel_map(path: str) -> dict:
    """Load reliability override map from a YAML file."""
    import yaml
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return data or {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="build_evidence_index.py", description="evidence index builder")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--write", action="store_true",
                    help="write evidence/_index.json + _INDEX.md under the workspace")
    ap.add_argument("--out", metavar="FILE",
                    help="write the JSON index to FILE instead of stdout (#277)")
    ap.add_argument("--rel", metavar="reliability_map.yaml",
                    help="custom Admiralty reliability overrides (YAML)")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    if not ws.is_dir():
        print(f"error: workspace does not exist: {ws}", file=sys.stderr)
        return 2

    rel_map = _load_rel_map(args.rel) if args.rel else None

    if args.write:
        if args.out:
            idx = build_index(ws, rel_map=rel_map)
            idx["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(
                json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
            md_path = Path(args.out).with_name("_INDEX.md")
            md_path.write_text(_render_md(idx), encoding="utf-8")
            print(f"evidence index written: {Path(args.out).resolve()} "
                  f"({len(idx['entries'])} entries)")
        else:
            p = build_and_write(ws, rel_map=rel_map)
            n = len(json.loads(p.read_text(encoding="utf-8"))["entries"])
            print(f"evidence index written: {p} ({n} entries)")
    else:
        idx = build_index(ws, rel_map=rel_map)
        payload = json.dumps(idx, ensure_ascii=False, indent=2)
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(payload, encoding="utf-8")
        else:
            print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
