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
