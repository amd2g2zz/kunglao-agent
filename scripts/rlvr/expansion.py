#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/expansion.py — the discovery-layer operator (issue #546, WS4 /
L3: the ONLY layer that can exceed historical experience).

The capture-refusal verdict named the missing second-order operator:
when a claim's obstacles accumulate AND the tried arms' posteriors have
collapsed, the system's full response surface today is retry-within-
vocabulary plus bookkeeping — the DLL that needs "write a custom
Themida-stub emulator" can never be proposed. This module is that
operator's mechanical face:

  - ``trigger``: the move fires when (a) the workspace's obstacle
    evidence reaches EXPAND_OBSTACLE_K rows and (b) at least one tried
    family is termination-dead. It reads ONLY sanctioned faces — the
    state snapshot's obstacle digest (rlvr.state, the 396 freeze wall:
    this module NEVER imports rlvr.obstacles) and the termination
    verdicts (the registry's one sanctioned consumer precedent;
    expansion is sanctioned consumer #2 per the #546 charter note).
  - ``score``: admission = ``log P_LLM + policy + NOVELTY_WEIGHT x
    novelty`` where novelty is FEATURE-KEYED — 1 minus the max Jaccard
    of the hypothesis's canonical feature tokens against every
    existing arm's tokens (feature_prior.jaccard). A renamed dead arm
    is the same tokens, Jaccard 1, novelty 0: the anti-novelty-hacking
    wall (string novelty is gameable; token novelty is not).
  - ``admit``: top-EXPAND_HYPOTHESES_N by total among hypotheses with
    novelty strictly > 0 — a zero-novelty hypothesis is a retry in a
    new name and never spends the move. Admission is verifier-GATED in
    the receipt (``verdict: "pending"``) — the wiring dispatches the
    gate; this module never promotes ungated.
  - ``record_receipt``: one ``runs/expansion/E-<n>.json`` per move
    (schema expansion/1) carrying the full provenance chain:
    obstacle digest -> collapsed arms -> hypotheses with per-score
    decomposition -> admitted ids. Append-only by index.

New arms admitted here seed cold with the WS3 model prior at the
wiring face (priors.seed_intake_prior families=) — not this module's
job. Constants (3, the WS4 budget): EXPAND_OBSTACLE_K,
EXPAND_HYPOTHESES_N, NOVELTY_WEIGHT.

Usage:
    python scripts/rlvr/expansion.py <workspace> --check   # trigger probe
"""
from __future__ import annotations

import json
import math
from pathlib import Path

if __package__ in (None, ""):
    # direct-path execution: scripts/ is NOT on sys.path (path[0] is
    # scripts/rlvr/) — insert it before sibling imports (the q_cells
    # direct-execution pattern)
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _common import utc_now_z
from rlvr.feature_prior import feature_tokens, jaccard

SCHEMA = "expansion/1"
RECEIPT_DIR = "runs/expansion"

#: obstacle rows (state digest count) required before a move may fire
EXPAND_OBSTACLE_K = 3
#: hypotheses one move may admit (the budget the move spends)
EXPAND_HYPOTHESES_N = 3
#: novelty term weight in the admission score
NOVELTY_WEIGHT = 1.0

_LOG_FLOOR = 1e-12  # log(0) guard — a zero P_LLM floors, never crashes


def trigger(snap: dict, death: dict | None,
            obstacle_k: int = EXPAND_OBSTACLE_K) -> dict | None:
    """The move's predicate over SANCTIONED faces only: the state
    snapshot's obstacle digest ({"obstacles": {"count": n}} — rlvr.state
    owns the read; this module never touches the registry) plus the
    termination verdicts ({family: {"dead": bool}}). Returns the trigger
    receipt ({"obstacle_count", "collapsed_arms"}) or None — never an
    exception, never a partial fire."""
    if not isinstance(snap, dict) or not isinstance(death, dict):
        return None
    count = int((snap.get("obstacles") or {}).get("count") or 0)
    if count < obstacle_k:
        return None
    collapsed = sorted(
        str(fam) for fam, v in death.items()
        if isinstance(v, dict) and bool(v.get("dead")))
    if not collapsed:
        return None
    return {"obstacle_count": count, "collapsed_arms": collapsed}


def novelty(hyp_features: dict,
            existing_features: list[dict]) -> float:
    """Feature-keyed novelty: 1 − max Jaccard of the hypothesis's
    canonical tokens against EVERY existing arm's tokens (dead or
    alive — a renamed dead arm is the anti-case). No existing arms ⇒
    1.0 (nothing shared with nothing)."""
    hyp_tokens = feature_tokens(hyp_features)
    best = 0.0
    for features in existing_features or []:
        overlap = jaccard(hyp_tokens, feature_tokens(features))
        if overlap > best:
            best = overlap
    return 1.0 - best


def score(p_llm: float, policy_score: float, novelty_value: float) -> dict:
    """The admission decomposition — every term attributable, no
    hidden normalization. ``policy_score`` arrives from the caller (the
    fold's posterior mean for the nearest existing arm); P_LLM floors
    at _LOG_FLOOR so a zero proposal never crashes the log."""
    log_p = math.log(max(float(p_llm), _LOG_FLOOR))
    nov = max(0.0, min(1.0, float(novelty_value)))
    return {
        "log_p_llm": round(log_p, 6),
        "policy": round(float(policy_score), 6),
        "novelty": round(nov, 6),
        "total": round(log_p + NOVELTY_WEIGHT * nov + float(policy_score), 6),
    }


def admit(hypotheses: list[dict], existing_features: list[dict],
          n: int = EXPAND_HYPOTHESES_N) -> list[dict]:
    """Rank the move's candidate hypotheses: each carries ``features``
    (the token source), ``p_llm``, and ``policy``. Zero-novelty
    candidates are excluded BEFORE ranking (a retry under a new name
    never spends the move); ties break by id (deterministic). The
    returned rows carry the full score decomposition and
    ``verdict: "pending"`` — the verifier gate is dispatched by the
    wiring, never assumed here."""
    ranked: list[dict] = []
    for hyp in hypotheses or []:
        feats = hyp.get("features") or {}
        nov = novelty(feats, existing_features)
        if nov <= 0.0:
            continue
        row = {
            "id": str(hyp.get("id") or ""),
            "family": str(hyp.get("family") or ""),
            "score": score(hyp.get("p_llm", _LOG_FLOOR),
                           hyp.get("policy", 0.0), nov),
            "verdict": "pending",
        }
        ranked.append(row)
    ranked.sort(key=lambda r: (-r["score"]["total"], r["id"]))
    return ranked[:max(0, int(n))]


def record_receipt(ws, trigger_doc: dict, hypotheses: list[dict],
                   admitted: list[dict]) -> dict:
    """Append the move's receipt as ``runs/expansion/E-<n>.json`` (next
    index — append-only, never rewritten). Fail-loud on OSError (the
    receipt IS the provenance chain; a silent miss would orphan the
    move) — the wiring catches and warns."""
    ws = Path(ws)
    directory = ws / RECEIPT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    index = 1
    while (directory / f"E-{index}.json").exists():
        index += 1
    doc = {
        "schema": SCHEMA,
        "ts": utc_now_z(),
        "trigger": trigger_doc,
        "hypotheses": hypotheses,
        "admitted": [str(h) for h in admitted],
    }
    path = directory / f"E-{index}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True,
                               indent=2) + "\n", encoding="utf-8")
    return doc


def read_receipts(ws) -> list[dict]:
    """All receipts, index order, tolerant of absence/corruption (an
    unreadable receipt is skipped — history stays readable)."""
    directory = Path(ws) / RECEIPT_DIR
    out: list[dict] = []
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("E-*.json"),
                       key=lambda p: int(p.stem.split("-")[1])
                       if p.stem.split("-")[-1].isdigit() else 0):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and doc.get("schema") == SCHEMA:
            out.append(doc)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="expansion.py",
        description="#546 WS4: the discovery-layer operator — trigger "
                    "probe, hypothesis admission scoring, move receipts")
    ap.add_argument("workspace")
    ap.add_argument("--check", action="store_true",
                    help="probe the trigger over the sanctioned faces")
    args = ap.parse_args(argv)
    if args.check:
        import method_families

        from rlvr import state as rlvr_state
        from rlvr import termination

        ws = Path(args.workspace)
        snap = rlvr_state.snapshot(ws)
        fams = sorted(method_families.registered_tokens())
        death = termination.verdicts(ws, fams) if fams else {}
        doc = trigger(snap, death)
        print(json.dumps({"workspace": str(ws), "fires": doc is not None,
                          "trigger": doc}, indent=2))
        return 0
    ap.error("nothing to do — pass --check")
    return 2



if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)

    force_utf8()
    raise SystemExit(main())
