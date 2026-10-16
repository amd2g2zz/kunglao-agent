#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/step_grain.py — the settlement grain (#690): step := one
subagent completion.

The measured defect: settlement fired only at claim-terminal / oracle-
case-run, so a 4-hour claim moved no posterior and no sampling
distribution until its very end, `runs/transitions.jsonl` stayed empty in
production (append_transition had zero plugin-path callers), and
promotion_attempts never accrued from dispatches. The grain fix, in three
faces:

  settle     SubagentStop IS the step boundary. ``settle_step`` (hosted
             by hooks/round_closure — the production SubagentStop hook)
             aggregates the session's step-record/1 tool-call rows into
             ONE completion-grain step-record/2 row (claim_ref mapped
             from the dispatch-launch stash), closes the transition via
             ``incremental_reward.append_transition`` (the missing
             production caller), and prices a branch_budget.wall_s
             overrun into runs/attributed-waste.jsonl. Since #712 the
             settle ALSO scores the evidence the step touched
             (rlvr.step_credit — cross-validated 1.0 / unverified 0.3 /
             refuted 0.0) and banks it into the Q-cell immediately, so
             a 10-step rollout produces ten Beta movements instead of
             one claim-terminal signal; claim-terminal calibration
             (scalar._bank_q_cell_credit) reconciles the residual.
  barrier    settle -> update -> decide: ``barrier_verdict`` REJECTS a
             new dispatch while a prior step is unsettled (the
             worker_budget_gates.check_step_settled battery face). The
             fail-open+warn line: a pending step older than
             STEP_SETTLE_TTL_MINUTES (the SubagentStop never fired —
             crash/kill) ADMITS with ONE warn rather than deadlocking
             the loop; the orphan sweep still catches the stash at end
             of run.
  budget     branch_budget ({wall_s, retries}) — parsed since #539 with
             zero consumers — is now a hard constraint: wall_s is priced
             at settle (attributed-waste), retries bounds the claim's
             next dispatch (check_branch_budget), and dispatch_count
             accrues INDEPENDENTLY of promotion_attempts at every
             approved dispatch (the acceptance: attempts visible in the
             rank feed; the #690 measurement had it pinned at 0 across
             7 dispatches).

Posture: fail-open telemetry everywhere — no face here may change a
dispatch or stop verdict on error (ONE warn, never a raise into the
hook path). Hash-only ledger boundary inherited from step_ledger: the
step-record/2 row carries call_id hashes and refs, never content.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from _common import utc_now_z
from kunglao_log import warn  # canonical warn: ONE implementation
from liveness_policy import STEP_SETTLE_TTL_MINUTES  # the fail-open line

from rlvr import incremental_reward as _ir
from rlvr import step_ledger as _sl

WASTE_SCHEMA = "attributed-waste/1"
WASTE_LEDGER_REL = "runs/attributed-waste.jsonl"

_WASTE_KEYS = frozenset({
    "schema", "ts", "claim_ref", "step_id", "kind",
    "budget_s", "actual_s", "waste_s"})

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"


# ------------------------------------------------------------ step identity

def step_id_for(session_id: str, ordinal: int) -> str:
    """The #690 step_id rule: deterministic in (session, ordinal) — the
    ordinal is the count of already-settled steps for that session, so a
    replay of the same ledger rebuilds the same ids (no clock, no rng)."""
    return _sl.sha_of([str(session_id or ""), str(int(ordinal))])[:16]


def aggregate_session_steps(ws, session_id: str) -> dict:
    """One completion-grain aggregate over the session's step-record/1
    tool-call rows (file order): tool_calls count, the call_id hashes,
    first/last ts, summed known durations. Other sessions never leak in."""
    rows = [r for r in _sl.read_steps(ws)
            if str(r.get("session_id") or "") == str(session_id)]
    stamps = [str(r.get("ts") or "") for r in rows if r.get("ts")]
    durations = [float(r["duration_ms"]) for r in rows
                 if isinstance(r.get("duration_ms"), (int, float))]
    return {
        "session_id": str(session_id or ""),
        "tool_calls": len(rows),
        "call_ids": [str(r.get("call_id") or "") for r in rows],
        "first_ts": min(stamps) if stamps else "",
        "last_ts": max(stamps) if stamps else "",
        "duration_ms": round(sum(durations), 3) if durations else None,
    }


# ------------------------------------------------- the dispatch-launch face

