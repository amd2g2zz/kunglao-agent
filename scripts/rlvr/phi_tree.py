# -*- coding: utf-8 -*-
"""rlvr/phi_tree.py — the Φ-tree economy (issue #796).

RE is an uncertainty-elimination business; reward must price
INFORMATION GAIN toward closure, not actions or assertions. The live Φ
(``W_FACTS·graded_fraction + W_ORACLE·green``) was convicted by both
the five-party and six-party reviews: ``graded_fact_fraction`` is
dilution-dominated (every DISCOVERY grows the denominator before
certification grows the numerator — discovery steps banked r_t < 0;
the ctf-1 audit found 8 distinct Φ values over 783 transitions,
monotone declining). Φ-v2 pins decisive mass on the closure hypothesis
tree (#528 layer, schema v2):

    Φ_tree(s) = min(1, Σ over decisively-resolved nodes
                      posterior × trunk-depth weight × chain_mult
                   ) / PHI_NORM
    r_t       = Φ(s') − Φ(s)          # potential-based (Ng 1999)

TWO ACCOUNTING CURRENCIES, ONE VALUE — no double count:

  - the POTENTIAL currency: mass arrives at decisive resolution and
    leaves at overturn; every movement banks exactly once as ΔΦ inside
    the transition ledger's ``r_incr`` (the shaping face);
  - the CREDIT currency: the settlement rows below (resolution /
    elimination / clawback / calibration) give the SAME value an
    ADDRESS — the escrowed advance against future truth, attributed to
    the proposing step. The clawback's ``clawed_credit`` documents the
    recovery of that address; the mass drop already banked the −ΔΦ, so
    the clawback row's only ADDITIONAL negative leg is the documented
    churn ``penalty`` — never both.

Panel pre-conditions honored (the #796 merge verdict):
  1. the chain multiplier lives INSIDE Φ (a Φ-term, never an additive
     settlement bonus — potential-order preservation is structural);
  2. Φ-regime versioning: every row stamps ``PHI_REGIME`` so the
     append-only ledger survives a Φ swap uncorrupted;
  3. uniform birth masses: an unresolved node carries ZERO Φ mass —
     adding nodes can never move Φ (the dilution ban); mechanical
     witnesses are the only differentiation channel at birth;
  4. signed clawbacks live OUTSIDE the non-negative credit stream (the
     ``phi-clawback/1`` negative face, sealed; the strategy-store
     mirror rides ``censored: true`` with negative ``phi_delta`` so
     warm pools never inherit the churn).

Adversarial patches honored:
  - straw-man farming: decisive resolution requires a MACHINE witness
    or an independent referee's confirmation; worker-authored
    refutations settle NEUTRAL and never move mass;
  - clawback timing evasion: credit is ESCROWED until the claim's
    terminal reconcile releases it — warm pools only ever see released
    (calibrated) rows;
  - cross-workspace laundering: the negative/amended face MIRRORS into
    the shared strategy store (censored), never stays local.

Relationship to the sibling faces (no overlap):
  - #760 pricing: prices whether an act SHOULD run (expected gain per
    probe); this module prices what the FINISHED act bought (ΔΦ);
  - #799 learning seal: every row is signed at write (``sign_row``)
    and every read goes through ``trusted_rows`` — no new key face;
  - #797 key freeze: the seal key stays the family-granularity frozen
    key; untouched.

Scope fence: ranker (#792), settlement_scorer/settlement_wire (#802),
supply (#794), claims_store/scalar are CALL-ONLY from here. Policy
constants are DOCUMENTED (ADR-001 governance), never fitted.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from hypothesis_store import HypothesisStore, InvalidTransition
from kunglao_log import warn

from rlvr import consolidated_ledger as _cl
from rlvr import learning_seal as _seal

#: the Φ formula version — rides every row this economy emits and every
#: transition row (incremental_reward) stamps it additively (pre-condition 2)
PHI_REGIME = "phi-tree/1"

RESOLUTION_SCHEMA = "hypothesis-resolution/1"
ELIMINATION_SCHEMA = "hypothesis-elimination/1"
CLAWBACK_SCHEMA = "phi-clawback/1"
CALIBRATION_SCHEMA = "phi-calibration/1"

# ---- documented policy constants (NOT fitted; ADR-001 governance) ----

#: posterior mass by decisive-evidence kind (uniform birth mass is ZERO
#: — an unresolved node never carries Φ mass; the machine witness is
#: the stronger differentiator, an independent referee confirm a
#: documented discount)
MACHINE_MASS = 1.0
REFEREE_MASS = 0.8

#: trunk-depth weight: a node on the critical path weighs its DEPTH
#: toward closure (deeper = closer to the payoff); off-trunk resolved
#: nodes ride the discount (progress off the trunk is real but small)
TRUNK_BASE = 0.3
TRUNK_DEPTH_STEP = 0.1
MAX_DEPTH_COUNTED = 3
OFF_TRUNK_WEIGHT = 0.1

#: the chain multiplier — INSIDE Φ (pre-condition 1): adjacent
#: decisively-resolved trunk nodes make the deeper node superlinear
CHAIN_MULT = 1.5

#: Φ saturation cap (Φ_tree ∈ [0, 1] after division)
PHI_NORM = 2.0

#: the rule threshold: a resolution whose ΔΦ is below this records
#: NEUTRAL (machine-recorded, zero credit) — the reward-rules v4 pin
DECISIVE_DPHI_MIN = 0.05

#: elimination credit (scenario 2: a well-formed failed attempt
#: eliminates a live candidate; saturating per same-hypothesis repeat)
ELIMINATION_CREDIT = 0.05
ELIMINATION_DECAY = 0.5
ELIMINATION_MAX_REPEATS = 4

#: the churn penalty — the clawback's additional negative leg on top of
#: the recovered credit (identity churn must be strictly unprofitable)
CHURN_PENALTY = 0.3

#: the closed decisive-evidence vocabulary. ``worker-assertion`` is
#: KNOWN but never decisive (the straw-man patch); an unknown kind is
#: a caller bug — refused, never guessed.
KIND_MACHINE = "machine-witness"
KIND_REFEREE = "referee-confirm"
KIND_ASSERTION = "worker-assertion"
DECISIVE_KINDS = (KIND_MACHINE, KIND_REFEREE)
KNOWN_KINDS = (KIND_MACHINE, KIND_REFEREE, KIND_ASSERTION)

_POSTERIOR_BY_KIND = {KIND_MACHINE: MACHINE_MASS,
                      KIND_REFEREE: REFEREE_MASS}

#: the workspace-relative root of the closure hypothesis tree (#528)
TREE_REL = "hypotheses"


def _store(ws) -> HypothesisStore:
    return HypothesisStore(Path(ws) / TREE_REL)


def _now_row(schema: str, **base) -> dict:
    from _common import utc_now_z  # noqa: PLC0415 — the canonical leaf
    return {"schema": schema, "ts": utc_now_z(),
            "id": uuid.uuid4().hex[:12], **base}


def _emit(ws, family: str, row: dict) -> dict | None:
    """Seal + append one economy row (the #799 gate on BOTH faces: the
    write signs, the read filters). Fail-open loud: a refused append
    returns None with the core's warn already emitted."""
    row = _seal.sign_row(row)
    if not _cl.append(ws, family, row):
        return None
    return row


