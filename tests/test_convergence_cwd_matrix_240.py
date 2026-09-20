# -*- coding: utf-8 -*-
"""Issue #240 — convergence_check cwd matrix (CLI face, hermetic).

The hermetic matrix the issue demands: cwd (workspace root / skill-dir-like
/ elsewhere / decoy-sibling home) x argument style (explicit path / "." /
no argument). The true decision of the seeded workspace is DISPATCH — every
row must either return that identical verdict or hard-error with "not a
kunglao workspace" (exit 64); a flipped verdict (e.g. a CONVERGED from a
non-workspace cwd) is the bug.

Integration tier by construction: one real subprocess per row.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "convergence_check.py"

# Default layout convention (env_manifest DEFAULT_LAYOUT workspace_dir).
WS_DIRNAME = "malware-analysis-workspace"

EXIT_MISSING_WORKSPACE = 64
DECIDED_BYTES = (0, 1, 2, 3, 4, 5)  # verdict bytes; hard errors live outside


def _real_ws(root: Path) -> Path:
    """A real workspace whose true decision is DISPATCH (one OPEN claim,
    free slots, empty primary_questions)."""
    ws = root / WS_DIRNAME
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "- id: C-1\n"
        "  status: OPEN\n"
        "  boundary_type: positive_observation\n"
        "  evidence_tier_attempted: 0\n"
        "  promotion_attempts: 0\n"
        "  depends_on: '[]'\n",
        encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "primary_questions: []\n", encoding="utf-8")
    return ws


def _register_only_ws(root: Path) -> Path:
    """The #240 decoy: an empty register with no task_spec.yaml — resolves
    as a workspace under the pre-fix rules and drains to a WRONG CONVERGED."""
    ws = root / WS_DIRNAME
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def _skill_like_dir(root: Path) -> Path:
    """A non-workspace cwd shaped like the skill dir (scripts/ payload,
    zero workspace markers)."""
    skill = root / "kunglao-skill"
    (skill / "scripts").mkdir(parents=True)
    (skill / "scripts" / "convergence_check.py").write_text("# stub\n",
                                                           encoding="utf-8")
    return skill


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=cwd, capture_output=True, text=True, timeout=120,
    )


# (label, cwd-builder, argv, expected outcome)
MATRIX = [
    ("ws_root__explicit_arg", "ws", ["{ws}"], "DISPATCH"),
    ("ws_root__dot_arg", "ws", ["."], "DISPATCH"),
    ("ws_root__no_arg", "ws", [], "DISPATCH"),
    ("parent_root__explicit_arg", "home", ["{ws}"], "DISPATCH"),
    ("parent_root__no_arg_sibling_probe", "home", [], "DISPATCH"),
    ("skill_dir__explicit_arg", "skill", ["{ws}"], "DISPATCH"),
    ("skill_dir__dot_arg", "skill", ["."], "HARD_ERROR"),
    ("skill_dir__no_arg", "skill", [], "HARD_ERROR"),
    ("elsewhere__no_arg", "elsewhere", [], "HARD_ERROR"),
    ("decoy_sibling_home__no_arg", "decoy", [], "HARD_ERROR"),
    ("decoy_sibling_home__dot_arg", "decoy", ["."], "HARD_ERROR"),
]


@pytest.mark.parametrize(
    "label,cwd_key,argv_tpl,expected",
    MATRIX,
    ids=[row[0] for row in MATRIX],
)
def test_cwd_matrix_never_flips_the_decision(
        tmp_path, label, cwd_key, argv_tpl, expected):
    """Every (cwd, arg-style) row: identical verdict or hard error — never
    a flipped decision."""
    home = tmp_path / "home"
    ws = _real_ws(home)
    cwd = {
        "ws": ws,
        "home": home,
        "skill": _skill_like_dir(tmp_path),
        "elsewhere": tmp_path / "elsewhere",
        "decoy": (_register_only_ws(tmp_path / "decoy-home").parent),
    }[cwd_key]
    cwd.mkdir(parents=True, exist_ok=True)
    argv = [a.replace("{ws}", str(ws)) for a in argv_tpl]

    r = _run(argv + ["--json"], cwd)

    if expected == "DISPATCH":
        assert r.returncode == 1, (
            f"[{label}] the true decision flipped: rc={r.returncode} "
            f"stderr={r.stderr[-300:]}")
        decision = json.loads(r.stdout)["decision"]
        assert decision == "DISPATCH", f"[{label}] flipped to {decision}"
    else:
        assert r.returncode == EXIT_MISSING_WORKSPACE, (
            f"[{label}] expected the #240 hard error, got rc="
            f"{r.returncode} stdout={r.stdout[:300]}")
        assert "not a kunglao workspace" in r.stderr, (
            f"[{label}] hard error must name the cause: {r.stderr[-300:]}")
        assert r.returncode not in DECIDED_BYTES, (
            f"[{label}] hard error leaked into the decided-state byte space")
        assert "CONVERGED" not in r.stdout, (
            f"[{label}] a verdict escaped the hard error: {r.stdout[:200]}")
