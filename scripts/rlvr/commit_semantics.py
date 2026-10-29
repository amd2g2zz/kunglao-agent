# -*- coding: utf-8 -*-
"""rlvr/commit_semantics.py — the tune/switch commits, the dead-path
gate, the surprise loop, and the component-ablation pricing (issue 826,
P3 of the #806 axis).

THE THREE-WAY COMMITS GET REAL SEMANTICS. P2's meta-policy chooses
persist/tune/switch at commit boundaries; this module defines WHAT each
choice means on the wire (the additive commit fields the episode/1
validator tolerates — `class`, `to_class`, `attribution_ref`,
`param_changes`, `tool_changes`):

  tune  = the SAME action class with a parameter/tool delta. A tune
          entry without `param_changes`/`tool_changes` is RED (a bare
          retry is not a tune).
  switch= a DIFFERENT action class (`to_class`) WITH the attribution
          reason attached (`attribution_ref` — the attribution report's
          digest). A switch without the reference is RED: a blind lane
          change is exactly the disease this card treats.

THE DEAD-PATH GATE — `validate_commit_history`: DEAD_PATH_CAP (9)
consecutive same-class attempts without an intervening tune/switch is
the 9x blind-re-probe shape and is RED. Tune/switch are the evidenced
pivots that reset the run.

THE SURPRISE LOOP — the update rule's contradiction face: a verified
outcome that contradicts the value table's expectation for its exact
(features x class) cell (completed against a negative expectation, or
failed against a positive one) is a surprise; `reexamination_block`
produces the forced re-examination commit payload it triggers.

THE ENVELOPE — `enrich_block` decorates the P2 meta-policy block
ADDITIVELY (the commit entry gains `attribution` on a switch, `tune`
on a tune, `dead_path` and `reexamination` readings on the three-way
phases; the episode_start select face stays exactly the P2 shape —
conflict keeps both sides). Fail-open: enrichment problems never raise
into the dispatch path.

THE ABLATION — `price_ablations` reports the four component switches
(retrieval / value_table from P2; attribution / playbook from this
card) each priced in OUTPUT terms: what disappears from the envelope
when the component is removed.

Zero telemetry points (Standard 11). No storage: every value traces to
the pool / the P2 faces at call time.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

from rlvr import attribution as attr
from rlvr import episode_pool as pool
from rlvr import episode_schema as es
from rlvr import meta_policy as mp
from rlvr import playbook as pb

#: the blind-re-probe cap (the 9x dead-path shape is RED)
DEAD_PATH_CAP = 9

ENVELOPE_SCHEMA = mp.ENVELOPE_SCHEMA


class CommitError(ValueError):
    """A commit entry or history violates the tune/switch/dead-path
    semantics. The message names the offending field (fail-closed)."""


# ------------------------------------------------------- commit entries

def validate_switch_commit(entry: dict) -> dict:
    """switch = a different class WITH the attribution reason. Red on a
    missing `to_class` or `attribution_ref` (blind lane change)."""
    if entry.get("action") != "switch":
        raise CommitError(f"validate_switch_commit: action "
                          f"{entry.get('action')!r} is not 'switch'")
    to_class = str(entry.get("to_class") or "").strip()
    if not to_class:
        raise CommitError("switch.to_class: missing — a switch names the "
                          "class it pivots TO")
    ref = str(entry.get("attribution_ref") or "").strip()
    if not ref:
        raise CommitError("switch.attribution_ref: missing — a switch "
                          "without its attribution reason is a blind lane "
                          "change (RED)")
    return dict(entry)


def validate_tune_commit(entry: dict) -> dict:
    """tune = the same class with a parameter/tool delta. Red when the
    delta is missing (a bare retry is not a tune)."""
    if entry.get("action") != "tune":
        raise CommitError(f"validate_tune_commit: action "
                          f"{entry.get('action')!r} is not 'tune'")
    klass = str(entry.get("class") or "").strip()
    if not klass:
        raise CommitError("tune.class: missing — a tune anchors the class "
                          "it parameterizes")
    params = entry.get("param_changes") or {}
    tools = entry.get("tool_changes") or []
    if not params and not tools:
        raise CommitError("tune delta: missing — a tune without "
                          "param_changes/tool_changes is a bare retry (RED)")
    return dict(entry)


# --------------------------------------------------------- dead-path gate

def dead_path_reading(doc: dict) -> dict:
    """The dead-path reading of a commit history: the longest run of
    consecutive same-class attempts without an intervening tune/switch
    pivot. Deterministic."""
    current: str | None = None
    attempts = 0
    worst = {"class": None, "attempts": 0}
    for commit in doc.get("commits") or []:
        action = commit.get("action")
        if action in ("tune", "switch"):
            current, attempts = None, 0  # the evidenced pivot resets
            continue
        klass = str(commit.get("class") or "").strip() or None
        if klass is None:
            continue
        if klass == current:
            attempts += 1
        else:
            current, attempts = klass, 1
        if attempts > int(worst["attempts"]):
            worst = {"class": klass, "attempts": attempts}
    return {"class": worst["class"], "attempts": int(worst["attempts"]),
            "cap": DEAD_PATH_CAP,
            "over_cap": int(worst["attempts"]) >= DEAD_PATH_CAP}


def validate_commit_history(doc: dict) -> dict:
    """The dead-path gate: the 9x same-class re-probe shape is RED.
    Returns the reading on a legal history."""
    reading = dead_path_reading(doc)
    if reading["over_cap"]:
        raise CommitError(
            f"dead-path: {reading['attempts']} consecutive same-class "
            f"attempts on {reading['class']!r} reach the "
            f"DEAD_PATH_CAP({DEAD_PATH_CAP}) — blind re-probing is RED; "
            "tune (same class + delta) or switch (with the attribution "
            "reason) is the way out")
    return {"max_run": {"class": reading["class"],
                        "attempts": reading["attempts"]},
            "cap": DEAD_PATH_CAP, "over_cap": reading["over_cap"]}


# --------------------------------------------------------- surprise loop

def surprise_check(ws, doc: dict) -> dict:
    """The contradiction face: a verified outcome vs the value table's
    expectation for the episode's EXACT (features x class) cell —
    computed from the OTHER episodes (the episode never surprises
    itself). No cell coverage = no expectation = no surprise."""
    ws = Path(ws)
    outcome = doc.get("outcome") or {}
    verified = bool(outcome.get("verified"))
    if not verified:
        return {"surprise": False, "kind": None, "n": 0,
                "expected_mean_reward": None}
    feats = tuple(sorted(str(f)
                         for f in doc.get("context_features") or []))
    classes = {str(c.get("action"))
               for c in doc.get("commits") or []}
    own = str(doc.get("claim"))
    sums: dict[str, list[float]] = {}
    for path, other in pool.load_all(ws):
        if str(other.get("claim")) == own:
            continue  # the episode never surprises itself
        other_feats = tuple(sorted(str(f) for f in
                                   other.get("context_features") or []))
        if other_feats != feats:
            continue
        # the stamped mission reward may ride as a bare float (the
        # reward_block carries the decomposition) — read both shapes.
        reward = other.get("reward") or {}
        r = reward.get("r") if isinstance(reward, dict) else reward
        if not isinstance(r, (int, float)) or isinstance(r, bool):
            continue
        for commit in other.get("commits") or []:
            klass = str(commit.get("action"))
            if klass in classes:
                sums.setdefault(klass, []).append(float(r))
    if not sums:
        return {"surprise": False, "kind": None, "n": 0,
                "expected_mean_reward": None}
    klass = min(sorted(sums), key=lambda k: (-len(sums[k]), k))
    expected = sum(sums[klass]) / len(sums[klass])
    completed = outcome.get("status") == "completed"
    if completed and expected < 0.0:
        kind = "completed_against_negative"
    elif (not completed) and expected > 0.0:
        kind = "failed_against_positive"
    else:
        kind = None
    return {"surprise": kind is not None, "kind": kind,
            "cell_class": klass, "n": len(sums[klass]),
            "expected_mean_reward": expected}


def reexamination_block(ws, doc: dict) -> dict:
    """The forced re-examination commit a surprise triggers (the update
    rule's contradiction handling): a verify commit carrying the
    contradiction evidence."""
    reading = surprise_check(ws, doc)
    if not reading["surprise"]:
        return {"commit": None, "reason": None,
                "evidence": reading, "summary": ""}
    summary = (f"surprise: verified "
               f"{(doc.get('outcome') or {}).get('status')} against the "
               f"{reading['n']}-episode expectation "
               f"({reading['expected_mean_reward']:.2f}) — forced "
               "re-examination")
    return {"commit": "verify", "reason": "surprise",
            "evidence": reading, "summary": summary}


# ------------------------------------------------------ the envelope face

def _claim_episode(ws, claim: str) -> tuple[Path, dict] | None:
    path = pool.episode_path(ws, str(claim))
    if not path.is_file():
        return None
    try:
        doc, _body = es.read_episode_file(path)
    except es.EpisodeError:
        return None
    return path, doc


def enrich_block(ws, claim, block: dict) -> dict:
    """The ADDITIVE envelope enrichment: on the three-way phases the
    commit entry gains the dead-path reading, the re-examination when a
    surprise fires, the tune contract (tune) or the attribution
    evidence (switch). The episode_start select face stays exactly the
    P2 shape. Fail-open: any enrichment problem leaves the block
    untouched."""
    ws = Path(ws)
    try:
        block = copy.deepcopy(block)
        phase = block.get("phase")
        if phase not in ("commit_boundary", "blocked"):
            return block
        commit = block.setdefault("commit", {})
        action = str(commit.get("action") or "")

        loaded = _claim_episode(ws, claim)
        doc = loaded[1] if loaded else None

        if doc is not None:
            reading = dead_path_reading(doc)
            commit["dead_path"] = reading
            reex = reexamination_block(ws, doc)
            if reex["commit"] is not None:
                commit["reexamination"] = reex
        if action == "tune":
            last_class = ""
            if doc is not None:
                for entry in reversed(doc.get("commits") or []):
                    if str(entry.get("class") or "").strip():
                        last_class = str(entry["class"]).strip()
                        break
            commit["tune"] = {"same_class": True, "class": last_class,
                              "requires": ["param_changes|tool_changes"]}
        if action == "switch":
            commit["attribution"] = _switch_attribution(ws, doc, block)
        return block
    except Exception:  # noqa: BLE001 — enrichment is additive, fail-open
        return block


def _switch_attribution(ws: Path, doc: dict | None, block: dict) -> dict:
    """The attribution evidence a switch commit must ride. With the
    attribution component ablated the block reports it unavailable —
    the executor then owes its OWN reason before the switch is legal."""
    if not attr.knob_on():
        return {"available": False,
                "reason": "attribution ablated "
                          "(KUNGLAO_META_ATTRIBUTION=0) — the switch owes "
                          "a manually supplied attribution_ref"}
    if doc is None:
        return {"available": False,
                "reason": "no pool episode for this claim — nothing to "
                          "attribute; the switch owes a manual "
                          "attribution_ref"}
    rep = attr.report(ws, doc=doc)
    method = (rep.get("method") or {}).get("method")
    features = [r["feature"] for r in rep.get("features") or []
                if r.get("contrast", 0.0) > 0.0][:3]
    return {"available": True,
            "ref": attr.report_ref(rep),
            "method": method,
            "features": features,
            "exogenous_count": len(rep.get("exogenous") or [])}


def price_ablations(ws, *, features: list[str], phase: str,
                    claim=None) -> dict:
    """The four component switches, each priced in OUTPUT terms: what
    disappears from the envelope when the component is removed.
    Deterministic; writes nothing."""
    ws = Path(ws)
    rows: dict[str, dict] = {}

    # playbook — the ride-along groups
    on_groups = _playbook_price(ws, features, on=True)
    off_groups = _playbook_price(ws, features, on=False)
    rows["playbook"] = {
        "component": "playbook", "on": on_groups, "off": off_groups,
        "price": (f"{on_groups['groups'] - off_groups['groups']} playbook "
                  f"group(s) leave the context")}

    # retrieval — the cases
    on_cases = _retrieval_price(ws, features, phase, on=True)
    off_cases = _retrieval_price(ws, features, phase, on=False)
    rows["retrieval"] = {
        "component": "retrieval", "on": on_cases, "off": off_cases,
        "price": (f"{len(on_cases['cases']) - len(off_cases['cases'])} "
                  f"case(s) leave the context")}

    # value_table — the contextual term of the selection
    on_sel = mp.select_commit(ws, features)
    off_sel = _selection_with("KUNGLAO_META_VALUE_TABLE", "0", ws, features)
    rows["value_table"] = {
        "component": "value_table",
        "on": {"source": on_sel["source"]},
        "off": {"source": off_sel["source"]},
        "price": ("context stops changing the commit "
                  f"({on_sel['source']} -> {off_sel['source']})")}

    # attribution — the evidence on a switch commit
    block = {"schema": ENVELOPE_SCHEMA, "claim": str(claim),
             "phase": "commit_boundary",
             "commit": {"action": "switch", "scores": {}, "source": "price"},
             "features": list(features), "context": {}}
    on_block = enrich_block(ws, claim, copy.deepcopy(block))
    off_block = _enrich_with("KUNGLAO_META_ATTRIBUTION", "0", ws, claim,
                             block)
    on_att = (on_block.get("commit") or {}).get("attribution") or {}
    off_att = (off_block.get("commit") or {}).get("attribution") or {}
    rows["attribution"] = {
        "component": "attribution",
        "on": {"available": on_att.get("available"),
               "method": on_att.get("method")},
        "off": {"available": off_att.get("available"),
                "method": off_att.get("method")},
        "price": ("the switch loses its learned reason — a manual "
                  "attribution_ref is owed")}
    return rows


def _playbook_price(ws: Path, features: list[str], *, on: bool) -> dict:
    if not on:
        return {"groups": 0}
    feats = {str(f) for f in features}
    groups = [g for g in pb.compressed_view(ws)
              if feats & {str(f) for f in g.get("context_features") or []}]
    return {"groups": len(groups)}


def _retrieval_price(ws: Path, features: list[str], phase: str,
                     *, on: bool) -> dict:
    """Read-only mirror of the retrieval face's filter (the pool's own
    retrieve call bumps its counters — a pricing report must not)."""
    if not on:
        return {"cases": []}
    k = mp.knobs()
    from rlvr import meta_retrieval  # noqa: PLC0415 — lazy (cycle-free)
    want = {str(f) for f in features}
    matched = [doc for _p, doc in pool.load_all(ws)
               if want & {str(f) for f in doc.get("context_features") or []}]
    ranked = sorted(
        matched,
        key=lambda doc: (-meta_retrieval.utility_score(doc, k),
                         str(doc.get("claim"))))
    cases: list[str] = []
    for doc in ranked:
        if float(doc.get("utility", {}).get("utility") or 0.0) \
                < float(k["min_utility"]):
            continue
        if len(cases) >= int(k["retrieve_max"]):
            break
        cases.append(str(doc.get("claim")))
    return {"cases": cases}


# --------------------------------------------------- env-toggle helpers

def _selection_with(env: str, value: str, ws: Path, features: list[str]):
    old = os.environ.get(env)
    os.environ[env] = value
    try:
        return mp.select_commit(ws, features)
    finally:
        if old is None:
            os.environ.pop(env, None)
        else:
            os.environ[env] = old


def _enrich_with(env: str, value: str, ws: Path, claim, block: dict):
    old = os.environ.get(env)
    os.environ[env] = value
    try:
        return enrich_block(ws, claim, block)
    finally:
        if old is None:
            os.environ.pop(env, None)
        else:
            os.environ[env] = old
