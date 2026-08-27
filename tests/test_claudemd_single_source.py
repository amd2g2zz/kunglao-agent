# -*- coding: utf-8 -*-
"""Issue #356 W2 — CLAUDE.md single-source template contract.

The 4 pre-#356 templates (CLAUDE.md.tmpl / .windows / .linux / .android) had
massive copy drift (five-layer principle only in OS variants, hallucinated
~/.claude/rules/common/ references, mixed Chinese/English). #356 W2 collapses
them into ONE handwritten source + kunglao-init OS-section injection:

RED assertions (fail until the rewrite lands):
  1. templates/CLAUDE.md.base.tmpl exists and is the ONLY CLAUDE.md template
  2. base carries: workspace type / sample table / SKILL_DIR script surface /
     state-file table / five-layer principle (all-OS) / hard constraints
     (common) / SUCCESS-CRITERIA section / MCP table with <TYPE> placeholder /
     env-var table referencing .env / venv
  3. base does NOT reference ~/.claude/rules/common/ (hallucinated paths)
  4. base is English-only prose (no CJK residue)
  5. <TYPE> injection placeholder present; OS sections injected by kunglao-init
  6. kunglao-init renders per-OS CLAUDE.md from the single source: windows
     gets x64dbg constraints, linux gdbserver/eBPF, android adb/gitnexus
  7. release manifest templates list matches the new file set
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TEMPLATES = ROOT / "templates"
BASE_TMPL = TEMPLATES / "CLAUDE.md.base.tmpl"
MANIFEST = ROOT / "release-manifest.yaml"

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"

_CJK = re.compile(r"[一-鿿]")


# ---------- 1. single source ----------

def test_base_template_exists():
    assert BASE_TMPL.is_file(), "templates/CLAUDE.md.base.tmpl missing (#356 W2)"


def test_legacy_variant_templates_removed():
    for legacy in ("CLAUDE.md.tmpl", "CLAUDE.md.windows.tmpl",
                   "CLAUDE.md.linux.tmpl", "CLAUDE.md.android.tmpl"):
        assert not (TEMPLATES / legacy).exists(), \
            f"legacy template {legacy} must be replaced by CLAUDE.md.base.tmpl"


def test_base_is_the_only_claudemd_template():
    claude_templates = sorted(p.name for p in TEMPLATES.glob("CLAUDE.md*"))
    assert claude_templates == ["CLAUDE.md.base.tmpl"], claude_templates


# ---------- 2. base structure ----------

def test_base_carries_required_sections():
    text = BASE_TMPL.read_text(encoding="utf-8")
    for section in (
        "## Workspace type",
        "## Sample under analysis",
        "## Skill & orchestrator",
        "## State files",
        "## Five-layer analysis principle",
        "## Hard constraints",
        "## Success criteria",
        "## MCP servers",
        "## Environment variables",
        "## Python venv",
    ):
        assert section in text, f"base template missing section: {section}"


def test_base_carries_memory_tiering_contract():
    """#785 ruling 2026-08-27: the template must DECLARE how memory is
    layered — including the host-harness native project memory as its own
    tier (not lumped into generic 'preferences')."""
    text = BASE_TMPL.read_text(encoding="utf-8")
    for needle in (
        "**Memory tiers**",
        "T1 workspace carriers",
        "T2 distilled lessons",
        "T3 reference library",
        "T4 project memory (Claude Code native)",
        "index + typed files",
        "Routing discipline",
    ):
        assert needle in text, f"memory-tier contract missing: {needle}"
    # write triggers are part of the table, not prose afterthoughts
    assert "Write trigger" in text


def test_base_sample_and_venv_placeholders():
    text = BASE_TMPL.read_text(encoding="utf-8")
    # #362: placeholders migrated <UPPERCASE> -> {{lowercase}} (shared
    # template_gen engine convention). Syntax update only — content
    # assertions unchanged.
    for ph in ("{{sample_sha1}}", "{{sample_sha256}}", "{{sample_type}}",
               "{{sample_path}}", "{{skill_dir}}", "{{venv_path}}",
               "{{type}}"):
        assert ph in text, f"base template missing placeholder {ph}"


def test_base_mcp_table_type_placeholder():
    """MCP table row check command uses the {{type}} placeholder (init injects)."""
    text = BASE_TMPL.read_text(encoding="utf-8")
    assert "mcp_probe.py . --type {{type}}" in text, \
        "MCP probe command must carry the {{type}} injection placeholder"


def test_base_references_workspace_env_file():
    """Env table points at the workspace .env (W4 deployment surface)."""
    text = BASE_TMPL.read_text(encoding="utf-8")
    assert ".env" in text and ".env.example" in text


# ---------- 3. hallucination purge ----------

def test_base_has_no_hallucinated_rules_common_section():
    text = BASE_TMPL.read_text(encoding="utf-8")
    assert "~/.claude/rules/common/" not in text, \
        "hallucinated ~/.claude/rules/common/ reference must be removed"
    assert "Required rules (read every session)" not in text


def test_base_no_cjk_prose():
    """#356 W2: base template is all-English (no mixed CJK residue)."""
    text = BASE_TMPL.read_text(encoding="utf-8")
    hits = _CJK.findall(text)
    assert not hits, f"CJK characters remain in base template: {hits[:10]}"


