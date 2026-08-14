# -*- coding: utf-8 -*-
"""RED tests for issue #332 — executable oracle contract (可执行预言机契约).

Pins the contract additions to the kunglao-agent repo:
- Every verification record (kunglao-redteam output) must carry at least one
  `machine_check: {command, expected, actual, passed}` — the check must
  terminate in a byte/execution-level comparison, not "I read the source".
- Schema validation: a record missing machine_check, or carrying passed=false,
  MUST fail validation (STAMP must not promote to PROVEN).
- Exception path: `machine_check: none` + reason is accepted ONLY when the
  declared claim_kind is in the mapping table's exception-allowed list AND
  matches the fact's boundary_type (pure-CTI-class claims).
- Mapping table (references/machine_check_map.yaml) is the single source of
  truth; references/machine-check-contract.md mirrors it and a parity test
  keeps them in sync (maker-checker: 机械门禁优先).
- verify() gates the L2 CONFIRMED path: machine_check contract failure
  downgrades overall to PARTIAL (no promotion).

Driven by 2026-08-14 CrackMeBench research (#330): agent over-trust of
decompiler output — independent agent + maker can share the same static
analysis blind spot and the conclusion comparison passes everything.

RED phase: none of the pinned functions exist yet (load_machine_check_map /
parse_machine_checks / validate_machine_check_entry /
check_machine_check_contract / machine_check_gate / machine_check_map_coverage
/ verify() gating), so every code test below fails; the doc pins fail until
agents/kunglao-redteam.md, references/schema.md and
references/machine-check-contract.md are updated.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import kunglao_verify as kv  # noqa: E402


# ---------- record builders (canonical #332 record shapes) ----------

def _check(command: str = "xxd -p -s 0x0 -l 2 bins/sample",
           expected: str = "4d5a", actual: str = "4d5a",
           passed: bool = True) -> dict:
    return {"command": command, "expected": expected, "actual": actual, "passed": passed}


def _none(reason: str = "pure CTI correlation — no sample bytes to check",
          claim_kind: str = "cti_correlation") -> dict:
    return {"machine_check": "none", "reason": reason, "claim_kind": claim_kind}


def _record(*entries) -> str:
    """A runs/verify-redteam-*.md record body with a machine_check fence."""
    return ("# Red-team verification: claim\n"
            "## My independent derivation\n"
            "derived from raw bytes\n"
            "## RED-TEAM VERDICT: CONFIRMED\n"
            "## MACHINE-CHECK (oracle contract #332)\n"
            "```machine_check\n"
            + json.dumps(list(entries), indent=2) +
            "\n```\n")


# ---------- parse_machine_checks ----------

def test_parse_extracts_fenced_machine_check_block():
    """The canonical ```machine_check fence yields the entry dicts."""
    entries = kv.parse_machine_checks(_record(_check()))
    assert len(entries) == 1
    assert entries[0] == _check()


def test_parse_handles_multiple_entries_and_blocks():
    """Multiple entries across multiple fenced blocks all parse."""
    text = _record(_check(expected="4d5a")) + "\n```machine_check\n"
    text += json.dumps(_check(expected="50450000")) + "\n```\n"
    entries = kv.parse_machine_checks(text)
    assert [e["expected"] for e in entries] == ["4d5a", "50450000"]


def test_parse_supports_inline_machine_check_prefix_line():
    """The issue's literal form `machine_check: {command, ...}` also parses."""
    text = "## MACHINE-CHECK\nmachine_check: " + json.dumps(_check()) + "\n"
    entries = kv.parse_machine_checks(text)
    assert entries == [_check()]


def test_parse_tolerates_trailing_comma_and_comments():
    """LLM-shaped JSON (trailing commas, // comments) must not break parsing."""
    text = ("```machine_check\n"
            "[\n"
            "  {\"command\": \"xxd -p -s 0x0 -l 2 bins/sample\", // header\n"
            "   \"expected\": \"4d5a\", \"actual\": \"4d5a\", \"passed\": true,}\n"
            "]\n"
            "```\n")
    entries = kv.parse_machine_checks(text)
    assert entries and entries[0]["passed"] is True


