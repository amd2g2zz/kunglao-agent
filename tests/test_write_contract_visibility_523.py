# -*- coding: utf-8 -*-
"""Issue #523 — the write contracts reach the session before the guards
refuse (the smoke pilot's third visibility gap).

Pilot evidence (runs/exp-cc-rl/smoke-kunglao-1usd): the model DID enter
the loop late (~150s in) and was refused at every write face —
facts/F001.md 16 lint violations (no id/type), F004.md twice, claim-
register direct Bash writes twice — burning the remaining wall on
refusals whose contracts nothing had shown it up front. The completion
contract (PR #536) fixed the operationalization gap; these pins hold
the write-contract half: both always-in-context faces name the fact
frontmatter and the single-writer path.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import heartbeat_loop_prompt as hlp  # noqa: E402

TEMPLATE = ROOT / "templates" / "CLAUDE.md.base.tmpl"


def test_constitution_names_the_write_contracts(tmp_path):
    text = hlp.constitution(str(tmp_path))
    assert "WRITE CONTRACTS" in text
    assert "type: fact" in text
    assert "ws_yaml.py set|del" in text
    assert "#516" in text


def test_template_names_the_write_contracts():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "type: fact" in text
    assert "ws_yaml.py" in text
    assert "single-writer" in text
