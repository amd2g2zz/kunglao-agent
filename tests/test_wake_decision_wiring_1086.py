# -*- coding: utf-8 -*-
"""tests/test_wake_decision_wiring_1086.py — #1086 S21: the wake decision
seat's first runtime caller.

#685 built the wake decision as a recorded action — the scheduling five
(sleep / wake_on / probe / close_loop / none) selected by Gumbel top-k with
exact Plackett-Luce propensities — and its own words say "the decision
module is the recorded seat, the orchestrator applies". Nothing ever
applied it: no import caller, no mechanism entry. The S18 wrapper closed
the prompt-registration bypass but still injected on EVERY wake verdict,
so the action layer stayed dead code with a perfect paper trail. This
module pins the wiring:

  1. the WAKE branch consults the seat exactly once and records ONE
     kind=scheduling decision row with its exact propensity and an
     honest probability_source (the dispatch face's vocabulary —
     selection_law_exact for a draw, unknown for a deterministic face;
     never a marginal dressed up as a law);
  2. a drawn `none` injects NOTHING — the two layers say different
     things and both are right: the gate said "there is work to look
     at", the action layer said "no wake is owed". A legal zero-cost
     outcome, not a fault;
  3. the QUIET branch never consults the seat (zero sampling on the
     quiet path — sampling again after a quiet verdict is pure overhead),
     and neither does STOP (a mandated stop) nor a gate FAULT (fail
     toward waking: the seat must never get to veto a broken gate's
     wake, that is the never-wakes posture);
  4. a broken seat fails toward waking too: loud warn, injection
     proceeds;
  5. the real seat through the real wrapper CLI, deterministic under a
     fixed decision seed (--decision-seed): seed 0 draws close_loop and
     stages the prompt, seed 1 draws none and stages nothing — the
     sampler stays live (production draws OS-entropy rng) while the
     pins never flake.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
for _p in (SCRIPTS, HOOKS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from _factories import write_hook_state  # noqa: E402

#: flat priors, k = 1 on a bare workspace: the first draw is uniform over
# the scheduling five, so propensity 1/5 pins the exact-law claim
FLAT_PROPENSITY = 0.2
#: seeds verified against scheduling_selection.gumbel_topk under the flat
# priors on a bare workspace (k = 1): seed 0 -> close_loop, seed 1 -> none
SEED_ACTION = 0
SEED_NONE = 1


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_runner(rc: int, stdout: str, stderr: str = ""):
    def _run(cmd, *, timeout=None):
        return _FakeCompleted(rc, stdout, stderr)
    return _run


class _Recorder:
    """The delivery seam: records every call (the exactly-once pin)."""

    def __init__(self):
        self.calls: list[tuple] = []

    def __call__(self, prompt: str, ws, *, claude_bin="claude"):
        self.calls.append((prompt, Path(ws)))
        return {"delivered": "kicked", "pid": 4242}


class _StubDecide:
    """The decision-seat seam: counts calls, returns a fixed record (or
    raises). The record carries the five fields the wrapper reads."""

    def __init__(self, action: str = "probe", *, propensity: float = 0.25,
                 source: str = "sampled",
                 probability_source: str = "selection_law_exact",
                 error: Exception | None = None):
        self.calls = 0
        self.action = action
        self.record = {
            "schema": "scheduling-decision/1", "ts": "2026-11-26T00:00:00Z",
            "action": action, "propensity": propensity, "source": source,
            "k": 1, "probability_source": probability_source,
            "selected": [{"action": action, "propensity": propensity,
                          "source": source}],
            "null": {"action": "none", "propensity": 0.2,
                     "cost": 0.0, "value": 0.0},
        }
        self._error = error

    def __call__(self, ws, *, rng=None, now=None):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return dict(self.record)


QUIET_GATE = _fake_runner(0, "QUIET: no LLM action needed — idle ≈ 0 tokens\n")
WAKE_GATE = _fake_runner(3, "WAKE: events:settlement — inject the loop prompt (exit 3)\n")
STOP_GATE = _fake_runner(2, "*** IDLE CIRCUIT BREAKER: 6 consecutive no-op ticks\n")
FAULT_GATE = _fake_runner(9, "REFUSE: version mismatch\n")


def _mk_ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def _sched_rows(ws: Path) -> list[dict]:
    import signals_stream
    return [r for r in signals_stream.read(ws)
            if r.get("kind") == "scheduling"]


def _decision_file(ws: Path) -> Path:
    return ws / "runs" / ".scheduling-decision.json"


# ---------------------------------------------------------------------------
# 1-2. the WAKE branch consults the seat; none vetoes the injection
# ---------------------------------------------------------------------------

class TestWakeBranchDecision:

    def test_wake_records_one_decision_row_with_exact_propensity(
            self, tmp_path):
        import heartbeat_wake_gate as wgw
        ws = _mk_ws(tmp_path)
        deliver = _Recorder()
        out = wgw.wake_pass(ws, runner=WAKE_GATE, deliver=deliver,
                            decision_rng=random.Random(SEED_ACTION))
        assert out["outcome"] == "wake"
        assert out["injected"] is True
        assert out["rc"] == 3
        assert len(deliver.calls) == 1
        rows = _sched_rows(ws)
        assert len(rows) == 1, "a wake pass must land exactly one decision row"
        row = rows[0]
        assert row["action"] == "close_loop"
        assert row["source"] == "sampled"
        assert abs(row["propensity"] - FLAT_PROPENSITY) < 1e-9, (
            "flat priors, k=1: the exact law says 1/5")
        assert row["probability_source"] == "selection_law_exact"
        # the persisted record and the receipt agree with the row
        doc = json.loads(_decision_file(ws).read_text(encoding="utf-8"))
        assert doc["action"] == row["action"]
        assert abs(doc["propensity"] - row["propensity"]) < 1e-9
        assert out["decision"]["action"] == "close_loop"
        assert out["decision"]["probability_source"] == "selection_law_exact"

    def test_none_draw_injects_nothing_and_is_not_a_fault(self, tmp_path):
        """The two layers disagree and both are right: the gate said wake,
        the action layer said no wake is owed. Nothing is injected, the
        decision is still recorded, the wrapper exits with the gate's
        wake rc — never re-read as quiet, never as a fault."""
        import heartbeat_wake_gate as wgw
        ws = _mk_ws(tmp_path)
        deliver = _Recorder()
        out = wgw.wake_pass(ws, runner=WAKE_GATE, deliver=deliver,
                            decision_rng=random.Random(SEED_NONE))
        assert out["outcome"] == "wake", "a none draw is not a fault"
        assert out["injected"] is False
        assert out["rc"] == 3, "the wrapper propagates the gate's verdict rc"
        assert deliver.calls == [], "a none draw delivered something"
        assert not (ws / "runs" / ".wake-gate-prompt.txt").exists(), (
            "a none draw staged prompt bytes")
        rows = _sched_rows(ws)
        assert len(rows) == 1, "the none decision is still recorded"
        assert rows[0]["action"] == "none"
        assert rows[0]["source"] == "none"
        assert abs(rows[0]["propensity"] - FLAT_PROPENSITY) < 1e-9
        assert rows[0]["probability_source"] == "selection_law_exact"
        assert out["decision"]["action"] == "none"
        receipt = json.loads(
            (ws / "runs" / ".wake-gate-receipt.json").read_text(
                encoding="utf-8"))
        assert receipt["injected"] is False
        assert receipt["decision"]["action"] == "none"

    def test_stubbed_contract_none_vetoes_any_action_injects(self, tmp_path):
        """The wiring contract independent of the sampler: a none record
        suppresses the injection, any other record injects exactly once."""
        import heartbeat_wake_gate as wgw
        for action, injected in (("none", False), ("sleep", True),
                                 ("wake_on", True), ("probe", True),
                                 ("close_loop", True)):
            ws = _mk_ws(tmp_path, f"ws-{action}")
            deliver = _Recorder()
            out = wgw.wake_pass(ws, runner=WAKE_GATE, deliver=deliver,
                                decide=_StubDecide(action))
            assert out["injected"] is injected, action
            assert len(deliver.calls) == (1 if injected else 0), action
            assert out["decision"]["action"] == action
            staged = ws / "runs" / ".wake-gate-prompt.txt"
            assert staged.exists() is injected, action


# ---------------------------------------------------------------------------
# 3. the two-layer semantics: only the WAKE verdict consults the seat
# ---------------------------------------------------------------------------

class TestTwoLayerSemantics:

    def test_quiet_never_consults_the_seat(self, tmp_path):
        """Zero sampling on the quiet path: the gate already judged no
        wake, drawing again is pure overhead (the rc-0 pin's other half)."""
        import heartbeat_wake_gate as wgw
        ws = _mk_ws(tmp_path)
        stub = _StubDecide("none")
        deliver = _Recorder()
        out = wgw.wake_pass(ws, runner=QUIET_GATE, deliver=deliver,
                            decide=stub)
        assert out["rc"] == 0 and out["injected"] is False
        assert stub.calls == 0, "the quiet path sampled the seat"
        assert deliver.calls == []
        assert _sched_rows(ws) == [], "the quiet path logged a decision"
        assert not _decision_file(ws).exists()
        assert not (ws / "runs" / ".wake-gate-receipt.json").exists(), (
            "quiet writes no receipt by design")

    def test_stop_never_consults_the_seat(self, tmp_path, capsys):
        """A mandated stop is the breaker's decision, not a scheduling
        action: the seat has no say in a #634 stop."""
        import heartbeat_wake_gate as wgw
        ws = _mk_ws(tmp_path)
        stub = _StubDecide("probe")
        out = wgw.wake_pass(ws, runner=STOP_GATE, deliver=_Recorder(),
                            decide=stub)
        assert out["rc"] == 2 and out["injected"] is False
        assert stub.calls == 0
        assert _sched_rows(ws) == []
        assert "WAKE-GATE" in capsys.readouterr().err

    def test_gate_fault_never_consults_the_seat_and_injects(
            self, tmp_path, capsys):
        """Fail toward waking: a broken gate's wake is not the action
        layer's to veto — a sampler seat that could suppress a fault-wake
        would recreate the never-wakes failure the wrapper refuses."""
        import heartbeat_wake_gate as wgw
        ws = _mk_ws(tmp_path)
        stub = _StubDecide("none")
        deliver = _Recorder()
        out = wgw.wake_pass(ws, runner=FAULT_GATE, deliver=deliver,
                            decide=stub)
        assert out["outcome"] == "fault" and out["rc"] == 1
        assert stub.calls == 0, "the fault path consulted the seat"
        assert len(deliver.calls) == 1, "a fault must still inject"
        assert _sched_rows(ws) == []
        assert "WAKE-GATE" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# 4. a broken seat fails toward waking
# ---------------------------------------------------------------------------

class TestSeatFailure:

    def test_broken_seat_is_loud_and_injects(self, tmp_path, capsys):
        import heartbeat_wake_gate as wgw
        ws = _mk_ws(tmp_path)
        deliver = _Recorder()
        out = wgw.wake_pass(
            ws, runner=WAKE_GATE, deliver=deliver,
            decide=_StubDecide(error=RuntimeError("seat unavailable")))
        assert out["outcome"] == "wake"
        assert out["injected"] is True, (
            "a broken seat must not sleep the system")
        assert out["rc"] == 3
        assert len(deliver.calls) == 1
        err = capsys.readouterr().err
        assert "WAKE-GATE" in err and "seat unavailable" in err, (
            "the seat failure must be loud"
        )
        receipt = json.loads(
            (ws / "runs" / ".wake-gate-receipt.json").read_text(
                encoding="utf-8"))
        assert "seat unavailable" in receipt["decision"]["fault"]


# ---------------------------------------------------------------------------
# the honest-word discipline (probability_source, the dispatch vocabulary)
# ---------------------------------------------------------------------------

class TestProbabilitySourceVocabulary:

    def test_sampled_face_is_selection_law_exact_and_dispatch_accepted(
            self, tmp_path):
        import intelligent_scheduling as isch
        from rlvr.policy_compare import ACCEPTED_PROBABILITY_SOURCES
        ws = _mk_ws(tmp_path)
        d = isch.decide(ws, rng=random.Random(SEED_ACTION))
        assert d["probability_source"] == "selection_law_exact"
        assert "selection_law_exact" in ACCEPTED_PROBABILITY_SOURCES, (
            "the wake face must speak the dispatch face's vocabulary"
        )
        row = _sched_rows(ws)[-1]
        assert row["probability_source"] == "selection_law_exact"

    def test_deterministic_faces_read_unknown(self, tmp_path):
        """Declared and forced-null faces carry no draw receipt: the 1.0
        is by fiat, so the honest word is unknown — the same rule that
        excludes declared dispatch rows from off-policy weighting."""
        import intelligent_scheduling as isch
        ws = _mk_ws(tmp_path)
        d = isch.decide(ws, declared_action="probe")
        assert d["propensity"] == 1.0
        assert d["probability_source"] == "unknown"
        ws2 = _mk_ws(tmp_path, "ws2")
        d2 = isch.decide(ws2, free_slots=0)
        assert d2["action"] == "none" and d2["k"] == 0
        assert d2["probability_source"] == "unknown"
        assert _sched_rows(ws2)[-1]["probability_source"] == "unknown"

    def test_drawn_none_is_a_draw_not_a_fiat(self, tmp_path):
        """The honesty corner: a DRAWN none (seed 1, flat priors) carries
        its exact 1/5 law; a FORCED none (k=0) carries 1.0-by-constraint
        and reads unknown. Same action name, opposite probability
        semantics — the two fields together tell the truth."""
        import intelligent_scheduling as isch
        ws = _mk_ws(tmp_path)
        drawn = isch.decide(ws, rng=random.Random(SEED_NONE))
        assert drawn["action"] == "none"
        assert abs(drawn["propensity"] - FLAT_PROPENSITY) < 1e-9
        assert drawn["probability_source"] == "selection_law_exact"
        ws2 = _mk_ws(tmp_path, "ws2")
        forced = isch.decide(ws2, free_slots=0)
        assert forced["action"] == "none" and forced["propensity"] == 1.0
        assert forced["probability_source"] == "unknown"


# ---------------------------------------------------------------------------
# 5. the production path (real CLI -> real gate -> real seat; --dry-run
#    never spawns; --decision-seed keeps the draw deterministic)
# ---------------------------------------------------------------------------

def _quiet_ws(tmp_path: Path) -> Path:
    """A minimal parked workspace the real gate accepts as QUIET (the
    same fixture shape tests/test_wake_gate_wiring_1086.py uses)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir(parents=True)
    (ws / "notes").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    write_hook_state(
        ws, active_hooks=["cost_gate"], ts=_iso(_now()), tier="none",
        phase="IDLE", user_override={},
        expires_at=_iso(_now() + timedelta(minutes=25)))
    now = _now()
    (ws / "runs" / ".heartbeat.json").write_text(
        json.dumps({"last_tick_ts": _iso(now), "loop_registered": True}),
        encoding="utf-8")
    (ws / "runs" / ".heartbeat.log").write_text("\n".join(
        json.dumps({"ts": _iso(now - timedelta(minutes=m)), "actor": "tick"})
        for m in (10, 5)) + "\n", encoding="utf-8")
    import heartbeat_tick
    (ws / "runs" / ".heartbeat-noop.json").write_text(json.dumps({
        "hash": heartbeat_tick.state_fingerprint(ws), "count": 1}),
        encoding="utf-8")
    return ws


def _wake_ws(tmp_path: Path) -> Path:
    """The same fixture with a stale heartbeat: the real gate judges WAKE
    (the #1086 gotcha — that WAKE is correct, never 'fixed' into quiet)."""
    ws = _quiet_ws(tmp_path)
    stale = _iso(_now() - timedelta(hours=2))
    (ws / "runs" / ".heartbeat.json").write_text(
        json.dumps({"last_tick_ts": stale}), encoding="utf-8")
    return ws


def _run_cli(ws: Path, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "heartbeat_wake_gate.py"), str(ws), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300, cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": os.pathsep.join(
            [str(ROOT), str(SCRIPTS), str(HOOKS)])})


