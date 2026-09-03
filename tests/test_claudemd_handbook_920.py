# -*- coding: utf-8 -*-
"""Issue #920 round 2 — CLAUDE.md as a living handbook.

User ruling: the north star of CLAUDE.md is agent informativeness —
accumulating more is WRONG, too much is harmful. Round 1 (inheriting
the #919 conditional render) made the template type-conditional; round 2
adds the missing heuristic sections and the init-worker render+cultivate
upgrade:

  1. Roles quick-reference — roster DERIVED from agents/*.md frontmatter
     (never hand-copied: the anchor is the directory itself); dispatch
     triggers from the ROLE_DISPATCH table; roster drift fails the render.
  2. Project layout — one line per directory (semantics + pitfall); the
     key set mirrors the scaffold contract (SCAFFOLD_DIRS) and real repo
     directories, so a scaffold change drags the handbook along.
  3. Quick start — type-keyed opening-moves scaffold (init stays purely
     mechanical); non-empty for every type; kunglao-init-worker cultivates
     it into the task's concrete quick start afterward.
  4. Keeping this handbook alive — governance section carrying the
     two-gate questions (dumber/stronger) and the red lines.
  5. Line budgets per new section — the mechanical form of "more is
     harmful": Roles 30 / Project layout 20 / Quick start 40 / governance 25.
"""
from __future__ import annotations

import collections
import importlib.util
import re
import sys
from pathlib import Path

import pytest
from _factories import seed_bins

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
BASE_TMPL = ROOT / "templates" / "CLAUDE.md.base.tmpl"
AGENTS_DIR = ROOT / "agents"

BUDGETS = {
    "Roles & responsibilities": 30,
    "Project layout": 20,
    "Quick start: how to work THIS analysis": 40,
    "Keeping this handbook alive": 25,
}

sys.path.insert(0, str(SCRIPTS))


def _load_init():
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_handbook", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def init_mod(monkeypatch):
    mod = _load_init()
    mod.SKILL_DIR = Path("/kunglao/skill-sentinel")
    # Pin the python-version sentinel the venv line echoes (same recipe as
    # test_renderer_unify's golden path).
    VI = collections.namedtuple("VI", "major minor micro release serial")
    real = sys.version_info
    monkeypatch.setattr(sys, "version_info", VI(3, 11, 0, "final", ""))
    yield mod
    monkeypatch.setattr(sys, "version_info", real)


def _render(init_mod, project_type: str, tmp_path: Path,
            sample: str = "sample.exe") -> str:
    ws = tmp_path / f"ws-{project_type}"
    seed_bins(ws)
    target = init_mod.write_claudemd(ws, sample, "a" * 40,
                                     project_type=project_type)
    assert target is not None
    return target.read_text(encoding="utf-8")


def _section(text: str, title: str) -> str:
    """Section body INCLUDING the heading, ending before the next heading
    (any level), the frame close marker, or EOF — whichever comes first."""
    pat = (rf"^(## {re.escape(title)}\n.*?)"
           rf"(?=^## |^# |^<hr|^<!-- /kunglao:frame -->|\Z)")
    m = re.search(pat, text, re.S | re.M)
    assert m, f"section missing: {title}"
    return m.group(1)


def _nonblank_lines(text: str) -> int:
    return len([l for l in text.splitlines() if l.strip()])


# ---------- 1. Roles: data-driven roster anchors ----------

def test_roles_roster_equals_agents_directory():
    """The roster is the directory — frontmatter names == file stems ==
    ROLE_DISPATCH keys, in both directions (drift fails closed in the
    render, and this anchor keeps the table honest)."""
    init = _load_init()
    roster = init._agent_roster()
    stems = {p.stem for p in AGENTS_DIR.glob("*.md")}
    assert set(roster) == stems, \
        f"frontmatter names != agents/ files: {sorted(set(roster) ^ stems)}"
    assert set(init.ROLE_DISPATCH) == stems
    assert len(roster) >= 5, "handbook lost most of the roster?"


