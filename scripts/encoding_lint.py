#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""encoding_lint.py — #811 裸 IO 编码扫描器（AST 版，多行/嵌套鲁棒）。

扫描生产 IO 面（scripts/ hooks/ tools/ templates/ 递归 .py），统计无
encoding 的文本 IO 调用：
  - Path.write_text / Path.read_text 无 encoding 关键字
  - open() 文本模式（mode 不含 'b'）无 encoding 关键字
  - subprocess.run/Popen/check_output/check_call 带 text=True 无 encoding

用途：#811 sweep 清零后挂为机械门（新增 bare 调用即非零退出，防复发）。
fail-closed：解析失败的文件计入 ERROR（不静默放行）。

豁免：SKIP_FILES 按文件名豁免（migrate_facts.py = 用户文件，#811 批次
约定跳过），豁免项单独计数上报（不算残留）。

用法：
  python scripts/encoding_lint.py            # 扫描生产面，残留>0 exit 1
  python scripts/encoding_lint.py --json     # 机读输出
  python scripts/encoding_lint.py --path DIR # 扫描任意目录（测试用）
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ["scripts", "hooks", "tools", "templates"]
SKIP_FILES = {
    # #811 批次约定：用户 WIP 文件跳过（proposal 豁免记录）
    "migrate_facts.py",
}
SUBPROC_FUNCS = {"run", "Popen", "check_output", "check_call"}


def _flag_call(node: ast.Call) -> str | None:
    """返回违规形态标签，合规返回 None。"""
    f = node.func
    # Path.write_text / read_text
    if isinstance(f, ast.Attribute) and f.attr in ("write_text", "read_text"):
        if not any(kw.arg == "encoding" for kw in node.keywords):
            return f.attr
        return None
    # open() 文本模式
    if isinstance(f, ast.Name) and f.id == "open":
        mode = "r"
        has_binary = False
        for a in node.args[1:2]:
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                mode = a.value
                has_binary = "b" in mode
        if any(kw.arg == "mode" for kw in node.keywords):
            return None  # mode 由变量传入——无法静态判定，不误报
        if has_binary:
            return None
        if not any(kw.arg == "encoding" for kw in node.keywords):
            return "open-no-encoding"
        return None
    # subprocess text=True
    if isinstance(f, ast.Attribute) and f.attr in SUBPROC_FUNCS and \
            isinstance(f.value, ast.Name) and f.value.id == "subprocess":
        has_text = any(kw.arg == "text" and
                       getattr(kw.value, "value", None) is True
                       for kw in node.keywords)
        if has_text and not any(kw.arg == "encoding" for kw in node.keywords):
            return "subprocess-text-no-encoding"
    return None


def scan_file(path: Path) -> tuple[list[dict], list[str]]:
    """返回 (violations, errors)。解析失败 → errors。"""
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except (OSError, SyntaxError, ValueError) as exc:
        return [], [f"{path}: parse error: {type(exc).__name__}"]
    out: list[dict] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            kind = _flag_call(node)
            if kind:
                out.append({"file": str(path), "line": node.lineno,
                            "kind": kind})
    return out, []


def scan_scope(root: Path = ROOT, scan_dirs=None) -> dict:
    scan_dirs = scan_dirs or SCAN_DIRS
    violations: list[dict] = []
    errors: list[str] = []
    scanned = 0
    for d in scan_dirs:
        base = root / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if p.name in SKIP_FILES:
                continue
            scanned += 1
            v, e = scan_file(p)
            violations.extend(v)
            errors.extend(e)
    return {"residue": len(violations), "violations": violations,
            "errors": errors, "scanned": scanned,
            "exempted": ["scripts/migrate_facts.py"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--path", default=None,
                    help="扫描指定目录（默认生产面，测试用）")
    args = ap.parse_args()
    if args.path:
        r = scan_scope(Path(args.path), ["."])
        r.pop("exempted", None)
    else:
        r = scan_scope()
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(f"scanned={r['scanned']} residue={r['residue']} "
              f"errors={len(r['errors'])} "
              f"exempted={len(r.get('exempted', []))}")
        for v in r["violations"][:40]:
            print(f"  {v['file']}:{v['line']} {v['kind']}")
        for e in r["errors"]:
            print(f"  ERR {e}")
    if r["residue"] > 0 or r["errors"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
