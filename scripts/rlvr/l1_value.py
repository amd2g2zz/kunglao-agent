#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/l1_value.py — the L1 value function + the rollout return.

The three-layer ruling (2026-10-16): the orchestration layer had no
learner — the highest-leverage decisions (WHAT to do, WHEN, WHO) sat
outside the learning loop, and no rollout-level return was computed,
stored, or consumed anywhere. This module owns the L1 half of that
closure, mirroring the q_cells (L2) machinery one level up:

  return     ``R(τ) = Σ γ^t·r_t`` — the discounted SUM, terminal-
             dominated (#716). The mean is a DIFFERENT objective
             (average-reward) that dilutes the sparse terminal reward
             (claim PROVEN/REFUTED) toward zero. With the shipped
             potential-based shaping the sum telescopes:
             ``Σ r_t = Φ(s_T) − Φ(s_0) − Σcost + terminal settlement``
             — the length is absorbed by the math; the terminal is
             never normalized away. ``compute_rollout_return`` is the
             pure face; ``record_terminal_return`` reads the claim's
             transition chain (rlvr.incremental_reward rows, whose
             ``r_incr`` already carries ALPHA·ΔΦ − LAMBDA·cost) plus
             the terminal ladder credit and appends ONE observation.

  store      append-only ``runs/l1-value-log.jsonl`` rows
             {schema: l1-value-obs/1, ts, source, claim, action_kind,
             state_signature, return, steps, components}. Cells are
             keyed **(state_signature, action_kind)** — the canonical
             state (rlvr.state, the same signature the L2 cells key on)
             × the L1 action vocabulary (dispatch / park / split /
             verify / reuse: the owner ruling's list).

  fold       the q_cells DTS pattern: rows in append order, each
             decayed once per LATER row at THAT row's event-time γ (the
             no-peeking recurrence; the SHIPPED default is the #428
             adaptive schedule imported from rlvr.posteriors). A return
             splits into the two Beta masses — POSITIVE mass banks
             success, NEGATIVE mass banks failure, 0.0 banks nothing
             (the do-nothing outcome cannot displace the prior) — so a
             cell's posterior mean rises with positive returns and falls
             with losses, and the cold cell stays the wide Beta(1,1).

Learning state is part of s (the plan's single hub): the canonical
signature already carries the claim pattern and the attributed
obstacle inventory, so failure streaks and no-progress patterns enter
the value function as STATE FEATURES — never as trigger rules. Nothing
in this module reads a threshold like "N failures -> split"; the
planner's choices are DTS draws over these cells end to end.

Signal separation: the step-credit stream (rlvr.step_credit, banked at
SubagentStop) is L2's dense signal and NEVER enters this store; the
rollout return is L1's terminal signal and never enters the q cells.
Two signals, two consumers, no mixing (pinned by test).

Posture: recording is fail-open telemetry (an unwritable log is ONE
rate-limited warn, never an exception into the settlement path); reads
are tolerant (missing/dirty rows skip). No gate, no dispatch decision
imports this module — the planner is the sole consumer.

CLI: python scripts/rlvr/l1_value.py --table <ws>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol


if __package__ in (None, ""):
    # direct-path execution (python scripts/rlvr/l1_value.py): the
    # package parent (scripts/) is NOT on sys.path — insert it BEFORE
    # the sibling imports (the q_cells precedent).
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kunglao_log import iter_jsonl, warn

from rlvr import state as ssig  # the canonical signature face


SCHEMA_TAG = "l1-value/1"
OBS_SCHEMA = "l1-value-obs/1"
TABLE_SCHEMA = "l1-value-table/1"
OBS_REL = "runs/l1-value-log.jsonl"

# Beta(1,1) — the one aggregate uniform base (the q_cells precedent).
BASE_ALPHA = 1.0
BASE_BETA = 1.0

# The rollout discount (documented policy constant, NOT fitted): 1.0 is
# the shipped calibration face — the pure sum, which makes "terminal-
# dominated" literal (a terminal 1.0 is never diluted by step count, and
# the shaping telescopes exactly). The γ face exists for later
# equal-budget calibration; changing the shipped value follows the
# ADR-001 governance procedure (replay evidence + pins).
ROLLOUT_GAMMA = 1.0

# The L1 action vocabulary (owner ruling 2026-10-16): the closed list of
# WHAT the planner may choose. A new action is one edit here plus its
# cost model at the caller — never an ad-hoc string.
ACTION_KINDS = ("dispatch", "park", "split", "verify", "reuse")


class L1Store(Protocol):
    """The thin store seam — any append-order observation feed."""

    def observations(self) -> list[dict]: ...


class InMemoryStore:
    """The protocol stub — composition/tests, no filesystem."""

    def __init__(self, rows: Iterable[dict] | None = ()):
        self._rows = [dict(r) for r in (rows or ())]

    def observations(self) -> list[dict]:
        return list(self._rows)


class JSONLStore:
    """The default day-one store: runs/l1-value-log.jsonl (tolerant)."""

    def __init__(self, root):
        self.path = Path(root) / OBS_REL

    def observations(self) -> list[dict]:
        if not self.path.is_file():
            return []
        try:
            text = self.path.read_text(encoding="utf-8",
                                       errors="replace")
        except OSError as exc:
            from kunglao_log import warn  # noqa: PLC0415 — the canonical face
            warn("l1_value_log_read",
                 f"{type(exc).__name__}: {exc} — log reads as empty")
            return []
        return [row for row in iter_jsonl(text.splitlines())
                if isinstance(row, dict)]


def default_store(ws) -> L1Store:
    return JSONLStore(ws)


def has_observations(store: L1Store) -> bool:
    """True once the store carries at least one numeric return — the
    advisory face's dormancy gate (an empty store means every rank
    path stays byte-identical). Non-mapping rows are skipped (the
    q_cells filter — a hostile store never raises here)."""
    return any(isinstance(r, dict) and _return_of(r) is not None
               for r in store.observations())


# ---------------------------------------------------------------------------
# the rollout return (#716 semantics)
# ---------------------------------------------------------------------------

def _return_of(row: dict):
    """A row's numeric return; absent/non-numeric/bool/NaN -> None (the
    honest gap — never a fabricated 0)."""
    r = row.get("return")
    if isinstance(r, bool) or not isinstance(r, (int, float)):
        return None
    r = float(r)
    if r != r or r in (float("inf"), float("-inf")):
        return None
    return r


def _gamma_ok(gamma) -> float:
    if isinstance(gamma, bool) or not isinstance(gamma, (int, float)):
        raise ValueError(f"gamma must be numeric: {gamma!r}")
    g = float(gamma)
    if g != g or not (0.0 < g <= 1.0):
        raise ValueError(f"gamma must be in (0, 1]: {gamma!r}")
    return g


def compute_rollout_return(transitions, terminal_credit,
                           *, gamma: float = ROLLOUT_GAMMA) -> dict:
    """The pure return face: ``R(τ) = Σ γ^t·r_t`` over the claim's
    transition rewards (append order = time order) plus the terminal
    ladder credit at weight γ^T. The terminal weight is the LAST step's
    — with the shipped γ=1 the sum is exact and the telescope holds.
    Rows without a numeric ``r_incr`` contribute nothing (the honest
    gap). ``transitions_sum`` reports the undiscounted Σ r_incr so the
    discounted total never hides the raw chain."""
    g = _gamma_ok(gamma)
    total = 0.0
    raw = 0.0
    weight = 1.0
    steps = 0
    for row in transitions or ():
        if not isinstance(row, dict):
            continue
        value = row.get("r_incr")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        value = float(value)
        if value != value or value in (float("inf"), float("-inf")):
            continue          # non-finite is not a reward (the honest gap)
        raw += value
        total += weight * value
        weight *= g
        steps += 1
    terminal = float(terminal_credit)
    if terminal != terminal or terminal in (float("inf"), float("-inf")):
        raise ValueError(
            f"terminal_credit must be finite: {terminal_credit!r}")
    total += weight * terminal
    return {"schema": "l1-return/1",
            "return": round(total, 6),
            "steps": steps,
            "transitions_sum": round(raw, 6),
            "terminal": round(terminal, 6),
            "gamma": g}


def record_terminal_return(ws, claim, terminal_credit, *, signature=None,
                           action_kind: str = "dispatch",
                           gamma: float = ROLLOUT_GAMMA) -> dict:
    """The claim-terminal hook (scalar.settle_round_credit, first
    settlement only): read the claim's transition chain + the terminal
    ladder credit, compute the rollout return, append ONE observation
    keyed to the state the dispatch was chosen in (the ``signature`` the
    L2 dispatch row recorded — passed through the settlement bank).
    No dispatch-time signature = the honest gap: no row, ONE warn (a
    post-terminal state would key the wrong cell). Fail-open telemetry:
    a broken chain or store is a warn, never a settlement break."""
    try:
        cid = str(claim or "")
        if not cid:
            return {"recorded": False, "reason": "no-claim"}
        if not signature:
            warn("l1_value.record_terminal_return",
                 f"no dispatch-time state signature for {cid!r} — "
                 f"rollout return not banked (the honest gap)")
            return {"recorded": False, "reason": "no-state-signature",
                    "claim": cid}
        from rlvr import incremental_reward as _ir  # noqa: PLC0415
        rows = [r for r in _ir.read_transitions(ws)
                if str(r.get("dispatch_id") or "") == cid]
        out = compute_rollout_return(rows, terminal_credit, gamma=gamma)
        appended = record_observation(
            ws, str(signature), action_kind, out["return"], claim=cid,
            source="terminal", steps=out["steps"],
            components={"transitions_sum": out["transitions_sum"],
                        "terminal": out["terminal"],
                        "gamma": out["gamma"]})
        return {"recorded": bool(appended.get("appended")),
                "reason": appended.get("reason"),
                "claim": cid, "return": out["return"],
                "steps": out["steps"]}
    except Exception as exc:  # noqa: BLE001 — telemetry, never the settle
        warn("l1_value.record_terminal_return",
             f"{type(exc).__name__}: {exc}")
        return {"recorded": False, "reason": f"error:{type(exc).__name__}"}


# ---------------------------------------------------------------------------
# the recording face (append-only; fail-open on I/O, loud on vocabulary)
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
        warn("l1_value.append", f"{type(exc).__name__}: {exc}")
        return False


def record_observation(ws, state_signature, action_kind, ret, *,
                       claim: str | None = None, source: str = "manual",
                       steps: int | None = None,
                       components: dict | None = None,
                       ts: str | None = None) -> dict:
    """Append one rollout-return observation row. The action vocabulary
    is a closed wall (a bad kind is a caller bug — fail fast); the
    signature must be a 12-hex state hash or a snapshot mapping; the
    store I/O is fail-open (ONE warn, appended=False). ``steps`` (the
    transition count the return rides) is an additive column when
    given."""
    sig = _coerce_signature(state_signature)
    kind = str(action_kind or "")
    if kind not in ACTION_KINDS:
        raise ValueError(
            f"action_kind must be one of {ACTION_KINDS}: {action_kind!r}")
    if isinstance(ret, bool) or not isinstance(ret, (int, float)) \
            or float(ret) != float(ret) \
            or float(ret) in (float("inf"), float("-inf")):
        raise ValueError(f"return must be a finite number: {ret!r}")
    row = {
        "schema": OBS_SCHEMA,
        "ts": ts or _now(),
        "source": str(source),
        "claim": (str(claim) if claim else None),
        "state_signature": sig,
        "action_kind": kind,
        "return": round(float(ret), 6),
        **({"steps": int(steps)} if steps is not None else {}),
        **({"components": dict(components)} if components else {}),
    }
    appended = _append_row(Path(ws) / OBS_REL, row)
    return {"appended": appended,
            "reason": None if appended else "write-failed",
            "row": row}


_SIG_HASH_RE = None


def _coerce_signature(state_signature) -> str:
    """Snapshot dict -> canonical hash; 12-hex string passes through;
    anything else is a caller bug (the q_cells boundary face)."""
    global _SIG_HASH_RE
    if isinstance(state_signature, dict):
        return ssig.signature_hash(dict(state_signature))
    if isinstance(state_signature, str):
        if _SIG_HASH_RE is None:
            import re
            _SIG_HASH_RE = re.compile(r"^[0-9a-f]{12}$")
        if _SIG_HASH_RE.fullmatch(state_signature):
            return state_signature
    raise ValueError(
        f"state_signature must be a state_signature snapshot dict or a "
        f"12-hex signature hash; got {state_signature!r:.80}")


def state_signature_of(ws) -> str:
    """The workspace's canonical pre-decision state hash (rlvr.state —
    the same signature the L2 cells key on)."""
    return ssig.signature_hash(ssig.snapshot(ws))


# ---------------------------------------------------------------------------
# the fold (γ discount on the read face; raw rows never rewritten)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValueCounts:
    """One (state_signature, action_kind) cell's γ-discounted masses."""
    state_signature: str
    action_kind: str
    success: float = 0.0
    failure: float = 0.0
    n: int = 0

    @property
    def evidence(self) -> float:
        return self.success + self.failure


@dataclass(frozen=True)
class ValueFold:
    """The γ-discounted read view over a store's observations."""
    cells: dict[tuple[str, str], ValueCounts] = field(default_factory=dict)

    def cell(self, signature_hash: str, action_kind: str) -> ValueCounts:
        return self.cells.get(
            (signature_hash, action_kind),
            ValueCounts(signature_hash, action_kind))


class GammaSchedule(Protocol):
    def gamma(self) -> float: ...

    def observe(self, outcome) -> None: ...


def _resolve_schedule(gamma) -> GammaSchedule:
    """The γ face resolution (the q_cells contract): None → the SHIPPED
    default (the #428 adaptive schedule, imported — one source of truth);
    a number → a constant schedule; a schedule-like object → itself."""
    if gamma is None or (isinstance(gamma, (int, float))
                         and not isinstance(gamma, bool)):
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


def fold(store: L1Store, gamma=None) -> ValueFold:
    """DTS-discounted fold over the return stream — the q_cells
    recurrence, one level up: each row is decayed once per LATER row, at
    THAT row's event-time γ (no peeking), so for a constant γ the weight
    is exactly γ^age with age = append-order distance from the end of
    the stream (machine-independent; no wall clock). A row's return
    splits into the two Beta masses: success += w·max(R, 0), failure +=
    w·max(−R, 0) — a 0.0 return banks no mass but still counts as an
    observation (the do-nothing outcome cannot displace the prior).
    Rows without a numeric return are the honest gap: skipped."""
    schedule = _resolve_schedule(gamma)
    rows = [r for r in store.observations()
            if isinstance(r, dict) and _return_of(r) is not None]
    n = len(rows)
    gammas = [0.0] * n
    for i, row in enumerate(rows):
        gammas[i] = schedule.gamma()
        # the schedule reads the POSITIVE part (its [0,1] outcome band);
        # losses are failures, never a negative EMA input
        schedule.observe(max(_return_of(row), 0.0))
    weights = [1.0] * n
    w = 1.0
    for i in range(n - 2, -1, -1):
        w *= gammas[i + 1]
        weights[i] = w
    cells: dict[tuple[str, str], ValueCounts] = {}
    for i, row in enumerate(rows):
        ret = _return_of(row)
        weight = weights[i]
        key = (str(row.get("state_signature") or ""),
               str(row.get("action_kind") or ""))
        cell = cells.get(key) or ValueCounts(key[0], key[1])
        cells[key] = ValueCounts(
            key[0], key[1],
            success=cell.success + weight * max(ret, 0.0),
            failure=cell.failure + weight * max(-ret, 0.0),
            n=cell.n + 1)
    return ValueFold(cells)


def cell_posterior(fold_view: ValueFold, signature_hash: str,
                   action_kind: str) -> tuple[float, float]:
    """The cell's Beta posterior (alpha, beta). A nowhere-observed cell
    is the wide Beta(1,1) — cold actions still rank through their
    candidate priors."""
    cell = fold_view.cell(signature_hash, action_kind)
    return (BASE_ALPHA + cell.success, BASE_BETA + cell.failure)


def sample_value(fold_view: ValueFold, signature_hash: str,
                 action_kind: str, rng: random.Random) -> float:
    """One DTS draw θ ~ Beta(cell posterior) ∈ (0, 1) — the exploration
    engine: an evidence-poor cell draws wide, a settled-good cell draws
    near its mean, a settled-bad cell effectively never retried."""
    alpha, beta = cell_posterior(fold_view, signature_hash, action_kind)
    return rng.betavariate(alpha, beta)


def seed_state(ws) -> tuple[random.Random, int]:
    """The planner's seed source, mirroring the q_cells contract: a
    digest over the canonical fold payload PLUS the round axis (the
    convergence ledger's raw snapshot-row count, lazily imported). The
    sample moves when evidence moves OR the round advances; no wall
    clock anywhere."""
    from priority_ratio import round_index  # noqa: PLC0415
    rnd = round_index(ws)
    store = default_store(ws)
    schedule = _resolve_schedule(None)   # the shipped DTS default
    fold_view = fold(store, gamma=schedule)
    payload = {
        "cells": sorted(
            [sig, kind, round(c.success, 9), round(c.failure, 9), c.n]
            for (sig, kind), c in fold_view.cells.items()),
        "gamma_schedule": {"floor": schedule.gamma_floor,
                           "ema_lambda": schedule.ema_lambda},
        "round": rnd,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True,
                   ensure_ascii=False).encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16)), rnd


