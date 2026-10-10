# -*- coding: utf-8 -*-
"""rlvr/refutation_fold.py — the refutation fold (deterministic).

Repeated deception must not reset to zero every loop: a class of claim
that keeps getting refuted in a given state shape deserves harder
verification, learned from evidence, and it deserves to FORGIVE when the
deception stops. This module aggregates refuted verify transitions into
a per-signature refutation rate and derives two consumers from it:

  1. a feature token (the policy conditions on refutation-heavy state)
  2. a verify-cadence multiplier (stale thresholds divide by it, so
     verification density rises exactly where refutations concentrate)

The fold mirrors the DTS discipline: raw rows are never rewritten, decay
is a READ-FACE property. Every verify observation replays in input order
through the recurrence

    (ref, hon) <- FOLD_GAMMA x (ref, hon) + (is_refuted, is_honest)

per (signature, boundary) bucket. FOLD_GAMMA < 1 means newer evidence
dominates: an honest verification streak folds the refuted mass away —
the DECAY GUARD. The rate is ref/(ref+hon) over the folded masses, so it
lives in [0, 1] by construction and the multiplier

    multiplier = 1 + (MULT_MAX - 1) x rate     ∈ [1, MULT_MAX]

is bounded, monotone in the rate, and never a clamp: it is arithmetic
over evidence, and it returns to 1.0 exactly when honest verification
has healed the signature. Never negative density: the multiplier is
>= 1, so a divided threshold only ever SHRINKS toward zero-density-floor
base/MULT_MAX, never below.

Sources (both pure reads, zero model calls):
  - the transition ledger (runs/transitions.jsonl): rows with
    action_type = verify and a settled credit — the refuted predicate is
    r_settle = 0, which per incremental_reward.verify_credit means
    refuted / unverified-with-gap / timeout (everything that decided
    nothing); r_settle = 1 is the honest class. The credit MAPPING is
    reused (verify_credit), never re-derived here.
  - the keyed posterior store (the cross-task store substrate):
    rows this module recorded at verify settle (arm refutation). Rows
    from OTHER workspaces are the cross-engagement face — a second
    workspace with the same feature signature inherits the raised
    density. The workspace's OWN store rows are skipped (they duplicate
    the local ledger's truth; the ledger is authoritative at home).

Claim boundary type: the verification boundary the act ran at (the
variant vocabulary: verify | redteam; default verify). The bucket key is
signature x boundary; the per-signature rate folds across boundaries.

Fail-open contract: a broken read lands on the ZERO face with one
canonical warn — a broken measurement never manufactures refutations
and never blocks the caller. ZERO LEARNING POSTURE: no model call, no
fitted parameter, no data files of its own; FOLD_GAMMA / MULT_MAX /
HOT_RATE / WARM_RATE are documented policy constants.

Consumers:
  - rlvr.feature_prior — the refutation-tier feature token (with_refutation_token)
  - convergence_check  — the cadence read point (effective stale threshold)
  - rlvr.compose       — the strategy object's refutation key + seam section
  - scripts/e2e/checkpoints — records verify outcomes into the keyed store
"""
from __future__ import annotations

from pathlib import Path

from kunglao_log import warn  # canonical warn: ONE implementation

#: the fold discount in force at every observation (policy constant):
#: newer evidence dominates, so an honest streak folds the refuted mass
#: away geometrically (the decay guard's mechanism).
FOLD_GAMMA = 0.9

#: the multiplier ceiling (bounded influence: verification density at
#: most MULT_MAX-fold above baseline, and the floor is exactly 1.0 —
#: a healed signature pays nothing).
MULT_MAX = 3.0

#: the multiplier floor (the healed baseline: no rate, no tax).
MULT_MIN = 1.0

#: token tiers: the rate at which a signature reads refutation-hot /
#: refutation-warm (below both, no token — silence is the default).
HOT_RATE = 0.5
WARM_RATE = 0.25

#: the store vocabulary of this face (rows ride the keyed store with
#: this arm key, so they never collide with method-arm rows).
STORE_ARM = "refutation"
STORE_FAMILY = "verify"

#: the boundary default when a row carries no variant vocabulary.
DEFAULT_BOUNDARY = "verify"

#: the signature placeholder when no feature signature is derivable.
SIGNATURE_NONE = "none"

VERIFY_ACTION = "verify"

_CREDIT_CLASSES = (0.0, 1.0)


# --- pure fold arithmetic ----------------------------------------------------

def multiplier_of(rate: float) -> float:
    """The bounded cadence multiplier over one rate: arithmetic, not a
    rule — 1.0 at no evidence, MULT_MAX at total refutation."""
    r = max(0.0, min(1.0, float(rate)))
    return 1.0 + (MULT_MAX - 1.0) * r