class TestProductionPath:

    def test_real_wake_with_action_seed_stages_the_prompt(self, tmp_path):
        ws = _wake_ws(tmp_path)
        r = _run_cli(ws, "--wake-gate", "--dry-run",
                     "--decision-seed", str(SEED_ACTION))
        assert r.returncode == 3, (
            f"a wake must propagate rc 3: {r.stdout[-300:]} {r.stderr[-300:]}")
        staged = ws / "runs" / ".wake-gate-prompt.txt"
        assert staged.exists(), "the wake did not stage the loop prompt"
        rows = _sched_rows(ws)
        assert len(rows) == 1 and rows[0]["action"] == "close_loop"
        assert rows[0]["probability_source"] == "selection_law_exact"
        receipt = json.loads(
            (ws / "runs" / ".wake-gate-receipt.json").read_text(
                encoding="utf-8"))
        assert receipt["injected"] is True
        assert receipt["decision"]["action"] == "close_loop"

    def test_real_wake_with_none_seed_stages_nothing(self, tmp_path):
        ws = _wake_ws(tmp_path)
        r = _run_cli(ws, "--wake-gate", "--dry-run",
                     "--decision-seed", str(SEED_NONE))
        assert r.returncode == 3, (
            f"a none-suppressed wake still propagates the gate's rc: "
            f"{r.stdout[-300:]} {r.stderr[-300:]}")
        assert not (ws / "runs" / ".wake-gate-prompt.txt").exists(), (
            "a none draw staged prompt bytes on the real path"
        )
        rows = _sched_rows(ws)
        assert len(rows) == 1 and rows[0]["action"] == "none"
        assert abs(rows[0]["propensity"] - FLAT_PROPENSITY) < 1e-9
        receipt = json.loads(
            (ws / "runs" / ".wake-gate-receipt.json").read_text(
                encoding="utf-8"))
        assert receipt["injected"] is False
        assert receipt["decision"]["action"] == "none"

    def test_real_quiet_pass_consults_nothing(self, tmp_path):
        ws = _quiet_ws(tmp_path)
        r = _run_cli(ws, "--wake-gate", "--dry-run")
        assert r.returncode == 0, r.stderr[-400:]
        assert _sched_rows(ws) == [], (
            "the real quiet pass produced a decision row"
        )
        assert not _decision_file(ws).exists()
        assert not (ws / "runs" / ".wake-gate-prompt.txt").exists()
