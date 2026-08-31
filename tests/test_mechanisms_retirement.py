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
2. The mechanism is reported as RETIRED by `hooks/lib_kunglao.py`
   (status attribute on the module — pure metadata, no behavior change).
3. The regex `DISPATCH_RE` is still defined and parseable (back-compat
   for any straggler call sites; the retirement is a governance act, not
   a runtime removal — that follow-up is a separate PR).
4. The mechanism ledger is wired into the spec-impl gap table
   (`openspec/changes/issue-446-governance-fg/mechanisms-status.md`):
   the row "合并/退役样板 PR (验收第三条)" is DONE, not PENDING.

The contract is "audit trail, not runtime removal" — retiring a mechanism
in the ledger means future authors can find one canonical record, not that
the regex disappears from the codebase tonight.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCES_DIR = REPO_ROOT / "references"
MECHANISMS_LEDGER = REFERENCES_DIR / "mechanisms.md"
MECHANISMS_STATUS = (
    REPO_ROOT / "openspec" / "archive" / "issue-446-governance-fg"
    / "mechanisms-status.md"
)


# ---------- helpers ----------

def _load_hooks_lib_kunglao():
    """Load hooks/lib_kunglao.py explicitly (mirrors test_dispatch_protocol)."""
    spec = importlib.util.spec_from_file_location(
        "_hooks_lib_kunglao_for_retirement_test",
        REPO_ROOT / "hooks" / "lib_kunglao.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


# ---------- (B) hooks/lib_kunglao.py metadata ----------

class TestDispatchRetirementMetadata:
    """The hooks module must declare the v0 regex's retirement as runtime
    metadata (purely informational; the regex stays callable for back-compat).
    This lets future readers learn the governance status without grepping
    documentation."""

    def test_module_exposes_lifecycle_attribute(self) -> None:
        lk = _load_hooks_lib_kunglao()
        # Module-level metadata (a plain dict or attribute); not behaviour.
        attr = getattr(lk, "MECHANISMS", None)
        assert attr is not None, (
            "hooks/lib_kunglao.py must declare MECHANISMS metadata"
        )
        # Must include the v0 dispatch entry.
        v0_keys = [k for k in attr if "DISPATCH_RE" in k or "v0" in str(k).lower()]
        assert v0_keys, (
            f"MECHANISMS must contain a DISPATCH_RE/v0 entry; got keys={list(attr)[:5]}…"
        )

    def test_v0_dispatch_lifecycle_is_retired(self) -> None:
        lk = _load_hooks_lib_kunglao()
        attr = getattr(lk, "MECHANISMS", {})
        v0_entry = None
        for k, v in attr.items():
            if "DISPATCH_RE" in k or ("v0" in str(k).lower() and "dispatch" in str(k).lower()):
                v0_entry = v
                break
        assert v0_entry is not None
        lifecycle = str(v0_entry.get("lifecycle", "")).upper()
        assert lifecycle == "RETIRED", (
            f"v0 dispatch lifecycle must be RETIRED; got {lifecycle!r}"
        )
        # Must reference the replacement for audit-trail completeness.
        replacement = str(v0_entry.get("replacement", ""))
        assert "v1" in replacement.lower(), (
            "v0 retirement record must name v1 as replacement"
        )

    def test_regex_remains_callable_for_backcompat(self) -> None:
        """Retirement is governance-only; the regex stays defined so any
        straggler caller keeps working. Behavioural removal is a separate PR
        once all call-sites are confirmed migrated."""
        lk = _load_hooks_lib_kunglao()
        assert lk.DISPATCH_RE is not None
        # Quick sanity: the regex still matches the canonical v0 form.
        m = lk.DISPATCH_RE.search("[T2 tools=pe_analyze] claim C-007")
        assert m is not None
        assert m.group(3) == "C-007"


# ---------- (C) spec-impl gap table update ----------

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


# ---------- (D) lifecycle sanity ----------

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