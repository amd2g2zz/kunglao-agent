#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/consolidated_ledger.py — the 4-file ledger consolidation core
(#721; the compat window retired by #1004).

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

Since #1004 every family has switched whole: there is ONE home per
family and no dual read — ``read()`` returns the consolidated rows
only. The pre-#1004 legacy rels (transitions / q-cell-log / step-ledger
/ evidence-credit / rollout-ledger / attributed-waste / cost_events /
interventions / predictions / situation-stream / strategy-log /
posterior-store / marl-negative / feature-table) are retired names: no
production module reads or writes them, and the one-time retire CLI
(``scripts/consolidate_ledgers.py --retire-legacy``) is the only place
their names survive — it appends a legacy rel's rows into the family
file (in the order the old dual-read produced them), verifies, then
DELETES the rel.

Row contracts (unchanged, enforced HERE):

  - append-only: no rewrite path exists in this module;
  - every row carries a ``<name>/N`` schema stamp — ``append`` REFUSES a
    stampless row (an unattributable row inside a multi-schema file is
    the orphan-store bug class issue-721 exists to kill): ONE warn + False;
  - flock single-writer: appends take ``.<stem>.lock`` in the file's own
    dir via the house lock-file pattern (POSIX fcntl; unlocked O_APPEND
    fallback where fcntl is unavailable — single writes stay atomic, CI
    is single-tenant). This is the ONLY writer guard on every family
    path — the movers' per-module lock rels retired with their IO;
  - identity ts lives on the rows — this module adds nothing to a row.

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

#: schemas born IN a consolidated file — no writer module declares them
#: (the case-observation rows, the Φ-tree economy, the blind settlement
#: wire, the disposition rows, the deadline timer). Registered so
#: ``liveness()`` pre-seeds them at 0: a schema whose writer dies must
#: read DEAD, never be absent (an unregistered stamp is invisible).
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
                   "strategic-action/1"),
    # issue-802: the blind settlement wire row (the settler-identity
    # liveness evidence) is born in the consolidated file
    "settlement": ("settlement-wire/1",),
    # the one evidence-gated disposition row per episode (rlvr.disposition
    # mirrors it here, so a dead writer must read 0, never be absent), its
    # bounded reward-face choice signal (rlvr.disposition_reward), and the
    # per-rollout deadline timer with its coefficient audit row
    "telemetry": ("disposition/1", "disposition-signal/1",
                  "rollout-timer/1", "rollout-budget/1"),
}

#: family -> the schema stamps the family's writer modules declare (the
#: #1004 writer registry — each mover registered its stamp here; a new
#: family writer registers its stamp here too). The consolidated append
#: enforces A stamp; this registry is the LIVENESS declaration: every
#: declared schema reports a count (0 = dead-but-visible alarm).
WRITER_SCHEMAS: dict[str, tuple[str, ...]] = {
    # the already-switched #721 experience writers
    "experience": ("transition/1", "q-cell-obs/1",
                   "step-record/1", "step-record/2",
                   "evidence-item/1", "credit-amendment/1"),
    # #1004 R2a: the rollout ledger, the attributed-waste pricing and
    # the cost telemetry (cost rows carried no stamp pre-#1004 — the
    # stamp is the migration's single structural addition)
    "settlement": ("rollout-ledger/1", "attributed-waste/1",
                   "cost-event/1", "distill-rollout/1"),
    # #1004 R2b: predictions, the situation stream, interventions and
    # the strategy dispatch log (strategy rows carried no stamp
    # pre-#1004); pricing's probe-price faces round the family out
    "telemetry": ("prediction-ledger/1", "situation/1",
                  "intervention/1", "strategy-log/1",
                  "probe-price/1", "unknown-set/1"),
    # #1004 R2c: the posterior store (cross-task + workspace credit
    # series), the MARL class negatives and the mined feature table
    "knowledge": ("posterior-store/1", "marl-negative/1",
                  "feature-table/1"),
}

#: family -> every registered stamp (liveness reports all of them; a dead
#: schema reads 0 — visible, never silently absent)
REGISTERED: dict[str, tuple[str, ...]] = {
    family: tuple(dict.fromkeys(
        list(NATIVE_SCHEMAS.get(family, ()))
        + list(WRITER_SCHEMAS.get(family, ()))))
    for family in FAMILIES
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


def _lock_path(p: Path) -> Path:
    return p.parent / f".{p.stem}.lock"


def _locked_append(p: Path, data: bytes) -> bool:
    """Append one chunk under the file lock. flock (POSIX) with an
    unlocked O_APPEND fallback where fcntl is unavailable (the house
    lock-file pattern). Never raises."""
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


def read(ws, family: str, *,
         schema_prefix: str | tuple[str, ...] | None = None) -> list[dict]:
    """All rows of one family from the consolidated file, oldest first.
    There is no dual read (#1004): a pre-retirement legacy rel on disk
    is invisible to every reader until the retire CLI moves its rows.
    ``schema_prefix`` keeps a multi-schema file readable through its
    stamps (``"step-record"`` catches /1 and /2; a tuple is any-of). An
    unknown family reads [] with ONE warn (the append() refusal
    symmetry — fail-open on both faces)."""
    if family not in CONSOLIDATED:
        warn("rlvr.consolidated_ledger.read",
             f"unknown family {family!r} — no rows read")
        return []
    prefixes = None if schema_prefix is None else _prefixes(schema_prefix)
    return [row for row in _read_rows(family_path(ws, family))
            if _stamp_kept(row, prefixes)]


def liveness(ws) -> dict[str, int]:
    """Per-schema row counts across the consolidated files (all four
    families; the legacy rels are retired names — nothing else
    contributes). Every registered schema reports a count — a dead
    schema reads 0 (visible), never silently absent; foreign/unknown
    stamps and unstamped rows count under their own keys. Keys:
    ``"<family>:<schema>"``."""
    counts: dict[str, int] = {}
    for family in FAMILIES:
        for stamp in REGISTERED.get(family, ()):
            counts[f"{family}:{stamp}"] = 0
    for family in FAMILIES:
        for row in read(ws, family, schema_prefix=None):
            stamp = str(row.get("schema") or "") or NO_SCHEMA
            key = f"{family}:{stamp}"
            counts[key] = counts.get(key, 0) + 1
    return counts


if __name__ == "__main__":  # pragma: no cover — library module
    print(__doc__)
