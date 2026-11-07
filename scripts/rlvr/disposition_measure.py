# -*- coding: utf-8 -*-
"""rlvr/disposition_measure.py — the disposition measurement face.

A pure read face over the episode disposition rows
(``runs/disposition/*.json``, with the unified telemetry mirror as the
secondary source). The classifier owns the verdict; this module owns how
each verdict enters the measurement denominators and how a learning claim
is made. Nothing here writes, classifies, or re-scores an episode.

Denominator rules (declared once in ``DENOMINATORS``):

  capability denominator   SOLVED + SURRENDER; success rate is
                           SOLVED / denominator, ``None`` when the
                           denominator is empty (insufficient evidence is
                           never reported as 0.0);
  censoring                CENSORED_ENV over every valid row; censored
                           episodes are excluded from strategy learning;
  capability gap           ATTEMPTED_EXHAUSTED emits a
                           ``capability-gap/1`` row that carries the
                           route-attempt ledger reference — an exhaustion
                           without that reference is refused (it is not
                           exhaustion, it is surrender);
  separate reporting       OUT_OF_SCOPE / INFRA / FAILED, no strategy
                           signal.

Risk and cost all ride the left tail, so the measurement makes them
visible instead of absorbing them:

  - ``process`` reports steps, cost, dead-end rate, and route-pruning
    quality per run (one disposition episode) and per arm. Sources are
    joined only when they exist — completion-grain step rows, q-cell
    observations, rollout-ledger rows, cost events, and the route ledger
    a row points at. A source that is absent contributes nothing; the
    metric is then an explicit ``None`` with a zero/unavailable coverage
    figure, never a fabricated value.
  - ``learning_claim`` refuses a single-episode verdict: a claim needs a
    pre/post or ablation delta, at least ``MIN_COHORT_N`` observations on
    every side, and an uncertainty for each cohort. Only then does it
    emit a ``learning-claim/1`` row.

The readers are tolerant: an absent directory, an unreadable file, or a
malformed row is an empty contribution with ONE warn (the house
fail-open posture). The route-ledger reference is resolved inside the
workspace only; a traversal or absolute reference is refused.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from kunglao_log import warn

from . import consolidated_ledger, disposition, ledger, step_ledger

MEASURE_SCHEMA = "disposition-measure/1"
GAP_SCHEMA = "capability-gap/1"
CLAIM_SCHEMA = "learning-claim/1"
DISPOSITION_SCHEMA = disposition.SCHEMA

#: the capability denominator: solved outcomes and honest surrenders
CAPABILITY_DENOMINATOR = ("SOLVED", "SURRENDER")

#: the dispositions reported on their own (no strategy signal)
SEPARATED = ("OUT_OF_SCOPE", "INFRA", "FAILED")

CENSORED = "CENSORED_ENV"
EXHAUSTED = "ATTEMPTED_EXHAUSTED"

#: the declared denominator mapping (one row per disposition)
DENOMINATORS = {
    "SOLVED": {"capability": True, "strategy_learning": True,
               "censoring": False, "capability_gap": False,
               "reported_separately": False},
    "OUT_OF_SCOPE": {"capability": False, "strategy_learning": False,
                     "censoring": False, "capability_gap": False,
                     "reported_separately": True},
    "CENSORED_ENV": {"capability": False, "strategy_learning": False,
                     "censoring": True, "capability_gap": False,
                     "reported_separately": False},
    "ATTEMPTED_EXHAUSTED": {"capability": False, "strategy_learning": False,
                            "censoring": False, "capability_gap": True,
                            "reported_separately": False},
    "INFRA": {"capability": False, "strategy_learning": False,
              "censoring": False, "capability_gap": False,
              "reported_separately": True},
    "FAILED": {"capability": False, "strategy_learning": False,
               "censoring": False, "capability_gap": False,
               "reported_separately": True},
    "SURRENDER": {"capability": True, "strategy_learning": True,
                  "censoring": False, "capability_gap": False,
                  "reported_separately": False},
}

#: a claim needs this many observations on each side of the delta
MIN_COHORT_N = 2

#: a settled q-cell credit at or below this value is a dead end
DEAD_END_CREDIT_MAX = 0.0

#: the two-sided normal quantile used for the delta interval
Z_95 = 1.96

#: the cost-event face (the settlement family's consolidated file; the
#: workspace-level spend face — no run identity exists). #1004: the
#: standalone cost-events rels retired into the family file.
COST_FACE = "runs/settlement.jsonl"
COST_SCHEMA = "cost-event/1"


class LearningClaimError(ValueError):
    """A learning-claim input violates the delta contract."""


# --------------------------------------------------------------- readers

def _token(value) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    return token or None


def _usable_row(row) -> bool:
    """The measurement-side row shape: a stamped disposition row with its
    identity and a known disposition. Evidence pointers are checked where a
    denominator needs them (exhaustion, censoring)."""
    if not isinstance(row, dict):
        return False
    if row.get("schema") != DISPOSITION_SCHEMA:
        return False
    if _token(row.get("episode_id")) is None:
        return False
    if _token(row.get("claim")) is None:
        return False
    return row.get("disposition") in disposition.DISPOSITIONS


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warn("rlvr.disposition_measure.read",
             f"{path.name}: {type(exc).__name__}: {exc} — skipped")
        return None


def _load(ws):
    """(rows oldest-first by episode id, invalid rows, source counts).

    The file row is primary; a telemetry mirror row is used only when the
    episode has no file row (a lost row is still measurable, a mirrored
    duplicate is never double-counted)."""
    ws = Path(ws)
    by_episode: dict[str, dict] = {}
    invalid: list[dict] = []
    sources = {"files": 0, "mirror": 0, "mirror_only": 0}
    base = ws / disposition.DISPOSITION_DIR
    if base.is_dir():
        for path in sorted(base.glob("*.json")):
            sources["files"] += 1
            row = _read_json(path)
            if not _usable_row(row):
                invalid.append({
                    "source": f"{disposition.DISPOSITION_DIR}/{path.name}",
                    "reason": "not a usable disposition/1 row"})
                continue
            by_episode.setdefault(row["episode_id"], row)
    for row in consolidated_ledger.read(
            ws, "telemetry", schema_prefix=DISPOSITION_SCHEMA):
        sources["mirror"] += 1
        if not _usable_row(row):
            invalid.append({
                "source": consolidated_ledger.CONSOLIDATED["telemetry"],
                "reason": "not a usable disposition/1 row"})
            continue
        if row["episode_id"] in by_episode:
            continue
        by_episode[row["episode_id"]] = row
        sources["mirror_only"] += 1
    rows = [by_episode[key] for key in sorted(by_episode)]
    return rows, invalid, sources


# ------------------------------------------------------- capability gaps

def _safe_ref(ref) -> str | None:
    """A workspace-relative reference token; absolute and traversal
    references are refused (syntax only — existence is a separate read)."""
    token = _token(ref)
    if token is None:
        return None
    if token.startswith(("/", "\\")):
        return None
    if len(token) >= 2 and token[1] == ":" and token[0].isalpha():
        return None  # drive-letter absolute (Windows)
    if ".." in token.replace("\\", "/").split("/"):
        return None
    return token


def capability_gap_row(row: dict) -> dict:
    """One ``capability-gap/1`` row from an exhausted disposition row.

    The route-attempt ledger reference rides the row so the gap is
    auditable: "attempted everything" is only a gap when the ledger says
    so. A reference that is not workspace-relative is refused (carried
    separately for audit, never as a usable ref). ``strategy_credit`` and
    ``learning_verdict`` stay ``None`` — an exhausted episode carries no
    strategy signal."""
    recorded_ref = _token(row.get("route_ledger_ref"))
    ref = _safe_ref(recorded_ref)
    evidence = row.get("evidence_refs")
    gap = {
        "schema": GAP_SCHEMA,
        "episode_id": row["episode_id"],
        "claim": row["claim"],
        "disposition": EXHAUSTED,
        "route_ledger_ref": ref,
        "budget": _number(row.get("budget")),
        "evidence_refs": [str(e) for e in evidence] if isinstance(
            evidence, list) else [],
        "ts": row.get("ts"),
        "strategy_credit": None,
        "learning_verdict": None,
    }
    if recorded_ref is not None and ref is None:
        gap["route_ledger_ref_refused"] = recorded_ref
    return gap


def _capability_gaps(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    gaps: list[dict] = []
    refusals: list[dict] = []
    for row in rows:
        if row.get("disposition") != EXHAUSTED:
            continue
        gap = capability_gap_row(row)
        if gap["route_ledger_ref"] is None:
            refused = gap.get("route_ledger_ref_refused")
            reason = ("ATTEMPTED_EXHAUSTED route_ledger_ref must be a "
                      "workspace-relative reference"
                      if refused is not None else
                      "ATTEMPTED_EXHAUSTED requires route_ledger_ref; "
                      "without the ledger the episode is SURRENDER")
            refusals.append({
                "episode_id": row["episode_id"],
                "claim": row["claim"],
                "reason": reason,
                "measured_as": "SURRENDER",
            })
            continue
        gaps.append(gap)
    gaps.sort(key=lambda g: g["episode_id"])
    refusals.sort(key=lambda r: r["episode_id"])
    return gaps, refusals


def _effective_rows(rows: list[dict]) -> list[dict]:
    """The measurement disposition: an exhaustion without a usable
    route-ledger reference falls to SURRENDER (recorded, never silently
    counted as exhaustion). The recorded disposition stays visible."""
    effective: list[dict] = []
    for row in rows:
        if (row.get("disposition") == EXHAUSTED
                and _safe_ref(row.get("route_ledger_ref")) is None):
            effective.append({**row, "disposition": "SURRENDER",
                              "recorded_disposition": EXHAUSTED})
            continue
        effective.append(row)
    return effective


# ------------------------------------------------------------- numbers

def _number(value):
    """A finite int/float or None (booleans are not numbers here). An int
    that cannot be represented as a finite float is out of contract: it is
    an empty contribution, never a crash."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        try:
            math.isfinite(float(value))
        except OverflowError:
            return None
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return None


