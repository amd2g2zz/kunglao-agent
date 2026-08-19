#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_event_stream_adoption.py — unified event-stream adoption (#459).

The #459 contract this file anchors (issue pains: "决策点零日志" /
"诊断不可解释"; 2026-08-19 挂靠评论: 事件流须含失败事件与三产物落地事件):

  1. every adopted decision face emits >= 1 event into kunglao_log when it
     fires — ask_for_direction_gate TYPE A-E interceptions, dispatch_gate
     #496 REJECT faces, plan_drift_detector class-7 WARN, failure_analysis
     record/blocked, convergence_check per-round DECISION;
  2. every action word used by an emit call site is a member of the
     controlled vocabulary event_taxonomy.EMIT_ACTIONS (CI anchor — an
     unregistered literal turns the suite red, issue acceptance
     "action 字段 100% 来自受控词表");
  3. emit failure NEVER changes a decision face's exit code (fail-open —
     observability must not gate decisions).

Script faces assert via a seam-level monkeypatched emit (call counting);
the hook face runs as a real subprocess and asserts the actual jsonl
(mirrors tests/test_decision_teeth.py conventions).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "hooks"))

# hook-level fixtures reuse the #496 suite's builders (same test dir is on
# sys.path under pytest's rootdir collection; test_decide_state_machine.py
# uses the same cross-test import convention).
from test_decision_teeth import _capability_ws, _event_rows, _run_gate, _top1_ws  # noqa: E402


# ---------- shared seam: capture kunglao_log.emit in-process ----------

@pytest.fixture
def events(monkeypatch):
    """Capture every kunglao_log.emit call made in-process after this point.

    The adopted faces import emit lazily at call time (the kunglao_record /
    kunglao_verify posture), so patching the module attribute is enough —
    no call-site surgery needed."""
    import kunglao_log

    calls: list[dict] = []

    def _fake(ws, actor, action, **kw):
        calls.append({"actor": actor, "action": action, **kw})

    monkeypatch.setattr(kunglao_log, "emit", _fake)
    return calls


def _actions(calls: list[dict], *words: str) -> list[dict]:
    return [c for c in calls if c["action"] in words]


# ---------- ④ controlled vocabulary (CI anchor) ------------------------

# Literal-call shapes the anchor recognizes. Char class [a-z0-9_]: action
# words may bear digits (this branch's own top1_reject) — F1: with a
# digit-blind [a-z_]+ class the anchor never matched them, so unregistered
# digit words sailed through while non-digit ones were caught.
_LITERAL_PATTERNS = [
    re.compile(r'action=["\']([a-z0-9_]+)["\']'),
    re.compile(r'_emit_trace\(\s*ws,\s*["\']([a-z0-9_]+)["\']'),
    re.compile(r'_emit_interception\(\s*workspace,\s*["\']([a-z0-9_]+)["\']'),
    re.compile(r'\.emit\(\s*[^,()]+,\s*["\'][^"\']+["\'],\s*'
               r'["\']([a-z0-9_]+)["\']'),
]

# argparse's own action kwarg (store_true / ...) — same keyword, different
# contract than the event-stream action field.
_ARGPARSE_ACTIONS = {
    "store", "store_true", "store_false", "store_const",
    "append", "append_const", "count", "help", "version",
    "extend", "raise",  # argparse ext vocabulary members
}


def _unregistered_action_literals(root: Path) -> dict[str, set[str]]:
    """Scan <root>/{scripts,hooks}/*.py for emit action literals outside
    event_taxonomy.EMIT_ACTIONS. Shared by the repo-wide CI anchor and the
    digit-visibility regression (F1) so both use ONE pattern table."""
    import event_taxonomy as et
    known = set(et.EMIT_ACTIONS)
    violations: dict[str, set[str]] = {}
    for sub in ("scripts", "hooks"):
        sdir = root / sub
        if not sdir.is_dir():
            continue
        for p in sorted(sdir.glob("*.py")):
            text = p.read_text(encoding="utf-8", errors="replace")
            found: set[str] = set()
            for pat in _LITERAL_PATTERNS:
                found |= set(pat.findall(text))
            bad = found - known - _ARGPARSE_ACTIONS
            if bad:
                violations[f"{sub}/{p.name}"] = bad
    return violations


