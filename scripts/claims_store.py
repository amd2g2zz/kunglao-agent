# -*- coding: utf-8 -*-
"""claims_store — the ONE semantic owner of claim-state transitions (#800).

The defect this module closes: claim state was mutated as a side-effect
of gate passage by whoever was passing, with compensation instead of
ownership. `status_defs.py` owns the vocabulary; THIS module owns the
transitions. The dispatch approval+flip+step-open sequence — formerly a
hand-rolled saga across two hook processes compensated by a fail-open
triple undo (undo_dispatch_anchor -> reopen_claim_no_worker ->
cancel_step_open, #623/#624/#690) — is a journalled transaction here.

Ownership contract
------------------
- The declared ``LEGAL_TRANSITIONS`` matrix (status x event -> status)
  is DEFAULT-DENY: every undeclared (from_status, event) pair is
  refused at the store and recorded. Terminal statuses
  (status_defs.TERMINAL) carry no outgoing edges, so PROVEN ->
  IN_PROGRESS cannot happen by construction.
- Every transition — applied, refused, aborted, recovered — lands ONE
  provenance row (``runs/claims-provenance.jsonl``, schema
  ``claims-provenance/1``).
- ``ws_yaml`` stays the serializer (tool-face); this module is the
  semantic mutator. Per-file atomicity is tmp+rename.

The dispatch transaction (chosen mechanism: intent journal + verify)
--------------------------------------------------------------------
``begin_dispatch`` writes the intent journal
(``runs/.claims-intent.json``, schema ``claims-intent/1``) BEFORE the
first write. ``commit_dispatch`` applies the steps — anchor append,
launch stash, ONE atomic register rewrite carrying the status flip +
``evidence_tier_attempted`` + ``dispatch_count`` — marking each step in
the journal as it lands. ``abort_dispatch`` (the reject face) inverts
exactly the applied steps from the journal. ``recover`` (run on store
entry) rolls a journal back when its owner pid is dead or its ts
exceeds the window — a SIGKILL between mutator steps leaves no partial
state after recovery.

Faces
-----
- ``apply(ws, claim, event, actor, ...)``  — the single semantic mutator
- ``begin_dispatch`` / ``commit_dispatch`` / ``confirm_dispatch`` /
  ``abort_dispatch`` / ``recover`` — the dispatch transaction
"""
from __future__ import annotations

import json
import os
import subprocess  # noqa: F401 — (pid liveness uses os.kill; kept for typing parity)
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

#: the provenance log (append-only JSONL, one row per transition face)
PROVENANCE_REL = Path("runs") / "claims-provenance.jsonl"
PROVENANCE_SCHEMA = "claims-provenance/1"

#: the intent journal (ONE active dispatch intent per workspace — the
#: PreToolUse gate chain is serial for a given dispatch)
JOURNAL_REL = Path("runs") / ".claims-intent.json"
JOURNAL_SCHEMA = "claims-intent/1"

#: a journal older than this (or with a dead owner pid) is recovered
RECOVERY_WINDOW_S = 120.0

#: fallback anchor-log cap (the worker_budget_gates constant when the
#: hooks package is importable)
_ANCHOR_LOG_MAX_ROWS = 32


def _utc_now_z() -> str:
    try:
        from harness_common import utc_now_z
        return utc_now_z()
    except Exception:  # noqa: BLE001 — clock-source outage: strftime face
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------- the matrix

