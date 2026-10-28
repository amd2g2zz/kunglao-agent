# -*- coding: utf-8 -*-
"""P6 guards — tier envelopes + tick arming + ticket discipline.

Behaviour pins for the learning-loop live-wire program card P6, written
before the implementation (test-driven):

  1. TIER ENVELOPES — T1 {wall 600s, calls 30, usd 0.30} /
     T2 {wall 1800s, calls 100, usd 1.00} / T3 {wall 5400s, calls 300,
     usd 2.50}. Each tier's envelope fires at ITS OWN caps, per dimension
     independently; at-cap is not an overrun.
  2. COST HONESTY — the TIMEOUT terminal event row in the trajectory
     (runs/logs/kunglao-*.jsonl) carries the ACTUAL spend/calls consumed
     in the worker's window, emitted ONCE per over-envelope worker while
     the rejection stays live.
  3. TICKET DISCIPLINE — a TIMEOUT with near-zero productive output
     (zero artifacts, zero dispatches in the window) is a granularity
     fault; repeated faults flip the forced-split marker the plan-review
     face reads.
  4. TICK-ARMING GATE — a LOOP-arm session launch on a workspace whose
     heartbeat loop is not verified armed is refused LOUDLY (structured
     refusal row + event row + stderr, no session launch); cc-default /
     cc-warm-context arms are never gated (neutral workspaces carry no
     kunglao heartbeat), and the stub session seam is never gated (the
     documented test/operator channel).

Integration tier: tmp-path file fixtures only; the run_loop_task
integration pins ride the eval-corpus presence mark (the corpus is
local-only material, mirroring tests/test_eval_loop_runner_334.py).
"""
from __future__ import annotations

import inspect
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVAL_CORPUS = ROOT / "eval" / "v1"

import eval_loop_runner as lr  # noqa: E402  (pytest pythonpath: scripts)
import worker_budget_gates as wbg  # noqa: E402  (pytest pythonpath: hooks)


# ------------------------------------------------------------ helpers ----

def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _seed_worker(ws: Path, worker_id: str = "w-1", claim: str = "C-001",
                 tier: int = 1, age_s: float = 0.0,
                 tools: str = "grep") -> float:
    """One active worker row in the state file; returns its dispatched_at."""
    return _seed_workers(ws, [dict(worker_id=worker_id, claim=claim,
                                   tier=tier, age_s=age_s, tools=tools)])[0]


def _seed_workers(ws: Path,
                  specs: list[dict]) -> list[float]:
    """CONCURRENT worker rows in one state file (a second _seed_worker
    call replaces the file — concurrent workers share it)."""
    now = time.time()
    lines = []
    anchors = []
    for s in specs:
        dispatched_at = int(now - s.get("age_s", 0.0))
        anchors.append(float(dispatched_at))
        lines.append(
            f"worker_id={s.get('worker_id', 'w-1')} | "
            f"claim_id={s.get('claim', 'C-001')} | "
            f"dispatched_at={dispatched_at} | tier={s.get('tier', 1)} | "
            f"tools={s.get('tools', 'grep')}")
    (ws / "analysis_state.txt").write_text(
        "[active_workers]\n" + "\n".join(lines) + "\n[/active_workers]\n",
        encoding="utf-8")
    return anchors


def _seed_cost(ws: Path, amount: float, ts_epoch: float) -> None:
    row = {"ts": _iso(ts_epoch), "amount": amount, "source": "test"}
    with (ws / "runs" / "cost_events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _seed_calls(ws: Path, n: int, from_epoch: float,
                claim: str = "C-001") -> None:
    """Attributed call rows: the journal keys a row on the dispatch claim
    (the documented derivation in tc_journal.from_kunglao_log)."""
    import tc_journal
    for i in range(n):
        tc_journal.record_call(ws, claim, "Bash",
                               ts=_iso(from_epoch + i))


