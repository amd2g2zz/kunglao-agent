# -*- coding: utf-8 -*-
"""posteriors.py — the DTS posterior store (Discounted Thompson Sampling,
issue 428 + 420 P2).

v0.1.6 W2-T1 learned-state core. Replaces the τ temperature-annealing
design (issue 386, retired by issue 428: τ flattening breaks the TS invariant and
the p_min patch was a patch to a broken mechanism) with DTS —
the documented non-stationarity standard (discounted/sliding-window TS
literature). ONE engine: DTS everywhere, day one (owner ruling
2026-09-29: DTS REPLACES TS — there is no plain-TS default and no
activation-pending shim anywhere on this surface). Samples always come
from a GENUINE posterior, only the data behind it is discounted.

Store — the knowledge family file (``knowledge-store.jsonl`` under the
guarded cross-task root, issue-1004 R2c), append-only JSONL,
ledger-isomorphic with ``rlvr/ledger.py``. One row = one Bernoulli
observation of one DTS cell ``(state, arm)``:

    {"schema": "posterior-store/1",
     "state": "<state-signature hash>",   # the Q-table key half
     "arm": "<method-family token>",      # the other half (issue 432 vocabulary;
                                          #  registry enforcement is the
                                          #  dispatch gate's, not the store's
                                          #  — observations are accepted as
                                          #  data, 0 or 1)
     "ts": "...Z",
     "gamma": 0.95,                       # γ in force AT EVENT TIME
     "outcome": 1,
     "alpha_add": 1.0, "beta_add": 0.0}

γ DECAY IS A FOLD/READ-FACE PROPERTY — raw counts are never rewritten.
Replaying the stream in input order through the recurrence

    (α, β) ← γ · (α, β) + obs     (per cell, seeded by pseudo-count priors)

derives the DECAYED posterior; the sampled distribution is a valid
posterior of the discounted data (TS invariant — no p_min, no flattened
draws). γ small = strong forgetting = wide exploration at cold start
(owner: 冷启动偏向更大探索空间); γ → 1 = anneal to balanced exploitation.

γ schedule — outcome-adaptive (owner semantics 1:1): poor recent
outcomes → γ grows slowly (stays near the floor = strong forgetting, so
early misattribution decays out — self-healing against issue 421-residual
noise); improving outcomes → γ → 1. Declared form:

    m ← λ·m + (1-λ)·outcome   (EMA of outcomes, m0 = 0.5)
    γ  = floor + (1-floor)·m  ∈ (0, 1]

Free-parameter discipline: γ_floor and λ are MEASURED, not vibes — the
calibration replay lives in ``experiments/ex2-gamma-calibration.md``
(synthetic drift injected into a posterior bank; tracking error across
constant {0.9, 0.95, 0.98, 0.99, 1.0} + the adaptive schedule) and the
shipped defaults cite those numbers. Prior strength
(PRIOR_ALPHA/BETA_DEFAULT) is the learning-rate knob: how many
observations a cell carries at birth.

Determinism: float sums and the decay recurrence run in input order,
one IEEE multiply + add per element — bit-exact replay is pinned in
tests/test_rlvr_posteriors_428.py. numpy appears only as the in-memory
view's elementwise statistics (np.sum/pairwise reductions NEVER touch
this surface — numpy policy 1, issue 420); no numpy float crosses a
boundary (policy 3) and DTS sampling stays stdlib ``betavariate``
(policy 4). Reads fail open (missing/dirty store → empty, rate-limited
WARN); writes are loud-result dicts, never raises into the producer.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from harness_common import utc_now_z as _utc_now
from kunglao_log import warn

from rlvr import consolidated_ledger as _cl

SCHEMA = "posterior-store/1"

# Pseudo-count priors = the learning-rate knob (prior strength = how many
# observations a newborn cell carries). Beta(1, 1) uniform: every arm is
# equally plausible until data arrives. EX-2 varies prior strength as a
# sensitivity axis; the uniform unit prior stayed optimal on the
# calibrated grid (experiments/ex2-gamma-calibration.md).
PRIOR_ALPHA_DEFAULT = 1.0
PRIOR_BETA_DEFAULT = 1.0

# EX-2 calibration result (experiments/ex2-gamma-calibration.md, declared
# synthetic: 4-arm bank, flip arm 0.8→0.2 at t=300, T=600, 25 seeds —
# experiments/ex2_gamma_calibration.py, bit-anchored to rlvr.posteriors.fold):
# chosen = outcome-adaptive floor=0.8 / EMA λ=0.9.
#   post-flip tracking err 0.181 (const γ=1.0: 0.430 — never heals; const
#   γ=0.9: 0.134 at the price of PERMANENT forgetting + worst-tier pre-flip
#   noise 0.093 ≈ adaptive's 0.095), regret 43.5 (γ=1.0: 69.9), cold-start
#   width 0.167 — 2nd widest of the grid (owner: 冷启动偏向更大探索空间).
# floor=0.9 variants hold γ too close to 1 while wounded (post_err ≈ 0.30).
GAMMA_FLOOR_DEFAULT = 0.8
ADAPTIVE_EMA_LAMBDA_DEFAULT = 0.9


# --- γ schedules (declared forms; EX-2-calibrated constants above) ----------

def _require_gamma(name: str, value) -> float:
    """γ domain wall: numeric, finite, in (0, 1]."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number in (0, 1], got {value!r}")
    g = float(value)
    if math.isnan(g) or math.isinf(g) or not (0.0 < g <= 1.0):
        raise ValueError(f"{name} must be in (0, 1], got {value!r}")
    return g


