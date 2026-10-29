# -*- coding: utf-8 -*-
"""policy/assigner.py — the method assigner, the ASSIGN_STEP sampling
face (issue 881).

Two-stage method selection. Stage 1 is the LLM Planner: it RANKS the
candidate method families (contextual judgment). In this codebase the
ranking arrives as DATA — a plain ``{family: rank}`` mapping handed in
by the caller — and is never an authority: nothing here asks a model,
and a rank only TILTS the draw, it never decides it. Stage 2 is the
state-driven sampling face: per-candidate shrunk Beta posterior
(``q_cells.cell_posterior`` over the γ-discounted ``q_cells.fold`` of
the consolidated experience ledger) sampled Thompson-style, weight =
P_planner · θ, one proportional draw — the same P ⊗ Q posture as
``q_cells.sample_method_family``, at the ASSIGN_STEP decision kind.

The planner weight is the harmonic conversion ``P(f) = 1 / rank(f)``
(rank 1 = the planner's top choice): monotone, strictly positive, so a
rank never deletes a candidate — every ranked arm stays samplable
(explore), a sharpened posterior out-pulls a better rank (exploit).
Cold start: the wide Beta(1,1) leaves the distribution
ranking-dominated but non-degenerate; banked evidence re-weights it.

Determinism: ``rng=None`` is the anchor-deterministic ``Random(0)``
default; live callers thread ``q_cells.q_cells_seed_state(ws)`` so the
draw moves when the evidence moves or the round advances (the #251
contract) — no wall clock anywhere. Pure: (ws, candidates, ranking,
rng) -> receipt; the ledger is read, never written — the implied
``assign_step`` Action rides the receipt for the loop to record.

Boundary (fail-closed): candidates must be non-empty, duplicate-free
tokens of the CLOSED registry vocabulary
(``method_families.registered_tokens``); every candidate needs a
finite rank >= 1 from the caller's mapping; the signature hash is the
12-hex state-signature form; garbage raises ValueError naming the
offense.
"""
from __future__ import annotations

import math
import random
import re
import sys
from pathlib import Path
from typing import Mapping

_LOOP = Path(__file__).resolve().parents[1]
_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
for _p in (_SCRIPTS, _LOOP):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import method_families  # noqa: E402 — the closed vocabulary owner
from core import Action, ActionKind, Budget, Context, action_to_doc  # noqa: E402
from rlvr import q_cells  # noqa: E402 — the store face (library use)

SCHEMA = "method-assign/1"

#: the implied action's policy face — names the decision kind family,
#: not a model version (the receipt is the policy's product).
POLICY_VERSION = "rl-v2-assign/1"

#: a rank below 1 is garbage (rank 1 IS the top choice; scores that
#: want their own scale are the caller's conversion job).
MIN_RANK = 1.0

_SIG_RE = re.compile(r"^[0-9a-f]{12}$")


def _validate_signature(signature_hash: object) -> str:
    """The 12-hex state-signature form, or a caller bug — fail fast."""
    if not isinstance(signature_hash, str) \
            or not _SIG_RE.fullmatch(signature_hash):
        raise ValueError(
            f"signature_hash must be a 12-hex signature hash; "
            f"got {signature_hash!r:.80}")
    return signature_hash


def _validate_tier(tier: object) -> int:
    """Tier buckets to int (the q_cells.arm_key convention); a
    non-coercible tier is a caller bug."""
    if isinstance(tier, bool):
        raise ValueError(f"tier must be an integer; got {tier!r}")
    try:
        return int(tier)
    except (TypeError, ValueError):
        raise ValueError(f"tier must be an integer; got {tier!r}") from None


def _validate_candidates(ws, candidates: object) -> list[str]:
    """The closed candidate vocabulary: non-empty, duplicate-free,
    registry-admitted tokens. The registry read (repo set + the
    workspace's admitted discovery overlay) is fail-closed — a
    RegistryError propagates, never degrades open."""
    if not isinstance(candidates, (list, tuple)) or not candidates:
        raise ValueError(
            "candidates must be a non-empty list of method-family tokens")
    vocab = method_families.registered_tokens(ws)
    seen: list[str] = []
    for cand in candidates:
        if not isinstance(cand, str) or not cand or cand.strip() != cand:
            raise ValueError(
                f"candidate must be a bare family token: {cand!r:.80}")
        if cand not in vocab:
            raise ValueError(
                f"candidate outside the closed method-family vocabulary: "
                f"{cand!r}")
        if cand in seen:
            raise ValueError(f"duplicate candidate: {cand!r}")
        seen.append(cand)
    return seen


