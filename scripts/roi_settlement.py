#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""roi_settlement.py — #49 dispatch intent contract + entropy-gain admission gate.

Owner rulings implemented here (v0.1.5 value-loop core, settlement + data
layer ONLY — Thompson sampling / posterior wiring stays v0.2 #50/#59):

- Ruling 1 (value = method x context x outcome): the settlement row records
  the full triple (``intent`` carries method + context_tags + uncertainty;
  ``outcome`` carries what came back). No method is ever labeled low-value on
  its own — value is always method-in-context-with-outcome.
- Ruling 2 (outcome judged ONLY against the declared intent): zero output is
  never a negative ROI by itself — early recon dispatched with intent "map
  the territory" is POSITIVE once a map artifact exists, even with a zero
  fact delta. Fact counts are NEVER a settlement signal.
- Ruling 3 (entropy-gain admission gate): action value = uncertainty
  eliminated, NOT fact count. An intent that cannot name WHICH uncertainty it
  eliminates is non-compliant: record_intent() returns
  ``{"ok": False, "reason": MISSING_UNCERTAINTY}`` and writes nothing.
  THIS PR EXPOSES THE GATE AS A DATA CHANNEL ONLY — wiring enforcement into
  dispatch_gate is explicitly out of scope for #49; the caller decides to
  reject the dispatch or proceed unbanked.

Files (workspace-relative JSONL, tolerant readers — junk lines are skipped):
  runs/roi-intents.jsonl      — one record per dispatch intent
  runs/roi-settlements.jsonl  — one row per settled outcome

Intent idempotency: keyed by claim + the DECLARED intent content (method,
tags, uncertainty, expected_artifact). Re-recording an identical declaration
is a no-op that keeps the FIRST ts; a corrected re-declaration lands as a new
record and the latest declaration wins at settlement time.

Uncertainty-elimination heuristic (deliberately SIMPLE, ruling 3):
  signals = any of
    S1 verdict_win        — outcome verdict in VERDICT_WINS (passes/CONFIRMED)
    S2 hypotheses_resolved — outcome["hypotheses_resolved"] > 0
    S3 claims_closed      — outcome["claims_closed"] > 0
    S4 artifact_match     — intent.expected_artifact token matches any entry
                            of outcome["artifacts"] (case-insensitive substring)
  uncertainty_eliminated = bool(signals); intent_met = True if signals, False
  on a losing verdict (fails/REFUTED), None otherwise. roi_class:
    POSITIVE   — intent_met (the named uncertainty was eliminated)
    NEGATIVE   — losing verdict and nothing eliminated
    NEUTRAL    — middling verdict (partial/UNVERIFIED*) with no signal
    UNRESOLVED — nothing comparable observed yet (never a NEGATIVE: ruling 2)

settle_intent is fail-open by contract: outcome_capture wiring (same PR)
treats every settlement failure as a no-op so capture never breaks.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from kunglao_log import iter_jsonl  # #863 Family K single source
from harness_common import utc_now_iso  # #863 Family F: single source

INTENTS_REL = "runs/roi-intents.jsonl"
SETTLEMENTS_REL = "runs/roi-settlements.jsonl"

# Ruling 3 gate reason (frozen token — callers key dispatch decisions on it).
MISSING_UNCERTAINTY = "MISSING_UNCERTAINTY"
NO_INTENT = "NO_INTENT"

ROI_POSITIVE = "POSITIVE"
ROI_NEUTRAL = "NEUTRAL"
ROI_NEGATIVE = "NEGATIVE"
ROI_UNRESOLVED = "UNRESOLVED"

# Settlement verdict vocabulary — the union of the verify-note and red-team
# result values outcome_capture already extracts (RESULT_SCORE faces).
VERDICT_WINS = frozenset({"passes", "confirmed"})
VERDICT_LOSSES = frozenset({"fails", "refuted"})
VERDICT_MIDDLES = frozenset({"partial", "unverified", "unverified-with-gap"})


def intents_path(ws: Path) -> Path:
    return Path(ws) / INTENTS_REL


def settlements_path(ws: Path) -> Path:
    return Path(ws) / SETTLEMENTS_REL


def _read_rows(p: Path) -> list[dict]:
    """Tolerant JSONL read: blank / malformed lines are skipped."""
    if not p.exists():
        return []
    return [row for row in iter_jsonl(
        p.read_text(encoding="utf-8", errors="replace").splitlines())
        if isinstance(row, dict)]


def read_intents(ws: Path) -> list[dict]:
    return _read_rows(intents_path(ws))


def read_settlements(ws: Path) -> list[dict]:
    return _read_rows(settlements_path(ws))


def _append(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _intent_key(claim_id: str, method: str, context_tags: list,
                uncertainty: str, expected_artifact: str) -> str:
    """Idempotency key: claim + declared intent content (see module doc)."""
    payload = {"claim_id": claim_id, "method": method,
               "context_tags": list(context_tags),
               "uncertainty": uncertainty,
               "expected_artifact": expected_artifact}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_intent(ws: Path, claim_id: str, method: str, context_tags: list,
                  uncertainty: str, expected_artifact: str) -> dict:
    """Record a dispatch intent (ruling 3 gate at the data channel).

    Returns ``{"ok": False, "reason": MISSING_UNCERTAINTY}`` when the intent
    cannot name its uncertainty — the CALLER decides to reject the dispatch
    or proceed unbanked (enforcement wiring stays out of #49 scope). A valid
    intent is appended idempotently; ``duplicate`` is True when the identical
    declaration was already recorded.
    """
    if not (uncertainty and str(uncertainty).strip()):
        return {"ok": False, "reason": MISSING_UNCERTAINTY}
    tags = [str(t) for t in (context_tags or [])]
    method_s = str(method)
    unc_s = str(uncertainty)
    art_s = str(expected_artifact or "")
    key = _intent_key(claim_id, method_s, tags, unc_s, art_s)
    existing = read_intents(ws)
    for rec in existing:
        if rec.get("intent_key") == key:
            return {"ok": True, "duplicate": True, "record": rec,
                    "path": intents_path(ws)}
    rec = {"intent_key": key, "ts": utc_now_iso(), "claim_id": claim_id,
           "method": method_s, "context_tags": tags, "uncertainty": unc_s,
           "expected_artifact": art_s}
    _append(intents_path(ws), rec)
    return {"ok": True, "duplicate": False, "record": rec,
            "path": intents_path(ws)}


def has_intent(ws: Path, claim_id: str) -> bool:
    """True when any dispatch intent exists for claim_id (wiring pre-check)."""
    return any(r.get("claim_id") == claim_id for r in read_intents(ws))


def _num(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _elimination_signals(intent: dict, outcome: dict) -> list[str]:
    """Ruling 3 heuristic (see module docstring). Fact counts are NOT
    consulted — "0 facts" is not a signal, a big fact delta is not either."""
    signals: list[str] = []
    verdict = str(outcome.get("verdict") or "").strip().lower()
    if verdict in VERDICT_WINS:
        signals.append("verdict_win")
    if _num(outcome.get("hypotheses_resolved")) > 0:
        signals.append("hypotheses_resolved")
    if _num(outcome.get("claims_closed")) > 0:
        signals.append("claims_closed")
    expected = str(intent.get("expected_artifact") or "").strip().lower()
    if expected:
        for artifact in (outcome.get("artifacts") or ()):
            if expected in str(artifact).lower():
                signals.append("artifact_match")
                break
    return signals


def _classify(signals: list[str], outcome: dict) -> tuple[bool | None, str]:
    """intent_met + roi_class from the signal list (see module docstring)."""
    if signals:
        return True, ROI_POSITIVE
    verdict = str(outcome.get("verdict") or "").strip().lower()
    if verdict in VERDICT_LOSSES:
        return False, ROI_NEGATIVE
    if verdict in VERDICT_MIDDLES:
        return None, ROI_NEUTRAL
    return None, ROI_UNRESOLVED


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def settle_intent(ws: Path, claim_id: str, outcome_observed: dict) -> dict:
    """Compute + persist the outcome-vs-intent attribution for claim_id.

    outcome_observed accepts (all optional): ``verdict`` (verify-note /
    red-team result value), ``artifacts`` (paths/names — matched against the
    intent's expected_artifact token), ``hypotheses_resolved``,
    ``claims_closed``, plus free-form provenance (``checker``, ``ts``, ...).
    Returns {"ok": False, "reason": NO_INTENT} when the claim never declared
    one (fail-open callers skip). Settlement is idempotent per
    (claim, outcome) pair; an evolving verdict settles again as a new row.
    """
    outcome = dict(outcome_observed or {})
    declared = [r for r in read_intents(ws) if r.get("claim_id") == claim_id]
    if not declared:
        return {"ok": False, "reason": NO_INTENT}
    intent = declared[-1]  # latest declaration wins (corrected intents)
    signals = _elimination_signals(intent, outcome)
    intent_met, roi_class = _classify(signals, outcome)
    settle_id = hashlib.sha256("\0".join(
        [claim_id, str(intent.get("intent_key")), _canonical(outcome)])
        .encode("utf-8")).hexdigest()
    for row in read_settlements(ws):
        if row.get("settle_id") == settle_id:
            return {"ok": True, "duplicate": True, "settlement": row,
                    "path": settlements_path(ws)}
    row = {"settle_id": settle_id, "ts": utc_now_iso(), "claim_id": claim_id,
           "intent": {"method": intent.get("method"),
                      "context_tags": intent.get("context_tags", []),
                      "uncertainty": intent.get("uncertainty"),
                      "expected_artifact": intent.get("expected_artifact"),
                      "ts": intent.get("ts")},
           "intent_met": intent_met,
           "uncertainty_eliminated": bool(signals),
           "signals": signals,
           "roi_class": roi_class,
           "outcome": outcome}
    _append(settlements_path(ws), row)
    return {"ok": True, "duplicate": False, "settlement": row,
            "path": settlements_path(ws)}


def main(argv: list[str] | None = None) -> int:
    """CLI: read faces over the two ledger files.

    python roi_settlement.py <ws> intents|settlements [--json]
    """
    import argparse
    ap = argparse.ArgumentParser(
        prog="roi_settlement.py",
        description="#49 dispatch intent ledger + outcome-vs-intent settlement")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("face", choices=["intents", "settlements"])
    ap.add_argument("--json", action="store_true", help="machine-readable")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    rows = read_intents(ws) if args.face == "intents" else read_settlements(ws)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print(f"{len(rows)} {args.face} row(s) under {ws / 'runs'}")
        for r in rows:
            if args.face == "intents":
                print(f"  {r.get('ts')} {r.get('claim_id')} method="
                      f"{r.get('method')} eliminates: {r.get('uncertainty')}")
            else:
                print(f"  {r.get('ts')} {r.get('claim_id')} "
                      f"{r.get('roi_class')} signals={r.get('signals')}")
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
