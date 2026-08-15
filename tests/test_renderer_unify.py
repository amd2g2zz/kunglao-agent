# -*- coding: utf-8 -*-
"""Issue #362 — unified template renderer contract (TDD).

The repo had TWO incompatible rendering systems (issue table):
  scripts/template_gen.py — {{lowercase}} regex single-pass + fail-closed
                            leftover detection
  scripts/kunglao-init.py — <UPPERCASE> str.replace chain, NO leftover
                            detection (an unfilled <XXX> shipped silently)

This file pins the unified engine:

  1. scripts/template_render.py exists as the shared primitive module
     (render + leftover_placeholders + placeholder pattern) and
     template_gen.py imports from it (single source, no copy)
  2. base.tmpl uses the {{lowercase}} convention (no <UPPERCASE> injection
     placeholders left)
  3. kunglao-init.write_claudemd renders through the shared engine
  4. fail-closed: a template with an unfilled {{placeholder}} makes
     write_claudemd raise TemplateRenderError (HARD error, no silent
     partial file) — monkeypatched templates-dir fixture
  5. golden equivalence: rendered CLAUDE.md for windows/linux/android is
     byte-identical to the pre-migration fixtures committed under
     tests/fixtures/claudemd-golden/ (generated at e4e70e0)
  6. dead stub template_for_type() is gone (zero callers after migration)
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TEMPLATES = ROOT / "templates"
BASE_TMPL = TEMPLATES / "CLAUDE.md.base.tmpl"
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "claudemd-golden"

sys.path.insert(0, str(SCRIPTS))

# Sentinels — MUST match the ones used to generate the golden fixtures at
# e4e70e0 (tests/fixtures/claudemd-golden/). Deterministic across machines,
# checkouts and python builds so the byte-equivalence proof is portable.
SKILL_DIR_SENTINEL = Path("/kunglao/skill-sentinel")
PY_VERSION_SENTINEL = "3.11.0"

PAYLOAD = b"MZ\x90\x00" + b"\x00" * 64
SAMPLE_SHA = hashlib.sha256(PAYLOAD).hexdigest()


def _load_init():
    """Load kunglao-init.py as a module (hyphen filename, no package)."""
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_unified", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def init_mod():
    mod = _load_init()
    mod.SKILL_DIR = SKILL_DIR_SENTINEL
    return mod


def _render(mod, project_type: str, tmp_path: Path) -> str:
    """write_claudemd with pinned sentinel inputs; returns rendered text."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(PAYLOAD)
    target = mod.write_claudemd(ws, "sample.exe", SAMPLE_SHA,
                                project_type=project_type)
    assert target is not None, "write_claudemd skipped (target existed?)"
    return target.read_text(encoding="utf-8")


# ---------- 1. shared primitive module ----------

def test_template_render_module_exists_with_primitives():
    import template_render
    assert hasattr(template_render, "render")
    assert hasattr(template_render, "leftover_placeholders")
    for text, params, want in (
        ("a {{x}} b", {"x": "1"}, "a 1 b"),
        ("no placeholders", {}, "no placeholders"),
        ("{{a}}{{a}}", {"a": "z"}, "zz"),           # every occurrence
        ("{{miss}}", {}, "{{miss}}"),               # unmatched kept for report
        ("{{a}}", {"a": "{{b}}"}, "{{b}}"),         # single pass, no rescan
    ):
        assert template_render.render(text, params) == want


def test_leftover_placeholders_reports_unfilled():
    import template_render
    assert template_render.leftover_placeholders("x {{b}} {{a}} {{b}} y") \
        == ["a", "b"]
    assert template_render.leftover_placeholders("clean text") == []


def test_template_gen_imports_shared_primitives():
    """template_gen.py reuses template_render (single source, no local copy)."""
    src = (SCRIPTS / "template_gen.py").read_text(encoding="utf-8")
    assert "import template_render" in src or "from template_render import" in src
    assert "def render(" not in src, \
        "template_gen.py must not keep a local render() copy"


# ---------- 2. base.tmpl placeholder convention ----------

def test_base_tmpl_uses_double_brace_placeholders():
    text = BASE_TMPL.read_text(encoding="utf-8")
    for ph in ("{{type_section}}", "{{type}}", "{{sample_sha1}}",
               "{{sample_sha256}}", "{{sample_type}}", "{{sample_path}}",
               "{{skill_dir}}", "{{venv_path}}"):
        assert ph in text, f"base.tmpl missing {ph} placeholder"
    # The old <UPPERCASE> injection placeholders must be gone. Prose <NNN>
    # (fact filename pattern) is NOT a placeholder and stays.
    import re
    legacy = re.findall(r"<[A-Z][A-Z0-9_]*>", text)
    assert legacy == [], f"legacy <UPPERCASE> placeholders remain: {legacy}"


def test_os_sections_contain_no_double_brace_collision():
    """OS_SECTIONS values are injected as {{type_section}} VALUES — a literal
    {{key}} inside them would be re-matched by leftover detection."""
    mod = _load_init()
    import re
    for os_name, block in mod.OS_SECTIONS.items():
        hits = re.findall(r"\{\{[A-Za-z0-9_]+\}\}", block)
        assert hits == [], f"OS_SECTIONS[{os_name!r}] contains {{{{...}}}}: {hits}"


# ---------- 3. write_claudemd renders through the shared engine ----------

def test_write_claudemd_uses_shared_engine(init_mod):
    """kunglao-init imports the shared primitives (no str.replace chain)."""
    src = (SCRIPTS / "kunglao-init.py").read_text(encoding="utf-8")
    assert "import template_render" in src or "from template_render import" in src
    assert ".replace(\"<" not in src, \
        "kunglao-init.py still carries the legacy <UPPERCASE> replace chain"