def test_parse_returns_empty_for_record_without_block():
    """No machine_check block → no entries."""
    assert kv.parse_machine_checks("# just a report\nVERDICT: CONFIRMED\n") == []


def test_parse_returns_empty_for_empty_text():
    assert kv.parse_machine_checks("") == []
    assert kv.parse_machine_checks(None) == []


# ---------- validate_machine_check_entry ----------

def test_entry_requires_all_four_fields():
    """command/expected/actual/passed are all mandatory."""
    for missing in ("command", "expected", "actual", "passed"):
        entry = _check()
        del entry[missing]
        ok, reason = kv.validate_machine_check_entry(entry)
        assert ok is False, f"missing {missing} must fail"
        assert missing in reason


def test_entry_passed_must_be_strict_boolean():
    """passed: 'true' (string) is not a machine verdict — reject."""
    ok, reason = kv.validate_machine_check_entry(
        {"command": "xxd -p -s 0x0 -l 2 b", "expected": "4d5a",
         "actual": "4d5a", "passed": "true"})
    assert ok is False
    assert "boolean" in reason.lower()


def test_entry_fields_must_be_nonempty():
    ok, _ = kv.validate_machine_check_entry(_check(command="   "))
    assert ok is False


def test_entry_command_must_be_machine_executable():
    """"I read the source" is NOT a machine check — reject prose commands."""
    ok, reason = kv.validate_machine_check_entry(
        _check(command="I read the decompiled source and the constant looks right"))
    assert ok is False
    assert "byte/execution-level" in reason

    for cmd in ("xxd -p -s 0x0 -l 2 bins/sample",
                "python -c \"print(open('bins/sample','rb').read(2).hex())\"",
                "sha256sum bins/sample",
                "vmr-shell exec sample.exe --trace",
                "disasm_constant_check.py --fact F-001 --binary bins/sample",
                "grep -c 'hid.dll' bins/sample"):
        ok, reason = kv.validate_machine_check_entry(_check(command=cmd))
        assert ok is True, f"machine command {cmd!r} must validate: {reason}"


def test_entry_with_expected_actual_mismatch_and_passed_false_is_structurally_valid():
    """A failed check is structurally valid — the CONTRACT rejects it, not the entry."""
    ok, _ = kv.validate_machine_check_entry(
        _check(expected="4d5a", actual="dead", passed=False))
    assert ok is True


# ---------- check_machine_check_contract (schema validation) ----------

def test_contract_passes_with_one_passing_machine_check():
    ok, reason = kv.check_machine_check_contract(_record(_check()))
    assert ok is True, reason


def test_contract_fails_when_record_has_no_machine_check():
    ok, reason = kv.check_machine_check_contract(
        "# report\nRED-TEAM VERDICT: CONFIRMED\nI re-derived it and agree.\n")
    assert ok is False
    assert "machine_check" in reason


def test_contract_fails_when_all_checks_passed_false():
    ok, reason = kv.check_machine_check_contract(
        _record(_check(expected="4d5a", actual="dead", passed=False)))
    assert ok is False
    assert "passed=false" in reason


def test_contract_fails_when_any_check_passed_false():
    """Fail-closed: one failed machine check taints the record (no promotion)."""
    ok, reason = kv.check_machine_check_contract(
        _record(_check(), _check(expected="4d5a", actual="dead", passed=False)))
    assert ok is False
    assert "passed=false" in reason


def test_contract_fails_on_structurally_invalid_entry():
    bad = _check()
    del bad["actual"]
    ok, reason = kv.check_machine_check_contract(_record(bad))
    assert ok is False
    assert "actual" in reason


def test_contract_passes_exception_none_for_allowed_kind():
    """machine_check: none + reason + allowed claim_kind (pure CTI) → accepted."""
    ok, reason = kv.check_machine_check_contract(_record(_none()))
    assert ok is True, reason
    assert "exception" in reason.lower() or "none" in reason.lower()


