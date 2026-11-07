# -*- coding: utf-8 -*-
"""rlvr/orphan_resolver.py — the orphan launch-sweep resolver (issue-1005 S7).

The end-of-run sweep (``incremental_reward.sweep_orphan_launches``,
issue-654 1-F1) only ever WARNED about launch stashes whose (claim,
action_type) never produced a transitions row — the return value had no
consumer, so a launch stash without a transition stayed an orphan
forever (the issue-1005 audit: the loop acts but never closes). This
module is the consumer: ``resolve(ws, orphans)`` takes the sweep's
return value at the close path and finishes every orphan with

  1. ONE ``orphan-resolution/1`` audit row in the TELEMETRY family (the
     same audit face ``disposition/1`` rides; registered in
     ``consolidated_ledger.NATIVE_SCHEMAS`` so a dead resolver reads 0,
     never absent) citing the stash path + sha256;
  2. a classification from the stash CONTENT only, through the EXISTING
     disposition vocabulary (``rlvr.disposition.DISPOSITIONS`` — never a
     redefined word, derived lazily at first use): a chosen action key
     inside (``a`` — the pre-1-F2 legacy shape without ``attempt_id``
     included) -> ATTEMPTED_EXHAUSTED; no action key at all -> INFRA;
  3. a QUARANTINE move to ``runs/orphan-archive/<name>.json`` — an
     explicit move, bytes intact, NEVER an unlink (user evidence is
     never deleted) and never ``runs/archive/`` (that name is scheduled
     for deletion by the schema-cutover slice);

and refuses (row only, stash STAYS) when

  - the claim's register status is present and not TERMINAL
    (status_defs) — the live settle may still consume the stash, so
    quarantine would strand it (a claim ABSENT from the register is not
    known to be open and resolves normally);
  - the stash doc is not launch state at all (a parked orchestrator
    envelope — the 1-F3 wall: foreign envelopes are never consumed and
    never moved out of the namespace their wake reader scans).

Producer-seam shape (the ``disposition_producer`` precedent): rows are
derived from already-written surfaces only; per-object cage (one bad
stash is ONE warn, the others still resolve); idempotent re-run —
SEQUENTIAL passes only, not a concurrency guarantee (concurrent
resolvers can race the check-then-append; a reservation, out of slice
scope). The row identity is (claim, action_type, stash_sha256): a stash
already carrying its resolution row never gains a duplicate, and a heal
pass re-attempts only the quarantine move. ``archived_to`` names the
quarantine destination the resolution targets: between a failed move
and its heal the stash still sits at its original path (evidence_refs
names it), and the next close pass completes the move without
duplicating the row. Fail-open: a broken workspace resolves nothing and
never raises into the caller.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rlvr import consolidated_ledger
from rlvr import disposition

#: the row schema stamp (registered in consolidated_ledger.NATIVE_SCHEMAS
#: under telemetry — the close-path audit face)
SCHEMA = "orphan-resolution/1"

#: the quarantine namespace (an EXPLICIT orphan archive — never
#: runs/archive/, the name the schema-cutover slice deletes)
ARCHIVE_DIR = "runs/orphan-archive"

#: the warn trace (ONE implementation, the canonical kunglao_log face)
OP = "rlvr.orphan_resolver"

#: the derived-ts floor (a stash with no timestamped content; the
#: disposition_producer precedent)
_TS_FLOOR = "1970-01-01T00:00:00Z"


def _warn(reason: str) -> None:
    """The module's ONE warn face. The kunglao_log import resolves at
    CALL time (the sweep-face pattern): a module-top from-import would
    pin the pre-patch function and blind every monkeypatch warn
    recorder the tests use."""
    from kunglao_log import warn  # noqa: PLC0415 — call-time resolve
    warn(OP, reason)


def _vocab(name: str) -> str:
    """One disposition word, resolved through the EXISTING vocabulary at
    FIRST USE — never at import: a vocabulary drift must not make the
    whole rlvr package unimportable, so the derivation defers to the
    first ``resolve()`` call and a drift surfaces as ONE warn inside the
    per-stash cage instead of an import-time raise."""
    if name not in disposition.DISPOSITIONS:
        raise ValueError(f"{name!r} left the disposition vocabulary")
    return name


#: first-use derivation cache (the words are stable vocabulary members;
#: the laziness is the fail-open contract, not a perf device)
_VOCAB: dict[str, str] = {}


def _word(name: str) -> str:
    """The lazy holder face (fix 4 of the L2 review): import never
    raises; the vocabulary check runs on first use inside resolve()."""
    word = _VOCAB.get(name)
    if word is None:
        word = _VOCAB[name] = _vocab(name)
    return word


# ------------------------------------------------------------- pure faces

def _launch_schema() -> str:
    """The launch-stash schema stamp from its single source (lazy — the
    import keeps this module leaf-light and cycle-safe)."""
    from rlvr import incremental_reward  # noqa: PLC0415 — lazy
    return incremental_reward.LAUNCH_SCHEMA


def _is_foreign(doc: object, launch_schema: str) -> bool:
    """The 1-F3 wall, mirrored from the settle face: a doc bearing any
    ``status`` field or a foreign schema stamp is NOT launch state (the
    live shape: an orchestrator PARKED envelope with a wake plan parked
    in the stash namespace)."""
    if not isinstance(doc, dict):
        return False
    schema = doc.get("schema")
    return "status" in doc or (
        isinstance(schema, str) and bool(schema) and schema != launch_schema)


def _has_attempt_evidence(doc: object) -> bool:
    """Real launch evidence: a chosen action key — the route WAS picked
    and the launch went out. A recorded attempt id is NOT required: the
    pre-1-F2 legacy stash shape (``a`` without ``attempt_id``) is a real
    attempt the settle face still honors."""
    return isinstance(doc, dict) and bool(str(doc.get("a") or "").strip())


def _classify(doc: object) -> tuple[str | None, str]:
    """(disposition, reason) from the stash content — pure. The caller
    handles the refusals (open claim, foreign envelope) BEFORE calling
    this, so both branches here quarantine."""
    if _has_attempt_evidence(doc):
        return (_word("ATTEMPTED_EXHAUSTED"),
                "launch attempt evidence present (the action key rides "
                "the stash) — the settle never fired")
    return (_word("INFRA"),
            "no action key in the stash — nothing was ever launched "
            "through it (infra residue, not an attempt)")


def _row_ts(doc: object) -> str:
    """The identity ts derived from the stash's own content (the
    producer-seam rule: no clock in the row builder)."""
    ts = doc.get("ts") if isinstance(doc, dict) else None
    return str(ts or "").strip() or _TS_FLOOR


def _rel(ws: Path, p: Path) -> str:
    """Workspace-relative posix path (the row cites workspace evidence);
    an outside path is kept verbatim (the rules-table precedent)."""
    try:
        return p.resolve().relative_to(ws.resolve()).as_posix()
    except (ValueError, OSError):
        return str(p)


# --------------------------------------------------------------- hosts

def _read_register(ws: Path) -> dict[str, str]:
    """claim id -> register status (the tolerant producer read). An
    ABSENT register is the normal register-less workspace (silent {});
    a PRESENT-but-unreadable register is ONE loud warn + {} — nothing is
    then known to be open (fail-open posture, but not silent)."""
    import ws_yaml  # noqa: PLC0415 — leaf face, import-light
    p = ws / "claim-register.yaml"
    if not p.is_file():
        return {}
    try:
        doc = ws_yaml.yaml.safe_load(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError,
            ws_yaml.yaml.YAMLError) as exc:
        _warn(f"claim register unreadable ({type(exc).__name__}: {exc}) "
              f"— the open-claim gate is skipped for this pass")
        return {}
    rows = (doc or {}).get("claims") if isinstance(doc, dict) else None
    out: dict[str, str] = {}
    for row in rows or []:
        if isinstance(row, dict):
            cid = str(row.get("id") or "").strip()
            if cid:
                out[cid] = str(row.get("status") or "").strip().upper()
    return out


def _resolved_identities(ws: Path) -> dict[tuple[str, str, str], dict]:
    """The already-written resolution rows, keyed by row identity — the
    idempotency face (a SEQUENTIAL re-run never writes a duplicate row;
    concurrent resolvers are a noted reservation, not built here)."""
    try:
        rows = consolidated_ledger.read(ws, "telemetry",
                                        schema_prefix=SCHEMA)
    except Exception as exc:  # noqa: BLE001 — telemetry, never the close
        _warn(f"resolution read failed: {exc}")
        return {}
    return {(str(r.get("claim") or ""),
             str(r.get("action_type") or "dispatch"),
             str(r.get("stash_sha256") or "")): r
            for r in rows if isinstance(r, dict)}


#: destinations whose occupied-state already warned this process (the
#: occupied case is a stable, expected state — byte-identical stashes
#: restored after their quarantine — not a transient failure, so it
#: must not re-warn every close pass within a process)
_OCCUPIED_WARNED: set[str] = set()

#: quarantine outcomes ("moved" | "occupied" | "failed")
_MOVED = "moved"
_OCCUPIED = "occupied"
_FAILED = "failed"


def _quarantine(ws: Path, path: Path) -> str:
    """Move the stash into the quarantine namespace. Bytes intact, never
    an unlink, never an overwrite (the migration face's rule: an
    existing archive entry is never clobbered — the stash stays at its
    original path).

    Returns ``"moved"`` on success, ``"occupied"`` when the destination
    entry already exists (a stable state — ONE targeted trace per
    process, never the transient-failure warn), ``"failed"`` on a
    transient move error (ONE warn; the next close pass heals it)."""
    dst = ws / ARCHIVE_DIR / path.name
    try:
        if dst.exists():
            if str(dst) not in _OCCUPIED_WARNED:
                _OCCUPIED_WARNED.add(str(dst))
                _warn(f"{dst} already exists — the quarantine entry is "
                      f"kept (never overwritten) and {path.name} is "
                      f"left in place")
            return _OCCUPIED
        dst.parent.mkdir(parents=True, exist_ok=True)
        path.replace(dst)  # a MOVE — bytes intact, never deleted
        return _MOVED
    except OSError as exc:
        _warn(f"quarantine move failed for {path.name}: "
              f"{type(exc).__name__}: {exc} — the row is on the "
              f"ledger, the next close pass heals the move")
        return _FAILED


def _build_row(ws: Path, *, claim: str, action_type: str, doc: object,
               path: Path, sha: str, word: str | None, refused: bool,
               reason: str, archived_to: str | None) -> dict:
    """One ``orphan-resolution/1`` row. ``evidence_refs`` cites the
    stash path and ``stash_sha256`` pins the exact bytes — the audit
    trail survives the quarantine move (the sha verifies the archived
    copy wherever it lives)."""
    return {
        "schema": SCHEMA,
        "ts": _row_ts(doc),
        "claim": claim,
        "action_type": action_type,
        "disposition": word,
        "refused": refused,
        "reason": reason,
        "evidence_refs": [_rel(ws, path)],
        "stash_sha256": sha,
        "archived_to": archived_to,
    }


def _refuse(ws: Path, *, claim: str, action_type: str, doc: object,
            path: Path, sha: str, reason: str, summary: dict) -> None:
    """Write the refused-with-reason row; the stash STAYS in place."""
    row = _build_row(ws, claim=claim, action_type=action_type, doc=doc,
                     path=path, sha=sha, word=None, refused=True,
                     reason=reason, archived_to=None)
    if consolidated_ledger.append(ws, "telemetry", row):
        summary["refused"].append(claim)
    else:
        summary["failed"].append(f"{claim}: resolution row refused")


def _load_stash(path: Path, claim: str,
                summary: dict) -> tuple[str, object] | None:
    """(sha256, parsed doc) for one stash file — the cage face: an
    unreadable or corrupt stash is ONE warn + a skipped entry (the file
    stays in place), and the caller moves on to the next orphan."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        _warn(f"{path.name}: unreadable stash ({type(exc).__name__}: "
              f"{exc}) — caged, left in place")
        summary["skipped"].append(claim)
        return None
    sha = hashlib.sha256(raw).hexdigest()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        _warn(f"{path.name}: corrupt stash doc (not JSON) — caged, "
              f"left in place")
        summary["skipped"].append(claim)
        return None
    return sha, doc


