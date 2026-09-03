#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""answer_key_lint.py — 单个 answer-key yaml 的质量门。

按 COLLECTION_PROTOCOL.md §5 步骤 7 调用。

检查清单（fail-closed，任何一项错就 exit 1）：
  1. schema 校验（scripts/bench_answer_key.validate_key）
     — 必填字段齐
     — 每 PQ matcher ∈ 4 选 1
  2. PQ expected 与顶层字段一致性
     — pq-001-family.expected == top-level family
     — pq-002-c2-protocol.expected == top-level c2[]
     — S3 pq-101-packer-family.expected == packer_family
     — ...
  3. normalize_ioc 跑通每个 expected（normalized-ioc matcher 必须）
     — 输出 normalized 形式给用户对比

用法：
  python scripts/answer_key_lint.py kunglao-bench/answer-keys/<id>.yaml
  python scripts/answer_key_lint.py kunglao-bench/answer-keys/  # 整目录
  python scripts/answer_key_lint.py <path> --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench_answer_key  # noqa: E402

# pq_id → 顶层字段名映射（COLLECTION_PROTOCOL §1-4）
_PQ_TO_FIELD: dict[str, str] = {
    # S1 / S2
    "pq-001-family": "family",
    "pq-002-c2-protocol": "c2",
    "pq-003-mutex-name": "mutex",
    "pq-004-persistence": "persistence",
    "pq-005-injection": "injection",
    "pq-006-crypto": "crypto",
    "pq-007-config-format": "config_format",
    "pq-008-attck": "attck",
    # S3
    "pq-101-packer-family": "packer_family",
    "pq-102-dex-recoverable": "dex_recoverable",
    "pq-103-native-entries": "native_entry",
    "pq-104-protections": "protections",
    "pq-105-core-functions": "core_functions",
    # S4
    "pq-201-packer-family": "packer_family",
    "pq-202-solution-digest": "solution_digest",
    "pq-203-key-check": "key_check",
}


def _check_consistency(key: dict) -> list[str]:
    """PQ expected 必须与对应顶层字段一致（数据完整性）。"""
    errs: list[str] = []
    for pq in key.get("pqs") or []:
        pid = str(pq.get("pq_id") or "")
        field = _PQ_TO_FIELD.get(pid)
        if field is None:
            errs.append(f"PQ '{pid}': unknown pq_id (not in COLLECTION_PROTOCOL §1-4)")
            continue
        if field not in key:
            errs.append(f"PQ '{pid}': top-level field '{field}' missing")
            continue
        top = key[field]
        exp = pq.get("expected")
        if isinstance(top, list):
            if not isinstance(exp, list) or sorted(map(str, top)) != sorted(map(str, exp)):
                errs.append(f"PQ '{pid}': expected != top-level {field}[]")
        else:
            if str(top).strip() != str(exp).strip():
                errs.append(f"PQ '{pid}': expected ({exp!r}) != top-level "
                            f"{field} ({top!r})")
    return errs


def _check_normalizable(key: dict) -> list[str]:
    """对每个 normalized-ioc / set-subset matcher 的 expected，
    跑 normalize_ioc；异常 / 归一化前后空串都报错。"""
    errs: list[str] = []
    for pq in key.get("pqs") or []:
        pid = str(pq.get("pq_id") or "")
        matcher = pq.get("matcher")
        if matcher not in ("normalized-ioc", "set-subset"):
            continue
        exp = pq.get("expected")
        items = exp if isinstance(exp, list) else [exp]
        for raw in items:
            if not isinstance(raw, str):
                continue
            try:
                norm = bench_answer_key.normalize_ioc(raw)
            except Exception as exc:
                errs.append(f"PQ '{pid}': normalize_ioc({raw!r}) raised {exc}")
                continue
            if not norm:
                errs.append(f"PQ '{pid}': normalize_ioc({raw!r}) → empty")
    return errs


def _normalize_preview(key: dict) -> dict[str, str]:
    """输出 expected 归一化预览（不报错；给用户对照）。"""
    out: dict[str, str] = {}
    for pq in key.get("pqs") or []:
        matcher = pq.get("matcher")
        if matcher != "normalized-ioc":
            continue
        str(pq.get("pq_id") or "")
        exp = pq.get("expected")
        items = exp if isinstance(exp, list) else [exp]
        for raw in items:
            if isinstance(raw, str) and raw:
                out[raw] = bench_answer_key.normalize_ioc(raw)
    return out


def lint_one(path: Path) -> dict:
    """lint 单个 yaml；返回 {ok, errors[], warnings[], preview{}}。"""
    try:
        key = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return {"ok": False, "errors": [f"yaml unreadable: {exc}"],
                "warnings": [], "preview": {}}
    if not isinstance(key, dict):
        return {"ok": False, "errors": ["yaml: not a mapping"],
                "warnings": [], "preview": {}}

    errs: list[str] = []
    errs.extend(bench_answer_key.validate_key(key))
    errs.extend(_check_consistency(key))
    errs.extend(_check_normalizable(key))

    return {"ok": not errs, "errors": errs, "warnings": [],
            "preview": _normalize_preview(key)}


def main() -> int:
    ap = argparse.ArgumentParser(description="answer-key yaml 质量门")
    ap.add_argument("path", type=Path,
                    help="单个 yaml 或目录（目录下所有 *.yaml）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.path.is_dir():
        files = sorted(args.path.glob("*.yaml"))
    else:
        files = [args.path]

    if not files:
        print(f"FAIL: no yaml files under {args.path}", file=sys.stderr)
        return 2

    all_results = []
    any_fail = False
    for f in files:
        r = lint_one(f)
        r["path"] = str(f)
        all_results.append(r)
        if not r["ok"]:
            any_fail = True

    if args.json:
        print(json.dumps(all_results, ensure_ascii=False, indent=2))
    else:
        for r in all_results:
            status = "PASS" if r["ok"] else "FAIL"
            print(f"{status}: {r['path']}")
            for e in r["errors"]:
                print(f"  ERR: {e}")
            for orig, norm in r["preview"].items():
                if orig != norm:
                    print(f"  norm: {orig!r} → {norm!r}")

    return 1 if any_fail else 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())