def _float_or_none(value):
    number = _number(value)
    return float(number) if number is not None else None


def _int_count(value) -> int:
    number = _number(value)
    return int(number) if number is not None and number >= 0 else 0


# ------------------------------------------------------ process sources

def _q_cell_index(ws):
    rows = [r for r in consolidated_ledger.read(
        ws, "experience", schema_prefix="q-cell-obs")
        if isinstance(r, dict)]
    index: dict[str, list[dict]] = {}
    for row in rows:
        claim = _token(row.get("claim"))
        if claim is not None:
            index.setdefault(claim, []).append(row)
    return index, rows


def _step_index(ws):
    rows = step_ledger.read_step_grains(ws)
    index: dict[str, list[dict]] = {}
    for row in rows:
        claim = _token(row.get("claim_ref"))
        if claim is not None:
            index.setdefault(claim, []).append(row)
    return index, rows


def _rollout_index(ws):
    """Claim -> {rollout_id: settled}. ``ledger.read`` returns identity
    and amendment rows sharing one rollout id, so a rollout is counted
    once and is settled when any of its rows carries a settlement."""
    rows = ledger.read(ws)
    index: dict[str, dict[str, bool]] = {}
    for row in rows:
        claim = _token(row.get("anchor"))
        if claim is None:
            continue
        entry = index.setdefault(claim, {})
        rollout_id = _token(row.get("rollout_id"))
        if rollout_id is None:
            rollout_id = f"row-{len(entry)}"
        entry[rollout_id] = (bool(entry.get(rollout_id))
                             or row.get("settlement") is not None)
    return index, rows


