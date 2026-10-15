#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/consolidated_ledger.py — the 4-file ledger consolidation core (#721).

Twelve-plus JSONL ledgers fragmented ONE logical stream (what happened /
how it closed / what was observed / what is known) across 12+ physical
files. The determinism wall never lived in file separation — it lives in
the ROW contracts (append-only, ``<name>/N`` schema stamps, identity ts,
flock), and ``runs/step-ledger.jsonl`` already hosted step-record/1 AND
step-record/2 in one file (the precedent). This module is the core:

    runs/experience.jsonl   WHAT HAPPENED    (the learning feed)
    runs/settlement.jsonl   HOW IT CLOSED    (the credit)
    runs/telemetry.jsonl    WHAT WAS OBSERVED (audit)
    knowledge-store.jsonl   WHAT IS KNOWN    (cross-task, guarded root)

Row contracts (unchanged, now enforced HERE):

  - append-only: no rewrite path exists in this module;
  - every row carries a ``<name>/N`` schema stamp — ``append`` REFUSES a
    stampless row (an unattributable row inside a multi-schema file is
    the orphan-store bug class #721 exists to kill): ONE warn + False;
  - flock single-writer: appends take ``.<stem>.lock`` in the file's own
    dir via the house lock-file pattern (POSIX fcntl; unlocked O_APPEND
    fallback where fcntl is unavailable — single writes stay atomic, CI
    is single-tenant);
  - identity ts lives on the rows — this module adds nothing to a row.

Compat window (#721 migration): writers target the consolidated file;
readers ride ``read()`` — legacy archive rows first (chronology: the
archive predates the live file), then the consolidated rows, with an
optional stamp filter. After ``migrate()`` moves a legacy rel into
``runs/archive/``, its rows arrive through the consolidated file only —
never double-counted.

Fail-open + warn, house style: reads tolerate absent/dirty files ([]);
appends refuse loudly (ONE warn) but never raise into a producer.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from kunglao_log import iter_jsonl, warn  # canonical warn: ONE implementation

FAMILIES = ("experience", "settlement", "telemetry", "knowledge")

#: family -> consolidated file (ws-relative, except knowledge — see below)
CONSOLIDATED: dict[str, str] = {
    "experience": "runs/experience.jsonl",
    "settlement": "runs/settlement.jsonl",
    "telemetry": "runs/telemetry.jsonl",
    "knowledge": "knowledge-store.jsonl",  # under the guarded cross-task root
}

#: the knowledge family's rel (resolved under the guarded root, not ws/)
KNOWLEDGE_REL = CONSOLIDATED["knowledge"]

#: family -> {legacy rel: the schema stamps rows in that rel may carry}.
#: The registry is documentation AND the migration/read source: read()
#: keeps an UNSTAMPED legacy row only when a registered stamp of that
#: rel matches the requested prefix (the pre-stamp transitions archive).
#: Knowledge rels resolve under the guarded root except the historical
#: ws-scoped runs/feature-table.jsonl (see the #721 follow-up card).
LEGACY: dict[str, dict[str, tuple[str, ...]]] = {
    "experience": {
        "runs/transitions.jsonl": ("transition/1",),
        "runs/q-cell-log.jsonl": ("q-cell-obs/1",),
        "runs/step-ledger.jsonl": ("step-record/1", "step-record/2"),
        "runs/evidence-credit.jsonl": ("evidence-item/1",
                                       "credit-amendment/1"),
    },
    "settlement": {
        "runs/rollout-ledger.jsonl": ("rollout-ledger/1",),
        "runs/attributed-waste.jsonl": ("attributed-waste/1",),
        "cost_events.jsonl": (),  # historical {"ts","amount","source"} rows
    },
    "telemetry": {
        "runs/interventions.jsonl": ("intervention/1",),
        "runs/predictions.jsonl": ("prediction-ledger/1",),
        "runs/situation-stream.jsonl": ("situation/1",),
        "runs/strategy-log.jsonl": (),  # historical event= rows, unstamped
    },
    "knowledge": {
        "posterior-store.jsonl": ("posterior-store/1",),
        "marl-negative.jsonl": ("marl-negative/1",),
        "runs/feature-table.jsonl": ("feature-table/1",),
    },
}

#: the families whose prose/writers/readers are SWITCHED in this change.
#: Settlement/telemetry/knowledge are registered here for migration and
#: liveness but switch in their follow-up cards (#721 tasks.md).
SWITCHED: tuple[str, ...] = ("experience",)

#: family -> every registered stamp (liveness reports all of them; a dead
#: schema reads 0 — visible, never silently absent)
REGISTERED: dict[str, tuple[str, ...]] = {
    family: tuple(dict.fromkeys(s for schemas in rels.values()
                                for s in schemas))
    for family, rels in LEGACY.items()
}

NO_SCHEMA = "(no-schema)"

#: the guarded cross-task root's env override (mirrors
#: strategy_store.STORE_ENV — the root single source is strategy_store)
STORE_ENV = "KUNGLAO_POSTERIOR_STORE"


def _knowledge_root() -> Path:
    """The guarded cross-task root: strategy_store.store_root() when
    importable (the single source), else the same two-step mirror
    (env override, then this package's patterns dir)."""
    try:
        from rlvr import strategy_store as _ss  # noqa: PLC0415 — lazy (cycle)
        return _ss.store_root()
    except Exception as exc:  # noqa: BLE001 — fail-open mirror, loud
        warn("rlvr.consolidated_ledger",
             f"strategy_store root unavailable ({type(exc).__name__}: "
             f"{exc}) — environment-mirror fallback")
        env = os.environ.get(STORE_ENV, "").strip()
        if env:
            return Path(env)
        return Path(__file__).resolve().parent / "patterns"


def family_path(ws, family: str) -> Path:
    """The consolidated file for one family. knowledge ignores ws (the
    store is cross-task by design — same file for every workspace)."""
    if family == "knowledge":
        return _knowledge_root() / KNOWLEDGE_REL
    return Path(ws) / CONSOLIDATED[family]


def legacy_path(ws, family: str, rel: str) -> Path:
    """One legacy archive rel. Knowledge rels resolve under the guarded
    root; every other family's rels are ws-relative."""
    if family == "knowledge":
        return _knowledge_root() / rel
    return Path(ws) / rel


def _lock_path(p: Path) -> Path:
    return p.parent / f".{p.stem}.lock"


def _locked_append(p: Path, data: bytes) -> bool:
    """Append one chunk under the file lock. flock (POSIX) with an
    unlocked O_APPEND fallback where fcntl is unavailable (the
    rollout-ledger pattern). Never raises."""
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        lock = _lock_path(p)
        lock.touch(exist_ok=True)
        fd = None
        try:
            import fcntl
            fd = lock.open("a", encoding="utf-8")
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
            except OSError as exc:
                warn("rlvr.consolidated_ledger.lock",
                     f"{type(exc).__name__}: {exc} — unlocked append")
                fd.close()
                fd = None
        except ImportError:
            fd = None  # Windows/CI: O_APPEND write stays atomic
        except OSError as exc:
            warn("rlvr.consolidated_ledger.lock",
                 f"{type(exc).__name__}: {exc} — unlocked append")
            fd = None
        try:
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
                except Exception as exc:  # noqa: BLE001 — best-effort unlock
                    warn("rlvr.consolidated_ledger.unlock",
                         f"{type(exc).__name__}: {exc}")
                fd.close()
    except OSError as exc:
        warn("rlvr.consolidated_ledger.append",
             f"{p}: {type(exc).__name__}: {exc}")
        return False


def append(ws, family: str, row: dict) -> bool:
    """Append one row to the family's consolidated file (flock-guarded,
    append-only). The ROW CONTRACT is enforced here: a row without a
    non-empty ``schema`` stamp is refused (ONE warn, False) — the
    multi-schema file stays attributable. Fail-open: never raises."""
    if family not in CONSOLIDATED:
        warn("rlvr.consolidated_ledger.append",
             f"unknown family {family!r} — row not appended")
        return False
    if not isinstance(row, dict) or not str(row.get("schema") or "").strip():
        warn("rlvr.consolidated_ledger.append",
             f"refused a stampless row for {family!r}: every row in a "
             f"consolidated file must carry a <name>/N schema stamp "
             f"(the #721 row contract)")
        return False
    data = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
    return _locked_append(family_path(ws, family), data)


def _read_rows(p: Path) -> list[dict]:
    """Tolerant JSONL read (absent/dirty -> what parses)."""
    if not p.is_file():
        return []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [row for row in iter_jsonl(text.splitlines())
            if isinstance(row, dict)]


def _stamp_kept(row: dict, schema_prefix: str | None) -> bool:
    if schema_prefix is None:
        return True
    return str(row.get("schema") or "").startswith(schema_prefix)


def _legacy_kept(row: dict, schemas: tuple[str, ...],
                 schema_prefix: str | None) -> bool:
    """A legacy (archive-window) row: a stamped row filters on its stamp;
    an UNSTAMPED row (the pre-stamp transitions archive) passes only
    when one of its rel's registered stamps matches the requested
    prefix — never leaking into another schema's read."""
    if schema_prefix is None:
        return True
    stamp = str(row.get("schema") or "")
    if stamp:
        return stamp.startswith(schema_prefix)
    return any(s.startswith(schema_prefix) for s in schemas)


def read(ws, family: str, *, schema_prefix: str | None = None,
         include_legacy: bool = True) -> list[dict]:
    """All rows of one family, oldest first: legacy archive rows (in
    registry order — they predate the live file), then the consolidated
    rows. ``schema_prefix`` keeps a multi-schema file readable through
    its stamps (e.g. ``"step-record"`` catches /1 and /2)."""
    rows: list[dict] = []
    if include_legacy:
        for rel, schemas in LEGACY.get(family, {}).items():
            for row in _read_rows(legacy_path(ws, family, rel)):
                if _legacy_kept(row, schemas, schema_prefix):
                    rows.append(row)
    for row in _read_rows(family_path(ws, family)):
        if _stamp_kept(row, schema_prefix):
            rows.append(row)
    return rows


def liveness(ws) -> dict[str, int]:
    """Per-schema row counts across the consolidated files AND any
    legacy rels still on disk (the compat window). Every registered
    schema reports a count — a dead schema reads 0 (visible), never
    silently absent; foreign/unknown stamps and unstamped rows count
    under their own keys. Keys: ``"<family>:<schema>"``."""
    counts: dict[str, int] = {}
    for family in FAMILIES:
        for stamp in REGISTERED.get(family, ()):
            counts[f"{family}:{stamp}"] = 0
    for family in FAMILIES:
        for row in read(ws, family, schema_prefix=None, include_legacy=True):
            stamp = str(row.get("schema") or "") or NO_SCHEMA
            key = f"{family}:{stamp}"
            counts[key] = counts.get(key, 0) + 1
    return counts
