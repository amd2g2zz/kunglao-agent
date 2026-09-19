#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""target_ladder.py — the third ladder (issue 234): target/attack-surface vocabulary.

THE GAP (issue 234): the promoted obstacle claim is a one-liner statement
(failure_analysis_gate.py:579) — samplable by TS but not actionable, and the
two existing recovery ladders (method-ladder / env-ladder,
ask_for_direction_gate.py) are TOOL-FAILURE-shaped. There is no vocabulary for
TARGET-imposed obstacles: "the target pins certificates", "the artifact
won't relaunch". This module is that third ladder, riding the ladder
primitive (extends vocabulary, adds no new orchestrating organ):

  - 3 levels (T1/T2/T3, mirroring infeasible_proposal.LADDER_LEVELS), each
    rung a MECHANISM FAMILY enumerated per obstacle class. Levels are
    family-distinct BY CONSTRUCTION — a walked ladder with two same-family
    rungs is INVALID (the same-prior correlation risk of the LLM authoring
    its own alternatives is bounded at the construction level; the residual
    risk is red-teamed at obstacle settlement, inside the PROVEN chain).
  - Instrument availability ANNOTATES a rung (the `instrument` field) and
    NEVER filters it — "frida unavailable" is a note on the rung, not a
    reason to skip it.
  - An unknown/absent obstacle class falls back to the generic target-axis
    enumeration: the ladder must never be unwalkable because a class string
    did not match (same fail-open posture as the instrument rule).

Settlement gate (issue 234, required behavior 2): an obstacle claim
(origin: failure-obstacle) cannot settle CONFIRMED — register status PROVEN,
"really can't" is a positive verdict on the blocking — without its target
ladder walked-valid AND a non-empty exhaustion inventory (what was tried per
rung; the exhaustion standard, same shape as the DEFERRED inventory of
infeasible_proposal.file_proposal) AND each inventory entry's strategy
sibling minted. The gate itself is write-side, in kunglao_record's
claim_migrator (the decision-rights R3 shape); this module provides the pure predicate
(`settlement_blocker`). REFUTED stays ungated — the path-scoped closure
standard requires refuting obstacles to stay possible.

Fan-out (issue 234, required behavior 3): `mint_sibling_claims` auto-registers one
OPEN sibling claim per inventory entry — origin: obstacle-alternative,
obstacle_for edge to the parent obstacle claim, answers_question inherited,
a real claim_deps.yaml depends_on edge (same construction as
_promote_obstacle_claim, idempotent on the (origin, obstacle_for,
ladder_family) marker, never on text) — so the alternative strategies are
immediately TS-samplable (priority_ratio.is_open). The statement carries
family + tried + failed_because: actionable, the direct answer to the
one-liner complaint.

Usage:
  python scripts/target_ladder.py <ws> --check C-NN   # settlement predicate
  python scripts/target_ladder.py <ws> --mint C-NN    # auto-register siblings

Ladder artifact (mirrors runs/infeasible-ladder-<claim>.yaml):
  runs/target-ladder-<claim>.yaml
    obstacle_class: interception
    attempts:
      - {level: T1, family: hooking, action: ..., outcome: ...,
         instrument: frida unavailable (annotation, never a filter)}
    inventory:
      - {family: hooking, tried: ..., failed_because: ...}
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

# The three target/attack-surface levels (mirrors the L1/L2/L3 shape of
# infeasible_proposal.LADDER_LEVELS — the ladder primitive's shape).
TARGET_LADDER_LEVELS = ("T1", "T2", "T3")

# Linkage vocabulary (issue 234, verbatim): the parent obstacle claims are
# minted by failure_analysis_gate._promote_obstacle_claim with
# origin=failure-obstacle; the strategy siblings minted here carry
# origin=obstacle-alternative.
OBSTACLE_ORIGIN = "failure-obstacle"
SIBLING_ORIGIN = "obstacle-alternative"

