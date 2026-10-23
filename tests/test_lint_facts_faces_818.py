# -*- coding: utf-8 -*-
"""tests/test_lint_facts_faces_818.py — the fact-schema lint engine's
deep branches, in the MEASURED leg (issue #818 coverage climb).

The primary pins live in fast-tier files (test_lint_facts_532,
test_lint_facts_assumptions_250) the CI measured-set coverage leg does
not execute. This file drives lint_fact / parse_frontmatter /
lint_workspace / lint_index over REAL fixture texts: every error code
is asserted from a genuinely malformed frontmatter field, never from a
mock shape.
"""
from __future__ import annotations

from pathlib import Path

from lint_facts import (  # noqa: E402  (scripts/ on pytest path)
    lint_fact,
    lint_index,
    lint_index_row,
    lint_workspace,
    parse_frontmatter,
)

IDS = {"F001", "F002"}


def _codes(fm: dict, body: str = "") -> set:
    return {code for sev, code, _msg in lint_fact("F001", fm, IDS, body)}


def _base(**over) -> dict:
    fm = {
        "id": "F001-clean", "type": "fact", "title": "the IV source",
        "created": "2026-10-01", "last_reviewed": "2026-10-02",
        "boundary_type": "confirmed", "promotion_gate": None,
        "provenance": [{"role": "public_doc", "path": "facts/F001.md",
                        "content_sha256": "a" * 64, "credibility": "B2"}],
        "claim": "the claim", "reproduce": "cmd", "expected": "out",
        "verified": "pending", "claim_id": "C-001",
        "source": "inference", "confidence": "medium",
        "status": "INFERRED", "verify_status": "pending",
    }
    fm.update(over)
    return fm


def test_clean_shape_has_no_findings() -> None:
    assert _codes(_base()) == set()


# ---------- identity + dates ----------

def test_bad_id_shapes() -> None:
    assert "BAD_FACT_ID" in _codes(_base(id="X1-clean"))
    assert "BAD_ID_NO_SLUG" in _codes(_base(id="F001"))


def test_bad_and_backdated_dates() -> None:
    assert "BAD_DATE" in _codes(_base(created="2026/01/02"))
    assert "BACKDATED" in _codes(
        _base(created="2026-10-05", last_reviewed="2026-10-01"))


def test_status_source_confidence_matrix() -> None:
    assert "BAD_STATUS" in _codes(_base(status="STAMP"))
    assert "BAD_SOURCE_ENUM" in _codes(_base(source="vibes"))
    assert "BAD_CONFIDENCE" in _codes(_base(confidence="certain"))
    assert "ILLEGAL_SOURCE_FOR_STATUS" in _codes(
        _base(status="PROVEN", source="inference", confidence="high"))
    assert "ILLEGAL_CONFIDENCE_FOR_STATUS" in _codes(
        _base(status="INFERRED", confidence="high"))
    assert "BAD_CLAIM_ID" in _codes(_base(claim_id="claim-1"))


# ---------- boundary + promotion gate ----------

def test_boundary_and_promotion_gate_contract() -> None:
    assert "BAD_BOUNDARY_TYPE" in _codes(_base(boundary_type="vibes"))
    assert "EMPTY_PROMOTION_GATE" in _codes(
        _base(boundary_type="observation", promotion_gate=None))
    assert "NONEMPTY_PROMOTION_GATE" in _codes(
        _base(boundary_type="confirmed", promotion_gate="must pass x"))
    codes = _codes(_base(boundary_type="pure_negative"))
    assert "PURE_NEG_STATUS" in codes
    assert "PURE_NEG_CONFIDENCE" in _codes(
        _base(boundary_type="pure_negative", status="NEGATIVE",
              confidence_zh="可确认"))


def test_confidence_zh_mapping() -> None:
    assert "BAD_CONFIDENCE_ZH" in _codes(_base(confidence_zh="大概是"))
    assert "CONFIDENCE_ZH_MISMATCH" in _codes(
        _base(confidence_zh="可确认"))       # medium is not 可确认-legal
    assert "CONFIDENCE_ZH_MISMATCH" in _codes(
        _base(source="static-decompile", confidence="high",
              status="INFERRED", confidence_zh="可确认"))


# ---------- provenance rows ----------

def test_provenance_row_shapes() -> None:
    assert "MISSING_PROVENANCE" in _codes(_base(provenance=None))
    assert "BAD_PROVENANCE" in _codes(_base(provenance=["not-a-dict"]))
    assert "BAD_PROVENANCE" in _codes(_base(provenance=[{}]))
    assert "UNKNOWN_PROVENANCE_ROLE" in _codes(
        _base(provenance=[{"role": "vibes", "path": "p"}]))
    row = lambda **over: {  # noqa: E731
        "role": "public_doc", "path": "facts/F001.md",
        "content_sha256": "a" * 64, "credibility": "B2", **over}
    no_sha = row()
    del no_sha["content_sha256"]
    assert "PROVENANCE_NO_CONTENT_SHA256" in _codes(
        _base(provenance=[no_sha]))
    assert "BAD_CONTENT_SHA256" in _codes(
        _base(provenance=[row(content_sha256=None)]))
    assert "BAD_CONTENT_SHA256" in _codes(
        _base(provenance=[row(content_sha256="xyz")]))
    no_cred = row()
    del no_cred["credibility"]
    assert "PROVENANCE_NO_CREDIBILITY" in _codes(
        _base(provenance=[no_cred]))
    assert "BAD_CREDIBILITY" in _codes(
        _base(provenance=[row(credibility="Z9")]))
    # a None rides str() -> the malformed-shape face (as-found)
    assert "BAD_CREDIBILITY" in _codes(
        _base(provenance=[row(credibility=None)]))
    assert "RECOMPUTE_NOT_UNDER_TOOLS" in _codes(
        _base(provenance=[row(role="recompute_script", path="misc/x.py")]))


