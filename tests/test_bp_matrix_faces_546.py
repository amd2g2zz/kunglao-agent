# -*- coding: utf-8 -*-
"""tests/test_bp_matrix_faces_546.py — the blocked-path measurement
faces (#546): the corpus-root redirection (eval/ is intermediate-
process material; the delta runs against the operator's LOCAL corpus),
the expansion ablation switch (KUNGLAO_EXPANSION=0 = the L3 off-arm),
and the two blocked-path family contract rows.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_contract  # noqa: E402
import eval_dataset  # noqa: E402


def test_corpus_root_env_override(monkeypatch, tmp_path):
    # the redirected root resolves units under <root>/v1/tasks/<tier>/
    monkeypatch.setenv("KUNGLAO_EVAL_ROOT", str(tmp_path))
    unit = tmp_path / "v1" / "tasks" / "toolflex" / "tf-x-v1"
    unit.mkdir(parents=True)
    (unit / "task.yaml").write_text("x: 1", encoding="utf-8")
    dirs = eval_dataset.iter_task_dirs(tier="toolflex")
    assert [d.name for d in dirs] == ["tf-x-v1"]


def test_corpus_root_defaults_to_repo_eval(monkeypatch):
    monkeypatch.delenv("KUNGLAO_EVAL_ROOT", raising=False)
    assert eval_dataset.EVAL_ROOT == ROOT / "eval"


def test_expansion_off_switch_is_pinned():
    src = (ROOT / "scripts" / "e2e" / "checkpoints.py").read_text(
        encoding="utf-8")
    body = src.split("def _maybe_expand")[1].split("def _maybe_distill")[0]
    assert 'KUNGLAO_EXPANSION' in body
    assert '== "0"' in body


def test_blocked_path_families_have_contract_rows():
    for fam in ("tf-novelvm", "tf-novelcipher"):
        row = eval_contract.require_family(fam)
        assert row["suffix"] == ".txt"
        assert row["target_surface"] == "text"
