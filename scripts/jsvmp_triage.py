#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jsvmp_triage.py — JSVMP/VMP three-feature triage for deobfuscated web JS (#790 adoptee).

Advisory static heuristic over ALREADY-DEOBFUSCATED bundles (wakaru/webcrack
output). Answers one question mechanically: does this bundle carry a
bytecode VM (big consumed integer array + dispatch switch loop + stack-op
handler bodies) so AST-level recovery should STOP and the operator should
switch to the instruction-trace methodology?

This is the CP1 gate of that methodology -- structured output instead of an
eyeball pass. It is NOT proof; runtime trace confirmation stays with the
operator.

Usage:
  python scripts/jsvmp_triage.py <file.js> [more.js ...] [--json]

Exit 0 always (advisory lint posture, mirrors think_seat).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MIN_ARRAY_ITEMS = 100          # "hundreds" per methodology; below = noise
MIN_CASE_COUNT = 8             # dispatch switches have real opcode tables
STACK_OP_RE = re.compile(
    r"\.(push|pop|shift|unshift|splice)\(|\b(this\.)?[A-Za-z_$][\w$]*\s*(\+=|-=)", )
SEMANTIC_HINT_RE = re.compile(
    r"(XMLHttp|fetch\(|localStorage|document\.|window\.|Element|Canvas"
    r"|navigator|history\.|CryptoJS|JSEncrypt|AES|MD5|SHA)", re.I)
DISPATCH_HEAD_RE = re.compile(
    r"\bwhile\s*\(\s*!!\[\]\s*\)|\bwhile\s*\(\s*true\s*\)|\bfor\s*\(\s*;\s*;\s*\)")
CASE_NUM_RE = re.compile(r"\bcase\s+(\d+)\s*:")
ARRAY_DECL_RE = re.compile(
    r"(?:var|let|const)?\s*[A-Za-z_$][\w$]*\s*=\s*\[([^\[\]]{200,}?)\]", re.S)
NUM_ITEM_RE = re.compile(r"-?\d+(?:\.\d+)?")
STR_ITEM_SPLIT_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
PC_TICKLE_RE = re.compile(r"[A-Za-z_$][\w$]*\[\s*[A-Za-z_$][\w$]*\+\+")


def _arrays(text: str) -> list[dict]:
    """Big literal arrays (numeric or string-element)."""

    found = []
    for m in ARRAY_DECL_RE.finditer(text):
        body = m.group(1)
        nums = NUM_ITEM_RE.findall(body)
        if len(nums) >= MIN_ARRAY_ITEMS:
            found.append({"kind": "numeric", "items": len(nums),
                          "offset": m.start()})
            continue
        strs = STR_ITEM_SPLIT_RE.findall(body)
        if len(strs) >= MIN_ARRAY_ITEMS:
            found.append({"kind": "string", "items": len(strs),
                          "offset": m.start()})
    return sorted(found, key=lambda x: -x["items"])


def _dispatch(text: str) -> dict | None:
    """switch-in-infinite-loop with a numeric case table."""
    best = None
    for head in DISPATCH_HEAD_RE.finditer(text):
        # crude window: from the loop head to the next top-level function --
        # bounded slice keeps false positives cheap without a full parser.
        window = text[head.end():head.end() + 60000]
        close = window.find("\nfunction ")
        if close == -1:
            close = len(window)
        body = window[:close]
        cases = CASE_NUM_RE.findall(body)
        if len(cases) < MIN_CASE_COUNT:
            continue
        cand = {"cases": len(set(cases)),
                "pc_indexing": bool(PC_TICKLE_RE.search(body))
                or bool(re.search(r"\+\+", body))}
        if best is None or cand["cases"] > best["cases"]:
            best = cand
    return best


def _semantics_ratio(text: str) -> float:
    """Share of case-body lines WITHOUT business/env semantics.

    VMP handlers are stack-machine primitives: push/pop/splice/arith only.
    Plain control-flow flattening leaves readable calls around."""

    case_bodies = re.findall(
        r"case\s+\d+\s*:(.*?)(?=case\s+\d+\s*:|default:|\Z)", text, re.S)
    if not case_bodies:
        return 1.0   # nothing looks like a dispatch table -> not VMP-shaped
    semantic = sum(1 for b in case_bodies if SEMANTIC_HINT_RE.search(b))
    return 1.0 - (semantic / max(1, len(case_bodies)))


def triage(text: str, source: str) -> dict:
    arrays = _arrays(text)
    disp = _dispatch(text)
    sem_ratio = round(_semantics_ratio(text), 3)

    f1 = bool(arrays)
    f2 = disp is not None
    f3 = sem_ratio >= 0.9

    confident = f1 and f2
    signals = []
    if arrays:
        signals.append(f"large array: {arrays[0]['items']} items "
                       f"({arrays[0]['kind']})")
    if disp:
        signals.append(f"dispatch switch: {disp['cases']} numeric cases"
                       + (" + pc indexing" if disp["pc_indexing"] else ""))
    signals.append(f"semantic-free case-body ratio: {sem_ratio}")

    verdict = {
        "source": source,
        "vmp_suspected": confident,
        "confidence": ("high" if confident and f3 else
                       "medium" if confident else "low"),
        "features": {
            "f1_bytecode_array": arrays,
            "f2_dispatch_loop": disp,
            "f3_semanticless_handlers": {"ratio": sem_ratio,
                                         "threshold": 0.9},
        },
        "signals": signals,
        "note": ("advisory triage only -- runtime confirmation requires a "
                 "single-generation complete opcode/stack trace (CP3 of the "
                 "trace methodology)"),
    }
    return verdict


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="three-feature JSVMP/VMP triage for deobfuscated bundles")
    ap.add_argument("files", nargs="+", help="deobfuscated .js files")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args(argv)

    results = []
    for f in args.files:
        p = Path(f)
        try:
            results.append(triage(p.read_text(encoding="utf-8",
                                              errors="replace"), str(p)))
        except OSError as exc:
            print(f"jsvmp_triage: unreadable {p}: {exc}", file=sys.stderr)
    out = json.dumps(results if len(results) != 1 else results[0],
                     ensure_ascii=False, indent=2)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
