# -*- coding: utf-8 -*-
"""js_env_diagnose — Node-VM sandbox env-diagnosis pins (synthetic targets).

Each target pin checks one diagnostic face: missing browser globals are
reported as undefined_paths, prelude stubs suppress the miss, console
output is captured, sandbox timeouts are results (not tool errors), and
tool-level breakage (no node binary, missing target) fails loudly.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "web" / "js_env_diagnose.py"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node binary not on PATH")

TARGET_READS_DOCUMENT = "var t = document.title;\n"
TARGET_CLEAN = "var c = console; var x = 1 + 1;\n"
TARGET_CONSOLE = "console.log('hello diag');\n"
TARGET_SYNTAX_ERROR = "var x = ;\n"
TARGET_INFINITE = "while (true) {}\n"

PRELUDE_DOCUMENT = "globalThis.document = { title: 'stub' };\n"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=120)


def _diag(tmp_path: Path, target: str, *extra: str,
          name: str = "target.js") -> dict:
    p = tmp_path / name
    p.write_text(target, encoding="utf-8")
    r = _run("--target", str(p), *extra)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_missing_document_is_reported(tmp_path: Path) -> None:
    out = _diag(tmp_path, TARGET_READS_DOCUMENT)
    assert out["success"] is False
    assert "document" in out["undefined_paths"]
    assert "TypeError" in (out["error"] or "")


def test_prelude_stub_suppresses_the_miss(tmp_path: Path) -> None:
    prelude = tmp_path / "prelude.js"
    prelude.write_text(PRELUDE_DOCUMENT, encoding="utf-8")
    out = _diag(tmp_path, TARGET_READS_DOCUMENT, "--prelude", str(prelude))
    assert out["success"] is True
    assert out["undefined_paths"] == []


def test_clean_target_succeeds_with_no_paths(tmp_path: Path) -> None:
    out = _diag(tmp_path, TARGET_CLEAN)
    assert out["success"] is True
    assert out["undefined_paths"] == []
    assert out["error"] is None


def test_console_output_captured(tmp_path: Path) -> None:
    out = _diag(tmp_path, TARGET_CONSOLE)
    assert any("hello diag" in " ".join(entry)
               for entry in out["console_tail"])


def test_access_stats_counters_present(tmp_path: Path) -> None:
    out = _diag(tmp_path, TARGET_CLEAN)
    stats = out["access_stats"]
    assert set(stats) == {"get", "set", "has", "construct"}
    assert stats["get"] > 0  # the sandbox itself property-probes


def test_syntax_error_is_a_result_not_a_crash(tmp_path: Path) -> None:
    out = _diag(tmp_path, TARGET_SYNTAX_ERROR)
    assert out["success"] is False
    assert "SyntaxError" in (out["error"] or "")


def test_sandbox_timeout_is_a_result(tmp_path: Path) -> None:
    out = _diag(tmp_path, TARGET_INFINITE, "--timeout-ms", "500")
    assert out["success"] is False
    assert "timed out" in (out["error"] or "").lower()


def test_missing_target_fails_loud(tmp_path: Path) -> None:
    r = _run("--target", str(tmp_path / "nope.js"))
    assert r.returncode == 2
    assert r.stderr.strip()


def test_missing_node_binary_fails_loud(tmp_path: Path) -> None:
    p = tmp_path / "target.js"
    p.write_text(TARGET_CLEAN, encoding="utf-8")
    r = _run("--target", str(p), "--node", str(tmp_path / "no-such-node"))
    assert r.returncode == 2
    assert "node" in r.stderr.lower()


def test_empty_target_fails_loud(tmp_path: Path) -> None:
    p = tmp_path / "empty.js"
    p.write_text("", encoding="utf-8")
    r = _run("--target", str(p))
    assert r.returncode == 2
    assert r.stderr.strip()


def test_help_carries_examples() -> None:
    r = _run("--help")
    assert r.returncode == 0
    assert "Examples:" in r.stdout
    assert "python tools/web/js_env_diagnose.py" in r.stdout
