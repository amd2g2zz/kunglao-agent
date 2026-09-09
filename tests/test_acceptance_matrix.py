# -*- coding: utf-8 -*-
"""Contract tests for the milestone acceptance CLI's matrix face.

scripts/acceptance_check.py is the ONE milestone-acceptance entry: the
static check battery (default / --full) plus the absorbed category
matrix (--categories, with --smoke as the pinned fastest face). The
former standalone matrix runner no longer exists.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import acceptance_check as ac  # noqa: E402


MATRIX_SCRIPT_GONE = ROOT / "scripts" / "run_test_matrix.py"


def test_matrix_runner_file_is_gone():
    """The merge is a real merge: the standalone matrix runner is deleted
    (no-backcompat), not left behind as a second entry point."""
    assert not MATRIX_SCRIPT_GONE.exists()


def test_all_categories_registered():
    assert set(ac.CATEGORY_FUNCS) == {
        "smoke", "complexity", "regression", "integration", "fault",
        "mutation"}


def test_parse_categories_accepts_subset_and_order():
    assert ac._parse_categories("smoke,regression") == ["smoke", "regression"]


def test_parse_categories_rejects_unknown():
    with pytest.raises(ValueError):
        ac._parse_categories("smoke,bogus")


def test_run_categories_reports_and_aggregates(monkeypatch, tmp_path):
    calls = []

    def fake(name):
        def _f():
            calls.append(name)
            return {"category": name, "exit_code": 0, "duration_s": 0.0}
        return _f

    monkeypatch.setattr(
        ac, "CATEGORY_FUNCS",
        {n: fake(n) for n in ("smoke", "regression")})
    report = ac.run_categories(["smoke", "regression"], out_root=tmp_path)
    assert calls == ["smoke", "regression"]
    assert report["overall_passed"] is True
    assert [c["category"] for c in report["categories"]] == [
        "smoke", "regression"]
    assert (tmp_path / "matrix-summary.json").is_file()


def test_run_categories_fails_on_nonzero_exit(monkeypatch, tmp_path):
    def failing():
        return {"category": "fault", "exit_code": 1, "duration_s": 0.0}

    monkeypatch.setattr(ac, "CATEGORY_FUNCS", {"fault": failing})
    report = ac.run_categories(["fault"], out_root=tmp_path)
    assert report["overall_passed"] is False


def test_cli_categories_flag_orchestrates(monkeypatch, tmp_path, capsys):
    seen = []

    def fake_smoke():
        seen.append("smoke")
        return {"category": "smoke", "exit_code": 0, "duration_s": 0.0}

    monkeypatch.setattr(ac, "CATEGORY_FUNCS", {"smoke": fake_smoke})
    rc = ac.main(["--categories", "smoke",
                  "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert seen == ["smoke"]
    assert "smoke" in out


def test_cli_smoke_flag_is_the_pinned_fastest_face(monkeypatch, tmp_path):
    seen = []

    def fake_smoke():
        seen.append("smoke")
        return {"category": "smoke", "exit_code": 0, "duration_s": 0.0}

    monkeypatch.setattr(ac, "CATEGORY_FUNCS", {"smoke": fake_smoke})
    rc = ac.main(["--smoke", "--out", str(tmp_path)])
    assert rc == 0
    assert seen == ["smoke"]


def test_cli_mutually_exclusive_modes():
    assert ac.main(["--smoke", "--full"]) == 2
    assert ac.main(["--smoke", "--categories", "smoke"]) == 2


def test_cli_help_faces():
    r = subprocess.run([sys.executable, str(SCRIPTS / "acceptance_check.py"),
                        "--help"], capture_output=True, text=True)
    assert r.returncode == 0
    for face in ("--smoke", "--categories", "--full", "--write"):
        assert face in r.stdout
