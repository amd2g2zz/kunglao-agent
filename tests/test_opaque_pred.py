# -*- coding: utf-8 -*-
"""tests/test_opaque_pred.py — issue #306: tools/static/opaque_pred.py contract.

z3 opaque-predicate checker + MBA equivalence simplifier over C expressions:
recursive-descent parser, 32-bit BitVec semantics, two-solver tautology /
contradiction check with 5s timeout, z3-missing degrade path (exit 2 with
install guidance) and #277 CLI mechanics (--json / --reproduce / exit codes).
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "tools" / "static"
for sub in ("tools/static",):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

import opaque_pred as op  # noqa: E402

HAS_Z3 = importlib.util.find_spec("z3") is not None
requires_z3 = pytest.mark.skipif(not HAS_Z3, reason="z3-solver not installed")

L1_LINE_RE = re.compile(r"^([A-Za-z_][\w.]*)\s*[:=]\s*(.+)$")


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(STATIC / "opaque_pred.py"), *args],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )


def _parse_reproduce(stdout: str) -> dict:
    return dict(L1_LINE_RE.match(line).groups() for line in stdout.splitlines()
                if L1_LINE_RE.match(line))


# =====================================================================
# parser (z3-free — no solver needed)
# =====================================================================

class TestParser:
    # (expr, expected_c) — parse + node_to_c round-trip table.
    PARSE_CASES = [
        ("(x + 1) * (x + 1)", "((x + 1) * (x + 1))"),
        ("x + y * 3", "(x + (y * 3))"),
        ("x + 1 << 2", "((x + 1) << 2)"),
        ("x & 1 == 1", "(x & (1 == 1))"),
        ("!(-x)", "(!(-x))"),
        ("x ^ 0xff", "(x ^ 255)"),
    ]

    def test_parse_roundtrips_to_c(self):
        for expr, expected in self.PARSE_CASES:
            node = op.parse_expr(expr)
            assert op.node_to_c(node) == expected, expr

    def test_parse_error_unbalanced_paren(self):
        with pytest.raises(op.ParseError):
            op.parse_expr("(x +")

    def test_parse_error_bad_operator(self):
        with pytest.raises(op.ParseError):
            op.parse_expr("x +* y")

    def test_parse_error_trailing_junk(self):
        with pytest.raises(op.ParseError):
            op.parse_expr("x + 1 y")


# =====================================================================
# opaque predicate classification (z3)
# =====================================================================

@requires_z3
class TestOpaquePredicate:
    def test_always_true_disjunction(self):
        r = run_cli("--expr", "x >= 0 || x < 0")
        assert r.returncode == 0
        assert "always_true" in r.stdout
        assert "simplified=1" in r.stdout

    def test_always_true_mba_identity(self):
        # (x+1)^2 == x^2 + 2x + 1 holds mod 2^32 — classic MBA identity.
        r = run_cli("--expr", "(x+1)*(x+1) == x*x+2*x+1")
        assert r.returncode == 0
        assert "always_true" in r.stdout

    def test_always_false_self_contradiction(self):
        r = run_cli("--expr", "x == x + 1")
        assert r.returncode == 0
        assert "always_false" in r.stdout
        assert "simplified=0" in r.stdout

    def test_always_false_constant_comparison(self):
        r = run_cli("--expr", "1 == 0")
        assert r.returncode == 0
        assert "always_false" in r.stdout

    def test_variable_predicate_unknown_exit_1(self):
        r = run_cli("--expr", "x > 5")
        assert r.returncode == 1
        assert "unknown" in r.stdout

    def test_non_bool_expression_unknown_exit_1(self):
        # x + y == 0 is satisfiable (x=y=0) and refutable -> variable.
        r = run_cli("--expr", "x + y")
        assert r.returncode == 1
        assert "unknown" in r.stdout

    def test_bv_expression_can_still_be_opaque(self):
        # x*x + 3 has no square-root solution mod 2^32 (a≡5 mod 8) — a real
        # bit-vector-level opaque predicate the 32-bit model must catch.
        r = run_cli("--expr", "x*x + 3")
        assert r.returncode == 0
        assert "always_true" in r.stdout

    def test_json_output_shape(self):
        r = run_cli("--expr", "x >= 0 || x < 0", "--json")
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["tool"] == "opaque-pred"
        assert payload["mode"] == "expr"
        assert payload["expr"] == "x >= 0 || x < 0"
        assert payload["width"] == 32
        assert payload["kind"] == "always_true"
        assert payload["simplified"] == 1
        assert payload["timeout_ms"] == 5000

    def test_reproduce_field_value_lines(self):
        r = run_cli("--expr", "x == x + 1", "--reproduce")
        assert r.returncode == 0
        rows = _parse_reproduce(r.stdout)
        assert rows["tool"] == "opaque-pred"
        assert rows["kind"] == "always_false"
        assert rows["simplified"] == "0"

    def test_width_64_still_identity(self):
        r = run_cli("--expr", "(x+1)*(x+1) == x*x+2*x+1", "--width", "64")
        assert r.returncode == 0
        assert "always_true" in r.stdout


# =====================================================================
# MBA simplification (expression pairs)
# =====================================================================

@requires_z3
class TestMbaSimplify:
    def test_even_product_masked_is_zero(self):
        # x*(x-1) is always even -> bit0 is always 0.
        r = run_cli("--simplify", "x*(x-1)&1 -> 0")
        assert r.returncode == 0
        assert "equivalent=yes" in r.stdout
        assert "rewrite=0" in r.stdout

    def test_mba_square_identity_equivalent(self):
        r = run_cli("--simplify", "(x+1)*(x+1) -> x*x+2*x+1")
        assert r.returncode == 0
        assert "equivalent=yes" in r.stdout

    def test_inequivalent_pair_exit_1(self):
        r = run_cli("--simplify", "x + y -> x * y")
        assert r.returncode == 1
        assert "equivalent=no" in r.stdout

    def test_simplify_json_shape(self):
        r = run_cli("--simplify", "x*(x-1)&1 -> 0", "--json")
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["mode"] == "simplify"
        assert payload["lhs"] == "x*(x-1)&1"
        assert payload["rhs"] == "0"
        assert payload["equivalent"] is True
        assert payload["rewrite"] == "0"

    def test_simplify_without_arrow_exit_2(self):
        r = run_cli("--simplify", "x + y")
        assert r.returncode == 2
        err = json.loads(r.stderr)
        assert "->" in err["error"]


# =====================================================================
# errors + z3-missing degrade
# =====================================================================

class TestErrors:
    def test_help_exit_zero(self):
        r = run_cli("--help")
        assert r.returncode == 0
        assert "--expr" in r.stdout
        assert "--simplify" in r.stdout

    def test_parse_error_exit_2(self):
        r = run_cli("--expr", "(x +")
        assert r.returncode == 2
        err = json.loads(r.stderr)
        assert err["exit_code"] == 2

    def test_no_mode_exit_2(self):
        r = run_cli()
        assert r.returncode == 2

    def test_z3_missing_exit_2_with_install_guidance(self, monkeypatch, capsys):
        monkeypatch.setattr(op, "z3", None)
        rc = op.main(["--expr", "x >= 0 || x < 0"])
        assert rc == 2
        err = json.loads(capsys.readouterr().err)
        assert "uv pip install z3-solver" in err["error"]

    def test_help_works_without_z3(self, monkeypatch, capsys):
        monkeypatch.setattr(op, "z3", None)
        with pytest.raises(SystemExit) as excinfo:
            op.main(["--help"])
        assert excinfo.value.code == 0
        assert "--expr" in capsys.readouterr().out

    def test_z3_import_is_guarded(self):
        # z3 is optional: module must import (and --help must work) without it.
        text = (STATIC / "opaque_pred.py").read_text(encoding="utf-8")
        assert "try:" in text
        assert "ImportError" in text
