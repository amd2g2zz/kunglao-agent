# -*- coding: utf-8 -*-
"""#863 Family C — workspace-resolution delegation contract (enforcement test).

Before: 9 ``_resolve_ws`` copies in 4 shapes across scripts/ (issue table
said 8 — statusline_snapshot joined in #883 after the audit), 8 of 9
hardcoding the sibling directory name and silently ignoring a manifest
``layout.workspace_dir`` override (latent bug B2 — the fix-first ruling
folds the behavior fix into this extraction). After:
``scripts/ws_layout.py`` is the ONE resolution source (manifest-aware via
``env_manifest.layout_conventions``); every former copy is a pure alias or
a one-line delegation.

Mirrors tests/test_loader_delegation_863b.py (Family A/B shape): a
mechanical confinement scan + wiring markers + identity-level delegation
asserts + util contract pins. Behavioral equivalence of all 4 pre-fix
shapes stays pinned by tests/test_env_manifest.py (4-shape coverage,
B2 two-state).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

# Every former copy site routes through ws_layout. Each entry names the
# util function its shape maps to (quiet = silent cwd-fallback family;
# strict = the #228 hard-error family).
WIRING = {
    # quiet + claim-register sentinel (the manifest-aware original + the
    # two hardcoded-quiet shapes that collapse into it post-B2-fix):
    "scripts/convergence_check.py": "resolve_quiet",
    "scripts/failure_analysis_gate.py": "resolve_quiet",
    "scripts/route_capability.py": "resolve_quiet",
    # quiet + ledger sentinel variant:
    "scripts/convergence_health.py": "resolve_quiet",
    # the #228 hard-error family:
    "scripts/heartbeat_tick.py": "resolve_strict",
    "scripts/hooks_selfcheck.py": "resolve_strict",
    "scripts/heartbeat_touch.py": "resolve_strict",
    "scripts/statusline_snapshot.py": "resolve_strict",
    # the util itself must exist where we say it is:
    "scripts/ws_layout.py": "layout_conventions",
}


def _repo_python_files():
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith("tests/"):        # fixtures may rebuild shapes freely
            continue
        if rel.startswith((".git", ".review", "openspec/", ".worktrees",
                           ".venv/", "venv/")):  # deps/virtualenvs, not repo code
            continue
        yield p, rel


def _resolve_ws_def_body(text: str) -> str | None:
    """Body of a `def _resolve_ws` definition (up to the next top-level
    def), or None when the file does not define one."""
    idx = text.find("def _resolve_ws")
    if idx < 0:
        return None
    rest = text[idx:]
    nxt = rest.find("\ndef ", 1)
    return rest if nxt < 0 else rest[:nxt]


# --------------------------------------------------------------------------
# confinement: a `def _resolve_ws` may exist ONLY as delegation to the
# ws_layout util — the probe logic (hardcoded sibling literal, direct
# layout_conventions calls) must never reappear in a consumer.
# --------------------------------------------------------------------------

def test_resolve_ws_probe_logic_confined():
    offenders = {}
    for p, rel in _repo_python_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        body = _resolve_ws_def_body(text)
        if body is None:
            continue
        bad = []
        if "malware-analysis-workspace" in body:
            bad.append("hardcoded sibling literal")
        if "layout_conventions" in body:
            bad.append("direct layout_conventions call")
        if "ws_layout" not in body:
            bad.append("no ws_layout delegation")
        if bad:
            offenders[rel] = bad
    assert offenders == {}, (
        "every `def _resolve_ws` must be pure delegation to scripts/"
        f"ws_layout.py (#863 Family C); offenders: {offenders}")


# --------------------------------------------------------------------------
# wiring: every former copy site imports the canonical util (static half;
# the identity half is test_resolve_ws_alias_identity below).
# --------------------------------------------------------------------------

def test_resolve_ws_wiring_is_delegated():
    missing = {}
    for rel, marker in WIRING.items():
        path = ROOT / rel
        if not path.exists():
            missing[rel] = "<file gone>"
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "ws_layout" not in text:
            missing[rel] = "ws_layout import"
        elif marker not in text:
            missing[rel] = marker
    assert missing == {}, (
        "every former _resolve_ws copy must reference the canonical "
        f"ws_layout util (#863 Family C); missing wiring: {missing}")


# --------------------------------------------------------------------------
# identity-level delegation: the aliased sites must bind the util function
# ITSELF (not a wrapper, not a re-implementation).
# --------------------------------------------------------------------------

def _import(mod_name: str):
    import importlib
    return importlib.import_module(mod_name)


def test_resolve_ws_alias_identity():
    import ws_layout
    quiet = ["convergence_check", "failure_analysis_gate",
             "route_capability"]
    strict = ["heartbeat_tick", "hooks_selfcheck", "heartbeat_touch",
              "statusline_snapshot"]
    drifted = {}
    for name in quiet:
        if getattr(_import(name), "_resolve_ws", None) is not ws_layout.resolve_quiet:
            drifted[name] = "not ws_layout.resolve_quiet"
    for name in strict:
        if getattr(_import(name), "_resolve_ws", None) is not ws_layout.resolve_strict:
            drifted[name] = "not ws_layout.resolve_strict"
    # convergence_health keeps a 2-line def (ledger sentinel override) —
    # its delegation is pinned by the confinement test above.
    assert drifted == {}, (
        "aliased _resolve_ws sites must bind the ws_layout function itself "
        f"(#863 Family C); drifted: {drifted}")


# --------------------------------------------------------------------------
# util contract pins (the exact arg semantics the 9 copies relied on)
# --------------------------------------------------------------------------

def test_resolve_quiet_arg_wins_unresolved():
    """Quiet shape: explicit arg wins WITHOUT resolve() — convergence_check
    and the silent copies returned Path(arg) verbatim."""
    import ws_layout
    out = ws_layout.resolve_quiet("relative/ws")
    assert out == Path("relative/ws")
    assert not out.is_absolute()


def test_resolve_strict_arg_wins_resolved():
    """Strict shape (#228): explicit arg wins, resolved absolute."""
    import ws_layout
    out = ws_layout.resolve_strict("relative/ws")
    assert out == Path("relative/ws").resolve()
    assert out.is_absolute()


def test_resolve_strict_exits_2_with_guidance(tmp_path, monkeypatch, capsys):
    """Nothing found → stderr guidance + sys.exit(2) — the #228 never-guess
    contract, byte-shaped like the four former inline copies."""
    import ws_layout
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    with __import__("pytest").raises(SystemExit) as exc:
        ws_layout.resolve_strict(None)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "no workspace found under cwd" in err
    assert "pass the workspace" in err
