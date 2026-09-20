#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hypothesis_bridge.py — the hypothesis layer <-> claim economy bridge (issue 252).

Issue 252: the hypothesis organ (issue 528 storage, issue 662 seeding, issue 711 bets) had
no bridge to the claim economy — candidates were filled by a prose contract
nobody mechanized, and TS could sample only claim-register. This module is
the representation-integrity bridge (owner research-note):

  - Arms are born as CLAIMS. `mint_family_arms` mints hypothesis candidates
    as OPEN claims carrying the family linkage `competitor_group:
    hyp-<H-id>` + `hypothesis_ref` (the issue 234 edge-field style) through the
    NORMAL mint path (claim-register append, single ID grammar). The claim
    IS the representation: a minted candidate never also lives as a store
    candidate string (the issue 446 no-second-representation red line).
  - The store demotes to the FAMILY LEDGER. `sync_family_ledger` derives
    family state FROM claim settlements with the issue 528 transitions
    unchanged: any arm PROVEN/VERIFIED -> the family hypothesis confirmed
    and competing open hypotheses in its competitor_group superseded; all
    arms terminal with none positive -> refuted; otherwise pending. It is
    called from kunglao_record.claim_migrator (guarded — a sync failure
    never fails the settlement).
  - Candidate-fillers integrate, they do not multiply. Issues 234 and
    250 stamp
    the family linkage at their EXISTING mint sites; the legacy string
    feeders (issue 669 apkid, issue 692 taint, issue 110 case bank) keep their contracts
    and `mint_pending_candidates` (wired into the cold-start chain,
    digest_build) pays their strings into the economy.
  - The no-orphan-representation guard. `check_bridge_lint` errors on
    candidate strings parked in hypotheses/ (a write without a claim mint)
    and on family claims pointing at nonexistent hypotheses.

Family group namespace: `hyp-<H-id>`. The claim field's documented v1.7
namespace is task_spec q_id, so `hyp-` is collision-free.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from hypothesis_store import (Hypothesis, HypothesisStore, InvalidTransition,
                              PQ_BODY_MARKER_FMT, PQ_GROUP_FMTS)
from status_defs import TERMINAL as TERMINAL_STATUSES
from tool_value import NEGATIVE_SETTLEMENTS, POSITIVE_SETTLEMENTS
from _scriptlib import claims_of, load_register_doc

FAMILY_GROUP_FMT = "hyp-{hyp_id}"
ARM_ORIGIN = "hypothesis-arm"
HYPOTHESIS_REF = "hypothesis_ref"
# The idempotency marker field: the normalized candidate slug carried on the
# arm claim (marker-not-text, the issue 234 rule).
ARM_KEY = "arm_key"

# Modules allowed to write hypotheses/ without minting claims — the
# scaffold/bet/retro-seed/adjudication faces (none of them arm-minting).
# Enforced by tests/test_hypothesis_bridge_252.py (the static writer pin).
HYPOTHESIS_WRITER_ALLOWLIST = (
    "backtrack_loop",      # retro failure-signature scaffolds (candidates=[])
    "hypothesis_store",    # the store itself
    "hypothesis_seeder",   # PQ scaffolds + string feeders (paid by the sweep)
    "notes_writer",        # adjudication: supersede per issue 528
    "think_seat",          # issue 711 falsifiable bets (group think-bet)
)


def family_group(hyp_id: str) -> str:
    """The family id for a hypothesis: `hyp-H-001`."""
    return FAMILY_GROUP_FMT.format(hyp_id=hyp_id)


# The hypothesis-ID grammar — the namespace guard (review F8): a claim
# competitor_group in the `hyp-` namespace only adjudicates a family when
# the suffix is a real hypothesis id, and (see family_claims) only when the
# claim carries the mint-issued `hypothesis_ref` edge field. An external
# task_spec q_id that merely LOOKS like a family group cannot capture the
# namespace.
_HYP_ID_RE = re.compile(r"H-\d+")