def _seed_dispatch_row(ws: Path, ts_epoch: float,
                       claim: str = "C-001") -> None:
    """One dispatch event row in the kunglao ledger (the orchestrator's
    fan-out face — the window-output reader counts these per claim)."""
    row = {"ts": _iso(ts_epoch), "actor": "hook:worker_budget",
           "action": "dispatch", "claim": claim}
    logs = ws / "runs" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / "kunglao-test.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _seed_artifact(ws: Path, rel: str = "facts/F001.md",
                   mtime_epoch: float | None = None) -> Path:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("finding\n", encoding="utf-8")
    if mtime_epoch is not None:
        os_utime(p, mtime_epoch)
    return p


def os_utime(p: Path, epoch: float) -> None:
    import os
    os.utime(p, (epoch, epoch))


def _ledger_rows(ws: Path, action: str) -> list[dict]:
    out: list[dict] = []
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return out
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("action") == action:
                out.append(row)
    return out


def _gate(ws: Path, tier: int = 1):
    return wbg.check_tier_envelope(
        {"workspace": str(ws), "state": ws / "analysis_state.txt"}, tier)


# ------------------------------------------------ 1. the envelope table ----

def test_tier_envelope_table_matches_issue_caps():
    """Issue-verbatim caps, per tier, all three dimensions."""
    assert wbg.TIER_ENVELOPES[1] == {"wall_s": 600, "calls": 30,
                                     "usd": 0.30}
    assert wbg.TIER_ENVELOPES[2] == {"wall_s": 1800, "calls": 100,
                                     "usd": 1.00}
    assert wbg.TIER_ENVELOPES[3] == {"wall_s": 5400, "calls": 300,
                                     "usd": 2.50}


def test_envelope_for_returns_the_tiers_own_caps_and_is_loud_on_unknown():
    assert wbg.envelope_for(2)["usd"] == 1.00
    with pytest.raises(KeyError):
        wbg.envelope_for(9)


@pytest.mark.parametrize("tier", [1, 2, 3])
def test_each_tier_fires_at_its_own_cap_per_dimension(tier):
    """Each dimension fires independently at ITS tier's cap; the other two
    dimensions sit at half-cap so only the exceeded dimension reports."""
    env = wbg.envelope_for(tier)
    half = {"wall_s": env["wall_s"] / 2, "calls": env["calls"] / 2,
            "usd": env["usd"] / 2}
    for dim, over in (("wall_s", env["wall_s"] + 1),
                      ("calls", env["calls"] + 1),
                      ("usd", env["usd"] + 0.01)):
        args = {**half, dim: over}
        overruns = wbg.envelope_overrun(tier, **args)
        assert [o["dim"] for o in overruns] == [dim], (
            f"tier {tier}: exceeding {dim} alone must fire only {dim}, "
            f"got {overruns}")
        assert overruns[0]["cap"] == env[dim]
        assert overruns[0]["actual"] == over


@pytest.mark.parametrize("tier", [1, 2, 3])
def test_at_cap_is_not_an_overrun(tier):
    env = wbg.envelope_for(tier)
    assert wbg.envelope_overrun(tier, **env) == ()


# --------------------------------------- 2. the battery gate + TIMEOUT ----

def test_over_wall_worker_rejects_with_envelope_guidance(tmp_path):
    ws = _ws(tmp_path)
    _seed_worker(ws, tier=1, age_s=601)
    ok, msg = _gate(ws, tier=1)
    assert not ok, "a T1 worker 601s into a 600s envelope must REJECT"
    assert "TIMEOUT" in msg, msg
    assert "600" in msg and "w-1" in msg, msg


def test_within_envelope_worker_allows(tmp_path):
    ws = _ws(tmp_path)
    _seed_worker(ws, tier=1, age_s=599)
    ok, msg = _gate(ws, tier=1)
    assert ok, msg


