# -*- coding: utf-8 -*-
"""Contract tests for scripts/report_render.py — the report/console
rendering face of the toolchain (guidance metadata, fix text, next
actions) and its pairing with toolchain_install."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import mcp_probe  # noqa: E402
import report_render  # noqa: E402
import toolchain  # noqa: E402
import toolchain_install  # noqa: E402


def test_render_module_owns_the_five_members():
    for name in ("ToolMeta", "FIXES", "fix_text", "NEXT_ACTION_VERBS",
                 "NextAction"):
        assert hasattr(report_render, name), name


def test_toolchain_shares_the_same_objects():
    """toolchain composes the render module: the names resolve to the very
    same objects (one definition, imported — not a copy)."""
    assert toolchain.FIXES is report_render.FIXES
    assert toolchain.ToolMeta is report_render.ToolMeta
    assert toolchain.NextAction is report_render.NextAction
    assert toolchain.fix_text is report_render.fix_text
    assert toolchain.NEXT_ACTION_VERBS is report_render.NEXT_ACTION_VERBS


def test_toolchain_install_pairs_with_report_render():
    assert (toolchain_install.toolchain.FIXES is report_render.FIXES)
    assert (toolchain_install.toolchain.NextAction is report_render.NextAction)


def test_fix_text_known_and_unknown():
    assert report_render.fix_text("pefile") == "pip install pefile"
    assert report_render.fix_text("no-such-item-xyz") is None


def test_fixes_is_structured_metadata():
    meta = report_render.FIXES["jadx"]
    assert meta.fix == "install jadx and add it to PATH"
    assert meta.package == "jadx"
    assert str(meta) == meta.fix  # the string face renders the guidance text


def test_mcp_entries_derived_from_manifest():
    for item in mcp_probe.MANIFEST:
        assert f"mcp:{item.name}" in report_render.FIXES


def test_next_action_vocabulary_is_closed():
    assert "install" in report_render.NEXT_ACTION_VERBS
    with __import__("pytest").raises(ValueError):
        report_render.NextAction("bogus-verb")


def test_ports_single_sourced_in_render_module():
    # the render module is the DEFINITION site; toolchain imports it
    # (value pin — a reload elsewhere may rebind fresh int objects)
    assert toolchain.FRIDA_PORT == report_render.FRIDA_PORT
    assert (toolchain.ANDROID_SERVER_PORT
            == report_render.ANDROID_SERVER_PORT)
    tc_src = (SCRIPTS / "toolchain.py").read_text(encoding="utf-8")
    assert "FRIDA_PORT = " not in tc_src, "port must not be redefined locally"
    assert "ANDROID_SERVER_PORT = " not in tc_src
    assert "from report_render import" in tc_src


def test_parse_port_defensive():
    assert report_render.parse_port(None, 1337) == 1337
    assert report_render.parse_port("abc", 1337) == 1337
    assert report_render.parse_port("0", 1337) == 1337
    assert report_render.parse_port("70000", 1337) == 1337
    assert report_render.parse_port(" 8080 ", 1337) == 8080
