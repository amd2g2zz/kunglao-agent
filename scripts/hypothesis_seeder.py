#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hypothesis_seeder.py — mechanical PQ scaffold seeder (#662).

Issue #662: the hypothesis layer (#528) has storage + rehydrate but no
input side — nothing seeds hypotheses from task_spec, so the layer starts
empty and stays empty unless the orchestrator LLM remembers to fill it.
This seeder closes that gap mechanically: at every cold-start digest
build (and on direct CLI invocation), every task_spec.primary_questions[]
entry gets an open scaffold hypothesis whose body carries the `pq:<qid>`
marker. Scaffolds invent NO analysis content (candidates=[] per #412).

Spec: openspec/changes/issue-662-hypothesis-seed/{proposal,design,specs}.
Design references D1-D8. Fail-open per D7.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None

# Canonical PQ parse — same schema rules as convergence_check (issue #77);
# a malformed schema is convergence's INVALID problem, not ours (D7).
from convergence_check import _parse_primary_questions
from init_state import STATE_FILE, read_project_type  # #110 init context
from hypothesis_store import Hypothesis, HypothesisStore

MARKER_FMT = "pq:{qid}"
PLACEHOLDER_CLAIM = "C-PENDING"


def _load_task_spec(ws: Path) -> dict:
    p = Path(ws) / "task_spec.yaml"
    if not p.exists() or yaml is None:
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _next_free_id(store: HypothesisStore) -> str:
    used = set()
    for h in store.list_all():
        num = "".join(ch for ch in h.id if ch.isdigit())
        if num:
            used.add(int(num))
    n = 1
    while n in used:
        n += 1
    return f"H-{n:03d}"


def _scaffold_body(qid: str, need: str | None) -> str:
    need_line = f" (need: {need})" if need else ""
    return (
        f"{MARKER_FMT.format(qid=qid)}\n\n"
        f"Seeded from primary_question {qid}{need_line}. Scaffold only —\n"
        "the orchestrator fills `candidates` with competing explanations\n"
        "BEFORE dispatching the first C-NN for this question. Adjudicate by\n"
        "refute (refuting_fact_id) or supersede (superseded_by) per #528.\n"
    )


def seed_from_task_spec(ws: Path) -> List[dict]:
    """Ensure every task_spec primary_question has a hypothesis scaffold.

    Idempotency: a question is already covered when ANY hypothesis (any
    status — adjudicated scaffolds must not resurrect, per #528's
    decided-hypotheses-stay-decided rule) carries the `pq:<qid>` body
    marker. The marker lives in the body because HypothesisStore._write
    drops unknown frontmatter keys on rewrite (design D2).

    Returns the list of created scaffolds: [{"hyp_id", "qid"}, ...].
    Fail-open: missing/malformed task_spec -> [] (never raises).
    """
    ws = Path(ws)
    task_spec = _load_task_spec(ws)
    questions, _err = _parse_primary_questions(task_spec)
    if not questions:
        return []

    store = HypothesisStore(ws / "hypotheses")
    existing = store.list_all()  # any status (see docstring)
    covered = set()
    for h in existing:
        for qid, _need in questions:
            if MARKER_FMT.format(qid=qid) in h.body:
                covered.add(qid)

    created: List[dict] = []
    for qid, need in questions:
        if qid in covered:
            continue
        hyp = Hypothesis(
            id=_next_free_id(store),
            claim_id=PLACEHOLDER_CLAIM,
            competitor_group=f"pq-{qid}",
            candidates=[],
            status="open",
            body=_scaffold_body(qid, need),
        )
        hyp.path = ws / "hypotheses" / f"{hyp.id}.md"
        store._write(hyp)  # store has no public create; _write is the writer
        created.append({"hyp_id": hyp.id, "qid": qid})
        _emit(ws, hyp.id, qid)
    return created


def _emit(ws: Path, hyp_id: str, qid: str) -> None:
    """kunglao_log observability (design D6) — guarded, never raises."""
    try:
        from kunglao_log import emit
        emit(ws, actor="hypothesis_seeder", action="hypothesis_seed",
             detail=f"{hyp_id} pq:{qid}")
    except Exception:  # noqa: BLE001 — logging must never break seeding
        pass


# ---------------------------------------------------------------------------
# #669 — apkid evidence feeds the pq-family competitor_groups
# ---------------------------------------------------------------------------
# Tokens that mark a PQ as apkid-relevant. A PQ id/question containing any
# of these tokens is a candidate to receive `apkid:<category>:<rule>`
# candidates from evidence/apkid.json. Kept short and conservative — over-
# matching is recovered downstream by the #528 adjudicator.
_APKID_PQ_TOKENS = ("packer", "compiler", "obfuscator", "anti-debug", "anti-vm", "anti_debug", "anti_vm")
# Category -> summary key in evidence/apkid.json
_CATEGORY_TO_SUMMARY_KEY = {
    "packer": "packer",
    "compiler": "compiler",
    "obfuscator": "obfuscator",
    "anti_vm": "anti_vm",
    "anti_debug": "anti_debug",
}


def _apkid_relevant_qids(task_spec: dict) -> dict[str, set[str]]:
    """Map qid -> set of apkid categories relevant to that qid.

    A category is relevant when ANY token in _APKID_PQ_TOKENS appears in the
    qid OR the question text (case-insensitive substring). Returns
    {qid: {category, ...}}."""
    questions, _err = _parse_primary_questions(task_spec)
    out: dict[str, set[str]] = {}
    for qid, _need in questions:
        # The qid itself + the question text (need may be free text)
        # Question text lives in raw primary_questions entries; recover here.
        raw = task_spec.get("primary_questions") or []
        text = ""
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("id") == qid:
                    # canonical {id, q/need/...} or legacy one-key
                    for k, v in item.items():
                        if isinstance(v, str):
                            text += " " + v
                    break
        haystack = (qid + " " + text).lower()
        cats: set[str] = set()
        for token in _APKID_PQ_TOKENS:
            if token.lower() in haystack:
                # map token back to category
                if token.lower() in ("anti-debug", "anti_debug"):
                    cats.add("anti_debug")
                elif token.lower() in ("anti-vm", "anti_vm"):
                    cats.add("anti_vm")
                else:
                    cats.add(token.lower())
        if cats:
            out[qid] = cats
    return out


def seed_apkid_candidates(ws: Path) -> int:
    """Append apkid-derived candidates to existing pq-family scaffolds.

    Reads <ws>/evidence/apkid.json when present (status == ok). For each PQ
    whose id/question matches a category-relevant token, appends candidate
    strings of the form `apkid:<category>:<rule>` to the matching hypothesis's
    `candidates` list. Idempotent: a candidate already present is skipped.

    Returns the count of NEW candidates appended. Fail-open: missing
    evidence, bad JSON, or no task_spec -> 0 (never raises).
    """
    ws = Path(ws)
    evidence_path = ws / "evidence" / "apkid.json"
    if not evidence_path.exists():
        return 0
    try:
        data = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(data, dict) or data.get("status") != "ok":
        return 0
    summary = data.get("summary") or {}

    task_spec = _load_task_spec(ws)
    qid_to_cats = _apkid_relevant_qids(task_spec)
    if not qid_to_cats:
        return 0

    store = HypothesisStore(ws / "hypotheses")
    if not store.root.is_dir():
        return 0

    appended = 0
    for qid, cats in qid_to_cats.items():
        target_group = f"pq-{qid}"
        matching = [h for h in store.list_all() if h.competitor_group == target_group]
        if not matching:
            continue
        for hyp in matching:
            existing = set(hyp.candidates)
            new_candidates: list[str] = []
            for cat in sorted(cats):
                rules = summary.get(_CATEGORY_TO_SUMMARY_KEY.get(cat, cat)) or []
                for rule in rules:
                    cand = f"apkid:{cat}:{rule}"
                    if cand not in existing and cand not in new_candidates:
                        new_candidates.append(cand)
            if new_candidates:
                hyp.candidates = list(hyp.candidates) + new_candidates
                store._write(hyp)
                appended += len(new_candidates)
                try:
                    from kunglao_log import emit
                    emit(ws, actor="hypothesis_seeder", action="apkid_candidates",
                         detail=f"{hyp.id} +{len(new_candidates)}")
                except Exception:  # noqa: BLE001
                    pass
    return appended


# ---------- #692 WP5: dexdc taint findings -> competitor candidates ------

_TAINT_PQ_TOKENS = ("collect", "fingerprint", "device", "track", "privacy",
                    "exfil", "sdk", "risk", "\u91c7\u96c6", "\u9690\u79c1",
                    "\u98ce\u63a7", "\u8ffd\u8e2a")

_TAINT_SEEDS_FILE = (Path(__file__).resolve().parent.parent /
                     "references" / "re-library" /
                     "android-fingerprint-seeds.yaml")


def _taint_api_categories() -> dict:
    """api -> category from the fingerprint seed table (fail-open {})."""
    try:
        data = yaml.safe_load(
            _TAINT_SEEDS_FILE.read_text(encoding="utf-8"))
        entries = data.get("seeds") if isinstance(data, dict) else None
        return {str(e.get("api")): str(e.get("category"))
                for e in (entries or [])
                if isinstance(e, dict) and e.get("api")}
    except (OSError, ValueError, yaml.YAMLError):
        return {}


def _taint_relevant_qids(task_spec: dict) -> list:
    """PQ ids whose id/question text matches a taint relevance token."""
    questions, _err = _parse_primary_questions(task_spec)
    raw = task_spec.get("primary_questions") or []
    out: list = []
    for qid, _need in questions:
        text = str(qid).lower()
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("id") == qid:
                    for v in item.values():
                        if isinstance(v, str):
                            text += " " + v
                    break
        if any(t.lower() in text for t in _TAINT_PQ_TOKENS):
            out.append(qid)
    return out


def seed_taint_candidates(ws: Path) -> int:
    """Append dexdc-taint-derived candidates to pq-family scaffolds
    (#692 WP5 - the exact mirror of seed_apkid_candidates #669).

    Reads <ws>/evidence/dexdc_taint.json when present (status == ok). For
    each issue, candidate = ``taint:<category>:<source>`` (category from
    the fingerprint seed table; ``uncategorized`` when not in it). Appends
    to hypotheses whose competitor_group == pq-<qid> for PQs whose
    id/question matches a taint relevance token. Idempotent + fail-open
    (missing evidence / bad JSON / no task_spec -> 0, never raises).
    Returns the count of NEW candidates appended.
    """
    ws = Path(ws)
    evidence_path = ws / "evidence" / "dexdc_taint.json"
    if not evidence_path.exists():
        return 0
    try:
        data = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(data, dict) or data.get("status") != "ok":
        return 0
    issues = data.get("issues") or []
    if not issues:
        return 0

    qids = _taint_relevant_qids(_load_task_spec(ws))
    if not qids:
        return 0

    api_cats = _taint_api_categories()
    store = HypothesisStore(ws / "hypotheses")
    if not store.root.is_dir():
        return 0

    appended = 0
    for qid in qids:
        target_group = "pq-%s" % qid
        matching = [h for h in store.list_all()
                    if h.competitor_group == target_group]
        for hyp in matching:
            existing = set(hyp.candidates)
            new_candidates: list = []
            for issue in issues:
                source = str((issue or {}).get("source") or "").strip()
                if not source:
                    continue
                category = api_cats.get(source, "uncategorized")
                cand = "taint:%s:%s" % (category, source)
                if cand not in existing and cand not in new_candidates:
                    new_candidates.append(cand)
            if new_candidates:
                hyp.candidates = list(hyp.candidates) + new_candidates
                store._write(hyp)
                appended += len(new_candidates)
                try:
                    from kunglao_log import emit
                    emit(ws, actor="hypothesis_seeder",
                         action="taint_candidates",
                         detail="%s +%d" % (hyp.id, len(new_candidates)))
                except Exception:  # noqa: BLE001 - logging never breaks seeding
                    pass
    return appended


# ---------------------------------------------------------------------------
# #110 — case-bank priors -> hypothesis layer (cold-start injection)
# ---------------------------------------------------------------------------
# Storage reality: the case bank is PER-WORKSPACE (runs/case-bank.jsonl), so
# the read side rides the cold-start chain (digest_build already fires
# seed_from_task_spec there) instead of a cross-workspace lookup — the
# initialized workspace's recurring cold start IS the replay face. Retrieval
# is scoped by (project_type + protection traits from recon evidence on
# disk); hits land as prior candidates with provenance on ONE carrier
# hypothesis. Zero rows / zero hits / zero derivable context -> nothing is
# written (cold start unchanged — no fabricated priors).
CASE_BODY_MARKER = "case-bank-priors"
_CASE_GROUP = "case-bank-priors"
CASE_HINT_LIMIT = 5


def _read_json_file(path: Path) -> dict:
    """Tolerant JSON read: missing/corrupt -> {} (never raises)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _case_query_tags(ws: Path) -> list[str]:
    """(project_type + protection traits) query context for #110 retrieval.

    project_type: init_state (analysis_state.txt, then the #625 state file).
    Protection traits: recon evidence already on disk — evidence/die.json
    (derived.detected_packer / high_entropy_sections) and evidence/apkid.json
    (summary packer/obfuscator/anti_debug/anti_vm). Dedup, order-stable.
    No derivable context -> [] (the caller skips: a context-free prior is a
    fabricated prior).
    """
    tags: list[str] = []
    ptype = read_project_type(ws)
    if not ptype:
        ptype = str(_read_json_file(ws / STATE_FILE).get("project_type") or "")
    if ptype:
        tags.append(str(ptype))
    die = _read_json_file(ws / "evidence" / "die.json")
    derived = die.get("derived") if isinstance(die.get("derived"), dict) else {}
    packer = str(derived.get("detected_packer")
                 or die.get("detected_packer") or "").strip()
    if packer:
        tags.extend(["packed", packer.lower()])
    if derived.get("high_entropy_sections") or die.get("high_entropy_sections"):
        tags.append("high-entropy")
    apkid = _read_json_file(ws / "evidence" / "apkid.json")
    summary = apkid.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    if summary.get("packer"):
        tags.append("packed")
    if summary.get("obfuscator"):
        tags.append("obfuscated")
    if summary.get("anti_debug") or summary.get("anti_vm"):
        tags.append("anti-analysis")
    out: list[str] = []
    for t in tags:
        if t and t not in out:
            out.append(t)
    return out


def _case_text(value) -> str:
    """Single-line, comma-free text (frontmatter list round-trip: the store
    parses `candidates: [a, b]` by splitting on commas)."""
    return " ".join(str(value or "").split()).replace(",", ";")


def _case_candidate_line(entry: dict) -> str:
    """One prior-candidate line with provenance (#110): failures carry
    attribution (+ premise_correction) like the <case-hints> face."""
    head = (f"case-bank prior: {entry.get('claim_id')} "
            f"({entry.get('roi_class')} method={entry.get('method')})")
    parts = [head]
    if entry.get("attribution"):
        parts.append(f"attribution: {_case_text(entry['attribution'])}")
    if entry.get("premise_correction"):
        parts.append(f"correction: {_case_text(entry['premise_correction'])}")
    return " | ".join(parts)


def _case_body() -> str:
    return (
        f"{CASE_BODY_MARKER}\n\n"
        "Prior candidates from the case bank (runs/case-bank.jsonl),\n"
        "retrieved at cold start by (project_type + protection traits).\n"
        "Failures lead (counterexample pruning > positive reuse). These are\n"
        "PROVENANCE-CARRIED hints — what was tried in a similar context,\n"
        "what the signals looked like, what the attribution was — never hard\n"
        "rules. Judgment stays with the orchestrator/worker; adjudicate per\n"
        "#528 (refute / supersede).\n"
    )


def _emit_case(ws: Path, hyp_id: str, n: int) -> None:
    """kunglao_log observability (#110) — guarded, never raises."""
    try:
        from kunglao_log import emit
        emit(ws, actor="hypothesis_seeder", action="case_priors_seeded",
             detail=f"{hyp_id} +{n} case prior(s)")
    except Exception:  # noqa: BLE001 — logging must never break seeding
        pass


def seed_case_candidates(ws: Path, limit: int = CASE_HINT_LIMIT) -> int:
    """Inject case-bank hits as prior candidates (cold-start face, #110).

    case_bank.retrieve over the (project_type + protection traits) context —
    FAILURES FIRST (the retrieve contract), newest first within a class.
    Hits append to ONE carrier hypothesis (identified by the
    case-bank-priors body marker — the #662 marker pattern, because the
    store drops unknown frontmatter keys on rewrite); idempotent per exact
    candidate string. Returns the count of NEW candidates appended.

    Zero rows / zero hits / zero derivable context -> 0, nothing written.
    Fail-open (D7): every failure degrades to 0, never raises.
    """
    ws = Path(ws)
    try:
        import case_bank
        tags = _case_query_tags(ws)
        if not tags:
            return 0
        entries = case_bank.retrieve(ws, tags, limit)
        if not entries:
            return 0
        cands = [_case_candidate_line(e) for e in entries]
        store = HypothesisStore(ws / "hypotheses")
        carrier = next((h for h in store.list_all()
                        if CASE_BODY_MARKER in h.body), None)
        if carrier is None:
            carrier = Hypothesis(
                id=_next_free_id(store),
                claim_id=PLACEHOLDER_CLAIM,
                competitor_group=_CASE_GROUP,
                candidates=[],
                status="open",
                body=_case_body(),
            )
            carrier.path = ws / "hypotheses" / f"{carrier.id}.md"
            store._write(carrier)  # store has no public create-with-body path
        existing = set(carrier.candidates)
        new_candidates = [c for c in cands if c not in existing]
        if new_candidates:
            carrier.candidates = list(carrier.candidates) + new_candidates
            store._write(carrier)
            _emit_case(ws, carrier.id, len(new_candidates))
        return len(new_candidates)
    except Exception:  # noqa: BLE001 — priors never break cold start (D7)
        return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="hypothesis_seeder — seed PQ scaffolds into hypotheses/")
    parser.add_argument("workspace", type=Path, help="workspace root")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)
    created = seed_from_task_spec(args.workspace)
    if args.json:
        print(json.dumps({"created": created, "count": len(created)},
                         ensure_ascii=False, indent=2))
    elif created:
        for c in created:
            print(f"SEEDED: {c['hyp_id']} pq:{c['qid']}")
    else:
        print("OK: nothing to seed (idempotent or no primary_questions)")
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
