# -*- coding: utf-8 -*-
"""rollout_ledger.py — THE unified rollout ledger (U1).

Owner ruling (2026-09-23): the whole RLVA reward is unified — ALL rollout
kinds share ONE accounting system. This module owns the ledger:
``<ws>/runs/rollout-ledger.jsonl``, append-only JSONL, one row schema:

    {"schema": "rollout-ledger/1",
     "rollout_id": "<kind>/<anchor>",   # identity (stable across folds)
     "kind": "task|self_distill|hybrid_distill|<registered>",
     "anchor": "C-101 | lesson-sig | item id",   # domain anchor
     "ts": "...Z",                       # identity creation time
     "signals": [{"type", "source", "value", "ts", ["advisory": true]}],
     "reward": null,                     # null until settled
     "settlement": null | {"reward", "band", "rule_id", "evidence_refs"}}

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

Locking: appends take an flock on ``runs/.rollout-ledger.lock`` (the repo's
lock-file pattern; POSIX fcntl, graceful unlocked fallback where flock is
unavailable — O_APPEND single-writes stay atomic, and CI is single-tenant).

The ONE prior interface (U4): ``settled(ws, kind=..., window=...)`` — the
Thompson/rank family reads settled rows through this call and no other
(consumed additively by compute_priors, issue 137).

Fail-open on reads (missing/dirty ledger = empty), loud on write rejections
(record/settle return a result dict, never raise into the producer).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from harness_common import utc_now_z as _utc_now
from kunglao_log import iter_jsonl

SCHEMA = "rollout-ledger/1"
LEDGER_REL = "runs/rollout-ledger.jsonl"
LOCK_REL = "runs/.rollout-ledger.lock"

# --- kinds registry (open enum, registered centrally) ----------------------
KIND_TASK = "task"
KIND_SELF_DISTILL = "self_distill"
KIND_HYBRID_DISTILL = "hybrid_distill"

ROLLOUT_KINDS: dict[str, str] = {
    KIND_TASK: "oracle-checked task rollout",
    KIND_SELF_DISTILL: "self-distillation rollout, lesson/card unit",
    KIND_HYBRID_DISTILL: "hybrid distill rollout — producer is the distill engine",
}

_WARN_LAST: dict[str, str] = {}


def warn(op: str, reason: str) -> None:
    """Rate-limited stderr WARN (the issue 276 _zof_warn pattern)."""
    if _WARN_LAST.get(op) == reason:
        return
    _WARN_LAST[op] = reason
    print(f"[kunglao-agent] rollout_ledger WARN (fail-open): "
          f"{op}: {reason}", file=sys.stderr)


def register_kind(kind: str, note: str = "") -> bool:
    """Open-enum registration. Returns False (no-op) when already
    registered — re-registration is idempotent, not an error."""
    kind = str(kind or "").strip()
    if not kind or kind in ROLLOUT_KINDS:
        return False
    ROLLOUT_KINDS[kind] = note or "(unannotated)"
    return True


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
    _lint_signals(row, errors)
    return errors


# --- IO ---------------------------------------------------------------------

def _path(ws) -> Path:
    return Path(ws) / LEDGER_REL


def _lock_path(ws) -> Path:
    return Path(ws) / LOCK_REL


def _locked_append(ws, data: bytes) -> bool:
    """Append under the ledger lock. flock (POSIX) with an unlocked
    O_APPEND fallback where fcntl is unavailable. Never raises."""
    p = _path(ws)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        lock = _lock_path(ws)
        lock.touch(exist_ok=True)
        fd = None
        try:
            import fcntl
            fd = lock.open("a", encoding="utf-8")
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
        except ImportError:
            fd = None  # Windows/CI: O_APPEND write stays atomic
        except OSError:
            fd = None
        try:
            import os
            append_fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                                0o644)
            try:
                os.write(append_fd, data)
            finally:
                os.close(append_fd)
            return True
        finally:
            if fd is not None:
                try:
                    fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
                except Exception as exc:  # noqa: BLE001 — unlock best-effort
                    warn("lock_unlock", f"{type(exc).__name__}: {exc}")
                fd.close()
    except Exception as exc:  # noqa: BLE001 — never raise into the producer
        warn("locked_append", f"{type(exc).__name__}: {exc}")
        return False


def read(ws) -> list[dict]:
    """Schema-enforced read: only rows passing row_schema_lint are signal
    (a settlement currency never half-reads a row); unparseable or
    schema-violating lines are skipped with one rate-limited WARN.
    Missing ledger -> []."""
    p = _path(ws)
    if not p.exists():
        return []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[dict] = []
    for row in iter_jsonl(text.splitlines()):
        if not isinstance(row, dict) or row_schema_lint(row):
            warn("read_dirty", "schema-violating row skipped")
            continue
        out.append(row)
    return out


def _row_bytes(rollout_id: str, kind: str, anchor: str, ts: str,
               signals: list[dict], settlement: dict | None) -> bytes:
    row = {
        "schema": SCHEMA,
        "rollout_id": rollout_id,
        "kind": kind,
        "anchor": anchor,
        "ts": ts,
        "signals": signals,
        "reward": None if settlement is None else settlement["reward"],
        "settlement": settlement,
    }
    return (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")


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

def record(ws, kind: str, anchor: str, signals: list[dict],
           rollout_id: str | None = None, ts: str | None = None) -> dict:
    """Identity append (deduped) / signal amendment.

    - unseen rollout_id -> append the identity row (unsettled);
    - seen rollout_id, same signal set -> no-op (idempotent);
    - seen rollout_id, grown/changed signals -> append an amendment row
      carrying the FULL current signal set (last-wins fold).
    Refuses unregistered kinds and schema-invalid rows (loud result, no
    raise)."""
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
    ok = _locked_append(ws, _row_bytes(
        rid, kind, anchor, row["ts"], signals, row["settlement"]))
    return {"appended": bool(ok),
            "reason": None if ok else "write failed",
            "rollout_id": rid}


def settle(ws, rollout_id: str, settlement: dict,
           ts: str | None = None) -> dict:
    """Append the settlement amendment for one rollout (the engine's only
    write path). Idempotent: refused only when the fold already carries the
    SAME settlement over the SAME signals (a signal-set change reopens the
    rollout — DEFERRED->wake->PROVEN upgrades its band). Carries signals=[]
    so the fold keeps the identity signals. Loud result, no raise."""
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
    ok = _locked_append(ws, _row_bytes(
        rollout_id, str(identity.get("kind")),
        str(identity.get("anchor")), str(identity.get("ts")),
        [], st))
    return {"appended": bool(ok),
            "reason": None if ok else "write failed"}


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
