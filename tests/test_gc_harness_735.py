# -*- coding: utf-8 -*-
"""tests/test_gc_harness_735.py — gc-harness code_gc leg (report-only rot sweep).

Subprocess-fixture suite (the test_gc_harness_720 pattern): a tmp git repo
is planted with the detection targets and the module runs against it via
`sys.executable gc-harness/code_gc.py scan`. Pins: dead-local CONFIRMED
tier, orphan-module SUSPECT tripwire, dispatch-surface liveness override,
--json report shape, and report-only safety (no mutation, no apply flag).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HARNESS = REPO / "gc-harness"

README = """# scripts inventory (fixture)

- registered_helper.py — dispatched via this surface
- live_module.py — dispatched via this surface
"""

CALC_KIT = "def compute(total):\n    leftover = total * 2\n    return total\n"

ORPHAN_MOD = "RATE = 2\n"

REGISTERED_HELPER = "def assist(x):\n    return x + 1\n"

LIVE_MODULE = "def lonely_helper():\n    return None\n"

GHOST_MOD = "def unmentioned_thing():\n    return 3\n"


def _clean_git_env() -> dict:
    env = dict(os.environ)
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(k, None)
    return env


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, env=_clean_git_env(), check=check,
    )


def _harness(tmp_repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run gc-harness/code_gc.py with cwd inside tmp_repo."""
    return subprocess.run(
        [sys.executable, str(HARNESS / "code_gc.py"), *args],
        cwd=str(tmp_repo), capture_output=True, text=True,
        env=_clean_git_env(), timeout=180,
    )


def _make_repo(tmp_path: Path) -> Path:
    """Tmp repo: the five planted detection subjects plus one inert test."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "dev")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    scripts = repo / "scripts"
    scripts.mkdir()
    (scripts / "README.md").write_text(README, encoding="utf-8")
    (scripts / "calc_kit.py").write_text(CALC_KIT, encoding="utf-8")
    (scripts / "orphan_mod.py").write_text(ORPHAN_MOD, encoding="utf-8")
    (scripts / "registered_helper.py").write_text(REGISTERED_HELPER, encoding="utf-8")
    (scripts / "live_module.py").write_text(LIVE_MODULE, encoding="utf-8")
    (scripts / "ghost_mod.py").write_text(GHOST_MOD, encoding="utf-8")
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_inert.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


def _snapshot(repo: Path) -> dict:
    """relpath -> sha256 for every file in the repo (workspace files only)."""
    out = {}
    for p in sorted(repo.rglob("*")):
        if ".git" in p.parts or not p.is_file():
            continue
        out[p.relative_to(repo).as_posix()] = hashlib.sha256(
            p.read_bytes()).hexdigest()
    return out


# ---------- class B: dead_local (CONFIRMED) ----------

def test_dead_local_planted_reproduces_confirmed(tmp_path: Path) -> None:
    """An unused local is a CONFIRMED candidate with file:line and symbol."""
    repo = _make_repo(tmp_path)
    r = _harness(repo, "scan")
    assert r.returncode == 0, r.stderr
    assert "CONFIRMED: scripts/calc_kit.py:2 leftover (F841)" in r.stdout


# ---------- class C: orphan_module tripwire (SUSPECT) ----------

def test_orphan_module_suspect_and_surface_referenced_ok(tmp_path: Path) -> None:
    """Zero surface hits -> SUSPECT; a surface-referenced module stays ok."""
    repo = _make_repo(tmp_path)
    r = _harness(repo, "scan")
    assert "SUSPECT: scripts/orphan_mod.py" in r.stdout
    assert "SUSPECT: scripts/registered_helper.py" not in r.stdout
    assert ("ok: scripts/registered_helper.py 1 symbols alive"
            " (surface hit: scripts/README.md)") in r.stdout


# ---------- class A: dead_symbol + dispatch-surface liveness ----------

def test_dispatch_surface_liveness_keeps_symbols_alive(tmp_path: Path) -> None:
    """A surface hit on the file keeps ALL its top-level symbols alive."""
    repo = _make_repo(tmp_path)
    r = _harness(repo, "scan")
    suspect_lines = [ln for ln in r.stdout.splitlines()
                     if ln.startswith("SUSPECT")]
    assert all("live_module" not in ln for ln in suspect_lines), suspect_lines
    assert all("lonely_helper" not in ln for ln in suspect_lines), suspect_lines
    assert ("ok: scripts/live_module.py 1 symbols alive"
            " (surface hit: scripts/README.md)") in r.stdout


def test_dead_symbol_in_unsurfaced_file_flagged_suspect(tmp_path: Path) -> None:
    """No surface hit + no witness outside the def line -> SUSPECT symbol."""
    repo = _make_repo(tmp_path)
    r = _harness(repo, "scan")
    line = next(ln for ln in r.stdout.splitlines()
                if "unmentioned_thing" in ln)
    assert line.startswith("SUSPECT: scripts/ghost_mod.py:1 unmentioned_thing")


# ---------- report shape ----------

def test_json_report_shape(tmp_path: Path) -> None:
    """--json carries leg/generated/head/scopes/candidates/counts only."""
    repo = _make_repo(tmp_path)
    r = _harness(repo, "scan", "--json")
    payload = json.loads(r.stdout)
    assert set(payload) == {
        "leg", "generated", "head", "scopes", "candidates", "counts"}
    assert payload["leg"] == "code_gc"
    assert payload["generated"]
    assert len(payload["head"]) == 40
    assert payload["scopes"] == ["scripts", "tools", "hooks", "gc-harness"]
    assert set(payload["counts"]) == {"confirmed", "suspect", "total"}
    counts = payload["counts"]
    assert counts["confirmed"] + counts["suspect"] == counts["total"]
    assert counts["total"] == len(payload["candidates"])
    assert counts["confirmed"] >= 1
    for c in payload["candidates"]:
        assert set(c) == {"class", "tier", "path", "line", "symbol", "evidence"}
        assert c["tier"] in ("CONFIRMED", "SUSPECT")
        assert c["evidence"]
    planted = [c for c in payload["candidates"]
               if c["path"] == "scripts/calc_kit.py" and c["symbol"] == "leftover"]
    assert planted and planted[0]["class"] == "dead_local"
    assert planted[0]["tier"] == "CONFIRMED"


# ---------- report-only safety ----------

def test_report_only_no_apply_no_mutation(tmp_path: Path) -> None:
    """scan never writes, never deletes; there is no --apply flag at all."""
    repo = _make_repo(tmp_path)
    before = _snapshot(repo)
    r = _harness(repo, "scan")
    assert r.returncode == 0, r.stderr
    assert _snapshot(repo) == before
    rj = _harness(repo, "scan", "--json")
    assert rj.returncode == 0
    assert _snapshot(repo) == before
    ra = _harness(repo, "scan", "--apply")
    assert ra.returncode != 0
    assert _snapshot(repo) == before
    help_text = _harness(repo, "scan", "--help")
    assert "--apply" not in help_text.stdout + help_text.stderr