#: status x event -> status. DEFAULT-DENY: an undeclared pair is
#: refused. Status sets come from status_defs (the vocabulary owner);
#: TERMINAL statuses have NO outgoing edges by construction — this map
#: simply never lists them as a ``from``.
LEGAL_TRANSITIONS: dict[str, dict[str, str]] = {
    # the dispatch approval flip (the transaction's register step uses
    # the same edge; apply() exposes it to non-transaction faces)
    "dispatch": {"OPEN": "IN_PROGRESS"},
    # the reject/recovery face: an unconfirmed dispatch intent unwinds
    "abort_dispatch": {"IN_PROGRESS": "OPEN"},
    # mission_stall suspension — a PARK MUST carry a wake_condition
    # (status_defs carrier-consistency rule (f)); enforced in apply()
    "park": {"OPEN": "PARK", "IN_PROGRESS": "PARK"},
    # mission_stall.revive
    "revive": {"PARK": "OPEN"},
    # claim_expiry / stale-blocker faces
    "stale": {"OPEN": "STALE", "IN_PROGRESS": "STALE",
              "PARTIALLY-VERIFIED": "STALE", "PARTIAL": "STALE",
              "PARTIALLY_VERIFIED": "STALE"},
    # superseded_by closure (#59)
    "supersede": {"OPEN": "SUPERSEDED", "IN_PROGRESS": "SUPERSEDED",
                  "PARK": "SUPERSEDED", "PARTIALLY-VERIFIED": "SUPERSEDED",
                  "PARTIAL": "SUPERSEDED", "PARTIALLY_VERIFIED": "SUPERSEDED"},
    # DLQ promotion exhaustion (#36)
    "dead": {"OPEN": "DEAD", "IN_PROGRESS": "DEAD",
             "PARTIALLY-VERIFIED": "DEAD", "PARTIAL": "DEAD",
             "PARTIALLY_VERIFIED": "DEAD"},
    # settlement faces (the decisive register statuses)
    "settle_proven": {"IN_PROGRESS": "PROVEN",
                      "PARTIALLY-VERIFIED": "PROVEN",
                      "PARTIAL": "PROVEN", "PARTIALLY_VERIFIED": "PROVEN"},
    "settle_verified": {"IN_PROGRESS": "VERIFIED",
                        "PARTIALLY-VERIFIED": "VERIFIED",
                        "PARTIAL": "VERIFIED", "PARTIALLY_VERIFIED": "VERIFIED"},
    "settle_negative": {"IN_PROGRESS": "NEGATIVE",
                        "PARTIALLY-VERIFIED": "NEGATIVE",
                        "PARTIAL": "NEGATIVE", "PARTIALLY_VERIFIED": "NEGATIVE"},
    "settle_refuted": {"IN_PROGRESS": "REFUTED",
                       "PARTIALLY-VERIFIED": "REFUTED",
                       "PARTIAL": "REFUTED", "PARTIALLY_VERIFIED": "REFUTED"},
    "settle_deferred": {"OPEN": "DEFERRED", "IN_PROGRESS": "DEFERRED",
                        "PARTIALLY-VERIFIED": "DEFERRED",
                        "PARTIAL": "DEFERRED", "PARTIALLY_VERIFIED": "DEFERRED"},
    # verification-debt face
    "verify_partial": {"IN_PROGRESS": "PARTIALLY-VERIFIED"},
}

TRANSITION_EVENTS = frozenset(LEGAL_TRANSITIONS)


@dataclass(frozen=True)
class TransitionResult:
    """One transition face's outcome (never raises into the caller)."""
    ok: bool
    claim: str
    event: str
    from_status: str | None
    to_status: str | None
    reason: str = ""
    journal_id: str | None = None


def _load_register_doc(ws) -> dict:
    import ws_yaml
    p = Path(ws) / "claim-register.yaml"
    if not p.is_file():
        return {}
    return ws_yaml.yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _save_register_doc(ws, doc: dict) -> None:
    """Atomic register rewrite: tmp + rename (the store's write face)."""
    import ws_yaml
    p = Path(ws) / "claim-register.yaml"
    tmp = p.with_suffix(".yaml.tmp")
    tmp.write_text(ws_yaml.canonical_dump(doc), encoding="utf-8")
    tmp.replace(p)


def _append_provenance(ws, row: dict) -> None:
    p = Path(ws) / PROVENANCE_REL
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        base = {"schema": PROVENANCE_SCHEMA, "ts": _utc_now_z()}
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({**base, **row}, ensure_ascii=False) + "\n")
    except OSError as exc:
        # provenance never blocks the transition face — but never silently
        print(f"[kunglao-agent] claims_store WARN (fail-open): "
              f"provenance append failed ({type(exc).__name__}: {exc})",
              file=sys.stderr)


# ------------------------------------------------------------- the mutator

