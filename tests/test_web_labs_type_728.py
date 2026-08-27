# -*- coding: utf-8 -*-
"""RED tests for #728 — web (labs) project type: type registration, camoufox
MCP supply, docker-default channel, CLAUDE.md template + quick reference,
setup/init handlers, toolchain WARN-only face, wakaru/webcrack provider
registration, references/SKILL doc wiring.

Contract source: openspec/changes/issue-728-web-labs-type/specs/web-labs-type/spec.md
Upstream verification date: 2026-08-26 (camoufox-reverse-mcp README v1.1.0,
wakaru README 1.10.0, webcrack README 2.16.0 — execution-verified --version).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import importlib.util  # noqa: E402

import init_state  # noqa: E402
import mcp_probe  # noqa: E402
import toolchain  # noqa: E402


def _load_init():
    """Load kunglao-init.py as a module (hyphen filename, no package)."""
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_web_labs", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# --- camoufox-reverse-mcp tool names verified against the upstream README
# (35 tools, v1.1.0; refresh = re-fetch + edit this constant).
VERIFIED_CAMOUFOX_TOOLS = frozenset({
    "launch_browser", "close_browser", "navigate", "reload",
    "take_screenshot", "take_snapshot", "click", "type_text", "wait_for",
    "get_page_info", "evaluate_js", "scripts", "search_code",
    "hook_function", "inject_hook_preset", "remove_hooks",
    "get_console_logs", "network_capture", "list_network_requests",
    "get_network_request", "get_request_initiator", "intercept_request",
    "hook_jsvmp_interpreter", "instrumentation", "compare_env", "cookies",
    "get_storage", "export_state", "import_state", "verify_signer_offline",
    "check_environment", "reset_browser_state", "trace_property_access",
    "list_trace_files", "query_trace_file",
})

# Preset names verified from the upstream README (inject_hook_preset face).
VERIFIED_CAMOUFOX_PRESETS = frozenset({
    "xhr", "fetch", "crypto", "websocket", "debugger_bypass", "cookie",
    "runtime_probe",
})

# Non-MCP snake_case tokens allowed in web docs (kunglao/env vocabulary).
GENERIC_SNAKE_ALLOWLIST = frozenset({
    "kunglao_channel", "kunglao_init", "web_labs", "web_re", "analysis_state",
    "network_capture", "type_web", "pre_inject", "search_code",
    "function_path", "hook_code", "pre_inject_hooks", "request_id",
    "camoufox_reverse_mcp",
})

QUICKREF = ROOT / "references" / "re-library" / "web-re-quickref.md"
QUICKREF_SECTIONS = (
    "Hook & breakpoint quick reference",
    "Signed-parameter location workflow",
    "Obfuscation recognition and layered peeling",
    "Crypto-algorithm signatures",
    "Anti-patterns",
    "Advanced topics",
)
OPS_CARD_TOOLS = ("get_request_initiator", "inject_hook_preset",
                  "verify_signer_offline")


# ---------- 1. type union ----------

def test_web_in_type_unions():
    assert "web" in init_state.VALID_TYPES
    assert "web" in toolchain.VALID_TYPES


def test_init_marker_accepts_web(tmp_path):
    rec = init_state.write_init_marker(
        tmp_path, state_hash="x" * 64, project_type="web", seed_count=0)
    assert rec["project_type"] == "web"


# ---------- 2. MCP manifest ----------

def test_camoufox_manifest_entry():
    item = mcp_probe._BY_NAME["camoufox-reverse"]
    assert item.tier == "WARN"
    assert item.types == ("web",)
    assert "python -m camoufox_reverse_mcp" in item.register
    assert mcp_probe.MANIFEST_GROUPS["web_labs"] == ["camoufox-reverse"]


def test_scaffold_json_carries_web_labs_group():
    manifest = mcp_probe.build_scaffold_json()["mcp_manifest"]
    assert "web_labs" in manifest
    assert [e["name"] for e in manifest["web_labs"]] == ["camoufox-reverse"]


def test_no_hard_manifest_item_applies_to_web():
    hard = [i.name for i in mcp_probe.MANIFEST
            if i.tier == "HARD" and "web" in i.types]
    assert hard == [], f"web must carry zero HARD MCP items, got {hard}"


def test_desktop_entries_pin_to_desktop_triple():
    desktop = ("windows", "linux", "android")
    for name in ("ghidra", "sequential-thinking", "ida-pro-vm", "virustotal"):
        assert mcp_probe._BY_NAME[name].types == desktop, name


def test_web_mcp_check_is_never_hard_fail():
    checks = [c for c in mcp_probe.check_mcp(ROOT, "web")
              if c.name == "camoufox-reverse"]
    assert checks and checks[0].tier == "WARN"
    assert checks[0].status in ("PASS", "WARN", "FAIL")  # FAIL is WARN-tier


# ---------- 3. CLAUDE.md web template ----------

def _web_section() -> str:
    return _load_init().os_section("web")


def test_web_os_section_constraints_and_tree():
    section = _web_section()
    assert "## Hard constraints (web)" in section
    assert "docker" in section.lower()
    assert "camoufox-reverse" in section
    # decision tree skeleton: solution patterns A-E
    for marker in ("A", "B", "C", "D", "E"):
        assert re.search(rf"\*\*{marker}:", section), marker


def test_web_os_section_ops_card_tools():
    section = _web_section()
    for tool in OPS_CARD_TOOLS:
        assert tool in section, tool


def test_os_section_unknown_type_still_empty():
    kunglao_init = _load_init()
    assert kunglao_init.os_section(None) == ""
    assert kunglao_init.os_section("bogus") == ""


def test_write_claudemd_web_injects_quickref(tmp_path):
    kunglao_init = _load_init()
    out = kunglao_init.write_claudemd(
        tmp_path, "site.js", "0" * 64, project_type="web")
    assert out is not None
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    for title in QUICKREF_SECTIONS:
        assert title in text, title
    # site-experience note pointer (case-template mapping)
    assert "site_" in text


def test_write_claudemd_web_missing_quickref_fails_closed(tmp_path, monkeypatch):
    kunglao_init = _load_init()
    monkeypatch.setattr(kunglao_init, "WEB_RE_QUICKREF",
                        tmp_path / "missing.md")
    with pytest.raises(Exception):
        kunglao_init.write_claudemd(
            tmp_path, "site.js", "0" * 64, project_type="web")


def test_web_docs_mention_only_verified_camoufox_tools():
    docs = _web_section() + QUICKREF.read_text(encoding="utf-8")
    snake = set(re.findall(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b", docs))
    unknown = {t for t in snake
               if t not in VERIFIED_CAMOUFOX_TOOLS
               and t not in VERIFIED_CAMOUFOX_PRESETS
               and t not in GENERIC_SNAKE_ALLOWLIST}
    assert unknown == set(), f"unverified camoufox tool names: {sorted(unknown)}"


# ---------- 4. quick reference file ----------

def test_quickref_six_sections_present():
    text = QUICKREF.read_text(encoding="utf-8")
    for title in QUICKREF_SECTIONS:
        assert f"## {title}" in text, title


def test_quickref_english_only():
    text = QUICKREF.read_text(encoding="utf-8")
    cjk = [ch for ch in text if "一" <= ch <= "鿿"]
    assert not cjk, f"CJK characters leaked: {cjk[:5]}"


def test_quickref_layered_peeling_routing():
    text = QUICKREF.read_text(encoding="utf-8")
    assert "wakaru" in text and "webcrack" in text
    assert "Peel in order" in text          # principle 1
    assert "exit early" in text             # principle 1
    assert "boundary" in text               # principle 2 (VM boundary)


def test_quickref_workflow_five_steps_and_paths():
    text = QUICKREF.read_text(encoding="utf-8")
    for step in ("Step 1", "Step 2", "Step 3", "Step 4", "Step 5"):
        assert step in text, step
    assert "instrument" in text             # Path A (four-tool tracing)
    assert "emulation" in text              # Path B (environment emulation)


def test_quickref_crypto_signature_table():
    text = QUICKREF.read_text(encoding="utf-8")
    for marker in ("MD5", "SHA-1", "SHA-256", "Base64", "AES", "HMAC"):
        assert marker in text, marker


# ---------- 5. setup handler / channel default ----------

def test_setup_web_env_writes_channel_default(tmp_path, capsys):
    kunglao_init = _load_init()
    (tmp_path / "analysis_state.txt").write_text(
        "project_type=web\n", encoding="utf-8")
    kunglao_init._setup_web_env(tmp_path)
    state = (tmp_path / "analysis_state.txt").read_text(encoding="utf-8")
    assert "KUNGLAO_CHANNEL=docker" in state
    out = capsys.readouterr().out + capsys.readouterr().err
    # idempotent: second call must not duplicate the line
    kunglao_init._setup_web_env(tmp_path)
    state2 = (tmp_path / "analysis_state.txt").read_text(encoding="utf-8")
    assert state2.count("KUNGLAO_CHANNEL=") == 1


def test_setup_web_env_never_overwrites_existing_channel(tmp_path):
    kunglao_init = _load_init()
    (tmp_path / "analysis_state.txt").write_text(
        "project_type=web\nKUNGLAO_CHANNEL=ssh\n", encoding="utf-8")
    kunglao_init._setup_web_env(tmp_path)
    state = (tmp_path / "analysis_state.txt").read_text(encoding="utf-8")
    assert "KUNGLAO_CHANNEL=ssh" in state
    assert state.count("KUNGLAO_CHANNEL=") == 1


# ---------- 6. toolchain WARN-only face ----------

def test_toolchain_web_has_no_hard_items():
    report = toolchain.check(ROOT, "web")
    hard = [i for i in report.items if i.tier == toolchain.Tier.HARD]
    assert hard == []
    names = [i.name for i in report.items]
    assert "channel:docker" in names
    assert any(n.startswith("mcp:camoufox") for n in names)


def test_toolchain_web_docker_absent_is_warn(tmp_path, monkeypatch):
    monkeypatch.setattr(toolchain.shutil, "which", lambda *_: None)
    report = toolchain.check(tmp_path, "web")
    docker = [i for i in report.items if i.name == "channel:docker"]
    assert docker and docker[0].tier == toolchain.Tier.WARN
    assert docker[0].status == toolchain.Status.WARN
    assert report.overall_status != toolchain.Status.FAIL


def test_toolchain_rejects_unknown_type():
    with pytest.raises(ValueError):
        toolchain.check(ROOT, "bogus")


# ---------- 7. CLI + guidance strings ----------

def test_init_cli_accepts_type_web():
    kunglao_init = _load_init()
    args = kunglao_init.parse_args(["ws", "--type", "web"])
    assert args.type == "web"


def test_init_cli_rejects_bogus_type():
    kunglao_init = _load_init()
    with pytest.raises(SystemExit):
        kunglao_init.parse_args(["ws", "--type", "bogus"])


def test_guidance_strings_list_web():
    # #760 sync: the type enum grew macos across every guidance face.
    for path, needle in (
        (SCRIPTS / "kunglao-init.py", "--type windows|linux|android|web"),
        (SCRIPTS / "kunglao_resume.py", "--type windows|linux|android|web"),
        (ROOT / "hooks" / "env_check_gate.py",
        "--type <windows|linux|android|web|macos>"),
        (SCRIPTS / "init_state.py", "--type <windows|linux|android|web"),
    ):
        assert needle in path.read_text(encoding="utf-8"), path.name


# ---------- 8. wakaru / webcrack provider registration ----------

def _index_entries():
    data = yaml.safe_load((ROOT / "tools" / "_INDEX.yaml").read_text(
        encoding="utf-8"))
    return data["tools"]


def test_wakaru_webcrack_index_entries():
    by_provider = {t.get("provider"): t for t in _index_entries()
                   if t.get("provider")}
    wakaru = by_provider["wakaru"]
    assert wakaru["capability"] == "js:unbundle"
    assert wakaru["quality"] == {"js:unbundle": "high"}
    webcrack = by_provider["webcrack"]
    assert webcrack["capability"] == "js:deobfuscate"
    assert webcrack["quality"] == {"js:deobfuscate": "high"}


def test_wakaru_webcrack_fixes_toolmeta():
    for key, package in (("wakaru", "wakaru"), ("webcrack", "webcrack")):
        meta = toolchain.FIXES[key]
        assert meta.package == package
        assert meta.url and "github.com" in meta.url
        assert meta.verify_cmd and "--version" in meta.verify_cmd
        assert "npx" in meta.verify_cmd or package in meta.verify_cmd


def test_index_yaml_validates():
    import subprocess
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "validate_index.py")],
        capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr


# ---------- 9. doc wiring ----------

def test_references_index_has_web_labs_domain():
    text = (ROOT / "references" / "_INDEX.md").read_text(encoding="utf-8")
    assert "web-labs" in text
    assert "_index-web-labs.md" in text


def test_web_labs_domain_index_exists():
    idx = ROOT / "references" / "_index-web-labs.md"
    assert idx.exists()
    assert "web-re-quickref.md" in idx.read_text(encoding="utf-8")


def test_references_index_yaml_pinned():
    pins = yaml.safe_load(
        (ROOT / "references" / "_INDEX.yaml").read_text(encoding="utf-8"))
    files = pins.get("files", {})
    assert "references/_index-web-labs.md" in files
    assert "references/re-library/web-re-quickref.md" in files


def test_skill_md_lists_web():
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "--type windows|linux|android|web" in text
    assert "camoufox" in text