def _claim_owners(rows: list[dict]) -> dict[str, str]:
    """The canonical episode per claim (first in deterministic episode
    order): the claim-grain process sources have no episode identity, so
    they are attributed to exactly one run instead of duplicated."""
    owners: dict[str, str] = {}
    for row in rows:
        owners.setdefault(row["claim"], row["episode_id"])
    return owners


def _claim_actions(rows: list[dict]) -> dict[str, str]:
    """The canonical strategic action per claim (the same first-episode
    rule as the owner), so every episode of one claim lands in one arm."""
    actions: dict[str, str] = {}
    for row in rows:
        actions.setdefault(row["claim"], _token(row.get("strategic_action")))
    return actions


def _arm_for(claim: str, q_rows: list[dict],
             fallback_action: str | None) -> tuple[str, str]:
    """The arm identity, best source first: the q-cell composite
    ``arm_key``, then the q-cell ``method_family``, then the claim's
    canonical strategic action, then an explicit unknown."""
    for q_row in reversed(q_rows):
        arm_key = _token(q_row.get("arm_key"))
        if arm_key is not None:
            return arm_key, "q-cell arm_key"
    for q_row in reversed(q_rows):
        family = _token(q_row.get("method_family"))
        if family is not None:
            return family, "q-cell method_family"
    if fallback_action is not None:
        return fallback_action, "strategic_action"
    return "unknown", "unknown"


