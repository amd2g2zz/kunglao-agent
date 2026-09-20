# -*- coding: utf-8 -*-
"""Issue #240 — fail-closed convergence_check workspace identity (unit face).

Field evidence: running convergence_check from a non-workspace cwd resolved
the cwd (or a stray sibling register) as the workspace via the silent
$PWD-fallback family, and an empty claim-register.yaml degenerated into a
WRONG CONVERGED (missing task_spec face -> zero primary_questions -> every
DRAIN gate silent). A false CONVERGED is the dangerous direction.

Contract (issue #240):
  - a resolved directory without claim-register.yaml AND task_spec.yaml is
    NOT a kunglao workspace: hard error "not a kunglao workspace", exit 64
    (EXIT_MISSING_WORKSPACE), never a verdict;
  - the valid no-arg sibling probe keeps working (verdict must stay
    identical across cwds when the workspace is real).

Fast tier: in-process main()/resolver calls only (the CLI cwd matrix,
which spawns the script per row, lives in test_convergence_cwd_matrix_240).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import convergence_check as cc  # noqa: E402

# Default layout convention (env_manifest DEFAULT_LAYOUT workspace_dir).
WS_DIRNAME = "malware-analysis-workspace"

REGISTER_NAME = "claim-register.yaml"
TASK_SPEC_NAME = "task_spec.yaml"


def _seed(ws: Path, *, register: bool = True, task_spec: bool = True) -> Path:
    """Seed a directory with the workspace identity markers."""
    ws.mkdir(parents=True, exist_ok=True)
    if register:
        (ws / REGISTER_NAME).write_text("claims: []\n", encoding="utf-8")
    if task_spec:
        (ws / TASK_SPEC_NAME).write_text(
            "primary_questions: []\n", encoding="utf-8")
    return ws


def _assert_not_a_workspace(excinfo, captured) -> None:
    """The #240 hard-error shape: exit 64, message, no verdict bytes."""
    assert excinfo.value.code == cc.EXIT_MISSING_WORKSPACE
    err = captured.err
    assert "not a kunglao workspace" in err, f"stderr={err[-300:]}"
    assert "CONVERGED" not in captured.out, "a verdict escaped the hard error"


# ------------------------------------------------------------------
# the issue repro, in-process: register-only cwd + the template's `.` arg
# ------------------------------------------------------------------

def test_register_only_cwd_dot_arg_hard_errors(tmp_path, monkeypatch, capsys):
    """A directory holding ONLY an empty claim-register.yaml is not a
    workspace: hard error, never a verdict. Pre-fix this returned rc=0
    CONVERGED — the exact wrong verdict the issue forbids."""
    decoy = _seed(tmp_path / "decoy", task_spec=False)
    monkeypatch.chdir(decoy)
    with pytest.raises(SystemExit) as excinfo:
        cc.main(["."])  # the template-prescribed invocation, pre-#240
    _assert_not_a_workspace(excinfo, capsys.readouterr())


def test_task_spec_only_cwd_is_not_a_workspace(tmp_path, monkeypatch, capsys):
    """Identity needs BOTH markers: task_spec.yaml alone hard-errors too."""
    decoy = _seed(tmp_path / "half", register=False)
    monkeypatch.chdir(decoy)
    with pytest.raises(SystemExit) as excinfo:
        cc.main(["."])
    _assert_not_a_workspace(excinfo, capsys.readouterr())


def test_markerless_cwd_without_arg_hard_errors(tmp_path, monkeypatch, capsys):
    """The else-$PWD fallback dies: a cwd with no markers and no valid
    sibling is a hard error, not a resolved 'workspace'."""
    empty = tmp_path / "empty-cwd"
    empty.mkdir()
    monkeypatch.chdir(empty)
    with pytest.raises(SystemExit) as excinfo:
        cc.main([])
    captured = capsys.readouterr()
    _assert_not_a_workspace(excinfo, captured)
    # both missing markers are named, so the caller can fix the path
    assert REGISTER_NAME in captured.err and TASK_SPEC_NAME in captured.err


# ------------------------------------------------------------------
# the resolver function: pure-unit face of the same contract
# ------------------------------------------------------------------

def test_resolver_accepts_valid_workspace(tmp_path):
    ws = _seed(tmp_path / "ws")
    out = cc._require_workspace(str(ws))
    assert out == ws.resolve()
    assert out.is_absolute()


def test_resolver_accepts_dot_from_valid_workspace(tmp_path, monkeypatch):
    """An explicit `.` from INSIDE a real workspace still resolves — the
    argument style is discouraged, not the location."""
    ws = _seed(tmp_path / "ws")
    monkeypatch.chdir(ws)
    assert cc._require_workspace(".") == ws.resolve()


def test_resolver_sibling_probe_keeps_working(tmp_path, monkeypatch):
    """No-arg from the parent of a REAL workspace still finds it via the
    manifest sibling probe — verdict identity across cwds is preserved."""
    home = tmp_path / "home"
    ws = _seed(home / WS_DIRNAME)
    monkeypatch.chdir(home)
    assert cc._require_workspace(None) == ws.resolve()


def test_resolver_rejects_decoy_sibling(tmp_path, monkeypatch, capsys):
    """A sibling dir with a stray register but no task_spec is NOT resolved
    as the workspace — the fallback that produced the wrong CONVERGED."""
    home = tmp_path / "decoy-home"
    _seed(home / WS_DIRNAME, task_spec=False)
    monkeypatch.chdir(home)
    with pytest.raises(SystemExit) as excinfo:
        cc._require_workspace(None)
    _assert_not_a_workspace(excinfo, capsys.readouterr())


def test_resolver_rejects_missing_explicit_path(tmp_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        cc._require_workspace(str(tmp_path / "absent"))
    _assert_not_a_workspace(excinfo, capsys.readouterr())
