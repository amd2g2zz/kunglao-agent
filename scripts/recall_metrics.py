#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recall_metrics.py — #814 recall 注入质量度量面。

追加式 jsonl 落盘（runs/.recall-metrics.jsonl）：每次 recall 注入/跳过记一行
{ts, kind, query, files, reason}。summarize() 聚合 injected/skipped/no_match
计数——#833 优化器与"召回改进只认 precision"裁决的输入口。纯 workspace
本地遥测，不动 references/ 字典本体。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

METRICS_FILE = ".recall-metrics.jsonl"
KINDS = ("injected", "skipped", "no_match")


def _metrics_path(ws: Path) -> Path:
    return Path(ws) / "runs" / METRICS_FILE


def record(ws: Path, kind: str, query: str, files: int = 0,
           reason: str = "") -> None:
    """追加一行度量事件。任何 IO 异常向上抛——fail-open 决策归调用方。"""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}: {kind!r}")
    ws = Path(ws)
    runs = ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kind": kind,
        "query": str(query)[:200],
        "files": int(files),
        "reason": str(reason)[:200],
    }
    with _metrics_path(ws).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def summarize(ws: Path) -> dict:
    """聚合度量：按 kind 计数 + total。文件缺失/坏行容忍（skip 坏行）。"""
    p = _metrics_path(ws)
    summary = {k: 0 for k in KINDS}
    summary["total"] = 0
    if not p.is_file():
        return summary
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = row.get("kind")
        if kind in summary and kind != "total":
            summary[kind] += 1
            summary["total"] += 1
    return summary
