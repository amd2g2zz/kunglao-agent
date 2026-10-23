#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_coverage_policy_564.py — issue #564 drift guard, #807 amendment.

Coverage policy (AMENDED 2026-10-23 by #807):
  - OBSERVATION at the pytest.ini / local level: pytest.ini MUST NOT carry
    `--cov-fail-under`; running pytest locally never fails on a percentage.
  - ENFORCED FLOOR on the MEASURED SET in CI: scripts/ + hooks/ production
    faces are gated at the raise-only ratchet floor in coverage-floor.json
    via scripts/coverage_floor.py (check + monotone steps in
    release-check.yml). The ratchet may only move UP; its absolute minimum
    (70.0) and raise-only semantics are pinned in
    tests/test_coverage_floor_ratchet_807.py.
  - The raw `--cov-fail-under` flag stays banned EVERYWHERE: enforcement
    goes through the ratchet file, which is strictly stronger because it
    cannot silently move down.
  - Gate 4 (the recorded mutation baseline, #663) REMAINS the primary
    effectiveness metric, NOT a coverage line %. pytest-cov is wired so the
    report lands in CI artifacts and feeds the #807 floor check.

This file is the regression guard: if a future change re-introduces an
enforcement threshold as a raw flag, or drops the #807 amendment markers
from the policy surfaces, this test fails loudly with the exact location
and rationale (so the change is conscious, not silent).

Reconciliation: tests/test_coverage_floor_520.py uses --cov at pytest
runtime but asserts a buffered floor (FLOOR=60, target 75) as a
NORMAL assertion, not via --cov-fail-under. That stays literally true.

Truth sources (verified here):
  1. pytest.ini: #463 observation basis + #807 amendment note
  2. release-check.yml: #807 floor steps (coverage_floor.py check/monotone)
  3. pyproject.toml dev dep comment: pytest-cov w/o threshold gate
  4. CHANGELOG.md / release-manifest.yaml / AGENTS.md: documented
     policy, amended by #807
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Authoritative config files in the coverage decision surface. Each MUST
# remain free of an enforcement threshold; this list is the single source
# of truth for what the guard scans.
COVERAGE_CONFIG_PATHS = (
    ROOT / "pytest.ini",
    ROOT / "pyproject.toml",
    ROOT / ".github" / "workflows" / "release-check.yml",
    ROOT / ".github" / "workflows" / "ci.yml",
)

# Files where the token may LEGITIMATELY appear in a comment / docstring
# (the test_coverage_floor_520.py RECONCILIATION NOTE is the canonical
# example; we exempt it explicitly to avoid breaking the doc).
COVERAGE_DOC_ALLOWLIST = {
    ROOT / "tests" / "test_coverage_floor_520.py",
    ROOT / "tests" / "test_coverage_policy_564.py",  # this file
}

# Regex for an ACTIVE --cov-fail-under. We accept:
#   --cov-fail-under=75
#   --cov-fail-under 75
# But we explicitly reject false-positive patterns in commented-out
# examples by stripping comment lines first.
ACTIVE_FAIL_UNDER = re.compile(
    r"^\s*--cov-fail-under(?:\s|=)\d+",
    re.MULTILINE,
)


def _strip_comments(text: str) -> str:
    """Strip line-style comments for the cfg/yml/toml scan.

    - ini / yml / toml: # is line-comment prefix
    - python: # is line-comment prefix (we never scan py anyway,
      but defensive in case of test files)
    """
    out = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        # Strip trailing inline comments (cfg/yml/toml/python all use #).
        # Be conservative: only treat as comment when preceded by whitespace
        # or at the start of a value.
        idx = line.find(" #")
        if idx == -1:
            out.append(line)
        else:
            out.append(line[:idx])
    return "\n".join(out)


def _scan(path: Path) -> list[str]:
    """Return a list of 'path:line' hits where --cov-fail-under is active."""
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    body = _strip_comments(text)
    hits = []
    for i, line in enumerate(body.splitlines(), start=1):
        if ACTIVE_FAIL_UNDER.search(line):
            hits.append(f"{path}:{i}: {line.strip()}")
    return hits


# ---- policy-truth tests --------------------------------------------------


def test_pytest_ini_has_no_cov_fail_under() -> None:
    """pytest.ini MUST NOT carry --cov-fail-under (#463; #807 keeps this)."""
    hits = _scan(ROOT / "pytest.ini")
    assert hits == [], (
        f"pytest.ini carries an active --cov-fail-under: {hits}. "
        f"Per #463 (kept by #807), local pytest is observation-only — "
        f"enforcement lives in the CI measured-set floor step."
    )


def test_release_check_workflow_has_no_cov_fail_under() -> None:
    """.github/workflows/release-check.yml MUST NOT add --cov-fail-under.

    Amendment: release-check DOES enforce coverage — through the
    raise-only ratchet (scripts/coverage_floor.py + coverage-floor.json),
    never through a static flag that could be quietly lowered.
    """
    hits = _scan(ROOT / ".github" / "workflows" / "release-check.yml")
    assert hits == [], (
        f"release-check.yml carries --cov-fail-under: {hits}. "
        f"#807: enforcement is the ratchet file (coverage-floor.json), "
        f"which can only move UP — do not replace it with a static flag."
    )


def test_pyproject_toml_has_no_cov_fail_under() -> None:
    """pyproject.toml MUST NOT carry a [tool.coverage.*] fail_under.

    The floor is the ratchet file, not a coverage-config constant.
    """
    p = ROOT / "pyproject.toml"
    if not p.is_file():
        return
    text = p.read_text(encoding="utf-8")
    # Active [tool.coverage.report] fail_under = NN — block any value.
    if re.search(
        r"\[tool\.coverage\.report\].*?fail_under\s*=\s*\d+",
        text,
        re.DOTALL,
    ):
        pytest.fail(
            "pyproject.toml [tool.coverage.report] fail_under is set. "
            "#807: enforcement is coverage-floor.json (raise-only ratchet), "
            "not a coverage-config constant."
        )


def test_ci_workflow_has_no_cov_fail_under() -> None:
    """If ci.yml exists, it MUST also be free of --cov-fail-under."""
    p = ROOT / ".github" / "workflows" / "ci.yml"
    if not p.is_file():
        pytest.skip("ci.yml absent — surface does not exist yet (#564)")
    hits = _scan(p)
    assert hits == [], (
        f"ci.yml carries --cov-fail-under: {hits}. "
        f"#807: enforcement is the raise-only ratchet, not a static flag."
    )


# ---- documentation-truth tests (amended) ----------------------------------


def test_pytest_ini_documents_observation_policy() -> None:
    """pytest.ini MUST carry the observation basis AND the amendment
    note (measured-set floor enforced in CI)."""
    text = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    assert "#463" in text and "coverage" in text.lower(), (
        "pytest.ini lost its #463 coverage-policy comment block. "
        "Re-add per #564."
    )
    assert "#807" in text, (
        "pytest.ini lost its #807 amendment note (measured-set floor). "
        "Re-add per the #807 policy amendment."
    )


def test_release_check_workflow_documents_observation_policy() -> None:
    """release-check.yml MUST carry the #463 rationale AND the #807 floor
    wiring (coverage_floor.py check step)."""
    text = (
        ROOT / ".github" / "workflows" / "release-check.yml"
    ).read_text(encoding="utf-8")
    assert "#463" in text and "observation" in text.lower(), (
        "release-check.yml lost its #463 coverage-rationale comment. "
        "Re-add per #564."
    )
    assert "#807" in text and "coverage_floor.py check" in text, (
        "release-check.yml lost its #807 measured-set floor step. "
        "Re-add per the #807 policy amendment."
    )


def test_pyproject_toml_documents_observation_policy() -> None:
    """pyproject.toml MUST carry the #463 observation comment AND the #807
    amendment marker near pytest-cov."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "#463" in text and "observation" in text.lower(), (
        "pyproject.toml lost its #463 observation comment. Re-add per #564."
    )
    assert "#807" in text, (
        "pyproject.toml lost its #807 amendment marker. Re-add per the "
        "#807 policy amendment."
    )


# ---- meta: drift detection of decision scope -----------------------------


def test_guard_scans_the_canonical_config_set() -> None:
    """Each canonical config path is exercised by exactly one test above.

    If a new path is added, two paired tests must be added (scan + doc).
    Fail loudly so the guard surface stays explicit.
    """
    expected = {
        "pytest.ini",
        ".github/workflows/release-check.yml",
        "pyproject.toml",
    }
    canonical = {p.relative_to(ROOT).as_posix() for p in COVERAGE_CONFIG_PATHS if p.is_file()}
    assert canonical == expected, (
        f"guard surface mismatch: scanned {canonical}, expected {expected}. "
        f"Update test_coverage_policy_564.py to reflect the new scope."
    )


def test_consistent_policy_across_all_truth_sources() -> None:
    """All policy documents must agree on the AMENDED stance.

    Amended policy (#807): observation at the pytest/local level; enforced
    floor on the measured set in CI via the raise-only ratchet. Every
    source keeps its OBSERVATION basis marker; the three config surfaces
    additionally carry the #807 amendment marker. If any single source
    contradicts the others, this test catches the drift.
    """
    sources = {
        "pytest.ini": ROOT / "pytest.ini",
        "release-check.yml": ROOT / ".github" / "workflows" / "release-check.yml",
        "pyproject.toml": ROOT / "pyproject.toml",
        "test_coverage_floor_520.py": ROOT / "tests" / "test_coverage_floor_520.py",
    }
    observed_phrase = "OBSERVATION"
    amended_sources = ("pytest.ini", "release-check.yml", "pyproject.toml")
    for label, path in sources.items():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert observed_phrase.lower() in text.lower(), (
            f"{label} lost its OBSERVATION marker. "
            f"Source must explicitly carry the #463 observation basis "
            f"(amended by #807: enforced floor on the measured set in CI)."
        )
        if label in amended_sources:
            assert "#807" in text, (
                f"{label} lost its #807 amendment marker. The policy text "
                f"must name the amendment: enforced floor on the measured "
                f"set (scripts/ + hooks/) via coverage-floor.json."
            )
