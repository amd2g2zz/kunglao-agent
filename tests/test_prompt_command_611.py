# -*- coding: utf-8 -*-
"""tests/test_prompt_command_611.py — #611: /loop prompt must not reference
a non-existent `decision` subcommand.

RED: heartbeat_loop_prompt.py:62 emitted `python {cc} {ws} decision → …` but
convergence_check.py argparse only accepts `workspace` + `--json`. Copy-paste
errors with `unrecognized arguments: decision`. Adjudicated fix (Option A):
rewrite the line to the real invocation `--json`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import heartbeat_loop_prompt as hlp  # noqa: E402


def _prompt_text(ws: Path) -> str:
    return hlp.build_prompt(str(ws), interval="5m")


def test_prompt_does_not_reference_nonexistent_decision_subcommand(tmp_path):
    """#611: the broken `decision → imperative execution` invocation must be gone."""
    text = _prompt_text(tmp_path)
    assert "decision → imperative execution" not in text


def test_prompt_references_real_json_invocation(tmp_path):
    """The convergence step must point at the actual argparse surface (--json)."""
    text = _prompt_text(tmp_path)
    assert "convergence_check" in text
    cc_line = next(ln for ln in text.splitlines() if "convergence_check" in ln and "python" in ln)
    assert "--json" in cc_line
