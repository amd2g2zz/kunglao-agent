#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""priority_ratio.py — M1 DECIDE action ranking, REBUILT (#107).

Owner ruling (issue #107, "探索和价值网络需要完全重构，之前的不要了"):
the weighted VoI-proxy formula score = [0.45·L + 0.30·D + 0.25·N]/cost and
the (bucket, score, claim_id) lexicographic sort are DISCARDED — weights
with no estimation basis, and a boolean bucket that dictated everything.
The explore/exploit dual path (the count-threshold gate module, its
constant, the cheapness spread) died with it: ONE ranker, no phase switch,
no count cliff.

The rebuilt value function (design card #97, unchanged):

    action value = Σ_cases P(flip | action) · case_weight + λ · ΔH_PQ(action)
    rank by Thompson sample per action per tick; stable tie-break claim_id

Concretely, per dispatchable claim (the candidate filter is UNCHANGED:
OPEN + promotion_attempts<3 + every depends_on parent holding a terminal
fact, #594/#596 per-claim fallback, #103 dirty-value tolerance):

  case face — the claim's oracle cases (workspace `oracle/cases/*.yaml`,
  each `target_pq` == the claim's `answers_question`) are Bernoulli
  posteriors (#106 CasePosterior, runs/posteriors.yaml). ONE Thompson Beta
  sample per linked case, summed; a claim with no linked case samples the
  Beta(1,1) prior once — cold start is UNIFORM RANDOM, which is Thompson's
  intrinsic exploration: an uncertain arm occasionally ranks first with no
  threshold gate, and bad priors recover by evidence.

  PQ face — the claim's primary_question categorical (#106
  PQCategorical). ΔH is mechanical: H(categorical), the entropy the
  categorical still carries — the updatable quantity an observation on
  that PQ can remove (a peaked distribution has little left to flip).
  No PQ categorical → ΔH = 0.

  score = (case_face + LAMBDA_DH · ΔH) · worth        (#759 worth channel)

  LAMBDA_DH = 0.25 is the ONLY free parameter of the rebuilt formula
  (#111 integration tests will exercise it). `worth` is the pre-existing
  #759 user worth ruling (runs/value-weights.yaml) — a sanctioned exogenous
  multiplier, not a formula DOF; absent weights → 1.0.

  rng — priority_ratio(claims, deps, evidence, rng=None). rng=None →
  random.Random(0): same inputs → same ranking (anchor-deterministic).
  Live callers (kunglao-decide, worker_budget.check_priority) share ONE
  seed source, posterior_rng(ws) — a digest of the CASES posterior state,
  so the sample moves when evidence moves (the issue's determinism clause:
  "same rank given the same posterior state") and DECIDE + the dispatch
  gate can never disagree about rank #1 (#100/#101 die at the root). The
  per-claim rng is forked from ONE base draw keyed by claim_id, so a
  register reorder never reshuffles dispatch order.

  flip potential (diagnostic, feeds["case_flip_potential"]) — the
  conservative P(cflip) reading: 0.5 at cold start, decayed by the claim's
  promotion_attempts (historical settlements), floored to
  FLIP_POTENTIAL_FALLBACK = 0.3 when the action has no oracle case / PQ
  linkage. It rides Action.feeds; it does NOT enter the score.

The LLM never enters the score; ranking is a pure function of (claims,
deps, evidence, rng). The record faces this module still reads for OTHER
consumers: analyses/failure-*.yaml → validated_capabilities /
identified_obstacles (the dispatch-gate capability card,
strategy_metrics), and runs/value-weights.yaml (#759).

Deleted with the formula (owner ruling): the mission_ledger L-term feeds
(the v_norm/d_slope_norm reads and the old lexicographic sort head —
mission_ledger.py itself KEEPS its V_m data face), the difficulty
D-multiplier, the novelty/strategy-log proxy feeds, the #823 prior_p cost
inflation and the capability bonus.
The routing tables (quickref peeling / jsvmp triage / route_capability)
survive as prior INPUT to hypothesis generation, never as rankers.

Usage:
  python priority_ratio.py <workspace> [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from status_defs import TERMINAL, IN_PROGRESS_STATUSES, SUSPENDED
import kunglao_log  # noqa: E402  (#104: #534 lifeline, emit only)
from posteriors import CasePosterior, PosteriorLedger  # noqa: E402  (#106)

# #107: the single free parameter of the rebuilt value function.
LAMBDA_DH = 0.25
# #107 conservative flip-potential reading (diagnostic only — see feeds).
FLIP_POTENTIAL_BASE = 0.5       # P(cflip) at cold start
FLIP_POTENTIAL_FALLBACK = 0.3   # no oracle case / no PQ linkage

_TIER_COST = {1: 1.0, 2: 3.0, 3: 10.0}

ORACLE_CASES_REL = "oracle/cases"


@dataclass(frozen=True)
class EvidenceView:
    """Evidence view (derived from facts/_INDEX, immutable).

    #107 rebuild: the view carries the record faces OTHER consumers need
    (capability cards, terminal facts, #759 worth weights) plus the
    workspace root (`ws`) the ranker loads #106 posteriors + oracle cases
    from. The weighted-era scoring feeds (mission dynamics, difficulty
    multiplier, novelty proxies, prior_p) are deleted with their formula.
    """

    terminal_fact_claims: frozenset[str] = frozenset()
    verified_fact_count: int = 0
    fact_count_by_category: dict[str, int] = field(default_factory=dict)
    raw_lines: tuple[str, ...] = ()
    validated_capabilities: tuple[tuple[str, str], ...] = ()  # (claim_id, text)
    identified_obstacles: tuple[tuple[str, str], ...] = ()  # (claim_id, text)
    # #759 H2: structured user worth ruling (fail-open loaded)
    value_class_weights: dict[str, float] = field(default_factory=dict)
    value_claim_overrides: dict[str, float] = field(default_factory=dict)
    # #107: workspace root — the ranker reads runs/posteriors.yaml and
    # oracle/cases/*.yaml through it. None (bare construction, tests) → no
    # posteriors: every action samples the Beta(1,1) prior and ΔH = 0.
    ws: Path | None = None

    @classmethod
    def from_workspace(cls, ws: Path) -> "EvidenceView":
        """Parse facts/_INDEX.md lines "F<id> | <status> | <claim_id> | <conclusion>".

        terminal_fact_claims: claims cited by facts whose status contains any
        TERMINAL token;
        verified_fact_count:  count of facts whose status contains
        PROVEN/VERIFIED;
        fact_count_by_category: left empty — the view has no claim
        statements, so it cannot self-classify.

        Also scans the #495 record face (analyses/failure-*.yaml) — each
        file individually fail-open, a broken artifact never breaks the
        ranking."""
        index = ws / "facts" / "_INDEX.md"
        if not index.exists():  # fixture-layout fallback
            index = ws / "_INDEX.md"
        terminal_claims: set[str] = set()
        verified = 0
        lines: tuple[str, ...] = ()
        if index.exists():
            lines = tuple(
                ln for ln in index.read_text(encoding="utf-8", errors="replace").splitlines()
                if "|" in ln
            )
            for line in lines:
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 3:
                    continue
                status, claim_id = parts[1].upper(), parts[2]
                if any(t in status for t in TERMINAL):
                    terminal_claims.add(claim_id)
                if "PROVEN" in status or "VERIFIED" in status:
                    verified += 1
        # #594: a fresh workspace's _INDEX.md carries only the version stamp —
        # zero terminal rows emptying the dispatchability gate. Fall back to
        # the register's PROVEN claims (index rows still win when present).
        if not terminal_claims:
            reg = ws / "claim-register.yaml"
            if reg.exists():
                try:
                    for c in (yaml.safe_load(reg.read_text(encoding="utf-8"))
                              or {}).get("claims") or []:
                        if str(c.get("status", "")).upper() in TERMINAL:
                            terminal_claims.add(c.get("id"))
                except (yaml.YAMLError, OSError):
                    pass  # fail-open: broken register must not break ranking
        caps, obstacles = _scan_failure_artifacts(ws)
        classes, overrides = load_value_weights(ws)
        return cls(frozenset(terminal_claims), verified, {}, lines,
                   caps, obstacles, classes, overrides, Path(ws))


@dataclass(frozen=True)
class Action:
    """A dispatchable action (the scored shape of M1.3 top_actions; skill is the worker's own choice — routing CUT issue #1).

    #107: score = (Thompson case face + LAMBDA_DH·ΔH_PQ) · worth. The
    weighted-era term fields (leverage/discriminator/novelty and the old
    lexicographic sort head) are deleted; feeds carries the new diagnostics."""

    claim_id: str
    action: str
    score: float
    skill: str | None
    tier: int
    attempts: int
    cost: float
    weight: float = 1.0  # #759 H2 worth multiplier (exogenous, not a DOF)
    # #107 diagnostics: thompson_sample / case_flip_potential / dh_pq
    feeds: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        # feeds stay object-level diagnostics, NOT a json face key:
        # consumers compare full to_dict() payloads across workspaces where
        # feed STATES legitimately differ while scores do not.
        return {"claim_id": self.claim_id, "action": self.action,
                "score": round(self.score, 3), "skill": self.skill,
                "weight": round(self.weight, 3)}


def is_open(claim: dict) -> bool:
    """Not terminal, not IN_PROGRESS, not PARK (#634: suspended claims exit
    the dispatch frontier; revival is explicit via mission_stall.revive)."""
    st = claim.get("status")
    return (st not in TERMINAL and st not in IN_PROGRESS_STATUSES
            and st not in SUSPENDED)


# ---------- action classification (feeds the Action.category + worker hints) ----------

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


# ---------- per-claim int guards (#103, unchanged) ----------

def _int_flag(value) -> tuple[int, bool]:
    """int conversion with a dirty flag (#103 per-claim tolerance).

    A register field that fails to parse ("two", a mapping, None) degrades
    to (0, True) — never a ValueError/TypeError escaping one claim's row
    into the whole-workspace conservative BLOCKED. The dirty flag feeds the
    Action.feeds diagnostic instead of a crash.
    """
    try:
        return int(value), False
    except (TypeError, ValueError):
        return 0, True


def attempts_of(claim: dict) -> int:
    """promotion_attempts → int; unparseable → 0 (#103)."""
    return _int_flag(claim.get("promotion_attempts", 0))[0]


def action_tier(claim: dict) -> int:
    """Action tier = min(evidence_tier_attempted + 1, 3); dirty value → tier 1 (#103)."""
    return min(_int_flag(claim.get("evidence_tier_attempted", 0))[0] + 1, 3)


def action_cost(claim: dict) -> float:
    """cost = tier cost (diagnostic field since #107 — the score no longer
    divides by it; the Thompson sample + ΔH carry the value)."""
    return _TIER_COST[action_tier(claim)]


def _reverse_deps(depends_on: dict) -> dict[str, list[str]]:
    """depends_on {child: [parents]} → reverse edges {parent: [dependents]}."""
    rev: dict[str, list[str]] = {}
    for child, parents in (depends_on or {}).items():
        for p in parents:
            rev.setdefault(p, []).append(child)
    return rev


# ===================== #496 typed-fact consumption (capability cards) =====================

def _scan_failure_artifacts(ws: Path) -> tuple[tuple[tuple[str, str], ...],
                                               tuple[tuple[str, str], ...]]:
    """Read-only scan of the #495 record face: analyses/failure-*.yaml.

    Returns (validated_capabilities, identified_obstacles) — the dispatch-
    gate capability card + strategy_metrics inputs. One file per claim
    (record_analysis overwrites) — the file content IS the latest analysis.
    Each file individually fail-open: an unreadable or malformed analysis is
    not evidence, it is skipped without a crash."""
    adir = ws / "analyses"
    caps: list[tuple[str, str]] = []
    obstacles: list[tuple[str, str]] = []
    if not adir.is_dir():
        return tuple(caps), tuple(obstacles)
    for p in sorted(adir.glob("failure-*.yaml")):
        try:
            entry = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 — unreadable analysis is not evidence
            continue
        if not isinstance(entry, dict):
            continue
        cid = str(entry.get("claim") or "").strip()
        if not cid:
            continue
        cap = str(entry.get("validated_capability") or "").strip()
        obs = str(entry.get("identified_obstacle") or "").strip()
        if cap:
            caps.append((cid, cap))
        if obs:
            obstacles.append((cid, obs))
    return tuple(caps), tuple(obstacles)


# #496: tool-family vocabulary for the capability card. A token maps a
# DECLARED tool name (protocol field, part-split) or a capability TEXT
# mention (ASCII word-bounded) to a canonical family. Unknown words never
# match — the judgment is mechanical, no natural-language inference.
_TOOL_FAMILY_BY_TOKEN: dict[str, str] = {
    "frida": "frida", "rev-frida": "frida",
    "xposed": "xposed", "lsposed": "xposed",
    "ghidra": "ghidra",
    "x64dbg": "x64dbg", "ollydbg": "x64dbg",
    "ida": "ida", "idapython": "ida",
    "volatility": "volatility",
    "vmr-shell": "vm", "vmrun": "vm",
    "qiling": "qiling", "malware-framework": "qiling",
}

_DISPROOF_RE = re.compile(r"capability-disproof:\s*([A-Za-z0-9_-]+)", re.IGNORECASE)


def tool_families_from_tools(tools: list[str]) -> set[str]:
    """Families of DECLARED dispatch tool names.

    Part-split matching (mcp__ghidra__import_file -> {mcp, ghidra, import,
    file}) so a token never substring-false-positives inside an unrelated
    tool name (the reason 'ida' cannot match 'pe-validate')."""
    fams: set[str] = set()
    for t in tools or []:
        name = str(t).lower().strip()
        if not name:
            continue
        parts = {p for p in re.split(r"[^a-z0-9]+", name) if p}
        parts.add(name)
        for token, fam in _TOOL_FAMILY_BY_TOKEN.items():
            if token in parts:
                fams.add(fam)
    return fams


def tool_families_from_text(text: str) -> set[str]:
    """Families mentioned in free text (the capability card's only channel —
    #495 records it as prose). ASCII word-bounded, case-insensitive: a
    hyphen/underscore-attached mention still matches ('frida-server' ->
    frida) but a token inside a longer word never does."""
    fams: set[str] = set()
    for token, fam in _TOOL_FAMILY_BY_TOKEN.items():
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(token) + r"(?![A-Za-z0-9])",
                     text or "", re.IGNORECASE):
            fams.add(fam)
    return fams


def capability_switch_violation(claim_ids, dispatch_tools: list[str],
                                prompt_text: str,
                                evidence: "EvidenceView") -> dict | None:
    """#496 ②(a): a validated capability in hand constrains tool choice.

    Card scope is the UNION over ALL in-scope analysis cards (the claim +
    its obstacle_for parent chain). from_workspace yields cards in sorted
    filename order and an obstacle child's id is always greater than its
    parent's, so the pre-F1 `caps[-1]` single-last-card read let the
    child's card shadow the parent's — masking the parent's constraint
    (leak) and falsely blocking a return to the parent's validated family
    (false block). Union semantics: ANY validated family intersecting the
    declared dispatch families = capability in hand, not a switch.

    Violation iff ALL of:
      - at least one in-scope analysis carries a validated_capability
        whose text mentions a known tool family (the cards);
      - the dispatch DECLARES at least one known tool family;
      - the two family sets are disjoint (a genuine switch);
      - some validated family is still in force after the
        `capability-disproof: <family>` exemptions (declaration over
        inference, #447 doctrine: the escape is the orchestrator SHOWING
        the card failed — trajectory-1 replay: switching from validated
        frida to xposed requires showing frida failed). Exemption is per
        family: disproving one family leaves the others in force.

    Returns the violation dict (claim_ids / validated_families /
    dispatch_families / capability) or None (= allowed / fail-open)."""
    ids = {str(c) for c in (claim_ids or [])}
    cards = [cap for cid, cap in evidence.validated_capabilities if cid in ids]
    if not cards:
        return None
    per_card: list[tuple[set[str], str]] = []  # (families, card text)
    cap_fams: set[str] = set()
    for text in cards:
        fams = tool_families_from_text(text)
        per_card.append((fams, text))
        cap_fams |= fams
    disp_fams = tool_families_from_tools(dispatch_tools)
    if not cap_fams or not disp_fams or (cap_fams & disp_fams):
        return None
    named = {m.group(1).lower() for m in _DISPROOF_RE.finditer(prompt_text or "")}
    in_force = {f for f in cap_fams if f.lower() not in named}
    if not in_force:
        return None
    capability = " | ".join(t for fams, t in per_card if fams & in_force)
    return {"claim_ids": sorted(ids), "validated_families": sorted(in_force),
            "dispatch_families": sorted(disp_fams), "capability": capability}


# ===================== #759 H2 value function (worth channel) =====================

VALUE_WEIGHTS_FILE = "runs/value-weights.yaml"

# Mechanical claim→impact-class vocabulary (word-bounded ASCII tokens +
# literal CJK phrases — no natural-language inference, mirroring
# tool_families_from_text's posture). Map order is tie-break priority.
_VALUE_CLASS_TOKENS: list[tuple[str, tuple[str, ...]]] = [
    ("rce", ("rce", "remote code execution", "代码执行", "deserialization")),
    ("dos", ("dos", "denial of service", "拒绝服务")),
    ("sandbox_escape", ("sandbox escape", "逃逸", "escape")),
    ("c2_extract", ("c2", "回连")),
    ("credential_theft", ("credential theft", "凭据窃取", "credential")),
    ("info_disclosure", ("information disclosure", "信息泄露")),
]


def _positive_weights(raw) -> dict[str, float]:
    """Keep only strictly-positive numeric entries; anything else is
    ignored per-entry (fail-open: a bad row must not neutralize the file)."""
    out: dict[str, float] = {}
    for k, v in (raw or {}).items():
        if isinstance(v, bool):
            continue
        try:
            w = float(v)
        except (TypeError, ValueError):
            continue
        if w > 0:
            out[str(k)] = w
    return out


def load_value_weights(ws: Path) -> tuple[dict[str, float], dict[str, float]]:
    """(claim_class_weights, per_claim_overrides) from runs/value-weights.yaml.

    Fail-open at every level: missing file → ({}, {}); unparsable YAML or a
    non-mapping root → ({}, {}); illegal entries dropped individually."""
    path = ws / VALUE_WEIGHTS_FILE
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, {}
    except Exception:  # noqa: BLE001 — corrupt weights never break ranking
        return {}, {}
    if not isinstance(data, dict):
        return {}, {}
    classes = data.get("claim_classes")
    overrides = data.get("overrides")
    return (_positive_weights(classes if isinstance(classes, dict) else None),
            _positive_weights(overrides if isinstance(overrides, dict) else None))


def classify_value_class(claim: dict) -> str | None:
    """Statement + answers_question keyword match against the mechanical
    vocabulary; no hit → None (weight stays 1.0)."""
    text = " ".join([str(claim.get("statement", "")),
                     str(claim.get("answers_question", ""))]).lower()
    for cls_, tokens in _VALUE_CLASS_TOKENS:
        for tok in tokens:
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(tok.lower())
                         + r"(?![A-Za-z0-9])", text, re.IGNORECASE):
                return cls_
    return None


def claim_value_weight(claim: dict,
                       classes: dict[str, float],
                       overrides: dict[str, float]) -> float:
    """Resolution order: per-claim override > explicit value_class field >
    keyword classification > 1.0."""
    cid = str(claim.get("id") or "")
    if cid and cid in overrides:
        return overrides[cid]
    cls_ = str(claim.get("value_class") or "").strip().lower() \
        or classify_value_class(claim)
    if cls_ and cls_ in classes:
        return classes[cls_]
    return 1.0


# ===================== #107 Thompson rebuild =====================

def _load_oracle_cases(ws: Path | None) -> list[tuple[str, str]]:
    """(case_id, target_pq) pairs from `<ws>/oracle/cases/*.yaml`, sorted by
    filename (deterministic). Fail-open per file: a broken case doc is not
    signal, it is skipped. No workspace / no dir → [] (cold start)."""
    if not ws:
        return []
    cdir = Path(ws) / ORACLE_CASES_REL
    if not cdir.is_dir():
        return []
    out: list[tuple[str, str]] = []
    for p in sorted(cdir.glob("*.yaml")):
        try:
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 — unreadable case is not evidence
            continue
        if not isinstance(doc, dict):
            continue
        case_id = str(doc.get("id") or p.stem).strip()
        target_pq = str(doc.get("target_pq") or "").strip()
        if case_id:
            out.append((case_id, target_pq))
    return out


def case_face_seed(ledger: PosteriorLedger) -> int:
    """Deterministic seed digest of the CASES posterior state (#106).

    Only the cases namespace enters the seed: a PQ-categorical update must
    move the ΔH term, not reshuffle the Thompson case samples (one signal,
    one channel). Same posterior state → same ranking (the #107 determinism
    clause); a runner verdict (new alpha/beta) moves the seed — the tick
    variation Thompson needs, with no clock and no counter file."""
    doc = {"cases": {k: ledger.cases[k].to_dict()
                     for k in sorted(ledger.cases)}}
    payload = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16], 16)


def posterior_rng(ws) -> random.Random:
    """THE shared per-tick Thompson seed source — DECIDE (kunglao-decide)
    and the dispatch gate (worker_budget.check_priority) both rank through
    this, so they can never disagree about rank #1 (#100/#101 die at the
    root: one ranker, one seed).

    Seed = case_face_seed(runs/posteriors.yaml); empty/absent ledger →
    Random(0) (cold start). A PosteriorSchemaError (unknown ledger version —
    the #106 version wall) propagates LOUD: DECIDE lands in its
    conservative-BLOCKED path, the gate fails open with a trace. Never a
    silent wrong-schema read."""
    ledger = PosteriorLedger.load(ws)
    if not ledger.cases:
        return random.Random(0)
    return random.Random(case_face_seed(ledger))


def priority_ratio(claims: list[dict], deps: dict, evidence: EvidenceView,
                   rng: random.Random | None = None) -> list[Action]:
    """#107 Thompson ranking (purely mechanical, zero LLM).

    Input: claims (claim-register claims[]), deps (claim_deps.yaml {depends_on, competitor_groups}),
          evidence (EvidenceView; `ws` present → #106 posteriors + oracle cases load),
          rng (injected; None → random.Random(0) — deterministic)
    Output: the sorted Action list (Thompson sample descending, stable
          tie-break by claim_id — the #107 spec sort).

    Candidate filter UNCHANGED from the pre-#107 ranker: OPEN + attempts<3
    + all depends_on parents holding a terminal fact (#594/#596 per-claim
    fallback; #103 dirty-value tolerance). RETRACTED/failure-blocked
    filtering stays the CALLER's job (contract §1)."""
    # #594/#596: claim_deps.yaml is the authoritative graph, but a fresh
    # workspace ships it empty ("depends_on: {}") — fall back to the
    # operator-natural per-claim depends_on field so the ranking has input
    # (and the per-claim field stops being cosmetic) until claim_deps is
    # hand-populated.
    depends_on = (deps or {}).get("depends_on", {}) or {}
    if not depends_on:
        depends_on = {c["id"]: list(c.get("depends_on") or [])
                      for c in claims if c.get("id") and c.get("depends_on")}
    terminal = evidence.terminal_fact_claims

    # dispatchable candidates: OPEN + attempts<3 + all depends_on terminal
    candidates: list[dict] = []
    for c in claims:
        cid = c.get("id")
        if not cid or not is_open(c):
            continue
        if attempts_of(c) >= 3:  # #103: dirty value → 0, never a row-crash
            continue
        parents = depends_on.get(cid, []) or []
        if any(p not in terminal for p in parents):
            continue
        candidates.append(c)

    # #106 posteriors + oracle case linkage (no ws → cold-start priors).
    ledger = (PosteriorLedger.load(evidence.ws)
              if evidence.ws is not None else PosteriorLedger())
    oracle_cases = _load_oracle_cases(evidence.ws)

    # ONE base draw; per-claim forks key on claim_id, so a register reorder
    # never reshuffles the dispatch order (the reorder-stability property).
    if rng is None:
        rng = random.Random(0)  # #107 default: same inputs → same ranking
    base = rng.getrandbits(64)

    actions: list[Action] = []
    for c in candidates:
        cid = c["id"]
        pq = str(c.get("answers_question") or "").strip()
        linked = [case_id for case_id, tpq in oracle_cases
                  if tpq and tpq == pq]
        child = random.Random(f"thompson/{base}/{cid}")
        # case face: ONE Thompson Beta sample per linked oracle case, summed;
        # no linkage → a single Beta(1,1) prior sample (cold start = uniform
        # random: Thompson's intrinsic exploration, no threshold gate).
        if linked:
            case_face = 0.0
            for case_id in linked:
                post = ledger.cases.get(case_id) or CasePosterior(case_id)
                case_face += child.betavariate(post.alpha, post.beta)
            fp = FLIP_POTENTIAL_BASE / (1.0 + attempts_of(c))
            thompson_state = (f"Thompson Beta over {len(linked)} linked oracle "
                              f"case(s) [{', '.join(linked)}] -> "
                              f"sample={round(case_face, 6)}")
        else:
            case_face = child.betavariate(1.0, 1.0)
            fp = min(FLIP_POTENTIAL_BASE / (1.0 + attempts_of(c)),
                     FLIP_POTENTIAL_FALLBACK)
            thompson_state = (f"no linked oracle case (oracle/cases/ target_pq "
                              f"!= '{pq or '-'}') -> Beta(1,1) prior sample="
                              f"{round(case_face, 6)} (cold-start exploration)")
        # ΔH_PQ: H(categorical) — the updatable quantity on the claim's PQ.
        pq_cat = ledger.pqs.get(pq) if pq else None
        dh = pq_cat.entropy() if pq_cat is not None else 0.0
        dh_state = (f"PQ '{pq}' categorical H={round(dh, 6)} bit"
                    if pq_cat is not None else
                    f"no PQ categorical for '{pq or '-'}' in "
                    f"runs/posteriors.yaml -> dH=0")
        # #759 worth channel (exogenous user ruling, not a formula DOF).
        weight = claim_value_weight(c, evidence.value_class_weights,
                                    evidence.value_claim_overrides)
        # stored at 6dp (sort precision; the to_dict/json face still rounds
        # to 3) so the #759 worth multiplier stays an exact identity.
        score = round((case_face + LAMBDA_DH * dh) * weight, 6)
        feeds = {
            "thompson_sample": thompson_state,
            "case_flip_potential": (
                f"P(flip)={round(fp, 3)} (base {FLIP_POTENTIAL_BASE} decayed "
                f"by promotion_attempts={attempts_of(c)})"
                + ("" if linked else
                   f"; no oracle/PQ linkage -> {FLIP_POTENTIAL_FALLBACK} fallback")),
            "dh_pq": dh_state,
        }
        # #103: attempts conversion is per-claim guarded; a dirty raw value
        # scores as 0 and surfaces here as a feed diagnostic instead of
        # freezing the whole DECIDE run in conservative BLOCKED.
        attempts, attempts_dirty = _int_flag(c.get("promotion_attempts", 0))
        if attempts_dirty:
            feeds["A"] = (f"promotion_attempts={c.get('promotion_attempts')!r} "
                          "unparseable -> treated as 0 (#103)")
        actions.append(Action(
            claim_id=cid, action=classify_action(c), score=score, skill=None,
            tier=action_tier(c), attempts=attempts, cost=action_cost(c),
            weight=weight, feeds=feeds,
        ))
    # #107 spec sort: Thompson sample descending, stable tie-break claim_id.
    actions.sort(key=lambda a: (-a.score, a.claim_id))
    return actions


def _load_yaml(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="priority_ratio.py", description="Thompson action ranking (#107)")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    # #534 lifeline (#104): relocated from module scope — the old block read an
    # undefined module-level `ws` and was NameError-swallowed, never emitted.
    try:
        kunglao_log.emit(ws, actor="priority_ratio",
                         action="priority_deviation", detail="module wired")
    except Exception:  # noqa: BLE001 — observability never disturbs the run
        pass
    reg = _load_yaml(ws / "claim-register.yaml")
    deps = _load_yaml(ws / "claim_deps.yaml")
    evidence = EvidenceView.from_workspace(ws)
    claims = reg.get("claims") or []
    actions = priority_ratio(claims, deps, evidence)
    # #610: plain-text reads the typed actions; out stays the --json payload only
    out = [a.to_dict() for a in actions]
    print(json.dumps(out, ensure_ascii=False, indent=2) if args.json else "\n".join(
        f"{a.claim_id:<6} {a.action:<22} score={a.score:<7} tier={a.tier} cost={a.cost}"
        for a in actions) or "(no dispatchable claims)")
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
