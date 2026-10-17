# -*- coding: utf-8 -*-
"""rlvr/scalar.py — two-level settlement + 3-tuple extraction (issue 379).

Issue #420 Phase 2: the implementation body moved here from
scripts/scalar_settlement.py (which stays a thin re-export adapter).

Level 1 — EPISODE settlement (reward-rules.yaml v2 ``tier_table``): the
fine-grained tiered scalar (GOLD 1.0 / SILVER 0.7 / BRONZE 0.4 /
NEUTRAL 0 / RED 0) entered by pure if-then conditions over MECHANICAL
dimensions (oracle verdict + probe sub-scores, evidence class,
cost-vs-class-reference, difficulty). Tier evaluation is FIRST-MATCH in
severity order with RED override. The tier scalar refines WITHIN the v1
polarity bands — it never raises a SETTLED_RED row and never lowers a
SETTLED_GREEN row's ledger reward (task/oracle-green is never_demoted).

Level 2 — ROUND credit settlement: per-dispatch rows
``r_i = full-credit artifacts created in dispatch i + one trace total per
demotion class present - attributed waste``, provenance-exact via the fact
frontmatter ``creator`` field (the dispatch trace id the worker echo'd at
creation). NO positional weighting — the time-preference ruling removed
the per-step weighting symbol from this design twice: the round index
orders rows, it never weights them; ``untraced`` artifacts are listed and
counted toward no dispatch. Issue 433 (value alignment, anti
fact-farming): credit is a VALUE LADDER, not a verified-count —
``verified`` is the admission ticket, ``cited / used-toward-stage`` is
the value condition; uncited verified artifacts settle one trace total
per dispatch row (the exploration option, worthless until cited), and a
late citation back-promotes through the amendment path. Issue 438
closes the ACTIVE vector: the citation surfaces are worker-writable
(one question-bearing claim stamp on N facts), so at most
CITED_CAP_DEFAULT cited artifacts per dispatch row settle FULL —
deterministic id-sort selection, no preference channel; the excess
joins the class demotion face as ``cited_over_cap``, and a capped
artifact that lands within a later settlement's cap amends up through
the same late-cite path. See the ladder block at ROUND_CREDIT_FULL.

Settlement output — the experience 3-tuple ``(s, a, r)`` is extracted AT
settlement as a first-class settlement-document field
(``experience_tuple``): the tuple's birth certificate. The tuple store is
the RL experience base; the contextual Q table (M1) is its soft-Q view.

Prior wiring: ``scalar_observations`` feeds compute_priors as a NEW
additive source (continuous scalars -> Normal-Gamma, an exponential-family
conjugate update — NOT Beta-Bernoulli; exponential-family Thompson
sampling regret is grounded in Russo & Van Roy 2014 "Learning to Optimize
via Posterior Sampling" + the information-ratio bound, which is why the
scalar posterior stays in the exponential family the TS literature
covers).

The import surface is allowlisted and pinned by test: pure if-then over
machine signals — no model-call path, no judgment slots (U3 extended).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np  # issue 420: ordered-float reductions only (see _seq_sum)

from rlvr import ledger as rl  # the package face (issue 420 Phase 2)

# the round-credit rollout kind — the ledger's OPEN ENUM registration API
# (a new kind is one register_kind entry, never an ad-hoc string).
rl.register_kind("round_credit", "per-dispatch round credit row (issue 379)")

KIND_ROUND_CREDIT = "round_credit"
BAND_ROUND_CREDIT = "ROUND_CREDIT"
RULE_ROUND_CREDIT = "round/provenance-credit"
RULE_NEUTRAL = "tier/neutral"
RULE_RED = "tier/red"

# --- round-credit VALUE LADDER (issue 433: anti fact-farming) --------------
#
# Declared in reward-rules.yaml round_credit.value_ladder; FIRST-MATCH:
#   cited / used-toward-stage verified artifact -> FULL 1.0
#   refuted-with-replay-evidence -> TRACE (information option)
#   verified but never cited -> TRACE (exploration option, worthless
#     until cited; demotion reason uncited_verified)
#   action success / tool ran -> 0
# No stage-milestone arm is declared: a milestone artifact (layer
# falls, key recovered) is stage use by construction, so it enters
# through the cited / used-toward-stage arm and keeps full credit
# there (plus the existing V-jump attribution face); an unlinked
# milestone settles the exploration-option trace — the disclosed
# under-credit-only assumption (issue 438 minor tail removed the
# declaration-only leg).
# ``verified`` is the ADMISSION TICKET, ``cited`` the value condition —
# the issue-433 inversion. The uncited demotion is a CLASS demotion: one
# trace total per dispatch row per demotion class, never a per-unit
# price — N farmed facts earn the same single exploration-option value
# as one, so the farming gradient dies at any N; back-promotion is
# per-fact via late citation (the amendment path).
#
# Issue 438 (the ACTIVE farming vector): the citation surfaces are
# worker-writable (fact frontmatter ``claim_id``; lint registers
# EXISTENCE only), so ONE question-bearing claim stamp on N verified
# facts would settle N x full. The per-dispatch cited cap closes it: at
# most CITED_CAP_DEFAULT cited artifacts per dispatch row earn FULL; the
# excess settles at the TRACE CLASS level (one trace total for the
# capped class, mirroring the uncited demotion's class semantics) under
# the named reason ``cited_over_cap`` — auditable, the worker sees WHY.
# Selection is DETERMINISTIC — the row's cited artifacts sort by
# artifact id, the first K stay full (no preference channel). Genuine
# deep citations still reward: a capped artifact that lands within a
# LATER settlement's cap amends up through the existing late-cite path
# (no extra code).
#
# Owner ruling 2026-09-28: within-cell homogeneity is a STATE-SIGNATURE
# property, not a reward property — NO reward-side normalization here;
# the cell structure already conditions the comparison (the full ruling
# wording lives in reward-rules.yaml round_credit.value_ladder.note).
ROUND_CREDIT_FULL = 1.0
DEMOTION_UNCITED_VERIFIED = "uncited_verified"
DEMOTION_REFUTED_INFORMATION = "refuted_with_replay_evidence"
# issue 438 per-dispatch cited cap: at most this many cited artifacts
# per dispatch row settle FULL; the excess demotes to the TRACE class
# (reason below). A named module constant ON PURPOSE (minimum diff) —
# the reward-rules.yaml promotion is a declared follow-up, not this
# change.
CITED_CAP_DEFAULT = 2

# --- the deliverable-citation producer (issue 678, T2) ---------------------
#
# ``cited_ids`` had NO production caller: ``cited_by_deliverable`` was
# permanently False and the deliverable half of the issue-433 citation
# relation was dead (only the claim-provenance leg ever fired). The
# producer scans the deliverable-facing document trees (notes/ results
# layer, analyses/ long-form, runs/deliverables/) for ``F<NNN>`` fact-id
# mentions. Content reads only, tolerant: an unreadable file contributes
# no citations and never raises (the question_claims precedent).
CITED_DELIVERABLE_RELS = ("notes", "analyses", "runs/deliverables")
CITED_DELIVERABLE_SUFFIXES = frozenset({".md", ".txt", ".yaml", ".yml"})
FACT_ID_CITE_RE = re.compile(r"\bF\d{3}\b")
DEMOTION_CITED_OVER_CAP = "cited_over_cap"

# --- settlement fairness: the sorted observation face -----------------------
#
# The banked ladder receipt stays the ladder value; cost enters ONLY the
# r_sorted companion (r_sorted = r_ladder - LAMBDA * cost), an
# ordering/observation field for downstream consumers. The offline spike
# measured the cost term as tie-breaking power alone (Spearman 0.929
# against the ladder ordering) — so it prices the receipt never: same
# output at higher cost ranks lower on r_sorted, settles identically on
# reward. LAMBDA is a documented policy constant, not a fitted parameter
# (the state.py precedent). Cost is the caller's normalized units —
# token/hour scale constants live with the transition ledger
# (rlvr.incremental_reward COST_TOKENS_DIV / COST_SECONDS_DIV).
SORT_COST_LAMBDA = 1.0

# The branch_budget hard constraint's settlement face: overrun is waste
# in the SAME unit as the ladder (1.0 = one full-credit artifact). Wall
# overrun normalizes at the transition ledger's hour scale (one wasted
# wall-hour = one waste unit); each retry over the declared budget books
# one waste unit. Both dimensions are measured facts — a budget without
# a usage (or the reverse) cannot overrun and books nothing.
BUDGET_RETRY_WASTE_UNIT = 1.0
# cross-linked by comment, not import (the dead_letter.DLQ_ATTEMPTS
# precedent): rlvr.incremental_reward.COST_SECONDS_DIV is the same
# hour scale — one value per repo, restated here only because the
# scalar engine's import allowlist stays intra-package-rlvr minimal.
BUDGET_WALL_DIV = 3_600.0

# outcome_class vocabulary — the act-outcome taxonomy the strategy
# learning faces book against. BLOCKED is the environment refusing the
# act (the measured noise source: infra outcomes dominating clean
# strategy failures); TIMEOUT is right-censored (the end was never
# observed); everything else is the strategy's own outcome. Conservative
# membership: only BLOCKED classifies infra — a crashed or failed act
# still carries strategy signal, a refused act carries none.
OUTCOME_STRATEGY = "strategy"
OUTCOME_INFRA = "infra"
OUTCOME_CENSORED = "censored"
INFRA_OUTCOMES = frozenset({"BLOCKED"})
CENSORED_OUTCOMES = frozenset({"TIMEOUT"})

TIER_GOLD = "GOLD"
TIER_SILVER = "SILVER"
TIER_BRONZE = "BRONZE"
TIER_TRACE = "TRACE"    # v3 validator output-scale name (issue 390/396)
TIER_NEUTRAL = "NEUTRAL"
TIER_RED = "RED"
MEASURED_TIERS = frozenset({TIER_GOLD, TIER_SILVER, TIER_BRONZE, TIER_RED})

# Normal-Gamma prior constants — documented policy constants (the lambda
# precedent: values carry a one-line rationale, they are not fitted).
NG_MU0 = 0.5     # scalar support midpoint (tiers live in [0, 1])
NG_KAPPA0 = 1.0  # one pseudo-observation of prior strength (weak)
NG_A0 = 1.0
NG_B0 = 1.0
from kunglao_log import warn  # canonical warn: one impl, dedupe + ledger face


def _now() -> str:
    from harness_common import utc_now_z
    return utc_now_z()


def _last(signals: list[dict], type_: str):
    """Last machine signal value of a type (fold order = append order)."""
    val = None
    for s in signals:
        if str(s.get("type") or "") == type_:
            val = s.get("value")
    return val


# --- dimension extraction (pure, mechanical) -------------------------------

def _probe_progress(signals: list[dict]) -> tuple[float, int, int] | None:
    """Aggregate probe sub-scores (checker static X/Y + replay N/M + chain
    dense layers): (done, total, faces) -> progress p. None when no probe
    face is present."""
    done = total = 0
    for type_ in ("static_probes", "replay_probes", "dense_layers"):
        v = _last(signals, type_)
        if not isinstance(v, dict):
            continue
        d = v.get("passed", v.get("completed", 0))
        t = v.get("total", 0)
        if not isinstance(d, (int, float)) or not isinstance(t, (int, float)):
            continue
        done += max(float(d), 0.0)
        total += max(float(t), 0.0)
    if total <= 0:
        return None
    return done, total, 1


def outcome_dim(signals: list[dict]) -> dict | None:
    """D1 outcome: PASS / partial(p) / FAIL from the oracle verdict plus
    the mechanical probe sub-scores. None when no verdict exists (the
    outcome axis is missing — nothing settles through this leg)."""
    verdict = _last(signals, "oracle_verdict")
    if verdict is None:
        return None
    verdict = str(verdict).strip().lower()
    progress = _probe_progress(signals)
    if verdict == "pass":
        return {"outcome": "pass", "p": 1.0}
    if progress is not None and progress[0] > 0:
        done, total, _ = progress
        return {"outcome": "partial", "p": done / total}
    return {"outcome": "fail", "p": 0.0}


def difficulty_dim(signals: list[dict]) -> str | None:
    """D2 difficulty: the unit manifest's resistance marker."""
    v = _last(signals, "unit_difficulty")
    v = str(v or "").strip().lower()
    return v if v in ("hard", "standard") else None


