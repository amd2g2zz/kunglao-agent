# -*- coding: utf-8 -*-
"""experience_triples.py — (s, a, r) triple extraction to
runs/triples.csv + the read-only Q report (issue 396, v0.1.6 RECORDING
face).

## Separated concerns (owner correction pins, 2026-09-27)

Learning samples = TRIPLES (s, a, r); the s column carries the canonical
state signature (state_signature.signature_str). The QUADRUPLE was
REJECTED (no s'/transition column — no bootstrap, group-relative
advantage, no critic); ΔV attribution and stall detection consume the
mainline situation snapshot stream (state_signature module), not tuple
columns.

Extraction is a DERIVED VIEW over the settlement currency the episode-settlement face
already produced — extraction NEVER re-scores:

  r sources: round_credit settlement rows (issue 379, per-dispatch round
  credit), the episode experience_tuple birth certificate (issues 379 + 388),
  the episode tier scalar, else the settled band reward.

## CSV contract (runs/triples.csv)

Header (byte-pinned):
  grain,rollout_id,s_signature,s_hash,a_arm,a_choices,r,r_source,ts

  grain      "round" (one row per round with credit — settled
             round_credit rows) | "episode" (one row per settled task
             rollout — the episode-settlement episode grain)
  s          state signature string + 12-hex hash AT EXTRACTION TIME
             (the settlement/terminal face); honest: the signature is
             the workspace state as the extraction face sees it
  a          strategy_arm + method_choices from the dispatch/eval faces:
             episode rows read the ledger signals (strategy_arm /
             method_choices) and the experience_tuple's a; round rows
             join runs/strategy-log.jsonl (event=dispatch rows) by claim
             id when the dispatch id IS a claim id
  r          the settled scalar (never recomputed here)

Regenerable: the ledger stays the system of record; extraction
overwrites the CSV deterministically (same inputs -> same bytes). An
empty ledger yields a header-only CSV.

## Q report (read-only)

``q_report`` — per-(s_hash, a_arm) empirical mean of r + sample count.
THE Q-table arithmetic (issue 386) as a banking-visibility REPORT: estimator =
per-cell mean arithmetic over the triple bank; no learning, no critic,
no Bellman updates. Cold start = no cells (the declared uniform prior is
the issue-386 dispatch face, v0.2). V(s) = expectation of Q over actions —
one estimator family. READ-ONLY: touches nothing.

ZERO DECISION POSTURE: pure reads + one derived-file write; never
imported by any dispatch, gate, or settlement face (pinned by
test_experience_freeze_396).
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import rollout_ledger as rl

TRIPLES_REL = "runs/triples.csv"
CSV_HEADER = ("grain", "rollout_id", "s_signature", "s_hash", "a_arm",
              "a_choices", "r", "r_source", "ts")
Q_REPORT_SCHEMA = "q-report/1"

_STRATEGY_LOG_REL = "runs/strategy-log.jsonl"

_WARN_LAST: dict[str, str] = {}


def warn(op: str, reason: str) -> None:
    """Rate-limited stderr WARN (the issue 276 _zof_warn pattern)."""
    if _WARN_LAST.get(op) == reason:
        return
    _WARN_LAST[op] = reason
    print(f"[kunglao-agent] experience_triples WARN (fail-open): "
          f"{op}: {reason}", file=sys.stderr)


def _last_signal(signals: list[dict], type_: str):
    """Last non-null signal value of one type (fold order = append order;
    the scalar_settlement._last semantics)."""
    val = None
    for s in signals or []:
        if str(s.get("type") or "") == type_:
            val = s.get("value")
    return val


def _strategy_arm_by_claim(ws) -> dict:
    """runs/strategy-log.jsonl event=dispatch rows: claim -> LAST strategy
    id (the strategy-log dispatch-pass-path writer; the per-claim arm face)."""
    p = Path(ws) / _STRATEGY_LOG_REL
    if not p.is_file():
        return {}
    out: dict[str, str] = {}
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or str(row.get("event")) != "dispatch":
            continue
        claim = str(row.get("claim") or "")
        strategy = str(row.get("strategy") or "")
        if claim and strategy:
            out[claim] = strategy
    return out


def _round_rows(ws) -> list[dict]:
    """One row per settled round_credit rollout (rounds WITH credit — the
    per-dispatch settlement the issue-379 face already wrote)."""
    arms = _strategy_arm_by_claim(ws)
    rows = []
    for row in rl.settled(ws, kind="round_credit"):
        st = row.get("settlement") or {}
        rid = str(row.get("rollout_id") or "")
        dispatch_id = rid.split("/", 1)[1] if "/" in rid else rid
        try:
            r = float(st.get("reward") or 0.0)
        except (TypeError, ValueError):
            r = 0.0
        rows.append({
            "grain": "round",
            "rollout_id": rid,
            "a_arm": arms.get(dispatch_id, ""),
            "a_choices": "",
            "r": r,
            "r_source": "round_credit",
            "ts": str(st.get("settled_ts") or row.get("ts") or ""),
        })
    return rows


def _episode_rows(ws) -> list[dict]:
    """One row per settled task rollout — the episode grain (the episode-settlement
    experience_tuple when present; the tier scalar / band reward as the
    honest fallback)."""
    rows = []
    for row in rl.settled(ws, kind="task"):
        st = row.get("settlement") or {}
        signals = row.get("signals") or []
        tup = st.get("experience_tuple")
        arm = choices = None
        if isinstance(tup, dict):
            a = tup.get("a") or {}
            arm = a.get("arm")
            choices = a.get("choices")
        if not arm:
            arm = _last_signal(signals, "strategy_arm")
        if not choices:
            choices = _last_signal(signals, "method_choices") or []
        if isinstance(tup, dict) and tup.get("r") is not None:
            r = float(tup["r"])
            r_source = "experience_tuple"
        elif "tier" in st:
            r = float(st.get("tier_reward") or 0.0)
            r_source = "tier_scalar"
        else:
            r = float(st.get("reward") or 0.0)
            r_source = "band_reward"
        rows.append({
            "grain": "episode",
            "rollout_id": str(row.get("rollout_id") or ""),
            "a_arm": str(arm or ""),
            "a_choices": ";".join(str(c) for c in (choices or [])),
            "r": r,
            "r_source": r_source,
            "ts": str(st.get("tier_settled_ts")
                      or st.get("settled_ts") or row.get("ts") or ""),
        })
    return rows


def extract(ws) -> dict:
    """Regenerate runs/triples.csv from the ledger (the system of record).
    Round rows first (append order), then episode rows. Returns
    {"rows", "path", "s_signature", "s_hash"}."""
    import state_signature as ssig
    ws = Path(ws)
    snap = ssig.snapshot(ws)
    sig = ssig.signature_str(snap)
    sig_hash = ssig.signature_hash(snap)
    rows = _round_rows(ws) + _episode_rows(ws)
    p = ws / TRIPLES_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(CSV_HEADER)
        for row in rows:
            writer.writerow([row["grain"], row["rollout_id"], sig,
                             sig_hash, row["a_arm"], row["a_choices"],
                             row["r"], row["r_source"], row["ts"]])
    return {"rows": len(rows), "path": str(p),
            "s_signature": sig, "s_hash": sig_hash}


def read_csv(ws) -> list[dict]:
    """Tolerant read of the derived view (missing -> [])."""
    p = Path(ws) / TRIPLES_REL
    if not p.is_file():
        return []
    try:
        with p.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def q_report(ws) -> dict:
    """READ-ONLY Q report: per-(s_hash, a_arm) empirical mean + count over
    the triple bank (the issue-386 estimator arithmetic, zero behavior —
    banking visibility). Cold start = no cells. Never writes."""
    cells: dict[tuple[str, str], list[float]] = {}
    total = 0
    for row in read_csv(ws):
        try:
            r = float(row.get("r") or 0.0)
        except (TypeError, ValueError):
            continue
        key = (str(row.get("s_hash") or ""), str(row.get("a_arm") or ""))
        cells.setdefault(key, []).append(r)
        total += 1
    out = [{"s_hash": k[0], "a_arm": k[1],
            "n": len(rs),
            "mean_r": round(sum(rs) / len(rs), 6)}
           for k, rs in sorted(cells.items())]
    return {"schema": Q_REPORT_SCHEMA, "cells": out, "rows": total}


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
