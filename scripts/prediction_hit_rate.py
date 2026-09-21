#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prediction_hit_rate.py — issue-135 prediction-calibration metric.

Success rate measures OUTCOMES; prediction error measures the WORLD MODEL
(issue-135 thesis). A loop can succeed by luck while its predictions are
persistently wrong — winrate_curve (issue 156) measures the former and cannot
see the latter. This face computes the second-order statistic from the
issues-110/146 case-bank rows, where the join is free: intent_uncertainty (the
DECLARED confidence, mirrored verbatim from the settled intent) and
roi_class (the settled outcome class) are co-located per row.

Counting contract (mirrors winrate_curve, owner-approved conventions):
  - scored observations = roi_class POSITIVE or NEGATIVE only. NEUTRAL /
    UNRESOLVED rows are settlements but never hit-rate observations
    (roi_settlement ruling 2) — they never enter a denominator.
  - a row is a COMMITTED prediction ("predicted") when its declared
    uncertainty text carries NO hedge keyword; a row carrying any hedge
    keyword is "declared-uncertain". The hedge vocabulary is the named
    constant UNCERTAINTY_KEYWORDS — case-insensitive substring match.
  - hit  = predicted row landed POSITIVE.
    miss = predicted row landed NEGATIVE (the wrong prediction).
    hit_rate  = hits / committed  (None when nothing committed).
    success_rate = POSITIVE / scored  (the issue-156 outcome rate, recomputed
    here over the bank mirror so luck-vs-skill is visible in ONE face).
  - rate rounding: 4 decimals (tuition_curve convention); zero
    denominators -> None (insufficient, never 0.0). A 0% hit rate with
    predictions committed is a REAL 0.0 and renders (alarm state).

Rolling window: DEFAULT_WINDOW consecutive scored-row chunks (winrate_curve
window convention; last window may be partial — its own counts stand).
Per-window hit_rate is None when the window committed nothing.

V0.1.6 slice — PRODUCE ONLY: this face is cockpit production (statusline
snapshot display, issue-212 perf face). No ranker / gate reads it; consumption
is v0.2 issue 129. The zero-consumption pin lives in
tests/test_prediction_hit_rate_135.py (TestZeroConsumptionPin).

Face read stream (tolerant — blank / malformed / non-dict rows are
skipped; a missing bank is an EMPTY stream, never an error):
  runs/case-bank.jsonl — case_bank.py schema (read_entries).