def evidence_dim(signals: list[dict]) -> str | None:
    """D4 evidence class: rerun-reproducible vs asserted-only."""
    v = _last(signals, "evidence_class")
    v = str(v or "").strip().lower()
    return v if v in ("reproducible", "asserted") else None


def cost_dim(signals: list[dict], cost_reference: dict) -> dict | None:
    """D3 cost: session spend vs the unit-class reference (class median +
    k from the measured exp1-7 distribution). None when no cost signal or
    an unknown class (no reference -> no cost judgment)."""
    cost = _last(signals, "session_cost")
    unit_class = _last(signals, "unit_class")
    if not isinstance(cost, (int, float)):
        return None
    medians = (cost_reference or {}).get("unit_class_median_usd") or {}
    median = medians.get(str(unit_class or ""))
    if not isinstance(median, (int, float)) or median <= 0:
        return None
    k = float((cost_reference or {}).get("k") or 0) or None
    ratio = float(cost) / float(median)
    return {"cost": float(cost), "median": float(median), "ratio": ratio,
            "within_median": ratio <= 1.0,
            "expensive": bool(k is not None and ratio > k)}


def extract_dimensions(signals: list[dict],
                       cost_reference: dict) -> dict:
    """All mechanical dimensions from one machine signal set (each cites
    its measurement source in reward-rules.yaml v2)."""
    return {
        "outcome": outcome_dim(signals),
        "difficulty": difficulty_dim(signals),
        "evidence": evidence_dim(signals),
        "cost": cost_dim(signals, cost_reference),
        "probes": _probe_progress(signals),
    }


# --- the tier engine (pure if-then, first-match by severity) ---------------

def classify_tier(signals: list[dict], tier_table: dict,
                  cost_reference: dict) -> dict:
    """Deterministic tier classification over mechanical dimensions.

    First-match in severity_order (RED override first), anti-pollution
    gate: fewer than min_machine_signals machine signals or zero
    corroborating dimensions land NEUTRAL. Returns {tier, tier_reward,
    tier_rule_id, dimensions, evidence_refs, inefficient?}."""
    machine = [s for s in (signals or []) if not s.get("advisory")]
    scalars = tier_table.get("scalars") or {}
    min_signals = int(tier_table.get("min_machine_signals") or 1)
    dims = extract_dimensions(machine, cost_reference)
    refs = [f"{s.get('type')}:{s.get('source')}="
            f"{json.dumps(s.get('value'), ensure_ascii=False, sort_keys=True)}"
            for s in machine]

    def _out(tier: str, rule_id: str, **extra) -> dict:
        doc = {"tier": tier, "tier_reward": float(scalars.get(tier, 0.0)),
               "tier_rule_id": rule_id, "dimensions": dims,
               "evidence_refs": refs}
        doc.update(extra)
        return doc

    outcome = dims["outcome"]
    corroborators = sum(1 for key in ("difficulty", "evidence", "cost",
                                      "probes") if dims[key] is not None)
    if outcome is None or corroborators == 0 or len(machine) < min_signals:
        return _out(TIER_NEUTRAL, RULE_NEUTRAL)
    if outcome["outcome"] == "fail":
        return _out(TIER_RED, RULE_RED)  # RED overrides everything
    if outcome["outcome"] == "partial":
        rule = str(tier_table.get("partial_rule") or "tier/partial-dense")
        return _out(TIER_BRONZE, rule, partial=outcome["p"])
    if dims["cost"] is not None and dims["cost"]["expensive"]:
        rule = str(tier_table.get("expensive_rule")
                   or "tier/bronze-expensive")
        return _out(TIER_BRONZE, rule, inefficient=True)
    within = dims["cost"] is None or dims["cost"]["within_median"]
    hard = dims["difficulty"] == "hard"
    reproducible = dims["evidence"] == "reproducible"
    if hard and reproducible and within:
        return _out(TIER_GOLD, "tier/gold")
    if (reproducible or hard) and within:
        return _out(TIER_SILVER, "tier/silver")
    return _out(TIER_BRONZE, "tier/bronze")


