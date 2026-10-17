# -*- coding: utf-8 -*-
"""tests/test_park_face_740.py — the zero-work park posture (Face 3 of the
progress-coupling card, #740).

The defect (RC1-proven): the tick machinery (seven gate:always channel-tick
mechanisms + think_seat + the unconditional ledger/cockpit block) ran on
EVERY tick even when zero dispatchable work existed — burning the very
budget the analysis needed (RC1 evidence: 396 statusline snapshots,
129 stale re-flags, 500 queue rebuilds vs 36 dispatches).

The contract under test:

  (i)   the park conjunction (dispatchable==0 AND active_workers==0 AND
        no fresh wake-class bus rows AND state fingerprint unchanged since
        the persisted noop hash, cold start excluded) parks the tick: the
        eight registry mechanisms + think_seat do not run, the
        ledger/cockpit block is skipped, report["parked"] carries
        {reason, wake}, and action_taken starts with PARK (the #237
        contract — an empty field is the idle fault, so park must name
        itself);
  (ii)  any single conjunct breaking lifts the park within one pass
        (machinery runs);
  (iii) the preserved set runs every parked pass: renew, selfcheck,
        reconcile, the durable tick row, the watchdog verdict, and the
        noop breaker stays armed — a 6-identical-ticks chain on a
        parked-and-healthy workspace (waiting fleet, fresh wait flags)
        never reaches rc=2;
  (iv)  park lifts within one pass of a register byte change;
  (v)   fail-open: a crashing park evaluation degrades to NOT-parked
        (machinery runs); undecidable inputs never park.

The registry flip itself is declarative (不入册不许跑): a mechanism whose
gate reads `parked` is skipped by ANY scheduler host while the conjunction
holds — pinned here at the run_due face, not only at the tick face.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import kunglao_log  # noqa: E402
import mechanism_scheduler as ms  # noqa: E402
import think_seat  # noqa: E402

import heartbeat_tick as ht  # noqa: E402

# The eight mechanisms the card flips from gate:always to gate:parked
# (the seven channel-tick mechanisms + think_seat).
PARKED_EIGHT = ("env_probe", "stale_feedback", "cadence_advisor",
                "slot_monitor", "verify_watch", "premise_expiry",
                "rotation_induction", "think_seat")

NOOP_STATE = Path("runs") / ".heartbeat-noop.json"


# ---------------------------------------------------------------- helpers --

def _ws(tmp_path: Path) -> Path:
    """Minimal workspace the chain scripts accept (claims: [] = zero
    dispatchable work through the real ranking machinery)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def _seed_noop(ws: Path) -> str:
    """Persist the CURRENT fingerprint as the noop breaker state — the
    workspace then reads as unchanged on the next pass."""
    fp = ht.state_fingerprint(ws)
    (ws / NOOP_STATE).write_text(json.dumps({"hash": fp, "count": 1}),
                                 encoding="utf-8")
    return fp


def _waiting_worker(ws: Path, wid: str = "C001") -> None:
    """A delivered worker polling for the next dispatch (fresh mtime)."""
    (ws / "runs" / f"worker-status-{wid}.md").write_text(
        "[2026-10-10T00:00Z] step: x | status: waiting\n", encoding="utf-8")


def _active_worker(ws: Path, wid: str = "C001") -> None:
    (ws / "runs" / f"worker-status-{wid}.md").write_text(
        "[2026-10-10T00:00Z] step: x | status: in-progress\n", encoding="utf-8")


def _parked_ws(tmp_path: Path) -> Path:
    """A workspace satisfying the full park conjunction."""
    ws = _ws(tmp_path)
    _seed_noop(ws)
    return ws


def _read_report(ws: Path) -> dict:
    return json.loads(
        (ws / "runs" / ".heartbeat-tick.json").read_text(encoding="utf-8"))


def _tick_rows(ws: Path) -> int:
    log = ws / "runs" / ".heartbeat.log"
    if not log.exists():
        return 0
    return len([ln for ln in log.read_text(encoding="utf-8").splitlines()
                if ln.strip()])


# ==========================================================================
# the declarative registry flip (不入册不许跑 — a gate diff, no tick code)
# ==========================================================================

