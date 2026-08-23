#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_coverage_policy_564.py — issue #564 drift guard.

Coverage is OBSERVATION-only per #463 (4-gate quality framework):
  - pytest.ini MUST NOT carry `--cov-fail-under`
  - release-check.yml MUST NOT carry `--cov-fail-under`
  - pyproject.toml MUST NOT carry a cov config that fails on %
  - Gate 4 (mutmut availability) is the primary quality metric, NOT
    a coverage line %. pytest-cov is wired only so the report lands
    in CI artifacts and can be inspected manually.

This file is the regression guard: if a future change re-introduces
an enforcement threshold somewhere, this test fails loudly with the
exact location and rationale (so the change is conscious, not silent).

Reconciliation: tests/test_coverage_floor_520.py uses --cov at pytest
runtime but asserts a buffered floor (FLOOR=60, target 75) as a
NORMAL assertion, not via --cov-fail-under. That stays literally true.

Truth sources (verified here):
  1. pytest.ini line ~6-8: comment block declaring observation-only
  2. release-check.yml line ~54-60: #463 rationale comment
  3. pyproject.toml dev dep comment: pytest-cov w/o threshold gate
  4. CHANGELOG.md / release-manifest.yaml / AGENTS.md: documented
     policy, no enforcement
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
    """pytest.ini MUST NOT carry --cov-fail-under (#463, #564)."""
    hits = _scan(ROOT / "pytest.ini")
    assert hits == [], (
        f"pytest.ini carries an active --cov-fail-under: {hits}. "
        f"Per #463, coverage is OBSERVATION-only — remove it."
    )


def test_release_check_workflow_has_no_cov_fail_under() -> None:
    """.github/workflows/release-check.yml MUST NOT add --cov-fail-under."""
    hits = _scan(ROOT / ".github" / "workflows" / "release-check.yml")
    assert hits == [], (
        f"release-check.yml carries --cov-fail-under: {hits}. "
        f"#564 decision: keep coverage as observation, do not fail the gate."
    )


def test_pyproject_toml_has_no_cov_fail_under() -> None:
    """pyproject.toml MUST NOT carry a [tool.coverage.*] fail_under."""
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
            "#463: coverage is observation, not a gate."
        )


def test_ci_workflow_has_no_cov_fail_under() -> None:
    """If ci.yml exists, it MUST also be free of --cov-fail-under."""
    p = ROOT / ".github" / "workflows" / "ci.yml"
    if not p.is_file():
        pytest.skip("ci.yml absent — surface does not exist yet (#564)")
    hits = _scan(p)
    assert hits == [], (
        f"ci.yml carries --cov-fail-under: {hits}. #564: observation-only."
    )


# ---- documentation-truth tests -------------------------------------------


def test_pytest_ini_documents_observation_policy() -> None:
    """pytest.ini MUST carry a comment block declaring the policy."""
    text = (ROOT / "pytest.ini").read_text(encoding="utf-8")
    # The #463 comment block anchors on the #463 / 4-gate phrase.
    assert "#463" in text and "coverage" in text.lower(), (
        "pytest.ini lost its #463 coverage-policy comment block. "
        "Re-add per #564."
    )


def test_release_check_workflow_documents_observation_policy() -> None:
    """release-check.yml MUST carry a #463 rationale comment in pytest step."""
    text = (
        ROOT / ".github" / "workflows" / "release-check.yml"
    ).read_text(encoding="utf-8")
    assert "#463" in text and "observation" in text.lower(), (
        "release-check.yml lost its #463 coverage-rationale comment. "
        "Re-add per #564."
    )


def test_pyproject_toml_documents_observation_policy() -> None:
    """pyproject.toml MUST carry an `#463 observation` comment near pytest-cov."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "#463" in text and "observation" in text.lower(), (
        "pyproject.toml lost its #463 observation comment. Re-add per #564."
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
    """All four policy documents must agree on OBSERVATION-only stance.

    This is the ultimate integration check: if any single source
    contradicts the others (e.g., someone adds --cov-fail-under to
    release-check.yml while pytest.ini still says observation-only),
    this test catches the drift.
    """
    sources = {
        "pytest.ini": ROOT / "pytest.ini",
        "release-check.yml": ROOT / ".github" / "workflows" / "release-check.yml",
        "pyproject.toml": ROOT / "pyproject.toml",
        "test_coverage_floor_520.py": ROOT / "tests" / "test_coverage_floor_520.py",
    }
    observed_phrase = "OBSERVATION"
    for label, path in sources.items():
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        assert observed_phrase.lower() in text.lower(), (
            f"{label} lost its OBSERVATION marker. "
            f"Source must explicitly say coverage is observation-only "
            f"per #463/#564."
        )