# --- the experience 3-tuple (settlement output) ----------------------------

def extract_tuple(signals: list[dict], tier_doc: dict) -> dict:
    """(s, a, r) at settlement — s from the unit manifest signals
    (family x tier x difficulty-marker), a from the strategy arm + key
    method choices, r from the tier scalar. Absent dims are explicit
    nulls (honest absence, not missing keys)."""
    dims = tier_doc.get("dimensions") or {}
    choices = _last(signals, "method_choices")
    return {
        "s": {"family": _last(signals, "unit_family"),
              "tier": _last(signals, "unit_tier"),
              "difficulty": dims.get("difficulty")},
        "a": {"arm": _last(signals, "strategy_arm"),
              "choices": list(choices) if isinstance(choices, list) else []},
        "r": float(tier_doc.get("tier_reward", 0.0)),
    }


# --- episode scalar settlement (the amendment face) ------------------------

def settle_workspace_scalars(ws, rules_path: Path | str | None = None,
                             now=None) -> dict:
    """Append the tier-scalar amendment for every settled task rollout
    whose settlement does not carry one yet. Idempotent; the v1 band,
    reward and rule_id are preserved verbatim (the scalar refines within
    the polarity currency); a v1 RED/ADVERSE band forces tier RED, a v1
    NEUTRAL stays tier NEUTRAL (pending is pending). Returns
    {"seen", "settled", "by_tier"}."""
    ws = Path(ws)
    from rlvr import reward as rs  # the package face (issue 420 Phase 2)
    doc = rs.load_rules(rules_path)
    tier_table = doc.get("tier_table") or {}
    cost_reference = doc.get("cost_reference") or {}
    by_tier: dict[str, int] = {}
    settled_n = seen = 0
    for row in rl.settled(ws, kind="task"):
        st = row.get("settlement") or {}
        if "tier" in st:
            continue
        seen += 1
        tier_doc = classify_tier(row.get("signals") or [], tier_table,
                                 cost_reference)
        band = str(st.get("band") or "")
        if band in ("SETTLED_RED", "ADVERSE"):
            tier_doc = dict(tier_doc, tier=TIER_RED,
                            tier_reward=float(
                                tier_table.get("scalars", {}).get(
                                    TIER_RED, 0.0)),
                            tier_rule_id=RULE_RED)
        elif band == "NEUTRAL" or not band:
            tier_doc = dict(tier_doc, tier=TIER_NEUTRAL,
                            tier_reward=float(
                                tier_table.get("scalars", {}).get(
                                    TIER_NEUTRAL, 0.0)),
                            tier_rule_id=RULE_NEUTRAL)
        amended = dict(st)
        amended["tier"] = tier_doc["tier"]
        amended["tier_reward"] = tier_doc["tier_reward"]
        amended["tier_rule_id"] = tier_doc["tier_rule_id"]
        amended["tier_dimensions"] = tier_doc["dimensions"]
        amended["tier_evidence_refs"] = tier_doc["evidence_refs"]
        if "partial" in tier_doc:
            amended["tier_partial"] = tier_doc["partial"]
        if "inefficient" in tier_doc:
            amended["tier_inefficient"] = tier_doc["inefficient"]
        amended["experience_tuple"] = extract_tuple(
            row.get("signals") or [], tier_doc)
        amended["tier_settled_ts"] = now or _now()
        res = rl.settle(ws, str(row.get("rollout_id")), amended)
        if res.get("appended"):
            settled_n += 1
            by_tier[tier_doc["tier"]] = \
                by_tier.get(tier_doc["tier"], 0) + 1
        else:
            warn("settle_workspace_scalars",
                 f"{row.get('rollout_id')}: {res.get('reason')}")
    return {"seen": seen, "settled": settled_n, "by_tier": by_tier,
            "rules_version": doc.get("version")}


def tuples(ws, kind: str = "task") -> list[dict]:
    """Read face over the extracted 3-tuples (the tuple store view of the
    settlement birth certificates; consumers = the contextual Q table)."""
    out: list[dict] = []
    for row in rl.settled(ws, kind=kind):
        st = row.get("settlement") or {}
        tup = st.get("experience_tuple")
        if not tup:
            continue
        out.append(dict(tup, rollout_id=str(row.get("rollout_id")),
                        tier=st.get("tier"),
                        settled_ts=st.get("tier_settled_ts")))
    return out


# --- round credit settlement -------------------------------------------------

_CREDIT_TERMINALS = frozenset({"PROVEN", "VERIFIED"})
_REFUTATION_STATUSES = frozenset({"NEGATIVE", "REFUTED"})


def _artifact_cited(artifact: dict) -> bool:
    """The citation relation — the issue-433 single chokepoint.

    An artifact is CITED iff it is named by a deliverable
    (``cited_by_deliverable`` — the deliverable citation face) OR linked
    via claim provenance to a question-bearing claim
    (``answers_question`` — the fact frontmatter claim_id resolving in
    claim-register.yaml to a claim with a non-null answers_question; the
    same surface the verdict scorer walks pq -> claim -> linked fact).
    Pure: same artifact face -> same verdict; the workspace-side
    determination of both legs lives in fact_artifacts."""
    return bool(artifact.get("cited_by_deliverable")
                or artifact.get("answers_question"))


def _artifact_credit(artifact: dict) -> tuple[float, str | None]:
    """One artifact's round-credit value under the issue-433 ladder:
    ``(value, demotion reason or None)``. FIRST-MATCH:
      terminal-verified + cited             -> (FULL, None)
      terminal-verified, never cited        -> (TRACE, uncited_verified)
      oracle-backed refutation w/ replay    -> (TRACE,
                                                refuted_with_replay_evidence)
      anything else (action/tool success)   -> (0.0, None)
    An unverified artifact earns nothing even when cited — verified is
    the admission ticket, not an alternative value path."""
    status = str(artifact.get("status") or "").strip().upper()
    if status in _CREDIT_TERMINALS:
        if _artifact_cited(artifact):
            return ROUND_CREDIT_FULL, None
        return TRACE_CANONICAL, DEMOTION_UNCITED_VERIFIED
    if (status in _REFUTATION_STATUSES
            and artifact.get("oracle_backed_refutation")
            and str(artifact.get("verify_status") or "").lower()
            == "passes"):
        return TRACE_CANONICAL, DEMOTION_REFUTED_INFORMATION
    return 0.0, None


def classify_outcome(o_status: str) -> str:
    """The outcome_class of one act outcome: censored (TIMEOUT — the end
    was never observed), infra (BLOCKED — the environment refused the
    act; no strategy signal), strategy (everything else). Pure; the
    strategy-learning faces book against this, never raw status words."""
    s = str(o_status or "").strip().upper()
    if s in CENSORED_OUTCOMES:
        return OUTCOME_CENSORED
    if s in INFRA_OUTCOMES:
        return OUTCOME_INFRA
    return OUTCOME_STRATEGY


def budget_overrun(branch_budget, usage) -> float:
    """The branch_budget hard constraint's settlement face: attributed
    waste from exceeding a declared budget. Wall overrun normalizes at
    the transition ledger's hour scale (one wasted wall-hour = one waste
    unit, same unit as the ladder); each retry over the declared budget
    books one waste unit. Both dimensions must be measured — a budget
    without a usage (or the reverse) books nothing (the honest gap).
    Non-mapping inputs book nothing. Never raises."""
    if not isinstance(branch_budget, dict) or not isinstance(usage, dict):
        return 0.0
    waste = 0.0
    cap = branch_budget.get("wall_s")
    used = usage.get("wall_s")
    if isinstance(cap, (int, float)) and not isinstance(cap, bool) \
            and isinstance(used, (int, float)) and not isinstance(used, bool):
        if used > cap:
            waste += (float(used) - float(cap)) / BUDGET_WALL_DIV
    retries_cap = branch_budget.get("retries")
    retries_used = usage.get("retries")
    if isinstance(retries_cap, (int, float)) \
            and not isinstance(retries_cap, bool) \
            and isinstance(retries_used, (int, float)) \
            and not isinstance(retries_used, bool):
        if retries_used > retries_cap:
            waste += (float(retries_used) - float(retries_cap)) \
                * BUDGET_RETRY_WASTE_UNIT
    return waste


