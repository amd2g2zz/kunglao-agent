# -*- coding: utf-8 -*-
"""tests/test_loop_prompt_split_434.py — loop-prompt restructure (issue 434).

The cron-injected operating manual (5-minute repetition) splits into:

  (a) CONSTITUTION — static decision semantics, injected ONCE at
      SessionStart (hooks/session_start.py prints it into the session
      context; the cron body stops carrying it);
  (b) STRATEGY SECTIONS — per decision, injected dynamically through a
      VERSIONED SEAM reading the round-strategy object (the producer lands
      with the strategy-object issue later; the seam must read an absent
      file and render NOTHING, cleanly);
  (c) GUARD GUIDANCE — dynamic, on Stop-hook fires (see the workguard
      suite).

Watchdog demotion: the cron heartbeat fires ONLY when an expected event
did not arrive. The loop body must stop re-injecting the manual on every
tick — a normal-event wake is a NO-OP for the LLM.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from _factories import write_claims_register, write_hook_state

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
for p in (SCRIPTS, HOOKS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import heartbeat_loop_prompt as hlp  # noqa: E402

# Manual-body markers that must leave the cron prompt (they are
# constitution content now — the cron body is the watchdog face).
MANUAL_MARKERS = (
    "Smart-ping",            # step 2 operating instruction
    "action_taken; an empty field = idle fault",  # step 5 fill-in manual
    "MUST dispatch priority_ratio",   # step 3 imperative decision table
    "handoff-check PASS first",       # step 3 CONVERGED branch
    "§6.2",                  # notes ritual reference
)
# Registration contract markers that MUST survive (loop_scheduler's
# _is_our_entry matches on them — dropping them orphans the durable cron).
REGISTRATION_MARKERS = ("kunglao-agent heartbeat", "--heartbeat-on",
                        "--loop-registered")


class TestWatchdogBody:
    def test_prompt_no_longer_carries_the_manual(self, tmp_path):
        text = hlp.build_prompt(str(tmp_path), interval="5m")
        for marker in MANUAL_MARKERS:
            assert marker not in text, (
                f"manual body re-injected by the cron: {marker!r} must be "
                "constitution content, not per-tick content")

    def test_prompt_keeps_registration_markers(self, tmp_path):
        """The born-registered contract and the scheduler's entry match
        both survive the restructure."""
        text = hlp.build_prompt(str(tmp_path), interval="5m")
        for marker in REGISTRATION_MARKERS:
            assert marker in text, f"registration marker lost: {marker!r}"

    def test_prompt_is_watchdog_shaped(self, tmp_path):
        """The body delegates to the tick's watchdog verdict: quiet -> the
        wake is a NO-OP (end the turn); fired -> act on the reasons."""
        text = hlp.build_prompt(str(tmp_path), interval="5m")
        low = text.lower()
        assert "watchdog" in low
        assert "no-op" in low or "noop" in low

    def test_prompt_keeps_real_json_invocation(self, tmp_path):
        """The 611 pin survives: any convergence_check line the prompt
        carries must use the real --json surface, never the dead `decision`
        subcommand."""
        text = hlp.build_prompt(str(tmp_path), interval="5m")
        assert "decision → imperative execution" not in text
        cc_lines = [ln for ln in text.splitlines()
                    if "convergence_check" in ln and "python" in ln]
        if cc_lines:  # the fired-reason branch may carry it
            assert all("--json" in ln for ln in cc_lines), cc_lines


class TestConstitution:
    def test_constitution_carries_decision_semantics(self, tmp_path):
        """The imperative decision table + the action contract move to the
        constitution — injected once per session, not per tick."""
        text = hlp.constitution(str(tmp_path))
        for word in ("DISPATCH", "BLOCKED", "PARK", "SATURATED", "CONVERGED"):
            assert word in text, f"decision {word} missing from constitution"
        assert "DEFERRED" in text
        assert "action_taken" in text  # the per-tick output contract

    def test_constition_is_stable_text(self, tmp_path):
        """Same workspace -> identical constitution (injectable once,
        comparable across sessions)."""
        assert hlp.constitution(str(tmp_path)) == hlp.constitution(
            str(tmp_path))


class TestStrategySeam:
    def test_absent_object_renders_nothing_cleanly(self, tmp_path):
        import strategy_sections
        assert strategy_sections.render(tmp_path) == ""
        assert strategy_sections.pointer(tmp_path) is None

    def test_v1_object_renders_sections(self, tmp_path):
        import strategy_sections
        (tmp_path / "runs").mkdir()
        (tmp_path / "runs" / "round-strategy.json").write_text(json.dumps({
            "schema": "round-strategy/1", "round": 7,
            "sections": [
                {"title": "focus", "body": "verify chain first"},
                {"title": "stop", "body": "no new families this round"}]}),
            encoding="utf-8")
        text = strategy_sections.render(tmp_path)
        assert "focus" in text and "verify chain first" in text
        assert "no new families this round" in text
        assert "round-strategy" in strategy_sections.pointer(tmp_path)

    def test_unknown_schema_renders_nothing(self, tmp_path, capsys):
        """A future schema version the consumer does not know must render
        nothing (never guess) — and leave the canonical warn trace."""
        import strategy_sections
        (tmp_path / "runs").mkdir()
        (tmp_path / "runs" / "round-strategy.json").write_text(json.dumps({
            "schema": "round-strategy/999", "round": 1, "sections": []}),
            encoding="utf-8")
        assert strategy_sections.render(tmp_path) == ""


def _mk_session_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    write_claims_register(ws, [{"id": "C-1", "status": "OPEN"}])
    write_hook_state(ws, active_hooks=["completion_gate"])
    return ws


class TestSessionStartInjection:
    def test_session_start_injects_constitution_once(self, tmp_path, capsys):
        """SessionStart writes the constitution exactly once per session
        event — the manual is born here now, not on the cron."""
        import session_start as ss
        ws = _mk_session_ws(tmp_path)
        rc = ss.main_with_payload({"cwd": str(ws), "source": "startup"})
        out = capsys.readouterr().out
        assert rc == 0
        marks = [ln for ln in out.splitlines() if "CONSTITUTION" in ln]
        assert len(marks) == 1, f"constitution must land once: {out!r}"
        assert "DISPATCH" in out  # the decision semantics arrived

    def test_session_start_resume_injects_last_strategy(
            self, tmp_path, capsys):
        """Resume re-attaches the operator to the last round strategy via
        the same seam (b) — sections render when the object exists."""
        import session_start as ss
        ws = _mk_session_ws(tmp_path)
        (ws / "runs" / "round-strategy.json").write_text(json.dumps({
            "schema": "round-strategy/1", "round": 7,
            "sections": [{"title": "focus",
                          "body": "settle C-3 before new claims"}]}),
            encoding="utf-8")
        rc = ss.main_with_payload({"cwd": str(ws), "source": "resume"})
        out = capsys.readouterr().out
        assert rc == 0
        assert "settle C-3 before new claims" in out

    def test_session_start_injection_lands_ledger_row(
            self, tmp_path, capsys):
        """The injection is recorded (action=constitution_injected) — the
        once-per-session contract is auditable, not self-declared."""
        import session_start as ss
        ws = _mk_session_ws(tmp_path)
        ss.main_with_payload({"cwd": str(ws), "source": "startup"})
        capsys.readouterr()
        logs = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
        assert logs, "session start injection must leave a ledger row"
        rows = [json.loads(ln) for ln in
                logs[-1].read_text(encoding="utf-8").splitlines() if ln]
        assert any(r.get("action") == "constitution_injected"
                   for r in rows), rows

    def test_legacy_direct_call_still_arms(self, tmp_path, capsys):
        """The pre-existing session_start(workspace) API keeps its
        always_arm/renew contract (notice face pinned by an older suite)."""
        import session_start as ss
        ws = tmp_path / "ws"
        (ws / ".kunglao").mkdir(parents=True)
        rc = ss.session_start(ws)
        out = capsys.readouterr().out
        assert rc == 0
        assert "always_arm" in out


class TestPreCompactContinuity:
    def test_compact_note_stashed_for_delivery(self, tmp_path, capsys):
        """The PreCompact face STASHES the continuity note carrying the
        current strategy pointer (this harness build refuses
        hookSpecificOutput on PreCompact — #630 — so delivery rides
        SessionStart(compact)); compaction must not evaporate the
        strategy the round is running."""
        import compact_continuity
        ws = _mk_session_ws(tmp_path)
        (ws / "runs" / "round-strategy.json").write_text(json.dumps({
            "schema": "round-strategy/1", "round": 7,
            "sections": [{"title": "focus", "body": "x"}]}),
            encoding="utf-8")
        rc = compact_continuity.process_event(
            {"cwd": str(ws), "trigger": "auto"})
        out = capsys.readouterr().out
        assert rc == 0
        assert out == ""  # the rejected hookSpecificOutput shape is gone
        stash = json.loads((ws / "runs" / ".compact-continuity-note.json")
                           .read_text(encoding="utf-8"))
        assert "round-strategy.json (SET" in stash["note"]
        assert "compact" in stash["note"].lower()

    def test_compact_note_without_strategy_points_at_seam(
            self, tmp_path, capsys):
        """No strategy object yet (producer lands later): the note still
        stashes (compaction continuity face is live) and says the pointer
        is unset — never a crash, never silence."""
        import compact_continuity
        ws = _mk_session_ws(tmp_path)
        rc = compact_continuity.process_event(
            {"cwd": str(ws), "trigger": "manual"})
        out = capsys.readouterr().out
        assert rc == 0 and out == ""
        stash = json.loads((ws / "runs" / ".compact-continuity-note.json")
                           .read_text(encoding="utf-8"))
        assert "round-strategy.json (unset" in stash["note"]

    def test_compact_no_workspace_passes_through(self, tmp_path, capsys):
        import compact_continuity
        rc = compact_continuity.process_event({"cwd": str(tmp_path)})
        out = capsys.readouterr().out
        assert rc == 0 and out == ""

    def test_stash_delivered_and_consumed_on_compact_session_start(
            self, tmp_path, capsys):
        """SessionStart(source=compact) delivers the stashed note through
        the supported stdout channel, exactly once; unrelated starts
        (startup) do not re-deliver it."""
        import compact_continuity
        import session_start as ss
        ws = _mk_session_ws(tmp_path)
        compact_continuity.process_event({"cwd": str(ws), "trigger": "auto"})
        capsys.readouterr()
        rc = ss.main_with_payload({"cwd": str(ws), "source": "compact"})
        out = capsys.readouterr().out
        assert rc == 0
        assert "compact-continuity" in out
        assert "round-strategy.json" in out
        assert not (ws / "runs" / ".compact-continuity-note.json").exists()
        ss.main_with_payload({"cwd": str(ws), "source": "startup"})
        out2 = capsys.readouterr().out
        assert "compact-continuity" not in out2

    def test_stale_stash_not_injected(self, tmp_path, capsys):
        """A stash older than the consume window is dropped, never
        injected into an unrelated later compact."""
        import compact_continuity
        ws = _mk_session_ws(tmp_path)
        stash = ws / "runs" / ".compact-continuity-note.json"
        stash.write_text(json.dumps({
            "ts": "2026-01-01T00:00:00Z", "trigger": "auto",
            "strategy_pointer": None, "note": "old note"}),
            encoding="utf-8")
        assert compact_continuity.consume_stashed_note(ws) is None
        assert not stash.exists()  # still consumed: a stale note never
                                   # lingers to fire at a later compact