# --------------------------------------------------------------- the reads

def _rows(ws, schema_prefix: str) -> list[dict]:
    return _seal.trusted_rows(
        _cl.read(ws, "experience", schema_prefix=schema_prefix),
        op=f"rlvr.phi_tree.{schema_prefix}")


def read_resolutions(ws) -> list[dict]:
    """All sealed hypothesis-resolution/1 rows, oldest first."""
    return _rows(ws, "hypothesis-resolution")


def read_eliminations(ws) -> list[dict]:
    """All sealed hypothesis-elimination/1 rows, oldest first."""
    return _rows(ws, "hypothesis-elimination")


def read_clawbacks(ws) -> list[dict]:
    """All sealed phi-clawback/1 rows (the signed negative face)."""
    return _rows(ws, "phi-clawback")


def read_calibrations(ws) -> list[dict]:
    """All sealed phi-calibration/1 rows (proxy-vs-truth triples)."""
    return _rows(ws, "phi-calibration")


def _released_ids(ws) -> set[str]:
    out: set[str] = set()
    for cal in read_calibrations(ws):
        for rid in (cal.get("released") or []):
            out.add(str(rid))
    return out


def _clawed_ids(ws) -> set[str]:
    return {str(r.get("target") or "") for r in read_clawbacks(ws)}


