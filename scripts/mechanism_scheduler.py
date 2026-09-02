#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mechanism_scheduler.py — #878 mechanism registry + single-host tick scheduler.

THE answer to "机制越来越庞大，什么在什么时候跑": every kunglao mechanism is
declared in ``mechanisms.yaml`` (schema ``kunglao.mechanisms/1``) with its
trigger, cost class and cockpit signal; the scheduler walks that registry on
every heartbeat_tick pass. 不入册不许跑 — a mechanism that is not declared
here physically cannot run (the scheduler only ever iterates the registry),
and the three go-live prerequisites (trigger.gate / cost_class /
cockpit_signal) are rejected mechanically when missing.

Design (issue #878):
  1. registry + schema gate   — load_registry / validate_registry; a BROKEN
     registry fails CLOSED (nothing runs, mech_reject lands) — the mirror of
     "not registered => must not run" is "registry invalid => nothing runs".
  2. single-host tick         — heartbeat_tick is the ONLY in-session time
     host; it passes its own ``run`` seam in, so per-script wiring tests keep
     pinning script names + argv byte-identically.
  3. ledger event bus         — the scheduler (not each mechanism) consumes
     the ledger tail with a persisted byte-offset incremental read (mirrors
     the #883 statusline reader's bounded-window convention); settlement /
     stall / plan_review events become trigger inputs for gates.
  4. single-tick budget       — cheap gates evaluate first (zero subprocess),
     candidates queue by cost_class (cheap -> medium -> expensive), and the
     whole scheduling pass is bounded by a wall-clock time cap; mechanisms
     that do not fit are DROPPED (reason=budget, drops counter++) and stay
     eligible next tick. A failed run is NOT a drop: rc passes through into
     last_rc for the cockpit health probe.
  5. cockpit health section   — per mechanism {last_run, next_eligible,
     drops} rides the #883 statusline snapshot.

CONSTITUTIONAL ISOLATION (non-negotiable): the scheduler is a pacemaker, not
a power center. It dispatches PROPOSAL-class mechanisms declared
``channel: tick`` ONLY; hooks/os/cli/host channels are declarative entries
(the hooks channel is host lifecycle — issue #878 explicitly excludes its
migration), and no decision authority (replan application / PROVEN
promotion / budget waiver) moves here.

State: runs/.mechanisms-state.json
    {"schema": 1,
     "mechanisms": {<name>: {last_run, last_rc, drops, last_drop_reason,
                             next_eligible, runs}},
     "events": {"file": <latest ledger file name>, "offset": <int>}}

Usage:
  python mechanism_scheduler.py <ws> --plan        # what runs when (one command)
  python mechanism_scheduler.py <ws> --status      # state view
  python mechanism_scheduler.py <ws> --run         # run due mechanisms now (advisory)
  python mechanism_scheduler.py --check [--registry PATH]   # schema gate
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

import kunglao_log
from kunglao_log import iter_jsonl  # noqa: E402  (#863 Family K single source)

# #863 Family C: workspace resolution is single-sourced in ws_layout
from ws_layout import resolve_strict as _resolve_ws

SCHEMA = "kunglao.mechanisms/1"
COST_CLASSES = ("cheap", "medium", "expensive")
TRIGGER_TYPES = ("tick", "event", "settlement", "stall", "manual")
EVENT_CLASSES = ("settlement", "stall", "plan_review")
CHANNELS = ("host", "tick", "hooks", "os", "cli")
DEPTHS = ("os", "session", "workspace", "mission")

REGISTRY_PATH = Path(__file__).resolve().parent / "mechanisms.yaml"
STATE_REL = Path("runs") / ".mechanisms-state.json"

# Single-tick scheduling budget (wall-clock seconds for the whole mechanism
# pass). Cheap mechanisms finish in well under a second; the expensive tail
# (policy retro carries two <=30s inner subprocesses) is what the cap exists
# to sacrifice first.
DEFAULT_BUDGET_S = 90.0
BUDGET_ENV = "KUNGLAO_MECH_BUDGET_S"

# Bounded ledger read window (mirror of the #883 statusline reader's tail
# convention): the FIRST read of a ledger starts at the 64KB tail, later
# reads are strictly incremental from the persisted offset.
LEDGER_WINDOW_BYTES = 65_536

# Ledger action -> event-bus wake class (issue: settlement/stall/plan_review
# 事件即触发器). Only actions with real producers are mapped (#459 discipline).
EVENT_CLASS_MAP = {
    "claim_settled": "settlement",   # #880 settlement rows (write_guard face)
    "mission_stall": "stall",        # #634 mission stall fingerprint
    "plan_stall": "stall",           # ask_for_direction_gate plan-stall face
    "plan_review": "plan_review",    # #822 review ritual verdict face
}

# #878 migration mapping: scheduler mechanism -> legacy heartbeat_tick report
# key. The migration moves the TRIGGER, not the report contract — the loop
# prompt and the per-step wiring tests consume these keys verbatim.
LEGACY_REPORT_KEYS = {
    "env_probe": "env_state",
    "workspace_monitor": "monitor",
    "stale_feedback": "feedback",
    "verify_watch": "verify_watch",
    "notes_rollup": "rollup_sweep",
    "think_seat": "think",
    "policy_retro": "backtrack",
}


from harness_common import utc_now_z as utc_now  # #863 Family F: single source (was a local def)


# ---------------------------------------------------------------------------
# state (one dotfile, two sections: mechanisms + event-bus offset)
# ---------------------------------------------------------------------------

def _read_state(ws: Path) -> dict:
    try:
        data = json.loads(
            (Path(ws) / STATE_REL).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(ws: Path, state: dict) -> None:
    """Atomic write (tmp + replace — backtrack_loop discipline)."""
    path = Path(ws) / STATE_REL
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(state, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass  # telemetry state must never break the tick


def _update_state(ws: Path, *, mechanisms: dict | None = None,
                  events: dict | None = None) -> dict:
    """Read-modify-write ONE section without touching the other (the event
    offset and the per-mechanism rows share a file but never a write)."""
    state = _read_state(ws)
    state.setdefault("schema", 1)
    if mechanisms is not None:
        merged = state.get("mechanisms") or {}
        merged.update(mechanisms)
        state["mechanisms"] = merged
    if events is not None:
        state["events"] = events
    _write_state(ws, state)
    return state


# ---------------------------------------------------------------------------
# registry + schema gate
# ---------------------------------------------------------------------------

def load_registry(path: Path | None = None) -> tuple[list[dict], list[str]]:
    """Load + validate mechanisms.yaml. Returns (entries, errors); errors
    non-empty means the registry is BROKEN and nothing may run (fail-closed)."""
    p = Path(path) if path is not None else REGISTRY_PATH
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        return [], [f"registry unreadable: {exc}"]
    except yaml.YAMLError as exc:
        return [], [f"registry unparseable yaml: {exc}"]
    if not isinstance(data, dict):
        return [], ["registry root is not a mapping"]
    errors: list[str] = []
    if data.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA!r}, got {data.get('schema')!r}")
    for vocab, required in (("cost_classes", COST_CLASSES),
                            ("trigger_types", TRIGGER_TYPES),
                            ("event_classes", EVENT_CLASSES),
                            ("channels", CHANNELS),
                            ("depths", DEPTHS)):
        got = data.get(vocab)
        if not isinstance(got, list) or not got:
            errors.append(f"{vocab} vocabulary missing/empty")
        elif not set(required) <= set(got):
            errors.append(
                f"{vocab} vocabulary is missing required members: "
                f"{sorted(set(required) - set(got))}")
    entries = data.get("mechanisms")
    if not isinstance(entries, list) or not entries:
        errors.append("mechanisms list missing/empty")
        return [], errors

    cost_vocab = set(data.get("cost_classes") or COST_CLASSES)
    type_vocab = set(data.get("trigger_types") or TRIGGER_TYPES)
    event_vocab = set(data.get("event_classes") or EVENT_CLASSES)
    chan_vocab = set(data.get("channels") or CHANNELS)
    depth_vocab = set(data.get("depths") or DEPTHS)

    seen: set[str] = set()
    for idx, e in enumerate(entries):
        name = str((e or {}).get("name") or "").strip()
        label = name or f"#{idx}"
        if not name:
            errors.append(f"mechanism {label}: missing name")
            continue
        if name in seen:
            errors.append(f"mechanism {label}: duplicate name")
            continue
        seen.add(name)
        where = f"mechanism {name!r}"
        if not str(e.get("entry") or "").strip():
            errors.append(f"{where}: missing entry")
        channel = e.get("channel")
        if channel not in chan_vocab:
            errors.append(f"{where}: unknown channel {channel!r}")
        trig = e.get("trigger")
        if not isinstance(trig, dict) or not trig:
            errors.append(f"{where}: missing trigger")
            trig = {}
        else:
            if trig.get("type") not in type_vocab:
                errors.append(
                    f"{where}: unknown trigger type {trig.get('type')!r}")
            gate = str(trig.get("gate") or "").strip()
            if not gate:
                errors.append(f"{where}: missing trigger.gate "
                              "(go-live prerequisite)")
            elif gate not in GATES:
                errors.append(
                    f"{where}: unknown trigger.gate {gate!r} "
                    f"(known: {sorted(GATES)})")
            if channel == "tick" and trig.get("type") == "manual":
                errors.append(
                    f"{where}: channel 'tick' rejects manual trigger "
                    "(manual belongs to the cli/hooks/os declaration faces)")
            events = trig.get("events") or []
            if not isinstance(events, list) or \
                    not set(events) <= event_vocab:
                errors.append(
                    f"{where}: trigger.events must be a subset of "
                    f"event_classes, got {events!r}")
        if channel == "host" and trig.get("host") is not True:
            errors.append(f"{where}: channel 'host' requires trigger.host=true")
        if trig.get("host") is True and channel != "host":
            errors.append(f"{where}: trigger.host=true requires channel 'host'")
        if not str(e.get("cost_class") or "").strip():
            errors.append(f"{where}: missing cost_class (go-live prerequisite)")
        elif e.get("cost_class") not in cost_vocab:
            errors.append(
                f"{where}: unknown cost_class {e.get('cost_class')!r} "
                f"(known: {sorted(cost_vocab)})")
        if e.get("depth") not in depth_vocab:
            errors.append(f"{where}: unknown depth {e.get('depth')!r}")
        if not str(e.get("cockpit_signal") or "").strip():
            errors.append(
                f"{where}: missing cockpit_signal (go-live prerequisite — "
                "a mechanism with no cockpit signal is not allowed to go live)")
        argv = e.get("argv") or []
        if not isinstance(argv, list) or \
                not all(isinstance(a, str) for a in argv):
            errors.append(f"{where}: argv must be a list of strings")
    return [e for e in entries if isinstance(e, dict)], errors


def validate_registry(path: Path | None = None) -> dict:
    """The mechanical schema gate face (--check). ok=False means the registry
    is broken: the scheduler refuses to run anything (fail-closed)."""
    _entries, errors = load_registry(path)
    return {"ok": not errors, "errors": errors,
            "mechanisms": 0 if errors else len(_entries)}


# ---------------------------------------------------------------------------
# ledger event bus (byte-offset incremental read)
# ---------------------------------------------------------------------------

def read_new_events(ws: Path) -> dict:
    """Consume the ledger tail incrementally: read only the bytes after the
    persisted offset of the latest day file, advance past COMPLETE lines
    (a partial trailing line stays for the next pass), and map actions to
    wake classes. Mirrors the #883 reader's bounded-window convention: the
    first read of a ledger starts at a 64KB tail, not the big bang.

    Fail-open everywhere: a broken ledger returns an empty class set and
    never breaks the scheduling pass."""
    ws = Path(ws)
    logs = ws / "runs" / "logs"
    counts: dict[str, int] = {}
    try:
        latest = max((p for p in logs.glob("kunglao-*.jsonl") if p.is_file()),
                     key=lambda p: p.stat().st_mtime, default=None)
        if latest is None:
            return {"classes": [], "counts": counts, "new": 0}
        size = latest.stat().st_size
    except OSError:
        return {"classes": [], "counts": counts, "new": 0}

    state = _read_state(ws)
    ev = state.get("events") or {}
    try:
        offset = int(ev.get("offset") or 0)
    except (TypeError, ValueError):
        offset = 0
    if ev.get("file") != latest.name or offset < 0 or offset > size:
        offset = 0  # first read / day rotation / truncated file
    if offset == 0:
        offset = max(0, size - LEDGER_WINDOW_BYTES)
    try:
        with latest.open("rb") as f:
            f.seek(offset)
            chunk = f.read()
    except OSError:
        return {"classes": [], "counts": counts, "new": 0}

    # only COMPLETE lines are consumed (byte-exact: no decode before split)
    cut = chunk.rfind(b"\n")
    if cut < 0:
        complete, consumed = b"", 0
    else:
        complete, consumed = chunk[:cut + 1], cut + 1
    new = 0
    # non-blank line count stays parse-independent (blank lines were never
    # counted); null rows keep reaching row.get below, byte-equivalent with
    # the pre-consolidation loop (#863 Family K)
    decoded_lines = [raw.decode("utf-8", errors="replace")
                     for raw in complete.split(b"\n") if raw.strip()]
    new += len(decoded_lines)
    for row in iter_jsonl(decoded_lines):
        cls = EVENT_CLASS_MAP.get(str(row.get("action") or ""))
        if cls:
            counts[cls] = counts.get(cls, 0) + 1
    _update_state(ws, events={"file": latest.name, "offset": offset + consumed})
    return {"classes": sorted(counts), "counts": counts, "new": new}


# ---------------------------------------------------------------------------
# gates (cheap: zero subprocess — state files + event classes only)
# ---------------------------------------------------------------------------

def _gate_always(ws: Path, events: set) -> bool:
    return True


def _gate_loop_unregistered(ws: Path, events: set) -> bool:
    """True while the /loop cron is not proven registered (#461 marker)."""
    try:
        hb = json.loads((Path(ws) / "runs" / ".heartbeat.json")
                        .read_text(encoding="utf-8"))
        return not hb.get("loop_registered")
    except (OSError, ValueError):
        return True  # no/unreadable heartbeat -> never registered


def _gate_session_dead(ws: Path, events: set) -> bool:
    """D1 dead-session judgment, reused from external_kicker (zero rewrite)."""
    try:
        import external_kicker as ek
        hb = None
        p = Path(ws) / "runs" / ".heartbeat.json"
        if p.exists():
            hb = json.loads(p.read_text(encoding="utf-8"))
        return ek.session_is_dead(hb, datetime.now(timezone.utc))
    except Exception:  # noqa: BLE001 — a gate must never raise (fail-open)
        return True


def _gate_policy_due(ws: Path, events: set) -> bool:
    """#882 policy-retro wake: the cheap file gates (settlement lag / stall
    fingerprint / plan_review ritual) OR a stall/plan_review ledger event
    class seen since the last pass (the event-bus term — wakes the retro
    even when the lag is below N)."""
    if events & {"stall", "plan_review"}:
        return True
    try:
        import backtrack_loop as bl
        return bool(bl.policy_due(ws).get("due"))
    except Exception:  # noqa: BLE001 — gate sources must never raise
        return False


GATES = {
    "always": _gate_always,
    "loop_unregistered": _gate_loop_unregistered,
    "session_dead": _gate_session_dead,
    "policy_due": _gate_policy_due,
}


# ---------------------------------------------------------------------------
# scheduling
# ---------------------------------------------------------------------------

def _budget_s() -> float:
    raw = os.environ.get(BUDGET_ENV)
    if raw:
        try:
            v = float(raw)
            if v >= 0:
                return v
        except ValueError:
            pass
    return DEFAULT_BUDGET_S


def next_eligible_for(entry: dict) -> str:
    """The human answer to "when does this run next" (one-command face)."""
    channel = entry.get("channel")
    if channel == "host":
        return "every tick (host)"
    if channel == "hooks":
        return "on next tool call (hooks channel)"
    if channel == "os":
        return "OS scheduler cadence (schtasks/cron)"
    if channel == "cli":
        return "on demand (CLI)"
    ttype = (entry.get("trigger") or {}).get("type")
    if ttype == "settlement":
        return "on next " + "/".join(
            (entry.get("trigger") or {}).get("events") or EVENT_CLASSES) + " event"
    if ttype == "stall":
        return "on next stall signal"
    if ttype == "event":
        return "on next ledger event"
    return "next tick"


def _mech_row(entry: dict, st: dict) -> dict:
    return {"name": entry["name"],
            "last_run": st.get("last_run"),
            "next_eligible": st.get("next_eligible")
            or next_eligible_for(entry),
            "drops": int(st.get("drops") or 0)}


def mechanisms_view(ws: Path) -> list[dict]:
    """Per-mechanism {last_run, next_eligible, drops} rows for the #883
    statusline snapshot's mechanisms health section (fail-open to [])."""
    entries, errors = load_registry()
    if errors:
        return []
    state = _read_state(Path(ws)).get("mechanisms") or {}
    return [_mech_row(e, state.get(e["name"]) or {}) for e in entries]


def mechanisms_health(ws: Path) -> list[str]:
    """Failing mechanism names as 'name(rc)' — the mechanism_health probe's
    data face. Empty list = all scheduler mechanisms clean."""
    state = _read_state(Path(ws)).get("mechanisms") or {}
    bad = []
    for name, st in sorted(state.items()):
        rc = (st or {}).get("last_rc")
        if rc is not None and rc != 0:
            bad.append(f"{name}(rc={rc})")
    return bad


def run_due(ws: Path, *, budget_s: float | None = None, runner=None,
            now: datetime | None = None) -> dict:
    """One scheduling pass: registry traversal, cheap gates, cost-queued
    runs inside the time cap. Purely advisory — never raises, never gates a
    decision (constitutional isolation)."""
    ws = Path(ws)
    now = now or datetime.now(timezone.utc)
    budget = DEFAULT_BUDGET_S if budget_s is None else float(budget_s)
    start = time.monotonic()
    entries, errors = load_registry()
    if errors:
        # fail-closed: a broken registry must not run anything (the mirror
        # of 不入册不许跑). Loud face + ledger row, then bail out.
        try:
            kunglao_log.emit(ws, "orchestrator", "mech_reject",
                             detail=json.dumps({"errors": errors[:8]},
                                               ensure_ascii=False))
        except Exception:  # noqa: BLE001 — logging never breaks the tick
            pass
        print("mechanism_scheduler: REGISTRY REJECTED — "
              f"{len(errors)} schema violation(s); nothing ran", file=sys.stderr)
        return {"ts": utc_now(), "error": errors, "ran": [], "skipped": [],
                "dropped": [], "events_seen": [], "results": {},
                "mechanisms": {}, "budget_s": budget, "elapsed_ms": 0}

    if runner is None:  # default execution seam = the tick's own runner
        def runner(script, ws_arg, *extra):  # noqa: F811 — local default
            import subprocess as sp
            script_path = Path(__file__).resolve().parent / script
            try:
                r = sp.run([sys.executable, str(script_path), str(ws), *extra],
                           capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace")
                return {"rc": r.returncode, "stdout": r.stdout.strip()[-300:],
                        "stderr": r.stderr.strip()[-300:]}
            except Exception as exc:  # noqa: BLE001
                return {"rc": -1, "stdout": f"EXC {exc}", "stderr": ""}

    bus = read_new_events(ws)
    event_classes = set(bus["classes"])

    results: dict[str, dict] = {}
    ran: list[str] = []
    skipped: list[str] = []
    state_updates: dict[str, dict] = {}
    candidates: list[tuple[int, int, dict]] = []

    for order, e in enumerate(entries):
        name = e["name"]
        row = {"next_eligible": next_eligible_for(e)}
        if e.get("channel") != "tick":
            # declaration-only channel (host/hooks/os/cli): the scheduler
            # never dispatches it — hooks stay host lifecycle (issue #878).
            skipped.append(name)
            results[name] = {"rc": 0,
                             "stdout": f"skipped: channel {e.get('channel')!r} "
                                       "is declarative (not scheduler-dispatched)",
                             "stderr": "", "skipped": True}
            state_updates[name] = row
            continue
        gate_id = (e.get("trigger") or {}).get("gate") or "always"
        try:
            due = GATES[gate_id](ws, event_classes)
        except Exception:  # noqa: BLE001 — a broken gate fails open to candidacy
            due = True
        if not due:
            skipped.append(name)
            results[name] = {"rc": 0,
                             "stdout": f"skipped: gate {gate_id!r} not due",
                             "stderr": "", "skipped": True}
            state_updates[name] = row
            continue
        candidates.append((COST_CLASSES.index(e.get("cost_class", "expensive"))
                           if e.get("cost_class") in COST_CLASSES
                           else len(COST_CLASSES),
                           order, e))

    # cheap gates first, expensive mechanisms queue at the tail (issue:
    # 廉价门先行，贵机制门控排队)
    candidates.sort(key=lambda t: (t[0], t[1]))

    dropped: list[dict] = []
    prev_state = _read_state(ws).get("mechanisms") or {}
    for _rank, _order, e in candidates:
        name = e["name"]
        row = {"next_eligible": next_eligible_for(e)}
        prev = prev_state.get(name) or {}
        if time.monotonic() - start >= budget:
            dropped.append({"name": name, "reason": "budget"})
            row["drops"] = int(prev.get("drops") or 0) + 1
            row["last_drop_reason"] = "budget"
            state_updates[name] = {**(state_updates.get(name) or {}), **row}
            continue
        argv = e.get("argv") or []
        script = str(e.get("entry") or "").rsplit("/", 1)[-1]
        t0 = time.monotonic()
        try:
            res = dict(runner(script, ws, *argv) or {})
        except Exception as exc:  # noqa: BLE001 — a crashed runner is advisory
            res = {"rc": -1, "stdout": "", "stderr": repr(exc)}
        res["duration_ms"] = int((time.monotonic() - t0) * 1000)
        results[name] = res
        ran.append(name)
        row["last_run"] = utc_now()
        row["last_rc"] = res.get("rc")
        row["runs"] = int(prev.get("runs") or 0) + 1
        row["drops"] = int(prev.get("drops") or 0)  # a failed run is NOT a drop
        state_updates[name] = {**(state_updates.get(name) or {}), **row}

    if state_updates:
        _update_state(ws, mechanisms=state_updates)

    elapsed_ms = int((time.monotonic() - start) * 1000)
    try:
        kunglao_log.emit(ws, "orchestrator", "mech_run",
                         detail=json.dumps(
                             {"ran": ran, "skipped": skipped,
                              "dropped": dropped, "events": bus["classes"],
                              "elapsed_ms": elapsed_ms},
                             ensure_ascii=False))
    except Exception:  # noqa: BLE001 — logging never breaks the tick
        pass

    mech_view = {}
    for e in entries:
        st = state_updates.get(e["name"]) or prev_state.get(e["name"]) or {}
        mech_view[e["name"]] = _mech_row(e, st)
    return {"ts": utc_now(), "error": None, "ran": ran, "skipped": skipped,
            "dropped": dropped, "events_seen": bus["classes"],
            "results": results, "mechanisms": mech_view,
            "budget_s": budget, "elapsed_ms": elapsed_ms}


def plan_view(ws: Path) -> dict:
    """THE one-command answer to "什么机制在什么时候跑": every registry entry
    with its trigger/gate/cost/depth/cockpit signal + live state + a live
    gate evaluation for the declaration-only channels."""
    ws = Path(ws)
    entries, errors = load_registry()
    state = _read_state(ws).get("mechanisms") or {}
    rows = []
    for e in entries:
        trig = e.get("trigger") or {}
        st = state.get(e["name"]) or {}
        try:
            gate_state = bool(
                GATES[str(trig.get("gate"))](ws, set())) \
                if str(trig.get("gate")) in GATES else None
        except Exception:  # noqa: BLE001 — display face, never raises
            gate_state = None
        rows.append({
            "name": e["name"], "entry": e.get("entry"),
            "channel": e.get("channel"),
            "trigger_type": trig.get("type"), "gate": trig.get("gate"),
            "events": trig.get("events") or [],
            "host": bool(trig.get("host")),
            "cost_class": e.get("cost_class"), "depth": e.get("depth"),
            "cockpit_signal": e.get("cockpit_signal"), "owner": e.get("owner"),
            "argv": e.get("argv") or [],
            "description": (e.get("description") or "").strip(),
            "gate_state": gate_state,
            "last_run": st.get("last_run"),
            "next_eligible": st.get("next_eligible")
            or next_eligible_for(e),
            "drops": int(st.get("drops") or 0),
            "last_rc": st.get("last_rc"),
            "runs": int(st.get("runs") or 0),
        })
    return {"schema": SCHEMA, "workspace": str(ws), "errors": errors,
            "mechanisms": rows}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # captured stream without reconfigure (pytest capsys)
    args = sys.argv[1:] if argv is None else argv
    if "--check" in args:
        reg = None
        if "--registry" in args:
            i = args.index("--registry")
            if i + 1 < len(args):
                reg = Path(args[i + 1])
        out = validate_registry(reg)
        if out["ok"]:
            print(f"mechanism registry OK: {out['mechanisms']} mechanism(s) "
                  f"({SCHEMA})")
            return 0
        print(f"mechanism registry REJECTED ({len(out['errors'])} violation(s)):")
        for err in out["errors"]:
            print(f"  - {err}")
        return 1
    rest = [a for a in args if not a.startswith("--")]
    if not rest:
        print("Usage: mechanism_scheduler.py <ws> "
              "[--plan|--status|--run] | --check [--registry PATH]",
              file=sys.stderr)
        return 2
    ws = _resolve_ws(rest[0])
    if "--run" in args:
        out = run_due(ws)
        print(json.dumps({"ran": out["ran"], "skipped": out["skipped"],
                          "dropped": out["dropped"],
                          "events_seen": out["events_seen"],
                          "error": out["error"]}, ensure_ascii=False))
        return 0
    if "--status" in args:
        state = _read_state(ws)
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    # default / --plan: the one-command answer (what runs when)
    plan = plan_view(ws)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
