# -*- coding: utf-8 -*-
"""rlvr/ledger.py — THE unified rollout ledger (U1).

Issue #420 Phase 2: the implementation body moved here; the top-level
adapter shim was retired by the legacy-surface card — importers use
``rlvr.ledger`` directly.

Owner ruling (2026-09-23): the whole RLVA reward is unified — ALL rollout
kinds share ONE accounting system. This module owns the ledger rows,
append-only JSONL in the consolidated settlement family file
``<ws>/runs/settlement.jsonl`` (the row schema and the
``rollout-ledger/1`` stamp are unchanged; the family move retired the
per-module file):

    {"schema": "rollout-ledger/1",
     "rollout_id": "<kind>/<anchor>",   # identity (stable across folds)
     "kind": "task|self_distill|hybrid_distill|<registered>",
     "anchor": "C-101 | lesson-sig | item id",   # domain anchor
     "ts": "...Z",                       # identity creation time
     "signals": [{"type", "source", "value", "ts", ["advisory": true]}],
     "reward": null,                     # null until settled
     "settlement": null | {"reward", "band", "rule_id", "evidence_refs"}}

The ``reward`` field's UNIT is declared per kind:
``REWARD_RAIL_BOUNDED`` kinds carry a [0,1] settlement scalar;
``round_credit`` (``REWARD_RAIL_PROVENANCE``) carries a provenance sum in
credit units — its rows also echo ``reward_rail: provenance`` and
``credit_units`` in the settlement; ``REWARD_RAIL_SIGNED`` kinds
(mainline ΔV, review-bridge attribution) carry an unbounded signed real.
``reward_rail_of(row)`` / ``reward_range_of(row)`` are the schema read
face; consumers that expect [0,1] must exclude + report the other rails
(see ``rlvr.reward``).

Append-only semantics (the wal-protocol posture): rows are NEVER rewritten
in place. A settlement is an AMENDMENT row (same rollout_id); the read face
``fold`` merges identity (first row), signals (last non-empty), and
settlement (last non-null) into one row per rollout. The file's byte prefix
is invariant across all activity — pinned by test.

Kinds are an OPEN ENUM registered centrally: a new kind is one
``register_kind`` entry (plus its reward-rules.yaml rule ids), never an
ad-hoc string. ``task`` and ``self_distill`` land now;
``hybrid_distill`` is pre-registered — the distill card's rollout rows
MUST conform to this schema (mother-card ruling).

Model-produced scores are admissible only as INPUT signals explicitly
marked ``advisory: true`` (U3 whitelist): the ledger stores them, but the
settlement engine never reads them for rule matching, and no single signal
— advisory or not — settles a band alone.

Locking: appends ride the consolidated settlement family's flock
(``runs/.settlement.lock`` via rlvr.consolidated_ledger — the ONE
writer guard; the per-module ``runs/.rollout-ledger.lock`` rel retired
with the family move; graceful unlocked fallback where flock is
unavailable — O_APPEND single-writes stay atomic, and CI is
single-tenant).

The ONE prior interface (U4): ``settled(ws, kind=..., window=...)`` — the
Thompson/rank family reads settled rows through this call and no other
(consumed additively by compute_priors, issue 137).

Fail-open on reads (missing/dirty ledger = empty), loud on write rejections
(record/settle return a result dict, never raise into the producer).
"""
from __future__ import annotations

import json
from pathlib import Path

from harness_common import utc_now_z as _utc_now

from rlvr import consolidated_ledger as _cl

SCHEMA = "rollout-ledger/1"
#: the legacy rel the rows wrote before the family move — kept as the
#: compat-window's documented name (readers still see it; production
#: no longer writes it; the schema-cutover slice retires the window)
LEDGER_REL = "runs/rollout-ledger.jsonl"

# --- kinds registry (open enum, registered centrally) ----------------------
KIND_TASK = "task"
KIND_SELF_DISTILL = "self_distill"
KIND_HYBRID_DISTILL = "hybrid_distill"
KIND_HYPOTHESIS = "hypothesis"