class TestEmitActionVocabulary:
    def test_vocabulary_exists_unique_sorted(self):
        """EMIT_ACTIONS: the single controlled word table for the emit
        action field — exists, unique, sorted (stable diff / review)."""
        import event_taxonomy as et
        words = et.EMIT_ACTIONS
        assert isinstance(words, (list, tuple)) and words, (
            "event_taxonomy.EMIT_ACTIONS must be a non-empty sequence")
        assert list(words) == sorted(set(words)), (
            f"EMIT_ACTIONS must be sorted + unique; got {words}")

    def test_vocabulary_covers_preexisting_and_new_words(self):
        """The 7 words already emitted by real code + the 11 new #459 faces
        are all registered — the table is complete, not aspirational."""
        import event_taxonomy as et
        expected = {
            # pre-existing producers (grep-verified 2026-08-20)
            "claim_migrate", "verify", "converge", "failure_blocked",
            "dispatch", "priority_deviation", "capability_switch",
            # #459 adopted faces
            "ask_back", "must_stop", "must_ask", "ladder_required",
            "death_verdict_rejected", "plan_stall",
            "top1_reject", "capability_reject",
            "stale_plan_on_new_evidence",
            "analysis_recorded", "analysis_blocked",
        }
        missing = expected - set(et.EMIT_ACTIONS)
        assert not missing, f"EMIT_ACTIONS missing words: {sorted(missing)}"

    def test_every_emit_action_literal_in_scripts_and_hooks_is_registered(self):
        """CI anchor: scan scripts/*.py + hooks/*.py for action literals —
        keyword form (action="word"), the trace-helper first-arg forms
        (dispatch_gate / ask_for_direction_gate), and the positional
        emit(ws, actor, "word") form. Any literal outside EMIT_ACTIONS is a
        vocabulary violation. argparse's own action kwarg (store_true / ...)
        is excluded — same keyword, different contract."""
        violations = _unregistered_action_literals(REPO_ROOT)
        assert not violations, (
            f"unregistered emit action words (extend EMIT_ACTIONS in "
            f"scripts/event_taxonomy.py): {violations}")

    def test_anchor_sees_digit_bearing_action_words(self, tmp_path):
        """F1 regression: the anchor regexes must MATCH action words that
        contain digits. Pre-fix ([a-z_]+) this branch's own top1_reject was
        invisible to the scan and an unregistered digit word sailed through
        the CI anchor while non-digit ones were caught — the anchor's
        'violation turns red' contract silently did not cover them."""
        sub = tmp_path / "scripts"
        sub.mkdir()
        # unregistered digit words in every literal form the anchor knows,
        # plus an argparse action kwarg that must stay excluded
        (sub / "fake_gate.py").write_text(
            '_emit_trace(ws, "top2_reject")\n'
            '_emit_interception(workspace, "s3_retry")\n'
            'kunglao_log.emit(ws, "orchestrator", "t1000_rewind")\n'
            'parser.add_argument("--x", action="store_true")\n',
            encoding="utf-8")
        violations = _unregistered_action_literals(tmp_path)
        assert violations.get("scripts/fake_gate.py") == {
            "top2_reject", "s3_retry", "t1000_rewind"}, (
            f"digit-bearing literals must be visible to the anchor; "
            f"got {violations}")
        # registered digit word must NOT be flagged — the anchor scans
        # against EMIT_ACTIONS, it does not blanket-reject digits
        (sub / "fake_gate.py").write_text(
            '_emit_trace(ws, "top1_reject")\n', encoding="utf-8")
        assert _unregistered_action_literals(tmp_path) == {}


# ---------- ① ask_for_direction_gate interception faces -----------------

