# -*- coding: utf-8 -*-
"""tests/test_eval_sdk_session.py — the Claude Agent SDK session face.

The driver (scripts/eval_sdk_session.py) is the runner's --session-cmd
face for the #816 re-run: same launch contract as `claude -p` (prompt as
the single positional, cwd IS the workspace, ONE stdout JSON cost line)
plus message-level observability and solo-cap enforcement. Faces pinned:

  (a) ESCALATION — the solo-cap reason ladder (contractual → second
      notice → hard reminder, clamped), the exact contract language the
      live session proved it reads;
  (b) CENSUS — SessionState records tool uses, counts Agent/Task
      dispatches, and flips solo_due exactly at cap with zero
      dispatches;
  (c) HOOK — the PostToolUse hook passes clean results through,
      replaces non-dispatch results past the solo cap with the
      escalating block reason, and stands down once a dispatch lands;
  (d) RUN/MAIN — a fake sdk.query stream yields the census + the cost
      doc; the stdout line parses through the runner's OWN
      _session_cost parser (the launch-contract round trip); the
      sdk-session.json forensics land in the workspace cwd.

No live model face: sdk.query is faked at the seam (the driver is a
thin adapter; the real face is exercised only in the live re-run).
"""
from __future__ import annotations

import asyncio
import json

import pytest

import eval_loop_runner as lr  # noqa: E402

# optional-dep convention (the tomli backfill pattern): stale side-venvs
# without claude-agent-sdk skip instead of erroring collection — CI and
# the dev env declare the SDK in [project].dependencies and run for real
pytest.importorskip("claude_agent_sdk",
                    reason="claude-agent-sdk not in this env")

import eval_sdk_session as es  # noqa: E402
import claude_agent_sdk as sdk  # noqa: E402

from claude_agent_sdk import (  # noqa: E402
    AssistantMessage, ResultMessage, ToolUseBlock)


# ---------------------------------------------------------------- fixtures

def _assistant(*tools: str) -> AssistantMessage:
    return AssistantMessage(
        content=[ToolUseBlock(name=n, id=f"t{i}", input={})
                 for i, n in enumerate(tools)],
        model="test-model")


def _result(cost: float | None = 1.25) -> ResultMessage:
    return ResultMessage(
        subtype="success", duration_ms=1, duration_api_ms=1,
        is_error=False, num_turns=1, session_id="s",
        total_cost_usd=cost,
        usage={"input_tokens": 10, "output_tokens": 20},
        result="done")


@pytest.fixture()
def fake_query(monkeypatch):
    """Fake the sdk seam: yields the given messages for any prompt."""
    def install(messages):
        async def _gen(prompt, options=None):
            for m in messages:
                yield m
        monkeypatch.setattr(sdk, "query", _gen)
    return install


# ------------------------------------------------------------------- (a)

class TestSoloEscalation:
    def test_ladder_levels_are_distinct_and_clamped(self):
        l0 = es.solo_escalation(900.0, 810.0, 0)
        l1 = es.solo_escalation(1200.0, 810.0, 1)
        l2 = es.solo_escalation(1500.0, 810.0, 2)
        assert "SOLO CAP EXCEEDED (900s > 810s)" in l0
        assert "SECOND NOTICE" in l1 and "via the Agent tool" in l1
        assert "HARD REMINDER" in l2 and "closed " in l2
        # clamped: beyond the ladder it stays the hard reminder
        assert es.solo_escalation(1500.0, 810.0, 99) == l2

    def test_names_the_dispatch_requirement(self):
        for lvl in range(3):
            text = es.solo_escalation(1000.0, 810.0, lvl)
            assert "dispatch" in text.lower()
            assert "Agent tool" in text


# ------------------------------------------------------------------- (b)