class TestRegistryFlip:
    def test_shipped_registry_flips_the_eight_to_parked(self):
        entries, errors = ms.load_registry()
        assert not errors, errors
        by = {e["name"]: e for e in entries}
        for name in PARKED_EIGHT:
            assert by[name]["trigger"]["gate"] == "parked", name
        # untouched postures: the host, the settlement feed, and the
        # event-gated forensics keep their gates.
        assert by["tick_host"]["trigger"]["gate"] == "always"
        assert by["credit_settle"]["trigger"]["gate"] == "always"
        assert by["workspace_monitor"]["trigger"]["gate"] == "events_seen"
        assert by["policy_retro"]["trigger"]["gate"] == "policy_due"

    def test_parked_gate_is_registered(self):
        assert "parked" in ms.GATES

    def test_parked_gate_not_due_while_parked(self, tmp_path):
        ws = _parked_ws(tmp_path)
        assert ms.GATES["parked"](ws, set()) is False

    def test_parked_gate_due_when_events_fresh(self, tmp_path):
        ws = _parked_ws(tmp_path)
        assert ms.GATES["parked"](ws, {"settlement"}) is True

    def test_registry_diff_alone_parks_any_host(self, tmp_path):
        """run_due with the REAL registry on a parked workspace: none of
        the eight run, whatever host drove the pass."""
        ws = _parked_ws(tmp_path)
        calls: list = []

        def _spy(script, ws_arg, *extra):
            calls.append(script)
            return {"rc": 0, "stdout": "", "stderr": ""}

        out = ms.run_due(ws, budget_s=30, runner=_spy)
        for name in PARKED_EIGHT:
            assert name in out["skipped"], (name, out["skipped"])
            assert name not in out["ran"], name
        # the registry was walked (the settlement feed keeps its always gate
        # and is the one tick channel this parked workspace still runs)
        assert "credit_settle" in out["ran"]


# ==========================================================================
# the conjunction evaluator
# ==========================================================================

class TestParkConjunction:
    def test_full_conjunction_parks(self, tmp_path):
        assert ms.is_parked(_parked_ws(tmp_path)) is True

    def test_first_tick_never_parks_cold_start(self, tmp_path):
        """No persisted fingerprint = cold start (the Face-1
        _persisted_sig empty shape): the first pass always runs."""
        assert ms.is_parked(_ws(tmp_path)) is False

    def test_active_worker_breaks_conjunction(self, tmp_path):
        ws = _parked_ws(tmp_path)
        _active_worker(ws)
        assert ms.is_parked(ws) is False

    def test_fresh_wake_class_event_breaks_conjunction(self, tmp_path):
        ws = _parked_ws(tmp_path)
        kunglao_log.emit(ws, "test", "claim_settled", detail="wake")
        assert ms.is_parked(ws) is False

    def test_fingerprint_change_breaks_conjunction(self, tmp_path):
        ws = _parked_ws(tmp_path)
        # a register byte changes the hash input, not the dispatch surface
        with (ws / "claim-register.yaml").open("a", encoding="utf-8") as fh:
            fh.write("# register byte changed\n")
        assert ms.is_parked(ws) is False

    def test_dispatchable_work_breaks_conjunction(self, tmp_path,
                                                  monkeypatch):
        ws = _parked_ws(tmp_path)
        # the ranking seam (same isolation the 711 seat tests use): the
        # conjunction wiring is what is pinned here, not the ranker.
        monkeypatch.setattr(think_seat, "dispatchable_count",
                            lambda ws_arg: 2)
        assert ms.is_parked(ws) is False

    def test_undecidable_dispatchable_never_parks(self, tmp_path,
                                                  monkeypatch):
        """dispatchable_count None = undecidable — fail-open to candidacy."""
        ws = _parked_ws(tmp_path)
        monkeypatch.setattr(think_seat, "dispatchable_count",
                            lambda ws_arg: None)
        assert ms.is_parked(ws) is False

    def test_corrupt_noop_state_never_parks(self, tmp_path):
        ws = _ws(tmp_path)
        (ws / NOOP_STATE).write_text("{not json", encoding="utf-8")
        assert ms.is_parked(ws) is False

    def test_is_parked_fail_open_on_internal_crash(self, tmp_path,
                                                   monkeypatch):
        ws = _parked_ws(tmp_path)
        monkeypatch.setattr(think_seat, "dispatchable_count",
                            lambda ws_arg: (_ for _ in ()).throw(
                                RuntimeError("probe down")))
        assert ms.is_parked(ws) is False

    def test_peek_does_not_consume_the_bus(self, tmp_path):
        """The park evaluation must never steal a wake: a non-committing
        bus read leaves the offset untouched for the real pass."""
        ws = _parked_ws(tmp_path)
        kunglao_log.emit(ws, "test", "claim_settled", detail="wake")
        peeked = ms.read_new_events(ws, commit=False)
        assert "settlement" in peeked["classes"]
        again = ms.read_new_events(ws)  # committing read sees the same row
        assert "settlement" in again["classes"]


