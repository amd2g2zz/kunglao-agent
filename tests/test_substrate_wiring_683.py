# -*- coding: utf-8 -*-
"""tests/test_substrate_wiring_683.py — #683: the shadow substrate is
deployed but not wired.

Two drifts pinned here (owner acceptance amendment 2026-10-14):

  1. REGISTRY DRIFT — `wire_up_settings.WIRE_UP_HOOK_FILES` (the
     post-write self-check's expected set, via `_wire_up_hook_files()`)
     and `hook_activation._DEPLOYED_WIRING` (what the deployed writer
     registers) listed different hook FILES. `step_record_capture.py`
     (#670 shadow step ledger) and `cost_input_capture.py` (#873) lived
     only in the second list, so the CANONICAL `register_hooks` never
     wrote them and the self-check stayed GREEN while both were absent —
     a missing hook was invisible by construction.

  2. OPAQUE REJECTs — worker_budget's gate REJECTs (tier / cap /
     liveness / heartbeat / ...) printed a stderr summary + stdout JSON
     guidance and exited 2, with no durable row: nothing a post-mortem
     could count (the #603 class, on the worker_budget face).

Scope (S11 pre-wave W2-B): loop-closure-critical only — registry
single-sourcing + REJECT telemetry. No slimming, no authority hand-off.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import hook_activation  # noqa: E402
import wire_up_settings  # noqa: E402

# the two substrate hooks the drift left unreachable (#670/#873).
SUBSTRATE_HOOKS = frozenset({"step_record_capture.py", "cost_input_capture.py"})


def _collect_commands(settings: dict) -> list[str]:
    return [str(h.get("command", ""))
            for entries in (settings.get("hooks") or {}).values()
            for e in entries
            for h in e.get("hooks", [])]


def _basenames(settings: dict) -> set[str]:
    return {c.replace("\\", "/").rsplit("/", 1)[-1]
            for c in _collect_commands(settings)}


def _wire(ws: Path) -> dict:
    """Fresh canonical wire-up into a scratch workspace (no live writes)."""
    ws.mkdir(parents=True, exist_ok=True)
    hook_activation.register_hooks(workspace=ws)
    return json.loads(
        (ws / ".claude" / "settings.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# T2: registry single-sourcing (the 2-hook drift)
# ---------------------------------------------------------------------------

def test_two_hook_registries_are_single_sourced() -> None:
    """The writer's row table and the self-check's expected set must be ONE
    list (or one derived from the other) — two independently maintained
    lists is exactly how the #683 drift (2 hooks unreachable + self-check
    blind) happened."""
    deployed_files = {f for _, _, f in hook_activation._DEPLOYED_WIRING}
    registry = set(wire_up_settings.WIRE_UP_HOOK_FILES)
    assert deployed_files == registry, (
        f"in _DEPLOYED_WIRING but not the registry: "
        f"{sorted(deployed_files - registry)}; registry-only: "
        f"{sorted(registry - deployed_files)} — the two hook registries "
        "must be single-sourced (#683)")
    assert SUBSTRATE_HOOKS <= registry, (
        f"substrate hooks missing from the registry: "
        f"{sorted(SUBSTRATE_HOOKS - registry)}")


def test_substrate_hooks_present_in_settings_after_wireup(tmp_path: Path) -> None:
    """A fresh canonical `register_hooks` must land BOTH substrate hooks in
    the workspace settings — pre-#683 the canonical writer skipped them
    while its self-check passed (the expected set lacked them too)."""
    settings = _wire(tmp_path / "ws")
    bases = _basenames(settings)
    assert SUBSTRATE_HOOKS <= bases, (
        f"register_hooks did not write the substrate hooks: "
        f"{sorted(SUBSTRATE_HOOKS - bases)}")


def test_register_hooks_adds_every_deployed_wiring_entry(tmp_path: Path) -> None:
    """Every deployed-wiring row (event, matcher, hook file) must be
    reachable by the canonical writer — a row only the deployed writer
    knows is the drift class, not a wiring."""
    settings = _wire(tmp_path / "ws")
    hooks_map = settings.get("hooks") or {}
    gaps: list[str] = []
    for event, matcher, hook_file in hook_activation._DEPLOYED_WIRING:
        entries = hooks_map.get(event) or []
        matching = [e for e in entries
                    if any(_base(h) == hook_file for h in e.get("hooks", []))]
        if not matching:
            gaps.append(f"{event}/{matcher or '*'}/{hook_file}: not registered")
            continue
        if matcher and not any(e.get("matcher") == matcher
                               for e in matching):
            gaps.append(f"{event}/{matcher}/{hook_file}: registered but "
                        f"matchers={[e.get('matcher') for e in matching]}")
    assert not gaps, f"deployed rows register_hooks cannot reach: {gaps}"


def _base(h: dict) -> str:
    return str(h.get("command", "")).replace("\\", "/").rsplit("/", 1)[-1]


# ---------------------------------------------------------------------------
# T3: worker_budget REJECTs are durable
# ---------------------------------------------------------------------------

def test_worker_budget_rejects_are_durable(tmp_path: Path, capsys) -> None:
    """A worker_budget gate REJECT must leave one row in
    runs/gate-telemetry.jsonl (the #603 class on the worker_budget face):
    gate identity, the exit code, and the reason — auditable after the
    fact, not just a stdout line nobody kept."""
    import worker_budget_sinks as sinks

    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    paths = {"workspace": str(ws)}

    rc = sinks._reject("tier",
                       "open claim C-1 at evidence_tier=0 < 1", paths)
    capsys.readouterr()  # swallow the stderr summary + stdout guidance

    assert rc == 2, "REJECT exit-code semantics are unchanged (#270)"
    p = ws / "runs" / "gate-telemetry.jsonl"
    assert p.is_file(), "the REJECT must land in runs/gate-telemetry.jsonl"
    rows = [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert rows, "at least one telemetry row"
    row = rows[-1]
    assert row.get("gate") == "worker_budget.tier"
    assert row.get("rc") == 2
    assert row.get("rc_meaning"), "rc_meaning rides the shared vocabulary"
    assert "evidence_tier" in str(row.get("msg", ""))
    assert row.get("ts"), "the row carries a timestamp"


def test_worker_budget_reject_telemetry_fails_open(tmp_path: Path,
                                                   capsys) -> None:
    """Telemetry is bookkeeping: an uninstrumented workspace (no runs/) or
    an unwritable ledger must never change the REJECT itself — same
    fail-open posture as every other ledger append in this hook."""
    import worker_budget_sinks as sinks

    bare = tmp_path / "bare"          # no runs/ -> gate_telemetry skips
    bare.mkdir()
    rc = sinks._reject("heartbeat", "heartbeat NOT registered",
                       {"workspace": str(bare)})
    capsys.readouterr()
    assert rc == 2, "no runs/ must not change the verdict"
    assert not (bare / "runs" / "gate-telemetry.jsonl").exists()

    # a paths dict without a workspace key degrades the same way
    rc = sinks._reject("cap", "promotion_attempts=3 >= 3", {})
    capsys.readouterr()
    assert rc == 2