def _heal(ws: Path, path: Path, claim: str, summary: dict) -> None:
    """The already-resolved face: only the quarantine move may need
    healing (the row landed but a previous move failed), or the
    destination is stably occupied (a restored copy — skipped, never a
    failing heal)."""
    outcome = _quarantine(ws, path)
    if outcome == _MOVED:
        summary["resolved"] += 1
    elif outcome == _OCCUPIED:
        summary["skipped"].append(claim)
    else:
        summary["failed"].append(f"{claim}: quarantine move still "
                                 f"failing (see the warn trace)")


def _refuse_if(ws: Path, *, claim: str, action_type: str, doc: object,
               path: Path, sha: str, register: dict[str, str],
               summary: dict) -> bool:
    """The two refusal walls (row only, stash STAYS). True when a
    refusal row was written:
    the register gate — a claim PRESENT with a non-terminal status (a
    blank status included — an unknown context never reads as closed)
    keeps its stash for the live settle; a claim absent from the
    register is not known to be open and resolves normally;
    the 1-F3 wall — a foreign envelope is never moved out of the
    namespace its wake reader scans."""
    if claim in register:
        import status_defs  # noqa: PLC0415 — the one status vocabulary
        status = register[claim]
        if status not in status_defs.TERMINAL:
            _refuse(ws, claim=claim, action_type=action_type, doc=doc,
                    path=path, sha=sha,
                    reason=(f"claim still open in the register "
                            f"(status={status or 'blank'}) — the stash "
                            f"stays for the live settle"),
                    summary=summary)
            return True
    if _is_foreign(doc, _launch_schema()):
        _refuse(ws, claim=claim, action_type=action_type, doc=doc,
                path=path, sha=sha,
                reason=("stash doc is not launch state (foreign "
                        "envelope, the 1-F3 wall) — never consumed, "
                        "never moved"),
                summary=summary)
        return True
    return False


