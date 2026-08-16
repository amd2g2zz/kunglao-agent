#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""explore_gate.py — M1 DECIDE exploration-phase gate (module-design.md M1.2 L119-121, design-spec §3.2 L132-134).

count < threshold → explore mode (spread T1 by cheapness). Contract-gap
freeze: EXPLORE_THRESHOLD = 5 (verified-fact count).

Usage:
  python explore_gate.py <verified_fact_count> [--threshold N]
Exit: 0 = explore mode, 1 = exploit mode.
"""
from __future__ import annotations

import argparse
import sys

EXPLORE_THRESHOLD = 5  # contract-gap freeze: verified-fact threshold


def explore_gate(verified_fact_count: int, threshold: int = EXPLORE_THRESHOLD) -> bool:
    """count < threshold → explore mode (True); else exploit mode (False)."""
    if threshold < 0:
        raise ValueError(f"explore_gate: threshold must be >= 0, got {threshold}")
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
