"""Phase 0 shared fixtures: reused by all later phases (SDD contract tests).

- ws_factory:       tmp workspace builder (claim-register.yaml / runs / facts/_INDEX / claim_deps.yaml / task_spec.yaml)
- contract_validator: schemas/*.json registry (jsonschema validation wrapper)
- golden_master:   manifest replay helper
- isolated_home:   monkeypatch HOME → tmp (prevents hook-deployment tests from writing the production settings.json)
- load_lock_factory / load_sensitive_registry: #369 cross-process serialization
  of the load-sensitive test family (machine-local flock; see bottom section)
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

try:  # POSIX only; Windows dev/CI is single-tenant and unaffected (#369)
    import fcntl
    _HAVE_FLOCK = hasattr(fcntl, "flock")
except ImportError:  # pragma: no cover - Windows
    _HAVE_FLOCK = False

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



# ---------- ws_factory: tmp workspace builder ----------

@pytest.fixture
def ws_factory(tmp_path):
    """Build a minimal synthetic workspace; ws_factory() returns a fresh workspace, each call in its own tmp dir."""

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
    """Validate that an arbitrary object conforms to schemas/<name>.json.

    Usage: contract_validator("decide-output", obj) -> None (raises AssertionError on violation)
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
            env=env, capture_output=True, text=True, timeout=120,
        )
        return r.stdout

    return _replay


# ---------- isolated_home: protect the production settings.json from writes ----------

@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Point HOME/USERPROFILE at tmp so every settings.json read/write lands in the sandbox."""
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


# ---------- #369: load-sensitive serialization (cross-process file lock) ----------
#
# The tick-chain / static-tools family fails only when concurrent pytest runs
# (multi-agent worktrees on one machine) execute these modules at the same
# time: subprocess spawn storms stretch wall-clock mtime windows (e.g. the
# 5s freshness assert in test_external_kicker) and the nested acceptance
# suite's subprocess timeout. Marked modules hold a machine-local flock for
# their whole duration, so no two sensitive modules ever co-run — within one
# run (tests are sequential) and across concurrent runs/worktrees.

LOAD_SENSITIVE_MODULES = frozenset({
    "test_drift_detection",       # tick-chain: mtime-based lock/worker windows
    "test_external_kicker",       # tick-chain: 5s lock-freshness wall-clock window
    "test_static_tools_1b",       # static-tools: per-test subprocess spawn storm
    "test_env_check",             # tick-chain adjacent (issue #369 audited set)
    "test_env_check_gate",        # real subprocess.run probes (timeout=60 each)
    "test_env_ports_wiring",      # tick-chain adjacent (issue #369 audited set)
})
LOAD_SENSITIVE_LOCK_NAME = "kunglao-pytest-load-sensitive.lock"
LOAD_SENSITIVE_ACQUIRE_TIMEOUT_S = 600.0  # generous: several queued suites under load


@contextmanager
def load_sensitive_lock(path=None, timeout: float = LOAD_SENSITIVE_ACQUIRE_TIMEOUT_S):
    """Cross-process mutual exclusion via flock on a machine-local file.

    The lock file lives in the system temp dir (per-user on macOS, shared
    /tmp per machine on Linux) — NOT in the repo, so concurrent worktrees
    of the same user contend on ONE lock. flock is bound to the open file
    description: the kernel releases it when the holding process dies, so
    there is no stale-lock handling. No-op where flock is unavailable.
    """
    if not _HAVE_FLOCK:  # pragma: no cover - Windows
        yield
        return
    lock_path = Path(path) if path is not None else Path(tempfile.gettempdir()) / LOAD_SENSITIVE_LOCK_NAME
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    acquired = False
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"load-sensitive lock not acquired within {timeout}s: {lock_path}")
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def pytest_collection_modifyitems(config, items):
    """Apply the load_sensitive marker via the module registry (single source
    of truth here — no per-file edits needed in the sensitive test modules)."""
    for item in items:
        module = getattr(item, "module", None)
        if module is not None and module.__name__.rsplit(".", 1)[-1] in LOAD_SENSITIVE_MODULES:
            item.add_marker(pytest.mark.load_sensitive)


@pytest.fixture
def load_lock_factory():
    """Raw lock factory for unit-testing the serialization mechanism (#369).
    Pass an explicit `path` (tmp) — the default is the real machine lock."""
    return load_sensitive_lock


@pytest.fixture
def load_sensitive_registry():
    """The frozenset of module names that must never co-run (#369)."""
    return LOAD_SENSITIVE_MODULES


@pytest.fixture(autouse=True, scope="module")
def _serialize_load_sensitive(request):
    """Hold the machine-local lock for the whole sensitive module (#369)."""
    module = getattr(request, "module", None)
    name = module.__name__.rsplit(".", 1)[-1] if module is not None else ""
    if name not in LOAD_SENSITIVE_MODULES or not _HAVE_FLOCK:
        yield
        return
    with load_sensitive_lock():
        yield
