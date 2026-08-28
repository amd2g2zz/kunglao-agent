#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""priority_ratio.py — M1 DECIDE VoI-proxy action ranking (issue #2, design-spec §3.2).

VoI proxy / cost (purely mechanical, zero LLM calls):
  score(a) = [0.45·L(a) + 0.30·D(a) + 0.25·N(a)] / cost(a)

Components (contract gaps, specs/phase-4/contract.md §1):
  L(a) = leverage: |downstream OPEN claims| normalized (claim_deps depends_on reverse edges); claim with a terminal fact → 0
  D(a) = discriminator: live competitor_group(≥2 OPEN)=1.0 / answers_question=0.5 / else=0.2
  N(a) = novelty: 1 − min(1, (terminal facts in the same action category
         + same-strategy historical failures, #496) / NOVELTY_BASE)
  cost(a) = TIER_COST[action_tier] = {1:1.0, 2:3.0, 3:10.0}  (deeper higher tier → lower ratio)

The LLM never enters the score: scoring is a pure function (claims, deps,
evidence) → same input, same output (test_scoring_is_deterministic_pure).
The LLM only touches the two seams — claim seeding (writing hypotheses/
discriminator groups) and results (writing facts); ranking is zero-LLM.

#496 typed-fact consumption (read-only over the #495 record face):
  EvidenceView also derives validated_capability / identified_obstacle
  from analyses/failure-*.yaml and the strategy dispatch log
  (runs/strategy-log.jsonl, appended by hooks/dispatch_gate.py) —
  capability_switch_violation() is the pure judgment behind the
  dispatch-gate capability card; strategy_failures feeds novelty.

#759 H2 value function: runs/value-weights.yaml carries the user's
  structured worth ruling (claim_classes impact→weight, per-claim
  overrides); the resolved multiplier applies to the final ratio
  (score = VoI/cost × weight). Loading is fail-open per entry and whole
  file — absent/corrupt/illegal → weight 1.0, byte-identical to the
  pre-#759 formula. This is the SANCTIONED worth channel (#711 E2:
  replaces hand-edited ranking inputs / SendMessage verdict hacks);
  see SKILL.md "Value ordering".

Usage:
  python priority_ratio.py <workspace> [--json]
"""
from __future__ import annotations

# #534: observability lifeline — module-level emit on load.
import kunglao_log  # noqa: E402

# #534: observability lifeline — module-level emit on load.
try:
    kunglao_log.emit(ws, actor="priority_ratio", action="priority_deviation",
                             detail="module wired")
except NameError:
    pass

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

import value_config
from status_defs import TERMINAL, IN_PROGRESS_STATUSES

WEIGHTS = {"L": 0.45, "D": 0.30, "N": 0.25}
TIER_COST = {1: 1.0, 2: 3.0, 3: 10.0}
NOVELTY_BASE = 3  # 3 terminal facts in a category → N=0 (saturated)
CAPABILITY_BONUS = 1.5  # #823 A3: multiplier for claims holding a validated capability card

# #496: the strategy dispatch log (single writer: hooks/dispatch_gate.py on
# its PASS path; the interface is deliberately optional — no marker, no row).
STRATEGY_LOG = "runs/strategy-log.jsonl"


@dataclass(frozen=True)
class EvidenceView:
    """Evidence view (derived from facts/_INDEX, immutable).

    #496 additions (all default-empty — the pre-#496 call shape is
    positionally compatible): the #495 failure artifacts and the strategy
    dispatch log are consumed READ-ONLY from the workspace."""

    terminal_fact_claims: frozenset[str] = frozenset()
    verified_fact_count: int = 0
    fact_count_by_category: dict[str, int] = field(default_factory=dict)
    raw_lines: tuple[str, ...] = ()
    validated_capabilities: tuple[tuple[str, str], ...] = ()  # (claim_id, text)
    identified_obstacles: tuple[tuple[str, str], ...] = ()  # (claim_id, text)
    strategy_failures: dict[str, int] = field(default_factory=dict)
    claim_strategy: dict[str, str] = field(default_factory=dict)
    # #759 H2: structured user worth ruling (fail-open loaded)
    value_class_weights: dict[str, float] = field(default_factory=dict)
    value_claim_overrides: dict[str, float] = field(default_factory=dict)
    # #823 A3 (N-arm): replay prior P(complete) for this workspace's bucket;
    # 1.0 = neutral → pre-#823 cost math. Resolved only when the flag is on.
    prior_p_complete: float = 1.0

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

        #496: also scans the #495 record face (analyses/failure-*.yaml) and
        the strategy dispatch log — each file individually fail-open, a
        broken artifact never breaks the ranking.
        """
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
        caps, obstacles, covers = _scan_failure_artifacts(ws)
        claim_strategy, strategy_failures = _load_strategy_view(ws, covers)
        classes, overrides = load_value_weights(ws)
        prior_p = _resolve_prior_p(ws) if value_config.is_enabled() else 1.0
        return cls(frozenset(terminal_claims), verified, {}, lines,
                   caps, obstacles, strategy_failures, claim_strategy,
                   classes, overrides, prior_p)


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
    weight: float = 1.0  # #759 H2 value multiplier (appended field — the pre-#759 construction shape is positionally compatible)

    def to_dict(self) -> dict:
        return {"claim_id": self.claim_id, "action": self.action,
                "score": round(self.score, 3), "skill": self.skill,
                "weight": round(self.weight, 3)}


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


