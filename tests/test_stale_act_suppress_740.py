# -*- coding: utf-8 -*-
"""tests/test_stale_act_suppress_740.py — the stale-plan warn gate: act once,
then suppress (Face 2 of the progress-coupling card, issue 740).

The defect (RC1-proven): the class-7 STALE_PLAN_ON_NEW_EVIDENCE warn is
emitted unconditionally per evaluation — two hook faces evaluate it every
dispatch attempt, so one stale claim produced 129 rows in 5h (43x per
claim) with ZERO escalations and ZERO suppressions. No consumer ever read
the warn back; the replan policy action names this detector as its trigger
with no implementation pointer; the drift->replan convergence wire in
plan_stages stayed a declared hook point.

The contract pinned here:

  G1  the treadmill ends: N identical evaluations of the same warn
      signature escalate exactly once; every later evaluation is a
      suppress-record at the 3-round window cadence (the plan_repair_tick
      shape), never per-evaluation;
  G2  a signature change re-arms: a new failure file (new warn items) or a
      new plan version (the mechanical re-render) buys one fresh escalate;
  G3  the escalate path IS the act face: the replan remedy is recorded in
      the planning-action ledger, the stage review records the replan
      verdict when a stage model exists (fail-open when it does not), and
      the mechanical re-derive re-renders the plan face from the timeline
      projection (never model-authored content);
  G4  the replan budget is bounded per warn set (the dual-gate replan
      limit, 3): at the cap the escalate path goes to the operator lane
      (signal_gate_escalate, reason=replan_limit) instead of a fourth
      replan;
  G5  fail-open: a corrupt state file never breaks check() — the gate
      degrades to escalate-once with one stderr annotation;
  G6  liveness: the face emits the issue-127 pair — detector_eval per
      warn-bearing evaluation, detector_fired per escalation; suppressions
      are evals-only (the liveness read face sees ACTIVE, never DORMANT);
  G7  the existing faces are unchanged: WARN-only rc, severe rc, the
      fresh-plan no-emission anchor, and the auto face's first-sight
      SATURATED classification all stay exactly as pinned by their own
      suites (regression pins here cover the interaction points).

Fast tier: in-process only — spawns no processes, no nested pytest.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import detector_liveness  # noqa: E402
import dual_gate  # noqa: E402
import event_taxonomy as et  # noqa: E402
import kunglao_log  # noqa: E402
import plan_drift_detector as pdd  # noqa: E402
import planning_actions  # noqa: E402

STATE_FILE = "runs/plan-drift-warn-state.json"
STALE_ACTION = "stale_plan_on_new_evidence"

T0 = 1_700_000_000.0        # the past: older than any re-render
T_FAR = 2_500_000_000.0     # the far future: newer than any re-render


# ---------- workspace builders ---------------------------------------------

def _register(claims: list[dict]) -> str:
    return yaml.safe_dump({"claims": claims}, sort_keys=True)


def _write_analysis(ws: Path, cid: str, ts: float) -> Path:
    adir = ws / "analyses"
    adir.mkdir(exist_ok=True)
    p = adir / f"failure-{cid}.yaml"
    p.write_text(yaml.safe_dump({"claim": cid, "note": "gap"},
                                sort_keys=True), encoding="utf-8")
    os.utime(p, (ts, ts))
    return p


def _mk_warn_ws(tmp_path: Path, *, t_evidence: float = T0 + 100,
                pre_rendered: bool = False) -> Path:
    """A warn-only workspace: C-1 OPEN, plan mentions C-1, one failure
    analysis newer than the plan. pre_rendered makes the plan face already
    the timeline projection (the act's re-render is then a no-op — the
    signature stays put across evaluations)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        _register([{"id": "C-1", "status": "OPEN"}]), encoding="utf-8")
    plan = ws / "global_plan.txt"
    plan.write_text("## plan\n- C-1 do the thing\n", encoding="utf-8")
    os.utime(plan, (T0, T0))
    _write_analysis(ws, "C-1", t_evidence)
    if pre_rendered:
        import timeline_face
        timeline_face.render_and_write(ws)
    return ws


