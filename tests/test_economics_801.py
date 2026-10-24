# -*- coding: utf-8 -*-
"""tests/test_economics_801.py — issue #801 economics v2 (RED-first pins).

Face 1: the pre-LLM wake gate — a quiet workspace costs ZERO LLM tokens
(the wake verdict is computed host-side; only watchdog.fired / wake-class
bus events / park-expity inject a prompt).
Face 2: gate layering — format-class and self-health faces demote to WARN
+ telemetry sidecars (never rc=2); exactly five HARD classes still block.
Face 3: the machine:analysis cockpit ratio with an alarm at >1, plus the
rc1-audit DuckDB queries committed as a regression runner.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
TICK = SCRIPTS / "heartbeat_tick.py"
RUNNER = SCRIPTS / "experiments" / "rc1_econ_replay.py"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HOOKS))

from _factories import write_hook_state  # noqa: E402


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _make_ws(tmp_path: Path) -> Path:
    """A minimal workspace the tick accepts (claim register + fresh state)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir(parents=True)
    (ws / "notes").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    write_hook_state(
        ws, active_hooks=["cost_gate"], ts=_iso(_now()), tier="none",
        phase="IDLE", user_override={},
        expires_at=_iso(_now() + timedelta(minutes=25)))
    (ws / "runs" / ".heartbeat.json").write_text(
        json.dumps({"last_tick_ts": _iso(_now()),
                    "loop_registered": True}), encoding="utf-8")
    # two fresh tick rows: heartbeat-check's continuity standard (>=2
    # ticks within cadence) must pass for the fixture to be QUIET
    log = ws / "runs" / ".heartbeat.log"
    now = _now()
    log.write_text("\n".join(
        json.dumps({"ts": _iso(now - timedelta(minutes=m)), "actor": "tick"})
        for m in (10, 5)) + "\n", encoding="utf-8")
    return ws


def _park(ws: Path) -> None:
    """Persist the noop fingerprint so the zero-work park conjunction holds."""
    import heartbeat_tick
    (ws / "runs" / ".heartbeat-noop.json").write_text(json.dumps({
        "hash": heartbeat_tick.state_fingerprint(ws), "count": 1,
    }), encoding="utf-8")


def _tick_gate(ws: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TICK), str(ws), "--origin", "cron",
         "--wake-gate"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=180, cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": os.pathsep.join(
            [str(ROOT), str(SCRIPTS), str(HOOKS)])})


# ---------------------------------------------------------------------------
# Face 1 — the wake predicate (spec centerpiece, pure pins)
# ---------------------------------------------------------------------------

class TestWakePredicate:
    def test_quiet_is_no_wake(self):
        """Quiet hour: watchdog quiet, no events, park below expiry -> no wake."""
        import heartbeat_tick
        v = heartbeat_tick.wake_verdict(
            watchdog_fired=False, tick_events=(), quiet_streak=3)
        assert v["needed"] is False
        assert v["reasons"] == []

    def test_watchdog_fires_wake(self):
        import heartbeat_tick
        v = heartbeat_tick.wake_verdict(
            watchdog_fired=True,
            watchdog_reasons=["heartbeat-gap:42min"], tick_events=())
        assert v["needed"] is True
        assert any("watchdog" in r for r in v["reasons"])

    def test_wake_class_event_fires_wake(self):
        import heartbeat_tick
        v = heartbeat_tick.wake_verdict(
            watchdog_fired=False, tick_events=("settlement",))
        assert v["needed"] is True
        assert any("settlement" in r for r in v["reasons"])

    def test_park_expiry_fires_wake(self):
        import heartbeat_tick
        v = heartbeat_tick.wake_verdict(
            watchdog_fired=False, tick_events=(),
            quiet_streak=heartbeat_tick.PARK_EXPIRY_TICKS_DEFAULT)
        assert v["needed"] is True
        assert any("park-expiry" in r for r in v["reasons"])

    def test_expiry_default_is_36(self):
        import heartbeat_tick
        assert heartbeat_tick.PARK_EXPIRY_TICKS_DEFAULT == 36


# ---------------------------------------------------------------------------
# Face 1 — the token-meter pin (acceptance 1): quiet fixture -> ZERO prompts
# ---------------------------------------------------------------------------