def _outstanding_resolutions(ws, *, claim: str = "",
                             hyp_id: str = "") -> list[dict]:
    """Credited (SETTLED_CREDIT) resolution rows whose escrow is still
    open: not released by a calibration pass, not clawed back."""
    released = _released_ids(ws)
    clawed = _clawed_ids(ws)
    out = []
    for r in read_resolutions(ws):
        if r.get("band") != "SETTLED_CREDIT":
            continue
        rid = str(r.get("id") or "")
        if rid in released or rid in clawed:
            continue
        if claim and str(r.get("claim_ref") or "") != claim:
            continue
        if hyp_id and str(r.get("hypothesis") or "") != hyp_id:
            continue
        out.append(r)
    return out


def escrow_open(ws, hyp_id: str) -> bool:
    """True iff the hypothesis carries an escrowed (settled, unreleased,
    unclawed) resolution credit — the clawback-timing face."""
    return bool(_outstanding_resolutions(ws, hyp_id=str(hyp_id)))


# ------------------------------------------------------------- the Φ core

def decisive(evidence_kind: str, evidence_ref: str) -> bool:
    """The decisive-evidence gate: a machine witness or an independent
    referee confirmation with a non-empty ref. Worker-authored
    assertions NEVER settle decisive-resolution (straw-man patch)."""
    return (str(evidence_kind) in DECISIVE_KINDS
            and bool(str(evidence_ref or "").strip()))


def _depth_of(hyp_id: str, by_id: dict) -> int:
    """Trunk depth: parent-chain distance to a root (cycle-guarded; a
    broken chain counts what is walkable — never hangs, never lies)."""
    depth = 0
    seen = {hyp_id}
    cur = str(by_id.get(hyp_id).parent_id or "") if hyp_id in by_id else ""
    while cur and cur in by_id and cur not in seen:
        depth += 1
        seen.add(cur)
        cur = str(by_id[cur].parent_id or "")
    return depth


def _mass_of(h, by_id: dict) -> float:
    """One node's Φ mass: zero unless decisively resolved AND confirmed;
    posterior × depth weight, chain-multiplied only on the trunk with a
    trunk-resolved parent (pre-condition 1 + 3)."""
    if h.status != "confirmed":
        return 0.0
    kind = str(h.resolved_evidence or "")
    if kind not in DECISIVE_KINDS:
        return 0.0
    posterior = float(h.posterior or 0.0) or _POSTERIOR_BY_KIND.get(kind, 0.0)
    if posterior <= 0.0:
        return 0.0
    parent = str(h.parent_id or "")
    parent_h = by_id.get(parent) if parent else None
    parent_pinned = (
        parent_h is not None and parent_h.critical_path
        and parent_h.status == "confirmed"
        and str(parent_h.resolved_evidence or "") in DECISIVE_KINDS)
    chain = bool(h.critical_path) and parent_pinned
    if h.critical_path:
        weight = TRUNK_BASE + TRUNK_DEPTH_STEP * min(
            _depth_of(h.id, by_id), MAX_DEPTH_COUNTED)
    else:
        weight = OFF_TRUNK_WEIGHT
    return posterior * weight * (CHAIN_MULT if chain else 1.0)


