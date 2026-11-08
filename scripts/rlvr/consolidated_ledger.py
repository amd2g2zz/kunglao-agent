#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/consolidated_ledger.py — the 4-file ledger consolidation core (issue-721).

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
    the orphan-store bug class issue-721 exists to kill): ONE warn + False;
  - flock single-writer: appends take ``.<stem>.lock`` in the file's own
    dir via the house lock-file pattern (POSIX fcntl; unlocked O_APPEND
    fallback where fcntl is unavailable — single writes stay atomic, CI
    is single-tenant);
  - identity ts lives on the rows — this module adds nothing to a row.

Compat window (issue-721 migration): writers target the consolidated file;
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
from contextlib import contextmanager
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
#: Knowledge rels resolve under the guarded root EXCEPT the ws-scoped
#: ``runs/`` rels — the historical ws-local posterior series and the
#: mined feature table (issue-1004 R2c: their writers moved to the
#: family file; the ws-local rels stay the compat window's read faces,
#: so the guarded root remains the only cross-task root resolver).
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
        # historical rows are UNSTAMPED {"ts","amount","source"}; the
        # registration lets them survive a cost-prefixed family read via
        # the pre-stamp rule and gives the migration its one-schema stamp
        "cost_events.jsonl": ("cost-event/1",),
    },
    "telemetry": {
        "runs/interventions.jsonl": ("intervention/1",),
        "runs/predictions.jsonl": ("prediction-ledger/1",),
        "runs/situation-stream.jsonl": ("situation/1",),
        # historical rows are UNSTAMPED event=dispatch rows; the
        # registration lets them survive a strategy-log-prefixed family
        # read via the pre-stamp rule and gives the migration its
        # one-schema stamp (issue-1004 R2b: the writer moved to the
        # family, new rows carry the stamp at write)
        "runs/strategy-log.jsonl": ("strategy-log/1",),
    },
    "knowledge": {
        "posterior-store.jsonl": ("posterior-store/1",),
        "marl-negative.jsonl": ("marl-negative/1",),
        # ws-scoped rels (legacy_path resolves them under the
        # WORKSPACE, not the guarded root — see the LEGACY note)
        "runs/feature-table.jsonl": ("feature-table/1",),
        # issue-1004 R2c: the ws-local credit/DTS series' pre-move
        # file — the writer moved to the family file
        "runs/posterior-store.jsonl": ("posterior-store/1",),
    },
}

#: the families whose prose/writers/readers are SWITCHED in this change.
#: Settlement/telemetry/knowledge are registered here for migration and
#: liveness but switch in their follow-up cards (issue-721 tasks.md).
SWITCHED: tuple[str, ...] = ("experience",)

#: family -> every registered stamp (liveness reports all of them; a dead
#: schema reads 0 — visible, never silently absent)
#: schemas born IN the consolidated file — no legacy rel to derive them
#: from (the case-observation rows). Registered so ``liveness()``
#: pre-seeds them at 0: a schema whose writer dies must read DEAD, never
#: be absent (an unregistered stamp is invisible).
NATIVE_SCHEMAS: dict[str, tuple[str, ...]] = {
    "experience": ("case-observation/1", "case-amendment/1",
                   # issue-796: the Φ-tree economy rows (resolution /
                   # elimination / signed clawback / calibration) are
                   # born in the consolidated experience file
                   "hypothesis-resolution/1", "hypothesis-elimination/1",
                   "phi-clawback/1", "phi-calibration/1",
                   # the strategic route choice (FIGHT/BYPASS/INVEST +
                   # propensity) is the learning feed's action face — a
                   # dead writer must read 0, never be absent
                   "strategic-action/1",
                   # the dispatch-gate reject face (issue-1005 S8): the
                   # gate's rc=2 tail appends the row the decision
                   # machine's feedback reads — a dead writer must read
                   # 0, never be absent
                   "dispatch-reject/1"),
    # issue-802: the blind settlement wire row (the settler-identity
    # liveness evidence) is born in the consolidated file
    "settlement": ("settlement-wire/1",
                   # the cost-event rows (cost_gate + the capture hook)
                   # write the settlement family directly — registered so
                   # a dead writer reads 0, never absent
                   "cost-event/1"),
    # the one evidence-gated disposition row per episode (rlvr.disposition
    # mirrors it here, so a dead writer must read 0, never be absent), its
    # bounded reward-face choice signal (rlvr.disposition_reward), and the
    # per-rollout deadline timer with its coefficient audit row
    "telemetry": ("disposition/1", "disposition-signal/1",
                  "rollout-timer/1", "rollout-budget/1",
                  # issue-1005 S7: the orphan launch-sweep's resolution
                  # row (rlvr.orphan_resolver mirrors it here — the
                  # close-path audit face; pre-seeded at 0 so a dead
                  # resolver reads DEAD, never absent)
                  "orphan-resolution/1",
                  # issue-1004 R2b: the strategy-log dispatch rows (the
                  # dispatch-gate writer) write the telemetry family
                  # directly — registered so a dead writer reads 0,
                  # never absent
                  "strategy-log/1"),
}