ROLLOUT_KINDS: dict[str, str] = {
    KIND_TASK: "oracle-checked task rollout",
    KIND_SELF_DISTILL: "self-distillation rollout, lesson/card unit",
    KIND_HYBRID_DISTILL: "hybrid distill rollout — producer is the distill engine",
    KIND_HYPOTHESIS: "hypothesis resolution/churn rollout — the Φ-tree "
                     "economy (#796)",
}

# --- reward units per row kind --------------------------------------------
#
# The ``reward`` field is NOT one unit across the ledger's kinds:
#   - BOUNDED kinds (task / distill / hypothesis settlement rows) carry a
#     [0,1] settlement scalar — the rail ``scalar.clamp_credit`` /
#     ``rail_of`` enforce on the settlement path;
#   - ``round_credit`` rows carry a PROVENANCE SUM in credit units
#     (2 cited artifacts + 1 demotion class = 2.01). It is deliberately
#     unclamped: clamping would erase the difference between citing one
#     and two artifacts;
#   - ``mainline_decision`` rows carry a SIGNED ΔV (the situation-stream
#     replay face, verification_ladder) — a real, not a reward scalar.
# This registry IS the ``rollout-ledger/1`` schema declaration. Consumers
# that expect a [0,1] reward call ``reward_rail_of(row)`` and EXCLUDE (and
# report) every row on any other rail instead of reading its value as a
# reward (the prior feed is the first such consumer, reward.py).
# The rule ids for these kinds live in reward-rules.yaml ``reward_units``.
REWARD_RAIL_BOUNDED = "bounded"
REWARD_RAIL_PROVENANCE = "provenance"
REWARD_RAIL_SIGNED = "signed"
REWARD_RANGE_BOUNDED = (0.0, 1.0)
#: rail -> declared range (None = unbounded by design)
REWARD_RAILS: dict[str, tuple[float, float] | None] = {
    REWARD_RAIL_BOUNDED: REWARD_RANGE_BOUNDED,
    REWARD_RAIL_PROVENANCE: None,
    REWARD_RAIL_SIGNED: None,
}
#: kind -> rail. Kinds absent here read as bounded (the register default);
#: a provenance kind MUST register itself with the provenance rail.
KIND_REWARD_RAILS: dict[str, str] = {
    KIND_TASK: REWARD_RAIL_BOUNDED,
    KIND_SELF_DISTILL: REWARD_RAIL_BOUNDED,
    KIND_HYBRID_DISTILL: REWARD_RAIL_BOUNDED,
    KIND_HYPOTHESIS: REWARD_RAIL_BOUNDED,
}
# canonical warn: ONE implementation (process-wide dedupe + ledger face)
from kunglao_log import warn  # noqa: E402 — post-constants, matches the shim layout


def register_kind(kind: str, note: str = "",
                  rail: str = REWARD_RAIL_BOUNDED) -> bool:
    """Open-enum registration. Returns False (no-op) when already
    registered — re-registration is idempotent, not an error (and never
    re-writes the rail: a later bare call cannot demote a provenance
    kind back to bounded). An unknown rail name is a caller bug —
    ValueError, the enum never invents a unit."""
    kind = str(kind or "").strip()
    if not kind or kind in ROLLOUT_KINDS:
        return False
    if rail not in REWARD_RAILS:
        raise ValueError(f"register_kind: unknown reward rail {rail!r}")
    ROLLOUT_KINDS[kind] = note or "(unannotated)"
    KIND_REWARD_RAILS[kind] = rail
    return True


def reward_rail_of(row_or_kind) -> str:
    """The declared reward rail of one ledger row (mapping) or kind name.
    The KIND registry is authoritative — a settlement's
    ``reward_rail`` marker is an audit echo, lint-checked for agreement,
    never a second source of truth. An unknown kind reads bounded (the
    register default)."""
    kind = (row_or_kind.get("kind") if isinstance(row_or_kind, dict)
            else row_or_kind)
    return KIND_REWARD_RAILS.get(str(kind or "").strip(),
                                 REWARD_RAIL_BOUNDED)