class _ConstantGamma:
    """γ = c for every observation (the EX-2 calibration grid face)."""

    def __init__(self, gamma: float):
        self.gamma_const = _require_gamma("gamma", gamma)

    @property
    def gamma_floor(self) -> float:  # symmetry with OutcomeAdaptiveGamma
        return self.gamma_const

    ema_lambda = None  # a constant schedule has no EMA

    def gamma(self) -> float:
        return self.gamma_const

    def observe(self, outcome) -> None:  # stateless: nothing to fold in
        return None

    def next_gamma(self, outcome) -> float:
        self.observe(outcome)
        return self.gamma()


class OutcomeAdaptiveGamma:
    """The outcome-adaptive schedule (declared form, see module doc).

    γ is a function of the PAST outcome stream only (no peeking):
    ``γ = floor + (1-floor)·m`` with ``m`` the EMA of outcomes. Poor
    stretch → m falls → γ sits near the floor (strong forgetting, the
    self-heal window); improving → m rises → γ anneals to 1.

    DECLARED v0.1.6 simplification: the EMA observes the outcome stream
    it is fed — one global regime per bank in the EX-2 calibration. A
    wounded cell that stops being played cannot feed its own bad
    outcomes in (EX-2 finding 3, experiments/ex2-gamma-calibration.md);
    per-cell γ routing is the named v0.2 refinement. The ROW schema
    already carries per-event γ, so per-cell engines need no store
    change — write the cell-schedule's γ at record time.
    """

    def __init__(self, gamma_floor: float = GAMMA_FLOOR_DEFAULT,
                 ema_lambda: float = ADAPTIVE_EMA_LAMBDA_DEFAULT):
        floor = _require_gamma("gamma_floor", gamma_floor)
        if isinstance(floor, bool) or not (0.0 < floor < 1.0):
            raise ValueError(
                f"gamma_floor must be in (0, 1) exclusive, got {gamma_floor!r}")
        lam = _require_gamma("ema_lambda", ema_lambda)
        if isinstance(lam, bool) or not (0.0 < lam < 1.0):
            raise ValueError(
                f"ema_lambda must be in (0, 1) exclusive, got {ema_lambda!r}")
        self.gamma_floor = floor
        self.ema_lambda = lam
        self._m = 0.5  # neutral seed: a newborn cell is neither good nor bad

    def gamma(self) -> float:
        """γ in force for the NEXT observation (from past outcomes only)."""
        return self.gamma_floor + (1.0 - self.gamma_floor) * self._m

    def observe(self, outcome) -> None:
        """Fold one outcome into the EMA: ``m ← λ·m + (1−λ)·outcome``.
        Domain: Bernoulli 0/1 (the store's outcome vocabulary) AND
        fractional outcomes in [0, 1] (the credit streams — e.g. q_cells'
        rail-clamped round credit — so ONE schedule drives every DTS
        read face). Bernoulli inputs are bit-identical to the 0/1
        truthiness fold; out-of-band values clamp into [0, 1]."""
        o = max(0.0, min(1.0, float(outcome)))
        self._m = self.ema_lambda * self._m + (1.0 - self.ema_lambda) * o

    def next_gamma(self, outcome) -> float:
        """Convenience: γ now, then fold the outcome in (engine loop)."""
        g = self.gamma()
        self.observe(outcome)
        return g


