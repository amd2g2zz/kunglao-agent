#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/consolidated_ledger.py — the 4-file ledger consolidation core (issue-721).

Twelve-plus JSONL ledgers fragmented ONE logical stream (what happened /
how it closed / what was observed / what is known) across 12+ physical
files. The determinism wall never lived in file separation — it lives in
the ROW contracts (append-only, ``<name>/N`` schema stamps, identity ts,
flock), and the pre-consolidation step ledger already hosted
step-record/1 AND step-record/2 in one file (the precedent). This module
is the core:

    runs/experience.jsonl   WHAT HAPPENED    (the learning feed)
    runs/settlement.jsonl   HOW IT CLOSED    (the credit)
    runs/telemetry.jsonl    WHAT WAS OBSERVED (audit)
    runs/posterior/knowledge-store.jsonl  WHAT IS KNOWN (workspace-local
                                          store — cross-project off)

Row contracts (unchanged, now enforced HERE):

  - append-only: no rewrite path exists in this module;
  - every row carries a ``<name>/N`` schema stamp — ``append`` REFUSES a
    stampless row (an unattributable row inside a multi-schema file is
    the orphan-store bug class issue-721 exists to kill): ONE warn + False;
  - single-writer appends take ``.<stem>.lock`` in the file's own dir via
    the house lock-file pattern: the knowledge family takes the strict
    platform lock it shares with the revocation rewrite and is REFUSED
    (False, one warn) when no real lock can be taken; the other families
    keep flock (POSIX fcntl) with an unlocked O_APPEND fallback where
    fcntl is unavailable (single writes stay atomic, CI is single-tenant);
  - identity ts lives on the rows — this module adds nothing to a row.

Post-cutover read contract (issue-1004 R3): the compat window is GONE.
Every writer was moved onto the family files by R2a/R2b/R2c, so
``read()`` returns exactly one consolidated file's rows — no legacy
branch, no ``include_legacy`` flag, chronology IS file order. The one
remaining legacy face is ``migrate()``: its per-rel SOURCE LIST is
explicit (``sources``), owned by the R4 retire CLI
(scripts/consolidate_ledgers.py), which appends the historical rows into
the family files and deletes the legacy rels.

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

#: family -> consolidated file (all ws-relative — the knowledge family
#: is workspace-local too: every learning store resolves inside the
#: workspace, under strategy_store.WS_STORE_REL)
CONSOLIDATED: dict[str, str] = {
    "experience": "runs/experience.jsonl",
    "settlement": "runs/settlement.jsonl",
    "telemetry": "runs/telemetry.jsonl",
    "knowledge": "runs/posterior/knowledge-store.jsonl",
}

#: the knowledge family's file name (resolved under the workspace's
#: store root — rel-based read faces resolve it through
#: strategy_store.store_root)
KNOWLEDGE_REL = "knowledge-store.jsonl"

#: family -> every registered stamp. Two origins, one contract:
#:   - schemas BORN in a consolidated file (no pre-consolidation series);
#:   - schemas whose writers were MOVED onto the family files by the
#:     issue-1004 family moves (R2a settlement / R2b telemetry / R2c
#:     knowledge) — their pre-move series land here through the R4
#:     migration carrying their original stamp.
#: ``liveness()`` pre-seeds every registered stamp at 0: a schema whose
#: writer dies must read DEAD, never be absent (an unregistered stamp is
#: invisible).
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
                   "dispatch-reject/1",
                   # the moved writers' series (issue-1004 R2a/R2b/R2c
                   # moved them onto this file; the stamps ride the
                   # migrated rows)
                   "transition/1", "q-cell-obs/1",
                   "step-record/1", "step-record/2",
                   "evidence-item/1", "credit-amendment/1",
                   # the live family writers' stamps (registered so a
                   # dead writer reads 0, never absent): the censored
                   # row (q_cells, the #955 link-12 face) and the
                   # q-cell action/result trajectory rows (q_cells'
                   # _append_v2)
                   "censored/1", "q-cell-action/1", "q-cell-result/1"),
    # issue-802: the blind settlement wire row (the settler-identity
    # liveness evidence) is born in the consolidated file
    "settlement": ("settlement-wire/1",
                   # the cost-event rows (cost_gate + the capture hook)
                   # write the settlement family directly — registered so
                   # a dead writer reads 0, never absent
                   "cost-event/1",
                   # the moved writers' series (issue-1004 R2a)
                   "rollout-ledger/1", "attributed-waste/1",
                   # the distillation attempt row (rlvr.distill_rollout
                   # — the self-distill trajectory credit feed; a dead
                   # writer must read 0, never absent)
                   "distill-rollout/1"),
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
                  "strategy-log/1",
                  # the moved writers' series (issue-1004 R2b)
                  "intervention/1", "prediction-ledger/1", "situation/1",
                  # the pricing face's probe-price row (rlvr.pricing —
                  # the issue-801-shaped probe-consumption account; a
                  # dead writer must read 0, never absent)
                  "probe-price/1"),
    # issue-1004 R2c: the posterior store's three populations (the
    # cross-task bank rows, the ws-local credit series, the DTS rows —
    # one stamp), the negative-knowledge rows, and the mined feature
    # table all live in the knowledge family file
    "knowledge": ("posterior-store/1", "marl-negative/1",
                  "feature-table/1"),
}