def apply(ws, claim: str, event: str, actor: str, *, evidence: str = "",
          wake_condition: str | None = None) -> TransitionResult:
    """The single semantic mutator. Looks up (status, event) in the
    matrix; an undeclared pair is refused and recorded. PARK demands a
    wake_condition. The register rewrite is tmp+rename atomic."""
    doc = _load_register_doc(ws)
    target = None
    for c in (doc.get("claims") or []):
        if str(c.get("id") or "") == str(claim):
            target = c
            break
    from_status = str(target.get("status") or "") if target else None
    if target is None:
        res = TransitionResult(False, claim, event, from_status, None,
                               reason="unknown-claim")
        _append_provenance(ws, {"claim": claim, "event": event,
                                "from": from_status, "to": None,
                                "actor": actor, "evidence": evidence,
                                "outcome": "refused", "reason": "unknown-claim"})
        return res
    edge = LEGAL_TRANSITIONS.get(event, {}).get(from_status)
    if edge is None:
        reason = (f"illegal-transition: {from_status or '<none>'} x "
                  f"{event} is not declared in LEGAL_TRANSITIONS")
        res = TransitionResult(False, claim, event, from_status or None,
                               None, reason=reason)
        _append_provenance(ws, {"claim": claim, "event": event,
                                "from": from_status, "to": None,
                                "actor": actor, "evidence": evidence,
                                "outcome": "refused", "reason": reason})
        return res
    if event == "park" and not (wake_condition or "").strip():
        reason = "wake-condition-required: a PARK must carry a wake_condition"
        _append_provenance(ws, {"claim": claim, "event": event,
                                "from": from_status, "to": edge,
                                "actor": actor, "evidence": evidence,
                                "outcome": "refused", "reason": reason})
        return TransitionResult(False, claim, event, from_status, None,
                                reason=reason)
    target["status"] = edge
    if event == "park":
        target["wake_condition"] = wake_condition
    _save_register_doc(ws, doc)
    _append_provenance(ws, {"claim": claim, "event": event,
                            "from": from_status, "to": edge,
                            "actor": actor, "evidence": evidence,
                            "outcome": "applied", "reason": ""})
    return TransitionResult(True, claim, event, from_status, edge)


# ------------------------------------------------- the dispatch transaction

def _journal_path(ws) -> Path:
    return Path(ws) / JOURNAL_REL


def _journal_load(ws) -> dict | None:
    p = _journal_path(ws)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")) or None
    except (OSError, ValueError):
        return None


def _journal_save(ws, journal: dict | None) -> None:
    """Atomic journal write; ``None`` clears it."""
    p = _journal_path(ws)
    if journal is None:
        try:
            p.unlink(missing_ok=True)
        except OSError as exc:
            print(f"[kunglao-agent] claims_store WARN (fail-open): "
                  f"journal clear failed ({type(exc).__name__}: {exc})",
                  file=sys.stderr)
        return
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(journal, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True


def begin_dispatch(ws, claim: str, actor: str, *, tier: int = 0,
                   prompt: str = "", agent: str = "",
                   method_family: str | None = None,
                   branch_budget: dict | None = None) -> TransitionResult:
    """Open the dispatch intent: journal BEFORE the first write. The
    journal carries the register's byte-exact before-image so the abort
    and recovery faces restore it verbatim."""
    stale = _journal_load(ws)
    if stale is not None:
        if stale.get("claim") == str(claim) and _pid_alive(stale.get("pid", 0)):
            return TransitionResult(False, claim, "dispatch", None, None,
                                    reason="intent-in-flight",
                                    journal_id=stale.get("id"))
        recover(ws)  # a dead/foreign journal is rolled back first
    reg_path = Path(ws) / "claim-register.yaml"
    before = reg_path.read_text(encoding="utf-8") if reg_path.is_file() else None
    journal = {
        "schema": JOURNAL_SCHEMA,
        "id": uuid.uuid4().hex[:12],
        "kind": "dispatch",
        "claim": str(claim),
        "actor": actor,
        "pid": os.getpid(),
        "ts": _utc_now_z(),
        "state": "pending",
        "tier": int(tier or 0),
        "prompt": prompt or "",
        "agent": agent or "",
        "method_family": method_family or "",
        "branch_budget": dict(branch_budget or {}),
        "register_before": before,
        "stash_path": str(Path("runs") / f"dispatch-launch-{claim}.json"),
        "stash_existed": (Path(ws) / "runs" / f"dispatch-launch-{claim}.json").is_file(),
        "anchor_row": None,
        "applied": [],
    }
    _journal_save(ws, journal)
    return TransitionResult(True, claim, "dispatch", None, None,
                            reason="intent-open", journal_id=journal["id"])


def _txn_step_anchor(ws, journal: dict) -> bool:
    """Step 1 — the per-dispatch nonce append. Row shape and cap match
    worker_budget_gates.record_dispatch_anchor; the appended row is
    captured in the journal for exact-tail rollback."""
    claim = journal["claim"]
    row = {"ts": _utc_now_z(), "claim": claim, "agent": journal.get("agent", "")}
    log = (Path(ws) / "runs"
           / f".dispatch-anchor-{str(claim).replace('-', '')}.jsonl")
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        if log.is_file():
            rows = [ln for ln in log.read_text(encoding="utf-8").splitlines()
                    if ln.strip()]
        rows = rows[-(_ANCHOR_LOG_MAX_ROWS - 1):]
        rows.append(json.dumps(row, ensure_ascii=False))
        tmp = log.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(rows) + "\n", encoding="utf-8")
        tmp.replace(log)
        journal["anchor_row"] = row
        return True
    except OSError:
        return False


