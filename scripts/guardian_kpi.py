# -*- coding: utf-8 -*-
"""guardian_kpi.py — the three guardian-KPI surfaces (issue #429 W3-T3.1).

RENDER-ONLY measurement face, consumed additively by
experience_triples.q_report (the #432 additive-key discipline: the
q-report/1 arithmetic stays byte-identical). Three blocks:

1. guardian_triggers(ws) — retry / stall / SATURATED trigger-rate trends.
   「守护者触发率=RL策略失败率的无偏指标」: every trigger is a recorded
   intervention the guardian layer made against the loop's own plan, so
   the trigger rate measures the RL policy's failure rate without any
   reward-side opinion — that is why it renders beside the #432
   method-family health block. Sources (all PRE-EXISTING faces, zero new
   writes):
     - SATURATED: unified-log ``converge`` rows (action="converge"); the
       decision word is the detail's leading token, the contracts EXIT_*
       byte the fallback for word-less rows;
     - stall: the recorded stall family — ``mission_stall`` detector
       FIRES (detector_fired rows, the detector_liveness actor face) plus
       the plan_stall / lifecycle_stalled / mission_stall action words;
       detector_eval rows are evaluations, not fires;
     - retry: ``redo_leak_warn`` rows (#772 redo-prompt value-overlap,
       the mechanical retry-loop detector) plus the claim register's
       promotion_attempts face (retried live claims / live claims).
   Per-task trend groups trigger rows by their ``claim`` field; the day
   trend buckets every row by its UTC date.

2. verifier_drift(ws) — the judge-calibration readout in-system (the W3
   plan's "verifier 漂移读出"): settlement AMENDMENTS landing on
   LLM-discretionary vs mechanical settlement rows, a PURE ledger query
   with zero new mechanisms. A discretionary revision rate significantly
   above the mechanical one = the verifier leg is drifting (model
   settlements get revised; mechanical ones hold). Classification basis
   (declared in the block's ``basis`` field):
     - mechanical   task rollouts carrying an oracle_verdict signal (the
                    oracle is the mechanical verifier) + round_credit
                    rows (provenance arithmetic);
     - discretionary self_distill / hybrid_distill rollouts + task
                    rollouts settled WITHOUT an oracle verdict (asserted
                    / advisory judgment);
     - unclassified everything else (visible counter, never dropped).
   A revision = a settlement document change beyond ``settled_ts`` (the
   same core-comparison settle() itself dedupes on) — signal amendments
   that re-attach an unchanged settlement are not revisions.

3. reject_rate(ws) — the output-compliance trend from the EXISTING
   gate-telemetry face (runs/gate-telemetry.jsonl, gate_telemetry.py):
   per-gate and per-day reject/hard_block rates.

ZERO DECISION POSTURE: pure reads; never writes; never imported by any
dispatch, gate, or settlement face. Degradation is an explicit
``unavailable`` marker (#432 visible-not-silent precedent), never a
silent empty block.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import rollout_ledger as rl
from kunglao_log import iter_jsonl

GUARDIAN_SCHEMA = "guardian-kpi/1"
VERIFIER_DRIFT_SCHEMA = "verifier-drift/1"
REJECT_RATE_SCHEMA = "gate-reject-kpi/1"
GUARDIAN_RATIONALE = "守护者触发率=RL策略失败率的无偏指标"

# converge decision vocabulary = the contracts EXIT_* bytes (single source)
from contracts import (EXIT_BLOCKED, EXIT_CONVERGED, EXIT_DISPATCH,  # noqa: E402
                       EXIT_PARK, EXIT_SATURATED, EXIT_VERIFY)
DECISION_BY_EXIT = {
    EXIT_CONVERGED: "CONVERGED", EXIT_DISPATCH: "DISPATCH",
    EXIT_VERIFY: "VERIFY", EXIT_SATURATED: "SATURATED",
    EXIT_BLOCKED: "BLOCKED", EXIT_PARK: "PARK",
}
DECISION_WORDS = frozenset(DECISION_BY_EXIT.values())

# claim status sets — the status_defs canonical vocabulary (constants only)
from status_defs import SUSPENDED, TERMINAL  # noqa: E402

STALL_ACTIONS = frozenset({"mission_stall", "plan_stall",
                           "lifecycle_stalled"})
STALL_DETECTORS = frozenset({"mission_stall"})  # detector_fired actor face
RETRY_ACTIONS = frozenset({"redo_leak_warn"})

DISCRETIONARY_KINDS = frozenset({"self_distill", "hybrid_distill"})

# verifier-drift alarm policy constants (documented, not fitted; the alarm
# is advisory-only — the readout never gates anything)
DRIFT_ALARM_FACTOR = 2.0   # discretionary rate must exceed FACTOR x mechanical
MIN_ROWS_FOR_ALARM = 2     # per-class rollout base below which it is noise

# the per-task trend budget (render face; the full set stays in trend/day)
PER_TASK_TOP = 20

GATE_TELEMETRY_REL = "runs/gate-telemetry.jsonl"


def _word(row: dict) -> str:
    return str(row.get("action") or "")


def _day(ts: str) -> str:
    return str(ts or "")[:10]


def _converge_decision(row: dict) -> str | None:
    """Decision word from the detail's leading token; the contracts EXIT_*
    byte is the fallback for word-less rows; None when neither names one."""
    detail = str(row.get("detail") or "").strip()
    if detail:
        word = detail.split()[0]
        if word in DECISION_WORDS:
            return word
    rc = row.get("exit")
    return DECISION_BY_EXIT.get(rc) if isinstance(rc, int) else None


def _claim_register(ws: Path) -> list[dict]:
    """Tolerant claim-register read (state_signature.claim_pattern's
    posture, plus promotion_attempts): [] when absent/unreadable."""
    import yaml
    try:
        reg = yaml.safe_load(
            (ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — tolerant read
        return []
    claims = reg.get("claims")
    return [c for c in claims if isinstance(c, dict)] \
        if isinstance(claims, list) else []


# ---------------------------------------------------------------------------
# 1. guardian trigger-rate trends
# ---------------------------------------------------------------------------

def _row_kind(row: dict) -> str | None:
    """'stall' / 'retry' for a trigger row, None otherwise (the recorded
    stall family + the redo-loop detector face)."""
    word = _word(row)
    if word in STALL_ACTIONS or (word == "detector_fired"
                                 and str(row.get("actor") or "")
                                 in STALL_DETECTORS):
        return "stall"
    return "retry" if word in RETRY_ACTIONS else None


def _live_claims(claims: list[dict]) -> tuple[list[dict], list[dict]]:
    """(live, retried) over the register: live = not TERMINAL/SUSPENDED;
    retried = promotion_attempts >= 1 among live."""
    live = [c for c in claims
            if str(c.get("status") or "").strip().upper() not in TERMINAL
            and str(c.get("status") or "").strip().upper() not in SUSPENDED]
    retried = [c for c in live
               if int(c.get("promotion_attempts") or 0) >= 1]
    return live, retried


def _trigger_trend(rows: list[dict], converge: list[dict]) -> list[dict]:
    """Per-UTC-day trigger buckets (converge/saturated/stall/retry)."""
    trend: dict[str, Counter] = {}
    for r in rows:
        kind = _row_kind(r)
        if kind:
            trend.setdefault(_day(r.get("ts")), Counter())[kind] += 1
    for r in converge:
        tc = trend.setdefault(_day(r.get("ts")), Counter())
        tc["converge"] += 1
        if _converge_decision(r) == "SATURATED":
            tc["saturated"] += 1
    return [{"day": d, "converge": n.get("converge", 0),
             "saturated": n.get("saturated", 0),
             "stall": n.get("stall", 0), "retry": n.get("retry", 0)}
            for d, n in sorted(trend.items())]


def guardian_triggers(ws) -> dict:
    """retry / stall / SATURATED trigger-rate trends (pure read)."""
    from kunglao_log import _all_rows  # detector_liveness's read precedent
    ws = Path(ws)
    rows = [r for r in _all_rows(ws) if isinstance(r, dict)]
    claims = _claim_register(ws)
    if not rows and not claims:
        return {"schema": GUARDIAN_SCHEMA, "rationale": GUARDIAN_RATIONALE,
                "unavailable": "no event-log face and no claim register"}

    converge = [r for r in rows if _word(r) == "converge"]
    decisions: Counter = Counter()
    for r in converge:
        d = _converge_decision(r)
        if d:
            decisions[d] += 1

    stall_rows = [r for r in rows if _row_kind(r) == "stall"]
    retry_rows = [r for r in rows if _row_kind(r) == "retry"]
    live, retried = _live_claims(claims)

    per_task: dict[str, Counter] = {}
    for r in stall_rows + retry_rows:
        claim = str(r.get("claim") or "")
        if claim:
            per_task.setdefault(claim, Counter())[_row_kind(r)] += 1
    task_rows = [{"claim": c, "retry": n.get("retry", 0),
                  "stall": n.get("stall", 0),
                  "total": n.get("retry", 0) + n.get("stall", 0)}
                 for c, n in sorted(per_task.items())]
    task_rows.sort(key=lambda t: (-t["total"], t["claim"]))

    saturated = decisions.get("SATURATED", 0)
    return {
        "schema": GUARDIAN_SCHEMA,
        "rationale": GUARDIAN_RATIONALE,
        "converge_rows": len(converge),
        "decisions": {k: decisions[k] for k in sorted(decisions)},
        "saturated_rate": (saturated / len(converge))
        if converge else None,
        "retry": {"redo_leak_rows": len(retry_rows),
                  "claims_retried": len(retried),
                  "claims_live": len(live),
                  "retried_share": (len(retried) / len(live))
                  if live else None},
        "stall": {"fires": len(stall_rows)},
        "per_task": task_rows[:PER_TASK_TOP],
        "trend": _trigger_trend(rows, converge),
    }


# ---------------------------------------------------------------------------
# 2. verifier-drift readout (pure ledger query)
# ---------------------------------------------------------------------------

def _classify_rollout(kind: str, signals: list[dict]) -> str:
    """The declared mechanical/discretionary basis (see module doc)."""
    if kind == "round_credit":
        return "mechanical"
    if kind in DISCRETIONARY_KINDS:
        return "discretionary"
    if kind == "task":
        has_oracle = any(isinstance(s, dict)
                         and str(s.get("type") or "") == "oracle_verdict"
                         for s in signals or [])
        return "mechanical" if has_oracle else "discretionary"
    return "unclassified"


def verifier_drift(ws) -> dict:
    """Settlement amendments on LLM-discretionary vs mechanical rows —
    a pure ledger query (the W3 'verifier drift' readout). Never gates."""
    ws = Path(ws)
    by_rid: dict[str, list[dict]] = {}
    order: list[str] = []
    for row in rl.read(ws):
        rid = str(row.get("rollout_id") or "")
        if rid not in by_rid:
            by_rid[rid] = []
            order.append(rid)
        by_rid[rid].append(row)

    rollouts: Counter = Counter()
    amendments: Counter = Counter()
    for rid in order:
        rows = by_rid[rid]
        kind = str(rows[0].get("kind") or "")
        signals = next((r.get("signals") for r in reversed(rows)
                        if r.get("signals")), [])
        cls = _classify_rollout(kind, signals)
        rollouts[cls] += 1
        prior_core = None
        for r in rows:
            st = r.get("settlement")
            if not isinstance(st, dict):
                continue
            core = {k: v for k, v in st.items() if k != "settled_ts"}
            if prior_core is not None and core != prior_core:
                amendments[cls] += 1
            prior_core = core

    def _rate(cls: str) -> float | None:
        base = rollouts.get(cls, 0)
        return amendments.get(cls, 0) / base if base else None

    m_rate, d_rate = _rate("mechanical"), _rate("discretionary")
    ratio = (d_rate / m_rate) if (m_rate and d_rate is not None) else None
    alarm = bool(
        rollouts.get("mechanical", 0) >= MIN_ROWS_FOR_ALARM
        and rollouts.get("discretionary", 0) >= MIN_ROWS_FOR_ALARM
        and m_rate is not None and d_rate is not None
        and d_rate > DRIFT_ALARM_FACTOR * m_rate)
    return {
        "schema": VERIFIER_DRIFT_SCHEMA,
        "rollouts": {"mechanical": rollouts.get("mechanical", 0),
                     "discretionary": rollouts.get("discretionary", 0),
                     "unclassified": rollouts.get("unclassified", 0)},
        "settlement_amendments": {
            "mechanical": amendments.get("mechanical", 0),
            "discretionary": amendments.get("discretionary", 0),
            "unclassified": amendments.get("unclassified", 0)},
        "amendment_rate": {"mechanical": m_rate, "discretionary": d_rate},
        "drift_ratio": (round(ratio, 6) if ratio is not None else None),
        "drift_alarm": alarm,
        "drift_alarm_factor": DRIFT_ALARM_FACTOR,
        "min_rows_for_alarm": MIN_ROWS_FOR_ALARM,
        "basis": "mechanical = task rows carrying an oracle_verdict signal "
                 "+ round_credit rows; discretionary = self_distill / "
                 "hybrid_distill rows + task rows without an oracle "
                 "verdict (asserted/advisory judgment); a revision = a "
                 "settlement change beyond settled_ts",
    }


# ---------------------------------------------------------------------------
# 3. reject-rate trend (gate telemetry, output compliance)
# ---------------------------------------------------------------------------

def reject_rate(ws) -> dict:
    """Reject-rate trend over the existing gate-telemetry face
    (gate_telemetry.py rows: {ts, gate, rc, rc_meaning}). Pure read."""
    p = Path(ws) / GATE_TELEMETRY_REL
    rows: list[dict] = []
    if p.is_file():
        try:
            rows = [r for r in iter_jsonl(
                p.read_text(encoding="utf-8", errors="replace").splitlines())
                if isinstance(r, dict)]
        except OSError:
            rows = []

    by_gate: dict[str, Counter] = {}
    trend: dict[str, Counter] = {}
    rejects = hard_blocks = exceptions = 0
    for r in rows:
        gate = str(r.get("gate") or "")
        rc = r.get("rc")
        rejects_here = hard_here = 0
        if rc == 1:
            rejects += 1
            rejects_here = 1
        elif rc == 2:
            hard_blocks += 1
            hard_here = 1
        elif rc is None:
            exceptions += 1
        gc = by_gate.setdefault(gate, Counter())
        gc["calls"] += 1
        gc["rejects"] += rejects_here
        gc["hard_blocks"] += hard_here
        tc = trend.setdefault(_day(r.get("ts")), Counter())
        tc["calls"] += 1
        tc["rejects"] += rejects_here
        tc["hard_blocks"] += hard_here

    n = len(rows)

    def _rate(num: int, den: int) -> float | None:
        return num / den if den else None

    return {
        "schema": REJECT_RATE_SCHEMA,
        "rows": n,
        "rejects": rejects,
        "hard_blocks": hard_blocks,
        "exceptions": exceptions,
        "overall_reject_rate": _rate(rejects + hard_blocks, n)
        if n else None,
        "by_gate": [{"gate": g, "calls": c["calls"],
                     "rejects": c["rejects"],
                     "hard_blocks": c["hard_blocks"],
                     "rate": _rate(c["rejects"] + c["hard_blocks"],
                                   c["calls"])}
                    for g, c in sorted(by_gate.items())],
        "trend": [{"day": d, "calls": c["calls"], "rejects": c["rejects"],
                   "hard_blocks": c["hard_blocks"]}
                  for d, c in sorted(trend.items())],
    }


# ---------------------------------------------------------------------------
# the q_report face composer (additive keys; each face is total)
# ---------------------------------------------------------------------------

def faces(ws) -> dict:
    """The three KPI blocks under their q_report key names. Each face is
    total (never raises); the wrapper's degradation is belt-and-braces."""
    try:
        return {"guardian_kpi": guardian_triggers(ws),
                "verifier_drift": verifier_drift(ws),
                "reject_rate": reject_rate(ws)}
    except Exception as exc:  # noqa: BLE001 — the report face never breaks
        marker = {"unavailable": f"guardian-kpi face unreadable: "
                                 f"{type(exc).__name__}: {exc}"}
        return {"guardian_kpi": dict(marker, schema=GUARDIAN_SCHEMA),
                "verifier_drift": dict(marker, schema=VERIFIER_DRIFT_SCHEMA),
                "reject_rate": dict(marker, schema=REJECT_RATE_SCHEMA)}


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
