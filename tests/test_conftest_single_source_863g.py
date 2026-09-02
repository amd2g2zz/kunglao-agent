# -*- coding: utf-8 -*-
"""863-h Family G pins: the 5 shared fixtures stay single-sourced in tests/conftest.py.

The root conftest.py once carried shadowed twins of all five Phase-0 fixtures
(tmp / ws_factory / contract_validator / golden_master / isolated_home). Their
drift was a live GBK regression trap: the root golden_master replayed manifests
with bare text=True, losing the #317 UTF-8 decode. The #811 arbitration ruled
the GBK-fixed child versions authoritative and deleted the root copies
(commit 34e1603). These pins keep the fork from re-growing and keep the
UTF-8 decode on the live fixture — fixture resolution must not regress.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_CONFTEST = ROOT / "conftest.py"
TESTS_CONFTEST = ROOT / "tests" / "conftest.py"

#: The five shadowed root fixtures removed by #811 arbitration (34e1603).
SHADOWED_FIXTURES = (
    "tmp",
    "ws_factory",
    "contract_validator",
    "golden_master",
    "isolated_home",
)


def _fixture_defs(source: str) -> set[str]:
    """Names defined as pytest fixtures in a conftest source string."""
    found = set()
    for m in re.finditer(r"@pytest\.fixture[^\n]*\n(?:@[^\n]+\n)*def (\w+)\(", source):
        found.add(m.group(1))
    return found


def test_root_conftest_defines_no_shadowed_fixtures():
    """The deleted root twins must never re-grow (B6 arbitration, mechanical)."""
    root_defs = _fixture_defs(ROOT_CONFTEST.read_text(encoding="utf-8"))
    regrown = sorted(root_defs & set(SHADOWED_FIXTURES))
    assert not regrown, (
        "root conftest.py re-defined shadowed fixture(s) "
        f"{regrown} — the 5 Phase-0 fixtures are single-sourced in "
        "tests/conftest.py (#811 arbitration / 863-h Family G)")


def test_tests_conftest_defines_all_five():
    """The single source still defines every one of the five fixtures."""
    src = TESTS_CONFTEST.read_text(encoding="utf-8")
    missing = sorted(set(SHADOWED_FIXTURES) - _fixture_defs(src))
    assert not missing, f"tests/conftest.py lost fixture(s): {missing}"


def test_golden_master_keeps_gbk_safe_decode():
    """The live golden_master must decode subprocess output as UTF-8 (#317).

    The whole point of the #811 B6 removal: a bare text=True replay crashes
    the reader thread on multi-byte output under a GBK locale. Pin the decode
    inside the golden_master fixture body.
    """
    src = TESTS_CONFTEST.read_text(encoding="utf-8")
    m = re.search(r"def golden_master\(.*?(?=\n@pytest\.fixture|\Z)", src, re.S)
    assert m, "golden_master fixture not found in tests/conftest.py"
    body = m.group(0)
    assert 'encoding="utf-8"' in body and 'errors="replace"' in body, (
        "golden_master lost the #317 UTF-8 decode (encoding='utf-8', "
        "errors='replace') — GBK regression trap would re-arm")


def test_fixture_resolution_unchanged(tmp, ws_factory, tmp_path, isolated_home):
    """Behavioral pin: the resolved fixtures still behave as before removal.

    - tmp aliases tmp_path (legacy main()-direct-run signature compat)
    - ws_factory writes the canonical 6-field claim-register dialect
    - isolated_home points HOME/USERPROFILE at the tmp home
    """
    assert tmp is tmp_path

    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    register = (ws / "claim-register.yaml").read_text(encoding="utf-8")
    assert register == (
        "claims:\n"
        "- id: C-1\n"
        "  status: OPEN\n"
        "  boundary_type: positive_observation\n"
        "  evidence_tier_attempted: 0\n"
        "  promotion_attempts: 0\n"
        "  depends_on: []\n"
    )

    home = Path(os.environ["HOME"])
    assert home.exists() and home == Path(os.environ["USERPROFILE"])
    assert tmp_path in home.parents or home.is_relative_to(tmp_path)
