# -*- coding: utf-8 -*-
"""rlvr/censoring.py — censored posterior semantics (issue #955, links 4+5+12).

An EXOGENOUS env death (rlvr.interruption's ``censored_env``) is a
CENSORED sample for the direction posterior: it produces NO observation
— no collapse, no reinforcement, never failure mass. Censoring only
removes information; it never adds wrong signal (#955 link 7 — the
anti-bias property absorbed by construction).

The three faces:

  observe_censored(ws, direction, reason)
      Appends a ``censored: true`` row to the direction state and
      NOTHING else — the whole point is the posterior's silence. The
      row lands in ``runs/direction-state.jsonl`` (schema
      ``direction-censor/1``), the workspace-state persistence the
      cross-run memory link (#955 link 12) demands: censor streaks and
      censored rows survive the process.

  censor_streaks(ws) / frozen(ws, direction)
      The racing-interaction face (#955 link 5): K CONSECUTIVE censored
      events on one direction FREEZE its budget — never eliminate, stop
      investing. The streak is a TRAILING run derived from the
      append-only rows (never a mutable counter that could drift from
      its own log — the banked_mass posture). Any live (non-censored)
      event on the direction breaks the run. The freeze predicate is
      what the racing/elimination faces consume; elimination stays
      forbidden here by design (a frozen direction can still return via
      the economics face / L3 expansion, #955 link 8).

  posterior_observations(rows)
      THE #954 INTEGRATION SEAM: the direction-posterior layer is #954's
      (not yet landed), so the censoring semantics live over a minimal
      direction-state schema. When #954 lands, its observation feed
      MUST route through this filter — censored rows drop out BEFORE any
      posterior update (a censored sample updates nothing: no Beta
      draw, no Normal-Gamma increment, no failure mass). The row's
      ``direction`` field is the join key #954's store keys on; the
      schema stamp ``direction-censor/1`` is additive to whatever
      stream #954 consolidates.

``observe_live`` is the seam's counterpart: #954's real observation
path appends a ``censored: false`` row (breaking the streak) — kept as
an explicit minimal face so the freeze semantics are complete and
testable before #954 exists.

Fail-open: reads tolerate an absent/dirty file ([]); appends refuse
loudly (ONE warn) but never raise into the producer.
"""
from __future__ import annotations

import json
from pathlib import Path

from kunglao_log import iter_jsonl, warn  # canonical warn: ONE implementation

from rlvr import learning_seal as _seal  # #799: the row seal

#: the minimal direction-state ledger (workspace-relative; #954 owns the
#: real direction-posterior store — this file is the seam substrate)
DIRECTION_STATE_REL = "runs/direction-state.jsonl"
SCHEMA = "direction-censor/1"

#: consecutive censored events that freeze a direction's budget
#: (#955 link 5; the K is a module constant — the racing faces tune it
#: via the predicate argument, never by editing the log)
CENSOR_FREEZE_K = 3

CENSORED_TRUE = True


def _append_row(ws, row: dict) -> bool:
    try:
        path = Path(ws) / DIRECTION_STATE_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        row = _seal.sign_row(row)  # #799: same seal discipline as q-cell rows
        data = (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8")
        import os
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return True
    except OSError as exc:
        warn("rlvr.censoring", f"append failed: {type(exc).__name__}: {exc}")
        return False


def _now() -> str:
    from harness_common import utc_now_z  # noqa: PLC0415
    return utc_now_z()


def state_rows(ws) -> list[dict]:
    """Every direction-censor/1 row, append order (fail-open read). The
    learner read face: armed, only seal-valid rows survive — a forged
    state row can never drive ``frozen()`` (same trust posture as the
    q-cell fold)."""
    path = Path(ws) / DIRECTION_STATE_REL
    if not path.is_file():
        return []
    out: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8",
                               errors="replace").splitlines()
        rows = [row for row in iter_jsonl(lines,
                                          source="censoring.state_rows")
                if isinstance(row, dict) and row.get("schema") == SCHEMA]
        out = _seal.trusted_rows(rows, op="rlvr.censoring.state_rows")
    except OSError as exc:
        warn("rlvr.censoring", f"read failed: {exc}")
        return []
    return out


# ------------------------------------------------------------- the faces

def observe_censored(ws, direction: str, reason: str) -> dict:
    """One censored event on a direction: the ``censored: true`` row and
    NOTHING else — no posterior update, no failure mass, no elimination.
    The reason rides the row (auditability: the worker sees WHY the
    sample was silent)."""
    direction = str(direction or "").strip()
    if not direction:
        raise ValueError("rlvr.censoring: direction must be non-empty")
    row = {
        "schema": SCHEMA,
        "ts": _now(),
        "direction": direction,
        "censored": True,
        "reason": str(reason or ""),
    }
    return {"appended": _append_row(ws, row), "row": row}


def observe_live(ws, direction: str) -> dict:
    """One LIVE observation marker (#954 seam): breaks the direction's
    trailing censor run. No reward semantics — the posterior update is
    #954's; this row only says "the direction produced a real sample"."""
    direction = str(direction or "").strip()
    if not direction:
        raise ValueError("rlvr.censoring: direction must be non-empty")
    row = {
        "schema": SCHEMA,
        "ts": _now(),
        "direction": direction,
        "censored": False,
        "reason": None,
    }
    return {"appended": _append_row(ws, row), "row": row}


def censor_streak(rows: list[dict], direction: str) -> int:
    """The direction's TRAILING consecutive-censored run (pure over the
    rows — the no-parallel-tally posture). A live row resets the run;
    rows of OTHER directions are invisible."""
    direction = str(direction or "").strip()
    streak = 0
    for row in rows:
        if str(row.get("direction") or "").strip() != direction:
            continue
        if row.get("censored") is True:
            streak += 1
        else:
            streak = 0
    return streak


def censor_streaks(ws) -> dict[str, int]:
    """Per-direction trailing censor streaks over the whole state file
    (the racing faces' read face; direction -> streak, only non-zero
    streaks listed)."""
    out: dict[str, int] = {}
    for row in state_rows(ws):
        d = str(row.get("direction") or "").strip()
        if not d:
            continue
        if row.get("censored") is True:
            out[d] = out.get(d, 0) + 1
        else:
            out[d] = 0
    return {d: n for d, n in out.items() if n > 0}


def frozen(ws, direction: str, *, k: int = CENSOR_FREEZE_K) -> bool:
    """The freeze predicate the racing/elimination faces consume: the
    direction's trailing censor streak reached K. NEVER an elimination
    signal — a frozen direction stops receiving budget; it keeps its
    posterior (what it had) and can return via the economics face or L3
    expansion (#955 links 7/8)."""
    return censor_streak(state_rows(ws), direction) >= max(1, int(k))


def posterior_observations(rows: list[dict]) -> list[dict]:
    """THE #954 SEAM FILTER: the observation feed any direction-posterior
    consumer MUST route through — ``censored: true`` rows drop out HERE,
    before any update (a censored sample updates nothing, by
    construction, not by consumer discipline)."""
    return [r for r in (rows or [])
            if isinstance(r, dict) and r.get("censored") is not True]
