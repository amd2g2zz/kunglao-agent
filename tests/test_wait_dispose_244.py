#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_wait_dispose_244.py — #244 WAIT pool settle-to-dispose.

Field evidence (wbtest 2026-09-12): a worker delivered its claim -> WAIT;
red-team verification settled; the orchestrator moved on — the waiting
worker sat in dumb-wait (傻等) until the ~30 min self-kill (exit 3/4,
status: failed, polluting failure telemetry). Contract after #244:

  1. Signal taxonomy: the wait signal gains ``type: dispatch | stop``.
     ``stop`` = settlement-confirmed dismissal — the wait tool consumes it,
     exits 0, compacts the ledger status to ``dismissed`` (NOT failed).
     Type-less signals (the pre-#244 shape) stay dispatch (compat).
  2. Settlement disposition hook: when a claim settles TERMINAL in the
     register-carrier ALLOW path (the settle transaction —
     register_proven_gate.emit_settlements), every waiting worker bound to
     that claim is disposed in the same beat:
       - REFUTED -> ``type: dispatch`` signal whose payload carries the
         GAP-ONLY redo input built via dispatch_context.build_redo_context
         (divergence pointer, NEVER the verifier's derivation);
       - every other terminal status (PROVEN/VERIFIED/...) -> ``type: stop``.
  3. Honest terminals: the wait self-kill reads ``status: unscheduled``
     (``failed`` is reserved for real failures); ``dismissed`` and
     ``unscheduled`` are TERMINAL worker statuses (liveness: freed slots).
  4. Floors: worker_pulse warns on stale WAITING workers (a dead waiting
     worker used to be invisible — pulse exempted waiting from zombie
     flags); the statusline workers face counts waiting + stale_waiting.

Subprocess for the wait tool (the loop IS the mechanism); in-process for
the settle hook and the floors.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "kunglao_wait.py"

POLL_S = "0.12"
MAX_ROUNDS = "10"

STATUS_TOKEN = re.compile(r"status:\s*(\S+)")


def _env(**over: str) -> dict:
    e = dict(os.environ)
    e["KUNGLAO_WAIT_POLL_S"] = POLL_S
    e["KUNGLAO_WAIT_MAX_ROUNDS"] = MAX_ROUNDS
    e["PYTHONIOENCODING"] = "utf-8"
    e.update(over)
    return e


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _waiting_ledger(ws: Path, agent: str = "kunglao-worker",
                    last: str = "waiting") -> Path:
    p = ws / "runs" / f"worker-status-{agent}.md"
    p.write_text(
        "[12:00] step: started task | status: in-progress\n"
        "[12:30] step: delivered | status: done\n"
        f"[12:31] wait: awaiting signal | status: {last}\n",
        encoding="utf-8")
    return p


def _bind_claim(ws: Path, claim: str = "C-1",
                agent: str = "kunglao-worker") -> None:
    """The claim->agent binding as production writes it: a dispatch row on
    the unified ledger (hooks/worker_budget_sinks detail carries agent=)."""
    import kunglao_log
    kunglao_log.emit(ws, "hook:worker_budget", "dispatch", claim=claim,
                     detail=f"tier=1 tools=Read agent={agent} "
                            f"(#461 linkage: renew + arm + phase=DISPATCH)")


def _register(old: str, new: str, claim: str = "C-1") -> tuple[str, str]:
    def _txt(status: str) -> str:
        return ("claims:\n"
                f"- id: {claim}\n  status: {status}\n"
                "  promotion_attempts: 0\n")
    return _txt(old), _txt(new)


def _settle(ws: Path, old: str, new: str) -> int:
    from register_proven_gate import emit_settlements
    return emit_settlements(ws, new, old)


def _signal(ws: Path, agent: str = "kunglao-worker") -> Path:
    return ws / "runs" / f"wait-signal-{agent}.json"


# ---- worker-side subprocess helpers (mirror test_kunglao_wait_902) --------

def _popen(ws: Path, claim: str | None = None) -> subprocess.Popen:
    args = [sys.executable, str(TOOL), "--worker", "kunglao-worker"]
    if claim:
        args += ["--claim", claim]
    return subprocess.Popen(
        args, cwd=str(ws), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", env=_env())


def _last_status(p: Path) -> str | None:
    m = STATUS_TOKEN.findall(p.read_text(encoding="utf-8", errors="replace"))
    return m[-1] if m else None


def _wait_for(predicate, timeout: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _spawn_until_waiting(ws: Path, claim: str | None = "C-1"
                         ) -> subprocess.Popen:
    proc = _popen(ws, claim=claim)
    try:
        assert _wait_for(
            lambda: _signal(ws).parent.joinpath(
                f"worker-status-kunglao-worker.md").exists()
            and _last_status(ws / "runs" / "worker-status-kunglao-worker.md")
            == "waiting")
    except Exception:
        proc.kill()
        proc.wait(timeout=5)
        raise
    return proc


# ---- shared DIFF fixture (the verifier's derivation MUST NOT leak) ---------

DIFF_BODY = """\
# Red-team verification: claim C-1 anchor recovery
## Claim under attack
producer claimed anchor 9001 for sec_user_id via string sweep
## My independent derivation
recomputed from raw bytes: actual anchor 3446, delta -555
sha256 of recomputed region: 3f9a11c2d47b6e8055aa12bb34cc90ee
## Attack attempts
search granularity suspected wrong for the v4 tokenizer path
scope assumption challenged as unfounded
## RED-TEAM VERDICT: REFUTED
## GAPs (if any)
- anchor mismatch at sec_user_id: producer value not reproduced from raw
  bytes; evidence gap on which tokenizer version applies
"""


@pytest.fixture
def diff_ws(tmp_path: Path) -> Path:
    ws = _mk_ws(tmp_path)
    (ws / "runs" / "verify-redteam-C-1.md").write_text(
        DIFF_BODY, encoding="utf-8")
    return ws


# ===========================================================================
# (a) CONFIRMED settle -> stop signal lands within the settle transaction
# ===========================================================================

class TestSettleStopSignal:
    def test_proven_settle_writes_stop_signal(self, tmp_path: Path) -> None:
        ws = _mk_ws(tmp_path)
        _waiting_ledger(ws)
        _bind_claim(ws, "C-1")
        old, new = _register("OPEN", "PROVEN")
        n = _settle(ws, old, new)
        assert n == 1, "the PROVEN transition must settle"
        sig = _signal(ws)
        assert sig.exists(), (
            "settled-CORRECT must actively STOP the bound waiting worker: "
            "a stop signal must land within the settle transaction")
        data = json.loads(sig.read_text(encoding="utf-8"))
        assert data.get("type") == "stop"
        assert data.get("claim") == "C-1"
        assert data.get("ts"), "signal must carry a ts field"

    def test_stop_signal_emits_worker_dismissed_row(
            self, tmp_path: Path) -> None:
        ws = _mk_ws(tmp_path)
        _waiting_ledger(ws)
        _bind_claim(ws, "C-1")
        old, new = _register("OPEN", "PROVEN")
        _settle(ws, old, new)
        from kunglao_log import _all_rows
        rows = [r for r in _all_rows(ws)
                if r.get("action") == "worker_dismissed"
                and r.get("claim") == "C-1"]
        assert rows, "the dismissal must leave one ledger row (observability)"

    def test_unbound_waiting_worker_untouched(self, tmp_path: Path) -> None:
        ws = _mk_ws(tmp_path)
        _waiting_ledger(ws)  # waiting, but no dispatch row binds it to C-1
        old, new = _register("OPEN", "PROVEN")
        _settle(ws, old, new)
        assert not _signal(ws).exists(), (
            "a waiting worker NOT bound to the settled claim must stay put")


# ===========================================================================
# (b) REFUTED settle -> dispatch signal with the GAP-ONLY redo payload
# ===========================================================================

class TestSettleRedoDispatch:
    def test_refuted_settle_writes_redo_dispatch_signal(
            self, diff_ws: Path) -> None:
        ws = diff_ws
        _waiting_ledger(ws)
        _bind_claim(ws, "C-1")
        old, new = _register("OPEN", "REFUTED")
        _settle(ws, old, new)
        sig = _signal(ws)
        assert sig.exists(), (
            "settled-REFUTED must re-arm the bound waiting worker with a "
            "gap-only redo dispatch signal")
        data = json.loads(sig.read_text(encoding="utf-8"))
        assert data.get("type") == "dispatch"
        assert data.get("claim") == "C-1"
        redo = data.get("redo")
        assert isinstance(redo, dict), (
            "the dispatch signal payload must embed the redo context")

    def test_redo_payload_gap_only_no_verifier_derivation(
            self, diff_ws: Path) -> None:
        ws = diff_ws
        _waiting_ledger(ws)
        _bind_claim(ws, "C-1")
        old, new = _register("OPEN", "REFUTED")
        _settle(ws, old, new)
        raw = _signal(ws).read_text(encoding="utf-8")
        payload = json.loads(raw)
        redo = payload["redo"]
        # the divergence pointer MUST be there...
        assert redo.get("sanitized") is True
        assert "sec_user_id" in raw, (
            "the redo payload must carry WHERE it diverged (gap shape)")
        # ...the verifier's own derivation MUST NOT be
        assert "3446" not in raw, (
            "the verifier's derived value must never ride the redo signal")
        assert "3f9a11c2" not in raw, (
            "the verifier's derived anchor hash must never ride the signal")
        assert "My independent derivation" not in raw, (
            "conclusion lines must never ride the redo signal")
        # and it must be the same slice the existing tool builds (wiring,
        # not a new policy): byte-equal to dispatch_context's own output
        from dispatch_context import build_redo_context
        expected = build_redo_context(
            ws, ws / "runs" / "verify-redteam-C-1.md")
        assert redo == expected, (
            "the signal payload must be BUILT VIA the existing "
            "--redo-diff builder, not a parallel sanitizer")

    def test_refuted_signal_emits_dispatch_ledger_row(
            self, diff_ws: Path) -> None:
        ws = diff_ws
        _waiting_ledger(ws)
        _bind_claim(ws, "C-1")
        old, new = _register("OPEN", "REFUTED")
        _settle(ws, old, new)
        from kunglao_log import _all_rows
        rows = [r for r in _all_rows(ws)
                if r.get("action") == "dispatch" and r.get("claim") == "C-1"
                and "redo" in str(r.get("detail") or "")]
        assert rows, "the redo wake must leave a dispatch row (duration anchor)"


# ===========================================================================
# (c) worker side: stop signal -> exit 0 dismissed; self-kill -> unscheduled
# ===========================================================================

class TestWorkerDismissFace:
    def test_stop_signal_consumed_rc0_dismissed(self, tmp_path: Path) -> None:
        ws = _mk_ws(tmp_path)
        proc = _spawn_until_waiting(ws)
        try:
            _signal(ws).write_text(json.dumps({
                "type": "stop", "claim": "C-1",
                "ts": "2026-09-12T00:00:00Z"}), encoding="utf-8")
            rc = proc.wait(timeout=10)
        finally:
            if proc.poll() is None:  # pragma: no cover — runaway guard
                proc.kill()
        assert rc == 0, f"dismissal must exit 0, got rc={rc}"
        status_file = ws / "runs" / "worker-status-kunglao-worker.md"
        assert _last_status(status_file) == "dismissed", (
            "the dismissed terminal must compact the status to 'dismissed', "
            "not 'failed'")
        assert not _signal(ws).exists(), "signal is single-shot"
        out = proc.stdout.read() if proc.stdout and not proc.stdout.closed \
            else ""
        assert "C-1" in out, "stdout is the agent-facing context face"

    def test_typeless_signal_still_unwaits_compat(self, tmp_path: Path) -> None:
        ws = _mk_ws(tmp_path)
        proc = _spawn_until_waiting(ws)
        try:
            _signal(ws).write_text(json.dumps({
                "claim": "C-7", "ts": "2026-09-12T00:00:00Z"}),
                encoding="utf-8")
            rc = proc.wait(timeout=10)
        finally:
            if proc.poll() is None:  # pragma: no cover
                proc.kill()
        assert rc == 0
        status_file = ws / "runs" / "worker-status-kunglao-worker.md"
        assert _last_status(status_file) == "in-progress", (
            "pre-#244 type-less signals keep the UNWAIT contract")

    def test_redo_signal_unwaits_in_progress(self, tmp_path: Path) -> None:
        ws = _mk_ws(tmp_path)
        proc = _spawn_until_waiting(ws)
        try:
            _signal(ws).write_text(json.dumps({
                "type": "dispatch", "claim": "C-1",
                "ts": "2026-09-12T00:00:00Z",
                "redo": {"kind": "REDO", "gap": "anchor mismatch"}}),
                encoding="utf-8")
            rc = proc.wait(timeout=10)
        finally:
            if proc.poll() is None:  # pragma: no cover
                proc.kill()
        assert rc == 0
        status_file = ws / "runs" / "worker-status-kunglao-worker.md"
        assert _last_status(status_file) == "in-progress"


class TestSelfKillUnscheduled:
    def test_self_kill_terminal_reads_unscheduled(self, tmp_path: Path) -> None:
        ws = _mk_ws(tmp_path)
        r = subprocess.run(
            [sys.executable, str(TOOL), "--worker", "kunglao-worker",
             "--claim", "C-9"],
            cwd=str(ws), capture_output=True, text=True, encoding="utf-8",
            errors="replace",
            env=_env(KUNGLAO_WAIT_POLL_S="0.05",
                     KUNGLAO_WAIT_MAX_ROUNDS="1"),
            timeout=15)
        assert r.returncode == 3
        status_file = ws / "runs" / "worker-status-kunglao-worker.md"
        body = status_file.read_text(encoding="utf-8")
        assert _last_status(status_file) == "unscheduled", (
            "the self-kill terminal is 'unscheduled' (honest telemetry) — "
            "'failed' is reserved for real failures")
        assert "self-killed" in body
        assert "status: failed" not in body

    def test_dismissed_and_unscheduled_are_terminal_liveness(
            self, tmp_path: Path) -> None:
        ws = _mk_ws(tmp_path)
        lib_spec = importlib.util.spec_from_file_location(
            "lib_kunglao_wait_dispose", ROOT / "hooks" / "lib_kunglao.py")
        lib = importlib.util.module_from_spec(lib_spec)
        lib_spec.loader.exec_module(lib)
        for token in ("dismissed", "unscheduled"):
            assert token in lib.TERMINAL_WORKER_STATUSES, (
                f"'{token}' must end liveness — a dismissed/unscheduled "
                f"worker must not hold a slot")
        for token in ("dismissed", "unscheduled"):
            _waiting_ledger(ws, last=token)
            active, _stuck = lib.scan_active_workers(ws)
            assert active == 0, f"'{token}' worker must not count active"


# ===========================================================================
# floors: taxonomy + pulse staleness + statusline face
# ===========================================================================

class TestFloors:
    def test_worker_dismissed_registered_sorted_unique(self) -> None:
        import event_taxonomy as et
        words = et.EMIT_ACTIONS
        assert "worker_dismissed" in words, (
            "#244: the dismissal face needs a controlled vocabulary word")
        assert words == sorted(set(words)), (
            "EMIT_ACTIONS must stay sorted + unique (anchor test is strict)")

    def test_pulse_warns_stale_waiting_worker(self, tmp_path: Path) -> None:
        import worker_pulse as wp
        ws = _mk_ws(tmp_path)
        p = _waiting_ledger(ws)
        old = time.time() - 30 * 60
        os.utime(p, (old, old))
        msg = wp._check_stale_workers(ws)
        assert msg, "a stale WAITING worker must WARN (it used to be invisible)"
        assert "kunglao-worker" in msg
        assert "waiting" in msg.lower()

    def test_pulse_quiet_on_fresh_waiting_worker(
            self, tmp_path: Path) -> None:
        import worker_pulse as wp
        ws = _mk_ws(tmp_path)
        _waiting_ledger(ws)  # fresh mtime
        assert wp._check_stale_workers(ws) == ''

    def test_statusline_workers_face_counts_waiting(
            self, tmp_path: Path) -> None:
        import statusline_snapshot as sls
        ws = _mk_ws(tmp_path)
        _waiting_ledger(ws)
        face = sls._perf_face(ws)
        workers = face["workers"]
        assert workers.get("waiting") == 1
        assert workers.get("stale_waiting") == 0

    def test_statusline_workers_face_counts_stale_waiting(
            self, tmp_path: Path) -> None:
        import statusline_snapshot as sls
        ws = _mk_ws(tmp_path)
        p = _waiting_ledger(ws)
        old = time.time() - 30 * 60
        os.utime(p, (old, old))
        face = sls._perf_face(ws)
        assert face["workers"].get("stale_waiting") == 1


# ===========================================================================
# signal taxonomy at the writer: the dispatch-gate wake carries type
# ===========================================================================

class TestGateSignalTaxonomy:
    def test_gate_wake_signal_carries_dispatch_type(
            self, tmp_path: Path) -> None:
        ws = _mk_ws(tmp_path)
        _waiting_ledger(ws)
        from _hooks_path import load_hooks_lib
        lib = load_hooks_lib()
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "runs").mkdir()
            _w = Path(td) / "runs" / "worker-status-kunglao-worker.md"
            _w.write_text("[12:31] wait: awaiting signal | status: waiting\n",
                          encoding="utf-8")
            stems = lib.scan_waiting_workers(Path(td))
            assert stems, "sanity: the waiting scan keys on the status file"


# ===========================================================================
# r2: the redo slice is claim-LOCAL (reviewer probes)
# ===========================================================================

class TestRedoSliceIsClaimLocal:
    def test_sibling_diff_never_rides_the_signal(self, tmp_path: Path) -> None:
        """Reviewer probe r2/HIGH: with only a SIBLING claim's diff on
        disk, the REFUTED settle must NOT deliver the sibling's diff_ref
        or gap text — no claim-local slice -> stop."""
        ws = _mk_ws(tmp_path)
        (ws / "runs" / "verify-redteam-C-9.md").write_text(
            "# Red-team verification: claim C-9 sibling anchor\n"
            "## My independent derivation\n"
            "recomputed: actual anchor 777\n"
            "## RED-TEAM VERDICT: REFUTED\n"
            "## GAPs (if any)\n"
            "- CINQUE sibling gap shape must not travel\n",
            encoding="utf-8")
        _waiting_ledger(ws)
        _bind_claim(ws, "C-1")
        old, new = _register("OPEN", "REFUTED")
        _settle(ws, old, new)
        sig = _signal(ws)
        assert sig.exists()
        data = json.loads(sig.read_text(encoding="utf-8"))
        assert data.get("type") == "stop", (
            "no claim-local slice must stop the worker — the workspace-"
            "global latest DIFF (C-9's) must never ride C-1's signal")
        raw = sig.read_text(encoding="utf-8")
        assert "CINQUE" not in raw
        assert "verify-redteam-C-9" not in raw

    def test_no_diff_anywhere_stops_not_empty_dispatch(
            self, tmp_path: Path) -> None:
        """Reviewer probe r2/HIGH: REFUTED settle with no DIFF anywhere on
        disk -> stop signal (a type: dispatch with an empty gap is
        forbidden)."""
        ws = _mk_ws(tmp_path)
        _waiting_ledger(ws)
        _bind_claim(ws, "C-1")
        old, new = _register("OPEN", "REFUTED")
        _settle(ws, old, new)
        sig = _signal(ws)
        assert sig.exists()
        data = json.loads(sig.read_text(encoding="utf-8"))
        assert data.get("type") == "stop", (
            "no diff anywhere -> stop; an empty-gap re-dispatch re-arms "
            "the worker with nothing to re-derive from")


# ===========================================================================
# r2: binding is the worker's LATEST dispatch row (reviewer probe)
# ===========================================================================

class TestLatestDispatchBinding:
    def test_stale_claim_binding_does_not_prematurely_dismiss(
            self, tmp_path: Path) -> None:
        """Reviewer probe r2/MEDIUM: a worker re-dispatched from C-1 to
        C-2 must NOT be stopped when its older C-1 settles first; it IS
        disposed when its current claim C-2 settles."""
        ws = _mk_ws(tmp_path)
        _waiting_ledger(ws)
        import kunglao_log
        kunglao_log.emit(ws, "hook:worker_budget", "dispatch", claim="C-1",
                         detail="tier=1 tools=Read agent=kunglao-worker "
                                "(#461 linkage)")
        kunglao_log.emit(ws, "hook:worker_budget", "dispatch", claim="C-2",
                         detail="tier=1 tools=Read agent=kunglao-worker "
                                "(#461 linkage)")
        # older claim C-1 settles first
        _settle(ws, *_register("OPEN", "PROVEN", claim="C-1"))
        assert not _signal(ws).exists(), (
            "binding is the LATEST dispatch row: an older C-1 settlement "
            "must not stop a worker now bound to C-2")
        # current claim C-2 settles
        _settle(ws, *_register("OPEN", "PROVEN", claim="C-2"))
        sig = _signal(ws)
        assert sig.exists(), "the CURRENT claim's settlement must dispose"
        assert json.loads(sig.read_text(encoding="utf-8")).get("type") == \
            "stop"
