# -*- coding: utf-8 -*-
"""tests/test_release_receipt.py — issue #80 release contract (SDD+TDD).

Contract: a fresh clone reproduces the documented install + CLI surface; the
release manifest + receipt validate asset/CLI inventory; README claims are
reconciled with the receipt (no hand-maintained counts).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
MANIFEST = ROOT / "release-manifest.yaml"
PYPROJECT = ROOT / "pyproject.toml"
UV_LOCK = ROOT / "uv.lock"
README = ROOT / "README.md"
WORKFLOW = ROOT / ".github" / "workflows" / "release-check.yml"
JUNIT = ROOT / "tests" / "fixtures" / "junit-sample.xml"

MANIFEST_AGENTS = {
    "kunglao-worker.md", "kunglao-redteam.md", "ghidra-light.md", "floss-filter.md",
    "pefile-signature.md", "go-symbols.md",
    "verdict-scorer.md", "verdict-redteam.md",
}
ROUTER_SUBS = ["decide", "tick", "verify", "record", "health"]


def _manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def _run(cmd: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gen_receipt(*extra: str) -> dict:
    r = _run([sys.executable, str(SCRIPTS / "release_receipt.py"),
              "--pytest-junit", str(JUNIT), "--out", "-",
              "--revision", "test-sha", *extra])
    assert r.returncode == 0, f"receipt exit {r.returncode}\nstdout={r.stdout[:400]}\nstderr={r.stderr[:400]}"
    return json.loads(r.stdout)


# ---------- manifest honesty ----------

def test_manifest_loads_and_declares_release_contract():
    m = _manifest()
    assert m["schema_version"]
    assert m["project"] == "kunglao-agent"
    assert m["version"]
    assert m["requires_python"]
    assert set(m["dependencies"]) >= {"PyYAML", "pefile", "capstone", "jsonschema"}
    for section in ("agents", "hooks", "templates"):
        assert m["assets"][section], f"manifest assets.{section} is empty"
    assert len(m["clis"]) == 8
    assert m["router_subcommands"] == ROUTER_SUBS
    assert m["test_command"]


def test_manifest_agents_match_documented_roster():
    declared = {Path(p).name for p in _manifest()["assets"]["agents"]}
    assert declared == MANIFEST_AGENTS


def test_all_declared_assets_exist_in_repo():
    declared = (list(_manifest()["assets"]["agents"])
                + list(_manifest()["assets"]["hooks"])
                + list(_manifest()["assets"]["templates"]))
    missing = [p for p in declared if not (ROOT / p).exists()]
    assert not missing, f"declared assets missing from tree: {missing}"


def test_pyproject_declares_imported_dependencies():
    text = PYPROJECT.read_text(encoding="utf-8")
    assert 'requires-python = ">=3.11"' in text
    for dep in ("PyYAML", "pefile", "capstone", "jsonschema", "pytest"):
        assert dep in text, f"pyproject missing dependency {dep}"
    assert _manifest()["version"] in text, "pyproject version != manifest version"
    assert UV_LOCK.exists(), "uv.lock missing (uv sync --locked would fail)"


# ---------- CLI surface ----------

def test_all_declared_clis_help_exit_zero():
    for cli in _manifest()["clis"]:
        r = _run([sys.executable, str(ROOT / cli), "--help"])
        assert r.returncode == 0, f"{cli} --help exit {r.returncode}: {r.stderr[:300]}"


def test_router_subcommands_help_exit_zero():
    """kunglao.py SHALL register decide/tick/verify/record/health (issue #80)."""
    for sub in _manifest()["router_subcommands"]:
        r = _run([sys.executable, str(SCRIPTS / "kunglao.py"), sub, "--help"])
        assert r.returncode == 0, f"kunglao.py {sub} --help exit {r.returncode}: {r.stderr[:300]}"


# ---------- receipt ----------

def test_receipt_schema_and_content(contract_validator):
    receipt = _gen_receipt()
    contract_validator("release-receipt", receipt)
    assert receipt["revision"] == "test-sha"
    assert receipt["valid"] is True
    assert receipt["dependencies"]["pyproject"]["path"] == "pyproject.toml"
    assert receipt["dependencies"]["lockfile"]["sha256"] == _sha256(UV_LOCK)
    assert receipt["assets"]["agents"], "receipt agents inventory empty"
    for agent in receipt["assets"]["agents"]:
        assert re.fullmatch(r"[0-9a-f]{64}", agent["sha256"]), f"bad digest for {agent['path']}"
    assert all(c["help_exit"] == 0 for c in receipt["clis"])
    assert receipt["router"]["subcommands"] == ROUTER_SUBS
    assert receipt["tests"]["command"] == "python -m pytest -q"
    assert receipt["tests"]["passed"] == 618
    assert receipt["tests"]["failed"] == 6
    assert receipt["tests"]["skipped"] == 1
    assert receipt["tests"]["collected"] == 625


def test_receipt_check_fails_on_missing_declared_asset(tmp_path):
    bogus = tmp_path / "bogus-manifest.yaml"
    m = dict(_manifest())
    m["assets"] = {"agents": ["agents/does-not-exist.md"], "hooks": [], "templates": []}
    bogus.write_text(yaml.safe_dump(m), encoding="utf-8")
    r = _run([sys.executable, str(SCRIPTS / "release_receipt.py"), "--check",
              "--manifest", str(bogus)])
    assert r.returncode == 1, f"expected exit 1, got {r.returncode}: {r.stdout[:300]}"
    assert "does-not-exist" in (r.stdout + r.stderr)


def test_receipt_contains_no_secrets():
    receipt = _gen_receipt()
    blob = json.dumps(receipt)
    for pat in (r"api_?key", r"token", r"password", r"secret", r"bearer\s+\S+"):
        assert not re.search(pat, blob, re.IGNORECASE), f"receipt leaks pattern {pat}"


# ---------- README reconciliation ----------

def test_readme_has_no_stale_test_count_or_dependency_claims():
    text = README.read_text(encoding="utf-8")
    assert not re.search(r"269\s*(tests?|passed)", text), "README still claims 269 tests"
    assert "cryptography" not in text, "README still claims cryptography as a dependency"
    assert "uv sync --locked" in text, "README must document the locked install command"


def test_readme_points_to_receipt_as_source_of_truth():
    text = README.read_text(encoding="utf-8")
    assert re.search(r"release[- ]receipt|release-check", text, re.IGNORECASE), \
        "README must reference the release receipt / release-check as source of truth"


# ---------- CI workflow ----------

def test_release_check_workflow_declares_clean_env_steps():
    wf = WORKFLOW.read_text(encoding="utf-8")
    for needle in ("uv sync --locked", "release_receipt.py --check",
                   "pytest", "upload-artifact", "release-receipt"):
        assert needle in wf, f"release-check.yml missing step/artifact {needle}"