def test_base_no_emdash_dash_inconsistency():
    """The pre-#356 templates mixed em-dash and '--' in prose; base uses
    em-dash. `--` inside code spans (claude mcp add ... -- cmd) is fine."""
    text = BASE_TMPL.read_text(encoding="utf-8")
    outside_code = re.sub(r"`[^`]*`", "", text)
    outside_code = re.sub(r"^\s*#.*$", "", outside_code, flags=re.M)
    assert " -- " not in outside_code, \
        "' -- ' prose separator remains (normalize to em-dash)"


# ---------- 4. accurate no-questions policy ----------

def test_base_no_mid_iteration_question_policy_accurate():
    text = BASE_TMPL.read_text(encoding="utf-8")
    # The anti-pattern one-liner must be gone...
    assert "No mid-iteration user questions: decide + record reasoning + continue." \
        not in text
    # ...replaced by the accurate formulation: no stopping for self-answerable
    # questions, schema/direction ambiguity still surfaced.
    assert "self-answerable" in text, \
        "accurate no-stopping policy (self-answerable questions) missing"
    assert "ambiguity" in text or "directional" in text, \
        "policy must still surface schema/direction ambiguity"


# ---------- 5. karpathy success criteria ----------

def test_base_success_criteria_verifiable():
    """SUCCESS-CRITERIA section turns key behaviors into checkable criteria."""
    text = BASE_TMPL.read_text(encoding="utf-8")
    m = re.search(r"## Success criteria(.*?)(?=\n## )", text, re.S)
    assert m, "no Success criteria section body"
    body = m.group(1)
    assert "PROVEN" in body and "verifier" in body.lower(), \
        "fact-promotion criterion (independent verifier sign-off) missing"
    assert "facts/_INDEX.md" in body, "criteria must name a checkable artifact"


# ---------- 6. init renders per-OS from single source ----------

@pytest.fixture
def init_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    return ws


def _run_init(ws: Path, project_type: str) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws),
            "--type", project_type, "--skip-toolchain",
            "--profile-root", str(ws.parent / "profile-root")]
    env = {k: v for k, v in os.environ.items() if k != FLAG_NAME}
    env[FLAG_NAME] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(argv, capture_output=True, text=True, timeout=120,
                          env=env, errors="replace")


@pytest.mark.parametrize("project_type,marker", [
    ("windows", "x64dbg"),
    ("linux", "gdbserver"),
    ("android", "adb"),
])
def test_init_injects_os_section(init_ws: Path, project_type: str, marker: str):
    r = _run_init(init_ws, project_type)
    assert r.returncode == 0, f"init failed: {r.stderr}"
    claude = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert marker in claude, \
        f"CLAUDE.md for {project_type} missing OS marker {marker!r}"
    assert f"({project_type})" in claude, "OS-specific section header missing"


def test_init_injected_claudemd_has_no_placeholder_residue(init_ws: Path):
    """#362 hardening: generic residue scan instead of an enumerated
    placeholder list — catches BOTH the legacy <UPPERCASE> form and the
    post-#362 {{lowercase}} form, including placeholders that did not
    exist when this test was written. Prose tokens <NNN> (fact filename
    pattern) and <C-NN> (claim id) are literal documentation, not
    placeholders — allowlisted."""
    r = _run_init(init_ws, "windows")
    assert r.returncode == 0, r.stderr
    claude = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    legacy = [p for p in re.findall(r"<[A-Z][A-Z0-9_]+>", claude)
              if p != "<NNN>"]  # <NNN> = fact filename prose, not a placeholder
    assert legacy == [], f"legacy placeholder residue in rendered CLAUDE.md: {legacy}"
    braced = re.findall(r"\{\{[a-z_]+\}\}", claude)
    assert braced == [], f"{{{{param}}}} residue in rendered CLAUDE.md: {braced}"


def test_init_claudemd_keeps_common_sections(init_ws: Path):
    """Five-layer principle + success criteria land in every OS render."""
    r = _run_init(init_ws, "linux")
    assert r.returncode == 0, r.stderr
    claude = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "Five-layer analysis principle" in claude
    assert "## Success criteria" in claude
    assert "maker-checker" in claude.lower() or "Maker-checker" in claude


# ---------- 7. release manifest alignment ----------

def test_release_manifest_templates_match_fileset():
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    declared = set(manifest["assets"]["templates"])
    on_disk = {p.relative_to(ROOT).as_posix()
               for p in TEMPLATES.rglob("*") if p.is_file()}
    # README.md files inside templates/ subdirs are prose, not declared
    # template assets (pre-existing convention).
    on_disk = {p for p in on_disk if not p.endswith("README.md")}
    assert declared == on_disk, (
        f"manifest/disk drift: only-manifest={sorted(declared - on_disk)} "
        f"only-disk={sorted(on_disk - declared)}")
