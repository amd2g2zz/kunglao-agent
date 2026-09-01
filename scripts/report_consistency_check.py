# -*- coding: utf-8 -*-
"""report_consistency_check — cross-chapter report-INTERNAL consistency checker (#57).

Detects contradictions that live ENTIRELY INSIDE a report markdown (no binary
read, no fact lookup). This is the report-INTERNAL sibling of #50
(`tools/static/disasm_constant_check.py`, report↔binary byte-exact) and the
cross-chapter sibling of the numeric-fidelity caliber rule
(`~/.claude/rules/common/numeric-fidelity.md`). #50 catches a report listing
that diverges from the PE bytes; numeric-fidelity catches a single number's
caliber collapsing across layers; #57 catches two chapters of the SAME report
contradicting each other. Complementary, non-overlapping (see openspec change
`report-consistency-check` design.md D1).

The a2b5e25c customer report (40 pages) had THREE internal contradiction
groups that all slipped past P4 review (sliced per-chapter, no cross-chapter
view), plus a negative-finding scope amplification:

  group A — §3.3 "does not go through the generic HandleCommand" (NEG,
            in the original Chinese) vs §3.4 code title `HandleCommand.func12`
            (POS) vs §4.1 "goes through func12 first" (POS)
  group B — §5.4 "named pipe or shared-memory channel" vs §6.1.3 shared-memory
            code listing (named pipe = zero evidence)
  group C — §1.1 "persistence does not rely on the system registry" (NEG) vs
            §2.3 Run-key table (POS)
  amplify — F035 config-storage negative (env vars are not written to disk)
            restated as a persistence-mechanism negative (persistence does
            not rely on the registry)

Three checks, all heuristic (regex/keyword only — no LLM, no network, no
binary):

  CC1  same-symbol polarity contradiction (group A). A function symbol
       (CamelCase identifier ≥5 chars, or `func\d+`) appears POSITIVE in one
       chapter and NEGATIVE in another. NEG = a routing negator within a
       ±12-char window (CJK negators 不经过/未经过/绕过/跳过, or `bypass|skip|not…through`);
       POS = mentioned without a negator.
  CC2  negative-finding scope amplification (amplify). A config-storage-
       caliber NEGATIVE in one chapter + a persistence-mechanism-caliber
       NEGATIVE in another → WARNING (severity="potential"), reported under
       `amplifications`, NOT counted as a hard inconsistency (the mechanical
       check cannot judge intent — it surfaces the caliber drift for review).
  CC3  conflicting-conclusion divergence (groups B + C). Either a mechanism
       topic (`注册表`(registry)/`registry`, `Run`/`Startup`, `持久化`(persistence)/`persistence`)
       flips polarity across chapters, OR two members of a configured
       exclusive-mechanism pair ({named-pipe, shared-memory}) are BOTH
       POSITIVE (exclusive transports cannot both be the channel).

A `CONFLICT` marker (HTML comment `<!-- CONFLICT: ... -->` or a `CONFLICT:`
label) in a chapter acknowledges its tensions: the CC1/CC3 rows it touches
carry `acknowledged=true` and are NOT counted under `inconsistency_count`
(issue: "contradictory conclusions must converge OR carry an explicit
CONFLICT marker").

Usage:
  python scripts/report_consistency_check.py <report-file>
Exit codes:
  0 = no inconsistencies and no amplifications (acknowledged tensions are OK)
  1 = one or more inconsistencies or amplifications
  2 = unreadable report file

Call contract (report pipeline — follow-up, out of scope for this PR):
  1. After per-chapter review (e.g. hr-report's g6_contradiction_check.py), run
     this checker on the ASSEMBLED markdown for the cross-chapter view P4's
     per-chapter slicing misses.
  2. CC1/CC3 with severity="error" and acknowledged=false → BLOCK (fix the
     contradiction or mark it CONFLICT).
  3. CC2 with severity="potential" → WARN (author preserves the caliber
     explicitly or removes the amplification).
  The JSON shape is stable so a pipeline can consume it without coupling;
  wiring this into hr-report is a cross-repo follow-up.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Optional

# ---------------------------------------------------------------------------
# Chapter segmentation — markdown `## N.N` / `### N.N.N` headers (D2).
# ---------------------------------------------------------------------------
# Real reports use `## 3.3 Title`; sub-sections `### 6.1.3 Title`. The first
# capture is the dotted number; lines before the first header = §preamble.
_HEADER_RE = re.compile(r"^#{2,3}\s+(\d+(?:\.\d+){1,2})\s+(.+?)\s*$", re.MULTILINE)

# Fenced code block (a chapter's evidence region for the "exclusive mechanism"
# / "symbol POS" sub-checks — a bare mention in a code listing is POSITIVE).
_FENCE_RE = re.compile(r"```[^\n`]*\n(.*?)```", re.DOTALL)

# An explicit CONFLICT acknowledgment in a chapter's text.
_CONFLICT_MARKER_RE = re.compile(r"<!--\s*CONFLICT:|CONFLICT:", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Polarity engine — negators that, near a referent, make it NEGATIVE (D3).
# Window = ±12 chars around the referent occurrence.
# ---------------------------------------------------------------------------
_WINDOW = 12

# Routing negators (function-symbol polarity — CC1). Sourced from the fixture's
# "does not go through the generic HandleCommand" (原文 Chinese) + close paraphrases.
_ROUTING_NEGATORS = [
    r"不经过", r"未经过", r"不再经过", r"未经", r"绕过", r"跳过",
    r"不\s*走", r"bypass", r"skip", r"not\s+through",
    r"does\s+not\s+(?:go\s+)?through", r"not\s+via",
]

# Mechanism negators (mechanism-topic polarity — CC3). Sourced from the
# fixture's "persistence does not rely on the system registry" (原文 Chinese) + close paraphrases.
_MECHANISM_NEGATORS = [
    r"不依赖", r"不使用", r"未使用", r"无需", r"不需要", r"不借助",
    r"不经过", r"不\s*走", r"does\s+not\s+(?:rely|use)", r"not\s+(?:rely|use)",
    r"never\s+(?:uses|relies|writes)", r"without",
]

_NEGATORS_ALL = _ROUTING_NEGATORS + _MECHANISM_NEGATORS


def _negator_near(text: str, start: int, end: int, patterns: list[str]) -> bool:
    """True if any negator pattern matches within ±_WINDOW chars of [start,end)."""
    lo = max(0, start - _WINDOW)
    hi = min(len(text), end + _WINDOW)
    window = text[lo:hi]
    return any(re.search(p, window, re.IGNORECASE) for p in patterns)


# ---------------------------------------------------------------------------
# Referent vocabularies (extensible module constants — D4/D6).
# ---------------------------------------------------------------------------

# CC1 — candidate function symbols (auto-extracted). A "symbol" is a CamelCase
# / underscore identifier ≥5 chars OR a `func\d+` token. CJK is NOT a symbol
# (CJK mechanism nouns belong to CC3).
_SYMBOL_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,}|func\d+\w*")
# Common false-positive identifiers to ignore (English prose words, not symbols).
_SYMBOL_STOP = {
    "about", "above", "after", "again", "alpha", "below", "blank", "block",
    "break", "bring", "catch", "chain", "check", "class", "clear", "close",
    "color", "could", "debug", "delta", "depth", "draft", "empty", "entry",
    "every", "false", "first", "frame", "front", "given", "going", "group",
    "have", "hello", "house", "ignore", "index", "input", "intro", "isrva",
    "jsonfile", "known", "large", "last", "left", "length", "level", "light",
    "lower", "match", "might", "model", "never", "night", "notes", "often",
    "order", "other", "outer", "over", "paper", "phase", "piece", "place",
    "plain", "point", "print", "probe", "quote", "raise", "range", "right",
    "round", "sample", "scope", "share", "sheet", "shift", "short", "since",
    "small", "sound", "space", "stage", "stand", "start", "state", "still",
    "stock", "store", "study", "style", "table", "their", "there", "these",
    "thing", "think", "third", "those", "three", "throw", "today", "trace",
    "track", "trial", "trick", "true", "under", "until", "upper", "usage",
    "value", "video", "watch", "where", "which", "while", "whole", "width",
    "world", "would", "write", "wrong", "yield", "your",
}

# CC3 — mechanism TOPIC tokens (CJK + ascii aliases). Each entry is a set of
# surface forms that name the SAME mechanism topic. Polarity is per-topic.
_TOPIC_ALIASES = {
    "registry": [r"注册表", r"registry", r"Run\s*键", r"Run\s*key"],
    "persistence": [r"持久化", r"persistence", r"自启(?:动)?(?:项)?", r"Startup"],
}

# CC3 — exclusive-mechanism pairs. Both members POSITIVE ⇒ flag (D6).
# Each member is a set of surface forms; transport-context words gate the flag
# so a clean report discussing both in a non-channel sense is not cried wolf.
_EXCLUSIVE_MECHANISM_PAIRS = [
    {
        "members": [
            {"id": "named-pipe", "patterns": [r"命名管道", r"named\s*pipe", r"named-pipe"]},
            {"id": "shared-memory", "patterns": [r"共享内存", r"shared\s*memory", r"shared-memory"]},
        ],
        "context": [r"通道", r"channel", r"回传", r"写入", r"write", r"视频流",
                    r"video", r"流", r"stream", r"传输", r"transmit", r"管道"],
    },
]

# CC2 — negative-finding scope amplification caliber keywords + negators.
_CALIBERS = {
    "config-storage": {
        "keywords": [r"环境变量", r"\benv\b", r"配置存储", r"配置(?!项)"],
        "negation": [r"不落盘", r"未落盘", r"不写入", r"未写入", r"不存储",
                     r"不写(?:入)?磁盘", r"does\s+not\s+write", r"not\s+persist"],
    },
    "persistence-mechanism": {
        "keywords": [r"持久化", r"persistence", r"注册表", r"registry",
                     r"Run\s*键", r"Run\s*key", r"Startup", r"启动项"],
        "negation": [r"不依赖", r"不使用", r"未使用", r"无需", r"不借助",
                     r"does\s+not\s+rely", r"not\s+rely", r"never\s+(?:uses|relies)"],
    },
}

# Sentence splitter for CC2 — CJK terminators + newline + ". " (not decimals).
_SENTENCE_SPLIT_RE = re.compile(r"[。！？\n]+|(?<!\d)\.\s+")


# ---------------------------------------------------------------------------
# Chapter model
# ---------------------------------------------------------------------------

class Chapter:
    """A numbered report section. `code` is the concatenation of fenced blocks
    (the evidence region); `prose` is the body minus fenced blocks."""

    __slots__ = ("id", "title", "text", "prose", "code", "has_conflict_marker")

    def __init__(self, cid: str, title: str, text: str):
        self.id = cid
        self.title = title
        self.text = text
        code_parts = [m.group(1) for m in _FENCE_RE.finditer(text)]
        self.code = "\n".join(code_parts)
        self.prose = _FENCE_RE.sub("", text)
        self.has_conflict_marker = bool(_CONFLICT_MARKER_RE.search(text))

    def polarity_of(self, m: re.Match, patterns: list[str]) -> str:
        """'negative' if a negator from `patterns` is near the match, else 'positive'."""
        neg = _negator_near(self.text, m.start(), m.end(), patterns)
        return "negative" if neg else "positive"


def _split_chapters(report_text: str) -> list[Chapter]:
    """Split a report into Chapter objects on `## N.N` / `### N.N.N` headers."""
    marks = list(_HEADER_RE.finditer(report_text))
    if not marks:
        return [Chapter("§preamble", "", report_text)]
    chapters: list[Chapter] = []
    preamble = report_text[: marks[0].start()]
    if preamble.strip():
        chapters.append(Chapter("§preamble", "", preamble))
    for i, m in enumerate(marks):
        cid = "§" + m.group(1)
        title = m.group(2).strip()
        body_start = m.end()
        body_end = marks[i + 1].start() if i + 1 < len(marks) else len(report_text)
        chapters.append(Chapter(cid, title, report_text[body_start:body_end]))
    return chapters


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _span_around(text: str, m: re.Match, width: int = 24) -> str:
    """A readable evidence span around the match (trimmed, single-line)."""
    lo = max(0, m.start() - width // 2)
    hi = min(len(text), m.end() + width // 2)
    return re.sub(r"\s+", " ", text[lo:hi]).strip()


def _acknowledged(chapters_by_id: dict[str, Chapter], chapter_ids: set[str]) -> bool:
    """A contradiction is acknowledged if ANY of its evidence chapters carries
    a CONFLICT marker (the author flagged the tension)."""
    return any(
        cid in chapters_by_id and chapters_by_id[cid].has_conflict_marker
        for cid in chapter_ids
    )


def _sentence_segments(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


# ---------------------------------------------------------------------------
# CC1 — same-symbol polarity contradiction
# ---------------------------------------------------------------------------

def _cc1_symbol_polarity(chapters: list[Chapter]) -> list[dict]:
    """For each auto-extracted symbol, collect per-chapter polarity; flag when
    a symbol has both POS and NEG across chapters.

    Scans the FULL chapter text (prose + code): a code listing that names a
    symbol (e.g. a `HandleCommand.func12:` title) is a POSITIVE assertion that
    the function exists and is the subject — exactly the §3.4 evidence in group
    A. Code mentions carry no negator, so they classify POS; only a real
    NEG-in-prose ↔ POS-in-code (or POS-in-prose) flip fires."""
    # symbol -> list of (chapter_id, polarity, span)
    by_symbol: dict[str, list[tuple[str, str, str]]] = {}
    for ch in chapters:
        for m in _SYMBOL_RE.finditer(ch.text):
            tok = m.group(0)
            if tok.lower() in _SYMBOL_STOP:
                continue
            pol = ch.polarity_of(m, _ROUTING_NEGATORS)
            by_symbol.setdefault(tok, []).append(
                (ch.id, pol, _span_around(ch.text, m)))
    rows: list[dict] = []
    for sym, hits in by_symbol.items():
        pols = {p for _, p, _ in hits}
        if {"positive", "negative"} <= pols:
            grouped: dict[str, list[tuple[str, str]]] = {}
            for cid, p, sp in hits:
                grouped.setdefault(p, []).append((cid, sp))
            chapter_evidence = []
            for p in ("negative", "positive"):
                for cid, sp in grouped.get(p, []):
                    chapter_evidence.append({"chapter": cid, "polarity": p, "span": sp})
            rows.append({
                "id": "CC1",
                "name": "symbol-polarity-contradiction",
                "referent": sym,
                "kind": "symbol-polarity",
                "chapters": chapter_evidence,
                "acknowledged": False,  # set by the orchestrator below
                "severity": "error",
                "note": f"symbol `{sym}` is asserted both positive and negative across chapters",
            })
    return rows


# ---------------------------------------------------------------------------
# CC3a — mechanism-topic polarity contradiction
# ---------------------------------------------------------------------------

def _cc3_topic_polarity(chapters: list[Chapter]) -> list[dict]:
    """For each mechanism topic (alias group), collect per-chapter polarity;
    flag when a topic has both POS and NEG across chapters."""
    rows: list[dict] = []
    for topic, patterns in _TOPIC_ALIASES.items():
        combined = re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)
        hits: list[tuple[str, str, str]] = []
        for ch in chapters:
            for m in combined.finditer(ch.prose):
                pol = ch.polarity_of(m, _MECHANISM_NEGATORS)
                hits.append((ch.id, pol, _span_around(ch.text, m)))
        pols = {p for _, p, _ in hits}
        if {"positive", "negative"} <= pols:
            grouped: dict[str, list[tuple[str, str]]] = {}
            for cid, p, sp in hits:
                grouped.setdefault(p, []).append((cid, sp))
            chapter_evidence = []
            for p in ("negative", "positive"):
                for cid, sp in grouped.get(p, []):
                    chapter_evidence.append({"chapter": cid, "polarity": p, "span": sp})
            rows.append({
                "id": "CC3",
                "name": "topic-polarity-contradiction",
                "referent": topic,
                "kind": "topic-polarity",
                "chapters": chapter_evidence,
                "acknowledged": False,
                "severity": "error",
                "note": f"mechanism topic `{topic}` is asserted both positive and negative across chapters",
            })
    return rows


# ---------------------------------------------------------------------------
# CC3b — exclusive-mechanism pair both-positive (D6)
# ---------------------------------------------------------------------------

def _member_positive(chapters: list[Chapter], member_patterns: list[str],
                     context_patterns: list[str]) -> list[tuple[str, str]]:
    """Chapters where this member is POSITIVE inside a transport context.
    Returns (chapter_id, span) pairs."""
    pat = re.compile("|".join(f"(?:{p})" for p in member_patterns), re.IGNORECASE)
    ctx = re.compile("|".join(f"(?:{p})" for p in context_patterns), re.IGNORECASE)
    out: list[tuple[str, str]] = []
    for ch in chapters:
        region = ch.prose + "\n" + ch.code
        if not ctx.search(region):
            continue
        for m in pat.finditer(region):
            if not _negator_near(region, m.start(), m.end(), _NEGATORS_ALL):
                out.append((ch.id, _span_around(region, m)))
                break
    return out


def _cc3_exclusive_mechanism(chapters: list[Chapter]) -> list[dict]:
    rows: list[dict] = []
    for pair in _EXCLUSIVE_MECHANISM_PAIRS:
        m_a, m_b = pair["members"]
        pos_a = _member_positive(chapters, m_a["patterns"], pair["context"])
        pos_b = _member_positive(chapters, m_b["patterns"], pair["context"])
        if pos_a and pos_b:
            chapter_evidence = (
                [{"chapter": cid, "polarity": "positive", "span": sp,
                  "mechanism": m_a["id"]} for cid, sp in pos_a]
                + [{"chapter": cid, "polarity": "positive", "span": sp,
                    "mechanism": m_b["id"]} for cid, sp in pos_b]
            )
            rows.append({
                "id": "CC3",
                "name": "exclusive-mechanism-contradiction",
                "referent": f"{m_a['id']} / {m_b['id']}",
                "kind": "exclusive-mechanism",
                "chapters": chapter_evidence,
                "acknowledged": False,
                "severity": "error",
                "note": (f"exclusive mechanisms {m_a['id']} and {m_b['id']} are both "
                         f"asserted as the channel — they are mutually exclusive"),
            })
    return rows


# ---------------------------------------------------------------------------
# CC2 — negative-finding scope amplification (caliber escalation)
# ---------------------------------------------------------------------------

def _caliber_negatives(chapters: list[Chapter]) -> dict[str, list[tuple[str, str]]]:
    """For each caliber, the chapters carrying a caliber-NEGATIVE sentence."""
    out: dict[str, list[tuple[str, str]]] = {cal: [] for cal in _CALIBERS}
    for ch in chapters:
        for seg in _sentence_segments(ch.prose):
            for cal, spec in _CALIBERS.items():
                if not any(re.search(p, seg, re.IGNORECASE) for p in spec["keywords"]):
                    continue
                if any(re.search(p, seg, re.IGNORECASE) for p in spec["negation"]):
                    out[cal].append((ch.id, re.sub(r"\s+", " ", seg).strip()))
    return out


def _cc2_amplification(chapters: list[Chapter]) -> list[dict]:
    """Flag when a config-storage NEG and a persistence-mechanism NEG coexist in
    DIFFERENT chapters (caliber escalation). severity=warning (potential)."""
    neg = _caliber_negatives(chapters)
    cfg = neg.get("config-storage", [])
    per = neg.get("persistence-mechanism", [])
    if not cfg or not per:
        return []
    cfg_chapters = {cid for cid, _ in cfg}
    per_chapters = {cid for cid, _ in per}
    # escalation only if the two calibers land in different chapters
    if cfg_chapters & per_chapters and not (cfg_chapters - per_chapters
                                            or per_chapters - cfg_chapters):
        # same single chapter for both → not cross-chapter amplification
        if len(cfg_chapters) == 1 and cfg_chapters == per_chapters:
            return []
    rows: list[dict] = []
    chapters_ev = (
        [{"chapter": cid, "caliber": "config-storage", "span": sp} for cid, sp in cfg]
        + [{"chapter": cid, "caliber": "persistence-mechanism", "span": sp} for cid, sp in per]
    )
    rows.append({
        "id": "CC2",
        "name": "negative-finding-scope-amplification",
        "calibers": ["config-storage", "persistence-mechanism"],
        "chapters": chapters_ev,
        "severity": "potential",
        "note": ("a config-storage negative is restated as a persistence-mechanism "
                 "negative across chapters — verify the caliber was preserved, not amplified"),
    })
    return rows


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check(report_text: str) -> dict:
    """Scan `report_text` (a markdown report) for cross-chapter internal
    inconsistencies. Returns a dict:

      {inconsistency_count, amplification_count, acknowledged_count,
       inconsistencies: [...], amplifications: [...]}

    Each hard inconsistency (CC1/CC3) carries {id, name, referent, kind,
    chapters:[{chapter, polarity, span}], acknowledged, severity, note}. Each
    CC2 amplification carries {id, name, calibers, chapters:[...], severity,
    note}. `inconsistency_count` excludes acknowledged rows.
    """
    chapters = _split_chapters(report_text)
    chapters_by_id = {ch.id: ch for ch in chapters}

    hard = (_cc1_symbol_polarity(chapters)
            + _cc3_topic_polarity(chapters)
            + _cc3_exclusive_mechanism(chapters))

    # Apply CONFLICT-marker acknowledgment to CC1/CC3 rows.
    for row in hard:
        cids = {c["chapter"] for c in row["chapters"]}
        row["acknowledged"] = _acknowledged(chapters_by_id, cids)

    amplifications = _cc2_amplification(chapters)

    hard_count = sum(1 for r in hard if not r.get("acknowledged"))
    ack_count = sum(1 for r in hard if r.get("acknowledged"))
    return {
        "inconsistency_count": hard_count,
        "amplification_count": len(amplifications),
        "acknowledged_count": ack_count,
        "inconsistencies": hard,
        "amplifications": amplifications,
    }


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Cross-chapter report-INTERNAL consistency checker (#57). "
                    "Complementary to #50 (report↔binary byte-exact) and the "
                    "numeric-fidelity caliber rule.",
    )
    ap.add_argument("report_file", help="UTF-8 markdown report file to check")
    args = ap.parse_args(argv)

    try:
        text = open(args.report_file, "r", encoding="utf-8", errors="replace").read()
    except OSError as exc:
        print(f"error: cannot read report file {args.report_file!r}: {exc}",
              file=sys.stderr)
        return 2

    report = check(text)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if (report["inconsistency_count"] > 0
                 or report["amplification_count"] > 0) else 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # #811 入口 UTF-8 保险
    force_utf8()
    sys.exit(main())
