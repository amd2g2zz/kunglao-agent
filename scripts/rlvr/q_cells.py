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

``runs/experience.jsonl`` (the consolidated WHAT-HAPPENED file, #721;
``runs/q-cell-log.jsonl`` remains readable — and migration-archived —
during the compat window) — append-only rows
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
import math
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Protocol


if __package__ in (None, ""):
    # direct-path execution (python scripts/rlvr/q_cells.py): the
    # package parent (scripts/) is NOT on sys.path (path[0] is
    # scripts/rlvr/) — insert it BEFORE the sibling imports; the guard
    # leaves the import-time path untouched for rlvr.q_cells consumers
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kunglao_log import iter_jsonl, warn

from rlvr import state as ssig  # the package face (issue 420 Phase 2)
from rlvr import consolidated_ledger as _cl  # #721: the consolidated files

SCHEMA_TAG = "q-cells/1"
OBS_SCHEMA = "q-cell-obs/1"
OBS_REL = "runs/q-cell-log.jsonl"  # legacy rel (pre-#721 archive)
# #721: the consolidated experience rel (the live observation home)
EXPERIENCE_REL = _cl.CONSOLIDATED["experience"]
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

# #548 follow-up (rides WS2, #545): the Φ tiebreaker weight on the
# credit READ face. The censored-review verdict (PR #549) showed
# censored-with-facts rows moving Φ +0.079 while clean failures moved
# −0.009, both banking ≈0.5 credit — the punishment did not track state
# work. The tiebreak shifts the effective credit by
# PHI_TIEBREAK_WEIGHT · phi_delta BEFORE the [0,1] clamp, so at equal
# banked credit the row that moved the state forward folds stronger.
# Policy constant (NOT fitted); rows without a phi_delta field are
# bit-identical to the pre-change fold (the determinism wall).
PHI_TIEBREAK_WEIGHT = 0.25

# issue-678 D-678.4a — the TRACE observation band: a settled credit in
# (0, OBSERVATION_BAND_CEIL] is the reward ladder's INFORMATION option
# (trace canonical 0.01 — refuted-with-replay / uncited-verified), not
# a verdict. The fold previously banked it as (1 − credit) FAILURE
# mass, so a 0.01 credit trained 0.99 failure against method families
# that produced verified work (the live un-training defect: 4 of 5
# failure units landed on successes). Such rows stay in the observation
# log and in the decay/schedule chain — they add NEITHER success nor
# failure mass. A genuine 0.0 remains a failure observation (nothing
# was produced). Mirrors scalar.OUTPUT_RAILS TRACE range top —
# dependency-light redeclaration, the TERMINAL_FACT_STATUSES precedent.
OBSERVATION_BAND_CEIL = 0.05

# #712 step-level ladder credit — the two step-boundary credit kinds that
# ride the #705 credit_kind column. "step" is an admissible DENSE
# observation (folds exactly like solve credit: (c, 1-c) — provisional
# mass that moves per SubagentStop, the fix for the 10-step-rollout-
# one-signal defect). "step_calibration" is the claim-terminal residual
# row carrying SIGNED mass deltas (credit = Δsuccess = ladder − Σstep,
# failure_delta = Δfailure): the fold applies both verbatim (no [0,1]
# clamp, no observation band, no Φ tiebreak) and never feeds them to the
# adaptive γ EMA (a residual is bookkeeping, not an outcome regime
# signal — a signed clawback would poison the schedule).
CREDIT_KIND_STEP = "step"
CREDIT_KIND_STEP_CALIBRATION = "step_calibration"
#: a ledger correction rides the SAME signed-delta semantics as
#: the step-residual semantics — the two kinds share one definition so the fold,
#: the EMA exclusion, the append boundary and the mass read cannot drift.
CREDIT_KIND_CREDIT_AMENDMENT = "credit_amendment"
SIGNED_CREDIT_KINDS = (CREDIT_KIND_STEP_CALIBRATION,
                       CREDIT_KIND_CREDIT_AMENDMENT)



