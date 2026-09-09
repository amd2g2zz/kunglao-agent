# -*- coding: utf-8 -*-
"""RED tests for inference-claim-blind-scope (issue #48, a2b5e25c problem 2).

TDD: these tests import check_inference_blind_scope which does NOT exist yet →
RED. Implementation in scripts/blind_gate.py makes them GREEN.

Covers:
  RED1: inferential claim + orchestrator-captured sign-off evidence → STAMP
  RED2: inferential claim + independent static xref in sign-off → PROVEN
  RED3: non-inferential (pure byte-anchor) claim → PROVEN regardless
  RED4: 0-hits + environmental-fault self-report + no static xref → STAMP,
        reason names the environmental evidence
  a2b5e25c backtest: F040 routing inference → STAMP; backfilled static xref → passes
  edges: no signoff, self-stamp, REFUTE, inference from fact text only,
         env-fault without 0-hits (generic coverage failure)
  integration: claim_migrator downgrade + worker_budget backstop
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from _factories import seed_difficulty, seed_verifier_dispatch  # #57 gate 5 evidence + #16 tier seeders

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


# ---------- helpers ----------

def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _claim_register(claims: list[dict]) -> str:
    """claim-register.yaml text with statement field (plain scalars)."""
    return "claims:\n" + "".join(
        f"- id: {c['id']}\n  status: {c.get('status', 'OPEN')}\n"
        f"  statement: {c.get('statement', '')}\n"
        f"  boundary_type: {c.get('boundary_type', 'observation')}\n"
        for c in claims)


def _signoff(evidence: str, verdict: str = "CONFIRMED",
             verifier_id: str = "redteam-w1", extra: str = "") -> str:
    """verifier_sign_off yaml block. Evidence lands in refute_attempt
    (plain scalar — no colon-space inside)."""
    return ("```yaml\nverifier_sign_off:\n"
            f"  verifier_id: {verifier_id}\n"
            f"  refute_attempt: {evidence}\n"
            f"  sign_off_at: 2026-08-11T10:00:00Z\n"
            f"  verdict: {verdict}\n"
            + (f"  {extra}\n" if extra else "")
            + "```\n")


def _register_statuses(ws: Path) -> dict[str, str]:
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    return {c["id"]: c["status"] for c in reg.get("claims", [])}


# =====================================================================
# RED1: inferential + orchestrator-captured → STAMP
# =====================================================================

def test_red1_orchestrator_captured_downgrades(tmp_path):
    """Routing claim signed off with orchestrator-captured evidence → STAMP."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-203",
                            "statement": "HandleCommand @0x3809A0 not on inject path (routing)"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-203.md",
           "# F040\n\nrouting inference\n\n"
           + _signoff("live-disasm re-run (orchestrator-captured); 0 hits confirm not on path"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-203", ws / "facts", reg)
    assert not allowed, "orchestrator-captured evidence must not cover an inference"
    assert effective == "STAMP"
    assert "orchestrator" in reason.lower()


# =====================================================================
# RED2: inferential + independent static xref → PROVEN
# =====================================================================

def test_red2_independent_static_xref_passes(tmp_path):
    """Routing claim with independent static xref/disasm in sign-off → PROVEN."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-203", "statement": "routing: config targets C2-A"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-203.md",
           "# F040\n\nrouting inference\n\n"
           + _signoff("xref 0x3809A0 shows func12 called from HandleCommand dispatch; disasm confirms"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-203", ws / "facts", reg)
    assert allowed, f"independent static evidence must cover the inference: {reason}"
    assert effective == "PROVEN"


def test_red2b_evidence_path_field_counts(tmp_path):
    """Static markers in the optional evidence_path field also cover."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-203", "statement": "not on inject path"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-203.md",
           "# F040\n\n"
           + _signoff("verifier re-ran byte anchors only", extra="evidence_path: verifier-xref-0x3809A0.txt"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-203", ws / "facts", reg)
    assert allowed, f"evidence_path with xref marker must cover: {reason}"
    assert effective == "PROVEN"


# =====================================================================
# RED3: non-inferential (pure byte anchors) → PROVEN
# =====================================================================

def test_red3_non_inferential_passes(tmp_path):
    """Byte-anchor claim with no inferential patterns → PROVEN regardless."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-1", "statement": "13 ASCII strings in .rdata at 0x4000"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-1.md", "# F001\n\nbyte anchors only\n")
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-1", ws / "facts", reg)
    assert allowed, f"non-inferential claim must pass: {reason}"
    assert effective == "PROVEN"


# =====================================================================
# RED4: 0-hits + env-fault self-report + no static xref → STAMP
# =====================================================================

def test_red4_zero_hits_env_fault_downgrades(tmp_path):
    """0-hits + stalled/never-reconnected provenance, byte-anchor sign-off
    only → STAMP; reason names the environmental negative evidence."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-203", "statement": "not on inject path (0 hits)"}])
    _write(ws / "claim-register.yaml", reg)
    fact_text = ("# F040\n\nHandleCommand @0x3809A0 NOT on inject path (0 hits)\n\n"
                 "provenance: debuggee 6500 WSS reconnect goroutine stalled; "
                 "never reconnected\n\n"
                 + _signoff("13/13 string bytes matched"))
    _write(ws / "facts" / "C-203.md", fact_text)
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-203", ws / "facts", reg)
    assert not allowed, "environmental negative evidence must not establish routing"
    assert effective == "STAMP"
    assert ("environmental" in reason.lower() or "stalled" in reason.lower()
            or "static xref" in reason.lower())


