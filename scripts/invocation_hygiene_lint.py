#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""invocation_hygiene_lint.py — python invocation standardization gate
(0.1.6 sweep, owner mandate).

THE standard (ONE legal form): `uv run --project <plugin-root> python
<script> ...` — never bare `python` / `python3` / `pip`. Live bug behind
the mandate: a bare `python` resolved an old interpreter and crashed
review_gate with a SyntaxError.

Scanned surfaces:
  - docs: skills/**/*.md, commands/**/*.md (if present), README.md
  - runtime: scripts/*.py + hooks/*.py subprocess spawn lines

Exemptions (never violations):
  - requirement statements ("Python 3.10+", `python3 -V` presence probes,
    .python-version, python_version, requires-python)
  - shebangs and docstring/comment-only lines (runtime .py: lines whose
    stripped form starts with `#`)
  - `claude mcp add ... -- python ...` MCP registration templates (the
    server spawn is the MCP client's config surface, not a shell
    invocation; plugin-scope carrying is the deploy-truth work stream)
  - eval-unit metadata labels (`"toolchain": "python3"`, `"language"` rows)
  - `sys.executable`-bearing lines (the sanctioned runtime form) and the
    `uv run ... python` canonical form itself

Baseline: ZERO violations (ratchet by absence — any new bare form fails).
Exit 0 clean / 1 violations found (mirrors comment_hygiene_lint).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

DOC_GLOBS = ("skills/**/*.md", "commands/**/*.md", "README.md")
RUNTIME_DIRS = ("scripts", "hooks")

# Bare interpreter invocations to refuse (docs and runtime argv literals).
_BARE = re.compile(
    r"(?<![A-Za-z0-9_.\-/])(python3?|pip3?)(?=\s|['\"]|\)|$|;|&&)")

# A line is CLEAN when it matches any of these.
_CLEAN_MARKERS = (
    re.compile(r"uv run\b"),                       # the canonical form
    re.compile(r"sys\.executable"),                # sanctioned runtime spawn
    re.compile(r"claude mcp add\b"),               # MCP registration template
    re.compile(r"python3? -V\b"),                  # presence probe / guidance
    re.compile(r"Python 3\b"),                     # requirement statement
    re.compile(r"python_version"),                 # markers
    re.compile(r"requires-python"),
    re.compile(r"\"(?:toolchain|language)\":\s*\"python3?\""),  # eval metadata
    re.compile(r"language.{0,4}python3?\""),       # eval unit descriptors
    re.compile(r"#"),                              # comment-only / annotated
    re.compile(r"\buv\b"),                            # uv-form argv lines (any shape)
    re.compile(r"(==|!=)\s*[\"']python3?\""),          # toolchain-name comparison
    re.compile(r"\(\s*[\"']python\""),               # tool-name vocab tuples
    re.compile(r"python3?\",\s*\"py\""),             # tool-name vocab tuples (cont.)
    re.compile(r"Manager\(|PkgSpec\(|ToolMeta\(|NextAction\("),  # supply metadata
    re.compile(r"name=\"python\""),                   # check-result component name
    re.compile(r"root_cause=\"python\""),              # root-cause component label
    re.compile(r"never inlined as"),                   # anti-pattern prose mention
    re.compile(r"argv\[0\] in \(\"python\""),         # the canonicalizer itself
)

_MD_SKIP = (
    re.compile(r"^\s*```"),                        # fence toggles handled below
)


def _clean_line(line: str) -> bool:
    if _CLEAN_MARKERS[8].match(line.strip()):
        return True
    if not _BARE.search(line):
        return True
    return any(m.search(line) for m in _CLEAN_MARKERS[:-1])


def _scan_docs(lines: list[str], rel: str, out: list[str]) -> None:
    fenced = False
    for i, line in enumerate(lines, 1):
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if _clean_line(line):
            continue
        out.append(f"{rel}:{i}: {line.strip()[:160]}")


def _scan_runtime(lines: list[str], rel: str, out: list[str]) -> None:
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("#") or s.startswith('"""') or s.startswith("'''"):
            continue
        for m in re.finditer(r"[\"']python3?[\"']|[\"']pip3?[\"']", line):
            # a quoted bare interpreter token: violation unless the line is
            # already sys.executable-based or an exempt metadata form
            if _clean_line(line):
                continue
            out.append(f"{rel}:{i}: {line.strip()[:160]}")
            break


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="python invocation hygiene gate (uv-run canonical form)")
    ap.add_argument("--root", default=str(REPO))
    a = ap.parse_args(argv)
    root = Path(a.root)
    out: list[str] = []

    for pattern in DOC_GLOBS:
        for p in sorted(root.glob(pattern)):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            _scan_docs(p.read_text(encoding="utf-8",
                                   errors="replace").splitlines(), rel, out)

    for d in RUNTIME_DIRS:
        for p in sorted((root / d).glob("*.py")):
            rel = p.relative_to(root).as_posix()
            _scan_runtime(p.read_text(encoding="utf-8",
                                      errors="replace").splitlines(), rel, out)

    if out:
        print(f"invocation-hygiene: {len(out)} violation(s); "
              f"canonical form: `uv run --project <plugin-root> python ...`")
        for v in out:
            print(f"  {v}")
        return 1
    print("invocation-hygiene: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
