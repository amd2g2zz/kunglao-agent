# -*- coding: utf-8 -*-
"""tests/test_ws_flag_args_739.py — flags are not workspace paths.

RC1 live evidence (re-labs/ctf-1, 2026-10-16 03:45:17): the
orchestrating model ran `heartbeat_touch --help` expecting usage text;
`ws_layout.resolve_strict` honored the arg unconditionally
(`Path("--help").resolve()`), and the touch silently created a literal
`--help/` workspace — runs/, .heartbeat.json, a whole log tree under a
directory named after the flag. The "never guess" discipline only
guarded the no-arg path.

The fix: a dash-leading arg is a FLAG, not a path. The strict family
says so loudly (stderr + exit 2 — the same guidance posture as the
nothing-found face); the quiet family treats it as absent (its
contract is silence) and probes as if no arg was passed.

Pins: strict rejects the flag shapes loudly; strict still honors real
paths; quiet falls back silently; and the RC1 repro — heartbeat_touch
--help exits 2 and creates NO directory.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from ws_layout import resolve_quiet, resolve_strict  # noqa: E402

FLAG_ARGS = ["--help", "-h", "--ws", "-o", "--workspace"]


def _marked_ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": []}), encoding="utf-8")
    return ws


# ---------- the strict family: loud refusal ---------------------------------

@pytest.mark.parametrize("flag", FLAG_ARGS)
def test_strict_rejects_flag_args_loudly(tmp_path, capsys, flag):
    with pytest.raises(SystemExit) as exc:
        resolve_strict(flag)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "flag" in err.lower()
    assert not (tmp_path / flag.lstrip("-")).exists()


def test_strict_still_honors_real_paths(tmp_path):
    """The arg-wins contract is untouched for actual paths: a marked
    workspace passed explicitly resolves to itself."""
    ws = _marked_ws(tmp_path)
    assert resolve_strict(str(ws)) == ws.resolve()


# ---------- the quiet family: silent fallback -------------------------------

def test_quiet_treats_flag_arg_as_absent(tmp_path, monkeypatch):
    """resolve_quiet's contract is silence: a flag arg degrades to the
    no-arg probe (sibling workspace with the sentinel wins; else cwd)
    instead of resolving a flag-named path. The sibling name follows the
    manifest convention (the probe's actual face)."""
    import env_manifest
    sub_name = env_manifest.layout_conventions(tmp_path).workspace_dir
    ws = tmp_path / sub_name
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": []}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert resolve_quiet("--help") == ws           # the sibling probe
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    assert resolve_quiet("-h") == plain.resolve()  # the cwd fallback


# ---------- the RC1 repro, end to end ---------------------------------------

def _worktree_heartbeat_touch():
    """Load THIS worktree's heartbeat_touch by path — the venv also
    installs a packaged copy whose main() is an older shape, and the
    pin is about THIS file's behavior."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "heartbeat_touch_739", SCRIPTS / "heartbeat_touch.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_heartbeat_touch_help_makes_no_directory(tmp_path, monkeypatch):
    """The live RC1 bug: `heartbeat_touch --help` once created a literal
    `--help/` workspace. Now it exits 2 with guidance and writes
    nothing."""
    mod = _worktree_heartbeat_touch()
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    with pytest.raises(SystemExit) as exc:
        mod.main(["--help"])
    assert exc.value.code == 2
    assert not (plain / "--help").exists()
    assert list(plain.iterdir()) == []            # nothing written at all