#: family -> every registered stamp (liveness reports all of them; a dead
#: schema reads 0 — visible, never silently absent)
REGISTERED: dict[str, tuple[str, ...]] = {
    family: NATIVE_SCHEMAS.get(family, ()) for family in FAMILIES
}

NO_SCHEMA = "(no-schema)"

#: the store root's env override (mirrors strategy_store.STORE_ENV —
#: the resolver single source is strategy_store.store_root; the override
#: is honored only when it points inside the workspace)
STORE_ENV = "KUNGLAO_POSTERIOR_STORE"


def family_path(ws, family: str) -> Path:
    """The consolidated file for one family. Every family is
    workspace-relative: the knowledge family lives under the
    workspace's own store root (cross-project off — a run touches no
    learning store outside its workspace), delegated to
    ``strategy_store.store_root(ws)`` (the single root resolver — an
    inside-workspace env override moves the family file with it). A
    workspace-less knowledge resolution cannot name a store and fails
    loud (the rootless shared-root faces retired with cross-project
    learning)."""
    if ws is None and family == "knowledge":
        raise ValueError(
            "knowledge family requires a workspace — cross-project "
            "learning is off, the store cannot resolve outside one")
    if family == "knowledge":
        from rlvr import strategy_store as _ss  # noqa: PLC0415 — lazy (cycle)
        return _ss.store_root(ws) / KNOWLEDGE_REL
    return Path(ws) / CONSOLIDATED[family]


def legacy_path(ws, family: str, rel: str) -> Path:
    """One MIGRATION-SOURCE rel. All rels resolve ws-relative: the
    knowledge family is workspace-local, so the guarded-root rels of
    the pre-cross-project era resolve under the workspace as well —
    which reads absent (a workspace never carried the global store
    inside it), making the migration a no-op for them (no cross-project
    carry-in by design; the global store file itself is simply no
    longer touched). A ``None`` ws cannot name a workspace: the
    ws-scoped ``runs/`` rels degrade to the module dir's sibling — that
    sibling does not exist as a workspace, so the degraded rel reads
    empty."""
    return Path(ws if ws is not None else
                Path(__file__).resolve().parent) / rel


def _lock_path(p: Path) -> Path:
    return p.parent / f".{p.stem}.lock"


@contextmanager
def family_lock(ws, family: str):
    """Exclusive hold of the family file's consolidated lock — the
    mutating-but-not-appending faces (the revocation rewrite) run
    INSIDE it so a concurrent ``append`` between their read and their
    atomic write can never be lost (issue-1004 R2c review fix). The
    knowledge family always takes a real lock shared with append; an
    unavailable lock refuses the rewrite. Other families retain their
    existing append-only fallback posture."""
    p = family_path(ws, family)
    p.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_path(p)
    if family == "knowledge":
        from platform_matrix import exclusive_file_lock
        with exclusive_file_lock(lock):
            yield
        return
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
    """Append one chunk under the file lock. The knowledge family takes
    the strict platform lock it shares with the revocation rewrite: when
    no real lock can be taken the append is refused (False, one warn).
    The other families keep flock (POSIX) with an unlocked O_APPEND
    fallback where fcntl is unavailable (the rollout-ledger pattern).
    Never raises."""
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        lock = _lock_path(p)
        if p.name == KNOWLEDGE_REL:
            from platform_matrix import exclusive_file_lock
            with exclusive_file_lock(lock), p.open("ab") as stream:
                stream.write(data)
            return True
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
    try:
        return _locked_append(family_path(ws, family), data)
    except ValueError as exc:  # workspace-less knowledge store — loud
        warn("rlvr.consolidated_ledger.append",
             f"{family!r}: {exc} — not appended")
        return False


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


