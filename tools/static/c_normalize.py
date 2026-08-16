#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/c-normalize.py — Ghidra decompiled-C normalizer (issue #306).

Ghidra's C output carries its own dialect quirks that make the text harder for
a worker LLM to read: the round-down modulo idiom ``x - (x/N)*N`` instead of
``x % N``, self-assignments like ``x = x;``, and ``undefined4/8`` type labels.
This tool applies conservative, mechanical text rewrites directly to the
decompiled C text (C-text level by design — issue #306 design comment #1:
the idiom source is Ghidra's C output, and the LLM consumes that text, so
normalizing the text is the whole job).

Rule-driven architecture (d810-informed, issue #306 design comment #2):
operations are declarative entries in the ordered ``RULES`` list below — each
rule has a name, a description, an enable flag and a pure ``(text) -> (text,
hits)`` function.  ``main()`` only iterates the list; adding a rule never
touches ``main()``:

    1. write a function ``_apply_<name>(code) -> tuple[str, int]``,
    2. append a ``Rule(name=..., description=..., enabled=..., apply=...)``
       entry to ``RULES`` in the desired run order,
    3. (optional) add its stats to the ``--json`` / ``--reproduce`` emission
       (rule hits are reported automatically from the rule name).

The undefined-types heuristic is default OFF by design (issue #306 design
comment #1): guessed int/long labels can mislead the LLM worse than the
explicit unknown ``undefined4`` marker, so it requires ``--heuristics``.

Usage:
  c-normalize --in decompiled.c
  c-normalize --in decompiled.c --heuristics --json
  type decompiled.c | c-normalize            # stdin when --in omitted

Exit codes: 0 = transformed (normalized C on stdout), 1 = nothing to
transform (original C on stdout), 2 = error (structured JSON on stderr).
A one-line summary goes to stderr so stdout stays pipeable.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from common import add_common_flags, error, sha256  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # non-TTY / captured stream without reconfigure (e.g. pytest capsys)

EXIT_OK = 0
EXIT_UNCHANGED = 1
EXIT_ERROR = 2

HEURISTICS_RULE = "undefined_types"


@dataclass(frozen=True)
class Rule:
    """One declarative normalization operation in the ordered RULES list."""
    name: str
    description: str
    enabled: bool
    apply: Callable[[str], tuple[str, int]]


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------

_NUM = r"(?:0[xX][0-9a-fA-F]+|\d+)"
# A variable access without side effects: identifier + optional []/->/. chains.
# Function calls (parentheses) are deliberately excluded — folding `f(x) -
# (f(x)/N)*N` would double-evaluate f(x).  Lazy whitespace keeps the captured
# operand clean (no trailing spaces).
_VAR = (r"[A-Za-z_]\w*"
        r"(?:\s*?(?:\[[^\]\n]*\]|->\s*?[A-Za-z_]\w*|\.\s*?[A-Za-z_]\w*)\s*?)*")
_IDENT_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
# Characters that may follow the rewritten unit without changing precedence:
# `x % N` binds tighter than the unit it replaced, so a following `* / %`
# would re-associate the expression — those are unsafe.
_SAFE_FOLLOW = frozenset("),;]}?:+-<>=!&|^")
_SAFE_PRECEDE = frozenset("*/%")

_PLAIN_DIVFIRST = re.compile(
    r"(?P<left>" + _VAR + r")\s*(?P<op>[-+])\s*"
    r"\(\s*(?P<inner>" + _VAR + r")\s*/\s*(?P<div>" + _NUM + r")\s*\)\s*"
    r"\*\s*(?P<mult>-?" + _NUM + r")")
_PLAIN_MULTFIRST = re.compile(
    r"(?P<left>" + _VAR + r")\s*(?P<op>[-+])\s*"
    r"(?P<mult>-?" + _NUM + r")\s*\*\s*"
    r"\(\s*(?P<inner>" + _VAR + r")\s*/\s*(?P<div>" + _NUM + r")\s*\)")
_CAST_DIVFIRST = re.compile(
    r"\(\s*(?P<cast>[A-Za-z_]\w*)\s*\)\s*"
    r"(?P<left>" + _VAR + r")\s*(?P<op>[-+])\s*"
    r"\(\s*(?P=cast)\s*\)\s*"
    r"\(\s*\(?\s*(?P<inner>" + _VAR + r")\s*\)?\s*/\s*(?P<div>" + _NUM + r")\s*\)\s*"
    r"\*\s*(?P<mult>-?" + _NUM + r")")
_CAST_MULTFIRST = re.compile(
    r"\(\s*(?P<cast>[A-Za-z_]\w*)\s*\)\s*"
    r"(?P<left>" + _VAR + r")\s*(?P<op>[-+])\s*"
    r"(?P<mult>-?" + _NUM + r")\s*\*\s*"
    r"\(\s*(?P=cast)\s*\)\s*"
    r"\(\s*\(?\s*(?P<inner>" + _VAR + r")\s*\)?\s*/\s*(?P<div>" + _NUM + r")\s*\)")

_DEAD_ASSIGN_RE = re.compile(
    r"(?P<pre>^|\n)[ \t]*(?P<var>[A-Za-z_]\w*)[ \t]*=[ \t]*(?P=var)"
    r"[ \t]*;[ \t]*(?P<post>\n|$)")

_UNDEF4_DECL_RE = re.compile(r"\bundefined4\s+(\w+)\b")
_UNDEF8_DECL_RE = re.compile(r"\bundefined8\s+(\w+)\b")


def _valid_modulo_match(m: re.Match[str]) -> bool:
    """Same divisor on both sides, sign-consistent operator, same variable."""
    try:
        div = int(m.group("div"), 0)
        mult = int(m.group("mult"), 0)
    except ValueError:
        return False
    if div != abs(mult):
        return False
    op = m.group("op")
    if op == "-" and mult < 0:
        return False
    if op == "+" and mult >= 0:
        return False
    return m.group("left") == m.group("inner")


def _safe_context(code: str, start: int, end: int) -> bool:
    """Textual-context guards: full operand boundary before, no
    precedence-changing multiplicative operator after."""
    i = start - 1
    while i >= 0 and code[i] in " \t":
        i -= 1
    if i >= 0 and (code[i] in _IDENT_CHARS or code[i] in _SAFE_PRECEDE
                   or code[i] in ".])"):
        return False
    j = end
    while j < len(code) and code[j] in " \t":
        j += 1
    return j >= len(code) or code[j] in _SAFE_FOLLOW


def _apply_modulo_idiom(code: str) -> tuple[str, int]:
    """x - (x/N)*N -> x % N, incl. cast-wrapped forms and * / swapped tails.

    Conservative by design: only the exact Ghidra emission shapes are
    rewritten (parenthesized division, identical divisor/multiplier, textual
    identity of the operand, safe surrounding context); anything ambiguous is
    left unchanged.
    """
    rewrites: list[tuple[int, int, str]] = []
    for pattern, casted in ((_CAST_DIVFIRST, True), (_CAST_MULTFIRST, True),
                            (_PLAIN_DIVFIRST, False), (_PLAIN_MULTFIRST, False)):
        for m in pattern.finditer(code):
            if not _valid_modulo_match(m):
                continue
            if not _safe_context(code, m.start(), m.end()):
                continue
            if casted:
                repl = f"({m.group('cast')})(({m.group('inner')}) % {m.group('div')})"
            else:
                repl = f"{m.group('left')} % {m.group('div')}"
            rewrites.append((m.start(), m.end(), repl))
    if not rewrites:
        return code, 0
    rewrites.sort(key=lambda r: r[0])
    kept: list[tuple[int, int, str]] = []
    last_end = -1
    for start, end, repl in rewrites:
        if start < last_end:
            continue  # overlapping/contained match — keep the leftmost
        kept.append((start, end, repl))
        last_end = end
    # single-pass chunked rebuild (r2-306 MEDIUM: the naive reversed-slice
    # rebuild is O(n·k) — 1MB ≈ 6s, 2MB ≈ 70s; chunks make it O(n + k log k))
    parts: list[str] = []
    pos = 0
    for start, end, repl in kept:
        parts.append(code[pos:start])
        parts.append(repl)
        pos = end
    parts.append(code[pos:])
    return "".join(parts), len(kept)


def _apply_dead_assignment(code: str) -> tuple[str, int]:
    """Remove `x = x;` no-effect self-assignment lines.

    The replacement keeps the surrounding line structure: a first-line match
    drops its trailing newline, a later-line match keeps the preceding one so
    neighbouring lines do not join.
    """
    def _drop(m: re.Match[str]) -> str:
        return "" if m.group("pre") == "" else "\n"

    new, hits = _DEAD_ASSIGN_RE.subn(_drop, code)
    return new, hits


def _is_loop_counter(code: str, var: str) -> bool:
    v = re.escape(var)
    return bool(re.search(
        r"for\s*\(\s*" + v + r"\s*=\s*0\s*;\s*" + v + r"\s*<\s*[^;]+\s*;\s*"
        + v + r"\s*(?:=\s*" + v + r"\s*\+\s*1|\+\+)\s*\)", code))


def _is_accumulator(code: str, var: str) -> bool:
    v = re.escape(var)
    init_zero = re.search(v + r"\s*=\s*0\s*;", code)
    add_assign = re.search(v + r"\s*\+=\s*[^;]+;", code)
    add_self = re.search(v + r"\s*=\s*" + v + r"\s*\+\s*[^;]+;", code)
    return bool(init_zero and (add_assign or add_self))


def _is_pointer_like(code: str, var: str) -> bool:
    v = re.escape(var)
    null_cmp = re.search(v + r"\s*[!=]=\s*(?:0x0\b|0\b|NULL\b)", code)
    dat_assign = re.search(v + r"\s*=\s*DAT_\w+", code)
    ptr_cast_deref = re.search(r"\*\s*(?:\(\s*\w+\s*\*\s*\)\s*)?" + v, code)
    return bool(null_cmp or dat_assign or ptr_cast_deref)


def _apply_undefined_types(code: str) -> tuple[str, int]:
    """undefined4->int (loop counter / accumulator), undefined8->long
    (pointer-like) — heuristic type guesses, DEFAULT OFF via --heuristics."""
    hits = 0
    for var in {m.group(1) for m in _UNDEF4_DECL_RE.finditer(code)}:
        if _is_loop_counter(code, var) or _is_accumulator(code, var):
            code, n = re.subn(
                r"undefined4(\s+" + re.escape(var) + r"\b)", r"int\1", code)
            hits += n
    for var in {m.group(1) for m in _UNDEF8_DECL_RE.finditer(code)}:
        if _is_pointer_like(code, var):
            code, n = re.subn(
                r"undefined8(\s+" + re.escape(var) + r"\b)", r"long\1", code)
            hits += n
    return code, hits


RULES: list[Rule] = [
    Rule(
        name="modulo_idiom",
        description="x - (x/N)*N -> x % N (incl. cast-wrapped / mixed *-/ forms)",
        enabled=True,
        apply=_apply_modulo_idiom,
    ),
    Rule(
        name="dead_assignment",
        description="remove `x = x;` no-effect self-assignment lines",
        enabled=True,
        apply=_apply_dead_assignment,
    ),
    Rule(
        name=HEURISTICS_RULE,
        description="undefined4->int / undefined8->long heuristics "
                    "(--heuristics; default off: type guesses can mislead the "
                    "LLM worse than undefined4)",
        enabled=False,
        apply=_apply_undefined_types,
    ),
]


def normalize(code: str, heuristics: bool = False) -> str:
    """Apply the enabled rules in RULES order; pure and idempotent."""
    for rule in RULES:
        if rule.enabled or (heuristics and rule.name == HEURISTICS_RULE):
            code, _ = rule.apply(code)
    return code


def _diff_stats(old: str, new: str) -> dict[str, int]:
    added = removed = 0
    for line in difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True), n=0):
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return {"lines_added": added, "lines_removed": removed}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _read_input(path: str | None) -> str:
    if path:
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            error(f"cannot read --in {path}: {exc} — check the path exists "
                  f"and is readable")
        try:
            return _normalize_newlines(data.decode("utf-8"))
        except UnicodeDecodeError:
            error(f"--in {path} is not valid UTF-8 — pass decompiled C text, "
                  f"not raw binary")
    try:
        # bytes + strict UTF-8: locale decoding (GBK) would corrupt non-ASCII
        # identifiers and can crash the downstream sha256 encode (r2/r3-306).
        return _normalize_newlines(sys.stdin.buffer.read().decode("utf-8"))
    except UnicodeDecodeError:
        error("stdin is not valid UTF-8 — pipe decompiled C text")
    except OSError as exc:
        error(f"cannot read stdin: {exc} — pipe decompiled C in or pass --in")


