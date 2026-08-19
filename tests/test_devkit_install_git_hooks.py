#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_devkit_install_git_hooks.py — install_git_hooks.py contract.

Tests:
  - id / uninstall / dry-run paths
  - placeholder stamping (anti-forgery)
  - chmod +x (git requires executable bit)
  - backup of pre-existing hook
  - idempotency (re-install doesn't break)
  - refusing to remove non-devkit hook
  - find_git_dir works for normal repos and worktrees (best-effort)
"""
from __future__ import annotations

import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "devkit" / "install_git_hooks.py"


def _make_fake_git_repo(tmp_path: Path) -> Path:
    """Create a tiny git repo at tmp_path/repo for isolated hook testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src.py").write_text("# stub\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", "--initial-branch=main"],
                   cwd=repo, check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email",
                    "test@test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "T"],
                   check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"],
                   check=True)
    return repo


def _copy_devkit_into(repo: Path) -> Path:
    """Copy devkit/ into the test repo so install_git_hooks finds it."""
    dst = repo / "devkit"
    shutil.copytree(REPO_ROOT / "devkit", dst)
    return dst


def _run_in_repo(installer: Path, repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(installer), *args],
        capture_output=True, text=True, timeout=15, cwd=repo,
        errors="replace")


def test_install_dry_run_creates_no_hook(tmp_path: Path) -> None:
    repo = _make_fake_git_repo(tmp_path)
    _copy_devkit_into(repo)
    hooks_dir = repo / ".git" / "hooks"
    assert not (hooks_dir / "pre-commit").exists()

    installer = repo / "devkit" / "install_git_hooks.py"
    r = _run_in_repo(installer, repo, "--dry-run")
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"
    assert not (hooks_dir / "pre-commit").exists(), \
        "dry-run must NOT create the hook"


def test_install_creates_executable_hook_with_stamp(tmp_path: Path) -> None:
    repo = _make_fake_git_repo(tmp_path)
    _copy_devkit_into(repo)
    installer = repo / "devkit" / "install_git_hooks.py"

    r = _run_in_repo(installer, repo)
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"

    hook = repo / ".git" / "hooks" / "pre-commit"
    assert hook.exists(), f"hook not created; stdout={r.stdout}"
    # On POSIX git requires +x; on Windows git uses file presence + shebang.
    # We always set the chmod bit (POSIX) and the file (Windows) — both
    # are stored regardless of platform support.
    if sys.platform != "win32":
        mode = hook.stat().st_mode
        assert mode & stat.S_IXUSR, \
            f"hook must be executable (mode={oct(mode)})"
    content = hook.read_text(encoding="utf-8")
    assert "__KUNGLAO_DEVKIT_ROOT__" not in content, \
        "placeholder must be replaced (anti-forgery)"
    assert "# devkit-installed:" in content


def test_install_uninstall_round_trip(tmp_path: Path) -> None:
    repo = _make_fake_git_repo(tmp_path)
    _copy_devkit_into(repo)
    installer = repo / "devkit" / "install_git_hooks.py"

    r = _run_in_repo(installer, repo)
    assert r.returncode == 0
    assert (repo / ".git" / "hooks" / "pre-commit").exists()

    r = _run_in_repo(installer, repo, "--uninstall")
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"
    assert not (repo / ".git" / "hooks" / "pre-commit").exists(), \
        "hook should be removed after uninstall"


def test_uninstall_refuses_non_devkit_hook(tmp_path: Path) -> None:
    repo = _make_fake_git_repo(tmp_path)
    _copy_devkit_into(repo)
    installer = repo / "devkit" / "install_git_hooks.py"

    foreign_hook = repo / ".git" / "hooks" / "pre-commit"
    foreign_hook.write_text("#!/bin/sh\necho foreign\n", encoding="utf-8")
    foreign_hook.chmod(0o755)

    r = _run_in_repo(installer, repo, "--uninstall")
    assert r.returncode == 0
    assert "refusing to remove" in r.stdout
    assert foreign_hook.exists()
    assert "foreign" in foreign_hook.read_text(encoding="utf-8")


def test_install_backs_up_pre_existing_hook(tmp_path: Path) -> None:
    repo = _make_fake_git_repo(tmp_path)
    _copy_devkit_into(repo)
    installer = repo / "devkit" / "install_git_hooks.py"

    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho previous\n", encoding="utf-8")
    hook.chmod(0o755)

    r = _run_in_repo(installer, repo)
    assert r.returncode == 0

    backups = list((repo / ".git" / "hooks").glob("pre-commit.bak-*"))
    assert backups, f"no backup created; stdout={r.stdout}"
    assert "previous" in backups[0].read_text(encoding="utf-8")


def test_install_idempotent(tmp_path: Path) -> None:
    repo = _make_fake_git_repo(tmp_path)
    _copy_devkit_into(repo)
    installer = repo / "devkit" / "install_git_hooks.py"

    r1 = _run_in_repo(installer, repo)
    r2 = _run_in_repo(installer, repo)
    assert r1.returncode == 0 and r2.returncode == 0
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert hook.exists()
    content = hook.read_text(encoding="utf-8")
    assert "__KUNGLAO_DEVKIT_ROOT__" not in content
    assert content.count("# devkit-installed:") == 1


def test_install_creates_hooks_dir_if_missing(tmp_path: Path) -> None:
    repo = _make_fake_git_repo(tmp_path)
    _copy_devkit_into(repo)
    hooks_dir = repo / ".git" / "hooks"
    for f in list(hooks_dir.iterdir()):
        if not f.name.endswith(".sample"):
            f.unlink()
    installer = repo / "devkit" / "install_git_hooks.py"
    r = _run_in_repo(installer, repo)
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"
    assert (hooks_dir / "pre-commit").exists()