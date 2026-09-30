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

from pathlib import Path

from kunglao_log import warn  # canonical warn: ONE implementation

from rlvr import ledger as rl
from rlvr import posteriors as dts
from rlvr import q_cells
from rlvr.compose import method_family_of_row  # the settled-row face


class PosteriorStrategyStore:
    """THE StrategyStore implementation over the landed faces."""

    def __init__(self, ws):
        self.ws = Path(ws)
        self._qstore = q_cells.default_store(self.ws)
        self._weights: dict[str, float] | None = None

    # ------------------------------------------------ StrategyStore seam

    def method_lead(self, state_fingerprint: str) -> str | None:
        """One DTS draw over the measured proposal channel at this state
        (None = no proposal ever recorded at this workspace)."""
        prior = self._proposal_prior()
        if not prior:
            return None
        rng, _round = q_cells.q_cells_seed_state(self.ws)
        receipt = q_cells.sample_method_family(
            state_fingerprint, prior, self._qstore, rng=rng)
        return str(receipt["family"])

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
        try:
            import method_families  # noqa: PLC0415 — registry sibling
            registered = method_families.registered_tokens()
        except Exception as exc:  # noqa: BLE001 — registry best-effort
            warn("strategy_store.prior",
                 f"registry unreadable ({type(exc).__name__}: {exc}) — "
                 f"prior unfiltered; the #432 gate remains the "
                 f"enforcement face")
            registered = None
        if registered is not None:
            counts = {fam: n for fam, n in counts.items()
                      if fam in registered}
        total = sum(counts.values())
        if total <= 0:
            return {}
        return {fam: count / total
                for fam, count in sorted(counts.items())}

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
