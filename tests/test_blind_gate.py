# -*- coding: utf-8 -*-
"""RED tests for blind-verify-on-promotion (issue #15, PRD M1).

TDD: these tests import modules/functions that do NOT exist yet
(blind_gate, measure_blind_coverage) → RED. Implementation in
scripts/blind_gate.py + tools/auxiliary/measure_blind_coverage.py makes them GREEN.

Covers:
  RED1: PROVEN promotion without BLIND sign-off → auto-downgrade to STAMP
  RED2: BLIND REFUTE verdict → cannot be PROVEN (downgrade to STAMP)
  RED3: PROVEN with valid BLIND sign-off → allowed as PROVEN
  RED4: measure_blind_coverage reports correct ratio

Additional edges: extract_verifier_signoff parsing, self-stamp rejection,
compare_register_change catches orchestrator bypass, STAMP non-terminal.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TOOLS = ROOT / "tools"
# scripts/ is on pythonpath via pytest.ini; #340: measure_blind_coverage lives
# in tools/auxiliary/ — add it for the measure tool
sys.path.insert(0, str(TOOLS / "auxiliary"))


# ---------- helpers ----------

VALID_SIGNOFF = textwrap.dedent("""\
    ```yaml
    verifier_sign_off:
      verifier_id: kunglao-redteam-w2
      refute_attempt: "tried grep for alt-config; not found — claim holds"
      sign_off_at: 2026-08-10T14:00:00Z
      verdict: CONFIRMED
    ```
    """)

REFUTE_SIGNOFF = textwrap.dedent("""\
    ```yaml
    verifier_sign_off:
      verifier_id: kunglao-redteam-w3
      refute_attempt: "found contradicting byte at 0x400 — claim is wrong"
      sign_off_at: 2026-08-10T14:05:00Z
      verdict: REFUTE
    ```
    """)


def _write_fact(ws: Path, claim_id: str, body: str) -> Path:
    """Write facts/<claim_id>.md with the given body."""
    facts = ws / "facts"
    facts.mkdir(exist_ok=True)
    f = facts / f"{claim_id}.md"
    f.write_text(body, encoding="utf-8")
    return f


# =====================================================================
# RED3: extract_verifier_signoff + check_proven_gate — VALID sign-off
# =====================================================================

def test_extract_verifier_signoff_parses_valid_block():
    """verifier_sign_off yaml block is correctly parsed from fact text."""
    from blind_gate import extract_verifier_signoff
    fields = extract_verifier_signoff(VALID_SIGNOFF)
    assert fields is not None, "must parse valid verifier_sign_off block"
    assert fields["verifier_id"] == "kunglao-redteam-w2"
    assert fields["verdict"] == "CONFIRMED"
    assert fields["sign_off_at"] == "2026-08-10T14:00:00Z"
    assert "refute_attempt" in fields


def test_extract_verifier_signoff_returns_none_when_absent():
    """No verifier_sign_off block → None."""
    from blind_gate import extract_verifier_signoff
    assert extract_verifier_signoff("# just a normal fact\nno signoff here") is None


def test_check_proven_gate_allows_with_valid_blind_signoff(ws_factory):
    """RED3: claim promoted to PROVEN WITH valid BLIND sign-off → allowed."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "VERIFIED"}])
    _write_fact(ws, "C-1", VALID_SIGNOFF)
    from blind_gate import check_proven_gate
    allowed, effective, reason = check_proven_gate("C-1", ws / "facts")
    assert allowed is True, f"valid BLIND sign-off must allow PROVEN: {reason}"
    assert effective == "PROVEN"


# =====================================================================
# RED1: PROVEN without BLIND sign-off → downgrade STAMP
# =====================================================================

def test_check_proven_gate_downgrades_when_no_signoff(ws_factory):
    """RED1: PROVEN promotion WITHOUT verifier_sign_off → downgrade to STAMP."""
    ws = ws_factory(claims=[{"id": "C-2", "status": "VERIFIED"}])
    _write_fact(ws, "C-2", "# fact without signoff\nsome evidence here")
    from blind_gate import check_proven_gate
    allowed, effective, reason = check_proven_gate("C-2", ws / "facts")
    assert allowed is False, "no BLIND sign-off must NOT allow PROVEN"
    assert effective == "STAMP", f"effective status must be STAMP, got {effective}"
    assert "verifier_sign_off" in reason or "missing" in reason.lower()