def gamma_constant(gamma: float) -> _ConstantGamma:
    """Constant-γ schedule factory (the EX-2 calibration grid face)."""
    return _ConstantGamma(gamma)


def default_schedule() -> OutcomeAdaptiveGamma:
    """THE shipped default schedule (the EX-2 constants above) — the one
    γ face of the DTS engine. Every module-wide default imports THIS; no
    duplicated constants anywhere (owner ruling 2026-09-29)."""
    return OutcomeAdaptiveGamma(gamma_floor=GAMMA_FLOOR_DEFAULT,
                                ema_lambda=ADAPTIVE_EMA_LAMBDA_DEFAULT)


# --- schema lint -------------------------------------------------------------

_REQUIRED_ROW_FIELDS = ("schema", "state", "arm", "ts", "gamma", "outcome",
                        "alpha_add", "beta_add")


def _bernoulli_adds(outcome) -> tuple[float, float] | None:
    """Bernoulli domain: 0/1 in int/float/bool → (alpha_add, beta_add);
    anything else → None (refused; scalar semantics are NOT this store)."""
    if isinstance(outcome, bool):
        return (1.0, 0.0) if outcome else (0.0, 1.0)
    if isinstance(outcome, (int, float)):
        if outcome == 1:
            return (1.0, 0.0)
        if outcome == 0:
            return (0.0, 1.0)
    return None


def row_schema_lint(row: dict) -> list[str]:
    """Schema errors for one row ([] = clean). Pure; used by tests and by
    both append-time validation and read-time enforcement."""
    if not isinstance(row, dict):
        return ["row: not a mapping"]
    missing = [f"missing field: {f}" for f in _REQUIRED_ROW_FIELDS
               if f not in row]
    if missing:
        return missing
    errors: list[str] = []
    if row["schema"] != SCHEMA:
        errors.append(f"schema {row['schema']!r} != {SCHEMA!r} "
                      f"(version wall — never half-read a foreign version)")
    for field in ("state", "arm"):
        if not isinstance(row[field], str) or not row[field].strip():
            errors.append(f"{field}: non-empty string required")
    if not (isinstance(row["ts"], str) and row["ts"].strip()):
        errors.append("ts: non-empty string required")
    try:
        _require_gamma("gamma", row["gamma"])
    except ValueError as exc:
        errors.append(str(exc))
    if _bernoulli_adds(row["outcome"]) is None:
        errors.append(f"outcome: Bernoulli 0/1 required, got {row['outcome']!r}")
    adds = _bernoulli_adds(row["outcome"])
    if adds is not None and (row["alpha_add"], row["beta_add"]) != adds:
        errors.append("alpha_add/beta_add inconsistent with outcome")
    return errors


# --- IO (the knowledge family face, issue-1004 R2c; the per-module
# --- lock silo retired with the move — the consolidated append's flock
# --- is the single guard) ---------------------------------------------