def _cost_workspace(ws) -> dict:
    """The workspace-level spend face over the settlement family's
    cost-event rows (tolerant read — malformed lines are skipped by the
    family read face, never fatal)."""
    from rlvr import consolidated_ledger as _cl  # noqa: PLC0415 — lazy
    rows = [r for r in _cl.read(ws, "settlement", schema_prefix=COST_SCHEMA)
            if _float_or_none(r.get("amount")) is not None]
    files = [COST_FACE] if rows else []
    total = sum(float(r["amount"]) for r in rows)
    events = len(rows)
    coverage = ("workspace-total (no run identity)" if files else "absent")
    return {"amount": round(total, 6) if events else None,
            "events": events, "files": files, "coverage": coverage}


# ------------------------------------------------------ route pruning

def _add_unique(out: list[str], value) -> None:
    if value is None:
        return
    token = str(value).strip()
    if token and token not in out:
        out.append(token)


def _route_name(item):
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return item.get("route") or item.get("id") or item.get("name")
    return None


def _route_attempted(item) -> bool:
    if not isinstance(item, dict):
        return False
    attempted = item.get("attempted")
    if attempted is True:
        return True
    if isinstance(attempted, list) and attempted:
        return True
    attempts = item.get("attempts")
    return isinstance(attempts, list) and bool(attempts)


def _collect_routes(routes, declared: list[str],
                    attempted: list[str]) -> None:
    """Collect the ``routes`` face: a list of names/objects or a
    name-keyed map whose values may carry attempts."""
    if isinstance(routes, list):
        for item in routes:
            name = _route_name(item)
            if name is None:
                continue
            _add_unique(declared, name)
            if _route_attempted(item):
                _add_unique(attempted, name)
    elif isinstance(routes, dict):
        for name, info in routes.items():
            _add_unique(declared, name)
            if _route_attempted(info):
                _add_unique(attempted, name)


def _route_lists(doc) -> tuple[list[str], list[str]]:
    """(declared routes, attempted routes) over the tolerant ledger shapes:
    a list of names, a list of objects with attempts, or a name-keyed map."""
    if not isinstance(doc, dict):
        return [], []
    declared: list[str] = []
    attempted: list[str] = []
    _collect_routes(doc.get("routes"), declared, attempted)
    # The production writer (rlvr.route_ledger.record_attempt) emits the
    # classifier-facing `declared_routes` key; the tolerant shapes keep
    # `declared`. Read both so a real ledger is never reported as
    # route-less.
    for key in ("declared", "declared_routes"):
        declared_items = doc.get(key)
        if isinstance(declared_items, list):
            for item in declared_items:
                _add_unique(declared, _route_name(item))
    for key in ("attempted", "attempts"):
        items = doc.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            _add_unique(attempted, _route_name(item))
    return declared, attempted


def _workspace_path(ws, ref) -> Path | None:
    """Resolve a row-supplied reference INSIDE the workspace; traversal and
    absolute references are refused."""
    token = _token(ref)
    if token is None:
        return None
    base = Path(ws).resolve()
    try:
        candidate = (base / token).resolve()
        candidate.relative_to(base)
    except (OSError, ValueError):
        return None
    return candidate


def _route_pruning(ws, ref) -> tuple[dict | None, str]:
    if _token(ref) is None:
        return None, "absent"
    path = _workspace_path(ws, ref)
    if path is None:
        return None, "refused"
    if not path.is_file():
        return None, "missing"
    doc = _read_json(path)
    if doc is None:
        return None, "unreadable"
    declared, attempted = _route_lists(doc)
    if not declared:
        return None, "no-declared-routes"
    attempted_set = set(attempted)
    attempted_declared = [r for r in declared if r in attempted_set]
    pruned = [r for r in declared if r not in attempted_set]
    return ({
        "declared": len(declared),
        "attempted": len(attempted_declared),
        "pruned": len(pruned),
        "pruned_fraction": round(len(pruned) / len(declared), 4),
    }, "route_ledger")