def reward_range_of(row_or_kind) -> tuple[float, float] | None:
    """The declared inclusive range of the row's reward value: (0.0,
    1.0) on the bounded rail; None on the provenance rail (an unclamped
    sum in credit units — not a reward)."""
    return REWARD_RAILS[reward_rail_of(row_or_kind)]


def _kind_names() -> tuple[str, ...]:
    return tuple(ROLLOUT_KINDS)


def kinds() -> tuple[str, ...]:
    """The registered kind names (open-enum read face)."""
    return _kind_names()


# --- schema lint ------------------------------------------------------------

_REQUIRED_ROW_FIELDS = ("rollout_id", "kind", "anchor", "ts",
                        "signals", "reward", "settlement")
_REQUIRED_SIGNAL_FIELDS = ("type", "source", "value", "ts")


def _lint_identity(row: dict, errors: list[str]) -> None:
    """Identity-face lint (fields checked present by the caller)."""
    if row["kind"] not in ROLLOUT_KINDS:
        errors.append(f"kind {row['kind']!r} not registered")
    for field in ("rollout_id", "anchor", "ts"):
        if not str(row[field]).strip():
            errors.append(f"{field}: empty")


def _lint_settlement(row: dict, errors: list[str]) -> None:
    """Settlement-face lint (null or a complete document)."""
    st = row["settlement"]
    if st is None:
        return
    if not isinstance(st, dict):
        errors.append("settlement: null or mapping")
        return
    for field in ("reward", "band", "rule_id", "evidence_refs"):
        if field not in st:
            errors.append(f"settlement: missing {field}")
    if isinstance(st, dict) and not isinstance(st.get("evidence_refs"), list):
        errors.append("settlement.evidence_refs: must be a list")


def _lint_signals(row: dict, errors: list[str]) -> None:
    """Signal-face lint (list of complete {type, source, value, ts})."""
    signals = row["signals"]
    if not isinstance(signals, list):
        errors.append("signals: must be a list")
        return
    for i, sig in enumerate(signals):
        if not isinstance(sig, dict):
            errors.append(f"signals[{i}]: not a mapping")
            continue
        for field in _REQUIRED_SIGNAL_FIELDS:
            if field not in sig:
                errors.append(f"signals[{i}]: missing {field}")


def _lint_reward_rail(row: dict, errors: list[str]) -> None:
    """Reward-unit lint: the settlement value must agree
    with the KIND's declared rail. Bounded kinds carry a numeric [0,1]
    reward; provenance kinds carry an unbounded sum, and when the
    additive ``credit_units`` audit field is present it must equal the
    settled value. A ``reward_rail`` marker that disagrees with the kind
    is a schema error (the marker echoes, it never overrides)."""
    st = row["settlement"]
    if st is None or not isinstance(st, dict):
        # a malformed settlement was already named by _lint_settlement;
        # the read path stays fail-open on dirty rows (never raise here).
        return
    kind = str(row["kind"])
    rail = reward_rail_of(kind)
    marker = st.get("reward_rail")
    if marker is not None and marker != rail:
        errors.append(
            f"settlement.reward_rail {marker!r} != the {kind!r} kind's "
            f"{rail!r} rail")
    reward = st.get("reward")
    if rail == REWARD_RAIL_BOUNDED:
        lo, hi = REWARD_RANGE_BOUNDED
        for face, value in (("reward", row.get("reward")),
                            ("settlement.reward", reward)):
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value,
                                                         (int, float)):
                errors.append(f"{face}: number on the bounded reward rail")
            elif not lo <= float(value) <= hi:
                errors.append(
                    f"{face}: {value!r} outside the [0,1] bounded reward "
                    f"rail (kind={kind})")
        return
    units = st.get("credit_units")
    if units is None:
        return  # legacy row: the kind declaration still carries the unit
    if isinstance(units, bool) or not isinstance(units, (int, float)):
        errors.append("settlement.credit_units: number")
    elif isinstance(reward, (int, float)) and not isinstance(reward, bool) \
            and float(units) != float(reward):
        errors.append(
            f"settlement.credit_units {units!r} != settlement.reward "
            f"{reward!r} (the provenance sum IS the settled value)")


