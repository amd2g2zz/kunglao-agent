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

  - ``trigger``: the move fires when the workspace's obstacle
    evidence reaches EXPAND_OBSTACLE_K rows AND at least one of two
    collapse arms holds — a tried family is termination-dead, or the
    loop is stalled (the settlement stream's potential tail flat
    within STALL_EPSILON over STALL_WINDOW_TICKS consecutive
    transitions; the stall arm only SPENDS the move — it never kills,
    parks, downweights, or writes anything). It reads ONLY sanctioned
    faces — the state snapshot's obstacle digest (rlvr.state, the 396
    freeze wall: this module NEVER imports rlvr.obstacles) and the
    termination verdicts (the registry's one sanctioned consumer
    precedent; expansion is sanctioned consumer #2 per the #546
    charter note).
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
    decomposition -> admitted ids. Append-only by index; the doc names
    its own index in ``receipt`` so the admission face can cite it.
  - ``register_admitted``: appends the move's admitted family tokens to
    the workspace overlay ``runs/discovered-families.yaml`` (schema
    discovered-families/1; idempotent by token+receipt, tolerant read)
    — the face that makes an admitted arm DISPATCHABLE: the vocabulary
    gate merges the overlay into its candidate enumeration, and the
    declaration path admits an overlay token only while the cited
    receipt closes in the same workspace.

New arms admitted here seed cold with the WS3 model prior at the
wiring face (priors.seed_intake_prior families=) — not this module's
job. Constants (5, the WS4 budget): EXPAND_OBSTACLE_K, STALL_EPSILON,
STALL_WINDOW_TICKS, EXPAND_HYPOTHESES_N, NOVELTY_WEIGHT.

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
from kunglao_log import warn
from rlvr.feature_prior import feature_tokens, jaccard

import yaml

SCHEMA = "expansion/1"
RECEIPT_DIR = "runs/expansion"

#: the workspace-local vocabulary overlay this module writes (the
#: reader face lives in method_families.load_discovered)
OVERLAY_SCHEMA = "discovered-families/1"
OVERLAY_REL = "runs/discovered-families.yaml"

#: obstacle rows (state digest count) required before a move may fire.
#: Budget-calibration, not tuned-to-fire: hard-kill evidence lands at
#: roughly one row per hour of grinding, so a two-hour budget stacks
#: about two rows — the fixed count is the canonical fixed-m stopping
#: shape, and a taller bar is structurally unreachable inside the
#: budget it calibrates.
EXPAND_OBSTACLE_K = 2
#: hypotheses one move may admit (the budget the move spends)
EXPAND_HYPOTHESES_N = 3
#: novelty term weight in the admission score
NOVELTY_WEIGHT = 1.0
#: a transition's potential move below which the loop reads as flat —
#: set at the measured grind scale (settled arms move the potential
#: well under this per tick while grinding; a real gain of a few
#: percent clears it and breaks the stall)
STALL_EPSILON = 0.02
#: consecutive flat transitions that read the loop as stalled — half
#: the transitions a two-hour budget settles (four to six observed),
#: so a stall only reads in the run's back half
STALL_WINDOW_TICKS = 3

_LOG_FLOOR = 1e-12  # log(0) guard — a zero P_LLM floors, never crashes


def loop_stalled(phi_series, window: int = STALL_WINDOW_TICKS,
                 epsilon: float = STALL_EPSILON) -> dict | None:
    """The loop-stall face: a mechanical read over the transition
    ledger's settlement stream (each row carries the potential it
    landed at). ``phi_series`` is that potential column, oldest first.
    The face reads stalled when the LAST ``window`` consecutive
    transitions each moved the potential by less than ``epsilon`` — a
    backward move counts toward the stall (it is not progress).
    Malformed input returns None (the wiring then degrades to the
    family-death-only predicate); a series too short to fill the
    window honestly reads as not stalled yet. Pure: nothing is
    written, nothing parked, nothing killed — the option-death
    estimator keeps sole authority over parking."""
    if not isinstance(phi_series, (list, tuple)):
        return None
    if not isinstance(window, int) or window < 1:
        return None
    phis = [float(v) for v in phi_series if isinstance(v, (int, float))]
    moves = [phis[i + 1] - phis[i] for i in range(len(phis) - 1)]
    tail = moves[-window:]
    stalled = len(tail) == window and all(m < epsilon for m in tail)
    return {"stalled": bool(stalled),
            "moves": [round(m, 6) for m in tail],
            "window": window, "epsilon": epsilon}