def test_contract_fails_exception_for_non_exception_kind():
    """static_constant is NOT in the exception-allowed list → machine check required."""
    ok, reason = kv.check_machine_check_contract(
        _record(_none(claim_kind="static_constant")))
    assert ok is False
    assert "exception" in reason.lower()


def test_contract_fails_exception_for_unknown_kind():
    ok, reason = kv.check_machine_check_contract(
        _record(_none(claim_kind="whatever")))
    assert ok is False
    assert "whatever" in reason


def test_contract_fails_exception_without_reason():
    ok, reason = kv.check_machine_check_contract(
        _record({"machine_check": "none", "claim_kind": "cti_correlation"}))
    assert ok is False
    assert "reason" in reason


def test_contract_fails_exception_without_claim_kind():
    ok, reason = kv.check_machine_check_contract(
        _record({"machine_check": "none", "reason": "no bytes"}))
    assert ok is False
    assert "claim_kind" in reason


def test_contract_fails_exception_when_fact_kinds_empty():
    """claim_kinds=[] (unknown boundary_type) → exceptions disabled (fail closed)."""
    ok, reason = kv.check_machine_check_contract(_record(_none()), claim_kinds=[])
    assert ok is False


def test_contract_fails_exception_for_kind_outside_fact_kinds():
    """Kind is exception-allowed globally but not for this fact's boundary_type."""
    ok, reason = kv.check_machine_check_contract(
        _record(_none()), claim_kinds=["static_constant", "numeric"])
    assert ok is False
    assert "cti_correlation" in reason


def test_contract_fails_closed_when_map_missing():
    """No mapping table → no exceptions allowed, machine checks still validate."""
    ok, reason = kv.check_machine_check_contract(_record(_none()), mc_map={})
    assert ok is False
    ok2, _ = kv.check_machine_check_contract(_record(_check()), mc_map={})
    assert ok2 is True


# ---------- mapping table ----------

def test_map_covers_all_boundary_types():
    """boundary_type_map must cover the 9 schema boundary_types + positive_observation."""
    mp = kv.load_machine_check_map()
    btm = mp.get("boundary_type_map") or {}
    schema_types = {"confirmed", "capability_not_executed", "link_not_closed",
                    "source_derived", "numeric", "observation", "coordinate",
                    "pure_negative", "contradiction", "positive_observation"}
    missing = schema_types - set(btm)
    assert not missing, f"mapping table missing boundary types: {missing}"


def test_map_has_issue_mandated_rows():
    """The five rows mandated by #332 plus the pure-CTI exception row."""
    mp = kv.load_machine_check_map()
    kinds = mp.get("claim_kinds") or {}
    mandated = {
        "static_constant": "disasm_constant_check",
        "decryption_key": "decrypt_compare",
        "input_bypass": "vm_execution",
        "numeric": "byte_recalc",
        "string": "byte_offset_locate",
    }
    for kind, check_type in mandated.items():
        assert kind in kinds, f"mapping table missing mandated kind {kind}"
        assert kinds[kind]["check_type"] == check_type, \
            f"{kind} must map to {check_type}"
    assert kinds.get("cti_correlation", {}).get("exception_allowed") is True, \
        "pure-CTI class must be exception-allowed"


def test_map_coverage_stat_for_current_workspace_types():
    """Coverage stat over current workspace fact types is ≥80% (acceptance)."""
    seen = ["observation", "pure_negative", "positive_observation"]
    covered, total, pct = kv.machine_check_map_coverage(seen)
    assert total == 3
    assert pct >= 80.0, f"mapping coverage {covered}/{total} = {pct}% < 80%"


def test_map_parity_with_contract_doc():
    """references/machine-check-contract.md table must mirror the YAML map (no drift)."""
    doc = (ROOT / "references" / "machine-check-contract.md")
    assert doc.exists(), "references/machine-check-contract.md must exist"
    rows: dict[str, tuple[str, bool]] = {}
    for line in doc.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\|\s*([a-z_]+)\s*\|\s*([a-z_]+)\s*\|\s*(yes|no)\s*\|",
                     line.strip())
        if m:
            rows[m.group(1)] = (m.group(2), m.group(3) == "yes")
    assert rows, "contract doc must contain the mapping table"
    mp = kv.load_machine_check_map()
    kinds = mp.get("claim_kinds") or {}
    assert set(rows) == set(kinds), "doc table kinds must equal YAML claim_kinds"
    for kind, (check_type, exception) in rows.items():
        assert kinds[kind]["check_type"] == check_type, kind
        assert kinds[kind]["exception_allowed"] == exception, kind