# Mechanism families per obstacle class (the analysis-target / attack-surface
# axis — NOT tool failures). The tuple is the class's family pool, in
# enumeration order. interception is the issue 234 example, verbatim.
OBSTACLE_CLASS_FAMILIES: dict[str, tuple[str, ...]] = {
    "interception": ("hooking", "repackaging", "ca-install",
                     "proxy-interposition"),
    "visibility": ("static-unpacking", "dynamic-tracing", "memory-imaging"),
    "execution": ("native-execution", "emulation", "instrumented-runner"),
}
# Fail-open fallback: an unknown or absent obstacle_class still enumerates a
# generic target-axis ladder — never unwalkable (same posture as the
# instrument-annotation rule).
FAMILY_FALLBACK: tuple[str, ...] = ("surface-pivot", "mechanism-substitution",
                                    "environment-reconstruction")


def ladder_path(ws: Path, claim_id: str) -> Path:
    """The ladder artifact for an obstacle claim (mirrors infeasible)."""
    return Path(ws) / "runs" / f"target-ladder-{claim_id}.yaml"


def family_ladder_for(obstacle_class: str | None) -> tuple[str, ...]:
    """The mechanism-family enumeration for an obstacle class (fail-open)."""
    cls = (obstacle_class or "").strip().lower()
    return OBSTACLE_CLASS_FAMILIES.get(cls, FAMILY_FALLBACK)


def load_ladder(ws: Path, claim_id: str) -> dict | None:
    """runs/target-ladder-<claim>.yaml -> dict, or None (fail-open read,
    same contract as infeasible_proposal._load_ladder)."""
    p = ladder_path(ws, claim_id)
    if not p.exists():
        return None
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def ladder_defects(ladder: dict | None,
                   obstacle_class: str | None = None) -> list[str]:
    """Empty list iff the ladder is walked-valid.

    Valid means: every level T1..T3 is covered; every rung's family is in
    the class's mechanism-family enumeration; NO family repeats (two
    same-family rungs -> the ladder is invalid — levels are
    mechanism-family distinct BY CONSTRUCTION, issue-234 acceptance).
    Instrument availability is never read here (annotation, not filter).
    """
    if not isinstance(ladder, dict):
        return [f"missing levels: {','.join(TARGET_LADDER_LEVELS)} "
                f"(no ladder artifact)"]
    fams = family_ladder_for(obstacle_class or ladder.get("obstacle_class"))
    attempts = ladder.get("attempts") or []
    if not isinstance(attempts, list):
        attempts = []
    seen_levels: list[str] = []
    seen_fams: list[str] = []
    defects: list[str] = []
    for a in attempts:
        if not isinstance(a, dict):
            continue
        level = str(a.get("level") or "").strip().upper()
        family = str(a.get("family") or "").strip().lower()
        if level not in TARGET_LADDER_LEVELS:
            defects.append(f"invalid level: {level or '(empty)'}")
            continue
        if family not in fams:
            defects.append(
                f"level {level}: unknown family '{family}' for the "
                f"enumeration {','.join(fams)}")
            continue
        seen_levels.append(level)
        seen_fams.append(family)
    missing = [lv for lv in TARGET_LADDER_LEVELS if lv not in seen_levels]
    if missing:
        defects.append(f"missing levels: {','.join(missing)}")
    for fam in sorted({f for f in seen_fams if seen_fams.count(f) > 1}):
        levels = ",".join(lv for lv, fm in zip(seen_levels, seen_fams)
                          if fm == fam)
        defects.append(f"family-repeat: {fam} on {levels} (levels are "
                       f"mechanism-family distinct by construction)")
    return defects


def inventory_entries(ladder: dict | None) -> list[dict]:
    """The exhaustion inventory: what was tried per rung. An entry must name
    its rung family AND what was tried — that is the exhaustion standard
    (same shape as the DEFERRED inventory of infeasible_proposal)."""
    if not isinstance(ladder, dict):
        return []
    inv = ladder.get("inventory")
    if not isinstance(inv, list):
        return []
    return [e for e in inv
            if isinstance(e, dict)
            and str(e.get("family") or "").strip()
            and str(e.get("tried") or "").strip()]