def family_hypothesis_id(group) -> str | None:
    """`hyp-H-001` -> `H-001`; anything else -> None (not a family group).

    The suffix MUST match the hypothesis-ID grammar (H-<digits>) — an
    arbitrary `hyp-<x>` string is not a family reference.
    """
    g = str(group or "").strip()
    prefix = FAMILY_GROUP_FMT.split("{")[0]  # "hyp-"
    if not g.startswith(prefix):
        return None
    suffix = g[len(prefix):]
    return suffix if _HYP_ID_RE.fullmatch(suffix) else None


def arm_key_of(candidate: str) -> str:
    """Normalized candidate slug — the idempotency marker."""
    return " ".join(str(candidate or "").split()).lower()[:200]


def family_claims(claims: list[dict], hyp_id: str) -> list[dict]:
    """The arm claims of family `hyp_id`.

    Membership requires BOTH the group (`competitor_group == hyp-<id>`)
    AND the mint-issued marker (`hypothesis_ref == <id>` — carried by
    bridge-minted arms and the issue 234/250 stamped claim rows). A claim
    whose competitor_group merely parses as a family group without the
    edge field is NOT a member (namespace capture is rejected; the lint's
    E2b names it).
    """
    g = family_group(hyp_id)
    return [c for c in claims or []
            if str(c.get("competitor_group") or "") == g
            and str(c.get(HYPOTHESIS_REF) or "") == hyp_id]


# ---------------------------------------------------------------------------
# Family scaffolds (the issue 662 marker convention — never overwrite a family)
# ---------------------------------------------------------------------------

def _next_hypothesis_id(store: HypothesisStore) -> str:
    from hypothesis_seeder import _next_free_id  # one ID grammar
    return _next_free_id(store)


def find_hypothesis_by_marker(store: HypothesisStore, marker: str):
    h = next((x for x in store.list_all() if marker in (x.body or "")), None)
    return h


def find_pq_bound_hypothesis(store: HypothesisStore, qid: str):
    """The issue 109 binding shapes: body marker `pq:<qid>` or group
    `pq-<qid>`/`pq:<qid>` (the seeder scaffold, or an equivalent family)."""
    marker = f"pq:{qid}"
    h = find_hypothesis_by_marker(store, marker)
    if h is not None:
        return h
    groups = {f"pq-{qid}", f"pq:{qid}"}
    return next((x for x in store.list_all()
                 if (x.competitor_group or "") in groups), None)


def ensure_family(ws: Path, *, marker: str, group: str | None = None,
                  claim_id: str = "C-PENDING",
                  body: str = "") -> Hypothesis:
    """Idempotent family-scaffold creation (body-marker lookup first).

    group=None defaults to the hypothesis's OWN family group
    (`hyp-<id>`); pq families pass group=`pq-<qid>` to keep the issue 109
    binding and seeder idempotency shapes.
    """
    ws = Path(ws)
    store = HypothesisStore(ws / "hypotheses")
    existing = find_hypothesis_by_marker(store, marker)
    if existing is not None:
        return existing
    hyp_id = _next_hypothesis_id(store)
    hyp = Hypothesis(
        id=hyp_id,
        claim_id=claim_id,
        competitor_group=group or family_group(hyp_id),
        candidates=[],
        status="open",
        body=f"{marker}\n\n{body.strip()}\n",
    )
    store.create(hyp)
    _emit(ws, "family_ensured", f"{hyp.id} {marker}")
    return hyp


# ---------------------------------------------------------------------------
# Arms as claims (the normal mint path — no parallel register)
# ---------------------------------------------------------------------------

def _emit(ws: Path, action: str, detail: str) -> None:
    try:
        from kunglao_log import emit
        emit(Path(ws), actor="hypothesis_bridge", action=action, detail=detail)
    except Exception as exc:  # noqa: BLE001 — logging must never break the bridge
        print(f"hypothesis_bridge: WARN emit unavailable for {action} "
              f"({type(exc).__name__}: {exc})",
              file=sys.stderr, flush=True)


