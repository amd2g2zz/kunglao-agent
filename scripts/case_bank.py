#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""case_bank.py — #49 case bank data layer: symmetric outcome collection +
failures-first retrieval (v0.1.5 value-loop, settlement + data layer ONLY).

Owner ruling 4 (this module's whole contract):
- SYMMETRIC COLLECTION: failures are banked like successes, but only WITH
  their attribution (+ optional premise_correction). A NEGATIVE entry without
  attribution raises CaseBankError — no silent banking of unattributed
  failures.
- COUNTEREXAMPLE PRUNING > POSITIVE REUSE: retrieve() returns matching
  entries with FAILURES FIRST, newest first within each class.
- #127: the old emit_case_hints dispatch-context face (<case-hints>
  wrapper) is DELETED — it had zero callers (hypothesis_seeder retrieves
  via case_bank.retrieve directly; the only emit_case_hints callers were
  this module's own CLI and its tests). Per the no-backcompat policy the
  half-utilized "wired-but-unread" face ends: the bank's read face is
  retrieve(), its consumers are the hypothesis seeder and this CLI. The
  <case-hints> tag stays RESERVED in references/xml-injection-standard.md
  for a future dispatch-face producer with an actual consumer contract.

Schema (runs/case-bank.jsonl, one JSON object per line):
  {ts, claim_id, method, context_tags, intent_uncertainty, outcome_observed,
   roi_class, attribution, premise_correction, how}
  - ts / claim_id / method / roi_class: required (ts filled on append).
  - attribution: required non-empty IFF roi_class == NEGATIVE (ruling 4).
  - premise_correction: optional.
  - how (#146): OPTIONAL structured forensics block (the outcome's
    mechanism: mismatch_class / mechanism note) — a mapping when present,
    refused otherwise (free text is a label, not a lesson); NEVER
    required: banked rows predating #146 read back with how=None.
  - context_tags: normalized to list[str]; intent_uncertainty: the named
    uncertainty from the dispatch intent (roi_settlement gate, ruling 3).
  - roi_class: roi_settlement's four classes (POSITIVE/NEUTRAL/NEGATIVE/
    UNRESOLVED) — value is always method-in-context-with-outcome (ruling 1);
    the bank stores the triple, never a per-method value label.

Retrieval: tag-INTERSECTION match (empty query tags -> all entries), then
sort key (0 for NEGATIVE else 1, -file-position). File position is append
order, so -position is newest-first — deterministic, no clock parsing.

This is the DATA LAYER only: who appends entries at settle time (and any
Thompson sampling over them) is v0.2 #50/#59.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from kunglao_log import iter_jsonl  # #863 Family K single source
from harness_common import utc_now_iso  # #863 Family F: single source

BANK_REL = "runs/case-bank.jsonl"

ROI_CLASSES = ("POSITIVE", "NEUTRAL", "NEGATIVE", "UNRESOLVED")
ROI_NEGATIVE = "NEGATIVE"

REQUIRED_FIELDS = ("claim_id", "method", "roi_class")


class CaseBankError(ValueError):
    """Banking contract violation (ruling 4: unattributed failure, missing
    required field, unknown roi_class). Callers must NOT swallow it — a
    refusal is the feature."""


def bank_path(ws: Path) -> Path:
    return Path(ws) / BANK_REL


def read_entries(ws: Path) -> list[dict]:
    """Tolerant read: blank / malformed lines are skipped (never crash)."""
    p = bank_path(ws)
    if not p.exists():
        return []
    return [row for row in iter_jsonl(
        p.read_text(encoding="utf-8", errors="replace").splitlines())
        if isinstance(row, dict)]


def append(ws: Path, entry: dict) -> dict:
    """Validate + append one case entry; returns the stored record.

    Ruling-4 lint rule: roi_class == NEGATIVE requires a non-empty
    attribution — CaseBankError otherwise, nothing written (no silent
    banking). Missing required fields / unknown roi_class also raise.
    """
    e = dict(entry or {})
    missing = [f for f in REQUIRED_FIELDS
               if not str(e.get(f) or "").strip()]
    if missing:
        raise CaseBankError(
            f"case-bank entry missing required field(s): {', '.join(missing)}")
    roi_class = str(e["roi_class"]).strip()
    if roi_class not in ROI_CLASSES:
        raise CaseBankError(
            f"unknown roi_class {roi_class!r} (allowed: {', '.join(ROI_CLASSES)})")
    attribution = str(e.get("attribution") or "").strip()
    if roi_class == ROI_NEGATIVE and not attribution:
        raise CaseBankError(
            f"NEGATIVE case for {e['claim_id']} refused: no attribution — "
            f"failures are banked only WITH attribution (ruling 4, no "
            f"silent banking)")
    tags = e.get("context_tags")
    if isinstance(tags, str):
        tags = [tags]
    # #146: `how` is the structured forensics block — a mapping when
    # present, refused otherwise (free text is a label, not a lesson);
    # absent stays absent (back-compat with banked rows).
    how = e.get("how")
    if how is not None and not isinstance(how, dict):
        raise CaseBankError(
            f"case-bank entry for {e['claim_id']} refused: `how` must be a "
            f"structured mapping (mismatch_class / mechanism), not "
            f"{type(how).__name__} — a label is not a lesson (#146)")
    stored = {
        "ts": str(e.get("ts") or utc_now_iso()),
        "claim_id": str(e["claim_id"]),
        "method": str(e["method"]),
        "context_tags": [str(t) for t in (tags or [])],
        "intent_uncertainty": str(e.get("intent_uncertainty") or ""),
        "outcome_observed": e.get("outcome_observed")
        if isinstance(e.get("outcome_observed"), dict) else {},
        "roi_class": roi_class,
        "attribution": attribution or None,
        "premise_correction": str(e.get("premise_correction") or "").strip()
        or None,
        "how": dict(how) if isinstance(how, dict) else None,
    }
    p = bank_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(stored, ensure_ascii=False) + "\n")
    return stored