# ---------- verify() integration: L2 CONFIRMED is gated by the oracle ----------

ANCHORS = [{"byte_offset": "0x0", "cmd": "xxd -p -s 0x0 -l 2 bins/sample",
            "expected": "4d5a"}]


def _fake_fact(ws: Path, *, boundary_type: str = "subjective_interpretation",
               needs_semantic_flag: str = "") -> dict:
    facts = ws / "facts"
    facts.mkdir(parents=True, exist_ok=True)
    f = facts / "F-940.md"
    f.write_text("---\nid: F-940\nclaim: C-940\n---\n", encoding="utf-8")
    return {"id": "F-940", "claim_id": "C-940", "_path": str(f),
            "reproduce": "print('0x5a4d')", "expected": "0x5a4d",
            "boundary_type": boundary_type,
            "needs_semantic": needs_semantic_flag, "anchors": ANCHORS}


def _confirmed_dispatcher():
    def _disp(claim_id, ws):
        return ("CONFIRMED", [])
    return _disp


def _write_redteam_record(ws: Path, body: str) -> Path:
    runs = ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    p = runs / "verify-redteam-C-940.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_verify_confirmed_with_passing_machine_check_is_verified(tmp_path, monkeypatch):
    """CONFIRMED + record with a passing machine_check → VERIFIED."""
    fact = _fake_fact(tmp_path)
    monkeypatch.setattr(kv, "load_fact", lambda ws, fid: fact)
    _write_redteam_record(tmp_path, _record(_check()))
    out = kv.verify(tmp_path, "F-940", l2_dispatcher=_confirmed_dispatcher())
    assert out["overall"] == "VERIFIED", out
    assert out["machine_check"]["ok"] is True


def test_verify_confirmed_record_missing_machine_check_downgrades(tmp_path, monkeypatch):
    """Record without machine_check → PARTIAL, no promotion (STAMP not PROVEN)."""
    fact = _fake_fact(tmp_path)
    monkeypatch.setattr(kv, "load_fact", lambda ws, fid: fact)
    _write_redteam_record(tmp_path, "# verdict\nRED-TEAM VERDICT: CONFIRMED\n")
    out = kv.verify(tmp_path, "F-940", l2_dispatcher=_confirmed_dispatcher())
    assert out["overall"] == "PARTIAL", f"oracle contract must block: {out}"
    assert out["machine_check"]["ok"] is False
    assert any(w["code"] == "MACHINE_CHECK_FAILED" for w in out["warnings"])


def test_verify_confirmed_record_passed_false_downgrades(tmp_path, monkeypatch):
    """Record whose machine check failed → PARTIAL."""
    fact = _fake_fact(tmp_path)
    monkeypatch.setattr(kv, "load_fact", lambda ws, fid: fact)
    _write_redteam_record(
        tmp_path, _record(_check(expected="4d5a", actual="dead", passed=False)))
    out = kv.verify(tmp_path, "F-940", l2_dispatcher=_confirmed_dispatcher())
    assert out["overall"] == "PARTIAL", out
    assert "machine_check" in " ".join(out["l2"]["gaps"]).lower()


def test_verify_confirmed_without_any_record_downgrades(tmp_path, monkeypatch):
    """CONFIRMED with no redteam record on disk → machine check unproven → PARTIAL."""
    fact = _fake_fact(tmp_path)
    monkeypatch.setattr(kv, "load_fact", lambda ws, fid: fact)
    out = kv.verify(tmp_path, "F-940", l2_dispatcher=_confirmed_dispatcher())
    assert out["overall"] == "PARTIAL", out
    assert out["machine_check"]["ok"] is False
    assert "no redteam verification record" in out["machine_check"]["reason"]


