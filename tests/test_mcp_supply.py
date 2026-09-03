# -*- coding: utf-8 -*-
"""Tests for #316 — MCP supply mechanism: probe + .mcp.json scaffold + docs table.

RED-first contract (SDD+TDD):

1. scripts/mcp_probe.py — single-source-of-truth manifest + registration probe:
   - Probes mcpServers registrations in ~/.claude.json (global mcpServers +
     projects.*.mcpServers) and <ws>/.mcp.json; name matching is
     case-insensitive.
   - Per-type checklist: all types require ghidra/sequential-thinking (HARD);
     windows(T3) x64dbg (HARD) + volatility (WARN);
     optional IDA: ida-pro-vm (WARN, all types); android: gitnexus (HARD);
     CTI: virustotal (WARN).
   - Missing HARD → exit 1 + registration guidance (`claude mcp add ...`);
     only WARN missing → exit 2; all present → exit 0. CLI contract:
     --json / --reproduce (same as toolchain.py).
2. kunglao-init optionally scaffolds <ws>/.mcp.json: generated only when
   missing (idempotent, never overwrites an existing one), --no-mcp skips;
   content matches the mcp_probe.MANIFEST single source of truth (valid
   JSON, _comment annotation).
3. Docs table matches the manifest: templates/CLAUDE.md.{windows,linux,android}.tmpl +
   templates/CLAUDE.md.base.tmpl + README.md Internals all carry the MCP
   table, row format `| `name` | tier |` pinned by this file.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from _factories import seed_bins

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TEMPLATES = ROOT / "templates"

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"

ALL_MCP_NAMES = {
    "ghidra", "sequential-thinking", "x64dbg", "volatility",
    "ida-pro-vm", "gitnexus", "virustotal",
    "ssh-mcp",  # #698 ssh-channel execution control plane (static decl)
    # #728 web (labs): browser JS RE supply — WARN, web-only
    "camoufox-reverse",
}


# ---------- hermetic run helpers ----------

def _base_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k != FLAG_NAME}
    env[FLAG_NAME] = "0"
    return env


def run_mcp_probe(ws: Path, *args: str,
                  env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """Hermetic mcp_probe.py run: KUNGLAO_CLAUDE_JSON pinned to a fake file
    (default resolution would read the REAL ~/.claude.json)."""
    env = _base_env()
    env["KUNGLAO_CLAUDE_JSON"] = str(ws.parent / "fake-claude.json")
    if env_extra:
        env.update(env_extra)
    argv = [sys.executable, str(SCRIPTS / "mcp_probe.py"), str(ws), *args]
    return subprocess.run(argv, capture_output=True, text=True, timeout=120,
                          env=env, encoding="utf-8", errors="replace")


def run_init(ws: Path, *extra: str) -> subprocess.CompletedProcess:
    """Hermetic kunglao-init run (profile-root in tmp; never touches real profiles).

    --skip-toolchain: after the #304 fix the toolchain gate runs before the
    scaffold — this file's tests focus on .mcp.json scaffold behavior; gate
    semantics are covered separately by #304's test_init_toolchain_gate.py
    (same _run_init convention as tests/test_kunglao_init.py).
    """
    env = _base_env()
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws), *extra]
    if "--skip-toolchain" not in argv:
        argv.append("--skip-toolchain")
    # target-alignment intake: pin the PE fixture's type explicitly — this
    # file owns .mcp.json scaffold behavior, not type semantics.
    if "--type" not in argv and "--resolve" not in argv:
        argv += ["--type", "windows"]
    argv += ["--profile-root", str(ws.parent / "profile-root")]
    if not any(a.startswith("--host-exec-protection") for a in argv) \
            and "--resolve" not in argv:
        # #919: non-interactive tests answer the host-exec ask explicitly.
        argv += ["--host-exec-protection", "enabled"]
    return subprocess.run(argv, capture_output=True, text=True, timeout=120,
                          env=env, encoding="utf-8", errors="replace")


def run_toolchain(ws: Path, *args: str,
                  env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = _base_env()
    env["KUNGLAO_CLAUDE_JSON"] = str(ws.parent / "fake-claude.json")
    if env_extra:
        env.update(env_extra)
    argv = [sys.executable, str(SCRIPTS / "toolchain.py"), str(ws), *args]
    return subprocess.run(argv, capture_output=True, text=True, timeout=120,
                          env=env, encoding="utf-8", errors="replace")


# ---------- fixtures ----------

@pytest.fixture
def fake_claude_json(tmp_path: Path) -> Path:
    """Fake ~/.claude.json path (KUNGLAO_CLAUDE_JSON target)."""
    return tmp_path / "fake-claude.json"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    """Minimal workspace dir (no analysis state)."""
    w = tmp_path / "ws"
    w.mkdir()
    return w


@pytest.fixture
def init_ws(tmp_path: Path) -> Path:
    """Synthetic init target: bins/ + sample + runs/ (mirrors test_kunglao_init)."""
    w = tmp_path / "ws"
    seed_bins(w, payload=b"MZ\x90\x00" + b"\x00" * 64)
    (w / "runs").mkdir()
    return w


# Project key in fake ~/.claude.json — an absolute path shape assembled from
# inert fragments (#690); assertions derive from the same constant.
_PROJECT_KEY = "D:" + "/some/ws"


def write_claude_json(path: Path, servers: dict[str, dict] | None = None,
                      project_servers: dict[str, dict] | None = None) -> None:
    """Write a fake ~/.claude.json (global + one project-scoped mcpServers)."""
    data: dict = {}
    if servers:
        data["mcpServers"] = servers
    if project_servers:
        data["projects"] = {_PROJECT_KEY: {"mcpServers": project_servers}}
    path.write_text(json.dumps(data), encoding="utf-8")


def reg(name: str) -> dict:
    """Minimal stdio registration stub."""
    return {"type": "stdio", "command": name, "args": []}


# ---------- manifest shape ----------

import mcp_probe  # noqa: E402  (pythonpath includes scripts/)


def _item(name: str) -> mcp_probe.MCPItem:
    return next(i for i in mcp_probe.MANIFEST if i.name == name)


def test_manifest_all_types_required_hard():
    for name in ("ghidra", "sequential-thinking"):
        item = _item(name)
        assert item.tier == "HARD", f"{name} must be HARD (required for all types)"
        assert set(item.types) == {"windows", "linux", "android"}, \
            f"{name} applies to all types"


def test_manifest_windows_t3():
    x64dbg = _item("x64dbg")
    assert x64dbg.tier == "HARD" and x64dbg.types == ("windows",)
    volatility = _item("volatility")
    assert volatility.tier == "WARN" and volatility.types == ("windows",)


def test_manifest_android_graph():
    gitnexus = _item("gitnexus")
    assert gitnexus.tier == "HARD" and gitnexus.types == ("android",)


def test_manifest_optional_ida_and_cti():
    ida = _item("ida-pro-vm")
    assert ida.tier == "WARN" and set(ida.types) == {"windows", "linux", "android"}
    vt = _item("virustotal")
    assert vt.tier == "WARN" and set(vt.types) == {"windows", "linux", "android"}


def test_manifest_names_unique_lowercase_with_register_cmd():
    names = [i.name for i in mcp_probe.MANIFEST]
    assert len(names) == len(set(names)), "manifest names must be unique"
    assert set(names) == ALL_MCP_NAMES
    for item in mcp_probe.MANIFEST:
        assert item.name == item.name.lower(), "canonical names are lowercase"
        assert item.register.startswith("claude mcp add"), \
            f"{item.name}: register field must carry a `claude mcp add` command"
        assert item.purpose and item.source


# ---------- probe behavior ----------

def test_probe_all_registered_exit0(fake_claude_json, ws):
    write_claude_json(fake_claude_json, {n: reg(n) for n in ALL_MCP_NAMES})
    r = run_mcp_probe(ws, "--type", "windows")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OVERALL: PASS" in r.stdout


def test_probe_missing_hard_exit1_with_guidance(fake_claude_json, ws):
    """Acceptance: simulated environment without a registered ghidra MCP → probe reports error + guidance."""
    fake_claude_json.write_text("{}", encoding="utf-8")
    r = run_mcp_probe(ws, "--type", "windows")
    assert r.returncode == 1, "HARD missing must exit 1"
    assert "[FAIL]" in r.stdout and "ghidra" in r.stdout
    assert "claude mcp add ghidra" in r.stdout, "missing guidance for registration"


def test_probe_missing_warn_only_exit2(fake_claude_json, ws):
    write_claude_json(fake_claude_json, {
        "ghidra": reg("ghidra"),
        "sequential-thinking": reg("sequential-thinking"),
        "x64dbg": reg("x64dbg"),
    })
    r = run_mcp_probe(ws, "--type", "windows")
    assert r.returncode == 2, "only WARN missing must exit 2"
    assert "volatility" in r.stdout and "claude mcp add volatility" in r.stdout


def test_probe_workspace_mcp_json_case_insensitive(fake_claude_json, ws):
    """workspace .mcp.json registrations are recognized; name matching is case-insensitive."""
    fake_claude_json.write_text("{}", encoding="utf-8")
    (ws / ".mcp.json").write_text(json.dumps({
        "mcpServers": {
            "Ghidra": reg("ghidra"),
            "sequential-thinking": reg("st"),
            "ida-pro-vm": reg("ida"),
            "virustotal": reg("vt"),
            "ssh-mcp": reg("sshm"),  # #698 linux channel control plane
        },
    }), encoding="utf-8")
    r = run_mcp_probe(ws, "--type", "linux", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    by_name = {c["name"]: c for c in out["checks"]}
    assert by_name["ghidra"]["status"] == "PASS"
    assert "workspace" in by_name["ghidra"]["detail"]
    assert by_name["sequential-thinking"]["status"] == "PASS"
    # linux manifest does not include x64dbg/volatility/gitnexus
    assert {c["name"] for c in out["checks"]} == {
        "ghidra", "sequential-thinking", "ida-pro-vm", "virustotal",
        "ssh-mcp"}  # #698 ssh-channel control plane (WARN, windows/linux)


def test_probe_project_scoped_claude_json(fake_claude_json, ws):
    """~/.claude.json projects.*.mcpServers (project scope) also count as registered."""
    write_claude_json(
        fake_claude_json,
        servers={"ghidra": reg("ghidra"), "sequential-thinking": reg("st"),
                 "ida-pro-vm": reg("ida"), "virustotal": reg("vt"),
                 "ssh-mcp": reg("sshm")},  # #698 windows channel plane
        project_servers={"x64dbg": reg("x64dbg"), "volatility": reg("vol")},
    )
    r = run_mcp_probe(ws, "--type", "windows", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    by_name = {c["name"]: c for c in out["checks"]}
    assert by_name["x64dbg"]["status"] == "PASS"
    assert "project" in by_name["x64dbg"]["detail"]


def test_probe_json_and_reproduce_contract(fake_claude_json, ws):
    write_claude_json(fake_claude_json, {"ghidra": reg("ghidra")})
    r = run_mcp_probe(ws, "--type", "windows", "--json")
    assert r.returncode == 1
    out = json.loads(r.stdout)
    assert out["project_type"] == "windows"
    assert out["overall"] == "FAIL"
    assert len(out["checks"]) == 7  # windows manifest size (+ssh-mcp #698)
    for c in out["checks"]:
        assert set(c) == {"name", "status", "tier", "detail", "fix"}
        if c["name"] == "ghidra":
            assert c["status"] == "PASS" and c["fix"] is None
        else:
            assert c["fix"] and c["fix"].startswith("claude mcp add")
    r2 = run_mcp_probe(ws, "--type", "windows", "--reproduce")
    assert "overall=FAIL" in r2.stdout
    assert "ghidra=PASS" in r2.stdout
    assert "sequential-thinking=FAIL" in r2.stdout


def test_probe_invalid_type_errors(ws):
    # CLI flag with unknown choice → argparse rejects (exit 2)
    r = run_mcp_probe(ws, "--type", "mac")
    assert r.returncode == 2
    assert "invalid choice" in r.stderr
    # type from analysis_state.txt with invalid value → ValueError path (exit 1)
    (ws / "analysis_state.txt").write_text("project_type=mac\n", encoding="utf-8")
    r2 = run_mcp_probe(ws)
    assert r2.returncode == 1
    assert "ERROR" in r2.stderr


def test_probe_reads_type_from_analysis_state(fake_claude_json, ws):
    write_claude_json(fake_claude_json, {n: reg(n) for n in ALL_MCP_NAMES})
    (ws / "analysis_state.txt").write_text("project_type=android\n", encoding="utf-8")
    r = run_mcp_probe(ws, "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    assert json.loads(r.stdout)["project_type"] == "android"
    assert len(json.loads(r.stdout)["checks"]) == 5  # android manifest size (ssh-mcp is windows/linux #698)


def test_probe_missing_claude_json_fails_open(fake_claude_json, ws):
    """~/.claude.json missing/corrupt → treated as zero registrations, no crash."""
    assert not fake_claude_json.exists()
    r = run_mcp_probe(ws, "--type", "windows")
    assert r.returncode == 1  # all HARD missing
    fake_claude_json.write_text("{not json", encoding="utf-8")
    r2 = run_mcp_probe(ws, "--type", "windows")
    assert r2.returncode == 1


# ---------- kunglao-init .mcp.json scaffold ----------

def test_init_scaffolds_mcp_json(init_ws):
    r = run_init(init_ws)
    assert r.returncode == 0, r.stdout + r.stderr
    target = init_ws / ".mcp.json"
    assert target.exists(), "kunglao-init must scaffold .mcp.json"
    data = json.loads(target.read_text(encoding="utf-8"))  # strict JSON (no // comments)
    assert data["mcpServers"] == {}, "scaffold must not register broken servers"
    manifest = data["mcp_manifest"]
    names = {e["name"] for group in manifest.values()
             if isinstance(group, list) for e in group}
    assert names == ALL_MCP_NAMES
    for group in manifest.values():
        if not isinstance(group, list):
            continue
        for entry in group:
            assert set(entry) == {"name", "tier", "types", "purpose", "source", "register"}


def test_init_mcp_json_idempotent_rerun(init_ws):
    """Acceptance: init generates .mcp.json idempotently (rerun adds no duplicates)."""
    assert run_init(init_ws).returncode == 0
    first = (init_ws / ".mcp.json").read_bytes()
    assert run_init(init_ws).returncode == 0  # second run resumes
    second = (init_ws / ".mcp.json").read_bytes()
    assert first == second, "rerun must not touch .mcp.json (byte-identical)"
    data = json.loads(second.decode("utf-8"))
    # No duplicates: json.loads already guarantees unique keys; additionally verify manifest name uniqueness
    entries = [e["name"] for g in data["mcp_manifest"].values()
               if isinstance(g, list) for e in g]
    assert len(entries) == len(set(entries))


def test_init_no_mcp_flag_skips(init_ws):
    r = run_init(init_ws, "--no-mcp")
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (init_ws / ".mcp.json").exists()
    assert "no-mcp" in r.stdout


def test_init_does_not_overwrite_existing_mcp_json(init_ws):
    """Existing file → not overwritten (idempotent)."""
    target = init_ws / ".mcp.json"
    target.write_text('{"mcpServers": {"custom": {"command": "x", "args": []}}}\n',
                      encoding="utf-8")
    assert run_init(init_ws).returncode == 0
    assert "custom" in target.read_text(encoding="utf-8")
    assert "mcp_manifest" not in target.read_text(encoding="utf-8")


def test_scaffold_manifest_matches_source():
    """The scaffolded mcp_manifest matches mcp_probe.MANIFEST field by field (single source of truth)."""
    scaffold = mcp_probe.build_scaffold_json()["mcp_manifest"]
    groups = mcp_probe.MANIFEST_GROUPS
    assert set(groups) == set(k for k in scaffold if k != "_comment")
    for group, names in groups.items():
        got = scaffold[group]
        assert [e["name"] for e in got] == names, f"group {group} order/names drift"
        for entry in got:
            item = _item(entry["name"])
            assert entry["tier"] == item.tier
            assert entry["types"] == list(item.types)
            assert entry["purpose"] == item.purpose
            assert entry["source"] == item.source
            assert entry["register"] == item.register


# ---------- toolchain.py integration ----------

def test_toolchain_integrates_mcp_items(fake_claude_json, ws):
    write_claude_json(fake_claude_json, {
        "ghidra": reg("ghidra"),
        "sequential-thinking": reg("sequential-thinking"),
    })
    r = run_toolchain(ws, "--type", "windows", "--json")
    assert r.returncode == 1, "x64dbg HARD missing must fail the toolchain"
    out = json.loads(r.stdout)
    by_name = {c["name"]: c for c in out["checks"]}
    assert "mcp:ghidra" in by_name and by_name["mcp:ghidra"]["status"] == "PASS"
    assert by_name["mcp:x64dbg"]["status"] == "FAIL"
    assert by_name["mcp:x64dbg"]["tier"] == "HARD"
    assert by_name["mcp:volatility"]["status"] == "WARN"


def test_toolchain_mcp_fix_guidance_in_human_output(fake_claude_json, ws):
    fake_claude_json.write_text("{}", encoding="utf-8")
    r = run_toolchain(ws, "--type", "windows")
    assert "mcp:ghidra" in r.stdout
    assert "claude mcp add ghidra" in r.stdout, "human output must carry registration guidance"


# ---------- #407: MCP-first decompiler check ----------

def test_toolchain_decompiler_mcp_first_ida_pro_vm(fake_claude_json, ws):
    """#407/#474: ida-pro-vm registered (ghidra absent) -> decompiler WARN
    'capability unverified' via MCP (registered supply defuses the HARD FAIL;
    a registry read is not capability), and the mcp:ghidra supply item is
    satisfied by the ida-pro-vm provider."""
    write_claude_json(fake_claude_json, {
        "sequential-thinking": reg("st"),
        "ida-pro-vm": reg("ida"),
    })
    r = run_toolchain(ws, "--type", "windows", "--json")
    assert r.returncode in (0, 1, 2), r.stdout + r.stderr
    out = json.loads(r.stdout)
    decomp = next(c for c in out["checks"] if c["name"] == "decompiler")
    assert decomp["status"] == "WARN", decomp
    assert "via MCP (ida-pro-vm)" in decomp["detail"], decomp
    assert "capability unverified" in decomp["detail"], decomp
    mcp_ghidra = next(c for c in out["checks"] if c["name"] == "mcp:ghidra")
    assert mcp_ghidra["status"] == "PASS", \
        f"ghidra supply must be satisfied by the ida-pro-vm provider: {mcp_ghidra}"


def test_toolchain_decompiler_mcp_first_ghidra(fake_claude_json, ws):
    """#407/#474: ghidra MCP registered -> decompiler WARN 'capability
    unverified' via MCP (registry evidence is not capability)."""
    write_claude_json(fake_claude_json, {
        "ghidra": reg("ghidra"),
        "sequential-thinking": reg("st"),
    })
    r = run_toolchain(ws, "--type", "windows", "--json")
    assert r.returncode in (0, 1, 2), r.stdout + r.stderr
    out = json.loads(r.stdout)
    decomp = next(c for c in out["checks"] if c["name"] == "decompiler")
    assert decomp["status"] == "WARN", decomp
    assert "via MCP (ghidra)" in decomp["detail"], decomp
    assert "capability unverified" in decomp["detail"], decomp