def _txn_step_stash(ws, journal: dict) -> bool:
    """Step 2 — the launch stash (the settle face's claim mapping +
    phi_before + branch_budget). Delegates to
    rlvr.incremental_reward.record_launch (the stash shape's owner);
    create-only semantics are what the sync barrier guarantees."""
    try:
        from rlvr import incremental_reward as ir
        doc = ir.record_launch(ws, journal["claim"],
                               journal.get("method_family") or "dispatch",
                               branch_budget=journal.get("branch_budget")
                               or None)
        return doc is not None
    except Exception:  # noqa: BLE001 — telemetry face, never the verdict
        return False


def _txn_step_register(ws, journal: dict) -> bool:
    """Step 3 — ONE atomic register rewrite: the OPEN -> IN_PROGRESS
    flip + the eta raise (max, monotonic) + the dispatch_count accrual.
    Formerly three separate rewrites across two modules (#624/#680/
    #690)."""
    doc = _load_register_doc(ws)
    for c in (doc.get("claims") or []):
        if str(c.get("id") or "") != str(journal["claim"]):
            continue
        if str(c.get("status") or "").upper() != "OPEN":
            return False  # #624: in-flight claims are not dispatchable
        c["status"] = "IN_PROGRESS"
        try:
            eta = int(c.get("evidence_tier_attempted", 0))
        except (TypeError, ValueError):
            eta = 0
        tier = int(journal.get("tier") or 0)
        if tier in (1, 2, 3) and tier > eta:
            c["evidence_tier_attempted"] = tier
        try:
            c["dispatch_count"] = int(c.get("dispatch_count") or 0) + 1
        except (TypeError, ValueError):
            c["dispatch_count"] = 1
        _save_register_doc(ws, doc)
        return True
    return False


def _txn_run_step(ws, journal: dict, name: str, step) -> bool:
    """Apply ONE transaction step and mark it in the journal BEFORE the
    next step starts — the mark is what makes a mid-crash invertible."""
    ok = step(ws, journal)
    if name not in journal["applied"]:
        journal["applied"].append(name)
        _journal_save(ws, journal)
    return ok


_TXN_STEPS = (("anchor", _txn_step_anchor), ("stash", _txn_step_stash),
              ("register", _txn_step_register))


def commit_dispatch(ws, claim: str) -> TransitionResult:
    """Apply the journalled steps with per-step journal marks. A crash
    between steps leaves a journal naming exactly what landed — which is
    what recover() inverts."""
    journal = _journal_load(ws)
    if journal is None or journal.get("claim") != str(claim):
        return TransitionResult(False, claim, "dispatch", None, None,
                                reason="no-intent")
    for name, step in _TXN_STEPS:
        ok = _txn_run_step(ws, journal, name, step)
        if not ok:
            journal["state"] = "failed"
            _journal_save(ws, journal)
            _append_provenance(ws, {"claim": claim, "event": "dispatch",
                                    "from": "OPEN", "to": "IN_PROGRESS",
                                    "actor": journal.get("actor", ""),
                                    "outcome": "failed",
                                    "reason": f"step-{name}-failed",
                                    "journal": journal["id"]})
            return TransitionResult(False, claim, "dispatch", "OPEN", None,
                                    reason=f"step-{name}-failed",
                                    journal_id=journal["id"])
    journal["state"] = "committed"
    _journal_save(ws, journal)
    _append_provenance(ws, {"claim": claim, "event": "dispatch",
                            "from": "OPEN", "to": "IN_PROGRESS",
                            "actor": journal.get("actor", ""),
                            "outcome": "applied", "reason": "",
                            "journal": journal["id"]})
    return TransitionResult(True, claim, "dispatch", "OPEN", "IN_PROGRESS",
                            reason="committed", journal_id=journal["id"])


