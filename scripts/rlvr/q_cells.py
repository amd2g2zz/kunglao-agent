#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""q_cells.py — the #429 §4 action-value layer: Q cells + DTS call site 2.

The RL kernel's round-layer Q table. Cells are keyed by the plan
contract's binary tuple **(signature_hash, method_family)** — the two
dimensions the kernel already owns on dev:

  - ``signature_hash``  scripts/state_signature.py (issue 396) — the
    canonical DISCRETIZED pre-dispatch state, sha256[:12];
  - ``method_family``   scripts/method_families.py (issue 432) — the
    closed approach vocabulary (the Q key's action half; a token names
    the APPROACH, never the tool chain).

## Hierarchical shrinkage toward the global anchor (层级收缩向全局锚)

A cell is sparse — #432 exists precisely because per-claim cells
fragment into powder. So every cell borrows strength from its family's
GLOBAL posterior (the aggregate over all OTHER signatures,
leave-one-out so a family observed only in one cell never self-echoes):

    anchor(f | sig) = family totals − this cell's own counts
    m_f    = (BASE_ALPHA + s_anchor) / (BASE_ALPHA + BASE_BETA
                                      + s_anchor + f_anchor)
    w_f    = min(SHRINK_CAP, s_anchor + f_anchor)     (borrowed weight)
    cell posterior = Beta(BASE_ALPHA + w_f·m_f + s_local,
                          BASE_BETA  + w_f·(1−m_f) + f_local)

  - 1-sample cell + strong anchor -> the posterior mean follows the
    anchor (borrowed strength; the sample alone cannot move it);
  - local evidence diverges once its mass outgrows the CAPPED anchor
    weight (SHRINK_CAP = the cap that lets cells specialize);
  - a family observed NOWHERE stays the wide Beta(1,1) — cold families
    still rank, exactly through the LLM prior (below).

SHRINK_CAP is a documented policy constant (8.0), not a fitted
parameter: a cell needs ~8 settled rounds of local evidence before its
own signal outweighs the family aggregate. Changing it follows the
ADR-001 governance pattern (replay evidence + pins; never runtime
self-tuning).

## DTS call site 2 — envelope method-family sampling (day-one ruling)

Call site 1 is priority_ratio's claim ordering (untouched here). THIS
module is call site 2: envelope SYNTHESIS time, per #429 §8's online
day-one ruling — the LLM is the PRIOR, sampling ∝
P_LLM(proposal) ⊗ Q:

    theta_f    ~ Beta(cell posterior)          (DTS draw)
    weight_f   =  P_LLM(f) · theta_f
    selection  ~ weight / Σ weight             (proportional draw)

Day one (no credits banked) every posterior is the wide Beta(1,1) and
the selection degenerates to the pure LLM prior — Q is the learned
ADJUSTMENT, it never overrides the proposal channel.

## γ discount — the DTS read face (owner ruling 2026-09-29)