REGISTERED: dict[str, tuple[str, ...]] = {
    family: tuple(dict.fromkeys(
        list(s for schemas in rels.values() for s in schemas)
        + list(NATIVE_SCHEMAS.get(family, ()))))
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
        import runtime_switches  # noqa: PLC0415 — fallback path only
        env = runtime_switches.get_str(STORE_ENV).strip()
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
    root EXCEPT the ws-scoped ``runs/`` rels (the historical ws-local
    posterior series and the mined feature table — they lived per
    workspace, so their compat faces stay per workspace); every other
    family's rels are ws-relative. A ``None`` ws (the cross-task faces
    — marl, the rootless store read) cannot name a workspace, so the
    ws-scoped rels degrade to the guarded root's own sibling. THE ONLY
    PROTECTION IS ABSENCE: that sibling does not exist under the real
    guarded root, so the degraded rel reads empty. There is NO stamp
    wall here — a degraded rel's rows carry exactly the stamps its own
    prefix read admits — so pointing KUNGLAO_POSTERIOR_STORE at a
    directory that happens to hold a workspace's ``runs/`` tree would
    alias that workspace's live series into the rootless reads (an
    operator misconfiguration, not a guarded state)."""
    if family == "knowledge":
        if rel.startswith("runs/"):
            return Path(ws if ws is not None else _knowledge_root()) / rel
        return _knowledge_root() / rel
    return Path(ws) / rel


def _lock_path(p: Path) -> Path:
    return p.parent / f".{p.stem}.lock"


@contextmanager
def family_lock(ws, family: str):
    """Exclusive hold of the family file's consolidated lock — the
    mutating-but-not-appending faces (the revocation rewrite) run
    INSIDE it so a concurrent ``append`` between their read and their
    atomic write can never be lost (issue-1004 R2c review fix). The
    same lock file and fallback posture as ``_locked_append``: flock
    where available, unlocked where not (single writes stay atomic, CI
    is single-tenant). Never raises on lock failure."""
    p = family_path(ws, family)
    p.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_path(p)
    lock.touch(exist_ok=True)
    fd = None
    try:
        try:
            import fcntl
            fd = lock.open("a", encoding="utf-8")
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
            except OSError as exc:
                warn("rlvr.consolidated_ledger.lock",
                     f"{type(exc).__name__}: {exc} — unlocked hold")
                fd.close()
                fd = None
        except ImportError:
            fd = None  # Windows/CI: single-writer posture, no flock
        except OSError as exc:
            warn("rlvr.consolidated_ledger.lock",
                 f"{type(exc).__name__}: {exc} — unlocked hold")
            fd = None
        yield
    finally:
        if fd is not None:
            try:
                fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
            except Exception as exc:  # noqa: BLE001 — best-effort unlock
                warn("rlvr.consolidated_ledger.unlock",
                     f"{type(exc).__name__}: {exc}")
            fd.close()


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
    non-empty, whitespace-free STRING ``schema`` stamp is refused (ONE
    warn, False) — the multi-schema file stays attributable, and an
    unstripped stamp can never go invisible to its own filtered read.
    Fail-open: never raises into a producer (a non-serializable row is
    refused, not propagated)."""
    if family not in CONSOLIDATED:
        warn("rlvr.consolidated_ledger.append",
             f"unknown family {family!r} — row not appended")
        return False
    stamp = row.get("schema") if isinstance(row, dict) else None
    if (not isinstance(row, dict) or not isinstance(stamp, str)
            or not stamp.strip() or stamp != stamp.strip()):
        warn("rlvr.consolidated_ledger.append",
             f"refused a row without a valid <name>/N schema stamp for "
             f"{family!r} (got {stamp!r}): stamps must be non-empty, "
             f"whitespace-free strings — the issue-721 attribution contract")
        return False
    try:
        data = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        warn("rlvr.consolidated_ledger.append",
             f"row not JSON-serializable for {family!r} "
             f"({type(exc).__name__}: {exc}) — not appended")
        return False
    return _locked_append(family_path(ws, family), data)


