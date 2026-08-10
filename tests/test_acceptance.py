"""tests/test_acceptance.py — 端到端静态验收 (issue #6, plan §2.3/§9)。"""
from __future__ import annotations

import acceptance_check as ac


def test_acceptance_overall_passes():
    report = ac.run_acceptance()
    failed = [c["name"] for c in report["checks"] if not c["passed"]]
    assert report["overall_passed"], f"验收失败项: {failed}"


def test_acceptance_has_five_checks():
    report = ac.run_acceptance()
    names = {c["name"] for c in report["checks"]}
    must = {"oracle_10_10", "cli_surface_8", "priority_voi_formula",
            "digest_builds", "test_suite_green"}
    assert must <= names, f"缺验收项: {must - names}"
