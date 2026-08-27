# -*- coding: utf-8 -*-
"""Issue #783 — deployment manifest single source (RED→GREEN).

The deploy-model inversion needs ONE authority answering "which framework
files live inside a workspace .claude tree". The scaffold set is computed
as the transitive import closure of hooks/, so new runtime deps can never
drift out of the deployment.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "deploy-manifest.yaml"


def _load() -> dict:
    import yaml
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _srcs() -> set[str]:
    return {e["src"] for e in (_load().get("files") or [])}


def test_manifest_exists_and_schema():
    assert MANIFEST.is_file()
    data = _load()
    assert data["schema_version"] == "1"
    for e in data["files"]:
        assert {"src", "dest", "kind", "sha256"} <= set(e)
        assert e["kind"] in ("hook", "agent", "scaffold")
        assert e["dest"].startswith(".claude/")


def test_manifest_covers_registry_p0():
    srcs = _srcs()
    for must in ("hooks/dispatch_gate.py",
                 "hooks/write_guard.py",
                 "hooks/worker_budget.py",
                 "hooks/_path_hygiene.py",
                 "agents/kunglao-worker.md",
                 "agents/kunglao-redteam.md"):
        assert must in srcs, f"deployment manifest missing {must}"


def test_manifest_verify_cli_green():
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "deploy_manifest.py"),
         "--verify"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_scaffold_closure_includes_transitive_kunglao_log():
    # kunglao_log is imported by many hooks and lives in scripts/ — the
    # closure MUST have pulled it transitively, not just direct imports.
    assert "scripts/kunglao_log.py" in _srcs()