def test_red4b_zero_hits_env_fault_with_static_passes(tmp_path):
    """Same 0-hits/env-fault fact but sign-off carries static xref → PROVEN."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-203", "statement": "not on inject path (0 hits)"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-203.md",
           "# F040\n\nHandleCommand NOT on inject path (0 hits)\n\n"
           "provenance: goroutine stalled; never reconnected\n\n"
           + _signoff("xref 0x3809A0 shows no callsite into inject path; ghidra call graph confirms"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-203", ws / "facts", reg)
    assert allowed, f"static xref must replace the dynamic-miss conclusion: {reason}"
    assert effective == "PROVEN"


# =====================================================================
# a2b5e25c backtest: F040 routing inference
# =====================================================================

def test_backtest_f040_downgrades(tmp_path):
    """Incident state: routing inference, orchestrator-captured live disasm,
    stalled/never-reconnected provenance, byte-anchor sign-off → STAMP."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-203",
                            "statement": "routing correction: HandleCommand NOT on inject path (0 hits), corrects F034"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-203.md",
           "# F040\n\n"
           "routing: HandleCommand @0x3809A0 NOT on inject path (0 hits); corrects F034\n\n"
           "live-disasm portion orchestrator-captured\n\n"
           "provenance: WSS reconnect goroutine stalled; never reconnected\n\n"
           + _signoff("byte-anchor re-run PASS 13/13"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-203", ws / "facts", reg)
    assert not allowed, "F040 must be blocked from PROVEN"
    assert effective == "STAMP"
    assert "INFERENCE" in reason


def test_backtest_f040_backfill_static_passes(tmp_path):
    """Backfilled state: sign-off carries independent static xref → PROVEN."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-203",
                            "statement": "routing correction: HandleCommand NOT on inject path (0 hits), corrects F034"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-203.md",
           "# F040\n\n"
           "routing: HandleCommand @0x3809A0 NOT on inject path (0 hits); corrects F034\n\n"
           "live-disasm portion orchestrator-captured\n\n"
           "provenance: WSS reconnect goroutine stalled; never reconnected\n\n"
           + _signoff("xref 0x3809A0 shows func12 is HandleCommand.func12 closure literal; "
                      "callsite from HandleCommand dispatch (ghidra)"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-203", ws / "facts", reg)
    assert allowed, f"backfilled static evidence must allow PROVEN: {reason}"
    assert effective == "PROVEN"


# =====================================================================
# Edges
# =====================================================================

def test_edge_no_signoff_downgrades(tmp_path):
    """Inferential claim with no sign-off at all → STAMP."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-203", "statement": "routing via C2-A"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-203.md", "# F040\n\nno signoff\n")
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-203", ws / "facts", reg)
    assert not allowed
    assert effective == "STAMP"


def test_edge_self_stamp_downgrades(tmp_path):
    """verifier_id == worker_id → self-stamp, not independent."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-203", "statement": "routing via C2-A"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-203.md",
           "# F040\n\n" + _signoff("xref confirms routing", verifier_id="w1"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope(
        "C-203", ws / "facts", reg, worker_id="w1")
    assert not allowed
    assert effective == "STAMP"
    assert "self" in reason.lower()


def test_edge_refute_downgrades(tmp_path):
    """BLIND REFUTE verdict → cannot be PROVEN."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-203", "statement": "routing via C2-A"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-203.md",
           "# F040\n\n" + _signoff("xref found contradicting callsite", verdict="REFUTE"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-203", ws / "facts", reg)
    assert not allowed
    assert effective == "STAMP"
    assert "REFUTE" in reason or "REFUTED" in reason


def test_edge_inference_from_fact_text_only(tmp_path):
    """Statement has no keyword but fact text says `corrects F-034` → inferential."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-203", "statement": "HandleCommand coverage trace"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-203.md",
           "# F040\n\ncorrects F-034 (routing)\n\n" + _signoff("13/13 byte anchors"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-203", ws / "facts", reg)
    assert not allowed, "fact-text-only inference must still require static coverage"
    assert effective == "STAMP"


def test_edge_env_fault_without_zero_hits_generic_failure(tmp_path):
    """Env fault alone (no 0-hits) → generic coverage failure (no static)."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-203", "statement": "routing via C2-A"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-203.md",
           "# F040\n\nrouting via C2-A\n\nprovenance: debuggee stalled\n\n"
           + _signoff("13/13 string bytes matched"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-203", ws / "facts", reg)
    assert not allowed
    assert effective == "STAMP"
    assert "static" in reason.lower() or "byte-anchor" in reason.lower()


# =====================================================================
# Integration: claim_migrator downgrade
# =====================================================================

def test_claim_migrator_downgrades_inferential_to_stamp(ws_factory):
    """Orchestrator promotes an inferential claim with orchestrator-captured
    sign-off → register gets STAMP, message names INFERENCE."""
    ws = ws_factory(claims=[{"id": "C-203", "status": "OPEN"}])
    _write(ws / "facts" / "C-203.md",
           "# F040\n\nrouting: HandleCommand NOT on inject path (0 hits)\n\n"
           + _signoff("13/13 byte anchors (orchestrator-captured)"))
    from kunglao_record import claim_migrator
    ok, msg = claim_migrator(ws, "C-203", "PROVEN", actor="orchestrator")
    assert ok, "claim_migrator should succeed (downgrade, not reject)"
    assert _register_statuses(ws)["C-203"] == "STAMP", "inference gap must downgrade to STAMP"
    assert "INFERENCE" in msg


def test_claim_migrator_promotes_non_inferential(ws_factory):
    """Non-inferential claim + valid BLIND sign-off → PROVEN kept."""
    ws = ws_factory(claims=[{"id": "C-11", "status": "OPEN"}])
    _write(ws / "facts" / "C-11.md",
           _signoff("13 ASCII strings byte-matched in .rdata"))
    seed_difficulty(ws, "easy")  # #16: easy = legacy single-verification posture
    seed_verifier_dispatch(ws, "C-11")  # #57 gate 5: a verifier WAS dispatched
    from kunglao_record import claim_migrator
    ok, msg = claim_migrator(ws, "C-11", "PROVEN", actor="orchestrator")
    assert ok, msg
    assert _register_statuses(ws)["C-11"] == "PROVEN", f"expected PROVEN, got: {msg}"


# =====================================================================
# Integration: worker_budget backstop (direct register write)
# =====================================================================

def test_backstop_blocks_direct_proven_inferential(ws_factory):
    """Direct PROVEN write for an uncovered inferential claim → blocked."""
    ws = ws_factory(claims=[{"id": "C-203", "status": "OPEN"}])
    _write(ws / "facts" / "C-203.md",
           "# F040\n\nrouting: NOT on inject path (0 hits)\n\n"
           + _signoff("13/13 byte anchors"))
    import worker_budget as wb
    reg_path = ws / "claim-register.yaml"
    reg_path.write_text(reg_path.read_text(encoding="utf-8")
                        .replace("status: OPEN", "status: PROVEN"), encoding="utf-8")
    ok, reason = wb.compare_register_change_proven_gate(
        reg_path, {"C-203": "OPEN"}, "kunglao-orch", ws / "facts")
    assert not ok, "direct PROVEN write over an uncovered inference must be blocked"
    assert "INFERENCE" in reason


def test_backstop_allows_direct_proven_non_inferential(ws_factory):
    """Direct PROVEN write for a non-inferential claim → allowed."""
    ws = ws_factory(claims=[{"id": "C-11", "status": "OPEN"}])
    _write(ws / "facts" / "C-11.md",
           _signoff("13 ASCII strings byte-matched in .rdata"))
    seed_difficulty(ws, "easy")  # #16: easy = legacy single-verification posture
    seed_verifier_dispatch(ws, "C-11")  # #57 gate 5: a verifier WAS dispatched
    import worker_budget as wb
    reg_path = ws / "claim-register.yaml"
    reg_path.write_text(reg_path.read_text(encoding="utf-8")
                        .replace("status: OPEN", "status: PROVEN"), encoding="utf-8")
    ok, reason = wb.compare_register_change_proven_gate(
        reg_path, {"C-11": "OPEN"}, "kunglao-orch", ws / "facts")
    assert ok, f"non-inferential direct PROVEN should be allowed: {reason}"
