# -*- coding: utf-8 -*-
"""rlvr/verification_debt.py — the verification-debt face (deterministic).

Unverified assertions that other work depends on accumulate silently. This
module makes that accumulation MEASURABLE and gives the scheduling layer a
single number to gate on:

    D = sum(dependency_count x age_weight)

over all unverified-but-depended-on claims — claims whose register status
is OPEN or in the partial family AND that at least one other claim cites in
``claim_deps.yaml`` (direct dependents only; the transitive closure is
deliberately NOT taken — a pinned, simple, direct-citation debt surface).

  dependency_count  how many claims cite this claim as a dependency. The
                    DAG file (``claim_deps.yaml`` ``depends_on``) is the
                    authoritative edge store; when it ships no edges, the
                    per-claim ``depends_on`` register fields count instead
                    (the same fallback the priority ranking established,
                    so the two readers can never disagree about the graph).
  age_weight        hours since the claim's last recorded status
                    transition, saturating: ``min(age_hours /
                    AGE_SATURATION_HOURS, AGE_WEIGHT_CAP)``. The anchor is
                    the newest parseable timestamp in the claim's history
                    lines. A claim with NO readable anchor never proves
                    freshness: it reads the cap. Asymmetry: under-counting
                    debt is the diagnosed failure mode (a loop going
                    blocked with unpaid verification), while over-counting
                    only reorders work toward verification — so an
                    unknown age reads stale, not fresh.
  exclusion         PROVEN / PARK / STAMP / every other terminal or
                    suspended status contributes 0. A claim with zero
                    dependents contributes 0 and never enters per_claim.

Fail-open contract: a broken registry or a broken DAG reads D = 0 (the
pre-feature behavior) with one canonical warn — a broken measurement never
manufactures debt, and never blocks the caller.

The slope is the change against the prior statusline snapshot's stored
debt value (``runs/.kunglao-statusline.json`` ``vd.D``): computable when a
prior snapshot exists, None otherwise. Pure read — nothing here writes.

ZERO LEARNING POSTURE: no model call, no fitted parameter, no data files.
DEBT_GATE / AGE_SATURATION_HOURS / AGE_WEIGHT_CAP are documented policy
constants. Consumers:
  - convergence_check  — the scheduling gate (debt above the gate routes
    the verifier first; blocked-with-verifiable-debt becomes unreachable)
  - rlvr.compose       — the strategy object's debt face + seam section
  - statusline_snapshot — the ``vd`` chip face
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from status_defs import PARTIAL_STATUSES

from kunglao_log import warn  # canonical warn: ONE implementation

#: the scheduling threshold: debt above this routes the verifier before
#: any further analysis dispatch (policy constant, joins the <=3 slot
#: discipline family; strict > comparison at the call sites).
DEBT_GATE = 8.0

#: hours after a status transition at which the age weight reaches its cap.
AGE_SATURATION_HOURS = 24.0

#: the saturating age weight (a week-old unverified dependency does not
#: weigh a thousand times more than a day-old one — bounded influence).
AGE_WEIGHT_CAP = 2.0

#: statuses that make a claim unverified-but-verifiable debt when cited.
#: OPEN is the not-yet-worked frontier; the partial family is the
#: worked-but-unverified surface (the workflow-layer vocabulary bridge).
DEBT_STATUSES = frozenset({"OPEN"}) | frozenset(PARTIAL_STATUSES)

DEPS_REL = "claim_deps.yaml"
REGISTER_REL = "claim-register.yaml"

_ISO_TOKEN_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def _parse_anchor(value) -> datetime | None:
    """One history entry -> its timestamp (naive UTC), None if none.

    Strings carry a free-text line whose trailing ISO token is the
    transition time (the sanctioned reopen writer's shape); dict entries
    expose a ``ts`` field. Tolerant: anything unparseable is None."""
    if isinstance(value, dict):
        value = value.get("ts")
    if not isinstance(value, str):
        return None
    candidate = None
    for tok in reversed(value.replace("Z", "+00:00").split()):
        if not _ISO_TOKEN_RE.match(tok):
            continue
        try:
            candidate = datetime.fromisoformat(tok)
            break
        except ValueError:
            continue
    if candidate is None:
        return None
    if candidate.tzinfo is not None:
        candidate = candidate.astimezone(timezone.utc).replace(tzinfo=None)
    return candidate


def _claim_age_hours(claim: dict, now: datetime) -> float | None:
    """Hours since the claim's last recorded transition; None when the
    claim carries no readable anchor (the caller reads the cap)."""
    anchors = [d for d in (_parse_anchor(e)
                           for e in (claim.get("history") or []))
               if d is not None]
    if not anchors:
        return None
    age = (now - max(anchors)).total_seconds() / 3600.0
    return max(age, 0.0)  # future-dated history: clock-skew tolerant clamp


def _age_weight(age_hours: float | None) -> float:
    """The saturating age weight; an unknown age reads the cap (never
    proves freshness)."""
    if age_hours is None:
        return AGE_WEIGHT_CAP
    return min(age_hours / AGE_SATURATION_HOURS, AGE_WEIGHT_CAP)


def _read_yaml(path: Path):
    """Tolerant YAML read: (doc, error). Missing file -> ({}, None)."""
    if not path.is_file():
        return {}, None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}, None
    except (OSError, yaml.YAMLError) as exc:
        return {}, f"{type(exc).__name__}: {exc}"


def _edges(doc) -> dict[str, list[str]]:
    """The child -> [parents] edge map from a claim_deps document (or a
    register claims list for the per-claim field fallback). Tolerant:
    non-mapping rows are skipped."""
    if isinstance(doc, dict):
        raw = doc.get("depends_on")
    else:  # a claims list: the per-claim field fallback
        raw = {c.get("id"): c.get("depends_on")
               for c in doc if isinstance(c, dict)}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for child, parents in raw.items():
        if not isinstance(parents, list):
            continue
        clean = [str(p).strip() for p in parents if str(p).strip()]
        if clean:
            out[str(child).strip()] = clean
    return out


def _dependent_counts(claims: list[dict], deps_doc,
                      register_doc) -> dict[str, list[str]]:
    """claim id -> sorted direct-dependent ids. The DAG file wins; a DAG
    with zero edges falls back to the register's per-claim fields (the
    two debt readers and the priority ranker share the graph)."""
    edges = _edges(deps_doc)
    if not edges:
        claims_raw = (register_doc.get("claims")
                      if isinstance(register_doc, dict) else None)
        if isinstance(claims_raw, list):
            edges = _edges(claims_raw)
    counts: dict[str, set[str]] = {}
    for child, parents in edges.items():
        for parent in parents:
            counts.setdefault(parent, set()).add(child)
    return {k: sorted(v) for k, v in counts.items()}


def _prior_debt(ws: Path) -> float | None:
    """The prior D stored by the statusline snapshot, when readable."""
    try:
        from entropy_face import SNAPSHOT_REL
        doc = json.loads((ws / SNAPSHOT_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError, ImportError):
        return None
    prior = doc.get("vd") if isinstance(doc, dict) else None
    value = prior.get("D") if isinstance(prior, dict) else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def zero_face() -> dict:
    """The absence face: no debt measured (the fail-open landing shape)."""
    return {"D": 0.0, "per_claim": {}, "slope": None, "top": None,
            "verifiable_open": []}


def debt(ws, now: datetime | None = None) -> dict:
    """The verification-debt face over one workspace.

    Returns {"D", "per_claim", "slope", "top", "verifiable_open"} where
    per_claim maps claim id -> {dependents, age_hours, weight,
    contribution}; ``top`` is the highest-contribution claim (ties break
    on the lexicographically smallest id — deterministic); ``slope`` is
    D minus the prior snapshot's stored D when one exists. Pure read;
    every degradation lands on the zero face with a warn, never a raise."""
    ws = Path(ws)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)

    register_doc, reg_err = _read_yaml(ws / REGISTER_REL)
    deps_doc, deps_err = _read_yaml(ws / DEPS_REL)
    for rel, err in ((REGISTER_REL, reg_err), (DEPS_REL, deps_err)):
        if err is not None:
            warn("verification_debt",
                 f"{rel} unreadable, reading zero debt: {err}")
    if reg_err is not None or deps_err is not None:
        return zero_face()

    claims_raw = (register_doc.get("claims")
                  if isinstance(register_doc, dict) else None)
    if not isinstance(claims_raw, list):
        if not (ws / REGISTER_REL).is_file():
            return zero_face()  # absent register: an idle workspace, silent
        warn("verification_debt",
             f"{REGISTER_REL}: claims is not a list, reading zero debt")
        return zero_face()

    dependents = _dependent_counts(claims_raw, deps_doc, register_doc)

    per_claim: dict[str, dict] = {}
    for claim in claims_raw:
        if not isinstance(claim, dict):
            continue
        cid = str(claim.get("id") or "").strip()
        status = str(claim.get("status") or "").strip().upper()
        deps = dependents.get(cid) or []
        if not cid or status not in DEBT_STATUSES or not deps:
            continue
        age = _claim_age_hours(claim, now)
        weight = _age_weight(age)
        per_claim[cid] = {
            "dependents": deps,
            "age_hours": (round(age, 4) if age is not None else None),
            "weight": round(weight, 4),
            "contribution": round(len(deps) * weight, 4),
        }

    total = round(sum(row["contribution"] for row in per_claim.values()), 4)
    top = None
    if per_claim:
        top = sorted(per_claim.items(),
                     key=lambda kv: (-kv[1]["contribution"], kv[0]))[0][0]
    prior = _prior_debt(ws)
    slope = (round(total - prior, 4) if prior is not None else None)
    return {
        "D": total,
        "per_claim": per_claim,
        "slope": slope,
        "top": top,
        "verifiable_open": sorted(per_claim),
    }


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