def test_roles_briefs_are_derived_not_copied():
    """Each responsibility cell is derived from that agent's own
    description through the documented first-sentence transform (mirror
    implemented here), never paraphrased by hand."""
    init = _load_init()
    for name, desc in init._agent_roster().items():
        first_sentence = re.split(r"\.\s", desc.strip(), maxsplit=1)[0]
        expected = " ".join(
            first_sentence.replace("for the kunglao-agent orchestrator", "")
            .split()).strip(" ,-—:")
        if len(expected) > init.ROLE_BRIEF_CAP:
            expected = expected[:init.ROLE_BRIEF_CAP - 1].rsplit(" ", 1)[0] + "…"
        got = init._agent_brief(desc)
        assert got == expected, f"{name} brief drift: {got!r} != {expected!r}"
        assert got, f"empty brief for {name}"
        assert len(got) <= init.ROLE_BRIEF_CAP
        assert "|" not in got.replace("\\|", ""), f"{name} breaks the table"


def test_roles_rows_render_fails_closed_on_drift(monkeypatch):
    init = _load_init()
    import template_render
    good = init.roles_rows()
    assert "| `kunglao-worker` |" in good
    assert good.count("\n") == len(init.ROLE_DISPATCH) - 1
    # a dispatch entry without an agent definition -> render error
    monkeypatch.setitem(init.ROLE_DISPATCH, "ghost-agent", "d. ghost")
    with pytest.raises(template_render.TemplateRenderError):
        init.roles_rows()
    # a new agent definition without a dispatch entry -> render error
    monkeypatch.undo()
    roster = {k: v for k, v in init.ROLE_DISPATCH.items()
              if k != "kunglao-worker"}
    monkeypatch.setattr(init, "_agent_roster", lambda: roster)
    with pytest.raises(template_render.TemplateRenderError):
        init.roles_rows()


# ---------- 2. Project layout: scaffold + repo anchors ----------

def test_layout_dirs_mirror_scaffold_contract():
    init = _load_init()
    keys = {r[0] for r in init.LAYOUT_ROWS}
    want = {"bins/"} | {d + "/" for d in init.SCAFFOLD_DIRS
                        if d != "runs/logs"}
    assert keys == want, f"layout keys != scaffold dirs (+bins): {keys ^ want}"
    # runs/logs is a scaffold dir — folded into the runs/ row, never dropped
    assert any("runs/logs" in cell for row in init.LAYOUT_ROWS
               for cell in row), "runs/logs semantics lost"
    # every caveat cell is filled (semantics + pitfall, per the ruling)
    assert all(c.strip() for _, _, c in init.LAYOUT_ROWS)


def test_layout_skill_dirs_exist():
    init = _load_init()
    for d in init.SKILL_LAYOUT_ROW[0].replace("+", " ").split():
        assert (ROOT / d).is_dir(), f"layout names a nonexistent dir: {d}"


def test_layout_rows_render_in_every_type(init_mod, tmp_path):
    for t in ("windows", "android", "web"):
        text = _render(init_mod, t, tmp_path)
        body = _section(text, "Project layout")
        assert f"| `{init_mod.SCAFFOLD_DIRS[0]}/` |" in body  # facts/ row
        assert "| `tools/ + scripts/` |" in body


# ---------- 3. Quick start: type scaffold, non-empty after init ----------

def test_quick_start_scaffold_is_type_dependent():
    init = _load_init()
    kinds = ("windows", "linux", "android", "web", "macos")
    scaffolds = [init.quick_start_scaffold(t) for t in kinds]
    assert all(s.strip() for s in scaffolds), "empty scaffold for some type"
    assert len(set(scaffolds)) >= 4, \
        "scaffolds collapsed to one shape — type methodology lost"
    assert "gdbserver" in init.quick_start_scaffold("linux")
    assert "jadx" in init.quick_start_scaffold("android")
    assert "verify_signer_offline" in init.quick_start_scaffold("web")
    assert init.quick_start_scaffold("bogus") == \
        init.quick_start_scaffold("windows"), "unknown type must fall back"
    assert "bins/sample.exe" in init.quick_start_scaffold(
        "windows", "sample.exe"), "target name must be threaded"


