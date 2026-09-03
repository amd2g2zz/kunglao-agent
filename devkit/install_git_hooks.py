#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""install_git_hooks.py — deploy devkit git hooks (#463).

Deploys `devkit/githooks/<name>` to `<repo>/.git/hooks/<name>` (or to the
git common-dir if `core.hooksPath` is set). Stamps the install-time
absolute devkit_root into the deployed hook so commit-time env
redirection cannot alter it (anti-forgery: same pattern as #367).

Usage:
  uv run python devkit/install_git_hooks.py                # install
  uv run python devkit/install_git_hooks.py --uninstall    # remove
  uv run python devkit/install_git_hooks.py --dry-run      # preview

Behaviour:
- Installs ONLY devkit-owned hooks (those in `devkit/githooks/`). The
  product's `.claude/git-hooks/pre-commit` template is NOT touched —
  dev hooks and product review hooks coexist on different names if both
  are present, or `pre-commit.devkit` vs `pre-commit.kunglao-review` if
  same name. (We default to `pre-commit` since the product review gate
  lives in `.claude/git-hooks/` and is a separate concept.)
- Per-hook backups of any pre-existing `.git/hooks/<name>` are written
  to `.git/hooks/<name>.bak-<UTC-ts>` before overwriting.
- Cross-platform: pure Python; works on Windows / Linux / macOS.
- Idempotent: re-running install overwrites the deployed hook with the
  same stamped path; safe to re-run.

Exit codes:
  0 = success
  1 = not a git repo
  2 = devkit/githooks/ missing or empty
  3 = uninstall requested but no devkit hook installed

Anti-forgery note (the absolute path stamp):
    After installation, the deployed `.git/hooks/pre-commit` contains a
    literal `devkit_root="<absolute path to this devkit>"`. A subagent
    that sets `KUNGLAO_DEVKIT_ROOT=/tmp/fake-devkit` at commit time
    CANNOT alter the literal — the hook reads the embedded stamp, not
    the env. To bypass, the attacker would need write access to
    `.git/hooks/pre-commit` itself, which already requires the same
    trust as committing code.
"""
from __future__ import annotations

import argparse
import datetime
import shutil
import stat
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEVKIT_ROOT = Path(__file__).resolve().parent
GITHOOKS_SRC = DEVKIT_ROOT / "githooks"
PLACEHOLDER = "__KUNGLAO_DEVKIT_ROOT__"
DEVKIT_HOOK_MARKER = "# devkit-installed:"


def _find_git_dir(start: Path) -> Path | None:
    """Locate the .git directory (or common-dir if worktrees)."""
    p = start
    for _ in range(8):  # walk up to 8 levels
        candidate = p / ".git"
        if candidate.is_dir():
            return candidate
        if candidate.is_file():
            try:
                target = candidate.read_text(encoding="utf-8").strip()
                if target.startswith("gitdir:"):
                    real = Path(target.split(":", 1)[1].strip())
                    if real.is_dir():
                        return real
            except OSError:
                pass
        if p.parent == p:
            return None
        p = p.parent
    return None


def _git_hooks_dir(git_dir: Path) -> Path:
    """Resolve hooks dir (respects `core.hooksPath` if set)."""
    try:
        r = subprocess.run(
            ["git", "config", "--get", "core.hooksPath"],
            cwd=git_dir.parent, capture_output=True, text=True, timeout=10,
            errors="replace")
        if r.returncode == 0 and r.stdout.strip():
            configured = Path(r.stdout.strip())
            if not configured.is_absolute():
                configured = (git_dir.parent / configured).resolve()
            configured.mkdir(parents=True, exist_ok=True)
            return configured
    except (OSError, subprocess.TimeoutExpired):
        pass
    return git_dir / "hooks"


def _stamp_hook(template: str, devkit_root: Path) -> str:
    """Replace PLACEHOLDER with the absolute devkit_root path."""
    if PLACEHOLDER not in template:
        return template  # already stamped (re-install) — pass through
    return template.replace(PLACEHOLDER, str(devkit_root).replace("\\", "/"))


def _install_one(src: Path, dst: Path, devkit_root: Path,
                 dry_run: bool = False) -> str:
    """Install one hook. Returns a status string for logging."""
    template = src.read_text(encoding="utf-8")
    stamped = _stamp_hook(template, devkit_root)

    backup = None
    if dst.exists():
        ts = datetime.datetime.now(tz=datetime.timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ")
        backup = dst.with_suffix(dst.suffix + f".bak-{ts}")
        if not dry_run:
            shutil.copy2(dst, backup)

    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        # newline="" preserves the source line endings (LF). Windows'
        # default `write_text` translates \n to \r\n, which contaminates
        # bash variable assignments with a trailing CR and breaks the
        # downstream `if [ "$devkit_root" = ... ]` string comparison
        # (the literal in the if line has no CR).
        with dst.open("w", encoding="utf-8", newline="") as f:
            f.write(stamped)
        mode = dst.stat().st_mode
        dst.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        with dst.open("a", encoding="utf-8", newline="") as f:
            f.write(f"\n{DEVKIT_HOOK_MARKER} {devkit_root}\n")

    msg = f"  installed: {dst.name}"
    if backup is not None:
        msg += f"  (backup: {backup.name})"
    return msg


def _uninstall_one(dst: Path, dry_run: bool = False) -> str:
    """Remove one devkit-installed hook. Returns a status string."""
    if not dst.exists():
        return f"  not installed: {dst.name}"
    text = dst.read_text(encoding="utf-8", errors="replace")
    if DEVKIT_HOOK_MARKER not in text:
        return f"  not a devkit hook (refusing to remove): {dst.name}"
    if not dry_run:
        dst.unlink()
    return f"  removed: {dst.name}"


def cmd_install(args: argparse.Namespace) -> int:
    if not GITHOOKS_SRC.is_dir():
        print(f"install_git_hooks: {GITHOOKS_SRC} not found", file=sys.stderr)
        return 2
    sources = sorted(p for p in GITHOOKS_SRC.iterdir()
                     if p.is_file() and not p.name.startswith("."))
    if not sources:
        print(f"install_git_hooks: no hooks in {GITHOOKS_SRC}",
              file=sys.stderr)
        return 2

    git_dir = _find_git_dir(REPO_ROOT)
    if git_dir is None:
        print("install_git_hooks: not a git repo (no .git found)",
              file=sys.stderr)
        return 1
    hooks_dir = _git_hooks_dir(git_dir)

    print(f"install_git_hooks: devkit={DEVKIT_ROOT} hooks={hooks_dir}")
    for src in sources:
        dst = hooks_dir / src.name
        msg = _install_one(src, dst, DEVKIT_ROOT, dry_run=args.dry_run)
        print(msg)

    print()
    print("Hooks installed. The devkit/pre-commit runs Gates 1/3/4 on every")
    print("commit. To also run Gate 2 (full pytest, ~3min), set env:")
    print("  export KUNGLAO_DEV_GATE2=1")
    print()
    print("Uninstall: uv run python devkit/install_git_hooks.py --uninstall")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    git_dir = _find_git_dir(REPO_ROOT)
    if git_dir is None:
        print("install_git_hooks: not a git repo", file=sys.stderr)
        return 1
    hooks_dir = _git_hooks_dir(git_dir)

    if not GITHOOKS_SRC.is_dir():
        print(f"install_git_hooks: {GITHOOKS_SRC} not found", file=sys.stderr)
        return 2

    sources = sorted(p for p in GITHOOKS_SRC.iterdir()
                     if p.is_file() and not p.name.startswith("."))
    print(f"install_git_hooks: uninstalling devkit hooks from {hooks_dir}")
    removed = 0
    refused = 0
    for src in sources:
        dst = hooks_dir / src.name
        msg = _uninstall_one(dst, dry_run=args.dry_run)
        print(msg)
        if msg.startswith("  removed"):
            removed += 1
        elif msg.startswith("  not a devkit hook"):
            refused += 1
    # Refusing to remove a foreign hook is NOT a failure — the user wanted
    # to remove devkit hooks; refusing a non-devkit one is correct behaviour.
    # Exit 3 only when NOTHING was inspected (e.g. devkit/githooks empty).
    if removed == 0 and refused == 0:
        return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    g = p.add_mutually_exclusive_group()
    g.add_argument("--install", action="store_true", default=True,
                   help="install devkit hooks (default)")
    g.add_argument("--uninstall", action="store_true",
                   help="remove devkit hooks")
    p.add_argument("--dry-run", action="store_true",
                   help="preview changes without writing")
    args = p.parse_args(argv)

    if args.uninstall:
        return cmd_uninstall(args)
    return cmd_install(args)


if __name__ == "__main__":
    sys.exit(main())