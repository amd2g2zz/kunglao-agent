#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_backlog_face.py — the #342 verify-backlog report face.

ONE report field for the heartbeat tick report: the PARTIAL-fact backlog
(count) and the oldest partial's age in heartbeat ticks. The timeliness
signal that makes verifier starvation VISIBLE even before the #342
VERIFY_STALE event fires (N ticks away is information, N ticks past is a
dispatch command).

Same shape as the h_bits / rank faces (issue #142 family): one computation
here, shared with any display consumer (statusline / resume read this
module directly), carried into runs/.heartbeat-tick.json by heartbeat_tick's
fail-open face block — a crashed face warns on the tick's stderr channel and
never fails the tick. No new tick steps, no distillation (2026-09-22 owner
restraint: verification cadence telemetry only).

The age numbers come from THE single #342 age reader
(convergence_check.partial_fact_ages) — the exact source the VERIFY_STALE
event consumes, so the telemetry and the decision can never drift.
"""
from __future__ import annotations

from pathlib import Path


def face(ws: Path) -> dict:
    """THE face: ``{"verify_backlog": {"count", "max_age_ticks"}}``.

    count         — number of PARTIAL facts in facts/_INDEX.md
    max_age_ticks — the stalest partial's age in ticks (None when the
                    backlog is empty or no partial has a readable date)

    Fail-open: any read/compute failure degrades to the zero face
    (count 0 / age None) — telemetry never blocks the loop it observes.
    """
    backlog: dict = {"count": 0, "max_age_ticks": None}
    try:
        from convergence_check import partial_fact_ages  # noqa: PLC0415
        rows = partial_fact_ages(Path(ws))
    except Exception:  # noqa: BLE001 — a report face never fails the tick
        return {"verify_backlog": backlog}
    backlog["count"] = len(rows)
    ages = [r["age_ticks"] for r in rows
            if isinstance(r.get("age_ticks"), (int, float))]
    if ages:
        backlog["max_age_ticks"] = round(max(ages), 1)
    return {"verify_backlog": backlog}


if __name__ == "__main__":  # pragma: no cover - manual inspection helper
    import json
    import sys
    print(json.dumps(face(Path(sys.argv[1])), indent=2))
