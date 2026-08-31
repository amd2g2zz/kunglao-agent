#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""write_guard_unlock.py — #820 解锁/迁移通道。

三条命令（全部落账 kunglao_log）：
  unlock     豁免目标文件自身的 lint 违规（迁移中重写合法化）。
             存储 runs/write-guard-waivers.yaml；write_guard 消费时落
             write_guard_waiver_used。
  quarantine 把 facts/<name> 移入 facts/_quarantine/（lint glob 非递归，
             天然退出语料）并落账 write_guard_quarantine。
  list       当前豁免与隔离清单。

失败语义：目标不存在 rc=2；成功 rc=0。本 CLI 不绕过 write_guard 的
R1/R2/supersedes/proven-gate 腿——它只管 lint 打击面收窄（#820）。
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _ledger(ws, action, artifact, detail):
    try:
        import kunglao_log
        kunglao_log.emit(ws, actor="operator", action=action,
                         artifact=artifact, detail=str(detail)[:2000])
    except Exception as exc:  # noqa: BLE001 — log never breaks the CLI
        print(f"write_guard_unlock: warning: {exc}", file=sys.stderr)


def _waiver_path(ws: Path) -> Path:
    return ws / "runs" / "write-guard-waivers.yaml"


def load_waivers(ws: Path) -> dict:
    p = _waiver_path(ws)
    if not p.is_file():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def cmd_unlock(ws: Path, fname: str, reason: str) -> int:
    f = ws / "facts" / fname
    if not f.is_file():
        print(f"FAIL: {fname} not in facts/", file=sys.stderr)
        return 2
    w = load_waivers(ws)
    w[fname] = {"reason": reason, "ts": _now_iso()}
    _waiver_path(ws).parent.mkdir(parents=True, exist_ok=True)
    _waiver_path(ws).write_text(yaml.safe_dump(w, allow_unicode=True, sort_keys=True), encoding="utf-8")
    _ledger(ws, "write_guard_unlock", fname, reason)
    print(f"OK: waived lint violations for {fname}")
    return 0


def cmd_quarantine(ws: Path, fname: str, reason: str) -> int:
    f = ws / "facts" / fname
    if not f.is_file():
        print(f"FAIL: {fname} not in facts/", file=sys.stderr)
        return 2
    qdir = ws / "facts" / "_quarantine"
    qdir.mkdir(exist_ok=True)
    target = qdir / fname
    if target.exists():
        print(f"FAIL: {target.name} already quarantined", file=sys.stderr)
        return 2
    f.rename(target)
    _ledger(ws, "write_guard_quarantine", fname, reason)
    print(f"OK: quarantined facts/{fname} -> facts/_quarantine/{fname}")
    return 0


def cmd_list(ws: Path) -> int:
    w = load_waivers(ws)
    qdir = ws / "facts" / "_quarantine"
    q = sorted(p.name for p in qdir.glob("*.md")) if qdir.is_dir() else []
    print("waivers:")
    for k in sorted(w):
        print(f"  {k}: {w[k].get('reason', '')} ({w[k].get('ts', '')})")
    print("quarantined:")
    for k in q:
        print(f"  {k}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="#820 write_guard 解锁/迁移通道")
    ap.add_argument("command", choices=["unlock", "quarantine", "list"])
    ap.add_argument("workspace", type=Path)
    ap.add_argument("--file", dest="fname")
    ap.add_argument("--reason", default="")
    args = ap.parse_args(argv)
    ws = args.workspace.resolve()
    if args.command == "list":
        return cmd_list(ws)
    if not args.fname:
        print("FAIL: --file required", file=sys.stderr)
        return 2
    if args.command == "unlock":
        return cmd_unlock(ws, args.fname, args.reason)
    return cmd_quarantine(ws, args.fname, args.reason)


if __name__ == "__main__":
    sys.exit(main())
