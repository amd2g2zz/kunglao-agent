#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""termination.py — the option-death estimator (issue 461 Phase 2:
Bayesian option-death termination for method families).

The learned "when to quit" in Option-Critic form, bandit realization:
termination is a posterior INSIDE the option (β(s) — a termination
function of the option, never a sibling arm), attribution-in-state is
the discriminator, and NOTHING here is a rule or gate — the module's
entire actuation surface is a sampling-weight multiplier that the DTS
sampler applies when a verdict is threaded into it (dead options
sample at ARM_FLOOR, never removed: the PARK posture — suspension on
posterior evidence, revivable by the same posterior).

## Posterior — Beta per (obstacle-kind, method-family)

    cell (K, F):  α = PRIOR_ALPHA + n_rows(kind=K, family=F)
                  β = PRIOR_BETA  + alive_mass(F)

DEATH evidence is an obstacle/1 ROW — an ATTRIBUTED failure (the
cause was pinned by an intervention probe; the registry gate already
enforced artifact existence + probe-marker shape at record time). A
timeout, a settled failure, or any cause-free failure contributes
NOTHING (the owner's core ruling: cause-free failures trigger the
attribution protocol, never termination). ALIVE evidence is outcome
correlation: the family's γ-discounted SUCCESS mass from the q-cell
fold (family-level pooling — settlement rows carry signature hashes,
not kinds, so no kind-keyed alive join exists; disclosed coarseness).
Aging asymmetry: death counts are lifetime integers while alive mass
decays under the fold's uniform tree γ — accepted, bounded by the
floor (any floor-weighted success re-banks alive mass at full weight
and revives the option; the same fold runs both directions).

Keying on the kind SEGMENT of the state signature, not the full hash:
ob= is cumulative (every recorded failure advances the signature), so
exact-hash keys fragment and repetition can never accumulate; the
closed 5-kind enum keeps the key space bounded and is exactly the
discriminable cause vocabulary the ob= dim was built from. Within a
live workspace every registry kind is always present in any snapshot,
so the kind-conditioning is the foreign-snapshot guard; the live
in-workspace floor is family-global and the operative discriminator
is the family-level alive mass.

## Decision — mean ≥ DEATH_THRESHOLD, floor-not-delete

    option_dead(F | s) ⇔ ∃ kind K ∈ kinds(s): mean(cell(K, F)) ≥ 0.75

Policy constants (ADR-001 posture — rationale carried, never runtime
tuned): DEATH_THRESHOLD 0.75 (with zero alive mass, one attributed
failure gives 2/3 — alive; two give exactly 3/4 — dead: "repeated"
means ≥ 2; each unit of alive mass costs ≈ 3 further deaths), ARM_FLOOR
0.1 (per-family weight RATIO 1:10 against an alive competitor; in the
multi-floor endgame k-of-m floored, each carries ≈ 0.1/(m−k+0.1k) of
the uniform-prior mass). Comparisons run on the computed float64 mean;
only the alive-mass-zero crossings are exactly representable. The
budget forced-closure stays the safety bound, orthogonal and
untouched: if the posteriors are wrong, the failure mode is bounded
exploration loss at floor weight, never an unbounded loop.

## Derived, not persisted

A PURE fold over two landed registries (obstacles + the q-cell log):
no new store, no write path, no dual-write hazard. Receipts are
deterministic (sorted cells, no wall clock; same workspace state →
same bytes). ZERO-REGISTRY RULE: verdicts() returns {} when no
obstacle row exists — the sampler hosts then thread no death kwarg at
all, so a day-one workspace's receipts are byte-identical to the
pre-change kernel, not just its draws.

## Consumers (both production sampler hosts, fail-open)

strategy_store.method_lead (the advisory compose lead) and
e2e/checkpoints._sample_envelope_family (the envelope sampler — the
action-selection site) compute verdicts(ws, prior.keys()) inside a
fail-open try/except and thread them into q_cells.sample_method_family
as the duck-typed ``death`` kwarg. The sampler itself never imports
this module or obstacles (import-direction wall: verdicts are DATA,
not imports). No gate, dispatch, or settlement face reads this module
as an enforcement input.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    # direct-path execution (python scripts/rlvr/termination.py): the
    # package parent (scripts/) is NOT on sys.path — insert it BEFORE
    # the sibling imports (the q_cells/obstacles precedent); the guard
    # leaves the import-time path untouched for rlvr.termination
    # consumers
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SCHEMA = "option-death/1"

