# -*- coding: utf-8 -*-
"""Phase 0 shared fixtures: reused by all later phases (SDD contract tests).

- ws_factory:       tmp workspace builder (claim-register.yaml / runs / facts/_INDEX / claim_deps.yaml / task_spec.yaml)
- contract_validator: schemas/*.json registry (jsonschema validation wrapper)
- golden_master:   manifest replay helper
- isolated_home:   monkeypatch HOME → tmp (prevents hook-deployment tests from writing the production settings.json)
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

# ---------- session HOME isolation (anti-forgery) ----------
# The learning channel arms on a FIXED host path (~/.claude/...), and
# workspace init provisions that host path. The suite runs the REAL
# production CLIs as subprocesses, so the run's HOME is pointed at a
# session-local directory BEFORE any test module (or spawned hook
# child) imports anything, and EVERY test gets a FRESH home: a test
# whose subprocess provisions the key (a real init CLI run) arms only
# its own throwaway home, and the next test starts CI-like empty
# again. No test — in-process or spawned — can ever read, create, or
# arm the host's real key. A test that needs a specific home overrides
# HOME itself (isolated_home / explicit env).
_SESSION_HOME = Path(tempfile.mkdtemp(prefix="kunglao-tests-home-"))
_SESSION_HOME.mkdir(exist_ok=True)
os.environ["HOME"] = str(_SESSION_HOME)
os.environ["USERPROFILE"] = str(_SESSION_HOME)


@pytest.fixture(autouse=True)
def _fresh_test_home(tmp_path, monkeypatch, request):
    # OUTSIDE tmp_path on purpose: zero-side-effect pins assert that a
    # CLI run lands nothing in its cwd/tmp_path, and the per-test home
    # must not count as a side effect.
    home = Path(tempfile.mkdtemp(prefix="kunglao-test-home-"))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    request.addfinalizer(lambda: shutil.rmtree(home, ignore_errors=True))
    yield

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


# ---------- posterior-store isolation (issue-1005) ----------
# Learning stores resolve INSIDE the workspace now (cross-project off):
# each test's tmp workspace carries its own store, so no test can touch
# the repo or the host home. The env override is cleared (an outside-
# workspace override is refused by the resolver — a leaked env var must
# never redirect a test's store).
@pytest.fixture(autouse=True)
def _isolated_posterior_store(tmp_path, monkeypatch):
    monkeypatch.delenv("KUNGLAO_POSTERIOR_STORE", raising=False)
    yield


# ---------- learning-seal key isolation ----------
# The learning channel arms on a FIXED host path (~/.claude/...), and
# workspace init now provisions that host path. No test may ever read,
# create, or arm the host's real key: every test runs against a tmp
# key path (unarmed unless the test provisions it explicitly). The
# path keeps the CANONICAL key NAME so a test that derives its own
# armed path from ``KEY_PATH.name`` (the armed production-stop tests)
# still lands where a HOME-keyed child looks. The autouse ordering
# puts this BEFORE same-scope test fixtures, so a test that wants an
# armed channel overrides the path itself.
@pytest.fixture(autouse=True)
def _isolated_learning_seal_key(tmp_path, monkeypatch):
    try:
        from rlvr import learning_seal as _seal
    except ImportError:  # pragma: no cover — collection never depends on it
        yield
        return
    monkeypatch.setattr(_seal, "KEY_PATH",
                        tmp_path / ".claude" / ("kunglao-learning" + ".key"),
                        raising=False)
    yield


# ---------- failure-analysis defaults isolation ----------
# The lessons library and the /reflect queue are WORKSPACE-LOCAL now
# (cross-project off): defaults resolve inside each test's tmp
# workspace, so no test can append to the host home. Nothing to
# redirect — the fixture remains as a no-op guard.
@pytest.fixture(autouse=True)
def _isolated_failure_analysis_defaults(tmp_path, monkeypatch):
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


@pytest.fixture(autouse=True)
def _no_ambient_playbook_channel(monkeypatch):
    """#969: the distill write face spends a real model call and writes
    the operator playbook store — an ambient KUNGLAO_PLAYBOOK=1 must not
    turn unrelated e2e tests into live distillers. Tests that NEED the
    channel set it explicitly (monkeypatch.setenv after this fixture)."""
    monkeypatch.delenv("KUNGLAO_PLAYBOOK", raising=False)