def _read_rows(p: Path) -> list[dict]:
    """Tolerant JSONL read (absent/dirty -> what parses)."""
    if not p.is_file():
        return []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        warn("ledger_rows_read",
             f"{type(exc).__name__}: {exc} — rows read as empty")
        return []
    return [row for row in iter_jsonl(text.splitlines())
            if isinstance(row, dict)]


def _prefixes(schema_prefix: str | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(schema_prefix, str):
        return (schema_prefix,)
    return tuple(schema_prefix)


def _stamp_kept(row: dict, prefixes: tuple[str, ...] | None) -> bool:
    if prefixes is None:
        return True
    stamp = str(row.get("schema") or "")
    return any(stamp.startswith(p) for p in prefixes)


def _legacy_kept(row: dict, schemas: tuple[str, ...],
                 prefixes: tuple[str, ...] | None) -> bool:
    """A legacy (archive-window) row: a stamped row filters on its stamp;
    an UNSTAMPED row (the pre-stamp transitions archive) passes only
    when one of its rel's registered stamps matches a requested prefix —
    never leaking into another schema's read."""
    if prefixes is None:
        return True
    stamp = str(row.get("schema") or "")
    if stamp:
        return any(stamp.startswith(p) for p in prefixes)
    return any(s.startswith(p) for s in schemas for p in prefixes)


def read(ws, family: str, *,
         schema_prefix: str | tuple[str, ...] | None = None,
         include_legacy: bool = True) -> list[dict]:
    """All rows of one family, oldest first: legacy archive rows (in
    registry order — they predate the live file), then the consolidated
    rows. ``schema_prefix`` keeps a multi-schema file readable through
    its stamps (``"step-record"`` catches /1 and /2; a tuple is
    any-of). An unknown family reads [] with ONE warn (the append()
    refusal symmetry — fail-open on both faces)."""
    if family not in CONSOLIDATED:
        warn("rlvr.consolidated_ledger.read",
             f"unknown family {family!r} — no rows read")
        return []
    prefixes = None if schema_prefix is None else _prefixes(schema_prefix)
    rows: list[dict] = []
    if include_legacy:
        for rel, schemas in LEGACY.get(family, {}).items():
            for row in _read_rows(legacy_path(ws, family, rel)):
                if _legacy_kept(row, schemas, prefixes):
                    rows.append(row)
    for row in _read_rows(family_path(ws, family)):
        if _stamp_kept(row, prefixes):
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


# --------------------------------------------------------- the migration

#: the families whose migration is armed: a family is migrated only once
#: its writers/readers are switched (its card landed) — migrating an
#: unswitched family would strand its rows in a file nothing reads yet.
DEFAULT_MIGRATION: tuple[str, ...] = SWITCHED

ARCHIVE_DIR_REL = "runs/archive"


def _canonical(row: dict) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


def _stamp_row(row: dict, schemas: tuple[str, ...]) -> dict:
    """Migration stamping, deliberately timid: a row that already
    carries a schema copies verbatim; an unstamped row gets a stamp ONLY
    when its rel registers exactly ONE schema (the pre-stamp transitions
    archive) — a two-schema rel's unstamped row is copied verbatim,
    never guessed."""
    if str(row.get("schema") or "").strip():
        return row
    if len(schemas) == 1:
        return {**row, "schema": schemas[0]}
    return row


def _archive_dst(ws, archive_dir: str, family: str, rel: str,
                 src: Path) -> Path:
    """One rel's archive destination. Flat ``<archive>/<src.name>``
    where the family's rel names are unique; when two registered rels
    share a file name (the knowledge family's guarded-root
    ``posterior-store.jsonl`` and ws-scoped ``runs/posterior-store.jsonl``
    — issue-1004 R2c), the flat name would collide and the second
    migration would land ``copied-unarchived`` (rows in the family file
    AND the rel left on disk: a permanent double-count). Colliding rels
    archive under a family-qualified, path-distinct name instead."""
    name = src.name
    others = [Path(r).name for r in LEGACY.get(family, {}) if r != rel]
    if name in others:
        name = f"{family}__{rel.replace('/', '__')}"
    return Path(ws) / archive_dir / name


def _append_verbatim(target: Path, row: dict) -> bool:
    """MIGRATION-ONLY bypass of the append() stamp gate: a row whose
    stamp cannot be inferred (its rel registers multiple schemas) is
    copied VERBATIM — the archive's bytes are the truth, and history is
    never dropped. ONE loud warn names the anomaly; liveness counts the
    row under ``(no-schema)``, so it stays visible. The public append()
    contract is unchanged."""
    warn("rlvr.consolidated_ledger.migrate",
         f"copied an UNSTAMPED row verbatim into {target.name} — its rel "
         f"registers multiple schemas, no stamp can be inferred; the row "
         f"will count under {NO_SCHEMA} in liveness")
    data = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
    return _locked_append(target, data)


def _existing_counts(target: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in _read_rows(target):
        key = _canonical(row)
        counts[key] = counts.get(key, 0) + 1
    return counts


def migrate(ws, families=None, *, dry_run: bool = False,
            archive_dir: str = ARCHIVE_DIR_REL) -> dict:
    """The one-time issue-721 migration, per rel: every legacy row is
    APPENDED into the family's consolidated file (values preserved; a
    missing stamp added per ``_stamp_row``), then the rel is MOVED into
    ``<ws>/runs/archive/`` — bytes intact, never deleted, and the live
    read face can never double-count it. Idempotent: rows the target
    already carries (canonical-JSON multiset) are not re-appended, so a
    re-run appends nothing. ``dry_run`` reports without writing.
    Returns {family: {rel: {status, rows, appended, archived}}} with
    status in absent|dry-run|migrated|partial|copied-unarchived."""
    report: dict[str, dict] = {}
    for family in (families or DEFAULT_MIGRATION):
        fam: dict[str, dict] = {}
        for rel, schemas in LEGACY.get(family, {}).items():
            src = legacy_path(ws, family, rel)
            if not src.is_file():
                fam[rel] = {"status": "absent", "rows": 0, "appended": 0,
                            "archived": None}
                continue
            legacy_rows = _read_rows(src)
            stamped = [_stamp_row(row, schemas) for row in legacy_rows]
            existing = _existing_counts(family_path(ws, family))
            to_append: list[dict] = []
            for row in stamped:
                key = _canonical(row)
                if existing.get(key, 0) > 0:
                    existing[key] -= 1  # an already-copied row (re-run)
                else:
                    to_append.append(row)
            if dry_run:
                fam[rel] = {"status": "dry-run", "rows": len(legacy_rows),
                            "appended": len(to_append), "archived": None}
                continue
            results = []
            for row in to_append:
                if str(row.get("schema") or "").strip():
                    results.append(append(ws, family, row))
                else:  # the multi-schema-rel anomaly — verbatim + warn
                    results.append(_append_verbatim(family_path(ws, family),
                                                    row))
            if not all(results):
                # append-only refusal: NEVER archive a rel whose rows did
                # not fully land (a re-run retries the missing ones)
                fam[rel] = {"status": "partial", "rows": len(legacy_rows),
                            "appended": sum(1 for r in results if r),
                            "archived": None}
                continue
            dst = _archive_dst(ws, archive_dir, family, rel, src)
            if dst.exists():
                warn("rlvr.consolidated_ledger.migrate",
                     f"{dst} already exists — never overwriting an "
                     f"existing archive; {src} left in place (its rows "
                     f"are in the consolidated file)")
                fam[rel] = {"status": "copied-unarchived",
                            "rows": len(legacy_rows),
                            "appended": len(to_append), "archived": None}
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                src.replace(dst)  # a MOVE — bytes intact, never deleted
            except OSError as exc:
                warn("rlvr.consolidated_ledger.migrate",
                     f"archive move failed for {src}: "
                     f"{type(exc).__name__}: {exc} — rows are in the "
                     f"consolidated file, the legacy rel stays")
                fam[rel] = {"status": "copied-unarchived",
                            "rows": len(legacy_rows),
                            "appended": len(to_append), "archived": None}
                continue
            fam[rel] = {"status": "migrated", "rows": len(legacy_rows),
                        "appended": len(to_append), "archived": str(dst)}
        report[family] = fam
    return report
