#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gate_policy.py — the #801 gate-layering authority (issue 801 Face 2).

The harness must never out-compete the analysis for budget (#801): a
format-invalid input or a crashed gate costs a full context re-read per
rc=2 rejection (~120k input tok each, ~20 loops/session, #741 shape) and
— the 51job FATAL shape — a gate crashing (ModuleNotFoundError) locked
the claim-register and STOPPED the mission. The layering:

  HARD   (blocks, unchanged) — exactly five classes:
           corruption          register/post-image integrity (write_guard)
           reward_integrity    blind-settlement read barriers (#687 family)
           termination_budget  budget/termination rc faces (worker_budget,
                               completion gate)
           evidence            evidence-pin + must-stop charter faces
           execution_surface   MCP/tool-surface + privileged-exec faces
  format / self_health (DEMOTED) — stderr WARN + ONE telemetry sidecar row
           in runs/gate-rejections.jsonl (gate_class, exit_code 0) + a
           `gate_warn` ledger row; the tool call PROCEEDS (rc 0). A human
           ruling is never needed mid-mission.

This SUPERSEDES the 2026-09-28 owner ruling (gate error = fail-closed)
for the format/self-health classes per #801 Face 2; the five hard
classes keep every tooth. The shared sidecar writer is the ONE telemetry
face — dispatch_gate and write_guard both land their demotion rows here,
so the rejection ledger stays single-shape.

Fail-open: telemetry must never break the demoted (or any) gate.
"""
from __future__ import annotations

try:
    from _path_hygiene import ensure_scripts_path as _esp801
    _esp801()
    from kunglao_log import warn
except Exception:  # noqa: BLE001 — fail-open lifeline, never block the hook
    import sys

    def warn(op: str, reason: str) -> None:
        print(f"[kunglao-agent] WARN (fail-open): {op}: {reason}",
              file=sys.stderr)

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# THE allowlist (spec centerpiece, #801 Face 2) — order is documentation,
# membership is the contract. Pinned exactly by
# tests/test_economics_801.py::test_hard_allowlist_exactly_five.
HARD_CLASSES = (
    "corruption",
    "reward_integrity",
    "termination_budget",
    "evidence",
    "execution_surface",
)

FORMAT_CLASS = "format"
SELF_HEALTH_CLASS = "self_health"
DEMOTED_CLASSES = (FORMAT_CLASS, SELF_HEALTH_CLASS)

GATE_REJECTIONS_LOG = Path("runs") / "gate-rejections.jsonl"

# #801 R2a (Standard 11) — bounded repetition + ownership transfer. The
# rc1 production shape: 540/593 warns were verbatim repeats of SIX
# pathologies, and a completion_gate leg hung 41h with nobody called —
# unbounded repeat warns are unowned noise. Each demoted warn accrues to
# its FAMILY (gate|class|name — the face identity, not the free-text msg:
# near-duplicate msgs with different claim ids must group); past the
# bound the harness takes EXACTLY ONE ownership action per family.
WARN_FAMILY_BOUND = 24
WARN_BREAKER_REL = Path("runs") / ".warn-breaker.json"
BREAKER_ACTIONS = ("circuit-break", "escalate", "downgrade")
BREAKER_ACTION_ENV = "KUNGLAO_WARN_BREAKER_ACTION"
BREAKER_WORD = "warn_breaker_tripped"


def _breaker_action() -> str:
    """The ownership action for a tripped family. Default circuit-break
    (suppress further same-family sidecar rows); `escalate` and
    `downgrade` are explicit operator choices via env — all three persist
    in the state file, so the choice is always observable."""
    import os
    val = os.environ.get(BREAKER_ACTION_ENV, "")
    return val if val in BREAKER_ACTIONS else "circuit-break"


def _load_breaker(ws: Path) -> dict:
    try:
        return json.loads((Path(ws) / WARN_BREAKER_REL).read_text(
            encoding="utf-8"))
    except Exception:  # noqa: BLE001 — absent/corrupt state = fresh ledger
        return {"families": {}}


def _save_breaker(ws: Path, state: dict) -> None:
    path = Path(ws) / WARN_BREAKER_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8")


def record_family(ws: Path | None, gate: str, gate_class: str,
                  name: str, msg: str) -> dict:
    """The bounded-repetition counter (R2a). Accrues the demotion to its
    family; at WARN_FAMILY_BOUND the family trips ONCE with the chosen
    ownership action (`warn_breaker_tripped` ledger row) — the tripping
    warn itself still lands, every FURTHER same-family warn is suppressed
    (the returned state carries suppress_row=True). Fail-open: counter
    trouble never breaks the gate."""
    fam_key = f"{gate}|{gate_class}|{name}"
    out = {"count": 0, "action": None, "tripped": False,
           "suppressed": 0, "suppress_row": False}
    if ws is None:
        out["count"] = 1
        return out
    state = _load_breaker(ws)
    fams = state.setdefault("families", {})
    fam = fams.setdefault(fam_key, {"count": 0, "action": None,
                                    "tripped": False, "suppressed": 0})
    if fam.get("tripped"):
        fam["suppressed"] = int(fam.get("suppressed", 0)) + 1
        out.update(fam, suppress_row=True)
        try:
            _save_breaker(ws, state)
        except OSError as exc:
            print(f"gate_policy: breaker state write failed ({exc!r})",
                  file=sys.stderr, flush=True)
        return out
    fam["count"] = int(fam.get("count", 0)) + 1
    out.update(fam)
    if fam["count"] >= WARN_FAMILY_BOUND and not fam.get("tripped"):
        fam["tripped"] = True
        fam["action"] = _breaker_action()
        _emit_breaker_trip(ws, fam_key, fam, msg)
    try:
        _save_breaker(ws, state)
    except OSError as exc:
        print(f"gate_policy: breaker state write failed ({exc!r})",
              file=sys.stderr, flush=True)
    return out


def _emit_breaker_trip(ws: Path, fam_key: str, fam: dict, msg: str) -> None:
    """The trip is OBSERVABLE: stderr WARN + one `warn_breaker_tripped`
    ledger row carrying the chosen action. `escalate` is the
    operator-facing variant — the stderr note names the operator. Fail-open
    (telemetry never breaks the gate)."""
    action = fam.get("action") or "circuit-break"
    detail = (f"warn family {fam_key} tripped at {fam.get('count')} "
              f"repeats; action={action}; last: {str(msg)[:200]}")
    if action == "escalate":
        detail = f"OPERATOR ESCALATION — {detail}"
    warn("warn_breaker", detail)
    try:
        from _path_hygiene import ensure_scripts_path as _esp801b
        _esp801b()
        from kunglao_log import emit
        emit(Path(ws), actor="hook:gate_policy", action=BREAKER_WORD,
             detail=detail)
    except Exception as exc:  # noqa: BLE001 — telemetry fail-open
        print(f"gate_policy: breaker emit failed ({exc!r})",
              file=sys.stderr, flush=True)


def is_hard(gate_class: str) -> bool:
    """True iff the class is one of the five HARD classes (still blocks)."""
    return gate_class in HARD_CLASSES


def should_block(gate_class: str) -> bool:
    """The ONE layering decision: hard classes block; format/self_health
    demote to WARN + telemetry (never block)."""
    return is_hard(gate_class)


def warn_sidecar(ws: Path | None, gate: str, gate_class: str, msg: str,
                 *, exit_code: int = 0, name: str | None = None) -> bool:
    """The demotion telemetry face: ONE durable sidecar row in
    runs/gate-rejections.jsonl carrying the class + exit_code 0, PLUS the
    R2a bounded-repetition counter (a tripped family suppresses further
    same-family rows — circuit-break). Best effort — a telemetry failure
    must never break the gate (stderr note only), matching every other
    observability face. Returns False when the row was suppressed."""
    if ws is None:
        return True
    try:
        fam = record_family(ws, gate, gate_class, name or gate, msg)
        if fam.get("suppress_row"):
            return False  # the family is owned now — silence IS the action
        row = {
            "ts": datetime.now(tz=timezone.utc).isoformat(
                timespec="seconds").replace("+00:00", "Z"),
            "gate": gate,
            "name": name or gate,
            "gate_class": gate_class,
            "msg": str(msg)[:500],
            "exit_code": int(exit_code),
        }
        ledger = Path(ws) / GATE_REJECTIONS_LOG
        ledger.parent.mkdir(parents=True, exist_ok=True)
        with open(ledger, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return True
    except OSError as exc:
        print(f"gate_policy: sidecar append failed ({exc!r})",
              file=sys.stderr, flush=True)
        return True


def demote(gate: str, gate_class: str, name: str, msg: str, *,
           ws: Path | None = None) -> int:
    """The WARN half of the layering: stderr WARN + sidecar row + rc 0.
    Callers add their hookSpecificOutput guidance before/after as they
    see fit — the contract is (never rc 2, always observable). The
    `gate_warn` ledger row rides here too (the #801 word for a demoted
    rejection — registered in event_taxonomy, emitted on EVERY demotion,
    so the ledger replay sees the soft verdicts the sidecar only counts)."""
    warn(f"gate_demoted:{gate}",
         f"{gate_class}-class rejection DEMOTED (no block, #801): "
         f"{name}: {msg}")
    warn_sidecar(ws, gate, gate_class, msg, name=name)
    if ws is not None:
        try:
            from _path_hygiene import ensure_scripts_path as _esp801d
            _esp801d()
            from kunglao_log import emit
            emit(Path(ws), actor=f"hook:{gate}", action="gate_warn",
                 detail=f"{gate_class}-class demoted (no block, #801): "
                        f"{name}: {str(msg)[:300]}")
        except Exception as exc:  # noqa: BLE001 — telemetry fail-open
            print(f"gate_policy: gate_warn emit failed ({exc!r})",
                  file=sys.stderr, flush=True)
    return 0