class TestQuietHourZeroPrompts:
    def test_quiet_fixture_injects_zero_prompts(self, tmp_path):
        """THE pin: parked, healthy quiet workspace -> rc 0, QUIET marker,
        no WATCHDOG banner, report.wake.needed false. Before #801 the cron
        woke the LLM to conclude no-op (~750k input tok/h)."""
        ws = _make_ws(tmp_path)
        _park(ws)
        r = _tick_gate(ws)
        report = json.loads(
            (ws / "runs" / ".heartbeat-tick.json").read_text(encoding="utf-8"))
        assert r.returncode == 0, f"quiet tick must exit 0: {r.stderr[-400:]}"
        assert "QUIET:" in r.stdout
        assert "*** WATCHDOG" not in r.stdout, "a quiet wake injected a prompt"
        assert report.get("wake", {}).get("needed") is False

    def test_stale_heartbeat_wakes(self, tmp_path):
        """A watchdog reason (stale heartbeat) -> rc 3 + WAKE marker."""
        ws = _make_ws(tmp_path)
        _park(ws)
        stale = _iso(_now() - timedelta(hours=2))
        (ws / "runs" / ".heartbeat.json").write_text(
            json.dumps({"last_tick_ts": stale}), encoding="utf-8")
        r = _tick_gate(ws)
        report = json.loads(
            (ws / "runs" / ".heartbeat-tick.json").read_text(encoding="utf-8"))
        assert r.returncode == 3, f"wake must exit 3: {r.stderr[-400:]}"
        assert "WAKE:" in r.stdout
        assert report.get("wake", {}).get("needed") is True


# ---------------------------------------------------------------------------
# Face 2 — gate layering (acceptance 2 + 3)
# ---------------------------------------------------------------------------

