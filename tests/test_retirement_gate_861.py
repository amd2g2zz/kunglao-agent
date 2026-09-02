# -*- coding: utf-8 -*-
"""tests/test_retirement_gate_861.py — #861 机器绑定治理门机制测试。

机制用例在 tmp 合成仓上验证门的检出/基线棘轮；真仓用例验证当前状态
findings ⊆ baseline（已知债务挂账 #867，新违规 CI 红）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import retirement_gate as rg  # noqa: E402


def _seed(root: Path, files: dict) -> None:
    for rel, body in files.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")


def test_gate_finds_retired_regex_copy_in_fixture():
    root = ROOT / "tests" / "_tmp_gate861" / "case1"
    _seed(root, {
        "hooks/lib_kunglao.py": "DISPATCH_RE = re.compile(r'x')\n",
        "scripts/other.py": "x = DISPATCH_RE\n",
    })
    r = rg.scan(root, [])
    keys = [k for k in r["findings"] if k.startswith("retired_regex_copy")]
    assert any(k.endswith("scripts/other.py") for k in keys), r
    import shutil
    shutil.rmtree(root.parent, ignore_errors=True)


def test_gate_allows_owner_and_twin():
    root = ROOT / "tests" / "_tmp_gate861" / "case2"
    _seed(root, {
        "hooks/lib_kunglao.py": "DISPATCH_RE = re.compile(r'x')\n",
        "scripts/lib_kunglao.py": "DISPATCH_RE = re.compile(r'x')\n",
        "scripts/clean.py": "print('no token here')\n",
    })
    r = rg.scan(root, [])
    assert not [k for k in r["findings"] if k.startswith("retired_regex_copy")], r
    import shutil
    shutil.rmtree(root.parent, ignore_errors=True)


def test_gate_flags_deprecated_module_with_live_caller():
    root = ROOT / "tests" / "_tmp_gate861" / "case3"
    _seed(root, {
        "scripts/legacy_mod.py": "DEPRECATED = True\n",
        "scripts/caller.py": "import legacy_mod\n",
    })
    r = rg.scan(root, [])
    assert "deprecated_live_caller:legacy_mod<-scripts/caller.py" in r["findings"], r
    import shutil
    shutil.rmtree(root.parent, ignore_errors=True)


def test_gate_ratchet_baseline_hides_known_debt():
    root = ROOT / "tests" / "_tmp_gate861" / "case4"
    _seed(root, {
        "scripts/legacy_mod.py": "DEPRECATED = True\n",
        "scripts/caller.py": "import legacy_mod\n",
    })
    base = ["deprecated_live_caller:legacy_mod<-scripts/caller.py"]
    r = rg.scan(root, base)
    assert r["ok"] is True and r["new_findings"] == [], r
    import shutil
    shutil.rmtree(root.parent, ignore_errors=True)


def test_gate_new_finding_blocks():
    root = ROOT / "tests" / "_tmp_gate861" / "case5"
    _seed(root, {
        "scripts/legacy_mod.py": "DEPRECATED = True\n",
        "scripts/caller.py": "import legacy_mod\n",
        "scripts/new_caller.py": "from legacy_mod import thing\n",
    })
    base = ["deprecated_live_caller:legacy_mod<-scripts/caller.py"]
    r = rg.scan(root, base)
    assert r["ok"] is False
    assert r["new_findings"] == [
        "deprecated_live_caller:legacy_mod<-scripts/new_caller.py"], r
    import shutil
    shutil.rmtree(root.parent, ignore_errors=True)


def test_real_repo_findings_within_baseline():
    """真仓状态：#867 已清偿挂账债务 → 零 findings、基线空。

    原 #861 状态钉（findings == [priority<-external_kicker]）随 #867 收口
    （external_kicker 改走 priority_ratio）一并翻转：任何 finding 都是
    新违规（NEW），不得再入基线。"""
    baseline_path = ROOT / "scripts" / ".retirement-gate-baseline.txt"
    baseline = [ln.strip() for ln in
                baseline_path.read_text(encoding="utf-8").splitlines()
                if ln.strip()] if baseline_path.exists() else []
    r = rg.scan(ROOT, baseline)
    assert r["ok"] is True, r
    assert r["findings"] == [], (
        "#867 cleared the last baselined debt; a finding here is NEW — "
        f"retire it, never re-baseline silently: {r['findings']}")
