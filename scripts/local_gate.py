#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""local_gate.py — 本地质量门统一入口（cwd 免疫）。

背景（2026-09-01）：后台启动会系统性丢弃 `cd X &&` 前缀——按目录假设写的
门命令在主仓静默执行，产出误导性结果（两次事故）。本脚本用 __file__
自定位仓库根并 os.chdir，任何 cwd 下行为一致。

用法（前台/后台等价）：
    python <worktree>/scripts/local_gate.py            # 全量：pytest+discovery-gate+ext-scan+manifest
    python <worktree>/scripts/local_gate.py --skip-pytest  # 只跑 gate+ext-scan+manifest
Exit：任一步失败非零。输出固定追加到 stdout（后台重定向友好）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list, timeout: int | None = None) -> int:
    print(f"[local_gate] $ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd).returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-pytest", action="store_true",
                    help="跳过 pytest 全量（调试 manifest/ext 面时用）")
    args = ap.parse_args()

    os.chdir(ROOT)  # cwd 免疫：一切以 __file__ 定位的仓库根为准
    print(f"[local_gate] repo root = {ROOT}", flush=True)

    failures = []
    if not args.skip_pytest:
        if _run([sys.executable, "-m", "pytest", "tests", "-q"]) != 0:
            failures.append("pytest")
    qg = ROOT / "devkit" / "quality_gates.py"
    if _run([sys.executable, str(qg), "9", "--quiet"]) != 0:
        failures.append("discovery-gate")
    if _run([sys.executable, str(ROOT / "tools" / "ext-scan.py")]) != 0:
        failures.append("ext-scan")
    dm = ROOT / "scripts" / "deploy_manifest.py"
    if _run([sys.executable, str(dm), "--verify"]) != 0:
        # 允许先 --write 再复验一次（首次接入新 hooks 面时清单会扩充）
        if _run([sys.executable, str(dm), "--write"]) == 0:
            if _run([sys.executable, str(dm), "--verify"]) != 0:
                failures.append("deploy-manifest")
        else:
            failures.append("deploy-manifest")

    if failures:
        print(f"[local_gate] FAIL: {', '.join(failures)}", flush=True)
        return 1
    print("[local_gate] ALL GREEN", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