def _credit_row(d: dict, credited_by: dict, demoted_by: dict,
                waste_by: dict, overrun_by: dict) -> dict | None:
    """One dispatch's round-credit row: the cited cap (deterministic
    id-sort selection — the first CITED_CAP_DEFAULT cited artifacts
    keep FULL, the excess joins the demotion face under the named
    reason), ONE trace total per demotion CLASS present, waste
    subtracted, and the additive-when-present fairness seams
    (r_sorted from a carried cost; budget_overrun when the dispatch
    overran its branch_budget). None when the dispatch id is empty."""
    did = str(d.get("dispatch_id") or "")
    if not did:
        return None
    full_sorted = sorted(credited_by[did])
    credited = full_sorted[:CITED_CAP_DEFAULT]
    over_cap = full_sorted[CITED_CAP_DEFAULT:]
    demoted = demoted_by[did] + [
        {"id": aid, "reason": DEMOTION_CITED_OVER_CAP}
        for aid in over_cap]
    trace_total = TRACE_CANONICAL * len({e["reason"] for e in demoted})
    r = float(len(credited)) + trace_total - waste_by[did]
    row = {"dispatch_id": did,
           "round": d.get("round"),  # ordering info ONLY
           "credited": credited,
           "demoted": demoted,
           "waste": waste_by[did],
           "r": r}
    cost = d.get("cost")
    if isinstance(cost, (int, float)) and not isinstance(cost, bool):
        row["r_sorted"] = round(r - SORT_COST_LAMBDA * float(cost), 6)
    if did in overrun_by:
        row["budget_overrun"] = round(overrun_by[did], 6)
    return row


def round_credit(dispatches: list[dict], artifacts: list[dict],
                 waste: list[dict] | None = None) -> dict:
    """Pure round-credit core: per-dispatch
    ``r_i = full-credit artifacts created in i + one trace total per
    demotion class present - attributed_waste(i)`` under the issue-433
    value ladder with the issue-438 per-dispatch cited cap (see the
    ladder block at ROUND_CREDIT_FULL).

    Provenance-exact attribution on the artifact ``creator`` field (the
    dispatch id); the round index carries ordering information only and
    never weights the sum. Artifacts with no creator (or a creator
    outside the dispatch set) are ``untraced``: listed, counted toward
    no dispatch. Demoted artifacts are listed per artifact with their
    reason (``demoted``) so the gradient is auditable — the worker sees
    WHY the credit is low. The cap (issue 438) bounds the cited FULL
    face per row at CITED_CAP_DEFAULT (deterministic id-sort selection);
    the excess demotes under ``cited_over_cap`` and stays rescue-eligible
    through the late-cite amendment path.

    Settlement-fairness seams (additive-when-present, byte-identical
    when absent): a dispatch dict may carry ``cost`` (caller-normalized
    units) — the row then gains ``r_sorted = r - SORT_COST_LAMBDA *
    cost``, the ordering/observation face (the banked ``r`` never
    moves); a dispatch dict may carry ``branch_budget`` + ``usage`` —
    an overrun books attributed waste (``budget_overrun`` on the row,
    folded into ``waste`` and subtracted from ``r``)."""
    dispatch_ids = [str(d.get("dispatch_id") or "")
                    for d in (dispatches or []) if d.get("dispatch_id")]
    known = set(dispatch_ids)
    credited_by: dict[str, list[str]] = {d: [] for d in dispatch_ids}
    demoted_by: dict[str, list[dict]] = {d: [] for d in dispatch_ids}
    untraced: list[str] = []
    for a in (artifacts or []):
        aid = str(a.get("id") or "")
        creator = a.get("creator")
        creator = str(creator).strip() if creator else ""
        if not creator or creator not in known:
            if aid:
                untraced.append(aid)
            continue
        value, reason = _artifact_credit(a)
        if value >= ROUND_CREDIT_FULL:
            credited_by[creator].append(aid)
        elif reason:
            demoted_by[creator].append({"id": aid, "reason": reason})
    waste_by: dict[str, float] = {d: 0.0 for d in dispatch_ids}
    unattributed_waste = 0.0
    for w in (waste or []):
        wid = str(w.get("dispatch_id") or "")
        if wid in waste_by:
            waste_by[wid] += 1.0
        else:
            unattributed_waste += 1.0
    # the branch_budget hard constraint: an overrun is ATTRIBUTED waste
    # (the dispatch id is known by construction) — new dict, credited/
    # demoted_by stay untouched (the immutability posture).
    overrun_by: dict[str, float] = {}
    for d in (dispatches or []):
        did = str(d.get("dispatch_id") or "")
        if not did or did not in waste_by:
            continue
        over = budget_overrun(d.get("branch_budget"), d.get("usage"))
        if over > 0:
            waste_by[did] += over
            overrun_by[did] = over
    rows = [row for d in (dispatches or [])
            if (row := _credit_row(d, credited_by, demoted_by,
                                   waste_by, overrun_by)) is not None]
    return {"rows": rows, "untraced": untraced,
            "unattributed_waste": unattributed_waste}


