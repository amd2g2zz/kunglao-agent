# -*- coding: utf-8 -*-
"""#412: kunglao-init is initialization — it must never emit analysis conclusions.

TDD RED — current state:
- the scaffolded claim-register carries sample-analysis hypotheses as seed
  claims: C-002 "Family attribution — <sample>'s family/behavior class (CTI
  hypothesis...)", C-003 "Packer/obfuscation — whether <sample> is packed...".
  These are analysis conclusions written before the operator defines primary
  questions.
- the init exit line summarizes sample content: "(seed_claims=3 sample=<name>)".

GREEN targets (issue #412 acceptance):
- init stdout/stderr + the scaffolded claim-register contain zero
  analysis-conclusion vocabulary (family/verdict/attribution/packer/malicious/
  obfuscation...).
- seed claims are restricted to structural facts (type, hashes) explicitly
  needed for scaffolding.
- the exit line lists what init did (scaffold/env), not what the sample is.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from _factories import seed_bins

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"

# Analysis-conclusion vocabulary that must NEVER appear in init output or in
# the scaffolded claim-register (#412 — init performs no analysis). Word-
# bounded to avoid false positives ("action" contains "cti", etc.).
ANALYSIS_PATTERNS = (
    r"\bfamily\b",
    r"\bverdict\b",
    r"attribut",
    r"\bmalicious\b",
    r"\bpacker\b",
    r"obfuscat",
    r"behavior class",
    r"\bcti\b",
    r"\bhips\b",
)


@pytest.fixture
def init_ws(tmp_path: Path) -> Path:
    """Fresh workspace: bins/ with a PE sample + runs/."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    seed_bins(ws)
    (ws / "runs").mkdir()
    return ws


def _run_init(ws: Path, extra: list[str] | None = None,
              profile_root: Path | None = None,
              flag: str | None = "0") -> subprocess.CompletedProcess:
    """Run kunglao-init hermetically (--skip-toolchain + tmp profile root)."""
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws), *(extra or [])]
    if "--skip-toolchain" not in argv:
        argv.append("--skip-toolchain")
    if profile_root is None:
        profile_root = ws.parent / "profile-root"
    argv += ["--profile-root", str(profile_root)]
    env = {k: v for k, v in os.environ.items() if k != FLAG_NAME}
    env["PYTHONIOENCODING"] = "utf-8"
    if flag is not None:
        env[FLAG_NAME] = flag
    if not any(a.startswith("--host-exec-protection") for a in argv) \
            and "--resolve" not in argv:
        # #919: non-interactive tests answer the host-exec ask explicitly.
        argv += ["--host-exec-protection", "enabled"]
    return subprocess.run(argv, capture_output=True, text=True, timeout=120,
                          env=env, errors="replace")


def _analysis_hits(text: str) -> list[str]:
    """Return the analysis-conclusion vocabulary present in text ([] = clean)."""
    return [p for p in ANALYSIS_PATTERNS if re.search(p, text, re.IGNORECASE)]


def test_init_stdout_has_no_analysis_conclusions(init_ws: Path) -> None:
    """#412: init stdout/stderr contains zero family/verdict/attribution strings."""
    r = _run_init(init_ws, ["--type", "windows"])
    assert r.returncode == 0, f"init failed: {r.stderr}"
    output = r.stdout + r.stderr
    hits = _analysis_hits(output)
    assert not hits, f"init output contains analysis-conclusion vocabulary: {hits}"


def test_init_claim_register_has_no_analysis_conclusions(init_ws: Path) -> None:
    """#412: the scaffolded claim-register contains no analysis conclusions —
    seed claims are structural facts (type/hash), not family/verdict guesses."""
    r = _run_init(init_ws, ["--type", "windows"])
    assert r.returncode == 0, f"init failed: {r.stderr}"
    reg = (init_ws / "claim-register.yaml").read_text(encoding="utf-8")
    hits = _analysis_hits(reg)
    assert not hits, f"claim-register contains analysis-conclusion vocabulary: {hits}"


def test_init_scaffolds_structural_facts(init_ws: Path) -> None:
    """#412: structural facts (type, hashes, sample identity) still scaffolded."""
    r = _run_init(init_ws, ["--type", "windows"])
    assert r.returncode == 0, f"init failed: {r.stderr}"
    state = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "project_type=windows" in state, "project_type not scaffolded"
    reg = (init_ws / "claim-register.yaml").read_text(encoding="utf-8")
    assert "sample.exe" in reg, "sample identity missing from seed register"
    assert "sha256=" in reg, "sample sha256 missing from seed register"
    assert reg.count("id: C-") == 3, "structural seed count dropped below 3"


def test_init_exit_line_lists_actions_not_sample_content(init_ws: Path) -> None:
    """#412 guard: the init exit message lists what init did (scaffold/env)
    and does NOT summarize sample content (no sample= in the output)."""
    r = _run_init(init_ws, ["--type", "windows"])
    assert r.returncode == 0, f"init failed: {r.stderr}"
    out = r.stdout
    assert "sample=" not in out, f"init output summarizes sample content: {out}"
    assert "initialized" in out, "exit line missing 'initialized'"
    assert "project_type=" in out, "exit line missing the env/scaffold record"