def _existing_arm_texts(claims: list[dict], hyp_id: str) -> dict[str, str]:
    """key -> candidate text of already-minted arms (the statement format
    is deterministic: "[<hyp_id> arm] <candidate>")."""
    stmt_prefix = f"[{hyp_id} arm] "
    existing: dict[str, str] = {}
    for c in claims:
        if (str(c.get("origin") or "") == ARM_ORIGIN
                and str(c.get(HYPOTHESIS_REF) or "") == hyp_id):
            stmt = str(c.get("statement") or "")
            existing[str(c.get(ARM_KEY) or "")] = stmt[len(stmt_prefix):]
    return existing


def _candidate_key_map(hyp_id: str, candidates: list[str],
                       existing: dict[str, str]) -> tuple[dict[str, str],
                                                          str | None]:
    """Batch -> {arm_key: candidate}, with the review F6b collision guard:
    the 200-char slug must never silently collapse two DIFFERENT
    candidates — a collision inside the batch or against a minted arm is
    an explicit refusal, never a silent partial mint. Returns
    (key_map, None) or ({}, refusal_reason)."""
    key_map: dict[str, str] = {}
    for cand in candidates:
        cand = str(cand or "").strip()
        if not cand:
            continue
        key = arm_key_of(cand)
        prev = key_map.get(key)
        if prev is not None and prev != cand:
            return {}, (f"arm_key collision in family {hyp_id}: two distinct "
                        f"candidates share the normalized marker '{key}' — "
                        f"shorten or differentiate the candidates, nothing "
                        f"minted")
        key_map[key] = cand
    for key, cand in key_map.items():
        prev = existing.get(key)
        if prev is not None and prev != cand:
            return {}, (f"arm_key collision in family {hyp_id}: candidate "
                        f"collides with a minted arm on the normalized "
                        f"marker '{key}' — nothing minted")
    return key_map, None


def mint_family_arms(ws: Path, hyp_id: str, candidates: list[str], *,
                     answers_question: str | None = None) -> dict:
    """Mint one OPEN arm claim per candidate into claim-register.yaml.

    Linkage: `competitor_group: hyp-<H-id>`, `hypothesis_ref: <H-id>`,
    `origin: hypothesis-arm`, `arm_key` = the normalized candidate slug.
    Idempotent on (origin, hypothesis_ref, arm_key). The candidate string
    is NEVER written to the hypothesis file — the claim is the one
    representation. Returns {"minted": [rows], "refused": None} or an
    explicit refusal (no register / no such hypothesis file / arm_key
    collision).
    """
    ws = Path(ws)
    store = HypothesisStore(ws / "hypotheses")
    try:
        store.get(hyp_id)
    except KeyError:
        return {"minted": [], "refused": (
            f"hypothesis {hyp_id} not found under {ws / 'hypotheses'} — "
            f"refusing to mint arms against a nonexistent family")}
    reg_path = ws / "claim-register.yaml"
    if not reg_path.is_file():
        return {"minted": [], "refused": f"no claim-register.yaml under {ws}"}
    reg = load_register_doc(ws)[0]
    claims = claims_of(reg)
    existing = _existing_arm_texts(claims, hyp_id)
    key_map, collision = _candidate_key_map(hyp_id, candidates, existing)
    if collision:
        return {"minted": [], "refused": collision}
    from failure_analysis_gate import _next_claim_id  # single ID grammar
    group = family_group(hyp_id)
    minted: list[dict] = []
    for key, cand in key_map.items():
        if key in existing:
            continue  # exact re-mint — idempotent
        row = {
            "id": _next_claim_id(claims),
            "status": "OPEN",
            "boundary_type": "hypothesis-arm",
            "statement": f"[{hyp_id} arm] {cand}",
            "origin": ARM_ORIGIN,
            "competitor_group": group,
            HYPOTHESIS_REF: hyp_id,
            ARM_KEY: key,
            "promotion_attempts": 0,
            "evidence_tier_attempted": 0,
            "source": "synthesis",
        }
        if answers_question:
            row["answers_question"] = answers_question
        claims.append(row)
        minted.append(row)
    if minted:
        reg["claims"] = claims
        tmp = reg_path.with_name(reg_path.name + ".tmp")
        tmp.write_text(yaml.safe_dump(reg, allow_unicode=True,
                                      sort_keys=False), encoding="utf-8")
        tmp.replace(reg_path)
        _emit(ws, "family_arms_minted",
              f"{hyp_id} +{len(minted)} "
              f"({', '.join(m['id'] for m in minted)})")
    return {"minted": minted, "refused": None}


