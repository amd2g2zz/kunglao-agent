#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""js_obfuscation_detect.py — obfuscation-technique inventory for JS bundles.

Answers one question mechanically: which obfuscation techniques does this
bundle carry (packer, string-array+rotation, control-flow flattening, opaque
predicates, dead-code injection, webpack markers, aaencode, …) and which
registered shelf capability should run next?

Advisory static heuristic over RAW or DEOBFUSCATED bundles. It routes work;
it does not transform anything and is not proof of any family. Per-technique
evidence is a hit count with the matched shape class so a reviewer can
audit every verdict.

Input: one or more .js file paths. Output: stdout JSON — one report object
  per file (or a JSON array for multiple files): {path, size_bytes,
  line_count, techniques: [{name, confidence, evidence}],
  recommendation: {route, next_tool, why}, errors: []}.
Exit 0 = every file analyzed; exit 2 = at least one path was missing,
unreadable, or empty (fail loud — errors listed on stderr; good files still
get reports).

Usage:
  python tools/web/js_obfuscation_detect.py <file.js> [more.js ...]

Examples:
  # route a raw minified bundle before touching it
  python tools/web/js_obfuscation_detect.py bundle.min.js

  # batch-scan a whole unpacked asset directory
  python tools/web/js_obfuscation_detect.py dist/assets/*.js

  # pipeline: detect first, then the routed tool decides
  python tools/web/js_obfuscation_detect.py bundle.js | jq -r .recommendation
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# UTF-8 stdout guard via the shared tools/ _lib; the guard itself fires in
# __main__ only.
import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents
                  if _p.name == "tools")
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402

PACKER_RE = re.compile(
    r"\bev" + r"al\s*\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k\s*,"
    r"\s*e\s*,\s*[dr]\s*\)")
STRING_ARRAY_DECL_RE = re.compile(r"\b_0x[0-9a-fA-F]+\s*=\s*\[")
HEX_ID_RE = re.compile(r"\b_0x[0-9a-fA-F]+\b")
ROTATION_RE = re.compile(
    r"while\s*\(\s*--?\s*_0x[0-9a-fA-F]+\s*\)[\s\S]{0,200}?"
    r"\[\s*['\"]push['\"]\s*\]\(\s*_0x[0-9a-fA-F]+\[\s*['\"]shift['\"]\s*\]")
HEX_ESCAPE_RE = re.compile(r"\\x[0-9a-fA-F]{2}")
UNICODE_ESCAPE_RE = re.compile(r"\\u[0-9a-fA-F]{4}")
FROM_CHARCODE_RE = re.compile(r"String\s*\.\s*fromCharCode\s*\(")
ATOB_RE = re.compile(r"\batob\s*\(\s*[\"'`]")
SPLIT_PIPE_RE = re.compile(r"[\"'][0-9]+(?:\|[0-9]+)+[\"']\s*\.\s*split")
LOOP_SWITCH_RE = re.compile(
    r"(?:while|for)\s*\(\s*(?:true|!!\s*\[\s*\]|1|!!\s*\"\"|!!1)\s*\)"
    r"[^;{}]{0,80}\{[\s\S]{0,200}?switch\s*\(")
OPAQUE_RE = re.compile(r"!!\s*\[\s*\]|if\s*\(\s*!{1,2}!?\s*\[\s*\]\s*\)")
DEAD_CODE_RE = re.compile(r"if\s*\(\s*(?:!1|false|0\s*===\s*1)\s*\)")
WEBPACK_RE = re.compile(r"__webpack_require__|webpackJsonp|webpackChunk")
AA_CHAR = "ﾟ"  # the halfwidth-kana corner face-text alphabet carrier

HIGH_HITS = 3          # >= distinct-or-total hits at this count -> high
AA_RATIO = 0.15        # non-ascii ratio for the aaencode face-text family
MIN_SIZE = 1           # empty files are rejected as tool-level errors


def _hit(regex: re.Pattern, text: str) -> tuple[int, str]:
    matches = regex.findall(text)
    n = len(matches)
    if n == 0:
        return 0, ""
    sample = matches[0] if isinstance(matches[0], str) \
        else str(matches[0][0])
    evidence = f"{n} hit(s); first shape: {sample[:60]!r}"
    return n, evidence


def _nonascii_hit(text: str) -> tuple[int, str]:
    if not text:
        return 0, ""
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    ratio = non_ascii / len(text)
    if ratio < AA_RATIO:
        return 0, ""
    return (1, f"non-ascii char ratio {ratio:.2f} "
               f"({text.count(AA_CHAR)} face-text carriers)")


def TECHNIQUES(text: str) -> list[dict]:  # noqa: N802 - table-shaped probe
    """Inventory every technique with count evidence; order is fixed."""
    probes = [
        ("packer", PACKER_RE),
        ("string-array-rotation", ROTATION_RE),
        ("string-array", STRING_ARRAY_DECL_RE),
        ("hex-escapes", HEX_ESCAPE_RE),
        ("unicode-escapes", UNICODE_ESCAPE_RE),
        ("from-charcode", FROM_CHARCODE_RE),
        ("base64-atob", ATOB_RE),
        ("opaque-predicates", OPAQUE_RE),
        ("dead-code-injection", DEAD_CODE_RE),
        ("webpack", WEBPACK_RE),
    ]
    found: list[dict] = []
    for name, regex in probes:
        hits, evidence = _hit(regex, text)
        if hits:
            found.append({
                "name": name,
                "confidence": "high" if hits >= HIGH_HITS else "medium",
                "evidence": evidence,
            })
    # two flattening shapes (numeric split-pipe order map, loop-wrapped
    # switch) report as ONE technique with both evidences merged
    flat_hits = 0
    flat_shapes: list[str] = []
    for name, regex in (("split-pipe order map", SPLIT_PIPE_RE),
                        ("loop-wrapped switch", LOOP_SWITCH_RE)):
        hits, evidence = _hit(regex, text)
        if hits:
            flat_hits += hits
            flat_shapes.append(f"{name}: {evidence}")
    if flat_hits:
        found.append({
            "name": "control-flow-flattening",
            "confidence": "high" if flat_hits >= HIGH_HITS else "medium",
            "evidence": "; ".join(flat_shapes),
        })
    hits, evidence = _nonascii_hit(text)
    if hits:
        found.append({
            "name": "aaencode",
            "confidence": "high",
            "evidence": evidence,
        })
    # hex identifier density is its own row (string-array marker without
    # a bracket declaration still matters)
    hex_ids = len(HEX_ID_RE.findall(text))
    if hex_ids >= HIGH_HITS and "string-array" not in \
            {t["name"] for t in found}:
        found.append({
            "name": "hex-renamed-identifiers",
            "confidence": "medium",
            "evidence": f"{hex_ids} _0x-style identifier occurrences",
        })
    return found


ROUTES: list[tuple[str, str, str, list[str]]] = [
    # (route, next_tool, why, requires-techniques-any-of)
    ("unpack-first", "webcrack-deobfuscate",
     "packer bootstrap must be unwrapped before any AST work",
     ["packer"]),
    ("sandbox-decode", "js_env_diagnose",
     "face-text/encoded program decodes itself at runtime — run it in "
     "the sandbox and capture the payload",
     ["aaencode"]),
    ("unbundle", "webcrack-deobfuscate",
     "bundler markers present — recover module boundaries first",
     ["webpack"]),
    ("webcrack-deobfuscate", "webcrack-deobfuscate",
     "string-array + flattening shapes are the registered deobfuscation "
     "pipeline's home ground",
     ["string-array", "string-array-rotation"]),
    ("vmp-triage", "jsvmp_triage",
     "flattening shapes present — confirm/deny the bytecode-VM verdict "
     "with the three-feature triage",
     ["control-flow-flattening"]),
    ("decode-helpers", "webcrack-deobfuscate",
     "encoded-literal helpers present — decode passes fold them first",
     ["from-charcode", "base64-atob", "hex-escapes", "unicode-escapes"]),
]


def recommend(techniques: list[dict]) -> dict:
    names = {t["name"] for t in techniques}
    for route, tool, why, triggers in ROUTES:
        if names & set(triggers):
            return {"route": route, "next_tool": tool, "why": why}
    return {"route": "direct-read", "next_tool": None,
            "why": "no known obfuscation shape — proceed to rename/"
                   "readability passes"}


def analyze(text: str, source: str) -> dict:
    techniques = TECHNIQUES(text)
    return {
        "path": source,
        "size_bytes": len(text.encode("utf-8", "replace")),
        "line_count": text.count("\n") + 1,
        "techniques": techniques,
        "recommendation": recommend(techniques),
        "note": ("advisory routing only — run the routed registered tool "
                 "for transforms or verdicts"),
    }


def _load(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"no such file: {path}")
    raw = path.read_bytes()
    if not raw.strip():
        raise ValueError(f"empty file: {path}")
    return raw.decode("utf-8", errors="strict")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="inventory obfuscation techniques in JS bundles and "
                    "route to the registered next tool",
        epilog=(
            "exit codes: 0 = all files analyzed; 2 = any missing/empty/"
            "undecodable path (reports still print for good files)\n"
            "\n"
            "Examples:\n"
            "  # route a raw minified bundle before touching it\n"
            "  python tools/web/js_obfuscation_detect.py bundle.min.js\n"
            "\n"
            "  # batch-scan a whole unpacked asset directory\n"
            "  python tools/web/js_obfuscation_detect.py "
            "dist/assets/*.js\n"
            "\n"
            "  # pipeline: detect first, then the routed tool decides\n"
            "  python tools/web/js_obfuscation_detect.py bundle.js | "
            "jq -r .recommendation.next_tool"),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="raw or deobfuscated .js files")
    args = ap.parse_args(argv)

    reports: list[dict] = []
    failed: list[str] = []
    for f in args.files:
        p = Path(f)
        try:
            reports.append(analyze(_load(p), str(p)))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            failed.append(str(exc))
            print(f"js_obfuscation_detect: {exc}", file=sys.stderr)

    payload: dict | list
    if len(reports) == 1 and not failed:
        payload = reports[0]
    else:
        payload = reports
    if failed:
        payload = payload if isinstance(payload, list) else [payload]
        payload.append({"errors": failed})
        code = 2
    else:
        code = 0
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    ensure_utf8_stdout()
    sys.exit(main())
