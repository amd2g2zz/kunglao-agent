# -*- coding: utf-8 -*-
"""claudemd_frame.py — CLAUDE.md three-segment framing (#755 G2/G3, issue
#758 Wave-2 tail).

The workspace CLAUDE.md is conceptually THREE segments:

    [preamble: version-stamp comment lines (+ any pre-frame prose)]
    <!-- kunglao:frame:v<skill-version> -->      (open marker, G2)
        ...the rendered base-template frame...
    <!-- /kunglao:frame -->                      (close marker)
    [tail: user customization sections]

G2 gives init's render the marker pair; G3 lets upgrade collect-and-merge:
extract the 需求段 (`## Task constraints (task_spec)` block injected by
#455) and the 定制段 (everything outside the frame), rebuild ONLY the frame
segment from the CURRENT template, and reassemble — needful/custom bytes
stay invariant. A marker-less v0.1.2 artifact falls back to a conservative
heading-walk classifier built on #758's heading skeleton; when even that
cannot place every current frame heading the merge REFUSES (skip + WARN,
body untouched) — 宁可旧也不要错删.

Pure text mechanics only: rendering the fresh frame stays with the caller
(kunglao_upgrade owns init-parity param derivation); template_version owns
the heading-skeleton authority (single source — this module never
re-implements its semantics).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REQUIREMENT_HEADING = "## Task constraints (task_spec)"
_OPEN_RE = re.compile(r"^<!--\s*kunglao:frame:v(\S+)\s*-->\s*$", re.MULTILINE)
_STAMP_LINE_RE = re.compile(
    r"^#\s*kunglao_template_version:\s*\S+\s*$", re.MULTILINE)

_HEADING_LINE_RE = re.compile(r"^#{1,6}\s")
_FENCE_RE = re.compile(r"^\s*```")


def frame_headings_via_tv(text: str) -> list[str]:
    """Delegate to THE heading-skeleton authority (#758); exported so tests
    and callers pin one fence-aware extractor."""
    import template_version as _tv
    return _tv.frame_headings_from_text(text)


def frame_open(version: str | None = None) -> str:
    """Versioned open marker. Version defaults to the skill package version
    (template_version.read_skill_version) — merges and renders always stamp
    the CURRENT release."""
    if version is None:
        import template_version as _tv
        version = _tv.read_skill_version()
    return f"<!-- kunglao:frame:v{version} -->"


FRAME_CLOSE = "<!-- /kunglao:frame -->"


def wrap_frame(text: str, version: str | None = None) -> str:
    """Wrap a rendered frame body in the G2 marker pair."""
    if not text.endswith("\n"):
        text += "\n"
    return f"{frame_open(version)}\n{text}{FRAME_CLOSE}\n"


# --------------------------------------------------------------------------
# marked split (G2 fast path)
# --------------------------------------------------------------------------

@dataclass
class MarkedSplit:
    preamble: str            # bytes before the open-marker line ("" if none)
    frame_inner: str | None  # body BETWEEN the markers (None: no pair)
    tail: str                # bytes after the close-marker line
    open_version: str | None = None


def split_marked(text: str) -> MarkedSplit:
    """Byte-range split on the marker PAIR. Both markers must exist — an
    open without a close is treated as unmarked (legacy fallback)."""
    m = _OPEN_RE.search(text)
    if m is None:
        return MarkedSplit("", None, text)
    close_at = text.find(FRAME_CLOSE, m.end())
    if close_at < 0:
        return MarkedSplit("", None, text)
    preamble = text[:m.start()]
    inner = text[m.end():close_at]
    tail = text[close_at + len(FRAME_CLOSE):]
    if tail.startswith("\n"):
        tail = tail[1:]
    return MarkedSplit(preamble, inner, tail, m.group(1))


# --------------------------------------------------------------------------
# requirement segment (需求段)
# --------------------------------------------------------------------------

def _requirement_span(lines: list[str]) -> tuple[int, int] | None:
    """[start, end) line span of the requirement block; end excludes the
    next heading (fence-aware so embedded bash '#' comments are safe)."""
    start = None
    fenced = False
    for idx, raw in enumerate(lines):
        if _FENCE_RE.match(raw):
            fenced = not fenced
            continue
        if fenced:
            continue
        stripped = raw.strip()
        if start is None:
            if stripped == REQUIREMENT_HEADING:
                start = idx
            continue
        if _HEADING_LINE_RE.match(stripped):
            return (start, idx)
    return (start, len(lines)) if start is not None else None


def extract_requirement(text: str) -> tuple[str | None, str]:
    """(block_bytes_or_None, remainder) — the block keeps its exact bytes;
    the remainder is the document with those lines removed."""
    lines = text.splitlines()
    span = _requirement_span(lines)
    if span is None:
        return None, text
    start, end = span
    block = "\n".join(lines[start:end])
    remainder = "\n".join(lines[:start] + lines[end:])
    if text.endswith("\n") and remainder and not remainder.endswith("\n"):
        remainder += "\n"
    return block, remainder


# --------------------------------------------------------------------------
# legacy classifier (unmarked fallback, conservative refusal)
# --------------------------------------------------------------------------

@dataclass
class MergeParts:
    status: str = "refused"                     # applied | refused
    reason: str = ""
    preamble: str = ""
    user_sections: list[tuple[str, str]] = field(default_factory=list)
    stray_prose: list[str] = field(default_factory=list)
    req_block: str | None = None                # 需求段 bytes (pre-split)


def _norm_heading(h: str) -> str:
    return re.sub(r"\{\{[^{}]*\}\}", "<var>", h.strip()).rstrip()


def _line_headings(text: str) -> list[tuple[int, str]]:
    """(line_index, normalized_heading) — same normalization contract as
    template_version.frame_headings_from_text, WITH positional bookkeeping."""
    out: list[tuple[int, str]] = []
    fenced = False
    for idx, raw in enumerate(text.splitlines()):
        stripped = raw.strip()
        if stripped.startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if _HEADING_LINE_RE.match(stripped):
            out.append((idx, _norm_heading(stripped)))
    return out


def _walk_flags(heads: list[tuple[int, str]],
                expected: list[str]) -> list[bool] | None:
    """Per-heading frame-membership booleans; None => refused. Greedy
    in-order walk; a mismatching heading survives as user content ONLY while
    the next wanted heading still appears further down."""
    wi = 0
    flags = [False] * len(heads)
    rest_all = [g for _, g in heads]
    for hi, (_idx, got) in enumerate(heads):
        if wi < len(expected):
            if got == expected[wi]:
                flags[hi] = True
                wi += 1
                continue
            if expected[wi] in rest_all[hi + 1:]:
                continue          # interleaved user section
            return None           # a wanted heading will never place
        # expectation exhausted: trailing headings are user content
    if wi != len(expected):
        return None
    return flags


def plan_legacy(text: str, expected_headings: list[str]) -> MergeParts:
    """Classify an UNMARKED doc against the current frame skeleton.

    In-order heading matches own their spans as frame; other HEADED
    sections are user sections; untitled prose living inside would-be frame
    spans cannot be told apart from template paragraphs, so it is reported
    as stray_prose (the assembler relocates those bytes rather than
    deleting — worst case is relocation, never loss). status refuses unless
    EVERY current-frame heading places in order."""
    req_block, text = extract_requirement(text)
    heads = _line_headings(text)
    if not heads:
        return MergeParts("refused", "no headings — cannot place frame",
                          req_block=req_block)
    flags = _walk_flags(heads, [_norm_heading(h) for h in expected_headings])
    if flags is None:
        return MergeParts("refused", "current frame does not place in order",
                          req_block=req_block)

    lines = text.splitlines()
    first_idx = heads[0][0]
    kept = [l for l in lines[:first_idx] if not _STAMP_LINE_RE.match(l)]
    preamble = "\n".join(kept).rstrip("\n")

    user_sections: list[tuple[str, str]] = []
    stray_prose: list[str] = []
    for pos, (idx, _normed) in enumerate(heads):
        nxt = heads[pos + 1][0] if pos + 1 < len(heads) else len(lines)
        body = "\n".join(lines[idx + 1:nxt])
        if flags[pos]:
            if body.strip():
                stray_prose.append(body)
        else:
            user_sections.append((lines[idx], body))
    return MergeParts("applied", "", preamble=preamble,
                      user_sections=user_sections, stray_prose=stray_prose,
                      req_block=req_block)


def scrub_stamp_lines(text: str) -> str:
    """Drop the #536 stamp comment lines (the guarded stamp refresh owns
    stamps); everything else byte-preserved."""
    return "\n".join(l for l in text.splitlines()
                     if not _STAMP_LINE_RE.match(l))


def scrub_for_remerge(text: str) -> str:
    """scrub_stamp_lines PLUS removal of any existing G2 marker pair lines —
    the remerge always emits a fresh versioned pair itself, so stale marker
    comment lines must never leak into the classified preamble."""
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if _STAMP_LINE_RE.match(line):
            continue
        if s == FRAME_CLOSE or \
                re.fullmatch(r"<!--\s*kunglao:frame:v\S+\s*-->", s):
            continue
        out.append(line)
    return "\n".join(out)


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------

def assemble(parts: MergeParts, new_frame_wrapped: str, *,
             literal_tail: str = "") -> str:
    """Rebuild: [preamble] + [fresh marked frame] + [user sections] +
    [literal_tail (marked-path opaque out-of-frame bytes)] + [relocated
    stray prose]. The frame arrives ALREADY carrying the requirement payload
    (caller feeds it through the template's task_spec_section slot), so
    needful bytes ride where init would have put them."""
    chunks: list[str] = []
    if parts.preamble:
        chunks.append(parts.preamble + "\n")
    chunks.append(new_frame_wrapped.rstrip("\n"))
    out = "\n".join(chunks) + "\n"
    for heading, body in parts.user_sections:
        out += "\n" + heading.rstrip("\n") + "\n"
        if body.strip():
            out += body.rstrip("\n") + "\n"
    if literal_tail.strip():
        out += "\n" + literal_tail.rstrip("\n") + "\n"
    for prose in parts.stray_prose:
        if prose.strip():
            out += "\n" + prose.rstrip("\n") + "\n"
    return out