def mint_pending_candidates(ws: Path) -> dict:
    """The sweep/migration face: pay parked candidate strings into the
    economy. For every hypothesis with candidate strings, mint each as a
    family arm, then rewrite the hypothesis with candidates=[] — the
    strings leave the store once claimed (one representation). Idempotent;
    a family whose arms all exist sweeps to empty without re-minting.
    """
    ws = Path(ws)
    store = HypothesisStore(ws / "hypotheses")
    if not store.root.is_dir():
        return {"minted": [], "swept": []}
    minted: list[dict] = []
    swept: list[str] = []
    for hyp in store.list_all():
        pending = [c for c in (hyp.candidates or []) if str(c).strip()]
        if not pending:
            continue
        r = mint_family_arms(ws, hyp.id, pending)
        if r["refused"] is not None:
            continue  # no register: the strings stay parked (lint will name it)
        minted.extend(r["minted"])
        hyp.candidates = []
        store._write(hyp)  # clear the paid strings (store rewrite keeps fm)
        swept.append(hyp.id)
    return {"minted": minted, "swept": swept}


# ---------------------------------------------------------------------------
# The family ledger sync (claim settlements -> issue 528 transitions)
# ---------------------------------------------------------------------------

def _status_of(claim: dict) -> str:
    return str((claim or {}).get("status") or "").upper()


def family_verdict(arms: list[dict]) -> str:
    """The single-source derivation shared by the sync and the lint
    (no drift): "confirm" | "refute" | "pending".

    confirm: any arm in POSITIVE_SETTLEMENTS (PROVEN/VERIFIED).
    refute:  every arm terminal AND at least one in NEGATIVE_SETTLEMENTS —
             the refuting reference must be a NEGATIVE arm id (the store's
             why-was-I-wrong trail may not carry a non-refutation); a
             DEFERRED/STALE-only family (budget exhausted, no evidence
             either way) is NOT a refutation.
    pending: anything else.
    """
    if any(_status_of(a) in POSITIVE_SETTLEMENTS for a in arms):
        return "confirm"
    if (arms
            and all(_status_of(a) in TERMINAL_STATUSES for a in arms)
            and any(_status_of(a) in NEGATIVE_SETTLEMENTS for a in arms)):
        return "refute"
    return "pending"


def _retire_open_arms(claims: list[dict], hyp_id: str, winner_id: str,
                      report: dict[str, list[str]]) -> bool:
    """Losing OPEN arms of a resolved family retire claim-level SUPERSEDED
    (superseded_by = the deciding reference — the status_defs SUPERSEDED
    semantics: a claim closed by replacement leaves the TS rank pool).
    Returns True when any claim changed (the caller persists the register).
    """
    changed = False
    for arm in family_claims(claims, hyp_id):
        if _status_of(arm) != "OPEN":
            continue
        arm["status"] = "SUPERSEDED"
        arm["superseded_by"] = winner_id
        report["retired"].append(str(arm.get("id")))
        changed = True
    return changed


