#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/signal_arrival.py — the signal-arrival report (slice N0).

A READ-ONLY report on one workspace: how far a learning signal travelled,
counted from what is on disk. ``python scripts/rlvr/signal_arrival.py <ws>``
prints one JSON object (schema ``signal-arrival/1``) on stdout and exits 0
— also when every count is ``no data``. A workspace path that is not a
directory is a usage error (exit 64, nothing on stdout).

Seven counts under ``counts``, in the slice spec's order. Each is made of
leaves ``{"value": <number | mapping>, ...}`` or
``{"value": "no data", "reason": "..."}``; nothing under ``counts`` is
blank. 0 is a fact about a file that exists; ``no data`` names the file
that is missing, empty or unparsable.

  1. candidate_families  candidates in the sampling receipt at the first
     recorded dispatch (the ``candidates`` column of the first
     ``q-cell-obs/1`` dispatch row, else the earliest staged receipt), and
     the families of ``runs/llm-prior.json``.
  2. dispatch_decisions  decision receipts still staged in
     ``runs/.dispatch-decisions`` and the dispatch rows that reached
     ``runs/experience.jsonl`` — with the rows whose dispatch id
     ``runs/dispatch-ledger.jsonl`` also carries (the id, or else the
     claim, that a settlement matches a dispatch row by).
  3. settlement  ``attempts`` = ``banked`` + ``unmatched``: the results
     of ``q_cells.observe_settlement`` that left a trace. ``banked`` is
     the rows it appends when a pending dispatch row matched (``source``
     ``settlement``, no step kind). ``unmatched`` is its "no pending
     dispatch row" result, which appends no ledger row and is counted in
     the warn rows of ``runs/logs/kunglao-*.jsonl``. Credit rows that are
     not settlement attempts — step banks, calibration banks, amendments —
     are ``other_credit_rows``. ``deferred_credit_files`` counts the credit
     files the blind path (``settlement_wire._bank_or_defer``) leaves in
     ``runs/.dispatch-decisions`` while execution is unconfirmed; each is
     deleted once its credit is banked, so they are what is still waiting,
     not a trace of the misses.
  4. credit_rows  every ``q-cell-obs/1`` row with a numeric credit, from
     the settlement face and from the other bank faces, counted per
     dispatch id and split by whether a dispatch row carries that id.
  5. posterior  the per-action Thompson cells at the first and the last
     recorded decision (``runs/plan-receipts.jsonl``; else the current
     projection ``runs/policy-state.json``, and the report says so).
  6. hypothesis_resolution_rows  rows stamped ``hypothesis-resolution/1``
     — the ``experience:hypothesis-resolution/1`` key of
     ``consolidated_ledger.liveness``.
  7. method_lead  whether ``runs/round-strategy.json`` carries a lead. The
     seam has no ``method_lead`` field: the lead rides as the section
     titled ``dispatch-lead`` (``compose._seam_sections`` renders it).

Read-only by construction: this module imports the standard library only
and opens nothing for writing — no ledger, no lock file, no append-mode
open. It deliberately does NOT reuse ``consolidated_ledger.read`` /
``liveness`` / ``posteriors_case``: on a degraded path each of them calls
``kunglao_log.warn``, whose ledger face (``_warn_to_ledger`` ->
``emit``) appends a row to the run log of whatever workspace it finds
from the cwd and prunes old day files, and the strategy store's
``_support_material_present`` writes a marker outright. The output is
ASCII-only JSON, so the entry needs no stdio reconfiguration.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "signal-arrival/1"
NO_DATA = "no data"
RC_USAGE = 64

EXPERIENCE_REL = "runs/experience.jsonl"
LOGS_REL = "runs/logs"
DECISIONS_REL = "runs/.dispatch-decisions"
DISPATCH_LEDGER_REL = "runs/dispatch-ledger.jsonl"
LLM_PRIOR_REL = "runs/llm-prior.json"
STRATEGY_SEAM_REL = "runs/round-strategy.json"
RECEIPTS_REL = "runs/plan-receipts.jsonl"
POLICY_STATE_REL = "runs/policy-state.json"
INIT_REPORT_REL = "runs/.init-report.json"