def tree_phi(ws) -> float | None:
    """Φ_tree ∈ [0, 1] over the closure hypothesis tree; None when the
    workspace has no tree at all (honest absence — the caller drops the
    dim, the legacy renormalization rides)."""
    nodes = _store(ws).list_all()
    if not nodes:
        return None
    by_id = {h.id: h for h in nodes}
    total = sum(_mass_of(h, by_id) for h in nodes)
    return min(1.0, total / PHI_NORM)


# ------------------------------------------------- the settlement faces

def settle_resolution(ws, hyp_id: str, *, evidence_kind: str,
                      evidence_ref: str, step_ref: str,
                      claim_ref: str = "") -> dict | None:
    """The ``hypothesis/decisive-resolution`` settle face.

    Confirms an open hypothesis (the #711 confirm transition rides the
    store), persists the v2 resolution fields, computes the machine
    ΔΦ from the tree state diff, and banks the escrowed credit WITH
    its attribution. Contract:
      - a known-but-undecisive kind (worker assertion) settles NEUTRAL
        (machine-recorded, zero credit, no mass — the row is history,
        not reward);
      - an UNKNOWN evidence kind is a caller bug — refused (None);
      - an empty step_ref is an INVALID credited row — refused before
        anything banks (the valuation+attribution pairing pin);
      - ΔΦ below DECISIVE_DPHI_MIN records with zero credit (the
        reward-rules v4 threshold pin).
    """
    kind = str(evidence_kind or "")
    if kind not in KNOWN_KINDS:
        warn("rlvr.phi_tree.settle_resolution",
             f"refused resolution of {hyp_id!r}: unknown evidence kind "
             f"{kind!r} (closed vocabulary: {', '.join(KNOWN_KINDS)})")
        return None
    store = _store(ws)
    try:
        h = store.get(hyp_id)
    except KeyError:
        warn("rlvr.phi_tree.settle_resolution",
             f"refused resolution: no such hypothesis {hyp_id!r}")
        return None
    if h.status in ("refuted", "superseded"):
        warn("rlvr.phi_tree.settle_resolution",
             f"refused resolution of {hyp_id!r}: terminal "
             f"({h.status}) nodes never resolve")
        return None
    if h.status == "open":
        try:
            store.transition(hyp_id, "confirmed",
                             confirming_fact_id=str(evidence_ref))
        except InvalidTransition as exc:
            warn("rlvr.phi_tree.settle_resolution",
                 f"refused resolution of {hyp_id!r}: {exc}")
            return None
    if not decisive(kind, evidence_ref):
        # the straw-man patch: recorded history, zero reward, no escrow
        row = _now_row(RESOLUTION_SCHEMA, hypothesis=str(hyp_id),
                       claim_ref=str(claim_ref or ""), step_ref="",
                       evidence_kind=kind,
                       evidence_ref=str(evidence_ref or ""),
                       phi_regime=PHI_REGIME, phi_before=None,
                       phi_after=None, dphi=0.0, credit=0.0,
                       band="NEUTRAL")
        return _emit(ws, "experience", row)
    if not str(step_ref or "").strip():
        warn("rlvr.phi_tree.settle_resolution",
             f"refused credited resolution of {hyp_id!r}: empty step_ref "
             f"(a credited row carries BOTH the ΔΦ valuation AND the "
             f"proposing-step attribution — no attribution, no settle)")
        return None
    phi_before = tree_phi(ws) or 0.0
    store.record_resolution(
        hyp_id, evidence_kind=kind, evidence_ref=str(evidence_ref),
        step_ref=str(step_ref), posterior=_POSTERIOR_BY_KIND[kind])
    phi_after = tree_phi(ws) or 0.0
    dphi = round(phi_after - phi_before, 6)
    settled = dphi >= DECISIVE_DPHI_MIN
    credit = round(dphi, 6) if settled else 0.0
    row = _now_row(
        RESOLUTION_SCHEMA, hypothesis=str(hyp_id),
        claim_ref=str(claim_ref or ""), step_ref=str(step_ref),
        evidence_kind=kind, evidence_ref=str(evidence_ref),
        phi_regime=PHI_REGIME, phi_before=round(phi_before, 6),
        phi_after=round(phi_after, 6), dphi=dphi, credit=credit,
        band="SETTLED_CREDIT" if settled else "NEUTRAL",
        **({"escrow": {"amount": credit, "released": False}}
           if settled else {}))
    return _emit(ws, "experience", row)