def _advance_timeline(ws: Path, decision: str) -> None:
    """One more projection step with a fresh decision word — the next
    act's re-render sees a different plan face (the plan_version leg of
    the signature moves)."""
    kunglao_log.emit(ws, actor="orchestrator",
                     action="convergence_decision",
                     detail=json.dumps({"decision": decision}))
    kunglao_log.emit(ws, actor="orchestrator", action="dispatch_attempt",
                     claim="C-1", detail="probe")
    kunglao_log.emit(ws, actor="orchestrator", action="dispatch_result",
                     claim="C-1", exit=0, detail="probe")


def _event_rows(ws: Path, action: str) -> list[dict]:
    out: list[dict] = []
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return out
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("action") == action:
                out.append(row)
    return out


def _stale_rows(ws: Path) -> list[dict]:
    return _event_rows(ws, STALE_ACTION)


def _escalates(ws: Path) -> list[dict]:
    """Escalate DECISIONS: one row per warn item on an escalate round, so
    decisions are counted as distinct non-suppressed signatures."""
    seen: dict[str, dict] = {}
    for r in _stale_rows(ws):
        d = json.loads(r["detail"])
        if not d.get("suppressed") and d.get("sig"):
            seen[d["sig"]] = r
    return list(seen.values())


def _suppressed_rounds(ws: Path) -> list[int]:
    return [json.loads(r["detail"])["rounds"] for r in _stale_rows(ws)
            if json.loads(r["detail"]).get("suppressed")]


def _replan_rows(ws: Path) -> list[dict]:
    return [r for r in planning_actions.read_actions(ws)
            if r.get("action") == "policy.replan"]


def _state(ws: Path) -> dict:
    return json.loads((ws / STATE_FILE).read_text(encoding="utf-8"))


# =====================================================================
# G1: the 43-repeat treadmill ends
# =====================================================================

class TestTreadmill:
    def test_forty_three_identical_evaluations_escalate_once(
            self, tmp_path, capsys):
        ws = _mk_warn_ws(tmp_path, t_evidence=T_FAR, pre_rendered=True)
        for _ in range(43):
            assert pdd.check(ws, active_only=True) == 0
        esc = _escalates(ws)
        assert len(esc) == 1, f"expected 1 escalate, got {len(esc)}"
        detail = json.loads(esc[0]["detail"])
        assert detail["act"] == "replan"
        assert esc[0]["claim"] == "C-1"
        assert _suppressed_rounds(ws) == list(range(3, 43, 3))
        # the window-cadence suppress record carries the shape
        sup = [r for r in _stale_rows(ws)
               if json.loads(r["detail"]).get("suppressed")]
        d = json.loads(sup[0]["detail"])
        assert d["window"] == pdd.STALE_WARN_WINDOW_ROUNDS
        assert d["items"] == ["failure:C-1"]
        assert d["sig"]
        # stdout warns once, not 43 times
        out = capsys.readouterr()
        assert out.out.count("WARN (observe-only)") == 1

    def test_state_file_episode_shape(self, tmp_path):
        ws = _mk_warn_ws(tmp_path, t_evidence=T_FAR, pre_rendered=True)
        pdd.check(ws, active_only=True)
        pdd.check(ws, active_only=True)
        st = _state(ws)
        assert st["sig"]
        assert st["items"] == ["failure:C-1"]
        assert st["plan_version"]
        assert st["rounds"] >= 1


# =====================================================================
# G2: signature changes re-arm
# =====================================================================