def tier(rate: float) -> str | None:
    """The feature-token tier of one rate: hot / warm / None (silence)."""
    r = max(0.0, min(1.0, float(rate)))
    if r >= HOT_RATE:
        return "hot"
    if r >= WARM_RATE:
        return "warm"
    return None


def _fold_stream(pairs: list[tuple[bool, bool]],
                 gamma: float = FOLD_GAMMA) -> tuple[float, float]:
    """Replay (refuted, honest) observations in input order through the
    discount recurrence. Bit-deterministic: one multiply + add per row."""
    ref = 0.0
    hon = 0.0
    for is_ref, is_hon in pairs:
        ref = gamma * ref + (1.0 if is_ref else 0.0)
        hon = gamma * hon + (1.0 if is_hon else 0.0)
    return ref, hon


def _bucket_key(sig: str, boundary: str) -> str:
    return f"{sig}|{boundary}"


def _credit_class(value) -> float | None:
    """Row credit -> the observation class (0.0 refuted / 1.0 honest);
    anything outside the settled vocabulary is not evidence."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    for cls in _CREDIT_CLASSES:
        if v == cls:
            return cls
    return None


def _boundary_of(row: dict) -> str:
    """The claim boundary type of one verify row: the act's variant
    vocabulary (verify | redteam), defaulting to the plain boundary."""
    o = row.get("o")
    if not isinstance(o, dict):
        return DEFAULT_BOUNDARY
    for field in ("variant", "class"):
        value = o.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return DEFAULT_BOUNDARY


def zero_face() -> dict:
    """The absence face: no refutation evidence (the fail-open landing
    shape)."""
    return {"buckets": {}, "rates": {},
            "mine": {"signature": SIGNATURE_NONE, "refuted": 0.0,
                     "honest": 0.0, "rate": 0.0},
            "multiplier": 1.0}


# --- read faces (pure ledger + store reads, zero model calls) ----------------

def _workspace_signature(ws) -> str:
    """The workspace's feature signature (the cross-workspace matching
    key): the keyed store's feature digest over the mined feature
    tokens, fail-open to the inert placeholder (a broken miner never
    blocks the fold). Module-level so tests can pin it."""
    try:
        from rlvr import strategy_store  # noqa: PLC0415 — lazy (import cost)
        return strategy_store.feature_key_of(ws)
    except Exception as exc:  # noqa: BLE001 — the seam is fail-open by design
        warn("refutation_fold.signature",
             f"{type(exc).__name__}: {exc} (signature=none)")
        return SIGNATURE_NONE


def _ledger_rows(ws) -> list[dict]:
    """The workspace's verify transitions (tolerant ledger read)."""
    from rlvr import incremental_reward  # noqa: PLC0415 — lazy (import cost)
    return [r for r in incremental_reward.read_transitions(ws)
            if isinstance(r, dict)
            and str(r.get("action_type") or "") == VERIFY_ACTION]


def _store_rows(ws) -> tuple[list[dict], list[dict]]:
    """Split the keyed store's refutation rows into (other, mine): rows
    from OTHER workspaces are cross-engagement evidence; the workspace's
    OWN store rows duplicate its ledger and never score."""
    from rlvr import strategy_store  # noqa: PLC0415 — lazy (import cost)
    mine_id = strategy_store.workspace_id_of(ws)
    other: list[dict] = []
    own: list[dict] = []
    for row in strategy_store.load_rows(ws=None):
        if not isinstance(row, dict) \
                or str(row.get("arm_key") or "") != STORE_ARM:
            continue
        if str(row.get("workspace_id") or "") == mine_id:
            own.append(row)
        else:
            other.append(row)
    return other, own


def fold(ws, *, gamma: float = FOLD_GAMMA) -> dict:
    """The refutation fold over one workspace.

    Returns {"buckets", "rates", "mine", "multiplier"}:

      buckets   signature|boundary -> {refuted, honest, rate} — the
                discounted masses and the folded rate per bucket
      rates     signature -> rate folded across that signature's
                boundaries
      mine      this workspace's own fold: {signature, refuted, honest,
                rate} — its ledger plus every other workspace's rows at
                its feature signature
      multiplier the cadence multiplier derived from the mine rate

    Pure read; every degradation lands on the zero face with a warn,
    never a raise."""
    try:
        return _fold_impl(ws, gamma=gamma)
    except Exception as exc:  # noqa: BLE001 — a broken measurement never
        warn("refutation_fold.fold",
             f"{type(exc).__name__}: {exc} (fail-open: zero fold)")
        return zero_face()