def row_schema_lint(row: dict) -> list[str]:
    """Schema errors for one row ([] = clean). Pure; used by tests and by
    append-time validation."""
    if not isinstance(row, dict):
        return ["row: not a mapping"]
    missing = [f"missing field: {f}" for f in _REQUIRED_ROW_FIELDS
               if f not in row]
    if missing:
        return missing
    errors: list[str] = []
    _lint_identity(row, errors)
    if row["reward"] is not None and not isinstance(row["reward"], (int, float)):
        errors.append("reward: null or number")
    _lint_settlement(row, errors)
    _lint_reward_rail(row, errors)
    _lint_signals(row, errors)
    return errors


# --- IO ---------------------------------------------------------------------

def read(ws) -> list[dict]:
    """Schema-enforced read: only rows passing row_schema_lint are signal
    (a settlement currency never half-reads a row); unparseable or
    schema-violating lines are skipped with one rate-limited WARN.
    Rows come from the consolidated settlement family read (legacy
    rollout-ledger rows first, then live family rows — chronology);
    missing ledger -> []."""
    out: list[dict] = []
    for row in _cl.read(ws, "settlement", schema_prefix="rollout-ledger"):
        if not isinstance(row, dict) or row_schema_lint(row):
            warn("read_dirty", "schema-violating row skipped")
            continue
        out.append(row)
    return out


def _row(rollout_id: str, kind: str, anchor: str, ts: str,
         signals: list[dict], settlement: dict | None) -> dict:
    return {
        "schema": SCHEMA,
        "rollout_id": rollout_id,
        "kind": kind,
        "anchor": anchor,
        "ts": ts,
        "signals": signals,
        "reward": None if settlement is None else settlement["reward"],
        "settlement": settlement,
    }


# --- fold + query faces ------------------------------------------------------

def _fold_rows(rows: list[dict]) -> list[dict]:
    """Fold raw rows into one row per rollout_id (append order): identity/
    ts from the FIRST row, signals from the LAST row carrying a non-empty
    list, reward/settlement from the LAST row carrying a non-null
    settlement."""
    folds: dict[str, dict] = {}
    order: list[str] = []
    for row in rows:
        rid = str(row.get("rollout_id") or "")
        if not rid:
            continue
        if rid not in folds:
            folds[rid] = dict(row)
            order.append(rid)
            continue
        cur = folds[rid]
        if row.get("signals"):
            cur["signals"] = row["signals"]
        if row.get("settlement") is not None:
            cur["settlement"] = row["settlement"]
            cur["reward"] = row.get("reward")
    return [folds[rid] for rid in order]


def _signals_digest(signals: list[dict]) -> str:
    """Stable digest of a signal set — the settlement currency's
    re-settlement key: a settled rollout whose signals GROW is a new
    settlement candidate (DEFERRED -> wake -> PROVEN upgrades its band)."""
    import hashlib
    return hashlib.sha256(json.dumps(
        signals, ensure_ascii=False, sort_keys=True)
        .encode("utf-8")).hexdigest()


def fold(ws, rollout_id: str) -> dict | None:
    """One rollout's current row (see _fold_rows). None when unknown."""
    rid = str(rollout_id or "")
    if not rid:
        return None
    return next((f for f in _fold_rows(read(ws))
                 if f.get("rollout_id") == rid), None)


