# -*- coding: utf-8 -*-
"""#165 — scripts/install_unidbg.sh contract tests (no VM install in CI).

Shape-level assertions for the unidbg deployment-preconditions installer:

  (a) shell syntax parses (bash -n);
  (b) strict-mode + per-step verdict helpers present (init-worker env-repair
      conventions: a failed step is reported, never silently skipped);
  (c) idempotency design: install marker recorded and honored on re-run,
      --force re-clone path exists;
  (d) the binding deployment preconditions from the card are the steps:
      JDK (java AND javac), Maven (wrapper-eligible skip, not silent fail),
      remote fetch (clone; pinned default ref master), first build;
  (e) --dry-run lists the plan and performs NO side effects (no target dir
      created, no clone, no build);
  (f) synthetic hygiene: no host absolute paths, no real IPv4s;
  (g) usage errors exit 2.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_unidbg.sh"

TEXT = SCRIPT.read_text(encoding="utf-8")
_ABS_PATH = re.compile(r"(?:[A-Za-z]:\\|/(?:Users|home|tmp|opt|var|etc)/)")
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")

_HAS_JDK = all(shutil.which(t) for t in ("java", "javac"))


def _run(*args: str, env_home: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, check=False,
    )


# ---------- (a) syntax ----------

def test_shell_syntax_parses():
    result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, f"bash -n failed: {result.stderr}"


# ---------- (b) strict mode + verdicts ----------

def test_strict_mode_and_verdict_helpers():
    assert re.search(r"set -u[o]\b|set -uo", TEXT), "strict mode (set -uo pipefail) required"
    for helper in ("log_ok", "log_fail", "log_skip"):
        assert f"{helper}()" in TEXT, f"per-step verdict helper missing: {helper}"
    assert "FAILED=1" in TEXT, "failed steps must flip the run status (never silent)"


# ---------- (c) idempotency design ----------

def test_marker_based_idempotency_and_force():
    assert ".unidbg-installed.json" in TEXT, "install marker missing (idempotent re-run design)"
    assert "--force" in TEXT, "--force re-clone path missing"
    assert "git clone" in TEXT and "fetch" in TEXT, "remote fetch paths (clone + refresh) missing"


# ---------- (d) the binding deployment preconditions ----------

def test_steps_cover_jdk_maven_remote_clone_first_build():
    assert "javac" in TEXT, "JDK step must require javac (a JRE cannot build)"
    assert "mvn" in TEXT and "mvnw" in TEXT, "Maven step must cover mvn + wrapper fallback"
    assert re.search(r"clone.*unidbg|unidbg.*clone|github.com/zhkl0228/unidbg", TEXT), (
        "remote fetch step must clone the unidbg repository"
    )
    assert "test-compile" in TEXT, "first-build step must compile (dependency resolution)"
    assert "UNIDBG_REF" in TEXT and "master" in TEXT, "default ref must be the pinned master line"


def test_failed_step_reports_and_nonzero_exit():
    assert "exit 1" in TEXT, "failed installs must exit non-zero"
    assert "safe to re-run" in TEXT, "re-run safety must be stated on failure"


# ---------- (e) dry-run performs no side effects ----------

@pytest.mark.skipif(not _HAS_JDK, reason="green-path dry run reports the JDK step; a JDK-less runner skips with reason (the script's own log_skip philosophy)")
def test_dry_run_lists_plan_without_side_effects(tmp_path: Path):
    target = tmp_path / "vendor" / "unidbg"
    result = subprocess.run(
        [str(SCRIPT), "--target", str(target), "--dry-run"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"dry run failed: {result.stderr}"
    plan = result.stdout
    for token in ("JDK", "Maven", "clone", "build"):
        assert token in plan, f"dry-run plan missing step keyword: {token}"
    assert not target.exists(), "dry run must not create the target directory"


def test_dry_run_fail_closed_branch_exists():
    """A failed precondition step must fail the run even in dry-run
    (fail-closed) — asserted at source level so the test does not depend
    on crafting a PATH that hides the JDK."""
    assert "--dry-run plan blocked" in TEXT, (
        "dry run must refuse a clean plan when precondition steps failed"
    )
    assert re.search(r"if \[ \"\$FAILED\" -ne 0 \]; then\s*\n\s*printf -- '--dry-run plan blocked", TEXT), (
        "dry-run fail-closed branch shape changed — keep it fail-closed"
    )


# ---------- (f) synthetic hygiene ----------

def test_no_host_absolute_paths_or_real_ips():
    code = TEXT.split('case "$1" in', 1)[1]  # usage text prints $0 via sed; check the logic body
    assert not _ABS_PATH.search(TEXT), "script contains a host absolute path"
    assert not _IP.search(code), "script contains a real IPv4 address"


# ---------- (g) usage errors ----------

def test_unknown_argument_exits_2():
    result = _run("--bogus-flag")
    assert result.returncode == 2, f"unknown flag must exit 2, got {result.returncode}"


if __name__ == "__main__":
    sys.exit(0)