def test_toolchain_decompiler_mcp_beats_cli_fallback(fake_claude_json, ws,
                                                     monkeypatch, tmp_path):
    """#407/#474: MCP registration is the PRIMARY signal; CLI (GHIDRA_HOME) is
    the fallback — an MCP registration wins even when GHIDRA_HOME is set
    (the decompiler item surfaces as WARN via MCP, not the CLI ghidra item)."""
    write_claude_json(fake_claude_json, {
        "ghidra": reg("ghidra"),
        "sequential-thinking": reg("st"),
    })
    monkeypatch.setenv("GHIDRA_HOME", str(tmp_path / "ghidra_12.1.2_PUBLIC"))
    r = run_toolchain(ws, "--type", "windows", "--json")
    out = json.loads(r.stdout)
    decomp = next(c for c in out["checks"] if c["name"] == "decompiler")
    assert decomp["status"] == "WARN", decomp
    assert "via MCP" in decomp["detail"], \
        f"MCP must be the primary decompiler signal: {decomp}"
    assert "capability unverified" in decomp["detail"], decomp


def test_toolchain_decompiler_fail_with_install_guidance(fake_claude_json, ws):
    """#407: neither MCP nor CLI decompiler -> FAIL with ask-to-install
    guidance referencing the #408 installer."""
    fake_claude_json.write_text("{}", encoding="utf-8")
    r = run_toolchain(ws, "--type", "windows", "--json")
    assert r.returncode == 1, r.stdout + r.stderr
    out = json.loads(r.stdout)
    decomp = next(c for c in out["checks"] if c["name"] == "decompiler")
    assert decomp["status"] == "FAIL", decomp
    assert decomp["fix"] and "install" in decomp["fix"].lower(), decomp["fix"]
    assert "#408" in decomp["fix"], decomp["fix"]