# ==========================================================================
# (i) the tick-level park face
# ==========================================================================

class TestTickParkFace:
    def test_conjunction_parks_the_machinery(self, tmp_path, monkeypatch):
        ws = _parked_ws(tmp_path)
        mech_calls: list = []
        real_mech = ht._run_mechanisms

        def spy_mech(ws_arg, runner):
            mech_calls.append(ws_arg)
            return real_mech(ws_arg, runner=runner)

        monkeypatch.setattr(ht, "_run_mechanisms", spy_mech)
        rc = ht.main([str(ws)])
        assert mech_calls == [], "a parked pass must not run the pass"
        report = _read_report(ws)
        assert isinstance(report.get("parked"), dict)
        assert "reason" in report["parked"] and "wake" in report["parked"]
        assert report["action_taken"].startswith("PARK"), report["action_taken"]
        assert report["mechanisms"]["ran"] == []
        assert "think" not in report, "think_seat must not run"
        assert rc in (0, 1)  # the parked face itself never invents rc=2

    def test_park_face_runs_on_every_identical_pass(self, tmp_path):
        ws = _parked_ws(tmp_path)
        assert ht.main([str(ws)]) in (0, 1)
        assert _read_report(ws).get("parked")
        assert ht.main([str(ws)]) in (0, 1)
        assert _read_report(ws).get("parked")


# ==========================================================================
# (ii) any conjunct breaking lifts the park within one pass
# ==========================================================================

class TestParkLifts:
    def test_dispatchable_work_lifts_park(self, tmp_path, monkeypatch):
        ws = _parked_ws(tmp_path)
        monkeypatch.setattr(think_seat, "dispatchable_count",
                            lambda ws_arg: 2)
        ht.main([str(ws)])
        report = _read_report(ws)
        assert "parked" not in report
        assert "env_probe" in report["mechanisms"]["ran"]

    def test_active_worker_lifts_park(self, tmp_path):
        ws = _parked_ws(tmp_path)
        _active_worker(ws)
        ht.main([str(ws)])
        report = _read_report(ws)
        assert "parked" not in report
        assert "env_probe" in report["mechanisms"]["ran"]

    def test_fresh_event_lifts_park(self, tmp_path):
        ws = _parked_ws(tmp_path)
        kunglao_log.emit(ws, "test", "claim_settled", detail="wake")
        ht.main([str(ws)])
        report = _read_report(ws)
        assert "parked" not in report
        assert "settlement" in (report["mechanisms"].get("events_seen") or [])

    def test_fingerprint_change_lifts_park(self, tmp_path):
        ws = _parked_ws(tmp_path)
        with (ws / "claim-register.yaml").open("a", encoding="utf-8") as fh:
            fh.write("# register byte changed\n")
        ht.main([str(ws)])
        report = _read_report(ws)
        assert "parked" not in report
        assert "env_probe" in report["mechanisms"]["ran"]


# ==========================================================================
# (iv) park lifts within one pass of a register byte change
# ==========================================================================

class TestParkLiftsMidChain:
    def test_register_byte_change_lifts_a_parked_chain(self, tmp_path):
        ws = _parked_ws(tmp_path)
        ht.main([str(ws)])
        assert _read_report(ws).get("parked"), "chain must be parked first"
        with (ws / "claim-register.yaml").open("a", encoding="utf-8") as fh:
            fh.write("# a decision landed in the register\n")
        ht.main([str(ws)])
        report = _read_report(ws)
        assert "parked" not in report
        assert "env_probe" in report["mechanisms"]["ran"]

    def test_event_arrival_lifts_a_parked_chain(self, tmp_path):
        ws = _parked_ws(tmp_path)
        ht.main([str(ws)])
        assert _read_report(ws).get("parked")
        kunglao_log.emit(ws, "test", "mission_stall", detail="wake")
        ht.main([str(ws)])
        report = _read_report(ws)
        assert "parked" not in report


# ==========================================================================
# (iii) the preserved set runs every parked pass
# ==========================================================================