def _load_claims(ws: Path) -> tuple[list, Path | None]:
    p = Path(ws) / "claim-register.yaml"
    if not p.exists():
        return [], None
    try:
        reg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return [], p
    return reg.get("claims") or [], p


def _claims_from_text(register_text: str) -> list:
    """Parsed claims from register TEXT (fail-open: a YAML error yields [])."""
    try:
        reg = yaml.safe_load(register_text) or {}
    except yaml.YAMLError:
        return []
    claims = reg.get("claims") if isinstance(reg, dict) else None
    return claims if isinstance(claims, list) else []


def _find_claim(claims: list, claim_id: str) -> dict | None:
    return next((c for c in claims
                 if isinstance(c, dict) and str(c.get("id") or "") == claim_id),
                None)


def _sibling_exists(claims: list, obstacle_claim_id: str,
                    family: str) -> bool:
    """Idempotency marker: (origin, obstacle_for, ladder_family) — the same
    marker-not-text rule as _promote_obstacle_claim. Family comparison is
    case-insensitive: a hand-authored sibling row with `ladder_family:
    Hooking` must be RECOGNIZED as the marker, not duplicated around."""
    return any(c.get("origin") == SIBLING_ORIGIN
               and c.get("obstacle_for") == obstacle_claim_id
               and str(c.get("ladder_family") or "").lower() ==
               family.lower()
               for c in claims)


def _class_defects(claim: dict | None, ladder: dict | None) -> list[str]:
    """The class-authority defects (issue 234, review F2): the authoritative
    obstacle_class lives on the PARENT CLAIM — pinned at promotion time by
    failure_analysis_gate._promote_obstacle_claim (--obstacle-class) — and
    the artifact must DECLARE and MATCH it. The model that authors the
    ladder artifact cannot choose its own family pool at walk time; a
    mismatch (or a claim with no pinned class) is a defect, fail-closed.
    Family-repeat invalidation stays an additional artifact-state check
    inside ladder_defects."""
    pinned = str((claim or {}).get("obstacle_class") or "").strip()
    if not pinned:
        return ["obstacle_class not pinned on the parent claim at promotion "
                "(re-record the failure analysis with --obstacle-class) — "
                "no authoritative family enumeration to walk against"]
    if not isinstance(ladder, dict):
        return []  # the missing-artifact defect names this case already
    declared = str(ladder.get("obstacle_class") or "").strip()
    if not declared:
        return ["ladder artifact declares no obstacle_class — the walk must "
                f"name the claim-pinned class '{pinned}'"]
    if declared.lower() != pinned.lower():
        return [f"ladder obstacle_class '{declared}' != claim-pinned "
                f"'{pinned}' — the class is pinned at promotion, not chosen "
                f"by the artifact author"]
    return []