def settled(ws, kind: str | None = None,
            window: tuple | None = None) -> list[dict]:
    """THE prior interface (U4): settled rows, optionally filtered by kind
    and a half-open [since, until) ts window (None = open end). Each row
    folds identity + signals + settlement; unsettled rollouts are absent.
    Never raises on a missing ledger (-> [])."""
    since, until = window if window else (None, None)
    out: list[dict] = []
    for f in _fold_rows(read(ws)):
        if f.get("settlement") is None:
            continue
        if kind is not None and f.get("kind") != kind:
            continue
        ts = str(f.get("settlement", {}).get("settled_ts")
                 or f.get("ts") or "")
        if since and ts and ts < str(since):
            continue
        if until and ts and ts >= str(until):
            continue
        out.append(dict(f, band=(f.get("settlement") or {}).get("band")))
    out.sort(key=lambda r: (str(r.get("ts") or ""), str(r.get("rollout_id"))))
    return out


def pending_settlement(ws) -> list[dict]:
    """Folded rows whose rollout has no settlement yet — the settlement
    engine's work queue."""
    out: list[dict] = []
    for f in _fold_rows(read(ws)):
        settlement = f.get("settlement")
        if settlement is None:
            out.append(f)
            continue
        # signals grew after the settlement landed -> re-settle candidate
        if settlement.get("signals_digest") != _signals_digest(
                f.get("signals") or []):
            out.append(f)
    return out


# --- write faces ---------------------------------------------------------------

def _sign_checked(sign, row: dict, rid: str, op: str) -> dict | None:
    """Apply the producer-injected seal, then RE-VALIDATE: the signed row
    must stay a schema-clean mapping (the lint is additive-key tolerant,
    so the channel's additive seal passes untouched). A signer that
    drops required fields or corrupts the shape gets ONE loud warn and a
    refused write — the schema-invalid-rows-refused promise holds for
    signed writes too, and the blast radius of a buggy signer is the
    producer's own append, never the ledger."""
    signed = sign(row)
    if not isinstance(signed, dict):
        warn(op, f"{rid}: sign callback returned "
                 f"{type(signed).__name__} (not a mapping) — write refused")
        return None
    errors = row_schema_lint(signed)
    if errors:
        warn(op, f"{rid}: post-sign schema violations ({'; '.join(errors)}"
                 f") — write refused")
        return None
    return signed


def record(ws, kind: str, anchor: str, signals: list[dict],
           rollout_id: str | None = None, ts: str | None = None,
           sign=None) -> dict:
    """Identity append (deduped) / signal amendment.

    - unseen rollout_id -> append the identity row (unsettled);
    - seen rollout_id, same signal set -> no-op (idempotent);
    - seen rollout_id, grown/changed signals -> append an amendment row
      carrying the FULL current signal set (last-wins fold).
    Refuses unregistered kinds and schema-invalid rows (loud result, no
    raise).

    ``sign`` is the PRODUCER-INJECTED seal step (a row->row callable,
    the learning channel's additive seal): the ledger core never seals
    on its own — a producer that owes sealed rows passes its signer and
    every row THIS call appends is sealed before the write; without it
    the write stays byte-identical legacy. The seal rides the row as an
    additive key, so the schema lint (which runs before the seal) and
    every fold/read face are untouched; the signed row is RE-VALIDATED
    after the callback (a signer that breaks the schema gets a loud
    refusal, never an append)."""
    ws = Path(ws)
    kind = str(kind or "").strip()
    anchor = str(anchor or "").strip()
    signals = [dict(s) for s in (signals or []) if isinstance(s, dict)]
    if kind not in ROLLOUT_KINDS:
        return {"appended": False,
                "reason": f"kind {kind!r} not registered "
                          f"(register_kind first; open enum)"}
    rid = rollout_id or f"{kind}/{anchor}"
    if not anchor:
        return {"appended": False, "reason": "anchor: empty"}
    row = {"rollout_id": rid, "kind": kind, "anchor": anchor,
           "ts": ts or _utc_now(), "signals": signals,
           "reward": None, "settlement": None}
    errors = row_schema_lint(row)
    if errors:
        return {"appended": False, "reason": "schema: " + "; ".join(errors)}
    existing = [r for r in read(ws) if r.get("rollout_id") == rid]
    if existing:
        last_signals = None
        for r in existing:
            if r.get("signals"):
                last_signals = r["signals"]
        if last_signals == signals:
            return {"appended": False, "reason": "duplicate: unchanged"}
        settlement = None
        for r in existing:
            if r.get("settlement") is not None:
                settlement = r["settlement"]
        row["settlement"] = settlement  # an amendment never un-settles
        row["reward"] = None if settlement is None else settlement["reward"]
        row["ts"] = existing[0].get("ts") or row["ts"]  # identity ts stable
    out_row = _row(rid, kind, anchor, row["ts"], signals,
                   row["settlement"])
    if sign is not None:
        out_row = _sign_checked(sign, out_row, rid, "ledger.record")
        if out_row is None:
            return {"appended": False,
                    "reason": "sign: post-sign validation refused"}
    ok = _cl.append(ws, "settlement", out_row)
    return {"appended": bool(ok),
            "reason": None if ok else "write failed",
            "rollout_id": rid}