def _row(state: str, arm: str, ts: str, gamma: float, outcome,
         adds: tuple[float, float], workspace_id: str) -> dict:
    return {
        "schema": SCHEMA,
        "state": state,
        "arm": arm,
        "ts": ts,
        "gamma": gamma,
        "outcome": outcome,
        "alpha_add": adds[0],
        "beta_add": adds[1],
        # PER-WORKSPACE ISOLATION (issue-1004 R2c review fix): the DTS
        # store's series was ws-local pre-move (per-workspace files —
        # never pooled across workspaces); the family file is
        # cross-task, so every NEW row carries its owning workspace and
        # ``read`` keeps only this workspace's rows (rows WITHOUT the
        # column are the pre-move ws-local history — migrated by the
        # R4 CLI with its owning workspace named on the row)
        "workspace_id": workspace_id,
    }


def read(ws) -> list[dict]:
    """Schema-enforced read: only rows passing row_schema_lint are signal
    (a learned state never half-reads a row, and a FOREIGN schema version
    is never merged — the version wall). Unparseable or schema-violating
    lines are skipped with one rate-limited WARN. Missing store → [].
    The read rides the knowledge family (issue-1004 R2c) — the only
    face since the issue-1004 R3 schema cutover — PER-WORKSPACE
    ISOLATED: rows carrying another workspace's ``workspace_id`` are
    skipped, so two workspaces sharing a guarded root never fold each
    other's posteriors (the pre-move ws-local store contract)."""
    mine = Path(ws).name
    out: list[dict] = []
    for row in _cl.read(ws, "knowledge", schema_prefix="posterior-store"):
        if not isinstance(row, dict) or row_schema_lint(row):
            warn("read_dirty", "schema-violating row skipped")
            continue
        rid = str(row.get("workspace_id") or "")
        if rid and rid != mine:
            continue
        out.append(row)
    return out


# --- write face ----------------------------------------------------------------

def record(ws, state: str, arm: str, outcome, *, gamma=None,
           ts: str | None = None) -> dict:
    """Append one observation row (the kernel's only write path).

    - ``outcome``: Bernoulli 0/1 (int/float/bool) — scalar semantics live
      in scalar_settlement; this store accepts observations as data.
    - ``gamma``: the γ in force at event time, recorded on the row. None
      = no schedule decision threaded by the caller → the SHIPPED default
      schedule's γ (``default_schedule().gamma()`` — the adaptive day-one
      value from the neutral seed; owner ruling 2026-09-29: no plain-TS
      write default anywhere). The adaptive engine loop threads its own
      per-event γ (``next_gamma(outcome)``). The decay itself is applied
      at the fold/read face, never in the file.
    The row rides the knowledge family file (issue-1004 R2c) — the
    consolidated append's stamp contract + flock are the write wall —
    carrying its owning workspace (per-workspace posterior isolation at
    the read face). Loud result dict, no raise."""
    ws = Path(ws)
    state = str(state or "").strip()
    arm = str(arm or "").strip()
    if not state or not arm:
        return {"appended": False, "reason": "state/arm: empty"}
    adds = _bernoulli_adds(outcome)
    if adds is None:
        return {"appended": False,
                "reason": f"outcome: Bernoulli 0/1 required, got {outcome!r}"}
    try:
        g = _require_gamma(
            "gamma", default_schedule().gamma() if gamma is None else gamma)
    except ValueError as exc:
        return {"appended": False, "reason": str(exc)}
    ok = _cl.append(ws, "knowledge",
                    _row(state, arm, ts or _utc_now(), g, outcome, adds,
                         ws.name))
    return {"appended": bool(ok),
            "reason": None if ok else "write failed"}


# --- fold / read face (γ decay lives HERE, never in the file) ------------------

