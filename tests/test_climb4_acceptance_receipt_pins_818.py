#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb4_acceptance_receipt_pins_818.py — #818 climb segment 4D.

Behavior pins on REAL fixtures for two long-tail faces the third climb leg
left unmeasured:

  scripts/acceptance_check.py — the matrix ORCHESTRATOR (not the nested
  pytest leaves): category-spec parsing with the unknown-name refusal,
  the ASCII progress renderer, the no-op bar shim, and run_categories'
  contract over stubbed category leaves — in-order execution, the
  smoke-failure short-circuit that marks the rest SKIPPED, the REJECT
  verdict on any failing category, the exception cage (a crashing leaf
  becomes exit_code 2 with the exception recorded), and the
  matrix-summary.json aggregate. The leaves themselves (nested pytest
  suites) stay untouched — the orchestration is the behavior under test.

  scripts/release_receipt.py — the junit intake and CLI contract: junit
  counting over both XML shapes, the --pytest-junit receipt face, the
  explicit tests-not-run fast-path marker, --check as the fast
  manifest/CLI gate (rc 0 clean / rc 1 with a declared-but-missing
  asset), the missing-manifest and missing-junit refusals, stdout mode,
  and the help-probe error path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import acceptance_check as ac  # noqa: E402
import release_receipt as rr  # noqa: E402


# ------------------------------------------------- acceptance orchestrator

class TestAcceptanceOrchestrator:
    def test_progress_bar_renders_ascii(self) -> None:
        bar = ac._progress("climb", 0.5, width=10)
        assert bar == "[=====     ]  50% climb"
        assert ac._progress("done", 1.0, width=4).startswith("[====] 100%")

    def test_category_spec_parses_and_refuses_unknowns(self) -> None:
        assert ac._parse_categories("smoke, complexity") == ["smoke",
                                                             "complexity"]
        with pytest.raises(ValueError, match="unknown category"):
            ac._parse_categories("smoke,no-such-cat")

    def test_noop_bar_shim_behaves_like_a_context_manager(
            self, capsys) -> None:
        with ac._NoOpBar(3) as bar:
            bar.update(2)
            bar.set_postfix_str("regression: PASS (rc=0)")
            bar.write("  === regression === exit=0")
            assert bar.n == 2
            bar.set_description("ignored")
        assert "regression: PASS" in capsys.readouterr().out
        bar.close()  # idempotent close is part of the shim contract

    def test_matrix_runs_in_order_and_accepts(self, tmp_path,
                                              monkeypatch) -> None:
        calls: list[str] = []
        for name in ("smoke", "complexity"):
            monkeypatch.setitem(
                ac.CATEGORY_FUNCS, name,
                (lambda n: lambda: (calls.append(n),
                                    {"category": n, "exit_code": 0,
                                     "duration_s": 0.0, "ts": "t"})[-1])(name))
        report = ac.run_categories(["smoke", "complexity"],
                                   out_root=tmp_path / "out")
        assert calls == ["smoke", "complexity"]
        assert report["verdict"] == "ACCEPT"
        assert report["overall_passed"] is True
        summary = json.loads(
            (tmp_path / "out" / "matrix-summary.json").read_text(
                encoding="utf-8"))
        assert [c["category"] for c in summary["categories"]] == calls

    def test_smoke_failure_short_circuits_the_rest(self, tmp_path,
                                                   monkeypatch) -> None:
        def smoke_fail():
            return {"category": "smoke", "exit_code": 1, "duration_s": 0.0,
                    "ts": "t"}

        ran: list[str] = []

        def leaf():
            ran.append("complexity")
            return {"category": "complexity", "exit_code": 0,
                    "duration_s": 0.0, "ts": "t"}

        monkeypatch.setitem(ac.CATEGORY_FUNCS, "smoke", smoke_fail)
        monkeypatch.setitem(ac.CATEGORY_FUNCS, "complexity", leaf)
        monkeypatch.setitem(ac.CATEGORY_FUNCS, "regression", leaf)
        report = ac.run_categories(["smoke", "complexity", "regression"],
                                   out_root=tmp_path / "out")
        assert report["verdict"] == "REJECT"
        assert ran == []  # nothing after a failed smoke actually runs
        skipped = [c for c in report["categories"] if c.get("skipped")]
        assert [c["category"] for c in skipped] == ["complexity",
                                                    "regression"]
        assert all(c["skipped"] == "smoke-failure-short-circuit"
                   for c in skipped)

    def test_crashing_leaf_is_caged_as_exit_code_2(self, tmp_path,
                                                   monkeypatch) -> None:
        def boom():
            raise RuntimeError("leaf exploded")

        monkeypatch.setitem(ac.CATEGORY_FUNCS, "smoke", boom)
        report = ac.run_categories(["smoke"], out_root=tmp_path / "out")
        row = report["categories"][0]
        assert row["exit_code"] == 2
        assert "leaf exploded" in row["exception"]
        assert report["verdict"] == "REJECT"

    def test_main_routes_matrix_mode_and_reports_rc(self, tmp_path,
                                                    monkeypatch) -> None:
        monkeypatch.setitem(
            ac.CATEGORY_FUNCS, "smoke",
            lambda: {"category": "smoke", "exit_code": 0, "duration_s": 0.0,
                     "ts": "t"})
        rc = ac.main(["--categories", "smoke", "--out", str(tmp_path / "o")])
        assert rc == 0
        monkeypatch.setitem(
            ac.CATEGORY_FUNCS, "smoke",
            lambda: {"category": "smoke", "exit_code": 1, "duration_s": 0.0,
                     "ts": "t"})
        assert ac.main(["--categories", "smoke",
                        "--out", str(tmp_path / "o2")]) == 1

    def test_main_flag_exclusivity(self, tmp_path) -> None:
        assert ac.main(["--smoke", "--full"]) == 2
        assert ac.main(["--smoke", "--categories", "smoke"]) == 2
        assert ac.main(["--full", "--categories", "smoke"]) == 2
        assert ac.main(["--categories", "not-a-cat"]) == 2


