#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""relib_audit.py — #817 re-library 知识库审查器。

三类问题检出 + 可逆 quarantine + 质量度量：
  孤儿        .md 文件未出现在任何 _index-*.md / _INDEX.md 目录中
              （recall 引擎永不返回 = 等于不存在）
  tracker 残留  正文含历史卡号字样 #NNN（内容策展归人工，机制只检出计量）
  声明行缺失    文件尾缺 worker 反馈声明 `recall_useful:`——缺失则
              feedback 管道对声明维度的数据永远为空

CLI:
  python scripts/relib_audit.py <lib_dir> [--json]
  python scripts/relib_audit.py --quarantine <lib_dir> <file.md> --reason <why>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_TRACKER_RE = re.compile(r"#\d{3}\b")
_MD_REF_RE = re.compile(r"\b([A-Za-z0-9-]+\.md)\b")
_DECL = "recall_useful:"


def _catalog(lib: Path) -> set:
    """被任何 _index-*.md（及顶层 _INDEX.md）提及的文件名集合。"""
    catalog: set = set()
    index_files = sorted(lib.glob("_index-*.md"))
    top = lib / "_INDEX.md"
    if top.exists():
        index_files.append(top)
    for f in index_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        catalog |= set(_MD_REF_RE.findall(text))
    return catalog


def audit(lib_dir) -> dict:
    """审查库目录。返回 {orphans, trackers, missing_decl, counts, metrics}。"""
    lib = Path(lib_dir)
    catalog = _catalog(lib)
    files = sorted(p for p in lib.glob("*.md") if not p.name.startswith("_"))
    orphans = [p.name for p in files if p.name not in catalog]
    trackers: dict = {}
    missing_decl: list = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        tids = sorted(set(_TRACKER_RE.findall(text)))
        if tids:
            trackers[p.name] = tids
        if _DECL not in text:
            missing_decl.append(p.name)
    return {
        "orphans": orphans,
        "trackers": trackers,
        "missing_decl": missing_decl,
        "counts": {"orphans": len(orphans), "trackers": len(trackers),
                   "missing_decl": len(missing_decl)},
        "metrics": {"files_total": len(files)},
    }


def quarantine(lib_dir, name: str, reason: str):
    """孤儿文件可逆隔离：移入 archive/ 并留 manifest 记账。

    拒绝对已收录（非孤儿）文件执行——archive 只收孤儿。
    """
    lib = Path(lib_dir)
    if name in _catalog(lib):
        raise ValueError(f"refusing to quarantine indexed file: {name}")
    src = lib / name
    if not src.is_file():
        raise FileNotFoundError(f"not a file in library: {name}")
    arch = lib / "archive"
    arch.mkdir(parents=True, exist_ok=True)
    dest = arch / name
    src.replace(dest)
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = arch / "quarantine-manifest.yaml"
    with manifest.open("a", encoding="utf-8") as fh:
        fh.write(f"- file: {name}\n  reason: {reason}\n  quarantined_at: {now}\n")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description="re-library 审查器 (#817)")
    ap.add_argument("lib_dir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quarantine", metavar="FILE")
    ap.add_argument("--reason", default="orphan-audit")
    args = ap.parse_args()
    lib = Path(args.lib_dir)
    if args.quarantine:
        dest = quarantine(lib, args.quarantine, args.reason)
        print(f"quarantined: {args.quarantine} -> {dest}")
        return 0
    r = audit(lib)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(f"files={r['metrics']['files_total']} "
              f"orphans={r['counts']['orphans']} "
              f"trackers={r['counts']['trackers']} "
              f"missing_decl={r['counts']['missing_decl']}")
        for name, tids in sorted(r["trackers"].items()):
            print(f"  tracker {name}: {', '.join(tids)}")
        if r["orphans"]:
            print("  orphans: " + ", ".join(r["orphans"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
