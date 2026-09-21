# -*- coding: utf-8 -*-
"""wait_dispose.py — the settle→dispose transition (issue #244).

Field evidence (wbtest 2026-09-12): a worker delivered its claim → WAIT;
verification settled; the orchestrator moved on — the waiting worker sat
in dumb-wait (傻等) until the self-kill. Owner ruling: settled-CORRECT →
actively STOP the worker; settled-REFUTED → sanitized gap-only
re-dispatch; endless waiting is ALWAYS a contract violation.

This module owns the disposal half of that ruling, called from the settle
transaction (register_proven_gate.emit_settlements, the write_guard
register-carrier ALLOW face): when a claim lands TERMINAL, every waiting
worker BOUND to that claim gets a wake signal in the same beat —

  - REFUTED → ``type: dispatch`` whose payload embeds the GAP-ONLY redo
    context built from the claim's OWN diff slice via
    dispatch_context.build_redo_context (the #772 sanitizer: divergence
    pointers, never the verifier's derivation); NO claim-local slice
    (missing, unreadable, or error-marked) degrades to ``stop`` — never
    a workspace-global fallback, never an empty-gap dispatch;
  - every other terminal status → ``type: stop`` (settlement-confirmed
    dismissal; the wait tool consumes it, exits 0, status ``dismissed``).

The claim→worker binding is the one production already writes: the
unified ledger's ``dispatch`` rows (hooks/worker_budget_sinks) carry
``claim=C-NN`` + ``agent=<name>`` in detail; a bound waiting worker is a
pool member (lib_kunglao.scan_waiting_workers) whose id matches a
dispatch-row agent (bare segment of plugin-qualified ids, the same
matching rule as dispatch_gate._waiting_target_id).

Posture: fire-and-forget like every signal writer — a failed disposal
never moves the settlement (the ALLOW decision was already made); it
still leaves one stderr WARN (#275 fail-open trace discipline). Ledger
faces: ``worker_dismissed`` (stop) / ``dispatch`` with a redo-marked
detail (re-arm; the word is reused so the next settlement's duration
anchor moves to the redo wake).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# settled-REFUTED is the ONLY terminal that re-arms: the claim's answer was
# wrong, so the bound worker re-derives from the gap. Every other terminal
# status means the claim needs no further work (status_defs.TERMINAL doc)
# — its waiting pool is dismissed outright.
REDO_TERMINAL_STATUSES = frozenset({"REFUTED"})

# the agent marker the #461 linkage row writes into detail
_AGENT_RE = re.compile(r"\bagent=(\S+)")

_WARN_LAST: dict[str, str] = {}


def warn(op: str, reason: str) -> None:
    if _WARN_LAST.get(op) == reason:
        return
    _WARN_LAST[op] = reason
    print(f"[kunglao-agent] wait_dispose WARN (fail-open): "
          f"{op}: {reason}",
          file=sys.stderr)


def _utc_now_z() -> str:
    # #863 Family F: utc_now_z is the timestamp single source; the local
    # fallback keeps standalone invocation honest (kunglao_wait precedent).
    try:
        from harness_common import utc_now_z
        return utc_now_z()
    except ImportError:  # standalone invocation outside the skill checkout
        from datetime import datetime, timezone
        return (datetime.now(timezone.utc)
                .isoformat(timespec="seconds").replace("+00:00", "Z"))


def claim_redteam_diff(ws: Path, claim_id: str) -> Path | None:
    """The claim's OWN latest verify-redteam DIFF (per-claim, fail-open).

    Not the workspace-global latest (dispatch_context.latest_redteam_diff):
    a disposal disposes ONE claim, so a stale DIFF for a sibling claim must
    never ride its redo signal. Claim ids come from the DIFF's own title
    line, falling back to the file name (the #772 conventions)."""
    from dispatch_context import REDO_DIFF_GLOB, _extract_claim_id, \
        _REDO_TITLE_RE
    runs = Path(ws) / "runs"
    if not runs.is_dir():
        return None
    best: Path | None = None
    best_mtime = -1.0
    try:
        candidates = sorted(runs.glob(Path(REDO_DIFF_GLOB).name))
    except OSError:
        return None
    for p in candidates:
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:2048]
            mtime = p.stat().st_mtime
        except OSError:
            continue
        m = _REDO_TITLE_RE.search(head)
        cid = _extract_claim_id(m.group(1) if m else "", p.name)
        if cid != claim_id:
            continue
        if mtime > best_mtime:
            best, best_mtime = p, mtime
    return best


