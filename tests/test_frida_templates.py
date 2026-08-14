# -*- coding: utf-8 -*-
"""#278 P3 — templates/frida CFG 模板契约测试.

RED 断言（模板落地前应全红）:
  (a) cfg-hook.js.tmpl 占位符集合恰为 5 个规定键, 无其他 {{...}} 键;
      cfg-analyze.py.tmpl 占位符集合恰为 3 个规定键
  (b) 全参数替换后的 hook 是括号平衡的 JS 骨架（字符串/注释剥离 + 计数器,
      非 JS 解析器）
  (c) cfg-analyze.py.tmpl 用合成 trace fixture 替换后, 以 venv python 运行:
      edges.csv 去重且按 (caller,target) 字典序排序; summary.md 含 top caller
  (d) analyzer 两次运行（仅 header started_ts 不同）输出逐字节一致, 且
      summary.md 不含 started_ts（#277 无时间戳契约, 对真实 hook header
      形状生效）
  (e) templates/frida/README.md 含 VM-only 警告 + 硬禁令 #5
  (f) 三个模板文件不含宿主绝对路径与真实 IP

契约口径:
  * hook 记录字段 = caller(返回地址)/target/args_count/thread_id/ts,
    与 analyzer 输入字段(caller/target/ts + 可选扩展)一致
  * analyzer 输出 edges.csv(header caller,target,calls) + summary.md,
    Top callers 节每行格式 `- <caller>: <n> calls`
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRIDA_DIR = ROOT / "templates" / "frida"

HOOK_TMPL = FRIDA_DIR / "cfg-hook.js.tmpl"
ANALYZE_TMPL = FRIDA_DIR / "cfg-analyze.py.tmpl"
README = FRIDA_DIR / "README.md"

HOOK_PLACEHOLDERS = {"TARGET_MODULE", "TARGET_EXPORTS", "CALL_DEPTH", "OUTFILE", "SAMPLE_SHA256"}
ANALYZE_PLACEHOLDERS = {"TRACE_FILE", "SAMPLE_SHA256", "OUT_DIR"}

_PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")
_ABS_PATH = re.compile(r"(?:[A-Za-z]:\\|/(?:Users|home|tmp|opt|var|etc)/)")
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")

SAMPLE_SHA = "aa" * 32


# ---------- helpers ----------

def _render(text: str, **params: str) -> str:
    """单遍替换所有 {{KEY}} 占位符（未提供的键原样保留）。"""
    return _PLACEHOLDER.sub(lambda m: params.get(m.group(1), m.group(0)), text)


def _placeholder_keys(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def _strip_js_strings_and_comments(text: str) -> str:
    """剥离单/双/反引号字符串与行/块注释（简易状态机, 非 JS 解析器）。"""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if ch == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if ch in ("'", '"', "`"):
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == ch:
                    j += 1
                    break
                j += 1
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _is_balanced(text: str) -> bool:
    """括号/花括号/方括号计数平衡（字符串与注释已剥离）。"""
    stack: list[str] = []
    pairs = {")": "(", "}": "{", "]": "["}
    for ch in _strip_js_strings_and_comments(text):
        if ch in "({[":
            stack.append(ch)
        elif ch in ")}]":
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack


def _run_analyzer(script: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        check=False,
    )


def _write_fixture_trace(path: Path, started_ts: int = 1000) -> None:
    """合成 trace (JSON lines): header + caller/target/ts + 扩展字段.

    header 与真实 hook 形状一致——cfg-hook.js.tmpl 必写 started_ts;
    该时间戳不得泄漏进 analyzer 输出（#277 无时间戳契约）。
    """
    lines = [
        {"header": {"sample_sha256": SAMPLE_SHA, "target_module": "sample.dll",
                    "call_depth": 5, "started_ts": started_ts}},
        {"caller": "0x7ffa1111", "target": "ExportA", "args_count": 2, "thread_id": 11, "ts": 1000},
        {"caller": "0x7ffa2222", "target": "ExportA", "args_count": 3, "thread_id": 11, "ts": 1001},
        {"caller": "0x7ffa2222", "target": "ExportB", "args_count": 1, "thread_id": 12, "ts": 1002},
        {"caller": "0x7ffa1111", "target": "ExportB", "args_count": 2, "thread_id": 11, "ts": 1003},
        {"caller": "0x7ffa2222", "target": "ExportA", "args_count": 1, "thread_id": 11, "ts": 1004},
        {"caller": "0x7ffa3333", "target": "ExportA", "args_count": 0, "thread_id": 13, "ts": 1005},
        {"caller": "0x7ffa2222", "target": "ExportC", "args_count": 2, "thread_id": 12, "ts": 1006},
    ]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")


# ---------- (a) placeholder contract ----------

def test_hook_placeholders_exactly_five_specified_keys():
    """(a) cfg-hook.js.tmpl 占位符集合恰为规定的 5 个键, 无其他 {{...}}."""
    text = HOOK_TMPL.read_text(encoding="utf-8")
    assert _placeholder_keys(text) == HOOK_PLACEHOLDERS


def test_analyzer_placeholders_exactly_three_specified_keys():
    """(a 扩展) cfg-analyze.py.tmpl 占位符集合恰为规定的 3 个键."""
    text = ANALYZE_TMPL.read_text(encoding="utf-8")
    assert _placeholder_keys(text) == ANALYZE_PLACEHOLDERS


# ---------- (b) substituted hook sanity ----------

def test_substituted_hook_balanced_and_no_leftover(tmp_path: Path):
    """(b) 全参数替换后: 无残留占位符, 括号/花括号/方括号平衡."""
    rendered = _render(
        HOOK_TMPL.read_text(encoding="utf-8"),
        TARGET_MODULE="sample.dll",
        TARGET_EXPORTS="ExportA,ExportB,ExportC",
        CALL_DEPTH="5",
        OUTFILE=str(tmp_path / "trace.jsonl"),
        SAMPLE_SHA256=SAMPLE_SHA,
    )
    assert "{{" not in rendered, "substitution left placeholder residue"
    assert _is_balanced(rendered), "hook JS skeleton has unbalanced delimiters"


# ---------- (c) analyzer end-to-end ----------

def test_analyzer_edges_sorted_and_summary_top_caller(tmp_path: Path):
    """(c) 替换后运行: edges.csv 去重+字典序, summary.md 含 top caller."""
    trace = tmp_path / "trace.jsonl"
    _write_fixture_trace(trace)
    out_dir = tmp_path / "out"
    script = tmp_path / "cfg-analyze.py"
    script.write_text(
        _render(
            ANALYZE_TMPL.read_text(encoding="utf-8"),
            TRACE_FILE=str(trace),
            SAMPLE_SHA256=SAMPLE_SHA,
            OUT_DIR=str(out_dir),
        ),
        encoding="utf-8",
    )

    result = _run_analyzer(script)
    assert result.returncode == 0, f"analyzer failed: {result.stderr}"

    edges_csv = out_dir / "edges.csv"
    assert edges_csv.is_file(), "edges.csv not written"
    rows = edges_csv.read_text(encoding="utf-8").splitlines()
    assert rows[0] == "caller,target,calls"
    data = [tuple(row.split(",")) for row in rows[1:]]
    assert len(data) == len(set(data)), "duplicate caller->callee edge rows"
    assert data == sorted(data), "edges.csv not sorted by (caller, target)"

    summary = (out_dir / "summary.md").read_text(encoding="utf-8")
    # fixture: caller 0x7ffa2222 共 4 次调用, 为 top caller
    assert "- 0x7ffa2222: 4 calls" in summary, "summary.md missing top caller line"
    assert SAMPLE_SHA in summary


# ---------- (d) determinism ----------

def test_analyzer_deterministic_byte_identical(tmp_path: Path):
    """(d) 同一 trace 两次采集、仅 header started_ts 不同 → 输出逐字节一致,
    且 summary.md 不含 started_ts（真实 hook header 形状下的无时间戳契约）."""
    trace = tmp_path / "trace.jsonl"
    script = tmp_path / "cfg-analyze.py"
    script.write_text(
        _render(
            ANALYZE_TMPL.read_text(encoding="utf-8"),
            TRACE_FILE=str(trace),
            SAMPLE_SHA256=SAMPLE_SHA,
            OUT_DIR=str(tmp_path / "OUT"),
        ),
        encoding="utf-8",
    )

    outputs: list[dict[str, bytes]] = []
    for started_ts in (1000, 2000):
        _write_fixture_trace(trace, started_ts=started_ts)
        result = _run_analyzer(script)
        assert result.returncode == 0, f"analyzer run failed: {result.stderr}"
        out_dir = tmp_path / "OUT"
        outputs.append({
            "edges": (out_dir / "edges.csv").read_bytes(),
            "summary": (out_dir / "summary.md").read_bytes(),
        })
    assert outputs[0] == outputs[1], "started_ts leaked into outputs (not deterministic)"
    assert "started_ts" not in (tmp_path / "OUT" / "summary.md").read_text(encoding="utf-8"), \
        "summary.md contains started_ts (violates #277 no-timestamp rule)"


# ---------- (e) README VM-only warning ----------

def test_readme_vm_only_warning_and_prohibition(tmp_path: Path):
    """(e) README.md 含 VM-only 警告与硬禁令 #5."""
    del tmp_path  # 无文件系统副作用, 纯文本断言
    text = README.read_text(encoding="utf-8")
    assert "硬禁令 #5" in text, "README missing hard prohibition #5 mention"
    assert "仅限 VM" in text and "宿主" in text, "README missing VM-only channel warning"


# ---------- (f) no host paths / real IPs ----------

@pytest.mark.parametrize("path", [HOOK_TMPL, ANALYZE_TMPL, README])
def test_templates_have_no_host_absolute_paths_or_real_ips(path: Path):
    """(f) 模板不含宿主绝对路径与真实 IP（VM 参数由占位符/<> 表示）."""
    text = path.read_text(encoding="utf-8")
    assert not _ABS_PATH.search(text), f"{path.name} contains a host absolute path"
    assert not _IP.search(text), f"{path.name} contains a real IPv4 address"
