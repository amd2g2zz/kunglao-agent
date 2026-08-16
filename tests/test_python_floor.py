# -*- coding: utf-8 -*-
"""tests/test_python_floor.py — issue #352 supported-runtime floor (TDD).

User directive (2026-08): the supported runtime is Python 3.10+ with uv —
NOT python2 (that half of #352 was delivered by #389/#391), and the floor
moves from 3.11 to 3.10.

Facts guarded here:
1. pyproject.toml requires-python parses to a floor of exactly "3.10".
   Parsing is regex-based on purpose (NOT tomllib) so this test itself
   runs on Python 3.10 — a floor test that cannot run on the floor is
   worthless.
2. uv.lock and release-manifest.yaml declare the same floor (three
   declarations, one truth — pyproject is the source).
3. No repo-owned Python file (scripts/ hooks/ tools/ templates/ tests/
   conftest.py) imports tomllib (3.11+ stdlib) without the sanctioned
   tomli fallback:
       try: import tomllib
       except ImportError: import tomli as tomllib
   tomli is the dev-group backfill so tests run on 3.10.
4. release-check.yml exercises the 3.10 floor in CI, so floor drift fails
   in CI instead of at a user install.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
RELEASE_MANIFEST = ROOT / "release-manifest.yaml"
WORKFLOW = ROOT / ".github" / "workflows" / "release-check.yml"
CONFTEST = ROOT / "conftest.py"

# Every repo-owned .py file: shipped code AND the test suite itself — the
# tests must run on 3.10, so their imports carry the same constraint.
PY_DIRS = ("scripts", "hooks", "tools", "templates", "tests")

REQUIRES_PYTHON_RE = re.compile(
    r'^requires[-_]python\s*[=:]\s*"([^"]+)"\s*$', re.MULTILINE)


def _floor(spec: str) -> str | None:
    """'>=3.10' -> '3.10'; '>=3.11.1' -> '3.11.1'. None if not a >= spec."""
    m = re.match(r">=\s*(\d+(?:\.\d+)*)", spec.strip())
    return m.group(1) if m else None


def _declared_floor(path: Path) -> str | None:
    m = REQUIRES_PYTHON_RE.search(path.read_text(encoding="utf-8"))
    assert m, f"{path.name} requires-python declaration missing"
    return _floor(m.group(1))


def _scanned_python_files() -> list[Path]:
    files = [CONFTEST]
    for d in PY_DIRS:
        files.extend(p for p in (ROOT / d).rglob("*.py") if p.is_file())
    return files


# ---------- the floor itself ----------

def test_pyproject_floor_is_exactly_310():
    floor = _declared_floor(PYPROJECT)
    assert floor == "3.10", f"pyproject requires-python floor is {floor!r}, want '3.10'"


def test_lock_and_manifest_declare_the_same_floor():
    py = _declared_floor(PYPROJECT)
    for path, label in ((UV_LOCK, "uv.lock"), (RELEASE_MANIFEST, "release-manifest.yaml")):
        other = _declared_floor(path)
        assert other == py, (
            f"{label} floor {other!r} != pyproject floor {py!r} "
            f"(regenerate with `uv lock` and edit the manifest)"
        )


# ---------- tomllib discipline (3.11-only stdlib) ----------

def test_no_tomllib_without_tomli_fallback():
    offenders = []
    for p in _scanned_python_files():
        text = p.read_text(encoding="utf-8")
        if "tomllib" in text and not (
            "import tomli as tomllib" in text and "except ImportError" in text
        ):
            offenders.append(str(p.relative_to(ROOT)))
    assert not offenders, (
        "tomllib is 3.11+; repo .py files may only use it with the "
        f"tomli fallback (try: import tomllib / except ImportError): {offenders}"
    )


# ---------- CI exercises the floor ----------

def test_release_check_ci_exercises_the_310_floor():
    wf = WORKFLOW.read_text(encoding="utf-8")
    assert "3.10" in wf, (
        "release-check.yml must run the suite on the 3.10 floor — CI is "
        "the only place floor drift gets caught before a user install"
    )
    assert "uv" in wf, "release-check.yml must keep the documented uv flow"