def _supersede_group_peers(store: HypothesisStore, hid: str,
                           hyp: Hypothesis, winner_id: str,
                           claims: list[dict],
                           report: dict[str, list[str]]) -> bool:
    """Any arm PROVEN -> competing open hypotheses (same competitor_group)
    supersede, and their open arms retire with the family. Returns whether
    any claim row changed."""
    changed = False
    for other in store.list_open():
        if other.id == hid:
            continue
        if (other.competitor_group or "") != (hyp.competitor_group or ""):
            continue
        try:
            store.transition(other.id, "superseded", superseded_by=hid)
        except (InvalidTransition, KeyError) as exc:
            report["skipped"].append(f"{other.id}: {exc}")
            continue
        report["superseded"].append(other.id)
        _emit(store.root.parent, "family_superseded", f"{other.id} <- {hid}")
        changed |= _retire_open_arms(claims, other.id, winner_id, report)
    return changed


def _families(ws: Path, claims: list[dict]) -> dict[str, list[dict]]:
    """family id -> member arm claims whose hypothesis file exists
    (missing-file arms are the lint's E2 business, not the sync's)."""
    out: dict[str, list[dict]] = {}
    for c in claims or []:
        hid = family_hypothesis_id(c.get("competitor_group"))
        if not hid:
            continue
        if str(c.get(HYPOTHESIS_REF) or "") != hid:
            continue  # not a mint-issued member — the lint's E2b names it
        if not (Path(ws) / "hypotheses" / f"{hid}.md").exists():
            continue
        out.setdefault(hid, []).append(c)
    return out


def sync_family_ledger(ws: Path) -> dict:
    """Derive family state from member claim settlements (issue 528 vocabulary).

    Per family hypothesis (arms = mint-issued member claims):
      - verdict "confirm" (any arm PROVEN/VERIFIED) -> the OPEN family
        transitions confirmed (confirming_fact_id = <winning arm id>);
        every OTHER open hypothesis in the same competitor_group
        transitions superseded (superseded_by = <family id>); losing OPEN
        arms (of the confirmed family AND of each superseded sibling)
        retire claim-level SUPERSEDED (superseded_by = the winning arm) so
        a decided question stops drawing TS budget.
      - verdict "refute" -> the OPEN family transitions refuted
        (refuting_fact_id = the first NEGATIVE arm id in claim-id order).
      - verdict "pending" (incl. DEFERRED/STALE-only) -> no write.
    An already-confirmed family is "unchanged" (no re-emit — the sync runs
    on every settlement); terminal non-matching states are "skipped" and
    never rewound (issue 528: decided hypotheses stay decided). Register
    writes (arm retirement) are one atomic rewrite, only when changed.
    """
    ws = Path(ws)
    reg_path = ws / "claim-register.yaml"
    empty = {"confirmed": [], "superseded": [], "refuted": [], "retired": [],
             "skipped": [], "pending": [], "unchanged": []}
    if not reg_path.is_file():
        return empty
    reg = load_register_doc(ws)[0]
    claims = claims_of(reg)
    store = HypothesisStore(ws / "hypotheses")
    report: dict[str, list[str]] = {k: list(v) for k, v in empty.items()}
    claims_changed = False
    for hid in sorted(_families(ws, claims)):
        arms = sorted(family_claims(claims, hid), key=lambda c: str(c.get("id")))
        try:
            hyp = store.get(hid)
        except KeyError:
            report["skipped"].append(f"{hid}: family file missing")
            continue
        verdict = family_verdict(arms)
        if verdict == "confirm":
            winner = next(a for a in arms
                          if _status_of(a) in POSITIVE_SETTLEMENTS)
            winner_id = str(winner.get("id"))
            if hyp.status == "open":
                store.transition(hid, "confirmed",
                                 confirming_fact_id=winner_id)
                report["confirmed"].append(hid)
                _emit(ws, "family_confirmed",
                      f"{hid} <- {winner_id} (PROVEN/VERIFIED arm)")
                # any arm PROVEN -> competing open hypotheses superseded,
                # and their open arms retire with the family
                claims_changed |= _supersede_group_peers(
                    store, hid, hyp, winner_id, claims, report)
            elif hyp.status == "confirmed":
                report["unchanged"].append(f"{hid}: already confirmed")
            else:
                report["skipped"].append(
                    f"{hid}: terminal ({hyp.status}) — never rewound")
            claims_changed |= _retire_open_arms(claims, hid, winner_id, report)
        elif verdict == "refute":
            if hyp.status == "open":
                negative = [a for a in arms
                            if _status_of(a) in NEGATIVE_SETTLEMENTS]
                killer = negative[0]  # NEGATIVE id only (review F2)
                store.transition(hid, "refuted",
                                 refuting_fact_id=str(killer.get("id")))
                report["refuted"].append(hid)
                _emit(ws, "family_refuted",
                      f"{hid} <- {killer.get('id')} (all arms settled, "
                      f"none won)")
            elif hyp.status == "refuted":
                report["unchanged"].append(f"{hid}: already refuted")
            else:
                report["skipped"].append(
                    f"{hid}: terminal ({hyp.status}) — never rewound")
        else:
            report["pending"].append(hid)
    if claims_changed:
        reg["claims"] = claims
        tmp = reg_path.with_name(reg_path.name + ".tmp")
        tmp.write_text(yaml.safe_dump(reg, allow_unicode=True,
                                      sort_keys=False), encoding="utf-8")
        tmp.replace(reg_path)
    return report


