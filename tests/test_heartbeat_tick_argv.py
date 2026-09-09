# -*- coding: utf-8 -*-
"""tests/test_heartbeat_tick_argv.py — CLI boundary argv validation (issue #6).

heartbeat_tick.py fed the raw first argv token into
ws_layout.resolve_strict, which resolves ANY token (flags included) as the
workspace path. Running ``heartbeat_tick.py --help`` therefore ran the whole
tick against a path literally named ``--help`` and materialized it
(noop_breaker mkdirs ``<ws>/runs`` for the no-progress state) — a classic
missing input-validation gate at the CLI boundary (#6).

Contract locked here:
  * ``--help``           → usage on stdout, exit 0, ZERO side effects
  * unknown flag         → argparse-style error, non-zero exit, zero effects
  * nonexistent path     → clear stderr error, non-zero exit, NOTHING created
                           (the tick runs on INITIALIZED workspaces only; the
                           mkdirs in noop_breaker / report-write are telemetry
                           for an existing ws, never workspace bootstrap —
                           creation is init's job)
  * existing directory   → unchanged tick behavior (rc 0/1 + report on disk)

Subprocess-driven like tests/test_heartbeat_tick.py (same convention, #365).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TICK = ROOT / "scripts" / "heartbeat_tick.py"


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TICK), *args],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180, cwd=str(cwd),
    )


def _make_ws(tmp_path: Path) -> Path:
    """Minimal workspace (claim-register.yaml so the chain scripts accept it)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


class TestHelpZeroSideEffects:
    def test_help_exits_zero_prints_usage_creates_nothing(self, tmp_path):
        """#6 core: --help must be a pure query — usage on stdout, exit 0,
        and the cwd byte-identical afterwards (no directory named --help)."""
        before = sorted(p.name for p in tmp_path.iterdir())
        r = _run(["--help"], tmp_path)
        assert r.returncode == 0, (
            f"--help must exit 0: rc={r.returncode} "
            f"stderr={r.stderr[:300]}")
        assert "usage:" in r.stdout, f"usage text expected on stdout: {r.stdout[:300]}"
        after = sorted(p.name for p in tmp_path.iterdir())
        assert after == before, (
            f"--help must have ZERO side effects: cwd went {before} -> {after}")

    def test_unknown_flag_errors_without_side_effects(self, tmp_path):
        """--nonsense is a usage error, not a workspace named --nonsense:
        non-zero exit, the error names the flag, cwd untouched."""
        r = _run(["--nonsense"], tmp_path)
        assert r.returncode != 0, (
            f"unknown flag must fail: rc={r.returncode} stdout={r.stdout[:300]}")
        assert "--nonsense" in (r.stderr + r.stdout), (
            f"error must name the bad flag: stderr={r.stderr[:300]}")
        assert not (tmp_path / "--nonsense").exists(), (
            "an unknown flag must never be materialized as a directory")
        assert sorted(p.name for p in tmp_path.iterdir()) == [], (
            "unknown flag must have zero side effects on cwd")

    def test_nonexistent_workspace_path_creates_nothing(self, tmp_path):
        """A path-shaped but nonexistent positional gets a clear stderr error
        and a non-zero exit — the tick never bootstraps a workspace."""
        ghost = tmp_path / "ghost-ws"
        r = _run([str(ghost)], tmp_path)
        assert r.returncode != 0, (
            f"nonexistent workspace must fail: rc={r.returncode} "
            f"stdout={r.stdout[:300]}")
        assert r.stderr.strip(), "clear error required on stderr"
        assert not ghost.exists(), (
            "tick must never create the workspace dir (init's job)")
        assert sorted(p.name for p in tmp_path.iterdir()) == [], (
            "failed resolution must have zero side effects on cwd")


class TestExistingWorkspaceUnchanged:
    def test_existing_workspace_runs_normal_tick(self, tmp_path):
        """Regression guard: a valid existing directory keeps the documented
        tick contract — rc 0/1, report on disk naming the workspace."""
        ws = _make_ws(tmp_path)
        r = _run([str(ws)], tmp_path)
        assert r.returncode in (0, 1), (
            f"documented tick exit semantics: rc={r.returncode} "
            f"stderr={r.stderr[:300]}")
        report_path = ws / "runs" / ".heartbeat-tick.json"
        assert report_path.exists(), "tick report must land in the workspace"
        data = json.loads(report_path.read_text(encoding="utf-8"))
        assert data["workspace"] == str(ws.resolve())
