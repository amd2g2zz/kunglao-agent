# -*- coding: utf-8 -*-
"""Phase 0 shared fixtures: reused by all later phases (SDD contract tests).

- ws_factory:       tmp workspace builder (claim-register.yaml / runs / facts/_INDEX / claim_deps.yaml / task_spec.yaml)
- contract_validator: schemas/*.json registry (jsonschema validation wrapper)
- golden_master:   manifest replay helper
- isolated_home:   monkeypatch HOME → tmp (prevents hook-deployment tests from writing the production settings.json)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


# ---------- tmp fixture: compatible with legacy tests' main() direct-run signature ----------

@pytest.fixture
def tmp(tmp_path) -> Path:
    """Legacy test_*.py use `def test_x(tmp: Path)` + a main() direct run (TemporaryDirectory passing a Path).

    Under pytest the built-in tmp_path is injected (also a Path), so both
    modes share the signature with zero test-file changes.
    """
    return tmp_path



# ---------- ws_factory: tmp workspace construction ----------

@pytest.fixture
def ws_factory(tmp_path):
    """Build a minimal synthetic workspace; ws_factory() returns a new workspace, an isolated tmp dir per call."""

    def _make(claims: list[dict] | None = None, with_deps: bool = False,
              with_index: bool = False, with_runs: bool = True) -> Path:
        ws = tmp_path / f"ws-{len(list(tmp_path.iterdir()))}"
        ws.mkdir(parents=True)
        if with_runs:
            (ws / "runs").mkdir()
        reg = claims if claims is not None else []
        (ws / "claim-register.yaml").write_text(
            "claims:\n" + "".join(
                f"- id: {c['id']}\n  status: {c.get('status', 'OPEN')}\n"
                f"  boundary_type: {c.get('boundary_type', 'positive_observation')}\n"
                f"  evidence_tier_attempted: {c.get('evidence_tier_attempted', 0)}\n"
                f"  promotion_attempts: {c.get('promotion_attempts', 0)}\n"
                f"  depends_on: {c.get('depends_on', '[]')}\n"
                for c in reg
            ), encoding="utf-8")
        if with_deps:
            (ws / "claim_deps.yaml").write_text("depends_on: {}\n", encoding="utf-8")
        if with_index:
            facts = ws / "facts"
            facts.mkdir()
            (facts / "_INDEX.md").write_text("# _INDEX\n", encoding="utf-8")
        return ws

    return _make


# ---------- contract_validator: schemas/*.json registry ----------

@pytest.fixture
def contract_validator():
    """Validate an arbitrary object against schemas/<name>.json.

    Usage: contract_validator("decide-output", obj) -> None (raises AssertionError on mismatch)
    """
    import jsonschema

    _cache: dict[str, jsonschema.Draft7Validator] = {}

    def _load(name: str) -> jsonschema.Draft7Validator:
        if name not in _cache:
            path = SCHEMAS / f"{name}.json"
            if not path.exists():
                pytest.fail(f"schema file missing: {path}")
            schema = json.loads(path.read_text(encoding="utf-8"))
            _cache[name] = jsonschema.Draft7Validator(schema)
        return _cache[name]

    def _validate(name: str, obj) -> None:
        v = _load(name)
        errs = sorted(v.iter_errors(obj), key=lambda e: list(e.path))
        if errs:
            raise AssertionError(f"schema[{name}] violations:\n" +
                                 "\n".join(f"  {'.'.join(map(str, e.path))}: {e.message}" for e in errs[:8]))

    return _validate


# ---------- golden_master: manifest replay helper ----------

@pytest.fixture
def golden_master():
    """Replay golden cases per the manifest.yaml registry (byte-for-byte comparison)."""

    def _replay(case_id: str) -> str:
        import os
        import subprocess

        import yaml

        manifest = yaml.safe_load((ROOT / "tests" / "fixtures" / "golden" / "manifest.yaml").read_text(encoding="utf-8"))
        case = next(c for c in manifest["cases"] if c["id"] == case_id)
        env = dict(os.environ)
        env.pop("PRIORITY_WEIGHTS", None)
        r = subprocess.run(
            case["cmd"]["argv"], cwd=case["cmd"].get("cwd", str(ROOT)),
            env=env, capture_output=True, text=True,
            # tools emit UTF-8 (#317 unified stdout); decode as UTF-8, not the
            # GBK locale default, or multi-byte chars crash the reader thread
            encoding="utf-8", errors="replace",
            timeout=120,
        )
        return r.stdout

    return _replay


# ---------- isolated_home: prevent writes to the production settings.json ----------

@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Point HOME/USERPROFILE at tmp so any settings.json read/write lands in the isolated area."""
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home
