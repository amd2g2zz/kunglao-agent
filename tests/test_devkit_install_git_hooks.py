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


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "devkit" / "install_git_hooks.py"

sys.path.insert(0, str(REPO_ROOT / "devkit"))
import install_git_hooks  # noqa: E402  (devkit module, path-inserted)


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
    # The marker line is appended once at the END of the file by
    # `install_git_hooks.py`. The hook template may mention the literal
    # string `# devkit-installed:` in prose comments, so we count the
    # line-anchored form (the actual marker is `# devkit-installed: <path>`).
    assert sum(1 for line in content.splitlines()
               if line.startswith("# devkit-installed: ")) == 1
    assert sum(1 for line in content.splitlines()
               if line.startswith("# devkit-review-key: ")) == 1


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


def _hook_template_text() -> str:
    return (REPO_ROOT / "devkit" / "githooks" / "pre-commit").read_text(
        encoding="utf-8")


def test_hook_template_chains_product_review_gate() -> None:
    # The devkit hook is the single resident pre-commit entry: after the
    # quality gates pass it must chain the product review-gate evidence
    # check (fail-closed), replacing the old standalone review hook.
    text = _hook_template_text()
    assert '"$skill_root/scripts/review_gate.py"' in text
    # The keyfile MUST come from the install-time stamp — an env-resolved
    # default would let a fake $HOME self-mint past the gate.
    assert 'check "$repo" "$out" "$branch" "$review_key"' in text
    assert "grep '^# devkit-review-key: '" in text
    assert '[ "$branch" = "HEAD" ]' in text
    # Gates judge the committing tree with its own tracked devkit.
    assert '"$repo/devkit/quality_gates.py"' in text


def test_hook_template_routes_gates_through_uv() -> None:
    # uv-only discipline: bare python on the PATH is unreliable (stray
    # venvs shadow the project interpreter), so both the quality gates
    # and the chained review check must run via `uv run --project`.
    text = _hook_template_text()
    assert 'uv run --project "$skill_root"' in text
    assert 'PY="$(command -v python)"' not in text


def test_hook_template_keeps_registry_minus_gate2() -> None:
    # The quick set must stay equal to the GATES registry minus the
    # opt-in Gate 2 (test_doc_sync derives the registry — never hardcode
    # the count anywhere else; this pin guards the invocation literal).
    text = _hook_template_text()
    assert "1 3 4 5 6 7 8 9 10 --quiet" in text


def test_find_git_dir_resolves_worktree_pointer_to_common_dir(
        tmp_path: Path) -> None:
    # A worktree's .git FILE points at <common>/.git/worktrees/<name>.
    # git executes hooks ONLY from the common dir, so the installer must
    # resolve there (the docstring always claimed this; the code didn't).
    common = tmp_path / "common"
    (common / ".git").mkdir(parents=True)
    wt = tmp_path / "wt"
    wtgitdir = common / ".git" / "worktrees" / "wt"
    wtgitdir.mkdir(parents=True)
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {wtgitdir}\n", encoding="utf-8")
    assert install_git_hooks._find_git_dir(wt) == common / ".git"


def test_install_from_worktree_targets_common_hooks(tmp_path: Path) -> None:
    repo = _make_fake_git_repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q",
                    str(repo / "wt"), "-b", "wtbranch"], check=True)
    wt = repo / "wt"
    shutil.copytree(REPO_ROOT / "devkit", wt / "devkit")
    installer = wt / "devkit" / "install_git_hooks.py"
    r = subprocess.run([sys.executable, str(installer)],
                       capture_output=True, text=True, timeout=30, cwd=wt,
                       errors="replace")
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"
    common_hook = repo / ".git" / "hooks" / "pre-commit"
    assert common_hook.exists()
    assert "devkit-installed:" in common_hook.read_text(encoding="utf-8")
    assert not (repo / ".git" / "worktrees" / "wt" / "hooks"
                / "pre-commit").exists()