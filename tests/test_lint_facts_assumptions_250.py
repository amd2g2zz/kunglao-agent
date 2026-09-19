# -*- coding: utf-8 -*-
"""Issue 250 — lint_facts: assumptions field + observation-vs-world wording.

Two rules added to scripts/lint_facts.py:

  - `assumptions: []` becomes a KNOWN frontmatter key (no UNKNOWN_KEY
    warning); malformed shapes error (BAD_ASSUMPTIONS); an entry without
    `topic=polarity` warns (ASSUMPTION_UNKEYED — it can never be
    semantically invalidated).
  - OBSERVATION_WORLD_BLUR (error): an observational-source fact
    (static-decompile/dynamic-trace/frida-capture/qiling-emu) whose TITLE
    asserts a world-existential ("no callers", "uncalled", ...) without a
    tool-scope qualifier — "tool X found no Y" != "no Y exists".
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import lint_facts as lf  # noqa: E402


def _fact(fm: dict, body: str = "body\n") -> Path:
    import tempfile
    import yaml
    d = Path(tempfile.mkdtemp()) / "facts"
    d.mkdir(parents=True)
    head = yaml.safe_dump(fm, sort_keys=False)
    (d / f"{fm['id']}.md").write_text(f"---\n{head}---\n\n{body}",
                                      encoding="utf-8")
    return d.parent


def _base_fm(fid: str, **over) -> dict:
    fm = {
        "id": fid, "type": "fact", "title": "neutral title",
        "status": "PROVEN", "created": "2026-09-18",
        "last_reviewed": "2026-09-18", "claim_id": "C-001",
        "boundary_type": "confirmed", "promotion_gate": "",
        "provenance": [{"role": "decompiled_c", "path": "x.c",
                        "content_sha256": "a" * 64, "credibility": "B2"}],
        "source": "static-decompile", "confidence": "high",
    }
    fm.update(over)
    return fm


def _codes(issues: list) -> set:
    return {code for _sev, code, _msg in issues}


# ---------- assumptions field ----------

def test_assumptions_is_known_key():
    errors, warnings = lf.lint_workspace(_fact(_base_fm(
        "F001-ok", assumptions=["dispatch=static"])))
    codes = {c for _s, c, _m in warnings}
    assert "UNKNOWN_KEY" not in codes
    assert not errors or all(c != "BAD_ASSUMPTIONS" for c in
                             {c for _s, c, _m in errors})


def test_assumptions_malformed_errors():
    fm = _base_fm("F002-bad", assumptions="dispatch=static")
    fm["title"] = "world title"
    errors, _warnings = lf.lint_workspace(_fact(fm))
    assert "BAD_ASSUMPTIONS" in {c for _s, c, _m in errors}


def test_assumptions_unkeyed_warns():
    errors, warnings = lf.lint_workspace(_fact(_base_fm(
        "F003-unkeyed", assumptions=["static linkage assumption"])))
    assert "ASSUMPTION_UNKEYED" in {c for _s, c, _m in warnings}
    assert "BAD_ASSUMPTIONS" not in {c for _s, c, _m in errors}


def test_assumptions_nonstring_entry_errors():
    errors, _warnings = lf.lint_workspace(_fact(_base_fm(
        "F004-mixed", assumptions=["dispatch=static", 42])))
    assert "BAD_ASSUMPTIONS" in {c for _s, c, _m in errors}


# ---------- observation-vs-world wording ----------

def test_world_existential_title_without_scope_errors():
    fm = _base_fm("F005-blur", title="No callers of sub_1234")
    errors, _w = lf.lint_workspace(_fact(fm))
    assert "OBSERVATION_WORLD_BLUR" in {c for _s, c, _m in errors}


def test_tool_scoped_title_clean():
    fm = _base_fm("F006-scoped", title="xref: no callers of sub_1234")
    errors, _w = lf.lint_workspace(_fact(fm))
    assert "OBSERVATION_WORLD_BLUR" not in {c for _s, c, _m in errors}


def test_found_by_scope_clean():
    fm = _base_fm("F007-found",
                  title="no xref callers found by static analysis")
    errors, _w = lf.lint_workspace(_fact(fm))
    assert "OBSERVATION_WORLD_BLUR" not in {c for _s, c, _m in errors}


def test_uncalled_world_title_dynamic_trace_errors():
    fm = _base_fm("F008-uncalled", title="sub_1234 is uncalled",
                  source="dynamic-trace")
    errors, _w = lf.lint_workspace(_fact(fm))
    assert "OBSERVATION_WORLD_BLUR" in {c for _s, c, _m in errors}


def test_world_title_with_dynamic_scope_clean():
    fm = _base_fm("F009-tracer",
                  title="tracer: sub_1234 uncalled in 120s window",
                  source="dynamic-trace")
    errors, _w = lf.lint_workspace(_fact(fm))
    assert "OBSERVATION_WORLD_BLUR" not in {c for _s, c, _m in errors}


def test_non_observational_source_not_checked():
    fm = _base_fm("F010-osint", title="No callers of sub_1234",
                  source="public-osint")
    errors, _w = lf.lint_workspace(_fact(fm))
    assert "OBSERVATION_WORLD_BLUR" not in {c for _s, c, _m in errors}


def test_neutral_title_clean():
    errors, _w = lf.lint_workspace(_fact(_base_fm("F011-neutral")))
    assert "OBSERVATION_WORLD_BLUR" not in {c for _s, c, _m in errors}
