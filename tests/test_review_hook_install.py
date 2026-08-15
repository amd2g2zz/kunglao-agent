# -*- coding: utf-8 -*-
"""Issue #367 — review-key path: template placeholder + install-time stamping.

The pre-#367 template hardcoded key="C:/Users/hr/.claude/kunglao-review.key"
(author username ships publicly; the gate is dead on every non-hr machine —
missing key = blocked commit). The #147 anti-forgery constraint forbids
env-resolving the path at commit time (a subagent must not redirect it via
HOME/USERPROFILE and self-mint+approve), so the fix is install-time
stamping:

  1. The tracked template .claude/git-hooks/pre-commit carries the literal
     placeholder __KUNGLAO_REVIEW_KEY__ instead of a real path.
  2. A human-run installer (kunglao-init --install-git-hooks) copies the
     template to .git/hooks/pre-commit, substituting the installer's
     $HOME/.claude/kunglao-review.key (resolved ONCE, at install time) for
     the placeholder, chmod +x.
  3. The installed copy fail-closes: if it still contains the literal
     placeholder (never stamped), the hook prints install guidance and
     exits 1 — same fail-closed shape as the missing-key path.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / ".claude" / "git-hooks" / "pre-commit"
INIT = ROOT / "scripts" / "kunglao-init.py"

PLACEHOLDER = "__KUNGLAO_REVIEW_KEY__"


# ---------------------------------------------------------------------------
# template side
# ---------------------------------------------------------------------------

def test_template_carries_placeholder_not_real_key_path() -> None:
    """The tracked template must reference the placeholder, never a real
    Windows/user path (#367 finding: the template shipped C:/Users/hr/...)."""
    text = TEMPLATE.read_text(encoding="utf-8")
    assert PLACEHOLDER in text, (
        f"template must carry the {PLACEHOLDER} placeholder for install-time "
        "stamping (#367)")
    # a stamped absolute path of the installing user must NOT be pre-baked
    assert "C:/Users/" not in text, "template must not ship any real user path"


def test_installed_hook_with_placeholder_residue_fails_closed(tmp_path: Path) -> None:
    """An unstamped hook (literal placeholder still present) must block the
    commit with install guidance — running the TEMPLATE itself against a
    scratch repo simulates exactly that (the template never gets stamped)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True, timeout=60)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "feature/x"],
                   check=True, timeout=60)
    # an initial commit: an unborn HEAD makes the hook fail on branch
    # resolution before ever reaching the key check under test.
    # -c identity: CI runners carry no git user (macOS synthesizes one
    # locally) — without it git exits 128 "Author identity unknown".
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=CI",
                    "-c", "user.email=ci@test.invalid", "commit", "-q",
                    "--allow-empty", "-m", "bootstrap"],
                   check=True, timeout=60)
    # template is executable and runs `sh`-portable; invoke via sh with the
    # scratch repo as cwd (the hook resolves the repo from git rev-parse)
    r = subprocess.run(
        ["sh", str(TEMPLATE)],
        cwd=repo, capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 1, (
        f"unstamped template must fail closed (rc={r.returncode}): "
        f"{r.stdout}{r.stderr}")
    out = r.stdout + r.stderr
    assert "REVIEW GATE BLOCKED" in out, out
    assert "install" in out.lower(), (
        f"guidance must tell the human how to install the hook: {out}")


# ---------------------------------------------------------------------------
# installer side (kunglao-init --install-git-hooks)
# ---------------------------------------------------------------------------

def _run_init_flag(ws: Path, home: Path, extra: list[str]) -> subprocess.CompletedProcess:
    env = {
        k: v for k, v in os.environ.items()
        if k != "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"
    }
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["PYTHONIOENCODING"] = "utf-8"
    argv = [sys.executable, str(INIT), str(ws), *extra]
    return subprocess.run(argv, capture_output=True, text=True, timeout=120,
                          env=env, errors="replace")


def _git_repo(ws: Path) -> None:
    subprocess.run(["git", "-C", str(ws), "init", "-q"], check=True, timeout=60)
    subprocess.run(["git", "-C", str(ws), "checkout", "-q", "-b", "trunk"],
                   check=True, timeout=60)
    # an initial commit: on unborn HEAD the hook fails on branch resolution
    # before ever reaching the key-path branch under test.
    # -c identity: CI runners carry no git user (macOS synthesizes one
    # locally) — without it git exits 128 "Author identity unknown".
    subprocess.run(["git", "-C", str(ws), "-c", "user.name=CI",
                    "-c", "user.email=ci@test.invalid", "commit", "-q",
                    "--allow-empty", "-m", "bootstrap"],
                   check=True, timeout=60)


def test_install_git_hooks_stamps_real_key_path(tmp_path: Path) -> None:
    """Happy path: key present at $HOME/.claude/kunglao-review.key ->
    installer writes .git/hooks/pre-commit with the REAL absolute path
    substituted for the placeholder, executable, placeholder gone."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "s.exe").write_bytes(b"MZ" + b"\x00" * 64)
    _git_repo(ws)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    key = home / ".claude" / "kunglao-review.key"
    key.write_text("a" * 64, encoding="utf-8")

    r = _run_init_flag(ws, home, ["--install-git-hooks", "--skip-toolchain"])
    assert r.returncode == 0, f"init failed: {r.stdout}{r.stderr}"

    hook = ws / ".git" / "hooks" / "pre-commit"
    assert hook.exists(), "installer must write .git/hooks/pre-commit"
    text = hook.read_text(encoding="utf-8")
    # placeholder must be gone from the key ASSIGNMENT; it legitimately
    # survives in the comment block and the [ "$key" = ... ] comparison
    # guard (that guard is what fail-closes an unstamped copy)
    import re
    m = re.search(r'^key="(.*)"$', text, re.M)
    assert m, "installed hook must keep the key=\"...\" assignment shape"
    assert PLACEHOLDER not in m.group(1), (
        "the stamped assignment must carry the real path, not the placeholder")
    # POSIX separators (hook runs via sh; backslashes get eaten as escapes)
    expected = (home / ".claude" / "kunglao-review.key").as_posix()
    assert expected in text, (
        f"installed hook must embed the real absolute key path {expected}: {text}")
    mode = stat.S_IMODE(hook.stat().st_mode)
    assert mode & stat.S_IXUSR, f"installed hook must be executable (mode {mode:o})"


def test_install_git_hooks_without_key_prints_key_init_guidance(
        tmp_path: Path) -> None:
    """Key absent -> installer still installs the hook (fail-closed template:
    it blocks until a key exists) and prints the review_gate.py key-init
    command the human must run (#367 acceptance: installer guides key-init)."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "s.exe").write_bytes(b"MZ" + b"\x00" * 64)
    _git_repo(ws)
    home = tmp_path / "home"
    home.mkdir()

    r = _run_init_flag(ws, home, ["--install-git-hooks", "--skip-toolchain"])
    assert r.returncode == 0, (
        f"missing key is guidance, not failure: {r.stdout}{r.stderr}")
    out = r.stdout + r.stderr
    assert "review_gate.py" in out and "key-init" in out, (
        f"must guide `python scripts/review_gate.py key-init <path>`: {out}")
    hook = ws / ".git" / "hooks" / "pre-commit"
    assert hook.exists(), "hook installs regardless; the hook itself fails closed"


def test_install_git_hooks_stamp_is_env_independent_at_commit_time(
        tmp_path: Path) -> None:
    """#147 anti-forgery preservation: the STAMPED path is a literal in the
    installed hook — a commit-time HOME redirection must NOT change the key
    the gate consults. Run the installed hook with HOME pointed elsewhere:
    it must still reference (and fail on) the ORIGINAL stamped path."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "s.exe").write_bytes(b"MZ" + b"\x00" * 64)
    _git_repo(ws)
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    key = home / ".claude" / "kunglao-review.key"
    key.write_text("a" * 64, encoding="utf-8")

    r = _run_init_flag(ws, home, ["--install-git-hooks", "--skip-toolchain"])
    assert r.returncode == 0, r.stdout + r.stderr

    # delete the key, redirect HOME to a fake home carrying a DIFFERENT key,
    # run the installed hook: it must fail on the ORIGINAL path (literal in
    # the script), never fall back to the fake home.
    key.unlink()
    fake = tmp_path / "fake-home"
    (fake / ".claude").mkdir(parents=True)
    (fake / ".claude" / "kunglao-review.key").write_text("b" * 64)
    env = {"HOME": str(fake), "USERPROFILE": str(fake),
           "PATH": os.environ.get("PATH", "")}
    r2 = subprocess.run(["sh", str(ws / ".git" / "hooks" / "pre-commit")],
                        cwd=ws, capture_output=True, text=True, env=env,
                        timeout=60)
    assert r2.returncode == 1, "redirected HOME must not satisfy the gate"
    out = r2.stdout + r2.stderr
    assert key.as_posix() in out, (
        f"hook must name the STAMPED key path ({key.as_posix()}), not resolve "
        f"HOME at commit time: {out}")


def test_install_git_hooks_refuses_non_git_workspace(tmp_path: Path) -> None:
    """No .git -> nothing to install into; refuse with a clear message and a
    distinct exit code, never create stray files."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "s.exe").write_bytes(b"MZ" + b"\x00" * 64)
    home = tmp_path / "home"
    home.mkdir()
    r = _run_init_flag(ws, home, ["--install-git-hooks", "--skip-toolchain"])
    out = r.stdout + r.stderr
    assert "unrecognized arguments" not in out, (
        f"the --install-git-hooks flag must exist: {out}")
    assert r.returncode != 0, "non-git workspace must not silently pass"
    assert "git" in out.lower(), out
    assert not (ws / ".git").exists()
