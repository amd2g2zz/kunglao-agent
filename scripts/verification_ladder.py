# -*- coding: utf-8 -*-
"""verification_ladder.py — the three-tier verification ladder's mechanical
core + mainline ΔV decision recording (issue 429 §1/§8, W2-T2.4).

## The ladder (settlement follows verification; verification is tiered)

  T0 (on-write, ~free)   write_guard / fact gates at artifact-write time.
                         Already a verifier — named as such by the owner
                         spec; this module adds nothing to it.
  T1 (mid-round, cheap)  oracle-case probe batches for LONG rounds. The
                         verified-write evidence stream (runs/signals.jsonl)
                         debounces into ONE batch: a batch is DUE when the
                         coalesced write count crosses the round-turn
                         threshold AND the min-interval floor since the
                         previous batch has elapsed. Firing consumes the
                         existing oracle cadence face (oracle_cadence.
                         run_cadence) — wired, never rebuilt. Registered as
                         the ``oracle_probe_t1`` mechanism (heartbeat tick
                         is the only time host; the ``long_round`` gate
                         reads the debounce state, fail-open).
  T2 (round close, real  replay / red-team adversarial re-derivation, a
      dispatch cost)     real-dispatch batch. Its deliverable here is the
                         PRIORITY QUEUE over sides ordered by UNBLOCKING
                         VALUE (the v0.1.6 simple rule: stalled-side
                         evidence first):
                           priority 0  stalled open sides — no evidence at
                                       all first (most in need of
                                       unblocking), then oldest evidence
                           priority 1  active open sides — oldest first
                           terminal sides are closure events: excluded.
                         ``round_close`` builds + persists the queue at the
                         round-closure event (worker return); ``drain``
                         pops the head up to budget and persists the
                         remainder — the existing dispatch faces consume
                         entries; red-team agent internals are untouched.
                         Settlement accepts T0/T1 immediately; T2 upgrades
                         settled rows via the ledger amendment path.

## Mainline ΔV decision rows (record first, learn later)

``mainline_decision`` rows on the unified rollout ledger — the same
append + amend pipeline as round_credit. One row per consecutive pair of
the mainline situation snapshot stream (state_signature.read_situations):
the MECHANICAL REPLAY of the situation stream, no counterfactual:

  s_M     the AFTER snapshot's canonical signature + short hash
  A_M     closed vocabulary: spawn | switch | allocate | park_revive |
          conclude (trigger-derived mapping for the mechanical face;
          orchestrator faces record explicit rows via
          record_mainline_decision)
  ΔV      V(after) - V(before) — the deterministic v_anchor face
          (state_signature.v_anchor; never a second V)
  provenance  the P_LLM⊗Q sampling document when the dispatch face used
          it (absent otherwise — honest absence)

Recording is pure + idempotent: replaying the same stream appends nothing
new and the folded row is unchanged. Zero behavior change in v0.1.6 —
mainline Q activation is a later switch-on (owner design pin).

Failure posture: recording faces are fail-open (a broken ladder never
breaks its producer); the trigger faces are loud (the emit word lands on
the unified log when a batch fires).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _common import atomic_write_text  # noqa: E402
from harness_common import utc_now_z as _utc_now  # noqa: E402
from kunglao_log import warn  # noqa: E402

# --- rollout-ledger registration (open enum, central registry) ------------
import rollout_ledger as rl  # noqa: E402

KIND_MAINLINE_DECISION = "mainline_decision"
rl.register_kind(
    KIND_MAINLINE_DECISION,
    "mainline (s_M, A_M, delta-V) decision row, situation-stream replay")

BAND_MAINLINE = "MAINLINE_DECISION"
RULE_MAINLINE = "mainline/delta-v"

MAINLINE_ACTIONS = ("spawn", "switch", "allocate", "park_revive", "conclude")

# trigger-derived action mapping for the mechanical replay face (the
# worker-return face is the spawned round's credit; the terminal face is
# the conclusion; any other snapshot trigger is a situation switch)
TRIGGER_ACTION = {"worker_return": "spawn", "terminal": "conclude"}
DEFAULT_ACTION = "switch"


# ---------- small shared helpers -------------------------------------------

def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _now_dt(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


# ===========================================================================
# T1 — long-round trigger + debounced probe batch
# ===========================================================================

T1_STATE_REL = "runs/.ladder-t1.json"

#: the round-turn threshold: verified-write evidence coalescing into one
#: probe batch (a turn with verifiable evidence leaves one signal row)
T1_ROUND_TURNS_THRESHOLD = 6

#: the debounce floor between probe batches (minutes) — a batch never
#: fires twice within the window
T1_MIN_INTERVAL_MIN = 30

T1_NOTE_KIND = "write_note"


def _threshold() -> int:
    raw = os.environ.get("KUNGLAO_T1_MIN_WRITES")
    if raw:
        try:
            v = int(raw)
            if v > 0:
                return v
        except ValueError as exc:
            warn("t1_threshold", f"{type(exc).__name__}: {exc}")
    return T1_ROUND_TURNS_THRESHOLD


def _interval_min() -> float:
    raw = os.environ.get("KUNGLAO_T1_MIN_INTERVAL_MIN")
    if raw:
        try:
            v = float(raw)
            if v >= 0:
                return v
        except ValueError as exc:
            warn("t1_interval", f"{type(exc).__name__}: {exc}")
    return float(T1_MIN_INTERVAL_MIN)


def t1_state(ws) -> dict:
    """Tolerant read of the debounce state (absent -> fresh; corrupt ->
    fresh with one rate-limited warn — never silent, never wedged)."""
    p = Path(ws) / T1_STATE_REL
    if not p.is_file():
        return {"last_probe_ts": None, "batches_fired": 0}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(doc, dict):
            return {"last_probe_ts": doc.get("last_probe_ts"),
                    "batches_fired": int(doc.get("batches_fired") or 0)}
    except (OSError, ValueError, TypeError) as exc:
        warn("t1_state_read", f"{type(exc).__name__}: {exc}")
    return {"last_probe_ts": None, "batches_fired": 0}


def _write_t1_state(ws, state: dict) -> None:
    p = Path(ws) / T1_STATE_REL
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        warn("t1_state_write", f"{type(exc).__name__}: {exc}")


def note_write(ws, *, n: int = 1, ts: str | None = None) -> dict:
    """Explicit verified-write intake: one signal row on the SAME evidence
    stream every producer already uses (one ledger, one truth). Faces that
    already land signal rows need no call — those rows count directly."""
    p = Path(ws) / "runs" / "signals.jsonl"
    row = {"ts": ts or _utc_now(), "kind": T1_NOTE_KIND, "n": max(int(n), 0)}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return {"appended": True, "n": row["n"]}
    except OSError as exc:
        warn("t1_note_write", f"{type(exc).__name__}: {exc}")
        return {"appended": False, "n": 0}


def pending_writes(ws, *, since_ts: str | None = None) -> int:
    """Coalesced verified-write count since the given ts (all rows on the
    evidence stream count; explicit note rows carry their batch size)."""
    p = Path(ws) / "runs" / "signals.jsonl"
    if not p.is_file():
        return 0
    total = 0
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if since_ts and str(row.get("ts") or "") <= str(since_ts):
            continue
        if row.get("kind") == T1_NOTE_KIND:
            try:
                total += max(int(row.get("n") or 1), 0)
            except (TypeError, ValueError):
                total += 1
        else:
            total += 1
    return total


def t1_due(ws, *, now: datetime | None = None, min_writes: int | None = None,
           min_interval_min: float | None = None) -> dict:
    """The T1 trigger: a debounced batch is DUE when the coalesced write
    count crosses the round-turn threshold (long round) AND the interval
    floor since the previous batch has elapsed. Fail-open."""
    ws = Path(ws)
    state = t1_state(ws)
    need = int(min_writes) if min_writes is not None else _threshold()
    # an unparseable probe stamp is honest absence: the count starts from
    # the epoch (a garbage since-ts would lexically swallow every row)
    last_raw = state["last_probe_ts"]
    since = last_raw if last_raw and _parse_ts(last_raw) else None
    pending = pending_writes(ws, since_ts=since)
    if pending < need:
        return {"due": False, "reason": "below_threshold",
                "pending_writes": pending, "threshold": need}
    last = _parse_ts(last_raw) if last_raw else None
    if last is not None:
        floor = (float(min_interval_min) if min_interval_min is not None
                 else _interval_min())
        elapsed = (_now_dt(now) - last).total_seconds() / 60.0
        if elapsed < floor:
            return {"due": False, "reason": "debounce_interval",
                    "pending_writes": pending, "threshold": need,
                    "minutes_since_probe": round(elapsed, 3),
                    "min_interval_min": floor}
    return {"due": True, "reason": "long_round",
            "pending_writes": pending, "threshold": need}


def fire_t1(ws, *, now: datetime | None = None) -> dict:
    """Consume the coalesced batch: stamp the probe, run the existing
    oracle cadence face (the probe batch), emit the registered event.
    The batch is consumed BEFORE the probe runs so a broken probe never
    wedges the debounce (the cadence emits its own loud warn faces)."""
    ws = Path(ws)
    due = t1_due(ws, now=now)
    if not due["due"]:
        return {"fired": False, "reason": due["reason"],
                "pending_writes": due["pending_writes"]}
    state = t1_state(ws)
    state["last_probe_ts"] = _utc_now() if now is None else _ts_of(now)
    state["batches_fired"] = int(state.get("batches_fired") or 0) + 1
    _write_t1_state(ws, state)
    probe: dict = {"fired": False, "reason": "cadence_unavailable"}
    try:
        import oracle_cadence
        probe = oracle_cadence.run_cadence(ws)
    except Exception as exc:  # noqa: BLE001 — the trigger never fails the tick
        warn("t1_probe", f"{type(exc).__name__}: {exc}")
    try:
        import kunglao_log
        kunglao_log.emit(
            ws, actor="verification_ladder", action="oracle_probe_t1",
            detail=json.dumps(
                {"pending_writes": due["pending_writes"],
                 "threshold": due["threshold"],
                 "probe_reason": probe.get("reason"),
                 "batches_fired": state["batches_fired"]},
                ensure_ascii=False, sort_keys=True))
    except Exception as exc:  # noqa: BLE001 — telemetry never breaks the ladder
        warn("t1_emit", f"{type(exc).__name__}: {exc}")
    return {"fired": True, "pending_writes": due["pending_writes"],
            "probe": probe}


def _ts_of(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ===========================================================================
# T2 — the unblocking-value priority queue (round close)
# ===========================================================================

T2_QUEUE_REL = "runs/t2-queue.json"
T2_QUEUE_SCHEMA = "t2-queue/1"

#: the v0.1.6 simple stall rule: evidence older than this (minutes) marks
#: an open side stalled (KUNGLAO_T2_STALL_MIN overrides)
T2_STALL_MIN_DEFAULT = 60.0


def _terminal_statuses() -> frozenset[str]:
    """TERMINAL + RETRACTED (the closure set; rollup's _terminal_set
    semantics, domain owners canonical)."""
    from status_defs import TERMINAL
    out = set(TERMINAL)
    try:
        import retract_claim
        out.add(retract_claim.RETRACTED)
    except ImportError as exc:
        warn("t2_terminal_set", f"{type(exc).__name__}: {exc}")
    return frozenset(out)


def _stall_min(override: float | None) -> float:
    if override is not None:
        return float(override)
    raw = os.environ.get("KUNGLAO_T2_STALL_MIN")
    if raw:
        try:
            v = float(raw)
            if v >= 0:
                return v
        except ValueError as exc:
            warn("t2_stall_min", f"{type(exc).__name__}: {exc}")
    return T2_STALL_MIN_DEFAULT


def _evidence_age_min(ws: Path, claim_id: str,
                      now: datetime) -> float | None:
    """Age (minutes) of the claim's newest evidence file, from the
    existing provenance face (latest verify-note / red-team outcome).
    None when the side carries no evidence at all."""
    try:
        import register_proven_gate
        ev = register_proven_gate.latest_evidence(ws, claim_id)
    except Exception as exc:  # noqa: BLE001 — evidence read never breaks the queue
        warn("t2_evidence", f"{type(exc).__name__}: {exc}")
        return None
    newest: datetime | None = None
    for row in (ev.get("verify_note"), ev.get("redteam")):
        source = (row or {}).get("source")
        if not source:
            continue
        p = ws / "runs" / str(source)
        if not p.is_file():
            continue
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime,
                                           tz=timezone.utc)
        except OSError:
            continue
        if newest is None or mtime > newest:
            newest = mtime
    if newest is None:
        return None
    return max((now - newest).total_seconds() / 60.0, 0.0)


def _queue_sort_key(entry: dict) -> tuple:
    """Unblocking-value order: stalled first; within stalled, no-evidence
    (age None) before any evidence, then oldest evidence; within active,
    oldest evidence; claim id breaks ties deterministically."""
    age = entry["age_min"]
    return (entry["priority"],
            0 if age is None else 1,
            -(age if age is not None else 0.0),
            entry["claim_id"])


def build_t2_queue(ws, *, now: datetime | None = None,
                   stall_min: float | None = None) -> dict:
    """Build the round-close priority queue over sides (claim-register
    claims). Pure read; deterministic for the same register + evidence."""
    ws = Path(ws)
    reg_path = ws / "claim-register.yaml"
    if not reg_path.exists():
        return {"built": False, "reason": "no-register", "queue": []}
    try:
        import yaml
        reg = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
        claims = reg.get("claims") or []
    except Exception as exc:  # noqa: BLE001 — a broken register is fail-open
        warn("t2_register", f"{type(exc).__name__}: {exc}")
        return {"built": False, "reason": "register-unreadable", "queue": []}
    now = _now_dt(now)
    floor = _stall_min(stall_min)
    terminal = _terminal_statuses()
    queue: list[dict] = []
    for c in claims:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "").strip()
        status = str(c.get("status") or "").strip().upper()
        if not cid or status in terminal:
            continue  # terminal sides are closure events — nothing to unblock
        age = _evidence_age_min(ws, cid, now)
        stalled = age is None or age >= floor
        queue.append({
            "claim_id": cid,
            "status": status,
            "stalled": stalled,
            "priority": 0 if stalled else 1,
            "age_min": None if age is None else round(age, 3),
            "reason": ("no-evidence" if age is None
                       else f"evidence-age={round(age, 1)}min"
                       f" (stall floor {floor:g}min)"),
        })
    queue.sort(key=_queue_sort_key)
    return {"built": True, "queue": queue, "stall_min": floor,
            "ts": _ts_of(now)}


def _persist_queue(ws: Path, doc: dict) -> bool:
    """Atomic persist (writer-unique tmp + os.replace): since #462 W6 the
    queue is written from the production SubagentStop face, where two
    workers stopping together spawn concurrent hook processes on one
    workspace. A FIXED tmp name would let the two writers truncate each
    other's buffer mid-write and tear the final file (the two-writer
    race, demonstrated in review); the unique name makes each rename
    atomic AND writer-isolated."""
    p = ws / T2_QUEUE_REL
    try:
        atomic_write_text(p, json.dumps(doc, ensure_ascii=False, indent=2),
                          unique=True)
        return True
    except OSError as exc:
        warn("t2_persist", f"{type(exc).__name__}: {exc}")
        return False


def drain_t2_queue(ws, *, budget: int | None = None,
                   now: datetime | None = None,
                   stall_min: float | None = None) -> dict:
    """Consume the queue head at round close: pop up to budget entries in
    unblocking-value order and persist the remainder (the durable face
    the dispatch faces read — enqueue here, existing faces consume)."""
    ws = Path(ws)
    built = build_t2_queue(ws, now=now, stall_min=stall_min)
    if not built.get("built"):
        return {"dispatched": [], "remaining": [],
                "reason": built.get("reason", "not-built")}
    queue = built["queue"]
    n = int(budget) if budget is not None else 3
    head, rest = queue[:n], queue[n:]
    doc = {"schema": T2_QUEUE_SCHEMA,
           "ts": built.get("ts"),
           "stall_min": built.get("stall_min"),
           "dispatched": head,
           "remaining": rest}
    _persist_queue(ws, doc)
    return {"dispatched": head, "remaining": rest}


def round_close(ws, *, now: datetime | None = None) -> dict:
    """The round-closure face: build + persist the T2 priority queue and
    emit the registered event. Fail-open: a workspace without a register
    records nothing and never breaks the closure."""
    ws = Path(ws)
    built = build_t2_queue(ws, now=now)
    if not built.get("built"):
        return {"built": False, "reason": built.get("reason", "not-built")}
    stalled = sum(1 for e in built["queue"] if e["stalled"])
    doc = {"schema": T2_QUEUE_SCHEMA,
           "ts": built.get("ts"),
           "stall_min": built.get("stall_min"),
           "queue": built["queue"]}
    ok = _persist_queue(ws, doc)
    try:
        import kunglao_log
        head = [e["claim_id"] for e in built["queue"][:3]]
        kunglao_log.emit(
            ws, actor="verification_ladder", action="t2_queue_built",
            detail=json.dumps(
                {"queued": len(built["queue"]), "stalled": stalled,
                 "head": head, "persisted": ok},
                ensure_ascii=False, sort_keys=True))
    except Exception as exc:  # noqa: BLE001 — telemetry never breaks closure
        warn("t2_emit", f"{type(exc).__name__}: {exc}")
    return {"built": True, "queued": len(built["queue"]),
            "stalled": stalled, "path": str(ws / T2_QUEUE_REL)}


# ===========================================================================
# Mainline ΔV decision rows (situation-stream replay, ledger-backed)
# ===========================================================================

def _v(snap: dict | None) -> float:
    return ssig_v(snap or {})


def ssig_v(snap: dict) -> float:
    """The deterministic v_anchor face — single source, never a fork."""
    import state_signature
    return state_signature.v_anchor(snap)


def _sig_faces(snap: dict) -> tuple[str, str]:
    import state_signature
    return (state_signature.signature_str(snap),
            state_signature.signature_hash(snap))


def mainline_rows(ws) -> list[dict]:
    """Replay the mainline situation snapshot stream into decision rows:
    one row per consecutive pair (mechanical replay, no counterfactual).
    Pure — the same stream always yields the same rows."""
    import state_signature
    rows = [r for r in state_signature.read_situations(ws)
            if isinstance(r.get("state"), dict)]
    out: list[dict] = []
    for prev, cur in zip(rows, rows[1:]):
        trigger = str(cur.get("trigger") or "")
        after_state = cur["state"]
        v_before = _v(prev.get("state"))
        v_after = _v(after_state)
        sig, sig_hash = _sig_faces(after_state)
        after_ts = str(cur.get("ts") or "")
        out.append({
            "rollout_id": f"{KIND_MAINLINE_DECISION}/{after_ts}",
            "anchor": "mainline",
            "action": TRIGGER_ACTION.get(trigger, DEFAULT_ACTION),
            "trigger": trigger,
            "state_signature": sig,
            "state_signature_hash": sig_hash,
            "v_before": v_before,
            "v_after": v_after,
            "delta_v": v_after - v_before,
            "before_ts": str(prev.get("ts") or ""),
            "after_ts": after_ts,
            "sampling": None,
        })
    return out


def record_mainline_decision(ws, action: str, *, before: dict,
                             after: dict, sampling: dict | None = None,
                             anchor: str = "mainline",
                             ts: str | None = None,
                             rollout_id: str | None = None,
                             trigger: str | None = None) -> dict:
    """The explicit single-row API for orchestrator faces that KNOW the
    decision (spawn/switch/allocate/park_revive/conclude). Validates the
    closed vocabulary, computes ΔV from the deterministic anchor, lands
    record + settle on the unified ledger (round_credit pipeline)."""
    ws = Path(ws)
    action = str(action or "").strip()
    if action not in MAINLINE_ACTIONS:
        return {"recorded": False,
                "reason": f"action {action!r} outside the closed vocabulary "
                          f"{MAINLINE_ACTIONS}"}
    ts = ts or _utc_now()
    rid = rollout_id or f"{KIND_MAINLINE_DECISION}/{ts}"
    v_before = _v(before)
    v_after = _v(after)
    sig, sig_hash = _sig_faces(after)
    signals = [
        {"type": "state_before", "source": "state_signature",
         "value": {"signature": _sig_faces(before)[0],
                   "signature_hash": _sig_faces(before)[1],
                   "v": v_before}, "ts": ts},
        {"type": "action", "source": "verification_ladder",
         "value": {"action": action, "trigger": trigger}, "ts": ts},
        {"type": "delta_v", "source": "state_signature.v_anchor",
         "value": {"delta_v": v_after - v_before, "v_before": v_before,
                   "v_after": v_after}, "ts": ts},
    ]
    if sampling:
        signals.append({"type": "sampling_provenance",
                        "source": "verification_ladder",
                        "value": dict(sampling), "ts": ts})
    rec = rl.record(ws, kind=KIND_MAINLINE_DECISION, anchor=anchor,
                    signals=signals, rollout_id=rid, ts=ts)
    if not rec.get("appended") and rec.get("reason") not in (
            "duplicate: unchanged",):
        warn("mainline_record", f"{rid}: {rec.get('reason')}")
        return {"recorded": False, "reason": rec.get("reason"),
                "rollout_id": rid}
    settlement = {
        "reward": v_after - v_before,
        "band": BAND_MAINLINE,
        "rule_id": RULE_MAINLINE,
        "evidence_refs": [f"situation:{ts}", f"signature:{sig_hash}",
                          f"action:{action}"],
        "action": action,
    }
    res = rl.settle(ws, rid, settlement, ts=ts)
    if not res.get("appended") and res.get("reason") not in (
            "duplicate: already settled",):
        warn("mainline_settle", f"{rid}: {res.get('reason')}")
    return {"recorded": True, "settled": bool(res.get("appended")),
            "rollout_id": rid, "delta_v": v_after - v_before}


def settle_mainline_decisions(ws, *, ts: str | None = None) -> dict:
    """Replay the situation stream and land one ledger row per decision
    pair. Idempotent: a re-run freezes each row's identity ts at the
    stream's own ts, so the signal set (and its digest) never churns and
    the ledger dedupes — the same ledger always folds to the same rows."""
    ws = Path(ws)
    settled = 0
    rows = mainline_rows(ws)
    for row in rows:
        rid = str(row["rollout_id"])
        existing = rl.fold(ws, rid)
        row_ts = str((existing or {}).get("ts") or row["after_ts"])
        signals = [
            {"type": "state_before", "source": "state_signature",
             "value": {"signature": row["state_signature"],
                       "signature_hash": row["state_signature_hash"],
                       "v": row["v_before"]}, "ts": row_ts},
            {"type": "action", "source": "verification_ladder",
             "value": {"action": row["action"], "trigger": row["trigger"]},
             "ts": row_ts},
            {"type": "delta_v", "source": "state_signature.v_anchor",
             "value": {"delta_v": row["delta_v"],
                       "v_before": row["v_before"],
                       "v_after": row["v_after"]}, "ts": row_ts},
        ]
        if row.get("sampling"):
            signals.append({"type": "sampling_provenance",
                            "source": "verification_ladder",
                            "value": dict(row["sampling"]), "ts": row_ts})
        rec = rl.record(ws, kind=KIND_MAINLINE_DECISION,
                        anchor=str(row["anchor"]), signals=signals,
                        rollout_id=rid, ts=row_ts)
        if not rec.get("appended") and rec.get("reason") not in (
                "duplicate: unchanged",):
            warn("mainline_replay_record", f"{rid}: {rec.get('reason')}")
            continue
        settlement = {
            "reward": row["delta_v"],
            "band": BAND_MAINLINE,
            "rule_id": RULE_MAINLINE,
            "evidence_refs": [f"situation:{row['after_ts']}",
                              f"signature:{row['state_signature_hash']}",
                              f"action:{row['action']}"],
            "action": row["action"],
        }
        res = rl.settle(ws, rid, settlement, ts=ts or row_ts)
        if res.get("appended"):
            settled += 1
        elif res.get("reason") not in ("duplicate: already settled",):
            warn("mainline_replay_settle", f"{rid}: {res.get('reason')}")
    return {"rows": len(rows), "settled": settled}


# ===========================================================================
# CLI (the mechanism entry face)
# ===========================================================================

def main(argv: list[str] | None = None) -> int:
    """The oracle_probe_t1 mechanism's entry: fire the T1 probe batch when
    the long-round trigger is due. Advisory rc — the mechanism scheduler
    treats the rc as accounting, never a gate."""
    parser = argparse.ArgumentParser(
        prog="verification_ladder.py",
        description="verification ladder (T1 probe trigger / T2 queue) + "
                    "mainline decision recording")
    parser.add_argument("workspace", help="initialized workspace directory")
    parser.add_argument("--t1", action="store_true",
                        help="fire the mid-round oracle probe batch when "
                             "the long-round trigger is due")
    parser.add_argument("--t2", action="store_true",
                        help="build + persist the round-close T2 queue")
    args = parser.parse_args(argv)
    ws = Path(args.workspace)
    if not ws.is_dir():
        print(f"FAIL: workspace {ws} does not exist", file=sys.stderr)
        return 2
    if args.t1:
        print(json.dumps(fire_t1(ws), ensure_ascii=False))
    if args.t2:
        print(json.dumps(round_close(ws), ensure_ascii=False))
    if not (args.t1 or args.t2):
        parser.print_help(sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot
    force_utf8()
    sys.exit(main())