# ---------- verify_status + edges + ach ----------

def test_verify_status_faces() -> None:
    assert "BAD_VERIFY_STATUS" in _codes(_base(verify_status="soon"))
    assert "VERIFY_STATUS_ABSENT" in _codes(_base(verify_status=None))
    assert "VERIFY_STATUS_STATUS_DRIFT" in _codes(
        _base(verify_status="fails"))


def test_dependency_alternatives_assumptions_and_probes() -> None:
    assert "MISSING_DEPENDENCY" in _codes(_base(depends_on=["F999"]))
    assert "BAD_ALTERNATIVES" in _codes(_base(alternatives="nope"))
    assert "BAD_ALTERNATIVES" in _codes(
        _base(alternatives=[{"hypothesis": "h"}]))   # no rejected_because
    assert "BAD_ASSUMPTIONS" in _codes(_base(assumptions="nope"))
    codes = _codes(_base(assumptions=["keyed=polarity", "no key here"]))
    assert "ASSUMPTION_UNKEYED" in codes
    assert "BAD_UNCERTAINTY" in _codes(_base(uncertainty="   "))
    assert "BAD_NEXT_PROBE" in _codes(_base(next_probe=3))


def test_observation_world_blur() -> None:
    fm = _base(source="frida-capture",
               title="hook output shows no callers for func_a")
    assert "OBSERVATION_WORLD_BLUR" in _codes(fm)
    ok = _base(source="frida-capture",
               title="hook output shows no callers for func_a "
                     "(frida trace scope)")
    assert "OBSERVATION_WORLD_BLUR" not in _codes(ok)


# ---------- parse_frontmatter faces ----------

def test_parse_frontmatter_faces() -> None:
    fm, body, err = parse_frontmatter("---\nid: F001\n---\nbody here\n")
    assert err is None and fm["id"] == "F001" and "body here" in body
    fm, body, err = parse_frontmatter("no frontmatter at all\n")
    assert fm == {} and err == "no-frontmatter"
    fm, body, err = parse_frontmatter("---\nid: F001\nbody\n")
    assert err == "no-closing-fence"
    fm, body, err = parse_frontmatter("---\n]]]: ]]]\n---\nb\n")
    assert err and "yaml" in err.lower()


# ---------- workspace faces ----------

def test_lint_workspace_faces(tmp_path: Path) -> None:
    errs, _warns = lint_workspace(tmp_path / "void")
    assert errs and "NO_FACTS_DIR" in errs[0][1]
    facts = tmp_path / "facts"
    facts.mkdir()
    (facts / "F999.md").write_text("plain prose, no frontmatter\n",
                                   encoding="utf-8")
    errs, _w = lint_workspace(tmp_path)
    assert any("NO_FRONTMATTER" in code for _s, code, _msg in errs)
    # duplicate ids across two files
    text = ("---\nid: F010-dup\ntype: fact\n---\nb\n")
    (facts / "F010.md").write_text(text, encoding="utf-8")
    (facts / "F011.md").write_text(text, encoding="utf-8")
    (facts / "_INDEX.md").write_text(
        "| fact | status | claim | conclusion |\n"
        "|---|---|---|---|\n"
        "F010 | PROVEN | C-001 | fine |\n", encoding="utf-8")
    errs, _w = lint_workspace(tmp_path)
    assert any("DUPLICATE_ID" in code for _s, code, _msg in errs)


# ---------- index rows ----------

def test_lint_index_row_and_file(tmp_path: Path) -> None:
    codes = lambda rows: {c for _s, c, _m in rows}  # noqa: E731
    assert "BAD_INDEX_SHAPE" in codes(
        lint_index_row("only | two | cols", 3))
    assert "BAD_INDEX_FACT_ID" in codes(
        lint_index_row("|  | PROVEN | C-001 | concl |", 4))
    assert "BAD_INDEX_STATUS" in codes(
        lint_index_row("F010 | VIBES | C-001 | concl |", 5))
    assert "BAD_INDEX_CLAIM_ID" in codes(
        lint_index_row("F010 | PROVEN | claim-9 | concl |", 6))
    ok = lint_index_row("F010 | PROVEN | C-001 | concl with | pipe", 7)
    assert ok == []
    idx = tmp_path / "_INDEX.md"
    idx.write_text(
        "# header comment\n"
        "| fact | status | claim | conclusion |\n"
        "|---|---|---|---|\n"
        "\n"
        "F010 | PROVEN | C-001 | fine |\n"
        "F011 | BAD | C-001 | drift |\n", encoding="utf-8")
    issues = lint_index(idx)
    assert len(issues) == 1
    assert "BAD_INDEX_STATUS" in issues[0][1]
    assert ":6:" in issues[0][2]
