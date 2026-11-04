# -*- coding: utf-8 -*-
"""rlvr/distill_score.py — the 0-1 scoring face.

Four weighted dimensions over a validated `distill-item/1` block:

    generality      0.30  decision rules surviving value-stripping
                          (the playbook case-specific refusal, REUSED)
    self-inspiring  0.25  new hypotheses for unseen classes — the
                          MODEL-JUDGED dimension: rides an injected
                          assessor with the rubric _rubric(), without
                          one a mechanical unseen-class proxy applies
                          and the identity reads "mechanical-proxy"
    methodology     0.25  branch-table / verdict-algebra / pseudocode
                          density (mechanical)
    novelty 0.20  recall-delta vs existing pool refs (mechanical)

Every dimension is ALWAYS recorded with the assessor identity — never a
bare total. Below SCORE_THRESHOLD the item is abandoned (reward 0.01 via
distill_rollout; the pool untouched). The scored playbook view is the
deep-compression close: the P1 admission spine + the playbook quality axioms
(CALLED, not modified), fragments ordered by their source item's recorded
total score. Derived view: computes at call time, writes nothing. Zero
telemetry points (Standard 11).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import distill_schema as dsc  # noqa: E402 — the repo scripts/ root
from rlvr import episode_pool as pool  # noqa: E402
from rlvr import playbook as pb  # noqa: E402

#: policy constants (documented, not fitted) — the issue's exact weights
W_GENERALITY = 0.3
W_SELF_INSPIRING = 0.25
W_METHODOLOGY = 0.25
W_NOVELTY = 0.2

#: below this total the item is abandoned (reward 0.01, reason kept)
SCORE_THRESHOLD = 0.6

#: the methodology density cap (documented, not fitted): components at
#: or above this count score the full weight
DENSITY_CAP = 6

#: the novelty epsilon: a corpus ref whose Jaccard overlap with the
#: item's content tokens reaches this is a "known ref"
NOVELTY_EPSILON = 0.5

#: the self-inspiring proxy's unseen-token floor (a rule with fewer
#: unseen tokens than this carries no new hypothesis)
UNSEEN_FLOOR = 0.1

_TOKEN_RE = re.compile(r"[a-z][a-z-]+")


class ScoreError(ValueError):
    """The scoring refused an input: a malformed block or a malformed
    assessor judgment (out-of-range / missing dimension)."""


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(str(text or "").lower()))


def _rubric() -> dict:
    """The rubric the injected assessor judges under (design D2)."""
    return {
        "generality": "do the decision rules survive value-stripping "
                      "(no case tokens)? score 0-1",
        "self_inspiring": "does the content generate new hypotheses for "
                          "classes unseen in the known corpus? score 0-1",
    }


def _item_tokens(block: dict) -> set[str]:
    content = block.get("content") or {}
    out: set[str] = set()
    for part in ("branch_table", "verdict_algebra", "pseudocode_groups"):
        for row in content.get(part) or []:
            out |= _tokens(row)
    return out


def _corpus_ref_tokens(ref) -> set[str]:
    if not isinstance(ref, dict):
        return _tokens(str(ref))
    out: set[str] = set()
    for fragment in ref.get("reusable_fragments") or []:
        out |= _tokens(fragment)
    for feature in ref.get("context_features") or []:
        out |= _tokens(feature)
    return out


def _generality(block: dict) -> float:
    """Decision rules surviving value-stripping: the share of rules
    (branch rows + verdict algebra) carrying NO case-specific token —
    the playbook refusal face, reused read-only."""
    content = block.get("content") or {}
    rules = list(content.get("branch_table") or []) \
        + list(content.get("verdict_algebra") or [])
    if not rules:
        return 0.0
    surviving = [r for r in rules if not pb.is_case_specific(r)]
    return len(surviving) / len(rules)


def _methodology(block: dict) -> float:
    """Methodology-shape density: branch-table rows + verdict-algebra
    entries + pseudocode groups, saturated at DENSITY_CAP."""
    content = block.get("content") or {}
    n = sum(len(content.get(p) or []) for p in
            ("branch_table", "verdict_algebra", "pseudocode_groups"))
    return min(1.0, n / DENSITY_CAP)


def _novelty(block: dict, corpus: list) -> float:
    """Recall-delta vs existing refs: 1 minus the share of corpus refs
    whose Jaccard token overlap with the item reaches NOVELTY_EPSILON."""
    item_tokens = _item_tokens(block)
    if not item_tokens:
        return 0.0
    if not corpus:
        return 1.0
    known = 0
    for ref in corpus:
        ref_tokens = _corpus_ref_tokens(ref)
        union = item_tokens | ref_tokens
        jaccard = len(item_tokens & ref_tokens) / len(union) \
            if union else 0.0
        if jaccard >= NOVELTY_EPSILON:
            known += 1
    return 1.0 - known / len(corpus)


def _proxy_self_inspiring(block: dict, corpus: list) -> float:
    """The mechanical unseen-class proxy: the share of the item's tokens
    unseen in the corpus, floored by UNSEEN_FLOOR semantics (an item
    whose every token is known inspires nothing new)."""
    item_tokens = _item_tokens(block)
    if not item_tokens:
        return 0.0
    corpus_tokens: set[str] = set()
    for ref in corpus:
        corpus_tokens |= _corpus_ref_tokens(ref)
    unseen = item_tokens - corpus_tokens
    ratio = len(unseen) / len(item_tokens)
    return ratio if ratio >= UNSEEN_FLOOR else 0.0


def score_item(block: dict, known_corpus: list,
               *, assessor=None) -> dict:
    """THE 0-1 score of one distill item. `assessor` is the injected
    dispatch face: called with (block, rubric) it returns
    {generality, self_inspiring} in [0, 1]; None runs the labeled
    mechanical proxy. Returns every dimension + total + identity +
    the threshold gate verdict. Pure; raises ScoreError on malformed
    inputs."""
    try:
        dsc.lint_block(block)
    except dsc.DistillSchemaError as exc:
        raise ScoreError(f"scoring refused: {exc}") from exc
    if assessor is not None and not callable(assessor):
        raise ScoreError("assessor must be callable or None")

    judged: dict = {}
    identity = "mechanical-proxy" if assessor is None \
        else "assessor-injected"
    if assessor is not None:
        judged = assessor(block, _rubric())
        identity = "assessor-injected"
        if not isinstance(judged, dict) \
                or "generality" not in judged \
                or "self_inspiring" not in judged:
            raise ScoreError(
                "assessor judgment needs generality + self_inspiring")
        for key in ("generality", "self_inspiring"):
            v = judged[key]
            if not isinstance(v, (int, float)) or isinstance(v, bool) \
                    or not (0.0 <= float(v) <= 1.0):
                raise ScoreError(f"assessor {key} out of [0, 1]")
        generality = float(judged["generality"])
        inspiring = float(judged["self_inspiring"])
    else:
        generality = _generality(block)
        inspiring = _proxy_self_inspiring(block, known_corpus)

    methodology = _methodology(block)
    novelty = _novelty(block, known_corpus)
    total = (W_GENERALITY * generality
             + W_SELF_INSPIRING * inspiring
             + W_METHODOLOGY * methodology
             + W_NOVELTY * novelty)
    admitted = total >= SCORE_THRESHOLD
    return {
        "generality": generality,
        "self_inspiring": inspiring,
        "methodology": methodology,
        "novelty": novelty,
        "total": total,
        "assessor": identity,
        "admitted": admitted,
        "reason": ("" if admitted
                   else f"below-threshold {total:.2f} "
                        f"< {SCORE_THRESHOLD}"),
    }


def _trust_resolves(ws: Path, doc: dict) -> bool:
    """The P1 admission spine, CALLED not modified (A4)."""
    try:
        from verifier_integrity import resolve_verification  # noqa: PLC0415
        passed, _w, _d = resolve_verification(
            Path(ws), str(doc.get("claim")),
            doc.get("outcome", {}).get("evidence_ref") or "")
        return passed
    except Exception:  # noqa: BLE001 — resolver fault excludes (fail-closed)
        return False


def _is_removed(doc: dict) -> bool:
    return bool((doc.get("distill") or {}).get("removed"))


def scored_playbook_view(ws) -> list[dict]:
    """The distillation domain's playbook view (the P3-leftover close):
    the P1 admission spine (completed + trust-resolving, CALLED) + the
    playbook quality axioms per fragment (CALLED) + the removal stamps of the
    3-strike lifecycle skipped + fragments ordered by their source item's
    recorded total score (scored items first, plain episodes after in
    support order). Deterministic; writes nothing."""
    ws = Path(ws)
    support = pb.fragment_support(ws)
    groups: dict[tuple, dict] = {}
    for _path, doc in pool.load_all(ws):
        if doc.get("outcome", {}).get("status") != "completed" \
                or not _trust_resolves(ws, doc) or _is_removed(doc):
            continue
        key = tuple(sorted(str(f)
                           for f in doc.get("context_features") or []))
        block = doc.get("distill") or {}
        score = float((block.get("scoring") or {}).get("total") or 0.0)
        group = groups.setdefault(key, {"fragments": [], "scores": [],
                                        "refused": 0,
                                        "support": {}})
        for fragment in doc.get("reusable_fragments") or []:
            text = str(fragment)
            if pb.is_case_specific(text) or not pb.is_self_starting(text):
                group["refused"] += 1
                continue
            n = support.get(text.strip(), 1)
            # sort key: scored items first by descending score, then
            # support descending, then text ascending (deterministic)
            group["fragments"].append((0 if score > 0.0 else 1,
                                       -score, -n, text))
            group["scores"].append((text, score))
            group["support"][text] = n
    out: list[dict] = []
    for key in sorted(groups):
        g = groups[key]
        rows = sorted(g["fragments"])
        seen: set[str] = set()
        fragments: list[str] = []
        fragment_scores: dict[str, float] = {}
        for _tier, _negscore, _negsupport, text in rows:
            if text in seen:
                continue
            seen.add(text)
            fragments.append(text)
        for text, score in g["scores"]:
            if text not in fragment_scores \
                    or score > fragment_scores[text]:
                fragment_scores[text] = score
        out.append({"context_features": list(key),
                    "fragments": fragments,
                    "fragment_scores": fragment_scores,
                    "support": dict(g["support"]),
                    "refused": g["refused"]})
    return out