def pending_step(ws) -> dict | None:
    """The OLDEST unsettled dispatch-launch stash — the sync barrier's
    subject and the settle face's claim mapping (claim_ref via the
    dispatch-launch mapping, #690). 1-F3 foreign envelopes (a status-
    bearing or foreign-schema doc parked in the namespace) and
    unparseable docs are skipped — never consumed, never guessed.
    #690 review CRITICAL: a stash whose claim/action_type is not a
    single safe path token is skipped at THIS read boundary too — the
    fields are worker-writable and later format into stash paths, so a
    traversal payload never becomes a pending step, never maps a
    claim_ref, and never reaches the barrier (sink-side wall in
    incremental_reward._launch_path is the second line of defense).
    None = nothing pending (fully settled)."""
    try:
        runs = Path(ws) / "runs"
        if not runs.is_dir():
            return None
        best: dict | None = None
        for path in sorted(runs.glob("dispatch-launch-*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(doc, dict):
                continue
            if "status" in doc or ("schema" in doc
                                   and doc.get("schema")
                                   != _ir.LAUNCH_SCHEMA):
                continue  # 1-F3: a foreign envelope is never launch state
            claim = str(doc.get("claim") or "").strip()
            if not claim:
                ident = _ir._stash_identity(path)
                if ident is None:
                    continue
                claim = ident[0]
            action_type = str(doc.get("action_type") or "dispatch")
            if not (_ir._safe_stash_token(claim)
                    and _ir._safe_stash_token(action_type)):
                continue  # #690: worker-writable path components — skip
            ts = str(doc.get("ts") or "")
            if best is None or (ts and ts < best["ts"]):
                budget = doc.get("branch_budget")
                best = {
                    "claim": claim,
                    "action_type": action_type,
                    "ts": ts,
                    "attempt_id": str(doc.get("attempt_id") or ""),
                    "branch_budget": (budget
                                      if isinstance(budget, dict) else {}),
                    "path": str(path),
                }
        return best
    except OSError as exc:
        warn("rlvr.step_grain.pending_step", f"{type(exc).__name__}: {exc}")
        return None


def _age_minutes(ts: str, now_dt: datetime) -> float | None:
    try:
        launched = datetime.strptime(str(ts), _TS_FMT).replace(
            tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None  # unknown ts shape — staleness undecidable
    return max(0.0, (now_dt - launched).total_seconds() / 60.0)


def _wall_s(ts: str, now_dt: datetime) -> float:
    try:
        launched = datetime.strptime(str(ts), _TS_FMT).replace(
            tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 0.0  # unknown launch time — zero cost, never negative
    return max(0.0, (now_dt - launched).total_seconds())


def _budget_float(budget: dict | None, key: str) -> float | None:
    v = (budget or {}).get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None  # absent/malformed budget dim — unconstrained
    return float(v) if float(v) > 0 else None


# -------------------------------------------------------------- the barrier

def barrier_verdict(ws, now: datetime | None = None) -> tuple[bool, str]:
    """The settle -> update -> decide sync barrier (#690): False while a
    prior step is unsettled — zero dispatches issued against an open
    step. The fail-open+warn line: a pending step older than
    STEP_SETTLE_TTL_MINUTES admits (the SubagentStop never fired; a
    crash must not deadlock the loop) with ONE warn; any read error also
    admits (fail-open — a broken ledger never newly blocks dispatch)."""
    try:
        pending = pending_step(ws)
        if pending is None:
            return True, ""
        now_dt = now or datetime.now(timezone.utc)
        age = _age_minutes(pending["ts"], now_dt)
        if age is not None and age > STEP_SETTLE_TTL_MINUTES:
            warn("rlvr.step_grain.barrier_verdict",
                 f"stale pending step for {pending['claim']!r} "
                 f"({int(age)}min > TTL {STEP_SETTLE_TTL_MINUTES}min) — "
                 f"admitting the dispatch (fail-open: the SubagentStop "
                 f"never settled it)")
            return True, (f"stale pending step {pending['claim']} "
                          f"({int(age)}min) admitted fail-open")
        return False, (
            f"prior step unsettled (claim {pending['claim']}, pending "
            f"since {pending['ts'] or 'unknown'}) — settle->update->"
            f"decide: no dispatch before the current step settles (#690)")
    except Exception as exc:  # noqa: BLE001 — fail-open, never the verdict
        warn("rlvr.step_grain.barrier_verdict",
             f"{type(exc).__name__}: {exc}")
        return True, ""


# ------------------------------------------------------------ the settlement

def record_attributed_waste(ws, *, claim_ref: str, step_id: str,
                            kind: str, budget_s: float, actual_s: float,
                            ts: str | None = None) -> dict | None:
    """One attributed-waste/1 row: spend beyond the branch act budget,
    attributed to the claim and the step that spent it. Hash-only
    posture (refs + numbers only). Fail-open: None + ONE warn."""
    row = {
        "schema": WASTE_SCHEMA,
        "ts": ts or utc_now_z(),
        "claim_ref": str(claim_ref or ""),
        "step_id": str(step_id or ""),
        "kind": str(kind or ""),
        "budget_s": round(float(budget_s), 3),
        "actual_s": round(float(actual_s), 3),
        "waste_s": round(float(actual_s) - float(budget_s), 3),
    }
    assert set(row) <= _WASTE_KEYS
    try:
        p = Path(ws) / WASTE_LEDGER_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row
    except OSError as exc:
        warn("rlvr.step_grain.record_attributed_waste",
             f"{type(exc).__name__}: {exc}")
        return None


def settle_step(ws, session_id: str, outcome: str = "completed",
                now: datetime | None = None) -> dict | None:
    """THE production step settlement (#690): the SubagentStop face.

    settle -> update -> decide, in order: the pending step's claim is
    resolved from the dispatch-launch stash (the mapping), the session's
    tool-call rows aggregate into ONE step-record/2 row, the transition
    closes via append_transition (Φ(s') read at settle; the stash is
    consumed there), a branch_budget.wall_s overrun lands in
    attributed-waste, and — #712 — the step's evidence window scores a
    step credit banked into the Q-cell at this boundary (the returned
    dict carries ``step_credit`` / ``credit_banked``; the ledger row
    whitelist is untouched). Returns the step row (transition, waste and
    credit receipt attached) or None — no pending step (silent:
    SubagentStop also fires for non-worker subagents) or a refusal
    (fail-open, ONE warn)."""
    try:
        pending = pending_step(ws)
        if pending is None:
            return None
        now_dt = now or datetime.now(timezone.utc)
        agg = aggregate_session_steps(ws, session_id)
        prior = _sl.read_step_grains(ws, session_id)
        ordinal = len(prior)
        # #712 the step's evidence window: (last settled step, this
        # settle] — the first step opens at the dispatch launch, so a
        # fact never re-enters through a wider window than its step.
        since_ts = (str(prior[-1].get("ts") or "") if prior
                    else str(pending["ts"] or ""))
        step_row = _sl.build_step_grain_row(
            session_id=session_id,
            claim_ref=pending["claim"],
            step_id=step_id_for(session_id, ordinal),
            call_ids=agg["call_ids"],
            first_ts=agg["first_ts"],
            last_ts=agg["last_ts"],
            duration_ms=agg["duration_ms"],
            ts=now_dt.strftime(_TS_FMT))
        if _sl.record_step_grain(ws, step_row) is None:
            return None  # ledger unwritable — the transition stays open
        actual_s = _wall_s(pending["ts"], now_dt)
        transition = _ir.append_transition(
            ws, pending["claim"], outcome,
            seconds=actual_s,
            action_type=pending["action_type"],
            attempt_id=pending["attempt_id"])
        waste = None
        budget_s = _budget_float(pending.get("branch_budget"), "wall_s")
        if budget_s is not None and actual_s > budget_s:
            waste = record_attributed_waste(
                ws, claim_ref=pending["claim"],
                step_id=step_row["step_id"], kind="wall_s_overrun",
                budget_s=budget_s, actual_s=actual_s)
        # #712 the step-boundary credit — score the evidence THIS step
        # touched (rlvr.step_credit: cross-validated 1.0 / unverified
        # 0.3 / refuted 0.0, reliability-weighted) and bank it into the
        # Q-cell immediately: the Beta moves at the stop, not at
        # claim-terminal, and the terminal residual reconciles later.
        # Fail-open inside its own cage: a scoring/banking failure never
        # undoes the settled step (the row + transition already landed).
        step_credit_value = None
        credit_banked = False
        try:
            from rlvr import q_cells as _qc  # noqa: PLC0415
            from rlvr import step_credit as _sc  # noqa: PLC0415
            items = _sc.evidence_in_window(
                ws, claim=str(pending["claim"]),
                since_ts=since_ts, until=now_dt)
            step_credit_value = _sc.step_credit(items)
            bank = _qc.observe_step_credit(
                ws, pending["claim"], step_credit_value,
                step_ref=step_row["step_id"])
            credit_banked = bool(bank.get("appended"))
        except Exception as exc:  # noqa: BLE001 — credit face, never the settle
            warn("rlvr.step_grain.settle_step.credit",
                 f"{type(exc).__name__}: {exc}")
        return dict(step_row, transition=transition, waste=waste,
                    step_credit=step_credit_value,
                    credit_banked=credit_banked)
    except Exception as exc:  # noqa: BLE001 — settle never breaks the stop
        warn("rlvr.step_grain.settle_step", f"{type(exc).__name__}: {exc}")
        return None


# --------------------------------------------------- dispatch_count accrual

def dispatch_count(ws, claim: str) -> int:
    """The claim's independent dispatch counter (register field — the
    rank feed reads it from there). Unreadable register / dirty value /
    unknown claim -> 0 (fail-open: a broken read never newly blocks)."""
    try:
        import yaml
        p = Path(ws) / "claim-register.yaml"
        if not p.is_file():
            return 0
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for c in (doc.get("claims") or []):
            if str(c.get("id") or "") == str(claim):
                try:
                    return int(c.get("dispatch_count") or 0)
                except (TypeError, ValueError) as exc:
                    warn("step_grain_dispatch_count",
                         f"{type(exc).__name__}: {exc} — count reads as 0")
                    return 0
        return 0
    except Exception as exc:  # noqa: BLE001 — fail-open read
        warn("rlvr.step_grain.dispatch_count", f"{type(exc).__name__}: {exc}")
        return 0


def bump_dispatch_count(ws, claim: str) -> int:
    """#690: accrue ONE dispatch on the claim at the APPROVAL point —
    INDEPENDENT of promotion_attempts (the settlement-side cap the issue
    measured at 0 across 7 live dispatches). Canonical register write via
    ws_yaml (the single-writer renderer). Returns the new count; -1 on
    failure or unknown claim (fail-open telemetry, never the verdict)."""
    if not claim:
        return -1
    try:
        import ws_yaml as _wsy
        p = Path(ws) / "claim-register.yaml"
        doc = _wsy.yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for c in (doc.get("claims") or []):
            if str(c.get("id") or "") == str(claim):
                try:
                    n = int(c.get("dispatch_count") or 0) + 1
                except (TypeError, ValueError):
                    n = 1
                c["dispatch_count"] = n
                p.write_text(_wsy.canonical_dump(doc), encoding="utf-8")
                return n
        return -1
    except Exception as exc:  # noqa: BLE001 — fail-open telemetry
        warn("rlvr.step_grain.bump_dispatch_count",
             f"{type(exc).__name__}: {exc}")
        return -1


def cancel_step_open(ws, claim: str) -> bool:
    """#690 review HIGH: the reject-undo face — a dispatch REJECTED after
    the approval point (dispatch_gate rc=2, the #623/#624 undo path) never
    ran a worker, so the step ``_open_step`` opened is cancelled here:
    the untyped launch stash is consumed (the sync barrier lifts at once
    instead of riding out the stale TTL, and no phantom settle can bank
    this attempt later) and the claim's ``dispatch_count`` bump is rolled
    back (the retries budget is not charged for a dispatch that never
    dispatched). Only the untyped dispatch stash is this face's to
    consume — a typed sibling (verify / redteam / prediction-settle)
    belongs to its own act; a 1-F3 foreign envelope parked at the claim's
    path is LEFT INTACT (never consumed, never deleted). Idempotent:
    True when a stash was consumed, False when there was nothing to
    cancel. Fail-open: ONE warn, never raises into the undo path."""
    if not _ir._safe_stash_token(str(claim or "")):
        return False
    try:
        p = Path(ws) / _ir.LAUNCH_REL.format(claim=claim)
        if p.is_file():
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                doc = None
            if (isinstance(doc, dict) and "status" not in doc
                    and ("schema" not in doc
                         or doc.get("schema") == _ir.LAUNCH_SCHEMA)):
                p.unlink(missing_ok=True)
                # the attempt never dispatched — roll the accrual back
                # (floor 0; a dirty value degrades to the floor)
                import ws_yaml as _wsy
                reg = Path(ws) / "claim-register.yaml"
                if reg.is_file():
                    rdoc = (_wsy.yaml.safe_load(
                        reg.read_text(encoding="utf-8")) or {})
                    for c in (rdoc.get("claims") or []):
                        if str(c.get("id") or "") == str(claim):
                            try:
                                n = max(0, int(c.get("dispatch_count") or 0)
                                        - 1)
                            except (TypeError, ValueError):
                                n = 0
                            c["dispatch_count"] = n
                            reg.write_text(_wsy.canonical_dump(rdoc),
                                           encoding="utf-8")
                            break
                return True
        return False
    except Exception as exc:  # noqa: BLE001 — undo trouble never the verdict
        warn("rlvr.step_grain.cancel_step_open",
             f"{type(exc).__name__}: {exc}")
        return False