# ---------------------------------------------------------------------------
# The no-orphan-representation guard
# ---------------------------------------------------------------------------

def _lint_register_claims(ws: Path, claims: list[dict],
                          errs: list[str]) -> None:
    """E2 (orphan family file) + E2b (namespace capture) over the register."""
    for c in claims:
        cid = str(c.get("id") or "?")
        hid = family_hypothesis_id(c.get("competitor_group"))
        if not hid:
            continue
        if not (ws / "hypotheses" / f"{hid}.md").exists():
            errs.append(
                f"E2 orphan family claim: {cid} names "
                f"{c.get('competitor_group')} but hypotheses/{hid}.md "
                f"does not exist")
        elif str(c.get(HYPOTHESIS_REF) or "") != hid:
            errs.append(
                f"E2b namespace claim without mint marker: {cid} names "
                f"{c.get('competitor_group')} but carries no matching "
                f"hypothesis_ref — set hypothesis_ref: {hid} (or use a "
                f"different competitor_group); unmarked hyp-* claims "
                f"never adjudicate the family")


def _lint_derivation_divergence(ws: Path, claims: list[dict],
                                hyp_by_id: dict, errs: list[str]) -> None:
    """E3: an OPEN family whose member claims already derive confirm/
    refute — the sync did not run after a settlement (the persistent-
    crash detector for the guarded claim_migrator call; repaired by
    --sync)."""
    families = _families(ws, claims)
    for hid in sorted(families):
        hyp = hyp_by_id.get(hid)
        if hyp is None or hyp.status != "open":
            continue
        verdict = family_verdict(families[hid])
        if verdict != "pending":
            errs.append(
                f"E3 derivation divergence: family {hid} is OPEN but "
                f"its member claims derive verdict '{verdict}' — the "
                f"ledger sync did not run after a settlement; run "
                f"python scripts/hypothesis_bridge.py {ws} --sync")


