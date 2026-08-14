# -*- coding: utf-8 -*-
"""tests/test_decompile_context.py — issue #306: ghidra-decompile-functions
--context mode (kong analyzer.py:208-348 technique, fresh implementation).

The context document assembles, per address target, the decompiled C alongside
caller/callee ~10-line snippets, xref'd strings and already-recovered names
into one JSON object.  Default (non-context) output must stay unchanged.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GHIDRA_DIR = ROOT / "tools" / "ghidra"
sys.path.insert(0, str(GHIDRA_DIR))

import run_ghidra_postscript as rp  # noqa: E402


def _lines(n: int) -> str:
    return "\n".join(f"    line{i + 1}" for i in range(n))


def make_artifact(*, with_context: bool = True) -> dict:
    """Synthetic DecompileFunctions.java output in the ghidra_decompile.v1 shape."""
    target = {
        "kind": "address",
        "address": "0x140001000",
        "function": "FUN_140001000",
        "entry": "0x140001000",
        "end": "0x140001080",
        "body_ranges": 1,
        "symbols": ["FUN_140001000 [FUNCTION]"],
        "decompiled_c": "void FUN_140001000(void) {\n  uVar1 = uVar1 - (uVar1 / 10) * 10;\n}\n",
        "disasm_window": "  0x140001000: ...\n",
    }
    if with_context:
        target["context"] = {
            "callers": [
                {"address": "0x140002000", "function": "FUN_140002000",
                 "snippet": _lines(15)},   # >10 lines: doc must cap
                {"address": "0x140002100", "function": "RecvLoop",   # recovered name
                 "snippet": _lines(4)},
            ],
            "callees": [
                {"address": "0x140003000", "function": "FUN_140003000",
                 "snippet": _lines(6)},
            ],
            "xref_strings": [
                {"address": "0x14000a000", "value": "config.ini"},
                {"address": "0x14000a010", "value": "GET /"},
            ],
            "recovered_names": [
                {"address": "0x140002100", "name": "RecvLoop"},
            ],
        }
    return {
        "schema": "ghidra_decompile.v1",
        "program": "sample.exe",
        "image_base": "0x140000000",
        "target_count": 1,
        "targets": [target],
    }


class TestBuildContextDocument:
    def test_doc_combines_decompilation_and_context(self):
        doc = rp.build_context_document(make_artifact())
        assert doc["schema"] == "ghidra_context.v1"
        assert doc["program"] == "sample.exe"
        assert doc["image_base"] == "0x140000000"
        t = doc["targets"][0]
        assert "uVar1" in t["decompiled_c"]
        assert t["context"]["callers"][0]["function"] == "FUN_140002000"
        assert t["context"]["callees"][0]["function"] == "FUN_140003000"
        assert {"address": "0x14000a000", "value": "config.ini"} \
            in t["context"]["xref_strings"]
        assert t["context"]["recovered_names"][0]["name"] == "RecvLoop"

    def test_snippets_capped_at_ten_lines(self):
        doc = rp.build_context_document(make_artifact())
        snippet = doc["targets"][0]["context"]["callers"][0]["snippet"]
        assert len(snippet.splitlines()) == 10

    def test_document_renders_llm_ready_sections(self):
        doc = rp.build_context_document(make_artifact())
        text = doc["targets"][0]["document"]
        assert "Target Function" in text
        assert "Decompilation" in text
        assert "Called Functions" in text
        assert "Calling Functions" in text
        assert "Referenced Strings" in text
        assert '"config.ini"' in text
        assert "Recovered Names" in text
        assert "RecvLoop" in text

    def test_target_without_context_degrades_to_empty_sections(self):
        artifact = make_artifact(with_context=False)
        doc = rp.build_context_document(artifact)
        t = doc["targets"][0]
        assert t["context"]["callers"] == []
        assert t["context"]["callees"] == []
        assert t["context"]["xref_strings"] == []
        assert t["context"]["recovered_names"] == []
        assert "Decompilation" in t["document"]

    def test_string_targets_pass_through_unchanged(self):
        artifact = {
            "schema": "ghidra_decompile.v1",
            "program": "sample.exe",
            "image_base": "0x140000000",
            "target_count": 1,
            "targets": [{"kind": "string", "query": "http",
                         "hits": [{"address": "0x14000b000", "value": "http://"}]}],
        }
        doc = rp.build_context_document(artifact)
        assert doc["targets"][0]["kind"] == "string"
        assert doc["targets"][0]["hits"][0]["value"] == "http://"
        assert "context" not in doc["targets"][0]

    def test_missing_targets_key_raises(self):
        with pytest.raises(ValueError):
            rp.build_context_document({"schema": "ghidra_decompile.v1"})


class TestWrapperBackwardCompat:
    def _fake_run(self, artifact: dict):
        def _run(cmd, **kwargs):
            for arg in cmd:
                if arg.startswith("--out="):
                    Path(arg[len("--out="):]).write_text(
                        json.dumps(artifact), encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        return _run

    def _ghidra_env(self, tmp: Path) -> Path:
        ghidra_home = tmp / "ghidra"
        (ghidra_home / "support").mkdir(parents=True)
        (ghidra_home / "support" / "analyzeHeadless.bat").write_text(
            "@echo off\n", encoding="utf-8")
        return ghidra_home

    def test_default_output_unchanged_without_context(self, tmp, capsys,
                                                      monkeypatch):
        # Backward compat: no --context -> artifact line only, no context doc.
        ghidra_home = self._ghidra_env(tmp)
        binary = tmp / "sample.exe"
        binary.write_bytes(b"MZ")
        out = tmp / "decompile.json"
        monkeypatch.setattr("subprocess.run",
                            self._fake_run(make_artifact(with_context=False)))
        rc = rp.main(["--tool", "ghidra-decompile-functions", "--binary", str(binary),
                      "--out", str(out), "--ghidra-home", str(ghidra_home),
                      "--addresses", "0x140001000"],
                     environ={})
        assert rc == 0
        captured = capsys.readouterr()
        assert "artifact:" in captured.out
        assert "ghidra_context" not in captured.out

    def test_context_flag_emits_context_document(self, tmp, capsys, monkeypatch):
        ghidra_home = self._ghidra_env(tmp)
        binary = tmp / "sample.exe"
        binary.write_bytes(b"MZ")
        out = tmp / "decompile.json"
        monkeypatch.setattr("subprocess.run", self._fake_run(make_artifact()))
        rc = rp.main(["--tool", "ghidra-decompile-functions", "--binary", str(binary),
                      "--out", str(out), "--ghidra-home", str(ghidra_home),
                      "--addresses", "0x140001000", "--context"],
                     environ={})
        assert rc == 0
        captured = capsys.readouterr()
        assert "ghidra_context.v1" in captured.out
        assert "RecvLoop" in captured.out


class TestJavaSourceGainsContext:
    def test_decompile_functions_java_has_context_mode(self):
        text = (GHIDRA_DIR / "DecompileFunctions.java").read_text(encoding="utf-8")
        assert "--context" in text
        for key in ("\"callers\"", "\"callees\"", "\"xref_strings\"",
                    "\"recovered_names\"", "\"snippet\""):
            assert key in text, f"DecompileFunctions.java missing {key}"
        # Default-mode fields unchanged (backward compat at source level).
        for key in ("\"decompiled_c\"", "\"disasm_window\"", "\"kind\""):
            assert key in text

    def test_wrapper_forwards_context_flag(self):
        pairs = rp.split_forwarded(["--addresses", "0x140001000", "--context"])
        assert ("context", "true") in pairs
