# -*- coding: utf-8 -*-
"""kunglao-status.py contract tests (#287): disk-rendered TUI status panel.

Read-only renderer over DISK state only (claim-register.yaml +
runs/worker-status-*.md + .convergence_ledger.jsonl + runs/logs/kunglao-*.jsonl).
ANSI colors are allowed but MUST degrade to plain text when the output is
not a TTY (or --no-color is passed).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _build_fixture_ws(tmp: Path) -> Path:
    """Minimal fixture workspace per the issue: 2 OPEN / 1 PROVEN claims,
    one active worker w1, a 3-row convergence ledger, one log event."""
    ws = tmp / "ws"
    (ws / "runs" / "logs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "- id: C-1\n  status: OPEN\n"
        "- id: C-2\n  status: OPEN\n"
        "- id: C-3\n  status: PROVEN\n",
        encoding="utf-8")
    (ws / "runs" / "worker-status-w1.md").write_text(
        "## Status\nclaim C-1 | step x | status: in-progress\n",
        encoding="utf-8")
    (ws / ".convergence_ledger.jsonl").write_text(
        json.dumps({"ts": "2026-08-13T01:00:00Z", "decision": "DISPATCH", "open_count": 3}) + "\n"
        + json.dumps({"ts": "2026-08-13T02:00:00Z", "decision": "DISPATCH", "open_count": 2}) + "\n"
        + json.dumps({"ts": "2026-08-13T03:00:00Z", "decision": "CONVERGED", "open_count": 0}) + "\n",
        encoding="utf-8")
    (ws / "runs" / "logs" / "kunglao-2026-08-13.jsonl").write_text(
        json.dumps({"ts": "2026-08-13T03:00:00Z", "actor": "orchestrator", "action": "verify",
                    "claim": "C-3", "tool": None, "artifact": "facts/F003.md",
                    "duration_ms": 123, "exit": 0, "detail": "L1 PASS"}) + "\n",
        encoding="utf-8")
    return ws


def _render(ws: Path, color: bool) -> str:
    sys.path.insert(0, str(SCRIPTS))
    from kunglao_status import render_status
    return render_status(ws, color=color)


def test_panel_renders_fixture_state(tmp: Path):
    ws = _build_fixture_ws(tmp)
    out = _render(ws, color=False)
    # claims board counts
    assert "OPEN: 2" in out, out
    assert "PROVEN: 1" in out, out
    # active worker id
    assert "w1" in out, out
    # recent event stream shows the verify event
    assert "verify" in out, out
    # convergence progress shows the open-count trend
    assert "3" in out and "0" in out, out


def test_no_color_output_equals_ansi_stripped(tmp: Path):
    ws = _build_fixture_ws(tmp)
    colored = _render(ws, color=True)
    plain = _render(ws, color=False)
    assert "\x1b[" in colored, "color=True must emit ANSI escapes"
    assert "\x1b[" not in plain, "color=False must emit no ANSI escapes"
    assert ANSI_RE.sub("", colored) == plain


def test_cli_no_color_and_non_tty_degrade(tmp: Path):
    ws = _build_fixture_ws(tmp)
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "kunglao-status.py"), str(ws), "--no-color"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "\x1b[" not in r.stdout
    assert "OPEN: 2" in r.stdout
    # without --no-color but piped (non-TTY) — must degrade to plain text too
    r2 = subprocess.run(
        [sys.executable, str(SCRIPTS / "kunglao-status.py"), str(ws)],
        capture_output=True, text=True, timeout=60)
    assert r2.returncode == 0, r2.stderr
    assert "\x1b[" not in r2.stdout, "non-TTY output must degrade to plain text"


def test_missing_workspace_error_exit_2(tmp: Path):
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "kunglao-status.py"), str(tmp / "nope")],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 2, f"expected exit 2, got {r.returncode}"
    assert "ERROR" in (r.stdout + r.stderr).upper()