# ---------- #407: ida-pro-vm tier semantics (mcp_probe) ----------

def test_ida_pro_vm_tier_sole_decompiler_provider_hard(fake_claude_json, ws):
    """#407: ida-pro-vm is HARD when it is the sole decompiler provider
    (ghidra absent); the ghidra supply item is satisfied via ida-pro-vm."""
    write_claude_json(fake_claude_json, {"ida-pro-vm": reg("ida")})
    checks = mcp_probe.check_mcp(ws, "linux", claude_json=fake_claude_json)
    by_name = {c.name: c for c in checks}
    assert by_name["ida-pro-vm"].tier == "HARD"
    assert by_name["ida-pro-vm"].status == "PASS"
    assert by_name["ghidra"].status == "PASS"
    assert "ida-pro-vm" in by_name["ghidra"].detail


def test_ida_pro_vm_tier_warn_when_ghidra_present(fake_claude_json, ws):
    """#407: ida-pro-vm keeps the WARN default when ghidra MCP is registered."""
    write_claude_json(fake_claude_json, {
        "ida-pro-vm": reg("ida"), "ghidra": reg("ghidra"),
    })
    checks = mcp_probe.check_mcp(ws, "linux", claude_json=fake_claude_json)
    by_name = {c.name: c for c in checks}
    assert by_name["ida-pro-vm"].tier == "WARN"
    assert by_name["ida-pro-vm"].status == "PASS"