class TestGateLayering:
    def test_hard_allowlist_exactly_five(self):
        """The spec centerpiece: exactly five HARD classes."""
        import gate_policy
        assert set(gate_policy.HARD_CLASSES) == {
            "corruption", "reward_integrity", "termination_budget",
            "evidence", "execution_surface"}
        assert gate_policy.should_block("format") is False
        assert gate_policy.should_block("self_health") is False
        for hard in gate_policy.HARD_CLASSES:
            assert gate_policy.should_block(hard) is True

    def test_format_rejection_demotes_to_warn(self, tmp_path):
        """A format-class rejection returns rc 0 + stderr WARN + ONE telemetry
        sidecar row (gate_class=format, exit_code=0) — NOT rc=2."""
        import dispatch_gate
        ws = _make_ws(tmp_path)
        rc = dispatch_gate._reject_with_guidance(
            "fmt_face", "envelope malformed", "fix the envelope", ws=ws)
        assert rc == 0, "format-class rejection must not block (was rc=2)"
        rows = [json.loads(ln) for ln in (
            ws / "runs" / "gate-rejections.jsonl").read_text(
                encoding="utf-8").splitlines() if ln.strip()]
        assert rows and rows[-1]["gate_class"] == "format"
        assert rows[-1]["exit_code"] == 0

    def test_execution_surface_still_blocks(self, tmp_path):
        """The mcp_prefix face's class (execution_surface) still returns rc 2."""
        import dispatch_gate
        ws = _make_ws(tmp_path)
        rc = dispatch_gate._reject_with_guidance(
            "mcp_prefix", "tool refused", "use the allowed tool", ws=ws,
            gate_class="execution_surface")
        assert rc == 2, "execution_surface must keep its teeth"

    def test_self_health_gate_error_never_blocks(self, tmp_path):
        """THE 51job FATAL shape: a crashed gate (ModuleNotFoundError-class)
        must WARN + telemetry + proceed, never rc=2 the action."""
        import dispatch_gate
        ws = _make_ws(tmp_path)
        rc = dispatch_gate._gate_error_reject(
            ws, "top1", None,
            RuntimeError("ModuleNotFoundError: notes_writer"), "fix it")
        assert rc == 0, "self-health failure must not block analysis"
        rows = [json.loads(ln) for ln in (
            ws / "runs" / "gate-rejections.jsonl").read_text(
                encoding="utf-8").splitlines() if ln.strip()]
        assert rows and rows[-1]["gate_class"] == "self_health"
        assert rows[-1]["exit_code"] == 0

    def test_write_guard_crash_fails_open_with_telemetry(
            self, tmp_path, monkeypatch):
        """write_guard locking the claim-register on its OWN crash is the
        production FATAL; the checker-crash arm must demote to WARN + allow."""
        import write_guard
        ws = _make_ws(tmp_path)
        target = ws / "notes" / "n-001.md"
        target.write_text("seed\n", encoding="utf-8")
        payload = {"tool_name": "Write", "cwd": str(ws),
                   "tool_input": {"file_path": str(target),
                                  "content": "# n-001\nbody\n"}}
        monkeypatch.setitem(sys.modules, "notes_writer", None)
        monkeypatch.setattr(write_guard, "_read_payload", lambda: payload)
        rc = write_guard.main()
        assert rc == 0, ("a crashed checker must not block the write "
                         "(the 51job shape)")
        rows = [json.loads(ln) for ln in (
            ws / "runs" / "gate-rejections.jsonl").read_text(
                encoding="utf-8").splitlines() if ln.strip()]
        assert any(r.get("gate_class") == "self_health" for r in rows)

    def test_corruption_register_contract_still_blocks(
            self, tmp_path, monkeypatch):
        """corruption class: a register post-image with an invented status
        word keeps its teeth (the write contract is not demoted)."""
        import write_guard
        ws = _make_ws(tmp_path)
        bad = ("claims:\n  - id: C-001\n"
               "    status: VERIFIED-BY-EXTRACTION\n"
               "    statement: invented status\n")
        payload = {"tool_name": "Write", "cwd": str(ws),
                   "tool_input": {
                       "file_path": str(ws / "claim-register.yaml"),
                       "content": bad}}
        monkeypatch.setattr(write_guard, "_read_payload", lambda: payload)
        rc = write_guard.main()
        assert rc == 2, "register corruption refusal must stay HARD"

    def test_reward_integrity_still_blocks(self):
        """reward_integrity: the blind-settlement read barrier keeps its
        teeth (settler may not launder identity through helper dispatch)."""
        import rt_read_barrier
        rc, err, _ctx = rt_read_barrier.evaluate(
            {"tool_name": "Task", "agent_type": "settler"})
        assert rc == 2, "settler identity-laundering refusal must stay HARD"
        assert "REJECT rt_read_barrier" in err

    def test_evidence_must_stop_still_blocks(self, tmp_path):
        """evidence class: the irreversible-action must-stop keeps its teeth."""
        import dispatch_gate
        rc = dispatch_gate._warn_must_stop(
            _make_ws(tmp_path), "C-1", "please sudo rm -rf /tmp", None)
        assert rc == 2, "must-stop must stay HARD"


# ---------------------------------------------------------------------------
# Face 3 — cockpit ratio + alarm (acceptance 5)
# ---------------------------------------------------------------------------

def _tx_row(machine_in: int, analysis_out: int, *,
            sidechain: bool, hour: int = 0) -> str:
    ts = f"2026-10-20T{hour:02d}:00:00.000Z"
    return json.dumps({
        "type": "assistant", "timestamp": ts, "isSidechain": sidechain,
        "message": {"role": "assistant", "usage": {
            "input_tokens": machine_in, "output_tokens": analysis_out}},
    }, ensure_ascii=False)