def test_no_active_workers_allows(tmp_path):
    ws = _ws(tmp_path)
    ok, msg = _gate(ws, tier=1)
    assert ok, msg


def test_no_workspace_allows(tmp_path):
    ok, msg = wbg.check_tier_envelope({}, tier=1)
    assert ok, msg


def test_timeout_event_row_carries_actual_spend_and_calls(tmp_path):
    """Cost honesty: the trajectory row carries THIS worker's ACTUAL
    consumed calls/spend (not the caps, not a workspace-wide total)."""
    ws = _ws(tmp_path)
    dispatched_at = _seed_worker(ws, tier=1, age_s=120)  # wall within T1
    since = dispatched_at + 1
    _seed_calls(ws, 35, since)                   # 35 attributed calls > cap 30
    _seed_cost(ws, 0.55, since + 10)             # unattributable spend
    _seed_cost(ws, 9.99, dispatched_at - 100)    # pre-window spend never counts
    ok, msg = _gate(ws, tier=1)
    assert not ok, "T1 worker at 35 calls in-window must REJECT"
    assert "calls" in msg, msg
    rows = _ledger_rows(ws, "envelope_timeout")
    assert len(rows) == 1, f"one TIMEOUT terminal row expected: {rows}"
    detail = json.loads(rows[0]["detail"])
    assert detail["tier"] == 1
    assert detail["calls"] == 35, (
        f"the row carries THIS worker's ACTUAL call count: {detail}")
    assert detail["usd"] == 0.0, (
        "cost_events carries no worker identity: unattributable spend is "
        f"excluded from per-worker accounting, never charged wholesale: "
        f"{detail}")
    assert [o["dim"] for o in detail["over"]] == ["calls"], detail


def test_unattributable_workspace_spend_never_fires_worker_usd(tmp_path):
    """Two concurrent workers at $0.20 each must not audit as $0.40: a
    spend source with no worker identity is excluded from per-worker
    accounting (the usd dimension fires only on attributed spend)."""
    ws = _ws(tmp_path)
    dispatched_at = _seed_worker(ws, tier=1, age_s=100)  # wall within T1
    _seed_cost(ws, 9.00, dispatched_at + 5)              # workspace-wide $9
    ok, msg = _gate(ws, tier=1)
    assert ok, f"unattributable spend must not reject a worker: {msg}"


def test_concurrent_worker_calls_do_not_bleed(tmp_path):
    """Worker w-2's calls (claim C-002) are not w-1's consumption: the
    audit must see 25, never the workspace-wide 50."""
    ws = _ws(tmp_path)
    dispatched_at = _seed_workers(ws, [
        dict(worker_id="w-1", claim="C-001", age_s=601),
        dict(worker_id="w-2", claim="C-002", age_s=300),
    ])[0]
    since = dispatched_at + 1
    _seed_calls(ws, 25, since, claim="C-001")
    _seed_calls(ws, 25, since, claim="C-002")
    ok, msg = _gate(ws, tier=1)
    assert not ok, "w-1 over its wall cap still rejects"
    assert "calls 25" in msg and "calls 50" not in msg, (
        f"only w-1's own calls count: {msg}")
    detail = json.loads(
        _ledger_rows(ws, "envelope_timeout")[0]["detail"])
    assert detail["calls"] == 25, detail


def test_window_dispatch_rows_are_claim_attributed(tmp_path):
    """Another claim's fan-out does not clear THIS worker's zero-output
    window (dispatch rows carry the claim — the attribution key)."""
    ws = _ws(tmp_path)
    dispatched_at = _seed_worker(ws, worker_id="w-1", claim="C-001",
                                 tier=1, age_s=601)
    _seed_dispatch_row(ws, dispatched_at + 5, claim="C-002")
    assert not _gate(ws, tier=1)[0], "wall overrun still rejects"
    assert wbg.granularity_fault_view(ws)["count"] == 1, (
        "C-002's dispatch is not w-1's output")