γ applies to the whole posterior tree uniformly (#429 §4) at the FOLD
read face; raw observation rows are append-only and NEVER rewritten
(the posterior-store design, #428). Age = append-order distance from
the end of the credit stream (machine-independent; no wall clock — the
#251 lesson). DTS REPLACES TS as the system's one engine: the SHIPPED
default is the #428 store's EX-2-calibrated adaptive schedule
(``posteriors.default_schedule()`` — floor 0.8 / EMA λ 0.9, imported,
never duplicated here). There is no plain-TS default and no
activation-pending shim: a bare fold discounts. An explicit number
selects a constant-γ schedule (the EX-2 calibration grid face); an
explicit schedule object selects that schedule. Each observation row is
decayed once per LATER row, at THAT row's event-time γ (the no-peeking
recurrence: γ is emitted before the row's own credit is folded in) —
for a constant γ this is exactly the γ^age weight.

## Recording face (the sampler's data spine)

``runs/q-cell-log.jsonl`` — append-only rows
{schema: q-cell-obs/1, ts, source: dispatch|settlement, signature_hash,
method_family, claim, agent, credit}. Dispatch rows carry credit=None
(pending — structural cell mass, never posterior mass); settlement rows
carry the rail-clamped round credit r_r ∈ [0,1]. The dispatch-gate
ALLOW tail records every declared dispatch via
``record_dispatch_observation`` (hooks/worker_budget_sinks.py); the
hook NEVER imports state_signature itself (the #396 freeze pins the
decision faces import-clean) — the signature is computed here, inside
the module. Recording is fail-open: telemetry never turns an ALLOW
into anything else, and the #432 gate stays the sole ENFORCEMENT face
of the vocabulary.

## Store protocol

The posterior store proper is a parallel maker's
scripts/rlvr/posteriors.py (#428, W2-T1). This module consumes ANY
object exposing ``observations() -> list[row]`` (the QCellStore
protocol). ``default_store`` prefers ``posteriors.q_cell_store(ws)``
when that factory exists (lazy import), else the JSONL face above.

## Offline index

``reindex(root)`` — the deterministic offline index over dispatch
history, à la method_families.reindex: face 1 the q-cell observation
log (exact signatures), faces 2/3 the #432 usage log and the
unified-log dispatch rows (no historical signature recoverable — keyed
under the workspace's CURRENT signature, flagged as approximated and
counted pending only; credits join through the observe() face, the
W2-T4 settlement wiring).

## Zero-decision posture

Reading and recording only. The sampler is a PURE function
(store fold + candidates + rng -> receipt); nothing here gates,
settles, or moves a dispatch decision on its own — the compose face
(#431, W2-T3) is the sole consumer of the sampler.

## CLI

  python scripts/rlvr/q_cells.py --reindex <root>   # offline cell index
  python scripts/rlvr/q_cells.py --cells <ws>       # cell table report
  python scripts/rlvr/q_cells.py --sample <ws> --prior fam-a:0.6,fam-b:0.4
  (equivalently PYTHONPATH=scripts python -m rlvr.q_cells ...)
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
from typing import Iterable, Mapping, Protocol

import numpy as np  # issue 420 P2: ordered-float reductions (see _seq_sum)

if __package__ in (None, ""):
    # direct-path execution (python scripts/rlvr/q_cells.py): the
    # package parent (scripts/) is NOT on sys.path (path[0] is
    # scripts/rlvr/) — insert it BEFORE the sibling imports; the guard
    # leaves the import-time path untouched for rlvr.q_cells consumers
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kunglao_log import iter_jsonl, warn

from rlvr import state as ssig  # the package face (issue 420 Phase 2)

SCHEMA_TAG = "q-cells/1"
OBS_SCHEMA = "q-cell-obs/1"
OBS_REL = "runs/q-cell-log.jsonl"
SAMPLE_SCHEMA = "q-cell-sample/1"
REINDEX_SCHEMA = "q-cell-reindex/1"
CELLS_SCHEMA = "q-cell-table/1"

# Beta(1,1) — the ONE aggregate uniform base (compute_priors precedent)
BASE_ALPHA = 1.0
BASE_BETA = 1.0

# Hierarchical-shrinkage anchor cap: the family-global posterior enters
# a cell as at most SHRINK_CAP pseudo-observations, so local evidence
# can always outgrow the anchor and specialize the cell. Policy constant
# (NOT fitted): a cell needs ~8 settled rounds before its own signal
# outweighs the family aggregate. Changing this value follows the
# ADR-001 governance procedure (replay evidence + pins).
SHRINK_CAP = 8.0


def _seq_sum(values) -> float:
    """Input-order float64 reduction — the settlement determinism axiom
    ("float sums in input order") as a numpy primitive (issue 420).

    np.add.accumulate is strictly left-to-right IEEE-754 double addition;
    the prepended 0.0 seed makes it bit-identical to a Python in-order
    sum for every finite input, and — unlike builtin sum(), which
    switched floats to Neumaier compensation in 3.12 — identical on
    every interpreter. np.sum / np.add.reduce are FORBIDDEN on this
    path: pairwise summation reorders the bits, and the pins in
    tests/test_rlvr_bitexact.py are the wall.

    Canonical implementation: rlvr.scalar._seq_sum (the pattern-setter);
    redeclared here to keep this module's deliberate import isolation
    (zero-decision posture — no settlement-family import) — the
    TERMINAL_FACT_STATUSES redeclaration precedent in rlvr.state.
    """
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        return 0.0
    return float(np.add.accumulate(np.concatenate(([0.0], arr)))[-1])


class GammaSchedule(Protocol):
    """Any γ schedule with the posteriors schedule face: ``gamma()``
    emits the γ in force for the NEXT observation; ``observe(outcome)``
    folds that outcome in (no peeking)."""

    def gamma(self) -> float: ...

    def observe(self, outcome) -> None: ...


def _resolve_schedule(gamma) -> GammaSchedule:
    """The γ face resolution. None → the SHIPPED default (the #428
    adaptive schedule, imported — single source of truth); a number → a
    constant schedule (the EX-2 calibration grid face, domain-validated
    (0, 1] by the store); a schedule-like object → itself. Anything else
    is a caller bug — fail fast at the boundary."""
    if gamma is None or isinstance(gamma, (int, float)) \
            and not isinstance(gamma, bool):
        from rlvr import posteriors as _posteriors  # noqa: PLC0415
        if gamma is None:
            return _posteriors.default_schedule()
        return _posteriors.gamma_constant(float(gamma))
    if hasattr(gamma, "gamma") and hasattr(gamma, "observe"):
        return gamma
    raise ValueError(
        f"gamma must be None (the shipped DTS default schedule), a "
        f"constant in (0, 1], or a gamma()/observe() schedule; got "
        f"{gamma!r:.80}")

# the #432 v0 prose declaration face (dual-face contract: v1 envelope
# field FIRST, prose marker second — same order as method_families)
_V0_MARKER_RE = re.compile(r"method-family:\s*([^\n]+)", re.IGNORECASE)
_SIG_HASH_RE = re.compile(r"^[0-9a-f]{12}$")

# #432 usage-log face (the (family, cell) counting feed) and the
# unified-log dispatch detail marker both feed reindex
_USAGE_REL = "runs/method-family-log.jsonl"
_FAMILY_DETAIL_RE = re.compile(r"\bmethod_family=([A-Za-z0-9-]+)")


# ---------------------------------------------------------------------------
# store protocol + faces
# ---------------------------------------------------------------------------

class QCellStore(Protocol):
    """The thin store seam — any append-order observation feed.

    scripts/rlvr/posteriors.py (#428, W2-T1) can implement this with the
    posterior bank's fold view; until then JSONLQStore reads the
    module's own append-only log. Dispatch rows (credit=None) are
    pending mass; only numeric credits enter the posterior fold.
    """

    def observations(self) -> list[dict]: ...


class InMemoryStore:
    """The protocol stub — composition/tests, no filesystem."""

    def __init__(self, rows: Iterable[dict] | None = ()):
        self._rows = [dict(r) for r in (rows or ())]

    def observations(self) -> list[dict]:
        return list(self._rows)


class JSONLQStore:
    """The default day-one store: runs/q-cell-log.jsonl (tolerant)."""

    def __init__(self, root):
        self.path = Path(root) / OBS_REL

    def observations(self) -> list[dict]:
        if not self.path.is_file():
            return []
        try:
            text = self.path.read_text(encoding="utf-8",
                                       errors="replace")
        except OSError:
            return []
        return [row for row in iter_jsonl(text.splitlines())
                if isinstance(row, dict)]


def default_store(ws) -> QCellStore:
    """Prefer the #428 posterior bank when its factory exists; else the
    JSONL face. Degrade is one rate-limited warn, never silent."""
    try:
        from rlvr import posteriors as _posteriors  # noqa: PLC0415
        factory = getattr(_posteriors, "q_cell_store", None)
        if callable(factory):
            return factory(ws)
        return JSONLQStore(ws)
    except ImportError:
        return JSONLQStore(ws)
    except Exception as exc:  # noqa: BLE001 — degrade, loudly
        warn("q_cells.default_store",
             f"posterior bank unusable ({type(exc).__name__}: {exc}) "
             f"— JSONL fallback")
        return JSONLQStore(ws)


# ---------------------------------------------------------------------------
# fold (γ discount on the read face; raw rows never rewritten)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CellCounts:
    """One (signature_hash, method_family) cell's γ-discounted masses."""
    signature_hash: str
    family: str
    success: float = 0.0
    failure: float = 0.0
    n_pending: int = 0

    @property
    def evidence(self) -> float:
        return self.success + self.failure


@dataclass(frozen=True)
class Fold:
    """The γ-discounted read view over a store's observations."""
    cells: dict[tuple[str, str], CellCounts] = field(default_factory=dict)

    def family_mass(self, family: str) -> tuple[float, float]:
        """(success, failure) mass over ALL signatures — the family
        global aggregate the anchor is built from.

        numpy adoption (issue 420 Phase 2, README rule 1): the mass
        accumulation runs through _seq_sum — cell insertion order,
        bit-identical to the former += loop and interpreter-stable
        (builtin sum() went Neumaier in 3.12)."""
        cells = [(cell.success, cell.failure)
                 for (_sig, fam), cell in self.cells.items()
                 if fam == family]
        return (_seq_sum([s for s, _ in cells]),
                _seq_sum([f for _, f in cells]))


def _credit_of(row: dict):
    c = row.get("credit")
    if isinstance(c, bool) or not isinstance(c, (int, float)):
        return None
    return float(c)


def fold(store: QCellStore, gamma: float | GammaSchedule | None = None
         ) -> Fold:
    """DTS-discounted fold over the credit stream. The SHIPPED default
    (``gamma=None``) is the #428 adaptive schedule imported from the
    posterior store — a bare fold DISCOUNTS (owner ruling 2026-09-29:
    DTS replaces TS; a constant γ is only the explicit calibration
    face). Each row is decayed once per LATER observation, at THAT
    observation's event-time γ (no peeking: the schedule emits γ before
    the row's own credit is folded in) — for a constant γ this is
    exactly the γ^age weight:

        weight_i = Π_{k>i} γ_k        (γ_k emitted at row k's event time)

    Age = append-order distance from the END of the global credit stream
    (uniform tree decay; no wall clock — machine-independent replay).
    Pending rows (credit=None) count toward n_pending only, never
    posterior mass."""
    schedule = _resolve_schedule(gamma)
    rows = [r for r in store.observations()
            if isinstance(r, dict) and _credit_of(r) is not None]
    n = len(rows)
    gammas = [0.0] * n
    for i, row in enumerate(rows):
        gammas[i] = schedule.gamma()
        schedule.observe(_credit_of(row))
    weights = [1.0] * n
    w = 1.0
    for i in range(n - 2, -1, -1):
        w *= gammas[i + 1]
        weights[i] = w
    cells: dict[tuple[str, str], CellCounts] = {}
    for i, row in enumerate(rows):
        credit = max(0.0, min(1.0, _credit_of(row)))
        weight = weights[i]
        key = (str(row.get("signature_hash") or ""),
               str(row.get("method_family") or ""))
        cell = cells.get(key)
        if cell is None:
            cell = CellCounts(key[0], key[1])
            cells[key] = cell
        cells[key] = CellCounts(
            key[0], key[1],
            success=cell.success + weight * credit,
            failure=cell.failure + weight * (1.0 - credit),
            n_pending=cell.n_pending)
    for row in store.observations():
        if not isinstance(row, dict) or _credit_of(row) is not None:
            continue
        key = (str(row.get("signature_hash") or ""),
               str(row.get("method_family") or ""))
        cell = cells.get(key) or CellCounts(key[0], key[1])
        cells[key] = CellCounts(cell.signature_hash, cell.family,
                                cell.success, cell.failure,
                                cell.n_pending + 1)
    return Fold(cells)


# ---------------------------------------------------------------------------
# hierarchical shrinkage
# ---------------------------------------------------------------------------

def cell_posterior(fold_view: Fold, signature_hash: str,
                   family: str, *,
                   feature_pool=None) -> tuple[float, float]:
    """The SHRUNK Beta posterior used for sampling — (alpha, beta).

    Anchor = the family's global aggregate LEAVE-ONE-OUT (this cell's
    own counts excluded — a family observed only here has an empty
    anchor and stands on its local evidence alone, no self-echo). A
    nowhere-observed family yields the wide Beta(1,1) prior.

    ``feature_pool`` (#460 Part B, predict-before-try) is an optional
    duck-typed FeaturePool (``.success``/``.failure``/``.rows`` —
    scripts/rlvr/feature_prior.py): its similarity-discounted masses
    are added to the anchor masses BEFORE the single SHRINK_CAP, so
    the family/global pool stays the base borrow and total borrowed
    pseudo-observations never exceed the cap. None (default) or a
    zero-mass pool is bit-identical to the pre-change kernel — the
    determinism wall. The live face pools every table row; the replay
    passes exclude_run by explicit run id (leave-instance-out is the
    replay's split, not a live-face filter)."""
    cell = fold_view.cells.get(
        (signature_hash, family),
        CellCounts(signature_hash, family))
    fam_s, fam_f = fold_view.family_mass(family)
    s_anchor = max(fam_s - cell.success, 0.0)
    f_anchor = max(fam_f - cell.failure, 0.0)
    if feature_pool is not None:
        s_anchor += float(feature_pool.success)
        f_anchor += float(feature_pool.failure)
    n_anchor = s_anchor + f_anchor
    if n_anchor <= 0.0:
        return (BASE_ALPHA + cell.success, BASE_BETA + cell.failure)
    m = (BASE_ALPHA + s_anchor) / (
        BASE_ALPHA + BASE_BETA + n_anchor)
    w = min(SHRINK_CAP, n_anchor)
    return (BASE_ALPHA + w * m + cell.success,
            BASE_BETA + w * (1.0 - m) + cell.failure)


# ---------------------------------------------------------------------------
# DTS call site 2: envelope method-family sampling
# ---------------------------------------------------------------------------

def _coerce_signature(state_signature) -> str:
    """Snapshot dict -> canonical hash; 12-hex string passes through.
    Anything else is a caller bug — fail fast at the boundary."""
    if isinstance(state_signature, Mapping):
        return ssig.signature_hash(dict(state_signature))
    if isinstance(state_signature, str) \
            and _SIG_HASH_RE.fullmatch(state_signature):
        return state_signature
    raise ValueError(
        f"state_signature must be a state_signature.snapshot() dict or a "
        f"12-hex signature hash; got {state_signature!r:.80}")


def _normalize_prior(candidates_with_llm_prior) -> dict[str, float]:
    if isinstance(candidates_with_llm_prior, Mapping):
        items = candidates_with_llm_prior.items()
    else:
        items = [(str(k), v) for k, v in candidates_with_llm_prior]
    prior: dict[str, float] = {}
    for family, p in items:
        if not isinstance(family, str) or not family.strip():
            raise ValueError(f"candidate family must be a token: {family!r}")
        if isinstance(p, bool) or not isinstance(p, (int, float)):
            raise ValueError(f"P_LLM({family}) must be numeric: {p!r}")
        p = float(p)
        if p < 0.0 or p != p:  # negative or NaN
            raise ValueError(f"P_LLM({family}) must be >= 0 and finite: {p}")
        prior[family.strip()] = p
    if not prior:
        raise ValueError("candidates_with_llm_prior is empty")
    if sum(prior.values()) <= 0.0:
        raise ValueError(
            "the LLM prior is REQUIRED (day-one ruling): at least one "
            "candidate must carry P_LLM > 0")
    return prior


def _feature_pools(features, feature_table,
                   prior: Mapping[str, float]) -> Mapping:
    """#460 Part B — the flag-gated pool resolution at call site 2.

    Returns {} (the inert no-op) unless the
    KUNGLAO_PREDICT_BEFORE_TRY flag is on AND both the features vector
    and a loadable table were supplied; otherwise one FeaturePool per
    candidate family. Any feature_prior failure degrades to {} (the
    seam is fail-open: a broken prior never breaks the sampler)."""
    if features is None or feature_table is None:
        return {}
    try:
        from rlvr import feature_prior as _fp  # noqa: PLC0415 — lazy
        if not _fp.enabled():
            return {}
        return _fp.pools_for_candidates(feature_table, features,
                                        prior.keys())
    except Exception:  # noqa: BLE001 — fail-open by design
        return {}


def _death_multiplier(death, family: str) -> tuple[float, dict | None]:
    """#461 Phase 2 (option-death) — one candidate's effective sampler
    multiplier + the additive receipt block.

    ``death`` is the duck-typed verdict mapping the sampler hosts
    thread (``{family → verdict}`` from rlvr.termination.verdicts);
    this module NEVER imports that face — verdicts are data. Absent
    verdict → (1.0, None): no multiplier, no receipt block, the draw
    bit-identical to the pre-change kernel (x · 1.0 is IEEE-exact). A
    non-mapping verdict degrades the same way (fail-open). A malformed
    multiplier (non-numeric, ≤ 0 — would DELETE the option, or > 1 —
    would AMPLIFY it) degrades to 1.0 with the receipt carrying the
    EFFECTIVE multiplier actually applied — the audit trail never lies
    about the arithmetic that ran."""
    if death is None:
        return 1.0, None
    verdict = death.get(family)
    if not isinstance(verdict, dict):
        return 1.0, None
    raw = verdict.get("weight_multiplier", 1.0)
    try:
        multiplier = float(raw)
        if not (0.0 < multiplier <= 1.0) or multiplier != multiplier:
            multiplier = 1.0
    except (TypeError, ValueError):
        multiplier = 1.0
    p_dead = verdict.get("p_dead")
    if isinstance(p_dead, bool) or not isinstance(p_dead, (int, float)):
        p_dead = None
    else:
        p_dead = round(float(p_dead), 9)
    return multiplier, {"dead": bool(verdict.get("dead")),
                        "p_dead": p_dead,
                        "weight_multiplier": multiplier}


def sample_method_family(state_signature, candidates_with_llm_prior,
                         store: QCellStore, rng: random.Random | None = None,
                         gamma: float | GammaSchedule | None = None, *,
                         features: Mapping | None = None,
                         feature_table=None,
                         death: Mapping | None = None) -> dict:
    """DTS call site 2 — sample ONE method family for envelope synthesis.

    sampling ∝ P_LLM(proposal) ⊗ Q (#429 §8 day-one ruling): per-family
    DTS draw theta_f from the shrunk cell posterior, weight =
    P_LLM · theta, one proportional selection. The fold runs under the
    shipped default schedule (gamma=None — the #428 adaptive DTS
    schedule, imported from the posterior store); the receipt's
    ``gamma`` reports the schedule's post-replay γ (the adaptive band —
    never pinned at 1.0). Pure: (fold, candidates, rng) -> receipt;
    every receipt number traces to store rows (逐句可归因). rng=None ->
    random.Random(0) (anchor-deterministic default); live callers thread
    q_cells_seed_state(ws) so the sample moves when evidence moves or
    the round advances (the #251 contract).

    #460 Part B (predict-before-try): ``features`` + ``feature_table``
    activate the feature-conditioned prior ONLY when
    KUNGLAO_PREDICT_BEFORE_TRY is set AND both inputs are usable —
    per-candidate similarity pools (feature_prior.pools_for_candidates)
    ride the cell posterior as a second anchor source under the one
    SHRINK_CAP, and candidates with contributing rows carry an additive
    ``feature_prior`` receipt block. Any other state (flag off, no
    inputs, empty table) is byte-identical to the pre-change kernel.

    #461 Phase 2 (option-death termination): ``death`` is the optional
    duck-typed verdict mapping {family → verdict} the sampler hosts
    thread from rlvr.termination.verdicts (this module never imports
    that face — verdicts are data, not imports). A dead family's
    weight is multiplied by its verdict's weight_multiplier (ARM_FLOOR
    0.1 — floored, never zeroed: the PARK posture, still samplable,
    revivable by new alive evidence); the per-candidate receipt gains
    an additive ``death`` block (dead, p_dead, the EFFECTIVE
    multiplier). Absent/empty/all-alive(×1.0) leaves the draw
    byte-identical to the pre-change kernel; malformed multipliers
    fail open to 1.0 (never delete, never amplify)."""
    sig = _coerce_signature(state_signature)
    prior = _normalize_prior(candidates_with_llm_prior)
    schedule = _resolve_schedule(gamma)
    fold_view = fold(store, gamma=schedule)
    pools = _feature_pools(features, feature_table, prior)
    if rng is None:
        rng = random.Random(0)  # anchor-deterministic default
    base = rng.getrandbits(64)
    # deterministic fork order: a candidate reorder never reshuffles
    order = sorted(prior)
    cand_doc: dict[str, dict] = {}
    weights: dict[str, float] = {}
    for family in order:
        alpha, beta = cell_posterior(
            fold_view, sig, family,
            feature_pool=pools.get(family) if pools else None)
        child = random.Random(f"qcell/{base}/{family}")
        theta = child.betavariate(alpha, beta)
        multiplier, death_doc = _death_multiplier(death, family)
        weights[family] = prior[family] * theta * multiplier
        cand = {
            "p_llm": prior[family],
            "alpha": alpha,
            "beta": beta,
            "theta": round(theta, 6),
            "weight": round(weights[family], 6),
        }
        if death_doc is not None:
            # additive block — no verdict, no block (byte identity)
            cand["death"] = death_doc
        pool = pools.get(family) if pools else None
        if pool is not None and pool.rows > 0:
            # additive block — a zero-row pool never rides the receipt
            cand["feature_prior"] = {
                "pool_success": round(pool.success, 9),
                "pool_failure": round(pool.failure, 9),
                "rows": pool.rows,
            }
        cand_doc[family] = cand
    # numpy adoption (issue 420 Phase 2, README rule 1): the sampling
    # weight total runs through _seq_sum — candidate insertion order
    # (the sorted fork order), bit-identical to the former builtin
    # sum() and interpreter-stable.
    total = _seq_sum(list(weights.values()))
    if total <= 0.0:  # pragma: no cover — theta > 0 a.s.
        raise ValueError("degenerate sampling weights (all zero)")
    u = random.Random(f"qcell-select/{base}").random() * total
    chosen = order[-1]
    cumulative = 0.0
    for family in order:
        cumulative += weights[family]
        if u <= cumulative:
            chosen = family
            break
    return {
        "schema": SAMPLE_SCHEMA,
        "signature_hash": sig,
        "family": chosen,
        "gamma": float(schedule.gamma()),
        "candidates": cand_doc,
    }


def q_cells_seed_state(ws) -> tuple[random.Random, int]:
    """THE shared per-round seed source for call site 2 — the #251
    contract f(store state, round): sha256 over the canonical fold
    payload PLUS the round axis mixed INSIDE the hashed doc
    (priority_ratio.round_index, the convergence ledger's RAW
    snapshot-row count — single source, lazily imported to keep this
    module's import cost off every recorder call). The sample moves
    when evidence moves OR the round advances — including the
    evidence-free cold workspace (distinct rounds produce distinct
    seeds; the #251 per-round-cold-start property, 462 design-review
    MEDIUM-1: the round used to be computed and returned but never
    hashed, freezing the cold draw); no wall clock anywhere."""
    from priority_ratio import round_index  # noqa: PLC0415
    rnd = round_index(ws)
    store = default_store(ws)
    schedule = _resolve_schedule(None)   # the shipped DTS default
    fold_view = fold(store, gamma=schedule)
    payload = {
        "cells": sorted(
            [sig, fam, round(c.success, 9), round(c.failure, 9),
             c.n_pending]
            for (sig, fam), c in fold_view.cells.items()),
        "gamma_schedule": {
            "floor": schedule.gamma_floor,
            "ema_lambda": schedule.ema_lambda,
        },
        "round": rnd,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True,
                   ensure_ascii=False).encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16)), rnd


# ---------------------------------------------------------------------------
# recording faces (append-only; fail-open)
# ---------------------------------------------------------------------------

def _now() -> str:
    from harness_common import utc_now_z  # noqa: PLC0415
    return utc_now_z()


def _append_row(path: Path, row: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
        import os
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return True
    except OSError as exc:
        warn("q_cells.append", f"{type(exc).__name__}: {exc}")
        return False


def append_observation(ws, signature_hash: str, method_family: str,
                       credit: float | None = None, *, source: str,
                       claim: str | None = None,
                       agent: str | None = None,
                       dispatch_id: str | None = None,
                       ts: str | None = None,
                       fingerprint: str | None = None) -> dict:
    """Append one observation row (the data spine). Credit clamps into
    [0,1] at this boundary (r_r is rail-clamped per #429 §4; the clamping
    belongs to the caller's rails but the boundary never trusts input).
    Fail-open: an unwritable log is one rate-limited warn, never an
    exception into the producer."""
    credit_out = None
    if credit is not None:
        if isinstance(credit, bool) or not isinstance(credit, (int, float)):
            warn("q_cells.append", f"non-numeric credit dropped: {credit!r}")
        else:
            credit_out = max(0.0, min(1.0, float(credit)))
    row = {
        "schema": OBS_SCHEMA,
        "ts": ts or _now(),
        "source": str(source),
        "signature_hash": str(signature_hash),
        "method_family": str(method_family),
        "claim": claim,
        "agent": agent,
        "dispatch_id": dispatch_id,
        "fingerprint": fingerprint,
        "credit": credit_out,
    }
    appended = _append_row(Path(ws) / OBS_REL, row)
    return {"appended": appended, "row": row}


def observe(ws, signature_hash: str, method_family: str,
            credit: float) -> dict:
    """The settlement feed: one (signature_hash, method_family, credit)
    observation — the observation interface as DATA (the W2-T4
    settlement wiring calls this from settled round_credit rows)."""
    return append_observation(ws, signature_hash, method_family, credit,
                              source="settlement")


def observe_settlement(ws, dispatch_id: str, credit) -> dict:
    """THE settlement feed's match-and-bank face (issue 462 W5): bank one
    settled round credit into the q cell the dispatch opened.

    Matches the LATEST pending dispatch row carrying this dispatch
    identity — the envelope's claim id (what the production ALLOW tail
    records; the row's explicit ``dispatch_id`` field is the test/
    override face) — or the honest gap. Banked rows stay pending forever
    (the log is append-only and never rewritten): a repeat settlement of
    the SAME dispatch id cannot double-bank because identical replays
    are refused by the ledger and any re-settlement (the late-cite
    amendment) is blocked from re-banking by the settlement-presence
    guard in scalar.settle_round_credit; a future ledger PRUNE +
    re-settle of the same claim would re-bank into the stale row — the
    named v1 limitation. The credit
    arriving here is the settled #433 ladder value (verified = admission
    ticket, cited-toward-stage = value — the ladder ran upstream in
    scalar.round_credit); the append boundary clamps it into [0, 1]
    (r_r is rail-clamped per #429 §4). No matching dispatch row is the
    honest gap: no row, never a fabricated bucket. Fail-open: telemetry
    never breaks settlement."""
    did = str(dispatch_id or "")
    try:
        match = None
        for row in reversed(JSONLQStore(ws).observations()):
            if not isinstance(row, dict) \
                    or str(row.get("source") or "") != "dispatch" \
                    or row.get("credit") is not None:
                continue
            if did and (str(row.get("claim") or "") == did
                        or str(row.get("dispatch_id") or "") == did):
                match = row
                break
        if match is None:
            warn("q_cells.observe_settlement",
                 f"no pending dispatch row for {did!r} — credit not "
                 f"banked (the honest gap)")
            return {"appended": False, "matched": False,
                    "reason": "unmatched", "dispatch_id": did}
        out = append_observation(ws, str(match.get("signature_hash")),
                                 str(match.get("method_family")), credit,
                                 source="settlement",
                                 claim=match.get("claim"),
                                 agent=match.get("agent"),
                                 dispatch_id=did,
                                 fingerprint=match.get("fingerprint"))
        return {"appended": out["appended"], "matched": True,
                "reason": None if out["appended"] else "write-failed",
                "dispatch_id": did,
                "signature_hash": match.get("signature_hash"),
                "method_family": match.get("method_family")}
    except Exception as exc:  # noqa: BLE001 — telemetry, never the producer
        warn("q_cells.observe_settlement", f"{type(exc).__name__}: {exc}")
        return {"appended": False, "matched": False,
                "reason": f"error:{type(exc).__name__}",
                "dispatch_id": did}


def declared_family(envelope_meta, prompt_text: str) -> str | None:
    """The declared method family — the #432 dual-face contract, single
    owner reused when importable: v1 envelope field first, v0 prose
    marker second. The local fallback is byte-equivalent for
    pre-#432-bases; once #432 is on dev the lazy import resolves and the
    fallback is dead code kept only for partial deployments."""
    if isinstance(envelope_meta, Mapping):
        v = envelope_meta.get("method_family")
        if isinstance(v, str) and v.strip():
            return v.strip()
    m = _V0_MARKER_RE.search(prompt_text or "")
    if m:
        return m.group(1).strip()
    return None


def record_dispatch_observation(ws, prompt: str, *,
                                envelope_meta=None,
                                claim: str | None = None,
                                agent: str | None = None,
                                fingerprint: str | None = None) -> dict:
    """Record the (signature_hash, method_family) observation at the
    dispatch ALLOW tail — s_r = state-sig/1 AT dispatch (#429 §2).

    The signature is computed HERE (the hook must stay state_signature-
    free per the #396 freeze). Undeclared families are the honest gap:
    no row, never a fabricated bucket (the #432 gate is the enforcement
    face that makes declaration mandatory). Fail-open throughout."""
    try:
        family = declared_family(envelope_meta, prompt or "")
        if not family:
            return {"appended": False, "reason": "undeclared",
                    "family": None, "signature_hash": None}
        sig = ssig.signature_hash(ssig.snapshot(ws))
        out = append_observation(ws, sig, family, None, source="dispatch",
                                 claim=claim, agent=agent,
                                 fingerprint=fingerprint)
        return {"appended": out["appended"], "reason": None,
                "family": family, "signature_hash": sig}
    except Exception as exc:  # noqa: BLE001 — telemetry, never the producer
        warn("q_cells.record_dispatch",
             f"{type(exc).__name__}: {exc}")
        return {"appended": False, "reason": f"error:{type(exc).__name__}",
                "family": None, "signature_hash": None}


# ---------------------------------------------------------------------------
# offline index (deterministic; pure read)
# ---------------------------------------------------------------------------

def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [r for r in iter_jsonl(text.splitlines())
            if isinstance(r, dict)]


def _current_sig(ws) -> str:
    """The workspace's CURRENT signature (the replay approximation face:
    historical signatures are unrecoverable from a final-state
    workspace; a bare/unreadable ws keeps a canonical cold signature)."""
    try:
        return ssig.signature_hash(ssig.snapshot(ws))
    except Exception:  # noqa: BLE001 — approximation degrades to a key
        return ""


def _count_pending(rows: Iterable[dict], pendings: dict, sig: str,
                   family_of) -> tuple[int, int]:
    """Count one face's rows into pendings; returns (unattributed,
    approximated)."""
    unattributed = approximated = 0
    for row in rows:
        family = family_of(row)
        if not family:
            unattributed += 1
            continue
        pendings[(sig, family)] = pendings.get((sig, family), 0) + 1
        approximated += 1
    return unattributed, approximated


def _scan_usage_face(root: Path, pendings: dict) -> tuple[set, int, int, int]:
    """Face 2 — the #432 usage log (family + claim; NO signature)."""
    roots: set[Path] = set()
    scanned = unattributed = approximated = 0
    for p in sorted(root.rglob(_USAGE_REL)):
        roots.add(p.parent.parent)
        rows = _read_jsonl(p)
        scanned += len(rows)
        u, a = _count_pending(rows, pendings, _current_sig(p.parent.parent),
                              lambda r: str(r.get("family") or ""))
        unattributed += u
        approximated += a
    return roots, scanned, unattributed, approximated


def _scan_unified_face(root: Path, skip: set[Path],
                       pendings: dict) -> tuple[int, int, int]:
    """Face 3 — unified-log dispatch rows (method_family= in detail)."""
    scanned = unattributed = approximated = 0
    for p in sorted(root.rglob("runs/logs/kunglao-*.jsonl")):
        ws = p.parent.parent.parent
        if ws in skip:
            continue  # counted from its authoritative faces already
        dispatch_rows = [r for r in _read_jsonl(p)
                         if r.get("action") == "dispatch"]
        scanned += len(dispatch_rows)
        u, a = _count_pending(
            dispatch_rows, pendings, _current_sig(ws),
            lambda r: (m.group(1) if (m := _FAMILY_DETAIL_RE.search(
                str(r.get("detail") or ""))) else ""))
        unattributed += u
        approximated += a
    return scanned, unattributed, approximated


def reindex(root, gamma: float | GammaSchedule | None = None) -> dict:
    """The deterministic offline index over dispatch history.

    The fold runs under the shipped DTS default (``gamma=None`` — the
    #428 adaptive schedule imported from the posterior store; an
    explicit constant γ selects the exact-count calibration face).

    Face 1 — runs/q-cell-log.jsonl (authoritative; exact signatures +
    credits). Face 2 — the #432 usage log (family + claim, NO
    signature/credit): keyed under the workspace's CURRENT signature
    (approximation — historical signatures are unrecoverable from a
    final-state workspace), counted PENDING only. Face 3 — unified-log
    dispatch rows carrying method_family= in detail (same
    approximation); a workspace with its own usage log is counted from
    that face only (no double count — the method_families.reindex
    precedence). Rows without a family are unattributed: counted once
    as the honest gap, never fabricated."""
    root = Path(root)
    schedule = _resolve_schedule(gamma)
    rows_scanned = unattributed = approximated = 0
    pendings: dict[tuple[str, str], int] = {}
    face1_rows: list[dict] = []
    obs_roots: set[Path] = set()
    for p in sorted(root.rglob(OBS_REL)):
        obs_roots.add(p.parent.parent)
        rows = _read_jsonl(p)
        rows_scanned += len(rows)
        face1_rows.extend(rows)
    fold_view = fold(InMemoryStore(face1_rows), gamma=schedule)
    # representative γ for the approximate-count face: the schedule's
    # post-replay γ (what the engine believes after the whole stream)
    rep_gamma = float(schedule.gamma())
    usage_roots, scanned, unattributed, approximated = _scan_usage_face(
        root, pendings)
    rows_scanned += scanned
    scanned, u3, a3 = _scan_unified_face(root, usage_roots | obs_roots,
                                         pendings)
    rows_scanned += scanned
    unattributed += u3
    approximated += a3
    cells = []
    for (sig, fam) in sorted(set(fold_view.cells) | set(pendings)):
        cell = fold_view.cells.get((sig, fam),
                                   CellCounts(sig, fam))
        cells.append({
            "signature_hash": sig, "method_family": fam,
            "credit_observations": int(round(
                _weighted_count(cell.success, cell.failure, rep_gamma))),
            "success": round(cell.success, 9),
            "failure": round(cell.failure, 9),
            "pending": cell.n_pending + pendings.get((sig, fam), 0),
        })
    families: dict[str, dict] = {}
    for c in cells:
        f = families.setdefault(c["method_family"],
                                {"family": c["method_family"],
                                 "cells": 0, "credit_observations": 0,
                                 "pending": 0})
        f["cells"] += 1
        f["credit_observations"] += c["credit_observations"]
        f["pending"] += c["pending"]
    return {
        "schema": REINDEX_SCHEMA,
        "root": str(root),
        "rows_scanned": rows_scanned,
        "unattributed": unattributed,
        "signature_approximated_cells": approximated,
        "cells": cells,
        "families": [families[k] for k in sorted(families)],
    }


def _weighted_count(success: float, failure: float,
                    gamma: float) -> float:
    """Approximate observation count from discounted masses (γ=1 is
    exact; γ<1 reports the discounted evidence mass — the honest
    decayed count, never a rewritten raw count)."""
    if gamma >= 1.0:
        return success + failure
    # γ<1: masses under-discount to a count only when every credit is
    # extreme; report the mass ratio-preserving estimate max component
    return max(success, failure) * 2.0 if success + failure > 0 else 0.0


# ---------------------------------------------------------------------------
# CLI (offline faces only — the sampler is a library call)
# ---------------------------------------------------------------------------

def cell_table(ws, gamma: float | GammaSchedule | None = None) -> dict:
    """The cell-table report over one workspace's observation log (the
    shipped DTS default fold when gamma is None)."""
    schedule = _resolve_schedule(gamma)
    fold_view = fold(default_store(ws), gamma=schedule)
    cells = [{
        "signature_hash": c.signature_hash,
        "method_family": c.family,
        "success": round(c.success, 9),
        "failure": round(c.failure, 9),
        "pending": c.n_pending,
    } for c in sorted(fold_view.cells.values(),
                      key=lambda c: (c.signature_hash, c.family))]
    return {"schema": CELLS_SCHEMA, "workspace": str(ws),
            "gamma": float(schedule.gamma()), "cells": cells}


def _parse_prior(text: str) -> dict[str, float]:
    prior: dict[str, float] = {}
    for part in text.split(","):
        fam, _, p = part.partition(":")
        prior[fam.strip()] = float(p)
    return prior


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rlvr.q_cells",
        description="#429 §4 Q cells — offline index, cell table, "
                    "diagnostic sample (the live sampler is a library "
                    "call consumed by the compose face #431)")
    ap.add_argument("--reindex", metavar="ROOT",
                    help="deterministic offline index over dispatch "
                         "history (campaign/workspaces root)")
    ap.add_argument("--cells", metavar="WS",
                    help="the (signature_hash, method_family) cell table")
    ap.add_argument("--sample", metavar="WS",
                    help="diagnostic sample for one workspace "
                         "(requires --prior)")
    ap.add_argument("--prior", metavar="FAM:P,...",
                    help="the P_LLM proposal prior (with --sample)")
    args = ap.parse_args(argv)
    if args.reindex:
        print(json.dumps(reindex(args.reindex), ensure_ascii=False,
                         indent=2))
        return 0
    if args.cells:
        print(json.dumps(cell_table(args.cells), ensure_ascii=False,
                         indent=2))
        return 0
    if args.sample:
        if not args.prior:
            ap.error("--sample requires --prior fam:p,...")
        rng, rnd = q_cells_seed_state(args.sample)
        receipt = sample_method_family(
            ssig.snapshot(args.sample), _parse_prior(args.prior),
            default_store(args.sample), rng=rng)
        receipt["round"] = rnd
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
