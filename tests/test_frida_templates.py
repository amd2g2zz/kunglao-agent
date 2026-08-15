# -*- coding: utf-8 -*-
"""#278 P3 — templates/frida CFG template contract tests.

RED assertions (all red before the templates land):
  (a) cfg-hook.js.tmpl placeholder set is exactly the 5 specified keys, no
      other {{...}} keys; cfg-analyze.py.tmpl placeholder set is exactly the
      3 specified keys
  (b) the fully-substituted hook is a bracket-balanced JS skeleton
      (string/comment stripping + counters, not a JS parser)
  (c) cfg-analyze.py.tmpl, substituted with a synthetic trace fixture and run
      under the venv python: edges.csv deduplicated and sorted
      lexicographically by (caller,target); summary.md contains top caller
  (d) two analyzer runs (differing only in header started_ts) produce
      byte-identical output, and summary.md contains no started_ts (#277
      no-timestamp contract, effective against the real hook header shape)
  (e) templates/frida/README.md carries the VM-only warning + hard
      prohibition #5
  (f) the three template files contain no host absolute paths or real IPs

Contract:
  * hook record fields = caller (return address) / target / args_count /
    thread_id / ts, consistent with the analyzer input fields
    (caller/target/ts + optional extensions)
  * analyzer output edges.csv (header caller,target,calls) + summary.md,
    Top callers section one line per entry: `- <caller>: <n> calls`
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
    """Single-pass substitution of all {{KEY}} placeholders (unprovided keys kept verbatim)."""
    return _PLACEHOLDER.sub(lambda m: params.get(m.group(1), m.group(0)), text)


def _placeholder_keys(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def _strip_js_strings_and_comments(text: str) -> str:
    """Strip single/double/backtick strings and line/block comments (simple state machine, not a JS parser)."""
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
    """Bracket/brace/bracket counts balance (strings and comments already stripped)."""
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
    """Synthetic trace (JSON lines): header + caller/target/ts + extensions.

    The header matches the real hook shape — cfg-hook.js.tmpl always writes
    started_ts; that timestamp must not leak into the analyzer output (#277
    no-timestamp contract).
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
    """(a) cfg-hook.js.tmpl placeholder set is exactly the 5 specified keys, no other {{...}}."""
    text = HOOK_TMPL.read_text(encoding="utf-8")
    assert _placeholder_keys(text) == HOOK_PLACEHOLDERS


def test_analyzer_placeholders_exactly_three_specified_keys():
    """(a extended) cfg-analyze.py.tmpl placeholder set is exactly the 3 specified keys."""
    text = ANALYZE_TMPL.read_text(encoding="utf-8")
    assert _placeholder_keys(text) == ANALYZE_PLACEHOLDERS


# ---------- (b) substituted hook sanity ----------

def test_substituted_hook_balanced_and_no_leftover(tmp_path: Path):
    """(b) after full substitution: no leftover placeholders; brackets/braces/brackets balance."""
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
    """(c) run after substitution: edges.csv deduplicated + lexicographic; summary.md contains top caller."""
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
    # fixture: caller 0x7ffa2222 has 4 calls total — the top caller
    assert "- 0x7ffa2222: 4 calls" in summary, "summary.md missing top caller line"
    assert SAMPLE_SHA in summary


# ---------- (d) determinism ----------

def test_analyzer_deterministic_byte_identical(tmp_path: Path):
    """(d) same trace collected twice, differing only in header started_ts → byte-identical output,
    and summary.md contains no started_ts (no-timestamp contract under the real hook header shape)."""
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
    """(e) README.md carries the VM-only warning and hard prohibition #5."""
    del tmp_path  # no filesystem side effects — pure text assertions
    text = README.read_text(encoding="utf-8")
    assert "hard prohibition #5" in text, "README missing hard prohibition #5 mention"
    assert "VM channel only" in text and "host" in text, "README missing VM-only channel warning"


# ---------- (f) no host paths / real IPs ----------

@pytest.mark.parametrize("path", [HOOK_TMPL, ANALYZE_TMPL, README])
def test_templates_have_no_host_absolute_paths_or_real_ips(path: Path):
    """(f) templates contain no host absolute paths or real IPs (VM params are placeholders/<...>)."""
    text = path.read_text(encoding="utf-8")
    assert not _ABS_PATH.search(text), f"{path.name} contains a host absolute path"
    assert not _IP.search(text), f"{path.name} contains a real IPv4 address"


# ---------- (g) Frida 17 API contract (#356 W5) ----------

def test_hook_uses_frida17_module_api():
    """(#356 W5) cfg-hook.js.tmpl must not use the Frida-16-only
    two-argument Module.getExportByName(mod, name) — the project baseline
    is frida >= 17, where the form is
    Process.getModuleByName(mod).getExportByName(name). Comments may
    mention the old API (explaining the migration); code may not."""
    text = HOOK_TMPL.read_text(encoding="utf-8")
    code = _strip_js_strings_and_comments(text)
    assert "Module.getExportByName(" not in code, \
        "Frida-16-only Module.getExportByName(mod, name) remains in code (#356 W5)"
    assert "Process.getModuleByName(" in code, \
        "Frida 17 form Process.getModuleByName(mod).getExportByName(name) missing"


def test_hook_keeps_null_safety_try_catch():
    """(#356 W5) the export lookup keeps its null-safety try/catch — a
    missing export must warn and skip, never crash the hook script."""
    text = HOOK_TMPL.read_text(encoding="utf-8")
    code = _strip_js_strings_and_comments(text)
    m = re.search(r"Process\.getModuleByName\(", code)
    assert m, "Frida 17 lookup not found (precondition)"
    # the lookup sits inside a try block with a catch that warns + returns
    try_block = code[max(0, m.start() - 400):m.end() + 600]
    assert "try {" in try_block and "catch" in try_block, \
        "export lookup must stay wrapped in try/catch null-safety"
    assert "console.warn" in text, "missing export must warn, not crash"


def test_hook_header_declares_frida17_requirement():
    """(#356 W5) header comment must state Requires: frida >= 17."""
    text = HOOK_TMPL.read_text(encoding="utf-8")
    header = text[:text.index("'use strict';")] if "'use strict';" in text else text[:2000]
    assert re.search(r"Requires:\s*frida\s*>=\s*17", header), \
        "header must declare 'Requires: frida >= 17'"