def append_once(ws: Path, entry: dict) -> dict:
    """Idempotent append keyed on (claim_id, action signature, roi_class).

    #110 keyed the middle axis on the free-text method; #126 upgrades it to
    the action signature (oracle_runner.action_channel): the same action
    under two tool names (device-trace via frida-stalker vs ida-server —
    one observation channel) banks ONCE, so a tool-name variant can no
    longer displace other failures-first lessons from the top-5 retrieval
    window. A DIFFERENT observation channel (emulator vs device) still
    banks separately: cross-channel divergence is itself an observation.

    Validation is NOT bypassed: the ruling-4 lint (unattributed NEGATIVE)
    and the required-field checks still raise CaseBankError — dedup only
    short-circuits the WRITE, never the contract.

    Returns {"ok": True, "duplicate": bool, "record": <stored or found>}.
    """
    e = entry or {}
    from oracle_runner import action_channel  # #126 signature axis (lazy:
    # keeps case_bank's import graph unchanged for its read/CLI faces)
    key = (str(e.get("claim_id") or ""), action_channel(e.get("method")),
           str(e.get("roi_class") or ""))
    for existing in read_entries(ws):
        if (str(existing.get("claim_id") or ""),
                action_channel(existing.get("method")),
                str(existing.get("roi_class") or "")) == key:
            return {"ok": True, "duplicate": True, "record": existing}
    record = append(ws, e)
    return {"ok": True, "duplicate": False, "record": record}


def retrieve(ws: Path, context_tags: list, limit: int = 5) -> list[dict]:
    """Matching entries, FAILURES FIRST then positives, newest first.

    Matching = tag intersection (any of the query tags present in the
    entry's context_tags); an empty query matches everything. Order is
    (NEGATIVE rank, -append-position): append order is recency, so
    -position is newest-first without clock parsing. limit applies AFTER
    ordering, so the top slice always leads with failures.
    """
    wanted = {str(t) for t in (context_tags or [])}
    matched = [e for e in read_entries(ws)
               if not wanted or wanted & {str(t) for t in
                                          (e.get("context_tags") or [])}]
    ranked = sorted(
        enumerate(matched),
        key=lambda pair: (0 if pair[1].get("roi_class") == ROI_NEGATIVE
                          else 1, -pair[0]))
    return [e for _, e in ranked[:max(int(limit), 0)]]


def _hint_line(entry: dict) -> str:
    """One human-readable line; failures carry attribution + correction;
    the #146 `how` block surfaces its mechanism when present."""
    tags = ",".join(entry.get("context_tags") or [])
    head = (f"[{entry.get('roi_class')}] {entry.get('claim_id')} "
            f"method={entry.get('method')} tags={tags}")
    parts = [head]
    if entry.get("intent_uncertainty"):
        parts.append(f"uncertainty: {entry['intent_uncertainty']}")
    if entry.get("attribution"):
        parts.append(f"attribution: {entry['attribution']}")
    if entry.get("premise_correction"):
        parts.append(f"correction: {entry['premise_correction']}")
    how = entry.get("how")
    if isinstance(how, dict):
        mcls = str(how.get("mismatch_class") or "").strip()
        mech = str(how.get("mechanism") or "").strip()
        if mcls or mech:
            parts.append(f"how: {mcls}{': ' + mech if mech else ''}")
    return " | ".join(parts)


def main(argv: list[str] | None = None) -> int:
    """CLI: python case_bank.py <ws> retrieve --tags a,b --limit 3 [--json]"""
    ap = argparse.ArgumentParser(
        prog="case_bank.py",
        description="#49 case bank — failures-first retrieval over "
                    "runs/case-bank.jsonl")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("face", choices=["retrieve"], help="read face")
    ap.add_argument("--tags", default="",
                    help="comma-separated context tags (empty = all)")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--json", action="store_true", help="machine-readable")
    args = ap.parse_args(argv)
    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    entries = retrieve(Path(args.workspace), tags, args.limit)
    if args.json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
    else:
        # #127: plain lines (the <case-hints> wrapper face was deleted —
        # zero consumers); ordering contract unchanged (failures first).
        if not entries:
            print("case-bank: no matching entries")
        else:
            n_fail = sum(1 for e in entries
                         if e.get("roi_class") == ROI_NEGATIVE)
            print(f"case-bank: {len(entries)} past run(s)"
                  + (f", {n_fail} failure(s) FIRST (counterexample pruning)"
                     if n_fail else ""))
            for e in entries:
                print(_hint_line(e))
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
