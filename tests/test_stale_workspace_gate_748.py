# -*- coding: utf-8 -*-
"""tests/test_stale_workspace_gate_748.py — issue #748 stale-workspace gate.

Plan: `.claude/PRPs/plans/subplans/v013/upgrade-slash-command.plan.md`
      followup (PR #747 ships `/kunglao-agent:upgrade`; this gate surfaces
      it as a hard refuse for `/kunglao-agent:analysis` and
      `/kunglao-agent:resume`).

5 RED → GREEN cases covering:
  1. `kunglao check-stale <ws>` on an un-stamped workspace: rc=5,
     status=no-stamp, advice directs to /kunglao-agent:init.
  2. `kunglao check-stale <ws>` on a v0.1.0 workspace (skill=v0.1.3):
     rc=5, status=stale, advice directs to /kunglao-agent:upgrade.
  3. `kunglao check-stale <ws>` on a current-stamp workspace: rc=0,
     status=current.
  4. `kunglao resume <ws>` on a stale workspace: rc=5 (gate refuses
     before delegating to kunglao_resume.main).
  5. `kunglao resume <ws>` on a current-stamp workspace: rc=0
     (delegates normally — no gate interference).

The gate refuses silently-readable form on stderr so the slash command
SKILL.md UX layer can map RC=5 to a refusal message.

Note (2026-08-26): head 0905bb2 received no check-suite from GitHub
Actions (platform dispatch miss — the workflow YAML is valid and matches
pull_request→dev). This delta commit forces a fresh synchronize event.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
KUNGLAO_PY = ROOT / "scripts" / "kunglao.py"


from template_version import read_skill_version


def _stamp(ws: Path, version: str | None) -> None:
    """Place `# kunglao_template_version: <v>` at the top of CLAUDE.md if
    version is not None; otherwise leave the workspace un-stamped."""
    if version is None:
        return
    (ws / "CLAUDE.md").write_text(
        f"# kunglao_template_version: {version}\n", encoding="utf-8")


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(KUNGLAO_PY), *args],
        capture_output=True, text=True, timeout=60,
        encoding="utf-8", errors="replace",
    )


# ---------------------------------------------------------------------------
# 1. un-stamped workspace: rc=5, status=no-stamp, advice → /init
# ---------------------------------------------------------------------------

def test_check_stale_unstamped_workspace(tmp_path: Path) -> None:
    """No version stamp on the workspace: gate refuses with status=no-stamp
    and the operator is directed to /kunglao-agent:init."""
    proc = _cli("check-stale", str(tmp_path))
    assert proc.returncode == 5, (
        f"un-stamped workspace must exit 5, got {proc.returncode}: "
        f"stderr={proc.stderr[-200:]}")
    envelope = json.loads(proc.stdout.strip().splitlines()[-1])
    assert envelope["status"] == "no-stamp"
    assert envelope["rc"] == 5
    assert envelope["workspace_stamp"] is None
    assert "/kunglao-agent:init" in envelope["advice"]


# ---------------------------------------------------------------------------
# 2. v0.1.0 workspace + skill v0.1.3: rc=5, status=stale, advice → /upgrade
# ---------------------------------------------------------------------------

def test_check_stale_v0_1_0_workspace(tmp_path: Path) -> None:
    """Workspace stamped v0.1.0 against active skill v0.1.3: gate refuses
    with status=stale and the operator is directed to /kunglao-agent:upgrade."""
    _stamp(tmp_path, "0.1.0")
    proc = _cli("check-stale", str(tmp_path))
    assert proc.returncode == 5, (
        f"stale workspace must exit 5, got {proc.returncode}: "
        f"stderr={proc.stderr[-200:]}")
    envelope = json.loads(proc.stdout.strip().splitlines()[-1])
    assert envelope["status"] == "stale"
    assert envelope["rc"] == 5
    assert envelope["workspace_stamp"] == "0.1.0"
    assert "/kunglao-agent:upgrade" in envelope["advice"]


# ---------------------------------------------------------------------------
# 3. current-stamp workspace: rc=0, status=current
# ---------------------------------------------------------------------------

def test_check_stale_current_workspace(tmp_path: Path) -> None:
    """Workspace stamp matches the active skill: gate returns rc=0 +
    status=current (loop may proceed)."""
    _stamp(tmp_path, read_skill_version())
    proc = _cli("check-stale", str(tmp_path))
    assert proc.returncode == 0, (
        f"current workspace must exit 0, got {proc.returncode}: "
        f"stderr={proc.stderr[-200:]}")
    envelope = json.loads(proc.stdout.strip().splitlines()[-1])
    assert envelope["status"] == "current"
    assert envelope["rc"] == 0
    assert envelope["workspace_stamp"] == read_skill_version()
    assert envelope["advice"] is None


# ---------------------------------------------------------------------------
# 4. `kunglao resume <stale ws>`: gate refuses BEFORE delegating
# ---------------------------------------------------------------------------

def test_resume_refuses_stale_workspace(tmp_path: Path) -> None:
    """cmd_resume must run the gate first; on a stale workspace it returns
    rc=5 without ever delegating to kunglao_resume.main. The gate's stderr
    line names /kunglao-agent:upgrade as the recovery path."""
    _stamp(tmp_path, "0.1.0")
    proc = _cli("resume", str(tmp_path))
    assert proc.returncode == 5, (
        f"resume on stale workspace must exit 5, got {proc.returncode}: "
        f"stderr={proc.stderr[-200:]}")
    # The gate's stderr message must point at /kunglao-agent:upgrade.
    assert "/kunglao-agent:upgrade" in proc.stderr, (
        f"resume gate stderr must name upgrade path: {proc.stderr[-200:]}")


# ---------------------------------------------------------------------------
# 5. `kunglao resume <current ws>`: gate passes, normal delegation runs
# ---------------------------------------------------------------------------

def test_resume_passes_current_workspace(tmp_path: Path) -> None:
    """On a current workspace, the gate does not interfere — cmd_resume
    delegates to kunglao_resume.main and returns whatever that script's
    normal path returns (rc=0 on a fresh workspace)."""
    _stamp(tmp_path, read_skill_version())
    proc = _cli("resume", str(tmp_path))
    # Resume on a fresh workspace returns its normal exit code (0 or 1
    # depending on what kunglao_resume.main does with an empty workspace).
    # We only assert: not 5 (gate didn't refuse), and stderr does NOT
    # contain the gate's refusal message.
    assert proc.returncode != 5, (
        f"resume on current workspace must not exit 5 (gate should pass); "
        f"got {proc.returncode} stderr={proc.stderr[-200:]}")
    assert "/kunglao-agent:upgrade" not in proc.stderr, (
        f"resume gate must not fire on current workspace; stderr: "
        f"{proc.stderr[-200:]}")