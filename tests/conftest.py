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

# 863-h Family L: shared fixture factories. Plain functions live in
# tests/_factories.py; tests/ is on sys.path under pytest's prepend
# import mode, so the bare module name resolves to THIS directory.
from _factories import seed_bins, write_claims_register, write_hook_state  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas"


# ---------- fresh canonical warn state per test ----------
# kunglao_log.warn dedupes process-wide (one dict per process, per
# (op, last-reason)); without a per-test reset, two tests exercising the
# same (op, reason) would suppress each other's expected WARN output.
# Autouse + cheap (one monkeypatch op). Import guarded: collection must
# never depend on scripts/ being importable.
@pytest.fixture(autouse=True)
def _fresh_canonical_warn_state(monkeypatch):
    try:
        import kunglao_log as _kl
    except ImportError:  # pragma: no cover
        yield
        return
    monkeypatch.setattr(_kl, "_WARN_LAST", {}, raising=False)
    yield


# ---------- posterior-store isolation (#545) ----------
# The WS2 store (scripts/rlvr/patterns/posterior-store.jsonl) is RUNTIME
# data — no test may ever append to the repo's guarded prior-store root.
# Every test gets KUNGLAO_POSTERIOR_STORE pointed at a tmp path; tests
# that exercise the store override it explicitly.
@pytest.fixture(autouse=True)
def _isolated_posterior_store(tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-store-isolated"))
    yield


# ---------- failure-analysis defaults isolation (issue 647 item 6) ----------
# The rollup's terminal path seeds analyses/failure-*.yaml skeletons, so
# aggregate_lessons now runs in EVERY rollup-firing test — and its default
# destinations (the global lessons library + ~/.claude/learnings-queue.json)
# are real-home paths no test may append to. Tests that exercise the
# aggregation override these explicitly; the defaults are redirected here.
@pytest.fixture(autouse=True)
def _isolated_failure_analysis_defaults(tmp_path, monkeypatch):
    try:
        import failure_analysis_gate as _fag
    except ImportError:  # pragma: no cover — collection never depends on it
        yield
        return
    monkeypatch.setattr(_fag, "LESSONS_DIR_DEFAULT",
                        tmp_path / "lessons-isolated", raising=False)
    monkeypatch.setattr(_fag, "REFLECT_QUEUE_DEFAULT",
                        tmp_path / "reflect-queue-isolated.json",
                        raising=False)
    yield


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
        write_claims_register(ws, reg, defaults=True)
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


# ---------- 863-h Family L: thin fixture re-exports of tests/_factories ----------

@pytest.fixture
def hook_state_seed():
    """Factory writing .hook_state.json (plain fn: tests/_factories)."""
    return write_hook_state


@pytest.fixture
def claims_seed():
    """Factory writing claim-register.yaml (plain fn: tests/_factories)."""
    return write_claims_register


@pytest.fixture
def bins_seed():
    """Factory seeding bins/ with a synthetic sample (plain fn)."""
    return seed_bins
