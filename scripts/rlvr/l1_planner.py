#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/l1_planner.py — the L1 planner: WHAT / WHEN / WHO.

The owner ruling (2026-10-16): the highest-leverage decisions (claim
selection, worker assignment, stopping) sat outside the learning loop —
heuristics + LLM with zero credit attribution. This module is the
planner above the L2 sampler: **action selection is a POLICY, not a
rule**. Every choice is an argmax over value/cost ratios of DTS draws
from the L1 value cells (rlvr.l1_value — the same mechanism as the L2
method-family choice, one level up); there is NO trigger anywhere in
this module ("N failures -> split", "solved -> skip" do not exist as
rules — failure patterns are state features inside ``s``, and solved
knowledge is a candidate action's value, not a veto).

    candidate        {action_kind ∈ dispatch / park / split / verify /
                     reuse, claim, cost, prior, value_hint}. The closed
                     vocabulary is l1_value.ACTION_KINDS; a bad kind is
                     a caller bug (fail fast).
    value            theta ~ Beta(cell posterior of (s, action_kind))
                     times VALUE_SCALE — 1.0 is the neutral value (the
                     prior mean 0.5 × 2), so a cold cell proposes around
                     the neutral point and learned returns move it.
                     ``value_hint`` is the KNOWLEDGE-substrate value: a
                     graded, known value (an existing verified answer's
                     strength — the knowledge query face below), never
                     sampled — you do not pretend uncertainty about a
                     fact. Hints live on the same scale.
    choice           argmax of value / cost. Doing nothing costs 0 —
                     cheapness alone can never win (park's ratio is 0.0
                     by construction, and ties without any positive
                     marginal value fall back to park, the do-nothing
                     baseline). All-zero value means park; a positive
                     value against a zero cost is refused at the
                     candidate boundary (park is the only zero-cost
                     action).

The knowledge seam (T5): ``knowledge_query`` reads the substrate —
the claim register, the facts index (verified answers exist), and the
cross-task posterior store (rlvr.strategy_store rows proving this
claim's identity was solved in another engagement) — and reports
{solved, strength, status, source}. ``plan_for_claim`` offers ``reuse``
(cost REUSE_COST, near zero) with the knowledge strength as its value
whenever the claim is solved: a solved claim is reused unless some
re-attempt's value/cost ratio actually beats the replay's — a
comparison, exactly as the ruling requires ("re-attempt only on
value/cost ratio superiority with positive marginal value").

The advisory consumption face (T4): ``advisory_factors`` is what the
rank path (scripts/priority_ratio.py) consumes. It returns {} WHILE
THE VALUE STORE IS EMPTY — the rank path stays byte-identical until
learning exists — and afterwards a per-claim factor ∈ (0, 1]: the
planner's dispatch SHARE of the claim's candidate ratios. A solved
claim's share drops (reuse dominates its dispatch), so the rank drags
exactly the claims whose dispatch the planner does not endorse. The
learned value's per-STATE component cannot reorder candidates within
one state by construction (the cells are keyed by state, not claim);
its consumers are the planner's own choices and the receipts — the
rank-side signal is the knowledge-driven share.

Posture: pure computation over the store + workspace; every read
fail-open, ONE warn (a broken face never invents knowledge, and never
breaks a plan). No gate, no dispatch decision imports this module
until a later card wires the receipt — advisory first.
"""
from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from pathlib import Path


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kunglao_log import warn

from rlvr import l1_value as lv

SCHEMA = "l1-plan/1"

#: the L1 action vocabulary (the owner ruling's list; single source in
#: l1_value — the cell key's action dimension).
ACTION_KINDS = lv.ACTION_KINDS

#: documented policy constants (NOT fitted): the value scale (the DTS
#: draw's neutral point is 1.0), the near-zero reuse cost (a replay is
#: a read, not a run), and park = the do-nothing baseline (cost 0,
#: value 0 — never a cheapness winner).
VALUE_SCALE = 2.0
REUSE_COST = 0.1
PARK_COST = 0.0

#: the knowledge-strength ladder (documented; the substrate's graded
#: value, never sampled): a verified/certified answer is the full
#: value; a terminal-but-not-verified status (REFUTED / NEGATIVE /
#: DEFERRED / STALE / SUPERSEDED / DEAD facts or claims, and partial
#: statuses) is real knowledge — weaker; a cross-task row is evidence
#: from another engagement — mid-strength.
CERTIFIED_STRENGTH = 1.0
CROSS_TASK_STRENGTH = 0.5
WEAK_STRENGTH = 0.3

_CERTIFIED = frozenset({"PROVEN", "VERIFIED"})

#: the ANSWER faces — the substrate saying an ANSWER TO THE QUESTION
#: exists (a verified answer artifact / another engagement's solve).
#: The register face answers a different question ("is the claim
#: closed?" — lifecycle, which the rank frontier already enforces), so
#: the rank-side drag keys on these two faces only while the planner's
#: own decision set considers every face.
_ANSWER_SOURCES = ("facts_index", "cross_task")


def _terminal_statuses() -> set[str]:
    """The terminal claim-status set from the one source of truth
    (status_defs); an unreadable import degrades to the certified pair
    (never a fabricated vocabulary)."""
    try:
        from status_defs import TERMINAL  # noqa: PLC0415
        return set(TERMINAL)
    except Exception:  # noqa: BLE001 — fail-open, the wall is data
        return set(_CERTIFIED)


def _strength_of(status) -> float | None:
    """A status -> its knowledge strength: certified 1.0, terminal-not-
    verified or partial 0.3, everything else (OPEN / IN_PROGRESS /
    unknown) None — not knowledge."""
    st = str(status or "").strip().upper()
    if not st:
        return None
    if st in _CERTIFIED:
        return CERTIFIED_STRENGTH
    try:
        from status_defs import PARTIAL_STATUSES  # noqa: PLC0415
        partial = set(PARTIAL_STATUSES)
    except Exception:  # noqa: BLE001 — fail-open
        partial = set()
    if st in _terminal_statuses() or st in partial:
        return WEAK_STRENGTH
    return None


# ---------------------------------------------------------------------------
# the knowledge query seam (T5)
# ---------------------------------------------------------------------------

def _register_face(ws: Path, claim: str) -> list[dict]:
    """The claim register's row for THIS claim (status -> strength)."""
    import yaml  # noqa: PLC0415
    p = ws / "claim-register.yaml"
    if not p.is_file():
        return []
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    out = []
    for c in (doc.get("claims") or []):
        if isinstance(c, dict) and str(c.get("id") or "") == claim:
            status = str(c.get("status") or "")
            s = _strength_of(status)
            if s is not None:
                out.append({"source": "register", "status": status,
                            "strength": s})
    return out


def _facts_face(ws: Path, claim: str) -> list[dict]:
    """The facts index rows naming THIS claim (the verified-answer
    channel): "F<id> | <status> | <claim_id> | <conclusion>" (the
    EvidenceView face; the fixture-layout fallback included)."""
    index = ws / "facts" / "_INDEX.md"
    if not index.is_file():
        index = ws / "_INDEX.md"
    if not index.is_file():
        return []
    out = []
    for line in index.read_text(encoding="utf-8",
                                errors="replace").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        if parts[2] != claim:
            continue
        status = parts[1].upper()
        s = _strength_of(status)
        if s is not None:
            out.append({"source": "facts_index", "status": status,
                        "strength": s, "fact": parts[0]})
    return out


def _cross_task_face(ws: Path, claim: str) -> list[dict]:
    """The cross-task posterior store: rows from OTHER workspaces whose
    claim identity is THIS claim and whose settled credit is positive —
    another engagement solved it (the #705 solution-broadcast face
    carries the claim id). Never reads the ws's own rows (the store's
    leave-one-out read)."""
    from rlvr import strategy_store as _store  # noqa: PLC0415
    out = []
    for row in _store.load_rows(ws):
        if str(row.get("claim") or "") != claim:
            continue
        credit = row.get("credit")
        if isinstance(credit, bool) or not isinstance(credit, (int, float)):
            continue
        if float(credit) > 0.0:
            out.append({"source": "cross_task", "status": "credit>0",
                        "strength": CROSS_TASK_STRENGTH,
                        "credit": float(credit)})
    return out


def knowledge_query(ws, claim) -> dict:
    """What does the substrate already know about this claim? Reads the
    three faces (register / facts index / cross-task store), each
    individually fail-open; the reported strength is the MAX over the
    contributing faces (ties: register > facts_index > cross_task —
    the caller-visible precedence), and every contributing row rides
    ``faces`` for audit. ``answer_strength`` narrows the strength to
    the ANSWER faces (facts_index / cross_task — an answer artifact
    exists); the register face reports lifecycle, not knowledge.
    Nothing known -> solved False, strength None (the honest cold
    start, never a fabricated answer)."""
    cid = str(claim or "")
    out = {"claim": cid, "solved": False, "strength": None,
           "answer_strength": None, "status": None, "source": None,
           "faces": []}
    if not cid:
        return out
    ws = Path(ws)
    for face_fn in (_register_face, _facts_face, _cross_task_face):
        try:
            out["faces"].extend(face_fn(ws, cid))
        except Exception as exc:  # noqa: BLE001 — one face never the query
            warn("l1_planner.knowledge_query",
                 f"{face_fn.__name__}: {type(exc).__name__}: {exc}")
    if out["faces"]:
        best = max(out["faces"], key=lambda f: f.get("strength") or 0.0)
        out.update({"solved": True,
                    "strength": float(best.get("strength") or 0.0),
                    "status": best.get("status"),
                    "source": best.get("source")})
        answers = [f for f in out["faces"]
                   if f.get("source") in _ANSWER_SOURCES]
        if answers:
            out["answer_strength"] = float(max(
                f.get("strength") or 0.0 for f in answers))
    return out


# ---------------------------------------------------------------------------
# candidates + the planning algorithm (T4)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    """One L1 candidate action. ``cost`` comes from the caller's cost
    model (the dispatch tier cost, REUSE_COST, PARK_COST); ``prior`` is
    the proposal channel's weight (> 0) — reserved for the P_LLM ⊗ Q
    composition at the wired call site; ``value_hint`` is a KNOWN value
    (the knowledge strength), never sampled; ``detail`` rides the
    receipt for audit."""
    action_kind: str
    claim: str
    cost: float
    prior: float = 1.0
    value_hint: float | None = None
    detail: dict | None = None

    @property
    def key(self) -> str:
        return f"{self.action_kind}/{self.claim}"


def candidate(action_kind, claim, cost, *, prior: float = 1.0,
              value_hint: float | None = None,
              detail: dict | None = None) -> Candidate:
    """Validated candidate constructor (the boundary wall): the action
    kind is the closed vocabulary, the claim is a non-empty token, cost
    is finite and > 0 except for park (the do-nothing baseline: cost
    exactly 0), and the hint is finite when given."""
    kind = str(action_kind or "")
    if kind not in ACTION_KINDS:
        raise ValueError(
            f"action_kind must be one of {ACTION_KINDS}: {action_kind!r}")
    cid = str(claim or "").strip()
    if not cid:
        raise ValueError("claim must be a non-empty token")
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) \
            or float(cost) != float(cost) \
            or float(cost) in (float("inf"), float("-inf")):
        raise ValueError(f"cost must be a finite number: {cost!r}")
    cost = float(cost)
    if kind == "park":
        if cost != PARK_COST:
            raise ValueError(
                f"park is the do-nothing baseline: cost must be "
                f"{PARK_COST}, got {cost!r}")
    elif cost <= 0.0:
        raise ValueError(
            f"a non-park candidate needs a positive cost (value/cost "
            f"is the criterion; cheapness alone must never win): "
            f"{kind!r} cost={cost!r}")
    if isinstance(prior, bool) or not isinstance(prior, (int, float)) \
            or not float(prior) > 0.0 or float(prior) != float(prior):
        raise ValueError(f"prior must be a positive finite number: "
                         f"{prior!r}")
    if value_hint is not None:
        if isinstance(value_hint, bool) \
                or not isinstance(value_hint, (int, float)) \
                or float(value_hint) != float(value_hint):
            raise ValueError(
                f"value_hint must be finite when given: {value_hint!r}")
        if kind == "park":
            raise ValueError("park has no value to hint (it is 0.0)")
        value_hint = float(value_hint)
    return Candidate(kind, cid, cost, float(prior), value_hint, detail)


def plan(ws, candidates, *, store=None, rng: random.Random | None = None,
         state_signature=None, gamma=None, fold_view=None) -> dict:
    """The planning algorithm: for every candidate, one DTS draw from
    its (state, action_kind) cell (or the known value_hint), then the
    argmax of value / cost. Pure in (fold, candidates, rng): the same
    inputs replay the same receipt. Candidates are keyed
    ``"<action_kind>/<claim>"``; duplicates are a caller bug (fail
    fast). No candidate carries a positive ratio -> park (the
    do-nothing baseline) or the first candidate — never a fabricated
    winner. ``fold_view`` lets a caller reuse ONE fold across many
    plans (the advisory face's per-claim loop); None folds the store."""
    cands = list(candidates or ())
    if not cands:
        raise ValueError("candidates is empty")
    if not all(isinstance(c, Candidate) for c in cands):
        raise ValueError("every candidate must be an l1_planner.Candidate")
    keys = [c.key for c in cands]
    if len(set(keys)) != len(keys):
        raise ValueError(f"duplicate candidate keys: {keys}")
    if fold_view is None:
        fold_view = lv.fold(
            store if store is not None else lv.default_store(ws),
            gamma=gamma)
    sig = state_signature or lv.state_signature_of(ws)
    rng = rng if rng is not None else random.Random(0)
    base = rng.getrandbits(64)
    doc: dict[str, dict] = {}
    for c in sorted(cands, key=lambda c: c.key):
        child = random.Random(f"l1plan/{base}/{c.key}")
        alpha, beta = lv.cell_posterior(fold_view, sig, c.action_kind)
        theta = child.betavariate(alpha, beta)
        if c.action_kind == "park":
            value = 0.0            # the do-nothing baseline, by ruling
        elif c.value_hint is not None:
            value = c.value_hint   # known (knowledge) — never sampled
        else:
            value = theta * VALUE_SCALE
        ratio = 0.0 if value <= 0.0 else value / c.cost
        doc[c.key] = {
            "action_kind": c.action_kind,
            "claim": c.claim,
            "cost": round(c.cost, 6),
            "prior": round(c.prior, 6),
            "theta": round(theta, 6),
            "value": round(value, 6),
            "ratio": round(ratio, 9),
            "value_hint": c.value_hint,
            "alpha": round(alpha, 6),
            "beta": round(beta, 6),
            **({"detail": c.detail} if c.detail else {}),
        }
    order = [c.key for c in cands]
    best = None
    for key in order:
        if doc[key]["ratio"] > 0.0 and (best is None
                                        or doc[key]["ratio"]
                                        > doc[best]["ratio"]):
            best = key
    if best is None:
        park = next((c.key for c in cands if c.action_kind == "park"),
                    order[0])
        best = park
    return {
        "schema": SCHEMA,
        "state_signature": sig,
        "chosen": dict(doc[best], key=best),
        "candidates": {k: doc[k] for k in order},
    }


def plan_for_claim(ws, claim, *, dispatch_cost, store=None,
                   rng: random.Random | None = None, knowledge=None,
                   state_signature=None, gamma=None,
                   fold_view=None) -> dict:
    """One claim's decision set: dispatch (the caller's cost model) and
    park are always available; ``reuse`` (REUSE_COST — a read, not a
    run) joins with the knowledge query's graded strength as its value
    when the substrate says the claim is solved. The value/cost
    comparison decides — re-attempt wins exactly when its ratio beats
    the replay's."""
    kc = knowledge if knowledge is not None else knowledge_query(ws, claim)
    cands = [candidate("dispatch", claim, cost=dispatch_cost),
             candidate("park", claim, cost=PARK_COST)]
    if kc.get("solved"):
        cands.append(candidate("reuse", claim, cost=REUSE_COST,
                               value_hint=kc.get("strength"),
                               detail={"knowledge": kc}))
    receipt = plan(ws, cands, store=store, rng=rng,
                   state_signature=state_signature, gamma=gamma,
                   fold_view=fold_view)
    receipt["knowledge"] = kc
    return receipt


# ---------------------------------------------------------------------------
# the advisory consumption face (T4: the rank path's additive signal)
# ---------------------------------------------------------------------------

def advisory_factors(ws, claim_costs, *, store=None,
                     rng: random.Random | None = None) -> dict:
    """{claim: factor ∈ (0, 1]} for the rank path — the planner's
    dispatch SHARE per claim (dispatch ratio / Σ candidate ratios over
    plan_for_claim's set). An unsolved claim with no learned evidence is
    exactly 1.0 (no drag, byte-identical); a claim with a verified
    ANSWER on record (the facts-index / cross-task faces — an answer
    artifact, not the register's lifecycle status: the rank frontier
    already enforces closure) is dragged by its replay dominance. {}
    while the value store is empty (the rank path's byte-identity
    contract — nothing to advise yet). Deterministic per (store,
    round): rng=None rides l1_value.seed_state."""
    pairs = [(str(c), float(k)) for c, k in (claim_costs or ())]
    if not pairs:
        return {}
    l1_store = store if store is not None else lv.default_store(ws)
    if not lv.has_observations(l1_store):
        return {}
    if rng is None:
        rng = lv.seed_state(ws)[0]
    base = rng.getrandbits(64)
    sig = lv.state_signature_of(ws)
    fold_view = lv.fold(l1_store)      # ONE fold for the whole claim loop
    out: dict[str, float] = {}
    for claim, cost in pairs:
        try:
            kc = knowledge_query(ws, claim)
            if kc.get("answer_strength") is None:
                kc = dict(kc, solved=False)
            else:
                kc = dict(kc, solved=True,
                          strength=kc["answer_strength"])
            receipt = plan_for_claim(
                ws, claim, dispatch_cost=cost, store=l1_store,
                rng=random.Random(f"l1adv/{base}/{claim}"),
                knowledge=kc, state_signature=sig, fold_view=fold_view)
            ratios = [c.get("ratio") or 0.0
                      for c in receipt["candidates"].values()]
            total = sum(r for r in ratios if r > 0.0)
            r_d = next((c["ratio"] for c in receipt["candidates"].values()
                        if c["action_kind"] == "dispatch"), 0.0)
            share = (r_d / total) if total > 0.0 and r_d > 0.0 else 0.0
            out[claim] = round(min(max(share, 0.0), 1.0), 9)
        except Exception as exc:  # noqa: BLE001 — the rank never breaks
            warn("l1_planner.advisory_factors",
                 f"{claim}: {type(exc).__name__}: {exc}")
    return out
