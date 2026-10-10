# -*- coding: utf-8 -*-
"""Wave-2 distillation few-shot landing checks (mechanical checklist).

Landing places per the acceptance criteria:
  (a) every new CLI's --help carries an "Examples:" epilog with copyable
      `python tools/...` commands
  (b) every new tool is registered in tools/_INDEX.yaml with a contract
      entry (H3 + 6 segments) in its category index md
  (c) usage examples are appended to existing knowledge cards until the
      wave-1 distillate cards land (then those get a Tool section at
      merge-sync)
  (d) frida templates are documented in templates/frida/README.md
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

NEW_TOOLS = [
    ("cipher_identify", "crypto", "tools/crypto/cipher_identify.py"),
    ("js_obfuscation_detect", "web", "tools/web/js_obfuscation_detect.py"),
    ("js_env_diagnose", "web", "tools/web/js_env_diagnose.py"),
    ("sign_candidate_verify", "web", "tools/web/sign_candidate_verify.py"),
]

NEW_TEMPLATES = [
    ("dex-dump-art.js.tmpl",
     ["OUT_DIR", "SAMPLE_SHA256", "MIN_DEX_BYTES"]),
    ("android-bypass-phase1.js.tmpl",
     ["ENABLE_ROOT", "ENABLE_EMULATOR", "ENABLE_PROXY", "ENABLE_SSL",
      "ENABLE_DEBUG"]),
]


def _yaml_tools() -> list[dict]:
    data = yaml.safe_load((TOOLS / "_INDEX.yaml").read_text(encoding="utf-8"))
    return data["tools"]


def test_a_help_examples_for_every_new_tool() -> None:
    for name, category, rel in NEW_TOOLS:
        script = ROOT / rel
        r = subprocess.run([sys.executable, str(script), "--help"],
                           capture_output=True, text=True)
        assert r.returncode == 0, name
        assert "Examples:" in r.stdout, f"{name}: --help lacks Examples"
        assert f"python {rel}" in r.stdout, \
            f"{name}: --help lacks a copyable python {rel} command"


def test_b_index_registration_complete() -> None:
    tools = {t["name"]: t for t in _yaml_tools()}
    for name, category, rel in NEW_TOOLS:
        entry = tools.get(name)
        assert entry is not None, f"{name} missing from _INDEX.yaml"
        assert entry["category"] == category
        md = (TOOLS / f"_index-{category}.md").read_text(encoding="utf-8")
        assert re.search(rf"^### {re.escape(name)}\s*$", md, re.M), \
            f"{name} missing H3 contract entry in _index-{category}.md"
        for seg in ("Purpose", "Usage", "Inputs", "Outputs",
                    "exit code", "when_not"):
            assert f"- **{seg}**" in md, \
                f"{name} entry missing segment {seg}"
        assert (ROOT / rel).is_file()


def test_c_card_usage_examples_appended() -> None:
    routing = (ROOT / "references/re-library/patterns/vm/"
               "vm-deobfuscation-routing.md").read_text(encoding="utf-8")
    assert "tools/web/js_obfuscation_detect.py" in routing
    assert "tools/web/js_env_diagnose.py" in routing
    quickref = (ROOT / "references/re-library/web/labs/"
                "web-re-quickref.md").read_text(encoding="utf-8")
    assert "tools/crypto/cipher_identify.py" in quickref
    assert "tools/web/sign_candidate_verify.py" in quickref


def test_c_wave1_distillate_cards_carry_tool_sections() -> None:
    """Merge-sync completed: the wave-1 cards landed, and each
    card matching a wave-2 capability now carries a Tool section pointing
    at its registered CLI."""
    cards = ROOT / "references/re-library/web/external-distilled"
    env_stub = (cards / "external-env-stub-generation.md").read_text(
        encoding="utf-8")
    assert "## Tool section" in env_stub
    assert "tools/web/js_env_diagnose.py" in env_stub
    peel = (cards / "external-peel-ordering-family-adapters.md").read_text(
        encoding="utf-8")
    assert "## Tool section" in peel
    assert "tools/web/js_obfuscation_detect.py" in peel
    algo = (cards / "external-algorithm-recovery-chains.md").read_text(
        encoding="utf-8")
    assert "## Tool section" in algo
    assert "tools/crypto/cipher_identify.py" in algo
    delivery = (cards / "external-delivery-verification-gates.md").read_text(
        encoding="utf-8")
    assert "## Tool section" in delivery
    assert "tools/web/sign_candidate_verify.py" in delivery


def test_d_templates_documented() -> None:
    readme = (ROOT / "templates/frida/README.md").read_text(encoding="utf-8")
    for tmpl, params in NEW_TEMPLATES:
        assert tmpl in readme, f"{tmpl} not documented in frida README"
        for param in params:
            assert param in readme, \
                f"{tmpl} param {param} missing from frida README"
        tmpl_path = ROOT / "templates" / "frida" / tmpl
        assert tmpl_path.is_file()