def read(ws, family: str, *,
         schema_prefix: str | tuple[str, ...] | None = None) -> list[dict]:
    """All rows of one family, oldest first (file order — since the
    issue-1004 R3 schema cutover the consolidated file is the only
    face, so append order IS chronology). ``schema_prefix`` keeps a
    multi-schema file readable through its stamps (``"step-record"``
    catches /1 and /2; a tuple is any-of). An unknown family reads []
    with ONE warn (the append() refusal symmetry — fail-open on both
    faces)."""
    if family not in CONSOLIDATED:
        warn("rlvr.consolidated_ledger.read",
             f"unknown family {family!r} — no rows read")
        return []
    prefixes = None if schema_prefix is None else _prefixes(schema_prefix)
    try:
        path = family_path(ws, family)
    except ValueError as exc:  # workspace-less knowledge store — loud
        warn("rlvr.consolidated_ledger.read",
             f"{family!r}: {exc} — no rows read")
        return []
    return [row for row in _read_rows(path)
            if _stamp_kept(row, prefixes)]


def liveness(ws) -> dict[str, int]:
    """Per-schema row counts across the four consolidated files — the
    only faces since the issue-1004 R3 schema cutover. Every registered
    schema reports a count — a dead schema reads 0 (visible), never
    silently absent; foreign/unknown stamps and unstamped rows count
    under their own keys. Keys: ``"<family>:<schema>"``."""
    counts: dict[str, int] = {}
    for family in FAMILIES:
        for stamp in REGISTERED.get(family, ()):
            counts[f"{family}:{stamp}"] = 0
    for family in FAMILIES:
        for row in read(ws, family):
            stamp = str(row.get("schema") or "") or NO_SCHEMA
            key = f"{family}:{stamp}"
            counts[key] = counts.get(key, 0) + 1
    return counts


# --------------------------------------------------------- the migration

def _canonical(row: dict) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


def _stamp_row(row: dict, schemas: tuple[str, ...]) -> dict:
    """Migration stamping, deliberately timid: a row that already
    carries a schema copies verbatim; an unstamped row gets a stamp ONLY
    when its rel registers exactly ONE schema — a two-schema rel's
    unstamped row is copied verbatim, never guessed."""
    if str(row.get("schema") or "").strip():
        return row
    if len(schemas) == 1:
        return {**row, "schema": schemas[0]}
    return row


def _archive_dst(ws, archive_dir: str, family: str, rel: str,
                 src: Path, family_rels) -> Path:
    """One rel's archive destination. Flat ``<archive>/<src.name>``
    where the family's rel names are unique; when two registered rels
    share a file name (the knowledge family's guarded-root store rel
    and its ws-scoped ``runs/`` sibling are ONE such colliding-basename
    pair), the
    flat name would collide and the second migration would land
    ``copied-unarchived`` (rows in the family file AND the rel left on
    disk: a permanent double-count). Colliding rels archive under a
    family-qualified, path-distinct name instead."""
    name = src.name
    others = [Path(r).name for r in family_rels if r != rel]
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


def migrate(ws, families=None, *,
            sources: dict[str, dict[str, tuple[str, ...]]],
            dry_run: bool = False,
            archive_dir: str = "runs/archive") -> dict:
    """The one-time issue-721 migration, per rel: every source row is
    APPENDED into the family's consolidated file (values preserved; a
    missing stamp added per ``_stamp_row``), then the rel is MOVED into
    ``<ws>/runs/archive/`` — bytes intact, never deleted, and the live
    read face can never double-count it. Idempotent: rows the target
    already carries (canonical-JSON multiset) are not re-appended, so a
    re-run appends nothing. ``dry_run`` reports without writing.
    ``sources`` is the EXPLICIT per-family source list (family ->
    {rel: the stamps its rows may carry}) — the registry lives in the
    R4 CLI surface (scripts/consolidate_ledgers.LEGACY_SOURCES) since
    the issue-1004 R3 schema cutover deleted the in-core compat
    window; ``families`` narrows the run (None = every family).
    Returns {family: {rel: {status, rows, appended, archived}}} with
    status in absent|dry-run|migrated|partial|copied-unarchived."""
    report: dict[str, dict] = {}
    for family in (families or FAMILIES):
        fam: dict[str, dict] = {}
        family_rels = sources.get(family, {})
        for rel, schemas in family_rels.items():
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
            dst = _archive_dst(ws, archive_dir, family, rel, src,
                               family_rels)
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
                        "appended": len(to_append),
                        "archived": str(dst)}
        report[family] = fam
    return report
