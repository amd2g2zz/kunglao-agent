# gc-harness/worktree_gc.py — Worktree lifecycle controller (#720 v1).
# merged + merged_days -> candidate; abandoned (zero own commits) +
# abandoned_days -> candidate. --apply removes worktree + branch and keeps
# ONLY a record line (commit_hash / branch / pr_link). Main worktree never
# a candidate. Dry-run report by default.
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402


def _main_worktree(root: Path) -> str:
    return str(root.resolve()).lower()


def _branch_merged(root: Path, branch: str) -> bool:
    # branch fully contained in origin/dev (or dev when no remote)?
    for base_ref in ("origin/dev", "dev"):
        r = C.git(root, "merge-base", "--is-ancestor", branch, base_ref)
        if r.returncode == 0:
            return True
    return False


def _last_commit_epoch(root: Path, branch: str) -> float | None:
    r = C.git(root, "log", "-1", "--format=%ct", branch)
    if r.returncode == 0 and r.stdout.strip().isdigit():
        return float(r.stdout.strip())
    return None


def _own_commit_count(root: Path, branch: str) -> int:
    base = "origin/dev" if C.git(root, "rev-parse", "-q", "--verify",
                                 "origin/dev").returncode == 0 else "dev"
    r = C.git(root, "rev-list", "--count", f"{base}..{branch}")
    return int(r.stdout.strip() or 0) if r.returncode == 0 else -1


def _pr_link(root: Path, branch: str) -> str | None:
    r = subprocess.run(["gh", "pr", "list", "--head", branch, "--state", "all",
                        "--json", "number", "--jq", ".[0].number"],
                       capture_output=True, text=True, cwd=str(root))
    if r.returncode == 0 and r.stdout.strip().isdigit():
        return f"#{r.stdout.strip()}"
    return None


def scan(root: Path, apply: bool) -> int:
    cfg = C.load_config(root).get("worktree", {})
    merged_days = int(cfg.get("merged_days", 7))
    abandoned_days = int(cfg.get("abandoned_days", 14))
    r = C.git(root, "worktree", "list", "--porcelain")
    entries: list[dict] = []
    cur: dict = {}
    for line in r.stdout.splitlines():
        if not line.strip():
            if cur:
                entries.append(cur); cur = {}
            continue
        k, _, v = line.partition(" ")
        cur[k] = v
    if cur:
        entries.append(cur)
    records = C.load_registry(root, "worktrees")
    for e in entries:
        wtp = e.get("worktree", "")
        branch = e.get("branch", "").replace("refs/heads/", "")
        if not wtp or not branch:
            continue                                    # detached/bare: skip
        if Path(wtp).resolve().as_posix().lower() == _main_worktree(root).replace("\\", "/"):
            continue                                    # main worktree: never
        wt = Path(wtp)
        last = _last_commit_epoch(root, branch)
        merged = _branch_merged(root, branch)
        owns = _own_commit_count(root, branch)
        age_last = (time.time() - last) / 86400.0 if last else None
        # abandoned signal: dir mtime of the worktree's .git file
        try:
            dir_age = (time.time() - os.path.getmtime(wt / ".git")) / 86400.0
        except OSError:
            dir_age = None
        verdict = ""
        if merged and age_last is not None and age_last > merged_days:
            verdict = (f"candidate: merged {age_last:.0f}d ago "
                       f"(> {merged_days}d)")
        elif owns == 0 and dir_age is not None and dir_age > abandoned_days:
            verdict = (f"candidate: abandoned (0 own commits, "
                       f"dir {dir_age:.0f}d old > {abandoned_days}d)")
        if not verdict:
            print(f"keep: {branch}  ({wt})")
            continue
        print(f"{verdict}  branch={branch}  ({wt})")
        if not apply:
            continue
        commit_hash = (C.git(root, "rev-parse", branch).stdout.strip()
                       or "unknown")
        records.append({
            "branch": branch, "path": wtp, "status": "removed",
            "commit_hash": commit_hash, "pr_link": _pr_link(root, branch),
            "last_modified": C.today(),
        })
        C.git(root, "worktree", "remove", "--force", wtp)
        C.git(root, "branch", "-D", branch)
        print(f"  removed (applied): worktree + branch; record kept "
              f"(commit={commit_hash[:12]} pr={records[-1]['pr_link']})")
    if apply:
        C.save_registry(root, "worktrees", records)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="worktree_gc — Worktree lifecycle (#720)")
    p.add_argument("cmd", choices=["scan"])
    p.add_argument("--apply", action="store_true")
    a = p.parse_args(argv)
    return scan(C.repo_root(), a.apply)


if __name__ == "__main__":
    sys.exit(main())