Schema: prediction-hit-rate/1
"""
from __future__ import annotations

import argparse
import json
import sys

from case_bank import ROI_CLASSES, read_entries

SCHEMA = "prediction-hit-rate/1"

# Rolling window over the scored bank stream (winrate_curve window
# convention); named per the issue-135 card. Window sizes below 1 clamp to 1.
DEFAULT_WINDOW = 5

# Hedge vocabulary — tokens that mark a declared uncertainty as
# UNCOMMITTED (the loop hedged instead of predicting). Case-insensitive
# substring match over intent_uncertainty. A declared uncertainty names
# WHAT is unknown by design (ruling 3), so unknown-nouns ("which builder")
# are not hedges; confidence MODIFIERS are. English + the Chinese tokens
# the repo's declaration vocabulary already uses (cf. summary_discriminator
# 暂定/未确认 family).
UNCERTAINTY_KEYWORDS = (
    "maybe", "possibly", "perhaps", "might", "may not", "might not",
    "could be", "unclear", "uncertain", "unconfirmed", "unverified",
    "speculative", "suspected", "tentative",
    "可能", "或许", "也许", "未确认", "未证实", "推测", "存疑", "暂定",
)


def hedged_keywords(text) -> list[str]:
    """Hedge keywords present in a declared-uncertainty text, tuple order,
    deduped — empty list = the row COMMITTED (a firm prediction)."""
    t = str(text or "").lower()
    out: list[str] = []
    for kw in UNCERTAINTY_KEYWORDS:
        if kw in t and kw not in out:
            out.append(kw)
    return out


def _rate(num: int, den: int):
    """Share with 4-decimal rounding; None when nothing to divide."""
    return round(num / den, 4) if den else None


def classify_row(row: dict) -> tuple[bool, list[str]]:
    """(is_scored, hedge_keywords) for one banked row."""
    return (str(row.get("roi_class") or "") in ("POSITIVE", "NEGATIVE"),
            hedged_keywords(row.get("intent_uncertainty")))


def face(ws, window: int = DEFAULT_WINDOW) -> dict:
    """Case bank -> the prediction hit-rate face.

    Empty / missing bank -> the empty face (n_rows_read 0, rates None).
    One bank read per face: n_rows_read and every series share a snapshot.
    Window sizes below 1 clamp to 1."""
    ws = str(ws)
    window = max(int(window), 1)
    rows = read_entries(ws)  # ONE read: counts and series share a snapshot

    scored: list[dict] = []
    for row in rows:
        is_scored, kws = classify_row(row)
        if not is_scored:
            continue
        scored.append({"row": row, "positive": row.get("roi_class")
                       == "POSITIVE", "hedged": bool(kws), "kws": kws})

    pos = sum(1 for s in scored if s["positive"])
    neg = len(scored) - pos
    committed = [s for s in scored if not s["hedged"]]
    hits = sum(1 for s in committed if s["positive"])
    misses = len(committed) - hits

    by_class = {cls: {"n": 0, "predicted": 0, "uncertain": 0,
                      "hits": 0, "misses": 0} for cls in ROI_CLASSES}
    by_keyword: dict[str, dict] = {}
    for row in rows:
        is_scored, kws = classify_row(row)
        cls = str(row.get("roi_class") or "")
        if cls in by_class:
            # class composition counts EVERY row (an unscored settlement is
            # still a banked case — visible as n, never a denominator);
            # predicted/uncertain/hits/misses stay scored-only (ruling 2).
            by_class[cls]["n"] += 1
        if not is_scored:
            continue
        positive = row.get("roi_class") == "POSITIVE"
        bucket = by_class[cls]
        bucket["predicted" if not kws else "uncertain"] += 1
        if not kws:
            bucket["hits" if positive else "misses"] += 1
        for kw in kws:
            k = by_keyword.setdefault(
                kw, {"n": 0, "positive": 0, "negative": 0})
            k["n"] += 1
            k["positive" if positive else "negative"] += 1
    for k in by_keyword.values():
        k["rate"] = _rate(k["positive"], k["n"])

    windowed = []
    for wi, start in enumerate(range(0, len(scored), window)):
        chunk = scored[start:start + window]
        c_committed = [s for s in chunk if not s["hedged"]]
        c_hits = sum(1 for s in c_committed if s["positive"])
        windowed.append({
            "index": wi, "start": start, "end": start + len(chunk),
            "n": len(chunk), "predicted": len(c_committed),
            "hits": c_hits, "hit_rate": _rate(c_hits, len(c_committed))})

    return {
        "schema": SCHEMA,
        "window": window,
        "n_rows_read": len(rows),
        "n_scored": len(scored),
        "overall": {
            "positive": pos, "negative": neg,
            "predicted": len(committed), "uncertain": len(scored) - len(committed),
            "hits": hits, "misses": misses,
            "hit_rate": _rate(hits, len(committed)),
            "success_rate": _rate(pos, len(scored)),
        },
        "windowed": windowed,
        "by_roi_class": by_class,
        "by_keyword": dict(sorted(by_keyword.items())),
    }


def summarize(data: dict) -> str:
    """Text summary (cockpit text face)."""
    data = data or {}
    n = data.get("n_scored") or 0
    if not n:
        return ("prediction-hit-rate: no scored bank rows "
                "(POSITIVE/NEGATIVE) — empty face")
    ov = data.get("overall") or {}
    lines = [f"prediction-hit-rate: n={n} predicted={ov.get('predicted')} "
             f"hits={ov.get('hits')} misses={ov.get('misses')} "
             f"hit_rate={ov.get('hit_rate')} "
             f"success_rate={ov.get('success_rate')} "
             f"(window={data.get('window')})"]
    for w in data.get("windowed") or []:
        lines.append(f"  window {w['index']} [{w['start']}:{w['end']}) "
                     f"predicted={w['predicted']} hits={w['hits']} "
                     f"hit_rate={w['hit_rate']}")
    for cls in ROI_CLASSES:
        b = (data.get("by_roi_class") or {}).get(cls) or {}
        if b.get("n"):
            lines.append(f"  class {cls}: n={b['n']} "
                         f"predicted={b['predicted']} uncertain={b['uncertain']}"
                         f" hits={b['hits']} misses={b['misses']}")
    for kw, k in (data.get("by_keyword") or {}).items():
        lines.append(f"  hedge {kw}: n={k['n']} (P={k['positive']} "
                     f"N={k['negative']}) rate={k.get('rate')}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI: python prediction_hit_rate.py <ws> [--json] [--window N]"""
    ap = argparse.ArgumentParser(
        prog="prediction_hit_rate.py",
        description="#135 prediction hit-rate — rolling prediction-error "
                    "metric over the case bank (offline aggregator, "
                    "PRODUCE only)")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable face on stdout")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                    help=f"rolling window size (default {DEFAULT_WINDOW})")
    args = ap.parse_args(argv)
    data = face(args.workspace, window=args.window)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(summarize(data))
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
