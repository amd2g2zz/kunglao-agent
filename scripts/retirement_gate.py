#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retirement_gate.py — 机器绑定治理门（#861）。

退役/弃用必须由机器执行，不由 prose 承诺（#819 关单审计 D2：priority.py
DEPRECATED=True 但 external_kicker 仍在活体调用——"关单未删码"复发形态）。

检查（对 hooks/ + scripts/ 扫描；tests/ 豁免）：
  1. RETIRED 正则散副本：`DISPATCH_RE` 标识符出现在 owner/白名单之外
     （owner = hooks/lib_kunglao.py + scripts/lib_kunglao.py 孪生；
     #863-d 起 dispatch_gate 的 compat re-export 已退役，白名单不再含它）
  2. DEPRECATED = True 模块的活体 caller：import/from-import 出现在
     其他 scripts/hooks 模块 → 记 finding（已知债务入基线文件）

基线棘轮：`scripts/.retirement-gate-baseline.txt`，每行一个 finding key；
findings ⊆ baseline → exit 0（已知债务，挂账 #867 清偿）；新 finding → exit 1。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RETIRE_TOKEN = "DISPATCH_RE"
OWNER_ALLOWLIST = {
    "hooks/lib_kunglao.py",    # canonical owner
    "scripts/lib_kunglao.py",  # #770 twin
}
SELF = "scripts/retirement_gate.py"
DEPRECATED_RE = re.compile(r"^DEPRECATED\s*=\s*True\b", re.MULTILINE)


def _import_re(mod: str) -> "re.Pattern":
    return re.compile(
        r"^\s*(?:import\s+" + re.escape(mod) + r"\b|from\s+" + re.escape(mod) + r"\b)",
        re.MULTILINE)


def _py_files(root: Path) -> dict:
    out: dict = {}
    for sub in ("hooks", "scripts"):
        d = root / sub
        if d.is_dir():
            for f in sorted(d.glob("*.py")):
                out[f.relative_to(root).as_posix()] = f
    return out


def scan(root: Path, baseline: list) -> dict:
    files = _py_files(root)
    findings: list = []
    for rel, f in files.items():
        if rel in OWNER_ALLOWLIST or rel == SELF:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if RETIRE_TOKEN in text:
            findings.append("retired_regex_copy:" + rel)
    deprecated = {}
    for rel, f in files.items():
        if rel.startswith("scripts/") and DEPRECATED_RE.search(
                f.read_text(encoding="utf-8", errors="replace")):
            deprecated[rel] = f
    for rel, f in deprecated.items():
        mod = Path(rel).stem
        pat = _import_re(mod)
        for rel2, f2 in files.items():
            if rel2 == rel or rel2 == SELF:
                continue
            if pat.search(f2.read_text(encoding="utf-8", errors="replace")):
                findings.append("deprecated_live_caller:" + mod + "<-" + rel2)
    keys = sorted(set(findings))
    new = [k for k in keys if k not in baseline]
    return {"ok": not new, "findings": keys, "new_findings": new,
            "baseline_count": len(baseline)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    ap.add_argument("--baseline", default="scripts/.retirement-gate-baseline.txt")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = Path(a.repo).resolve()
    bpath = root / a.baseline
    baseline: list = []
    if bpath.exists():
        baseline = [ln.strip() for ln in
                    bpath.read_text(encoding="utf-8").splitlines() if ln.strip()]
    r = scan(root, baseline)
    if a.json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        for k in r["findings"]:
            mark = "BASELINE" if k in baseline else "NEW"
            print("[" + mark + "] " + k)
        print("ok" if r["ok"] else "new findings present - retire them or extend baseline")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
