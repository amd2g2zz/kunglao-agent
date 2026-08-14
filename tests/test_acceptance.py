# -*- coding: utf-8 -*-
"""tests/test_acceptance.py — 端到端静态验收 (issue #6, plan §2.3/§9)。"""
from __future__ import annotations

import inspect

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


def test_test_suite_green_timeout_fits_full_suite():
    """#351: _check_test_suite 内嵌全量子进程, 超时必须容纳套件真实时长
    (CI 实测 ~2.5 min)。60s 会恒定 timeout → 验收永远红。"""
    assert ac.TEST_SUITE_TIMEOUT >= 300, (
        f"TEST_SUITE_TIMEOUT={ac.TEST_SUITE_TIMEOUT} — 全量套件 CI 实跑 ~150s, "
        "过短的超时使 test_suite_green 永远超时失败")


def test_test_suite_green_keeps_quiet_no_cache_pytest_flags():
    """#351: 内嵌 pytest 调用保持 -q --tb=no -p no:cacheprovider 且
    排除自身 (否则递归内嵌)。"""
    src = inspect.getsource(ac._check_test_suite)
    assert "-q" in src and "--tb=no" in src and "no:cacheprovider" in src
    assert "--ignore=tests/test_acceptance.py" in src