def test_timeout_row_emitted_once_rejection_stays_live(tmp_path):
    ws = _ws(tmp_path)
    _seed_worker(ws, tier=1, age_s=601)
    assert not _gate(ws, tier=1)[0]
    assert not _gate(ws, tier=1)[0]
    assert len(_ledger_rows(ws, "envelope_timeout")) == 1, (
        "TIMEOUT is a terminal outcome: ONE row per over-envelope worker, "
        "while the rejection keeps firing")


def test_worker_without_parseable_dispatched_at_is_skipped(tmp_path):
    """A worker row without an evaluable anchor cannot be envelope-audited:
    the gate lets it pass (the deadline gate's unparseable-ts posture)."""
    ws = _ws(tmp_path)
    (ws / "analysis_state.txt").write_text(
        "[active_workers]\n"
        "worker_id=w-x | claim_id=C-001 | tier=1 | tools=grep\n"
        "[/active_workers]\n", encoding="utf-8")
    ok, msg = _gate(ws, tier=1)
    assert ok, msg


def test_envelope_gate_registered_in_battery_registry():
    """The battery-registration pin: the battery may not run an
    unregistered check — the new face registers in hooks/battery.yaml
    with its telemetry word + liveness fingerprint BEFORE it may run."""
    import battery_registry
    assert battery_registry.launch_gate({"envelope"}) is None


def test_envelope_gate_wired_into_pre_check_battery():
    from worker_budget_sinks import pre_check
    assert "check_tier_envelope(" in inspect.getsource(pre_check), (
        "the envelope gate must sit in the live dispatch battery")


# ------------------------------------------ 3. ticket (sizing) discipline ----

def test_granularity_fault_counted_for_zero_output_shape(tmp_path):
    ws = _ws(tmp_path)
    _seed_worker(ws, tier=1, age_s=601)  # over wall, NOTHING produced
    assert not _gate(ws, tier=1)[0]
    view = wbg.granularity_fault_view(ws)
    assert view["count"] == 1, view
    assert view["forced_split"] is False, (
        "one fault below the threshold must not force a split")
    assert len(_ledger_rows(ws, "granularity_fault")) == 1


def test_no_fault_when_worker_produced_artifacts(tmp_path):
    ws = _ws(tmp_path)
    dispatched_at = _seed_worker(ws, tier=1, age_s=601)
    _seed_artifact(ws, "facts/F001.md", mtime_epoch=dispatched_at + 5)
    assert not _gate(ws, tier=1)[0], "wall overrun still rejects"
    assert wbg.granularity_fault_view(ws)["count"] == 0, (
        "a worker that produced artifacts is NOT a granularity fault")


def test_old_artifacts_do_not_count_as_output(tmp_path):
    ws = _ws(tmp_path)
    dispatched_at = _seed_worker(ws, tier=1, age_s=601)
    _seed_artifact(ws, "facts/F000.md", mtime_epoch=dispatched_at - 500)
    assert not _gate(ws, tier=1)[0]
    assert wbg.granularity_fault_view(ws)["count"] == 1, (
        "pre-window artifacts are not THIS worker's output")


def test_no_fault_when_window_had_dispatch_fanout(tmp_path):
    ws = _ws(tmp_path)
    dispatched_at = _seed_worker(ws, tier=1, age_s=601)
    _seed_dispatch_row(ws, dispatched_at + 5)
    assert not _gate(ws, tier=1)[0]
    assert wbg.granularity_fault_view(ws)["count"] == 0


def test_fault_state_persisted_and_readable_when_absent(tmp_path):
    ws = _ws(tmp_path)
    assert wbg.granularity_fault_view(ws) == {"count": 0,
                                              "forced_split": False}


