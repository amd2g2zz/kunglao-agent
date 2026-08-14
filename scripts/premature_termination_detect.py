# -*- coding: utf-8 -*-
"""premature_termination_detect.py — detect the 4-fingerprint signature of
premature-termination in an orchestrator's closing declaration (#54).

Premature-termination = the orchestrator declares "task complete" while open
items != 0. This is the 3rd documented recurrence (2026-07-28 / 07-30 /
2026-08-11). The detector scans the closing DECLARATION TEXT for 4 fingerprints:

  F1 self-anchoring        — closing quotes the agent's OWN summary, not the
                             user's verbatim instruction.
  F2 self-invented tiering — invented tiers (备注级 / deferred / low-priority)
                             that are NOT in the task mask open items.
  F3 cost-semantic drift   — a cost figure appears in the closing declaration
                             (cost is never a stop reason — behavior #3).
  F4 false completion      — "task complete" co-occurs with open-items-remaining
                             signals.

LAYERING — this is #54's KEY PROPERTY. It is COMPLEMENTARY to the two existing
mechanical layers, NOT a duplicate of either:

  #43 (scripts/lib_kunglao.py :: drift_detected / signature_rotation) — RUNTIME,
      per-loop-iteration; reads .convergence_ledger.jsonl signature rotation.
      Catches a loop SPINNING (frozen state), not a loop DECLARING DONE with
      open items. The 2026-08-11 failure had a HEALTHY moving ledger while the
      declaration abandoned the goal — #43 would report convergence.
  #44 (hooks/state_anchor.py :: build_anchor) — per-turn, PostToolUse(Agent);
      injects mechanical state. Cures context rot. Does not read the
      declaration text.
  #54 (THIS) — DECLARATION-TIME, transcript-level; reads what the agent SAID at
      termination. Catches the failure that lives in the closing utterance.

#54 does NOT duplicate signature_rotation (#43) or build_anchor (#44): different
input (declaration text, not ledger rows), different time (declaration, not
loop-iteration). See openspec/archive/premature-termination-detect/design.md.

Heuristic, not semantic: regex/keyword patterns only. No LLM call, no network.
The detector reads NO workspace state — only the `transcript` text and the
optional `task_text`. The recall/precision tradeoff is documented in design.md
(D4): the detector fires loudly on the documented failure (4/4 on the issue
fixture) and quietly on clean completions (0 on the clean transcript), with the
pattern tables extensible for future instances. #55 (completion_gate Stop hook)
will consume this detector's JSON report.

Usage:
  python scripts/premature_termination_detect.py <transcript-file> \\
      [--task-text <string> | --task-text-file <path>]
Exit codes:
  0 = no fingerprint fired
  1 = one or more fingerprints fired
  2 = unreadable transcript file
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# F1 — self-anchoring: self-summary done-phrase present + task anchor absent.
# These are phrases an agent uses to SUMMARIZE ITS OWN framing of done-ness
# (not phrases a user uses to instruct). Sourced verbatim from the issue's
# instance evidence ("Substantive task complete", "stopping here is
# appropriate", "run is done") + close paraphrases.
# ---------------------------------------------------------------------------
SELF_SUMMARY_PHRASES = [
    r"substantive\s+(?:task\s+)?complete",
    r"stopping\s+here\s+is\s+appropriate",
    r"\brun\s+is\s+done\b",
    r"\btask\s+complete\b",
    r"\bmission\s+complete\b",
    r"任务完成",
    r"声明完成",
]

# ---------------------------------------------------------------------------
# F2 — self-invented tier keywords: labels that re-tier open items into a
# "don't count" bucket the user never authorized. Sourced verbatim from the
# issue's instance evidence ("备注级（记录即可）", "deferred") + close paraphrases.
# ---------------------------------------------------------------------------
TIER_KEYWORDS = [
    r"备注级",
    r"记录即可",
    r"\bdeferred\b",
    r"\bdefer\b",
    r"low[-\s]priority",
    r"nice[-\s]to[-\s]have",
    r"out[-\s]of[-\s]scope",
    r"non[-\s]?essential",
    r"信息级",
    r"参考级",
    r"低优先级",
]

# Open-item references: G<digit> (gap ids), #<digit> (issue/task ids),
# C-<digit> (claim ids), the literal "gap"/"item", CJK 缺口/遗留项/未决项.
OPEN_ITEM_REFS = [
    r"\bG\d",
    r"#\d+",
    r"C-\d+",
    r"\bgap\b",
    r"\bitems?\b",
    r"缺口",
    r"遗留项",
    r"未决项",
]

# ---------------------------------------------------------------------------
# F3 — cost-semantic drift: a cost figure + an "informational" qualifier
# co-occur in the closing declaration (cost treated as stop reasoning —
# behavior #3 violation). A bare cost figure does NOT fire (D4 precision guard).
# ---------------------------------------------------------------------------
COST_FIGURE_RE = re.compile(r"[\$￥]\s?\d+(?:\.\d{1,2})?")
COST_QUALIFIERS = [
    r"informational",
    r"info[-\s]?only",
    r"for[-\s]?reference",
    r"仅供参考",
    r"仅.{0,3}信息",
    r"\b参考\b",
]

# ---------------------------------------------------------------------------
# F4 — false completion: a completion declaration co-occurs with an
# open-items-REMAINING signal. Zero-open phrasing ("0 open", "all closed") is
# excluded so a genuine completion does not fire (D4 precision guard).
# ---------------------------------------------------------------------------
COMPLETION_PHRASES = [
    r"\btask\s+complete\b",
    r"substantive\s+(?:task\s+)?complete",
    r"\bmission\s+complete\b",
    r"\brun\s+is\s+done\b",
    r"stopping\s+here",
    r"任务完成",
    r"声明完成",
]

OPEN_ITEMS_SIGNALS = [
    r"deferred\s*[（(]?\s*#?\d",
    r"\bqueued\b",
    r"pull\s+in\s+if\s+you\s+want",
    r"\bremaining\b",
    r"\bTODO\b",
    r"未关",
    r"遗留",
    r"未决",
    r"open\s+items?\s*[:：]\s*[1-9]",
]

ZERO_OPEN_RE = re.compile(
    r"0\s+open|no\s+open|zero\s+open|all\s+(?:closed|done|proven|resolved)|"
    r"0\s+items?\s+remaining|没有\s*(?:遗留|open)|无\s*(?:遗留|open)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# task_text recovery + agent-region segmentation (F1 only — D3).
# ---------------------------------------------------------------------------
# A line is a task-echo when it leads with a task/user marker FOLLOWED BY A
# COLON (the "：" after 任务原文 / "user:" / "task:"). The colon is required so
# a declaration line like "Task complete." (no colon) is NOT stripped.
TASK_ECHO_LINE_RE = re.compile(
    r"^\s*(?:任务原文|用户|user|task|instruction|原指令)\s*[：:]",
    re.IGNORECASE | re.MULTILINE,
)

TASK_TEXT_EXTRACT_RE = re.compile(
    r"(?:任务原文|用户原文?|user(?:\s+instruction)?|instruction|原指令|task)"
    r"\s*[：:]\s*[「「\"'『]?(.+?)[」」\"'』]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Content anchors extracted from task_text: CJK runs >= 3 chars (catches
# "全面分析", "重检测") and ascii tokens >= 5 chars (catches "comprehensively",
# "re-analyze"). The length threshold is the primary grammar-word filter; the
# stoplist is a reserved tightening hook (D4).
ANCHOR_CJK_RE = re.compile(r"[一-鿿]{3,}")
ANCHOR_ASCII_RE = re.compile(r"[A-Za-z][A-Za-z-]{4,}")
ANCHOR_STOPLIST = {
    "分析", "如果", "需要", "存在", "当前", "进行", "已经", "可以", "应该",
    "their", "there", "these", "those", "where", "which", "would", "could",
    "should", "every", "about",
}

# Sentence splitter for F3 / F4: splits on CJK terminators, newlines, and ". "
# NOT on a decimal point (negative lookbehind on a digit), so "$52.85" stays
# in one segment.
SENTENCE_SPLIT_RE = re.compile(r"[。！？\n]+|(?<!\d)\.\s+")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fp(fid: str, name: str, fired: bool, evidence: list, note: str) -> dict:
    return {
        "id": fid,
        "name": name,
        "fired": bool(fired),
        "evidence": evidence,
        "note": note,
    }


def _agent_region(transcript: str) -> str:
    """The transcript with task-echo lines (任务原文：/user:/task: headings)
    removed — the space where the agent's OWN declaration lives. F1 checks
    done-phrase + anchor-absence against this region (D3)."""
    kept = [ln for ln in transcript.splitlines() if not TASK_ECHO_LINE_RE.match(ln)]
    return "\n".join(kept)


def _recover_task_text(transcript: str) -> Optional[str]:
    """Recover the user's verbatim instruction from a `任务原文：「...」` /
    `user: ...` / `task: ...` marker line in the transcript. None if no marker."""
    m = TASK_TEXT_EXTRACT_RE.search(transcript)
    return m.group(1).strip() if m else None


def _extract_anchors(task_text: str) -> set:
    """Content anchors from the user's task_text (F1 grounding). CJK runs >= 3
    chars + ascii tokens >= 5 chars, minus the stoplist."""
    anchors = set()
    for m in ANCHOR_CJK_RE.finditer(task_text):
        w = m.group(0)
        if w not in ANCHOR_STOPLIST:
            anchors.add(w)
    for m in ANCHOR_ASCII_RE.finditer(task_text):
        w = m.group(0).lower()
        if w not in ANCHOR_STOPLIST:
            anchors.add(w)
    return anchors


def _split_sentences(text: str) -> list:
    return [p for p in SENTENCE_SPLIT_RE.split(text) if p.strip()]


# ---------------------------------------------------------------------------
# Fingerprint detectors
# ---------------------------------------------------------------------------

def _check_f1_self_anchoring(transcript: str, task_text: Optional[str]) -> dict:
    region = _agent_region(transcript)
    evidence = []
    for pat in SELF_SUMMARY_PHRASES:
        for m in re.finditer(pat, region, re.IGNORECASE):
            evidence.append({"pattern": pat, "span": m.group(0)})
    if not evidence:
        return _fp("F1", "self-anchoring", False, [], "no self-summary done-phrase found")
    if not task_text:
        return _fp(
            "F1", "self-anchoring", False, evidence,
            "indeterminate: no task_text to ground the self-anchoring check",
        )
    anchors = _extract_anchors(task_text)
    if not anchors:
        return _fp(
            "F1", "self-anchoring", False, evidence,
            "indeterminate: task_text yielded no content anchors",
        )
    region_lower = region.lower()
    echoed = sorted(a for a in anchors if a.lower() in region_lower)
    if echoed:
        return _fp(
            "F1", "self-anchoring", False, evidence,
            "declaration echoes task anchor(s): " + ", ".join(echoed),
        )
    return _fp("F1", "self-anchoring", True, evidence, "")


def _check_f2_self_invented_tiering(transcript: str, task_text: Optional[str]) -> dict:
    evidence = []
    for pat in TIER_KEYWORDS:
        if task_text and re.search(pat, task_text, re.IGNORECASE):
            # The user themselves used this tier word -> not self-invented.
            continue
        for m in re.finditer(pat, transcript, re.IGNORECASE):
            evidence.append({"pattern": pat, "span": m.group(0)})
    if not evidence:
        return _fp("F2", "self-invented tiering", False, [], "no self-invented tier keyword found")
    open_ref_found = any(re.search(p, transcript, re.IGNORECASE) for p in OPEN_ITEM_REFS)
    fired = bool(open_ref_found)
    note = "" if fired else "tier keyword present but no open-item reference nearby"
    return _fp("F2", "self-invented tiering", fired, evidence, note)


def _check_f3_cost_drift(transcript: str) -> dict:
    evidence = []
    for seg in _split_sentences(transcript):
        if COST_FIGURE_RE.search(seg) and any(
            re.search(q, seg, re.IGNORECASE) for q in COST_QUALIFIERS
        ):
            evidence.append({
                "pattern": "cost-figure + qualifier (same sentence)",
                "span": seg.strip(),
            })
    return _fp("F3", "cost-semantic drift", bool(evidence), evidence, "")


def _check_f4_false_completion(transcript: str) -> dict:
    completion_evidence = []
    for pat in COMPLETION_PHRASES:
        for m in re.finditer(pat, transcript, re.IGNORECASE):
            completion_evidence.append({"pattern": pat, "span": m.group(0)})
    if not completion_evidence:
        return _fp("F4", "false completion", False, [], "no completion declaration found")
    open_evidence = []
    for seg in _split_sentences(transcript):
        if ZERO_OPEN_RE.search(seg):
            continue  # a genuine zero-open assertion; signals here do not count
        for pat in OPEN_ITEMS_SIGNALS:
            for m in re.finditer(pat, seg, re.IGNORECASE):
                open_evidence.append({"pattern": pat, "span": m.group(0)})
    fired = bool(open_evidence)
    evidence = completion_evidence + open_evidence
    note = "" if fired else "completion declared but no open-items-remaining signal"
    return _fp("F4", "false completion", fired, evidence, note)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect(transcript: str, task_text: Optional[str] = None) -> dict:
    """Scan `transcript` (the closing declaration) for the 4 premature-
    termination fingerprints. Returns a dict with `fired_count`, `fired_ids`,
    and `fingerprints` (each: id, name, fired, evidence[{pattern, span}], note).

    `task_text` (the user's verbatim instruction) grounds F1/F2. When omitted,
    it is recovered from a `任务原文：` / `user:` / `task:` marker; F1 degrades
    to "indeterminate" (not fired) if no task_text is recoverable.
    """
    if task_text is None:
        task_text = _recover_task_text(transcript)
    fingerprints = [
        _check_f1_self_anchoring(transcript, task_text),
        _check_f2_self_invented_tiering(transcript, task_text),
        _check_f3_cost_drift(transcript),
        _check_f4_false_completion(transcript),
    ]
    fired_ids = [fp["id"] for fp in fingerprints if fp["fired"]]
    return {
        "fired_count": len(fired_ids),
        "fired_ids": fired_ids,
        "fingerprints": fingerprints,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect the 4-fingerprint premature-termination signature "
                    "in a closing declaration transcript (#54). Complementary "
                    "to #43 (runtime drift) and #44 (per-turn re-anchor).",
    )
    parser.add_argument("transcript_file", help="UTF-8 text file with the closing declaration transcript")
    parser.add_argument("--task-text", dest="task_text", default=None,
                        help="the user's verbatim task instruction (grounds F1/F2)")
    parser.add_argument("--task-text-file", dest="task_text_file", default=None,
                        help="file containing the user's verbatim task instruction")
    args = parser.parse_args(argv)

    try:
        transcript = Path(args.transcript_file).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"error: cannot read transcript file {args.transcript_file!r}: {exc}",
              file=sys.stderr)
        return 2

    task_text = args.task_text
    if task_text is None and args.task_text_file:
        try:
            task_text = Path(args.task_text_file).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"error: cannot read task-text file {args.task_text_file!r}: {exc}",
                  file=sys.stderr)
            return 2

    report = detect(transcript, task_text=task_text)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["fired_count"] >= 1 else 0


if __name__ == "__main__":
    sys.exit(main())