def test_quick_start_renders_per_type_no_cross_leaks(init_mod, tmp_path):
    text = _render(init_mod, "android", tmp_path)
    body = _section(text, "Quick start: how to work THIS analysis")
    assert "CULTIVATION SLOT" in body  # the init-worker contract comment
    assert "jadx" in body and body.strip() != ""
    for banned in ("x64dbg", "KUNGLAO_VM_HOST", "VM-only"):
        assert banned not in body, f"android quick start leaks {banned}"
    web_body = _section(_render(init_mod, "web", tmp_path),
                        "Quick start: how to work THIS analysis")
    assert "verify_signer_offline" in web_body
    assert "KUNGLAO_VM_HOST" not in web_body
    win_body = _section(_render(init_mod, "windows", tmp_path),
                        "Quick start: how to work THIS analysis")
    assert "static-first" in win_body


# ---------- 4. Governance: two gates + red lines ----------

@pytest.mark.parametrize("project_type", ["windows", "web"])
def test_governance_carries_two_gates_and_red_lines(init_mod, tmp_path,
                                                    project_type):
    text = _render(init_mod, project_type, tmp_path)
    body = " ".join(_section(text, "Keeping this handbook alive").split())
    # the two questions, verbatim intents (whitespace-normalized: prose wraps)
    assert "get dumber" in body and "get stronger" in body
    assert "BOTH gates" in body
    # red-line vocabulary
    for needle in ("chronological", "Red lines", "distilled"):
        assert needle in body, f"governance missing red-line keyword {needle}"
    # update triggers + the init-worker authority clause
    for needle in ("user ruling", "pitfall", "NOT append-only",
                   "kunglao-init-worker", "informativeness"):
        assert needle in body, f"governance missing {needle}"


def test_base_template_carries_handbook_slots_and_sections():
    text = BASE_TMPL.read_text(encoding="utf-8")
    for slot in ("{{roles_rows}}", "{{layout_rows}}",
                 "{{quick_start_section}}"):
        assert slot in text, f"base template missing slot {slot}"
    for title in BUDGETS:
        assert f"## {title}" in text, f"base template missing section {title}"


# ---------- 5. Line budgets (the "more is harmful" gate) ----------

@pytest.mark.parametrize("project_type", ["windows", "linux", "android",
                                          "web", "macos"])
def test_handbook_section_line_budgets(init_mod, tmp_path, project_type):
    text = _render(init_mod, project_type, tmp_path)
    for title, budget in BUDGETS.items():
        n = _nonblank_lines(_section(text, title))
        assert n <= budget, \
            f"{project_type} section '{title}' over budget: {n} > {budget}"


def test_init_cli_render_carries_all_four_sections(tmp_path):
    """End-to-end init path: the four sections land in the real CLI render
    and the quick start is non-empty (cultivation pending, not absent)."""
    import os
    import subprocess
    ws = tmp_path / "ws"
    seed_bins(ws)
    env = {k: v for k, v in os.environ.items()
           if k != "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"}
    env["CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws),
         "--type", "android", "--skip-toolchain",
         "--profile-root", str(ws.parent / "profile-root")],
        capture_output=True, text=True, timeout=120, env=env,
        errors="replace")
    assert r.returncode == 0, r.stderr
    text = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    for title in BUDGETS:
        _section(text, title)  # asserts presence
    qs = _section(text, "Quick start: how to work THIS analysis")
    assert "jadx" in qs and "gitnexus" in qs


def test_upgrade_frame_parity_renders_handbook_slots(tmp_path):
    """The upgrade re-render derives init-parity params — the three new
    slots must resolve there too, or upgrade leaves {{placeholder}} holes
    inside the frame."""
    spec = importlib.util.spec_from_file_location(
        "kunglao_upgrade_handbook", SCRIPTS / "kunglao_upgrade.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ws = tmp_path / "ws"
    seed_bins(ws)
    frame = mod._build_current_frame(ws, "", None)
    import template_render
    assert template_render.leftover_placeholders(frame) == []
    for title in BUDGETS:
        _section(frame, title)
