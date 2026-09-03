# -*- coding: utf-8 -*-
"""tests/test_c_normalize.py — issue #306: tools/static/c_normalize.py contract.

Ghidra C normalizer: modulo-idiom recovery, dead-assignment removal, and
opt-in undefined4/8 type heuristics.  Covers the #277 CLI checklist
(parameterized --in/stdin, three-state exit codes, --json, --reproduce),
idempotence, conservative no-false-positive rewrites, and UTF-8 output.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "tools" / "static"
for sub in ("tools/static",):
    if str(ROOT / sub) not in sys.path:
        sys.path.insert(0, str(ROOT / sub))

import c_normalize as cn  # noqa: E402

# Matches scripts/kunglao_verify.py _ACTUAL_ASSERTION_RE (L1 field=value parser).
L1_LINE_RE = re.compile(r"^([A-Za-z_][\w.]*)\s*[:=]\s*(.+)$")


def run_cli(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(STATIC / "c_normalize.py"), *args],
        input=stdin, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )


def _parse_reproduce(stdout: str) -> dict:
    return dict(L1_LINE_RE.match(line).groups() for line in stdout.splitlines()
                if L1_LINE_RE.match(line))


GENERIC_C = (
    "void check(void)\n"
    "{\n"
    "  return;\n"
    "}\n"
)


# =====================================================================
# modulo idiom recovery
# =====================================================================

class TestModuloIdiom:
    # (src, expected) — exact-equality modulo-folding cases.
    MODULO_FOLD_CASES = [
        ("uVar1 = uVar1 - (uVar1 / 10) * 10;\n", "uVar1 = uVar1 % 10;\n"),
        ("x = x - (x / 0x1000) * 0x1000;\n", "x = x % 0x1000;\n"),
        ("y = y + (y / 3) * -3;\n", "y = y % 3;\n"),
        ("a=x-(x/7)*7;\n", "a=x % 7;\n"),
        ("v = buf[i] - (buf[i] / 4) * 4;\n", "v = buf[i] % 4;\n"),
    ]

    def test_modulo_idiom_folds_exactly(self):
        for src, expected in self.MODULO_FOLD_CASES:
            assert cn.normalize(src) == expected, src

    def test_cast_wrapped_whole_expression(self):
        # Ghidra emission for the cast-wrapped round-down idiom.
        src = "uVar1 = (int)(x - (x/0x1000)*0x1000);\n"
        out = cn.normalize(src)
        assert "x % 0x1000" in out
        assert "(int)" in out

    def test_cast_per_operand(self):
        src = "uVar1 = (uint)x - (uint)((x) / 0x1000) * 0x1000;\n"
        out = cn.normalize(src)
        assert "(uint)((x) % 0x1000)" in out

    def test_multiple_divisors_in_one_input(self):
        src = ("a = x - (x/16)*16;\n"
               "b = y - (y / 8) * 8;\n")
        out = cn.normalize(src)
        assert "x % 16" in out
        assert "y % 8" in out


class TestModuloNoFalsePositives:
    # (src, reason) — each must round-trip unchanged (no modulo folding).
    UNCHANGED_INPUTS = [
        ("z = x - (y/16)*16;\n", "different variables"),
        ("z = x - (x/16)*15;\n", "divisor/multiplier mismatch"),
        ("z = x - x/16*16;\n", "unparenthesized division"),
        ("z = f(x) - (f(x)/16)*16;\n", "function call (double-eval hazard)"),
        ("z = x - (x/16)*16 * y;\n", "multiplicative follow context"),
        ("z = ax - (x/16)*16;\n", "identifier prefix boundary (ax != x)"),
    ]

    def test_no_false_positive_folding(self):
        for src, reason in self.UNCHANGED_INPUTS:
            assert cn.normalize(src) == src, reason


# =====================================================================
# dead assignment removal
# =====================================================================

class TestDeadAssignment:
    def test_bare_self_assignment_line_removed(self):
        src = "uVar1 = uVar1;\n  uVar2 = 7;\n"
        assert cn.normalize(src) == "  uVar2 = 7;\n"

    def test_self_assignment_in_function_body(self):
        src = ("void f(void)\n{\n  uVar1 = uVar1;\n  return;\n}\n")
        out = cn.normalize(src)
        assert "uVar1 = uVar1;" not in out
        assert "void f(void)" in out

    def test_distinct_variables_kept(self):
        src = "uVar1 = uVar2;\n"
        assert cn.normalize(src) == src


# =====================================================================
# undefined4/8 heuristics (default OFF)
# =====================================================================

HEURISTIC_SRC = (
    "undefined4 f(undefined8 param_1)\n"
    "{\n"
    "  undefined4 i;\n"
    "  undefined4 acc;\n"
    "  undefined8 ptr;\n"
    "  for (i = 0; i < 10; i = i + 1) {\n"
    "    acc = 0;\n"
    "    acc += i;\n"
    "    ptr = DAT_00104020;\n"
    "    if (ptr == (undefined8 *)0x0) {\n"
    "      return 0;\n"
    "    }\n"
    "  }\n"
    "  return acc;\n"
    "}\n"
)


class TestHeuristicsDefaultOff:
    def test_undefined4_kept_without_flag(self):
        assert cn.normalize("undefined4 i;\ni = i + 1;\n") \
            == "undefined4 i;\ni = i + 1;\n"

    def test_heuristics_flag_enables_rule(self):
        out = cn.normalize(HEURISTIC_SRC, heuristics=True)
        assert "int i;" in out
        assert "int acc;" in out
        assert "long ptr;" in out
        assert "undefined4 i" not in out

    def test_heuristics_documented_default_off(self):
        # Default-off is a design decision: type guesses can mislead the LLM
        # worse than undefined4 (issue #306 design comment).  Pin the default.
        rule = next(r for r in cn.RULES if r.name == "undefined_types")
        assert rule.enabled is False


# =====================================================================
# idempotence + composition
# =====================================================================

class TestIdempotence:
    def test_normalize_is_idempotent(self):
        src = ("uVar1 = uVar1 - (uVar1 / 10) * 10;\n"
               "uVar2 = uVar2;\n")
        once = cn.normalize(src)
        twice = cn.normalize(once)
        assert once == twice

    def test_cli_output_is_idempotent(self, tmp_path):
        src = "uVar1 = uVar1 - (uVar1 / 10) * 10;\n"
        inp = tmp_path / "in.c"
        inp.write_text(src, encoding="utf-8")
        r1 = run_cli("--in", str(inp))
        assert r1.returncode == 0
        out = tmp_path / "out.c"
        out.write_text(r1.stdout, encoding="utf-8")
        r2 = run_cli("--in", str(out))
        assert r2.returncode == 1  # second pass: nothing left to transform
        assert r2.stdout == r1.stdout


# =====================================================================
# CLI contract (#277)
# =====================================================================

class TestCliContract:
    def test_help_exit_zero(self):
        r = run_cli("--help")
        assert r.returncode == 0
        assert "--heuristics" in r.stdout
        assert "--in" in r.stdout

    def test_exit_0_transformed_stdout_is_normalized_c(self, tmp_path):
        src = "uVar1 = uVar1 - (uVar1 / 10) * 10;\n"
        inp = tmp_path / "in.c"
        inp.write_text(src, encoding="utf-8")
        r = run_cli("--in", str(inp))
        assert r.returncode == 0
        assert "uVar1 % 10" in r.stdout

    def test_exit_1_nothing_to_transform(self, tmp_path):
        src = "return;\n"
        inp = tmp_path / "in.c"
        inp.write_text(src, encoding="utf-8")
        r = run_cli("--in", str(inp))
        assert r.returncode == 1
        assert r.stdout == src

    def test_exit_2_missing_file_with_guidance(self, tmp_path):
        r = run_cli("--in", str(tmp_path / "nope.c"))
        assert r.returncode == 2
        err = json.loads(r.stderr)
        assert err["exit_code"] == 2
        assert "check" in err["error"]

    def test_stdin_input_without_in_flag(self):
        r = run_cli(stdin="uVar1 = uVar1 - (uVar1 / 10) * 10;\n")
        assert r.returncode == 0
        assert "uVar1 % 10" in r.stdout

    def test_json_emit_on_changed(self, tmp_path):
        src = "uVar1 = uVar1 - (uVar1 / 10) * 10;\nuVar2 = uVar2;\n"
        inp = tmp_path / "in.c"
        inp.write_text(src, encoding="utf-8")
        r = run_cli("--in", str(inp), "--json")
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["tool"] == "c-normalize"
        assert payload["changed"] is True
        assert payload["rule_hits"]["modulo_idiom"] == 1
        assert payload["rule_hits"]["dead_assignment"] == 1
        assert payload["rule_hits"]["undefined_types"] == 0
        assert payload["diff"]["lines_added"] == 1
        assert payload["diff"]["lines_removed"] == 2
        assert len(payload["input_sha256"]) == 64
        assert len(payload["output_sha256"]) == 64

    def test_json_emit_on_unchanged_exit_1(self, tmp_path):
        inp = tmp_path / "in.c"
        inp.write_text("return;\n", encoding="utf-8")
        r = run_cli("--in", str(inp), "--json")
        assert r.returncode == 1
        payload = json.loads(r.stdout)
        assert payload["changed"] is False
        assert sum(payload["rule_hits"].values()) == 0

    def test_reproduce_field_value_lines(self, tmp_path):
        src = "uVar1 = uVar1 - (uVar1 / 10) * 10;\n"
        inp = tmp_path / "in.c"
        inp.write_text(src, encoding="utf-8")
        r = run_cli("--in", str(inp), "--reproduce")
        assert r.returncode == 0
        rows = _parse_reproduce(r.stdout)
        assert rows["tool"] == "c-normalize"
        assert rows["changed"] == "1"
        assert rows["hits.modulo_idiom"] == "1"
        assert "modulo_idiom" in rows["rules_enabled"]

    def test_utf8_roundtrip_with_non_ascii_comment(self, tmp_path):
        src = "// 中文注释保留\nuVar1 = uVar1 - (uVar1 / 10) * 10;\n"
        inp = tmp_path / "in.c"
        inp.write_text(src, encoding="utf-8")
        r = run_cli("--in", str(inp))
        assert r.returncode == 0
        assert "中文注释保留" in r.stdout
        assert "uVar1 % 10" in r.stdout

    def test_empty_input_exit_1(self, tmp_path):
        inp = tmp_path / "in.c"
        inp.write_text("", encoding="utf-8")
        r = run_cli("--in", str(inp))
        assert r.returncode == 1

    def test_rule_registry_is_declarative(self):
        # Rule-driven architecture: ordered, named, toggleable — main() only
        # iterates RULES; adding a rule must not touch main().
        names = [r.name for r in cn.RULES]
        assert names == ["modulo_idiom", "dead_assignment", "undefined_types"]
        assert all(r.description for r in cn.RULES)
        assert [r.enabled for r in cn.RULES] == [True, True, False]