Q_CELL_OBS = "q-cell-obs/1"
#: the two ``source`` values a credit row carries
SETTLEMENT_SOURCE = "settlement"
AMENDMENT_SOURCE = "credit-amendment"
CREDIT_SOURCES = (SETTLEMENT_SOURCE, AMENDMENT_SOURCE)
#: the step-credit faces' banks, by the ``credit_kind`` they write
STEP_KINDS = ("step", "step_calibration")
AMENDMENT_KIND = "credit_amendment"
#: the credit-row faces that are not settlement attempts, in print order
OTHER_FACES = (*STEP_KINDS, AMENDMENT_KIND)
#: what an unmatched warn row is listed under when the settlement was
#: called with an empty id (the warn text then carries ``''``)
NO_DISPATCH_ID = "(no dispatch id)"
HYPOTHESIS_RESOLUTION = "hypothesis-resolution/1"
PLAN_RECEIPT = "plan-receipt/1"
LEAD_SECTION = "dispatch-lead"

#: a staged decision receipt: <dispatch_id>-<tool_call_key>.json
#: (hooks/worker_budget_sinks._stage_method_decision); a deferred
#: credit: <id>.credit.json (settlement_wire._deferred_credit_path)
_STAGED_RECEIPT_RE = re.compile(r".+-[0-9a-f]{64}\.json$")
_DEFERRED_CREDIT_RE = re.compile(r"\.credit\.json$")
#: the warn row q_cells.observe_settlement leaves on an unmatched bank
_UNMATCHED_RE = re.compile(
    r"q_cells\.observe_settlement: no pending dispatch row for '([^']*)'")
#: the seam's lead sentence (compose._seam_sections)
_LEAD_RE = re.compile(r"method lead: prefer family (\S+) for matching states")

NOTE_CANDIDATES = (
    "0 or 1 candidate is the baseline before N1, not a fault.")
NOTE_ATTEMPTS = (
    "attempts = banked + unmatched: the results of "
    "q_cells.observe_settlement that left a trace. banked is the rows it "
    f"appends when a pending dispatch row matched (source settlement, no "
    f"step kind, in {EXPERIENCE_REL}); unmatched is its warn rows in the "
    "run log. Not a bound on the calls made, and not every call: a "
    "dispatch settled again in one process warns once, a swept day file "
    "takes its warn rows with it, a bank whose row the ledger refused is "
    "in no count here, and a step bank written without its credit_kind "
    "column reads as banked. Credit rows of the other faces (step banks, "
    "calibration banks, amendments) are other_credit_rows and are not in "
    "this sum.")
NOTE_UNMATCHED = (
    "The unmatched result of q_cells.observe_settlement appends no ledger "
    "row. The trace that stays is its warn row in the run log (counted "
    "here: at most one per process and dispatch id, and only while its day "
    "file is among the newest 30 the log keeps). While execution is "
    "unconfirmed, the blind path also writes a deferred credit file "
    "(deferred_credit_files); that file is deleted once the credit is "
    "banked, so it counts what is still waiting, not the misses so far. A "
    "dispatch settled again in a later process warns again: rows can "
    "exceed dispatch ids.")
NOTE_OTHER_FACES = (
    "Credit rows that are not settlement attempts: step and "
    "step_calibration are the step-credit faces' banks "
    "(q_cells.observe_step_credit, q_cells.observe_step_calibration), "
    "credit_amendment is q_cells.amend_settlement.")
NOTE_POSTERIOR = (
    "'after' is the cell recorded at the last decision: credit banked "
    "after it is in no cell yet.")
NOTE_LEAD = (
    f"{STRATEGY_SEAM_REL} has no method_lead field; the lead rides as the "
    f"section titled {LEAD_SECTION} (compose._seam_sections renders it).")

#: status -> the word the reason carries
_WORD = {"malformed": "unparsable", "unparsable": "unparsable",
         "unusable": "unusable"}


# ------------------------------------------------------------- read faces

def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _count(value, **extra) -> dict:
    return {"value": value, **extra}


def _no_data(reason: str, **extra) -> dict:
    return {"value": NO_DATA, "reason": reason, **extra}


def _note(files: dict, rel: str, status: str, **extra) -> None:
    files[rel] = {"status": status, **extra}