# -------------------------------------------------------- process metrics

def _run_metrics(ws, row: dict, q_index: dict, step_index: dict,
                 rollout_index: dict, owners: dict,
                 actions: dict) -> dict:
    claim = row["claim"]
    owner = owners.get(claim, row["episode_id"])
    is_owner = owner == row["episode_id"]
    q_rows = q_index.get(claim) or []
    grains = step_index.get(claim) or []
    rollouts = rollout_index.get(claim) or {}
    # The joined sources are claim-grain: they are attributed to the
    # claim's canonical episode; every other episode of the claim reports
    # an explicit absence plus the owner's episode id (no duplication).
    steps = sum(_int_count(g.get("tool_calls")) for g in grains) \
        if (is_owner and grains) else None
    credits = [c for c in (_number(q.get("credit")) for q in q_rows)
               if c is not None] if is_owner else []
    # dead end: a settled q-cell credit at or below the zero floor
    dead_ends = sum(1 for c in credits if c <= DEAD_END_CREDIT_MAX)
    pruning, pruning_coverage = _route_pruning(
        ws, row.get("route_ledger_ref"))
    arm, arm_source = _arm_for(claim, q_rows, actions.get(claim))
    entry = {
        "episode_id": row["episode_id"],
        "claim": claim,
        "disposition": row.get("disposition"),
        "arm": arm,
        "arm_source": arm_source,
        "metrics_grain": "claim",
        "claim_metrics_owner": owner,
        "steps": steps,
        "steps_coverage": len(grains) if is_owner else 0,
        "cost": None,
        "cost_coverage": "unattributable",
        "dead_end_rate": (round(dead_ends / len(credits), 4)
                          if credits else None),
        "dead_end_settled": len(credits),
        "dead_end_count": dead_ends,
        "route_pruning": pruning,
        # route-pruning quality: the fraction of declared routes left
        # unattempted (work saved when the episode solved, unexplored
        # routes otherwise — reported with its outcome, never judged here)
        "route_pruning_quality": (pruning["pruned_fraction"]
                                  if pruning else None),
        "route_pruning_coverage": pruning_coverage,
        "rollouts": len(rollouts) if is_owner else 0,
        "rollout_settlements": (sum(1 for settled in rollouts.values()
                                    if settled) if is_owner else 0),
    }
    recorded = row.get("recorded_disposition")
    if recorded is not None:
        entry["recorded_disposition"] = recorded
    return entry


def _aggregate_arms(runs: list[dict]) -> dict:
    arms: dict[str, dict] = {}
    seen_claims: dict[str, set[str]] = {}
    for run in runs:
        arm = arms.setdefault(run["arm"], {
            "episodes": 0, "by_disposition": {}, "steps": 0,
            "steps_coverage": 0, "dead_end_settled": 0,
            "dead_end_count": 0, "rp_declared": 0, "rp_attempted": 0,
            "rp_pruned": 0})
        arm["episodes"] += 1
        arm["by_disposition"][run["disposition"]] = (
            arm["by_disposition"].get(run["disposition"], 0) + 1)
        # The joined process sources are claim-grain: when two episodes
        # share a claim, their steps/credits/routes are the same rows and
        # must enter the arm aggregate once.
        claims = seen_claims.setdefault(run["arm"], set())
        if run["claim"] in claims:
            continue
        claims.add(run["claim"])
        arm["steps_coverage"] += 1 if run["steps"] is not None else 0
        arm["steps"] += run["steps"] or 0
        arm["dead_end_settled"] += run["dead_end_settled"]
        arm["dead_end_count"] += run["dead_end_count"]
        pruning = run["route_pruning"]
        if pruning:
            arm["rp_declared"] += pruning["declared"]
            arm["rp_attempted"] += pruning["attempted"]
            arm["rp_pruned"] += pruning["pruned"]
    return {name: _finish_arm(value) for name, value in sorted(arms.items())}