def _novelty(action_cat: str, fact_counts: dict[str, int],
             strategy_failures: int = 0) -> float:
    """N = 1 − min(1, (facts already produced in the category + same-strategy
    historical failures) / NOVELTY_BASE). Unexplored → 1.0; saturated → 0.0.

    #496: the strategy term is opt-in — a claim with no [strategy] dispatch
    history keeps strategy_failures=0 and the formula is byte-identical to
    the pre-#496 behavior."""
    n = fact_counts.get(action_cat, 0) + strategy_failures
    return 1.0 - min(1.0, n / NOVELTY_BASE)


# ===================== #496 typed-fact consumption (read-only) =====================

def _scan_failure_artifacts(ws: Path) -> tuple[tuple[tuple[str, str], ...],
                                               tuple[tuple[str, str], ...],
                                               dict[str, int]]:
    """Read-only scan of the #495 record face: analyses/failure-*.yaml.

    Returns (validated_capabilities, identified_obstacles, covers_by_claim).
    One file per claim (record_analysis overwrites) — the file content IS
    the latest analysis. Each file individually fail-open: an unreadable or
    malformed analysis is not evidence, it is skipped without a crash."""
    adir = ws / "analyses"
    caps: list[tuple[str, str]] = []
    obstacles: list[tuple[str, str]] = []
    covers: dict[str, int] = {}
    if not adir.is_dir():
        return tuple(caps), tuple(obstacles), covers
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
        try:
            covers[cid] = int(entry.get("covers_attempt") or 0)
        except (TypeError, ValueError):
            covers[cid] = 0
        cap = str(entry.get("validated_capability") or "").strip()
        obs = str(entry.get("identified_obstacle") or "").strip()
        if cap:
            caps.append((cid, cap))
        if obs:
            obstacles.append((cid, obs))
    return tuple(caps), tuple(obstacles), covers


def _load_strategy_view(ws: Path, covers: dict[str, int]) -> tuple[dict[str, str], dict[str, int]]:
    """Derive (claim_strategy, strategy_failures) from runs/strategy-log.jsonl.

    claim_strategy: claim id -> strategy of its LATEST dispatch row.
    strategy_failures: strategy -> count of dispatch rows whose claim later
    failed — the #495 analysis covers_attempt exceeded the attempts snapshot
    taken at dispatch time (attempts semantics make timestamps redundant: a
    post-dispatch failure always re-records the analysis with a higher
    covers). Rows without a snapshot cannot be judged and are ignored for
    failure counting. Missing/corrupt log -> ({}, {}) — opt-in interface."""
    log = ws / Path(STRATEGY_LOG)
    if not log.is_file():
        return {}, {}
    try:
        rows = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}, {}
    claim_strategy: dict[str, str] = {}
    failures: dict[str, int] = {}
    for line in rows:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict) or e.get("event") != "dispatch":
            continue
        strategy = str(e.get("strategy") or "").strip()
        claim = str(e.get("claim") or "").strip()
        if not strategy or not claim:
            continue
        claim_strategy[claim] = strategy  # file order = latest row wins
        try:
            snapshot = int(e.get("attempts_at_snapshot"))
        except (TypeError, ValueError):
            continue
        if covers.get(claim, 0) > snapshot:
            failures[strategy] = failures.get(strategy, 0) + 1
    return claim_strategy, failures


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


