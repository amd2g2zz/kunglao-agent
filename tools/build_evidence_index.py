#!/usr/bin/env python3
"""build_evidence_index.py — evidence index builder (P1, PRD evidence-integrity-icd203).

扫 workspace 的 raw 证据(evidence/ + analysis_artifacts/),注册进 evidence/_index.json
(权威)+ _INDEX.md(生成)。派生(summary.json/correlated.json/verdict.json)不算证据,排除。

每条:{eid, path(ws-relative, /), sha256, size, type}。
派生不进 index → P2 provenance gate 拒"引派生"的 fact(派生 path 不在 index → invalid)。

用法: python build_evidence_index.py <workspace> [--write]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DERIVATION_NAMES = {"summary.json", "correlated.json", "verdict.json",
                    "loop-state.json", ".heartbeat.json", "_index.json"}
SCAN_DIRS = ("evidence", "analysis_artifacts")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _classify(rel_path: str) -> str:
    name = rel_path.lower()
    if "capture" in name:
        return "capture"
    if "trace" in name:
        return "trace"
    if "dump" in name:
        return "dump"
    if "yara" in name:
        return "yara-scan"
    if name.endswith((".pcap", ".pcapng")):
        return "pcap"
    if name.endswith(".json"):
        return "json"
    if name.endswith(".txt"):
        return "text"
    return "other"


def _is_derivation(p: Path) -> bool:
    return p.name in DERIVATION_NAMES


def build_index(ws: Path) -> dict:
    """扫 ws 的 raw 证据,返回 {entries: [...]}。派生排除。"""
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
            if p.name in ("_INDEX.md", "_index.json"):
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
    return {"entries": entries, "schema": "evidence-index-v1"}


def _render_md(idx: dict) -> str:
    L = ["# Evidence Index", "", "| eid | path | sha256(前12) | size | type |",
         "|---|---|---|---|---|"]
    for e in idx["entries"]:
        L.append(f"| {e['eid']} | {e['path']} | {e['sha256'][:12]} | {e['size']} | {e['type']} |")
    return "\n".join(L) + "\n"


def build_and_write(ws: Path) -> Path:
    idx = build_index(ws)
    idx["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_dir = ws / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "_index.json"
    md_path = out_dir / "_INDEX.md"
    json_path.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_md(idx), encoding="utf-8")
    return json_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="build_evidence_index.py", description="证据索引构建")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    if args.write:
        p = build_and_write(ws)
        n = len(json.loads(p.read_text(encoding="utf-8"))["entries"])
        print(f"evidence index written: {p} ({n} entries)")
    else:
        idx = build_index(ws)
        print(json.dumps(idx, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