def test_check_proven_gate_downgrades_when_no_fact_file(ws_factory):
    """RED1 edge: PROVEN promotion but fact file doesn't exist → STAMP."""
    ws = ws_factory(claims=[{"id": "C-3", "status": "VERIFIED"}])
    # no facts/ dir, no fact file
    from blind_gate import check_proven_gate
    allowed, effective, reason = check_proven_gate("C-3", ws / "facts")
    assert allowed is False
    assert effective == "STAMP"
    assert "fact" in reason.lower()


# =====================================================================
# RED2: BLIND REFUTE → cannot be PROVEN
# =====================================================================

def test_check_proven_gate_downgrades_on_blind_refute(ws_factory):
    """RED2: verifier_sign_off with verdict=REFUTE → cannot be PROVEN."""
    ws = ws_factory(claims=[{"id": "C-4", "status": "VERIFIED"}])
    _write_fact(ws, "C-4", REFUTE_SIGNOFF)
    from blind_gate import check_proven_gate
    allowed, effective, reason = check_proven_gate("C-4", ws / "facts")
    assert allowed is False, "BLIND REFUTE must NOT allow PROVEN"
    assert effective == "STAMP"
    assert "REFUTE" in reason or "REFUTED" in reason


# =====================================================================
# Self-stamp: verifier_id == worker_id → rejected
# =====================================================================

def test_self_stamp_rejected(ws_factory):
    """verifier_id == claim's worker_id → self-stamp, not valid BLIND."""
    ws = ws_factory(claims=[{"id": "C-5", "status": "VERIFIED"}])
    self_signoff = textwrap.dedent("""\
        ```yaml
        verifier_sign_off:
          verifier_id: w1
          refute_attempt: "checked myself"
          sign_off_at: 2026-08-10T14:00:00Z
          verdict: CONFIRMED
        ```
        """)
    _write_fact(ws, "C-5", self_signoff)
    from blind_gate import check_proven_gate
    # worker_id=w1 matches verifier_id=w1 → self-stamp
    allowed, effective, reason = check_proven_gate("C-5", ws / "facts", worker_id="w1")
    assert allowed is False, "self-stamp must not count as independent BLIND"
    assert effective == "STAMP"
    assert "self" in reason.lower() or "stamp" in reason.lower()


# =====================================================================
# Integration: claim_migrator auto-downgrades PROVEN → STAMP
# =====================================================================

def test_claim_migrator_proven_without_blind_downgrades_to_stamp(ws_factory):
    """RED1 integration: orchestrator promotes to PROVEN without BLIND → STAMP written."""
    ws = ws_factory(claims=[{"id": "C-10", "status": "VERIFIED"}])
    _write_fact(ws, "C-10", "# fact\nno signoff")
    from kunglao_record import claim_migrator
    ok, msg = claim_migrator(ws, "C-10", "PROVEN", actor="orchestrator")
    assert ok, "claim_migrator should succeed (downgrade, not reject)"
    # register should say STAMP, not PROVEN
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    statuses = {c["id"]: c["status"] for c in reg["claims"]}
    assert statuses["C-10"] == "STAMP", f"expected STAMP in register, got {statuses['C-10']}"
    assert "STAMP" in msg or "downgrad" in msg.lower()


def test_claim_migrator_proven_with_blind_stays_proven(ws_factory):
    """RED3 integration: orchestrator promotes to PROVEN with valid BLIND → PROVEN kept."""
    ws = ws_factory(claims=[{"id": "C-11", "status": "VERIFIED"}])
    _write_fact(ws, "C-11", VALID_SIGNOFF)
    from kunglao_record import claim_migrator
    ok, msg = claim_migrator(ws, "C-11", "PROVEN", actor="orchestrator")
    assert ok
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    statuses = {c["id"]: c["status"] for c in reg["claims"]}
    assert statuses["C-11"] == "PROVEN", f"expected PROVEN, got {statuses['C-11']}"