# ===================== #759 H2 value function =====================

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


def _resolve_prior_p(ws: Path) -> float:
    """#823 A3: this workspace's bucket P(complete) from the A1 replay
    priors (same bucket derivation as build_priors). Deferred imports —
    value_replay imports this module at top level (cycle breaker).
    Any read failure → 1.0 (neutral: a missing prior must not reshape
    the ranking, mirroring the #759 fail-open posture)."""
    try:
        import rho_checkpoint
        import value_replay
        priors = {}
        p = ws / "runs" / "value-priors.yaml"
        if p.exists():
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                priors = data
        spec = {}
        sp = ws / "task_spec.yaml"
        if sp.exists():
            data = yaml.safe_load(sp.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                spec = data
        depth = str(spec.get("depth") or "unknown").strip().lower()
        v, _source, _band = rho_checkpoint.v_from_priors(
            priors, depth, value_replay.dominant_family(ws))
        return float(v)
    except (OSError, yaml.YAMLError, ImportError):
        return 1.0


def priority_ratio(claims: list[dict], deps: dict, evidence: EvidenceView) -> list[Action]:
    """VoI proxy / cost ranking (purely mechanical, zero LLM).

    Input: claims (claim-register claims[]), deps (claim_deps.yaml {depends_on, competitor_groups}),
          evidence (EvidenceView, with terminal_fact_claims)
    Output: the sorted Action list (score descending, ties broken by lower cost, then by claim_id)
    """
    # #594/#596: claim_deps.yaml is the authoritative graph, but a fresh
    # workspace ships it empty ("depends_on: {}") — fall back to the
    # operator-natural per-claim depends_on field so the ranking has input
    # (and the per-claim field stops being cosmetic) until claim_deps is
    # hand-populated.
    depends_on = (deps or {}).get("depends_on", {}) or {}
    if not depends_on:
        depends_on = {c["id"]: list(c.get("depends_on") or [])
                      for c in claims if c.get("id") and c.get("depends_on")}
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
        # #496: same-strategy historical failures join the novelty count
        # (opt-in — claims with no [strategy] dispatch history keep N intact)
        strat = evidence.claim_strategy.get(cid)
        s_fails = evidence.strategy_failures.get(strat, 0) if strat else 0
        N = _novelty(action_cat, fact_counts, s_fails)
        cost = action_cost(c)
        numerator = WEIGHTS["L"] * L + WEIGHTS["D"] * D + WEIGHTS["N"] * N
        # #759 H2: the user's structured worth ruling multiplies the final
        # ratio (absent weights → 1.0 → the pre-#759 formula byte-identical).
        weight = claim_value_weight(c, evidence.value_class_weights,
                                    evidence.value_claim_overrides)
        # #823 A3 (N-arm only): feed-side terms — cost inflated by the
        # bucket's inverse P(complete) (rework expectation, floored at 0.05
        # to bound the inflation) and the capability bonus. Flag off → both
        # neutral, byte-identical to the pre-#823 formula.
        cost_eff, bonus = cost, 1.0
        if value_config.is_enabled():
            cost_eff = cost / max(evidence.prior_p_complete, 0.05)
            if any(cid == cap_cid
                   for cap_cid, _ in evidence.validated_capabilities):
                bonus = CAPABILITY_BONUS
        score = round(numerator / cost_eff * weight * bonus, 3)
        actions.append(Action(
            claim_id=cid, action=action_cat, score=score, skill=None,
            tier=action_tier(c), attempts=int(c.get("promotion_attempts", 0)),
            leverage=round(L, 3), discriminator=D, novelty=round(N, 3), cost=cost,
            weight=weight,
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
    # #610: plain-text reads the typed actions; out stays the --json payload only
    out = [a.to_dict() for a in actions]
    print(json.dumps(out, ensure_ascii=False, indent=2) if args.json else "\n".join(
        f"{a.claim_id:<6} {a.action:<22} score={a.score:<7} L={a.leverage} D={a.discriminator} N={a.novelty} cost={a.cost}"
        for a in actions) or "(no dispatchable claims)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