def test_retry_churn_does_not_recount_the_same_workers_fault(tmp_path):
    """One over-envelope zero-output worker + orchestrator retry attempts
    is ONE sizing fault — the recount would let retry churn masquerade as
    repeated sizing failures."""
    ws = _ws(tmp_path)
    _seed_worker(ws, worker_id="w-1", age_s=601)
    assert not _gate(ws, tier=1)[0]
    assert not _gate(ws, tier=1)[0]      # the retry attempt
    assert not _gate(ws, tier=1)[0]      # and another
    view = wbg.granularity_fault_view(ws)
    assert view["count"] == 1, (
        f"one worker is one fault; got {view}")
    assert view["forced_split"] is False
    assert len(_ledger_rows(ws, "granularity_fault")) == 1


def test_forced_split_marker_after_two_distinct_workers_faults(tmp_path):
    """Two DISTINCT workers' zero-output TIMEOUTs (the first settled, then
    a second oversized claim stalls the same way) drive the forced-split
    marker — retry churn on one worker must not reach the threshold."""
    ws = _ws(tmp_path)
    _seed_worker(ws, worker_id="w-1", claim="C-001", age_s=601)
    assert not _gate(ws, tier=1)[0]
    assert not _gate(ws, tier=1)[0]      # retry churn: still ONE fault
    assert wbg.granularity_fault_view(ws)["count"] == 1
    # the orchestrator settles w-1 (the state file now carries only w-2)
    _seed_worker(ws, worker_id="w-2", claim="C-002", age_s=601)
    ok, msg = _gate(ws, tier=1)
    assert not ok
    view = wbg.granularity_fault_view(ws)
    assert view["count"] == wbg.GRANULARITY_FAULT_SPLIT_THRESHOLD
    assert view["forced_split"] is True, (
        "repeated zero-output TIMEOUTs tighten the gate: the plan-review "
        "face must demand a claim split")
    directive = wbg.forced_split_directive(ws)
    assert directive is not None
    assert "claim_granularity.py" in directive and "--split" in directive, \
        directive
    assert "forced-split" in msg, (
        "the reject message surfaces the forced-split marker")


def test_below_threshold_no_directive(tmp_path):
    ws = _ws(tmp_path)
    assert wbg.forced_split_directive(ws) is None


# ------------------------------------------------- 4. the tick gate ----

def _heartbeat_registered(ws: Path) -> None:
    """The kunglao-init shape: the heartbeat FILE exists, loop_registered
    stays false (the cron never took)."""
    from heartbeat import heartbeat_register
    heartbeat_register(ws)


def _heartbeat_armed(ws: Path) -> None:
    from heartbeat import heartbeat_register, mark_loop_registered
    from rlvr.liveness import append_tick_log
    heartbeat_register(ws)
    mark_loop_registered(ws)
    # TWO real tick rows: the sidecar skips the registration row
    # (actor=register) and continuity requires two ticks minimum.
    append_tick_log(ws, "tick", origin="cron")
    append_tick_log(ws, "tick", origin="cron")


def test_tick_gate_refuses_unarmed_loop_workspace(tmp_path):
    ws = _ws(tmp_path)
    _heartbeat_registered(ws)
    ok, msg = lr.tick_arm_gate(ws)
    assert not ok, "loop_registered=false means CronCreate did not take"
    assert "loop_registered" in msg, msg


def test_tick_gate_accepts_armed_workspace(tmp_path):
    ws = _ws(tmp_path)
    _heartbeat_armed(ws)
    ok, msg = lr.tick_arm_gate(ws)
    assert ok, msg


def test_tick_gate_refuses_never_registered_workspace(tmp_path):
    ws = _ws(tmp_path)
    ok, msg = lr.tick_arm_gate(ws)
    assert not ok
    assert "UNREGISTERED" in msg, msg


_TASK = {"family": "py-derive", "checker": {"kind": "unit"}}