class TestRearm:
    def test_new_failure_file_buys_one_fresh_escalate(self, tmp_path):
        ws = _mk_warn_ws(tmp_path, t_evidence=T_FAR, pre_rendered=True)
        pdd.check(ws, active_only=True)  # escalate 1
        _write_analysis(ws, "C-2", T_FAR + 10)
        pdd.check(ws, active_only=True)  # new items -> fresh escalate
        esc = _escalates(ws)
        assert len(esc) == 2
        # the fresh escalate carries both items (one row per item, the
        # per-item face), naming the replan act
        assert len(_stale_rows(ws)) == 3  # 1 item + 2 items
        assert json.loads(esc[1]["detail"])["act"] == "replan"
        assert json.loads(esc[1]["detail"])["items"] == \
            ["failure:C-1", "failure:C-2"]
        assert len(_replan_rows(ws)) == 2  # the replan budget reset
        assert _suppressed_rounds(ws) == []

    def test_rearm_via_plan_version_only_when_warns_persist(self, tmp_path):
        """The act face re-rendered the plan (mtime advanced) — the warn
        persists only because the evidence is still newer; the new plan
        version re-arms once, then the stable face suppresses."""
        ws = _mk_warn_ws(tmp_path, t_evidence=T_FAR)
        plan = ws / "global_plan.txt"
        m0 = plan.stat().st_mtime_ns
        assert pdd.check(ws, active_only=True) == 0
        m1 = plan.stat().st_mtime_ns
        assert m1 > m0  # G3: the act face ran — the plan was re-derived
        import timeline_face
        assert timeline_face.plan_is_rendered(ws)
        assert pdd.check(ws, active_only=True) == 0  # pv re-arm
        assert len(_escalates(ws)) == 2
        # the face is stable now: same signature -> suppress at the window
        # cadence, no third act (rounds: escalate resets to 1, then 2, then 3)
        assert pdd.check(ws, active_only=True) == 0
        assert pdd.check(ws, active_only=True) == 0
        assert len(_escalates(ws)) == 2
        assert _suppressed_rounds(ws) == [3]
        assert len(_replan_rows(ws)) == 2


# =====================================================================
# G3: the act face is mechanical and attributed
# =====================================================================

class TestActFace:
    def test_replan_attributed_with_step_ref(self, tmp_path):
        ws = _mk_warn_ws(tmp_path, t_evidence=T_FAR, pre_rendered=True)
        pdd.check(ws, active_only=True)
        rows = _replan_rows(ws)
        assert len(rows) == 1
        assert rows[0]["step_ref"].startswith("stale-plan-warn:")

    def test_stage_model_records_replan_verdict(self, tmp_path):
        ws = _mk_warn_ws(tmp_path, t_evidence=T_FAR, pre_rendered=True)
        (ws / "runs").mkdir(exist_ok=True)
        stages = [
            {"id": "S1", "name": "core", "goal": "settle C-1",
             "claims": ["C-1"], "expected_evidence": "facts/F",
             "exit_criteria": "C-1 PROVEN", "status": "active"},
            {"id": "S2", "name": "tail", "goal": "close out",
             "claims": ["C-1"], "expected_evidence": "report",
             "exit_criteria": "report written", "status": "pending"},
        ]
        (ws / "runs" / "plan-stages.yaml").write_text(
            yaml.safe_dump({"stages": stages, "reviews": []},
                           sort_keys=False), encoding="utf-8")
        pdd.check(ws, active_only=True)
        data = yaml.safe_load(
            (ws / "runs" / "plan-stages.yaml").read_text(encoding="utf-8"))
        replans = [r for r in data["reviews"] if r["verdict"] == "replan"]
        assert len(replans) == 1
        assert "stale-plan" in replans[0]["reason"]

    def test_no_stage_model_act_still_lands(self, tmp_path):
        """No stage skeleton: the verdict leg fails open, the attribution
        and the re-render still land."""
        ws = _mk_warn_ws(tmp_path, t_evidence=T_FAR, pre_rendered=True)
        assert not (ws / "runs" / "plan-stages.yaml").exists()
        assert pdd.check(ws, active_only=True) == 0
        assert len(_replan_rows(ws)) == 1
        import timeline_face
        assert timeline_face.plan_is_rendered(ws)


# =====================================================================
# G4: the replan budget and the operator lane
# =====================================================================

class TestReplanCap:
    def test_cap_escalates_to_operator_lane(self, tmp_path):
        ws = _mk_warn_ws(tmp_path, t_evidence=T_FAR)
        for word in (None, "DISPATCH", "SATURATED", "DISPATCH"):
            if word:
                _advance_timeline(ws, word)
            pdd.check(ws, active_only=True)
        # three mechanical replans, then the cap: the fourth escalate is
        # the operator lane, not another replan
        assert len(_replan_rows(ws)) == dual_gate.MAX_REPLANS == 3
        sig_rows = _event_rows(ws, "signal_gate_escalate")
        assert len(sig_rows) == 1
        detail = json.loads(sig_rows[0]["detail"])
        assert detail["reason"] == "replan_limit"
        assert detail["detector"] == STALE_ACTION
        # the operator lane still counts as an escalation (a fire)
        assert len(_escalates(ws)) == 4
        assert json.loads(_escalates(ws)[-1]["detail"])["act"] \
            == "operator-escalation"
        # past the cap the stable face suppresses, forever quiet per window
        pdd.check(ws, active_only=True)
        pdd.check(ws, active_only=True)
        assert len(_replan_rows(ws)) == 3
        assert len(_event_rows(ws, "signal_gate_escalate")) == 1

    def test_cap_constant_mirrors_dual_gate(self):
        assert pdd.STALE_WARN_MAX_REPLANS == dual_gate.MAX_REPLANS == 3
        assert pdd.STALE_WARN_WINDOW_ROUNDS == pdd.PLAN_REPAIR_WINDOW_ROUNDS