from _common import seq_sum as _seq_sum  # noqa: E402 — the canonical leaf (the per-module redeclaration is retired)


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
    """The default day-one store: the consolidated runs/experience.jsonl
    (#721) with the legacy runs/q-cell-log.jsonl riding the compat
    window. The stamp filter keeps the file's other schemas out — only
    q-cell-obs rows ever enter the fold."""

    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / OBS_REL  # legacy rel (kept for callers)

    def observations(self) -> list[dict]:
        return _cl.read(self.root, "experience",
                        schema_prefix="q-cell-obs")


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

        #545 keyed consumption: cells are keyed by the 4-dim arm_key
        (family|recipe|verif|tier) since WS1's dual-write, so the family
        aggregate pools every cell whose key's FAMILY PART matches
        (``family_of_action``) — legacy family-keyed cells match
        directly. Consumers that read by family (termination.alive,
        the anchor) are family-addressed, never key-addressed.

        numpy adoption (issue 420 Phase 2, README rule 1): the mass
        accumulation runs through _seq_sum — cell insertion order,
        bit-identical to the former += loop and interpreter-stable
        (builtin sum() went Neumaier in 3.12)."""
        cells = [(cell.success, cell.failure)
                 for (_sig, key), cell in self.cells.items()
                 if family_of_action(key) == family]
        return (_seq_sum([s for s, _ in cells]),
                _seq_sum([f for _, f in cells]))


def _credit_of(row: dict):
    c = row.get("credit")
    if isinstance(c, bool) or not isinstance(c, (int, float)):
        return None
    return float(c)


def _phi_delta_of(row: dict) -> float:
    """The row's Φ movement (the #548 tiebreaker raw material); absent or
    non-numeric fields fail open to 0.0 (the bit-identity wall)."""
    pd = row.get("phi_delta")
    if isinstance(pd, bool) or not isinstance(pd, (int, float)):
        return 0.0
    return float(pd)


def _failure_delta_of(row: dict) -> float:
    """A #712 calibration row's signed Δfailure mass; absent or
    non-numeric -> 0.0 (success-only residual, fail-open)."""
    fd = row.get("failure_delta")
    if isinstance(fd, bool) or not isinstance(fd, (int, float)):
        return 0.0
    return float(fd)


def _admits_to_posterior(row: dict) -> bool:
    """#705 agent-level credit: verification credit CONFIRMS existing
    knowledge — it is recorded (the audit trail) but is inadmissible to
    the Beta posterior (success, failure AND n_pending). Absent or any
    other credit_kind is the solve path (bit-identical to pre-#705)."""
    return str(row.get("credit_kind") or "solve") != "verification"


def tiebroken_credit(credit: float, phi_delta) -> float:
    """The #548 tiebreaker on the credit read: clamp01(credit +
    PHI_TIEBREAK_WEIGHT · phi_delta). phi_delta=0/None is bit-identical
    to the raw credit (the branch makes the wall auditable)."""
    credit = max(0.0, min(1.0, float(credit)))
    pd = phi_delta if isinstance(phi_delta, (int, float)) \
        and not isinstance(phi_delta, bool) else 0.0
    if pd == 0.0:
        return credit
    return max(0.0, min(1.0, credit + PHI_TIEBREAK_WEIGHT * float(pd)))


def family_of_action(action_key: str) -> str:
    """The FAMILY part of a consumed action key: the 4-dim arm_key's
    first segment, or the key itself for legacy family-keyed rows (the
    dual-write tolerance — #539 WS1 recorded the key, #545 consumes it)."""
    k = str(action_key or "")
    return k.split("|", 1)[0] if "|" in k else k


def _action_key_of(row: dict) -> str:
    """The row's consumption key: the arm_key column when present, else
    the bare method_family (old logs keep folding exactly as before)."""
    ak = str(row.get("arm_key") or "").strip()
    return ak or str(row.get("method_family") or "")


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
    posterior mass.

    #545 keyed consumption: rows group by the 4-dim arm_key
    (family|recipe|verif|tier — dual-written since WS1); rows without an
    arm_key fall back to the bare method_family, so old logs fold
    exactly as before (the dual-write tolerance). The read face stays
    family-addressed through ``family_of_action`` /
    ``Fold.family_mass``.

    #548 tiebreaker: a row's effective credit runs through
    ``tiebroken_credit`` — PHI_TIEBREAK_WEIGHT · phi_delta before the
    [0,1] clamp; rows without phi_delta are bit-identical to the
    pre-change fold.

    issue-678 D-678.4a (TRACE observation band): a SETTLED credit in
    (0, OBSERVATION_BAND_CEIL] adds no cell mass — success and failure
    stay put (the information option is an observation, never a
    verdict); a genuine 0.0 still trains failure. The band keys on the
    raw settled credit; the tiebreaker only refines admissible rows.

    #705 agent-level credit: rows carrying
    ``credit_kind: "verification"`` are inadmissible — they contribute
    to neither success, failure, nor n_pending (verification confirms
    knowledge, it never produces it). Absent credit_kind is the solve
    path, bit-identical.

    #712 step-level credit: ``credit_kind: "step"`` rows are admissible
    dense observations (folded exactly like solve credit — (c, 1-c) per
    SubagentStop); ``credit_kind: "step_calibration"`` rows are the
    claim-terminal residual — signed Δsuccess (row ``credit``) and
    Δfailure (row ``failure_delta``) applied verbatim after the γ weight,
    outside the band and the tiebreak, and excluded from the γ EMA."""
    schedule = _resolve_schedule(gamma)
    rows = [r for r in store.observations()
            if isinstance(r, dict) and _credit_of(r) is not None
            and _admits_to_posterior(r)]
    n = len(rows)
    gammas = [0.0] * n
    for i, row in enumerate(rows):
        gammas[i] = schedule.gamma()
        # #712: a step_calibration residual occupies a stream position
        # (it takes this row's γ weight) but is NOT an outcome — it
        # never feeds the adaptive EMA (a signed clawback would drag the
        # schedule's γ off its declared range).
        if str(row.get("credit_kind") or "") not in SIGNED_CREDIT_KINDS:
            schedule.observe(_credit_of(row))
    weights = [1.0] * n
    w = 1.0
    for i in range(n - 2, -1, -1):
        w *= gammas[i + 1]
        weights[i] = w
    cells: dict[tuple[str, str], CellCounts] = {}
    for i, row in enumerate(rows):
        raw_credit = _credit_of(row)
        weight = weights[i]
        key = (str(row.get("signature_hash") or ""),
               _action_key_of(row))
        cell = cells.get(key)
        if cell is None:
            cell = CellCounts(key[0], key[1])
            cells[key] = cell
        if str(row.get("credit_kind") or "") in SIGNED_CREDIT_KINDS:
            # #712 signed mass deltas: the claim-terminal residual adds
            # Δsuccess/Δfailure VERBATIM (both may be negative — the
            # clawback face), so the cumulative mass lands on the
            # step-less endpoint. No band, no tiebreak, no clamp: a
            # residual is bookkeeping over what the steps banked.
            cells[key] = CellCounts(
                key[0], key[1],
                success=cell.success + weight * raw_credit,
                failure=cell.failure + weight * _failure_delta_of(row),
                n_pending=cell.n_pending)
            continue
        if 0.0 < raw_credit <= OBSERVATION_BAND_CEIL:
            # issue-678 D-678.4a: the TRACE information option is an
            # OBSERVATION, not a verdict — the cell records the row's
            # existence (zero mass) and the schedule/decay chain above
            # already consumed it; the band keys on the SETTLED credit,
            # never the tiebroken one (phi_delta refines admissible
            # rows, it never promotes an information option)
            continue
        credit = tiebroken_credit(raw_credit, row.get("phi_delta"))
        cells[key] = CellCounts(
            key[0], key[1],
            success=cell.success + weight * credit,
            failure=cell.failure + weight * (1.0 - credit),
            n_pending=cell.n_pending)
    for row in store.observations():
        if not isinstance(row, dict) or _credit_of(row) is not None:
            continue
        if not _admits_to_posterior(row):
            continue          # #705: verification rows are never pending
        key = (str(row.get("signature_hash") or ""),
               _action_key_of(row))
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
                   feature_pool=None, warm_pool=None,
                   arm_key: str | None = None,
                   negative_pool=None) -> tuple[float, float]:
    """The SHRUNK Beta posterior used for sampling — (alpha, beta).

    Anchor = the family's global aggregate LEAVE-ONE-OUT (this cell's
    own counts excluded — a family observed only here has an empty
    anchor and stands on its local evidence alone, no self-echo). A
    nowhere-observed family yields the wide Beta(1,1) prior.

    ``arm_key`` (#545 keyed consumption): address the cell at the 4-dim
    action key (family|recipe|verif|tier). The legacy cell at the bare
    family key (old logs — the dual-write tolerance) POOLS into the
    local mass, and the leave-one-out anchor subtracts BOTH, so a
    key-addressed read never self-echoes its own family-grain history.

    #705 MARL: a 5-dim agent-conditioned key (…|agent) reads its OWN
    cell as local mass and does NOT pool the same-arm 4-dim cell into
    local — every peer's mass (other agents, the untyped pool) stays in
    the leave-one-out anchor, so knowledge transfers through the
    warm-start prior, never through forced pooling. The anchor is
    family_aggregate − local, so a cold agent cell inherits its peers
    by construction.

    ``negative_pool`` (#705, class-level dead ends): a duck-typed pool
    whose FAILURE mass is added to the anchor face under the SAME single
    SHRINK_CAP as every other anchor source. The guaranteed effect is a
    HIGHER β — the borrowed anchor is a failure pseudo-count, never a
    deletion — but the mean does NOT always fall: the anchor's own mean
    is (BASE_ALPHA + s_anchor)/(BASE_ALPHA + BASE_BETA + n_anchor), so a
    cell whose failures already sit below that mean can see a slight
    lift. Absent/None is bit-identical to the pre-change kernel.

    ``feature_pool`` (#460 Part B, predict-before-try) and ``warm_pool``
    (#545, the cross-task posterior store) are optional duck-typed
    pools (``.success``/``.failure``/``.rows`` — FeaturePool shape):
    their masses are added to the anchor masses BEFORE the single
    SHRINK_CAP, so the family/global pool stays the base borrow and
    total borrowed pseudo-observations never exceed the cap. None
    (default) or a zero-mass pool is bit-identical to the pre-change
    kernel — the determinism wall. The feature face pools every table
    row; the replay passes exclude_run by explicit run id
    (leave-instance-out is the replay's split, not a live-face filter)."""
    cell = fold_view.cells.get(
        (signature_hash, arm_key or family),
        CellCounts(signature_hash, family))
    s_local, f_local = cell.success, cell.failure
    # #539/#545 legacy tolerance: a 4-dim key pools the bare family cell
    # into local (and the leave-one-out anchor subtracts both). A 5-dim
    # agent key skips this — the same-arm mass stays ANCHOR (prior),
    # never this agent's own evidence.
    if arm_key and arm_key != family and not _is_agent_key(arm_key):
        legacy = fold_view.cells.get((signature_hash, family))
        if legacy is not None:
            s_local += legacy.success
            f_local += legacy.failure
    fam_s, fam_f = fold_view.family_mass(family)
    s_anchor = max(fam_s - s_local, 0.0)
    f_anchor = max(fam_f - f_local, 0.0)
    if feature_pool is not None:
        s_anchor += float(feature_pool.success)
        f_anchor += float(feature_pool.failure)
    if warm_pool is not None:
        s_anchor += float(warm_pool.success)
        f_anchor += float(warm_pool.failure)
    if negative_pool is not None:
        s_anchor += float(negative_pool.success)
        f_anchor += float(negative_pool.failure)
    n_anchor = s_anchor + f_anchor
    if n_anchor <= 0.0:
        return (BASE_ALPHA + s_local, BASE_BETA + f_local)
    m = (BASE_ALPHA + s_anchor) / (
        BASE_ALPHA + BASE_BETA + n_anchor)
    w = min(SHRINK_CAP, n_anchor)
    return (BASE_ALPHA + w * m + s_local,
            BASE_BETA + w * (1.0 - m) + f_local)


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
                         death: Mapping | None = None,
                         warm_pools: Mapping | None = None,
                         arm_context: Mapping | None = None,
                         negative_pools: Mapping | None = None) -> dict:
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
    fail open to 1.0 (never delete, never amplify).

    #545 warm start: ``warm_pools`` is the cross-task posterior store's
    per-candidate anchor pools ({family → duck-typed pool}); their
    LAMBDA-tempered masses ride the SAME anchor face as the feature
    pools (never a local-cell write), and candidates with contributing
    rows carry an additive ``posterior_store`` receipt block — the warm
    start is traceable, 逐句可归因. ``arm_context`` (recipe/verif/tier —
    the dispatch meta) keys the per-candidate cell read at the 4-dim
    arm_key; candidates carry an additive ``arm_key`` receipt field.
    Both None (default) = the pre-#545 sampler, byte-identical.

    #705 MARL: ``arm_context`` may carry an ``agent_type`` (the 5th arm
    key dim) so each worker type samples from its OWN cell, and
    ``negative_pools`` ({family → duck-typed pool} of CLASS-LEVEL dead
    ends, rlvr.marl.negative_pools) adds failure mass to the anchor
    face under the same SHRINK_CAP — candidates with contributing
    negative rows carry an additive ``negative_knowledge`` receipt
    block. Both absent = the pre-#705 sampler, byte-identical."""
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
        ak = None
        if arm_context is not None:
            ak = arm_key(family,
                         str(arm_context.get("context_recipe")
                             or "facts_snapshot"),
                         str(arm_context.get("verification_mode")
                             or "none"),
                         arm_context.get("tier", 0),
                         arm_context.get("agent_type"))
        warm = (warm_pools or {}).get(family)
        neg = (negative_pools or {}).get(family)
        alpha, beta = cell_posterior(
            fold_view, sig, family,
            feature_pool=pools.get(family) if pools else None,
            warm_pool=warm, arm_key=ak, negative_pool=neg)
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
        if ak is not None:
            # additive field — no arm_context, no field (byte identity)
            cand["arm_key"] = ak
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
        if warm is not None and warm.rows > 0:
            # additive block — the warm start is traceable to its rows
            cand["posterior_store"] = {
                "success": round(warm.success, 9),
                "failure": round(warm.failure, 9),
                "rows": warm.rows,
            }
        if neg is not None and neg.rows > 0:
            # additive block — #705 class-level dead end, traceable
            cand["negative_knowledge"] = {
                "success": round(neg.success, 9),
                "failure": round(neg.failure, 9),
                "rows": neg.rows,
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


def arm_key(method_family: str, context_recipe: str,
            verification_mode: str, tier, agent_type: str | None = None
            ) -> str:
    """#539 WS1: the 4-dim arm key (family|recipe|verif|tier) — the
    anti-explosion compromise: tool_sequence/budget/control ride as
    feature columns, never as key dimensions. Tier buckets to int.

    #705 MARL: a NON-EMPTY ``agent_type`` appends a fifth segment
    (family|recipe|verif|tier|agent) so each worker type addresses its
    OWN Beta cell. A falsy agent type produces the exact pre-#705
    4-dim string — the determinism wall (test_action_space_539 pins it;
    every golden that pins an arm key stays byte-identical)."""
    try:
        t = int(tier)
    except (TypeError, ValueError):
        t = 0
    base = f"{method_family}|{context_recipe}|{verification_mode}|{t}"
    agent = str(agent_type).strip() if agent_type is not None else ""
    return f"{base}|{agent}" if agent else base


def agent_of_action(action_key: str) -> str | None:
    """#705 MARL: the AGENT part of a consumed action key — the fifth
    segment of a 5-dim key, or None for a legacy 4-dim/family key."""
    parts = str(action_key or "").split("|")
    return parts[4] if len(parts) >= 5 and parts[4] else None


def _is_agent_key(action_key: str) -> bool:
    """True for a 5-dim agent-conditioned key (the #705 local-mass
    carve-out: a 5-dim read never pools a same-arm 4-dim cell into
    local — sharing rides the anchor, never forced pooling)."""
    return len(str(action_key or "").split("|")) >= 5


def _recipe_cols(recipe_id, recipe_propensity,
                 recipe_source) -> tuple[str | None, float | None,
                                         str | None]:
    """#695 boundary validation for the recipe triple — non-string ids,
    NaN / out-of-[0,1] propensities and foreign sources degrade to null
    with one warn each, never a raise (the #691 usage-row boundary
    semantics)."""
    rid_out, rprop_out, rsrc_out = None, None, None
    if isinstance(recipe_id, str) and recipe_id.strip():
        rid_out = recipe_id.strip()
    elif recipe_id is not None:
        warn("q_cells.append", f"non-string recipe_id dropped: {recipe_id!r}")
    if recipe_propensity is not None:
        if isinstance(recipe_propensity, bool) \
                or not isinstance(recipe_propensity, (int, float)):
            warn("q_cells.append",
                 f"non-numeric recipe_propensity dropped: "
                 f"{recipe_propensity!r}")
        else:
            v = float(recipe_propensity)
            if v == v and 0.0 <= v <= 1.0:   # finite + in-range (NaN fails)
                rprop_out = round(v, 6)
            else:
                warn("q_cells.append",
                     f"out-of-range recipe_propensity dropped: "
                     f"{recipe_propensity!r}")
    if recipe_source is not None:
        s = str(recipe_source).strip()
        if s in ("sampled", "declared", "none"):
            rsrc_out = s
        else:
            warn("q_cells.append",
                 f"foreign recipe_source dropped: {recipe_source!r}")
    return rid_out, rprop_out, rsrc_out
def _coerce_credit(credit, credit_kind, failure_delta):
    """The append boundary's #712 credit validation: verdict credits
    clamp into [0,1] (the #429 §4 rail — the boundary never trusts
    input), a "step_calibration" credit is taken SIGNED with finite-only
    validation (the clawback's job is to be negative), and
    failure_delta is legal ONLY on a calibration row (ONE warn, else
    dropped). Returns ``(credit, failure_delta)``; invalid input drops
    to None."""
    is_calibration = str(credit_kind or "") in SIGNED_CREDIT_KINDS
    credit_out = None
    if credit is not None:
        if isinstance(credit, bool) or not isinstance(credit, (int, float)):
            warn("q_cells.append", f"non-numeric credit dropped: {credit!r}")
        elif is_calibration:
            if not math.isfinite(float(credit)):
                warn("q_cells.append",
                     f"non-finite calibration credit dropped: {credit!r}")
            else:
                credit_out = float(credit)
        else:
            credit_out = max(0.0, min(1.0, float(credit)))
    failure_delta_out = None
    if failure_delta is not None:
        if not is_calibration:
            warn("q_cells.append",
                 "failure_delta outside a calibration row dropped")
        elif isinstance(failure_delta, bool) or not isinstance(
                failure_delta, (int, float)):
            warn("q_cells.append",
                 f"non-numeric failure_delta dropped: {failure_delta!r}")
        elif not math.isfinite(float(failure_delta)):
            warn("q_cells.append",
                 f"non-finite failure_delta dropped: {failure_delta!r}")
        else:
            failure_delta_out = float(failure_delta)
    return credit_out, failure_delta_out


def append_observation(ws, signature_hash: str, method_family: str,
                       credit: float | None = None, *, source: str,
                       claim: str | None = None,
                       agent: str | None = None,
                       dispatch_id: str | None = None,
                       ts: str | None = None,
                       fingerprint: str | None = None,
                       arm_key_col: str | None = None,
                       action_type: str | None = None,
                       phi_delta: float | None = None,
                       credit_kind: str | None = None,
                       recipe_id: str | None = None,
                       recipe_propensity: float | None = None,
                       recipe_source: str | None = None,
                       failure_delta: float | None = None,
                       reason: str | None = None) -> dict:
    """Append one observation row (the data spine). Credit clamps into
    [0,1] at this boundary (r_r is rail-clamped per #429 §4; the clamping
    belongs to the caller's rails but the boundary never trusts input).
    Fail-open: an unwritable log is one rate-limited warn, never an
    exception into the producer.

    #705 agent-level credit: ``credit_kind`` ("solve" | "verification")
    rides the row so the fold can apply the admission rule. Absent or
    "solve" is the pre-#705 path (the row carries no kind column).

    #695 recipe arms: the dispatch-time recipe triple rides the row as
    ``recipe_id`` / ``recipe_propensity`` / ``recipe_source`` (closed
    vocab sampled|declared|none). The three keys are emitted TOGETHER
    (explicit nulls inside) and ONLY when the view carries a recipe —
    every pre-#695 writer (``observe()``, the reindex faces) stays
    byte-identical. The boundary validates: non-string ids, NaN /
    out-of-[0,1] propensities and foreign sources degrade to null with
    one warn, never a raise.

    #712 step-level credit: a ``credit_kind`` of "step" keeps the normal
    [0,1] clamp (a dense step credit is still a bounded observation);
    "step_calibration" takes the credit SIGNED (the claim-terminal
    residual claws back mass — negative is its job) with finite-only
    validation, and may carry ``failure_delta`` (the signed Δfailure the
    fold applies verbatim). failure_delta outside a calibration row is
    dropped with ONE warn — the column has exactly one legal home."""
    credit_out, failure_delta_out = _coerce_credit(
        credit, credit_kind, failure_delta)
    phi_out = None
    if phi_delta is not None:
        if isinstance(phi_delta, bool) or not isinstance(phi_delta,
                                                         (int, float)):
            warn("q_cells.append",
                 f"non-numeric phi_delta dropped: {phi_delta!r}")
        else:
            phi_out = round(float(phi_delta), 6)
    rid_out, rprop_out, rsrc_out = _recipe_cols(
        recipe_id, recipe_propensity, recipe_source)
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
        # #539 WS1 dual-write: the 4-dim arm key + the policy's action
        # type. #545 WS2: the fold consumes the arm_key (family fallback
        # for old logs) and the phi_delta tiebreaker rides the credit
        # read (consumption-only — the row field is one optional column).
        "arm_key": arm_key_col,
        "action_type": action_type,
        "phi_delta": phi_out,
    }
    # #705 agent-level credit: the column is emitted ONLY for
    # "verification" — the solve path's row stays byte-identical to
    # pre-#705 (no key at all, not even a null).
    if credit_kind:
        row["credit_kind"] = str(credit_kind)
    # #695: the recipe triple rides TOGETHER, only when the view names
    # a recipe (the none-gap row — no recipe_id — stays byte-identical
    # to pre-#695; review-1: source "none" must NOT trip the gate).
    if rid_out is not None:
        row["recipe_id"] = rid_out
        row["recipe_propensity"] = rprop_out
        row["recipe_source"] = rsrc_out
    # #712: the signed Δfailure rides only a calibration row (the guard
    # above already refused every other home).
    if failure_delta_out is not None:
        row["failure_delta"] = failure_delta_out
    # the amendment audit reason — emitted ONLY when set (the
    # the established emission discipline: absent = byte-identical row).
    if reason:
        row["reason"] = str(reason)
    appended = _cl.append(ws, "experience", row)
    return {"appended": appended, "row": row}


def observe(ws, signature_hash: str, method_family: str,
            credit: float) -> dict:
    """The settlement feed: one (signature_hash, method_family, credit)
    observation — the observation interface as DATA (the W2-T4
    settlement wiring calls this from settled round_credit rows)."""
    return append_observation(ws, signature_hash, method_family, credit,
                              source="settlement")


def _match_pending_dispatch(ws, dispatch_id: str) -> dict | None:
    """The LATEST pending dispatch row carrying this identity (claim id
    or explicit dispatch_id) — the ONE match face shared by the #462 W5
    settlement bank, the #712 step-credit bank and its claim-terminal
    calibration. Pending means source=dispatch + credit=None (banked rows
    carry a numeric credit and can never be re-matched). None = the
    honest gap — no row, never a fabricated bucket."""
    did = str(dispatch_id or "")
    for row in reversed(JSONLQStore(ws).observations()):
        if not isinstance(row, dict) \
                or str(row.get("source") or "") != "dispatch" \
                or row.get("credit") is not None:
            continue
        if did and (str(row.get("claim") or "") == did
                    or str(row.get("dispatch_id") or "") == did):
            return row
    return None


def observe_settlement(ws, dispatch_id: str, credit,
                       *, phi_delta: float | None = None,
                       credit_kind: str = "solve") -> dict:
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
    named v1 limitation. The credit arriving here is the settled #433
    ladder value (verified = admission
    ticket, cited-toward-stage = value — the ladder ran upstream in
    scalar.round_credit); the append boundary clamps it into [0, 1]
    (r_r is rail-clamped per #429 §4). No matching dispatch row is the
    honest gap: no row, never a fabricated bucket. Fail-open: telemetry
    never breaks settlement.

    #545: the matched dispatch row's ``arm_key`` rides the settlement
    row (keyed consumption — the banked credit lands in the arm cell
    the dispatch opened, family fallback for legacy rows) and
    ``phi_delta`` threads to the row (the #548 tiebreaker raw
    material). The result carries ``arm_key``/``fingerprint`` so the
    cross-task store's write face (rlvr.strategy_store) can key its row
    without a second scan.

    #705 agent-level credit: ``credit_kind`` decomposes the settlement
    into "solve" (produced new evidence — the DEFAULT, bit-identical to
    the pre-#705 path) and "verification" (confirmed existing knowledge
    — the row is still recorded for the audit trail but the fold marks
    it inadmissible, so the Beta posterior never moves). The result
    carries ``beta_updated: bool`` reporting the decomposition.

    #695 recipe arms: the matched dispatch row's recipe triple
    (``recipe_id``/``recipe_propensity``/``recipe_source``) rides the
    settlement row and the result — the credit banks against the
    DISPATCH-RECORDED recipe (ITT via the #678 trusted chain); no
    worker narrative is ever read here (the #881 ``steps:`` pattern
    stays dead)."""
    did = str(dispatch_id or "")
    kind = "verification" if str(credit_kind or "").strip() == \
        "verification" else "solve"
    try:
        match = _match_pending_dispatch(ws, did)
        if match is None:
            warn("q_cells.observe_settlement",
                 f"no pending dispatch row for {did!r} — credit not "
                 f"banked (the honest gap)")
            return {"appended": False, "matched": False,
                    "reason": "unmatched", "dispatch_id": did,
                    "credit_kind": kind, "beta_updated": False}
        out = append_observation(ws, str(match.get("signature_hash")),
                                 str(match.get("method_family")), credit,
                                 source="settlement",
                                 claim=match.get("claim"),
                                 agent=match.get("agent"),
                                 dispatch_id=did,
                                 fingerprint=match.get("fingerprint"),
                                 arm_key_col=match.get("arm_key"),
                                 phi_delta=phi_delta,
                                 # the solve path emits NO kind column —
                                 # the default row stays byte-identical
                                 # to pre-#705; only verification marks.
                                 credit_kind=(kind if kind == "verification"
                                              else None),
                                 # #695: credit banks against the
                                 # DISPATCH-RECORDED recipe (ITT) —
                                 # the triple rides the settlement row
                                 recipe_id=match.get("recipe_id"),
                                 recipe_propensity=match.get(
                                     "recipe_propensity"),
                                 recipe_source=match.get("recipe_source"))
        return {"appended": out["appended"], "matched": True,
                "reason": None if out["appended"] else "write-failed",
                "dispatch_id": did,
                "credit_kind": kind,
                "beta_updated": bool(out["appended"] and kind == "solve"),
                "signature_hash": match.get("signature_hash"),
                "method_family": match.get("method_family"),
                "arm_key": match.get("arm_key"),
                "fingerprint": match.get("fingerprint"),
                "recipe_id": match.get("recipe_id"),
                "recipe_propensity": match.get("recipe_propensity"),
                "recipe_source": match.get("recipe_source")}
    except Exception as exc:  # noqa: BLE001 — telemetry, never the producer
        warn("q_cells.observe_settlement", f"{type(exc).__name__}: {exc}")
        return {"appended": False, "matched": False,
                "reason": f"error:{type(exc).__name__}",
                "dispatch_id": did,
                "credit_kind": kind, "beta_updated": False}


def _bank_matched(ws, did: str, match: dict, credit, *,
                  kind: str, failure_delta: float | None = None,
                  reason: str | None = None) -> dict:
    """Append one credit row into the matched dispatch's cell and shape
    the shared result dict (the #712 faces' common tail: same keys
    observe_settlement returns, so callers — strategy store, case-
    posterior leg — read one shape). ``reason`` rides the row only when
    set (the amendment audit face)."""
    out = append_observation(ws, str(match.get("signature_hash")),
                             str(match.get("method_family")), credit,
                             source=("credit-amendment"
                                     if kind == CREDIT_KIND_CREDIT_AMENDMENT
                                     else "settlement"),
                             claim=match.get("claim"),
                             agent=match.get("agent"),
                             dispatch_id=did,
                             fingerprint=match.get("fingerprint"),
                             arm_key_col=match.get("arm_key"),
                             credit_kind=kind,
                             failure_delta=failure_delta,
                             reason=reason)
    return {"appended": out["appended"], "matched": True,
            "reason": None if out["appended"] else "write-failed",
            "dispatch_id": did,
            "credit_kind": kind,
            "beta_updated": bool(out["appended"]),
            "signature_hash": match.get("signature_hash"),
            "method_family": match.get("method_family"),
            "arm_key": match.get("arm_key"),
            "fingerprint": match.get("fingerprint")}


def _match_banked_row(ws, dispatch_id: str) -> dict | None:
    """The LATEST banked row (settlement or amendment source)
    carrying this identity — the prune-safe identity fallback. A
    pruned dispatch row never orphans a correction: the banked row's
    own signature/method_family/arm_key ARE the cell address."""
    did = str(dispatch_id or "")
    for row in reversed(JSONLQStore(ws).observations()):
        if not isinstance(row, dict):
            continue
        if str(row.get("source") or "") not in ("settlement",
                                                "credit-amendment"):
            continue
        if row.get("credit") is None:
            continue
        if did and (str(row.get("claim") or "") == did
                    or str(row.get("dispatch_id") or "") == did):
            return row
    return None


def banked_mass(ws, dispatch_id: str) -> tuple[float, float, int] | None:
    """(success, failure, n_rows) — the fold has banked the fold has banked for this
    identity — the amendment's operand, read from the SAME append-only
    log the fold consumes (the residual posture: what actually banked, never a
    parallel tally that could drift). Solve rows contribute their
    tiebroken credit (a band-valued row is the information option:
    zero mass, existence only); verification rows are inadmissible to
    the posterior (the fold skips them — so does this read); signed
    kinds contribute verbatim; step rows are NOT included
    (``step_credit_totals`` owns that leg — sum them at the call
    site). **None = the log could not be read** — callers must treat
    None as "skip this pass" (an empty read and an unreadable read are
    different facts; conflating them would fire a full-target
    over-amendment)."""
    did = str(dispatch_id or "")
    s = f = 0.0
    n = 0
    try:
        for row in JSONLQStore(ws).observations():
            if not isinstance(row, dict):
                continue
            if str(row.get("source") or "") not in ("settlement",
                                                    "credit-amendment"):
                continue
            if not (did and (str(row.get("claim") or "") == did
                             or str(row.get("dispatch_id") or "") == did)):
                continue
            c = _credit_of(row)
            if c is None:
                continue
            if str(row.get("credit_kind") or "") == CREDIT_KIND_STEP:
                continue          # step mass: step_credit_totals owns it
            if not _admits_to_posterior(row):
                continue          # verification: never banked, never read
            n += 1
            if str(row.get("credit_kind") or "") in SIGNED_CREDIT_KINDS:
                s += c
                f += _failure_delta_of(row)
                continue
            if 0.0 < c <= OBSERVATION_BAND_CEIL:
                continue          # the information option — no mass
            t = tiebroken_credit(c, row.get("phi_delta"))
            s += t
            f += 1.0 - t
    except Exception as exc:  # noqa: BLE001 — telemetry, never the settle
        warn("q_cells.banked_mass", f"{type(exc).__name__}: {exc}")
        return None
    return round(s, 6), round(f, 6), n


def _mass_targets(credit) -> tuple[float, float]:
    """The band-aware mass endpoint of one ladder value (the step-residual
    target half, single-sourced for the amendment face): clamp01, and a
    band-valued value is the information option — (0, 0). Both halves
    are rounded to 6 dp — the SAME grid the banked read and the delta
    rounding live on; an unrounded target could sit on a 6-dp half
    point and the delta would oscillate ±1e-6 forever (the review's
    non-idempotence finding)."""
    settled = round(max(0.0, min(1.0, float(credit))), 6)
    if 0.0 < settled <= OBSERVATION_BAND_CEIL:
        return 0.0, 0.0
    return settled, round(1.0 - settled, 6)


def amend_settlement(ws, dispatch_id: str, target_credit,
                     *, reason: str | None = None) -> dict:
    """The ledger-correction face — move a dispatch's banked mass
    to the corrected ladder value with ONE signed ``credit_amendment``
    row (same verbatim semantics as the residual semantics; rows carry
    ``source: "credit-amendment"`` so settlement-keyed ad-hoc readers —
    the e2e repeat-failure feed, the proposal priors — stay blind).

    The operand is the fold's full mass view (``banked_mass`` +
    ``step_credit_totals``); the delta is rounded to 6 dp and a
    zero-rounded delta appends NOTHING — idempotent by construction, a
    re-run converges because the amendment row itself enters the next
    read. Identity, strongest-first: the pending dispatch row (the
    pending-dispatch face), else the latest banked row's own signature (a pruned
    dispatch row never orphans a correction); neither → the honest
    gap. Fail-open: telemetry never breaks settlement."""
    did = str(dispatch_id or "")
    kind = CREDIT_KIND_CREDIT_AMENDMENT
    try:
        t_s, t_f = _mass_targets(target_credit)
        step_sum, step_n = step_credit_totals(ws, did)
        mass = banked_mass(ws, did)
        if mass is None:
            return {"appended": False, "matched": False,
                    "reason": "log-unreadable", "dispatch_id": did,
                    "credit_kind": kind, "beta_updated": False}
        s_eff, f_eff, _n = mass
        s_eff += step_sum
        f_eff += float(step_n) - step_sum
        d_s = round(t_s - s_eff, 6)
        d_f = round(t_f - f_eff, 6)
        if d_s == 0.0 and d_f == 0.0:
            return {"appended": False, "matched": True,
                    "reason": "already-current", "dispatch_id": did,
                    "credit_kind": kind, "beta_updated": False}
        match = _match_pending_dispatch(ws, did) \
            or _match_banked_row(ws, did)
        if match is None:
            warn("q_cells.amend_settlement",
                 f"no row carries {did!r} — amendment not banked (the "
                 f"honest gap)")
            return {"appended": False, "matched": False,
                    "reason": "unmatched", "dispatch_id": did,
                    "credit_kind": kind, "beta_updated": False}
        return _bank_matched(ws, did, match, d_s, kind=kind,
                             failure_delta=d_f, reason=reason)
    except Exception as exc:  # noqa: BLE001 — telemetry, never the producer
        warn("q_cells.amend_settlement", f"{type(exc).__name__}: {exc}")
        return {"appended": False, "matched": False,
                "reason": f"error:{type(exc).__name__}",
                "dispatch_id": did,
                "credit_kind": kind, "beta_updated": False}


def observe_step_credit(ws, dispatch_id: str, credit, *,
                        step_ref: str | None = None) -> dict:
    """#712: bank ONE step-boundary credit — the dense signal that moves
    the Q-cell Beta at SubagentStop, BEFORE claim-terminal.

    Matches the claim's pending dispatch row through the shared face
    (the honest gap when none exists) and appends a settlement-source
    row marked ``credit_kind: "step"``: the fold admits it exactly like
    solve credit ((c, 1−c) per step), and the claim-terminal calibration
    sums exactly these rows (``step_credit_totals``) to price its
    residual. The credit here is rlvr.step_credit's evidence-quality
    score (already in [0,1]); ``step_ref`` (the producing step_record/2
    step_id) rides only the returned receipt — the append-only log stays
    one optional column richer per kind, never content-bearing.
    Fail-open: telemetry never breaks the settle that called it."""
    did = str(dispatch_id or "")
    kind = CREDIT_KIND_STEP
    try:
        match = _match_pending_dispatch(ws, did)
        if match is None:
            warn("q_cells.observe_step_credit",
                 f"no pending dispatch row for {did!r} — step credit not "
                 f"banked (the honest gap)")
            return {"appended": False, "matched": False,
                    "reason": "unmatched", "dispatch_id": did,
                    "credit_kind": kind, "beta_updated": False}
        out = _bank_matched(ws, did, match, credit, kind=kind)
        if step_ref:
            out["step_ref"] = str(step_ref)
        return out
    except Exception as exc:  # noqa: BLE001 — telemetry, never the producer
        warn("q_cells.observe_step_credit", f"{type(exc).__name__}: {exc}")
        return {"appended": False, "matched": False,
                "reason": f"error:{type(exc).__name__}",
                "dispatch_id": did,
                "credit_kind": kind, "beta_updated": False}


def observe_step_calibration(ws, dispatch_id: str, credit, *,
                             failure_delta: float = 0.0) -> dict:
    """#712: bank the claim-terminal RESIDUAL — ONE signed mass-delta row
    that corrects the cumulative Beta into the step-less endpoint:
    ``credit`` = Δsuccess = ladder_credit − Σ(step_credit) (negative =
    over-credit clawback, positive = under-credit top-up) and
    ``failure_delta`` = Δfailure so the failure mass also lands on
    (1 − ladder) after the provisional step rows. Claims with no step
    credit never reach this face — scalar._bank_q_cell_credit keeps them
    on observe_settlement (byte-identical legacy rows). Fail-open."""
    did = str(dispatch_id or "")
    kind = CREDIT_KIND_STEP_CALIBRATION
    try:
        match = _match_pending_dispatch(ws, did)
        if match is None:
            warn("q_cells.observe_step_calibration",
                 f"no pending dispatch row for {did!r} — calibration not "
                 f"banked (the honest gap)")
            return {"appended": False, "matched": False,
                    "reason": "unmatched", "dispatch_id": did,
                    "credit_kind": kind, "beta_updated": False}
        return _bank_matched(ws, did, match, credit, kind=kind,
                             failure_delta=failure_delta)
    except Exception as exc:  # noqa: BLE001 — telemetry, never the producer
        warn("q_cells.observe_step_calibration",
             f"{type(exc).__name__}: {exc}")
        return {"appended": False, "matched": False,
                "reason": f"error:{type(exc).__name__}",
                "dispatch_id": did,
                "credit_kind": kind, "beta_updated": False}


def step_credit_totals(ws, dispatch_id: str) -> tuple[float, int]:
    """#712: (Σ credit, n rows) over the step rows whose credit actually
    became FOLD MASS for this identity — the claim-terminal
    calibration's operand, read from the SAME append-only log the fold
    consumes (what actually banked, never a parallel tally that could
    drift). Mirrors the fold's admission EXACTLY: credit == 0.0 is a
    failure observation (mass (0, 1)); credit in
    (0, OBSERVATION_BAND_CEIL] is the D-678.4a information option — NO
    mass, so it counts in NEITHER the sum nor the count (clawing it
    back would subtract mass that was never banked — the #712 review's
    band-interaction finding); above the band a full observation.
    Fail-open: an unreadable log reports (0.0, 0) so the settlement
    takes the legacy face rather than a fabricated correction."""
    did = str(dispatch_id or "")
    total, count = 0.0, 0
    try:
        for row in JSONLQStore(ws).observations():
            if not isinstance(row, dict) \
                    or str(row.get("credit_kind") or "") != CREDIT_KIND_STEP:
                continue
            if not (did and (str(row.get("claim") or "") == did
                             or str(row.get("dispatch_id") or "") == did)):
                continue
            credit = _credit_of(row)
            if credit is None:
                continue
            if 0.0 < credit <= OBSERVATION_BAND_CEIL:
                continue          # information option — zero mass, no operand
            total += credit
            count += 1
    except Exception as exc:  # noqa: BLE001 — telemetry, never the settle
        warn("q_cells.step_credit_totals", f"{type(exc).__name__}: {exc}")
        return 0.0, 0
    return round(total, 6), count


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


#: the #695 recipe-view gap — the honest none (explicit nulls; the
#: dispatch row stays byte-identical to pre-#695 on any miss).
_RECIPE_GAP = {"recipe_id": None, "propensity": None, "source": "none",
               "sampled_recipe": None, "deviates": False,
               "registered": None, "reason": None}


def _recipe_view(ws, family: str, meta: dict, prompt: str | None,
                 agent: str | None, claim: str | None) -> dict:
    """#695: the recipe-arms view at the ALLOW tail (lazy import — the
    decision faces stay import-clean). Fail-open to the none gap with
    one rate-limited warn: a recipe failure never breaks the dispatch
    observation itself."""
    try:
        from rlvr import recipe_arms as _ra695  # noqa: PLC0415 — lazy
        return _ra695.record_dispatch_recipe(
            ws, family=family, envelope_meta=meta, prompt=prompt,
            agent=agent, claim=claim)
    except Exception as exc:  # noqa: BLE001 — telemetry, never the gate
        warn("q_cells.recipe_view", f"{type(exc).__name__}: {exc}")
        return dict(_RECIPE_GAP)


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
    face that makes declaration mandatory). Fail-open throughout.

    #695: the row also carries the recipe triple ({recipe_id,
    recipe_propensity, recipe_source: sampled|declared|none} — see
    rlvr.recipe_arms.record_dispatch_recipe) and the result gains the
    additive ``recipe`` view; the deviation event fires inside the
    recipe face, never here."""
    try:
        family = declared_family(envelope_meta, prompt or "")
        if not family:
            return {"appended": False, "reason": "undeclared",
                    "family": None, "signature_hash": None}
        sig = ssig.signature_hash(ssig.snapshot(ws))
        # #539 WS1: derive the 4-dim arm key from the v2 envelope fields
        # (v1 back-fill defaults keep legacy shapes identical). #705 MARL:
        # an envelope-declared agent_type appends the 5th dim so the
        # dispatch opens the AGENT's own cell.
        meta = envelope_meta if isinstance(envelope_meta, dict) else {}
        recipe = str(meta.get("context_recipe") or "facts_snapshot")
        verif = str(meta.get("verification_mode") or "none")
        tier = meta.get("tier", 0)
        # #695 recipe arms: the dispatch-time recipe view (envelope
        # declaration reconciled against the gate's own arm sampler —
        # rlvr.recipe_arms, fail-open to the none gap on any miss)
        view = _recipe_view(ws, family, meta, prompt, agent, claim)
        out = append_observation(ws, sig, family, None, source="dispatch",
                                 claim=claim, agent=agent,
                                 fingerprint=fingerprint,
                                 arm_key_col=arm_key(family, recipe,
                                                     verif, tier,
                                                     meta.get("agent_type")),
                                 action_type=str(meta.get("action_type")
                                                 or "dispatch"),
                                 recipe_id=view.get("recipe_id"),
                                 recipe_propensity=view.get("propensity"),
                                 recipe_source=view.get("source"))
        return {"appended": out["appended"], "reason": None,
                "family": family, "signature_hash": sig,
                "recipe": view}
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
    for p in (sorted(root.rglob(OBS_REL))
              + sorted(root.rglob(EXPERIENCE_REL))):
        obs_roots.add(p.parent.parent)
        rows = _read_jsonl(p)
        if p.name == Path(EXPERIENCE_REL).name:
            # #721: the consolidated file is multi-schema — only
            # q-cell-obs rows are face-1 rows; the legacy group above
            # precedes this one (archive history predates the file)
            rows = [r for r in rows
                    if str(r.get("schema") or "").startswith("q-cell-obs")]
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
    for (sig, ak) in sorted(set(fold_view.cells) | set(pendings)):
        cell = fold_view.cells.get((sig, ak),
                                   CellCounts(sig, ak))
        entry = {
            "signature_hash": sig,
            "method_family": family_of_action(ak),
            "credit_observations": int(round(
                _weighted_count(cell.success, cell.failure, rep_gamma))),
            "success": round(cell.success, 9),
            "failure": round(cell.failure, 9),
            "pending": cell.n_pending + pendings.get((sig, ak), 0),
        }
        if "|" in ak:  # #545 keyed consumption: the cell's 4-dim key
            entry["arm_key"] = ak
        cells.append(entry)
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
    cells = []
    for c in sorted(fold_view.cells.values(),
                    key=lambda c: (c.signature_hash, c.family)):
        entry = {
            "signature_hash": c.signature_hash,
            "method_family": family_of_action(c.family),
            "success": round(c.success, 9),
            "failure": round(c.failure, 9),
            "pending": c.n_pending,
        }
        if "|" in c.family:
            entry["arm_key"] = c.family
        cells.append(entry)
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