def _finish_arm(arm: dict) -> dict:
    settled = arm["dead_end_settled"]
    pooled = None
    if arm["rp_declared"]:
        pooled = {
            "declared": arm["rp_declared"],
            "attempted": arm["rp_attempted"],
            "pruned": arm["rp_pruned"],
            "pruned_fraction": round(
                arm["rp_pruned"] / arm["rp_declared"], 4),
        }
    return {
        "episodes": arm["episodes"],
        "by_disposition": dict(sorted(arm["by_disposition"].items())),
        "steps": arm["steps"] if arm["steps_coverage"] else None,
        "steps_coverage": arm["steps_coverage"],
        "cost": None,
        "cost_coverage": "unattributable",
        "dead_end_rate": (round(arm["dead_end_count"] / settled, 4)
                          if settled else None),
        "dead_end_settled": settled,
        "dead_end_count": arm["dead_end_count"],
        "route_pruning": pooled,
        "route_pruning_quality": (pooled["pruned_fraction"]
                                  if pooled else None),
    }


def _process(ws, rows: list[dict]) -> dict:
    q_index, q_rows = _q_cell_index(ws)
    step_index, step_rows = _step_index(ws)
    rollout_index, rollout_rows = _rollout_index(ws)
    owners = _claim_owners(rows)
    actions = _claim_actions(rows)
    per_run = [_run_metrics(ws, row, q_index, step_index, rollout_index,
                            owners, actions)
               for row in rows]
    return {
        "per_run": per_run,
        "per_arm": _aggregate_arms(per_run),
        "workspace": {
            "cost": _cost_workspace(ws),
            "step_rows": len(step_rows),
            "q_cell_rows": len(q_rows),
            "rollout_rows": len(rollout_rows),
            "join_grain": "claim",
        },
    }


# --------------------------------------------------------------- measure

def measure(ws) -> dict:
    """The disposition measurement report (read-only, deterministic)."""
    rows, invalid, sources = _load(ws)
    measured = _effective_rows(rows)
    counts = {word: 0 for word in disposition.DISPOSITIONS}
    for row in measured:
        counts[row["disposition"]] += 1
    total = len(measured)
    solved = counts["SOLVED"]
    surrender = counts["SURRENDER"]
    capability_n = solved + surrender
    censored = counts[CENSORED]
    gaps, refusals = _capability_gaps(rows)
    strategy_rows = [row for row in measured
                     if DENOMINATORS[row["disposition"]]["strategy_learning"]]
    excluded = {word: counts[word] for word in disposition.DISPOSITIONS
                if not DENOMINATORS[word]["strategy_learning"]
                and counts[word]}
    return {
        "schema": MEASURE_SCHEMA,
        "rows": rows,
        "measured_rows": measured,
        "n_rows": total,
        "n_invalid": len(invalid),
        "invalid_rows": invalid,
        "sources": sources,
        "by_disposition": counts,
        "denominators": DENOMINATORS,
        "capability": {
            "denominator": capability_n,
            "solved": solved,
            "surrender": surrender,
            "success_rate": (round(solved / capability_n, 4)
                             if capability_n else None),
        },
        "censoring": {
            "censored": censored,
            "denominator": total,
            "rate": round(censored / total, 4) if total else None,
        },
        "reported_separately": {word: counts[word] for word in SEPARATED},
        "strategy_learning": {
            "included": len(strategy_rows),
            "episode_ids": [row["episode_id"] for row in strategy_rows],
            "excluded_from_strategy_learning": excluded,
        },
        "capability_gaps": gaps,
        "capability_gap_refusals": refusals,
        "process": _process(ws, measured),
    }


# -------------------------------------------------------- learning claims

def _finite_int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LearningClaimError(f"{label}: n must be a finite integer")
    try:
        finite = math.isfinite(float(value))
    except OverflowError as exc:
        raise LearningClaimError(
            f"{label}: n must be a finite integer") from exc
    if not finite or float(value) != int(float(value)):
        raise LearningClaimError(f"{label}: n must be a finite integer")
    return int(value)


def _sample_cohort(values, label: str) -> tuple[int, float, float | None]:
    if not isinstance(values, list) or not values:
        raise LearningClaimError(f"{label}: values must be a non-empty list")
    samples = []
    for value in values:
        number = _number(value)
        if number is None:
            raise LearningClaimError(
                f"{label}: every sample must be a finite number")
        samples.append(float(number))
    n = len(samples)
    mean = sum(samples) / n
    if n < 2:
        return n, mean, None
    variance = sum((x - mean) ** 2 for x in samples) / (n - 1)
    return n, mean, math.sqrt(variance / n)