def settle(ws, rollout_id: str, settlement: dict,
           ts: str | None = None, sign=None) -> dict:
    """Append the settlement amendment for one rollout (the engine's only
    write path). Idempotent: refused only when the fold already carries the
    SAME settlement over the SAME signals (a signal-set change reopens the
    rollout — DEFERRED->wake->PROVEN upgrades its band). Carries signals=[]
    so the fold keeps the identity signals. Loud result, no raise.

    ``sign`` is the producer-injected seal step (same contract as
    ``record``): the ledger core never seals on its own; the seal rides
    the appended amendment row as an additive key and the settlement
    dedupe compares the settlement BLOCK only — a sealed row dedupes
    against its unsealed predecessor exactly like an unsealed one. The
    signed row is re-validated after the callback (same refusal face as
    ``record``)."""
    ws = Path(ws)
    if not isinstance(settlement, dict):
        return {"appended": False, "reason": "settlement: not a mapping"}
    for field in ("reward", "band", "rule_id", "evidence_refs"):
        if field not in settlement:
            return {"appended": False, "reason": f"settlement: missing {field}"}
    existing = [r for r in read(ws)
                if r.get("rollout_id") == rollout_id]
    if not existing:
        return {"appended": False, "reason": "unknown rollout_id"}
    identity = existing[0]
    st = dict(settlement)
    st["signals_digest"] = _signals_digest(
        next((r.get("signals") for r in reversed(existing)
              if r.get("signals")), []))
    core = {k: v for k, v in st.items() if k != "settled_ts"}
    current = next((r.get("settlement") for r in reversed(existing)
                    if r.get("settlement") is not None), None)
    if current is not None:
        current_core = {k: v for k, v in current.items()
                        if k != "settled_ts"}
        if current_core == core:
            return {"appended": False, "reason": "duplicate: already settled"}
    st.setdefault("settled_ts", ts or _utc_now())
    # the write boundary lints BEFORE the append — a bounded
    # row at 2.01 would be rejected by the read face anyway, and a
    # write-then-hide is exactly the silent-unit bug the contract kills.
    candidate = {"rollout_id": rollout_id,
                 "kind": str(identity.get("kind")),
                 "anchor": str(identity.get("anchor")),
                 "ts": str(identity.get("ts")), "signals": [],
                 "reward": st.get("reward"), "settlement": st}
    errors = row_schema_lint(candidate)
    if errors:
        return {"appended": False,
                "reason": "schema: " + "; ".join(errors)}
    out_row = _row(rollout_id, str(identity.get("kind")),
                   str(identity.get("anchor")), str(identity.get("ts")),
                   [], st)
    if sign is not None:
        out_row = _sign_checked(sign, out_row, str(rollout_id),
                                "ledger.settle")
        if out_row is None:
            return {"appended": False,
                    "reason": "sign: post-sign validation refused"}
    ok = _cl.append(ws, "settlement", out_row)
    return {"appended": bool(ok),
            "reason": None if ok else "write failed"}


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
