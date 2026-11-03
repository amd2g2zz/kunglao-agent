# -*- coding: utf-8 -*-
"""state/statusline_feed.py — the rl-v2 statusline feed face (#914).

The session statusline must reflect the rl-v2 architecture (owner
directive 2026-10-30), not the old loop's state. This face renders the
loop's live state from the unified ledger ALONE into one deterministic
dict (``loop-statusline/1``):

    {schema, lap, laps, rollout_id, task, method_family, phase,
     p_level, p_trend, pool, trust_band}

  - lap/laps: the lap axis from BOTH ledger stamps — the telemetry
    rows' explicit ``lap`` column (the v3 driver's axis) and the
    #913 loop's pinned rollout-id convention ``...-lap<N>`` (the
    DecisionLoop's structural stamp on every action/result row);
    current = the max seen;
  - rollout_id: the LAST trajectory row's rollout (append order is
    recency — the ledger is append-only);
  - task: the belief snapshot's ``current_goal`` (the #903 face —
    never re-derived here);
  - method_family / phase: the latest action row's ``params`` (the
    #913 dispatch receipt's own tags);
  - p_level / p_trend: the P(s) trajectory's last level + the last
    ΔP's sign (rising/flat/falling), from the #915 ``loop_summary``
    series — the trend is the ledger's own deltas, never a clock;
  - pool: the episode pool's size (the #824 episodic-memory pool);
  - trust_band: the latest observation row's ``confidence_band`` (the
    #433/#799 ladder band the current credit trades under).

Posture (the state faces' two-sided rule):

- DETERMINISTIC from the ledger alone — no wall clock in the content
  (the content-hash pin; the same ledger renders a byte-identical
  feed);
- fail-CLOSED on garbage — a schema-valid-but-garbage row (a
  non-mapping ``params``, a non-finite ΔP) raises ValueError AT THE
  FACE (a poisoned feed must never read as recorded state);
- fail-OPEN on the environment — a missing ledger is the STABLE
  degraded view (all-None segments, zero pool), never a crash.

MATERIALIZATION: the deployed scripts tree cannot import the
experiments tree (the #865 restructure + the #467 dep-surface gate),
so the FILE is the only bridge (the policy-state precedent):
``write_feed`` lands the feed atomically at
``runs/.loop-statusline.json``; ``scripts/statusline_snapshot.py``
embeds it verbatim (pure disk observation); the renderer is a dumb
view. The production write trigger is the #913 loop's belief seam
(once per lap).
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Mapping

_HERE = Path(__file__).resolve().parent.parent          # learning-loop/
_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
for _p in (_HERE, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rlvr import episode_pool  # noqa: E402 — the pool read face
from rlvr import q_cells  # noqa: E402 — the trajectory read face
from state import belief as _belief  # noqa: E402
from state import telemetry as _telemetry  # noqa: E402

#: the feed's schema stamp (the receipt discipline)
SCHEMA = "loop-statusline/1"

#: the materialized feed's home (the snapshot reads THIS file — the
#: single source crosses the deploy boundary as a file, never an import)
REL = "runs" / Path(".loop-statusline.json")

#: the closed trend vocabulary (the renderer's arrow table keys)
TRENDS = ("rising", "flat", "falling")

#: the #913 loop's rollout-id lap stamp (`ro-<task>-lap<N>`) — the
#: DecisionLoop path's structural lap axis (the v3 driver stamps the
#: telemetry ``lap`` column instead; the feed reads BOTH)
_LAP_SUFFIX = re.compile(r"-lap(\d+)$")


def _fail(field: str, why: str) -> ValueError:
    return ValueError(f"state.statusline_feed.{field}: {why}")


def _wall_row(row: Any, where: str) -> Mapping:
    """The fail-closed row wall: a ledger row that IS read must be a
    mapping — anything else is structural garbage (raise, never
    guess)."""
    if not isinstance(row, Mapping):
        raise _fail(where, f"row must be a mapping, got {type(row).__name__}")
    return row


def _wall_params(params: Any, where: str) -> Mapping:
    if params is None:
        return {}
    if not isinstance(params, Mapping):
        raise _fail(where, "params must be a mapping")
    return params


def _clean(value: Any) -> str | None:
    """A segment value: a non-empty string or None (the absent face —
    never a placeholder)."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _latest_action_tags(rows: list) -> tuple[str | None, str | None,
                                             str | None, str | None,
                                             list[int]]:
    """Scan the trajectory rows in append order; the LAST row carrying
    each tag wins (recency = the ledger's own order). Returns
    (rollout_id, method_family, phase, trust_band, lap_ids) where
    lap_ids are the rollout-id lap stamps in append order."""
    rollout_id: str | None = None
    method_family: str | None = None
    phase: str | None = None
    trust_band: str | None = None
    lap_ids: list[int] = []
    for row in rows:
        _wall_row(row, "trajectory")
        rid = _clean(row.get("rollout_id"))
        if rid is not None:
            rollout_id = rid
            m = _LAP_SUFFIX.search(rid)
            if m is not None:
                lap_ids.append(int(m.group(1)))
        params = _wall_params(row.get("params"), "trajectory.params")
        family = _clean(params.get("method_family"))
        if family is not None:
            method_family = family
        tag = _clean(params.get("phase"))
        if tag is not None:
            phase = tag
        band = _clean(row.get("confidence_band"))
        if band is not None:
            trust_band = band
    return rollout_id, method_family, phase, trust_band, lap_ids


