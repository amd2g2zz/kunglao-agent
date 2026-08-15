# -*- coding: utf-8 -*-
"""tools/auxiliary/sanitize.py — sample-content prompt-injection sanitizer.

Deterministic text-sanitize CLI for sample-derived content before it reaches
LLM workers. Neutralizes:
  1. Zero-width characters (U+200B/U+200C/U+200D/U+200E/U+200F/U+2060/U+2066/
     U+2069/U+202C/U+202E/U+2069/U+FEFF/U+00AD)
  2. Homoglyphs (Cyrillic/Greek lookalikes for ASCII characters)
  3. LLM instruction markers (<|...|>, [INST], ###, System:, etc.)
  4. ANSI escape sequences + C0 control characters (#333, --mode ansi only)

Modes:
  default = three injection passes (zero-width+homoglyph+markers);
  --mode zero-width|homoglyph|markers for single injection pass;
  --mode ansi = ANSI/C0 stripping pass (standalone, NOT part of full —
    keeps #307 full-mode semantics unchanged);
  --report-only: findings JSON, no rewrite

ANSI mode (#333) strips:
  - CSI (ESC [ ...), OSC (ESC ] ... BEL/ST), DCS/SOS/PM/APC (ESC P/X/^/_ ...
    ST), and two-byte Fe sequences (ESC + intermediates + final)
  - C0 control characters U+0000-U+001F except LF (U+000A) and TAB (U+0009),
    plus DEL (U+007F)
  - ansi_count = escape sequences stripped; ctrl_count = control characters
    stripped (a lone ESC counts as 1 ctrl char; ESC inside a sequence does
    not double-count). Strip findings are aggregated counts, not itemized
    in `suspicious` (console output can contain thousands of sequences).

Exit codes (#277 contract):
  0 = clean or sanitized (changes applied)
  1 = nothing to sanitize (input already clean, negative result)
  2 = error + guidance message

CLI contract (#277):
  --in PATH       input file (or stdin if omitted)
  --json          structured JSON output
  --reproduce     field=value lines for reproducibility
  --mode MODE     zero-width|homoglyph|markers|ansi (default: full)
  --report-only   findings only, no rewrite
  --sentinel-prefix PREFIX  custom sentinel prefix (default: INJ)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# UTF-8 stdout reconfigure (#278-1c pattern)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# ---------------------------------------------------------------------------
# Character maps
# ---------------------------------------------------------------------------

ZERO_WIDTH_CHARS: set[int] = {
    0x200B,  # ZERO WIDTH SPACE
    0x200C,  # ZERO WIDTH NON-JOINER
    0x200D,  # ZERO WIDTH JOINER
    0x200E,  # LEFT-TO-RIGHT MARK
    0x200F,  # RIGHT-TO-LEFT MARK
    0x202C,  # POP DIRECTIONAL FORMATTING
    0x202E,  # RIGHT-TO-LEFT OVERRIDE
    0x2060,  # WORD JOINER
    0x2066,  # LEFT-TO-RIGHT ISOLATE
    0x2069,  # POP DIRECTIONAL ISOLATE
    0xFEFF,  # ZERO WIDTH NO-BREAK SPACE / BOM
    0x00AD,  # SOFT HYPHEN
}

# Cyrillic lowercase lookalikes for ASCII: char → (ascii replacement, description)
CYRILLIC_HOMOGLYPHS: dict[int, tuple[str, str]] = {
    0x0430: ("a", "Cyrillic small a"),     # а
    0x0435: ("e", "Cyrillic small e"),     # е
    0x043E: ("o", "Cyrillic small o"),     # о
    0x0441: ("c", "Cyrillic small es"),    # с
    0x0440: ("p", "Cyrillic small er"),    # р
    0x0443: ("y", "Cyrillic small u"),     # у  (r1-307 H2: Sуstem bypass)
    0x0445: ("x", "Cyrillic small kha"),   # х
    0x0455: ("s", "Cyrillic small dze"),   # ѕ
    0x0456: ("i", "Cyrillic small Byelorussian-Ukrainian i"),  # і
    0x0458: ("j", "Cyrillic small je"),    # ј
    0x04BB: ("h", "Cyrillic small shha"),  # һ
}

# Cyrillic uppercase lookalikes
CYRILLIC_UPPER_HOMOGLYPHS: dict[int, tuple[str, str]] = {
    0x0401: ("E", "Cyrillic capital Io"),       # Ё
    0x0405: ("S", "Cyrillic capital Dze"),      # Ѕ  (r1-307 H2: [INЅT] bypass)
    0x0406: ("I", "Cyrillic capital Byelorussian-Ukrainian I"),  # І
    0x0410: ("A", "Cyrillic capital A"),     # А
    0x0412: ("B", "Cyrillic capital Ve"),    # В
    0x0415: ("E", "Cyrillic capital Ye"),    # Е
    0x041A: ("K", "Cyrillic capital Ka"),    # К
    0x041C: ("M", "Cyrillic capital Em"),    # М
    0x041D: ("H", "Cyrillic capital En"),    # Н
    0x041E: ("O", "Cyrillic capital O"),     # О
    0x0420: ("P", "Cyrillic capital Er"),    # Р
    0x0421: ("S", "Cyrillic capital Es"),    # С
    0x0422: ("T", "Cyrillic capital Te"),    # Т
    0x0423: ("Y", "Cyrillic capital U"),     # У  (y-like)
    0x0425: ("X", "Cyrillic capital Ha"),    # Х
}

# Greek lookalikes for ASCII (capital)
GREEK_HOMOGLYPHS: dict[int, tuple[str, str]] = {
    0x0391: ("A", "Greek capital Alpha"),     # Α
    0x0392: ("B", "Greek capital Beta"),      # Β
    0x0395: ("E", "Greek capital Epsilon"),    # Ε
    0x0396: ("Z", "Greek capital Zeta"),       # Ζ
    0x0397: ("H", "Greek capital Eta"),       # Η
    0x0399: ("I", "Greek capital Iota"),       # Ι
    0x039A: ("K", "Greek capital Kappa"),     # Κ
    0x039C: ("M", "Greek capital Mu"),         # Μ
    0x039F: ("O", "Greek capital Omicron"),    # Ο
    0x03A1: ("P", "Greek capital Rho"),        # Ρ  (note: not same shape as P but confusable)
    0x03A4: ("T", "Greek capital Tau"),        # Τ
    0x03A7: ("X", "Greek capital Chi"),         # Χ
}

# Greek lowercase lookalikes
GREEK_LOWER_HOMOGLYPHS: dict[int, tuple[str, str]] = {
    0x03B1: ("a", "Greek small alpha"),    # α
    0x03B2: ("B", "Greek small beta"),     # β  (stretch)
    0x03B5: ("e", "Greek small epsilon"), # ε
    0x03B6: ("z", "Greek small zeta"),    # ζ
    0x03B7: ("n", "Greek small eta"),     # η  (n-like)
    0x03B9: ("i", "Greek small iota"),    # ι
    0x03BA: ("k", "Greek small kappa"),   # κ
    0x03BF: ("o", "Greek small omicron"), # ο
    0x03C1: ("p", "Greek small rho"),     # ρ
    0x03C4: ("t", "Greek small tau"),     # τ
    0x03C7: ("x", "Greek small chi"),     # χ
}

ALL_HOMOGLYPHS: dict[int, tuple[str, str]] = {}
for _d in (CYRILLIC_HOMOGLYPHS, CYRILLIC_UPPER_HOMOGLYPHS,
           GREEK_HOMOGLYPHS, GREEK_LOWER_HOMOGLYPHS):
    ALL_HOMOGLYPHS.update(_d)

# ---------------------------------------------------------------------------
# LLM instruction marker patterns
# ---------------------------------------------------------------------------

# Patterns to neutralize. Each tuple: (compiled regex, description)
# NOTE: Patterns must not overlap — first match wins per run, and re-running
# on output must not re-match. The generic <|...|> pattern covers all ChatML
# special tokens including im_start/im_end, so no separate im pattern needed.
MARKER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # ChatML / generic special tokens: <|anything|>
    (re.compile(r"<\|[^>]*\|>", re.DOTALL), "ChatML special token"),
    # LLaMA [INST] / [/INST]
    (re.compile(r"\[/?INST\]", re.IGNORECASE), "LLaMA INST token"),
    # Markdown heading as instruction: ### at line start followed by word
    (re.compile(r"(?:^|\n)#{1,6}\s+\w", re.MULTILINE), "Markdown heading"),
    # System:/Assistant: line-initial role markers. MULTILINE ^ matches at
    # line starts WITHOUT consuming the preceding newline (the (?:^|\n)
    # alternative would eat it into the replacement — r2-307 MEDIUM).
    (re.compile(r"^\s*(?:System|Assistant|User|Human)\s*:", re.MULTILINE | re.IGNORECASE),
     "Role marker"),
    # Triple backtick code fence (often used for injection payloads)
    (re.compile(r"```"), "Code fence"),
]

# ---------------------------------------------------------------------------
# ANSI escape / C0 control patterns (#333)
# ---------------------------------------------------------------------------

# One ESC-led sequence per ECMA-48 §5.4:
#   CSI  ESC [ params(0x30-0x3F)* intermediates(0x20-0x2F)* final(0x40-0x7E)
#   OSC  ESC ] ... (BEL | ST=ESC \)
#   DCS/SOS/PM/APC  ESC P/X/^/_ ... (BEL | ST)
#   Fe   ESC intermediates(0x20-0x2F)* final(0x20-0x7E)  — e.g. ESC ( B, ESC 7
#        (VT100 DECSC/DECRC), ESC = — final widened to 0x20-0x7E because
#        real console output uses 0x30-0x3F finals (ESC 7/8) that strict
#        ECMA-48 Fe (0x40-0x7E) would miss
# C1 single-byte controls (U+0080-U+009F) are out of scope (not produced by
# Ghidra/yara console output; issue #333 explicitly excludes GBK/mojibake handling, so no encoding involvement here).
ANSI_ESCAPE_RE: re.Pattern[str] = re.compile(
    r"\x1b"
    r"(?:"
    r"\[[0-?]*[ -/]*[@-~]"
    r"|\][^\x1b\x07]*(?:\x07|\x1b\\)"
    r"|[PX^_][^\x1b\x07]*(?:\x07|\x1b\\)"
    r"|[ -/]*[ -~]"
    r")"
)


def _is_control_to_strip(cp: int) -> bool:
    """True for C0 control chars (U+0000-U+001F) except LF/TAB, plus DEL."""
    return (cp < 0x20 and cp not in (0x09, 0x0A)) or cp == 0x7F

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SuspiciousEntry:
    offset: int
    original: str
    replacement: str
    kind: str  # "zero-width" | "homoglyph" | "marker"
    desc: str = ""  # human-readable reason (e.g. marker pattern description)


@dataclass
class SanitizeResult:
    output: str
    zwx_count: int
    homoglyph_count: int
    marker_count: int
    ansi_count: int = 0
    ctrl_count: int = 0
    suspicious: list[dict] = field(default_factory=list)
    input_sha256: str = ""
    output_sha256: str = ""
    changed: bool = False


# ---------------------------------------------------------------------------
# Sanitization passes
# ---------------------------------------------------------------------------

def _count_and_strip_zwx(
    text: str, suspicious: list[SuspiciousEntry]
) -> tuple[str, int, list[int]]:
    """Strip zero-width characters, recording each removal. Returns the
    cleaned text, the count, and an offset map: original index of each
    character position in the cleaned text (so later passes can report
    exact original-text offsets)."""
    result = []
    count = 0
    orig_offsets: list[int] = []
    for i, ch in enumerate(text):
        cp = ord(ch)
        if cp in ZERO_WIDTH_CHARS:
            suspicious.append(SuspiciousEntry(
                offset=i, original=ch, replacement="<ZWX>",
                kind="zero-width",
            ))
            count += 1
        else:
            result.append(ch)
            orig_offsets.append(i)
    return "".join(result), count, orig_offsets


def _count_and_normalize_homoglyphs(
    text: str, suspicious: list[SuspiciousEntry],
    orig_offsets: list[int] | None = None,
) -> tuple[str, int]:
    """Replace homoglyphs with ASCII equivalents, recording each replacement
    at its ORIGINAL-text offset (mapped back through the zwx-strip table so
    all suspicious entries share one coordinate space)."""
    result = []
    count = 0
    for i, ch in enumerate(text):
        cp = ord(ch)
        if cp in ALL_HOMOGLYPHS:
            replacement, desc = ALL_HOMOGLYPHS[cp]
            reported = orig_offsets[i] if orig_offsets is not None else i
            suspicious.append(SuspiciousEntry(
                offset=reported, original=ch, replacement=replacement,
                kind="homoglyph",
            ))
            count += 1
            result.append(replacement)
        else:
            result.append(ch)
    return "".join(result), count


# Characters escaped inside a wrapped marker so the payload loses its
# instruction semantics (e.g. <|im_start|> → &lt;|im_start|&gt; — the literal
# special-token bytes are gone, the text is visibly flagged).
MARKER_ESCAPES: dict[str, str] = {
    "<": "&lt;",
    ">": "&gt;",
    "[": "&lbrack;",
    "]": "&rbrack;",
    "#": "&num;",
    "`": "&grave;",
    ":": "&colon;",
    '"': "&quot;",
    "'": "&apos;",
}


def _escape_marker_text(text: str) -> str:
    """Escape delimiter chars inside a marker so it no longer parses as one."""
    return "".join(MARKER_ESCAPES.get(ch, ch) for ch in text)


def _count_and_neutralize_markers(
    text: str,
    suspicious: list[SuspiciousEntry],
    sentinel_prefix: str = "INJ",
    orig_offsets: list[int] | None = None,
) -> tuple[str, int]:
    """Wrap LLM instruction markers in visible sentinels, escaping the marker's
    delimiter characters inside the sentinel so the payload no longer carries
    instruction semantics (idempotent: escapes contain no re-matchable chars).
    If orig_offsets is given (post-zwx offset map), suspicious marker offsets
    are reported against the ORIGINAL text."""
    count = 0
    result = text

    for pattern, desc in MARKER_PATTERNS:
        def replacer(m, _desc=desc):
            nonlocal count
            count += 1
            escaped = _escape_marker_text(m.group())
            offset = m.start()
            if orig_offsets is not None and offset < len(orig_offsets):
                offset = orig_offsets[offset]
            suspicious.append(SuspiciousEntry(
                offset=offset, original=m.group(),
                replacement=f"‹{sentinel_prefix}:{escaped}›",
                kind="marker", desc=_desc,
            ))
            return f"‹{sentinel_prefix}:{escaped}›"
        result = pattern.sub(replacer, result)

    return result, count


def _count_and_strip_ansi(text: str) -> tuple[str, int, int]:
    """Strip ANSI escape sequences and C0 control chars (keep LF/TAB).

    Returns (cleaned_text, ansi_count, ctrl_count).
      ansi_count = escape sequences removed (1 per ESC-led sequence)
      ctrl_count = control characters removed (C0 except LF/TAB, plus DEL;
                   a lone ESC not forming a sequence counts here, not in
                   ansi_count — no double counting).
    Sequence removal runs first, so the ESC bytes inside matched sequences
    are consumed before the control-char sweep.
    """
    ansi_count = 0

    def replacer(_m: re.Match[str]) -> str:
        nonlocal ansi_count
        ansi_count += 1
        return ""

    stripped = ANSI_ESCAPE_RE.sub(replacer, text)

    kept: list[str] = []
    ctrl_count = 0
    for ch in stripped:
        if _is_control_to_strip(ord(ch)):
            ctrl_count += 1
        else:
            kept.append(ch)
    return "".join(kept), ansi_count, ctrl_count


def sanitize(
    text: str,
    mode: str = "full",
    sentinel_prefix: str = "INJ",
) -> SanitizeResult:
    """Run sanitization passes on text. Returns SanitizeResult."""
    suspicious: list[SuspiciousEntry] = []

    result_text = text
    orig_offsets: list[int] | None = None

    if mode in ("full", "zero-width"):
        result_text, zwx_count, orig_offsets = _count_and_strip_zwx(result_text, suspicious)
    else:
        zwx_count = 0

    if mode in ("full", "homoglyph"):
        result_text, homoglyph_count = _count_and_normalize_homoglyphs(
            result_text, suspicious, orig_offsets)
    else:
        homoglyph_count = 0

    if mode in ("full", "markers"):
        result_text, marker_count = _count_and_neutralize_markers(
            result_text, suspicious, sentinel_prefix, orig_offsets,
        )
    else:
        marker_count = 0

    # ansi is a standalone mode (#333): deliberately NOT in "full" so the
    # #307 full-mode semantics stay regression-free.
    if mode == "ansi":
        result_text, ansi_count, ctrl_count = _count_and_strip_ansi(result_text)
    else:
        ansi_count = 0
        ctrl_count = 0

    input_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    output_sha256 = hashlib.sha256(result_text.encode("utf-8")).hexdigest()

    return SanitizeResult(
        output=result_text,
        zwx_count=zwx_count,
        homoglyph_count=homoglyph_count,
        marker_count=marker_count,
        ansi_count=ansi_count,
        ctrl_count=ctrl_count,
        suspicious=[
            {"offset": s.offset, "original": s.original,
             "replacement": s.replacement, "kind": s.kind, "desc": s.desc}
            for s in suspicious
        ],
        input_sha256=input_sha256,
        output_sha256=output_sha256,
        changed=(input_sha256 != output_sha256),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sanitize sample-derived text for prompt-injection safety",
    )
    parser.add_argument("--in", dest="in_path", metavar="PATH",
                        help="Input file path (omit to read stdin)")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON output")
    parser.add_argument("--reproduce", action="store_true",
                        help="Emit field=value reproduce lines")
    parser.add_argument("--mode",
                        choices=["zero-width", "homoglyph", "markers", "ansi", "full"],
                        default="full",
                        help="Sanitization mode (default: full; ansi = strip ANSI/C0)")
    parser.add_argument("--report-only", action="store_true",
                        help="Report findings only, no rewrite")
    parser.add_argument("--sentinel-prefix", default="INJ",
                        help="Custom sentinel prefix for marker wrapping (default: INJ)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Read input — BYTES + strict UTF-8 decode, so neither locale decoding
    # (GBK stdin → silent homoglyph/zwx misses) nor universal-newline
    # normalization (CRLF → sha mismatch) can corrupt the contract.
    if args.in_path:
        try:
            text = Path(args.in_path).read_bytes().decode("utf-8")
        except FileNotFoundError:
            print(f"Error: input file not found: {args.in_path}\n"
                  f"To fix: provide a valid --in PATH to an existing file.",
                  file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"Error: cannot read input file: {exc}\n"
                  f"To fix: check file permissions and path.",
                  file=sys.stderr)
            return 2
        except UnicodeDecodeError:
            print(f"Error: input file is not valid UTF-8: {args.in_path}\n"
                  f"To fix: sanitize expects text input (UTF-8); pass a "
                  f"text/decoded file, not raw binary.",
                  file=sys.stderr)
            return 2
    else:
        try:
            text = sys.stdin.buffer.read().decode("utf-8")
        except UnicodeDecodeError:
            print(f"Error: stdin is not valid UTF-8\n"
                  f"To fix: pipe UTF-8 text input or use --in PATH.",
                  file=sys.stderr)
            return 2
        except Exception as exc:
            print(f"Error: cannot read stdin: {exc}\n"
                  f"To fix: pipe input or use --in PATH.",
                  file=sys.stderr)
            return 2

    # Run sanitization
    result = sanitize(text, mode=args.mode, sentinel_prefix=args.sentinel_prefix)

    # --report-only: findings without output
    if args.report_only:
        report = {
            "input_sha256": result.input_sha256,
            "zwx_count": result.zwx_count,
            "homoglyph_count": result.homoglyph_count,
            "marker_count": result.marker_count,
            "ansi_count": result.ansi_count,
            "ctrl_count": result.ctrl_count,
            "suspicious": result.suspicious,
        }
        json.dump(report, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        # report-only: exit 0 if there were findings, 1 if clean
        return 0 if (result.zwx_count + result.homoglyph_count
                     + result.marker_count
                     + result.ansi_count + result.ctrl_count) > 0 else 1

    # Exit code: 0 if sanitized (changed), 1 if clean (no changes), 2 reserved for errors
    if not result.changed:
        # Nothing to sanitize — output nothing on stdout for text mode
        if args.json:
            report = {
                "input_sha256": result.input_sha256,
                "output_sha256": result.output_sha256,
                "zwx_count": result.zwx_count,
                "homoglyph_count": result.homoglyph_count,
                "marker_count": result.marker_count,
                "ansi_count": result.ansi_count,
                "ctrl_count": result.ctrl_count,
                "suspicious": result.suspicious,
            }
            json.dump(report, sys.stdout, ensure_ascii=False)
            sys.stdout.write("\n")
        return 1

    # Output sanitized text
    if args.reproduce:
        lines = [
            f"input_sha256={result.input_sha256}",
            f"zwx_count={result.zwx_count}",
            f"homoglyph_count={result.homoglyph_count}",
            f"marker_count={result.marker_count}",
            f"ansi_count={result.ansi_count}",
            f"ctrl_count={result.ctrl_count}",
            f"output_sha256={result.output_sha256}",
        ]
        sys.stdout.write("\n".join(lines) + "\n")
    elif args.json:
        report = {
            "input_sha256": result.input_sha256,
            "output_sha256": result.output_sha256,
            "zwx_count": result.zwx_count,
            "homoglyph_count": result.homoglyph_count,
            "marker_count": result.marker_count,
            "ansi_count": result.ansi_count,
            "ctrl_count": result.ctrl_count,
            "output": result.output,
            "suspicious": result.suspicious,
        }
        json.dump(report, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(result.output)

    return 0


if __name__ == "__main__":
    sys.exit(main())