class TestSessionState:
    def test_census_counts_dispatches(self):
        st = es.SessionState()
        st.record("Bash")
        st.record("Bash")
        st.record("Agent")
        assert st.tool_census == {"Bash": 2, "Agent": 1}
        assert st.dispatch_count == 1

    def test_empty_tool_name_is_not_censused(self):
        st = es.SessionState()
        st.record("")
        assert st.tool_census == {}
        assert st.dispatch_count == 0

    def test_solo_due_flips_exactly_at_cap_with_zero_dispatches(self):
        import time
        st = es.SessionState(solo_cap_s=0.0)
        assert st.solo_due() is False, "cap 0 means enforcement off"
        st2 = es.SessionState(solo_cap_s=0.05)
        time.sleep(0.06)
        assert st2.solo_due() is True
        st2.record("Agent")
        assert st2.solo_due() is False, "one dispatch stands the cap down"


# ------------------------------------------------------------------- (c)

class TestPostToolUseHook:
    def _hook(self, solo_cap_s=0.0):
        st = es.SessionState(solo_cap_s=solo_cap_s)
        return es.make_post_tool_use_hook(st), st

    def test_clean_pass_through_without_cap(self):
        hook, st = self._hook(0.0)
        out = asyncio.run(hook({"tool_name": "Bash"}))
        assert out == {}
        assert st.tool_census == {"Bash": 1}

    def test_past_cap_non_dispatch_tool_is_blocked_escalating(self):
        import time
        hook, st = self._hook(solo_cap_s=0.05)
        time.sleep(0.06)
        first = asyncio.run(hook({"tool_name": "Bash"}))
        assert first.get("decision") == "block"
        assert "SOLO CAP EXCEEDED" in first["reason"]
        second = asyncio.run(hook({"tool_name": "Read"}))
        assert "SECOND NOTICE" in second["reason"]
        assert st.escalations == 2

    def test_dispatch_stands_down_the_enforcement(self):
        import time
        hook, st = self._hook(solo_cap_s=0.05)
        time.sleep(0.06)
        blocked = asyncio.run(hook({"tool_name": "Bash"}))
        assert blocked.get("decision") == "block"
        clean = asyncio.run(hook({"tool_name": "Agent"}))
        assert clean == {}
        after = asyncio.run(hook({"tool_name": "Bash"}))
        assert after == {}, "enforcement stops once the loop is engaged"


# ------------------------------------------------------------------- (d)

class TestRunAndMain:
    def test_run_session_counts_and_parses_through_the_runner(self,
                                                              fake_query,
                                                              tmp_path,
                                                              monkeypatch):
        fake_query([_assistant("Bash", "Agent"), _result(1.25)])
        monkeypatch.chdir(tmp_path)
        st = es.SessionState()
        text, cost = asyncio.run(es.run_session(
            "PROMPT", sdk.ClaudeAgentOptions(cwd=str(tmp_path)), st))
        assert text == "done"
        assert cost["total_cost_usd"] == 1.25
        assert st.dispatch_count == 1
        # the launch-contract round trip: the runner's own parser reads
        # the driver's stdout line
        parsed = lr._session_cost(json.dumps(cost))
        assert parsed["total_cost_usd"] == 1.25
        assert parsed["input_tokens"] == 10

    def test_main_writes_forensics_and_emits_cost_line(self, fake_query,
                                                       tmp_path,
                                                       monkeypatch,
                                                       capsys):
        fake_query([_assistant("Bash"), _result(0.5)])
        monkeypatch.chdir(tmp_path)
        rc = es.main(["eval_sdk_session.py", "THE PROMPT"])
        assert rc == 0
        doc = json.loads(capsys.readouterr().out.strip())
        assert doc["total_cost_usd"] == 0.5
        forensics = json.loads(
            (tmp_path / "sdk-session.json").read_text("utf-8"))
        assert forensics["schema"] == "sdk-session/1"
        assert forensics["tool_census"] == {"Bash": 1}
        assert forensics["dispatch_count"] == 0
        assert forensics["result_head"] == "done"

    def test_main_without_prompt_refuses(self, capsys):
        assert es.main([]) == 2
        assert "usage:" in capsys.readouterr().err

    def test_main_sdk_failure_is_loud_rc1(self, monkeypatch, capsys,
                                          tmp_path):
        async def _boom(prompt, options=None):
            raise RuntimeError("engine down")
            yield  # pragma: no cover
        monkeypatch.setattr(sdk, "query", _boom)
        monkeypatch.chdir(tmp_path)
        assert es.main(["P"]) == 1
        assert "engine down" in capsys.readouterr().err