# Policy constants (ADR-001 posture: documented rationale, never
# runtime self-tuning — changing either follows the replay-evidence +
# pins governance procedure, not a config flag).
DEATH_THRESHOLD = 0.75
ARM_FLOOR = 0.1

# the one uniform base (q_cells.BASE_* / posteriors.PRIOR_* idiom)
PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0

# canonical warn: ONE implementation (process-wide dedupe + ledger face)
from kunglao_log import warn  # noqa: E402


# ---------- internals (pure; lazy imports keep this module light) ----------


def _registry_rows(ws):
    """Tolerant obstacle-registry read (the recording face's own
    reader — never a second validator). Any failure degrades to []."""
    try:
        from rlvr import obstacles  # noqa: PLC0415 — lazy (state.py idiom)

        return obstacles.read(ws)
    except Exception as exc:  # noqa: BLE001 — fail-open read
        warn("termination.registry", f"{type(exc).__name__}: {exc}")
        return []


def _kinds_of(snap) -> frozenset[str] | None:
    """The kind names present in one snapshot's ob= pattern; None when
    the snapshot is unusable (fail-open: no filtering — every cell
    counts). The pattern is the sorted ``kind=count`` join; '' (no
    rows) parses to the EMPTY set (nothing counts — honest absence)."""
    try:
        face = (snap or {}).get("obstacles") or {}
        kinds = face.get("kinds")
        if not isinstance(kinds, str) or not kinds:
            return frozenset()
        return frozenset(part.split("=", 1)[0] for part in kinds.split("|") if part)
    except Exception:  # noqa: BLE001 — malformed snapshot: no filter
        return None


def _present_kinds(ws, snap):
    """Kinds in force for the decision: the caller's snapshot when
    given, else the CURRENT workspace signature (state.snapshot). Any
    read failure degrades to None (NO filtering — disclosed: the
    degrade can only let cells count that a snapshot would have
    excluded; it is a broken-workspace condition, and the budget
    forced-closure remains the safety bound)."""
    if snap is not None:
        return _kinds_of(snap)
    try:
        from rlvr import state  # noqa: PLC0415 — lazy

        return _kinds_of(state.snapshot(ws))
    except Exception:  # noqa: BLE001 — fail-open read
        return None


def _alive_masses(ws, families) -> dict[str, float]:
    """Per-family γ-discounted SUCCESS mass from the q-cell fold (the
    shipped DTS default schedule — one engine, imported, never
    duplicated). Pure read; any failure degrades to zero mass."""
    if not families:
        return {}
    try:
        from rlvr import posteriors, q_cells  # noqa: PLC0415 — lazy

        schedule = posteriors.default_schedule()
        fold_view = q_cells.fold(q_cells.default_store(ws), gamma=schedule)
        return {f: float(fold_view.family_mass(f)[0]) for f in sorted(set(families))}
    except Exception as exc:  # noqa: BLE001 — fail-open read
        warn("termination.alive", f"{type(exc).__name__}: {exc}")
        return {f: 0.0 for f in sorted(set(families))}


def _post_gamma(ws) -> float:
    """The fold's post-replay γ (the band the engine believes in after
    the whole stream) — the report's determinism/audit field."""
    try:
        from rlvr import posteriors, q_cells  # noqa: PLC0415 — lazy

        schedule = posteriors.default_schedule()
        q_cells.fold(q_cells.default_store(ws), gamma=schedule)
        return float(schedule.gamma())
    except Exception:  # noqa: BLE001 — fail-open read
        return 1.0


def _death_counts(rows) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (str(row.get("kind") or ""), str(row.get("method_family") or ""))
        if key[0] and key[1]:
            counts[key] = counts.get(key, 0) + 1
    return counts


def _cell(alpha: float, beta: float) -> dict:
    """One cell's posterior face: dead is decided on the UNROUNDED
    float64 mean; p_dead is the receipt's 9-dp rounding (display)."""
    mean = alpha / (alpha + beta)
    return {
        "alpha": alpha,
        "beta": beta,
        "p_dead": round(mean, 9),
        "dead": bool(mean >= DEATH_THRESHOLD),
    }


# ---------- the report (deterministic receipt; cell-level) ----------


