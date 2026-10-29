# -*- coding: utf-8 -*-
"""rlvr/reward_signal.py — the A1 learning signal (issue 824, P1).

AXIOM A1 (#806 axis, owner-approved): the learning signal is

    R = W_COMPLETION * task_completion
      + W_MILESTONE * milestone_progress
      - cost_term

Per-fact credit RETIRES from the learning signal — it survives only as
the audit face (the existing step-credit / scalar-settlement faces,
called read-only; `audit_fact_mass` reports an episode's fact-side mass
labeled `audit_only`). The structural wall is the signature itself:
`compute_reward` takes completion / milestones / cost — no fact-credit
parameter exists, and the PE pathology (many verified facts, zero task
completion) scores zero (pinned by tests/test_model_contract_824.py).

Milestones are the task decomposition's VERIFIED sub-goals: a
milestone counts toward progress only when its own evidence reference
resolves to a PASSED record through the unmodified trust spine
(`verifier_integrity.resolve_verification`) — the trust spine gates
milestone verification exactly as it gates completion (A4: trust =
the reward channel).

THE SETTLEMENT HOOK — `on_settlement(ws, claim)`: reads the claim's
settled receipt through the EXISTING consolidated settlement read face
(`consolidated_ledger.read`, the settlement-wire rows — settlement
semantics are only ever CALLED, never modified), computes the episode
reward, stamps it into the pool episode, and runs the pool's UPDATE
policy over the retrieval window (self-citation: the settled episode
gains its own citation mass).

Zero telemetry points (Standard 11): refusals raise to the caller.
All coefficients are documented policy constants (the state.py
precedent); nothing is fitted.
"""
from __future__ import annotations

from pathlib import Path

from rlvr import episode_pool as pool
from rlvr import episode_schema as es

#: policy constants (documented, not fitted)
W_COMPLETION = 1.0
W_MILESTONE = 1.0
COST_TOKENS_NORM = 10_000.0   # the settlement cost_t convention (tokens/1e4)
COST_SECONDS_NORM = 3_600.0   # ... and seconds/3600
PATHOLOGY_EPSILON = 1e-9


class SettlementMissing(Exception):
    """`on_settlement` ran with no settled receipt for the claim — the
    hook fires on settlement, never on hope."""


def cost_term(tokens: float, seconds: float) -> float:
    """The normalized cost in [0, 1]: the settlement bookkeeping's own
    ratios (tokens/COST_TOKENS_NORM + seconds/COST_SECONDS_NORM),
    saturated at 1.0 so cost can never outweigh a full completion."""
    t = max(0.0, float(tokens)) / COST_TOKENS_NORM
    s = max(0.0, float(seconds)) / COST_SECONDS_NORM
    return min(1.0, t + s)


def compute_reward(completion: float, milestone_progress: float,
                   cost_tokens: float, cost_seconds: float) -> float:
    """THE learning signal (A1). Completion and milestone progress are
    trust-derived (see task_completion / milestone_progress); cost is
    the normalized episode cost. NO fact-credit parameter exists —
    per-fact credit is structurally out of the learning signal."""
    return (W_COMPLETION * float(completion)
            + W_MILESTONE * float(milestone_progress)
            - cost_term(cost_tokens, cost_seconds))


def _resolves(ws: Path, claim: str, ref: str) -> bool:
    """The trust spine, CALLED not modified. Fail-closed."""
    try:
        from verifier_integrity import resolve_verification  # noqa: PLC0415
        passed, _w, _d = resolve_verification(Path(ws), claim, ref or "")
        return passed
    except Exception:  # noqa: BLE001 — resolver fault = not verified
        return False


def task_completion(ws, claim: str, outcome: dict) -> float:
    """1.0 iff the episode outcome is a completed task whose evidence
    resolves to a PASSED record; 0.0 otherwise (fail-closed)."""
    if outcome.get("status") != "completed":
        return 0.0
    return 1.0 if _resolves(ws, claim,
                            outcome.get("evidence_ref") or "") else 0.0


def milestone_progress(ws, claim: str, milestones: list) -> float:
    """Verified sub-goal fraction: every milestone claiming `verified`
    must resolve its own evidence reference through the trust spine —
    an unverified milestone contributes nothing."""
    if not milestones:
        return 0.0
    done = 0
    for m in milestones:
        if not m.get("verified"):
            continue
        if _resolves(ws, claim, m.get("evidence_ref") or ""):
            done += 1
    return done / len(milestones)


def episode_reward(ws, doc: dict) -> dict:
    """The stamped reward block for one episode document (completion and
    milestones trust-derived; cost from the episode's own cost block)."""
    claim = str(doc.get("claim"))
    completion = task_completion(ws, claim, doc.get("outcome") or {})
    progress = milestone_progress(ws, claim, doc.get("milestones") or [])
    cost = doc.get("cost") or {}
    term = cost_term(cost.get("tokens") or 0.0, cost.get("seconds") or 0.0)
    r = compute_reward(completion, progress,
                       cost.get("tokens") or 0.0, cost.get("seconds") or 0.0)
    return {"completion": completion, "milestone_progress": progress,
            "cost_term": term, "r": r}


# --- THE Φ STEP reward face (the P2 settlement card) ------------------------

#: Φ contraction weights — the kill outweighs the confirm (the repo's
#: refutation doctrine: a mismatch narrows the search more than a
#: survival). Calibrated on the distribution fixture
#: (tests/test_episode_settle.py, the Φ-gain distribution pin): with
#: kill=1.0 / confirm=0.5 a symmetric pair scores refutation exactly 2x
#: confirmation, and the sanity gate holds — active contraction > 0,
#: no-contraction == 0, refutation >= confirmation over ~10 synthetic
#: step pairs.
PHI_KILL_WEIGHT = 1.0
PHI_CONFIRM_WEIGHT = 0.5


