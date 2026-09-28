#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""exogenous.py — exogenous-failure classification for settlement (#421).

Owner-identified live-run causal finding: environment failures (MCP down,
VM down, adb dead, network) cause action failures that are NOT the
action's fault — but settlement recorded them as RED 0.0, poisoning the
arm's posterior and losing the opportunity until manual intervention.

MEASURED DISCRIMINATOR (not counterfactual estimation): the workspace's
component-state face (runs/env-state.json, the env_probe liveness subset)
is consulted for the state AT ACTION TIME. If a component required by the
action's lane was DOWN when the action executed, the failure is
classified EXOGENOUS:

  - the settlement band becomes "<kind>/exogenous" — a NEUTRAL-polarity
    band, so the prior feed (polarity_of / prior_observations) feeds no
    beta: the advisory anti-pollution wall construction, unchanged;
  - the row stays visible for audit (evidence_refs carry the component
    probe evidence);
  - partial provenance credit is preserved by construction: already-
    satisfied signals ride evidence_refs exactly as the normal engine
    records them;
  - the settlement document carries a wake_condition (#634 PARK
    precedent) — "wake when <component> recovers" — the convergence-side
    PARK face consumes it; the opportunity pauses, it is not lost.

Single runs are ambiguous by design (component flaky AND method weak):
separation is statistical over multiple observations across differing
component states. Classification is CONSERVATIVE: absent/unreadable
state, no probe near the action time, or no failed lane-required
component -> None (normal settlement; fail-closed stays fail-closed).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ENV_STATE_REL = Path("runs") / "env-state.json"
# the env snapshot must bracket the action this closely to count as
# "state at action time" (probe cadence is tick-bound)
PROXIMITY_MINUTES = 30

# components required by the lane (liveness vocabulary of env_state_probe)
LANE_REQUIRED: dict[str, tuple[str, ...]] = {
    "windows": ("vm_reachable", "mcp_bridge"),
    "linux": ("vm_reachable", "mcp_bridge"),
    "android": ("adb", "frida_server"),
    "web": ("mcp_bridge",),
    "macos": ("mcp_bridge",),
}


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def state_at(ws: Path, action_ts, *,
             now=None) -> dict | None:
    """The env-state snapshot when it plausibly describes ACTION TIME.

    Returns the per_capability mapping when the snapshot's probe ts is
    within PROXIMITY_MINUTES of the action ts (or of now, when the action
    carries no ts); None otherwise — absence of evidence is NOT evidence
    of a healthy component, and an unclassifiable row settles normally."""
    ws = Path(ws)
    path = ws / ENV_STATE_REL
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    caps = doc.get("per_capability")
    if not isinstance(caps, dict):
        return None
    probe_ts = _parse_ts(doc.get("ts"))
    if probe_ts is None:
        return None
    ref = (_parse_ts(action_ts) if action_ts else None) \
        or (now or datetime.now(timezone.utc))
    drift = abs((probe_ts - ref).total_seconds())
    if drift > PROXIMITY_MINUTES * 60:
        return None
    return caps


def classify_exogenous(ws: Path, project_type: str | None,
                       action_ts=None, *, now=None) -> dict | None:
    """EXOGENOUS classification: a lane-required component DOWN at action
    time. Returns {"component", "detail", "probe_ts"} or None (including
    the component-up case — a healthy component never classifies)."""
    caps = state_at(ws, action_ts, now=now)
    if caps is None:
        return None
    required = LANE_REQUIRED.get(str(project_type or "").strip(), ())
    for name in required:
        entry = caps.get(name)
        if not isinstance(entry, dict):
            continue  # unprobed capability is not evidence of down
        if str(entry.get("status")) == "fail":
            return {"component": name,
                    "detail": str(entry.get("detail") or ""),
                    "probe_ts": str(entry.get("last_probe_ts") or "")}
    return None


def wake_condition(component: str) -> str:
    """The #634-PRECEDENT wake condition: the claim auto-revives when the
    named component recovers (next successful env probe clears it)."""
    return f"component:{component} recovered (env-state.json status=pass)"
