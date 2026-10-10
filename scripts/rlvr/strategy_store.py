#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""strategy_store.py — the REAL compose store adapter (kernel W2-T4 seam,
issue 462 W3).

compose.py sees the learned state only through the ``StrategyStore``
protocol (method_lead / decayed_weight / cell_count). Until this module
the protocol had NO implementation: ``load_store`` imported a
nonexistent ``rlvr.posteriors.PosteriorsStore`` and silently degraded to
``IdentityStore`` — no lead, unit decay weights, no cell population — so
even library use of compose yielded zero learned content. This adapter
points the seam at the faces that actually landed (#428 posterior store,
#429 §4 q_cells, #420 ledger):

  - ``method_lead(fp)``  DTS call site 2 THROUGH the compose single-point
    (the q_cells docstring's "compose is the sole consumer of the
    sampler"): the candidate set is the workspace's measured proposal
    channel (families the LLM actually declared — q-cell dispatch rows +
    settled-ledger ``method_family`` signals), P_LLM = the family's
    proposal share; the draw reweights by the γ-discounted shrunk cell
    posterior (``q_cells.sample_method_family``). Day one the posteriors
    are the wide Beta(1,1) and the selection degenerates to the pure
    proposal prior — Q is the learned ADJUSTMENT, it never overrides the
    proposal channel (#429 §8 day-one ruling). rng =
    ``q_cells.q_cells_seed_state(ws)`` — the sample moves when evidence
    moves or the round advances, never on a wall clock (#251). No
    candidates (no declaration ever recorded) -> None: honest silence,
    the cold-start posture, never a fabricated lead.

  - ``decayed_weight(row_id)``  the γ-linked retrieval weight for a
    card's backing row: the settled stream replayed in input order under
    the shipped DTS default schedule, ``weight_i = Π_{k>i} γ_k`` (the
    no-peeking recurrence — the same shape as the q_cells fold). A row
    outside the settled stream keeps the unit weight (no invented decay).

  - ``cell_count(fp)``  the state-conditioned evidence population: rows
    in the q-cell log at THIS signature (credits + pending). While the
    spine has recorded nothing at all the workspace has no cell data, and
    the seam returns None — compose's documented fallback to the settled
    ledger total (the pre-spine evidence base, IdentityStore semantics).

Failure posture: compose is the decision single-point — the seam
FAILS LOUDLY on a broken construction (never a silent fake policy).
Store READS ride the documented q_cells store protocol: a corrupt
posterior bank degrades to the tolerant JSONL face with one rate-
limited warn (the store's own fail-open read contract), and the
learned values derived from it are pure deterministic reads of
whatever rows survive.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from kunglao_log import iter_jsonl, warn  # canonical warn: ONE implementation

from rlvr import ledger as rl
from rlvr import posteriors as dts
from rlvr import q_cells
from rlvr.compose import method_family_of_row  # the settled-row face

# --------------------------------------------------------------------------
# the cross-task posterior store (#545, WS2) — append-only JSONL, keyed
# (family, arm_key, feature_key, fingerprint), living inside the guarded
# prior_store_root (eval/v1/split.yaml prior_store_roots →
# scripts/rlvr/patterns). The store is repo-code territory: the OWNER
# RULING (2026-10-07) keeps everything under eval/ WRITE-FORBIDDEN — this
# module only ever READS split.yaml (the holdout firewall's filter face),
# never writes anything under eval/.
#
# Write face: the e2e settlement hook (e2e/checkpoints._settle_dispatch_outcome)
# appends one row per settled dispatch — holdout-filtered BEFORE append,
# fail-open telemetry (a store failure never breaks settlement).
# Read face: ``warm_pools`` — cross-task rows enter ONLY as
# LAMBDA-tempered anchor mass through the sampler's existing pool face
# (q_cells.cell_posterior's warm_pool), NEVER as a local-cell write; the
# per-workspace q-cell log stays authoritative for local cells.
# Firewall: eval_split_lint hard-fails any holdout unit-id reaching the
# store rows (the write-face filter is the first gate, the lint the
# second — defense in depth).

STORE_SCHEMA = "posterior-store/1"
STORE_REL = "posterior-store.jsonl"
STORE_ENV = "KUNGLAO_POSTERIOR_STORE"

#: the refutation fold's store arm (its rows ride the same keyed store —
#: the cross-workspace verify stream — and are never method proposals).
#: The fallback candidate channel excludes them by arm key; the
#: registered-vocabulary intersect is the second wall. The literal
#: mirrors rlvr.refutation_fold.STORE_ARM (pinned equal by test).
_REFUTATION_ARM = "refutation"


def store_root() -> Path:
    """The store root: env KUNGLAO_POSTERIOR_STORE override, else the
    skill-dir patterns path (the guarded prior_store_root)."""
    env = os.environ.get(STORE_ENV, "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent / "patterns"


def store_path() -> Path:
    return store_root() / STORE_REL


def workspace_id_of(ws) -> str:
    """The cross-task identity of a workspace: its directory name (stable
    across the run's lifetime, human-traceable, never an eval unit id)."""
    return Path(ws).name


def holdout_unit_ids() -> set[str]:
    """The holdout unit-ids from eval/v1/split.yaml (READ-ONLY — the
    never-write wall). Fail-open to an EMPTY filter with a loud warn:
    a broken filter read can never block settlement, and the lint face
    (eval_split_lint) remains the enforcement wall."""
    try:
        import yaml  # noqa: PLC0415
        p = Path(__file__).resolve().parents[2] / "eval" / "v1" \
            / "split.yaml"
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        hold = doc.get("holdout") or {}
        ids = list(hold.get("interpolation") or []) \
            + list(hold.get("extrapolation") or [])
        return {str(u).lower() for u in ids if u}
    except Exception as exc:  # noqa: BLE001 — fail-open, loud
        warn("strategy_store.holdout_ids",
             f"split.yaml unreadable ({type(exc).__name__}: {exc}) — "
             f"holdout filter empty; eval_split_lint stays the wall")
        return set()


def feature_key_of(ws) -> str:
    """The workspace's FEATURE key (feature-keyed, never identity-keyed
    — the #518 rule): a stable digest over the mined feature tokens.
    Fail-open to the inert "none" (a broken miner never blocks
    settlement)."""
    try:
        from rlvr import feature_prior as _fp  # noqa: PLC0415
        feats = _fp.features_from_workspace(ws)
        toks = sorted(_fp.feature_tokens(feats or {}))
        if not toks:
            return "none"
        return hashlib.sha256(
            "|".join(toks).encode("utf-8")).hexdigest()[:12]
    except Exception as exc:  # noqa: BLE001 — fail-open, loud
        warn("strategy_store.feature_key",
             f"{type(exc).__name__}: {exc} (feature_key=none)")
        return "none"


def append_row(row: dict) -> dict:
    """Filter-and-append one store row. THE HOLDOUT FILTER PRECEDES THE
    APPEND: any row whose serialized form carries a holdout unit-id is
    refused with a loud warn (the same predicate eval_split_lint
    enforces — belt and suspenders). Fail-open telemetry: a store
    failure never breaks settlement."""
    try:
        payload = json.dumps(row, ensure_ascii=False).lower()
        hit = next((u for u in sorted(holdout_unit_ids())
                    if u in payload), None)
        if hit is not None:
            warn("strategy_store.append_row",
                 f"holdout unit-id {hit!r} refused — the firewall "
                 f"filter precedes the append")
            return {"appended": False, "reason": f"holdout-filter:{hit}"}
        ok = q_cells._append_row(store_path(), row)
        return {"appended": bool(ok),
                "reason": None if ok else "write-failed"}
    except Exception as exc:  # noqa: BLE001 — telemetry, never the producer
        warn("strategy_store.append_row", f"{type(exc).__name__}: {exc}")
        return {"appended": False, "reason": f"error:{type(exc).__name__}"}


def append_store_row(ws=None, *, method_family: str, status: str,
                     credit, censored: bool = False, facts_citing: int = 0,
                     propensity=None, phi_delta=None,
                     dispatch_id: str | None = None, arm_key: str | None
                     = None, feature_key: str | None = None,
                     fingerprint: str | None = None,
                     ts: str | None = None) -> dict:
    """Build and append one ``posterior-store/1`` row (the settlement
    hook's face): schema stamp, ts, workspace identity, feature key
    (ws-derived defaults), the 4-dim arm key, the settled credit, the
    censoring flag, the fact signal, the OPE propensity, and the Φ
    tiebreaker — one field, no new machinery (the #548 verdict's fix
    rides the row). Delegates to ``append_row`` (filter + fail-open)."""
    from harness_common import utc_now_z  # noqa: PLC0415
    row = {
        "schema": STORE_SCHEMA,
        "ts": ts or utc_now_z(),
        "workspace_id": workspace_id_of(ws) if ws is not None else "unknown",
        "arm_key": str(arm_key) if arm_key else str(method_family),
        "method_family": str(method_family),
        "feature_key": str(feature_key) if feature_key
        else (feature_key_of(ws) if ws is not None else "none"),
        "fingerprint": fingerprint,
        "status": str(status),
        "credit": (max(0.0, min(1.0, float(credit)))
                   if isinstance(credit, (int, float))
                   and not isinstance(credit, bool) else None),
        "censored": bool(censored),
        "facts_citing": int(facts_citing),
        "propensity": (float(propensity)
                       if isinstance(propensity, (int, float))
                       and not isinstance(propensity, bool) else None),
        "phi_delta": (round(float(phi_delta), 6)
                      if isinstance(phi_delta, (int, float))
                      and not isinstance(phi_delta, bool) else None),
        "provenance": {"dispatch_id": str(dispatch_id or "")},
    }
    return append_row(row)


def load_rows(ws=None) -> list[dict]:
    """The tolerant read: schema-filtered rows, oldest first; when ``ws``
    is given, rows from THAT workspace are excluded (the leave-one-out
    shape — a workspace never warm-starts from its own rows). Missing
    store = [], corrupt lines skip, unknown schemas skip."""
    try:
        text = store_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rows = [r for r in iter_jsonl(text.splitlines())
            if isinstance(r, dict)
            and str(r.get("schema") or "") == STORE_SCHEMA]
    if ws is not None:
        mine = workspace_id_of(ws)
        rows = [r for r in rows
                if str(r.get("workspace_id") or "") != mine]
    return rows


def warm_pools(ws, families) -> dict:
    """The read face — cross-task rows as LAMBDA-tempered anchor pools.

    Every OTHER workspace's settled store row contributes
    LAMBDA · tiebroken_credit mass to its family's pool (the tempering
    convention of meta_arms.hierarchical_prior, applied at the store
    face; the #548 tiebreaker rides the credit). NEVER full weight,
    NEVER a local-cell write. Returns {family → FeaturePool} (the
    sampler's duck type) — families without pool rows are absent (a
    zero-mass pool is a no-op at the anchor)."""
    rows = load_rows(ws=ws)
    if not rows:
        return {}
    wanted = set(families)
    acc: dict[str, list[float]] = {}
    from rlvr import meta_arms as _ma  # noqa: PLC0415 — the temper
    for r in rows:
        fam = str(r.get("method_family") or "")
        if fam not in wanted:
            continue
        c = r.get("credit")
        if isinstance(c, bool) or not isinstance(c, (int, float)):
            continue  # pending/unknown rows carry no outcome
        eff = q_cells.tiebroken_credit(float(c), r.get("phi_delta"))
        s, f, n = acc.get(fam, (0.0, 0.0, 0))
        acc[fam] = (s + _ma.LAMBDA * eff,
                    f + _ma.LAMBDA * (1.0 - eff), n + 1)
    if not acc:
        return {}
    from rlvr import feature_prior as _fp  # noqa: PLC0415 — the duck type
    return {fam: _fp.FeaturePool(s, f, n)
            for fam, (s, f, n) in sorted(acc.items())}


def _registered_only(counts: dict[str, int]) -> dict[str, int]:
    """Intersect a family -> count face with the registered vocabulary —
    a retired token must never ride a prior into the loop prompt (the
    lead is advisory, but steering declarations the fail-closed
    vocabulary gate rejects is the lockstep hazard in advisory form). An
    unreadable registry degrades to the unfiltered face with one warn;
    the gate stays the enforcement face."""
    try:
        import method_families  # noqa: PLC0415 — registry sibling
        registered = method_families.registered_tokens()
    except Exception as exc:  # noqa: BLE001 — registry best-effort
        warn("strategy_store.prior",
             f"registry unreadable ({type(exc).__name__}: {exc}) — "
             f"prior unfiltered; the gate remains the enforcement face")
        return dict(counts)
    return {fam: n for fam, n in counts.items() if fam in registered}


def _share(counts: dict[str, int]) -> dict[str, float]:
    """Normalize a family -> count face into a proposal prior over the
    retained mass ({} when nothing survives) — deterministic order."""
    total = sum(counts.values())
    if total <= 0:
        return {}
    return {fam: n / total for fam, n in sorted(counts.items())}


class PosteriorStrategyStore:
    """THE StrategyStore implementation over the landed faces."""

    def __init__(self, ws):
        self.ws = Path(ws)
        self._qstore = q_cells.default_store(self.ws)
        self._weights: dict[str, float] | None = None

    # ------------------------------------------------ StrategyStore seam

    def method_lead(self, state_fingerprint: str) -> str | None:
        """One DTS draw over the live material at this state (None = no
        proposal ever recorded at this workspace AND no cross-task store
        row to stand in). When the workspace's own proposal channel is
        empty, the cross-task posterior store's families carry the
        candidate set — the live store write (the settlement bank keys
        its row with the dispatch's own arm key) is only half a wire
        without this read face, and the warm pools need a candidate set
        to ride or they never reach the draw."""
        prior = self._proposal_prior()
        if not prior:
            prior = self._store_prior()
        if not prior:
            return None
        rng, _round = q_cells.q_cells_seed_state(self.ws)
        kwargs: dict = {}
        kwargs.update(self._feature_prior_kwargs())
        kwargs.update(self._warm_pool_kwargs(prior.keys()))
        kwargs.update(self._termination_kwargs(prior.keys()))
        receipt = q_cells.sample_method_family(
            state_fingerprint, prior, self._qstore, rng=rng, **kwargs)
        return str(receipt["family"])

    def _store_prior(self) -> dict[str, float]:
        """The cross-task fallback candidate channel: families the keyed
        store holds settled rows for (OTHER workspaces only — the
        leave-one-out shape), weighted by their row share, intersected
        with the registered vocabulary. Empty when the store is empty or
        unreadable: the honest cold start stays silence, never a
        fabricated lead — and every sampled candidate then carries the
        additive posterior_store receipt block through the warm pools,
        so the fallback draw stays traceable to its rows."""
        try:
            counts = self._store_family_counts()
        except Exception as exc:  # noqa: BLE001 — fail-open at the seam
            warn("strategy_store.store_prior",
                 f"{type(exc).__name__}: {exc}")
            return {}
        return _share(_registered_only(counts))

    def _store_family_counts(self) -> dict[str, int]:
        """Row counts per method family over the cross-task store's
        settled rows (the workspace's own rows excluded by the read
        face). The refutation fold's rows ride the same store under
        their own arm key — never proposals, excluded here."""
        counts: dict[str, int] = {}
        for row in load_rows(ws=self.ws):
            if not isinstance(row, dict):
                continue
            if str(row.get("arm_key") or "") == _REFUTATION_ARM:
                continue
            fam = str(row.get("method_family") or "").strip()
            if fam:
                counts[fam] = counts.get(fam, 0) + 1
        return counts

    def _warm_pool_kwargs(self, families=None) -> dict:
        """#545 wiring (the cross-task warm start): thread the posterior
        store's LAMBDA-tempered anchor pools into call site 2 — without
        this the compose seam would stay store-blind. Fail-open: any
        failure yields {} (the sampler stays store-blind, the pre-change
        draw)."""
        try:
            fams = families if families is not None \
                else self._proposal_prior().keys()
            pools = warm_pools(self.ws, fams)
            return {"warm_pools": pools} if pools else {}
        except Exception as exc:  # noqa: BLE001 — fail-open at the seam
            warn("strategy_store.warm_pools",
                 f"{type(exc).__name__}: {exc}")
            return {}

    def _termination_kwargs(self, families=None) -> dict:
        """#461 Phase 2 wiring (option-death termination): thread the
        per-candidate death verdicts into call site 2 — dead options
        sample at ARM_FLOOR (rlvr.termination; floor-not-delete, the
        PARK posture). ``families`` defaults to the proposal prior's
        keys (the verdict face's candidate set — verdicts(ws,
        prior.keys())); the zero-registry rule returns {} there, so a
        day-one workspace threads no kwarg at all. Fail-open: any
        failure yields {} (the sampler stays termination-blind, the
        pre-change draw)."""
        try:
            from rlvr import termination as _term  # noqa: PLC0415
            fams = families if families is not None \
                else self._proposal_prior().keys()
            verdicts = _term.verdicts(self.ws, fams)
            return {"death": verdicts} if verdicts else {}
        except Exception:  # noqa: BLE001 — fail-open at the seam
            return {}

    def _feature_prior_kwargs(self) -> dict:
        """#460 Part B wiring (predict-before-try): thread the live
        instance features + the workspace's mined feature table into
        call site 2 WHEN the KUNGLAO_PREDICT_BEFORE_TRY flag is on —
        without this the flag-on path would be dead code at the
        production seam. Fail-open: any extraction/loading failure
        yields {} (the sampler stays flag-off-identical)."""
        try:
            from rlvr import feature_prior as _fp  # noqa: PLC0415
            if not _fp.enabled():
                return {}
            features = _fp.features_from_workspace(self.ws)
            if not features:
                return {}
            return {"features": features,
                    "feature_table": _fp.default_table_path(self.ws)}
        except Exception:  # noqa: BLE001 — fail-open at the seam
            return {}

    def decayed_weight(self, row_id: str) -> float:
        """γ-decayed weight of one settled backing row (unit weight for
        rows outside the settled stream)."""
        # lifecycle pin: the weight ladder is cached per INSTANCE and a
        # fresh store is built per decision event (compose.compose does
        # exactly that) — a long-lived instance would serve stale weights
        # after settlements land.
        if self._weights is None:
            self._weights = self._decayed_weights()
        return float(self._weights.get(str(row_id), 1.0))

    def cell_count(self, state_fingerprint: str) -> int | None:
        """Q-cell rows at this signature; None while the spine has no
        data at all (compose falls back to the settled-ledger total)."""
        rows = self._qstore.observations()
        if not rows:
            return None
        fp = str(state_fingerprint)
        return sum(1 for row in rows
                   if isinstance(row, dict)
                   and str(row.get("signature_hash") or "") == fp)

    # ------------------------------------------------------------ internals

    def _proposal_prior(self) -> dict[str, float]:
        """P_LLM as a measured face: each family's share of the
        declarations this workspace has seen — the two PROPOSAL faces
        only (q-cell DISPATCH rows + settled ``method_family`` signals),
        INTERSECTED with the #432 registered vocabulary (a retired
        token must never ride the prior — the lead is advisory, but a
        retired family steered into the loop prompt would push
        declarations the fail-closed vocabulary gate rejects; the same
        lockstep hazard the W4 sampler face filters). Settlement-source
        q-cell rows are outcome data, never proposals; counting them
        would skew the prior toward dispatch-heavy families. The two
        proposal channels intentionally double-count a dispatched-then-
        settled declaration (a weighting choice, 462 design review
        LOW-3). An unreadable registry degrades to the unfiltered prior
        with one warn — the #432 GATE stays the enforcement face (the
        q_cells store's own division: enforcement is the gate's, never
        the store's). Deterministic in workspace state; empty when
        nothing was ever declared."""
        counts: dict[str, int] = {}
        for row in self._qstore.observations():
            if not isinstance(row, dict) \
                    or str(row.get("source") or "") != "dispatch":
                continue
            fam = str(row.get("method_family") or "").strip()
            if fam:
                counts[fam] = counts.get(fam, 0) + 1
        for row in rl.settled(self.ws, kind="task"):
            fam = method_family_of_row(row)
            if fam and fam != "any":
                counts[fam] = counts.get(fam, 0) + 1
        return _share(_registered_only(counts))

    def _decayed_weights(self) -> dict[str, float]:
        """The γ ladder over the settled stream, input order, shipped
        default schedule; ``weight_i = Π_{k>i} γ_k`` (no peeking — each
        row is decayed once per LATER row, at THAT row's event γ)."""
        rows = rl.settled(self.ws)
        schedule = dts.default_schedule()
        gammas = [0.0] * len(rows)
        for i, row in enumerate(rows):
            gammas[i] = schedule.gamma()
            schedule.observe(_row_outcome(row))
        weights: dict[str, float] = {}
        w = 1.0
        for i in range(len(rows) - 1, -1, -1):
            rid = str(rows[i].get("rollout_id") or "")
            weights[rid] = w
            if i > 0:
                w *= gammas[i]
        return weights


def _row_outcome(row: dict) -> float:
    """One settled row's outcome for the schedule's EMA face: the settled
    reward clamped into [0, 1] (the credit-stream shape; unparseable
    rewards fold as the neutral 0.5)."""
    try:
        reward = float((row.get("settlement") or {}).get("reward"))
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, reward))


def load_store(ws) -> "PosteriorStrategyStore":
    """Standalone constructor face for callers that want the adapter
    without importing compose (compose.load_store constructs
    PosteriorStrategyStore directly; this wrapper adds the loud
    warn-and-reraise on a failed construction)."""
    try:
        return PosteriorStrategyStore(ws)
    except Exception as exc:  # noqa: BLE001 — re-raise LOUDLY (fail-closed)
        warn("strategy_store", f"store construction failed: "
                               f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
