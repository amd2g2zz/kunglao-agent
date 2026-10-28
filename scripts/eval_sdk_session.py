#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/eval_sdk_session.py — the Claude Agent SDK session face.

The runner's session seam (--session-cmd) drives this driver INSTEAD of
`claude -p`: same launch contract (the prompt travels as the single
positional; the cwd IS the workspace; exactly ONE stdout JSON line with
total_cost_usd at the end; rc 0 on completion) plus what print-mode
cannot give the #816 re-run:

  - MESSAGE-LEVEL OBSERVABILITY: every tool use is counted live; the
    dispatch count (Agent/Task tool uses) and the full tool census land
    in sdk-session.json in the workspace — the zero-dispatch diagnosis
    that took transcript archaeology on the first run becomes a
    harvested artifact.
  - SOLO-CAP ENFORCEMENT: past KUNGLAO_SOLO_CAP_S seconds with zero
    dispatches, every subsequent non-dispatch tool result is replaced
    with an escalating contract reminder (decision=block + reason) —
    the tooth the WALL_BUDGET_PARTITION text lacked on the first run,
    where the orchestrator quoted the solo cap and then overran it.

Env:
  KUNGLAO_SDK_PLUGIN_DIR  plugin dir (default: the repo root this
                          script lives in)
  KUNGLAO_SDK_BUDGET_USD  native engine-side USD cap (the runner's
                          session-cmd seam does not add CLI budget
                          flags, so the driver owns this face)
  KUNGLAO_SOLO_CAP_S      solo-cap enforcement seconds (0/absent = off)
  KUNGLAO_SDK_MAX_TURNS   optional max_turns cap

stdlib + claude-agent-sdk only.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import claude_agent_sdk as sdk

DISPATCH_TOOLS = {"Agent", "Task"}
REPO_ROOT = Path(__file__).resolve().parents[1]

ESCALATION_LEVELS = 3


def solo_escalation(elapsed_s: float, cap_s: float, level: int) -> str:
    """The reason injected into a non-dispatch tool result once the solo
    window is gone: level 0 is contractual, 1 a second notice, 2+ the
    hard reminder — the model demonstrably reads this block, so the
    reminder re-states exactly what the run measures."""
    level = min(max(level, 0), ESCALATION_LEVELS - 1)
    over = int(elapsed_s - cap_s)
    if level <= 0:
        return (f"SOLO CAP EXCEEDED ({int(elapsed_s)}s > {int(cap_s)}s): "
                "the WALL_BUDGET_PARTITION contract requires a worker "
                "dispatch NOW. Stop solo work and dispatch a kunglao "
                "worker via the Agent tool with the current GAP attached.")
    if level == 1:
        return (f"SECOND NOTICE: still no dispatch {int(elapsed_s)}s into "
                f"a {int(cap_s)}s solo cap. Your next action MUST be a "
                "dispatch via the Agent tool. Solo-only output is not "
                "what this run measures; the orchestrated loop is.")
    return (f"HARD REMINDER: the solo window closed {over}s ago. Dispatch "
            "a worker via the Agent tool immediately — every further "
            "non-dispatch step escalates this notice.")


class SessionState:
    """Live census: tool uses, dispatch count, solo-cap escalations."""

    def __init__(self, solo_cap_s: float = 0.0) -> None:
        self.started = time.monotonic()
        self.solo_cap_s = solo_cap_s
        self.tool_census: dict[str, int] = {}
        self.dispatch_count = 0
        self.escalations = 0

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def record(self, tool_name: str) -> None:
        if not tool_name:
            return
        self.tool_census[tool_name] = self.tool_census.get(tool_name, 0) + 1
        if tool_name in DISPATCH_TOOLS:
            self.dispatch_count += 1

    def solo_due(self) -> bool:
        return (self.solo_cap_s > 0 and self.dispatch_count == 0
                and self.elapsed() > self.solo_cap_s)

    def forensics(self) -> dict:
        return {
            "schema": "sdk-session/1",
            "wall_s": round(self.elapsed(), 3),
            "solo_cap_s": self.solo_cap_s,
            "tool_census": self.tool_census,
            "dispatch_count": self.dispatch_count,
            "escalations": self.escalations,
        }