# ---------------------------------------------------------------------------
# CLI (offline face only — the sampler/planner are library calls)
# ---------------------------------------------------------------------------

def value_table(ws, gamma=None) -> dict:
    """The cell-table report over one workspace's L1 value log."""
    schedule = _resolve_schedule(gamma)
    fold_view = fold(default_store(ws), gamma=schedule)
    cells = []
    for c in sorted(fold_view.cells.values(),
                    key=lambda c: (c.state_signature, c.action_kind)):
        alpha, beta = cell_posterior(fold_view, c.state_signature,
                                     c.action_kind)
        cells.append({
            "state_signature": c.state_signature,
            "action_kind": c.action_kind,
            "success": round(c.success, 9),
            "failure": round(c.failure, 9),
            "n": c.n,
            "alpha": round(alpha, 6),
            "beta": round(beta, 6),
            "mean": round(alpha / (alpha + beta), 6),
        })
    return {"schema": TABLE_SCHEMA, "workspace": str(ws),
            "gamma": float(schedule.gamma()), "cells": cells}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rlvr.l1_value",
        description="L1 value store — rollout-return table (the live "
                    "faces are library calls: record_terminal_return "
                    "at claim terminal, the planner for choices)")
    ap.add_argument("--table", metavar="WS",
                    help="the (state, action) value-cell table")
    args = ap.parse_args(argv)
    if args.table:
        print(json.dumps(value_table(args.table), ensure_ascii=False,
                         indent=2))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