def test_claim_migrator_stamp_is_non_terminal(ws_factory):
    """STAMP can be subsequently promoted to PROVEN (after obtaining sign-off)."""
    ws = ws_factory(claims=[{"id": "C-12", "status": "VERIFIED"}])
    _write_fact(ws, "C-12", "# no signoff yet")
    from kunglao_record import claim_migrator
    # first: downgrade to STAMP
    claim_migrator(ws, "C-12", "PROVEN", actor="orchestrator")
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    assert {c["id"]: c["status"] for c in reg["claims"]}["C-12"] == "STAMP"
    # now: add sign-off and promote again
    (ws / "facts" / "C-12.md").write_text(VALID_SIGNOFF, encoding="utf-8")
    ok, msg = claim_migrator(ws, "C-12", "PROVEN", actor="orchestrator")
    assert ok
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    assert {c["id"]: c["status"] for c in reg["claims"]}["C-12"] == "PROVEN"


# =====================================================================
# worker_budget.compare_register_change: orchestrator bypass gate
# =====================================================================

def test_compare_register_change_blocks_orchestrator_proven_without_blind(ws_factory):
    """Orchestrator directly edits register to PROVEN without BLIND → reject."""
    ws = ws_factory(claims=[{"id": "C-20", "status": "VERIFIED"}])
    _write_fact(ws, "C-20", "# no signoff")
    import worker_budget as wb
    # point wb at this workspace's facts_dir via monkey-patching the helper
    before = {"C-20": "VERIFIED"}
    # simulate orchestrator directly wrote PROVEN
    reg_path = ws / "claim-register.yaml"
    reg_text = reg_path.read_text(encoding="utf-8").replace("status: VERIFIED", "status: PROVEN")
    reg_path.write_text(reg_text, encoding="utf-8")
    ok, reason = wb.compare_register_change_proven_gate(
        reg_path, before, "kunglao-orch", ws / "facts")
    assert not ok, "orchestrator PROVEN without BLIND must be blocked"
    assert "BLIND" in reason or "STAMP" in reason


def test_compare_register_change_allows_orchestrator_proven_with_blind(ws_factory):
    """Orchestrator directly edits register to PROVEN WITH BLIND → allowed."""
    ws = ws_factory(claims=[{"id": "C-21", "status": "VERIFIED"}])
    _write_fact(ws, "C-21", VALID_SIGNOFF)
    import worker_budget as wb
    before = {"C-21": "VERIFIED"}
    reg_path = ws / "claim-register.yaml"
    reg_text = reg_path.read_text(encoding="utf-8").replace("status: VERIFIED", "status: PROVEN")
    reg_path.write_text(reg_text, encoding="utf-8")
    ok, reason = wb.compare_register_change_proven_gate(
        reg_path, before, "kunglao-orch", ws / "facts")
    assert ok, f"PROVEN with valid BLIND should be allowed: {reason}"


# =====================================================================
# RED4: measure_blind_coverage reports correct ratio
# =====================================================================

def test_measure_blind_coverage_reports_correct_ratio(ws_factory):
    """RED4: 3 PROVEN claims, 1 with BLIND sign-off → coverage 1/3."""
    ws = ws_factory(claims=[
        {"id": "C-30", "status": "PROVEN"},
        {"id": "C-31", "status": "PROVEN"},
        {"id": "C-32", "status": "PROVEN"},
        {"id": "C-33", "status": "OPEN"},
    ])
    # only C-30 gets a valid BLIND sign-off
    _write_fact(ws, "C-30", VALID_SIGNOFF)
    _write_fact(ws, "C-31", "# no signoff")
    _write_fact(ws, "C-32", REFUTE_SIGNOFF)  # REFUTE doesn't count as valid
    # C-33 has no fact file (OPEN, not counted in PROVEN anyway)

    from measure_blind_coverage import measure
    result = measure(ws)
    assert result["proven"] == 3, f"expected 3 PROVEN, got {result['proven']}"
    assert result["blind_signed"] == 1, f"expected 1 BLIND-signed, got {result['blind_signed']}"
    assert result["unverified"] == 2, f"expected 2 unverified, got {result['unverified']}"
    assert abs(result["coverage"] - 1 / 3) < 0.01, f"coverage should be ~0.333, got {result['coverage']}"


