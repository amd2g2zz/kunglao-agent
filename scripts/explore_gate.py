#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""explore_gate.py — M1 DECIDE 探索阶段判定 (module-design.md M1.2 L119-121, design-spec §3.2 L132-134).

count < threshold → 探索模式(按 cheapness 铺开 T1)。契约空白: EXPLORE_THRESHOLD = 5
(verified facts 数)。

用法:
  python explore_gate.py <verified_fact_count> [--threshold N]
Exit: 0 = 探索模式(explore), 1 = 利用模式(exploit)。
"""
from __future__ import annotations

import argparse
import sys

EXPLORE_THRESHOLD = 5  # 契约空白冻结: verified facts 阈值


def explore_gate(verified_fact_count: int, threshold: int = EXPLORE_THRESHOLD) -> bool:
    """count < threshold → 探索模式(True); 否则利用模式(False)."""
    if threshold < 0:
        raise ValueError(f"explore_gate: threshold 必须 >= 0, 收到 {threshold}")
    return verified_fact_count < threshold


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="kunglao-agent M1 explore gate")
    ap.add_argument("count", type=int, help="verified fact count")
    ap.add_argument("--threshold", type=int, default=EXPLORE_THRESHOLD)
    args = ap.parse_args(argv)
    explore = explore_gate(args.count, args.threshold)
    print("EXPLORE (cheap T1 spread)" if explore else "EXPLOIT (ratio-key ranking)")
    return 0 if explore else 1


if __name__ == "__main__":
    sys.exit(main())