class TestAskForDirectionGateEmit:
    def _ws(self, tmp: Path) -> Path:
        ws = tmp / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
        return ws

    def test_type_a_ask_back_emits_with_rc(self, tmp, events):
        import ask_for_direction_gate as afd
        rc = afd.check(self._ws(tmp), "should I dispatch the next worker now?")
        assert rc == 1
        rows = _actions(events, "ask_back")
        assert rows, f"Type A interception must emit ask_back; got {events}"
        assert rows[-1]["exit"] == 1, f"event must carry rc; got {rows[-1]}"
        assert rows[-1]["actor"] == "orchestrator"

    def test_type_a_three_strike_hard_pause_carries_rc2(self, tmp, events):
        import ask_for_direction_gate as afd
        ws = self._ws(tmp)
        # strikes 1-2: rc=1; strike 3 crosses the 3-in-an-hour threshold
        assert afd.check(ws, "should I dispatch the next worker?") == 1
        assert afd.check(ws, "should I dispatch the next worker?") == 1
        assert afd.check(ws, "should I dispatch the next worker?") == 2
        strikes = _actions(events, "ask_back")
        assert len(strikes) == 3, (
            f"every interception emits; got {len(strikes)} for 3 checks")
        assert [s["exit"] for s in strikes] == [1, 1, 2], (
            f"event exit must mirror each rc; got {strikes}")

    def test_type_s_must_stop_emits(self, tmp, events):
        import ask_for_direction_gate as afd
        rc = afd.check(self._ws(tmp),
                       "we will run git push --force to publish the results")
        assert rc == 2
        assert _actions(events, "must_stop"), f"got {events}"

    def test_type_d_must_ask_emits(self, tmp, events):
        import ask_for_direction_gate as afd
        rc = afd.check(self._ws(tmp),
                       "this request is not in original scope for the task")
        assert rc == 2
        assert _actions(events, "must_ask"), f"got {events}"

    def test_type_d_blocker_without_exhaustion_ladder_required(self, tmp, events):
        import ask_for_direction_gate as afd
        rc = afd.check(self._ws(tmp),
                       "we encountered blocker: the VM network is down")
        assert rc == 1
        rows = _actions(events, "ladder_required")
        assert rows and rows[-1]["exit"] == 1, f"got {events}"

    def test_type_d_ladder_exhausted_blocker_stays_must_ask(self, tmp, events):
        """F2 (#459 review): the ladder-EXHAUSTED sub-face — a blocker on a
        claim whose failure_analysis recorded NO candidates after 3+
        attempts (#495 fields) HARD_PAUSEs as must-ask rc=2 (charter v2:
        tools/resources exhausted is not self-resolvable). Distinct from
        the rc=1 ladder_required face above; the event detail must name
        the exhausted claim so a --tail can tell the two apart."""
        import yaml
        import ask_for_direction_gate as afd
        ws = self._ws(tmp)
        (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [
            {"id": "C-7", "status": "OPEN", "promotion_attempts": 3}]},
            sort_keys=False), encoding="utf-8")
        adir = ws / "analyses"
        adir.mkdir()
        (adir / "failure-C-7.yaml").write_text(yaml.safe_dump({
            "claim": "C-7", "candidates": [],
            "validated_capability": "frida reaches the check",
            "identified_obstacle": "spawn timeout kills the path"},
            sort_keys=False), encoding="utf-8")
        rc = afd.check(ws, "we encountered blocker: the VM network is down")
        assert rc == 2, "exhausted-ladder blocker must stay must-ask (rc=2)"
        rows = _actions(events, "must_ask")
        assert rows and rows[-1]["exit"] == 2, f"got {events}"
        detail = rows[-1].get("detail") or ""
        assert "ladder-exhausted" in detail and "C-7" in detail, (
            f"detail must distinguish the exhausted sub-face; got {detail!r}")
        assert _actions(events, "ladder_required") == [], (
            f"exhausted path must not also emit ladder_required; got {events}")

    def test_type_e_death_verdict_rejected_emits(self, tmp, events):
        import ask_for_direction_gate as afd
        rc = afd.check(self._ws(tmp), "这条路走不通,换别的思路吧")
        assert rc == 1
        rows = _actions(events, "death_verdict_rejected")
        assert rows and rows[-1]["exit"] == 1, f"got {events}"

    def test_plan_stall_emits(self, tmp, events):
        import ask_for_direction_gate as afd
        rc = afd.check(self._ws(tmp),
                       "milestone summary reached.\n下一步: verify C-2")
        assert rc == 1
        rows = _actions(events, "plan_stall")
        assert rows and rows[-1]["exit"] == 1, f"got {events}"

    def test_clean_text_emits_nothing(self, tmp, events):
        """Guard: the interception face only — clean passes stay silent
        (zero-noise contract, mirroring dispatch_gate's top1-silent guard)."""
        import ask_for_direction_gate as afd
        rc = afd.check(self._ws(tmp),
                       "proceeding with the static analysis of the sample")
        assert rc == 0
        assert not events, f"clean pass must not emit; got {events}"


