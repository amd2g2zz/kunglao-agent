# -*- coding: utf-8 -*-
"""TDD RED — tests for scripts/fixture_excerpt_lint.py (#58).

The a2b5e25c problem-1 root cause: a worker's CONDENSED Ghidra decompile
excerpt introduced an UNANNOTATED semantic conversion — `rc.averageBitRate =
bitrate*1000;` (kbps→bps) with no machine-code basis (zero imul/0x3E8 in the
function) and no `unit:` caliber note. The report copied the excerpt verbatim
and a customer audit found the mismatch.

This lint is the front-line EXCERPT-TEXT layer (regex only, no binary, no VA):
it flags (R1) numeric-literal scaling without a `unit:` annotation, and (R3)
unresolved-variable (`sVarN`) speculation without a `// resolved:` note. It is
COMPLEMENTARY to #50 (byte-exact, binary+VA required — disproves the multiply
at the VA) and #49 (fact expected-value binding). Different layer, not a
duplicate.

REGRESSION_FIXTURE is the issue #58 body's quoted nvenc excerpt verbatim —
SYNTHETIC test data (a public issue excerpt), not live user/malware data.
"""
import json


import fixture_excerpt_lint as fel


# ---------------------------------------------------------------------------
# Regression fixture — issue #58 body's quoted excerpt, verbatim.
# The two telltale `*1000` statements MUST stay intact for the R1 matches to
# be real:
#   `rc.averageBitRate = bitrate*1000;`
#   `rc.maxBitRate    = bitrate*1000;`
# ---------------------------------------------------------------------------

REGRESSION_FIXTURE = """\
init.frameRateNum = bitrate; init.frameRateDen = fps;
rc.averageBitRate = bitrate*1000; rc.maxBitRate = bitrate*1000; rc.gopLength = fps;
"""


# ---------------------------------------------------------------------------
# (a) Regression: the two *1000 statements are flagged (R1, high severity).
# ---------------------------------------------------------------------------

def test_regression_nvenc_asterisk1000_flagged():
    report = fel.lint(REGRESSION_FIXTURE)
    assert report["ok"] is False, report
    r1 = [v for v in report["violations"] if v["rule"] == "R1"]
    assert len(r1) == 2, [v["snippet"] for v in r1]
    # Both *1000 are known unit-scale (kbps→bps) → high severity, operand 1000.
    for v in r1:
        assert v["severity"] == "high", v
        assert "1000" in v["operand"], v
    # The two flagged statements are the averageBitRate / maxBitRate lines.
    snippets = " ".join(v["snippet"] for v in r1)
    assert "averageBitRate" in snippets
    assert "maxBitRate" in snippets
    # No R3 violations (no unresolved LHS in this excerpt).
    assert not [v for v in report["violations"] if v["rule"] == "R3"]
    # The non-scaling statements (frameRateNum=bitrate, Den=fps, gopLength=fps)
    # are NOT flagged.
    assert report["violation_count"] == 2, report
    # checks = assignment statements scanned (5 in this excerpt).
    assert report["checks"] == 5, report


# ---------------------------------------------------------------------------
# (b) The same *1000 statements WITH a `// unit:` annotation are NOT flagged.
# ---------------------------------------------------------------------------

def test_regression_unit_annotation_exempts():
    excerpt = (
        "init.frameRateNum = bitrate; init.frameRateDen = fps;\n"
        "rc.averageBitRate = bitrate*1000; rc.maxBitRate = bitrate*1000; "
        "rc.gopLength = fps; // unit: bps (kbps*1000)\n"
    )
    report = fel.lint(excerpt)
    assert report["ok"] is True, report
    assert report["violation_count"] == 0, report


# ---------------------------------------------------------------------------
# (c) Unresolved-variable speculation (R3).
# ---------------------------------------------------------------------------

def test_sVar_speculation_flagged():
    report = fel.lint("sVar1 = bitrate;\n")
    assert report["ok"] is False, report
    r3 = [v for v in report["violations"] if v["rule"] == "R3"]
    assert len(r3) == 1, r3
    v = r3[0]
    assert v["severity"] == "normal"
    assert v["operand"] is None
    assert v["line_no"] == 1


def test_sVar_resolved_annotation_exempts():
    excerpt = "sVar1 = bitrate; // resolved: reg-tracked from EBX at 0x401234\n"
    report = fel.lint(excerpt)
    assert report["ok"] is True, report
    assert report["violation_count"] == 0, report


def test_sVar_faithful_copy_and_cast_not_flagged():
    excerpt = "sVar1 = sVar2;\nsVar3 = (long)sVar4;\n"
    report = fel.lint(excerpt)
    assert report["ok"] is True, report
    assert report["violation_count"] == 0, report


def test_sVar_arithmetic_on_temps_not_flagged():
    excerpt = "sVar1 = sVar2 + sVar3;\n"
    report = fel.lint(excerpt)
    assert report["violation_count"] == 0, report