def test_refusal_row_is_loud_and_structured(tmp_path):
    ws = _ws(tmp_path)
    _heartbeat_registered(ws)
    out = tmp_path / "out"
    row = lr._tick_gate_skip_row(ws, _TASK, tmp_path / "t1", out,
                                 arm=lr.ARM, session_cmd=None)
    assert row is not None, "an unarmed loop workspace must refuse"
    assert row["verdict"] == "SKIP"
    assert row["failures"][0]["code"] == lr.TICK_GATE_CODE
    assert row["loop"]["status"] == "harness_error"
    assert row["excluded_from_performance"] is True
    events = [json.loads(ln) for ln in
              (out / "harness-events.jsonl").read_text(
                  encoding="utf-8").splitlines() if ln.strip()]
    assert any(e.get("action") == lr.TICK_GATE_REFUSED_ACTION
               for e in events), events


def test_refusal_row_captures_the_verify_guidance(tmp_path):
    ws = _ws(tmp_path)
    _heartbeat_registered(ws)
    row = lr._tick_gate_skip_row(ws, _TASK, tmp_path / "t1", tmp_path / "o",
                                 arm=lr.ARM, session_cmd=None)
    assert "loop_registered" in row["failures"][0]["detail"], (
        "the refusal carries the reused verify face's repair guidance")


def test_stub_session_seam_is_never_gated(tmp_path):
    ws = _ws(tmp_path)
    _heartbeat_registered(ws)
    assert lr._tick_gate_skip_row(ws, _TASK, tmp_path / "t1",
                                  tmp_path / "o", arm=lr.ARM,
                                  session_cmd="python stub.py") is None, (
        "the session-cmd seam is the documented test/operator channel — "
        "the tick gate guards the production launch only")


def test_cc_arms_are_never_gated(tmp_path):
    ws = _ws(tmp_path)
    for arm in ("cc-default", "cc-warm-context"):
        assert lr._tick_gate_skip_row(ws, _TASK, tmp_path / "t1",
                                      tmp_path / "o", arm=arm,
                                      session_cmd=None) is None, (
            f"{arm} workspaces are neutral — no kunglao heartbeat, no gate")


def test_armed_workspace_launches(tmp_path):
    ws = _ws(tmp_path)
    _heartbeat_armed(ws)
    assert lr._tick_gate_skip_row(ws, _TASK, tmp_path / "t1",
                                  tmp_path / "o", arm=lr.ARM,
                                  session_cmd=None) is None


def test_tick_gate_refused_word_registered():
    from event_taxonomy import EMIT_ACTIONS
    for word in ("envelope_timeout", "granularity_fault",
                 lr.TICK_GATE_REFUSED_ACTION):
        assert word in EMIT_ACTIONS, (
            f"{word} must be a controlled emit-action word (#459)")


# ----------------------- 5. run_loop_task integration (eval-corpus gated) ----

@pytest.mark.skipif(not EVAL_CORPUS.is_dir(),
                    reason="the eval corpus is local-only material")
class TestRunLoopTaskTickGate:
    """The production launch face (session_cmd=None) on a REAL
    kunglao-init workspace: init registers the heartbeat with
    loop_registered=false, so an unarmed launch refuses WITHOUT spawning
    the session (the 19-minute-silent-stall incident shape)."""

    def test_unarmed_production_launch_refuses_without_session(
            self, tmp_path, monkeypatch):
        import eval_dataset as ds

        def _no_launch(*a, **k):  # the launch must never be reached
            raise AssertionError("launch_session called on an unarmed "
                                 "workspace — the tick gate leaked")

        monkeypatch.setattr(lr, "launch_session", _no_launch)
        row = lr.run_loop_task("py-derive-v1", tmp_path, budget_usd=1.0,
                               wall_cap_s=60.0, session_cmd=None)
        assert row["verdict"] == "SKIP"
        assert row["failures"][0]["code"] == lr.TICK_GATE_CODE
        assert row["loop"]["status"] == "harness_error"
        assert row["excluded_from_performance"] is True
        assert row["arm"] == ds.ARM if hasattr(ds, "ARM") else True