def trigger(snap: dict, death: dict | None,
            stall: dict | None = None,
            obstacle_k: int = EXPAND_OBSTACLE_K) -> dict | None:
    """The move's predicate over SANCTIONED faces only: the state
    snapshot's obstacle digest ({"obstacles": {"count": n}} — rlvr.state
    owns the read; this module never touches the registry), the
    termination verdicts ({family: {"dead": bool}}), and the optional
    loop-stall face ({"stalled": bool} — loop_stalled's read of the
    transition ledger). The stall arm ORs in: an absent or malformed
    face degrades to the family-death-only predicate (fail-closed).
    THE SPEND-ONLY INVARIANT: the stall arm only spends the discovery
    move — it never kills, parks, downweights, or writes anything; the
    option-death estimator keeps sole authority over parking. Returns
    the trigger receipt ({"obstacle_count", "collapsed_arms", "arm"})
    — ``arm`` names the evidence that fired ("family-death" takes
    precedence when both arms hold) — or None: never an exception,
    never a partial fire."""
    if not isinstance(snap, dict) or not isinstance(death, dict):
        return None
    count = int((snap.get("obstacles") or {}).get("count") or 0)
    if count < obstacle_k:
        return None
    collapsed = sorted(
        str(fam) for fam, v in death.items()
        if isinstance(v, dict) and bool(v.get("dead")))
    stalled = isinstance(stall, dict) and stall.get("stalled") is True
    if not collapsed and not stalled:
        return None
    return {"obstacle_count": count, "collapsed_arms": collapsed,
            "arm": "family-death" if collapsed else "loop-stall"}


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
        "receipt": f"E-{index}",
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


def register_admitted(ws, receipt: dict) -> list[str]:
    """Registry admission: append the move's admitted family tokens to
    the workspace overlay (``runs/discovered-families.yaml``, schema
    discovered-families/1) so the vocabulary gate can enumerate — and,
    receipt-gated, VALIDATE — dispatches declaring them. Reads the
    receipt doc ``record_receipt`` returned (its ``receipt`` index,
    ``hypotheses`` rows and ``admitted`` ids are the provenance chain
    the gate re-closes later). Idempotent by (token, receipt); rows
    failing the overlay grammar or already in the closed repo registry
    are skipped with a warn, never written. The read side is the
    vocabulary owner's tolerant face, so a corrupt pre-existing overlay
    is replaced by the normalized merge. Fail-open: an OSError warns
    and registers nothing (the wiring catches; the loop is never
    broken by bookkeeping). Returns the tokens actually persisted."""
    doc = receipt if isinstance(receipt, dict) else {}
    rid = str(doc.get("receipt") or "").strip()
    admitted = {str(h) for h in doc.get("admitted") or []}
    tokens: list[str] = []
    for hyp in doc.get("hypotheses") or []:
        if not isinstance(hyp, dict) \
                or str(hyp.get("id") or "") not in admitted:
            continue
        fam = str(hyp.get("family") or "").strip()
        if fam:
            tokens.append(fam)
    if not rid or not tokens:
        return []
    import method_families  # the vocabulary owner owns grammar + repo set

    repo = method_families.registered_tokens()
    rows = method_families.load_discovered(ws)
    known = {(str(r.get("token")), str(r.get("receipt") or ""))
             for r in rows}
    ts = utc_now_z()
    added: list[str] = []
    for tok in dict.fromkeys(tokens):
        if (tok, rid) in known:
            continue
        if not method_families.TOKEN_RE.fullmatch(tok):
            warn("expansion.register_admitted",
                 f"family {tok!r} fails the token grammar — not registered")
            continue
        if tok in repo:
            continue  # already vocabulary; nothing to admit
        rows.append({"token": tok, "receipt": rid, "admitted_ts": ts})
        added.append(tok)
    if not added:
        return []
    try:
        path = Path(ws) / OVERLAY_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump({"schema": OVERLAY_SCHEMA, "families": rows},
                           sort_keys=True, allow_unicode=True),
            encoding="utf-8")
    except OSError as exc:
        warn("expansion.register_admitted",
             f"overlay write failed ({type(exc).__name__}: {exc}) — "
             "nothing registered")
        return []
    return added


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

        from rlvr import incremental_reward
        from rlvr import state as rlvr_state
        from rlvr import termination

        ws = Path(args.workspace)
        snap = rlvr_state.snapshot(ws)
        fams = sorted(method_families.registered_tokens())
        death = termination.verdicts(ws, fams) if fams else {}
        phis = [r.get("s_prime_phi")
                for r in incremental_reward.read_transitions(ws)
                if isinstance(r, dict)]
        stall = loop_stalled(phis)
        doc = trigger(snap, death, stall)
        print(json.dumps({"workspace": str(ws), "fires": doc is not None,
                          "trigger": doc, "stall": stall}, indent=2))
        return 0
    ap.error("nothing to do — pass --check")
    return 2



if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)

    force_utf8()
    raise SystemExit(main())
