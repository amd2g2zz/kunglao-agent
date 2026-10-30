# -*- coding: utf-8 -*-
"""claims_view.py — the claim/evidence view utilities (relocated verbatim
from priority_ratio, #886 preparation).

Issue #886 will retire scripts/priority_ratio.py, but the file is a
114-file substrate: most consumers import NON-selection infrastructure
that merely LIVES there. This module is that infrastructure's own home —
the claim/evidence view faces: EvidenceView + Action, the dispatchability
guard (is_open) and the per-claim attempt/tier/cost guards, the action
vocabulary aliases, the #294 downstream term, the #496 capability-card
tool-family vocabulary, the #759 worth channel, the oracle-case loader,
and the convergence round axis. Every body below is a VERBATIM move from
priority_ratio.py (no signature, default, or message changed).

  - priority_ratio.py re-imports these names, so its ordering face and
    every straggler consumer keep their exact surface unchanged;
  - the DELETION of priority_ratio.py itself stays gated on the #886
    ruling — this module is ruling-agnostic preparation;
  - consumers: import from HERE, not from priority_ratio (issue #886).
"""
from __future__ import annotations
# issue 275 batch-3: fail-open handlers leave ONE rate-limited trace —
# the canonical kunglao_log.warn.
# canonical warn: ONE implementation (process-wide dedupe + ledger face)
from kunglao_log import warn
import re
from typing import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from status_defs import TERMINAL, IN_PROGRESS_STATUSES, SUSPENDED
import action_space  # the action-vocabulary registry (classify_action face)
import kunglao_log  # the tolerant JSONL reader (round_index face)


# #294 downstream-blocker term: a claim others depend on is worth starting
# earlier — its sample unblocks a subtree, a leaf's unblocks only itself.
# THREE named free parameters under the ADR-001 governance procedure
# (docs/adr-001-strategy-parameter-governance.md — the discipline the
# removed LAMBDA_DH embodied, now codified). The values
# below carry their #295 earn-in evidence FROM THE REPLAY RULER
# (scripts/replay_ruler.py, run 2026-09-21 against three real historical
# workspaces — offline policy evaluation, read-only):
#
#   earn-in evidence (TTC = replayed ticks to drain, serial dispatch,
#   same-seed configs; anti-starvation: every claim dispatched, zero
#   stalls attributable to the term):
#     cc-case    (25 claims, 215 snaps): base TTC 149 -> term 146 (delta -3)
#     doubao_web (16 claims, 152 snaps): base TTC 142 -> term 137 (delta -5)
#     wbtest     ( 6 claims,  39 snaps): base TTC  32 -> term  32 (delta  0)
#   order digests changed on cc-case/doubao_web (the term reorders real
#   history); identical on wbtest (frontier too small to differentiate).
#
#   W_DOWNSTREAM  — the term's weight inside the composite (bounded lift:
#                   max lift = W_DOWNSTREAM * DOWNSTREAM_CAP < one cold-start
#                   prior draw, so a leaf is never systematically starved).
#                   CHANGING THIS VALUE REQUIRES THE ADR-001 GOVERNED
#                   PROCEDURE — value pins + attached replay evidence; the
#                   pins are tests/test_replay_ruler_294.py hard asserts
#                   and silent drift goes red;
#   DOWNSTREAM_DECAY — geometric decay per dependency-graph level (direct
#                   dependents count 1, grandchildren DECAY, ...);
#   DOWNSTREAM_CAP   — hard clamp on the weighted count (a hub cannot
#                   dominate the sample face no matter how wide its subtree).
DOWNSTREAM_DECAY = 0.5
DOWNSTREAM_CAP = 4.0
W_DOWNSTREAM = 0.1

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
    # posteriors: every action samples the Beta(1,1) prior. (#295: the
    # PQ-categorical surface no longer feeds any score term.)
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
                except (yaml.YAMLError, OSError) as exc:
                    warn("from_workspace", f"{type(exc).__name__}: {exc}")
        caps, obstacles = _scan_failure_artifacts(ws)
        classes, overrides = load_value_weights(ws)
        return cls(frozenset(terminal_claims), verified, {}, lines,
                   caps, obstacles, classes, overrides, Path(ws))


@dataclass(frozen=True)
class Action:
    """A dispatchable action (the scored shape of M1.3 top_actions; skill is the worker's own choice — routing CUT issue #1).

    #792: score = (posterior-mean case value + W_DOWNSTREAM·downstream_term)
    · worth (the #107 draw face and the #295 LAMBDA_DH·ΔH_PQ face are both
    retired — docs/adr-001-strategy-parameter-governance.md). The
    weighted-era term fields (leverage/discriminator/novelty and the old
    lexicographic sort head) are deleted; feeds carries the diagnostics
    (case_value / case_flip_potential / downstream)."""

    claim_id: str
    action: str
    score: float
    skill: str | None
    tier: int
    attempts: int
    cost: float
    weight: float = 1.0  # #759 H2 worth multiplier (exogenous, not a DOF)
    # #107/#294 diagnostics: thompson_sample / case_flip_potential / downstream
    feeds: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        # feeds stay object-level diagnostics, NOT a json face key:
        # consumers compare full to_dict() payloads across workspaces where
        # feed STATES legitimately differ while scores do not.
        return {"claim_id": self.claim_id, "action": self.action,
                "score": round(self.score, 3), "skill": self.skill,
                "weight": round(self.weight, 3), "tier": self.tier}


def is_open(claim: dict) -> bool:
    """Not terminal, not IN_PROGRESS, not PARK (#634: suspended claims exit
    the dispatch frontier; revival is explicit via mission_stall.revive)."""
    st = claim.get("status")
    return (st not in TERMINAL and st not in IN_PROGRESS_STATUSES
            and st not in SUSPENDED)


