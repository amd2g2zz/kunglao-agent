#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""calibration_face.py — #134 rho/Platt calibration cockpit face (PRODUCE only).

The #823-P2 shadow accumulated (rho, z_self) pairs in the ledger "feeding
Platt calibration" while the calibration machinery idled. This module is
the graduation of the PRODUCER + DATA FACE — nothing else:

  1. Calibration curve + current gap: how well does the dense progress
     proxy (rho) predict the mechanical terminal anchor (z_self)?
     Reliability diagram over equal-width score bins (mean rho vs observed
     pass rate per bin), expected calibration error (ECE, the n-weighted
     mean |observed − predicted| gap), and current_gap = |rho − z| of the
     LATEST settled pair. Platt coefficients are the single-sourced
     rho_checkpoint.fit_platt (the #823 stdlib fit — no second logistic
     regression exists on this card).
  2. NO GATING. Consumption decisions belong to v0.2 (#129/#135). The face
     is read-only offline aggregation — the tuition_curve contract: ledger
     only, tolerant reads, 4-decimal rounding, nothing written back. A
     test pin (tests/test_calibration_face_134.py) fails the tree the day
     a gate module imports this face.
  3. Liveness: the rho sampler rides the #127 vocabulary —
     rho_verifier.sample_and_pair emits detector_eval per checkpoint
     sample and detector_fired when an anchor settles, so
     detector_liveness.liveness_report sees rho_sampler and a sampler
     whose pairs never settle is a loud DORMANT finding (statusline
     health dot + the face status below), never silence.

Face status vocabulary:
  ACTIVE   n_samples > 0 and n_pairs > 0 (settled anchors calibrate)
  DORMANT  n_samples > 0 and n_pairs == 0 (sampling fires, never settles)
  NO_DATA  no rho_pair rows at all (the sampler never ran)
"""
from __future__ import annotations



# issue 275 batch-3: fail-open handlers keep their liveness posture (never
# raise, never change the return shape) but must leave ONE trace - a stderr
# WARN naming the operation + reason, rate-limited to once per op until the
# reason changes (the _zof_warn pattern of issue 276; one ws per process,
# so op is the key).
import sys
_WARN_LAST: dict[str, str] = {}


def warn(op: str, reason: str) -> None:
    if _WARN_LAST.get(op) == reason:
        return
    _WARN_LAST[op] = reason
    print(f"[kunglao-agent] calibration_face WARN (fail-open): "
          f"{op}: {reason}",
          file=sys.stderr)
import json
from pathlib import Path

import rho_checkpoint
import rho_verifier

SCHEMA = "rho-calibration/1"
N_BINS = 5
_LEDGER_REL = Path("runs") / "logs"


# ---------------------------------------------------------------- curve

def curve(pairs: list[dict], n_bins: int = N_BINS) -> dict:
    """Settled (score, outcome) pairs -> reliability-curve face.

    bins: equal-width buckets over [0,1]; only bins that received pairs are
    listed (an empty bin is no observation, never a 0). ece: expected
    calibration error = n-weighted mean |observed − mean_score|, rounded
    4dp; None when there are no pairs (insufficient, never 0.0 — the
    winrate_curve zero-observations ruling). current_gap: |rho − z| of the
    LAST pair in ledger order (the most recent divergence actually
    observed); None when none. platt: the single-sourced
    rho_checkpoint.fit_platt coefficients (w, b) — the calibration the
    accumulated pairs would support today, DISPLAYED, never applied.
    """
    n_bins = max(int(n_bins), 1)
    acc: dict[int, dict] = {}
    for p in pairs or []:
        x, y = float(p["score"]), float(p["outcome"])
        b = acc.setdefault(min(int(x * n_bins), n_bins - 1),
                           {"n": 0, "sx": 0.0, "sy": 0.0})
        b["n"] += 1
        b["sx"] += x
        b["sy"] += y
    bins = []
    for i in sorted(acc):
        b = acc[i]
        mean_score = round(b["sx"] / b["n"], 4)
        observed = round(b["sy"] / b["n"], 4)
        bins.append({"lo": round(i / n_bins, 4),
                     "hi": round((i + 1) / n_bins, 4),
                     "n": b["n"], "mean_score": mean_score,
                     "observed": observed,
                     "gap": round(abs(observed - mean_score), 4)})
    n = len(pairs or [])
    ece = (round(sum(b["gap"] * b["n"] for b in bins) / n, 4)
           if n else None)
    current_gap = (round(abs(float(pairs[-1]["score"])
                             - float(pairs[-1]["outcome"])), 4)
                   if n else None)
    w, b0 = rho_checkpoint.fit_platt(list(pairs or []))
    return {"n": n, "bins": bins, "ece": ece, "current_gap": current_gap,
            "platt": {"w": round(w, 6), "b": round(b0, 6)}}


# -------------------------------------------------------------- liveness

def _n_samples(ws) -> int:
    """ALL rho_pair ledger rows (pending included) — the sampler's own
    evaluation counter, the denominator pairs_from_ledger's settled list
    is scored against. Tolerant read: blank/malformed/non-dict lines are
    skipped; missing files are an empty stream, never an error."""
    logs = Path(ws) / _LEDGER_REL
    n = 0
    try:
        paths = sorted(logs.glob("kunglao-*.jsonl"))
    except OSError:
        return 0
    for p in paths:
        try:
            lines = p.read_text(encoding="utf-8",
                                errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(r, dict) and r.get("action") == "rho_pair":
                n += 1
    return n


def face(ws) -> dict:
    """THE single-source calibration face (the rank_face shape).

    Settled pairs come from rho_verifier.pairs_from_ledger — the ledger
    replay is single-sourced, the face adds only the binning/aggregation
    and the sampler liveness counters. Fail-open: an unreadable ledger is
    the NO_DATA face (absence is no-data, not dormancy — the #127
    distinction: a sampler that never ran says nothing about whether
    rho predicts the anchor)."""
    try:
        pairs = rho_verifier.pairs_from_ledger(ws)
    except Exception as exc:  # noqa: BLE001 — a face never breaks the snapshot
        warn("pairs_replay", f"{type(exc).__name__}: {exc}")
        pairs = []
    try:
        n_samples = _n_samples(ws)
    except Exception as exc:  # noqa: BLE001 — a face never breaks the snapshot
        warn("samples_count", f"{type(exc).__name__}: {exc}")
        n_samples = len(pairs)
    if n_samples > 0:
        status = "ACTIVE" if pairs else "DORMANT"
    else:
        status = "NO_DATA"
    return {"schema": SCHEMA, "status": status,
            "n_samples": n_samples, "n_pairs": len(pairs),
            **curve(pairs)}


def summarize(data: dict) -> str:
    """Text face (cockpit text rendering). DORMANT is loud, by name."""
    data = data or {}
    status = data.get("status") or "NO_DATA"
    n_samples, n_pairs = data.get("n_samples", 0), data.get("n_pairs", 0)
    if status == "DORMANT":
        return (f"rho-calibration: DORMANT — {n_samples} checkpoint "
                f"samples, 0 settled (rho, z) pairs; the dense proxy never "
                f"met a terminal anchor (#127: evaluated, never fired)")
    if status == "NO_DATA":
        return ("rho-calibration: NO_DATA — no rho_pair rows in the "
                "ledger (rho sampler never ran)")
    platt = data.get("platt") or {}
    lines = [f"rho-calibration: ACTIVE n={n_pairs} samples={n_samples} "
             f"ece={data.get('ece')} current_gap={data.get('current_gap')} "
             f"platt(w={platt.get('w')}, b={platt.get('b')})"]
    for b in data.get("bins") or []:
        lines.append(f"  [{b['lo']:.1f},{b['hi']:.1f}) n={b['n']} "
                     f"rho={b['mean_score']} z={b['observed']} "
                     f"gap={b['gap']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
