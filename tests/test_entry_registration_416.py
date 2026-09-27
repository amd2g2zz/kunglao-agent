# -*- coding: utf-8 -*-
"""tests/test_entry_registration_416.py — issue #416 entry-point registration (TDD).

#416 audit: an analysis session could not find ANY kunglao entry point. The
router (scripts/kunglao.py, 9 subcommands) was only invokable as
`python scripts/kunglao.py`; pyproject.toml had NO [project.scripts]; doc
references to bare `kunglao ...` (skills/analysis/SKILL.md:29,60,
skills/init/SKILL.md:60) had no backing surface; the /kunglao-agent:help menu
and subcommands.yaml (the #456 UX single source) only knew the slash-command
face, never the CLI face.

RED on baseline (dev @ 37db9934): no [project.scripts], no kunglao_agent_cli
package, no `cli:` section in subcommands.yaml, no CLI block in the help /
root menus or README, _entry.py docstring does not disclaim router-hood, and
three live files still reference the external malware-veri-notes skill
unconditionally (the skill has NEVER existed in this repo's tree or history —
ICD-203 interop already treats it as user-level, skip-if-absent,
tests/test_icd203_alignment.py:466-473).

Contract: wrappers ONLY register entry points — zero behavior change to any
existing script's CLI semantics. Each wrapper mirrors its target's own
`__main__` guard (UTF-8 boot where the target has one) and returns the
target's main() rc.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

try:
    import tomllib
except ImportError:  # sanctioned backfill (test_python_floor #352)
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
ROUTER = ROOT / "scripts" / "kunglao.py"
ENTRY_HELPER = ROOT / "scripts" / "_entry.py"
YAML_FILE = ROOT / "skills" / "subcommands.yaml"
HELP_SKILL = ROOT / "skills" / "help" / "SKILL.md"
ROOT_SKILL = ROOT / "SKILL.md"
README = ROOT / "README.md"

# issue #416 naming table: console script -> registered callable
EXPECTED_SCRIPTS = {
    "kunglao": "kunglao_agent_cli.kunglao_cli:main",
    "kunglao-init": "kunglao_agent_cli.kunglao_init_cli:main",
    "kunglao-verify": "kunglao_agent_cli.kunglao_verify_cli:main",
    "kunglao-upgrade": "kunglao_agent_cli.kunglao_upgrade_cli:main",
    "heartbeat-tick": "kunglao_agent_cli.heartbeat_tick_cli:main",
    "convergence-check": "kunglao_agent_cli.convergence_check_cli:main",
}

# wrapper module -> the scripts/ file it faithfully fronts
TARGET_FILES = {
    "kunglao_cli": "kunglao.py",
    "kunglao_init_cli": "kunglao-init.py",
    "kunglao_verify_cli": "kunglao-verify.py",
    "kunglao_upgrade_cli": "kunglao_upgrade.py",
    "heartbeat_tick_cli": "heartbeat_tick.py",
    "convergence_check_cli": "convergence_check.py",
}

# wrappers must mirror the target's own __main__ guard: these four targets
# boot UTF-8 before main(); init/verify dispatch through _entry.run (no boot)
UTF8_BOOT_WRAPPERS = {"kunglao", "kunglao-upgrade", "heartbeat-tick", "convergence-check"}
NO_BOOT_WRAPPERS = {"kunglao-init", "kunglao-verify"}

ADD_PARSER_RE = re.compile(r'sub\.add_parser\(\s*\n?\s*"([a-z][a-z-]*)"', re.M)


def _router_subcommands() -> set[str]:
    """The router's subcommand set, parsed from scripts/kunglao.py itself."""
    found = set(ADD_PARSER_RE.findall(ROUTER.read_text(encoding="utf-8")))
    assert len(found) == 9, f"router subcommand anchor drifted: {sorted(found)}"
    return found


def _wrapper_src(script_name: str) -> str:
    module_name = EXPECTED_SCRIPTS[script_name].split(":")[0].split(".")[-1]
    return (ROOT / "kunglao_agent_cli" / f"{module_name}.py").read_text(encoding="utf-8")


def _cli_registry() -> dict:
    data = yaml.safe_load(YAML_FILE.read_text(encoding="utf-8"))
    cli = data.get("cli")
    assert isinstance(cli, dict), "subcommands.yaml must carry a 'cli' mapping (#416)"
    return cli


# ---------------------------------------------------------------------------
# 1. registration — pyproject [project.scripts] + build backend
# ---------------------------------------------------------------------------

