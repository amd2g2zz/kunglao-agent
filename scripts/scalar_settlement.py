# -*- coding: utf-8 -*-
"""scalar_settlement.py — two-level settlement + 3-tuple extraction (issue 379).

Level 1 — EPISODE settlement (reward-rules.yaml v2 ``tier_table``): the
fine-grained tiered scalar (GOLD 1.0 / SILVER 0.7 / BRONZE 0.4 /
NEUTRAL 0 / RED 0) entered by pure if-then conditions over MECHANICAL
dimensions (oracle verdict + probe sub-scores, evidence class,
cost-vs-class-reference, difficulty). Tier evaluation is FIRST-MATCH in
severity order with RED override. The tier scalar refines WITHIN the v1
polarity bands — it never raises a SETTLED_RED row and never lowers a
SETTLED_GREEN row's ledger reward (task/oracle-green is never_demoted).

Level 2 — ROUND credit settlement: per-dispatch rows
``r_i = sum(credited artifacts created in dispatch i) - attributed waste``,
provenance-exact via the fact frontmatter ``creator`` field (the dispatch
trace id the worker echo'd at creation). NO positional weighting — the
time-preference ruling removed the per-step weighting symbol from this
design twice: the round index orders rows, it never weights them;
``untraced`` artifacts are listed and counted toward no dispatch.

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
import sys
from pathlib import Path

import rollout_ledger as rl

# the round-credit rollout kind — the ledger's OPEN ENUM registration API
# (a new kind is one register_kind entry, never an ad-hoc string).
rl.register_kind("round_credit", "per-dispatch round credit row (issue 379)")

KIND_ROUND_CREDIT = "round_credit"
BAND_ROUND_CREDIT = "ROUND_CREDIT"
RULE_ROUND_CREDIT = "round/provenance-credit"
RULE_NEUTRAL = "tier/neutral"
RULE_RED = "tier/red"

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

_WARN_LAST: dict[str, str] = {}


def warn(op: str, reason: str) -> None:
    """Rate-limited stderr WARN (the issue 276 _zof_warn pattern)."""
    if _WARN_LAST.get(op) == reason:
        return
    _WARN_LAST[op] = reason
    print(f"[kunglao-agent] scalar_settlement WARN (fail-open): "
          f"{op}: {reason}", file=sys.stderr)


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
    import reward_settlement as rs
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


def _artifact_credited(artifact: dict) -> bool:
    """oracle-verified OR cited-by-deliverable OR oracle-backed
    refutation (the spec's three credited classes)."""
    if artifact.get("cited_by_deliverable"):
        return True
    status = str(artifact.get("status") or "").strip().upper()
    if status in _CREDIT_TERMINALS:
        return True
    if status in _REFUTATION_STATUSES \
            and artifact.get("oracle_backed_refutation") \
            and str(artifact.get("verify_status") or "").lower() == "passes":
        return True
    return False


def round_credit(dispatches: list[dict], artifacts: list[dict],
                 waste: list[dict] | None = None) -> dict:
    """Pure round-credit core: per-dispatch
    ``r_i = sum(credited artifacts created in i) - attributed_waste(i)``.

    Provenance-exact attribution on the artifact ``creator`` field (the
    dispatch id); the round index carries ordering information only and
    never weights the sum. Artifacts with no creator (or a creator
    outside the dispatch set) are ``untraced``: listed, counted toward
    no dispatch."""
    dispatch_ids = [str(d.get("dispatch_id") or "")
                    for d in (dispatches or []) if d.get("dispatch_id")]
    known = set(dispatch_ids)
    credited_by: dict[str, list[str]] = {d: [] for d in dispatch_ids}
    untraced: list[str] = []
    for a in (artifacts or []):
        aid = str(a.get("id") or "")
        creator = a.get("creator")
        creator = str(creator).strip() if creator else ""
        if not creator or creator not in known:
            if aid:
                untraced.append(aid)
            continue
        if _artifact_credited(a):
            credited_by[creator].append(aid)
    waste_by: dict[str, float] = {d: 0.0 for d in dispatch_ids}
    unattributed_waste = 0.0
    for w in (waste or []):
        wid = str(w.get("dispatch_id") or "")
        if wid in waste_by:
            waste_by[wid] += 1.0
        else:
            unattributed_waste += 1.0
    rows = []
    for d in (dispatches or []):
        did = str(d.get("dispatch_id") or "")
        if not did:
            continue
        credited = credited_by[did]
        rows.append({"dispatch_id": did,
                     "round": d.get("round"),  # ordering info ONLY
                     "credited": credited,
                     "waste": waste_by[did],
                     "r": float(len(credited)) - waste_by[did]})
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
    episode scalars only."""
    ws = Path(ws)
    doc = round_credit(dispatches, artifacts, waste)
    settled_n = 0
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
                              "waste": row["waste"]},
                    "ts": ts_row}]
        rec = rl.record(ws, kind=KIND_ROUND_CREDIT,
                        anchor=str(row["dispatch_id"]), signals=signals,
                        ts=ts_row)  # identity ts == signal ts on first write
        if not rec.get("appended") and rec.get("reason") not in (
                "duplicate: unchanged",):
            warn("settle_round_credit", f"{rid}: {rec.get('reason')}")
        settlement = {"reward": row["r"], "band": BAND_ROUND_CREDIT,
                      "rule_id": RULE_ROUND_CREDIT,
                      "evidence_refs": [
                          f"creator:{row['dispatch_id']}"] + [
                          f"credited:{aid}" for aid in row["credited"]],
                      "credited": row["credited"],
                      "waste": row["waste"],
                      "round": row["round"],
                      "untraced": doc["untraced"],
                      "settled_ts": ts}
        res = rl.settle(ws, rid, settlement)
        if res.get("appended"):
            settled_n += 1
        elif res.get("reason") not in ("duplicate: already settled",):
            warn("settle_round_credit", f"{rid}: {res.get('reason')}")
    return {"settled": settled_n, "untraced": doc["untraced"],
            "unattributed_waste": doc["unattributed_waste"]}


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
    prior (mu=0.5, one pseudo-observation). Pure and deterministic."""
    n = len(observations)
    if n == 0:
        return _ng_from_stats(0, 0.0, 0.0, mu0, kappa0, a0, b0)
    xbar = sum(float(x) for x in observations) / n
    m2 = sum((float(x) - xbar) ** 2 for x in observations)
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
    n_all = sum(n for n, _, _ in stats)
    xbar_all = sum(n * x for n, x, _ in stats) / n_all
    m2_all = sum(m2 + n * (x - xbar_all) ** 2 for n, x, m2 in stats)
    return _ng_from_stats(n_all, xbar_all, m2_all, mu0, kappa0, a0, b0)


# --- fact provenance read face (the creator field) --------------------------

def fact_artifacts(ws, cited_ids: set | list | None = None) -> list[dict]:
    """Read <ws>/facts/*.md frontmatter into round-credit artifact rows.

    Provenance channel: the fact frontmatter ``creator`` field (the
    dispatch id the worker echo'd at creation; falls back to the issue-879
    trace_id when creator itself is absent — both are worker echo
    channels, trace_id is mission-stable so it attributes to the mission,
    not the dispatch). Status/verify_status are the oracle faces;
    ``cited_by_deliverable`` comes from the deliverable citation face
    (cited_ids — the ids the deliverable document names). Tolerant read:
    unparseable or extension-layer-incomplete files are skipped (they are
    not credit artifacts; lint_facts owns their loudness)."""
    import yaml
    cited = {str(c) for c in (cited_ids or [])}
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
        out.append({"id": fid,
                    "creator": creator or None,
                    "status": str(meta.get("status") or ""),
                    "verify_status": str(meta.get("verify_status") or ""),
                    "cited_by_deliverable": fid in cited,
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
                                now=None) -> dict:
    """Validate + settle a trajectory segment (settlement v3). Fail-closed:
    an invalid verdict doc writes NOTHING. Re-application with changed
    inputs (late evidence joining the signal set) appends an AMENDMENT
    row through the SAME rl.settle path — the ledger stays append-only
    and the audit chain ('where did this score come from') stays
    answerable. Prior settlement lineage (v1 band/reward/rule_id) is
    carried forward so hard-currency provenance survives; ``reward`` and
    ``tier`` carry the v3 authoritative scalar."""
    ws = Path(ws)
    validation = validate_verdict_doc(verdict_doc,
                                      resolvable_registry(ws),
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