def phi_contraction_gain(prev_hypotheses, conclusion) -> float:
    """Information gain of the conclusion over the prev hypothesis set,
    as the covering space's contraction: each hypothesis is one
    independently-decidable cell (the covering matrix's t=1 face over
    {h_i: alive, dead} — 2^n assignments), so the gain is the DECIDED
    mass share — a killed hypothesis at PHI_KILL_WEIGHT, an explicitly
    confirmed one at PHI_CONFIRM_WEIGHT (refutation narrows more).
    The decision scan is step_record's own clause-scoped contraction
    matrix, CALLED single-source (kill face) + mirrored (confirm face)
    so the verdict vocabulary never drifts. Deciding NOTHING gains
    exactly 0 — activity theater dies. Pure; inputs never mutated."""
    from rlvr import step_record  # noqa: PLC0415 — lazy (late facade line)
    hyps = [h for h in (prev_hypotheses or []) if isinstance(h, dict)]
    text = str(conclusion or "").strip()
    if not hyps or not text:
        return 0.0
    killed = set(step_record._killed_identities({"conclusion": text}, hyps))
    confirmed = _confirmed_identities(step_record, text, hyps) - killed
    total = len(hyps)
    gain = (PHI_KILL_WEIGHT * len(killed)
            + PHI_CONFIRM_WEIGHT * len(confirmed)) / total
    return max(0.0, min(1.0, gain))


def _confirmed_identities(step_record, conclusion: str,
                          hypotheses: list) -> set:
    """The confirm-side mirror of step_record's clause-scoped kill scan:
    same clause split, the confirm-marker vocabulary, the same reference
    test (id or salient claim terms). Passed the module explicitly so
    the single-source dependency stays visible at the call site."""
    confirmed: set = set()
    for clause in step_record._CLAUSE_SPLIT_RE.split(conclusion):
        if not step_record._CONFIRM_RE.search(clause):
            continue
        cterms = step_record._salient_terms(clause)
        for hyp in hypotheses:
            if not isinstance(hyp, dict):
                continue
            ident = step_record._hyp_identity(hyp)
            if not ident or ident in confirmed:
                continue
            if step_record._id_in_text(ident, clause) or \
                    step_record._salient_terms(
                        step_record._hyp_claim(hyp)) & cterms:
                confirmed.add(ident)
    return confirmed


def step_reward(prev_hypotheses, conclusion, evidence_valid,
                checkpoint_closed, cost_tokens, cost_seconds) -> float:
    """THE step reward (the P2 settlement card), the step/1 reward
    block's value:

        r = phi_contraction_gain(prev_hypotheses, conclusion)
            x evidence_valid x checkpoint_closed - cost_term(tokens, s)

    The zero gate: a step that decides no hypothesis (gain 0), rides no
    valid evidence, or closes no checkpoint scores EXACTLY 0.0 —
    activity theater dies (no gain, no cost bill: there is nothing to
    bill a gain against). Only a deciding step pays its cost, so a
    costly lesson can ride negative (honest accounting)."""
    gain = phi_contraction_gain(prev_hypotheses, conclusion)
    gate = (1.0 if evidence_valid else 0.0) \
        * (1.0 if checkpoint_closed else 0.0)
    gain *= gate
    if gain <= 0.0:
        return 0.0
    return gain - cost_term(cost_tokens, cost_seconds)


def settled_receipt(ws, claim: str) -> dict | None:
    """The claim's settled receipt through the EXISTING consolidated
    settlement read face (settlement-wire rows, `settled: true`). None
    when the claim has none — the hook reads, it never mints."""
    for row in cl_read(ws):
        if str(row.get("claim") or "") != str(claim):
            continue
        if row.get("schema") != "settlement-wire/1":
            continue
        if row.get("settled"):
            return row
    return None


def cl_read(ws) -> list[dict]:
    """The settlement family read, through the unmodified consolidated
    ledger (lazy: keeps this module import-light)."""
    from rlvr import consolidated_ledger  # noqa: PLC0415
    return consolidated_ledger.read(ws, "settlement")


def on_settlement(ws, claim: str) -> dict:
    """THE settlement hook: the reward switch fires the update policy.
    Refuses without a settled receipt (SettlementMissing). Stamps the
    episode's reward and settles its retrieval window (self-citation:
    the settled episode gains its own citation mass)."""
    ws = Path(ws)
    receipt = settled_receipt(ws, claim)
    if receipt is None:
        raise SettlementMissing(
            f"{claim}: no settled settlement-wire receipt — the hook "
            "fires on settlement only")
    path = pool.episode_path(ws, claim)
    if not path.is_file():
        raise SettlementMissing(
            f"{claim}: no pool episode at {pool.EPISODES_REL} — nothing "
            "to stamp")
    doc, body = es.read_episode_file(path)
    reward = episode_reward(ws, doc)
    doc["reward"] = reward
    es.write_episode_file(path, doc, body=body)
    cited = (str(claim),)
    stats = pool.update_on_settlement(ws, str(claim), cited=cited)
    return {"claim": str(claim), "reward": reward, "updated": stats}


def audit_fact_mass(doc: dict) -> dict:
    """The AUDIT face of the retired per-fact credit: reports an
    episode's fact-side mass (the verified-fact fragments and
    milestones the old signal would have paid) labeled audit_only —
    this mass can influence nothing (compute_reward has no fact
    parameter; the deep per-fact ledger faces stay in their own
    modules)."""
    return {
        "audit_only": True,
        "fragment_count": len(doc.get("reusable_fragments") or []),
        "milestone_count": len(doc.get("milestones") or []),
        "note": "per-fact credit retired from the learning signal "
                "(A1); reported here for audit only",
    }