# ---------- docs tables vs manifest ----------

def test_per_os_templates_exist_with_mcp_table():
    """#356 W2: the single-source base template carries the MCP table;
    per-OS renders are produced by kunglao-init injection (see
    tests/test_claudemd_single_source.py)."""
    p = TEMPLATES / "CLAUDE.md.base.tmpl"
    assert p.exists(), "missing templates/CLAUDE.md.base.tmpl (#356 W2)"
    text = p.read_text(encoding="utf-8")
    assert "MCP" in text


def test_docs_tables_match_manifest():
    """The README MCP table + the #919 row-data single source match MANIFEST
    (row-prefix pin: `| `name` | tier |`).

    #356 W2: the README table is the superset (all types). #919: the base
    template no longer carries the rows inline — kunglao-init renders the
    per-type table from MCP_ROW_TEXT filtered by MANIFEST `types` (noise +
    cold-start misdirection fix), so the row-data dict is the pinned
    surface here."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_supply", SCRIPTS / "kunglao-init.py")
    init = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(init)
    for item in mcp_probe.MANIFEST:
        row_prefix = f"| `{item.name}` | {item.tier} |"
        assert row_prefix in readme, f"README MCP table missing {item.name}"
        assert item.name in init.MCP_ROW_TEXT, \
            f"MCP_ROW_TEXT missing manifest member {item.name}"
        assert row_prefix in init.MCP_ROW_TEXT[item.name], \
            f"MCP_ROW_TEXT[{item.name!r}] tier/prefix drift vs MANIFEST"
    # Reverse direction: the row data must not carry names beyond the
    # manifest (avoid calibration drift), and order must be stable.
    assert set(init.MCP_ROW_TEXT) == {i.name for i in mcp_probe.MANIFEST}, \
        "MCP_ROW_TEXT/MANIFEST name-set drift"
    assert tuple(init.MCP_ROW_TEXT) == tuple(init.MCP_ROW_ORDER), \
        "MCP_ROW_TEXT key order must match MCP_ROW_ORDER"


def test_readme_mentions_probe_and_scaffold():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "mcp_probe.py" in text
    assert "--no-mcp" in text


# ---------- #515 acceptance 1: environment-side inventory (--mcp-inventory) ----------

class TestMcpInventory:
    """--mcp-inventory: enumerate REGISTERED servers across the three
    registration surfaces with the mcp__<server>__* tool prefix and the
    per-type required/optional annotation. Read-only / zero-network /
    zero-spawn; secret hygiene (no command/args/env values)."""

    def test_enumerates_all_three_registration_surfaces(
            self, tmp_path, fake_claude_json, ws):
        write_claude_json(
            fake_claude_json,
            servers={"Camoufox": {"type": "stdio", "command": "uvx",
                                  "args": ["camoufox-mcp"],
                                  "env": {"CAMOUFOX_API_KEY": "sk-leak-me"}},
                     "gitnexus": reg("gitnexus")},
            project_servers={"playwright": reg("npx")})
        (ws / ".mcp.json").write_text(
            json.dumps({"mcpServers": {"volatility": reg("vol")}}),
            encoding="utf-8")
        r = run_mcp_probe(ws, "--mcp-inventory",
                          "--claude-json", str(fake_claude_json))
        assert r.returncode == 0, r.stderr
        inv = json.loads(r.stdout)
        servers = {s["name"]: s for s in inv["servers"]}
        assert set(servers) == {"camoufox", "gitnexus", "playwright",
                                "volatility"}, (
            "inventory must enumerate global + project-scoped + workspace "
            "surfaces, canonical lowercase")
        assert servers["camoufox"]["prefix"] == "mcp__camoufox__*"
        assert servers["camoufox"]["sources"] == ["user-global"]
        assert servers["playwright"]["sources"] == [f"user-project:{_PROJECT_KEY}"]
        assert servers["volatility"]["sources"] == ["workspace"]

    def test_manifest_annotation_tier_and_types(self, tmp_path, fake_claude_json,
                                                ws):
        write_claude_json(fake_claude_json,
                          servers={"gitnexus": reg("gitnexus"),
                                   "camoufox": reg("camoufox")})
        r = run_mcp_probe(ws, "--mcp-inventory",
                          "--claude-json", str(fake_claude_json))
        assert r.returncode == 0, r.stderr
        servers = {s["name"]: s for s in json.loads(r.stdout)["servers"]}
        # manifest member: tier + types from the #316 supply manifest
        assert servers["gitnexus"]["in_manifest"] is True
        assert servers["gitnexus"]["manifest_tier"] == "HARD"
        assert servers["gitnexus"]["required_for_types"] == ["android"]
        # environment-extra: not in the manifest
        assert servers["camoufox"]["in_manifest"] is False
        assert servers["camoufox"]["manifest_tier"] is None
        assert servers["camoufox"]["required_for_types"] == []

    def test_secret_hygiene_never_emits_config_values(
            self, tmp_path, fake_claude_json, ws):
        """MCP configs may carry API keys in `env` — the inventory must be
        pasteable: names/sources/tiers only, never command/args/env values."""
        write_claude_json(fake_claude_json, servers={
            "camoufox": {"type": "stdio", "command": "uvx",
                         "args": ["--secret-arg"],
                         "env": {"CAMOUFOX_API_KEY": "sk-do-not-leak"}}})
        r = run_mcp_probe(ws, "--mcp-inventory",
                          "--claude-json", str(fake_claude_json))
        assert r.returncode == 0, r.stderr
        for secret in ("sk-do-not-leak", "--secret-arg", "uvx"):
            assert secret not in r.stdout, (
                f"inventory leaked config value {secret!r}")

    def test_inventory_is_type_agnostic_and_exits_zero(
            self, tmp_path, fake_claude_json, ws):
        """Enumeration face: no --type / analysis_state.txt needed (check
        mode would exit 1 on a missing type — inventory must not)."""
        write_claude_json(fake_claude_json, servers={"camoufox": reg("x")})
        r = run_mcp_probe(ws, "--mcp-inventory",
                          "--claude-json", str(fake_claude_json))
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["server_count"] == 1

    def test_inventory_missing_config_is_empty_not_error(
            self, tmp_path, ws):
        """Fail-open JSON read (same policy as check face): unreadable
        config -> empty inventory, exit 0."""
        r = run_mcp_probe(ws, "--mcp-inventory",
                          "--claude-json", str(tmp_path / "nope.json"))
        assert r.returncode == 0, r.stderr
        inv = json.loads(r.stdout)
        assert inv["server_count"] == 0 and inv["servers"] == []

    def test_inventory_mutually_exclusive_with_check_modes(
            self, tmp_path, fake_claude_json, ws):
        write_claude_json(fake_claude_json, servers={"camoufox": reg("x")})
        for flag in ("--json", "--reproduce"):
            r = run_mcp_probe(ws, "--mcp-inventory", flag,
                              "--claude-json", str(fake_claude_json))
            assert r.returncode == 2, (
                f"--mcp-inventory + {flag} is a usage error (distinct faces)")

    def test_inventory_deterministic(self, tmp_path, fake_claude_json, ws):
        write_claude_json(fake_claude_json,
                          servers={"camoufox": reg("x"), "gitnexus": reg("y")})
        argv = [sys.executable, str(SCRIPTS / "mcp_probe.py"), str(ws),
                "--mcp-inventory", "--claude-json", str(fake_claude_json)]
        outs = [subprocess.run(argv, capture_output=True, text=True,
                               timeout=120).stdout for _ in range(2)]
        assert outs[0] == outs[1]