def report(ws, snap=None) -> dict:
    """The option-death receipt over one workspace: cells sorted by
    (kind, family) with deaths/alpha/beta/p_dead/dead, the per-family
    alive mass, threshold, floor, and the fold's post-replay γ. NO
    wall clock — the same workspace state produces the same bytes.
    Cell-level (no snapshot conditioning): the state conditioning
    belongs to the VERDICT faces. Fail-open: absent/corrupt inputs are
    the empty report, never a raise."""
    ws = Path(ws)
    rows = _registry_rows(ws)
    counts = _death_counts(rows)
    families = sorted({fam for _, fam in counts})
    alive = _alive_masses(ws, families)
    cells = []
    for kind, family in sorted(counts):
        cell = _cell(PRIOR_ALPHA + counts[(kind, family)], PRIOR_BETA + alive.get(family, 0.0))
        cells.append({"kind": kind, "family": family, "deaths": counts[(kind, family)], **cell})
    dead_families = sorted({c["family"] for c in cells if c["dead"]})
    return {
        "schema": SCHEMA,
        "threshold": DEATH_THRESHOLD,
        "arm_floor": ARM_FLOOR,
        "gamma": round(_post_gamma(ws), 9),
        "alive_mass": {f: round(alive.get(f, 0.0), 9) for f in families},
        "cells": cells,
        "dead_families": dead_families,
    }


# ---------- the verdict faces (state-conditioned decision) ----------


def verdicts(ws, families, snap=None) -> dict[str, dict]:
    """Per-family termination verdicts for the sampler hosts.

    The decision face: dead iff any kind PRESENT in the snapshot's ob=
    pattern carries a cell with posterior mean ≥ DEATH_THRESHOLD; the
    reported cell is the argmax-mean present-kind cell; a family with
    no present-kind cells gets the BASE cell Beta(1, 1 + alive_mass) —
    structurally never dead without death evidence. ZERO-REGISTRY
    RULE: no obstacle rows at all -> {} (the hosts thread no kwarg;
    day-one receipts stay byte-identical to the pre-change kernel)."""
    ws = Path(ws)
    rows = _registry_rows(ws)
    if not rows:
        return {}
    counts = _death_counts(rows)
    present = _present_kinds(ws, snap)
    wanted = sorted({str(f) for f in families if str(f)})
    alive = _alive_masses(ws, wanted)
    out: dict[str, dict] = {}
    for family in wanted:
        best: dict | None = None
        for (kind, fam), n in sorted(counts.items()):
            if fam != family or n <= 0:
                continue
            if present is not None and kind not in present:
                continue  # the foreign-snapshot guard
            cell = _cell(PRIOR_ALPHA + n, PRIOR_BETA + alive.get(family, 0.0))
            if best is None or cell["p_dead"] > best["p_dead"]:
                best = {**cell, "kind": kind}
        if best is None:
            best = {**_cell(PRIOR_ALPHA, PRIOR_BETA + alive.get(family, 0.0)), "kind": None}
        dead = best["dead"]
        out[family] = {
            "family": family,
            "dead": dead,
            "p_dead": best["p_dead"],
            "kind": best["kind"],
            "alpha": best["alpha"],
            "beta": best["beta"],
            "weight_multiplier": ARM_FLOOR if dead else 1.0,
            "threshold": DEATH_THRESHOLD,
        }
    return out


def option_dead(ws, family: str, snap=None) -> dict:
    """The single-family decision face (always answers — unlike
    verdicts, which returns {} on a zero registry so hosts can skip
    the kwarg entirely)."""
    family = str(family)
    out = verdicts(ws, [family], snap=snap)
    if out:
        return out[family]
    # zero registry: the base cell — structurally never dead
    alive = _alive_masses(ws, [family])
    return {
        "family": family,
        "dead": False,
        "p_dead": round(PRIOR_ALPHA / (PRIOR_ALPHA + PRIOR_BETA + alive.get(family, 0.0)), 9),
        "kind": None,
        "alpha": PRIOR_ALPHA,
        "beta": PRIOR_BETA + alive.get(family, 0.0),
        "weight_multiplier": 1.0,
        "threshold": DEATH_THRESHOLD,
    }


# ---------- CLI (offline diagnostic; live faces are library calls) ----------


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="option-death termination estimator (issue 461 "
        "Phase 2) — the deterministic report face; the "
        "verdict faces are library calls consumed by the "
        "sampler hosts"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    rep = sub.add_parser("report", help="print the option-death report")
    rep.add_argument("ws", help="workspace root")
    args = ap.parse_args(argv)
    if args.cmd == "report":
        print(json.dumps(report(args.ws), ensure_ascii=False, indent=2))
        return 0
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI face
    sys.exit(main())