def check_bridge_lint(ws: Path) -> list[str]:
    """Errors for representations that bypass the bridge. Empty list = clean.

    E1: candidate strings parked in hypotheses/ — a path wrote to
        hypotheses/ without a corresponding claim mint (remediation: the
        sweep). E2: a claim claiming family linkage to a nonexistent
        hypothesis file. E2b: a claim in the hyp- namespace without the
        mint-issued hypothesis_ref edge field (namespace capture).
        E3: derivation divergence (see _lint_derivation_divergence).
    """
    ws = Path(ws)
    errs: list[str] = []
    store = HypothesisStore(ws / "hypotheses")
    for hyp in store.list_all():
        for cand in (hyp.candidates or []):
            if not str(cand).strip():
                continue
            errs.append(
                f"E1 orphan candidate: {hyp.id} parks '{cand}' in "
                f"hypotheses/ with no claim mint — run the sweep "
                f"(python scripts/hypothesis_bridge.py {ws} --sweep)")
    reg_path = ws / "claim-register.yaml"
    if reg_path.is_file():
        try:
            reg = load_register_doc(ws)[0]
        except yaml.YAMLError:
            reg = {}
        claims = claims_of(reg)
        _lint_register_claims(ws, claims, errs)
        hyp_by_id = {h.id: h for h in store.list_all()}
        _lint_derivation_divergence(ws, claims, hyp_by_id, errs)
    return errs


def open_family_arms_for_question(claims: list[dict],
                                  hypotheses: list,
                                  qid: str,
                                  claim_question: dict[str, str] | None = None,
                                  ) -> list[str]:
    """The issue 109 admission read, family-arm face: OPEN arm claim ids
    whose family hypothesis is bound to PQ `qid`.

    Binding mirrors hypothesis_store.open_candidates_for_question (the
    issue 109 shapes: body marker pq:<qid>, group pq-<qid>/pq:<qid>, or a
    claim_id -> answers_question link). Order-stable, deduplicated. This
    is the sanctioned competing-explanation pool after the issue 252
    migration — a sweep-drained (lint-clean) workspace passes first
    dispatch through minted arms, not parked strings.
    """
    cq = claim_question or {}
    group_hits = tuple(g.format(qid=qid) for g in PQ_GROUP_FMTS)
    marker = PQ_BODY_MARKER_FMT.format(qid=qid)
    bound_ids: set[str] = set()
    for h in hypotheses:
        bound = (
            marker in (h.body or "")
            or (h.competitor_group or "") in group_hits
            or cq.get(h.claim_id) == qid
        )
        if bound and h.status == "open":
            bound_ids.add(h.id)
    out: list[str] = []
    for c in claims or []:
        if _status_of(c) != "OPEN":
            continue
        hid = family_hypothesis_id(c.get("competitor_group"))
        if hid and hid in bound_ids and str(c.get(HYPOTHESIS_REF) or "") == hid:
            cid = str(c.get("id") or "").strip()
            if cid and cid not in out:
                out.append(cid)
    return out


# --- static writer scan (the allowlist pin; review F6b hardening) ---------

# Writer signals, calibrated so the CURRENT tree trips exactly the five
# allowlisted faces + the bridge (zero false positives; the regression
# window is a new writer):
#   (a) the Hypothesis dataclass constructor — nobody constructs a
#       Hypothesis to read;
#   (b) a store reference (name or type) AND a store write face;
#   (d) the hypothesis frontmatter schema key AND a raw file write — the
#       no-import raw-frontmatter evasion (hand-rolled YAML body).
_WRITER_CONSTRUCTOR_RE = re.compile(r"\bHypothesis\(")
_WRITER_STORE_RE = re.compile(r"hypothesis_store|HypothesisStore")
_WRITER_STORE_FACE_RE = re.compile(r"\._write\(|\.create\(|\.transition\(")
_WRITER_RAW_RE = re.compile(r"schema_rev")
_WRITER_RAW_WRITE_RE = re.compile(r"write_text\(")
_BRIDGE_IMPORT_RE = re.compile(
    r"^\s*(?:from hypothesis_bridge import|import hypothesis_bridge\b)",
    re.MULTILINE)


