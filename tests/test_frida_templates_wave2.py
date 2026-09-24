# -*- coding: utf-8 -*-
"""Wave-2 frida template consistency pins.

Each new template must (1) be documented in templates/frida/README.md with
its required params, (2) fully substitute via the documented {{KEY}} keys,
and (3) produce syntactically valid JavaScript after substitution
(node --check; skipped when no node binary is on PATH).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FRIDA = ROOT / "templates" / "frida"
README = (FRIDA / "README.md").read_text(encoding="utf-8")

NEW_TEMPLATES = [
    ("dex-dump-art.js.tmpl",
     {"OUT_DIR": "/sdcard/dump", "SAMPLE_SHA256": "a" * 64,
      "MIN_DEX_BYTES": "4096"}),
    ("android-bypass-phase1.js.tmpl",
     {"ENABLE_ROOT": "1", "ENABLE_EMULATOR": "0", "ENABLE_PROXY": "0",
      "ENABLE_SSL": "1", "ENABLE_DEBUG": "0"}),
]

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node --check needs a node binary")


@pytest.mark.parametrize("name,params", NEW_TEMPLATES)
def test_template_documented_with_params(name: str, params: dict) -> None:
    assert name in README, f"{name} missing from frida README"
    for key in params:
        assert key in README, f"{name} param {key} missing from README"


@pytest.mark.parametrize("name,params", NEW_TEMPLATES)
def test_template_substitutes_to_valid_js(name: str, params: dict) -> None:
    src = (FRIDA / name).read_text(encoding="utf-8")
    out = src
    for key, value in params.items():
        out = out.replace("{{" + key + "}}", value)
    leftovers = re.findall(r"\{\{[A-Z_]+\}\}", out)
    assert not leftovers, f"{name}: unsubstituted placeholders {leftovers}"
    with tempfile.TemporaryDirectory() as td:
        js = Path(td) / name.replace(".tmpl", "")
        js.write_text(out, encoding="utf-8")
        check = subprocess.run(["node", "--check", str(js)],
                               capture_output=True, text=True)
        assert check.returncode == 0, check.stderr


def test_dex_dump_uses_java_bridge_not_bare_java() -> None:
    """node --check is syntax-only and cannot catch Frida-bridge mistakes;
    pin the known bug class: bare lowercase `java.` in CODE is not a Frida
    global (the bridge object is `Java.`). Quoted class-name strings like
    Java.use('java.io.File') are legitimate and excluded."""
    src = (FRIDA / "dex-dump-art.js.tmpl").read_text(encoding="utf-8")
    code_only = re.sub(r"'[^']*'", "''", src)
    bare = re.findall(r"(?<![A-Za-z0-9_.$''])java\.\w", code_only)
    assert not bare, f"bare java. usage (not a Frida global): {bare}"


def test_dex_dump_java_path_shares_dedup_contract() -> None:
    """The README/header claim 'dedups by size+checksum' must hold on BOTH
    dump paths: the Java path computes the same size:checksum key and
    consults the same `dumped` map as the native path."""
    src = (FRIDA / "dex-dump-art.js.tmpl").read_text(encoding="utf-8")
    assert src.count("dumped[key]") >= 2, (
        "both dump paths must consult the shared dumped[key] map")
    assert "checksum: null" not in src, (
        "manifest entries must carry the real checksum")
    assert "bytes[8] & 0xff" in src, (
        "java path must reassemble the header checksum for the dedup key")