def settle_round_credit(ws, dispatches: list[dict], artifacts: list[dict],
                        waste: list[dict] | None = None,
                        now=None) -> dict:
    """Emit one round_credit ledger row per dispatch (record + settle).
    Idempotent at any wall-clock distance: a re-run reuses the existing
    row's identity ts for its signal, so the signal set is byte-identical
    and record/settle dedupe (no ledger churn). ROUND_CREDIT is
    polarity-none: it feeds no Beta prior and the scalar feed reads
    episode scalars only. Returns {"settled", "untraced",
    "unattributed_waste", "banked", "amended"} — ``banked`` lists the
    dispatch ids whose FIRST settlement rode this pass (the learning
    clock's tick); replays and the late-cite amendment path report
    none. ``amended`` lists the dispatch ids whose bank was
    corrected to a moved ledger value or whose missed first bank was
    repaired — the learning signal tracking the ledger."""
    ws = Path(ws)
    # issue-678 T3: the creator backfill rides the SAME pass — a
    # creator-less artifact whose claim_id names a dispatch in THIS
    # settlement attributes to that claim (new dicts; the pure core
    # below sees the backfilled rows, never the originals)
    dispatch_ids = [str(d.get("dispatch_id") or "")
                    for d in (dispatches or [])]
    artifacts = backfill_artifact_creators(artifacts, dispatch_ids)
    doc = round_credit(dispatches, artifacts, waste)
    settled_n = 0
    banked: list[str] = []
    amended: list[str] = []
    ts = now or _now()
    for row in doc["rows"]:
        rid = f"{KIND_ROUND_CREDIT}/{row['dispatch_id']}"
        existing = rl.fold(ws, rid)
        if existing is not None:
            # re-run: freeze the signal ts at the row's identity ts so the
            # signal set (and its digest) never churns — dedupe holds at
            # any wall-clock distance
            ts_row = str(existing.get("ts") or ts)
        else:
            ts_row = ts
        signals = [{"type": "round_credit_signal",
                    "source": "scalar_settlement",
                    "value": {"credited": len(row["credited"]),
                              "demoted": len(row["demoted"]),
                              "waste": row["waste"]},
                    "ts": ts_row}]
        rec = rl.record(ws, kind=KIND_ROUND_CREDIT,
                        anchor=str(row["dispatch_id"]), signals=signals,
                        ts=ts_row)  # identity ts == signal ts on first write
        if not rec.get("appended") and rec.get("reason") not in (
                "duplicate: unchanged",):
            warn("settle_round_credit", f"{rid}: {rec.get('reason')}")
        # issue 433 late-cite provenance: the ids THIS settlement raises
        # out of a prior trace demotion into full credit (a late citation
        # is foresight rewarded through the amendment path, never
        # punished; a first settlement has no prior demotions)
        prior_st = (existing.get("settlement") or {}) if existing else {}
        prior_demoted = {str(e.get("id"))
                         for e in (prior_st.get("demoted") or [])
                         if isinstance(e, dict)}
        settlement = {"reward": row["r"], "band": BAND_ROUND_CREDIT,
                      "rule_id": RULE_ROUND_CREDIT,
                      "evidence_refs": [
                          f"creator:{row['dispatch_id']}"] + [
                          f"credited:{aid}" for aid in row["credited"]] + [
                          f"demoted:{e['id']}:{e['reason']}"
                          for e in row["demoted"]],
                      "credited": row["credited"],
                      "demoted": row["demoted"],
                      "waste": row["waste"],
                      "round": row["round"],
                      "untraced": doc["untraced"],
                      "settled_ts": ts}
        # additive-when-present fairness seams: the sorted observation
        # face (never the banked reward) and the budget-overrun audit
        # trail ride the settlement only when the dispatch carried the
        # inputs — legacy rows stay byte-identical.
        if "r_sorted" in row:
            settlement["r_sorted"] = row["r_sorted"]
        if "budget_overrun" in row:
            settlement["budget_overrun"] = row["budget_overrun"]
        prior_late = [str(x) for x in (prior_st.get("late_cited") or [])]
        late_cited = prior_late + [
            aid for aid in row["credited"]
            if aid in prior_demoted and aid not in prior_late]
        if late_cited:
            settlement["late_cited"] = late_cited
        res = rl.settle(ws, rid, settlement)
        if res.get("appended"):
            settled_n += 1
            # issue 462 W5 — the settlement feed: the FIRST SUCCESSFUL
            # settlement of a dispatch banks its ladder value into the
            # matching Q cell (the eager learning clock). The guard tests
            # settlement PRESENCE in the fold, not mere row existence: a
            # first run that recorded the identity row but failed/died
            # before settling must bank on the retry, while replays and
            # the late-cite amendment path (both carrying a settlement in
            # the fold) refine the LEDGER only — the append-only
            # observation log has no retraction face, so re-banking would
            # double-count the round.
            if not (existing and existing.get("settlement") is not None):
                bank = _bank_q_cell_credit(ws, row)
                # #718: the same first-settlement tick banks the L1
                # rollout return — the claim-terminal learning target the
                # orchestration layer consumes (fail-open, lazy import;
                # the L2 bank above is never affected by this leg)
                _bank_l1_rollout_return(ws, row, bank)
                banked.append(str(row["dispatch_id"]))
        elif res.get("reason") not in ("duplicate: already settled",):
            warn("settle_round_credit", f"{rid}: {res.get('reason')}")
        # the bank tracks the LEDGER, not the first write.
        # Every already-settled dispatch reconciles (replays included,
        # so a bank that failed on pass 1 is repaired whatever the
        # ledger says); the repair/amendment NEVER reports into
        # `banked` — the case-posterior leg keys on that set.
        if existing and existing.get("settlement") is not None:
            if _reconcile_q_cell_bank(ws, row):
                amended.append(str(row["dispatch_id"]))
    return {"settled": settled_n, "untraced": doc["untraced"],
            "unattributed_waste": doc["unattributed_waste"],
            # the dispatches whose FIRST settlement rode this pass (the
            # learning clock's tick) — the case-posterior observation
            # leg keys on exactly this set, so a replay or late-cite
            # amendment additively reports none
            "banked": banked,
            # the dispatches whose bank was corrected or repaired
            # on this pass (the learning signal tracking the ledger)
            "amended": amended}


def _calibration_delta(ladder_credit, step_sum: float, step_n: int,
                       *, band_ceil: float) -> tuple[float, float]:
    """#712 the claim-terminal residual — the pure
    ``calibration = ladder_credit − Σ(step_credit)`` of issue #712 A,
    extended to BOTH Beta dimensions: ``(Δsuccess, Δfailure)`` landing
    the cumulative mass on the step-less endpoint the legacy fold would
    have banked for this ladder value.

    Success target = clamp01(r) — the legacy rail clamp — band-aware
    (D-678.4a: a TRACE-band ladder settled MASSLESS before, so the
    target is (0, 0) and the step rows wash out completely);
    failure target = 1 − L (the same legacy endpoint's failure mass).
    Over-credit (Σstep > L) yields a negative Δsuccess — the clawback;
    under-credit a positive top-up. ``step_sum``/``step_n`` arrive as
    the fold's MASS view (q_cells.step_credit_totals excludes
    band-valued information-option rows, which banked no mass — the
    operand can never claw back mass that was never banked). Pure:
    same inputs, same deltas."""
    settled = clamp_credit(ladder_credit)      # the legacy [0,1] rail
    if 0.0 < settled <= band_ceil:             # the information option
        target_s, target_f = 0.0, 0.0
    else:
        target_s, target_f = settled, 1.0 - settled
    return (round(target_s - float(step_sum), 6),
            round(target_f - (int(step_n) - float(step_sum)), 6))


def _reconcile_q_cell_bank(ws, row: dict) -> bool:
    """The bank tracks the LEDGER, not the first write. Two faces
    behind one guard: a bank that never landed (no settlement-source
    rows) gets the full first bank via the q-cell faces DIRECTLY —
    never ``_bank_q_cell_credit``, whose strategy-store and L1 legs
    must not double-write; a banked dispatch whose ledger value moved
    gets ONE signed ``credit_amendment`` row. Fail-open telemetry: a
    reconcile failure is one rate-limited WARN, never a settlement
    break."""
    try:
        from rlvr import q_cells as _qc  # noqa: PLC0415
        did = str(row["dispatch_id"])
        mass = _qc.banked_mass(ws, did)
        if mass is None:
            # an unreadable log is not an empty one — amending against a
            # fabricated (0, 0) read would fire a full-target overshoot
            warn("q_cell_reconcile", f"{did}: log unreadable — skipped")
            return False
        _s, _f, n_rows = mass
        if n_rows == 0:
            step_sum, step_n = _qc.step_credit_totals(ws, did)
            if step_n == 0:
                bank = _qc.observe_settlement(ws, did, row["r"])
            else:
                d_s, d_f = _calibration_delta(
                    row["r"], step_sum, step_n,
                    band_ceil=_qc.OBSERVATION_BAND_CEIL)
                bank = _qc.observe_step_calibration(
                    ws, did, d_s, failure_delta=d_f)
            return bool((bank or {}).get("appended"))
        bank = _qc.amend_settlement(ws, did, row["r"],
                                    reason="ledger-amendment")
        return bool(bank.get("appended"))
    except Exception as exc:  # noqa: BLE001 — telemetry, never settlement
        warn("q_cell_reconcile", f"{type(exc).__name__}: {exc}")
        return False


def _bank_q_cell_credit(ws, row: dict) -> dict | None:
    """Issue 462 W5: bank one settled round credit into the matching Q
    cell (rlvr.q_cells.observe_settlement — the match-and-bank face).
    The bank result carries the matched row's ``arm_key``/``fingerprint``
    so the SAME settled credit keys the cross-task posterior store row
    (rlvr.strategy_store.append_store_row) without a second scan — the
    store's write face exists for exactly this call and had no live
    caller. Telemetry posture: fail-open, a banked-credit failure is one
    rate-limited WARN and never breaks settlement (the determinism wall
    covers the ledger receipt; the Q bank is the learning feed). Returns
    the bank dict (None on failure) so the caller can thread the matched
    dispatch signature into the L1 rollout-return bank (#718) without a
    second match scan.

    #712 branch: when step credit already banked for this dispatch
    (``step_credit_totals`` — n > 0) the terminal bank is the RESIDUAL,
    not the raw ladder — one signed ``observe_step_calibration`` row so
    cumulative success lands on the ladder value (over-credit clawed
    back, under-credit topped up) and cumulative failure on 1 − L.
    n == 0 keeps the legacy observe_settlement face byte-identically
    (the backward-compatibility acceptance: claims that settled before
    this change work unchanged)."""
    try:
        from rlvr import q_cells as _qc  # noqa: PLC0415
        did = str(row["dispatch_id"])
        step_sum, step_n = _qc.step_credit_totals(ws, did)
        if step_n == 0:
            bank = _qc.observe_settlement(ws, did, row["r"])
        else:
            delta_success, delta_failure = _calibration_delta(
                row["r"], step_sum, step_n,
                band_ceil=_qc.OBSERVATION_BAND_CEIL)
            bank = _qc.observe_step_calibration(
                ws, did, delta_success, failure_delta=delta_failure)
    except Exception as exc:  # noqa: BLE001 — telemetry, never settlement
        warn("q_cell_bank", f"{type(exc).__name__}: {exc}")
        return None
    _bank_strategy_store_row(ws, row, bank)
    return bank