def waiting_workers_for_claim(ws: Path, claim_id: str) -> list[str]:
    """Waiting worker ids CURRENTLY bound to `claim_id`.

    Binding is the worker's LATEST dispatch row (append-only ledger, so
    the last `dispatch` row naming a worker is where it is now) — a
    worker re-dispatched from C-1 to C-2 must NOT be stopped when its
    older C-1 settles first (#244 r2). A worker whose latest dispatch is
    `claim_id` and whose status is `waiting` is disposed; everyone else
    stays put.

    Fail-open: a pool-scan or ledger outage yields [] — a disposal must
    never block the settlement on protocol hiccups."""
    ws = Path(ws)
    try:
        from _hooks_path import load_hooks_lib
        pool = load_hooks_lib().scan_waiting_workers(ws)
    except Exception as exc:  # noqa: BLE001 — fail-open disposal
        warn("waiting_pool", f"{type(exc).__name__}: {exc}")
        return []
    ids = {s.removeprefix("worker-status-") for s in pool}
    if not ids:
        return []
    try:
        from kunglao_log import _all_rows
        rows = _all_rows(ws)
    except Exception as exc:  # noqa: BLE001 — fail-open disposal
        warn("dispatch_rows", f"{type(exc).__name__}: {exc}")
        return []
    latest: dict[str, str] = {}  # agent (bare) -> claim of its LAST dispatch
    for row in rows:
        if row.get("action") != "dispatch":
            continue
        m = _AGENT_RE.search(str(row.get("detail") or ""))
        if not m:
            continue
        name = m.group(1).strip().rsplit(":", 1)[-1]
        latest[name] = str(row.get("claim") or "")
    return [name for name, cid in latest.items()
            if cid == claim_id and name in ids]


def write_settle_signal(ws: Path, worker_id: str, signal: dict) -> bool:
    """One single-shot wake signal file (fire-and-forget; never raises)."""
    path = Path(ws) / "runs" / f"wait-signal-{worker_id}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(signal, ensure_ascii=False),
                        encoding="utf-8")
        return True
    except OSError as exc:
        warn("write_settle_signal", f"{worker_id}: {exc}")
        return False


def dispose_waiting_pool(ws: Path, claim_id: str, to_status: str) -> int:
    """Dispose the waiting pool bound to a just-settled claim.

    Called from the settle transaction (emit_settlements) per transitioned
    claim. Returns the count of signals actually written (0 = nothing
    waiting / nothing landed). Never raises."""
    try:
        workers = waiting_workers_for_claim(ws, claim_id)
    except Exception as exc:  # noqa: BLE001 — disposal never blocks settle
        warn("dispose", f"{type(exc).__name__}: {exc}")
        return 0
    if not workers:
        return 0
    is_redo = to_status in REDO_TERMINAL_STATUSES
    redo: dict | None = None
    if is_redo:
        # The redo payload is built ONLY from the claim's OWN diff slice:
        # claim_redteam_diff returns None unless a diff names THIS claim,
        # and it is passed explicitly so build_redo_context's fallback to
        # the workspace-global latest DIFF can never fire (a sibling
        # claim's gap must not ride this claim's signal — the module's
        # per-claim contract, r2).
        diff = claim_redteam_diff(Path(ws), claim_id)
        if diff is None:
            is_redo = False  # no claim-local slice -> stop, never a re-arm
        else:
            try:
                from dispatch_context import build_redo_context
                redo = build_redo_context(Path(ws), diff)
            except Exception as exc:  # noqa: BLE001 — slice failure -> stop
                warn("redo_context", f"{type(exc).__name__}: {exc}")
                redo = None
            if redo is None or redo.get("error") is not None:
                # no CLEAN claim-local slice -> stop (never an empty-gap
                # dispatch, never a global fallback)
                is_redo = False
    ts = _utc_now_z()
    written = 0
    for worker_id in workers:
        signal: dict = {
            "type": "dispatch" if is_redo else "stop",
            "claim": claim_id,
            "ts": ts,
        }
        if is_redo and redo is not None:
            signal["redo"] = redo
        if not write_settle_signal(ws, worker_id, signal):
            continue
        written += 1
        try:
            from kunglao_log import emit
            if is_redo:
                emit(Path(ws), "hook:write_guard", "dispatch", claim=claim_id,
                     detail=f"redo-wake worker={worker_id} settle={to_status} "
                            f"gap_ref={(redo or {}).get('diff_ref') or '?'} "
                            f"(#244 settle→dispose: sanitized gap-only "
                            f"re-dispatch)")
            else:
                emit(Path(ws), "hook:write_guard", "worker_dismissed",
                     claim=claim_id,
                     detail=json.dumps(
                         {"worker": worker_id, "settle": to_status,
                          "reason": "settlement-confirmed dismissal (#244)"},
                         ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001 — logging never breaks settle
            warn("dispose_emit", f"{type(exc).__name__}: {exc}")
    return written
