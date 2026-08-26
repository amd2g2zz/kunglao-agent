# gc-harness/_common.py — shared config/registry/date helpers (#720 v1).
# Identity/status/linkage ONLY in registries — no scores, no embeddings,
# no AI-judgment fields (spec-of-record prohibition list).
from __future__ import annotations

import datetime as _dt
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore


def repo_root(cli_cwd: Path | None = None) -> Path:
    """Repo root for a gc CLI invocation (CLI runs with cwd=<target repo>)."""
    start = (cli_cwd or Path.cwd()).resolve()
    r = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return Path(r.stdout.strip())
    return start


def load_config(root: Path) -> dict:
    cfg_path = root / "gc-harness" / "config.yaml"
    if not cfg_path.is_file():
        return {}
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def load_registry(root: Path, name: str) -> list[dict]:
    """Read .agent/<name>.yaml -> list of entry dicts. Fail-open: absent/broken → []."""
    p = root / ".agent" / f"{name}.yaml"
    if not p.is_file():
        return []
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return []
    entries = data.get(name) if isinstance(data, dict) else None
    return [e for e in (entries or []) if isinstance(e, dict)]


def save_registry(root: Path, name: str, entries: list[dict]) -> Path:
    d = root / ".agent"
    d.mkdir(exist_ok=True)
    p = d / f"{name}.yaml"
    p.write_text(
        yaml.safe_dump({name: entries}, sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    return p


def today() -> str:
    return _dt.date.today().isoformat()


def days_since(date_str: str | None) -> int | None:
    """Days from an ISO date to today; unparseable/absent → None (fail-open)."""
    if not date_str:
        return None
    try:
        d = _dt.date.fromisoformat(str(date_str).strip()[:10])
    except ValueError:
        return None
    return (_dt.date.today() - d).days


def grep_count(root: Path, token: str, subdirs: tuple[str, ...]) -> int:
    """Count files under subdirs whose text contains token (case-insensitive —
    reference counting must not miss SPEC-X vs spec-x spellings).
    Fail-open: error → 0."""
    if not token:
        return 0
    needle = token.lower()
    hits = 0
    for sub in subdirs:
        base = root / sub
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix not in (".py", ".md", ".yaml", ".yml"):
                continue
            try:
                if needle in p.read_text(encoding="utf-8", errors="replace").lower():
                    hits += 1
            except OSError:
                continue
    return hits


def norm_stem(stem: str) -> str:
    """Duplicate-detection normal form: strip trailing version suffixes
    (spec-alpha-v2 -> spec-alpha) so renumbered copies of one spec collide.
    Issue-numbered stems (issue-720-...) never collide with each other."""
    return re.sub(r"[-_]?v\d+$", "", stem.lower())


def git(root: Path, *args: str) -> subprocess.CompletedProcess:
    """Run git in root with a stripped environment (never inherit
    GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE — tmp-fixture hygiene)."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")}
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, env=env)


def stem_token(path_str: str) -> str:
    """Searchable token from a spec path: its directory name
    (openspec/changes/<dir>/proposal.md → <dir>)."""
    parts = Path(path_str.replace("\\", "/")).parts
    if len(parts) >= 2 and parts[-1].endswith(".md"):
        return parts[-2]
    return Path(path_str).stem
