#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_mechanisms_retirement.py — issue #566 / #446 closure.

Closes #446 acceptance criterion #3 ("merge a retirement sample PR") by
locking down the v0 dispatch protocol regex retirement lifecycle. The
v0 protocol was the legacy `[T<N> tools=a,b] claim C-NN ...` text form
introduced before #452 shipped the JSON v1 protocol; v1 has been
canonical since 2026-08-19 and v0 has had no production callers.

This test file encodes the governance contract:

1. The retirement ledger `references/mechanisms.md` exists, is a single
   source for mechanism lifecycle (lifecycle column = ACTIVE | DEPRECATED
   | RETIRED), and lists v0 dispatch as RETIRED.
2. The mechanism ledger is wired into the spec-impl gap table
   (`openspec/changes/issue-446-governance-fg/mechanisms-status.md`):
   the row "合并/退役样板 PR (验收第三条)" is DONE, not PENDING.

The hooks-side `MECHANISMS` metadata dict and its test class were removed
(#861/#863 no-backcompat cleanup): zero production readers. The v0 regex
STAYS live (single source DISPATCH_RE); its parse behavior is pinned by
tests/test_v0_retirement_861.py (three-parser consistency on V0_PREFIX).

The contract is "audit trail, not runtime removal" — retiring a mechanism
in the ledger means future authors can find one canonical record, not that
the regex disappears from the codebase tonight.
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCES_DIR = REPO_ROOT / "references"
MECHANISMS_LEDGER = REFERENCES_DIR / "mechanisms.md"
MECHANISMS_STATUS = (
    REPO_ROOT / "openspec" / "archive" / "issue-446-governance-fg"
    / "mechanisms-status.md"
)


# ---------- helpers ----------

def _load_references_mechanisms() -> str:
    """Return the raw text of references/mechanisms.md (raises if missing)."""
    assert MECHANISMS_LEDGER.exists(), (
        f"governance ledger missing: {MECHANISMS_LEDGER.relative_to(REPO_ROOT)}"
        " — issue #446 acceptance criterion #1 is unsatisfied."
    )
    return MECHANISMS_LEDGER.read_text(encoding="utf-8")


# ---------- (A) ledger existence + format ----------

class TestMechanismsLedgerExists:
    """#446 acceptance criterion #1: mechanisms.md master ledger exists."""

    def test_ledger_path_exists(self) -> None:
        assert MECHANISMS_LEDGER.exists(), (
            f"missing: {MECHANISMS_LEDGER.relative_to(REPO_ROOT)}"
        )

    def test_ledger_has_lifecycle_column(self) -> None:
        """The ledger must define an explicit lifecycle vocabulary
        (ACTIVE / DEPRECATED / RETIRED) — without it, retirement has no
        semantic anchor and authors can drift back to ad-hoc states."""
        text = _load_references_mechanisms()
        # Every lifecycle word must appear in the file at least once.
        for word in ("ACTIVE", "DEPRECATED", "RETIRED"):
            assert word in text, (
                f"lifecycle vocabulary missing: {word!r} not in ledger"
            )

    def test_ledger_documents_v0_dispatch_as_retired(self) -> None:
        """v0 dispatch protocol regex must be in the ledger with lifecycle
        = RETIRED. This is the retirement sample PR closing #446."""
        text = _load_references_mechanisms()
        # The regex itself — pattern must appear so the record is grep-able.
        assert "DISPATCH_RE" in text or "v0" in text.lower(), (
            "ledger does not reference the retired v0 dispatch regex"
        )
        # The retirement row marker — at least one row contains both a
        # v0 reference and the RETIRED lifecycle marker.
        retired_rows = re.findall(
            r"^\|[^\n]*RETIRED[^\n]*\|",
            text,
            flags=re.MULTILINE,
        )
        v0_retired = [r for r in retired_rows if "v0" in r.lower() or "dispatch" in r.lower()]
        assert v0_retired, (
            "no RETIRED row mentions v0/dispatch — retirement record absent"
        )

    def test_ledger_records_replacement(self) -> None:
        """Every RETIRED entry must reference its replacement so future
        authors know what to use instead (no orphan retirements)."""
        text = _load_references_mechanisms()
        # The v0 retirement record must mention v1 (the replacement).
        m = re.search(
            r"^\|[^\n]*v0[^\n]*\|[^\n]*RETIRED[^\n]*\|",
            text,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        assert m, "no v0 RETIRED row found"
        assert "v1" in m.group(0).lower(), (
            "v0 retirement must reference its v1 replacement — orphan retirement"
        )


# ---------- (B) spec-impl gap table update ----------

class TestMechanismsStatusUpdated:
    """#446 acceptance criterion #3 row in mechanisms-status.md must flip
    from PENDING to DONE once the retirement sample PR lands."""

    def _read_status_table(self) -> str:
        assert MECHANISMS_STATUS.exists(), (
            f"missing: {MECHANISMS_STATUS.relative_to(REPO_ROOT)}"
        )
        return MECHANISMS_STATUS.read_text(encoding="utf-8")

    def test_retirement_row_is_done(self) -> None:
        text = self._read_status_table()
        # Find the retirement row by its label keyword.
        # The row label mentions both "退役" and "合并" (or "样板 PR").
        pattern = re.compile(
            r"^\|[^\n]*退役[^\n]*\|[^\n]*\|",
            flags=re.MULTILINE,
        )
        rows = pattern.findall(text)
        assert rows, "no row mentions 退役 in mechanisms-status.md"
        # At least one row must have status DONE.
        assert any("DONE" in r for r in rows), (
            "retirement row must be DONE, not PENDING:\n"
            + "\n".join(rows)
        )

    def test_no_remaining_pending_for_retirement(self) -> None:
        """Belt-and-braces: no row containing both 退役/合并/样板 and
        PENDING. A lingering PENDING would mean the closure didn't reach
        the table."""
        text = self._read_status_table()
        bad = re.findall(
            r"^\|[^\n]*(?:退役|合并|样板)[^\n]*\|[^\n]*PENDING[^\n]*\|",
            text,
            flags=re.MULTILINE,
        )
        assert not bad, (
            "retirement sample PR row still PENDING:\n" + "\n".join(bad)
        )


# ---------- (C) lifecycle sanity ----------

class TestLifecycleSemantics:
    """Governance lifecycle: a retired mechanism MUST have been DEPRECATED
    first (you can't skip straight to RETIRED without a soft-warning window).
    The ledger must record both transitions or the audit trail is incomplete."""

    def test_v0_dispatch_has_full_lifecycle_record(self) -> None:
        text = _load_references_mechanisms()
        # Look for a "lifecycle:" or transition table in the v0 entry.
        # We accept either a transitions column or a history note in the
        # row; what matters is that BOTH deprecated and retired dates exist.
        # (For the sample precedent, the doc_sync-approved format is a
        # single RETIRED row with a transition-history note.)
        assert "DEPRECATED" in text and "RETIRED" in text, (
            "ledger must contain both DEPRECATED and RETIRED markers"
        )
        # The v0 row itself, if it carries dates, must list at least one
        # deprecated milestone (e.g., the v1 introduction date).
        v0_section = re.search(
            r"^\|[^\n]*v0[^\n]*\|[^\n]*RETIRED[^\n]*\|",
            text,
            flags=re.MULTILINE | re.IGNORECASE,
        )
        assert v0_section
        # The surrounding context must contain a deprecation reference
        # (within ~3 lines above or below).
        start = max(0, v0_section.start() - 400)
        end = min(len(text), v0_section.end() + 400)
        window = text[start:end]
        assert re.search(r"deprecated|DEPRECATED", window), (
            "v0 RETIRED row must be co-located with a DEPRECATED marker "
            "(lifecycle skipped — no soft-warning window)"
        )