# =====================================================================
# G5: fail-open posture
# =====================================================================

class TestFailOpen:
    def test_corrupt_state_degrades_to_escalate_once(self, tmp_path, capsys):
        ws = _mk_warn_ws(tmp_path, t_evidence=T_FAR, pre_rendered=True)
        (ws / "runs").mkdir(exist_ok=True)
        (ws / STATE_FILE).write_text("{not json", encoding="utf-8")
        assert pdd.check(ws, active_only=True) == 0
        assert "fail-open" in capsys.readouterr().err
        assert len(_escalates(ws)) == 1  # degraded fresh: escalate once
        assert _state(ws)["sig"]        # the state file healed
        # and the healed state suppresses the next identical evaluation
        pdd.check(ws, active_only=True)
        assert len(_escalates(ws)) == 1

    def test_clean_workspace_stays_silent(self, tmp_path):
        """The fresh-plan anchor: no warns, no state, no events."""
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "claim-register.yaml").write_text(
            _register([{"id": "C-1", "status": "OPEN"}]), encoding="utf-8")
        (ws / "global_plan.txt").write_text("C-1 in plan\n", encoding="utf-8")
        os.utime(ws / "global_plan.txt", (T0, T0))
        _write_analysis(ws, "C-1", T0 - 100)  # older than the plan
        assert pdd.check(ws, active_only=True) == 0
        assert not (ws / STATE_FILE).exists()
        assert _stale_rows(ws) == []
        assert _event_rows(ws, "detector_eval") == []


# =====================================================================
# G6: the liveness pair
# =====================================================================

class TestLiveness:
    def test_eval_and_fired_counted(self, tmp_path):
        ws = _mk_warn_ws(tmp_path, t_evidence=T_FAR, pre_rendered=True)
        for _ in range(5):
            pdd.check(ws, active_only=True)
        report = detector_liveness.liveness_report(ws)
        c = report["detectors"][STALE_ACTION]
        assert c["evaluations"] == 5   # every warn-bearing evaluation
        assert c["fires"] == 1         # exactly the escalation
        assert c["status"] == "ACTIVE"

    def test_words_registered_sorted_unique(self):
        for word in (STALE_ACTION, "signal_gate_escalate",
                     "detector_eval", "detector_fired"):
            assert word in et.EMIT_ACTIONS, word
        assert et.EMIT_ACTIONS == sorted(set(et.EMIT_ACTIONS))


# =====================================================================
# G7: the existing faces are unchanged
# =====================================================================

class TestExistingFaces:
    def test_severe_drift_rc_unchanged_with_warn(self, tmp_path, capsys):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "claim-register.yaml").write_text(_register([
            {"id": "C-1", "status": "OPEN"},
            {"id": "C-2", "status": "OPEN"}]), encoding="utf-8")
        (ws / "global_plan.txt").write_text("- C-1 only\n", encoding="utf-8")
        os.utime(ws / "global_plan.txt", (T0, T0))
        _write_analysis(ws, "C-1", T_FAR)
        assert pdd.check(ws, active_only=True) == 1  # ORPHAN_CLAIM decides
        out = capsys.readouterr().out
        assert "ORPHAN_CLAIM" in out
        assert "STALE_PLAN_ON_NEW_EVIDENCE" in out  # the warn block still prints

    def test_auto_face_first_sight_still_saturated(self, tmp_path, capsys):
        """The auto integration classifies the ENTRY warn state: even
        though the act face remedies the warn inside check(), the
        first-sight dispatch stays SATURATED."""
        ws = _mk_warn_ws(tmp_path, t_evidence=T_FAR)
        assert pdd.check_auto(ws, active_only=True) == 3
