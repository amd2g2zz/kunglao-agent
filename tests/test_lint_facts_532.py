# -*- coding: utf-8 -*-
"""Issue #532 items 2/6 — lint_facts gains claim-existence lookback, plural
claim-reference collection, an _INDEX row linter, and four schema extensions.

RED contract (dev baseline, 2026-08-20): lint_facts validated a single
`claim_id` against CLAIM_ID_RE and never opened claim-register.yaml, so the
external-user dump's `claim_ids: [C-001, q1]` passed clean (L-1). There was
no _INDEX linter at all, so the drifted status column parsed as
"endpoints-and-auth (login path)" (L-2/W-4).

Adaptation note (2026-08-21): the plan's minimal 7-key fixtures are stale —
HEAD's lint_facts (#336) enforces the FULL ICD-203 matrix, so every fixture
here uses the real migrated shape (type/title/created/provenance/extension
layer) and asserts only the #532 codes, keeping the GREEN/RED signal on the
new checks rather than on pre-existing mandatory-field errors.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import lint_facts  # noqa: E402
import update_index  # noqa: E402

_SHA = "b" * 64


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "notes").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-001\n"
        "    status: OPEN\n"
        "    statement: imports resolved at runtime\n",
        encoding="utf-8")
    return ws


def _fact_fm(fid: str, **extra) -> str:
    """A schema-legal frontmatter block (the migrated #336 shape)."""
    fm = {
        "id": fid,
        "type": "fact",
        "title": f"{fid} title",
        "status": "INFERRED",
        "created": "2026-08-20",
        "last_reviewed": "2026-08-20",
        "claim_id": "C-001",
        "claim": "imports resolved at runtime",
        "boundary_type": "observation",
        "promotion_gate": "resolve the loader stub under dynamic-trace",
        "source": "static-decompile",
        "confidence": "medium",
        "verify_status": "partial",
        "reproduce": "python runs/verify.py",
        "expected": _SHA,
        "verified": "pending",
        "provenance": [
            {"role": "decompiled_c", "path": "evidence/x.c",
             "content_sha256": _SHA, "credibility": "B2"},
        ],
    }
    fm.update(extra)
    lines = []
    for k, v in fm.items():
        if k == "provenance":
            lines.append("provenance:")
            for entry in v:
                cells = ", ".join(f"{ek}: {ev}" for ek, ev in entry.items())
                lines.append(f"  - {{{cells}}}")
        elif isinstance(v, list):
            lines.append(f"{k}: [{', '.join(map(str, v))}]")
        else:
            lines.append(f"{k}: {v}")
    return "\n".join(lines) + "\n"


def _fact(ws: Path, name: str, frontmatter: str,
          body: str = "\n## Status\nINFERRED\n") -> None:
    (ws / "facts" / name).write_text(f"---\n{frontmatter}---\n{body}",
                                     encoding="utf-8")


def _codes(items) -> set[str]:
    return {code for _sev, code, _msg in items}


def _errs_of(ws: Path):
    errors, _warnings = lint_facts.lint_workspace(ws)
    return errors


# ---------- L-1: claim existence is checked against the register ----------

def test_ghost_claim_id_is_an_error(tmp_path):
    ws = _ws(tmp_path)
    _fact(ws, "F001-x.md", _fact_fm("F001-x", claim_id="C-999"))
    assert "GHOST_CLAIM" in _codes(_errs_of(ws)), (
        f"L-1: C-999 is absent from claim-register.yaml and must be an "
        f"error; got {_codes(_errs_of(ws))}")


def test_plural_claim_ids_field_is_collected(tmp_path):
    """The live dump used `claim_ids: [C-001, q1]` — a plural alias the
    single-value regex never saw."""
    ws = _ws(tmp_path)
    fm = _fact_fm("F002-x")
    fm = fm.replace("claim_id: C-001\n", "claim_ids: [C-001, q1]\n")
    _fact(ws, "F002-x.md", fm)
    codes = _codes(_errs_of(ws))
    assert "GHOST_CLAIM" in codes or "BAD_CLAIM_ID" in codes, (
        f"L-1: `q1` in a plural claim field must be caught; got {codes}")


def test_existing_claim_passes(tmp_path):
    ws = _ws(tmp_path)
    _fact(ws, "F003-x.md", _fact_fm("F003-x"))
    assert "GHOST_CLAIM" not in _codes(_errs_of(ws))


def test_no_register_degrades_to_warning_not_error(tmp_path):
    """A workspace with no register (pre-init / partial scaffold) must not
    turn every fact into a GHOST_CLAIM error."""
    ws = _ws(tmp_path)
    (ws / "claim-register.yaml").unlink()
    _fact(ws, "F004-x.md", _fact_fm("F004-x"))
    errors, warnings = lint_facts.lint_workspace(ws)
    assert "GHOST_CLAIM" not in _codes(errors)
    assert "NO_REGISTER" in _codes(warnings)


# ---------- L-2 / W-4: the _INDEX row linter ----------

@pytest.mark.parametrize("row,ok", [
    ("| F001-x | PROVEN | C-001 | imports resolved at runtime |", True),
    ("F001-x | PROVEN | C-001 | imports resolved at runtime", True),
    ("F001-x | PARTIALLY-VERIFIED | C-001 | migrated workflow word", True),
    ("| F001-x | endpoints-and-auth (login path) | C-001 | x |", False),
    ("| F001-x | PROVEN | C-001 |", False),
    ("| | PROVEN | C-001 | x |", False),
    ("F001-x | PROVEN | q1 | ghost claim", False),
])
def test_index_row_shape(row, ok):
    issues = lint_facts.lint_index_row(row, lineno=9)
    assert (issues == []) is ok, f"row {row!r} -> {issues}"


def test_index_pipe_inside_conclusion_is_not_a_split(tmp_path):
    """#538 single-schema rule: the conclusion column may contain ' | ' —
    parsers join, not split. An escaped pipe is not a separator either."""
    row = "F001-x | PROVEN | C-001 | endpoints | and auth paths"
    assert lint_facts.lint_index_row(row, lineno=1) == []
    escaped = "F002-x | PROVEN | C-001 | a \\| b"
    assert lint_facts.lint_index_row(escaped, lineno=2) == []


def test_lint_index_flags_status_column_drift(tmp_path):
    ws = _ws(tmp_path)
    (ws / "facts" / "_INDEX.md").write_text(
        "| Fact | Status | Claim | Conclusion |\n"
        "|---|---|---|---|\n"
        "| F001-x | endpoints-and-auth (login path) | C-001 | drifted |\n",
        encoding="utf-8")
    issues = lint_facts.lint_index(ws / "facts" / "_INDEX.md")
    assert any(code == "BAD_INDEX_STATUS" for _s, code, _m in issues), (
        f"W-4: the drifted status column must be caught; got {issues}")


def test_lint_index_accepts_the_538_canonical_form(tmp_path):
    """The #538 single-schema form (no pipes, migrate_facts output shape,
    including the PARTIALLY-VERIFIED workflow word) must lint clean."""
    ws = _ws(tmp_path)
    idx = ws / "facts" / "_INDEX.md"
    idx.write_text(
        "# Facts Index — sample\n\n## Status: 2 PROVEN / 1 PARTIALLY-VERIFIED\n\n"
        "F001-sample-overview | PROVEN | C-001 | Sample Overview\n"
        "F005-xor-string-decode | PARTIALLY-VERIFIED | C-005 | XOR Decode\n",
        encoding="utf-8")
    assert lint_facts.lint_index(idx) == []


# ---------- L-7: NO_FRONTMATTER no longer skips the whole file ----------

def test_no_frontmatter_still_lints_the_body(tmp_path):
    ws = _ws(tmp_path)
    (ws / "facts" / "F005-x.md").write_text(
        "## Status\nPROVEN\n\nNo frontmatter at all.\n", encoding="utf-8")
    errors, _warnings = lint_facts.lint_workspace(ws)
    codes = _codes(errors)
    assert "NO_FRONTMATTER" in codes
    assert "STATUS_MISMATCH" in codes, (
        "L-7: NO_FRONTMATTER must not `continue` past every other check — a "
        "body claiming PROVEN with no frontmatter has the L-4 mismatch too")


# ---------- L-3 / L-4 / L-6 ----------

def test_unknown_frontmatter_key_warns(tmp_path):
    ws = _ws(tmp_path)
    fm = _fact_fm("F006-x") + "vibes: strong\n"
    _fact(ws, "F006-x.md", fm)
    _errors, warnings = lint_facts.lint_workspace(ws)
    assert "UNKNOWN_KEY" in _codes(warnings), (
        f"L-3: unknown frontmatter key `vibes` must warn; got {_codes(warnings)}")


def test_body_status_line_must_match_frontmatter(tmp_path):
    ws = _ws(tmp_path)
    _fact(ws, "F007-x.md", _fact_fm("F007-x"),
          body="\n## Status\nPROVEN\n")
    errors, _warnings = lint_facts.lint_workspace(ws)
    assert "STATUS_MISMATCH" in _codes(errors), (
        f"L-4: body Status PROVEN vs frontmatter INFERRED must reconcile; "
        f"got {_codes(errors)}")


def test_note_carrying_fact_semantics_warns(tmp_path):
    """L-6: notes/ carrying fact-shaped verdict semantics is a carrier mix-up."""
    ws = _ws(tmp_path)
    (ws / "notes" / "N001.md").write_text(
        "---\nid: N001\nclaim_id: C-001\nstatus: PROVEN\n"
        "verify_status: passes\ncredibility: A1\n---\n\nprose\n",
        encoding="utf-8")
    _errors, warnings = lint_facts.lint_workspace(ws)
    assert "NOTE_SEMANTIC_MIX" in _codes(warnings), (
        f"L-6: a note carrying fact verdict keys must warn; "
        f"got {_codes(warnings)}")


def test_legal_note_shape_does_not_warn(tmp_path):
    """The legal convergence-note shape (id + claim_id + verify_status only)
    must NOT trip L-6 — the #336 fixture note shape stays quiet."""
    ws = _ws(tmp_path)
    (ws / "notes" / "N002.md").write_text(
        "---\nid: N002\nclaim_id: C-001\nverify_status: pending\n"
        "facts_used: []\ndepends_on: []\n---\n\nprose\n",
        encoding="utf-8")
    _errors, warnings = lint_facts.lint_workspace(ws)
    assert "NOTE_SEMANTIC_MIX" not in _codes(warnings)


# ---------- W-4 write side: update_index refuses malformed rows ----------
# #538 already landed validate_row-based refusal; these pin the #532 accept
# cases (drifted status, ghost claim id, atomic refusal) so the writer and
# the linter cannot drift apart again.

def test_update_index_refuses_a_drifted_status(tmp_path):
    """W-4 write side: the conclusion text bled into the status column must
    be refused before any disk write (atomic refusal)."""
    idx = tmp_path / "_INDEX.md"
    idx.write_text("F001-x | INFERRED | C-001 | prior row\n", encoding="utf-8")
    with pytest.raises(ValueError) as exc:
        update_index.upsert(idx, "F001-x", "endpoints-and-auth (login path)",
                            "C-001", "drifted")
    assert "status" in str(exc.value).lower()
    assert "endpoints-and-auth" not in idx.read_text(encoding="utf-8"), (
        "a refused upsert must not have written anything (atomic refusal)")


def test_update_index_refuses_a_non_claim_id(tmp_path):
    idx = tmp_path / "_INDEX.md"
    idx.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        update_index.upsert(idx, "F001-x", "PROVEN", "", "ghost claim")


def test_update_index_accepts_a_legal_row(tmp_path):
    idx = tmp_path / "_INDEX.md"
    idx.write_text("", encoding="utf-8")
    update_index.upsert(idx, "F001-x", "PROVEN", "C-001", "imports resolved")
    text = idx.read_text(encoding="utf-8")
    assert "F001-x" in text and "PROVEN" in text


def test_written_row_survives_its_own_linter(tmp_path):
    """Writer and linter share ONE row definition — everything upsert can
    write, lint_index_row must accept (#532 Task 6 round-trip)."""
    idx = tmp_path / "_INDEX.md"
    idx.write_text("", encoding="utf-8")
    update_index.upsert(idx, "F002-x", "PROVEN", "C-001", "plain conclusion")
    row = [ln for ln in idx.read_text(encoding="utf-8").splitlines()
           if "F002-x" in ln][0]
    assert lint_facts.lint_index_row(row, 3) == [], (
        f"the written row must survive its own linter: {row!r}")
