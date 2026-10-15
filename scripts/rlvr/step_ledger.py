#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/step_ledger.py — the shadow experience substrate (the online
off-policy controller's recording face, issue-667 design).

Three append-only, hash-only ledgers under runs/:

  runs/step-ledger.jsonl       step-record/1       one row per tool call
                              step-record/2       one row per subagent
                                                  completion (#690 — the
                                                  settlement grain, carries
                                                  claim_ref + step_id)
  runs/evidence-credit.jsonl   evidence-item/1     evidence citing its
                              credit-amendment/1   producing step + the
                                                   escrow lifecycle
  runs/interventions.jsonl     intervention/1      operator/controller
                                                   interventions

The trust boundary is HASH-ONLY: content-bearing fields (tool input,
tool output, artifact bytes, subject text, notes) never land — the row
builders whitelist keys and sha256 everything else. A ledger that
cannot leak can be kept forever.

The admission rule is fixed BEFORE anything consumes these rows: a
CONFIRM amendment requires the evidence item's certification verdict
(the fact-certification gate's output) — uncertified evidence escrows
and can only expire, so the two-junk-files farming shape nets zero
CONFIRMED credit by construction. Revocation walks back to the
PRODUCING step's evidence; the verifier act that confirmed is never the
revoke target.

ZERO DECISION POSTURE, as recorded by #670 (shadow telemetry): pure
append + fail-open reads; no dispatch, gate, settlement, or promotion
face imports this module (the 396 freeze-wall posture). #690 GRADUATES
exactly one seam: the completion-grain step-record/2 rows (the settle
face's own rows, hash-only like the rest) plus ``read_step_grains`` are
consumed by rlvr.step_grain — the step grain is the settlement grain.
step-record/1 (the per-tool-call shadow rows) stays append-only shadow
telemetry under its original posture. Event time rides the events —
the replay of a session's amendment stream is a pure function of its
evidence items and byte-identical to the recorded file.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from _common import utc_now_z
from kunglao_log import warn  # canonical warn: ONE implementation

STEP_SCHEMA = "step-record/1"
STEP_SCHEMA_V2 = "step-record/2"
EVIDENCE_SCHEMA = "evidence-item/1"
AMENDMENT_SCHEMA = "credit-amendment/1"
INTERVENTION_SCHEMA = "intervention/1"

STEP_LEDGER_REL = "runs/step-ledger.jsonl"
CREDIT_LEDGER_REL = "runs/evidence-credit.jsonl"
INTERVENTIONS_REL = "runs/interventions.jsonl"

# the escrow lifecycle: escrow opens, the three closures resolve it
ACTIONS = ("escrow", "confirm", "revoke", "expire")
EVIDENCE_KINDS = ("confirm", "refute", "expiry")

# pending evidence older than this many hours expires on the sweep
PENDING_TTL_HOURS = 72


def sha_of(obj) -> str:
    """sha256 hex of the canonical JSON (or of raw bytes/str verbatim)."""
    if isinstance(obj, (bytes, bytearray)):
        data = bytes(obj)
    elif isinstance(obj, str):
        data = obj.encode("utf-8", errors="replace")
    else:
        data = json.dumps(obj, sort_keys=True,
                          ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _append(rel: str, row: dict, ws) -> dict | None:
    try:
        p = Path(ws) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row
    except OSError as exc:
        warn("rlvr.step_ledger", f"{rel}: {type(exc).__name__}: {exc}")
        return None


def _read(rel: str, ws) -> list[dict]:
    p = Path(ws) / rel
    if not p.is_file():
        return []
    rows: list[dict] = []
    for line in p.read_text(encoding="utf-8",
                            errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


# ---------------------------------------------------------- step ledger

_STEP_KEYS = frozenset({
    "schema", "ts", "session_id", "call_id", "tool", "input_sha",
    "output_sha", "reads", "writes", "duration_ms"})


def build_step_row(*, session_id: str, tool: str, tool_input,
                   tool_response, reads=None, writes=None,
                   duration_ms=None, ts: str | None = None) -> dict:
    """The hash-only step-record/1 builder: content-bearing payload
    fields become shas; anything outside the whitelist is dropped (the
    raw text physically cannot reach the ledger)."""
    input_sha = sha_of(tool_input or {})
    output_sha = sha_of(tool_response if tool_response is not None else {})
    event_ts = ts or utc_now_z()
    row = {
        "schema": STEP_SCHEMA,
        "ts": event_ts,
        "session_id": str(session_id or ""),
        "call_id": sha_of([session_id, tool, input_sha, event_ts])[:16],
        "tool": str(tool or ""),
        "input_sha": input_sha,
        "output_sha": output_sha,
        "reads": [sha_of(r) for r in (reads or [])],
        "writes": [sha_of(w) for w in (writes or [])],
        "duration_ms": (float(duration_ms)
                        if isinstance(duration_ms, (int, float)) else None),
    }
    assert set(row) <= _STEP_KEYS
    return row


def record_step(ws, row: dict) -> dict | None:
    """Append one step-record/1 row. The whitelist is re-enforced here —
    a caller cannot smuggle a raw-content key into the ledger."""
    clean = {k: row[k] for k in _STEP_KEYS if k in row}
    return _append(STEP_LEDGER_REL, clean, ws)


def read_steps(ws) -> list[dict]:
    return _read(STEP_LEDGER_REL, ws)


# ------------------------------------ the completion grain (#690, step-record/2)

_STEP_V2_KEYS = frozenset({
    "schema", "ts", "session_id", "step_id", "claim_ref",
    "tool_calls", "call_ids", "first_ts", "last_ts", "duration_ms"})


def build_step_grain_row(*, session_id: str, claim_ref: str, step_id: str,
                         call_ids, first_ts: str = "", last_ts: str = "",
                         duration_ms=None,
                         ts: str | None = None) -> dict:
    """The completion-grain step-record/2 builder (#690): ONE row per
    subagent completion, aggregating the session's per-tool-call rows.
    ``call_ids`` are step-record/1 call_id hashes (hash-only preserved —
    no content-bearing field exists in the whitelist); ``claim_ref`` rides
    via the dispatch-launch mapping (rlvr.step_grain.settle_step)."""
    ids = [str(c) for c in (call_ids or [])]
    row = {
        "schema": STEP_SCHEMA_V2,
        "ts": ts or utc_now_z(),
        "session_id": str(session_id or ""),
        "step_id": str(step_id or ""),
        "claim_ref": str(claim_ref or ""),
        "tool_calls": len(ids),
        "call_ids": ids,
        "first_ts": str(first_ts or ""),
        "last_ts": str(last_ts or ""),
        "duration_ms": (float(duration_ms)
                        if isinstance(duration_ms, (int, float)) else None),
    }
    assert set(row) <= _STEP_V2_KEYS
    return row


def record_step_grain(ws, row: dict) -> dict | None:
    """Append one step-record/2 row. The v2 whitelist is re-enforced here —
    a caller cannot smuggle a raw-content key into the ledger."""
    clean = {k: row[k] for k in _STEP_V2_KEYS if k in row}
    return _append(STEP_LEDGER_REL, clean, ws)


def read_step_grains(ws, session_id: str | None = None) -> list[dict]:
    """The completion-grain read face: every step-record/2 row (oldest
    first), optionally scoped to one session."""
    rows = [r for r in _read(STEP_LEDGER_REL, ws)
            if r.get("schema") == STEP_SCHEMA_V2]
    if session_id is None:
        return rows
    return [r for r in rows
            if str(r.get("session_id") or "") == str(session_id)]


# --------------------------------------------- the evidence-credit ledger

def record_evidence(ws, *, step_ref: str, claim_ref: str, kind: str,
                    artifact, certified: bool,
                    ts: str | None = None) -> dict | None:
    """One evidence-item/1 row: the producing step's call id, the claim
    reference, the artifact sha, and the certification verdict computed
    upstream by the fact-certification gate."""
    if kind not in EVIDENCE_KINDS:
        warn("rlvr.step_ledger.record_evidence",
             f"refused kind {kind!r} — not one of {EVIDENCE_KINDS}")
        return None
    item_ts = ts or utc_now_z()
    row = {
        "schema": EVIDENCE_SCHEMA,
        "id": sha_of([step_ref, claim_ref, kind, item_ts])[:12],
        "ts": item_ts,
        "step_ref": str(step_ref or ""),
        "claim_ref": str(claim_ref or ""),
        "kind": kind,
        "artifact_sha": sha_of(artifact or {}),
        "certified": bool(certified),
    }
    return _append(CREDIT_LEDGER_REL, row, ws)


def _item(items: list[dict], evidence_id: str) -> dict | None:
    for row in items:
        if str(row.get("id") or "") == str(evidence_id):
            return row
    return None


def amend(ws, *, evidence_id: str, verb: str, amount=None,
          reason: str = "", ts: str | None = None) -> dict | None:
    """One credit-amendment/1 row, validated at the boundary (D2):
    escrow opens an item's lifecycle; confirm requires the item's
    certification verdict; revoke walks the credit back to the
    producing step's evidence; expire ages a pending item out. Refusals
    are None + ONE warn."""
    if verb not in ACTIONS:
        warn("rlvr.step_ledger.amend",
             f"refused verb {verb!r} — not one of {ACTIONS}")
        return None
    items = [r for r in _read(CREDIT_LEDGER_REL, ws)
             if r.get("schema") == EVIDENCE_SCHEMA]
    item = _item(items, str(evidence_id))
    if item is None:
        warn("rlvr.step_ledger.amend",
             f"refused {verb} of {evidence_id!r}: no such evidence item")
        return None
    prior_all = [r for r in _read(CREDIT_LEDGER_REL, ws)
                 if r.get("schema") == AMENDMENT_SCHEMA
                 and r.get("evidence_id") == str(evidence_id)]
    if verb == "escrow":
        if prior_all:
            warn("rlvr.step_ledger.amend",
                 f"refused escrow of {evidence_id!r}: the lifecycle is "
                 f"already opened ({prior_all[-1].get('action')!r})")
            return None
    else:
        prior = [r for r in prior_all if r.get("action") != "escrow"]
        if prior:
            warn("rlvr.step_ledger.amend",
                 f"refused {verb} of {evidence_id!r}: the lifecycle is "
                 f"already resolved ({prior[-1].get('action')!r}) — one "
                 f"resolution per item")
            return None
    if verb == "confirm" and not bool(item.get("certified")):
        warn("rlvr.step_ledger.amend",
             f"refused confirm of {evidence_id!r}: the evidence item is "
             f"not certified — uncertified evidence escrows and can "
             f"only expire (the admission rule)")
        return None
    row = {
        "schema": AMENDMENT_SCHEMA,
        "ts": ts or item.get("ts") or utc_now_z(),
        "evidence_id": str(evidence_id),
        "action": verb,
        "amount": (float(amount) if isinstance(amount, (int, float))
                   and not isinstance(amount, bool) else None),
        "reason": str(reason or ""),
    }
    return _append(CREDIT_LEDGER_REL, row, ws)


def expire_pending(ws, *, now=None) -> list[str]:
    """Age pending items out at the TTL: every evidence item with no
    resolution older than PENDING_TTL_HOURS gets its expire amendment.
    Returns the expired ids."""
    items = [r for r in _read(CREDIT_LEDGER_REL, ws)
             if r.get("schema") == EVIDENCE_SCHEMA]
    from datetime import datetime, timedelta, timezone
    now_dt = now or datetime.now(timezone.utc)
    expired: list[str] = []
    for item in items:
        if not item.get("ts"):
            continue
        try:
            ts = datetime.fromisoformat(
                str(item["ts"]).replace("Z", "+00:00"))
        except ValueError:
            continue
        if now_dt - ts <= timedelta(hours=PENDING_TTL_HOURS):
            continue
        if amend(ws, evidence_id=str(item.get("id")), verb="expire",
                 reason="pending past the TTL"):
            expired.append(str(item.get("id")))
    return expired


def replay_credit_ledger(ws) -> str:
    """The replay face (D3): re-derive the amendment stream from the
    evidence items — escrow per item, confirm iff certified — and
    return the exact bytes. For a session whose operator actions are
    none, this equals the recorded file byte for byte."""
    items = [r for r in _read(CREDIT_LEDGER_REL, ws)
             if r.get("schema") == EVIDENCE_SCHEMA]
    lines = []
    for item in items:
        for action in ("escrow", "confirm"):
            if action == "confirm" and not bool(item.get("certified")):
                continue
            row = {
                "schema": AMENDMENT_SCHEMA,
                "ts": item.get("ts"),
                "evidence_id": str(item.get("id")),
                "action": action,
                "amount": None,
                "reason": "",
            }
            lines.append(json.dumps(row, ensure_ascii=False))
    return "\n".join(lines) + ("\n" if lines else "")


def read_amendments(ws) -> list[dict]:
    return [r for r in _read(CREDIT_LEDGER_REL, ws)
            if r.get("schema") == AMENDMENT_SCHEMA]


# ------------------------------------------------------- interventions

_INTERVENTION_KEYS = frozenset({
    "schema", "ts", "trigger", "actor", "subject_sha", "note_sha"})


def record_intervention(ws, *, trigger: str, actor: str, subject,
                        note: str = "", ts: str | None = None) -> dict | None:
    """One intervention/1 row — shadow-only; subject and note ride as
    shas."""
    row = {
        "schema": INTERVENTION_SCHEMA,
        "ts": ts or utc_now_z(),
        "trigger": str(trigger or ""),
        "actor": str(actor or ""),
        "subject_sha": sha_of(subject or ""),
        "note_sha": sha_of(note or ""),
    }
    assert set(row) <= _INTERVENTION_KEYS
    return _append(INTERVENTIONS_REL, row, ws)