# ---------- ① dispatch_gate #496 REJECT faces (real subprocess) ----------

class TestDispatchGateRejectEmit:
    def test_top1_reject_leaves_trace(self, tmp_path):
        """#459: the top-1 REJECT face must reach the unified log — the
        excused deviation already traces (priority_deviation, #496); the
        REJECT side was stderr-only."""
        root = tmp_path / "r1"
        ws = _top1_ws(root)
        r = _run_gate(root, ws, "[T2 tools=grep] claim C-3 background sweep")
        assert r.returncode == 2, f"stderr={r.stderr!r}"
        rows = [e for e in _event_rows(ws) if e.get("action") == "top1_reject"]
        assert any(e.get("claim") == "C-3" for e in rows), (
            f"unified log must carry the top1 REJECT trace; rows={_event_rows(ws)}")
        assert all(e.get("exit") == 2 for e in rows), f"rows={rows}"

    def test_capability_reject_leaves_trace(self, tmp_path):
        """#459: the capability-card REJECT face must reach the unified log
        (trajectory-1 replay: validated frida, silent pivot to xposed)."""
        root = tmp_path / "r2"
        ws = _capability_ws(root)
        r = _run_gate(root, ws,
                      "[T2 tools=rev-xposed] claim C-1 hook the check via xposed")
        assert r.returncode == 2, f"stderr={r.stderr!r}"
        rows = [e for e in _event_rows(ws)
                if e.get("action") == "capability_reject"]
        assert any(e.get("claim") == "C-1" for e in rows), (
            f"unified log must carry the capability REJECT trace; "
            f"rows={_event_rows(ws)}")
        assert all(e.get("exit") == 2 for e in rows), f"rows={rows}"


# ---------- ① plan_drift_detector class-7 WARN face ---------------------

