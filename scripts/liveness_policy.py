#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""liveness_policy.py — THE single source for liveness/staleness thresholds (#597).

v0.1.3 root-cause survey finding: 10+ ``_MINUTES`` constants were hardcoded
across hooks/ and scripts/ with zero shared source — at least 4 duplicated
value-pairs drifted independently (a comment in event_taxonomy.py even
restated a hard "20" that silently rots when the value changes).

ADJUDICATION (v0.1.3 plan §D row #597): the VALUES stay exactly as they were
(20/30/35 are each deliberate with their own rationale — this module does NOT
unify numbers; changing any value needs its own adjudication). What changed
is the SOURCE: every former definition site imports from here, so a future
value change lands in exactly one place with its rationale attached.

Import conventions (unchanged by this module):
  - scripts/ consumers: plain ``import liveness_policy`` / ``from
    liveness_policy import X`` (sys.path[0] is scripts/ when run as a script;
    pytest.ini adds scripts/ to pythonpath).
  - hooks/ consumers: hooks run with their own dir at sys.path[0], so they
    insert the scripts dir first (worker_budget_core / session_start /
    lib_kunglao._env_layout precedent — missing module = broken install,
    not a degraded mode, #444 posture: hooks/ and scripts/ ship together).

Drift guard: tests/test_liveness_policy_597.py fails on any bare
``X_MINUTES = <int>`` assignment reintroduced in a consumer file.

Pure stdlib. Constants only, no state, no imports of sibling modules
(safe for hooks/ and scripts/ alike — no cycle in either direction).
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Worker-status staleness (the stuck-family threshold, value 20 everywhere)
# ---------------------------------------------------------------------------

# hooks/lib_kunglao.py (#444): an in-progress worker-status file older than
# this (mtime) with no status transition = stuck. The ONE canonical
# worker-liveness parse point (scan_active_workers / iter_worker_states);
# scripts-side consumers (event_taxonomy STUCK_SECONDS, kunglao_resume,
# external_kicker FRESH_WORKER_MINUTES) all mirror this same 20.
STUCK_MINUTES = 20

# scripts/lib_kunglao.py (#43 drift detection D3): an in-progress status file
# YOUNGER than this = the session is still moving (signature rotation vs
# frozen loop). Same 20 as STUCK_MINUTES — freshness and stuckness are the
# two sides of one worker-liveness line.
WORKER_PROGRESS_MINUTES = 20

# scripts/external_kicker.py (D3): worker status files fresher than this
# block a kick (session mid-dispatch — kicking a live dispatch would
# duplicate work). Mirrors STUCK_MINUTES by design: a worker the stuck
# scan would call stuck is exactly one the kicker may kick.
FRESH_WORKER_MINUTES = 20

# scripts/worker_death.py + hooks/lib_kunglao.scan_active_workers (#11): the
# DEATH line — a non-terminal worker-status file silent for 2x STUCK_MINUTES
# is GONE (API disconnect / crash: no more writes, ever), not merely stuck.
# Adjudicated as 2x, not a free constant: the 20-40 band stays backtrack_gate
# territory (#38 — the worker may still be poked back to life), while one
# full stuck interval of extra silence past the stuck line is the evidence
# that nothing will ever write again. Composes with #595/#607: the stuck scan
# carries the dead flag; the stuck action (#11 resume contract) consumes it.
DEAD_WORKER_MINUTES = 2 * STUCK_MINUTES

# ---------------------------------------------------------------------------
# Heartbeat staleness (the monitoring-liveness threshold, value 35)
# ---------------------------------------------------------------------------

# scripts/heartbeat.py: a 5-min cron tick should refresh .heartbeat.json
# continuously; > 35 min stale (5-min interval + jitter margin) means the
# MONITORING itself is not running — not merely a quiet session. kunglao_resume
# reuses the same predicate for its NEXT-dispatch prediction (HEARTBEAT_STALE_
# MINUTES is the same 35, kept as a distinct name because its consumer-facing
# meaning is "would the resume gate pass", not "is monitoring alive").
STALE_MINUTES = 35
HEARTBEAT_STALE_MINUTES = 35

# ---------------------------------------------------------------------------
# Heartbeat tick continuity (#754 E2)
# ---------------------------------------------------------------------------

# scripts/heartbeat.py (#754): the tick interval assumed when .heartbeat.json
# carries no interval_min (heartbeat_register writes 5; the /loop default is
# 5m). The continuity gate doubles it as the maximum tolerated gap between
# adjacent ticks (one missed tick is jitter; two is a dead cron). Named _MIN
# not _MINUTES to stay outside the #597 bare-assignment drift-guard family —
# this value is NEW in #754, not a surveyed pre-existing constant.
TICK_INTERVAL_DEFAULT_MIN = 5

# scripts/heartbeat.py (#4): the continuity verdict reads a SLIDING WINDOW,
# not the whole durable tick sidecar - a tick participates when it is among
# the last CONTINUITY_WINDOW_TICKS OR within the last CONTINUITY_WINDOW_HOURS;
# older ticks stay on disk (append-only, nothing deleted) but stop voting.
# Sized to the real cadence above (5m): 12 ticks ~= 1 hour of normal
# operation, so ordinary jitter never trips it, while any historical stall
# stops counting within ~a day (24h age bound) instead of re-rejecting the
# workspace forever after one mid-life gap.
CONTINUITY_WINDOW_TICKS = 12
CONTINUITY_WINDOW_HOURS = 24

# ---------------------------------------------------------------------------
# Hook-activation TTL (the enforcement-liveness threshold, value 30)
# ---------------------------------------------------------------------------

# scripts/hook_activation.py: activation is short-lived BY DESIGN — the
# orchestrator must renew every 30 min or the hooks sleep, which makes
# activation a real liveness signal (a stale activation from a dead/abandoned
# session cannot keep firing hooks). external_kicker.ACTIVATION_TTL_MINUTES
# is the SAME 30 (D6): the tick interval must stay below it or the
# TTL-expiry→next-tick gap silently closes the gates.
DEFAULT_TTL_MINUTES = 30
ACTIVATION_TTL_MINUTES = 30

# ---------------------------------------------------------------------------
# Env-state freshness (the environment-liveness threshold, value 30)
# ---------------------------------------------------------------------------

# hooks/worker_budget_core.py (#475): runs/env-state.json older than this =
# env drift — the dispatch gate REJECTS at 2x this line (worker_budget_sinks),
# kunglao-monitor uses the same 30 as its advisory drift threshold. One
# threshold, two severities — the value must not fork between them.
ENV_STATE_TTL_MINUTES = 30

# ---------------------------------------------------------------------------
# Kicker / renewal margins (value 10)
# ---------------------------------------------------------------------------

# scripts/external_kicker.py (D1): both heartbeat signals stale beyond this
# (in addition to DEFAULT_TICK_INTERVAL_MIN=15): 15+10 = worst-case detection
# ≤ 25 min < 30-min TTL → the kick always lands BEFORE the old activation
# expires (no silent window, with margin). NOT the heartbeat 35 — this is
# the kicker's own dead-session bound, deliberately tighter.
DEFAULT_STALE_MINUTES = 10

# scripts/heartbeat_tick.py (#365): renewal-margin early warning — a tick
# chain that is ALIVE but cadence-mismatched with the 30-min TTL renews
# just before expiry (the one silent-gate case no other anomaly surfaces).
# 10 min = a third of the TTL: enough lead time to act before the NEXT tick
# misses the renewal entirely.
RENEW_MARGIN_LOW_MINUTES = 10

# ---------------------------------------------------------------------------
# Mission-ledger V_m sampling gate (#8)
# ---------------------------------------------------------------------------

# scripts/heartbeat_tick.py _mission_history_due: mission_ledger.value_m
# appends a V_m history point on EVERY call, and the tick's cockpit block
# runs every pass — un-gated, the 5-min cadence spams
# runs/mission_ledger.yaml and flattens d_slope (statusline slopes over the
# last-5 history window). 30 min = one V_m sample per heartbeat-TTL grid
# cell: real progress lands within one TTL window, ticks in between only
# re-settle PQ states (mission_ledger.update is un-gated and idempotent).
# Named _MIN per the #754 precedent — NEW in #8, not a surveyed constant.
MISSION_SETTLE_MIN = 30
