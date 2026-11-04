# -*- coding: utf-8 -*-
"""rlvr/playbook.py — playbook compression under the distillation
quality axioms (issue 826, P3 of the #806 axis).

Successful episodes compress into REUSABLE PLAYBOOKS — the legitimate
form of distillation. This face is the P3 COMPRESSION layer over the
P1 playbook view (`pool_indexer.playbook_view` — the admission spine,
CALLED not modified: verified completions, feature-grouped, deduped,
capped). The view owns NO storage: it computes over the pool at call
time and writes nothing (A2 — no parallel store; regenerate =
identical output).

THE QUALITY AXIOMS (repo distillation rulings — generalizable +
self-starting only, case-specific rather discarded, methodology most
welcome):

  CASE-SPECIFIC -> REFUSED. A fragment carrying claim ids, fact ids,
  long hex digests, or artifact paths names one case, not a method;
  it never rides the executor's context (counted per group in
  `refused`).
  SELF-STARTING -> KEPT. A fragment that carries a verb-bearing method
  summary can be applied autonomously; a bare noun phrase cannot.
  SUPPORT -> RANKED. The same fragment text verified in more episodes
  is more generalizable; groups rank fragments by support descending
  (text asc tie-break) so the capped context carries the most
  general guidance first. Per-group `support` reports the counts.

Injection goes through the P2 retrieval face
(`meta_retrieval.assemble` — feature-matched groups, context budget)
and the envelope render. Zero telemetry points (Standard 11).
"""
from __future__ import annotations

import re

from rlvr import episode_pool as pool
from rlvr import pool_indexer

#: case-specific shapes — a fragment naming one case is refused
_CASE_PATTERNS = (
    re.compile(r"\bC-[A-Z0-9]+\b"),                      # claim ids
    re.compile(r"\bF\d{3,}\b"),                          # fact ids
    re.compile(r"\b[0-9a-fA-F]{16,}\b"),                 # long hex digests
    re.compile(r"\b[\w./-]+\.(?:md|json|jsonl|bin|so|dex|apk|ipa)\b"),
    re.compile(r"\bsha(?:256|1|md5)?\s*[:=]", re.IGNORECASE),
)

#: the self-starting verb hints (documented open set — method language)
ACTION_HINTS = frozenset({
    "use", "run", "hook", "attach", "patch", "unpack", "replay", "verify",
    "try", "avoid", "need", "needs", "require", "requires", "missing",
    "work", "works", "fail", "fails", "check", "spawn", "inject", "dump",
    "trace", "decode", "re-sign", "resign", "rebuild", "strip", "wrap",
    "proxy", "pin", "disable", "enable", "install", "invoke", "load",
    "call", "mount", "persist", "tune", "switch", "select", "deliver",
    "bypass", "emulate", "decrypt", "encrypt", "parse", "map", "read",
})

_SUFFIXES = ("ing", "ed", "es", "s")


def is_case_specific(fragment: str) -> bool:
    """True when the fragment names a specific case (claim/fact ids,
    long hex, artifact paths) rather than a method — refused."""
    text = str(fragment or "")
    return any(p.search(text) for p in _CASE_PATTERNS)


def _verb_hit(token: str) -> bool:
    if token in ACTION_HINTS:
        return True
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and token[:-len(suffix)] in ACTION_HINTS:
            return True
    return False


def is_self_starting(fragment: str) -> bool:
    """True when the fragment carries a verb-bearing method summary —
    it can be applied autonomously, without re-deriving the case."""
    tokens = re.findall(r"[a-z][a-z-]*", str(fragment or "").lower())
    return any(_verb_hit(t) for t in tokens)


def fragment_support(ws) -> dict[str, int]:
    """Cross-episode support: normalized fragment text -> the number of
    distinct episodes carrying it (deterministic counting)."""
    counts: dict[str, int] = {}
    for _path, doc in pool.load_all(ws):
        seen = set(doc.get("reusable_fragments") or [])
        for fragment in seen:
            key = str(fragment).strip()
            counts[key] = counts.get(key, 0) + 1
    return counts


def compressed_view(ws) -> list[dict]:
    """The compressed playbook: the P1 view's admission spine, then the
    quality axioms. Groups carry `context_features` (sorted), the kept
    `fragments` (strings, support-ranked), their `support` map, and the
    `refused` count. Deterministic; writes nothing."""
    support = fragment_support(ws)
    groups: list[dict] = []
    for group in pool_indexer.playbook_view(ws):
        kept: list[tuple[int, str]] = []
        support_map: dict[str, int] = {}
        refused = 0
        for fragment in group.get("fragments") or []:
            text = str(fragment)
            if is_case_specific(text) or not is_self_starting(text):
                refused += 1
                continue
            n = support.get(text.strip(), 1)
            kept.append((-n, text))
            support_map[text] = n
        kept.sort()
        groups.append({"context_features":
                       list(group.get("context_features") or []),
                       "fragments": [text for _n, text in kept],
                       "support": {t: support_map[t]
                                   for _n, t in kept},
                       "refused": refused})
    return groups


def knob_on() -> bool:
    """The component-ablation switch (the fourth of four knobs)."""
    import os  # noqa: PLC0415 — leaf face, keeps module import-light
    return os.environ.get("KUNGLAO_META_PLAYBOOK", "1") != "0"
