#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""priority_ratio.py — M1 DECIDE action ranking, REBUILT (#107).

Owner ruling (issue #107, "探索和价值网络需要完全重构，之前的不要了"):
the weighted VoI-proxy formula score = [0.45·L + 0.30·D + 0.25·N]/cost and
the (bucket, score, claim_id) lexicographic sort are DISCARDED — weights
with no estimation basis, and a boolean bucket that dictated everything.
The explore/exploit dual path (the count-threshold gate module, its
constant, the cheapness spread) died with it: ONE ranker, no phase switch,
no count cliff.

The rebuilt value function (design card #97, unchanged):

    action value = Σ_cases P(flip | action) · case_weight + λ · ΔH_PQ(action)
    rank by Thompson sample per action per tick; stable tie-break claim_id

Concretely, per dispatchable claim (the candidate filter is UNCHANGED:
OPEN + promotion_attempts<3 + every depends_on parent holding a terminal
fact, #594/#596 per-claim fallback, #103 dirty-value tolerance):

  case face — #792: the value face is the posterior MEAN, never a draw.
  The claim's oracle cases (workspace `oracle/cases/*.yaml`, each
  `target_pq` == the claim's `answers_question`) are Bernoulli posteriors
  (#106 CasePosterior, runs/posteriors.yaml — the SAME store the strategy
  sampler consumes). value = sum(alpha_i / (alpha_i + beta_i)) over the
  linked cases: deterministic given data, monotone in evidence, moving
  only when evidence moves. A claim with NO linked case has no value
  channel by definition — zero is not fabricated for it; it is DEMOTED
  below every value-bearing claim, ordered by the declared deterministic
  default (downstream_term, tier, worth), and its feeds say
  `unlinked — no value channel (arm oracle cases / set answers_question)`
  so the linkage gap is the visible actionable signal. The retired draw
  faces (the round-seeded `thompson/{base}/{cid}` Beta re-draw and the
  Beta(1,1) unlinked fallback) simulated exploration while doing none of
  its work: nothing fed the draw back, nothing learned from it. Real
  exploration lives in the strategy sampler (method_sample) — and at
  this face only as the EXPLICIT exploration slot (EXPLORE_EVERY_N_ROUNDS,
  default 0 = off): when enabled, every Nth round promotes the best
  unlinked/lowest-attempts claim, labeled `exploration_arm` in feeds,
  never conflated with the value column.

  PQ face — REMOVED (#295, the first ADR-001 governed application). The
  #106/#107 ΔH_PQ face (case_face + LAMBDA_DH·ΔH) died on replay
  evidence: EXP-B measured ΔH = 0 on 612/612 real rank events
  (runs/posteriors.yaml never instantiated in any real workspace,
  pooled Spearman vs progress +0.068 p=0.16, wrong-signed vs gate
  fires) and the #294 λ epistemology check produced order digests
  BYTE-IDENTICAL at every tick for λ=0.25 vs λ=0 — mechanically inert
  on all real data. The removal is therefore a runtime no-op on
  history; the old feeds["dh_pq"] diagnostic is gone with it. The
  λ epistemology HARNESS face (replay_ruler.lambda_check) stays — it
  reads history, where dh_pq strings legitimately exist. Any
  re-introduction goes through docs/adr-001-strategy-parameter-
  governance.md (replay evidence + versioned PR + pins; never runtime
  self-tuning).

  score = (case_face + W_DOWNSTREAM · downstream_term) · worth
                                                  (#759 worth channel)

  The composite's free parameters live in the downstream block below,
  each carrying its earn-in evidence and governance comment. `worth`
  is the pre-existing #759 user worth ruling (runs/value-weights.yaml)
  — a sanctioned exogenous multiplier, not a formula DOF; absent
  weights → 1.0.

  determinism — #792: same (ledger, claims, weights) → byte-identical
  ranking, ANY round. The #251 per-round seed (case_face_seed /
  posterior_rng / posterior_seed_state — the f(posterior_state, round)
  digest) is RETIRED together with the draw it seeded: a ranking column
  whose numbers move because the round counter advanced is ordering
  noise, not signal (the same claim re-ranked across rounds while no
  data changed). The rank is a pure function of the inputs; the emit
  fingerprint pins (claims_hash, evidence_hash, posterior_hash, round)
  so the event tail stays exactly replayable. DECIDE + the dispatch gate
  share the ONE deterministic ranker — an authority mismatch stays
  structurally impossible (#100/#101 die at the root, now seed-free).
  The #266 frozen-sampling observable is defined out at the source: new
  rank_feeds fingerprints carry rng_base=null (the detector remains for
  historical tails, where it still reads the retired integer face).

  flip potential (diagnostic, feeds["case_flip_potential"]) — the
  conservative P(cflip) reading: 0.5 at cold start, decayed by the claim's
  total attempt mass (attempts_of = max(dispatch_count,
  promotion_attempts) — dispatch churn decays it too), floored to
  FLIP_POTENTIAL_FALLBACK = 0.3 when the action has no oracle case / PQ
  linkage. It rides Action.feeds; it does NOT enter the score.

The LLM never enters the score; ranking is a pure function of (claims,
deps, evidence, rng). The record faces this module still reads for OTHER
consumers: analyses/failure-*.yaml → validated_capabilities /
identified_obstacles (the dispatch-gate capability card,
strategy_metrics), and runs/value-weights.yaml (#759).

Deleted with the formula (owner ruling): the mission_ledger L-term feeds
(the v_norm/d_slope_norm reads and the old lexicographic sort head —
mission_ledger.py itself KEEPS its V_m data face), the difficulty
D-multiplier, the novelty/strategy-log proxy feeds, the #823 prior_p cost
inflation and the capability bonus.
The routing tables (quickref peeling / jsvmp triage / route_capability)
survive as prior INPUT to hypothesis generation, never as rankers.

Usage:
  python priority_ratio.py <workspace> [--json]
"""
from __future__ import annotations
# issue 275 batch-3: fail-open handlers leave ONE rate-limited trace —
# the canonical kunglao_log.warn.
# canonical warn: ONE implementation (process-wide dedupe + ledger face)
from kunglao_log import warn
import argparse
import hashlib
import json
import math
import random
import sys
from typing import Iterable
from dataclasses import replace
from pathlib import Path

import yaml

from status_defs import TERMINAL, IN_PROGRESS_STATUSES, SUSPENDED  # noqa: F401  (re-export: replay_ruler reads pr.TERMINAL)
import kunglao_log  # noqa: E402  (#104: #534 lifeline, emit only)
import rank_face  # noqa: E402  (issue 218: the emit-failure marker)
from posteriors_case import CasePosterior, PosteriorLedger  # noqa: E402  (#106)

# #886 preparation: the claim/evidence view utilities moved to
# claims_view.py (verbatim relocation). The names are re-imported here so
# this module's ordering face below and every straggler consumer keep the
# exact pre-move surface; deleting this file stays gated on the #886
# ruling.
from claims_view import (DOWNSTREAM_CAP, DOWNSTREAM_DECAY, W_DOWNSTREAM,
                         Action, EvidenceView, _int_flag,
                         _load_oracle_cases, action_cost, action_tier,
                         attempts_of, claim_value_weight, classify_action,
                         dispatch_count_of, downstream_term, is_open,
                         round_index, strikes_of)
# pure re-export surface — no in-module caller anymore; the names exist so
# straggler consumers keep importing them from here until #886 lands:
from claims_view import CONV_LEDGER_NAME  # noqa: F401  (re-export surface)
from claims_view import DEFAULT_ACTION  # noqa: F401  (re-export surface)
from claims_view import ORACLE_CASES_REL  # noqa: F401  (re-export surface)
from claims_view import VALUE_WEIGHTS_FILE  # noqa: F401  (re-export surface)
from claims_view import _DISPROOF_RE  # noqa: F401  (re-export surface)
from claims_view import _KEYWORD_MAP  # noqa: F401  (re-export surface)
from claims_view import _TIER_COST  # noqa: F401  (re-export surface)
from claims_view import _TOOL_FAMILY_BY_TOKEN  # noqa: F401  (re-export surface)
from claims_view import _VALUE_CLASS_TOKENS  # noqa: F401  (re-export surface)
from claims_view import _positive_weights  # noqa: F401  (re-export surface)
from claims_view import _reverse_deps  # noqa: F401  (re-export surface)
from claims_view import _scan_failure_artifacts  # noqa: F401  (re-export surface)
from claims_view import capability_switch_violation  # noqa: F401  (re-export surface)
from claims_view import classify_value_class  # noqa: F401  (re-export surface)
from claims_view import load_value_weights  # noqa: F401  (re-export surface)
from claims_view import tool_families_from_text  # noqa: F401  (re-export surface)
from claims_view import tool_families_from_tools  # noqa: F401  (re-export surface)

# #295: LAMBDA_DH is DELETED (the first governed application of
# docs/adr-001-strategy-parameter-governance.md — see the module
# docstring's PQ-face note for the removal evidence).
# #107 conservative flip-potential reading (diagnostic only — see feeds).
FLIP_POTENTIAL_BASE = 0.5       # P(cflip) at cold start
FLIP_POTENTIAL_FALLBACK = 0.3   # no oracle case / no PQ linkage


# #792 explicit exploration slot (design 3 — structural, never smuggled):
# every Nth round promotes the best unlinked/lowest-attempts claim and
# LABELS it `exploration_arm` in feeds. 0 = OFF (the default: the value
# column is then the whole rank, byte-identical across rounds). A nonzero
# value is a DECLARED exploration face — auditable, tunable, removable —
# never a hidden draw inside the score.
EXPLORE_EVERY_N_ROUNDS = 0

# #266 frozen-sampling marker: K CONSECUTIVE rank runs whose recorded
# rng_base is EQUAL while the recorded round ADVANCES. The #251 contract
# made the seed move whenever the round moved — a run of advancing rounds
# with a static base was the old frozen-sampler defect (the 53-consecutive
# wild audit). #792 retires the seed at the SOURCE (ranker output is
# round-invariant), so new fingerprints carry rng_base=null and the
# detector reads them as the honest gap; the consumer remains a pure tail
# function for HISTORICAL tails (the retired integer face) — no state,
# idempotent under tail replay.
FROZEN_SAMPLE_K = 3


def posterior_digest(ledger: PosteriorLedger) -> str:
    """Canonical digest of the CASES posterior state (#792 fingerprint
    component). Only the cases namespace enters: a PQ-categorical update
    must not move the case-value face (one signal, one channel — the same
    scoping the retired case_face_seed used). The digest pins the ledger
    state in the rank_feeds fingerprint, so the event tail stays exactly
    replayable without any seed: same (claims, evidence, posteriors) →
    the identical ranking, recomputeable from the tail alone."""
    doc = {"cases": {k: ledger.cases[k].to_dict()
                     for k in sorted(ledger.cases)}}
    payload = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ---------- #266 frozen-sampling consumer (pure tail function) -------------

def frozen_sampling_markers(rows: Iterable) -> list[dict]:
    """#266: scan a rank_feeds event tail for frozen sampling.

    A RUN is a maximal stretch of consecutive ``rank_feeds`` rows whose
    ``input_fingerprint.rng_base`` stays EQUAL while ``round`` strictly
    ADVANCES; a run of length >= FROZEN_SAMPLE_K is a marker (the seed
    ignored a moving round axis). Rows that break either condition reset
    the run: a different base (healthy reseed), an equal round (the
    contract replaying an unchanged tick), a decreasing round, or an
    unparseable/absent fingerprint (conservative gap — old envelopes with
    ``epoch: null`` still carry the fingerprint doc inside ``detail``,
    which is what this consumer keys on). Pure function of the rows:
    identical tails -> identical markers, forever (tail-replay safe).

    Returns [{"rng_base", "rounds", "length"}, ...] in tail order."""
    markers: list[dict] = []
    cur: dict | None = None
    for e in rows:
        if not isinstance(e, dict) or e.get("action") != "rank_feeds":
            continue
        # #863 Family K: JSON parsing is delegated to kunglao_log's
        # tolerant single-source reader (a broken detail yields nothing,
        # next() falls back to None) — never an inline json parse here.
        parsed = next(iter(kunglao_log.iter_jsonl(
            [str(e.get("detail") or "")])), None)
        fp = (parsed or {}).get("input_fingerprint") or {} \
            if isinstance(parsed, dict) else {}
        base, rnd = fp.get("rng_base"), fp.get("round")
        if base is None or rnd is None or not isinstance(rnd, int):
            cur = None
            continue
        if cur is not None and base == cur["rng_base"] \
                and rnd > cur["rounds"][-1]:
            cur["rounds"].append(rnd)
            cur["length"] += 1
        else:
            if cur and cur["length"] >= FROZEN_SAMPLE_K:
                markers.append(cur)
            cur = {"rng_base": base, "rounds": [rnd], "length": 1}
    if cur and cur["length"] >= FROZEN_SAMPLE_K:
        markers.append(cur)
    return markers


# ---------- #157 algorithm event log: rank_feeds (one emit per RUN) --------

def _evidence_digest(evidence: EvidenceView) -> str:
    """Canonical digest of the ranking-relevant evidence view (#157 input
    fingerprint component): the terminal-fact set (candidate filter), the
    verified count, and the #759 worth weights — only what the rank actually
    consumed, not the whole index."""
    doc = {
        "terminal_fact_claims": sorted(evidence.terminal_fact_claims),
        "verified_fact_count": evidence.verified_fact_count,
        "value_class_weights": dict(sorted(
            evidence.value_class_weights.items())),
        "value_claim_overrides": dict(sorted(
            evidence.value_claim_overrides.items())),
    }
    payload = json.dumps(doc, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _view_stats(actions: list) -> dict:
    """The additive decision-view payload keys — pure functions of the
    ranked actions (no workspace, no clock, no randomness), so same-seed
    payload replay stays byte-identical including these keys:

      k         — the ranked candidate count;
      propensity — the top-ranked arm's share of the total score mass
                   (6dp). The rank-time "how dominant was the pick"
                  readout for the view; NOT the dispatch-receipt MC
                  propensity (that one stays on the envelope, a
                  different layer). Null when the ranking is empty or a
                  multi-candidate score mass cannot be normalized;
      entropy   — Shannon entropy in BITS of the normalized score
                  distribution over the k candidates (6dp); 0.0 when the
                  choice is fully determined (a single candidate),
                  null when a multi-candidate mass cannot be
                  normalized (zero total score);
      tiers     — {claim_id: tier} over the ranked candidates, the same
                  claim-keyed shape feeds/scores already use.

    Negative scores (reachable only through a negative worth override)
    clamp at zero before normalizing, so the shares always form a
    simplex."""
    k = len(actions)
    tiers = {a.claim_id: a.tier for a in actions}
    if k == 0:
        return {"entropy": None, "propensity": None, "k": 0, "tiers": tiers}
    if k == 1:
        return {"entropy": 0.0, "propensity": 1.0, "k": 1, "tiers": tiers}
    scores = [max(a.score, 0.0) for a in actions]
    total = sum(scores)
    if total <= 0:
        return {"entropy": None, "propensity": None, "k": k, "tiers": tiers}
    shares = [s / total for s in scores]
    # 0.0 - sum(...) (not -sum(...)): the all-p=1 edge would otherwise
    # yield a signed -0.0 that serializes as "-0.0" in the payload.
    entropy = round(0.0 - sum(p * math.log2(p) for p in shares if p > 0), 6)
    return {"entropy": entropy, "propensity": round(shares[0], 6),
            "k": k, "tiers": tiers}


def _emit_rank_feeds(ws, claims: list[dict], evidence: EvidenceView,
                     rank_inputs: dict, actions: list[Action],
                     round_no: int | None,
                     planner: dict | None = None) -> None:
    """#157: ONE ``rank_feeds`` event per priority_ratio() run — the
    per-claim Thompson feeds + the input fingerprint (claims hash,
    evidence-view digest, rng base draw, #251 round). Given the seed inputs,
    the ranking is exactly replayable from the event tail.

    #792 fingerprint: (claims_hash, evidence_hash, posterior_hash, round)
    — the FULL ranking input face, so the event tail is exactly replayable
    without any seed: same inputs → recompute the identical ranking from
    the tail alone. The retired ``rng_base`` ride stays as an explicit
    null (the #266 detector reads it as the honest gap; historical tails
    keep their integer face). The fingerprint hash covers the round key.
    Never re-read round_index(ws) here when the round is THREADED — the
    None fallback re-read (static-fixture callers only) lives inside the
    fail-open try.

    SILENT FAIL-OPEN for the ranking (the decide_fail_open contract, #569):
    a crash in payload build or emit never reaches the ranking result. Issue
    218 makes the crash OBSERVABLE instead of invisible: the attempt leaves
    the marker runs/.rank-emit-fail.json {ts, error class} (rank_face), a
    success clears it, and the statusline snapshot / heartbeat tick report
    surface it as the rank_log health bit. Neither the ranking result nor
    the payload is touched by the marker.

    The real writer reports a failed write by returning False instead of
    raising (kunglao_log.emit never raises), so the health bit keys off
    BOTH shapes: a payload/build crash and a plain write failure.

    The payload additionally carries the four additive decision-view keys
    (entropy of the score distribution in bits, the top arm's score share,
    the candidate count k, and the per-claim tier map — see _view_stats).
    They are pure functions of the ranked actions, computed here at the
    decision point, and stay OUTSIDE input_fingerprint: the fingerprint
    covers ranking inputs, these are outputs, so the replay hash and the
    frozen-sampling observability stay byte-identical.

    #718 additive planner block: when the L1 planner's advisory factors
    moved any candidate this run (the value store is non-empty and at
    least one claim is knowledge-solved), the per-claim factors ride the
    payload under ``planner`` — an OUTPUT key (same convention as the
    view keys), so an all-empty run emits the pre-#718 payload
    byte-identically."""
    try:
        fp_doc = {"claims_hash": rank_inputs["claims_hash"],
                  "evidence_hash": rank_inputs["evidence_hash"],
                  "posterior_hash": rank_inputs["posterior_hash"],
                  # #792: the per-round seed draw is retired — the null
                  # keeps the key face stable for tail readers while the
                  # frozen-sampling detector reads it as the honest gap.
                  "rng_base": None,
                  "round": int(round_no) if round_no is not None
                  else round_index(ws)}
        fingerprint = hashlib.sha256(json.dumps(
            fp_doc, sort_keys=True, ensure_ascii=False)
            .encode("utf-8")).hexdigest()
        payload = {
            "feeds": {a.claim_id: dict(a.feeds) for a in actions},
            "scores": {a.claim_id: a.score for a in actions},
            "ranked_order": [a.claim_id for a in actions],
            "tiers": {a.claim_id: a.tier for a in actions},
            "input_fingerprint": dict(fp_doc, fingerprint=fingerprint),
            **_view_stats(actions),
            # additive-when-present (#718): no factors -> no key at all
            **({"planner": dict(planner)} if planner else {}),
        }
        # #801 R2b NOTE: rank_feeds stays PER-RUN (no value gate) — the
        # #157 replay spine ("the ranking is exactly replayable from the
        # event tail") and the #218 last-attempt health bit both pin the
        # emit attempt itself; a suppressed identical ranking would erase
        # the round-advance marker the replay needs. The R2b gate applies
        # to the detector_eval and statusline faces only.
        if kunglao_log.emit(ws, actor="priority_ratio", action="rank_feeds",
                            arm=(actions[0].claim_id if actions else None),
                            detail=json.dumps(payload, sort_keys=True,
                                              ensure_ascii=False)) is False:
            # Issue 218/225: the health bit tracks the LAST ATTEMPT. The
            # writer reports a failed write with False (it never raises) —
            # the marker MUST be set here, and a failed attempt must never
            # erase a marker left by an earlier failure.
            rank_face.write_fail_marker(ws, "EmitWriteError")
        else:
            # The last attempt succeeded — the marker clears itself so the
            # health bit recovers without operator action.
            rank_face.clear_fail_marker(ws)
    except Exception as exc:  # noqa: BLE001 — observability never disturbs the rank
        # Issue 218: the fail-open contract stays (the ranking result is
        # untouched) — the crash just stops being silent (see rank_face).
        rank_face.write_fail_marker(ws, exc)


def priority_ratio(claims: list[dict], deps: dict, evidence: EvidenceView,
                   round_no: int | None = None) -> list[Action]:
    """#792 deterministic evidence ranking (purely mechanical, zero LLM).

    Input: claims (claim-register claims[]), deps (claim_deps.yaml {depends_on, competitor_groups}),
          evidence (EvidenceView; `ws` present → #106 posteriors + oracle cases load),
          round_no (the calling tick — threaded to the emit fingerprint and
          the exploration slot ONLY; the ranking itself never reads it).
    Output: the sorted Action list — value-bearing claims by composite
          score descending; unlinked claims DEMOTED below every value-
          bearing one, ordered by the declared deterministic default
          (downstream_term, tier, worth); stable tie-break claim_id.

    Value face (issue #792): score = (case_value + W_DOWNSTREAM ·
    downstream_term) · worth, where case_value = Σ αᵢ/(αᵢ+βᵢ) over the
    linked oracle-case posteriors — deterministic given data, monotone in
    evidence. Unlinked claims carry no fabricated value (the Beta(1,1)
    fallback is gone); the linkage gap is their feeds-visible signal.

    Candidate filter UNCHANGED from the pre-#107 ranker: OPEN + attempts<3
    + all depends_on parents holding a terminal fact (#594/#596 per-claim
    fallback; #103 dirty-value tolerance). RETRACTED/failure-blocked
    filtering stays the CALLER's job (contract §1)."""
    # #594/#596: claim_deps.yaml is the authoritative graph, but a fresh
    # workspace ships it empty ("depends_on: {}") — fall back to the
    # operator-natural per-claim depends_on field so the ranking has input
    # (and the per-claim field stops being cosmetic) until claim_deps is
    # hand-populated.
    depends_on = (deps or {}).get("depends_on", {}) or {}
    if not depends_on:
        depends_on = {c["id"]: list(c.get("depends_on") or [])
                      for c in claims if c.get("id") and c.get("depends_on")}
    terminal = evidence.terminal_fact_claims
    # issue 241 (review round 1, CRITICAL): replacement lineage satisfies the
    # dep gate alongside the facts face. A parent carrying `superseded_by` is
    # terminal by replacement (status_defs SUPERSEDED / issue 59) — its scope
    # lives in the successors, so its dependents must rank. This is a REGISTER
    # consult, deliberately NOT folded into EvidenceView: the facts index is
    # the evidence channel and its zero-rows fallback (issue 594) keeps its
    # semantics; supersession is lineage, never an evidence artifact. The
    # mint_split_claims fan-out writes exactly this shape (parent SUPERSEDED
    # + superseded_by = sub ids, register only) — without this consult the
    # split's sub-claims stay dep-blocked forever in any workspace whose
    # facts index already carries a terminal row (settled subs cite subs,
    # never the parent — the block would never lift).
    superseded = {c["id"] for c in claims
                  if c.get("id") and c.get("superseded_by")}

    # dispatchable candidates: OPEN + attempts<3 + all depends_on terminal
    candidates: list[dict] = []
    for c in claims:
        cid = c.get("id")
        if not cid or not is_open(c):
            continue
        if strikes_of(c) >= 3:  # #103: dirty value → 0, never a row-crash
            continue
        parents = depends_on.get(cid, []) or []
        if any(p not in terminal and p not in superseded for p in parents):
            continue
        candidates.append(c)

    # #106 posteriors + oracle case linkage (no ws → cold-start priors).
    ledger = (PosteriorLedger.load(evidence.ws)
              if evidence.ws is not None else PosteriorLedger())
    oracle_cases = _load_oracle_cases(evidence.ws)

    # #792 rank-input digests: the emit fingerprint's input face and the
    # L1 planner fork seed BOTH derive from these — inputs, never a round
    # counter (the planner block must not reintroduce round-dependence).
    claims_hash = hashlib.sha256(json.dumps(
        claims, sort_keys=True, ensure_ascii=False, default=repr)
        .encode("utf-8")).hexdigest()
    evidence_hash = _evidence_digest(evidence)
    posterior_hash = posterior_digest(ledger)

    actions: list[Action] = []
    # #792: the unlinked demotion metadata — cid -> (dterm, tier, worth)
    # for the declared deterministic default ordering of the no-value band.
    unlinked_meta: dict[str, tuple[float, int, float]] = {}
    for c in candidates:
        cid = c["id"]
        pq = str(c.get("answers_question") or "").strip()
        linked = [case_id for case_id, tpq in oracle_cases
                  if tpq and tpq == pq]
        # case value: the posterior MEAN of each linked oracle case, summed
        # (#792). No linkage → NO fabricated value (the Beta(1,1) fallback
        # is retired): case_value stays 0.0 and the claim is demoted by the
        # partition sort below; the linkage gap is the feeds signal.
        if linked:
            case_value = 0.0
            linked_names: list[str] = []
            for case_id in linked:
                post = ledger.cases.get(case_id) or CasePosterior(case_id)
                case_value += post.alpha / (post.alpha + post.beta)
                linked_names.append(case_id)
            fp = FLIP_POTENTIAL_BASE / (1.0 + attempts_of(c))
            value_state = (f"posterior mean over {len(linked)} linked oracle "
                           f"case(s) [{', '.join(linked_names)}] -> "
                           f"value={round(case_value, 6)}")
        else:
            case_value = 0.0
            fp = min(FLIP_POTENTIAL_BASE / (1.0 + attempts_of(c)),
                     FLIP_POTENTIAL_FALLBACK)
            value_state = ("unlinked — no value channel (arm oracle cases / "
                           f"set answers_question): oracle/cases/ target_pq "
                           f"!= '{pq or '-'}'")
        # ΔH_PQ face REMOVED (#295 governed application, ADR-001): the
        # PQ categorical is no longer read, no entropy is computed, and
        # no dh_pq feed is emitted. On all real ledgers the removed term
        # contributed LAMBDA_DH × 0 ≡ 0 at every tick (EXP-B: 612/612
        # rank events dh_pq=0; #294: λ=0.25 vs λ=0 order digests
        # byte-identical), so ordering is unchanged byte-for-byte.
        # #792 keeps the removal intact — the mean face never reads the
        # PQ categorical either.
        # #759 worth channel (exogenous user ruling, not a formula DOF).
        weight = claim_value_weight(c, evidence.value_class_weights,
                                    evidence.value_claim_overrides)
        # #294 downstream-blocker term (bounded, decaying; feeds-recorded
        # like every other component per the #251 auditability convention).
        dterm = downstream_term(cid, depends_on, claims)
        # stored at 6dp (sort precision; the to_dict/json face still rounds
        # to 3) so the #759 worth multiplier stays an exact identity.
        score = round(
            (case_value + W_DOWNSTREAM * dterm) * weight, 6)
        feeds = {
            "case_value": value_state,
            "case_flip_potential": (
                f"P(flip)={round(fp, 3)} (base {FLIP_POTENTIAL_BASE} decayed "
                f"by attempts={attempts_of(c)} [dispatches="
                f"{dispatch_count_of(c)}, failure_strikes="
                f"{strikes_of(c)}])"
                + ("" if linked else
                   f"; no oracle/PQ linkage -> {FLIP_POTENTIAL_FALLBACK} fallback")),
            "downstream": (
                f"downstream_weighted={round(dterm, 3)} "
                f"(decay {DOWNSTREAM_DECAY}, cap {DOWNSTREAM_CAP}, "
                f"weight {W_DOWNSTREAM})"),
        }
        # #103: attempts conversion is per-claim guarded; a dirty raw value
        # scores as 0 and surfaces here as a feed diagnostic instead of
        # freezing the whole DECIDE run in conservative BLOCKED. The
        # Action.attempts face reads the total attempt mass (attempts_of).
        attempts_dirty = _int_flag(c.get("promotion_attempts", 0))[1]
        dc_dirty = _int_flag(c.get("dispatch_count", 0))[1]
        if attempts_dirty:
            feeds["A"] = (f"promotion_attempts={c.get('promotion_attempts')!r} "
                          "unparseable -> treated as 0 (#103)")
        if dc_dirty:
            feeds["A"] = (f"dispatch_count={c.get('dispatch_count')!r} "
                          "unparseable -> treated as 0 (#103)")
        dc, _dc_dirty = _int_flag(c.get("dispatch_count", 0))
        if dc > 0:
            feeds["dispatch_count"] = (
                f"dispatch_count={dc} (independent of promotion_attempts="
                f"{attempts_of(c)}; the #690 branch act budget counts dispatches, "
                f"not promotions)")
        actions.append(Action(
            claim_id=cid, action=classify_action(c), score=score, skill=None,
            tier=action_tier(c), attempts=attempts_of(c), cost=action_cost(c),
            weight=weight, feeds=feeds,
        ))
        if not linked:
            unlinked_meta[cid] = (dterm, action_tier(c), weight)
    # #718 additive L1 planner signal: while the value store is empty
    # `advisory_factors` returns {} and nothing here runs (the ranking
    # above stays byte-identical — the frozen-capture contract). Once
    # learned, a claim whose dispatch the planner does not endorse (its
    # verified answer already exists — reuse dominates its ratio) is
    # dragged by the dispatch SHARE; exact-1.0 claims keep their score
    # and their feeds untouched. Fail-open: a broken planner never
    # touches the ranking result. #792: the planner fork seed derives
    # from the rank INPUT digests (never the round), so the planner face
    # cannot reintroduce round-dependence into the rank.
    planner_block: dict | None = None
    if evidence.ws is not None:
        factors: dict = {}
        try:
            from rlvr import l1_planner as _l1p  # noqa: PLC0415 — lazy
            factors = _l1p.advisory_factors(
                evidence.ws, [(a.claim_id, a.cost) for a in actions],
                rng=random.Random(f"l1rank/{claims_hash}/{evidence_hash}"))
        except Exception as exc:  # noqa: BLE001 — the rank never breaks
            warn("priority_ratio.planner",
                 f"{type(exc).__name__}: {exc}")
        moves = {cid: f for cid, f in factors.items() if 0.0 < f < 1.0}
        if moves:
            planner_block = {cid: round(f, 6) for cid, f in moves.items()}
            actions = [
                replace(a, score=round(a.score * moves[a.claim_id], 6),
                        feeds=dict(
                            a.feeds,
                            planner=f"l1 dispatch share={round(moves[a.claim_id], 6)} "
                                    f"(the planner does not endorse this "
                                    f"dispatch: a knowledge-solved claim is "
                                    f"reused unless a re-attempt's value/cost "
                                    f"beats the replay's)"))
                if a.claim_id in moves else a
                for a in actions]
    # #792 partition sort: value-bearing claims by composite score
    # descending; unlinked claims DEMOTED below every value-bearing one,
    # ordered by the declared deterministic default (downstream_term, tier,
    # worth); stable tie-break by claim id — the sort key is a pure
    # function of the actions and their unlinked metadata (no rng, no
    # round, no clock).
    def _rank_key(a: Action) -> tuple:
        meta = unlinked_meta.get(a.claim_id)
        if meta is None:
            return (0, -a.score, 0, 0.0, a.claim_id)
        dterm_u, tier_u, weight_u = meta
        return (1, -dterm_u, tier_u, -weight_u, a.claim_id)

    actions.sort(key=_rank_key)
    # #792 design 3: the explicit exploration slot (default OFF — see
    # EXPLORE_EVERY_N_ROUNDS). When enabled and the round hits the slot,
    # the best unlinked (or lowest-attempts) claim is promoted and
    # LABELED, never conflated with the value column.
    actions = _apply_exploration_slot(actions, unlinked_meta, round_no)
    # The emit below reads actions[0] as the event's arm — valid only
    # because this sort already ran: actions[0] IS the selected arm.
    # #157: one rank_feeds event per RUN (post-decision, silent fail-open).
    # The emit consumes the ALREADY-BUILT actions — a crash inside it can
    # never change the ranking result (pinned by
    # tests/test_algorithm_event_log_157.py). No ws -> pure in-memory
    # surface, nothing to log to (bare-EvidenceView calls stay pure).
    if evidence.ws is not None:
        _emit_rank_feeds(evidence.ws, claims, evidence,
                         {"claims_hash": claims_hash,
                          "evidence_hash": evidence_hash,
                          "posterior_hash": posterior_hash},
                         actions, round_no=round_no, planner=planner_block)
    return actions


def _apply_exploration_slot(actions: list[Action],
                            unlinked_meta: dict[str, tuple[float, int, float]],
                            round_no: int | None) -> list[Action]:
    """#792 design 3 — the DECLARED epsilon slot. Disabled (the default,
    EXPLORE_EVERY_N_ROUNDS == 0) this is the identity. Enabled, every Nth
    round promotes the best unlinked claim (or, with none, the
    lowest-attempts claim) to the front and labels it `exploration_arm` in
    feeds — the value scores of every row are untouched, so the promotion
    is never conflated with the value column. Pure: same inputs -> the
    same promoted arm (ties break by the incoming sort order)."""
    n = EXPLORE_EVERY_N_ROUNDS
    if n <= 0 or round_no is None or len(actions) < 2 \
            or round_no % n != 0:
        return actions
    pick = next((a for a in actions if a.claim_id in unlinked_meta), None)
    if pick is None:
        pick = min(actions, key=lambda a: (a.attempts, a.claim_id))
    if pick is actions[0]:
        return actions
    labeled = replace(pick, feeds=dict(
        pick.feeds,
        exploration_arm=(f"exploration arm: round {round_no} slot "
                         f"(every {n}) — coverage promotion; value column "
                         f"untouched (#792 design 3)")))
    return [labeled] + [a for a in actions if a is not pick]


# ---------- strategy convergence four metrics ----------
# Four orthogonal convergence questions layered atop the ranker's own
# action/evidence model: reverse-regret vs an oracle selection,
# efficient-frontier slope (diminishing returns), conditional
# P(faster | hit), and tool-family competence coverage. Pure
# functions (zero LLM, no I/O) — embeddable without the workspace.
# snapshot_for_workspace assembles the full snapshot from workspace
# artefacts (validated_capability cards + the optional hit_times
# file); the CLI face is priority_ratio.main's --strategy flag.

# ---------- regret ----------

def regret(actions: list[dict], picked: set[str], oracle: set[str]) -> dict:
    """Reverse-regret vs. oracle selection.

    regret = score(oracle_top) − score(picked_top), bounded below by 0.
    Empty actions → 0 (trivially converged).  Multi-action oracle/picked
    supported: top score wins on each side; missing top → use 0.

    Returns {"regret": float, "picked": list[str], "oracle": list[str]} —
    the picked/oracle echoes aid debugging the metric when it spikes.
    """
    if not actions:
        return {"regret": 0.0, "picked": [], "oracle": []}

    def _top(ids: set[str]) -> tuple[float, str | None]:
        if not ids:
            return 0.0, None
        ranked = [a for a in actions if a.get("claim_id") in ids]
        if not ranked:
            return 0.0, None
        ranked.sort(key=lambda a: a.get("score", 0.0), reverse=True)
        return ranked[0].get("score", 0.0), ranked[0].get("claim_id")

    oracle_score, oracle_id = _top(oracle)
    picked_score, picked_id = _top(picked)
    # both empty → 0; else subtract
    if oracle_id is None and picked_id is None:
        return {"regret": 0.0, "picked": [], "oracle": []}
    loss = oracle_score - picked_score
    if loss < 0:
        loss = 0.0  # negative regret → picked beat oracle (just luck / ahead of information)
    return {
        "regret": round(float(loss), 6),
        "picked": [picked_id] if picked_id else [],
        "oracle": [oracle_id] if oracle_id else [],
    }


# ---------- cost_to_slope ----------

def cost_to_slope(actions: list[dict]) -> list[dict]:
    """Efficient-frontier curve: per-action Δscore/Δcost.

    Sorted by cost ascending; computes prefix sums, then per-step
    marginal slope (cumulative Δscore / cumulative Δcost).  First row is
    always `slope=None` (cannot form a slope with one point) so callers
    can drop it without indexing errors.

    Returns list[{"claim_id", "cost", "score", "cum_score", "cum_cost", "slope"}].
    Empty input → [].
    """
    if not actions:
        return []
    sorted_actions = sorted(actions, key=lambda a: (a.get("cost", 0.0), a.get("claim_id", "")))
    rows: list[dict] = []
    prev_cum_score = 0.0
    prev_cum_cost = 0.0
    first = True
    for a in sorted_actions:
        cost = float(a.get("cost", 0.0))
        score = float(a.get("score", 0.0))
        cum_score = prev_cum_score + score
        cum_cost = prev_cum_cost + cost
        if first:
            slope = None
        else:
            d_score = cum_score - prev_cum_score
            d_cost = cum_cost - prev_cum_cost
            slope = (d_score / d_cost) if d_cost > 0 else None
        rows.append({
            "claim_id": a.get("claim_id"),
            "cost": cost,
            "score": score,
            "cum_score": round(cum_score, 6),
            "cum_cost": round(cum_cost, 6),
            "slope": round(slope, 6) if slope is not None else None,
        })
        prev_cum_score = cum_score
        prev_cum_cost = cum_cost
        first = False
    return rows


# ---------- P(faster | hit) ----------

def _median(values: Iterable[float]) -> float:
    """Median of a finite iterable.  Empty → 0.0 (no signal)."""
    vs = sorted(values)
    n = len(vs)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return float(vs[mid])
    return (vs[mid - 1] + vs[mid]) / 2.0


def p_faster_given_hit(hits: list[float], median_hit_time: float | None = None) -> dict:
    """Conditional P(faster | hit) — fraction of hits faster than median.

    If median_hit_time is omitted, compute it from the hits directly
    (defined only when n > 0; the test pins an explicit median so the
    formula is reproducible against a fixed reference).

    Returns {"p_faster": float, "hits": int, "median": float}.
    """
    if not hits:
        return {"p_faster": 0.0, "hits": 0, "median": 0.0}
    median = median_hit_time if median_hit_time is not None else _median(hits)
    if median <= 0:
        # pathological: zero-or-negative median ⇒ degenerate; treat as no signal
        return {"p_faster": 0.0, "hits": len(hits), "median": median}
    faster = sum(1 for t in hits if t < median)
    return {
        "p_faster": round(faster / len(hits), 6),
        "hits": len(hits),
        "median": round(float(median), 6),
    }


# ---------- competence coverage ----------

def competence_coverage(validated_families: set[str], required_families: set[str]) -> dict:
    """Coverage = |validated ∩ required| / |required|.

    Empty required → 1.0 (trivially covered; nothing missing by definition).
    All-required-missing → 0.0 with every required family echoed in
    `missing` (sorted) for the dispatch gate to consume.

    Returns {"coverage": float, "missing": list[str], "validated": list[str]}.
    """
    validated = {str(f) for f in (validated_families or set())}
    required = {str(f) for f in (required_families or set())}
    if not required:
        return {"coverage": 1.0, "missing": [], "validated": sorted(validated)}
    missing = sorted(required - validated)
    covered = required & validated
    return {
        "coverage": round(len(covered) / len(required), 6),
        "missing": missing,
        "validated": sorted(validated),
    }


# ---------- composite ----------

def compute_all(actions: list[dict], picked: set[str], oracle: set[str],
                hits: list[float] | None = None,
                validated_families: set[str] | None = None,
                required_families: set[str] | None = None) -> dict:
    """Bundle the four metrics into one snapshot dict.

    Optional inputs (hits / families) default empty; p_faster_given_hit
    and competence_coverage each degrade to their trivial defaults.
    """
    return {
        "regret": regret(actions, picked, oracle),
        "cost_to_slope": cost_to_slope(actions),
        "p_faster_given_hit": p_faster_given_hit(hits or []),
        "competence": competence_coverage(validated_families or set(),
                                          required_families or set()),
    }


# ---------- integration helpers (workspace-backed; optional) ----------

def snapshot_for_workspace(workspace: Path,
                           picked: set[str] | None = None,
                           oracle: set[str] | None = None,
                           hits: list[float] | None = None,
                           required_families: set[str] | None = None) -> dict:
    """Read-only integration: rank the workspace, then assemble the
    four-metric snapshot.

    Loads claim-register.yaml + claim_deps.yaml, runs the ranker to
    produce the action list, then assembles the four-metric snapshot
    from the workspace artefacts (validated_capability cards + the
    optional hit_times file).  All four inputs are optional; the
    corresponding metric degrades to its no-signal default.

    Required-families defaults to nothing (the metric reports coverage=1.0
    until the workspace declares requirements — its own contract: the
    metric cannot fail closed without an explicit requirement list)."""
    ws = Path(workspace)
    reg = _load_yaml(ws / "claim-register.yaml")
    deps = _load_yaml(ws / "claim_deps.yaml")
    claims = reg.get("claims") or []
    evidence = EvidenceView.from_workspace(ws)
    actions = priority_ratio(claims, deps, evidence)
    action_dicts = [a.to_dict() for a in actions]
    validated = {fam for _, text in evidence.validated_capabilities
                 for fam in _families_from_text(text)}
    return compute_all(
        actions=action_dicts,
        picked=picked or set(),
        oracle=oracle or set(),
        hits=hits or [],
        validated_families=validated,
        required_families=required_families or set(),
    )


_FAMILY_TOKENS = ("frida", "xposed", "lsposed", "ghidra", "ida",
                  "idapython", "x64dbg", "ollydbg", "volatility",
                  "vmr-shell", "vmrun", "qiling", "malware-framework")


def _families_from_text(text: str) -> set[str]:
    """Best-effort family extraction from validated_capability text.
    ASCII word-bounded; mirrors priority_ratio's vocabulary."""
    import re
    found: set[str] = set()
    for tok in _FAMILY_TOKENS:
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(tok) + r"(?![A-Za-z0-9])",
                     text or "", re.IGNORECASE):
            found.add(tok)
    return found


def _load_yaml(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="priority_ratio.py", description="Thompson action ranking")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strategy", action="store_true",
                    help="print the four-metric convergence snapshot "
                         "(regret / cost_to_slope / p_faster_given_hit / "
                         "competence) instead of the action ranking")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    if args.strategy:
        snap = snapshot_for_workspace(ws)
        print(json.dumps(snap, ensure_ascii=False, indent=2) if args.json
              else "\n".join(f"{k}: {v}" for k, v in snap.items()))
        return 0
    # #534 lifeline (#104): relocated from module scope — the old block read an
    # undefined module-level `ws` and was NameError-swallowed, never emitted.
    try:
        kunglao_log.emit(ws, actor="priority_ratio",
                         action="priority_deviation", detail="module wired")
    except Exception as exc:  # noqa: BLE001 — observability never disturbs the run
        warn("main", f"{type(exc).__name__}: {exc}")
    reg = _load_yaml(ws / "claim-register.yaml")
    deps = _load_yaml(ws / "claim_deps.yaml")
    evidence = EvidenceView.from_workspace(ws)
    claims = reg.get("claims") or []
    actions = priority_ratio(claims, deps, evidence)
    # #610: plain-text reads the typed actions; out stays the --json payload only
    out = [a.to_dict() for a in actions]
    print(json.dumps(out, ensure_ascii=False, indent=2) if args.json else "\n".join(
        f"{a.claim_id:<6} {a.action:<22} score={a.score:<7} tier={a.tier} cost={a.cost}"
        for a in actions) or "(no dispatchable claims)")
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