class TestPlanDriftWarnEmit:
    def _warn_ws(self, tmp: Path) -> Path:
        ws = tmp / "ws"
        ws.mkdir(parents=True)
        (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
        plan = ws / "global_plan.txt"
        plan.write_text("# plan v1\nno claim ids here\n", encoding="utf-8")
        an = ws / "analyses" / "failure-C-1.yaml"
        an.parent.mkdir()
        an.write_text("claim: C-1\n", encoding="utf-8")
        now = time.time()
        os.utime(plan, (now - 3600, now - 3600))  # plan written an hour ago
        return ws

    def test_stale_plan_warn_emits_per_item(self, tmp, events):
        """#497 class-7 WARN is observe-only on stdout; #459 adds the
        unified-log face so the Orient layer sees it without re-deriving
        mtimes. WARN never changes the exit code — neither may the emit."""
        import plan_drift_detector as pdd
        rc = pdd.check(self._warn_ws(tmp), active_only=True)
        assert rc == 0, "stale-plan warns must NOT count toward drift rc"
        rows = _actions(events, "stale_plan_on_new_evidence")
        assert rows and any(r.get("claim") == "C-1" for r in rows), (
            f"class-7 WARN must emit with the claim id; got {events}")

    def test_fresh_plan_emits_nothing(self, tmp, events):
        import plan_drift_detector as pdd
        ws = tmp / "ws"
        ws.mkdir(parents=True)
        (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
        (ws / "global_plan.txt").write_text("# plan v1\n", encoding="utf-8")
        assert pdd.check(ws, active_only=True) == 0
        assert not events, f"no warn, no event; got {events}"


# ---------- ② failure events (#495 landing face) ------------------------

class TestFailureAnalysisEmit:
    def _ws(self, tmp: Path, attempts: int = 1) -> Path:
        import yaml
        ws = tmp / "ws"
        ws.mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [
            {"id": "C-1", "status": "OPEN",
             "promotion_attempts": attempts}]}, sort_keys=False),
            encoding="utf-8")
        return ws

    def test_record_success_emits_analysis_recorded(self, tmp, events):
        """--record success = the three-artifact LANDING event (2026-08-19
        issue comment: Orient layer input). detail carries source + the
        candidates count."""
        import failure_analysis_gate as fag
        ws = self._ws(tmp)
        r = fag.record_analysis(
            ws, "C-1",
            assumption="frida spawn keeps the process alive",
            validity="not-justified",
            next_method="listen mode instead of spawn",
            validated_capability="frida injection reaches the check",
            identified_obstacle="spawn timeout kills the spawn path only",
            source="lesson-hit",
            library=tmp / "lessons")
        assert r["recorded"], f"record failed: {r}"
        rows = _actions(events, "analysis_recorded")
        assert rows, f"record success must emit; got {events}"
        row = rows[-1]
        assert row.get("claim") == "C-1"
        assert "source=lesson-hit" in (row.get("detail") or ""), f"row={row}"
        assert "candidates=0" in (row.get("detail") or ""), f"row={row}"

    def test_artifact_gap_blocked_emits_analysis_blocked(self, tmp, events):
        """BLOCKED with missing three-artifacts -> analysis_blocked carrying
        the missing list (the orchestrator's to-do)."""
        import failure_analysis_gate as fag
        ws = self._ws(tmp)  # attempts=1, no analysis at all
        rc = fag.main([str(ws), "C-1"])
        assert rc == 1
        rows = _actions(events, "analysis_blocked")
        assert rows, f"artifact-gap BLOCKED must emit analysis_blocked; got {events}"
        detail = rows[-1].get("detail") or ""
        assert "validated_capability" in detail and "identified_obstacle" in detail, (
            f"detail must name the missing artifacts; got {detail!r}")
        assert rows[-1].get("claim") == "C-1"

    def test_stale_coverage_blocked_keeps_failure_blocked(self, tmp, events):
        """Split pin: BLOCKED because covers_attempt lags (artifacts all
        present) keeps the pre-existing word failure_blocked — the word
        carries the REASON, no double emission."""
        import yaml
        import failure_analysis_gate as fag
        ws = tmp / "ws"
        ws.mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [
            {"id": "C-1", "status": "OPEN", "promotion_attempts": 2}]},
            sort_keys=False), encoding="utf-8")
        adir = ws / "analyses"
        adir.mkdir()
        (adir / "failure-C-1.yaml").write_text(yaml.safe_dump({
            "claim": "C-1", "covers_attempt": 1,
            "validated_capability": "frida works",
            "identified_obstacle": "spawn timeout"}, sort_keys=False),
            encoding="utf-8")
        rc = fag.main([str(ws), "C-1"])
        assert rc == 1
        assert _actions(events, "analysis_blocked") == [], (
            f"stale coverage is not an artifact gap; got {events}")
        rows = _actions(events, "failure_blocked")
        assert rows and rows[-1].get("claim") == "C-1", f"got {events}"


# ---------- ① convergence_check per-round DECISION (existing face) ------

class TestConvergenceDecisionEmit:
    def test_decision_round_emits_converge_with_counts(self, tmp, events, capsys):
        """The per-round DECISION already reaches the log (action=converge,
        #287); #459 makes the detail self-contained for --tail diagnosis
        (decision + open/partial/slots/workers counts) without touching the
        decision itself."""
        import convergence_check as cc
        ws = tmp / "ws"
        ws.mkdir(parents=True)
        (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
        rc = cc.main([str(ws), "--json"])
        rows = _actions(events, "converge")
        assert rows, f"every round's DECISION must emit; got {events}"
        row = rows[-1]
        assert row.get("exit") == rc, f"event exit must mirror rc; {row}"
        detail = row.get("detail") or ""
        assert "open=" in detail and "partial=" in detail, (
            f"detail must carry the counts for tail diagnosis; got {detail!r}")

    def test_decision_round_exit_code_unchanged_by_emit(self, tmp, events,
                                                        monkeypatch):
        """F3 (#459 review): the emit is observability only — rc identical
        between the healthy path (event fires) and the crash path (emit
        raises), compared against each other on a NON-trivial decision
        state (OPEN claim -> DISPATCH rc=1), not just rc-range membership.
        Regression anchor for '只加观测'."""
        import kunglao_log
        import yaml
        import convergence_check as cc
        ws = tmp / "ws"
        ws.mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [
            {"id": "C-1", "status": "OPEN"}]}, sort_keys=False),
            encoding="utf-8")
        rc_with_emit = cc.main([str(ws), "--json"])  # emit fires (captured)
        rows = _actions(events, "converge")
        assert rows, f"emit must fire on the healthy path; got {events}"
        assert rows[-1]["exit"] == rc_with_emit, (
            f"event exit must mirror the healthy rc; got {rows[-1]}")

        def _boom(*a, **kw):
            raise RuntimeError("log write failed")

        monkeypatch.setattr(kunglao_log, "emit", _boom)
        rc_emit_crashed = cc.main([str(ws), "--json"])
        assert rc_emit_crashed == rc_with_emit == 1, (
            f"emit failure must not move the decision's exit code: "
            f"healthy={rc_with_emit} crashed={rc_emit_crashed}")