def _bank_l1_rollout_return(ws, row: dict, bank: dict | None) -> None:
    """#718: at the claim-terminal first settlement, compute and store
    the rollout return (rlvr.l1_value — the discounted SUM of the
    claim's transition rewards plus the terminal ladder credit, #716
    semantics). The dispatch-time state signature rides the L2 bank
    result (the matched dispatch row's recorded state — the state the
    action was chosen in); no signature is the honest gap (no row, ONE
    warn inside the callee). Fail-open: the L1 leg is telemetry — a
    broken value store never breaks settlement, and the row's ladder
    credit is unchanged by anything this face does."""
    try:
        from rlvr import l1_value as _l1  # noqa: PLC0415
        _l1.record_terminal_return(
            ws, str(row["dispatch_id"]), row["r"],
            signature=(bank or {}).get("signature_hash"))
    except Exception as exc:  # noqa: BLE001 — telemetry, never settlement
        warn("l1_rollout_return", f"{type(exc).__name__}: {exc}")


def _bank_strategy_store_row(ws, row: dict, bank: dict) -> None:
    """Append the settled dispatch's cross-task store row, keyed by the
    dispatch's own arm key/fingerprint the Q bank returned. The honest
    gap (unmatched dispatch, no banked credit) writes nothing — the same
    no-row-never-a-fabricated-bucket posture as the Q bank. The credit
    is the settled ladder value; ``facts_citing`` is the settlement's
    own full-credit fact count; the status names the settlement band the
    row describes. Fail-open telemetry: a store failure is one
    rate-limited WARN, never a settlement break."""
    try:
        if not (bank.get("matched") and bank.get("appended")):
            return
        from rlvr import strategy_store as _store  # noqa: PLC0415
        _store.append_store_row(
            ws,
            method_family=str(bank.get("method_family") or ""),
            status=BAND_ROUND_CREDIT,
            credit=row["r"],
            dispatch_id=str(row["dispatch_id"]),
            arm_key=bank.get("arm_key"),
            fingerprint=bank.get("fingerprint"),
            facts_citing=len(row.get("credited") or []))
    except Exception as exc:  # noqa: BLE001 — telemetry, never settlement
        warn("q_cell_bank.store", f"{type(exc).__name__}: {exc}")


# --- scalar prior feed (exponential family, consumed by compute_priors) --

def scalar_observations(ws, kind: str = "task",
                        window: tuple | None = None) -> list[float]:
    """Settled episode tier scalars via THE one ledger interface. A
    measured scalar is any GOLD/SILVER/BRONZE/RED tier reward; NEUTRAL is
    UNMEASURED (pending) and is not an observation. Direct sums only —
    the per-round weighting symbol is ruled out here too."""
    out: list[float] = []
    for row in rl.settled(ws, kind=kind, window=window):
        st = row.get("settlement") or {}
        if st.get("tier") in MEASURED_TIERS:
            out.append(float(st.get("tier_reward", 0.0)))
    return out


from _common import seq_sum as _seq_sum  # noqa: E402 — the canonical leaf (the per-module redeclaration is retired)


def _ng_from_stats(n: int, xbar: float, m2: float,
                   mu0: float, kappa0: float, a0: float, b0: float) -> dict:
    """Normal-Gamma conjugate update from sufficient statistics
    (n, mean, sum of squared deviations around the mean). Exact and
    deterministic; the one place the update math lives."""
    if n == 0:
        return {"n": 0, "mu": float(mu0), "kappa": float(kappa0),
                "alpha": float(a0), "beta": float(b0), "var": 0.0}
    kappa = float(kappa0) + n
    mu = (float(kappa0) * float(mu0) + n * xbar) / kappa
    alpha = float(a0) + n / 2.0
    beta = (float(b0) + 0.5 * m2
            + (float(kappa0) * n * (xbar - float(mu0)) ** 2)
            / (2.0 * (float(kappa0) + n)))
    return {"n": n, "mu": mu, "kappa": kappa, "alpha": alpha,
            "beta": beta, "var": m2 / n}


def normal_gamma_update(observations: list[float],
                        mu0: float = NG_MU0, kappa0: float = NG_KAPPA0,
                        a0: float = NG_A0, b0: float = NG_B0) -> dict:
    """Normal-Gamma conjugate update over scalar observations (the
    exponential-family posterior for a continuous reward; NOT
    Beta-Bernoulli — that family counts binary outcomes). Documented weak
    prior (mu=0.5, one pseudo-observation). Pure and deterministic.

    numpy adoption (issue 420, the pattern-setter): the mean and the
    sum of squared deviations run through ``_seq_sum`` — input-order,
    bit-identical to the former hand-rolled loop, pinned by
    tests/test_rlvr_bitexact.py. The per-element ``** 2`` stays Python
    float pow on purpose: the pins ride on libm pow rounding, and
    np.square / x*x is an IEEE multiply that differs from pow by 1 ulp
    on some inputs (no behavior change is the adoption contract)."""
    n = len(observations)
    if n == 0:
        return _ng_from_stats(0, 0.0, 0.0, mu0, kappa0, a0, b0)
    arr = np.asarray(observations, dtype=np.float64)
    xbar = _seq_sum(arr) / n
    m2 = _seq_sum([d ** 2 for d in (arr - xbar).tolist()])
    return _ng_from_stats(n, xbar, m2, mu0, kappa0, a0, b0)


def merge_normal_gamma_posts(posts: list[dict],
                             mu0: float = NG_MU0,
                             kappa0: float = NG_KAPPA0,
                             a0: float = NG_A0,
                             b0: float = NG_B0) -> dict:
    """Pool per-workspace Normal-Gamma posteriors into ONE exact posterior
    over all their observations — the weak prior (kappa0, mu0) enters
    exactly ONCE, not once per workspace. Recovers each workspace's
    sufficient statistics from the doc this module emits (n, mu, kappa,
    var) — the exact inverse of _ng_from_stats:
    n*xbar = kappa*mu - kappa0*mu0; m2 = var*n — shifts them to the
    pooled mean, and runs one sufficient-stats update. Pure."""
    stats: list[tuple[int, float, float]] = []
    for p in (posts or []):
        n_i = int(p.get("n") or 0)
        if n_i <= 0:
            continue
        xbar_i = (float(p.get("kappa") or 0.0)
                  * float(p.get("mu") or 0.0)
                  - float(kappa0) * float(mu0)) / n_i
        m2_i = float(p.get("var") or 0.0) * n_i
        stats.append((n_i, xbar_i, m2_i))
    if not stats:
        return _ng_from_stats(0, 0.0, 0.0, mu0, kappa0, a0, b0)
    # numpy adoption (issue 420): the pooled float reductions run through
    # _seq_sum (input order, bit-identical to the former builtin sum);
    # n_all stays an exact integer count; the pooled terms keep scalar
    # `** 2` (libm pow) semantics per the pin wall.
    n_all = int(sum(n for n, _, _ in stats))
    xbar_all = _seq_sum([n * x for n, x, _ in stats]) / n_all
    m2_all = _seq_sum([m2 + n * (x - xbar_all) ** 2
                       for n, x, m2 in stats])
    return _ng_from_stats(n_all, xbar_all, m2_all, mu0, kappa0, a0, b0)


# --- fact provenance read face (the creator field) --------------------------

