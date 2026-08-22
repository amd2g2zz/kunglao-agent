# -*- coding: utf-8 -*-
"""Frontmatter contract tests for the trigger_precision block (#525).

Every lesson that enters the library MUST carry trigger_precision with all
four sub-fields populated (tool, error_signature, family, unit). These
tests pin the contract independently of aggregate_lessons: the gate is
about WHAT a lesson file looks like on disk, not HOW it gets there.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402


def _write_register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _claim(cid: str, attempts: int = 3) -> dict:
    return {"id": cid, "status": "OPEN", "boundary_type": "positive_observation",
            "evidence_tier_attempted": 1, "promotion_attempts": attempts,
            "depends_on": [], "statement": f"topic {cid}"}


def _record(ws, cid, *, tp):
    import failure_analysis_gate as fag  # noqa: E402
    return fag.record_analysis(
        ws, cid,
        assumption="a", validity="not-justified",
        next_method="runtime hook",
        outcome="PROVEN", what_happened="ok",
        validated_capability="x", identified_obstacle="y",
        source="lesson-hit",
        trigger_precision=tp)


def _fm(path: Path) -> dict:
    parts = path.read_text(encoding="utf-8").split("---", 2)
    return yaml.safe_load(parts[1])


def _aggregate(ws, lib, q):
    import failure_analysis_gate as fag  # noqa: E402
    return fag.aggregate_lessons(ws, library=lib, reflect_queue=q)


# ---------- write-gate: required fields ----------

def test_frontmatter_has_all_four_precision_subfields(tmp_path):
    """When the analysis carries a complete trigger_precision, the lesson
    file's frontmatter mirrors all four sub-fields verbatim."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1")])
    _record(ws, "C-1", tp={
        "tool": "ghidra.decompile",
        "error_signature": "Cannot LE",
        "family": "ghidra.script",
        "unit": "function",
    })
    lib = tmp_path / "lib"
    res = _aggregate(ws, lib, tmp_path / "q.json")

    assert res["lessons_written"] == 1
    files = list(lib.glob("lesson-*.md"))
    fm = _fm(files[0])
    tp = fm["trigger_precision"]
    assert tp["tool"] == "ghidra.decompile"
    assert tp["error_signature"] == "Cannot LE"
    assert tp["family"] == "ghidra.script"
    assert tp["unit"] == "function"


def test_frontmatter_default_stage_is_draft(tmp_path):
    """Every freshly-written lesson starts at stage=draft (nursery model)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-2")])
    _record(ws, "C-2", tp={
        "tool": "x", "error_signature": "y", "family": "z", "unit": "attempt",
    })
    lib = tmp_path / "lib"
    _aggregate(ws, lib, tmp_path / "q.json")
    fm = _fm(next(lib.glob("lesson-*.md")))
    assert fm["stage"] == "draft"


# ---------- lint: missing precision sub-fields ----------

def test_missing_tool_field_blocks_write(tmp_path):
    """tool is one of the four required sub-fields; omit it and the
    aggregate layer rejects the entry."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-3")])
    _record(ws, "C-3", tp={
        "error_signature": "y", "family": "z", "unit": "attempt",  # no tool
    })
    lib = tmp_path / "lib"
    res = _aggregate(ws, lib, tmp_path / "q.json")

    assert res["lessons_written"] == 0
    assert list(lib.glob("lesson-*.md")) == []


def test_missing_unit_field_blocks_write(tmp_path):
    """unit is the numeric scope per #525's global numeric-fidelity rule."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-4")])
    _record(ws, "C-4", tp={
        "tool": "x", "error_signature": "y", "family": "z",  # no unit
    })
    lib = tmp_path / "lib"
    res = _aggregate(ws, lib, tmp_path / "q.json")

    assert res["lessons_written"] == 0


def test_empty_string_in_precision_blocks_write(tmp_path):
    """Empty strings count as missing — a present-but-empty field is the
    same gate failure as omission."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-5")])
    _record(ws, "C-5", tp={
        "tool": "x", "error_signature": "  ", "family": "z", "unit": "attempt",
    })
    lib = tmp_path / "lib"
    res = _aggregate(ws, lib, tmp_path / "q.json")

    assert res["lessons_written"] == 0


def test_promoted_lesson_keeps_precision(tmp_path):
    """promote_lesson must not drop the precision block; the gate that
    protects active-stage injection depends on it being intact."""
    import failure_analysis_gate as fag  # noqa: E402
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-6")])
    _record(ws, "C-6", tp={
        "tool": "frida.attach", "error_signature": "ENOENT",
        "family": "process.attach", "unit": "attempt",
    })
    lib = tmp_path / "lib"
    _aggregate(ws, lib, tmp_path / "q.json")
    lesson = next(lib.glob("lesson-*.md"))

    fag.promote_lesson(lesson, workspace=ws, promoted_by="kunglao-verify",
                       evidence="L1 reproduce #42")

    fm = _fm(lesson)
    assert fm["stage"] == "active"
    assert fm["trigger_precision"]["tool"] == "frida.attach"
    assert fm["trigger_precision"]["error_signature"] == "ENOENT"
    assert fm["trigger_precision"]["family"] == "process.attach"
    assert fm["trigger_precision"]["unit"] == "attempt"