def test_measure_blind_coverage_zero_proven(ws_factory):
    """No PROVEN claims → coverage 0.0, no division error."""
    ws = ws_factory(claims=[{"id": "C-40", "status": "OPEN"}])
    from measure_blind_coverage import measure
    result = measure(ws)
    assert result["proven"] == 0
    assert result["coverage"] == 0.0


# =====================================================================
# Non-PROVEN promotions are NOT affected by the gate
# =====================================================================

def test_non_proven_terminal_not_affected(ws_factory):
    """NEGATIVE / REFUTED / DEFERRED promotions do not require BLIND sign-off."""
    ws = ws_factory(claims=[{"id": "C-50", "status": "VERIFIED"}])
    _write_fact(ws, "C-50", "# no signoff at all")
    from kunglao_record import claim_migrator
    for terminal in ("NEGATIVE", "REFUTED", "DEFERRED"):
        ws2 = ws_factory(claims=[{"id": "C-50", "status": "VERIFIED"}])
        ok, msg = claim_migrator(ws2, "C-50", terminal, actor="orchestrator")
        assert ok, f"{terminal} must not require BLIND: {msg}"
        reg = yaml.safe_load((ws2 / "claim-register.yaml").read_text(encoding="utf-8"))
        assert {c["id"]: c["status"] for c in reg["claims"]}["C-50"] == terminal


# =====================================================================
# Dissent recording: BLIND REFUTE writes structured dissent (P4, issue #27)
# =====================================================================

def test_record_dissent_appends_block_to_fact(ws_factory):
    """REFUTE: record_dissent writes a ```dissent block with required fields."""
    ws = ws_factory(claims=[{"id": "C-60", "status": "VERIFIED"}])
    fact_path = _write_fact(ws, "C-60", "# fact body\nsome evidence\n")
    from blind_gate import record_dissent, extract_dissent
    record_dissent(
        fact_path=fact_path,
        verifier_id="kunglao-redteam-w5",
        finding="found alt-config at 0x500 contradicting claim",
        evidence_path="evidence/alt-config.bin",
    )
    text = fact_path.read_text(encoding="utf-8")
    # block must be present
    assert "```dissent" in text, "dissent block marker not found"
    # extract and verify fields
    dissents = extract_dissent(text)
    assert len(dissents) >= 1, "at least one dissent must be extractable"
    d = dissents[-1]  # latest dissent
    assert d["verifier_id"] == "kunglao-redteam-w5"
    assert "alt-config" in d["finding"]
    assert d["evidence_path"] == "evidence/alt-config.bin"
    assert "ts" in d or "timestamp" in d, "dissent must have a timestamp"


def test_record_dissent_preserves_original_content(ws_factory):
    """Dissent append must not destroy existing fact content."""
    ws = ws_factory(claims=[{"id": "C-61", "status": "VERIFIED"}])
    original = "# Important Fact\n\nThis is critical evidence.\n"
    fact_path = _write_fact(ws, "C-61", original)
    from blind_gate import record_dissent
    record_dissent(
        fact_path=fact_path,
        verifier_id="v2",
        finding="refuted",
        evidence_path="evidence/x.txt",
    )
    text = fact_path.read_text(encoding="utf-8")
    assert "Important Fact" in text
    assert "critical evidence" in text


def test_extract_dissent_returns_empty_when_none():
    """No dissent block → empty list."""
    from blind_gate import extract_dissent
    assert extract_dissent("# plain fact\nno dissent") == []


def test_extract_dissent_multiple_blocks():
    """Multiple dissent blocks (re-refutation) → all extracted in order."""
    from blind_gate import extract_dissent
    text = (
        "# fact\n\n"
        "```dissent\n"
        "verifier_id: v1\n"
        "finding: first issue\n"
        "evidence_path: evidence/a.txt\n"
        "ts: 2026-08-10T10:00:00Z\n"
        "```\n\n"
        "```dissent\n"
        "verifier_id: v2\n"
        "finding: second issue\n"
        "evidence_path: evidence/b.txt\n"
        "ts: 2026-08-10T11:00:00Z\n"
        "```\n"
    )
    dissents = extract_dissent(text)
    assert len(dissents) == 2
    assert dissents[0]["verifier_id"] == "v1"
    assert dissents[1]["verifier_id"] == "v2"