def _resolve_one(ws: Path, orphan: object, register: dict[str, str],
                 resolved: dict[tuple[str, str, str], dict],
                 summary: dict) -> None:
    """Finish one orphan (the per-object cage body). The caller's cage
    turns any escape into ONE failed entry + warn."""
    entry = orphan if isinstance(orphan, dict) else {}
    claim = str(entry.get("claim") or "").strip()
    action_type = (str(entry.get("action_type") or "").strip()
                   or "dispatch")
    path = Path(str(entry.get("path") or ""))
    if not claim:
        _warn("an orphan entry without a claim — skipped")
        summary["skipped"].append(path.name or "?")
        return
    if not path.is_file():
        # consumed between the sweep and the resolve (the idempotent
        # face): a stale sweep entry is a silent skip, not an error
        summary["skipped"].append(claim)
        return
    loaded = _load_stash(path, claim, summary)
    if loaded is None:
        return
    sha, doc = loaded

    existing = resolved.get((claim, action_type, sha))
    if existing is not None:
        # the row exists — never a duplicate. A refused row means the
        # stash must stay; otherwise only the quarantine move may need
        # healing (the row landed but a previous move failed).
        if existing.get("refused") is True:
            summary["skipped"].append(claim)
            return
        _heal(ws, path, claim, summary)
        return

    if _refuse_if(ws, claim=claim, action_type=action_type, doc=doc,
                  path=path, sha=sha, register=register, summary=summary):
        return

    word, reason = _classify(doc)
    row = _build_row(ws, claim=claim, action_type=action_type, doc=doc,
                     path=path, sha=sha, word=word, refused=False,
                     reason=reason, archived_to=_rel(
                         ws, ws / ARCHIVE_DIR / path.name))
    if not consolidated_ledger.append(ws, "telemetry", row):
        # the row is the audit trail — quarantine without one would be
        # unattributed evidence movement; the stash stays for a retry
        summary["failed"].append(f"{claim}: resolution row refused")
        return
    outcome = _quarantine(ws, path)
    if outcome == _MOVED:
        summary["resolved"] += 1
    elif outcome == _OCCUPIED:
        summary["skipped"].append(claim)
    else:
        summary["failed"].append(f"{claim}: quarantine move failed "
                                 f"(the next close pass heals it)")


def resolve(ws, orphans) -> dict:
    """Resolve the orphan launch stashes the sweep found (fail-open).

    ``orphans`` is ``incremental_reward.sweep_orphan_launches``'s return
    value. Returns ``{"resolved": n, "refused": [claims], "skipped":
    [names], "failed": [reasons]}``. Never raises into the caller: the
    per-object cage turns one bad stash into ONE warn + a skipped
    entry, and the outer guard turns an unexpected escape into ONE warn
    with the summary so far.
    """
    summary: dict = {"resolved": 0, "refused": [], "skipped": [],
                     "failed": []}
    try:
        ws = Path(ws)
        register = _read_register(ws)
        resolved = _resolved_identities(ws)
        for orphan in orphans or []:
            try:
                _resolve_one(ws, orphan, register, resolved, summary)
            except Exception as exc:  # noqa: BLE001 — one stash's cage
                name = (str(orphan.get("claim") or "")
                        if isinstance(orphan, dict) else "?")
                summary["failed"].append(
                    f"{name}: {type(exc).__name__}: {exc}")
                _warn(f"{name}: {type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001 — never raise into the close
        _warn(f"resolve failed ({type(exc).__name__}: {exc}) — "
              f"no stash was resolved")
    return summary