def settlement_blocker(ws: Path, claim_id: str,
                       register_text: str | None = None) -> str | None:
    """The NAMED reason an obstacle claim cannot settle CONFIRMED, or None.

    Applies ONLY to obstacle claims (origin: failure-obstacle) — any other
    claim returns None (the gate is silent). The origin/claim lookup is the
    PARSED route: the caller's register text (the migrator's and the hook
    backstop's already-read snapshot) is yaml-parsed in memory; a missing
    register_text falls back to one file read. Same-parse claims also feed
    the sibling checks — no snapshot/fresh-read TOCTOU mix.

    Defects, in order: the class authority (claim-pinned obstacle_class
    missing, artifact class undeclared, or mismatch — review F2); the
    ladder is not walked-valid (level gaps, unknown family, family
    repeats); the exhaustion inventory is empty; an inventory entry's
    strategy sibling was never minted (fan-out enforcement — exhaustion
    means the alternatives are REGISTERED, not just listed).
    """
    ws = Path(ws)
    if register_text is not None:
        claims = _claims_from_text(register_text)
    else:
        claims, _ = _load_claims(ws)
    claim = _find_claim(claims, claim_id)
    if claim is None or str(claim.get("origin") or "") != OBSTACLE_ORIGIN:
        return None
    ladder = load_ladder(ws, claim_id)
    defects = _class_defects(claim, ladder)
    if not defects:
        defects = ladder_defects(ladder, claim.get("obstacle_class"))
    if defects:
        return (f"TARGET LADDER GATE: obstacle claim {claim_id} cannot "
                f"settle CONFIRMED (PROVEN) — walk the 3-level "
                f"target/attack-surface ladder first ({'; '.join(defects)}); "
                f"artifact: {ladder_path(ws, claim_id)} (scripts/"
                f"target_ladder.py)")
    inv = inventory_entries(ladder)
    if not inv:
        return (f"TARGET LADDER GATE: obstacle claim {claim_id} exhaustion "
                f"inventory empty — list what was tried per rung "
                f"({ladder_path(ws, claim_id)} inventory)")
    # review r2 (same class as the 237 H1 two-read seam): the sibling
    # checks consume the SAME parsed register as the origin/class lookup —
    # the caller's snapshot when register_text was supplied, else the one
    # file read above. No second read, no TOCTOU window.
    unminted = [str(e.get("family")) for e in inv
                if not _sibling_exists(claims, claim_id,
                                       str(e.get("family")).strip().lower())]
    if unminted:
        return (f"TARGET LADDER GATE: inventory entries without registered "
                f"strategy siblings: {', '.join(unminted)} — run "
                f"python scripts/target_ladder.py <ws> --mint {claim_id}")
    return None