def _validate_ranks(candidates: list[str],
                    planner_ranking: object) -> dict[str, float]:
    """The planner ranking IS data — validate it like any boundary
    input: one finite rank >= MIN_RANK per candidate, nothing more
    (an unranked candidate and an out-of-vocabulary rank are both
    caller bugs, never silent defaults)."""
    if not isinstance(planner_ranking, Mapping):
        raise ValueError(
            "planner_ranking must be a {family: rank} mapping")
    ranks: dict[str, float] = {}
    for family, rank in planner_ranking.items():
        if family not in candidates:
            raise ValueError(
                f"planner ranked a non-candidate family: {family!r}")
        if isinstance(rank, bool) or not isinstance(rank, (int, float)) \
                or not math.isfinite(rank):
            raise ValueError(f"rank({family}) must be a finite number: "
                             f"{rank!r}")
        if rank < MIN_RANK:
            raise ValueError(f"rank({family}) must be >= {MIN_RANK}: "
                             f"{rank!r}")
        ranks[family] = float(rank)
    for family in candidates:
        if family not in ranks:
            raise ValueError(f"candidate left unranked by the planner: "
                             f"{family!r}")
    return ranks


def _sample(fold_view, sig: str, ranks: dict[str, float],
            rng: random.Random) -> tuple[str, dict[str, dict]]:
    """The P ⊗ Q draw: per-candidate shrunk posterior, one
    proportional selection. Sorted fork order — a candidate reorder
    never reshuffles the streams (the q_cells sampler's determinism
    wall). math.fsum keeps the weight total order-stable and
    interpreter-stable."""
    base = rng.getrandbits(64)
    order = sorted(ranks)
    cand_doc: dict[str, dict] = {}
    weights: dict[str, float] = {}
    for family in order:
        p_llm = 1.0 / ranks[family]
        alpha, beta = q_cells.cell_posterior(fold_view, sig, family)
        theta = random.Random(
            f"method-assign/{base}/{family}").betavariate(alpha, beta)
        weight = p_llm * theta
        weights[family] = weight
        cand_doc[family] = {
            "rank": ranks[family],
            "p_llm": p_llm,
            "alpha": alpha,
            "beta": beta,
            "theta": round(theta, 6),
            "weight": round(weight, 6),
        }
    total = math.fsum(weights[f] for f in order)
    if total <= 0.0:  # pragma: no cover — theta > 0 a.s.
        raise ValueError("degenerate sampling weights (all zero)")
    u = random.Random(f"method-assign-select/{base}").random() * total
    chosen = order[-1]
    cumulative = 0.0
    for family in order:
        cumulative += weights[family]
        if u <= cumulative:
            chosen = family
            break
    return chosen, cand_doc


def assign_method(ws, candidates, planner_ranking, *, signature_hash,
                  tier, rng: random.Random | None = None,
                  gamma: float | q_cells.GammaSchedule | None = None
                  ) -> dict:
    """Sample ONE method family for the step assignment — the
    ASSIGN_STEP face.

    ws supplies the consolidated experience ledger the fold reads
    (``q_cells.default_store``); the assignment itself writes NOTHING
    (the policy faces are side-effect-free — the implied action rides
    the receipt for the loop to record through ``q_cells.append_action``).
    ``gamma`` passes through to the fold; the shipped default (None) is
    the #428 adaptive DTS schedule and the receipt's ``gamma`` reports
    the schedule's post-replay value, mirroring the q_cells sampler.

    Receipt (schema ``method-assign/1``): signature_hash, the chosen
    family, gamma, per-candidate {rank, p_llm, alpha, beta, theta,
    weight}, and ``action`` — the canonical ``action/1`` document the
    decision implies (kind=assign_step, target=the chosen family,
    params carrying the family + tier; its context names the
    assignment event itself, ``assign/<sig>`` — the loop
    re-contextualizes the row when it records the real step).
    """
    sig = _validate_signature(signature_hash)
    tier_out = _validate_tier(tier)
    cands = _validate_candidates(ws, candidates)
    ranks = _validate_ranks(cands, planner_ranking)
    # the fold's own schedule seam, reused so the receipt reports the
    # EXACT gamma the fold ran (no duplicated default to drift apart)
    schedule = q_cells._resolve_schedule(gamma)
    fold_view = q_cells.fold(q_cells.default_store(ws), gamma=schedule)
    if rng is None:
        rng = random.Random(0)  # anchor-deterministic default
    chosen, cand_doc = _sample(fold_view, sig, ranks, rng)
    action = action_to_doc(Action(
        kind=ActionKind.ASSIGN_STEP,
        target=chosen,
        params={"method_family": chosen, "tier": tier_out},
        budget=Budget(wall_s=0.0, max_calls=None),
        context=Context(rollout_id=f"assign/{sig}", step_id=None,
                        policy_version=POLICY_VERSION)))
    return {
        "schema": SCHEMA,
        "signature_hash": sig,
        "family": chosen,
        "gamma": float(schedule.gamma()),
        "candidates": cand_doc,
        "action": action,
    }
