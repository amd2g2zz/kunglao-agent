# -*- coding: utf-8 -*-
"""tests/test_audit_guard_reviewgate_799.py — #799 pin: audit scan excludes the .review prefix family.

#799: `test_v012_milestone_audit.py::test_no_legacy_precommit_reference`
excluded the exact component name `.review`, but the review gate's evidence
surface is `.review-gate/` (scripts/review_gate.py; gitignored) — so on any
dev machine holding local evidence files containing the retired legacy
pre-commit hook path string, the audit false-reds:

    AssertionError: legacy pre-commit refs: ['.review-gate/evidence-ci-fix.md']

The GUARD_TEST_SWEEP (#799) found the predicate mirrored in
`test_dedup_319.py::test_no_reference_to_legacy_precommit_path` as
`".review-gate" in p.parts` — the complementary half: it misses the retired
`.review/` dir (#455/#472 lineage, still gitignored at .gitignore:80).

These pins drive the REAL scanner functions (module-level ROOT monkeypatched
to a tmp layout — no predicate re-implementation, so the pins fail if the
scanners drift again). Ruling: the exclusion covers the `.review` PREFIX
FAMILY — any path component starting with `.review` is local review evidence,
not repo content (see openspec/changes/issue-799-audit-guard-review-gate/).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

import test_dedup_319
import test_v012_milestone_audit

# The needle is split across adjacent literals: this file's SOURCE must not
# contain the contiguous legacy path, or the scanners would flag the pin
# itself (they scan every committed file outside their allow-list).
LEGACY_STRING = "see .claude/hooks/" "pre-commit for the retired gate"

V012_SCANNER = test_v012_milestone_audit.test_no_legacy_precommit_reference
DEDUP_SCANNER = test_dedup_319.test_no_reference_to_legacy_precommit_path


def _plant(root: Path, rel: str, text: str = LEGACY_STRING) -> None:
    """Drop a file with the legacy pre-commit string into a tmp repo layout."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _scanner_must_ignore(monkeypatch, tmp_path: Path, scanner, plant_rel: str) -> None:
    """Run a real audit scanner against a tmp ROOT holding one planted file.

    The scanner under test must NOT count the planted local-review file as
    an offender (i.e. calling it must not raise AssertionError).
    """
    _plant(tmp_path, plant_rel)
    monkeypatch.setattr(sys.modules[scanner.__module__], "ROOT", tmp_path)
    scanner()  # AssertionError here == the planted review file was flagged


def _scanner_must_flag(monkeypatch, tmp_path: Path, scanner, plant_rel: str) -> None:
    """Positive control: a legacy string in plain repo content IS flagged."""
    _plant(tmp_path, plant_rel)
    monkeypatch.setattr(sys.modules[scanner.__module__], "ROOT", tmp_path)
    with pytest.raises(AssertionError, match=re.escape(plant_rel)):
        scanner()


# --- #799 core: .review-gate evidence must not be scanned as repo content ---

def test_v012_scanner_ignores_reviewgate_evidence(monkeypatch, tmp_path: Path):
    """#799 RED: .review-gate/evidence-*.md must not be an offender."""
    _scanner_must_ignore(
        monkeypatch, tmp_path, V012_SCANNER, ".review-gate/evidence-ci-fix.md",
    )


def test_dedup_scanner_ignores_reviewgate_evidence(monkeypatch, tmp_path: Path):
    """Mirror pin (dedup-319): .review-gate/evidence-*.md must not be an offender."""
    _scanner_must_ignore(
        monkeypatch, tmp_path, DEDUP_SCANNER, ".review-gate/evidence-ci-fix.md",
    )


# --- prefix family: the retired .review/ dir is excluded by BOTH scanners ---

def test_v012_scanner_ignores_retired_review_dir(monkeypatch, tmp_path: Path):
    """v0.1.2 scanner keeps excluding the original .review component."""
    _scanner_must_ignore(
        monkeypatch, tmp_path, V012_SCANNER, ".review/evidence-472-a1.md",
    )


def test_dedup_scanner_ignores_retired_review_dir(monkeypatch, tmp_path: Path):
    """#799 mirror RED: dedup scanner excluded only .review-gate exactly —
    a dev machine retaining .review/*.md process files false-reds it too."""
    _scanner_must_ignore(
        monkeypatch, tmp_path, DEDUP_SCANNER, ".review/evidence-472-a1.md",
    )


# --- positive controls: the fix must not make the audits vacuous ---

def test_v012_scanner_still_flags_repo_content(monkeypatch, tmp_path: Path):
    _scanner_must_flag(monkeypatch, tmp_path, V012_SCANNER, "docs/legacy-note.md")


def test_dedup_scanner_still_flags_repo_content(monkeypatch, tmp_path: Path):
    _scanner_must_flag(monkeypatch, tmp_path, DEDUP_SCANNER, "docs/legacy-note.md")


if __name__ == "__main__":
    sys.exit(0)