# ---------- action classification (feeds the Action.category + worker hints) ----------

# The claim-category vocabulary is REGISTRY-OWNED (scripts/action_space.py,
# the action-vocabulary issue). Verbatim move (same tuples, same order): the
# rank output stays byte-identical under default weights, pinned by the
# frozen capture in tests/test_action_space_12.py. The legacy module names
# stay as aliases for the existing consumers (value_replay, think_seat, tests).
import action_space  # noqa: E402  (registry-sourced action field)

_KEYWORD_MAP = action_space.CLAIM_ACTION_KEYWORDS
DEFAULT_ACTION = action_space.DEFAULT_CLAIM_ACTION


def classify_action(claim: dict) -> str:
    """statement + answers_question keywords → action category; no hit →
    evidence_collection. Single scoring authority:
    action_space.classify_claim_action (the action registry)."""
    return action_space.classify_claim_action(claim)


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
    """Total attempt mass at a claim: max(dispatch_count,
    promotion_attempts). Every dispatch accrues dispatch_count; a failed
    dispatch ALSO strikes promotion_attempts — max counts the attempt
    once, never double-counting a failure. Legacy registers without the
    dispatch_count field read the strikes alone (pre-wiring behavior).
    Feeds the flip-potential decay and Action.attempts — the churn
    visibility the strike counter alone never had (a claim dispatched
    7x with zero failures read 0)."""
    return max(dispatch_count_of(claim), strikes_of(claim))


def strikes_of(claim: dict) -> int:
    """promotion_attempts → int; the DLQ failure-STRIKE face (dirty
    tolerance, same guard as attempts_of). The candidate filter and the
    must-ask lane key on THIS — dispatch churn alone never evicts a
    claim from the frontier."""
    return _int_flag(claim.get("promotion_attempts", 0))[0]


def dispatch_count_of(claim: dict) -> int:
    """dispatch_count → int; every dispatch accrues here (dirty
    tolerance, same guard as attempts_of). Absent field → 0 (legacy
    register)."""
    return _int_flag(claim.get("dispatch_count", 0))[0]


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


def downstream_term(claim_id: str, depends_on: dict,
                    claims: Iterable | None = ()) -> float:
    """#294: bounded, decaying downstream_count for one claim.

    Reverse edges over claim_deps/depends_on {child: [parents]} PLUS the
    register's `obstacle_for` fields (the ladder-mint face writes the same
    edge into claim_deps.yaml, but a register-only row must still count —
    the graph, not the file layout, is the signal). BFS from claim_id:
    each dependent at graph distance d contributes DECAY**d; the sum is
    clamped to DOWNSTREAM_CAP. Deterministic pure function of the dep
    inputs — no rng, no wall clock (the seed contract is untouched);
    cycles are cut by a visited set.

    The count is deliberately STATUS-BLIND (settled dependents still
    count): filtering live-only would need the whole register threaded
    through every score and would make the term drift mid-round as
    statuses flip. The cap keeps a stale hub bounded; the replay ruler is
    where a status-aware variant must EARN its place on data.
    """
    rev: dict[str, list[str]] = _reverse_deps(depends_on or {})
    for c in claims or ():
        parent = str(c.get("obstacle_for") or "").strip()
        cid_ = c.get("id")
        if parent and cid_:
            rev.setdefault(parent, []).append(str(cid_))
    if claim_id not in rev:
        return 0.0
    total = 0.0
    seen = {claim_id}
    frontier = [claim_id]
    level = 0
    while frontier:
        level += 1
        nxt: list[str] = []
        for node in frontier:
            for dep in rev.get(node, ()):
                if dep in seen:
                    continue
                seen.add(dep)
                total += DOWNSTREAM_DECAY ** (level - 1)
                nxt.append(dep)
        if total >= DOWNSTREAM_CAP:
            break
        frontier = nxt
    return min(total, DOWNSTREAM_CAP)


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
    # the web analysis chain: the jsir docker face, the iv8 module face
    # and the camoufox L4 MCP (part-split matching hits
    # mcp__camoufox-reverse__* tool names too)
    "jsir": "jsir", "iv8": "iv8", "camoufox": "camoufox",
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


# ===================== Thompson seed contract (EXP-1) =====================

# The round axis reads the convergence ledger by name (the writer's own
# constant, scripts/convergence_check.py — pinned equal by
# tests/test_priority_ratio.py::test_251_accessor_ledger_name_matches_the_writer;
# a local constant avoids importing the whole checker into every ranker
# consumer).
CONV_LEDGER_NAME = ".convergence_ledger.jsonl"


def round_index(ws) -> int:
    """round := RAW snapshot-row count in `<ws>/.convergence_ledger.jsonl`.

    The writer (convergence_check._append_ledger) stores no round field —
    the index IS the row count. The filter mirrors
    convergence_health.assess's snapshot face: a snapshot row has no
    "type" key and carries "open_count" (OPERATOR_ACTION / rollup rows are
    events, not snapshots); unparseable dirty lines are skipped (#103
    tolerance, via the kunglao_log tolerant reader — #863 Family K).
    Deliberately the RAW count, never assess()["rounds"]:
    _dedup_consecutive collapses same-turn rows on wall-clock proximity
    (SAME_TURN_WINDOW_SEC), and a deduped index would leak the clock into
    the seed, breaking machine-independent replay."""
    p = Path(ws) / CONV_LEDGER_NAME
    if not p.exists():
        return 0
    # a dirty row can also parse to a non-dict ("5", "[1,2]") — only a
    # mapping can carry the snapshot face
    return sum(1 for e in kunglao_log.iter_jsonl(
                   p.read_text(encoding="utf-8", errors="replace").splitlines())
               if isinstance(e, dict)
               and "type" not in e and "open_count" in e)