def _normalize_newlines(text: str) -> str:
    """Universal-newline semantics after a byte-exact read: CRLF/CR → LF, so
    the rules' line-oriented regexes and sha256 operate on canonical text."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="c-normalize",
        description="Ghidra decompiled-C normalizer (issue #306)")
    add_common_flags(ap)
    ap.add_argument("--heuristics", action="store_true",
                    help="enable the undefined_types rule (undefined4->int / "
                         "undefined8->long guesses; default off)")
    args = ap.parse_args(argv)

    text_in = _read_input(args.in_path)
    rules = [r for r in RULES
             if r.enabled or (args.heuristics and r.name == HEURISTICS_RULE)]
    text = text_in
    rule_hits: dict[str, int] = {r.name: 0 for r in RULES}
    for rule in rules:
        text, n = rule.apply(text)
        rule_hits[rule.name] += n
    changed = text != text_in

    input_sha = sha256(text_in.encode("utf-8"))
    output_sha = sha256(text.encode("utf-8"))
    summary = " ".join(f"{name}={rule_hits[name]}" for name in
                       (r.name for r in rules))
    exit_code = EXIT_OK if changed else EXIT_UNCHANGED

    if args.reproduce:
        rows = {
            "tool": "c-normalize",
            "input_sha256": input_sha,
            "output_sha256": output_sha,
            "changed": 1 if changed else 0,
            "rules_enabled": ",".join(r.name for r in rules),
        }
        for r in rules:
            rows[f"hits.{r.name}"] = rule_hits[r.name]
        for key, value in rows.items():
            print(f"{key}={value}")
        return exit_code

    if args.json:
        payload = {
            "tool": "c-normalize",
            "input_sha256": input_sha,
            "output_sha256": output_sha,
            "changed": changed,
            "rule_hits": rule_hits,
            "rules_enabled": [r.name for r in rules],
            "diff": _diff_stats(text_in, text),
        }
        print(json.dumps(payload, ensure_ascii=False))
        return exit_code

    sys.stdout.write(text)  # exact text — stdout stays pipeable/fidelity-safe
    print(f"c-normalize: {'changed: ' + summary if changed else 'unchanged'}",
          file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
