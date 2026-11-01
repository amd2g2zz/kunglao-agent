#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verdict_scorer.py — deterministic PQ-coverage scorer (owner ruling:
the verdict-scorer LLM judgment surface sinks to this script).

The verdict-scorer LLM judgment surface sinks to this script: scoring is
pure mechanical matching over the same inputs the agent read —

  task_spec.yaml  primary_questions[] (canonical parse: convergence_check)
  claim-register.yaml  claims[] with answers_question + status
  facts/_INDEX.md      F<id> | <status> | <claim_id> | <conclusion> rows
  facts/*.md           frontmatter confidence_band (C0a/C0b bands)
  evidence/replay-*.json   controlled-comparison artifacts (reproduction)

Ruling faces (mirrors the retired agent contract, schema v11):

  STEP 1  answering claim = claim with answers_question == <qid>
  STEP 2  C0a: claim PROVEN + linked fact PROVEN + band PROVEN-FULL.
          C0b (need: model_selection): one candidate terminal PROVEN,
          remaining candidates REFUTED/DEFERRED. yes_no_with_evidence
          accepts ONLY PROVEN answers here (stricter than convergence's
          terminal set — VERIFIED/NEGATIVE/REFUTED are refused by the
          status gate); a PROVEN answer still owes the C0a band. PARTIAL
          never answers. The adversarial gate stays ORCHESTRATOR-SIDE:
          scoring here does not sign — a claim with open adversarial
          challenges is gated at signing by the orchestrator (the HMAC
          key lives only in orchestrator process context), never by
          this script.
  STEP 2b reproduction: true questions are NOT satisfiable by status —
          the PROVEN answering claim needs evidence/replay-*.json with
          >= 1 byte-matched pair (replay_equivalence is the checker;
          never reimplemented here).
  STEP 3  verdict build: complete / correct / per-PQ entries /
          unresolved[] / degraded[] (fail-closed honesty).
  STEP 4  contradictions: fact_contradiction_gate.scan_conflicts output
          consumed read-only — each conflict lands in contradictions[]
          and forces correct=false.

"Never more lenient than convergence": satisfaction semantics are
convergence_check's OWN parse faces, imported — not reimplemented.

Fail-closed: missing task_spec / claim-register / malformed
primary_questions → exit 2, NO verdict file written (the agent's
"status: blocked" residue is a named non-zero exit).

Output: <ws>/evidence/verdict.json (analysis_verdict schema v11).
Re-running over identical inputs is byte-identical (deterministic; the
only clock face is _meta.queried_at).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import convergence_check
import fact_contradiction_gate
import replay_equivalence
from kunglao_log import warn  # canonical warn: ONE implementation, dedupe

SCHEMA_VERSION = "v11"
SOURCE = "verdict-scorer"

# C0b candidate closure: candidates that are neither PROVEN nor in this
# set are recorded as degradation (OPEN/PARTIAL left behind).
_C0B_CLOSED = {"REFUTED", "DEFERRED"}

SEP = " | "


def _load_yaml(p: Path) -> dict:
    import yaml  # local import: soft dependency, mirrors other CLIs
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}


def _index_rows(facts_dir: Path) -> List[dict]:
    """facts/_INDEX.md rows: F<id> | <status> | <claim_id> | <conclusion>."""
    path = facts_dir / "_INDEX.md"
    if not path.exists():
        return []
    rows: List[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = [p.strip() for p in s.split(SEP)]
        if len(parts) >= 3 and parts[0].startswith("F"):
            rows.append({"fact_id": parts[0], "status": parts[1].upper(),
                         "claim_id": parts[2]})
    return rows


def _fact_band(facts_dir: Path, fact_id: str) -> str:
    """Tolerant frontmatter confidence_band read (line-level `key: value`
    + YAML-block fallback; the band is a flat scalar). Missing/unreadable
    → "" (never a band — C0a fails closed)."""
    f = facts_dir / f"{fact_id}.md"
    if not f.exists():
        return ""
    text = f.read_text(encoding="utf-8", errors="replace")
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover — soft dependency
        warn("verdict_yaml_soft_dep", f"{type(exc).__name__}: {exc}")
        yaml = None
    if yaml is not None:
        for block in _yaml_blocks(text):
            try:
                parsed = yaml.safe_load(block) or {}
            except yaml.YAMLError as exc:
                # corrupt YAML block -> fall through to the line-level scan
                warn("verdict_band_yaml", f"{type(exc).__name__}: {exc}")
                continue
            if isinstance(parsed, dict) and parsed.get("confidence_band"):
                return str(parsed["confidence_band"]).strip()
    for line in text.splitlines():
        if line.lstrip().startswith("confidence_band:"):
            return line.split(":", 1)[1].split("#", 1)[0].strip()
    return ""


def _yaml_blocks(text: str) -> List[str]:
    import re
    return re.findall(r"```yaml\s*(.*?)```", text, re.DOTALL)


def _frontmatter_fm(text: str) -> str:
    """The `---` frontmatter block body, if present."""
    if not text.lstrip().startswith("---"):
        return ""
    parts = text.split("---", 2)
    return parts[1] if len(parts) >= 3 else ""


def _fact_fm_status_band(facts_dir: Path, fact_id: str) -> Tuple[str, str]:
    """(status, confidence_band) from the fact file's `---` frontmatter,
    falling back to the fenced YAML block, then to the _INDEX status."""
    f = facts_dir / f"{fact_id}.md"
    fm_text = f.read_text(encoding="utf-8", errors="replace") if f.exists() else ""
    fm = _frontmatter_fm(fm_text)
    status, band = "", ""
    for line in fm.splitlines():
        s = line.strip()
        if s.startswith("status:"):
            status = s.split(":", 1)[1].split("#", 1)[0].strip()
        elif s.startswith("confidence_band:"):
            band = s.split(":", 1)[1].split("#", 1)[0].strip()
    if not (status or band):
        band = _fact_band(facts_dir, fact_id)
    return status.upper(), band


def _facts_for_claim(rows: List[dict], claim_id: str) -> List[dict]:
    return [r for r in rows if r.get("claim_id") == claim_id]


def _conflict_pairs(facts_dir: Path) -> List[str]:
    """STEP 4 source: fact_contradiction_gate conflicts as verdict rows.
    Read-only consumer — detection is never reimplemented here."""
    index_path = facts_dir / "_INDEX.md"
    if not index_path.exists():
        return []
    return [
        f"{c['fact_a']} <-> {c['fact_b']} (claims {c['claim_a']}/"
        f"{c['claim_b']}) same-topic PROVEN contradiction, no supersedes"
        for c in fact_contradiction_gate.scan_conflicts(index_path, facts_dir)
    ]


def _c0a_ok(fact_rows: List[dict], facts_dir: Path) -> Tuple[bool, str]:
    """PROVEN fact + PROVEN-FULL band, or the named failure."""
    if not fact_rows:
        return False, "claim links no fact in facts/_INDEX.md"
    proven = [r for r in fact_rows if r["status"] == "PROVEN"]
    if not proven:
        statuses = ", ".join(sorted({r["status"] for r in fact_rows}))
        return False, f"answering fact status not PROVEN ({statuses})"
    for r in proven:
        _, band = _fact_fm_status_band(facts_dir, r["fact_id"])
        if band == "PROVEN-FULL":
            return True, ""
    return False, "confidence_band not PROVEN-FULL (C0a)"


def _status_gate(
    need: Optional[str],
    answering: List[dict],
    rows: List[dict],
    facts_dir: Path,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """STEP 2 status/band gate. Returns (cited_fact, band, gap); gap None
    = satisfied. C0a (default) / C0b (model_selection) — PARTIAL never
    answers; C0b's terminal-PROVEN is the only relaxation. Mirrors
    convergence — never more lenient."""
    proven_claims = [c for c in answering
                     if str(c.get("status") or "").upper() == "PROVEN"]
    if not proven_claims:
        statuses = ", ".join(sorted(
            {str(c.get("status") or "UNKNOWN").upper() for c in answering}))
        return None, None, f"answering claim status not PROVEN ({statuses})"
    gap: Optional[str] = "no PROVEN answering claim"
    for c in proven_claims:
        cid = str(c.get("id") or "")
        fact_rows = _facts_for_claim(rows, cid)
        if need == "model_selection":
            # C0b: one terminal PROVEN candidate; remaining candidates
            # closed (REFUTED/DEFERRED) — OPEN/PARTIAL left behind fails.
            open_candidates = sorted(
                str(o.get("id")) for o in answering
                if o is not c and str(o.get("status") or "").upper()
                not in _C0B_CLOSED | {"PROVEN"})
            ok, why = _c0a_ok(fact_rows, facts_dir)
            if ok and open_candidates:
                ok, why = False, ("C0b candidates left OPEN/PARTIAL: "
                                  + ", ".join(open_candidates))
        else:
            ok, why = _c0a_ok(fact_rows, facts_dir)
        if ok:
            cited = fact_rows[0]["fact_id"] if fact_rows else None
            band = None
            if cited:
                _, band = _fact_fm_status_band(facts_dir, cited)
            return cited, band, None
        gap = why
    return None, None, gap


def _reproduction_gate(
    ws: Path,
    answering: List[dict],
    repro_qids: set,
) -> Optional[str]:
    """STEP 2b: a reproduction: true question is never answered by
    status alone — the PROVEN answering claim owes a controlled-
    comparison artifact with matched pairs. None = satisfied."""
    proven_claims = [c for c in answering
                     if str(c.get("status") or "").upper() == "PROVEN"]
    reason = replay_equivalence.NO_RUN_NOT_EVIDENCE
    for c in proven_claims:
        try:
            ok, reason = replay_equivalence.equivalence_verdict(
                ws, c, repro_qids=repro_qids)
        except (OSError, ValueError) as exc:
            ok, reason = False, f"face check unavailable ({exc})"
        if ok:
            return None
    return ("ran without error is NOT evidence of equivalence — "
            f"{reason}")


def score_workspace(ws: Path) -> Tuple[Optional[dict], str]:
    """Score one workspace. Returns (verdict_doc|None, error).

    None verdict = fail-closed input problem (error names it); no
    evidence/verdict.json is written in that case.
    """
    task_spec = convergence_check._load_task_spec(ws)
    pqs, pq_err = convergence_check._parse_primary_questions(task_spec)
    if pq_err:
        return None, f"task_spec primary_questions malformed: {pq_err}"
    reg = _load_yaml(ws / "claim-register.yaml")
    claims = reg.get("claims") or []
    if not task_spec and not reg:
        return None, "no task_spec.yaml and no claim-register.yaml (blocked)"
    facts_dir = ws / "facts"
    rows = _index_rows(facts_dir)
    repro_qids = replay_equivalence.declared_reproduction_qids(task_spec)
    conflict_pairs = _conflict_pairs(facts_dir)

    pq_entries: List[dict] = []
    unresolved: List[str] = []
    degraded: List[dict] = []

    for qid, need in pqs:
        gap = None
        cited_fact = None
        band_out = None
        answering = [c for c in claims
                     if str(c.get("answers_question") or "") == qid]
        if not answering:
            gap = "no answering claim"
        else:
            cited_fact, band_out, gap = _status_gate(
                need, answering, rows, facts_dir)
            if gap is None and qid in repro_qids:
                gap = _reproduction_gate(ws, answering, repro_qids)
        answered = gap is None
        if not answered:
            unresolved.append(qid)
        pq_entries.append({
            "id": qid,
            "answered": answered,
            "cited_fact": cited_fact,
            "confidence_band": band_out,
            "gap": gap,
        })

    complete = bool(pq_entries) and all(e["answered"] for e in pq_entries)
    correct = not conflict_pairs
    if conflict_pairs:
        degraded.append({
            "reason": f"{len(conflict_pairs)} same-topic PROVEN "
                      "contradiction(s) reported by fact_contradiction_gate",
            "affected_question": None,
        })
    if unresolved:
        degraded.append({
            "reason": f"{len(unresolved)} primary question(s) unresolved: "
                      + ", ".join(unresolved),
            "affected_question": None,
        })
    if complete and not degraded:
        strength = "strong"
    elif not complete:
        strength = "weak"
    else:
        strength = "mixed"

    verdict = {
        "_meta": {
            "source": SOURCE,
            "schema_version": SCHEMA_VERSION,
            "queried_at": datetime.now(timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            "methodology": "task_spec.primary_questions coverage "
                           "+ fact-citation validity (deterministic)",
        },
        "sample_sha256": str(task_spec.get("sample_sha256") or ""),
        "analysis_verdict": {
            "complete": complete,
            "correct": correct,
            "primary_questions": pq_entries,
            "unresolved": unresolved,
            "contradictions": conflict_pairs,
            "degraded": degraded,
        },
        "self_audit": {
            "evidence_strength": strength,
            "ignored_evidence": [],
            "open_questions": list(unresolved),
        },
    }
    return verdict, ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="verdict_scorer — deterministic PQ-coverage verdict "
                    "(analysis_verdict schema v11)")
    ap.add_argument("workspace", type=Path, help="workspace root")
    ap.add_argument("--output", type=Path, default=None,
                    help="verdict path (default <ws>/evidence/verdict.json)")
    ap.add_argument("--stdout", action="store_true",
                    help="print the verdict JSON instead of writing")
    args = ap.parse_args(argv)
    ws = args.workspace
    verdict, err = score_workspace(ws)
    if verdict is None:
        print(f"BLOCKED: {err}", file=sys.stderr)
        return 2
    payload = json.dumps(verdict, ensure_ascii=False, indent=2)
    if args.stdout:
        print(payload)
        return 0
    out = args.output or (ws / "evidence" / "verdict.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload + "\n", encoding="utf-8")
    av = verdict["analysis_verdict"]
    print(f"verdict written: {out} (complete={av['complete']} "
          f"correct={av['correct']} unresolved={len(av['unresolved'])})")
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
