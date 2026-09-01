#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intake_one.py — 单条 entry 立即验证。

按 COLLECTION_PROTOCOL.md §5 步骤 5 调用。用户填完一条 entry + 写完 sha256
后立即跑，不必等 30 条齐。

检查项（基于 bench_intake.check 单条版本）：
  1. stratum ∈ S1..S4
  2. path 存在 + 出 REPO_ROOT
  3. sha256 匹配 vault 文件
  4. first_seen ≥ MODEL_CUTOFF (2025-08)
  5. truth_sources ≥ 2 OR (1 + A+ tier)
  6. scoring_pqs / excluded_pqs 都是 list

用法：
  python scripts/intake_one.py <manifest.yaml> --entry-id <id>
  python scripts/intake_one.py <manifest.yaml> --entry-id <id> --json

返回 exit 0 = PASS；exit 1 = 有 violations。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_intake  # noqa: E402


def _find_entry(manifest: dict, entry_id: str) -> dict | None:
    for e in manifest.get("samples") or []:
        if str(e.get("id") or "") == entry_id:
            return e
    return None


def _check_single_entry(entry: dict) -> dict:
    """逐项校验单条 entry；返回 {ok, violations[]}。"""
    viols: list[str] = []
    sid = str(entry.get("id") or "<missing>")

    # stratum
    stratum = str(entry.get("stratum") or "")
    if stratum not in bench_intake.STRATA:
        viols.append(f"{sid}: bad stratum {stratum!r} "
                     f"(valid: {bench_intake.STRATA})")

    # path + sha256
    p = Path(str(entry.get("path") or ""))
    if not p.is_file():
        viols.append(f"{sid}: sample file missing: {p}")
    else:
        actual = bench_intake._sha256(p)
        expected_sha = str(entry.get("sha256") or "").lower()
        if actual != expected_sha:
            viols.append(f"{sid}: sha256 mismatch (manifest={expected_sha[:12]}..., "
                         f"actual={actual[:12]}...)")

    # path 出 REPO_ROOT
    repo_root = Path(bench_intake.REPO_ROOT).resolve()
    try:
        inside = p.resolve().is_relative_to(repo_root)
    except (OSError, ValueError):
        inside = False
    if inside:
        viols.append(f"{sid}: sample path inside repo (git hygiene)")

    # first_seen
    fs = str(entry.get("first_seen") or "")
    if fs < bench_intake.MODEL_CUTOFF:
        viols.append(f"{sid}: first_seen {fs!r} < MODEL_CUTOFF "
                     f"{bench_intake.MODEL_CUTOFF}")

    # truth_sources
    tier = str(entry.get("truth_tier") or "")
    sources = entry.get("truth_sources") or []
    if not isinstance(sources, list):
        viols.append(f"{sid}: truth_sources must be a list")
    elif tier == "A+":
        if len(sources) < 1:
            viols.append(f"{sid}: tier=A+ requires ≥1 source")
    else:
        if len(sources) < 2:
            viols.append(f"{sid}: tier={tier!r} requires ≥2 sources (single-source rejected)")

    # scoring_pqs / excluded_pqs
    if not isinstance(entry.get("scoring_pqs"), list):
        viols.append(f"{sid}: scoring_pqs must be a list")
    if not isinstance(entry.get("excluded_pqs"), list):
        viols.append(f"{sid}: excluded_pqs must be a list")

    return {"ok": not viols, "violations": viols}


def main() -> int:
    ap = argparse.ArgumentParser(description="单条 entry 立即验证")
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--entry-id", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        manifest = yaml.safe_load(Path(args.manifest).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"FAIL: manifest unreadable: {exc}", file=sys.stderr)
        return 2

    entry = _find_entry(manifest, args.entry_id)
    if entry is None:
        print(f"FAIL: entry-id '{args.entry_id}' not found in {args.manifest}",
              file=sys.stderr)
        return 2

    result = _check_single_entry(entry)
    result["entry_id"] = args.entry_id

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"{status}: {args.entry_id}")
        for v in result["violations"]:
            print(f"  ERR: {v}")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())