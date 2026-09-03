# -*- coding: utf-8 -*-
"""B9 (#823): check_safety — the three-check mechanical pre-run gate.

Any red REFUSES the run (fail-closed); a red check is a human action,
never auto-repaired.
"""
from pathlib import Path

import bench_intake as bi


def _vault(tmp: Path, encrypted=True) -> Path:
    v = tmp / "vault"
    v.mkdir(parents=True)
    if encrypted:
        (v / ".encrypted").write_text("age\n", encoding="utf-8")
    return v


def _bench_dir(tmp: Path) -> None:
    bench_dir = tmp / "kunglao-bench"
    bench_dir.mkdir()
    (bench_dir / ".gitignore").write_text("samples/\n", encoding="utf-8")


def _clean_git(monkeypatch):
    monkeypatch.setattr(bi, "_git_porcelain", lambda root: (0, ""))


def test_all_green_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(bi, "REPO_ROOT", tmp_path)
    _bench_dir(tmp_path)
    _clean_git(monkeypatch)
    out = bi.check_safety(_vault(tmp_path), vm_snapshot="clean-baseline")
    assert out["ok"] is True and all(out["checks"].values())


def test_unencrypted_vault_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(bi, "REPO_ROOT", tmp_path)
    _bench_dir(tmp_path)
    _clean_git(monkeypatch)
    out = bi.check_safety(_vault(tmp_path, encrypted=False),
                          vm_snapshot="snap")
    assert out["ok"] is False
    assert out["checks"]["vault_encrypted"] is False


def test_missing_vm_snapshot_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(bi, "REPO_ROOT", tmp_path)
    _bench_dir(tmp_path)
    _clean_git(monkeypatch)
    out = bi.check_safety(_vault(tmp_path), vm_snapshot=None)
    assert out["ok"] is False
    assert out["checks"]["vm_snapshot"] is False


def test_gitignore_without_samples_rule_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(bi, "REPO_ROOT", tmp_path)
    bench_dir = tmp_path / "kunglao-bench"
    bench_dir.mkdir()
    (bench_dir / ".gitignore").write_text("runs/\n", encoding="utf-8")
    _clean_git(monkeypatch)
    out = bi.check_safety(_vault(tmp_path), vm_snapshot="snap")
    assert out["ok"] is False
    assert out["checks"]["git_clean"] is False