def mint_sibling_claims(ws: Path, obstacle_claim_id: str) -> dict:
    """Auto-register one strategy sibling per inventory entry (issue 234).

    Same construction as _promote_obstacle_claim: OPEN claim,
    depends_on the parent, answers_question inherited, a real
    claim_deps.yaml edge, idempotent on the (origin, obstacle_for,
    ladder_family) marker (case-insensitive).

    Guarded (review F3): the parent must EXIST, carry origin
    failure-obstacle, and its target ladder must be walked-valid against
    the CLAIM-PINNED obstacle_class BEFORE anything is minted — a mistyped
    id or a non-obstacle parent must never pollute the register and
    claim_deps.yaml with edges into the TS pool.

    Returns {"minted": [rows], "refused": None} on success (rows may be
    empty when every entry already has its sibling), or
    {"minted": [], "refused": "<reason>"} — the refusal is explicit, never
    a silent partial write.
    """
    ws = Path(ws)
    claims, p = _load_claims(ws)
    if p is None:
        return {"minted": [],
                "refused": f"no claim-register.yaml under {ws}"}
    parent = _find_claim(claims, obstacle_claim_id)
    if parent is None:
        return {"minted": [],
                "refused": f"parent claim {obstacle_claim_id} not found — "
                           f"refusing to mint siblings against a "
                           f"nonexistent parent"}
    if str(parent.get("origin") or "") != OBSTACLE_ORIGIN:
        return {"minted": [],
                "refused": f"parent claim {obstacle_claim_id} origin is "
                           f"'{parent.get('origin')}' — only "
                           f"{OBSTACLE_ORIGIN} claims fan out"}
    ladder = load_ladder(ws, obstacle_claim_id)
    defects = _class_defects(parent, ladder) or ladder_defects(
        ladder, parent.get("obstacle_class"))
    if defects:
        return {"minted": [],
                "refused": f"target ladder not walked-valid "
                           f"({'; '.join(defects)}) — walk it before "
                           f"minting"}
    inv = inventory_entries(ladder)
    if not inv:
        return {"minted": [],
                "refused": "exhaustion inventory empty — nothing to fan out"}
    # ---- issue 252: the fan-out family IS a hypothesis family ----
    # One family hypothesis per obstacle claim (body-marker idempotent);
    # every minted sibling is stamped with its linkage so the sibling arms
    # are family-visible and their settlements sync the family ledger.
    from hypothesis_bridge import ensure_family, family_group, HYPOTHESIS_REF
    family = ensure_family(
        ws,
        marker=f"obstacle-family:{obstacle_claim_id}",
        claim_id=obstacle_claim_id,
        body=(f"Family ledger for obstacle claim {obstacle_claim_id} — its "
              f"strategy siblings are the arms; family state syncs from "
              f"their claim settlements (#528) via hypothesis_bridge."))
    reg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    from failure_analysis_gate import _next_claim_id  # single ID grammar
    minted: list[dict] = []
    for entry in inv:
        family_name = str(entry.get("family")).strip().lower()
        if _sibling_exists(claims, obstacle_claim_id, family_name):
            continue
        tried = " ".join(str(entry.get("tried") or "").split())
        failed_because = " ".join(str(entry.get("failed_because") or "").split())
        statement = (f"Alternative for obstacle {obstacle_claim_id} "
                     f"[{family_name}]: try {tried}")
        if failed_because:
            statement += f" — the walked rung failed because {failed_because}"
        new_id = _next_claim_id(claims)
        sibling = {
            "id": new_id,
            "status": "OPEN",
            "boundary_type": "obstacle-alternative",
            "evidence_tier_attempted": 0,
            "promotion_attempts": 0,
            "depends_on": [obstacle_claim_id],
            "statement": statement,
            "origin": SIBLING_ORIGIN,
            "obstacle_for": obstacle_claim_id,
            "ladder_family": family_name,
            "promoted_from": str(ladder_path(ws, obstacle_claim_id)),
            # issue 252 family linkage (edge fields, the origin/obstacle_for style)
            "competitor_group": family_group(family.id),
            HYPOTHESIS_REF: family.id,
        }
        if (parent or {}).get("answers_question"):
            sibling["answers_question"] = parent["answers_question"]
        claims.append(sibling)
        reg["claims"] = claims
        p.write_text(
            yaml.safe_dump(reg, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        _ensure_dep_edge(ws, obstacle_claim_id, new_id)
        minted.append({"id": new_id, "ladder_family": family_name})
    return {"minted": minted, "refused": None}


def _ensure_dep_edge(ws: Path, parent_id: str, child_id: str) -> None:
    """The real DAG edge (claim_deps.yaml — the authoritative dep store),
    mirroring _promote_obstacle_claim's deps write."""
    deps_path = Path(ws) / "claim_deps.yaml"
    deps: dict = {}
    if deps_path.exists():
        try:
            loaded = yaml.safe_load(deps_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                deps = loaded
        except Exception:  # noqa: BLE001 — rebuild from the edge below
            deps = {}
    edges = deps.get("depends_on")
    if not isinstance(edges, dict):
        edges = {}
    parents = edges.get(child_id)
    if not isinstance(parents, list):
        parents = []
    if parent_id not in parents:
        parents.append(parent_id)
    edges[child_id] = parents
    deps["depends_on"] = edges
    deps_path.write_text(
        yaml.safe_dump(deps, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="target_ladder.py",
        description="Target/attack-surface ladder (issue 234): settlement predicate "
                    "+ strategy fan-out for obstacle claims")
    parser.add_argument("workspace", help="workspace root (claim-register.yaml)")
    parser.add_argument("--check", metavar="C-NN",
                        help="print the settlement blocker for an obstacle "
                             "claim (exit 1 when blocked)")
    parser.add_argument("--mint", metavar="C-NN",
                        help="auto-register one strategy sibling per "
                             "inventory entry (idempotent)")
    args = parser.parse_args()
    ws = Path(args.workspace)
    if args.check:
        blocker = settlement_blocker(ws, args.check)
        if blocker:
            print(blocker)
            return 1
        print(f"OK: {args.check} ladder walked + inventory non-empty + "
              f"siblings minted")
        return 0
    if args.mint:
        r = mint_sibling_claims(ws, args.mint)
        if r["refused"]:
            print(f"REFUSED: {r['refused']}")
            return 1
        if not r["minted"]:
            print("no new siblings (every inventory entry already minted)")
            return 0
        for m in r["minted"]:
            print(f"MINTED {m['id']} <- {args.mint} [{m['ladder_family']}]")
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
