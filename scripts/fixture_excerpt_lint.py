# -*- coding: utf-8 -*-
"""fixture_excerpt_lint — condensed decompile excerpt conversion/speculation lint (#58).

The a2b5e25c problem-1 root cause lived in a worker's CONDENSED Ghidra decompile
excerpt: it materialized an UNANNOTATED semantic conversion (`rc.averageBitRate =
bitrate*1000;`, kbps→bps) that has no machine-code basis, and the report copied
the excerpt verbatim. This module is the front-line EXCERPT-TEXT lint that flags
the smell at fixture-authoring time, BEFORE any binary is involved.

Two rules (regex heuristics only — no LLM, no binary, no network):

  R1 unannotated-conversion — an assignment whose RHS contains a numeric-literal
      scaling operator (`*N`, `/N`, `<<K`, `>>K`) is FLAGGED unless a `unit:`
      caliber annotation is in scope (same-line `// unit: <caliber>` or a
      preceding block-scoped `// unit:` declaration). A known unit-scale operand
      (1000/1024/100/8/60/3600/...) is `severity=high`; any other numeric scaling
      is `severity=normal`. Variable-only arithmetic (`a * b`) is NOT flagged.
  R3 unresolved-speculation — an assignment whose LHS is a generic Ghidra
      unresolved name (`sVarN`/`uVarN`/`lVarN`/`unaff_*`) is FLAGGED when the RHS
      contains a numeric literal or a non-generic (semantic) identifier, unless a
      `// resolved: <how>` annotation is on the line. A faithful temp-to-temp
      copy (`sVar1 = sVar2;`) or cast of a generic (`sVar1 = (long)sVar2;`) is
      NOT flagged.

LAYERING — this is #58's KEY PROPERTY. It is COMPLEMENTARY to the two existing
mechanical checkers, NOT a duplicate of either:

  #50 (tools/static/disasm_constant_check.py :: check_fact_disasm / check_report_listing)
      — BYTE-EXACT, BACK-LINE. Needs the sample binary + a VA anchor on each
      assertion; its `scaled` kind disproves a `*1000` by scanning capstone disasm
      for an imul/<K> at the VA. Runs AFTER VA-anchoring, against the binary.
  #49 (fact-expected-value-binding) — binds a fact's `expected:` values for
      cross-layer report↔fact comparison.
  #58 (THIS) — EXCERPT-TEXT, FRONT-LINE. Reads the raw condensed `.c` text only;
      never opens the binary, never resolves a VA, never runs capstone. Flags the
      ABSENCE of a `unit:`/`resolved:` annotation at authoring time.

#50 and #58 both flag the a2b5e25c `*1000` — by design, at different layers:
#50 disproves the multiply at the VA in disasm (needs binary); #58 smells the
unannotated scaling op in the text (needs only text). Defense in depth. #58 does
NOT duplicate #50 (different input: text vs binary+VA; different time: authoring
vs byte-verification) or #49 (no expected-value map comparison). See
openspec/changes/fixture-excerpt-lint/design.md (D1 layering table).

Heuristic, not semantic: regex/keyword patterns only. The recall/precision
tradeoff is documented in design.md (D5): the lint fires loudly on the documented
failure (the `*1000`, severity=high) and quietly on clean faithful excerpts (0 on
the clean fixture), with the operator/exemption tables table-driven and
extensible. Rule 2 (traceability to address+bytes) is enforced structurally by
#50's VA anchoring; #58 cross-references it in references/excerpt-lint.md but
does not re-check it here.

CLI:  python scripts/fixture_excerpt_lint.py <excerpt.c>
Exit: 0 = clean, 1 = >=1 violation, 2 = unreadable file.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Numeric literal + scaling-operator patterns (R1).
# A scaling op is suspect in a condensed excerpt ONLY when it carries a NUMERIC
# operand — `a * b` (two variables) is normal arithmetic, not a unit conversion.
# ---------------------------------------------------------------------------
_NUM = r"(?:0[xX][0-9a-fA-F]+|\d+)"
MUL_SCALE_RE = re.compile(rf"\*\s*({_NUM})")            # *N
DIV_SCALE_RE = re.compile(rf"/(?![*/])\s*({_NUM})")     # /N (not // or /*)
SHL_SCALE_RE = re.compile(rf"<<\s*({_NUM})")            # <<K
SHR_SCALE_RE = re.compile(rf">>\s*({_NUM})")            # >>K
SCALING_PATTERNS = (MUL_SCALE_RE, DIV_SCALE_RE, SHL_SCALE_RE, SHR_SCALE_RE)

# Operands that parse to one of these values are textbook unit conversions
# (kbps→bps, KiB↔byte, byte↔bit, percent, minute/hour, MiB) → severity=high.
KNOWN_UNIT_SCALES = frozenset({
    1000, 1024, 100, 8, 60, 3600, 512, 2048, 4096, 1000000, 1048576,
})

# ---------------------------------------------------------------------------
# R3 — generic Ghidra unresolved names + RHS classification.
# ---------------------------------------------------------------------------
_UNRESOLVED_LHS_RE = re.compile(r"^([a-zA-Z]Var\d+|unaff_\w+)$")
_GENERIC_NAME_RE = re.compile(
    r"^([a-zA-Z]Var\d+|unaff_\w+|FUN_[0-9a-fA-F]+|param_\d+|in_\w+|out_\w+)$"
)
# C / Ghidra cast type keywords — when seen on an unresolved LHS's RHS they are a
# cast, not a semantic value (e.g. `sVar1 = (long)sVar2;` is faithful).
TYPE_KEYWORDS = frozenset({
    "void", "char", "short", "int", "long", "float", "double", "signed",
    "unsigned", "bool", "_Bool", "__int8", "__int16", "__int32", "__int64",
    "int8_t", "int16_t", "int32_t", "int64_t", "uint8_t", "uint16_t",
    "uint32_t", "uint64_t", "size_t", "ssize_t", "intptr_t", "uintptr_t",
    "wchar_t", "_BYTE", "_WORD", "_DWORD", "_QWORD", "_OWORD", "_BOOL1",
    "_BOOL2", "_BOOL4", "_REAL4", "_REAL8", "const", "static", "struct",
    "union", "enum",
})
# A numeric literal NOT part of an identifier (the lookbehind excludes digits
# inside names like `param_1` / `_DWORD8` / `sVar2`).
_rhs_LITERAL_RE = re.compile(r"(?<![A-Za-z0-9_])(?:0[xX][0-9a-fA-F]+|\d+)")

# ---------------------------------------------------------------------------
# `unit:` block-scoped declaration (R1 exemption form (b)).
# A comment-ONLY line whose first token after the marker is `unit:` establishes a
# caliber for subsequent lines in the same block (blank line resets).
# ---------------------------------------------------------------------------
_UNIT_DECL_LINE_RE = re.compile(r"^\s*(?://|#|/\*)\s*unit:\s*\S")

_COMPOUND_EQ_PREV = frozenset("=!<>+-*/%&|^~")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_int(s: str) -> int:
    s = s.strip()
    return int(s, 16) if s.lower().startswith("0x") else int(s, 10)


def _code_lines(text: str) -> list[tuple[int, str, str]]:
    """Return [(line_no, raw, code)] per physical line. `code` is `raw` with
    comments removed (`//` line comments + `/* ... */` segments, tracked across
    lines for multi-line block comments). `raw` is retained so annotation
    markers (`unit:` / `resolved:`) stay detectable."""
    out: list[tuple[int, str, str]] = []
    in_block = False
    for line_no, raw in enumerate(text.splitlines(), 1):
        if in_block:
            end = raw.find("*/")
            if end == -1:
                out.append((line_no, raw, ""))
                continue
            code = raw[end + 2:]
            in_block = False
        else:
            code = raw
        # strip single-line /* ... */ segments; detect a multi-line block start
        while "/*" in code:
            start = code.find("/*")
            end = code.find("*/", start + 2)
            if end == -1:
                code = code[:start]
                in_block = True
                break
            code = code[:start] + code[end + 2:]
        idx = code.find("//")
        if idx != -1:
            code = code[:idx]
        out.append((line_no, raw, code))
    return out


def _split_assignment(stmt: str) -> tuple[str, str] | None:
    """Split `LHS = RHS` on the first SINGLE `=` (skipping `==`/`!=`/`<=`/`>=`
    and compound `+=`/`-=`/...). None when the statement is not an assignment."""
    for i, ch in enumerate(stmt):
        if ch != "=":
            continue
        prev = stmt[i - 1] if i > 0 else ""
        nxt = stmt[i + 1] if i + 1 < len(stmt) else ""
        if nxt == "=" or prev in _COMPOUND_EQ_PREV:
            continue
        return stmt[:i].strip(), stmt[i + 1:].strip()
    return None


def _detect_scaling(rhs: str) -> tuple[str, str] | None:
    """Return (operand_str, severity) if `rhs` has any numeric-literal scaling
    op, else None. A known unit-scale operand yields severity=high (reported as
    the representative operand); otherwise the first scaling op, severity=normal."""
    found: list[tuple[str, int]] = []
    for pat in SCALING_PATTERNS:
        for m in pat.finditer(rhs):
            try:
                val = _parse_int(m.group(1))
            except ValueError:
                continue
            found.append((m.group(0).strip(), val))
    if not found:
        return None
    known = [op for op, val in found if val in KNOWN_UNIT_SCALES]
    if known:
        return known[0], "high"
    return found[0][0], "normal"


def _is_speculative(lhs: str, rhs: str) -> bool:
    """True iff LHS is a generic unresolved name AND the RHS carries a concrete
    or semantic value (numeric literal, or a non-generic / non-type identifier)."""
    if not _UNRESOLVED_LHS_RE.match(lhs):
        return False
    if _rhs_LITERAL_RE.search(rhs):
        return True
    for tok in re.findall(r"[A-Za-z_]\w*", rhs):
        if tok in TYPE_KEYWORDS:
            continue
        if _GENERIC_NAME_RE.match(tok):
            continue
        return True
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def lint(excerpt_text: str) -> dict:
    """Scan a condensed C decompile excerpt for unannotated semantic conversions
    (R1) and unresolved-variable speculation (R3).

    Returns ``{ok, violation_count, violations, checks}`` where each violation
    is ``{rule, severity, line_no, snippet, operand, note}`` and ``checks`` is
    the number of assignment statements scanned.
    """
    violations: list[dict] = []
    checks = 0
    block_unit_active = False
    for line_no, raw, code in _code_lines(excerpt_text):
        if not raw.strip():
            block_unit_active = False
            continue
        if _UNIT_DECL_LINE_RE.match(raw):
            block_unit_active = True
            continue  # comment-only declaration line; no assignments to scan
        same_line_unit = "unit:" in raw
        same_line_resolved = "resolved:" in raw
        r1_exempt = same_line_unit or block_unit_active
        for stmt in code.split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            split = _split_assignment(stmt)
            if split is None:
                continue
            lhs, rhs = split
            if not lhs or not rhs:
                continue
            checks += 1
            if not r1_exempt:
                scaling = _detect_scaling(rhs)
                if scaling:
                    operand, severity = scaling
                    violations.append({
                        "rule": "R1", "severity": severity,
                        "line_no": line_no, "snippet": stmt, "operand": operand,
                        "note": f"unannotated numeric scaling {operand!r} "
                                f"(no `unit:` caliber on the line or block)",
                    })
            if not same_line_resolved and _is_speculative(lhs, rhs):
                violations.append({
                    "rule": "R3", "severity": "normal",
                    "line_no": line_no, "snippet": stmt, "operand": None,
                    "note": f"unresolved LHS {lhs!r} bound to a concrete/semantic "
                            f"value (no `// resolved:` annotation)",
                })
    return {
        "ok": not violations,
        "violation_count": len(violations),
        "violations": violations,
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Condensed decompile excerpt lint — flag unannotated "
                    "semantic conversions and unresolved-variable speculation "
                    "(#58). Complementary to #50 (byte-exact, binary+VA) and "
                    "#49 (expected-value binding).",
    )
    parser.add_argument("excerpt", help="UTF-8 condensed .c excerpt file")
    args = parser.parse_args(argv)
    try:
        text = Path(args.excerpt).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"error: cannot read excerpt file {args.excerpt!r}: {exc}",
              file=sys.stderr)
        return 2
    report = lint(text)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
