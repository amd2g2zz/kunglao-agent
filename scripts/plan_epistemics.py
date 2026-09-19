# -*- coding: utf-8 -*-
"""plan_epistemics.py — issue 250 epistemic bookkeeping (plans branch,
unknowns mint, assumptions undermine, coverage annotates).

Owner root correction on issue 250: the root is PLAN EPISTEMICS — plans are
linear happy-path pipelines, situational unknowns are never minted or
priced, facts are assumption-free atoms. Fix = epistemic BOOKKEEPING, not a
new algorithm. Four pieces live here (or wire in from here):

  Piece 1 — lint_plan_contingency: per-step `if-fails:` branches in worker
      plans (runs/plan-<KEY>*.md). Wired into check_worker_plan's
      re-dispatch leg (hooks/worker_budget_gates.py).
  Piece 2 — derive_must_master / mint_epistemic_claims /
      seed_situational_pqs: situational unknowns -> claims with
      `boundary_type: epistemic` -> PQCategorical seeded into
      runs/posteriors.yaml keyed by the claim's answers_question string
      (the SAME string priority_ratio keys on; EXP-3 finding).
  Piece 3 matcher — split_assumption / contradicts_assumption: the
      mechanical topic/polarity contradiction rule consumed by
      refutation_propagate's semantic face.
  Piece 4 — settle_coverage / coverage_note: settle-time epistemic
      coverage ANNOTATION. Sort-shaped only (R4 anti-Goodhart): never
      blocks settlement, never blocks promotion.

Signed-gain convention (pinned by the EXP-3 spike, .spike-exp3-findings.md):
  - PQCategorical.update_* mutate IN PLACE and return None — the caller
    snapshots entropy BEFORE the call. apply_and_measure removes that
    footgun.
  - delta_h_bits = H_before − H_after is SIGNED information gain in bits;
    softening evidence legitimately RAISES entropy, so delta MAY be
    negative. NEVER clamped.
  - h_standing_bits (the entropy the categorical still carries) and
    delta_h_bits (the per-event reduction) are separate fields —
    priority_ratio prices the STANDING entropy; issue 257's settlement
    bookkeeping records the PER-EVENT delta.

Boundaries: no settlement code calls update_eliminate/update_evidence
(issue 257 wires that); LAMBDA_DH stays the only pricing parameter; no
VMP/Android replay infrastructure (issue 260).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from posteriors import PosteriorLedger, PQCategorical, entropy_bits

# ---------------------------------------------------------------------------
# Piece 1 — per-step if-fails contingency lint
# ---------------------------------------------------------------------------

_TOP_LABEL_RE = re.compile(r"^(goal|preflight|steps|fallback)\s*:",
                           re.IGNORECASE)
_STEP_LINE_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)\S")
_IF_FAILS_RE = re.compile(r"^\s*if-fails\s*:\s*(.*)$", re.IGNORECASE)


def lint_plan_contingency(text: str) -> list[str]:
    """Violations of per-step contingency in a plan document.

    The `steps:` section spans from its top-level label to the next
    top-level label (goal/preflight/steps/fallback) or EOF. Each STEP
    ENTRY (a bullet or numbered sub-line) must be followed by an
    `if-fails:` line carrying condition + action (non-empty content — a
    bare label is a violation). Plans with zero enumerated entries (the
    legacy inline single-value shape) pass trivially.
    """
    lines = text.splitlines()
    # locate the steps section
    start = None
    for i, ln in enumerate(lines):
        if _TOP_LABEL_RE.match(ln) and ln.strip().lower().startswith("steps"):
            start = i + 1
            continue
        if start is not None and _TOP_LABEL_RE.match(ln):
            lines = lines[:i]
            break
    if start is None:
        return []
    violations: list[str] = []
    step_no = 0
    pending = None  # (step_no, first-words) of a step awaiting its if-fails
    for ln in lines[start:]:
        m = _IF_FAILS_RE.match(ln)
        if m:
            if pending is None:
                continue  # stray if-fails outside a step — not our defect
            if not m.group(1).strip():
                violations.append(
                    f"step {pending}: if-fails branch has no condition/"
                    "action (bare if-fails: label)")
            pending = None
            continue
        if _STEP_LINE_RE.match(ln):
            if pending is not None:
                violations.append(
                    f"step {pending}: no if-fails branch (condition + "
                    "action) before the next step")
            step_no += 1
            pending = step_no
    if pending is not None:
        violations.append(
            f"step {pending}: no if-fails branch (condition + action) — "
            "per-step contingency required (issue 250)")
    return violations


# ---------------------------------------------------------------------------
# Piece 2 — derive MUST-MASTER unknowns, mint epistemic claims, seed PQs
# ---------------------------------------------------------------------------

# vmp class = the difficulty_calibration SEVERE_PACKERS family (vmprotect/
# themida): dispatch is the whole game, so dispatch-mode and pointer-table
# reachability are MUST-MASTER situational facts.
VMP_PACKERS = ("vmprotect", "themida")

_DISPATCH_GATE = ("PROVEN fact cites the dispatch mechanism with byte/"
                  "runtime evidence")
_TABLE_GATE = ("PROVEN fact cites a pointer-table entry or its absence "
               "with byte evidence")
_NATIVES_GATE = ("PROVEN fact cites the registration binding (which "
                 "method, which offset) with byte evidence")

# Each unknown: pq_id == the answers_question string (the ONE string that
# keys the ledger PQ, matches oracle target_pq, and rides the claim).
_MUST_MASTER: dict[str, list[dict]] = {
    "vmp": [
        {"pq_id": "q_dispatch_mode",
         "question": ("Is dispatch static (xref-addressable) or dynamic "
                      "(runtime-resolved)?"),
         "candidates": {"static": 1.0, "dynamic": 1.0},
         "promotion_gate": _DISPATCH_GATE},
        {"pq_id": "q_pointer_table_reachability",
         "question": ("Which functions are reachable via pointer/dispatch "
                      "tables?"),
         "candidates": {"table_reachable": 1.0, "not_table_reachable": 1.0},
         "promotion_gate": _TABLE_GATE},
    ],
    "android": [
        {"pq_id": "q_dispatch_mode",
         "question": ("Is JNI dispatch static (static bindings) or dynamic "
                      "(RegisterNatives)?"),
         "candidates": {"static": 1.0, "dynamic": 1.0},
         "promotion_gate": _DISPATCH_GATE},
        {"pq_id": "q_register_natives_map",
         "question": ("Which native methods are registered dynamically via "
                      "RegisterNatives?"),
         "candidates": {"register_natives_dynamic": 1.0,
                        "static_jni_bindings": 1.0},
         "promotion_gate": _NATIVES_GATE},
    ],
}


def detect_target_class(ws: Path) -> str | None:
    """vmp | android | None — from recon evidence already on disk.

    vmp: evidence/die.json detected_packer in the SEVERE_PACKERS family.
    android: evidence/apkid.json status ok (the hypothesis_seeder read
    precedent) or an android project_type in analysis_state.txt.
    Fail-open: any read problem -> None (no derivation, never a crash).
    """
    ws = Path(ws)
    try:
        die = ws / "evidence" / "die.json"
        if die.exists():
            data = json.loads(die.read_text(encoding="utf-8"))
            derived = data.get("derived") if isinstance(data, dict) else None
            packer = str((derived or {}).get("detected_packer")
                         or (data or {}).get("detected_packer") or "").lower()
            if any(p in packer for p in VMP_PACKERS):
                return "vmp"
    except (OSError, ValueError):
        pass
    try:
        apkid = ws / "evidence" / "apkid.json"
        if apkid.exists():
            data = json.loads(apkid.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("status") == "ok":
                return "android"
    except (OSError, ValueError):
        pass
    try:
        state = ws / "analysis_state.txt"
        if state.exists() and "android" in state.read_text(
                encoding="utf-8", errors="replace").lower():
            return "android"
    except OSError:
        pass
    return None


def derive_must_master(target_class: str | None, task_spec: dict) -> list[dict]:
    """The MUST-MASTER situational unknown list for a target class.

    Derived from the target class (never user-articulated — the
    issue-170 lineage). Copies (never the template dicts) so callers can mutate.
    Unknown target class -> [] (nothing derived, nothing fabricated).
    """
    if target_class not in _MUST_MASTER:
        return []
    return [dict(u) for u in _MUST_MASTER[target_class]]


def mint_epistemic_claims(existing_claims: list[dict], unknowns: list[dict],
                          next_id_fn) -> list[dict]:
    """Mint boundary_type: epistemic claims for unresolved unknowns.

    Idempotent by pq_id: an answers_question already covered by ANY
    existing claim skips (re-running mint never duplicates). Each minted
    claim records the signed-gain fields at mint time: h_standing_bits =
    the uniform-prior entropy (entropy_bits, never a guess),
    delta_h_bits = 0.0 (no settlement event has touched the PQ yet).
    """
    covered = {str(c.get("answers_question") or "").strip()
               for c in (existing_claims or [])}
    minted: list[dict] = []
    for i, u in enumerate(unknowns or []):
        pq_id = str(u.get("pq_id") or "").strip()
        if not pq_id or pq_id in covered:
            continue
        candidates = {str(k): float(v)
                      for k, v in (u.get("candidates") or {}).items()}
        if not candidates:
            continue
        h0 = entropy_bits([1.0 / len(candidates)] * len(candidates))
        minted.append({
            "id": next_id_fn(len(minted)),
            "status": "OPEN",
            "boundary_type": "epistemic",
            "answers_question": pq_id,
            "statement": str(u.get("question") or pq_id),
            "title": str(u.get("question") or pq_id),
            "promotion_gate": str(u.get("promotion_gate") or "").strip(),
            "evidence_tier_attempted": 0,
            "promotion_attempts": 0,
            "depends_on": [],
            "candidates": candidates,
            "h_standing_bits": round(h0, 6),
            "delta_h_bits": 0.0,
            "source": "synthesis",
        })
    return minted


def _task_spec_candidates(task_spec: dict, pq_id: str) -> dict | None:
    """model_selection candidates for pq_id, uniform weights (the 106
    seeder convention — scaffolds invent no analysis content, issue 412)."""
    for q in (task_spec or {}).get("primary_questions") or []:
        if not isinstance(q, dict) or q.get("id") != pq_id:
            continue
        cands = q.get("candidates") or []
        if q.get("need") == "model_selection" and cands:
            return {str(c): 1.0 for c in cands}
    return None


def seed_situational_pqs(ws: Path, claims: list[dict],
                         task_spec: dict) -> list[dict]:
    """Seed one PQCategorical per epistemic claim into ledger.pqs.

    Key = the claim's answers_question string; candidates prefer the
    matching task_spec model_selection candidate set, else the claim's
    derived competitor set (both uniform). Idempotent: a pq_id already in
    the ledger is left untouched. Saves the ledger atomically. Returns a
    report: [{pq_id, h_standing_bits, source}].
    """
    ws = Path(ws)
    ledger = PosteriorLedger.load(ws)
    report: list[dict] = []
    for c in claims or []:
        if str(c.get("boundary_type") or "") != "epistemic":
            continue
        pq_id = str(c.get("answers_question") or "").strip()
        if not pq_id or pq_id in ledger.pqs:
            continue
        cands = _task_spec_candidates(task_spec, pq_id)
        source = "task_spec_candidates"
        if cands is None:
            cands = {str(k): float(v)
                     for k, v in (c.get("candidates") or {}).items()}
            source = "derived"
        if not cands:
            continue
        pq = PQCategorical(pq_id, cands)
        ledger.pqs[pq_id] = pq
        h = round(pq.entropy(), 6)
        c["h_standing_bits"] = h
        report.append({"pq_id": pq_id, "h_standing_bits": h,
                       "source": source})
    if report:
        ledger.save(ws)
    return report


# ---------------------------------------------------------------------------
# Signed-gain bookkeeping (the EXP-3 call shape, footgun removed)
# ---------------------------------------------------------------------------

def apply_and_measure(pq: PQCategorical, event: tuple) -> dict:
    """Apply ONE update event to pq and measure the signed information gain.

    event: ("eliminate", name) | ("evidence", name, strength).
    delta_h_bits = H_before − H_after (SIGNED, may be negative under
    softening, NEVER clamped). Eliminating the last surviving candidate is
    a no-op (a PQ that settled to one survivor is DONE — further
    elimination events must not crash, spike finding 4.5).
    """
    h_before = pq.entropy()
    kind = event[0]
    if kind == "eliminate":
        nonzero = [p for p in pq.probs.values() if p > 0.0]
        if len(nonzero) <= 1:
            return {"h_before_bits": round(h_before, 6),
                    "h_standing_bits": round(h_before, 6),
                    "delta_h_bits": 0.0}
        pq.update_eliminate(event[1])
    elif kind == "evidence":
        pq.update_evidence(event[1], event[2])
    else:
        raise ValueError(f"unknown event kind {kind!r}")
    h_after = pq.entropy()
    return {"h_before_bits": round(h_before, 6),
            "h_standing_bits": round(h_after, 6),
            "delta_h_bits": round(h_before - h_after, 6)}


# ---------------------------------------------------------------------------
# Piece 3 matcher — assumption split + mechanical contradiction rule
# ---------------------------------------------------------------------------

# Minimal-viable polarity contradiction table (full ATMS is out of scope
# per the issue; same spirit as fact_contradiction_gate's topic-key proxy).
CONTRADICTION_TABLE: dict[str, frozenset[str]] = {
    "static": frozenset({"dynamic"}),
    "dynamic": frozenset({"static"}),
    "synchronous": frozenset({"asynchronous"}),
    "asynchronous": frozenset({"synchronous"}),
}


def split_assumption(entry: str) -> tuple[str, str] | None:
    """'topic=polarity' -> (topic, polarity); anything else -> None (the
    entry can never be semantically invalidated)."""
    s = str(entry or "").strip()
    if "=" not in s:
        return None
    topic, _, polarity = s.partition("=")
    topic, polarity = topic.strip().lower(), polarity.strip().lower()
    if not topic or not polarity:
        return None
    return topic, polarity


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", str(text or "").lower())
            if len(t) >= 3]


def contradicts_assumption(assumption: str, content: str) -> bool:
    """True iff content states the assumption's topic with a CONTRADICTING
    polarity (mechanical proxy: content contains a topic token AND a
    contradicting-polarity token)."""
    parts = split_assumption(assumption)
    if parts is None:
        return False
    topic, polarity = parts
    contra = CONTRADICTION_TABLE.get(polarity, frozenset())
    if not contra:
        return False
    low = str(content or "").lower()
    topic_hit = any(t in low for t in _tokens(topic))
    contra_hit = any(tok in low for pol in contra for tok in _tokens(pol))
    return topic_hit and contra_hit


# ---------------------------------------------------------------------------
# Facts / register readers shared by pieces 3 + 4
# ---------------------------------------------------------------------------

_TERMINAL = frozenset({"PROVEN", "VERIFIED", "NEGATIVE", "REFUTED",
                       "DEFERRED", "STALE", "SUPERSEDED", "DEAD"})


def _read_register(ws: Path) -> list[dict]:
    reg = Path(ws) / "claim-register.yaml"
    if not reg.is_file():
        return []
    try:
        data = yaml.safe_load(reg.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    claims = data.get("claims") if isinstance(data, dict) else None
    return claims if isinstance(claims, list) else []


def _read_facts(ws: Path) -> list[tuple[Path, dict, str]]:
    """[(path, frontmatter, body)] for facts/F*.md (tolerant parse — a
    broken fact degrades to empty frontmatter, never a crash)."""
    from lint_facts import parse_frontmatter
    out: list[tuple[Path, dict, str]] = []
    facts_dir = Path(ws) / "facts"
    if not facts_dir.is_dir():
        return out
    for p in sorted(facts_dir.glob("F*.md")):
        if p.name == "_INDEX.md":
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm, body, _err = parse_frontmatter(text)
        out.append((p, fm or {}, body))
    return out


def _assumptions_of(fm: dict) -> list[str]:
    v = fm.get("assumptions")
    if not isinstance(v, list):
        return []
    return [str(a) for a in v if isinstance(a, str) and a.strip()]


def _resolver_claim(claims: list[dict], topic: str) -> dict | None:
    """The epistemic claim answering a presupposition topic: exact
    answers_question match first, else token-intersection (topic
    'dispatch' matches answers_question 'q_dispatch_mode')."""
    topic_tokens = set(_tokens(topic))
    for c in claims:
        if str(c.get("answers_question") or "").strip() == topic:
            return c
    for c in claims:
        aq_tokens = set(_tokens(c.get("answers_question") or ""))
        if topic_tokens and aq_tokens & topic_tokens:
            return c
    return None


# ---------------------------------------------------------------------------
# Piece 3 face — semantic undermining scan (wired by refutation_propagate)
# ---------------------------------------------------------------------------

def semantic_undermined(ws: Path) -> list[dict]:
    """Facts whose assumptions are contradicted by PROVEN/VERIFIED content.

    Sources: facts at status PROVEN/VERIFIED (title + body) and register
    claims at PROVEN/VERIFIED (title/statement/evidence). A source never
    undermines its own claim (same claim_id). Returns
    [{fact_id, claim_id, assumption, source_id}] — reporting only; the
    MARKING (needs_re-eval on the register claim) is refutation_propagate's
    business (marking only, no cascade, idempotent).
    """
    ws = Path(ws)
    claims = _read_register(ws)
    facts = _read_facts(ws)

    sources: list[tuple[str, str]] = []  # (source_id, content)
    for p, fm, body in facts:
        if str(fm.get("status") or "").upper() in _TERMINAL:
            content = " ".join([str(fm.get("title") or ""), body])
            sources.append((str(fm.get("id") or p.stem), content))
    for c in claims:
        if str(c.get("status") or "").upper() in _TERMINAL:
            content = " ".join([str(c.get(k) or "")
                                for k in ("title", "statement", "evidence")])
            sources.append((str(c.get("id")), content))

    rows: list[dict] = []
    for p, fm, _body in facts:
        cid = str(fm.get("claim_id") or "").strip()
        for assumption in _assumptions_of(fm):
            for source_id, content in sources:
                if cid and source_id == cid:
                    continue  # a claim never undermines itself
                if contradicts_assumption(assumption, content):
                    rows.append({"fact_id": str(fm.get("id") or p.stem),
                                 "claim_id": cid,
                                 "assumption": assumption,
                                 "source_id": source_id})
                    break
    return rows


# ---------------------------------------------------------------------------
# Piece 4 — settle-time coverage annotation (sort-shaped, never blocking)
# ---------------------------------------------------------------------------

def settle_coverage(ws: Path, claim_id: str) -> dict:
    """Whether claim_id's fact assumptions resolve to terminal epistemic
    claims. coverage: 'covered' (all presuppositions addressed — any
    terminal status counts, dead-ends included) | 'uncovered'. The result
    is an ANNOTATION INPUT only: callers must never block on it."""
    ws = Path(ws)
    claims = _read_register(ws)
    presuppositions: list[dict] = []
    unresolved: list[str] = []
    for p, fm, _body in _read_facts(ws):
        if str(fm.get("claim_id") or "").strip() != str(claim_id):
            continue
        for assumption in _assumptions_of(fm):
            parts = split_assumption(assumption)
            if parts is None:
                continue
            topic, polarity = parts
            resolver = _resolver_claim(claims, topic)
            status = str((resolver or {}).get("status") or "").upper()
            addressed = bool(resolver) and status in _TERMINAL
            row = {"assumption": assumption, "topic": topic,
                   "polarity": polarity,
                   "resolver_id": (resolver or {}).get("id"),
                   "resolver_status": status or None,
                   "addressed": addressed}
            presuppositions.append(row)
            if not addressed:
                unresolved.append(
                    topic if resolver else
                    f"{topic} (no epistemic claim answers it)")
    return {"claim_id": str(claim_id),
            "presuppositions": presuppositions,
            "unresolved": sorted(set(unresolved)),
            "coverage": "uncovered" if unresolved else "covered"}


def coverage_note(ws: Path) -> str | None:
    """Settlement-face annotation for a workspace: the terminal claims
    whose fact presuppositions are unresolved. None = nothing to annotate
    (all covered / nothing assumed). Event-log input — never a gate."""
    uncovered: list[str] = []
    for c in _read_register(ws):
        cid = str(c.get("id") or "").strip()
        if not cid or str(c.get("status") or "").upper() not in _TERMINAL:
            continue
        row = settle_coverage(ws, cid)
        if row["coverage"] == "uncovered":
            uncovered.append(
                f"{cid} presupposes {', '.join(row['unresolved'])}")
    if not uncovered:
        return None
    return "epistemic-coverage uncovered: " + "; ".join(uncovered)


# ---------------------------------------------------------------------------
# CLI — the mint face (detect -> derive -> mint -> register append -> seed)
# ---------------------------------------------------------------------------

def _next_free_id_fn(existing: list[dict]):
    used = []
    for c in existing:
        m = re.search(r"C-(\d+)", str(c.get("id") or ""))
        if m:
            used.append(int(m.group(1)))
    base = (max(used) + 1) if used else 1

    def next_id(i: int) -> str:
        return f"C-{base + i:03d}"
    return next_id


def mint_workspace(ws: Path) -> dict:
    """Detect target class -> derive MUST-MASTER unknowns -> mint epistemic
    claims into claim-register.yaml -> seed situational PQs into
    runs/posteriors.yaml. Idempotent end-to-end (mint by pq_id, seed by
    ledger key). Returns a summary dict."""
    ws = Path(ws)
    target_class = detect_target_class(ws)
    unknowns = derive_must_master(target_class, {})
    if not unknowns:
        return {"target_class": target_class, "minted": [], "report": []}
    reg_path = ws / "claim-register.yaml"
    existing: list[dict] = []
    if reg_path.is_file():
        data = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
        existing = data.get("claims") if isinstance(data, dict) else []
        existing = existing if isinstance(existing, list) else []
    task_spec = {}
    ts_path = ws / "task_spec.yaml"
    if ts_path.is_file():
        try:
            task_spec = yaml.safe_load(ts_path.read_text(encoding="utf-8"))
            task_spec = task_spec if isinstance(task_spec, dict) else {}
        except (OSError, yaml.YAMLError):
            task_spec = {}
    minted = mint_epistemic_claims(
        existing, unknowns, _next_free_id_fn(existing))
    # ---- issue 252: unknowns route into hypothesis families at this mint
    # Each unknown joins ONE pq-bound family hypothesis (the issue 662/109
    # binding shapes: body marker pq:<qid>, group pq-<qid> — reused when
    # present, ensured otherwise); the minted epistemic claim IS the arm
    # (stamped with the family linkage, never re-minted, never duplicated
    # as a store candidate string). boundary_type: epistemic is preserved.
    if minted:
        from hypothesis_bridge import (ensure_family, family_group,
                                       find_pq_bound_hypothesis,
                                       HYPOTHESIS_REF)
        from hypothesis_store import HypothesisStore
        store = HypothesisStore(ws / "hypotheses")
        for c in minted:
            qid = str(c.get("answers_question") or "").strip()
            fam = find_pq_bound_hypothesis(store, qid)
            if fam is None:
                fam = ensure_family(
                    ws, marker=f"pq:{qid}", group=f"pq-{qid}",
                    body=(f"Family ledger for situational unknown {qid} "
                          f"(#250) — its epistemic claims are the arms; "
                          f"family state syncs from their settlements "
                          f"(#528) via hypothesis_bridge."))
            c["competitor_group"] = family_group(fam.id)
            c[HYPOTHESIS_REF] = fam.id
    if minted:
        doc = {"claims": list(existing) + minted}
        tmp = reg_path.with_name(reg_path.name + ".tmp")
        tmp.write_text(yaml.safe_dump(doc, allow_unicode=True,
                                      sort_keys=False), encoding="utf-8")
        tmp.replace(reg_path)
    report = seed_situational_pqs(ws, minted, task_spec)
    return {"target_class": target_class, "minted": minted, "report": report}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="plan_epistemics — mint situational unknowns as "
                    "epistemic claims and seed their PQs (issue 250)")
    ap.add_argument("--mint", metavar="WORKSPACE",
                    help="derive + mint + seed for this workspace")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable output")
    a = ap.parse_args(argv)
    if a.mint:
        summary = mint_workspace(a.mint)
        if a.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print(f"target_class: {summary['target_class']}")
            for c in summary["minted"]:
                print(f"MINTED: {c['id']} epistemic "
                      f"answers_question={c['answers_question']} "
                      f"h_standing_bits={c['h_standing_bits']}")
            for r in summary["report"]:
                print(f"SEEDED: pq {r['pq_id']} "
                      f"H={r['h_standing_bits']} bit (source={r['source']})")
            if not summary["minted"]:
                print("OK: nothing to mint (idempotent or no target class)")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