def _txn_rollback(ws, journal: dict) -> None:
    """Invert EXACTLY the applied steps (reverse order, journal-driven —
    no fresh-tail heuristics)."""
    for name in reversed(list(journal.get("applied") or [])):
        if name == "register":
            before = journal.get("register_before")
            reg = Path(ws) / "claim-register.yaml"
            tmp = reg.with_suffix(".yaml.tmp")
            tmp.write_text(before if before is not None else "", encoding="utf-8")
            tmp.replace(reg)
        elif name == "anchor":
            row = journal.get("anchor_row")
            if row is None:
                continue
            log = (Path(ws) / "runs" / f".dispatch-anchor-"
                   f"{str(journal['claim']).replace('-', '')}.jsonl")
            if not log.is_file():
                continue
            try:
                rows = [ln for ln in
                        log.read_text(encoding="utf-8").splitlines()
                        if ln.strip()]
                if rows and json.loads(rows[-1]) == row:
                    rows = rows[:-1]
                tmp = log.with_suffix(".jsonl.tmp")
                tmp.write_text(("\n".join(rows) + "\n") if rows else "",
                               encoding="utf-8")
                tmp.replace(log)
            except (OSError, ValueError):
                continue
        elif name == "stash":
            if not journal.get("stash_existed"):
                try:
                    (Path(ws) / journal["stash_path"]).unlink(missing_ok=True)
                except OSError as exc:
                    print(f"[kunglao-agent] claims_store WARN (fail-open): "
                          f"stash rollback unlink failed "
                          f"({type(exc).__name__}: {exc})", file=sys.stderr)


def abort_dispatch(ws, claim: str, actor: str = "") -> TransitionResult:
    """The reject face: invert exactly what the commit applied. Idempotent
    — a reject with nothing journalled is a no-op, never a failure."""
    journal = _journal_load(ws)
    if journal is None or journal.get("claim") != str(claim):
        return TransitionResult(True, claim, "abort_dispatch", None, None,
                                reason="no-intent")
    from_status = "IN_PROGRESS" if "register" in (journal.get("applied") or []) \
        else None
    _txn_rollback(ws, journal)
    _journal_save(ws, None)
    _append_provenance(ws, {"claim": claim, "event": "abort_dispatch",
                            "from": from_status, "to": "OPEN",
                            "actor": actor or journal.get("actor", ""),
                            "outcome": "aborted", "reason": "reject-undo",
                            "journal": journal["id"]})
    return TransitionResult(True, claim, "abort_dispatch", from_status,
                            "OPEN", reason="aborted", journal_id=journal["id"])


def confirm_dispatch(ws, claim: str) -> bool:
    """The rc=0 face: the gate chain approved — the journal's work stands."""
    journal = _journal_load(ws)
    if journal is None or journal.get("claim") != str(claim):
        return False
    _journal_save(ws, None)
    return True


def recover(ws) -> list[TransitionResult]:
    """Roll back journals whose owner pid is dead or whose ts exceeds
    the window — the crash-in-the-middle face. Returns one result per
    recovered journal (zero or one: the journal is single-slot)."""
    journal = _journal_load(ws)
    if journal is None:
        return []
    fresh = True
    try:
        ts = datetime.strptime(str(journal.get("ts")), "%Y-%m-%dT%H:%M:%SZ") \
            .replace(tzinfo=timezone.utc)
        fresh = (datetime.now(timezone.utc) - ts) <= timedelta(
            seconds=RECOVERY_WINDOW_S)
    except (ValueError, TypeError):
        fresh = False
    if fresh and _pid_alive(journal.get("pid", 0)):
        return []  # a live chain owns this intent — hands off
    applied = list(journal.get("applied") or [])
    _txn_rollback(ws, journal)
    _journal_save(ws, None)
    from_status = "IN_PROGRESS" if "register" in applied else None
    _append_provenance(ws, {"claim": journal.get("claim", ""),
                            "event": str(journal.get("kind") or "dispatch"),
                            "from": from_status, "to": "OPEN",
                            "actor": "claims_store.recover",
                            "outcome": "recovered",
                            "reason": f"journal-{journal.get('state', 'unknown')}",
                            "journal": journal.get("id")})
    return [TransitionResult(True, journal.get("claim", ""), "recover",
                             from_status, "OPEN", reason="recovered",
                             journal_id=journal.get("id"))]