def question_claims(ws) -> set[str]:
    """<ws>/claim-register.yaml -> ids of the question-bearing claims
    (answers_question non-null) — the claim-provenance half of the
    issue-433 citation relation (the same surface the verdict scorer
    walks: pq -> claim -> linked fact; a fact on such a claim is used
    toward the deliverable/stage). Tolerant: a missing, unparseable, or
    undecodable (invalid UTF-8) register degrades to an empty set — a
    decode error is a data problem, never a face-killer; no claim face
    means no claim-provenance citations; the deliverable face is
    unaffected."""
    import yaml
    try:
        data = yaml.safe_load(
            (Path(ws) / "claim-register.yaml").read_text(
                encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return set()
    out: set[str] = set()
    if isinstance(data, dict):
        for c in data.get("claims") or []:
            if isinstance(c, dict) and c.get("id") \
                    and c.get("answers_question"):
                out.add(str(c["id"]))
    return out


def cited_ids_from_deliverables(ws) -> set[str]:
    """<ws> deliverable trees -> every ``F<NNN>`` fact id named by a
    deliverable document — THE producer the issue-433 deliverable
    citation face never had (issue 678 T2: no production caller ever
    passed ``cited_ids``, so ``cited_by_deliverable`` was permanently
    False). Scans notes/, analyses/, runs/deliverables/ recursively for
    text/yaml files. Tolerant: an unreadable file contributes no
    citations and never raises; an absent tree is an empty set (the
    honest absence, same posture as question_claims)."""
    ws = Path(ws)
    out: set[str] = set()
    for rel in CITED_DELIVERABLE_RELS:
        root = ws / rel
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() \
                    or path.suffix.lower() not in CITED_DELIVERABLE_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            out |= set(FACT_ID_CITE_RE.findall(text))
    return out


def backfill_artifact_creators(artifacts: list[dict],
                               dispatch_ids) -> list[dict]:
    """Issue-678 T3 — the creator backfill (settlement path only).

    A creator-less artifact whose ``claim_id`` names a dispatch in THIS
    settlement attributes to that claim (the claim id IS the dispatch
    identity the settlement face keys on — the CLI assembles dispatch
    rows from terminal claims, so the two ids coincide by construction).
    Launch stashes were considered as the attribution source and
    REJECTED: ``append_transition`` consumes the stash on settle, so the
    namespace is empty exactly when the old (pre-#648) facts need
    backfilling; the claim id is the same identity, durable in the
    register. A creator-less artifact with no path stays untraced and is
    explicitly marked ``creditable: false`` — the named non-creditable
    face the issue asks for, auditable instead of silent. New dicts
    throughout (immutability): rows WITH a creator pass through
    unchanged."""
    known = {str(d).strip() for d in (dispatch_ids or [])}
    out: list[dict] = []
    for a in (artifacts or []):
        creator = str(a.get("creator") or "").strip()
        if creator:
            out.append(a)
            continue
        claim_id = str(a.get("claim_id") or "").strip()
        if claim_id and claim_id in known:
            out.append({**a, "creator": claim_id, "creditable": True})
        else:
            out.append({**a, "creditable": False})
    return out


def _deliverable_cited(fid: str, cited: set[str]) -> bool:
    """The deliverable citation match: exact id membership first (the
    explicit ``cited_ids`` face — a caller may pass slugged ids), then
    the BARE-token leg the producer needs: fact ids carry slugs
    (``F008-decrypt-key`` — the ``<FNNN>-<slug>`` grammar) while a
    deliverable document names the bare token ``F008`` (the ``\\b``
    boundary treats the hyphen separator as non-word, so the scan
    extracts exactly the bare id). Match on the artifact id's own
    ``F<NNN>`` token — a bare id (legacy grammar) matches itself."""
    if not fid or not cited:
        return False
    if fid in cited:
        return True
    token = FACT_ID_CITE_RE.search(fid)
    return bool(token) and token.group(0) in cited


def fact_artifacts(ws, cited_ids: set | list | None = None) -> list[dict]:
    """Read <ws>/facts/*.md frontmatter into round-credit artifact rows.

    Provenance channel: the fact frontmatter ``creator`` field (the
    dispatch id the worker echo'd at creation; falls back to the issue-879
    trace_id when creator itself is absent — both are worker echo
    channels, trace_id is mission-stable so it attributes to the mission,
    not the dispatch). Status/verify_status are the oracle faces;
    ``cited_by_deliverable`` comes from the deliverable citation face
    (cited_ids — the ids the deliverable document names; issue 678 T2:
    ``cited_ids=None`` — the default every production caller uses — now
    INVOKES the producer ``cited_ids_from_deliverables`` instead of
    meaning "no citations"; an explicit set keeps its exact meaning) and
    ``answers_question`` from the claim-provenance face (claim_id
    resolving to a question-bearing claim — the used-toward-stage leg of
    the issue-433 citation relation; see question_claims). Tolerant read:
    unparseable or extension-layer-incomplete files are skipped (they are
    not credit artifacts; lint_facts owns their loudness)."""
    import yaml
    if cited_ids is None:
        cited = cited_ids_from_deliverables(ws)
    else:
        cited = {str(c) for c in cited_ids}
    question_bearing = question_claims(ws)
    out: list[dict] = []
    facts_dir = Path(ws) / "facts"
    if not facts_dir.is_dir():
        return out
    for path in sorted(facts_dir.glob("F*.md")):
        try:
            parts = path.read_text(
                encoding="utf-8", errors="replace").split("---", 2)
            meta = yaml.safe_load(parts[1]) if len(parts) >= 3 else None
        except OSError:
            continue
        except yaml.YAMLError:
            continue
        if not isinstance(meta, dict):
            continue
        fid = str(meta.get("id") or path.stem)
        creator = str(meta.get("creator") or meta.get("trace_id") or "")
        claim_id = str(meta.get("claim_id") or "").strip()
        out.append({"id": fid,
                    "creator": creator or None,
                    "status": str(meta.get("status") or ""),
                    "verify_status": str(meta.get("verify_status") or ""),
                    "claim_id": claim_id or None,
                    "answers_question": bool(claim_id)
                    and claim_id in question_bearing,
                    "cited_by_deliverable": _deliverable_cited(fid,
                                                               cited),
                    "oracle_backed_refutation": str(
                        meta.get("status") or "").strip().upper()
                        in _REFUTATION_STATUSES})
    return out


# --- deterministic validator (settlement v3 face, issues 390 + 396) -------
#
# issue 396 (owner redesign 2026-09-26) demotes the issue-390 owner-ruled
# to the VERIFIER'S OUTPUT SCALE and resitles judgment in the verifier
# subagent (a separate face). THIS layer stays purely mechanical — three
# passes over a parsed verifier verdict doc (the XML->dict adapter lives
# with the verifier face):
#   1. citation resolution — every evidence citation must resolve to a
#      real ledger rollout id / fact id; ONE unresolvable citation
#      rejects the WHOLE verdict doc (fail-closed hallucination wall);
#   2. rail clamping — verifier-emitted credit scalars clamp into the
#      declared rails below;
#   3. oracle non-overridability — pass locks reward at 1.0 (the checker
#      verdict is the hard currency); a fail caps at the TRACE rail top.
# Plus the anti-surrender floor (rubric line, enforced mechanically):
# refuted-with-replay-evidence = low positive (TRACE canonical); surrender
# with no replay evidence settles 0.0. The rails live HERE (validator's
# own config, per the issue-396 rescope) — the rules yaml is not rewritten.

OUTPUT_RAILS: dict[str, dict] = {
    # Declared reference bands, NOT tuned weights — zero free parameters;
    # the placement fraction is measured, not learned (issue-390 ruling kept
    # as the scale definition). Anti-farming stays structural: TRACE
    # 0.01 vs pass 1.0 keeps a 100x differential (85x vs the 0.85 pass
    # floor) — no farming incentive.
    "GOLD": {"range": [0.85, 1.0]},
    "SILVER": {"range": [0.55, 0.85]},
    "BRONZE": {"range": [0.15, 0.55]},
    "TRACE": {"range": [0.0, 0.05], "canonical": 0.01},
    "NEUTRAL": {"range": [0.0, 0.0]},
    "RED": {"range": [0.0, 0.0]},
}
TRACE_CANONICAL = float(OUTPUT_RAILS["TRACE"]["canonical"])
FAIL_CREDIT_CAP = float(OUTPUT_RAILS["TRACE"]["range"][1])  # 0.05
ORACLE_PASS_LOCK = 1.0   # task/oracle-green never_demoted carries over
RULE_TRAJECTORY_CREDIT = "trajectory/verifier-credit"


def clamp_credit(scalar) -> float:
    """Clamp a verifier-emitted credit scalar into [0, 1] (the union of
    the declared rails). Deterministic; no judgment; tolerant of None or
    non-numeric input (settles 0.0 — never raises on verifier noise)."""
    try:
        s = float(scalar)
    except (TypeError, ValueError):
        return 0.0
    return min(max(s, 0.0), 1.0)


def rail_of(scalar: float, oracle_verdict=None) -> str:
    """Name the declared rail a settled scalar lands in (audit face).
    0.0 names RED on an oracle-fail trajectory, NEUTRAL otherwise."""
    s = clamp_credit(scalar)
    if s <= 0.0:
        return (TIER_RED if str(oracle_verdict or "").strip().lower()
                == "fail" else TIER_NEUTRAL)
    for tier in (TIER_GOLD, TIER_SILVER, TIER_BRONZE, TIER_TRACE):
        lo, hi = OUTPUT_RAILS[tier]["range"]
        if lo <= s <= hi:
            return tier
    return TIER_NEUTRAL  # unreachable after clamping


def resolve_citations(actions: list[dict], resolvable_ids) -> dict:
    """Hallucination wall: every evidence citation on every credited
    action must resolve to a REAL id (ledger rollout ids, fact ids from
    facts/*.md provenance, round-credit artifact ids). ONE unresolvable
    citation rejects the WHOLE verdict document — fail-closed.
    Returns {"ok", "unresolved": {action_id: [ids...]}}."""
    resolvable = {str(i) for i in (resolvable_ids or set())}
    unresolved: dict[str, list[str]] = {}
    for action in (actions or []):
        if not isinstance(action, dict):
            continue
        aid = str(action.get("action_id") or "")
        missing = sorted({str(c) for c in (action.get("evidence") or [])
                          if str(c) not in resolvable})
        if missing:
            unresolved[aid] = missing
    return {"ok": not unresolved, "unresolved": unresolved}


def oracle_lock(oracle_verdict, scalar,
                has_reproducible_evidence: bool) -> dict:
    """Oracle non-overridability + the anti-surrender floor.
    - pass: reward locks at 1.0 (verifier credit cannot lower it);
    - fail: reward caps at the TRACE rail top (verifier credit cannot
      raise a fail into pass territory) AND floors at the TRACE
      canonical 0.01 when the trajectory carries rerun-reproducible
      evidence (refuted-with-replay-evidence = low positive; surrender
      with no evidence settles 0.0);
    - no verdict: clamped scalar passes through (no lock, no cap).
    Deterministic enforcement of a rubric line — no judgment here."""
    s = clamp_credit(scalar)
    v = str(oracle_verdict or "").strip().lower()
    if v == "pass":
        return {"reward": ORACLE_PASS_LOCK, "locked": True,
                "floor_applied": False, "capped": False}
    if v == "fail":
        floor = TRACE_CANONICAL if has_reproducible_evidence else 0.0
        reward = min(max(s, floor), FAIL_CREDIT_CAP)
        return {"reward": reward, "locked": False,
                "floor_applied": bool(s < floor),
                "capped": bool(s > FAIL_CREDIT_CAP)}
    return {"reward": s, "locked": False, "floor_applied": False,
            "capped": False}


def validate_verdict_doc(doc, resolvable_ids, oracle_verdict,
                         has_reproducible_evidence: bool) -> dict:
    """The deterministic validator over a parsed verifier verdict doc.
    Three mechanical passes (citation resolution -> rail clamping ->
    oracle non-overridability + anti-surrender floor). ok=False means
    nothing settles: the caller MUST NOT write a settlement. Pure —
    same inputs, same output, no sampling slot (the determinism posture:
    verifier judgment is sampled; the validator never is)."""
    errors: list[str] = []
    if not isinstance(doc, dict) or not isinstance(doc.get("actions"),
                                                   list):
        return {"ok": False, "errors": ["verdict doc: missing actions[]"],
                "actions": [], "reward": 0.0, "tier": None,
                "locked": False, "floor_applied": False, "capped": False}
    cites = resolve_citations(doc["actions"], resolvable_ids)
    if not cites["ok"]:
        for aid, ids in cites["unresolved"].items():
            errors.append(f"unresolved citations on {aid}: {ids}")
    actions_out = []
    for action in doc["actions"]:
        if not isinstance(action, dict):
            errors.append(f"verdict doc: non-mapping action {action!r}")
            continue
        credit = clamp_credit(action.get("credit"))
        actions_out.append({"action_id": str(action.get("action_id") or ""),
                            "credit": credit, "rail": rail_of(credit)})
    if not actions_out:
        errors.append("verdict doc: zero credited actions")
    lock = oracle_lock(oracle_verdict, doc.get("trajectory_credit"),
                       has_reproducible_evidence)
    ok = not errors
    return {"ok": ok, "errors": errors, "actions": actions_out,
            "reward": lock["reward"] if ok else 0.0,
            "tier": (rail_of(lock["reward"], oracle_verdict) if ok
                     else None),
            "locked": lock["locked"], "floor_applied": lock["floor_applied"],
            "capped": lock["capped"]}


def resolvable_registry(ws) -> set:
    """Every id a verdict citation may legitimately reference: ledger
    rollout ids + fact ids (facts/*.md frontmatter provenance)."""
    ws = Path(ws)
    ids = {str(r.get("rollout_id")) for r in rl.read(ws)}
    ids |= {str(a["id"]) for a in fact_artifacts(ws)}
    return ids


def apply_trajectory_settlement(ws, rollout_id, verdict_doc, *,
                                oracle_verdict,
                                has_reproducible_evidence: bool,
                                extra_resolvable=(),
                                now=None) -> dict:
    """Validate + settle a trajectory segment (settlement v3). Fail-closed:
    an invalid verdict doc writes NOTHING. Re-application with changed
    inputs (late evidence joining the signal set) appends an AMENDMENT
    row through the SAME rl.settle path — the ledger stays append-only
    and the audit chain ('where did this score come from') stays
    answerable. Prior settlement lineage (v1 band/reward/rule_id) is
    carried forward so hard-currency provenance survives; ``reward`` and
    ``tier`` carry the v3 authoritative scalar. ``extra_resolvable`` is
    an additive id set the CALLER already vouched for (the blind
    settler's input-doc artifact paths ride here so a verdict citing
    what it actually saw resolves); default empty keeps the citation
    registry exactly the workspace-derived set."""
    ws = Path(ws)
    if isinstance(extra_resolvable, str):
        extra_resolvable = (extra_resolvable,)  # never iterate a bare str
    validation = validate_verdict_doc(
        verdict_doc,
        resolvable_registry(ws)
        | {str(i) for i in (extra_resolvable or ())},
        oracle_verdict,
        has_reproducible_evidence)
    if not validation["ok"]:
        return {"settled": False, "reason": "validation failed",
                "validation": validation}
    existing = rl.fold(ws, str(rollout_id)) or {}
    base_st = existing.get("settlement") or {}
    ts = now or _now()
    # order-preserving merge: identical re-application must produce a
    # byte-identical settlement or the ledger dedupe would churn
    refs = list(base_st.get("evidence_refs") or [])
    for ref in (f"action:{a['action_id']}={a['credit']}"
                for a in validation["actions"]):
        if ref not in refs:
            refs.append(ref)
    amended = dict(base_st)
    amended.update({
        "reward": validation["reward"],
        "band": str(base_st.get("band") or "TRAJECTORY"),
        "rule_id": str(base_st.get("rule_id") or RULE_TRAJECTORY_CREDIT),
        "trajectory_rule_id": RULE_TRAJECTORY_CREDIT,
        "tier": validation["tier"],
        "tier_reward": validation["reward"],
        "verifier_credit": clamp_credit(
            verdict_doc.get("trajectory_credit")),
        "oracle_locked": validation["locked"],
        "anti_surrender_floor": validation["floor_applied"],
        "trajectory_actions": validation["actions"],
        "evidence_refs": refs,
        "settled_ts": ts,
    })
    res = rl.settle(ws, str(rollout_id), amended)
    if res.get("appended"):
        return {"settled": True, "validation": validation,
                "settlement": amended}
    warn("apply_trajectory_settlement",
         f"{rollout_id}: {res.get('reason')}")
    return {"settled": False, "reason": res.get("reason"),
            "validation": validation}


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