def test_router_has_nine_subcommands() -> None:
    """Anchor: the router really exposes the 9-subcommand surface #416 names."""
    assert _router_subcommands() == {
        "decide", "tick", "verify", "record", "health",
        "resume", "check-stale", "upgrade", "analysis",
    }


def test_project_scripts_table_matches_issue_naming() -> None:
    """[project.scripts] registers exactly the #416 table (no extras, no typos)."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    assert data["project"]["scripts"] == EXPECTED_SCRIPTS


def test_build_backend_present() -> None:
    """[project.scripts] only installs via a build backend — pin its presence
    so a future pyproject cleanup cannot silently drop registration."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    backend = data["build-system"]["build-backend"]
    assert "setuptools" in backend, f"unexpected build backend: {backend}"
    packages = data["tool"]["setuptools"]["packages"]
    assert packages == ["kunglao_agent_cli"]


# ---------------------------------------------------------------------------
# 2. wrappers — importable, invoke the real target, mirror its guard
# ---------------------------------------------------------------------------

def test_wrapper_targets_exist() -> None:
    """Every wrapper fronts a real scripts/ file (the issue's six; the
    hyphenated kunglao-upgrade.py from the issue table is spelled
    kunglao_upgrade.py in reality — wrapper targets the underscore module)."""
    for module_name, target in TARGET_FILES.items():
        assert (ROOT / "kunglao_agent_cli" / f"{module_name}.py").is_file(), module_name
        assert (ROOT / "scripts" / target).is_file(), target


def test_wrappers_importable_with_callable_main() -> None:
    import kunglao_agent_cli  # noqa: F401 — package must import on its own

    for script_name in EXPECTED_SCRIPTS:
        module_name, _, attr = EXPECTED_SCRIPTS[script_name].partition(":")
        module = __import__(module_name, fromlist=[attr])
        assert callable(getattr(module, attr)), script_name


def test_wrapper_main_invokes_target_main(monkeypatch) -> None:
    """Import-test, not assumption: each wrapper actually CALLS the target's
    main and returns its rc (some scripts could execute at import — the
    wrapper contract is invoke-on-call, load-is-side-effect-free)."""
    import kunglao_agent_cli as pkg

    for module_name, target_file in TARGET_FILES.items():
        target = pkg.load_script_module(target_file)
        calls: list[tuple] = []
        monkeypatch.setattr(target, "main", lambda *a, calls=calls: calls.append(a) or 0)
        wrapper = __import__(f"kunglao_agent_cli.{module_name}", fromlist=["main"])
        rc = wrapper.main()
        assert rc == 0, module_name
        assert len(calls) == 1, f"{module_name}: target main not called exactly once"


def test_wrapper_mirrors_target_utf8_boot_guard() -> None:
    """No behavior change: a console-script run must behave like
    `python scripts/<file>.py`, including the UTF-8 boot the target performs
    in its own __main__ guard (init/verify dispatch via _entry.run — no boot)."""
    for name in UTF8_BOOT_WRAPPERS:
        assert "force_utf8" in _wrapper_src(name), f"{name}: missing UTF-8 boot mirror"
    for name in NO_BOOT_WRAPPERS:
        assert "force_utf8" not in _wrapper_src(name), f"{name}: unexpected boot"


def test_loader_fails_loud_on_missing_script() -> None:
    """Never silently swallow a vanished target — a renamed script must break
    the wrapper's import/call loudly, not exit 0 doing nothing."""
    import kunglao_agent_cli as pkg

    try:
        pkg.load_script_module("definitely-not-a-script-416.py")
    except (ImportError, FileNotFoundError) as exc:
        assert "definitely-not-a-script-416" in str(exc)
    else:
        raise AssertionError("missing target must raise, not return")


# ---------------------------------------------------------------------------
# 3. smoke — the registered face actually runs (subprocess = real entry path)
# ---------------------------------------------------------------------------

def _run_entry(argv: list[str]) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    prog, *rest = argv
    code = (f"import sys; sys.argv={argv!r}; "
            f"import {EXPECTED_SCRIPTS[prog].split(':')[0]} as m; m.main()")
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        env=env, timeout=120, cwd=str(ROOT),
    )


def test_entry_point_smoke_help() -> None:
    """Every registered entry answers --help with rc 0 (argparse standard face)."""
    for prog in EXPECTED_SCRIPTS:
        proc = _run_entry([prog, "--help"])
        assert proc.returncode == 0, f"{prog} --help rc={proc.returncode}: {proc.stderr[-400:]}"
        assert "usage" in proc.stdout.lower(), prog