class PosteriorView:
    """In-memory numpy view over one fold of the store.

    ``alpha``/``beta``/``n_effective`` are the DECAYED counts per cell
    (float64 arrays, one slot per cell in insertion order); every value
    crossing the boundary leaves as a Python float (numpy policy 3).
    ``sample`` stays stdlib betavariate (policy 4) — the drawn
    distribution IS the decayed posterior (TS invariant).
    """

    def __init__(self, cells: list[tuple[str, str]], alpha: list[float],
                 beta: list[float], n_eff: list[float]):
        self.cells: list[tuple[str, str]] = list(cells)
        self.alpha = np.array(alpha, dtype=np.float64)
        self.beta = np.array(beta, dtype=np.float64)
        self.n_effective = np.array(n_eff, dtype=np.float64)

    def _index(self) -> dict[tuple[str, str], int]:
        return {key: i for i, key in enumerate(self.cells)}

    def cell(self, state: str, arm: str) -> dict | None:
        """One cell's decayed posterior (Python floats)."""
        i = self._index().get((str(state), str(arm)))
        if i is None:
            return None
        a = float(self.alpha[i])
        b = float(self.beta[i])
        n = float(self.n_effective[i])
        total = a + b
        return {"alpha": a, "beta": b, "mean": a / total,
                "n_effective": n,
                "width": math.sqrt(a * b / (total * total * (total + 1.0)))}

    def means(self) -> list[float]:
        """Decayed posterior means, cell insertion order (vectorized)."""
        total = self.alpha + self.beta
        return [float(v) for v in self.alpha / total]

    def widths(self) -> list[float]:
        """Decayed posterior standard deviations (vectorized) — the
        exploration-width face (cold start: γ < 1 → wider)."""
        total = self.alpha + self.beta
        var = self.alpha * self.beta / (total * total * (total + 1.0))
        return [float(v) for v in np.sqrt(var)]

    def sample(self, rng) -> list[float]:
        """One DTS draw per cell from the DECAYED posterior."""
        return [rng.betavariate(float(a), float(b))
                for a, b in zip(self.alpha, self.beta)]


def fold(ws, schedule=None, *, prior_alpha=None,
         prior_beta=None) -> PosteriorView:
    """Replay the store in input order through the γ recurrence — the
    ONE decay face. Raw counts on disk are never rewritten.

    - ``schedule=None``: replay each row's OWN recorded γ (the store's
      truth — what the engine believed at event time).
    - ``schedule``: a γ schedule object (gamma_constant /
      OutcomeAdaptiveGamma / default_schedule) drives the replay
      counterfactually — the EX-2 calibration face. The schedule sees
      each row's outcome only AFTER emitting that row's γ (no peeking).
    - ``prior_alpha``/``prior_beta``: pseudo-count priors, seeded at each
      cell's birth and decayed under the same γ (defaults = the
      PRIOR_*_DEFAULT learning-rate knob).

    Bit-exact: one IEEE multiply + add per element, input order — pinned
    in tests/test_rlvr_posteriors_428.py."""
    a0 = PRIOR_ALPHA_DEFAULT if prior_alpha is None else float(prior_alpha)
    b0 = PRIOR_BETA_DEFAULT if prior_beta is None else float(prior_beta)
    if a0 <= 0.0 or b0 <= 0.0:
        raise ValueError("prior_alpha/prior_beta must be positive")
    index: dict[tuple[str, str], int] = {}
    cells: list[tuple[str, str]] = []
    alpha: list[float] = []
    beta: list[float] = []
    n_eff: list[float] = []
    for row in read(ws):
        key = (row["state"], row["arm"])
        i = index.get(key)
        if i is None:
            i = len(cells)
            index[key] = i
            cells.append(key)
            alpha.append(a0)
            beta.append(b0)
            n_eff.append(0.0)
        g = row["gamma"] if schedule is None else schedule.gamma()
        alpha[i] = g * alpha[i] + row["alpha_add"]
        beta[i] = g * beta[i] + row["beta_add"]
        n_eff[i] = g * n_eff[i] + 1.0
        if schedule is not None:
            schedule.observe(row["outcome"])
    return PosteriorView(cells, alpha, beta, n_eff)


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
