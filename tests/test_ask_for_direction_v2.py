#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TDD RED — issue #497, decision grammar v2 (declarative-sentence gates).

v0.1.1 field evidence: the two recurring misbehaviours were DECLARATIVE
sentences, not questions — every existing enforcement lived on the
interrogative layer (Type A/B patterns, redirect counting):

  trajectory 1 (premature death verdict): transient failures x2 + "这条路
  走不通" with no obstacle/capability evidence -> the task died quietly
  because a blocker reworded as a death verdict silences BOTH gates
  (must-ask deadlocks hard-prohibition #1).

  trajectory 2 (plan stall): milestone summary + "下一步: ..." followed by
  zero tool actions -> letter-compliant Type-B-in-spirit violation.

Behaviour-equivalence classes tested here (NOT verbatim narrative replay —
plan risk row "双轨迹重演测试过度拟合叙事细节"):
  - TYPE D blocker tripwire tightens: HARD_PAUSE only with a ladder-exhaustion
    marker (#495 fields: failure_analysis with empty candidates on a claim
    with promotion_attempts >= 3); otherwise degrades to rc=1 with
    climb-the-ladder guidance.
  - TYPE E (death declaration, NEW): rejected without evidence, allowed with
    obstacle-REFUTED / capability-falsification evidence.
  - plan-stall (NEW): "下一步:"/"next step:" declaration with no subsequent
    tool action in the self_redirects event stream -> Type B equivalent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import ask_for_direction_gate as afd  # noqa: E402


def write_register(ws: Path, claims: list[dict]) -> None:
    import yaml
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def write_analysis(ws: Path, cid: str, entry: dict) -> Path:
    import yaml
    adir = ws / "analyses"
    adir.mkdir(exist_ok=True)
    p = adir / f"failure-{cid}.yaml"
    base = {
        "claim": cid,
        "covers_attempt": 1,
        "method_assumption": "spawn returns within timeout",
        "assumption_validity": "not-justified",
        "next_method": "listen mode instead of spawn",
        "next_method_source": "lesson-hit",
        "validated_capability": "JNI bridge works (NewByteArray called)",
        "identified_obstacle": "spawn timeout kills only the spawn path",
        "method_ladder_query": "spawn timeout",
        "candidates": [{"file": "lesson-x.md", "score": 3}],
    }
    base.update(entry)
    p.write_text(yaml.safe_dump(base, allow_unicode=True, sort_keys=False),
                 encoding="utf-8")
    return p


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


# ----- TYPE D blocker tightening (宪法校准 v2) ------------------------

class TestTypeDBlockerTightening:
    def test_new_blocker_without_ladder_exhaustion_degrades_to_rc1(
            self, workspace: Path, capsys) -> None:
        """Negative (d): blocker claim with NO ladder-exhaustion marker ->
        downgrade to ladder guidance (rc=1), NOT HARD_PAUSE."""
        rc = afd.check(workspace,
                       "encountered blocker: toolchain mismatch after upgrade")
        assert rc == 1
        out = capsys.readouterr().out
        assert "ladder" in out.lower() or "梯" in out

    def test_new_blocker_with_ladder_exhaustion_hard_pauses(
            self, workspace: Path) -> None:
        """Ladder exhausted (#495 fields: empty candidates + attempts>=3) ->
        must-ask preserved (rc=2)."""
        write_register(workspace, [{"id": "C-1", "status": "OPEN",
                                    "promotion_attempts": 3}])
        write_analysis(workspace, "C-1", {"covers_attempt": 3,
                                          "candidates": []})
        rc = afd.check(workspace, "encountered new blocker: no licenses left")
        assert rc == 2

    def test_candidates_present_means_ladder_not_exhausted(
            self, workspace: Path) -> None:
        write_register(workspace, [{"id": "C-1", "status": "OPEN",
                                    "promotion_attempts": 3}])
        write_analysis(workspace, "C-1", {"covers_attempt": 3})
        rc = afd.check(workspace, "encountered new blocker: no licenses left")
        assert rc == 1

    def test_attempts_below_3_means_ladder_not_exhausted(
            self, workspace: Path) -> None:
        write_register(workspace, [{"id": "C-1", "status": "OPEN",
                                    "promotion_attempts": 2}])
        write_analysis(workspace, "C-1", {"covers_attempt": 2,
                                          "candidates": []})
        rc = afd.check(workspace, "encountered new blocker: no licenses left")
        assert rc == 1

    def test_identity_ambiguity_still_hard_pauses(self, workspace: Path) -> None:
        rc = afd.check(workspace,
                       "multiple VMs found matching the criteria")
        assert rc == 2

    def test_scope_change_still_hard_pauses(self, workspace: Path) -> None:
        rc = afd.check(workspace,
                       "this is a scope change beyond the task boundary")
        assert rc == 2


# ----- TYPE E: death declaration (判死门) ------------------------------

class TestTypeE:
    @pytest.mark.parametrize("verdict", [
        "这条路走不通",   # trajectory-1 verbatim class
        "此路不通",
        "行不通",
        "无法继续",
        "这条路卡死了",
        "this is a dead end",
        "cannot proceed further",
        "no viable path forward",
    ])
    def test_death_declaration_without_evidence_rejected(
            self, workspace: Path, verdict: str, capsys) -> None:
        rc = afd.check(workspace, f"spawn 超时两次。{verdict}，换个方向吧")
        assert rc == 1
        out = capsys.readouterr().out
        assert "ladder" in out.lower() or "梯" in out

    def test_death_with_obstacle_claim_refuted_is_legal_terminal(
            self, workspace: Path) -> None:
        """Negative (c): obstacle claim promoted (#495) then REFUTED ->
        the death verdict is allowed (rc=0)."""
        write_register(workspace, [
            {"id": "C-1", "status": "OPEN", "promotion_attempts": 2},
            {"id": "C-2", "status": "REFUTED",
             "origin": "failure-obstacle", "obstacle_for": "C-1"},
        ])
        rc = afd.check(workspace, "这条路走不通")
        assert rc == 0

    def test_death_with_analysis_refuted_outcome_is_legal_terminal(
            self, workspace: Path) -> None:
        """Capability-falsification evidence: failure_analysis record with
        outcome REFUTED -> death verdict allowed."""
        write_register(workspace, [{"id": "C-1", "status": "OPEN",
                                    "promotion_attempts": 2}])
        write_analysis(workspace, "C-1",
                       {"outcome": "REFUTED",
                        "what_happened": "spawn path disproven, listen works"})
        rc = afd.check(workspace, "cannot proceed down this path")
        assert rc == 0

    def test_open_obstacle_claim_is_not_death_evidence(
            self, workspace: Path) -> None:
        """A promoted-but-unresolved obstacle claim is a TODO, not a
        terminal — the verdict is still rejected."""
        write_register(workspace, [
            {"id": "C-1", "status": "OPEN", "promotion_attempts": 2},
            {"id": "C-2", "status": "OPEN",
             "origin": "failure-obstacle", "obstacle_for": "C-1"},
        ])
        rc = afd.check(workspace, "这条路走不通")
        assert rc == 1


# ----- plan-stall (计划搁浅, Type B equivalent) ------------------------

class TestPlanStall:
    def test_zh_declaration_without_action_rejected(
            self, workspace: Path, capsys) -> None:
        rc = afd.check(workspace,
                       "里程碑总结： C-1 完成。\n下一步: 用 listen 模式重测 C-2")
        assert rc == 1
        out = capsys.readouterr().out
        assert "Type B" in out  # equivalent-class framing in guidance

    def test_en_declaration_without_action_rejected(
            self, workspace: Path) -> None:
        rc = afd.check(workspace,
                       "Milestone reached.\nnext step: run the verifier on C-3")
        assert rc == 1

    def test_fullwidth_colon_also_rejected(self, workspace: Path) -> None:
        rc = afd.check(workspace, "总结完毕。\n下一步：验证 C-2")
        assert rc == 1

    def test_declaration_without_colon_not_flagged(
            self, workspace: Path) -> None:
        """Zero-regression anchor: 'next step' / '下一步' WITHOUT a colon is
        narrative, not a stall declaration."""
        rc = afd.check(workspace, "计划里的 next step 是 C-2。下一步是派发。")
        assert rc == 0

    def test_markdown_heading_not_a_declaration(
            self, workspace: Path) -> None:
        """F3: '## next step:' as a markdown heading is a plan-file title,
        not a stall declaration — must not trip the gate (zh+en)."""
        assert afd.check(workspace,
                         "## next step: Phase 2 verification plan") == 0
        assert afd.check(workspace, "## 下一步: 第二阶段计划") == 0

    def test_heading_does_not_mask_body_declaration(
            self, workspace: Path) -> None:
        """F3 guard: skipping headings must not hide a real body
        declaration in the same text."""
        rc = afd.check(workspace,
                       "## next step: Phase 2\n正文。\nnext step: verify C-2")
        assert rc == 1

    def test_action_between_declarations_clears_the_window(
            self, workspace: Path) -> None:
        """decl -> act (tool-action event) -> new decl: not stalled."""
        assert afd.check(workspace, "总结。\n下一步: X") == 1
        assert afd.check(workspace,
                         "Dispatching W-9 via priority_ratio.py now") == 0
        rc = afd.check(workspace, "W-9 在跑。\n下一步: 验证 C-2")
        assert rc == 0

    def test_stall_persists_while_no_action_happens(
            self, workspace: Path) -> None:
        assert afd.check(workspace, "总结。\n下一步: X") == 1
        # a round with neither declaration nor action narrative
        assert afd.check(workspace, "C-1 已完成，等待结果。") == 0
        rc = afd.check(workspace, "还在等。\n下一步: X")
        assert rc == 1

    def test_warm_history_does_not_clear_first_declaration(
            self, workspace: Path) -> None:
        """F1 (review #497-r1): a WARM action history must not grandfather a
        fresh declaration through — actions BEFORE the declaration did not
        execute the DECLARED step. Reviewer demonstrated rc=0 here before
        the bounded-window fix (trajectory-2 shape: act -> milestone +
        'next step:' -> wait)."""
        assert afd.check(workspace,
                         "Dispatching W-1 via priority_ratio.py") == 0
        rc = afd.check(workspace,
                       "DPoP milestone reached.\nnext step: verify C-2")
        assert rc == 1

    def test_warm_history_declaration_cleared_by_subsequent_action(
            self, workspace: Path) -> None:
        """F1 positive side: an action AFTER the declaration (inside the
        bounded window) clears it — the next declaration passes."""
        assert afd.check(workspace,
                         "Dispatching W-1 via priority_ratio.py") == 0
        assert afd.check(workspace,
                         "milestone.\nnext step: verify C-2") == 1
        assert afd.check(workspace, "Running the C-2 verifier now") == 0
        rc = afd.check(workspace, "C-2 verified.\nnext step: close claim")
        assert rc == 0

    def test_action_outside_bounded_window_does_not_clear(
            self, workspace: Path) -> None:
        """F1 bounded window: only the PLAN_STALL_WINDOW_EVENTS stream
        events AFTER the declaration form the clearing window — a later
        action does not retroactively clear it. Pads are violation-class
        events (neither declaration nor action) so the window position is
        controlled exactly."""
        assert afd.check(workspace, "总结。\n下一步: X") == 1
        for _ in range(afd.PLAN_STALL_WINDOW_EVENTS):
            afd._append_event(workspace, "window pad", "ask-back:")
        assert afd.check(workspace, "Dispatching W-9 now") == 0
        rc = afd.check(workspace, "下一步: 验证 C-2")
        assert rc == 1

    def test_action_events_do_not_inflate_three_strike_counter(
            self, workspace: Path) -> None:
        """tool-action bookkeeping must not count as self-redirects — the
        3-strike HARD_PAUSE semantics stay untouched."""
        for _ in range(3):
            assert afd.check(workspace,
                             "Dispatching worker via priority_ratio.py") == 0
        rc = afd.check(workspace, "should I do thing X?")
        assert rc == 1  # NOT 2: 3 tool-action events are not redirects


# ----- trajectory replay (behaviour-equivalence classes) ---------------

class TestTrajectoryReplay:
    def test_trajectory1_transient_failures_then_death_verdict_intercepted(
            self, workspace: Path, capsys) -> None:
        """轨迹1 equivalence class: 2 transient failures recorded (analysis
        present, ladder NOT exhausted) + death verdict -> intercepted and
        pointed at the ladder, never a quiet terminal."""
        write_register(workspace, [{"id": "C-1", "status": "OPEN",
                                    "promotion_attempts": 2}])
        write_analysis(workspace, "C-1", {"covers_attempt": 2})
        rc = afd.check(workspace,
                       "frida spawn 第二次超时。这条路走不通，换方向吧。")
        assert rc == 1
        out = capsys.readouterr().out
        assert "failure_analysis" in out or "梯" in out

    def test_trajectory2_milestone_summary_next_step_no_action(
            self, workspace: Path, capsys) -> None:
        """轨迹2 equivalence class: milestone summary + next-step declaration
        + zero tool actions -> intercepted (execution demanded, no waiting)."""
        rc = afd.check(workspace,
                       "DPoP 里程碑达成：三产物齐。\n下一步: 对 C-2 跑 listen 模式验证")
        assert rc == 1
        out = capsys.readouterr().out
        assert "执行" in out or "execute" in out.lower()


# ----- event-stream bookkeeping shape ----------------------------------

class TestEventStream:
    def test_declaration_logged_in_redirect_stream(
            self, workspace: Path) -> None:
        afd.check(workspace, "总结。\n下一步: X")
        log = workspace / afd.SELF_REDIRECT_LOG
        assert log.exists()
        events = [json.loads(line) for line in
                  log.read_text(encoding="utf-8").strip().splitlines()]
        kinds = {e["violation"].split(":", 1)[0] for e in events}
        assert "plan-stall" in kinds