def test_write_claudemd_no_leftover_after_render(init_mod, tmp_path):
    """A healthy render leaves zero {{...}} placeholders in the output."""
    import template_render
    text = _render(init_mod, "windows", tmp_path)
    assert template_render.leftover_placeholders(text) == []


# ---------- 4. fail-closed leftover detection ----------

def test_unfilled_placeholder_fails_loudly(init_mod, tmp_path, monkeypatch):
    """A base.tmpl with a deliberately unfilled {{placeholder}} is a HARD
    error: TemplateRenderError names the leftover, no partial CLAUDE.md is
    written."""
    import template_render
    bad_dir = tmp_path / "templates"
    bad_dir.mkdir()
    good = BASE_TMPL.read_text(encoding="utf-8")
    (bad_dir / "CLAUDE.md.base.tmpl").write_text(
        good + "\nBOGUS = {{deliberately_unfilled}}\n", encoding="utf-8")
    monkeypatch.setattr(init_mod, "CLAUDEMD_TMPL",
                        bad_dir / "CLAUDE.md.base.tmpl")

    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    with pytest.raises(template_render.TemplateRenderError) as excinfo:
        init_mod.write_claudemd(ws, "sample.exe", SAMPLE_SHA,
                                project_type="windows")
    assert "deliberately_unfilled" in str(excinfo.value)
    assert not (ws / "CLAUDE.md").exists(), \
        "fail-closed must not leave a partial CLAUDE.md"


def test_type_section_typo_fails_loudly(init_mod, tmp_path, monkeypatch):
    """A typo'd placeholder name ({{type_sectio}}) is also caught — the
    engine does not depend on knowing the intended param list."""
    import template_render
    bad_dir = tmp_path / "templates"
    bad_dir.mkdir()
    good = BASE_TMPL.read_text(encoding="utf-8")
    (bad_dir / "CLAUDE.md.base.tmpl").write_text(
        good.replace("{{type_section}}", "{{type_sectio}}"), encoding="utf-8")
    monkeypatch.setattr(init_mod, "CLAUDEMD_TMPL",
                        bad_dir / "CLAUDE.md.base.tmpl")

    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    with pytest.raises(template_render.TemplateRenderError):
        init_mod.write_claudemd(ws, "sample.exe", SAMPLE_SHA,
                                project_type="linux")
    assert not (ws / "CLAUDE.md").exists()


def test_init_cli_exits_nonzero_on_template_defect(init_mod, tmp_path,
                                                   monkeypatch):
    """End-to-end: run() with a defect-injected template exits non-zero and
    leaves no partial CLAUDE.md behind. (The render error itself is raised
    by write_claudemd — proven above; this pins the run() wiring.)"""
    bad_dir = tmp_path / "templates"
    bad_dir.mkdir()
    good = BASE_TMPL.read_text(encoding="utf-8")
    (bad_dir / "CLAUDE.md.base.tmpl").write_text(
        good + "\nBOGUS = {{cli_level_defect}}\n", encoding="utf-8")

    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(PAYLOAD)

    monkeypatch.setattr(init_mod, "CLAUDEMD_TMPL",
                        bad_dir / "CLAUDE.md.base.tmpl")
    rc = init_mod.run(ws, skip_toolchain=True,
                      project_type="windows",
                      profile_root=tmp_path / "profile-root")
    assert rc != 0, "init must exit non-zero when the template is defective"
    assert not (ws / "CLAUDE.md").exists()


# ---------- 5. golden equivalence (byte-identical vs pre-migration) ----------

@pytest.mark.parametrize("project_type", ["windows", "linux", "android"])
def test_golden_equivalence_byte_identical(init_mod, tmp_path, monkeypatch,
                                           project_type):
    """Rendered CLAUDE.md is byte-identical to the e4e70e0 pre-migration
    fixture for the same sentinel inputs (skill dir + python version)."""
    # Pin the venv Python-version append sentinel (post-render step reads
    # sys.version_info at call time — freeze it for this test).
    real_vi = sys.version_info
    monkeypatch.setattr(sys, "version_info",
                        types.SimpleNamespace(major=3, minor=11, micro=0))
    try:
        text = _render(init_mod, project_type, tmp_path)
    finally:
        monkeypatch.setattr(sys, "version_info", real_vi)
    golden = (GOLDEN_DIR / f"{project_type}.md").read_text(encoding="utf-8")
    assert text == golden, (
        f"golden drift for {project_type}: "
        f"{sum(1 for a, b in zip(text, golden) if a != b)} first-diff chars; "
        f"len {len(text)} vs {len(golden)}")


def test_golden_fixtures_are_pinned():
    """All three golden files exist and are non-trivial (regen guard)."""
    for t in ("windows", "linux", "android"):
        p = GOLDEN_DIR / f"{t}.md"
        assert p.is_file(), f"golden fixture missing: {p}"
        assert len(p.read_bytes()) > 1000


# ---------- 6. dead stub removal ----------

def test_dead_stub_template_for_type_removed():
    src = (SCRIPTS / "kunglao-init.py").read_text(encoding="utf-8")
    assert "def template_for_type" not in src, \
        "template_for_type() is a dead stub (zero callers) — remove it"


# ---------- 7. os_section still feeds the engine (behavior kept) ----------

def test_os_section_lookup(init_mod):
    assert "x64dbg" in init_mod.os_section("windows")
    assert "gdbserver" in init_mod.os_section("linux")
    assert "adb" in init_mod.os_section("android")
    assert init_mod.os_section(None) == ""
    assert init_mod.os_section("bogus") == ""
