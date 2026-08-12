"""RED tests for fact-expected-value-binding (GitHub #49, a2b5e25c incident).

Pins three contract additions to kunglao_verify.py:
- assignment-class expected MUST bind concrete value assertions
- assignment-class without value assertions MUST be lint-rejected (blocks promotion)
- byte-exact compare SHALL target value assertions individually (not whole-blob sha256)

Driven by a2b5e25c: F015 (NVENC init) passed L1 with an API-sequence-only
expected even though field assignments were all-reversed. The old verifier
reduced expected to a single sha256 of prose, hiding the per-field mismatch.

RED phase: is_assignment_class / parse_value_assertions / check_assignment_expected
/ compare_value_assertions do not exist yet, so every test below fails.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import kunglao_verify as kv  # noqa: E402


def _repro(lines):
    """Build a reproduce command printing each field=value on its own line.

    chr(39) is the single quote, kept out of source so this file stays
    heredoc-safe; reproduce becomes print(fv); print(fv); ... which python -c
    runs as one statement per line.
    """
    q = chr(39)
    return "; ".join("print(" + q + ln + q + ")" for ln in lines)


# ---------- D4 classifier: is_assignment_class ----------

def test_class_detects_field_equals_concrete():
    assert kv.is_assignment_class("frameRateNum=fps; gopLength=0xFFFFFFFF") is True


def test_class_detects_placeholder_equals():
    # the a2b5e25c F015 bug shape: field=?? placeholders still carry assignment-class
    assert kv.is_assignment_class("frameRateNum=??; gopLength=??") is True


def test_class_rejects_equality_operator():
    # ==, !=, >=, <= are comparisons, not assignments
    assert kv.is_assignment_class("if x == 0: return") is False
    assert kv.is_assignment_class("a >= b or c <= d") is False
    assert kv.is_assignment_class("x != y") is False


def test_class_pure_api_sequence_not_flagged():
    # RED3: pure API call sequence / hex literal, no assignment -> NOT assignment-class
    assert kv.is_assignment_class("calls NV_ENC_INITIALIZE_ENCODER(codec, width, height)") is False
    assert kv.is_assignment_class("0x5a4d") is False
    assert kv.is_assignment_class("0xdeadbeef") is False


# ---------- parser: parse_value_assertions ----------

def test_parse_extracts_concrete_bindings():
    d = dict(kv.parse_value_assertions("frameRateNum=fps; frameRateDen=1; gopLength=0xFFFFFFFF"))
    assert d == {"frameRateNum": "fps", "frameRateDen": "1", "gopLength": "0xFFFFFFFF"}


def test_parse_skips_placeholders_and_empty():
    # ?? / TBD / empty RHS are not concrete value bindings
    assert kv.parse_value_assertions("frameRateNum=??; gopLength=") == []
    assert kv.parse_value_assertions("frameRateNum=TBD") == []


def test_parse_handles_newline_and_comma_separators():
    raw = "frameRateDen=1\naverageBitRate=bitrate, maxBitRate=bitrate"
    d = dict(kv.parse_value_assertions(raw))
    assert d == {"frameRateDen": "1", "averageBitRate": "bitrate", "maxBitRate": "bitrate"}


# ---------- lint gate: check_assignment_expected (D1, D3) ----------

def test_gate_rejects_class_without_assertions():
    # RED1: assignment-class (has =) but only placeholders -> reject
    ok, reason = kv.check_assignment_expected({"expected": "frameRateNum=??; frameRateDen=??; gopLength=??"})
    assert ok is False
    assert "assertion" in reason.lower()


def test_gate_accepts_class_with_assertions():
    # RED2 precondition: assignment-class WITH concrete bindings -> ok
    ok, _ = kv.check_assignment_expected({"expected": "frameRateNum=fps; frameRateDen=1; gopLength=0xFFFFFFFF"})
    assert ok is True


def test_gate_passes_non_class_unchanged():
    # RED3: pure API sequence -> not assignment-class -> ok, skip
    ok, reason = kv.check_assignment_expected({"expected": "calls Foo(a, b, c)"})
    assert ok is True
    assert "not assignment" in reason.lower()


def test_gate_grace_warns_does_not_reject():
    ok, reason = kv.check_assignment_expected({"expected": "frameRateNum=??"}, grace=True)
    assert ok is True
    assert ("grace" in reason.lower()) or ("warn" in reason.lower())


# ---------- byte-exact compare: compare_value_assertions (D2) ----------

def test_compare_all_match_passes():
    actual = b"frameRateNum=30\nframeRateDen=1\ngopLength=0xFFFFFFFF\n"
    ok, mismatches = kv.compare_value_assertions(
        [("frameRateNum", "30"), ("frameRateDen", "1"), ("gopLength", "0xFFFFFFFF")], actual)
    assert ok is True
    assert mismatches == []


def test_compare_one_wrong_reports_field_name():
    # a2b5e25c shape: four right, one wrong (gopLength)
    actual = b"frameRateNum=30\nframeRateDen=1\naverageBitRate=8000000\nmaxBitRate=8000000\ngopLength=0\n"
    ok, mismatches = kv.compare_value_assertions(
        [("frameRateNum", "30"), ("frameRateDen", "1"), ("averageBitRate", "8000000"),
         ("maxBitRate", "8000000"), ("gopLength", "0xFFFFFFFF")], actual)
    assert ok is False
    assert [m[0] for m in mismatches] == ["gopLength"]
    gop = mismatches[0]
    assert "0xFFFFFFFF" in gop[1]
    assert "0" in gop[2]


def test_compare_normalizes_hex_and_decimal():
    # 0xFFFFFFFF == 4294967295
    ok, _ = kv.compare_value_assertions([("gopLength", "0xFFFFFFFF")], b"gopLength=4294967295\n")
    assert ok is True


def test_compare_symbolic_value_string_match():
    # symbolic source (fps) matches the same symbolic in actual (static-fact style)
    ok, _ = kv.compare_value_assertions([("frameRateNum", "fps")], b"frameRateNum=fps\n")
    assert ok is True


# ---------- l1_mechanical routing ----------

def test_l1_routes_assignment_class_to_value_compare():
    fact = {"reproduce": _repro(["gopLength=0xFFFFFFFF"]), "expected": "gopLength=0xFFFFFFFF"}
    out = kv.l1_mechanical(fact)
    assert out["verdict"] == "PASS"
    assert "assertion" in out["detail"].lower()


def test_l1_assignment_class_mismatch_fails_with_field():
    fact = {"reproduce": _repro(["gopLength=0"]), "expected": "gopLength=0xFFFFFFFF"}
    out = kv.l1_mechanical(fact)
    assert out["verdict"] == "FAIL"
    assert "gopLength" in out["detail"]


def test_l1_non_assignment_class_keeps_sha256_path():
    # RED3 integration: non-class expected -> existing sha256 path unchanged
    fact = {"reproduce": "print(hex(0x5A4D))", "expected": "0x5a4d"}
    out = kv.l1_mechanical(fact)
    assert out["verdict"] == "PASS"
    assert "sha256" in out["detail"].lower()


def test_l1_output_keeps_schema_keys_for_assignment_class():
    # verify-output schema requires l1.{verdict, actual_sha256, cmd}
    fact = {"reproduce": _repro(["gopLength=0xFFFFFFFF"]), "expected": "gopLength=0xFFFFFFFF"}
    out = kv.l1_mechanical(fact)
    assert out["verdict"] in ("PASS", "FAIL")
    assert len(out["actual_sha256"]) == 64
    assert out["cmd"]


# ---------- a2b5e25c F015 regression (task 2.4) ----------

F015_ORIG_EXPECTED = (
    "nvenc_create_d3d11_encoder calls NV_ENC_INITIALIZE_ENCODER; "
    "frameRateNum=??; frameRateDen=??; averageBitRate=??; maxBitRate=??; gopLength=??"
)
F015_BACKFILLED_EXPECTED = (
    "frameRateNum=fps; frameRateDen=1; "
    "averageBitRate=bitrate; maxBitRate=bitrate; gopLength=0xFFFFFFFF"
)
_F015_CORRECT_LINES = [
    "frameRateNum=fps", "frameRateDen=1",
    "averageBitRate=bitrate", "maxBitRate=bitrate", "gopLength=0xFFFFFFFF",
]
_F015_BUGGY_LINES = [
    "frameRateNum=fps", "frameRateDen=1",
    "averageBitRate=bitrate", "maxBitRate=bitrate", "gopLength=0",
]


def test_f015_original_rejected_by_lint_gate():
    ok, reason = kv.check_assignment_expected({"expected": F015_ORIG_EXPECTED})
    assert ok is False, f"F015 original (a2b5e25c bug) must be rejected: {reason}"


def test_f015_backfilled_passes_byte_exact():
    fact = {"reproduce": _repro(_F015_CORRECT_LINES), "expected": F015_BACKFILLED_EXPECTED}
    out = kv.l1_mechanical(fact)
    assert out["verdict"] == "PASS", f"backfilled F015 should PASS byte-exact: {out}"


def test_f015_backfilled_detects_reversed_assignment():
    # a2b5e25c root cause: gopLength observed 0 while expected 0xFFFFFFFF
    fact = {"reproduce": _repro(_F015_BUGGY_LINES), "expected": F015_BACKFILLED_EXPECTED}
    out = kv.l1_mechanical(fact)
    assert out["verdict"] == "FAIL"
    assert "gopLength" in out["detail"]


# ---------- CLI --grace-scan (task 7.2) ----------

def test_grace_scan_lists_assignment_class_without_assertions(tmp_path):
    """--grace-scan enumerates assignment-class facts lacking value assertions."""
    import json as _json
    import subprocess
    facts = tmp_path / "facts"
    facts.mkdir()
    # bad: assignment-class (has =) but only ?? placeholders
    (facts / "F-bad.md").write_text(
        "---\nid: F-bad\nstatus: PROVEN\nexpected: frameRateNum=??; gopLength=??\n---\n",
        encoding="utf-8")
    # good: non-assignment-class (no =) -> not flagged
    (facts / "F-good.md").write_text(
        "---\nid: F-good\nstatus: PROVEN\nexpected: calls Foo(a, b)\n---\n",
        encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "kunglao-verify.py"), str(tmp_path), "--grace-scan"],
        capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, f"--grace-scan failed: {r.stderr}"
    affected = _json.loads(r.stdout)
    assert [e["fact_id"] for e in affected] == ["F-bad"], f"should list only F-bad: {affected}"


def test_grace_scan_empty_when_all_backfilled(tmp_path):
    """--grace-scan returns [] when every assignment-class fact has assertions."""
    import json as _json
    import subprocess
    facts = tmp_path / "facts"
    facts.mkdir()
    (facts / "F-ok.md").write_text(
        "---\nid: F-ok\nstatus: PROVEN\nexpected: gopLength=0xFFFFFFFF\n---\n",
        encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "kunglao-verify.py"), str(tmp_path), "--grace-scan"],
        capture_output=True, text=True, timeout=30)
    assert r.returncode == 0
    assert _json.loads(r.stdout) == []
