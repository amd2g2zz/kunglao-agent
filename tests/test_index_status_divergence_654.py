# -*- coding: utf-8 -*-
"""Issue #654 1-F4 — facts/_INDEX.md ↔ frontmatter status divergence.

Live instance from the audit: an index row reading ``F001 | INFERRED``
beside a fact whose frontmatter says PARTIAL, and rows reading ``OPEN``
for facts that exist on disk. The only index writer is promotion-scoped
(fact_status_sync fires solely from the PROVEN settle), so every other
status transition leaves the row behind and the derived briefs /
dispatch_context / contradiction joins misreport progress.

The audit named the cheapest detector: lint_facts validates row SHAPE,
never row↔frontmatter AGREEMENT. This pins that detector — a WARNING
(drift is visibility, never a write block: the claim register stays
authoritative and the lint never hard-fails an existing workspace on a
row-vs-file disagreement).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import lint_facts  # noqa: E402

_SHA = "c" * 64


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


def _fact(ws: Path, name: str, *, fid: str, status: str) -> None:
    """A schema-legal fact file whose frontmatter AND body status agree
    (so the divergence signal is the only status issue under test)."""
    body_status = status if status in lint_facts.VALID_STATUS else "OPEN"
    fm = {
        "id": fid,
        "type": "fact",
        "title": f"{fid} title",
        "status": status,
        "created": "2026-08-20",
        "last_reviewed": "2026-08-20",
        "claim_id": "C-001",
        "boundary_type": "observation",
        "promotion_gate": "resolve the loader stub under dynamic-trace",
        "source": "static-decompile",
        "confidence": "high" if status == "PROVEN" else "medium",
        "verify_status": "partial",
        "reproduce": "python runs/verify.py",
        "expected": _SHA,
        "verified": "pending",
        "provenance": [
            {"role": "decompiled_c", "path": "evidence/x.c",
             "content_sha256": _SHA, "credibility": "B2"},
        ],
    }
    lines = []
    for k, v in fm.items():
        if k == "provenance":
            lines.append("provenance:")
            for entry in v:
                cells = ", ".join(f"{ek}: {ev}" for ek, ev in entry.items())
                lines.append(f"  - {{{cells}}}")
        else:
            lines.append(f"{k}: {v}")
    (ws / "facts" / name).write_text(
        "---\n" + "\n".join(lines) + f"\n---\n\n## Status\n{body_status}\n",
        encoding="utf-8")


def _index(ws: Path, rows: list[str]) -> None:
    (ws / "facts" / "_INDEX.md").write_text(
        "# _INDEX\n\n" + "\n".join(rows) + "\n", encoding="utf-8")


def _codes(items) -> set[str]:
    return {code for _sev, code, _msg in items}


def _lint(ws: Path):
    return lint_facts.lint_workspace(ws)


# ------------------------------------------------------------ the detector

def test_divergent_index_status_warns(tmp_path):
    """Frontmatter says INFERRED, the row says OPEN — the live shape."""
    ws = _ws(tmp_path)
    _fact(ws, "F001-x.md", fid="F001-x", status="INFERRED")
    _index(ws, ["F001-x | OPEN | C-001 | imports resolved at runtime"])
    errors, warnings = _lint(ws)
    assert "INDEX_STATUS_DIVERGENCE" in _codes(warnings), (
        f"the row↔frontmatter disagreement must warn; got {warnings}")
    assert "INDEX_STATUS_DIVERGENCE" not in _codes(errors), (
        "drift is visibility, never an error — the index never blocks")


def test_illegal_frontmatter_status_still_diverges(tmp_path):
    """The live PARTIAL case: the frontmatter word is illegal (BAD_STATUS
    errors), AND the row can never agree with it — both signals fire."""
    ws = _ws(tmp_path)
    _fact(ws, "F001-x.md", fid="F001-x", status="PARTIAL")
    _index(ws, ["F001-x | INFERRED | C-001 | partly verified"])
    errors, warnings = _lint(ws)
    assert "BAD_STATUS" in _codes(errors)
    assert "INDEX_STATUS_DIVERGENCE" in _codes(warnings)


def test_agreeing_index_status_is_clean(tmp_path):
    ws = _ws(tmp_path)
    _fact(ws, "F001-x.md", fid="F001-x", status="INFERRED")
    _index(ws, ["F001-x | INFERRED | C-001 | imports resolved at runtime"])
    _errors, warnings = _lint(ws)
    assert "INDEX_STATUS_DIVERGENCE" not in _codes(warnings)


def test_short_fact_token_matches_the_slugged_fact(tmp_path):
    """The live rows carried the bare F<NNN> token while the file is
    slugged (F004 vs F004-x.md) — the join normalizes both."""
    ws = _ws(tmp_path)
    _fact(ws, "F004-x.md", fid="F004-x", status="INFERRED")
    _index(ws, ["F004 | OPEN | C-001 | slugged fact, short row token"])
    _errors, warnings = _lint(ws)
    assert "INDEX_STATUS_DIVERGENCE" in _codes(warnings)


def test_pipe_table_grammar_is_checked_too(tmp_path):
    ws = _ws(tmp_path)
    _fact(ws, "F001-x.md", fid="F001-x", status="INFERRED")
    _index(ws, ["| fact | status | claim | conclusion |",
                "|---|---|---|---|",
                "| F001-x | OPEN | C-001 | drifted |"])
    _errors, warnings = _lint(ws)
    assert "INDEX_STATUS_DIVERGENCE" in _codes(warnings)


def test_row_without_a_fact_file_is_not_divergence(tmp_path):
    """A row naming a fact that does not exist has no frontmatter to
    disagree with — the shape validator's domain, not this detector's."""
    ws = _ws(tmp_path)
    _index(ws, ["F099-x | OPEN | C-001 | no fact file on disk"])
    _errors, warnings = _lint(ws)
    assert "INDEX_STATUS_DIVERGENCE" not in _codes(warnings)


def test_no_index_is_clean(tmp_path):
    ws = _ws(tmp_path)
    _fact(ws, "F001-x.md", fid="F001-x", status="INFERRED")
    _errors, warnings = _lint(ws)
    assert "INDEX_STATUS_DIVERGENCE" not in _codes(warnings)