class TestCockpitRatio:
    def test_alarm_fires_when_ratio_over_one(self, tmp_path):
        import cost_input_capture as cic
        tx = tmp_path / "t.jsonl"
        tx.write_text("\n".join([
            _tx_row(5000, 100, sidechain=False),
            _tx_row(50, 1000, sidechain=True),
        ]) + "\n", encoding="utf-8")
        ratio = cic.compute_ratio(tx)
        assert ratio == pytest.approx(5000 / 1000)
        assert ratio > 1

    def test_healthy_ratio_below_one(self, tmp_path):
        import cost_input_capture as cic
        tx = tmp_path / "t.jsonl"
        tx.write_text("\n".join([
            _tx_row(500, 10, sidechain=False),
            _tx_row(10, 5000, sidechain=True),
        ]) + "\n", encoding="utf-8")
        assert cic.compute_ratio(tx) == pytest.approx(0.1)

    def test_process_event_writes_cockpit_and_alarms(self, tmp_path):
        import cost_input_capture as cic
        ws = _make_ws(tmp_path)
        tx = tmp_path / "t.jsonl"
        tx.write_text("\n".join([
            _tx_row(9000, 100, sidechain=False),
            _tx_row(10, 1000, sidechain=True),
        ]) + "\n", encoding="utf-8")
        cic.process_event({"cwd": str(ws), "tool_name": "Bash",
                           "tool_response": "no cost line here",
                           "transcript_path": str(tx)})
        face = json.loads(
            (ws / "runs" / ".cockpit-ratio.json").read_text(encoding="utf-8"))
        assert face["ratio"] > 1
        assert face["alarm"] is True
        ledger = (ws / "runs" / "logs").glob("kunglao-*.jsonl")
        rows = [json.loads(ln) for f in ledger for ln in
                f.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert any(r.get("action") == "cockpit_ratio_alarm" for r in rows)

    def test_ratio_words_registered(self):
        """Telemetry words are registered (sorted+unique EMIT_ACTIONS)."""
        sys.path.insert(0, str(SCRIPTS))
        from event_taxonomy import EMIT_ACTIONS
        assert "gate_warn" in EMIT_ACTIONS
        assert "cockpit_ratio_alarm" in EMIT_ACTIONS
        assert EMIT_ACTIONS == sorted(set(EMIT_ACTIONS))


# ---------------------------------------------------------------------------
# Face 3 — the rc1 regression runner (acceptance 6)
# ---------------------------------------------------------------------------

class TestRc1RegressionRunner:
    def test_runner_replays_fixture(self, tmp_path):
        """The rc1-audit queries replay: hourly machine:analysis series with
        flagged alarm hours, over the committed DuckDB-first runner."""
        ws = _make_ws(tmp_path)
        tx = tmp_path / "transcript.jsonl"
        tx.write_text("\n".join([
            _tx_row(60000, 500, sidechain=False, hour=1),
            _tx_row(10, 3000, sidechain=True, hour=1),
            _tx_row(60000, 500, sidechain=False, hour=2),
            _tx_row(10, 90000, sidechain=True, hour=2),
        ]) + "\n", encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(RUNNER), str(tx), "--ws", str(ws)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120,
            env={**os.environ, "PYTHONPATH": str(SCRIPTS)})
        assert r.returncode == 0, r.stderr[-400:]
        out = json.loads(r.stdout)
        hours = {h["hour"]: h for h in out["hours"]}
        h1 = hours["2026-10-20T01"]
        h2 = hours["2026-10-20T02"]
        assert h1["alarm"] is True
        assert h1["ratio"] == pytest.approx(60000 / 3000)
        assert h2["alarm"] is False
        assert h2["ratio"] == pytest.approx(60000 / 90000)
        assert out["alarm_hours"] == 1


# ---------------------------------------------------------------------------
# R2a — bounded repetition + ownership transfer (Standard 11)
# ---------------------------------------------------------------------------

class TestWarnFamilyBreaker:
    def test_below_bound_every_demotion_keeps_its_row(self, tmp_path):
        """Below the bound every demotion keeps its stderr WARN + sidecar
        row — the bound never hides fresh signal."""
        import gate_policy
        ws = _make_ws(tmp_path)
        for i in range(gate_policy.WARN_FAMILY_BOUND - 1):
            gate_policy.warn_sidecar(ws, "dispatch_gate", "format",
                                     f"msg {i}", name="fmt_face")
        rows = [json.loads(ln) for ln in (
            ws / "runs" / "gate-rejections.jsonl").read_text(
                encoding="utf-8").splitlines() if ln.strip()]
        assert len(rows) == gate_policy.WARN_FAMILY_BOUND - 1

    def test_392_warn_replay_trips_circuit_breaker(self, tmp_path):
        """THE replay pin (Standard 11): a synthetic 392-warn same-family
        sequence (the rc1 shape: 540/593 warns = six verbatim-repeated
        pathologies) trips the family breaker EXACTLY ONCE; the sidecar
        stops growing (circuit-break), the state file names the action,
        and a warn_breaker_tripped ledger row lands."""
        import gate_policy
        ws = _make_ws(tmp_path)
        for _ in range(392):
            gate_policy.warn_sidecar(ws, "dispatch_gate", "format",
                                     "same pathology", name="fmt_face")
        rows = [json.loads(ln) for ln in (
            ws / "runs" / "gate-rejections.jsonl").read_text(
                encoding="utf-8").splitlines() if ln.strip()]
        assert len(rows) == gate_policy.WARN_FAMILY_BOUND, (
            "circuit-break must stop the sidecar growth at the bound")
        state = json.loads(
            (ws / "runs" / ".warn-breaker.json").read_text(
                encoding="utf-8"))
        fam = state["families"]["dispatch_gate|format|fmt_face"]
        assert fam["action"] == "circuit-break"
        assert fam["suppressed"] == 392 - gate_policy.WARN_FAMILY_BOUND
        ledger = (ws / "runs" / "logs").glob("kunglao-*.jsonl")
        lrows = [json.loads(ln) for f in ledger for ln in
                 f.read_text(encoding="utf-8").splitlines() if ln.strip()]
        trips = [r for r in lrows
                 if r.get("action") == "warn_breaker_tripped"]
        assert len(trips) == 1, "the family trips EXACTLY once"
        assert "circuit-break" in trips[0].get("detail", "")

    def test_other_family_unaffected(self, tmp_path):
        """A tripped family must not silence a DIFFERENT family."""
        import gate_policy
        ws = _make_ws(tmp_path)
        for _ in range(gate_policy.WARN_FAMILY_BOUND + 5):
            gate_policy.warn_sidecar(ws, "dispatch_gate", "format",
                                     "same pathology", name="fmt_face")
        gate_policy.warn_sidecar(ws, "write_guard", "self_health",
                                 "different pathology", name="other_face")
        rows = [json.loads(ln) for ln in (
            ws / "runs" / "gate-rejections.jsonl").read_text(
                encoding="utf-8").splitlines() if ln.strip()]
        assert any(r.get("msg") == "different pathology" for r in rows), (
            "a tripped family must not silence a DIFFERENT family")
        state = json.loads(
            (ws / "runs" / ".warn-breaker.json").read_text(
                encoding="utf-8"))
        assert state["families"]["write_guard|self_health|other_face"][
            "count"] == 1

    def test_breaker_surfaces_in_tick_report(self, tmp_path):
        """The heartbeat face: the tick report names the tripped family
        (nobody-called 41h must become a surfaced, owned state)."""
        import gate_policy
        ws = _make_ws(tmp_path)
        for _ in range(gate_policy.WARN_FAMILY_BOUND + 1):
            gate_policy.warn_sidecar(ws, "dispatch_gate", "format",
                                     "same pathology", name="fmt_face")
        subprocess.run(
            [sys.executable, str(TICK), str(ws), "--origin", "cron"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=180, cwd=str(ROOT),
            env={**os.environ, "PYTHONPATH": os.pathsep.join(
                [str(ROOT), str(SCRIPTS), str(HOOKS)])})
        report = json.loads(
            (ws / "runs" / ".heartbeat-tick.json").read_text(
                encoding="utf-8"))
        fams = report.get("warn_breaker", {}).get("families", {})
        assert "dispatch_gate|format|fmt_face" in fams


# ---------------------------------------------------------------------------
# R2b — incremental telemetry (emit only on value change)
# ---------------------------------------------------------------------------

class TestIncrementalTelemetry:
    def test_same_value_emits_once_then_silent(self, tmp_path):
        """THE pin: an unchanged value (the dead rho=0.0 x76 shape) emits
        exactly once; every identical repeat is silent but counted."""
        import incremental_telemetry as it
        ws = _make_ws(tmp_path)
        assert it.should_emit(ws, "rho_eval", "rho=0.0") is True
        for _ in range(76):
            assert it.should_emit(ws, "rho_eval", "rho=0.0") is False
        state = json.loads(
            (ws / "runs" / ".telemetry-last.json").read_text(
                encoding="utf-8"))
        assert state["rho_eval"]["suppressed"] == 76

    def test_changed_value_emits_and_rearms(self, tmp_path):
        import incremental_telemetry as it
        ws = _make_ws(tmp_path)
        it.should_emit(ws, "rho_eval", "rho=0.0")
        it.should_emit(ws, "rho_eval", "rho=0.0")
        assert it.should_emit(ws, "rho_eval", "rho=0.37") is True
        assert it.should_emit(ws, "rho_eval", "rho=0.37") is False

    def test_faces_are_independent(self, tmp_path):
        import incremental_telemetry as it
        ws = _make_ws(tmp_path)
        it.should_emit(ws, "rank_feeds", "order=A|B")
        assert it.should_emit(ws, "statusline_snapshot", "state=analyzing") \
            is True

    def test_dead_rho_stops_detector_eval_spam(self, tmp_path, monkeypatch):
        """The wiring pin: repeated rho_sampler evaluations at the SAME rho
        land exactly ONE detector_eval row (production: 76 dead rows)."""
        import rho_verifier
        ws = _make_ws(tmp_path)
        calls = {"n": 0}

        class _Stub:
            @staticmethod
            def sample(_ws):
                calls["n"] += 1
                return {"rho": 0.0, "backend": "stub", "level": None,
                        "lexical": None}

        monkeypatch.setattr(rho_verifier, "get_backend", lambda: _Stub)
        monkeypatch.setattr(rho_verifier, "_mission_level", lambda _ws: None)
        for _ in range(4):
            rho_verifier.sample_and_pair(ws)
        ledger = (ws / "runs" / "logs").glob("kunglao-*.jsonl")
        rows = [json.loads(ln) for f in ledger for ln in
                f.read_text(encoding="utf-8").splitlines() if ln.strip()]
        evals = [r for r in rows if r.get("action") == "detector_eval"]
        assert calls["n"] == 4, "sampling itself must keep its cadence"
        assert len(evals) == 1, (
            f"dead-rho repeats must be silent, got {len(evals)} evals")

    def test_rank_feeds_keeps_per_run_emission(self, tmp_path, monkeypatch):
        """#801 R2b scoping pin: rank_feeds stays PER-RUN — the #157 replay
        spine (ranking exactly replayable from the event tail) and the #218
        last-attempt health bit pin the emit attempt itself, so identical
        rankings are NOT suppressed (unlike detector_eval/statusline)."""
        import priority_ratio as pr
        ws = _make_ws(tmp_path)
        ev = pr.EvidenceView(ws=ws)
        actions = [
            pr.Action(claim_id="C-1", action="dispatch", score=0.9,
                      skill=None, tier=2, attempts=0, cost=0.0,
                      feeds={"a": "1"}),
            pr.Action(claim_id="C-2", action="dispatch", score=0.1,
                      skill=None, tier=2, attempts=0, cost=0.0,
                      feeds={"a": "1"}),
        ]
        monkeypatch.setattr(pr, "round_index", lambda _ws: 1)
        ri = {"claims_hash": "0", "evidence_hash": "0",
              "posterior_hash": "0"}
        pr._emit_rank_feeds(ws, [], ev, ri, actions, 1)
        pr._emit_rank_feeds(ws, [], ev, ri, actions, 1)
        ledger = (ws / "runs" / "logs").glob("kunglao-*.jsonl")
        rows = [json.loads(ln) for f in ledger for ln in
                f.read_text(encoding="utf-8").splitlines() if ln.strip()]
        ranks = [r for r in rows if r.get("action") == "rank_feeds"]
        assert len(ranks) == 2, (
            f"per-run emission must hold, got {len(ranks)}")

    def test_statusline_emit_silent_when_state_unchanged(self, tmp_path):
        """The snapshot FILE stays fresh (display truth), but the
        statusline_snapshot LEDGER event fires only when the semantic
        state changed. Warm-up first: the very first emit can flip a
        ledger-observing probe code (feedback), so the steady-state
        contract is pinned after the probe codes stabilize."""
        import statusline_snapshot as ss
        ws = _make_ws(tmp_path)
        ss.write_snapshot(ws)  # warm-up (may flip a probe code)
        ss.write_snapshot(ws)  # steady-state value A
        ss.write_snapshot(ws)  # same value -> suppressed
        ss.write_snapshot(ws)  # same value -> suppressed
        ledger = (ws / "runs" / "logs").glob("kunglao-*.jsonl")
        rows = [json.loads(ln) for f in ledger for ln in
                f.read_text(encoding="utf-8").splitlines() if ln.strip()]
        emits = [r for r in rows
                 if r.get("action") == "statusline_snapshot"]
        assert len(emits) == 2, (
            f"steady-state repeats must be silent, got {len(emits)}")
        assert (ws / "runs" / ".kunglao-statusline.json").exists()


# ---------------------------------------------------------------------------
# R2c — unactuated detector evaluations are billed consumption
# ---------------------------------------------------------------------------

def _ledger_row(action: str, detector: str = "rho_sampler") -> str:
    return json.dumps({
        "ts": "2026-10-22T10:00:00Z", "actor": "rho_verifier",
        "action": action,
        "detail": json.dumps({"detector": detector}),
    }, ensure_ascii=False)


class TestUnactuatedDetectorBilling:
    def test_replay_reports_unactuated_61(self, tmp_path):
        """THE pin (62:1 production shape): 62 detector_eval + 1
        detector_fired -> unactuated = 61, eval:fire ratio reported."""
        ws = _make_ws(tmp_path)
        led = ws / "runs" / "logs" / "kunglao-2026-10-22.jsonl"
        led.parent.mkdir(parents=True, exist_ok=True)
        led.write_text("\n".join(
            [_ledger_row("detector_eval")] * 62
            + [_ledger_row("detector_fired")]) + "\n", encoding="utf-8")
        tx = tmp_path / "transcript.jsonl"
        tx.write_text(_tx_row(1000, 500, sidechain=False) + "\n",
                      encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(RUNNER), str(tx), "--ws", str(ws),
             "--ledger", str(led)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120,
            env={**os.environ, "PYTHONPATH": str(SCRIPTS)})
        assert r.returncode == 0, r.stderr[-400:]
        out = json.loads(r.stdout)
        acc = out["detector_accounting"]
        assert acc["detector_eval"] == 62
        assert acc["detector_fired"] == 1
        assert acc["unactuated"] == 61
        assert acc["eval_fire_ratio"] == 62.0

    def test_cockpit_face_carries_detector_consumption(self, tmp_path):
        """The live face: .cockpit-ratio.json carries the eval/fire/
        unactuated counts next to the ratio (142:1 shape observable live)."""
        import cost_input_capture as cic
        ws = _make_ws(tmp_path)
        led = ws / "runs" / "logs" / "kunglao-2026-10-22.jsonl"
        led.parent.mkdir(parents=True, exist_ok=True)
        led.write_text("\n".join(
            [_ledger_row("detector_eval")] * 142
            + [_ledger_row("detector_fired")]) + "\n", encoding="utf-8")
        tx = tmp_path / "t.jsonl"
        tx.write_text("\n".join([
            _tx_row(500, 10, sidechain=False),
            _tx_row(10, 5000, sidechain=True),
        ]) + "\n", encoding="utf-8")
        face = cic.cockpit_ratio(ws, tx)
        assert face is not None
        assert face["detector"]["detector_eval"] == 142
        assert face["detector"]["unactuated"] == 141

    def test_healthy_ledger_zero_unactuated(self, tmp_path):
        import cost_input_capture as cic
        ws = _make_ws(tmp_path)
        led = ws / "runs" / "logs" / "kunglao-2026-10-22.jsonl"
        led.parent.mkdir(parents=True, exist_ok=True)
        led.write_text("\n".join(
            [_ledger_row("detector_eval"),
             _ledger_row("detector_fired")]) + "\n", encoding="utf-8")
        tx = tmp_path / "t.jsonl"
        tx.write_text(_tx_row(10, 5000, sidechain=True) + "\n",
                      encoding="utf-8")
        face = cic.cockpit_ratio(ws, tx)
        assert face["detector"]["unactuated"] == 0

    def test_absent_ledger_failopen_no_detector_block(self, tmp_path):
        import cost_input_capture as cic
        ws = _make_ws(tmp_path)
        tx = tmp_path / "t.jsonl"
        tx.write_text(_tx_row(10, 5000, sidechain=True) + "\n",
                      encoding="utf-8")
        face = cic.cockpit_ratio(ws, tx)
        assert face is not None
        assert "detector" not in face
