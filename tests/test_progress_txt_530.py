# -*- coding: utf-8 -*-
"""tests/test_progress_txt_530.py — issue #530 disposition lock:
progress.txt downgraded from machine memory to human log.

The contract split: SKILL.md / cold-start-contract.md framed progress.txt
as core structured external memory, but the machine consumers refuse it as
a state source (hooks/state_anchor.py:251 and scripts/external_kicker.py:644
"NEVER reads progress.txt"; digest_build.py carries only a mechanical
3-line tail). The drift caused agents to write analysis into it expecting
semantic ingestion that never happens.

These anchors prevent silent re-promotion to a machine memory contract.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_MD = ROOT / "skills" / "kunglao-agent" / "SKILL.md"
COLD_START = ROOT / "references" / "cold-start-contract.md"


def _external_memory_line(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("**External memory**"):
            return line
    return ""


def test_progress_txt_not_presented_as_structured_machine_memory():
    """The cold-start 8-file read must not frame progress.txt as a
    structured machine segment source (that role belongs to
    analysis_state.txt)."""
    text = COLD_START.read_text(encoding="utf-8")
    for bad in (
        "**`progress.txt`** — structured sections",
        "progress.txt** — structured sections: VERIFIED-FACTS LEDGER",
    ):
        assert bad.lower() not in text.lower(), (
            f"cold-start-contract.md still frames progress.txt as structured "
            f"machine memory: {bad!r}"
        )


def test_skill_md_external_memory_line_demotes_progress_txt():
    """SKILL.md's External memory line must qualify progress.txt as a
    human/narrative log, not a peer machine state file."""
    text = SKILL_MD.read_text(encoding="utf-8")
    line = _external_memory_line(text)
    assert line, "SKILL.md External memory line not found"
    if "progress.txt" in line:
        idx = line.index("progress.txt")
        window = line[max(0, idx - 60): idx + 100].lower()
        assert any(
            qualifier in window
            for qualifier in ("human", "narrative", "log", "log only", "not machine")
        ), (
            "SKILL.md External memory line lists progress.txt without a "
            "human/narrative/log qualifier — downgrade or remove it"
        )


def test_progress_txt_never_marked_machine_ingested():
    """No skill contract may claim machine/semantic ingestion of
    progress.txt (the false-completion trap mention is fine — it says
    writing it does NOT change state)."""
    text = SKILL_MD.read_text(encoding="utf-8")
    for bad in (
        "progress.txt 自动读取",
        "machine-ingested progress.txt",
        "progress.txt (machine",
    ):
        assert bad.lower() not in text.lower(), (
            f"SKILL.md claims machine ingestion of progress.txt: {bad!r}"
        )