def _text_of(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _parse_jsonl(text: str) -> tuple[list, int]:
    """(object rows, malformed lines): blank lines skipped; a line that is
    not JSON, is not an object, or is nested past what the decoder can read
    counts as malformed."""
    rows, malformed = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except (ValueError, RecursionError):
            malformed += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            malformed += 1
    return rows, malformed


def _jsonl(path: Path, rel: str, files: dict) -> list:
    """Tolerant JSONL read of one ledger file; records its status."""
    if not path.exists():
        _note(files, rel, "missing")
        return []
    text = _text_of(path)
    if text is None:
        _note(files, rel, "unreadable")
        return []
    rows, malformed = _parse_jsonl(text)
    status = "read" if rows else ("malformed" if malformed else "empty")
    _note(files, rel, status, lines=len(rows) + malformed, malformed=malformed)
    return rows


def _json(path: Path, rel: str, files: dict, usable) -> object | None:
    """Tolerant read of one JSON document. ``usable(doc)`` returns why the
    document's shape cannot serve (None when it can). None when unusable."""
    if not path.exists():
        _note(files, rel, "missing")
        return None
    text = _text_of(path)
    if text is None:
        _note(files, rel, "unreadable")
        return None
    if not text.strip():
        _note(files, rel, "empty")
        return None
    try:
        doc = json.loads(text)
    except ValueError:
        _note(files, rel, "unparsable", detail="not JSON")
        return None
    except RecursionError:
        # valid JSON nested deeper than the decoder can go
        _note(files, rel, "unparsable",
              detail="nested past what the decoder can read")
        return None
    problem = usable(doc) if isinstance(doc, dict) else "not a JSON object"
    if problem:
        _note(files, rel, "unusable", detail=problem)
        return None
    _note(files, rel, "read")
    return doc


def _any_shape(doc: dict) -> None:
    return None


def _problem(files: dict, rel: str, *, kind: str = "file") -> str | None:
    """Why ``rel`` yields no data, without the path; None when it was read."""
    record = files.get(rel) or {"status": "missing"}
    status = record["status"]
    if status == "read":
        return None
    if status == "missing":
        return f"{kind} missing"
    if status == "empty":
        return "empty"
    if status in _WORD:
        detail = record.get("detail")
        if status == "malformed":
            detail = (f"{record.get('malformed', 0)} of "
                      f"{record.get('lines', 0)} lines malformed")
        return f"{_WORD[status]} ({detail})"
    return f"{status} ({record.get('detail') or 'cannot be read'})"


def _why(files: dict, rel: str, *, kind: str = "file") -> str | None:
    problem = _problem(files, rel, kind=kind)
    return f"{rel}: {problem}" if problem else None


def _state(files: dict, rel: str, *, kind: str = "file") -> str:
    """'' when ``rel`` was read, else ' (<what is wrong with it>)'."""
    problem = _problem(files, rel, kind=kind)
    return f" ({problem})" if problem else ""


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _staged_receipts(ws: Path, files: dict) -> tuple[list, list]:
    """(staged decision receipts earliest first, deferred credit files) in
    the decisions directory; records the directory's status."""
    directory = ws / DECISIONS_REL
    try:
        names = [entry.name for entry in os.scandir(directory) if entry.is_file()]
    except FileNotFoundError:
        _note(files, DECISIONS_REL, "missing")
        return [], []
    except OSError:
        _note(files, DECISIONS_REL, "unreadable")
        return [], []
    staged = sorted((name for name in names if _STAGED_RECEIPT_RE.fullmatch(name)),
                    key=lambda name: (_mtime_ns(directory / name), name))
    deferred = sorted(name for name in names if _DEFERRED_CREDIT_RE.search(name))
    _note(files, DECISIONS_REL, "read", entries=len(names),
          staged=len(staged), deferred=len(deferred))
    return staged, deferred


def _run_log_rows(ws: Path, files: dict) -> list:
    """Every parseable row of the run-log day files, oldest file first."""
    logs = ws / LOGS_REL
    if not logs.exists():
        _note(files, LOGS_REL, "missing")
        return []
    if not logs.is_dir():
        _note(files, LOGS_REL, "unreadable")
        return []
    day_files = sorted(p for p in logs.glob("kunglao-*.jsonl") if p.is_file())
    rows, malformed, unreadable = [], 0, 0
    for path in day_files:
        text = _text_of(path)
        if text is None:
            unreadable += 1
            continue
        parsed, bad = _parse_jsonl(text)
        rows.extend(parsed)
        malformed += bad
    if rows:
        status = "read"
    elif unreadable and not malformed:
        status = "unreadable"
    elif malformed or unreadable:
        status = "malformed"
    else:
        status = "empty"
    _note(files, LOGS_REL, status, day_files=len(day_files),
          lines=len(rows) + malformed, malformed=malformed,
          unreadable=unreadable)
    return rows


def _dir_count(files: dict, staged: int) -> dict:
    """A number out of the decisions directory, or why it cannot be given."""
    why = _why(files, DECISIONS_REL, kind="directory")
    return _no_data(why) if why else _count(staged)


# ------------------------------------------------------------ the ledger

def _dispatch_rows(ledger: list) -> list:
    return [row for row in ledger
            if row.get("schema") == Q_CELL_OBS and row.get("source") == "dispatch"]


def _credit_rows(ledger: list) -> list:
    """Every credit row: a numeric credit booked by any bank face."""
    return [row for row in ledger
            if row.get("schema") == Q_CELL_OBS
            and row.get("source") in CREDIT_SOURCES
            and _is_number(row.get("credit"))]


def _bank_face(row: dict) -> str:
    """The face that booked a credit row, read off the row's own columns.
    ``step`` and ``step_calibration`` are the step-credit faces' banks
    (``q_cells.observe_step_credit`` / ``observe_step_calibration``; a step
    bank may be the pool bridge's); ``credit_amendment`` is
    ``q_cells.amend_settlement``; ``settlement`` is what
    ``q_cells.observe_settlement`` appends when a pending dispatch row
    matched."""
    if row.get("source") == SETTLEMENT_SOURCE:
        kind = row.get("credit_kind")
        return kind if kind in STEP_KINDS else SETTLEMENT_SOURCE
    return AMENDMENT_KIND


def _credit_key(row: dict) -> str:
    """The identity a credit row is booked under: its dispatch id, else the
    claim (the match key of q_cells._match_pending_dispatch)."""
    for field in ("dispatch_id", "claim"):
        value = row.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return "(no dispatch id and no claim)"


def _carries(dispatches: list, key: str) -> bool:
    return any(row.get("dispatch_id") == key or row.get("claim") == key
               for row in dispatches)


# ------------------------------------------------------- 1. candidates

def _first_dispatch_candidates(ws: Path, dispatches: list, staged: list,
                               files: dict) -> dict:
    if dispatches:
        candidates = dispatches[0].get("candidates")
        if isinstance(candidates, dict):
            return _count(len(candidates), families=sorted(candidates),
                          source="ledger dispatch row")
        return _no_data("the first dispatch row carries no sampling receipt "
                        "(no candidates column)", source="ledger dispatch row")
    if not staged:
        return _no_data(
            f"no dispatch row in {EXPERIENCE_REL}"
            f"{_state(files, EXPERIENCE_REL)} and no staged receipt in "
            f"{DECISIONS_REL}{_state(files, DECISIONS_REL, kind='directory')}")
    rel = f"{DECISIONS_REL}/{staged[0]}"
    doc = _json(ws / rel, rel, files, _any_shape)
    view = doc.get("sampler_view") if doc else None
    candidates = view.get("candidates") if isinstance(view, dict) else None
    where = {"source": "staged receipt", "receipt": staged[0]}
    if isinstance(candidates, dict):
        return _count(len(candidates), families=sorted(candidates), **where)
    problem = _problem(files, rel) or "carries no candidates"
    return _no_data(f"the earliest staged receipt {staged[0]}: {problem}", **where)


def _llm_prior_usable(doc: dict) -> str | None:
    """The tolerance of ``priors.read_intake_prior``: wrong schema, no
    families or one malformed family rejects the whole document."""
    if doc.get("schema") != "llm-prior/1":
        return f"schema {doc.get('schema')!r} is not llm-prior/1"
    families = doc.get("families")
    if not isinstance(families, dict) or not families:
        return "no families in the document"
    for name, row in families.items():
        try:
            positive = float(row["alpha"]) > 0.0 and float(row["beta"]) > 0.0
        except (KeyError, TypeError, ValueError):
            positive = False
        if not positive:
            return f"family {name!r} carries no positive alpha and beta"
    return None


def _llm_prior(ws: Path, files: dict) -> dict:
    doc = _json(ws / LLM_PRIOR_REL, LLM_PRIOR_REL, files, _llm_prior_usable)
    if doc is None:
        return _no_data(_why(files, LLM_PRIOR_REL))
    families = doc["families"]
    return _count(len(families), families=sorted(families),
                  seed_source=str(doc.get("source") or "unknown"))


def _candidate_families(ws: Path, ledger: list, staged: list, files: dict) -> dict:
    return {
        "first_dispatch": _first_dispatch_candidates(
            ws, _dispatch_rows(ledger), staged, files),
        "llm_prior": _llm_prior(ws, files),
        "note": NOTE_CANDIDATES,
    }


# ------------------------------------------------- 2. dispatch decisions

def _dispatch_decisions(ws: Path, ledger: list, staged: list, files: dict) -> dict:
    dispatches = _dispatch_rows(ledger)
    if _problem(files, EXPERIENCE_REL):
        rows = _no_data(_why(files, EXPERIENCE_REL))
        without_id = dict(rows)
    else:
        identified = [row for row in dispatches
                      if isinstance(row.get("dispatch_id"), str)
                      and row["dispatch_id"].strip()]
        rows = _count(len(dispatches))
        without_id = _count(len(dispatches) - len(identified))
    return {
        "staged_receipts": _dir_count(files, len(staged)),
        "ledger_dispatch_rows": rows,
        "rows_without_dispatch_id": without_id,
        "rows_reachable_by_dispatch_id": _reachable(ws, dispatches, files),
    }


def _reachable(ws: Path, dispatches: list, files: dict) -> dict:
    """Dispatch rows whose dispatch id the dispatch ledger also carries."""
    ledger_rows = _jsonl(ws / DISPATCH_LEDGER_REL, DISPATCH_LEDGER_REL, files)
    problems = [_why(files, rel) for rel in (EXPERIENCE_REL, DISPATCH_LEDGER_REL)]
    problems = [problem for problem in problems if problem]
    if problems:
        return _no_data("; ".join(problems))
    ids = {str(row.get("dispatch_id") or "") for row in ledger_rows} - {""}
    # both sides as strings, as the line above reads the dispatch ledger: an
    # id that is a list or an object cannot enter a set membership test
    return _count(sum(1 for row in dispatches
                      if str(row.get("dispatch_id") or "") in ids))


# ---------------------------------------------------------- 3. settlement

def _unmatched(log_rows: list, files: dict) -> dict:
    why = _why(files, LOGS_REL, kind="directory")
    if why:
        return _no_data(why, note=NOTE_UNMATCHED)
    dispatch_ids = []
    for row in log_rows:
        if row.get("action") == "warn":
            found = _UNMATCHED_RE.search(str(row.get("detail") or ""))
            if found:
                # an empty id between the quotes is listed by a word: no
                # field under counts is an empty string
                dispatch_ids.append(found.group(1) or NO_DISPATCH_ID)
    return _count(len(dispatch_ids), dispatch_ids=sorted(set(dispatch_ids)),
                  source=f"{LOGS_REL}/kunglao-*.jsonl", note=NOTE_UNMATCHED)


def _settlement(ledger: list, deferred: list, log_rows: list, files: dict) -> dict:
    problem = _problem(files, EXPERIENCE_REL)
    if problem:
        banked = _no_data(_why(files, EXPERIENCE_REL))
        others = _no_data(_why(files, EXPERIENCE_REL), note=NOTE_OTHER_FACES)
    else:
        faces: dict = {}
        for row in _credit_rows(ledger):
            face = _bank_face(row)
            faces[face] = faces.get(face, 0) + 1
        banked = _count(faces.get(SETTLEMENT_SOURCE, 0))
        others = _count({face: faces[face] for face in OTHER_FACES if face in faces},
                        note=NOTE_OTHER_FACES)
    unmatched = _unmatched(log_rows, files)
    if _is_number(banked["value"]) and _is_number(unmatched["value"]):
        attempts = _count(banked["value"] + unmatched["value"], note=NOTE_ATTEMPTS)
    else:
        missing = [leaf["reason"] for leaf in (banked, unmatched)
                   if leaf["value"] == NO_DATA]
        attempts = _no_data("; ".join(missing), note=NOTE_ATTEMPTS)
    return {"attempts": attempts, "banked": banked, "unmatched": unmatched,
            "other_credit_rows": others,
            "deferred_credit_files": _dir_count(files, len(deferred))}


# -------------------------------------------------------- 4. credit rows

def _credit(ledger: list, files: dict) -> dict:
    problem = _problem(files, EXPERIENCE_REL)
    if problem:
        return {name: _no_data(_why(files, EXPERIENCE_REL)) for name in (
            "booked", "by_dispatch_id", "ids_with_dispatch_row",
            "ids_without_dispatch_row")}
    credits = _credit_rows(ledger)
    dispatches = _dispatch_rows(ledger)
    by_dispatch_id: dict = {}
    for row in credits:
        key = _credit_key(row)
        by_dispatch_id[key] = by_dispatch_id.get(key, 0) + 1
    with_row = [key for key in by_dispatch_id if _carries(dispatches, key)]
    without_row = [key for key in by_dispatch_id if key not in with_row]
    return {
        "booked": _count(len(credits)),
        "by_dispatch_id": _count(by_dispatch_id),
        "ids_with_dispatch_row": _count(len(with_row)),
        "ids_without_dispatch_row": _count(
            len(without_row), dispatch_ids=sorted(without_row)),
    }


# ----------------------------------------------------------- 5. posterior

def _numeric_cell(cell) -> dict | None:
    """{alpha, beta} as numbers — the numeric entries only; None when the
    cell carries none (policy_state.posterior_summary's rule)."""
    if not isinstance(cell, dict):
        return None
    numbers = {key: float(cell[key]) for key in ("alpha", "beta")
               if _is_number(cell.get(key))}
    return numbers or None


def _cells(receipt: dict) -> dict:
    """Per action kind, the recorded Thompson cell: the latest candidate of
    each kind wins (``policy_state.posterior_summary``'s rule)."""
    candidates = receipt.get("candidates")
    cells = {}
    for doc in candidates.values() if isinstance(candidates, dict) else ():
        if isinstance(doc, dict) and doc.get("action_kind"):
            cell = _numeric_cell(doc)
            if cell:
                cells[str(doc["action_kind"])] = cell
    return cells


def _projected_cells(ws: Path, files: dict) -> list:
    """The one state ``runs/policy-state.json`` projects (0 or 1 states)."""
    def usable(doc: dict) -> str | None:
        posterior = doc.get("posterior")
        actions = posterior.get("actions") if isinstance(posterior, dict) else None
        if not isinstance(actions, dict):
            return "no posterior in the projection"
        return None

    doc = _json(ws / POLICY_STATE_REL, POLICY_STATE_REL, files, usable)
    if doc is None:
        return []
    cells = {}
    for kind, cell in doc["posterior"]["actions"].items():
        numeric = _numeric_cell(cell)
        if numeric:
            cells[kind] = numeric
    if not cells:
        _note(files, POLICY_STATE_REL, "unusable",
              detail="no posterior cell in the projection")
        return []
    return [cells]


def _posterior(ws: Path, files: dict) -> dict:
    receipts = _jsonl(ws / RECEIPTS_REL, RECEIPTS_REL, files)
    problem = _problem(files, RECEIPTS_REL)
    if problem:
        receipt_count = _no_data(_why(files, RECEIPTS_REL))
    else:
        receipt_count = _count(sum(1 for row in receipts
                                   if row.get("schema") == PLAN_RECEIPT))
    states = []
    for row in receipts:
        cells = _cells(row)
        if row.get("schema") == PLAN_RECEIPT and cells:
            states.append(cells)
    source = RECEIPTS_REL
    if not states:
        states = _projected_cells(ws, files)
        source = POLICY_STATE_REL
    if not states:
        missing = _why(files, RECEIPTS_REL) or (
            f"{RECEIPTS_REL}: no decision carries a posterior cell")
        missing = f"{missing}; {_why(files, POLICY_STATE_REL)}"
        absent = _no_data(missing)
        return {"receipts": receipt_count, "source": NO_DATA,
                "coverage": NO_DATA, "before": absent, "after": dict(absent),
                "moved": NO_DATA, "note": NOTE_POSTERIOR}
    coverage = "current-state-only" if len(states) == 1 else "first-vs-last"
    return {"receipts": receipt_count, "source": source, "coverage": coverage,
            "before": _count(states[0]), "after": _count(states[-1]),
            "moved": states[0] != states[-1], "note": NOTE_POSTERIOR}


# ------------------------------------- 6. hypothesis-resolution rows

def _hypothesis_resolution_rows(ledger: list, files: dict) -> dict:
    problem = _problem(files, EXPERIENCE_REL)
    if problem:
        return _no_data(_why(files, EXPERIENCE_REL))
    return _count(sum(1 for row in ledger
                      if row.get("schema") == HYPOTHESIS_RESOLUTION))


# ------------------------------------------------------------ 7. the lead

def _seam_usable(doc: dict) -> str | None:
    if doc.get("schema") != "round-strategy/1":
        return f"schema {doc.get('schema')!r} is not round-strategy/1"
    if not isinstance(doc.get("sections"), list):
        return "sections is not a list"
    return None


def _lead_body(sections: list) -> str | None:
    for section in sections:
        if isinstance(section, dict) and section.get("title") == LEAD_SECTION:
            body = str(section.get("body") or "").strip()
            if body:
                return body
    return None


def _method_lead(ws: Path, files: dict) -> dict:
    doc = _json(ws / STRATEGY_SEAM_REL, STRATEGY_SEAM_REL, files, _seam_usable)
    if doc is None:
        return _no_data(_why(files, STRATEGY_SEAM_REL), note=NOTE_LEAD)
    extra = {"note": NOTE_LEAD}
    if _is_number(doc.get("round")):
        extra["round"] = doc["round"]
    body = _lead_body(doc["sections"])
    if body is None:
        return _count(0, **extra)
    found = _LEAD_RE.search(body)
    return _count(1, lead=found.group(1) if found else body.splitlines()[0], **extra)


# ------------------------------------------------- which build ran here

def _run_log_versions(log_rows: list, files: dict) -> dict:
    """The ``version`` stamps the run-log rows carry (the emitting checkout's
    git sha), in first-seen order, with the first and the last seen."""
    why = _why(files, LOGS_REL, kind="directory")
    if why:
        return _no_data(why)
    rows: dict = {}
    first = last = None
    for row in log_rows:
        version = str(row.get("version") or "unknown")
        rows[version] = rows.get(version, 0) + 1
        last = version
        if first is None:
            first = version
    if not rows:
        return _no_data(f"{LOGS_REL}: no row to read")
    return _count({"first": first, "last": last, "distinct": len(rows), "rows": rows})


def _workspace_build(ws: Path, log_rows: list, files: dict) -> dict:
    """The build labels, each a leaf: the value, or ``no data`` with the
    reason beside it — a number is read together with its label."""
    doc = _json(ws / INIT_REPORT_REL, INIT_REPORT_REL, files, _any_shape)
    version = doc.get("skill_version") if doc else None
    if isinstance(version, str) and version.strip():
        skill = _count(version.strip())
    else:
        skill = _no_data(_why(files, INIT_REPORT_REL)
                         or f"{INIT_REPORT_REL}: carries no skill_version")
    return {"init_skill_version": skill,
            "run_log_versions": _run_log_versions(log_rows, files)}


# ------------------------------------------------------------- the report

def _prune(node):
    """Drop fields whose value is an empty list: a list that names nothing is
    omitted, never emitted blank."""
    if isinstance(node, dict):
        return {key: _prune(value) for key, value in node.items()
                if not (isinstance(value, list) and not value)}
    return node


def build_report(workspace) -> dict:
    """The report for one workspace directory. Reads; writes nothing."""
    ws = Path(workspace)
    files: dict = {}
    ledger = _jsonl(ws / EXPERIENCE_REL, EXPERIENCE_REL, files)
    log_rows = _run_log_rows(ws, files)
    staged, deferred = _staged_receipts(ws, files)
    return {
        "schema": SCHEMA,
        "workspace": str(workspace),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "workspace_build": _workspace_build(ws, log_rows, files),
        "counts": _prune({
            "candidate_families": _candidate_families(ws, ledger, staged, files),
            "dispatch_decisions": _dispatch_decisions(ws, ledger, staged, files),
            "settlement": _settlement(ledger, deferred, log_rows, files),
            "credit_rows": _credit(ledger, files),
            "posterior": _posterior(ws, files),
            "hypothesis_resolution_rows": _hypothesis_resolution_rows(ledger, files),
            "method_lead": _method_lead(ws, files),
        }),
        "files": files,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="signal_arrival.py",
        description="read-only signal-arrival report on a workspace: seven "
                    "counts, each a number or \"no data\" with the reason "
                    "(slice N0)")
    ap.add_argument("workspace", help="the workspace directory to read")
    args = ap.parse_args(argv)
    ws = Path(args.workspace).expanduser()
    if not ws.is_dir():
        print(f"signal_arrival: workspace not found or not a directory: "
              f"{args.workspace}", file=sys.stderr)
        return RC_USAGE
    print(json.dumps(build_report(ws), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
