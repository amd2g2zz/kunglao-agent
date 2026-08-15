# -*- coding: utf-8 -*-
"""Phase 0 contract tests: pytest suite health + golden master infrastructure.

Step 0/1 RED — current state:
- test_claim_status_guard.py raises ModuleNotFoundError at pytest collection (no pytest.ini pythonpath)
- golden master not yet captured (manifest/fixtures absent) → all replays RED

GREEN target (phase 0 criteria):
- running `uv run pytest` from the kunglao-agent/ root collects with zero ERRORs, all green
- 29/29 golden cases replayable (byte-for-byte comparison against expected)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]  # kunglao-agent/
GOLDEN = ROOT / "tests" / "fixtures" / "golden"
MANIFEST = GOLDEN / "manifest.yaml"


# ---------- suite health ----------

def test_collection_no_error() -> None:
    """pytest collection of the full test-file set has no ERROR (incl. test_claim_status_guard.py's hooks import)."""
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert r.returncode == 0, f"collection had errors:\n{r.stdout}\n{r.stderr}"


def test_claim_status_guard_importable() -> None:
    """hooks/worker_budget.py importable from any CWD (pythonpath fix)."""
    r = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0,'.'); import worker_budget; print('ok')"],
        cwd=ROOT / "hooks", capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0 and r.stdout.strip() == "ok", r.stderr


# ---------- golden master ----------

def _load_manifest() -> list[dict]:
    """Load golden cases and rebase their commands to THIS machine.

    Fixtures were captured on the original author's Windows box and still
    contain absolute paths (python.exe, absolute venv/home dirs).
    The captured paths were rewritten to {{PYTHON}}/{{ROOT}} placeholders in
    the repo; on any other machine those become sys.executable and the paths
    under ROOT.  A legacy direct-prefix branch is kept for robustness.
    The ws/ dirs and expected/stdout.txt stay byte-for-byte comparable.
    """
    if not MANIFEST.exists():
        return []
    import yaml
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    cases = data["cases"]
    OLD_PY = r"C:\Users\hr\AppData\Local\Programs\Python\Python311\python.exe"
    OLD_PREFIX = r"C:\Users\hr\.claude\kong-refactor\kong-agent"
    for c in cases:
        argv = list(c["cmd"]["argv"])
        # argv[0] is the Windows python.exe (or its {{PYTHON}} placeholder)
        # — run with THIS interpreter
        if argv[0] in ("{{PYTHON}}", OLD_PY):
            argv[0] = sys.executable
        rebased = []
        for a in argv[1:]:
            if isinstance(a, str):
                if "{{ROOT}}" in a:
                    a = str(ROOT) + a.split("{{ROOT}}", 1)[1]
                elif OLD_PREFIX in a:
                    a = str(ROOT) + a.split(OLD_PREFIX, 1)[1]
                # captured paths use backslash separators, which only Windows
                # resolves — normalize for the machine actually running them
                a = a.replace("\\", "/")
            rebased.append(a)
        c["cmd"]["argv"] = [argv[0]] + rebased
        cwd = c["cmd"].get("cwd")
        if isinstance(cwd, str):
            if "{{ROOT}}" in cwd:
                cwd = str(ROOT) + cwd.split("{{ROOT}}", 1)[1]
            elif OLD_PREFIX in cwd:
                cwd = str(ROOT) + cwd.split(OLD_PREFIX, 1)[1]
            c["cmd"]["cwd"] = cwd.replace("\\", "/")
    return cases


def _tree_digest(root: Path) -> str:
    """Deterministic digest of a fixture tree (relpath:sha256 per file)."""
    import hashlib

    if not root.exists():
        return "<no-ws>"
    parts = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            parts.append(f"{p.relative_to(root)}:{hashlib.sha256(p.read_bytes()).hexdigest()}")
    return "\n".join(parts)


@pytest.mark.parametrize("case", _load_manifest(), ids=lambda c: c["id"])
def test_golden_replay(case: dict) -> None:
    """Replay golden cases byte for byte; output must match the captured expected.

    Replay runs against a TEMPORARY COPY of the fixture ws dir — the CLI
    appends ledger rows, so running against the fixture itself would mutate
    tracked files and make replays non-idempotent.
    """
    import re
    import shutil
    import tempfile

    case_dir = GOLDEN / case["id"]
    expected = case_dir / "expected" / "stdout.txt"
    assert expected.exists(), f"golden fixture missing: {expected}"
    cmd = case["cmd"]
    env = dict(os.environ)
    env.pop("PRIORITY_WEIGHTS", None)
    digest_before = _tree_digest(case_dir / "ws")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_ws = Path(tmp) / "ws"
        if (case_dir / "ws").exists():
            shutil.copytree(case_dir / "ws", tmp_ws)
        else:
            tmp_ws.mkdir()
        # point every fixture ws argument at the temp copy (keep any file
        # tail: F-13 passes ws/claim.txt etc.)
        argv = []
        for a in cmd["argv"]:
            if "tests/fixtures/golden" in a:
                tail = a.split("/ws", 1)[1] if "/ws" in a else ""
                a = str(tmp_ws) + tail
            argv.append(a)
        r = subprocess.run(
            argv, cwd=cmd.get("cwd", str(ROOT)),
            env=env, capture_output=True, text=True, timeout=120,
        )
    assert _tree_digest(case_dir / "ws") == digest_before, \
        f"golden replay mutated fixture ws dir: {case_dir / 'ws'}"
    if case.get("expected_exit") is not None:
        assert r.returncode == case["expected_exit"], \
            f"exit {r.returncode} != {case['expected_exit']}\nstdout={r.stdout[:500]}\nstderr={r.stderr[:500]}"
    else:
        exp = expected.read_text(encoding="utf-8")
        # Timestamp normalization: capture and replay cross seconds; progress_report etc. carry current UTC time
        exp_norm = re.sub(r"\(20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ\)", "(<TS>)", exp)
        act_norm = re.sub(r"\(20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ\)", "(<TS>)", r.stdout)
        assert act_norm == exp_norm, f"stdout differs:\n--- expected ---\n{exp_norm}\n--- actual ---\n{act_norm}"


def test_golden_cmd_json_has_no_absolute_paths() -> None:
    """Golden fixtures must be machine-portable: no absolute paths (C:\\, D:\\,
    /Users/, /home/) anywhere in cmd.json argv/cwd or manifest.yaml."""
    import json
    abs_markers = ("C:\\", "c:\\", "D:\\", "d:\\", "/Users/", "/home/")
    hits: list[str] = []
    for case_dir in sorted(GOLDEN.glob("F-*")):
        if not case_dir.is_dir():
            continue
        raw = (case_dir / "cmd.json").read_text(encoding="utf-8")
        if any(m in raw for m in abs_markers):
            hits.append(f"{case_dir.name}/cmd.json")
    if MANIFEST.exists():
        raw = MANIFEST.read_text(encoding="utf-8")
        if any(m in raw for m in abs_markers):
            hits.append("manifest.yaml")
    assert not hits, f"absolute paths hardcoded in: {hits}"
