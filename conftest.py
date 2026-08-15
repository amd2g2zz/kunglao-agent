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



# ---------- ws_factory: tmp 工作区构造 ----------

@pytest.fixture
def ws_factory(tmp_path):
    """构造最小合成工作区; ws_factory() 返回新工作区, 每调用独立 tmp 目录."""

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


# ---------- contract_validator: schemas/*.json 注册表 ----------

@pytest.fixture
def contract_validator():
    """校验任意对象是否符合 schemas/<name>.json.

    用法: contract_validator("decide-output", obj) -> None(不符抛 AssertionError)
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


# ---------- golden_master: manifest 重放辅助 ----------

@pytest.fixture
def golden_master():
    """按 manifest.yaml 注册表重放 golden 用例(逐字节比对)."""

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


# ---------- isolated_home: 防写生产 settings.json ----------

@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """把 HOME/USERPROFILE 指向 tmp, 任何 settings.json 读写落在隔离区."""
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home
