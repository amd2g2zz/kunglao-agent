#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""policy_state.py — the policy-state projection (issue #769).

The planner's decision receipt (#760; landed per dispatch by the gate at
``runs/plan-receipts.jsonl``) lived in ledger files only — the operator
watching a session could not see the candidate set, the admitted 1..k
set, or which action is executing. This module projects the LATEST
receipt into ONE compact file, ``runs/policy-state.json`` (schema
``policy-state/1``):

    {schema, round, ts, claim, receipt_ts, candidates, admitted,
     chosen, posterior}

  - candidates: the sampled projection per candidate key
    {action_kind, cost, ratio, theta, alpha, beta} — the Thompson draw
    and the posterior cell it came from, exactly as the receipt carried
    (single source: this module NEVER re-samples; a projection over the
    same receipts, not a second decision).
  - admitted / chosen: the receipt's own words.
  - posterior: the per-action-kind Thompson cell summary
    ({alpha, beta} — the exploration-vs-exploitation shape) plus the
    decision's state_signature.
  - round: priority_ratio.round_index(ws) — the machine-independent
    round axis (raw snapshot-row count), never a wall clock.
  - ts: the projection's write time (the receipt keeps its own
    receipt_ts).

Producers/consumers:

  - WRITTEN by hooks/round_closure (the round-closure kernel face — the
    compose face's sibling cage), so every round close refreshes the
    projection; a receipt-less workspace writes NOTHING (the
    policy-state-fresh liveness fingerprint treats absence as the
    failure — a decorative face is the failure mode).
  - READ by scripts/statusline_snapshot (the ``policy`` display face —
    the renderer stays a dumb view) and by humans tailing runs/.

Discipline: atomic write (tmp + replace, heartbeat_touch F2); dedup on
the receipt identity (an unchanged receipt re-writes nothing — compose's
content-hash posture); fail-open reads (a corrupt file reads as None);
one controlled-vocabulary ledger row per write (EMIT word
``policy_state_projected``, scripts/event_taxonomy.py).

Usage: python policy_state.py <workspace>   # project + print one line
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "policy-state/1"
REL = "runs" / Path("policy-state.json")
RECEIPTS_REL = "runs" / Path("plan-receipts.jsonl")

from kunglao_log import warn  # canonical warn: ONE implementation


# ------------------------------------------------------------- receipt read

def last_receipt(ws: Path) -> dict | None:
    """The newest plan-receipt/1 row (file order = dispatch order; the
    gate appends). Absent ledger / corrupt tail -> None (fail-open)."""
    path = Path(ws) / RECEIPTS_REL
    if not path.is_file():
        return None
    last: dict | None = None
    try:
        for line in path.read_text(encoding="utf-8",
                                   errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                last = row
    except OSError as exc:
        warn("policy_state.receipt", f"{type(exc).__name__}: {exc}")
        return None
    if last is not None and str(last.get("schema") or "") != "plan-receipt/1":
        return None
    return last


def _receipt_key(receipt: dict) -> str:
    """The dedup key: sha256 over the receipt's decision content (claim,
    admitted, chosen, candidates). An unchanged receipt never re-writes
    the projection."""
    payload = {k: receipt.get(k)
               for k in ("claim", "admitted", "chosen", "candidates")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True,
                                     ensure_ascii=False).encode()
                          ).hexdigest()


# ------------------------------------------------------------- projection

def posterior_summary(receipt: dict) -> dict:
    """The Thompson cell summary per action kind (latest candidate of
    each kind wins) + the decision's state_signature. Old receipts
    (pre-candidates) project the honest empty face."""
    actions: dict[str, dict] = {}
    for doc in (receipt.get("candidates") or {}).values():
        if not isinstance(doc, dict):
            continue
        kind = str(doc.get("action_kind") or "")
        if not kind:
            continue
        entry: dict = {}
        for k in ("alpha", "beta"):
            v = doc.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                entry[k] = float(v)
        if entry:
            actions[kind] = entry
    return {"state_signature": receipt.get("state_signature"),
            "actions": actions}


def project(ws: Path, receipt: dict, *, now: datetime | None = None) -> dict:
    """The policy-state/1 document for one receipt. Pure in (receipt,
    workspace round index) — no sampling, no new decision."""
    from priority_ratio import round_index  # the round axis (machine-independent)
    ws = Path(ws)
    return {
        "schema": SCHEMA,
        "round": int(round_index(ws)),
        "ts": (now or datetime.now(timezone.utc)).isoformat(
            timespec="seconds").replace("+00:00", "Z"),
        "claim": receipt.get("claim"),
        "receipt_ts": receipt.get("ts"),
        "candidates": (receipt.get("candidates") or {}),
        "admitted": list(receipt.get("admitted") or []),
        "chosen": receipt.get("chosen"),
        "posterior": posterior_summary(receipt),
        "receipt_key": _receipt_key(receipt),
    }


def read(ws: Path) -> dict | None:
    """The consumer face (statusline): the current projection, or None
    when absent/corrupt (fail-open — the renderer hides the face)."""
    path = Path(ws) / REL
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


# ---------------------------------------------------------------- writer

def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def run_face(ws: Path, *, now: datetime | None = None) -> bool:
    """The production face (the round-closure host): project the latest
    receipt, atomic-write the projection, emit ONE ledger row. True when
    written; False when skipped (no receipt / unchanged receipt). Never
    raises — a projection failure must never disturb the subagent's own
    stop path."""
    ws = Path(ws)
    receipt = last_receipt(ws)
    if receipt is None:
        return False  # no decision happened -> nothing to project
    doc = project(ws, receipt, now=now)
    out = ws / REL
    # read() is fail-open by contract (corrupt/absent file -> None), so
    # the dedup comparison needs no handler of its own: a corrupt old
    # projection just rewrites.
    # issue 805: the dedup identity (receipt identity + round — never
    # the wall clock) rides the SHARED input-signature primitive; the
    # sig lands additively in the doc (policy-state/1 keeps its fields).
    import input_signature
    sig = input_signature.signature({"receipt_key": doc["receipt_key"],
                                     "round": doc["round"]})
    if input_signature.unchanged_doc(out, sig):
        return False  # unchanged receipt + unchanged round: dedup
    _atomic_write(out, json.dumps(input_signature.stamped(doc, sig),
                                  ensure_ascii=False,
                                  sort_keys=True) + "\n")
    try:
        import kunglao_log
        kunglao_log.emit(
            ws, "policy_state", "policy_state_projected",
            claim=str(receipt.get("claim") or "") or None,
            detail=json.dumps({"round": doc["round"],
                               "chosen": doc["chosen"],
                               "admitted_n": len(doc["admitted"]),
                               "candidates_n": len(doc["candidates"])},
                              ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 — logging never breaks the write
        warn("policy_state.emit", f"{type(exc).__name__}: {exc}")
    return True


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: policy_state.py <workspace>", file=sys.stderr)
        return 2
    ws = Path(args[0])
    written = run_face(ws)
    doc = read(ws)
    print(f"policy_state: {ws / REL} written={written}")
    if doc is not None:
        print(json.dumps({"round": doc.get("round"),
                          "claim": doc.get("claim"),
                          "chosen": doc.get("chosen"),
                          "admitted": doc.get("admitted")},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