def elimination_credit(ws, hyp_id: str, *, candidate: str,
                       evidence_kind: str, evidence_ref: str,
                       step_ref: str, claim_ref: str = "") -> dict | None:
    """Scenario-2 elimination: a well-formed failed attempt eliminates a
    live candidate for small SATURATING credit
    (ELIMINATION_CREDIT·DECAY^repeat). The same decisive gate applies —
    planting candidates to refute them farms nothing (the straw-man
    patch), a terminal node has no live candidate, and the saturated
    repeat is refused (ONE warn). Elimination is a settlement leg, not
    Φ mass: only resolution/refutation moves node mass."""
    kind = str(evidence_kind or "")
    if not decisive(kind, evidence_ref):
        warn("rlvr.phi_tree.elimination_credit",
             f"refused elimination on {hyp_id!r}: candidate elimination "
             f"requires a machine witness or referee confirmation "
             f"(worker-authored failures farm nothing)")
        return None
    if not str(step_ref or "").strip():
        warn("rlvr.phi_tree.elimination_credit",
             f"refused elimination on {hyp_id!r}: empty step_ref "
             f"(attribution wall)")
        return None
    try:
        h = _store(ws).get(hyp_id)
    except KeyError:
        warn("rlvr.phi_tree.elimination_credit",
             f"refused elimination: no such hypothesis {hyp_id!r}")
        return None
    if h.status != "open":
        warn("rlvr.phi_tree.elimination_credit",
             f"refused elimination on {hyp_id!r}: {h.status} nodes have "
             f"no live candidate field")
        return None
    repeat = sum(1 for r in read_eliminations(ws)
                 if str(r.get("hypothesis") or "") == str(hyp_id))
    if repeat >= ELIMINATION_MAX_REPEATS:
        warn("rlvr.phi_tree.elimination_credit",
             f"elimination on {hyp_id!r} saturated after {repeat} "
             f"same-shape repeats — no further credit")
        return None
    credit = round(ELIMINATION_CREDIT
                   * (ELIMINATION_DECAY ** repeat), 6)
    row = _now_row(ELIMINATION_SCHEMA, hypothesis=str(hyp_id),
                   candidate=str(candidate or ""),
                   evidence_kind=kind, evidence_ref=str(evidence_ref),
                   step_ref=str(step_ref), claim_ref=str(claim_ref or ""),
                   credit=credit, repeat_index=repeat,
                   phi_regime=PHI_REGIME)
    return _emit(ws, "experience", row)