# R3-speculation sources: Ghidra generic temps assigned from a field /
# concrete literal / generic register name are all speculation.
R3_SPECULATION_CASES = [
    "sVar1 = param_1->count;\n",
    "sVar1 = 0x100;\n",
    "unaff_EAX = bitrate;\n",
]


def test_sVar_speculation_sources_flagged():
    for excerpt in R3_SPECULATION_CASES:
        report = fel.lint(excerpt)
        r3 = [v for v in report["violations"] if v["rule"] == "R3"]
        assert len(r3) == 1, f"expected exactly 1 R3 for {excerpt!r}: {r3}"


# ---------------------------------------------------------------------------
# (d) Clean faithful excerpt → 0 violations (precision guard).
# ---------------------------------------------------------------------------

def test_clean_faithful_excerpt_zero():
    excerpt = (
        "init.frameRateNum = fps;\n"
        "init.frameRateDen = 1;\n"
        "rc.gopLength = 0xFFFFFFFF;\n"
    )
    report = fel.lint(excerpt)
    assert report["ok"] is True, report
    assert report["violation_count"] == 0, report


# ---------------------------------------------------------------------------
# (e) Variable-only arithmetic (no numeric operand) is NOT flagged.
# ---------------------------------------------------------------------------

def test_variable_multiply_not_flagged():
    report = fel.lint("x = a * b;\n")
    assert report["ok"] is True, report
    assert report["violation_count"] == 0, report


# ---------------------------------------------------------------------------
# R1 severity discrimination + division/shift coverage.
# ---------------------------------------------------------------------------

def test_known_unit_scale_vs_other_severity():
    excerpt = "a = n * 1000;\nb = m * 4;\n"
    report = fel.lint(excerpt)
    assert report["ok"] is False
    r1 = {v["snippet"]: v for v in report["violations"] if v["rule"] == "R1"}
    high = [v for v in r1.values() if v["severity"] == "high"]
    normal = [v for v in r1.values() if v["severity"] == "normal"]
    assert len(high) == 1 and "1000" in high[0]["operand"]
    assert len(normal) == 1 and "4" in normal[0]["operand"]


def test_division_and_shift_flagged():
    excerpt = "a = total / 1024;\nb = addr << 12;\n"
    report = fel.lint(excerpt)
    r1 = [v for v in report["violations"] if v["rule"] == "R1"]
    assert len(r1) == 2, [v["snippet"] for v in r1]
    # 1024 is a known unit scale (KiB); 12 is not.
    sev = sorted(v["severity"] for v in r1)
    assert sev == ["high", "normal"], sev


# ---------------------------------------------------------------------------
# `unit:` exemption — block-scoped declaration form + scope boundary.
# ---------------------------------------------------------------------------

def test_block_scoped_unit_declaration_exempts():
    excerpt = (
        "// unit: all rates in bps\n"
        "rc.averageBitRate = bitrate*1000;\n"
    )
    report = fel.lint(excerpt)
    assert report["ok"] is True, report
    assert report["violation_count"] == 0, report


def test_block_scope_resets_on_blank_line():
    # The blank line ends the block → the declaration no longer covers the
    # assignment, so the *1000 IS flagged.
    excerpt = (
        "// unit: all rates in bps\n"
        "\n"
        "rc.averageBitRate = bitrate*1000;\n"
    )
    report = fel.lint(excerpt)
    r1 = [v for v in report["violations"] if v["rule"] == "R1"]
    assert len(r1) == 1, report


# ---------------------------------------------------------------------------
# (f) Module docstring cross-references #50 and #49 (Acceptance).
# ---------------------------------------------------------------------------

def test_module_docstring_cross_references_50_49():
    doc = fel.__doc__ or ""
    assert "#50" in doc, "module docstring must cross-reference #50 (byte-exact)"
    assert "#49" in doc, "module docstring must cross-reference #49 (expected-value)"


# ---------------------------------------------------------------------------
# (g) CLI — exit codes + JSON report.
# ---------------------------------------------------------------------------

def test_cli_clean_excerpt_exits_0(tmp_path, capsys):
    f = tmp_path / "clean.c"
    f.write_text("init.frameRateNum = fps;\n", encoding="utf-8")
    rc = fel.main([str(f)])
    out = capsys.readouterr().out
    assert rc == 0
    report = json.loads(out)
    assert report["ok"] is True
    assert report["violation_count"] == 0


def test_cli_violating_excerpt_exits_1(tmp_path, capsys):
    f = tmp_path / "nvenc.c"
    f.write_text(REGRESSION_FIXTURE, encoding="utf-8")
    rc = fel.main([str(f)])
    out = capsys.readouterr().out
    assert rc == 1
    report = json.loads(out)
    assert report["ok"] is False
    assert any(v["rule"] == "R1" for v in report["violations"])


def test_cli_missing_file_exits_2(capsys):
    rc = fel.main(["/no/such/path_fixture_excerpt_xyz.c"])
    err = capsys.readouterr().err
    assert rc == 2
    assert err.strip()  # a clear error message on stderr
