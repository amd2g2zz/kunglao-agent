#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/yara-scan.py — rule-based byte scanning (issue #313).

Fresh kunglao-native implementation (the upstream findcrypt-yara is an IDA
plugin; only its curated rules file was absorbed as data — see
tools/static/yara-rules/). Engine: yara-python.

Contract (#277): parameterized (--binary/--rules), three-state exits
(0 = hits, 1 = no hits, 2 = error with guidance), --json single object,
--reproduce field=value lines for the L1 gate, UTF-8 stdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402
ensure_utf8_stdout()

BUNDLED_RULES_DIR = Path(__file__).resolve().parent / "yara-rules"

EXIT_OK = 0
EXIT_NEGATIVE = 1
EXIT_ERROR = 2


def _error(msg: str) -> int:
    print(json.dumps({"error": msg, "exit_code": EXIT_ERROR}), file=sys.stderr)
    return EXIT_ERROR


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="yara-scan.py",
        description="rule-based byte scanning (yara engine; issue #313)")
    ap.add_argument("--binary", required=True, help="file to scan")
    ap.add_argument("--rules", default=None,
                    help="comma-separated rule file/dir paths (default: bundled "
                         f"{BUNDLED_RULES_DIR.name}/)")
    ap.add_argument("--max-hits", type=int, default=200,
                    help="report at most N hits (default 200)")
    ap.add_argument("--json", action="store_true",
                    help="single JSON object on stdout")
    ap.add_argument("--reproduce", action="store_true",
                    help="field=value lines for the kunglao L1 gate")
    return ap.parse_args(argv)


def _load_engine():
    try:
        import yara  # noqa: PLC0415 — lazy import keeps --help degrade clean
    except ImportError:
        print(json.dumps({
            "error": "yara engine missing — install with: "
                     "`uv pip install yara-python` (NOT the `yara` package)",
            "exit_code": EXIT_ERROR}), file=sys.stderr)
        sys.exit(EXIT_ERROR)
    return yara


def _resolve_rules(spec: str | None) -> list[Path]:
    if spec:
        paths = [Path(p) for p in spec.split(",")]
    else:
        paths = [BUNDLED_RULES_DIR]
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(sorted(p.glob("*.yar")))
            files.extend(sorted(p.glob("*.yara")))
        elif p.is_file():
            files.append(p)
        else:
            print(json.dumps({
                "error": f"rule path not found: {p} — pass a .yar file or a "
                         f"directory of rules (see --help)",
                "exit_code": EXIT_ERROR}), file=sys.stderr)
            sys.exit(EXIT_ERROR)
    if not files:
        print(json.dumps({
            "error": f"no rule files found under: {[str(p) for p in paths]} "
                     f"— expected *.yar / *.yara",
            "exit_code": EXIT_ERROR}), file=sys.stderr)
        sys.exit(EXIT_ERROR)
    return files


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    binary = Path(args.binary)
    try:
        data = binary.read_bytes()
    except OSError as exc:
        return _error(f"cannot read --binary {args.binary}: {exc} — check the "
                      f"path exists and is readable")

    yara = _load_engine()
    rule_files = _resolve_rules(args.rules)
    try:
        rules = yara.compile(filepaths={str(p): str(p) for p in rule_files})
    except yara.Error as exc:
        return _error(f"rule compilation failed: {exc} — check rule syntax in "
                      f"{[p.name for p in rule_files]}")

    hits: list[dict] = []
    for match in rules.match(data=data):
        for s in match.strings:
            instances = s.instances if hasattr(s, "instances") else [s]
            for inst in instances:
                matched = bytes(inst.matched_data)
                hits.append({
                    "rule": match.rule,
                    "namespace": match.namespace,
                    "offset": int(inst.offset),
                    "length": len(matched),
                    "preview": matched[:16].hex(),
                    "tags": list(match.tags),
                })
    hits.sort(key=lambda h: (h["offset"], h["rule"]))
    hits = hits[: args.max_hits]

    data_sha = hashlib.sha256(data).hexdigest()
    if args.reproduce:
        print("tool=yara-scan")
        print(f"binary_sha256={data_sha}")
        print(f"rule_files={len(rule_files)}")
        print(f"hit_count={len(hits)}")
        for i, h in enumerate(hits[:10]):
            print(f"hit{i}_rule={h['rule']}")
            print(f"hit{i}_offset={h['offset']}")
            print(f"hit{i}_len={h['length']}")
    elif args.json:
        print(json.dumps({
            "tool": "yara-scan",
            "binary": str(binary),
            "binary_sha256": data_sha,
            "rule_files": [str(p) for p in rule_files],
            "hit_count": len(hits),
            "hits": hits,
        }, ensure_ascii=False))
    else:
        for h in hits:
            print(f"{h['offset']:>10}  {h['rule']}  len={h['length']} "
                  f"preview={h['preview']}")
        print(f"-- {len(hits)} hit(s) from {len(rule_files)} rule file(s)")

    return EXIT_OK if hits else EXIT_NEGATIVE


if __name__ == "__main__":
    sys.exit(main())