def writer_scan_offenders(scripts_dir: Path, hooks_dir: Path | None = None,
                          allowlist=HYPOTHESIS_WRITER_ALLOWLIST) -> list[str]:
    """Modules that write hypotheses/ outside the bridge + allowlist.

    A writer is a module matching any writer signal (constructor, store
    reference + write face, raw frontmatter + file write) WITHOUT either
    a real bridge import line (a comment mention does not count) or
    allowlisting. Scans scripts/ AND hooks/.
    """
    offenders: list[str] = []
    roots = [Path(scripts_dir)]
    if hooks_dir is not None:
        roots.append(Path(hooks_dir))
    for base in roots:
        if not Path(base).is_dir():
            continue
        for p in sorted(Path(base).glob("*.py")):
            if p.stem in allowlist or p.stem == "hypothesis_bridge":
                continue
            src = p.read_text(encoding="utf-8", errors="replace")
            is_writer = (
                bool(_WRITER_CONSTRUCTOR_RE.search(src))
                or (bool(_WRITER_STORE_RE.search(src))
                    and bool(_WRITER_STORE_FACE_RE.search(src)))
                or (bool(_WRITER_RAW_RE.search(src))
                    and bool(_WRITER_RAW_WRITE_RE.search(src)))
            )
            if is_writer and not _BRIDGE_IMPORT_RE.search(src):
                offenders.append(f"{base.name}/{p.name}")
    return offenders


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _as_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _cmd_mint(a: argparse.Namespace, ws: Path) -> int:
    hyp_id, cands = a.mint
    r = mint_family_arms(ws, hyp_id,
                         [c for c in cands.split(",") if c.strip()])
    if a.json:
        _as_json(r)
    elif r["refused"]:
        print(f"REFUSED: {r['refused']}")
        return 1
    else:
        for m in r["minted"]:
            print(f"MINTED {m['id']} <- {hyp_id} [{m[ARM_KEY]}]")
        if not r["minted"]:
            print("no new arms (every candidate already minted)")
    return 0


def _cmd_sweep(a: argparse.Namespace, ws: Path) -> int:
    r = mint_pending_candidates(ws)
    if a.json:
        _as_json(r)
    else:
        print(f"swept {len(r['swept'])} family/families, "
              f"minted {len(r['minted'])} arm(s)")
    return 0


def _cmd_sync(a: argparse.Namespace, ws: Path) -> int:
    r = sync_family_ledger(ws)
    if a.json:
        _as_json(r)
    else:
        print(f"confirmed={r['confirmed']} superseded={r['superseded']} "
              f"refuted={r['refuted']} pending={len(r['pending'])} "
              f"skipped={r['skipped']}")
    return 0


def _cmd_check(a: argparse.Namespace, ws: Path) -> int:
    errs = check_bridge_lint(ws)
    if a.json:
        _as_json({"errors": errs})
    elif errs:
        for e in errs:
            print(e)
    else:
        print("OK: no orphan representations")
    return 1 if errs else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="hypothesis_bridge.py",
        description="hypothesis <-> claim-economy bridge (issue 252): mint "
                    "family arms as claims, sync the family ledger, sweep "
                    "parked candidates, lint orphan representations")
    ap.add_argument("workspace", type=Path, help="workspace root")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--mint", nargs=2, metavar=("H-ID", "CANDIDATES"),
                   help="mint comma-separated candidates as arms of H-ID")
    g.add_argument("--sweep", action="store_true",
                   help="pay all parked candidate strings into the economy")
    g.add_argument("--sync", action="store_true",
                   help="sync family states from claim settlements")
    g.add_argument("--check", action="store_true",
                   help="lint orphan representations (exit 1 on findings)")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    a = ap.parse_args(argv)
    ws = a.workspace
    if a.mint:
        return _cmd_mint(a, ws)
    if a.sweep:
        return _cmd_sweep(a, ws)
    if a.sync:
        return _cmd_sync(a, ws)
    return _cmd_check(a, ws)


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