def _fold_impl(ws, *, gamma: float) -> dict:
    ws = Path(ws)
    my_sig = _workspace_signature(ws)

    bucket_streams: dict[str, list[tuple[bool, bool]]] = {}
    sig_streams: dict[str, list[tuple[bool, bool]]] = {}
    mine_stream: list[tuple[bool, bool]] = []

    def _observe(sig: str, boundary: str, cls: float) -> None:
        obs = (cls == 0.0, cls == 1.0)
        bucket_streams.setdefault(_bucket_key(sig, boundary),
                                  []).append(obs)
        sig_streams.setdefault(sig, []).append(obs)
        mine_stream.append(obs)

    # source 1: the local ledger (own truth, authoritative at home)
    for row in _ledger_rows(ws):
        cls = _credit_class(row.get("r_settle"))
        if cls is None:
            continue
        sig = str(row.get("s") or "").strip() or SIGNATURE_NONE
        _observe(sig, _boundary_of(row), cls)

    # source 2: other workspaces' rows at MY feature signature only —
    # foreign buckets stay foreign (a signature I do not match raises no
    # density here)
    other, _own = _store_rows(ws)
    for row in other:
        cls = _credit_class(row.get("credit"))
        if cls is None:
            continue
        sig = str(row.get("feature_key") or "").strip() or SIGNATURE_NONE
        if sig == my_sig:
            _observe(sig, str(row.get("status") or "").strip()
                     or DEFAULT_BOUNDARY, cls)

    buckets: dict[str, dict] = {}
    rates: dict[str, float] = {}
    for key, stream in bucket_streams.items():
        ref, hon = _fold_stream(stream, gamma)
        total = ref + hon
        buckets[key] = {"refuted": round(ref, 6),
                        "honest": round(hon, 6),
                        "rate": round(ref / total, 6) if total > 0 else 0.0}
    for sig, stream in sig_streams.items():
        ref, hon = _fold_stream(stream, gamma)
        total = ref + hon
        rates[sig] = round(ref / total, 6) if total > 0 else 0.0

    m_ref, m_hon = _fold_stream(mine_stream, gamma)
    m_total = m_ref + m_hon
    m_rate = round(m_ref / m_total, 6) if m_total > 0 else 0.0
    return {"buckets": buckets,
            "rates": rates,
            "mine": {"signature": my_sig, "refuted": round(m_ref, 6),
                     "honest": round(m_hon, 6), "rate": m_rate},
            "multiplier": multiplier_of(m_rate)}


def cadence_multiplier(ws) -> float:
    """The verify-cadence multiplier for this workspace (>= 1.0): the
    number the stale threshold divides by when its signature is
    refutation-heavy. 1.0 = the honest baseline (no tax)."""
    return float(fold(ws)["multiplier"])


# --- write face (the cross-engagement substrate) -----------------------------

def record_verify_outcome(ws, *, verdict: str, boundary: str = "",
                          signature: str | None = None) -> dict:
    """Record one verify outcome into the keyed store (the write face
    behind cross-engagement): the verdict banks through THE credit
    mapping (verify_credit — reuse, never a second rule), the row rides
    the shared append primitive (holdout-filtered, guarded root,
    fail-open loud). Loud result dict, never raises."""
    from rlvr import incremental_reward  # noqa: PLC0415 — lazy (import cost)
    from rlvr import strategy_store  # noqa: PLC0415 — lazy (import cost)
    try:
        sig = (str(signature).strip() if signature
               else _workspace_signature(ws))
        row = {
            "schema": strategy_store.STORE_SCHEMA,
            "ts": _utc_now_z(),
            "workspace_id": strategy_store.workspace_id_of(ws),
            "arm_key": STORE_ARM,
            "method_family": STORE_FAMILY,
            "feature_key": sig,
            "fingerprint": None,
            "status": str(boundary).strip() or DEFAULT_BOUNDARY,
            "credit": incremental_reward.verify_credit(verdict),
            "censored": False,
            "facts_citing": 0,
            "propensity": None,
            "phi_delta": None,
            "provenance": {"dispatch_id": ""},
        }
        return strategy_store.append_row(row)
    except Exception as exc:  # noqa: BLE001 — telemetry, never the producer
        warn("refutation_fold.record",
             f"{type(exc).__name__}: {exc}")
        return {"appended": False, "reason": f"error:{type(exc).__name__}"}


def _utc_now_z() -> str:
    from _common import utc_now_z  # noqa: PLC0415 — the canonical leaf
    return utc_now_z()


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
