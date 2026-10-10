#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/prediction_ledger.py — the prediction ledger.

Real targets lack an immediate oracle: many assertions cannot be
verified now (some never), and today such assertions sit at
PARTIALLY-VERIFIED with the loop's only levers being blind-verify acts
(costly, sometimes premature) or BLOCKED. The ledger turns those
assertions into delayed settlement events: a claim attaches falsifiable
predictions with non-trivial prior uncertainty, later observations
(their discriminator = the machine-checkable observable that settles
them) settle them into transition-ledger rows, and the existing
settlement pipeline consumes those rows unchanged.

Faces:

  register(ws, claim_id, statement, discriminator, actor) -> row | None
      One falsifiable prediction, schema ``prediction-ledger/1``.
      Refuses (None + loud warn) a trivial discriminator — one whose
      tokens are a subset of the statement's (the statement restates
      what is already observed; it banks ~0 lift) — a SCAFFOLD-AIMED
      discriminator (4-L5: one whose tokens touch the checker's
      own MANDATED output — the engine-parsed ``verdict:`` frontmatter
      line settles on contract compliance, never on the claim's truth),
      and a duplicate discriminator against any open prediction (dedup).
      5-F4: ``actor`` (the registering act's identity) is REQUIRED
      and rides the row as ``registered_by`` — the raw-JSONL-append
      bypass (runs/predictions.jsonl is not a carrier) mints rows the
      settle face will never honor. Input validation at the boundary:
      empty statement/discriminator/actor raise.

  base_rate(discriminator, statement) -> float
      The trivial-prior estimate: 1.0 when the discriminator is trivial
      (token subset — the observable is already claimed true by the
      statement itself), else the floor constant. The point is
      anti-trivial, not calibrated precision.

  log_lift(rate) -> float
      log(1 / max(rate, BASE_RATE_FLOOR)) — trivial predictions bank
      ~0 lift; honest ones ride the floor-bounded maximum. One
      constant, pinned.

  settle(ws, prediction_id, outcome) -> transition row | None
      Append the settle row to the ledger history, then close the
      transition via the existing face (launch stash + append, so the
      row carries the full SMDP shape): action_type
      "prediction-settle", r_settle from the credit mapping
      (confirmed -> 1.0, refuted -> 0.0), the log-lift riding the row
      as the lift weight. Returns the transition row (None when the
      prediction is unknown/already settled or the transition face had
      no stash to close).

  pending(ws) -> list
      Open predictions (latest status pending, inside the TTL), oldest
      registration first — the controller-state backlog face.

  expired(ws) -> list
      Pending-on-disk predictions past the TTL: they flip to expired
      ON READ (never deleted — the ledger history is append-only).

  backlog(ws) -> dict
      {count, max_age_hours} over the pending set — the compose-state
      face (count x age is the controller signal).

  settle_matching(ws, claim_id, evidence_text) -> list[str]
      The wiring face: pending predictions registered against the claim
      whose discriminator appears in the observed evidence text
      (case-insensitive containment — the mechanical v1 match) settle
      confirmed. Returns the settled ids.
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

from _common import utc_now_z
from kunglao_log import warn  # canonical warn: ONE implementation

from rlvr import incremental_reward as ir

SCHEMA = "prediction-ledger/1"
LEDGER_REL = "runs/predictions.jsonl"

STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_REFUTED = "refuted"
STATUS_EXPIRED = "expired"
SETTLE_OUTCOMES = (STATUS_CONFIRMED, STATUS_REFUTED)

# the ONE anti-trivial constant: base rates clamp here from below, so
# the maximum lift any prediction can bank is log(1 / 0.01) ~= 4.605 —
# the point is anti-trivial, not calibrated precision
BASE_RATE_FLOOR = 0.01

# open predictions older than this many hours flip to expired on read
PREDICTION_TTL_HOURS = 72

# 4-L5: the checker's own MANDATED output — the `verdict:`
# frontmatter line the dispatch contract requires and the engine itself
# parses (checkpoints.py:1308/1518/1553). A discriminator touching
# these tokens settles on contract compliance, never on the claim's
# truth. Extension point: a scaffold line joins only when the contract
# actually mandates it — never fabricated here.
MANDATED_CHECKER_MARKERS = ("verdict",)

_ID_RE = re.compile(r"^P-(\d+)$")


# ------------------------------------------------------------- helpers

def _tokens(text: str) -> set[str]:
    """Lowercased word tokens (the mechanical triviality heuristic)."""
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def is_trivial(discriminator: str, statement: str) -> bool:
    """True when the discriminator adds no observable beyond the
    statement's own tokens (the statement restates what is already
    observed — base rate ~1, lift ~0)."""
    disc = _tokens(discriminator)
    return bool(disc) and disc <= _tokens(statement)


def is_scaffold_aimed(discriminator: str) -> bool:
    """4-L5: True when the discriminator's tokens touch the
    checker's MANDATED output (``MANDATED_CHECKER_MARKERS``) — such a
    discriminator is a guaranteed hit on any contract-compliant verifier
    note regardless of the claim's truth (base rate ~1 by
    construction)."""
    disc = _tokens(discriminator)
    return bool(disc) and bool(disc & set(MANDATED_CHECKER_MARKERS))


def base_rate(discriminator: str, statement: str) -> float:
    """The trivial-prior estimate: 1.0 for a trivial discriminator, the
    floor for an honest one."""
    return 1.0 if is_trivial(discriminator, statement) else BASE_RATE_FLOOR


def log_lift(rate: float) -> float:
    """log(1 / max(rate, BASE_RATE_FLOOR)) — the anti-trivial weight."""
    return math.log(1.0 / max(float(rate), BASE_RATE_FLOOR))


def _ledger_path(ws: Path) -> Path:
    return Path(ws) / LEDGER_REL


def _append_row(ws: Path, row: dict) -> None:
    p = _ledger_path(ws)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_ledger(ws) -> list[dict]:
    """All ledger rows, oldest first; tolerant read (blank/malformed
    lines skipped; absent file = empty)."""
    p = _ledger_path(ws)
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


def _age_hours(registered_ts: str) -> float:
    """Hours since the registration stamp; a corrupt stamp counts as
    expired-age (fail-closed — an untimed prediction cannot pretend to
    be fresh)."""
    try:
        dt = datetime.fromisoformat(str(registered_ts).replace("Z", "+00:00"))
    except ValueError:
        return float("inf")
    now = datetime.now(tz=timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 3600.0)


def latest_by_id(ws) -> dict[str, dict]:
    """The current state per prediction id (last row wins)."""
    out: dict[str, dict] = {}
    for row in read_ledger(ws):
        pid = str(row.get("id") or "")
        if pid:
            out[pid] = row
    return out


# ---------------------------------------------------------- registration

def register(ws, claim_id: str, statement: str,
             discriminator: str, actor: str) -> dict | None:
    """One falsifiable prediction (see module docstring). 5-F4:
    ``actor`` (the registering act's identity) is required — the row
    stamps it as ``registered_by`` and the settle faces refuse rows
    without it, so the raw JSONL-append bypass mints rows that can
    never bank lift."""
    statement = str(statement or "").strip()
    discriminator = str(discriminator or "").strip()
    claim_id = str(claim_id or "").strip()
    actor = str(actor or "").strip()
    if not statement or not discriminator or not claim_id or not actor:
        raise ValueError(
            "prediction_ledger.register: claim_id, statement, "
            "discriminator and actor must all be non-empty")
    if is_scaffold_aimed(discriminator):
        warn("prediction_ledger.register",
             f"refused scaffold-aimed discriminator {discriminator!r} "
             f"for {claim_id}: its tokens touch the checker's MANDATED "
             f"output {MANDATED_CHECKER_MARKERS} — it settles on "
             f"contract compliance, not on the claim's truth (4-L5)")
        return None
    if is_trivial(discriminator, statement):
        warn("prediction_ledger.register",
             f"refused trivial discriminator {discriminator!r} for "
             f"{claim_id}: the discriminator's tokens restate the "
             f"statement (base rate ~1, lift ~0) — provide a "
             f"machine-checkable observable")
        return None
    disc_key = " ".join(sorted(_tokens(discriminator)))
    for row in latest_by_id(ws).values():
        if str(row.get("status") or "") == STATUS_PENDING \
                and " ".join(sorted(_tokens(
                    str(row.get("discriminator") or "")))) == disc_key:
            warn("prediction_ledger.register",
                 f"refused duplicate discriminator {discriminator!r} for "
                 f"{claim_id}: an open prediction ({row.get('id')}) "
                 f"already carries it")
            return None
    next_n = 1
    for pid in latest_by_id(ws):
        m = _ID_RE.match(pid)
        if m:
            next_n = max(next_n, int(m.group(1)) + 1)
    row = {
        "schema": SCHEMA,
        "id": f"P-{next_n}",
        "claim_id": claim_id,
        "statement": statement,
        "discriminator": discriminator,
        "registered_by": actor,
        "registered_ts": utc_now_z(),
        "status": STATUS_PENDING,
    }
    _append_row(ws, row)
    return row


# ------------------------------------------------------------ read faces

def _latest_status(row: dict) -> str:
    return str(row.get("status") or "")


def pending(ws) -> list[dict]:
    """Open predictions inside the TTL, oldest registration first."""
    out = []
    for row in latest_by_id(ws).values():
        if _latest_status(row) != STATUS_PENDING:
            continue
        if _age_hours(row.get("registered_ts")) > PREDICTION_TTL_HOURS:
            continue  # expired on read
        out.append(row)
    out.sort(key=lambda r: (str(r.get("registered_ts")), str(r.get("id"))))
    return out


def expired(ws) -> list[dict]:
    """Pending-on-disk predictions past the TTL (expired on read; the
    rows stay on disk — append-only history, never deleted)."""
    out = []
    for row in latest_by_id(ws).values():
        if _latest_status(row) == STATUS_PENDING \
                and _age_hours(row.get("registered_ts")) \
                > PREDICTION_TTL_HOURS:
            out.append(row)
    out.sort(key=lambda r: (str(r.get("registered_ts")), str(r.get("id"))))
    return out


def backlog(ws) -> dict:
    """{count, max_age_hours} over the pending set (0.0 age when
    empty) — the compose-state face."""
    open_rows = pending(ws)
    return {
        "count": len(open_rows),
        "max_age_hours": round(max(
            (_age_hours(r.get("registered_ts")) for r in open_rows),
            default=0.0), 4),
    }


# ------------------------------------------------------------- settlement

def settle(ws, prediction_id: str, outcome: str) -> dict | None:
    """Settle one prediction (see module docstring). Returns the
    transition row."""
    outcome = str(outcome or "").strip().lower()
    if outcome not in SETTLE_OUTCOMES:
        raise ValueError(
            f"prediction_ledger.settle: outcome must be one of "
            f"{SETTLE_OUTCOMES}, got {outcome!r}")
    prediction_id = str(prediction_id or "").strip()
    current = latest_by_id(ws).get(prediction_id)
    if current is None or _latest_status(current) != STATUS_PENDING:
        warn("prediction_ledger.settle",
             f"refused settle of {prediction_id}: unknown or no longer "
             f"pending (status "
             f"{_latest_status(current or {}) or 'unknown'!r})")
        return None
    if not str(current.get("registered_by") or "").strip():
        # 5-F4: the raw JSONL-append bypass (runs/predictions.jsonl is
        # not a carrier) mints rows with no authorship — they can never
        # bank lift, no matter what the evidence text carries.
        warn("prediction_ledger.settle",
             f"refused settle of {prediction_id}: the pending row "
             f"carries no registered_by authorship — a row that bypassed "
             f"the register face never settles (5-F4)")
        return None
    claim_id = str(current.get("claim_id") or "")
    statement = str(current.get("statement") or "")
    discriminator = str(current.get("discriminator") or "")
    settle_row = {
        "schema": SCHEMA,
        "id": prediction_id,
        "claim_id": claim_id,
        "statement": statement,
        "discriminator": discriminator,
        "registered_by": current.get("registered_by"),
        "registered_ts": current.get("registered_ts"),
        "status": outcome,
        "settled_ts": utc_now_z(),
    }
    _append_row(ws, settle_row)
    lift = log_lift(base_rate(discriminator, statement))
    try:
        # 1-F2: the settle binds to the attempt it just launched —
        # a concurrent re-dispatch's stash is never banked as this row's
        # before-state (the guard refuses on a mismatched attempt id).
        launch_doc = ir.record_launch(ws, claim_id, "prediction-settle",
                                      action_type="prediction-settle")
        t_row = ir.append_transition(
            ws, claim_id, outcome,
            status=prediction_id,
            r_settle=ir.verify_credit(outcome),
            action_type="prediction-settle",
            lift=lift,
            attempt_id=str((launch_doc or {}).get("attempt_id") or ""))
    except (OSError, ValueError, TypeError) as exc:  # loud telemetry
        warn("prediction_ledger.settle",
             f"transition face failed for {prediction_id}: "
             f"{type(exc).__name__}: {exc}")
        return None
    if t_row is None:
        warn("prediction_ledger.settle",
             f"transition row absent for {prediction_id} (no stash to "
             f"close) — the ledger history still carries the settle")
    return t_row


# ----------------------------------------------------- the wiring face

def settle_matching(ws, claim_id: str, evidence_text) -> list[str]:
    """Pending predictions of the claim whose discriminator appears in
    the observed evidence (case-insensitive containment — the
    mechanical v1 match) settle confirmed. Returns the settled ids."""
    text = str(evidence_text or "").lower()
    if not text.strip():
        return []
    settled: list[str] = []
    for row in pending(ws):
        if str(row.get("claim_id") or "") != str(claim_id or "").strip():
            continue
        if not str(row.get("registered_by") or "").strip():
            # 5-F4: the raw-append bypass never settles (see settle).
            warn("prediction_ledger.settle_matching",
                 f"refused settle of {row.get('id')}: the pending row "
                 f"carries no registered_by authorship — a row that "
                 f"bypassed the register face never settles (5-F4)")
            continue
        discriminator = str(row.get("discriminator") or "").strip().lower()
        if discriminator and discriminator in text:
            t_row = settle(ws, str(row["id"]), STATUS_CONFIRMED)
            if t_row is not None:
                settled.append(str(row["id"]))
    return settled


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
