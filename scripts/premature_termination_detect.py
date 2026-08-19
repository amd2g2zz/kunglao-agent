# -*- coding: utf-8 -*-
"""premature_termination_detect.py — detect the fingerprint signature of
premature-termination in an orchestrator's closing declaration (#54, #473).

Premature-termination = the orchestrator declares "task complete" while open
items != 0. This is the 3rd documented recurrence (2026-07-28 / 07-30 /
2026-08-11) plus the 2026-08-18 handoff-escape variant (#473: self-completion
-> invented "pure-manual" tier -> cost/session stop reason -> user-directed
imperatives). The detector scans the closing DECLARATION TEXT for 5
fingerprints:

  F1 self-anchoring        — closing quotes the agent's OWN summary, not the
                             user's verbatim instruction.
  F2 self-invented tiering — invented tiers ("note-only" / deferred / low-
                             priority / #473 human-handoff) that are NOT in
                             the task mask open items.
  F3 cost-semantic drift   — a cost figure (currency OR #473 time-cost)
                             appears in the closing declaration as stop
                             reasoning (cost is never a stop reason —
                             behavior #3).
  F4 false completion      — "task complete" (or #473 its semantic
                             equivalent) co-occurs with open-items-remaining
                             signals.
  F5 user-delegation       — #473: user-directed imperatives (你打开/手动跟/
     escape                   dump 给我) assign the OPERATOR work while open
                             items remain.

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
# #473: HANDOFF_KEYWORDS extend the family — assigning the USER manual work
# ("纯人工 RE" / "手动跟" / "dump 给我") is the same re-tiering move wearing
# a handoff costume: the tier ("human must do it") was never in the task.
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

HANDOFF_KEYWORDS = [
    r"手动",
    r"人工",
    r"\bmanual(?:ly)?\b",
    r"\bby\s+hand\b",
    r"\bGUI\b",
    r"dump\s*给我",
    r"交给用户",
    r"需要人工",
    r"\bhand\s*off\b",
]

# Open-item references: G<digit> (gap ids), #<digit> (issue/task ids),
# C-<digit> (claim ids), the literal "gap"/"item", CJK open-item words
# (缺口/遗留项/未决项 — "gap"/"leftover item"/"unresolved item").
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
# #473: TIME_COST_RE joins the currency figure — "1-2 小时纯人工" is a cost
# argument exactly like "$52.85"; a bare duration report ("扫描花了 30 分钟",
# past-tense fact) stays quiet under the same sentence qualifier rule.
# ---------------------------------------------------------------------------
COST_FIGURE_RE = re.compile(r"[\$￥]\s?\d+(?:\.\d{1,2})?")
TIME_COST_RE = re.compile(
    r"\d+(?:[-~到至]\d+)?\s*(?:小时|分钟|钟头|min(?:ute)?s?|hours?|hrs?)",
    re.IGNORECASE,
)
COST_QUALIFIERS = [
    r"informational",
    r"info[-\s]?only",
    r"for[-\s]?reference",
    r"仅供参考",
    r"仅.{0,3}信息",
    r"\b参考\b",
    # #473: stop-reason qualifiers — the sentence frames cost as why the
    # work stops/gets handed off ("需要 ... 纯人工", "不值得继续").
    r"需要",
    r"纯人工",
    r"人工",
    r"手动",
    r"无法自动化",
    r"不值得",
    r"超过收益",
    r"成本.{0,6}超",
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
    # #473: semantic-equivalent completion — "I've done everything I can"
    # declares done-ness without the literal phrase (2026-08-18 step 1).
    r"我能(?:做的|继续的)(?:事|工作)?都(?:已经)?做(?:了|完)",
    r"没有(?:更多|别的)(?:我能)?做的",
    r"nothing\s+more\s+I\s+can\s+do",
    r"everything\s+I\s+can\s+do\s+(?:has|is)\s+been\s+done",
    r"已经没有(?:可做的|能做的)",
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
    # #473: remaining-work phrasing without item ids — the 2026-08-18
    # escape says "当前剩余的工作需要 ..." (work remains, re-tiered as
    # manual) instead of naming G-ids. 剩余/还需/剩下的 + 工作/任务/RE.
    r"剩余.{0,6}(?:工作|任务|分析|RE)",
    r"还需.{0,6}(?:做|处理|分析|人工)",
    r"剩下的(?:工作|事)",
    r"(?:继续|后续)(?:投入|跟进|分析)",
]

ZERO_OPEN_RE = re.compile(
    r"0\s+open|no\s+open|zero\s+open|all\s+(?:closed|done|proven|resolved)|"
    r"0\s+items?\s+remaining|没有\s*(?:遗留|open)|无\s*(?:遗留|open)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# F5 — user-delegation escape (#473): the closing declaration contains a
# user-directed imperative (assigning the OPERATOR work) while open items
# remain. Patterns: 你打开/你装上/你接着干/你来/手动跟/dump 给我. Sourced from
# the 2026-08-18 step-4 narration ("你能继续的路: Ghidra GUI 手动跟 30 分钟,
# 把字节码 dump 给我" — the escalation rewritten as user errands).
# ---------------------------------------------------------------------------
USER_IMPERATIVE_PATTERNS = [
    r"你(?:能|可以)?(?:继续|接着|来)[的]?(?:路|话)?[：:]?",  # 你能继续的路: / 你接着干
    r"你(?:来|打开|装上|跟|跑|执行|跑一下|手动)",
    r"手动跟",
    r"dump\s*给我",
    r"把.{0,30}(?:给|发|贴)(?:给)?我",
]

# #473 tool-rebuttal duty: a needs-human/cannot-automate assertion makes the
# declaration LEGAL only with tools/_INDEX.yaml + tool-search zero-hit
# evidence attached (the exact spot where the 2026-08-18 worker claimed
# "1-2h manual RE" while tools/_INDEX.yaml's ghidra-decompile-functions
# --addresses reaches the capability without any human GUI session).
NEEDS_HUMAN_RE = re.compile(r"需(?:要)?人工|人工(?:RE|分析|操作)|无法自动化|只能手动|必须手动|需手动", re.IGNORECASE)

# ---------------------------------------------------------------------------
# task_text recovery + agent-region segmentation (F1 only — D3).
# ---------------------------------------------------------------------------
# A line is a task-echo when it leads with a task/user marker FOLLOWED BY A
# COLON (the "：" after the CJK task-source markers / "user:" / "task:"). The
# colon is required so a declaration line like "Task complete." (no colon)
# is NOT stripped.
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
# CJK phrases like "comprehensive analysis"/"re-detect") and ascii tokens
# >= 5 chars (catches "comprehensively",
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
    # #473: handoff keywords are tier-family — a "human must do it" bucket is
    # as self-invented as "备注级". Excluded when the user's own task says it.
    evidence = []
    for pat in TIER_KEYWORDS + HANDOFF_KEYWORDS:
        if task_text and re.search(pat, task_text, re.IGNORECASE):
            # The user themselves used this tier word -> not self-invented.
            continue
        for m in re.finditer(pat, transcript, re.IGNORECASE):
            evidence.append({"pattern": pat, "span": m.group(0)})
    if not evidence:
        return _fp("F2", "self-invented tiering", False, [], "no self-invented tier keyword found")
    # #473: id refs (G1/#2/C-3/缺口) OR remaining-work phrasing both prove
    # items stay open while the tier bucket re-classifies them.
    open_ref_found = any(re.search(p, transcript, re.IGNORECASE)
                         for p in OPEN_ITEM_REFS + OPEN_ITEMS_SIGNALS)
    fired = bool(open_ref_found)
    note = "" if fired else "tier keyword present but no open-item reference nearby"
    return _fp("F2", "self-invented tiering", fired, evidence, note)


def _check_f3_cost_drift(transcript: str) -> dict:
    evidence = []
    for seg in _split_sentences(transcript):
        figure = COST_FIGURE_RE.search(seg) or TIME_COST_RE.search(seg)
        if figure and any(
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


def _check_f5_user_delegation(transcript: str) -> dict:
    """#473: user-directed imperative + open-items-remaining signals in the
    same declaration -> the escalation was rewritten as user errands. A
    zero-open assertion anywhere in the declaration is the genuine-completion
    guard (same D4 shape as F4)."""
    imperative_evidence = []
    for pat in USER_IMPERATIVE_PATTERNS:
        for m in re.finditer(pat, transcript):
            imperative_evidence.append({"pattern": pat, "span": m.group(0)})
    if not imperative_evidence:
        return _fp("F5", "user-delegation escape", False, [],
                   "no user-directed imperative found")
    if ZERO_OPEN_RE.search(transcript):
        return _fp("F5", "user-delegation escape", False, imperative_evidence,
                   "zero-open asserted; imperative not an escape")
    open_ref_found = any(re.search(p, transcript, re.IGNORECASE)
                         for p in OPEN_ITEM_REFS + OPEN_ITEMS_SIGNALS)
    fired = bool(open_ref_found)
    note = "" if fired else "imperative present but no open-item reference nearby"
    return _fp("F5", "user-delegation escape", fired, imperative_evidence, note)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect(transcript: str, task_text: Optional[str] = None) -> dict:
    """Scan `transcript` (the closing declaration) for the premature-
    termination fingerprints. Returns a dict with `fired_count`, `fired_ids`,
    `fingerprints` (each: id, name, fired, evidence[{pattern, span}], note),
    and `require_evidence` (#473: evidence duties — a needs-human assertion
    demands a tool-search zero-hit proof before it is legal).

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
        _check_f5_user_delegation(transcript),
    ]
    fired_ids = [fp["id"] for fp in fingerprints if fp["fired"]]
    # #473 tool-rebuttal duty: needs-human/cannot-automate assertions are
    # legal ONLY with tools/_INDEX.yaml + tool-search zero-hit evidence.
    require_evidence = (
        ["tool_search_zero_hit"] if NEEDS_HUMAN_RE.search(transcript) else []
    )
    return {
        "fired_count": len(fired_ids),
        "fired_ids": fired_ids,
        "fingerprints": fingerprints,
        "require_evidence": require_evidence,
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