def test_router_entry_point_check_stale_help() -> None:
    """The exact command from the #416 audit that had no backing surface:
    `kunglao check-stale --help` must answer rc 0 through the kunglao entry."""
    proc = _run_entry(["kunglao", "check-stale", "--help"])
    assert proc.returncode == 0, proc.stderr[-400:]
    assert "check-stale" in proc.stdout


# ---------------------------------------------------------------------------
# 4. discoverability — subcommands.yaml `cli:` + help/root menus + README
# ---------------------------------------------------------------------------

def test_subcommands_yaml_cli_section_covers_router() -> None:
    """subcommands.yaml gains a `cli:` sibling of the #456 `subcommands:` map
    (the pinned 5-slash-command registry is untouched — render surfaces of the
    slash face lint separately). The CLI map covers exactly the router's 9."""
    cli = _cli_registry()
    assert set(cli) == _router_subcommands()
    for name, rec in cli.items():
        assert isinstance(rec, dict) and rec.get("usage") and rec.get("summary"), name
        assert rec["usage"].startswith(f"kunglao {name}"), name
        assert str(rec.get("slash", "")).strip(), f"{name}: slash-face cross-reference missing"


def test_help_skill_lists_cli_face() -> None:
    """/kunglao-agent:help menu gains a CLI section listing all 9 subcommand
    tokens and the 5 dedicated console scripts."""
    body = HELP_SKILL.read_text(encoding="utf-8")
    m = re.search(r"^## CLI\b.*?$(.*?)(?=^## )", body, re.S | re.M)
    assert m, "help SKILL.md missing a '## CLI' section (#416)"
    section = m.group(1)
    for name in sorted(_router_subcommands()):
        assert f"kunglao {name}" in section, name
    for dedicated in ("kunglao-init", "kunglao-verify", "kunglao-upgrade",
                      "heartbeat-tick", "convergence-check"):
        assert dedicated in section, dedicated


def test_root_menu_lists_cli_face() -> None:
    """The root /kunglao-agent no-args menu shows the CLI face too — discovery
    must not depend on having read pyproject.toml."""
    menu = re.search(r"^## No arguments.*?$(.*?)(?=^## )", ROOT_SKILL.read_text(encoding="utf-8"),
                     re.S | re.M).group(1)
    assert "kunglao <sub>" in menu
    for name in sorted(_router_subcommands()):
        assert name in menu, name


def test_readme_documents_console_scripts() -> None:
    readme = README.read_text(encoding="utf-8")
    assert "kunglao --help" in readme, "README must teach the CLI discovery command"
    for dedicated in ("kunglao-init", "kunglao-verify", "kunglao-upgrade",
                      "heartbeat-tick", "convergence-check"):
        assert dedicated in readme, dedicated


# ---------------------------------------------------------------------------
# 5. _entry.py docstring + verify-note conditionality
# ---------------------------------------------------------------------------

def test_entry_helper_docstring_disclaims_router_role() -> None:
    """#416 finding 4: `_entry.py` misleads — it is a main-guard helper, not a
    router. Rename is out of scope (many importers); the docstring must say so."""
    text = ENTRY_HELPER.read_text(encoding="utf-8")
    assert "NOT a CLI router" in text
    assert "kunglao.py" in text


def _verify_note_ref_files() -> list[Path]:
    """Live surfaces only: skills/, references/, agents/, README, root SKILL.md.
    docs/design/archive and openspec/ are change-history, not live instructions."""
    roots = [ROOT / "skills", ROOT / "references", ROOT / "agents",
             ROOT / "README.md", ROOT_SKILL]
    hits: list[Path] = []
    for root in roots:
        paths = sorted(root.rglob("*.md")) if root.is_dir() else [root]
        for p in paths:
            if "<malware-veri-notes>" in p.read_text(encoding="utf-8"):
                hits.append(p)
    return hits


def test_external_verify_note_references_are_conditional() -> None:
    """#416 finding 2: verify-note.py belongs to the user-level
    malware-veri-notes skill — absent from this tree/history forever (git log
    --all -- '*verify-note*' is empty; CI skips it, see test_icd203_alignment).
    Every live reference must degrade to conditional, never assert existence."""
    files = _verify_note_ref_files()
    assert files, "sanity: expected at least one malware-veri-notes reference"
    conditional = re.compile(r"installed|absent|not available|not installed|external skill",
                             re.I)
    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if "<malware-veri-notes>" not in line:
                continue
            window = "\n".join(lines[max(0, i - 2):i + 3])
            assert conditional.search(window), (
                f"{path.relative_to(ROOT)}:{i + 1} references the external skill "
                f"unconditionally")
