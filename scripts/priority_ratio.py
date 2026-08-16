#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""priority_ratio.py — M1 DECIDE VoI-proxy action ranking (issue #2, design-spec §3.2).

VoI proxy / cost (purely mechanical, zero LLM calls):
  score(a) = [0.45·L(a) + 0.30·D(a) + 0.25·N(a)] / cost(a)

Components (contract gaps, specs/phase-4/contract.md §1):
  L(a) = leverage: |downstream OPEN claims| normalized (claim_deps depends_on reverse edges); claim with a terminal fact → 0
  D(a) = discriminator: live competitor_group(≥2 OPEN)=1.0 / answers_question=0.5 / else=0.2
  N(a) = novelty: 1 − min(1, terminal facts already produced in the same action category / NOVELTY_BASE)
  cost(a) = TIER_COST[action_tier] = {1:1.0, 2:3.0, 3:10.0}  (deeper higher tier → lower ratio)

The LLM never enters the score: scoring is a pure function (claims, deps,
evidence) → same input, same output (test_scoring_is_deterministic_pure).
The LLM only touches the two seams — claim seeding (writing hypotheses/
discriminator groups) and results (writing facts); ranking is zero-LLM.

Usage:
  python priority_ratio.py <workspace> [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from status_defs import TERMINAL, IN_PROGRESS_STATUSES

WEIGHTS = {"L": 0.45, "D": 0.30, "N": 0.25}
TIER_COST = {1: 1.0, 2: 3.0, 3: 10.0}
NOVELTY_BASE = 3  # 3 terminal facts in a category → N=0 (saturated)


@dataclass(frozen=True)
class EvidenceView:
    """Evidence view (derived from facts/_INDEX, immutable)."""

    terminal_fact_claims: frozenset[str] = frozenset()
    verified_fact_count: int = 0
    fact_count_by_category: dict[str, int] = field(default_factory=dict)
    raw_lines: tuple[str, ...] = ()

    @classmethod
    def from_workspace(cls, ws: Path) -> "EvidenceView":
        """Parse facts/_INDEX.md lines "F<id> | <status> | <claim_id> | <conclusion>".

        terminal_fact_claims: claims cited by facts whose status contains any
        TERMINAL token;
        verified_fact_count:  count of facts whose status contains
        PROVEN/VERIFIED (explore_gate input);
        fact_count_by_category: left empty — priority_ratio derives it from
        (claims, terminal_fact_claims) (this view has no claim statements,
        so it cannot self-classify).
        """
        index = ws / "facts" / "_INDEX.md"
        if not index.exists():  # fixture-layout fallback
            index = ws / "_INDEX.md"
        if not index.exists():
            return cls()
        lines = tuple(
            ln for ln in index.read_text(encoding="utf-8", errors="replace").splitlines()
            if "|" in ln
        )
        terminal_claims: set[str] = set()
        verified = 0
        for line in lines:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                continue
            status, claim_id = parts[1].upper(), parts[2]
            if any(t in status for t in TERMINAL):
                terminal_claims.add(claim_id)
            if "PROVEN" in status or "VERIFIED" in status:
                verified += 1
        return cls(frozenset(terminal_claims), verified, {}, lines)


@dataclass(frozen=True)
class Action:
    """A dispatchable action (the scored shape of M1.3 top_actions; skill is the worker's own choice — routing CUT issue #1)."""

    claim_id: str
    action: str
    score: float
    skill: str | None
    tier: int
    attempts: int
    leverage: float
    discriminator: float
    novelty: float
    cost: float

    def to_dict(self) -> dict:
        return {"claim_id": self.claim_id, "action": self.action,
                "score": round(self.score, 3), "skill": self.skill}


def is_open(claim: dict) -> bool:
    """Not terminal and not IN_PROGRESS (same rule as priority.py L60-64)."""
    return claim.get("status") not in TERMINAL and claim.get("status") not in IN_PROGRESS_STATUSES


# ---------- action classification (unchanged, feeds the novelty region + worker hints) ----------

_KEYWORD_MAP: list[tuple[tuple[str, ...], str]] = [
    (("c2", "mpd", "pegasus", "dead-drop", "dead drop", "c2 配置"), "c2_config_extract"),
    (("命令表", "command table", "命令分发"), "command_table"),
    (("协议", "protocol", "runtime 行为", "network io", "网络"), "protocol_restore"),
    (("持久化", "persistence", "autorun", "注册表"), "persistence"),
    (("注入", "injection", "reflective", "createremotethread"), "injection"),
    (("反分析", "anti-analysis", "anti analysis", "garble", "诱饵", "decoy", "cff", "混淆"), "anti_analysis"),
    (("家族", "family", "归属", "vidar", "wingo", "gsb"), "family_attribution"),
]
DEFAULT_ACTION = "evidence_collection"


def classify_action(claim: dict) -> str:
    """statement + answers_question keywords → action category; no hit → evidence_collection.

    Scoring: each category accumulates keyword hit counts, the highest
    wins; ties broken by _KEYWORD_MAP order.
    """
    text = " ".join([
        str(claim.get("statement", "")),
        str(claim.get("answers_question", "")),
    ]).lower()
    best, best_score = DEFAULT_ACTION, 0
    for keywords, action in _KEYWORD_MAP:
        score = sum(text.count(k) for k in keywords)
        if score > best_score:
            best, best_score = action, score
    return best


# ---------- VoI components ----------

def action_tier(claim: dict) -> int:
    """Action tier = min(evidence_tier_attempted + 1, 3)."""
    return min(int(claim.get("evidence_tier_attempted", 0)) + 1, 3)


def action_cost(claim: dict) -> float:
    """cost = TIER_COST[tier]; a higher tier (deep dive/VM) enlarges the ratio's denominator → lower score."""
    return TIER_COST[action_tier(claim)]


def cheapness(claim: dict) -> float:
    """For explore-mode ranking: 1/cost (high T1 → breadth first). The reciprocal of action_cost."""
    return 1.0 / action_cost(claim)


def _reverse_deps(depends_on: dict) -> dict[str, list[str]]:
    """depends_on {child: [parents]} → reverse edges {parent: [dependents]}."""
    rev: dict[str, list[str]] = {}
    for child, parents in (depends_on or {}).items():
        for p in parents:
            rev.setdefault(p, []).append(child)
    return rev


def _active_competitor_groups(claims: list[dict], competitor_groups: dict) -> set:
    """A live group = ≥2 OPEN members."""
    open_ids = {c.get("id") for c in claims if c.get("id") and is_open(c)}
    active: set = set()
    for g, members in (competitor_groups or {}).items():
        if sum(1 for m in (members or []) if m in open_ids) >= 2:
            active.add(g)
    return active


def _discriminator(claim: dict, active_groups: set) -> float:
    """D: live competitor_group=1.0 / answers_question=0.5 / else=0.2."""
    cg = claim.get("competitor_group")
    if cg and cg in active_groups:
        return 1.0
    if claim.get("answers_question"):
        return 0.5
    return 0.2


def _fact_count_by_category(claims: list[dict], evidence: EvidenceView) -> dict[str, int]:
    """action_cat → terminal fact count.

    Uses evidence.fact_count_by_category directly when non-empty (test
    injection); otherwise derives from (claims, evidence.terminal_fact_claims):
    +1 for each terminal claim's action category.
    """
    if evidence.fact_count_by_category:
        return dict(evidence.fact_count_by_category)
    by_id = {c.get("id"): c for c in claims if c.get("id")}
    counts: dict[str, int] = {}
    for tcid in evidence.terminal_fact_claims:
        c = by_id.get(tcid)
        if c:
            cat = classify_action(c)
            counts[cat] = counts.get(cat, 0) + 1
    return counts


def _novelty(action_cat: str, fact_counts: dict[str, int]) -> float:
    """N = 1 − min(1, facts already produced in the category / NOVELTY_BASE). Unexplored → 1.0; saturated → 0.0."""
    n = fact_counts.get(action_cat, 0)
    return 1.0 - min(1.0, n / NOVELTY_BASE)


def priority_ratio(claims: list[dict], deps: dict, evidence: EvidenceView) -> list[Action]:
    """VoI proxy / cost ranking (purely mechanical, zero LLM).

    Input: claims (claim-register claims[]), deps (claim_deps.yaml {depends_on, competitor_groups}),
          evidence (EvidenceView, with terminal_fact_claims)
    Output: the sorted Action list (score descending, ties broken by lower cost, then by claim_id)
    """
    depends_on = (deps or {}).get("depends_on", {}) or {}
    competitor_groups = (deps or {}).get("competitor_groups", {}) or {}
    rev_deps = _reverse_deps(depends_on)
    open_ids = {c.get("id") for c in claims if c.get("id") and is_open(c)}
    active_groups = _active_competitor_groups(claims, competitor_groups)
    fact_counts = _fact_count_by_category(claims, evidence)
    terminal = evidence.terminal_fact_claims

    # dispatchable candidates: OPEN + attempts<3 + all depends_on terminal
    candidates: list[dict] = []
    for c in claims:
        cid = c.get("id")
        if not cid or not is_open(c):
            continue
        if int(c.get("promotion_attempts", 0)) >= 3:
            continue
        parents = depends_on.get(cid, []) or []
        if any(p not in terminal for p in parents):
            continue
        candidates.append(c)

    # leverage count (per candidate): downstream OPEN dependents; terminal claim → 0
    lev_raw: dict[str, int] = {}
    for c in candidates:
        cid = c["id"]
        if cid in terminal:
            lev_raw[cid] = 0
            continue
        lev_raw[cid] = sum(1 for d in rev_deps.get(cid, []) if d in open_ids)
    max_lev = max(lev_raw.values(), default=0)

    actions: list[Action] = []
    for c in candidates:
        cid = c["id"]
        action_cat = classify_action(c)
        L = (lev_raw[cid] / max_lev) if max_lev else 0.0
        D = _discriminator(c, active_groups)
        N = _novelty(action_cat, fact_counts)
        cost = action_cost(c)
        numerator = WEIGHTS["L"] * L + WEIGHTS["D"] * D + WEIGHTS["N"] * N
        score = round(numerator / cost, 3)
        actions.append(Action(
            claim_id=cid, action=action_cat, score=score, skill=None,
            tier=action_tier(c), attempts=int(c.get("promotion_attempts", 0)),
            leverage=round(L, 3), discriminator=D, novelty=round(N, 3), cost=cost,
        ))
    # score tie within ε → lower cost wins (mechanical ruling, no LLM); then stable by claim_id
    actions.sort(key=lambda a: (-a.score, a.cost, a.claim_id))
    return actions


# ---------- legacy caller compatibility (used by kunglao-decide._cheapness_order) ----------

def next_tier_cost(claim: dict) -> float:
    """[Deprecated, kept for compatibility] the old NEXT_TIER_CHEAP semantics. New code uses action_cost / cheapness."""
    return cheapness(claim)


def _load_yaml(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="priority_ratio.py", description="VoI-proxy action ranking")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    reg = _load_yaml(ws / "claim-register.yaml")
    deps = _load_yaml(ws / "claim_deps.yaml")
    evidence = EvidenceView.from_workspace(ws)
    claims = reg.get("claims") or []
    actions = priority_ratio(claims, deps, evidence)
    out = [a.to_dict() for a in actions]
    print(json.dumps(out, ensure_ascii=False, indent=2) if args.json else "\n".join(
        f"{a.claim_id:<6} {a.action:<22} score={a.score:<7} L={a.leverage} D={a.discriminator} N={a.novelty} cost={a.cost}"
        for a in out) or "(no dispatchable claims)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
