# -*- coding: utf-8 -*-
"""tests/test_dep_surface_gate_467.py — issue 467 manifest-vs-imports gate.

The deployed env (framework install root pyproject/uv.lock) must cover
the hard import surface of the deployed code. Live evidence (E2E
round-6): 218 ModuleNotFoundError warns per round because the stale
production install's pyproject lacked numpy while the workspace-deployed
scripts imported it unguarded.

Spec: openspec/changes/issue-467-deploy-numpy/specs/deploy-truth/spec.md
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import dep_surface_gate as dsg  # noqa: E402
import hook_activation as ha  # noqa: E402


# ---------- fixture builders ----------

def _write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _surface_with_numpy(tmp: Path) -> Path:
    """A package whose deployed surface imports numpy UNGUARDED (the issue-467
    shape: scripts/rlvr/*.py module-level numpy)."""
    _write(tmp / "scripts" / "rlvr" / "winrate.py",
           "import numpy as np\n\nSCHEMA = 'x'\n")
    _write(tmp / "hooks" / "tick.py",
           "import yaml\n\n\ndef main():\n    return yaml.safe_load('')\n")
    return tmp


def _pyproject(tmp: Path, deps: list[str]) -> Path:
    lines = "\n".join(f'    "{d}",' for d in deps)
    return _write(tmp / "pyproject.toml",
                  "[project]\nname = 'fixture'\ndependencies = [\n"
                  + lines + "\n]\n")


def _env_root(tmp: Path, deps: list[str]) -> Path:
    _pyproject(tmp, deps)
    return tmp


# ---------- R1: package self-check ----------

class TestPackageSelfCheck:
    def test_numpy_import_with_numpyless_manifest_fails(self, tmp_path):
        surface = _surface_with_numpy(tmp_path)
        _pyproject(tmp_path, ["PyYAML>=6.0"])
        report = dsg.check(surface_root=surface, env_root=tmp_path)
        assert report["ok"] is False
        missing = {m["module"]: m for m in report["missing"]}
        assert "numpy" in missing, report
        assert any("rlvr" in f for f in missing["numpy"]["needed_by"])

    def test_repo_own_package_passes(self):
        """The repo's hard import surface is covered by the repo pyproject
        (the post-fix contract: numpy declared alongside the RLVR faces)."""
        report = dsg.check(surface_root=ROOT, env_root=ROOT)
        assert report["ok"] is True, report["missing"]

    def test_guarded_import_is_exempt(self, tmp_path):
        _write(tmp_path / "scripts" / "lazy.py",
               "try:\n    import tqdm\nexcept ImportError:\n"
               "    tqdm = None\n")
        _pyproject(tmp_path, [])
        report = dsg.check(surface_root=tmp_path, env_root=tmp_path)
        assert report["ok"] is True
        assert "tqdm" in report["guarded_undeclared"], report

    def test_bare_except_and_exception_guards_count_as_guarded(
            self, tmp_path):
        _write(tmp_path / "scripts" / "a.py",
               "try:\n    import rho_llm_backend\nexcept Exception:\n"
               "    rho_llm_backend = None\n")
        _write(tmp_path / "hooks" / "b.py",
               "try:\n    import yara\nexcept:\n    yara = None\n")
        _pyproject(tmp_path, [])
        report = dsg.check(surface_root=tmp_path, env_root=tmp_path)
        assert report["ok"] is True, report["missing"]

    def test_alias_mapping_covers_import_distribution_name_split(
            self, tmp_path):
        _write(tmp_path / "scripts" / "m.py", "import yaml\nimport z3\n")
        _pyproject(tmp_path, ["PyYAML>=6.0", "z3-solver>=4.12"])
        report = dsg.check(surface_root=tmp_path, env_root=tmp_path)
        assert report["ok"] is True, report["missing"]

    def test_stdlib_and_in_tree_modules_are_exempt(self, tmp_path):
        _write(tmp_path / "scripts" / "rlvr" / "__init__.py", "")
        _write(tmp_path / "scripts" / "local_face.py",
               "import json\nfrom rlvr import winrate\n")
        _write(tmp_path / "scripts" / "rlvr" / "winrate.py",
               "def face():\n    return {}\n")
        _pyproject(tmp_path, [])
        report = dsg.check(surface_root=tmp_path, env_root=tmp_path)
        assert report["ok"] is True, report["missing"]

    def test_cli_exits_nonzero_on_missing_dep(self, tmp_path, capsys):
        surface = _surface_with_numpy(tmp_path)
        _pyproject(tmp_path, [])
        rc = dsg.main(["--surface", str(surface), "--env", str(tmp_path)])
        captured = capsys.readouterr()
        assert rc == 1
        assert "numpy" in captured.out + captured.err

    def test_cli_exits_zero_on_clean_package(self, tmp_path):
        surface = _surface_with_numpy(tmp_path)
        _pyproject(tmp_path, ["PyYAML>=6.0", "numpy>=2.2"])
        assert dsg.main(["--surface", str(surface), "--env",
                         str(tmp_path)]) == 0


# ---------- R2: deploy-time env-coverage refusal ----------

class TestDeployRefusal:
    def _env_without_numpy(self, tmp_path_factory):
        env = tmp_path_factory.mktemp("env-root")
        _pyproject(env, ["PyYAML>=6.0", "pefile>=2023.2.7",
                         "capstone>=5.0"])
        return env

    def test_refuses_when_env_root_lacks_numpy(self, tmp_path,
                                               tmp_path_factory,
                                               monkeypatch):
        """The issue-467 mixed-drift replay: executing tree (repo surface)
        imports numpy hard; the resolved env root does not declare it."""
        env = self._env_without_numpy(tmp_path_factory)
        monkeypatch.setattr(ha, "_framework_project_root",
                            lambda: env)
        ws = tmp_path / "ws"
        ws.mkdir()
        with pytest.raises(RuntimeError) as exc:
            ha.deploy_workspace_copy(ws)
        msg = str(exc.value)
        assert "numpy" in msg
        assert str(env) in msg
        assert not (ws / ".claude" / "deployed-manifest.json").exists(), (
            "refusal must happen BEFORE any workspace mutation")
        assert not (ws / ".claude" / "scripts").exists()

    def test_green_path_unchanged_on_consistent_roots(self, tmp_path,
                                                       monkeypatch):
        # hermetic: pin the env resolution to the repo root (the machine
        # may carry an older production install — the refusal test owns
        # that behavior; this test owns the consistent-pair green path).
        monkeypatch.setattr(ha, "_framework_project_root", lambda: ROOT)
        ws = tmp_path / "ws"
        ws.mkdir()
        report = ha.deploy_workspace_copy(ws)
        assert report["copied"] + report["skipped"] > 0
        assert (ws / ".claude" / "deployed-manifest.json").is_file()

    def test_unresolvable_env_root_fails_open(self, tmp_path, monkeypatch,
                                              capsys):
        monkeypatch.setattr(ha, "_framework_project_root", lambda: None)
        ws = tmp_path / "ws"
        ws.mkdir()
        report = ha.deploy_workspace_copy(ws)
        assert report["copied"] + report["skipped"] > 0
        assert (ws / ".claude" / "deployed-manifest.json").is_file()
        captured = capsys.readouterr()
        assert "dep_surface_gate" in captured.out + captured.err, (
            "the fail-open path must leave the canonical warn trace")


# ---------- R3: upgrade refresh posture ----------

class TestUpgradeRefreshPosture:
    def test_gap_surfaces_as_warn_detail_never_raises(
            self, tmp_path, tmp_path_factory, monkeypatch):
        env = tmp_path_factory.mktemp("env-root-2")
        _pyproject(env, ["PyYAML>=6.0", "pefile>=2023.2.7",
                         "capstone>=5.0"])
        monkeypatch.setattr(ha, "_framework_project_root", lambda: env)
        import deployed_refresh as dr
        detail = dr.refresh(tmp_path)
        assert "dep_gap" in detail
        assert "numpy" in detail


# ---------- spec-side unit pins ----------

def test_norm_dist_is_pep503_and_alias_aware():
    assert dsg.norm_dist("PyYAML") == "pyyaml"
    assert dsg.norm_dist("z3_solver") == "z3-solver"
    assert dsg.dist_for("yaml") == "pyyaml"
    assert dsg.dist_for("z3") == "z3-solver"
    assert dsg.dist_for("PIL") == "pillow"
    assert dsg.dist_for("numpy") == "numpy"
