#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_answer_key.py — answer-key compiler (B2, #823 AB-VALUE).

Three jobs, all mechanical:
  1. validate_key — per-stratum schema (S1/S2 malware, S3 hardened
     Android, S4 packed PE/crackme).
  2. normalize_ioc — the ONE canonical IOC form (lowercase, scheme
     stripped, default ports stripped, IDN → punycode); every matcher
     routes through it.
  3. task_spec_pqs — generate the task-spec PQ entries carrying
     pq_id + question ONLY. The expected answer never leaves this
     module's input format: a leaked expected into a task-spec is a
     dead experiment (AB-DESIGN §5.3 leak rule).

Usage: bench_answer_key.py <answer-key.yaml> --task-spec-out <f>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

MATCHERS = ("exact", "set-subset", "normalized-ioc", "attck-id")

_REQUIRED_BY_STRATUM: dict[str, tuple[str, ...]] = {
    "S1": ("stratum", "family", "c2", "mutex", "persistence", "injection",
           "crypto", "attck", "config_format"),
    "S2": ("stratum", "family", "c2", "mutex", "persistence", "injection",
           "crypto", "attck", "config_format"),
    "S3": ("stratum", "packer_family", "dex_recoverable", "native_entry",
           "protections", "core_functions"),
    "S4": ("stratum", "packer_family", "solution_digest", "key_check"),
}

_DEFAULT_PORTS = ("80", "443")


def normalize_ioc(raw: str) -> str:
    """Canonical IOC form: lowercase → scheme stripped → default port
    stripped (non-default kept) → trailing slash stripped → IDN labels
    punycoded. Unparsable labels pass through unchanged."""
    v = str(raw).strip().lower()
    v = re.sub(r"^https?://", "", v)
    v = v.rstrip("/")
    host, _sep, rest = v.partition("/")
    if ":" in host:
        h, _, port = host.rpartition(":")
        if port in _DEFAULT_PORTS and h:
            host = h
    if not host.isascii():
        try:
            host = ".".join(
                label.encode("idna").decode("ascii")
                if label and not label.isascii() else label
                for label in host.split("."))
        except (UnicodeError, UnicodeDecodeError):
            pass
    return f"{host}/{rest}" if rest else host


def validate_key(key: dict) -> list[str]:
    """Return a list of schema violations (empty = valid). Fail-closed
    callers treat ANY violation as a dead key."""
    if not isinstance(key, dict):
        return ["key: not a mapping"]
    violations: list[str] = []
    stratum = str(key.get("stratum") or "")
    required = _REQUIRED_BY_STRATUM.get(stratum)
    if required is None:
        return [f"key: bad stratum {stratum!r}"]
    for field in required:
        if field not in key:
            violations.append(f"key: missing required field {field}")
    pqs = key.get("pqs")
    if not isinstance(pqs, list) or not pqs:
        violations.append("key: pqs empty")
        return violations
    seen: set[str] = set()
    for pq in pqs:
        if not isinstance(pq, dict):
            violations.append("pqs: non-mapping entry")
            continue
        pid = str(pq.get("pq_id") or "")
        if not pid:
            violations.append("pqs: missing pq_id")
        elif pid in seen:
            violations.append(f"pqs: duplicate pq_id {pid}")
        seen.add(pid)
        for field in ("question", "expected", "matcher"):
            if not pq.get(field):
                violations.append(f"pqs[{pid or '?'}]: missing {field}")
        if pq.get("matcher") not in MATCHERS:
            violations.append(
                f"pqs[{pid or '?'}]: bad matcher {pq.get('matcher')!r} "
                f"(valid: {MATCHERS})")
    return violations


def match(answer, expected, matcher: str) -> bool:
    """Apply one mechanical matcher. All comparisons are deterministic —
    zero LLM in scoring (AB-DESIGN §7 L1 rule)."""
    if matcher == "exact":
        return str(answer).strip() == str(expected).strip()
    if matcher == "set-subset":
        # the key's expected set must be COVERED by the analyst's answer
        try:
            return set(expected) <= set(answer)
        except TypeError:
            return False
    if matcher == "normalized-ioc":
        return normalize_ioc(str(answer)) == normalize_ioc(str(expected))
    if matcher == "attck-id":
        return str(answer).strip().upper() == str(expected).strip().upper()
    return False


def task_spec_pqs(key: dict) -> list[dict]:
    """Leak-free PQ view for the task-spec: pq_id + question ONLY."""
    return [{"pq_id": pq.get("pq_id"), "question": pq.get("question")}
            for pq in (key.get("pqs") or []) if isinstance(pq, dict)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench_answer_key.py",
                                 description="answer-key compiler")
    ap.add_argument("key", help="answer-key YAML path")
    ap.add_argument("--task-spec-out", default=None,
                    help="write leak-free PQ entries as JSON here")
    args = ap.parse_args(argv)
    try:
        key = yaml.safe_load(Path(args.key).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"FAIL: unreadable key: {exc}", file=sys.stderr)
        return 1
    violations = validate_key(key if isinstance(key, dict) else {})
    if violations:
        for v in violations:
            print(f"VIOLATION: {v}", file=sys.stderr)
        return 1
    if args.task_spec_out:
        out = Path(args.task_spec_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(task_spec_pqs(key), ensure_ascii=False,
                                  indent=2), encoding="utf-8")
    print(f"KEY PASS ({key.get('stratum')}, "
          f"{len(key.get('pqs') or [])} scoring PQs)")
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # #811 入口 UTF-8 保险
    force_utf8()
    sys.exit(main())