# ------------------------------------------------------ release receipt

def _junit(tmp_path: Path, wrapped: bool) -> Path:
    suite = ('<testsuite name="t" tests="10" failures="2" skipped="1" '
             'errors="1"></testsuite>')
    body = (f"<testsuites>{suite}</testsuites>" if wrapped else suite)
    p = tmp_path / ("wrapped.junit.xml" if wrapped else "flat.junit.xml")
    p.write_text(f'<?xml version="1.0"?>{body}', encoding="utf-8")
    return p


class TestJunitIntake:
    def test_junit_counts_both_xml_shapes(self, tmp_path) -> None:
        for wrapped in (True, False):
            got = rr.parse_junit(_junit(tmp_path, wrapped))
            assert got == {"collected": 10, "passed": 6, "failed": 2,
                           "skipped": 1}

    def test_receipt_from_junit_records_the_counts(self, tmp_path,
                                                   capsys) -> None:
        out = tmp_path / "receipt.json"
        rc = rr.main(["--manifest", "release-manifest.yaml",
                      "--pytest-junit", str(_junit(tmp_path, True)),
                      "--out", str(out)])
        assert rc == 0
        assert "release receipt valid" in capsys.readouterr().err
        receipt = json.loads(out.read_text(encoding="utf-8"))
        assert receipt["tests"]["passed"] == 6
        assert receipt["tests"]["failed"] == 2
        assert receipt["valid"] is True

    def test_fast_path_marker_is_explicit_not_silent(self, tmp_path) -> None:
        out = tmp_path / "receipt.json"
        rc = rr.main(["--manifest", "release-manifest.yaml",
                      "--tests-not-run-fast-path", "--out", str(out)])
        assert rc == 0
        tests = json.loads(out.read_text(encoding="utf-8"))["tests"]
        assert tests["not_run"] is True
        assert tests["reason"] == rr.FAST_PATH_NOT_RUN_REASON

    def test_stdout_mode_emits_the_json(self, tmp_path, capsys) -> None:
        rc = rr.main(["--manifest", "release-manifest.yaml", "--no-tests",
                      "--out", "-"])
        assert rc == 0
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["schema_version"] == rr.SCHEMA_VERSION

    def test_check_is_the_fast_gate_rc0(self, capsys) -> None:
        assert rr.main(["--manifest", "release-manifest.yaml",
                        "--check"]) == 0
        assert "VIOLATIONS" not in capsys.readouterr().err

    def test_check_reports_validation_violations(self, tmp_path,
                                                 capsys) -> None:
        import yaml
        # pure-validate faces: a version disagreement with pyproject.toml
        # and an empty test_command both violate the release contract
        bad = tmp_path / "bad-manifest.yaml"
        bad.write_text(yaml.safe_dump({
            "version": "0.0.0-test",
            "assets": {},
        }), encoding="utf-8")
        rc = rr.main(["--manifest", str(bad), "--check"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "RELEASE CONTRACT VIOLATIONS" in err
        assert "version mismatch" in err
        assert "test_command is empty" in err

    def test_missing_manifest_refuses(self, tmp_path, capsys) -> None:
        rc = rr.main(["--manifest", str(tmp_path / "nope.yaml")])
        assert rc == 1
        assert "manifest not found" in capsys.readouterr().err

    def test_missing_junit_refuses(self, tmp_path) -> None:
        assert rr.main(["--manifest", "release-manifest.yaml",
                        "--pytest-junit",
                        str(tmp_path / "absent.xml")]) == 1

    def test_help_probe_records_the_failure_rc(self) -> None:
        stub = rr.__file__  # any real file: `[python file --help]` runs it
        errors: list[str] = []
        # a python file that is not a CLI: exits 0 on --help? This script
        # has no argparse so --help is just an ignored argv -> rc 0. Use
        # an exit-code stub instead for the failure face.
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            cli = Path(td) / "fails.py"
            cli.write_text("import sys; sys.exit(3)\n", encoding="utf-8")
            got = rr.cli_inventory([str(cli)], errors)
            assert got[0]["help_exit"] == 3
            assert errors and "--help failed" in errors[0]
        del stub
