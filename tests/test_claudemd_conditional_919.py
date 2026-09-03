# -*- coding: utf-8 -*-
"""Issue #49 / #919 — CLAUDE.md base template: type-conditional rendering.

User ruling: the base template rendered desktop-VM assumptions into EVERY
workspace — Android (adb device dynamics), web (browser dynamics) and the
labs macos type got the VM-only bullet, the VM env-var rows and binary-RE
MCP rows that do not apply (noise + cold-start misdirection). Also, the
identity line still framed the product as a "malware RE workspace", while
the ruled positioning is a general reverse-engineering expert (the task
domain is user input, not the product's scope).

Engine note: the repo renderer is the {{KEY}} single-pass engine
(scripts/template_render.py, frozen semantics, stdlib-only — there is no
jinja2 here). Conditionality therefore lives in DATA on the init side
(type-keyed tuples + the mcp_probe.MANIFEST filter feeding new template
slots), the same pattern as {{type_section}} — never if-elif chains in the
template.

Contracts pinned here:
  1. android render: zero VMware/VBox/x64dbg/VM-env vocabulary
  2. web render: zero VM-channel section, browser MCP row only
  3. windows render: the desktop contract survives byte-for-byte (anchor)
  4. linux render: VM channel + ssh row survive, android/web rows absent
  5. macos render: labs posture — no VM channel, manifest note row
  6. identity: zero task-enumeration positioning ("malware analysis" etc.)
  7. MCP rows are manifest-filtered data (union == MANIFEST, per-type ==
     item.types), displayed rows byte-pinned
  8. every type renders with zero leftover {{placeholder}} residue
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import types
from pathlib import Path

import pytest
from _factories import seed_bins

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TEMPLATES = ROOT / "templates"
BASE_TMPL = TEMPLATES / "CLAUDE.md.base.tmpl"
FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"

sys.path.insert(0, str(SCRIPTS))


def _load_init():
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_conditional", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_init(ws: Path, project_type: str) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws),
            "--type", project_type, "--skip-toolchain",
            "--host-exec-protection", "enabled",
            "--profile-root", str(ws.parent / "profile-root")]
    env = {k: v for k, v in os.environ.items() if k != FLAG_NAME}
    env[FLAG_NAME] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(argv, capture_output=True, text=True, timeout=120,
                          env=env, errors="replace")


@pytest.fixture
def init_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    seed_bins(ws)
    (ws / "runs").mkdir()
    return ws


def _rendered_claudemd(tmp_path: Path, project_type: str) -> str:
    ws = tmp_path / project_type
    seed_bins(ws)
    (ws / "runs").mkdir()
    r = _run_init(ws, project_type)
    assert r.returncode == 0, f"init {project_type} failed: {r.stderr}"
    return (ws / "CLAUDE.md").read_text(encoding="utf-8")


# ---------- 1/2. android + web: VM/binary-RE noise purged ----------

def test_android_render_has_no_vm_or_x64dbg_vocabulary(tmp_path):
    text = _rendered_claudemd(tmp_path, "android")
    for banned in ("VMware", "VBox", "vbox", "x64dbg",
                   "Dynamic tools VM-only", "KUNGLAO_VM_HOST",
                   "KUNGLAO_VM_SHELL_PORT", "KUNGLAO_FRIDA_PORT"):
        assert banned not in text, f"android CLAUDE.md carries VM artifact: {banned}"
    assert "adb" in text  # android contract anchor intact


def test_web_render_has_no_vm_section(tmp_path):
    text = _rendered_claudemd(tmp_path, "web")
    for banned in ("Dynamic tools VM-only", "KUNGLAO_VM_HOST",
                   "KUNGLAO_VM_SHELL_PORT", "KUNGLAO_FRIDA_PORT"):
        assert banned not in text, f"web CLAUDE.md carries VM artifact: {banned}"
    # browser MCP supply present; binary-RE MCP rows absent
    assert "| `camoufox-reverse` |" in text
    assert "| `ghidra` |" not in text
    assert "| `x64dbg` |" not in text


def test_android_render_mcp_rows_are_android_scoped(tmp_path):
    text = _rendered_claudemd(tmp_path, "android")
    assert "| `gitnexus` |" in text
    assert "| `ghidra` |" in text
    for absent in ("| `x64dbg` |", "| `volatility` |",
                   "| `camoufox-reverse` |", "| `ssh-mcp` |"):
        assert absent not in text, f"android MCP table keeps non-android row {absent}"


# ---------- 3/4/5. windows anchor + linux + macos ----------

def test_windows_render_keeps_desktop_vm_contract(tmp_path):
    text = _rendered_claudemd(tmp_path, "windows")
    assert "Dynamic tools VM-only" in text
    for env_row in ("KUNGLAO_VM_HOST", "KUNGLAO_VM_SHELL_PORT",
                    "KUNGLAO_FRIDA_PORT"):
        assert f"| `{env_row}` |" in text
    for mcp_row in ("| `ghidra` |", "| `sequential-thinking` |",
                    "| `x64dbg` |", "| `volatility` |",
                    "| `ida-pro-vm` |", "| `virustotal` |",
                    "| `ssh-mcp` |"):
        assert mcp_row in text, f"windows MCP anchor row missing: {mcp_row}"
    assert "| `gitnexus` |" not in text
    assert "| `camoufox-reverse` |" not in text


def test_linux_render_keeps_vm_contract_no_windows_rows(tmp_path):
    text = _rendered_claudemd(tmp_path, "linux")
    assert "Dynamic tools VM-only" in text
    assert "| `KUNGLAO_VM_HOST` |" in text
    assert "| `ssh-mcp` |" in text
    assert "| `x64dbg` |" not in text
    assert "| `gitnexus` |" not in text


def test_macos_render_is_labs_posture_no_vm_channel(tmp_path):
    text = _rendered_claudemd(tmp_path, "macos")
    assert "Dynamic tools VM-only" not in text
    assert "KUNGLAO_VM_HOST" not in text
    assert "NO VM channel" in text  # macos OS-section contract anchor
    assert "no MCP manifest members" in text


# ---------- 6. identity: RE expert, not task enumeration ----------

@pytest.mark.parametrize("project_type", ["windows", "android", "web"])
def test_identity_is_not_task_enumerated(tmp_path, project_type):
    text = _rendered_claudemd(tmp_path, project_type)
    for banned in ("malware RE workspace", "analyzing a malware sample",
                   "malware analysis"):
        assert banned not in text, \
            f"{project_type} identity still task-enumerates: {banned!r}"
    assert "reverse-engineering workspace" in text
    assert "not the product's scope" in text


# ---------- 7. MCP rows are manifest-filtered data ----------

def test_mcp_rows_union_equals_manifest():
    init = _load_init()
    import mcp_probe
    manifest_names = [i.name for i in mcp_probe.MANIFEST]
    union: list[str] = []
    for t in ("windows", "linux", "android", "web", "macos"):
        for line in init.mcp_rows(t).splitlines():
            m = re.match(r"^\| `([a-z0-9-]+)` \| (HARD|WARN) \|", line)
            if m:
                union.append(m.group(1))
    assert sorted(set(union)) == sorted(manifest_names)


def test_mcp_rows_per_type_match_manifest_types():
    init = _load_init()
    import mcp_probe
    for t in ("windows", "linux", "android", "web", "macos"):
        # Presentation order is golden-anchored (MCP_ROW_ORDER); membership
        # must equal the manifest filter for the type.
        applicable = {i.name for i in mcp_probe.MANIFEST if t in i.types}
        want = [n for n in init.MCP_ROW_ORDER if n in applicable]
        got = [m.group(1) for m in
               (re.match(r"^\| `([a-z0-9-]+)` \|(?: (HARD|WARN) \|)?", line)
                for line in init.mcp_rows(t).splitlines())
               if m and m.group(1)]
        assert got == want, f"mcp_rows({t}) drift: {got} != {want}"


def test_mcp_row_tiers_match_manifest():
    init = _load_init()
    import mcp_probe
    tiers = {i.name: i.tier for i in mcp_probe.MANIFEST}
    for name, row in init.MCP_ROW_TEXT.items():
        m = re.match(r"^\| `[a-z0-9-]+` \| (HARD|WARN) \|", row)
        assert m, f"MCP_ROW_TEXT[{name!r}] is not a table row"
        assert m.group(1) == tiers[name], f"tier drift for {name}"


def test_vm_conditional_helpers():
    init = _load_init()
    for vm_type in ("windows", "linux"):
        assert "VM-only" in init.vm_constraint_line(vm_type)
        assert "KUNGLAO_VM_HOST" in init.vm_env_rows(vm_type)
    for other in ("android", "web", "macos", None, "bogus"):
        assert init.vm_constraint_line(other) == ""
        assert init.vm_env_rows(other) == ""


# ---------- 8. template slots + render residue ----------

def test_base_template_carries_conditional_slots():
    text = BASE_TMPL.read_text(encoding="utf-8")
    for slot in ("{{vm_constraint_line}}", "{{mcp_rows}}", "{{vm_env_rows}}"):
        assert slot in text, f"base template missing conditional slot {slot}"


@pytest.mark.parametrize("project_type", ["windows", "linux", "android",
                                          "web", "macos"])
def test_rendered_claudemd_zero_placeholder_residue(tmp_path, project_type):
    import template_render
    init = _load_init()
    init.SKILL_DIR = Path("/kunglao/skill-sentinel")
    real_vi = sys.version_info
    import collections
    VI = collections.namedtuple("VI", "major minor micro release serial")
    monkey = pytest.MonkeyPatch()
    monkey.setattr(sys, "version_info", VI(3, 11, 0, "final", 0))
    try:
        ws = tmp_path / f"ws-{project_type}"
        seed_bins(ws, payload=b"MZ\x90\x00" + b"\x00" * 64)
        target = init.write_claudemd(ws, "sample.exe", "a" * 40,
                                     project_type=project_type)
    finally:
        monkey.setattr(sys, "version_info", real_vi)
        monkey.undo()
    text = target.read_text(encoding="utf-8")
    assert template_render.leftover_placeholders(text) == []