def make_post_tool_use_hook(state: SessionState):
    """PostToolUse over every tool: record the census, and past the solo
    cap (still zero dispatches) replace the tool result the model sees
    with the escalating dispatch reminder."""

    async def hook(input_data, tool_use_id=None, context=None):
        state.record(input_data.get("tool_name") or "")
        # the runner's wall-cap SIGKILL cannot be trapped — flush the
        # forensics periodically so a killed session still leaves its
        # census behind
        if state.tool_census and sum(state.tool_census.values()) % 25 == 0:
            _flush_forensics(state, "")
        if state.solo_due():
            reason = solo_escalation(
                state.elapsed(), state.solo_cap_s, state.escalations)
            state.escalations += 1
            return {"decision": "block", "reason": reason}
        return {}

    return hook


def build_options(state: SessionState) -> sdk.ClaudeAgentOptions:
    plugin_dir = os.environ.get(
        "KUNGLAO_SDK_PLUGIN_DIR") or str(REPO_ROOT)
    budget = os.environ.get("KUNGLAO_SDK_BUDGET_USD") or ""
    max_turns = os.environ.get("KUNGLAO_SDK_MAX_TURNS") or ""
    return sdk.ClaudeAgentOptions(
        cwd=os.getcwd(),
        permission_mode="bypassPermissions",
        plugins=[{"type": "local", "path": plugin_dir}],
        max_budget_usd=float(budget) if budget else None,
        max_turns=int(max_turns) if max_turns else None,
        hooks={"PostToolUse": [sdk.HookMatcher(hooks=[
            make_post_tool_use_hook(state)])]},
    )


async def run_session(prompt: str, options: sdk.ClaudeAgentOptions,
                      state: SessionState) -> tuple[str, dict]:
    """Stream the session; return (final result text, cost doc).

    Counting lives in the PostToolUse hook ALONE: in a live SDK run the
    hook fires once per tool execution AND the message stream carries
    the same tool_use block — recording in both would double every
    census entry (and the wall-cap SIGKILL is uncatchable, so the hook
    also flushes forensics periodically instead of only at exit)."""
    result_text = ""
    cost: dict = {}
    async for msg in sdk.query(prompt=prompt, options=options):
        if isinstance(msg, sdk.ResultMessage):
            result_text = getattr(msg, "result", "") or ""
            usage = getattr(msg, "usage", None) or {}
            cost = {
                "total_cost_usd": getattr(msg, "total_cost_usd", None),
                "usage": {
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                },
            }
    return result_text, cost


def _flush_forensics(state: "SessionState", result_head: str) -> None:
    try:
        Path.cwd().joinpath("sdk-session.json").write_text(
            json.dumps({**state.forensics(),
                        "result_head": result_head}), encoding="utf-8")
    except OSError as exc:
        print(f"[sdk-session] forensics flush failed: {exc}",
              file=sys.stderr)  # loud but never session-breaking


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print("usage: eval_sdk_session.py '<prompt>'", file=sys.stderr)
        return 2
    prompt = args[-1]
    state = SessionState(
        solo_cap_s=float(os.environ.get("KUNGLAO_SOLO_CAP_S") or 0))
    options = build_options(state)
    try:
        result_text, cost = asyncio.run(run_session(prompt, options, state))
    except Exception as exc:  # loud, never a silent zero-spend row
        print(f"sdk session failed: {exc}", file=sys.stderr)
        return 1
    _flush_forensics(state, result_text[:500])
    print(json.dumps(cost))
    return 0


if __name__ == "__main__":
    sys.exit(main())