def clawback(ws, hyp_id: str, *, reason: str = "",
             superseded_by: str = "") -> dict | None:
    """Churn clawback: overturning a credited node revokes its escrowed
    credit against the PROPOSING step (the attribution address the
    settle stored) and charges the documented churn penalty.

    Contract:
      - only an escrowed attribution ref is executable: an outstanding
        credited resolution row is the precondition — a node that never
        settled (or already released/clawed) refuses (None, ONE warn);
        an outstanding row WITHOUT a step_ref could not have settled
        (the write-time wall) — the same refusal fires defensively;
      - ``clawed_credit`` documents the recovery; the mass drop already
        banked the −ΔΦ, so the row's additional negative leg is the
        ``penalty`` ONLY (one value, one count — the module docstring's
        two-currency note);
      - the row lands on the SIGNED negative face (phi-clawback/1,
        sealed) — never folded into any non-negative credit stream —
        and MIRRORS into the shared strategy store as a censored row
        with negative phi_delta (the laundering patch);
      - one clawback per credited resolution row (the target is
        consumed; a re-claw refuses).
    """
    try:
        h = _store(ws).get(hyp_id)
    except KeyError:
        warn("rlvr.phi_tree.clawback",
             f"refused clawback: no such hypothesis {hyp_id!r}")
        return None
    if h.status not in ("refuted", "superseded"):
        warn("rlvr.phi_tree.clawback",
             f"refused clawback of {hyp_id!r}: the node is "
             f"{h.status} — clawback executes on OVERTURNED nodes only")
        return None
    outstanding = _outstanding_resolutions(ws, hyp_id=str(hyp_id))
    if not outstanding:
        warn("rlvr.phi_tree.clawback",
             f"refused clawback of {hyp_id!r}: no outstanding escrowed "
             f"credit (an uncredited or already-settled node claws "
             f"nothing back)")
        return None
    row = None
    for res in outstanding:
        step_ref = str(res.get("step_ref") or "")
        if not step_ref:
            # cannot happen past the write-time wall — the assert face
            warn("rlvr.phi_tree.clawback",
                 f"refused clawback of {hyp_id!r}: the credited row "
                 f"{res.get('id')!r} carries no attribution ref (no "
                 f"attribution ⇒ the credit could not have settled)")
            continue
        clawed = round(float(res.get("credit") or 0.0), 6)
        signed = _emit(ws, "experience", _now_row(
            CLAWBACK_SCHEMA, hypothesis=str(hyp_id),
            target=str(res.get("id") or ""), step_ref=step_ref,
            claim_ref=str(res.get("claim_ref") or ""),
            clawed_credit=clawed, penalty=CHURN_PENALTY,
            amount=round(clawed + CHURN_PENALTY, 6),
            direction="negative", reason=str(reason or ""),
            **({"superseded_by": str(superseded_by)}
               if superseded_by else {}),
            phi_regime=PHI_REGIME))
        if signed is None:
            return None
        _mirror(ws, signed)
        row = signed
    return row


def _mirror(ws, clawback_row: dict) -> None:
    """The cross-workspace laundering patch: the negative/amended face
    MIRRORS into the shared strategy store as a CENSORED row with zero
    credit and negative phi_delta — warm pools never inherit the churn,
    and the audit trail does not stay local. Fail-open loud."""
    try:
        from rlvr import strategy_store  # noqa: PLC0415 — lazy (cycle)
        result = strategy_store.append_store_row(
            ws=ws, method_family="hypothesis", status="phi-clawback",
            credit=0.0, censored=True,
            phi_delta=-float(clawback_row.get("penalty") or 0.0),
            dispatch_id=str(clawback_row.get("step_ref") or ""),
            claim=(str(clawback_row.get("claim_ref") or "") or None))
        if not result.get("appended"):
            warn("rlvr.phi_tree.mirror",
                 f"clawback mirror not appended ({result.get('reason')}) "
                 f"— the local negative face still stands")
    except Exception as exc:  # noqa: BLE001 — telemetry, never the producer
        warn("rlvr.phi_tree.mirror",
             f"{type(exc).__name__}: {exc} — clawback mirror failed "
             f"(the local negative face still stands)")


def reconcile_claim(ws, claim: str, *, oracle_outcome: str = "") -> dict | None:
    """The proxy-vs-truth reconciliation pass (fired on the claim's
    terminal close): records the ``(ΔΦ valuation, attribution, oracle
    outcome)`` calibration triples for every attributed resolution row
    of the claim and RELEASES the escrows — credit becomes warm-pool
    eligible only after release (the clawback-timing-evasion patch).
    Nothing to reconcile → a silent no-op (None)."""
    outstanding = _outstanding_resolutions(ws, claim=str(claim or ""))
    if not outstanding:
        return None
    row = _now_row(
        CALIBRATION_SCHEMA, claim=str(claim or ""),
        oracle_outcome=str(oracle_outcome or ""),
        reconciled=[{"resolution": str(r.get("id") or ""),
                     "dphi": r.get("dphi"), "credit": r.get("credit"),
                     "step_ref": r.get("step_ref"),
                     "hypothesis": r.get("hypothesis")}
                    for r in outstanding],
        released=[str(r.get("id") or "") for r in outstanding],
        phi_regime=PHI_REGIME)
    return _emit(ws, "experience", row)