def test_verify_exception_path_for_source_derived_verified(tmp_path, monkeypatch):
    """source_derived fact + allowed machine_check:none exception → VERIFIED."""
    fact = _fake_fact(tmp_path, boundary_type="source_derived",
                      needs_semantic_flag="true")
    monkeypatch.setattr(kv, "load_fact", lambda ws, fid: fact)
    _write_redteam_record(tmp_path, _record(_none()))
    out = kv.verify(tmp_path, "F-940", l2_dispatcher=_confirmed_dispatcher())
    assert out["overall"] == "VERIFIED", out
    assert out["machine_check"]["ok"] is True, "gate result must be recorded"


def test_verify_exception_rejected_for_observation_fact(tmp_path, monkeypatch):
    """observation fact trying the none-exception → PARTIAL (kind not eligible)."""
    fact = _fake_fact(tmp_path, boundary_type="observation",
                      needs_semantic_flag="true")
    monkeypatch.setattr(kv, "load_fact", lambda ws, fid: fact)
    _write_redteam_record(tmp_path, _record(_none()))
    out = kv.verify(tmp_path, "F-940", l2_dispatcher=_confirmed_dispatcher())
    assert out["overall"] == "PARTIAL", out


def test_verify_non_semantic_fact_untouched(tmp_path):
    """L1-only facts keep the old path — no machine_check gate, no key."""
    facts = tmp_path / "facts"
    facts.mkdir()
    (facts / "F-941.md").write_text(
        "---\nid: F-941\nclaim: C-941\nreproduce: import struct; print(hex(0x5A4D))\n"
        "expected: 0x5a4d\n---\n", encoding="utf-8")
    out = kv.verify(tmp_path, "F-941")
    assert out["overall"] == "VERIFIED", out
    assert "machine_check" not in out


# ---------- dispatch prompt contract (#332: the BLIND prompt must demand it) ----------

def test_dispatch_prompt_requires_machine_check_block(tmp_path):
    """build_redteam_prompt must instruct the machine_check block — a redteam
    agent dispatched without the requirement has no reason to emit it."""
    prompt = kv.build_redteam_prompt("C-940", tmp_path)
    assert "machine_check" in prompt
    for key in ("expected", "actual", "passed"):
        assert key in prompt


def test_dispatch_prompt_machine_check_addition_stays_blind(tmp_path):
    """The #332 instruction is generic contract text — it must not leak the
    maker's fact content (prompt_is_blind still holds)."""
    facts = tmp_path / "facts"
    facts.mkdir()
    (facts / "F-1.md").write_text(
        "---\nid: F-1\nclaim_id: C-940\n---\n"
        "the XOR key is index+0x4d over the .rdata blob at 0x21A640\n",
        encoding="utf-8")
    prompt = kv.build_redteam_prompt("C-940", tmp_path)
    assert kv.prompt_is_blind(prompt, tmp_path, "C-940") is True


# ---------- contract doc pins (red-team agent + facts schema) ----------

def test_redteam_agent_doc_requires_machine_check():
    """agents/kunglao-redteam.md must carry the #332 oracle contract (format spot check)."""
    text = (ROOT / "agents" / "kunglao-redteam.md").read_text(encoding="utf-8",
                                                              errors="ignore")
    assert "machine_check" in text
    assert "```machine_check" in text
    assert "expected" in text and "actual" in text and "passed" in text


def test_redteam_agent_doc_failed_check_blocks_confirmed():
    """The agent contract must forbid CONFIRMED when a machine check failed."""
    text = (ROOT / "agents" / "kunglao-redteam.md").read_text(encoding="utf-8",
                                                              errors="ignore")
    assert ("passed=false" in text) or ("passed: false" in text)
    assert "REFUTED" in text
    assert "machine_check: none" in text


def test_facts_schema_doc_documents_machine_check_contract():
    """references/schema.md must point at the oracle contract + map file."""
    text = (ROOT / "references" / "schema.md").read_text(encoding="utf-8",
                                                         errors="ignore")
    assert "machine_check" in text
    assert "machine_check_map.yaml" in text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
