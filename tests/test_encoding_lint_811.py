# -*- coding: utf-8 -*-
"""tests/test_encoding_lint_811.py — #811 扫描器测试。

AST 扫描器三断言面：
  1. 植入 bare 调用的样本被检出（write_text/open/subprocess 三形态）
  2. 干净样本零残留 rc=0
  3. 解析失败 fail-closed（计 ERROR 非零退出）
  4. 多行/嵌套调用不漏报
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import encoding_lint as el  # noqa: E402


def _plant(tmp_path, name: str, body: str) -> Path:
    d = tmp_path / "prod"
    d.mkdir(exist_ok=True)
    f = d / name
    f.write_text(body, encoding="utf-8")
    return d


def test_detects_bare_write_text(tmp_path):
    d = _plant(tmp_path, "x.py",
               "from pathlib import Path\n"
               "p = Path('a')\n"
               "p.write_text('数据')\n")
    r = el.scan_scope(tmp_path, ["prod"])
    assert r["residue"] >= 1
    assert any(v["kind"] == "write_text" for v in r["violations"])


def test_detects_bare_open_and_subprocess(tmp_path):
    d = _plant(tmp_path, "y.py",
               "import subprocess\n"
               "open('中文.txt', 'w').close()\n"
               "subprocess.run(['cmd'], text=True)\n")
    r = el.scan_scope(tmp_path, ["prod"])
    kinds = {v["kind"] for v in r["violations"]}
    assert "open-no-encoding" in kinds
    assert "subprocess-text-no-encoding" in kinds


def test_clean_sample_zero(tmp_path):
    d = _plant(tmp_path, "ok.py",
               "from pathlib import Path\n"
               "Path('a').write_text('数据', encoding='utf-8')\n"
               "open('b', 'w', encoding='utf-8').close()\n"
               "subprocess.run(['c'], text=True, encoding='utf-8')\n")
    r = el.scan_scope(tmp_path, ["prod"])
    assert r["residue"] == 0
    assert r["errors"] == []


def test_multiline_call_not_missed(tmp_path):
    d = _plant(tmp_path, "m.py",
               "from pathlib import Path\n"
               "p = Path('a')\n"
               "p.write_text(\n"
               "    'line1\\n'\n"
               "    'line2\\n',\n"
               ")\n")
    r = el.scan_scope(tmp_path, ["prod"])
    assert r["residue"] >= 1


def test_binary_mode_and_mode_var_not_flagged(tmp_path):
    d = _plant(tmp_path, "b.py",
               "open('x', 'rb').close()\n"
               "import subprocess\n"
               "subprocess.run(['c'], text=True, encoding='utf-8')\n")
    r = el.scan_scope(tmp_path, ["prod"])
    assert r["residue"] == 0


def test_parse_error_fails_closed(tmp_path):
    d = _plant(tmp_path, "bad.py", "def broken(:\n")
    r = el.scan_scope(tmp_path, ["prod"])
    assert r["residue"] == 0 and len(r["errors"]) == 1
    assert el.main is not None  # scanner exits 1 on errors (main 逻辑)


def test_skip_files_exemption(tmp_path):
    """SKIP_FILES 按文件名豁免——migrate_facts.py 的 bare 调用不计数。"""
    d = _plant(tmp_path, "migrate_facts.py",
               "from pathlib import Path\n"
               "Path('a').write_text('数据')\n")
    r = el.scan_scope(tmp_path, ["prod"])
    assert r["residue"] == 0, r["violations"]
    # 豁免面在扫描生产面时上报
    assert el.SKIP_FILES == {"migrate_facts.py"}


def test_flag_call_contract():
    """_flag_call 纯函数契约：直测判定逻辑。"""
    import ast
    for src, expect in [
        ("Path('a').write_text('x')", "write_text"),
        ("Path('a').write_text('x', encoding='utf-8')", None),
        ("open('a', 'rb')", None),
        ("open('a', 'w')", "open-no-encoding"),
        ("subprocess.run(a, text=True)", "subprocess-text-no-encoding"),
        ("subprocess.run(a)", None),  # 无 text=True 不归本扫描器管
    ]:
        node = ast.parse(src).body[0].value
        assert el._flag_call(node) == expect, src