def _explicit_cohort(cohort: dict,
                     label: str) -> tuple[int, float | None, float | None]:
    n = _finite_int(cohort.get("n"), label)
    value = _float_or_none(cohort.get("value"))
    raw_stderr = cohort.get("stderr")
    stderr = None if raw_stderr is None else _float_or_none(raw_stderr)
    return n, value, stderr


def _cohort_stats(cohort, label: str) -> dict:
    if not isinstance(cohort, dict):
        raise LearningClaimError(f"{label}: cohort must be a mapping")
    if "values" in cohort:
        n, value, stderr = _sample_cohort(cohort.get("values"), label)
    else:
        n, value, stderr = _explicit_cohort(cohort, label)
    if n < MIN_COHORT_N:
        raise LearningClaimError(
            f"{label}: n={n} is below MIN_COHORT_N={MIN_COHORT_N} — a "
            f"single rollout is never a learning verdict")
    if value is None:
        raise LearningClaimError(f"{label}: value must be a finite number")
    if stderr is None:
        raise LearningClaimError(
            f"{label}: uncertainty (stderr) is required for a learning claim")
    if stderr < 0:
        raise LearningClaimError(f"{label}: stderr must be non-negative")
    return {"n": n, "value": value, "stderr": stderr}


def learning_claim(metric: str, *, pre: dict | None = None,
                   post: dict | None = None,
                   ablation: dict | None = None) -> dict:
    """Emit a ``learning-claim/1`` row from a pre/post or ablation delta.

    Raises ``LearningClaimError`` unless exactly one delta design is
    supplied, both cohorts carry at least ``MIN_COHORT_N`` observations,
    and each cohort carries an uncertainty. A single-episode verdict can
    never produce a claim row.
    """
    if _token(metric) is None:
        raise LearningClaimError("metric must be a non-empty string")
    if (post is None) == (ablation is None):
        raise LearningClaimError(
            "a learning claim requires exactly one delta design: pre/post "
            "or ablation")
    if ablation is not None and pre is not None:
        raise LearningClaimError(
            "a pre cohort belongs to the pre/post design — drop it for an "
            "ablation claim")
    if post is not None:
        if pre is None:
            raise LearningClaimError("a pre/post claim requires both sides")
        before = _cohort_stats(pre, "pre")
        after = _cohort_stats(post, "post")
        design = "pre_post"
        cohorts = {"pre": before, "post": after}
        delta = after["value"] - before["value"]
        uncertainty = math.sqrt(before["stderr"] ** 2 + after["stderr"] ** 2)
    else:
        if not isinstance(ablation, dict):
            raise LearningClaimError("ablation: arm/control mapping required")
        arm = _cohort_stats(ablation.get("arm"), "arm")
        control = _cohort_stats(ablation.get("control"), "control")
        design = "ablation"
        cohorts = {"arm": arm, "control": control}
        delta = arm["value"] - control["value"]
        uncertainty = math.sqrt(arm["stderr"] ** 2 + control["stderr"] ** 2)
    if not math.isfinite(delta) or not math.isfinite(uncertainty):
        raise LearningClaimError("delta and uncertainty must be finite")
    low = delta - Z_95 * uncertainty
    high = delta + Z_95 * uncertainty
    return {
        "schema": CLAIM_SCHEMA,
        "metric": metric,
        "design": design,
        "delta": round(delta, 6),
        "uncertainty": round(uncertainty, 6),
        "ci95": [round(low, 6), round(high, 6)],
        "excludes_zero": low > 0 or high < 0,
        "cohorts": cohorts,
        "min_cohort_n": MIN_COHORT_N,
    }


def success_rate_cohort(rows: list[dict]) -> dict:
    """Capability-denominator rows -> a cohort usable in ``learning_claim``
    (binomial mean + standard error; empty cohort reports ``None``)."""
    usable = [row for row in rows if isinstance(row, dict)
              and row.get("disposition") in CAPABILITY_DENOMINATOR]
    n = len(usable)
    if not n:
        return {"n": 0, "value": None, "successes": 0, "stderr": None}
    successes = sum(1 for row in usable
                    if row.get("disposition") == "SOLVED")
    value = successes / n
    return {"n": n, "value": round(value, 6), "successes": successes,
            "stderr": math.sqrt(value * (1 - value) / n)}