def _p_face(p_series: list, delta_series: list) -> tuple[float | None,
                                                          str | None]:
    """The P level (the series' last point) + the trend (the LAST
    delta's sign). Fewer than one point is the honest absent face
    (None/None) — never a fabricated 0. A non-finite delta is poison
    (the wall)."""
    if delta_series:
        last = delta_series[-1]
        if not math.isfinite(last):
            raise _fail("delta_series", f"non-finite ΔP {last!r} — a "
                                        "poisoned transition fingerprint")
        trend = "rising" if last > 0 else ("falling" if last < 0 else "flat")
    else:
        trend = None
    level = p_series[-1] if p_series else None
    if level is not None and not math.isfinite(level):
        raise _fail("p_series", f"non-finite P level {level!r}")
    return level, trend


def feed(ws) -> dict:
    """The ``loop-statusline/1`` dict — deterministic from the ledger
    alone. Absent layers read the stable degraded face; garbage rows
    raise at the wall."""
    ws = Path(ws)
    summary = _telemetry.loop_summary(ws)
    rows = q_cells.trajectory_rows(ws)
    rollout_id, method_family, phase, trust_band, lap_ids = \
        _latest_action_tags(rows)
    level, trend = _p_face(summary["p_series"], summary["delta_series"])
    laps = sorted({int(l) for l in summary["laps"]} | set(lap_ids))
    return {
        "schema": SCHEMA,
        "lap": laps[-1] if laps else None,
        "laps": laps,
        "rollout_id": rollout_id,
        "task": _clean(_belief.build_snapshot(ws).get("current_goal")),
        "method_family": method_family,
        "phase": phase,
        "p_level": level,
        "p_trend": trend,
        "pool": {"episodes": len(episode_pool.list_episodes(ws))},
        "trust_band": trust_band,
    }


def write_feed(ws) -> Path:
    """Materialize the feed atomically (tmp + replace, the
    heartbeat_touch F2 discipline) at ``runs/.loop-statusline.json``.
    Content-stable: the same ledger rewrites byte-identical bytes (no
    ts — the content-hash pin). Fail-closed: a wall raise propagates —
    the loop lap fails loudly on a poisoned ledger, the statusline's
    own fail-open lives snapshot-side (the renderer never sees a
    half-written file: atomic replace)."""
    ws = Path(ws)
    doc = feed(ws)
    out = ws / REL
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n",
                   encoding="utf-8")
    tmp.replace(out)
    return out