class TestPreservedSet:
    def test_preserved_steps_run_and_breaker_stays_armed(self, tmp_path,
                                                         monkeypatch):
        """6 identical parked ticks on a parked-and-healthy workspace
        (waiting fleet, fresh wait flags): renew/selfcheck/reconcile run,
        the durable tick row lands every pass, the watchdog is evaluated,
        and the noop breaker stays armed WITHOUT reaching rc=2."""
        ws = _parked_ws(tmp_path)
        _waiting_worker(ws)
        calls: list = []
        real_run = ht.run

        def recording_run(script, ws_arg, *extra):
            calls.append([script, list(extra)])
            return real_run(script, ws_arg, *extra)

        monkeypatch.setattr(ht, "run", recording_run)
        rows_before = _tick_rows(ws)
        breaker = json.loads((ws / NOOP_STATE).read_text(encoding="utf-8"))
        assert breaker["count"] == 1
        for i in range(1, 7):
            rc = ht.main([str(ws)])
            report = _read_report(ws)
            assert report.get("parked"), f"pass {i} must stay parked"
            assert rc != 2, f"pass {i} tripped the breaker on a healthy park"
            assert "idle_circuit_breaker" not in report
            this_pass = calls[-4:]
            assert ["hooks_selfcheck.py", []] in this_pass
            assert ["hook_activation.py", ["--renew"]] in this_pass, (
                "renew is non-negotiable on a parked pass")
            assert ["hook_activation.py", ["--reconcile"]] in this_pass
            assert ["hook_activation.py", ["--heartbeat-check"]] in this_pass
            assert isinstance(report.get("watchdog"), dict), (
                "the watchdog verdict is preserved on a parked pass")
            assert _tick_rows(ws) == rows_before + i, (
                "the durable tick row appends every parked pass")
        breaker = json.loads((ws / NOOP_STATE).read_text(encoding="utf-8"))
        assert breaker["count"] == 7, (
            "the breaker executed (and counted) every parked pass")

    def test_breaker_escalates_when_no_one_waits(self, tmp_path):
        """The park is the breaker's ordered predecessor, not a suppression:
        a parked workspace with NO waiting fleet still reaches rc=2 at the
        breaker threshold (the empty action_taken is filled by PARK, the
        stop verdict still fires)."""
        ws = _parked_ws(tmp_path)
        rcs = [ht.main([str(ws)]) for _ in range(6)]
        assert 2 in rcs, rcs
        report = _read_report(ws)
        assert report["idle_circuit_breaker"]["tripped"] is True
        assert report["action_taken"].startswith("PARK")


# ==========================================================================
# (v) fail-open: the park evaluation crashing degrades to NOT-parked
# ==========================================================================

class TestParkFailOpen:
    def test_park_evaluation_crash_runs_machinery(self, tmp_path,
                                                  monkeypatch):
        ws = _parked_ws(tmp_path)

        def boom(ws_arg, **kw):
            raise RuntimeError("park evaluation down")

        monkeypatch.setattr(ms, "is_parked", boom)
        ht.main([str(ws)])
        report = _read_report(ws)
        assert "parked" not in report
        assert "env_probe" in report["mechanisms"]["ran"]

    def test_scheduler_import_failure_runs_machinery(self, tmp_path,
                                                     monkeypatch):
        """The tick's park import seam is fail-open like every watcher."""
        ws = _parked_ws(tmp_path)
        real_import = __import__

        def broken_import(name, *a, **kw):
            if name == "mechanism_scheduler":
                raise ImportError("scheduler gone")
            return real_import(name, *a, **kw)

        monkeypatch.setattr("builtins.__import__", broken_import)
        ht.main([str(ws)])
        report = _read_report(ws)
        assert "parked" not in report


# ==========================================================================
# the cadence ceiling is untouched by the park
# ==========================================================================

class TestCadenceCeilingUnchanged:
    def test_park_never_legitimizes_a_ttl_plus_interval(self):
        """Park = the advisor's quiet branch at its 25m ceiling; the hard
        interval gate still rejects anything at or past the activation TTL.
        The park adds no new cadence authority — this pins the ceiling."""
        import external_kicker as ek
        assert ek.validate_interval(25) is None
        with pytest.raises(ValueError):
            ek.validate_interval(30)
        import cadence_advisor as ca
        assert ca.CEIL_MIN < 30
