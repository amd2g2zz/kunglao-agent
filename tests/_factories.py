# -*- coding: utf-8 -*-
"""Shared test fixture factories (863-h Family L, issue #863).

Consolidates the three most-duplicated fixture-seeding shapes from the
2026-09-01 code-hygiene audit: hook_state writers, claim-register seeds
and bins/sample.exe seeds - importable plain functions so test modules
stop hand-rolling them per file.

Import note: test modules must use "from _factories import ...", NOT
"from conftest import ...": pytest.ini pythonpath lists the repo root
first, so the name conftest resolves to the ROOT conftest.py. tests/ is
on sys.path via pytest prepend import mode, so the bare module name
_factories is unambiguous.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOOK_STATE_FILE = ".hook_state.json"
# Far-future expiry of the armed-forever inline shapes.
FAR_FUTURE = "2099-12-31T23:59:59Z"
# The dominant synthetic PE sample payload (MZ header + zero tail).
DEFAULT_SAMPLE = b"MZ\x90\x00" + b"\x00" * 64


def _in_minutes(minutes: float) -> str:
    """Timestamp now+minutes, second precision, Z suffix."""
    return (datetime.now(tz=timezone.utc) + timedelta(minutes=minutes)
            ).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_hook_state(ws: Path, *, active_hooks: list[str],
                     paused_hooks: list[str] | None = (),
                     expires_at: str | None = FAR_FUTURE,
                     expires_minutes: float | None = None,
                     phase: str | None = None,
                     tier: str | None = None,
                     ts: str | None = None,
                     user_override: dict | None = None,
                     extra: dict | None = None) -> Path:
    """Write the workspace hook-state file.

    Field-presence semantics mirror the inline shapes this factory
    replaces: active_hooks is always emitted; paused_hooks defaults to
    the empty list and is omitted entirely when passed None (the 2-key
    backtrack shape); expires_at is emitted as given (None becomes JSON
    null, the dispatch_contract shape) unless expires_minutes computes a
    now-relative stamp; ts/tier/phase/user_override are emitted only
    when not None (full-schema sites pass all four).
    """
    state: dict = {"active_hooks": list(active_hooks)}
    if paused_hooks is not None:
        state["paused_hooks"] = list(paused_hooks)
    if expires_minutes is not None:
        state["expires_at"] = _in_minutes(expires_minutes)
    else:
        state["expires_at"] = expires_at
    if ts is not None:
        state["ts"] = ts
    if tier is not None:
        state["tier"] = tier
    if phase is not None:
        state["phase"] = phase
    if user_override is not None:
        state["user_override"] = user_override
    if extra:
        state.update(extra)
    path = ws / HOOK_STATE_FILE
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


# Canonical 6-field defaults of the ws_factory claim-register dialect.
_CLAIM_DEFAULTS = ((
    ("status", "OPEN"),
    ("boundary_type", "positive_observation"),
    ("evidence_tier_attempted", 0),
    ("promotion_attempts", 0),
    ("depends_on", "[]"),
))

def write_claims_register(ws: Path, claims: list[dict],
                          *, defaults: bool = False) -> Path:
    """Write the workspace claim-register.yaml (text dialect).

    defaults=False emits only the keys present on each claim (bools
    lowercased, lists JSON-encoded) - the sparse inline dialect.
    defaults=True emits the five canonical fields with the historical
    ws_factory defaults (byte-identical to pre-consolidation output).
    Consumers parse YAML, so both dialects are parse-equivalent for the
    same input.
    """
    lines = ["claims:"]
    for c in claims:
        lines.append(f"- id: {c['id']}")
        if defaults:
            for key, dflt in _CLAIM_DEFAULTS:
                lines.append(f"  {key}: {c.get(key, dflt)}")
        else:
            for key, value in c.items():
                if key == "id":
                    continue
                if isinstance(value, str):
                    lines.append(f"  {key}: {value}")
                elif isinstance(value, bool):
                    lines.append(f"  {key}: {str(value).lower()}")
                elif isinstance(value, list):
                    lines.append(f"  {key}: {json.dumps(value)}")
                else:
                    lines.append(f"  {key}: {value}")
    path = ws / "claim-register.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def seed_bins(ws: Path, *, name: str = "sample.exe",
              payload: bytes = DEFAULT_SAMPLE) -> Path:
    """Create the bins/ directory with one synthetic sample.

    Replaces the two-line mkdir+write_bytes shape that 26 test files
    hand-rolled (issue #863 Family L, sample.exe fixture family).
    """
    bins = ws / "bins"
    bins.mkdir(parents=True, exist_ok=True)
    target = bins / name
    target.write_bytes(payload)
    return target


def write_worker_status(ws: Path, name: str, status: str,
                        age_min: float | None = None) -> Path:
    """#915 item 8: the ONE runs/worker-status-<name>.md seeding shape.

    Two-line body (in-progress history + last line carrying `status`), the
    dominant fixture shape across scan_waiting/wait_signal/liveness tests.
    age_min backdates the mtime (stale-worker scenarios)."""
    p = ws / "runs" / f"worker-status-{name}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"[12:00] step: started task | status: in-progress\n"
        f"[12:30] wait: awaiting signal | status: {status}\n",
        encoding="utf-8")
    if age_min is not None:
        import os
        import time
        old = time.time() - age_min * 60
        os.utime(p, (old, old))
    return p