# ---------- ③ --tail read-only diagnostic -------------------------------
# (CLI contract tests live in tests/test_kunglao_log.py::TestTailCli —
# module-owned behavior; this file covers the adopted FACES.)


# ---------- fail-open: observability never gates decisions ---------------

class TestFailOpenEmit:
    def test_ask_gate_rc_survives_emit_crash(self, tmp, monkeypatch):
        import kunglao_log
        import ask_for_direction_gate as afd

        def _boom(*a, **kw):
            raise RuntimeError("log write failed")

        monkeypatch.setattr(kunglao_log, "emit", _boom)
        ws = tmp / "ws"
        ws.mkdir(parents=True)
        (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
        assert afd.check(ws, "should I dispatch?") == 1
        assert afd.check(ws, "git push --force to publish") == 2

    def test_record_survives_emit_crash(self, tmp, monkeypatch):
        import kunglao_log
        import failure_analysis_gate as fag

        def _boom(*a, **kw):
            raise RuntimeError("log write failed")

        monkeypatch.setattr(kunglao_log, "emit", _boom)
        import yaml
        ws = tmp / "ws"
        ws.mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [
            {"id": "C-1", "status": "OPEN", "promotion_attempts": 1}]},
            sort_keys=False), encoding="utf-8")
        r = fag.record_analysis(
            ws, "C-1", assumption="a", validity="not-justified",
            next_method="different method", source="lesson-hit",
            library=tmp / "lessons")
        assert r["recorded"], f"record must survive emit crash; got {r}"

    def test_dispatch_reject_survives_unwritable_log(self, tmp_path):
        """Hook side: sabotage runs/ (make it a FILE so the log dir cannot
        be created) — the #496 teeth must still REJECT with rc=2."""
        root = tmp_path / "r1"
        ws = _top1_ws(root)
        (ws / "runs").write_text("", encoding="utf-8")  # runs/ is now a file
        r = _run_gate(root, ws, "[T2 tools=grep] claim C-3 background sweep")
        assert r.returncode == 2, (
            f"REJECT must not depend on the log write; rc={r.returncode}, "
            f"stderr={r.stderr!r}")

    def test_convergence_round_rc_survives_emit_crash(self, tmp, events,
                                                      monkeypatch):
        """4th fail-open face (#459 review F3): the convergence per-round
        DECISION. Emit crash must not move the decision rc — the fail-open
        posture the ask gate / record / REJECT anchors above already pin,
        on a non-trivial state (OPEN claim -> DISPATCH rc=1)."""
        import kunglao_log
        import yaml
        import convergence_check as cc
        ws = tmp / "ws"
        ws.mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [
            {"id": "C-1", "status": "OPEN"}]}, sort_keys=False),
            encoding="utf-8")
        healthy = cc.main([str(ws), "--json"])  # healthy baseline rc
        assert _actions(events, "converge"), "sanity: healthy path emits"

        def _boom(*a, **kw):
            raise RuntimeError("log write failed")

        monkeypatch.setattr(kunglao_log, "emit", _boom)
        assert cc.main([str(ws), "--json"]) == healthy == 1, (
            "convergence DECISION rc must survive the emit crash "
            "(healthy != 0 -> the comparison is non-trivial)")
