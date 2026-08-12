"""RED tests for env-negative-rule (issue #56, generalizes #48's F040 gate).

#48 shipped check_inference_blind_scope with an env-fault diagnostic that
rejects (0 hits + env-fault) routing inferences. #56 generalizes the rule:
environmental negative evidence (BP 0 hits / no call captured / no calls
observed) under a self-reported env fault must NOT establish a routing OR
existence conclusion. This suite asserts:

  * acceptance #2 (F040 regression): routing + 0 hits + env-fault -> STAMP
    (already enforced by #48; recorded here as the regression contract).
  * the RESIDUAL (#56): existence conclusions phrased via the issue's
    无调用捕获 / "no call captured" / "absent" vocabulary currently slip
    through as "non-inferential" -> PROVEN. These tests are RED before the
    #56 generalization (G2: negative-existence is inferential; G1: the
    broadened basis vocab makes the reason name the environmental problem).
  * complementarity with #48: same gate function (no duplicate), and no
    over-flagging of positive existence / pure byte-anchor claims.

The fixture claim text mirrors the issue's documented F040 shapes (the
issue body is the source — synthetic, not live data).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


# ---------- helpers ----------

def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _claim_register(claims: list[dict]) -> str:
    return "claims:\n" + "".join(
        f"- id: {c['id']}\n  status: {c.get('status', 'OPEN')}\n"
        f"  statement: {c.get('statement', '')}\n"
        f"  boundary_type: {c.get('boundary_type', 'observation')}\n"
        for c in claims)


def _signoff(evidence: str, verdict: str = "CONFIRMED",
             verifier_id: str = "redteam-w1") -> str:
    return ("```yaml\nverifier_sign_off:\n"
            f"  verifier_id: {verifier_id}\n"
            f"  refute_attempt: {evidence}\n"
            f"  sign_off_at: 2026-08-11T10:00:00Z\n"
            f"  verdict: {verdict}\n"
            + "```\n")


def _env_fault_note() -> str:
    """Provenance self-report mirroring the F040 incident (a2b5e25c)."""
    return ("provenance: debuggee PID 6500 WSS reconnect goroutine stalled; "
            "never reconnected\n")


# =====================================================================
# Acceptance #2 — F040 regression (routing; already covered by #48,
# asserted here as the regression contract for the generalized gate)
# =====================================================================

def test_f040_regression_routing_zero_hits_downgrades(tmp_path):
    """F040 verbatim shape: routing + '0 hits' + env-fault -> STAMP."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-203",
                            "statement": "HandleCommand NOT on the inject path (routing correction, 0 hits)"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-203.md",
           "# F040\n\nHandleCommand @0x3809A0 NOT on inject path (0 hits)\n\n"
           + _env_fault_note() + "\n"
           + _signoff("byte-anchor re-run PASS 13/13"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-203", ws / "facts", reg)
    assert not allowed, "F040 routing inference must be blocked from PROVEN"
    assert effective == "STAMP"
    assert "INFERENCE" in reason


# =====================================================================
# RESIDUAL (#56) — existence conclusions that slip past #48 (RED)
# =====================================================================

def test_existence_no_call_captured_downgrades(tmp_path):
    """Existence claim based on 'no call captured' under env fault -> STAMP.

    The issue's rule names 无调用捕获 ('no call captured') as a trigger, but
    #48's INFERENTIAL_PATTERNS has no existence / no-call-captured vocabulary,
    so this claim currently short-circuits as 'non-inferential' -> PROVEN.
    RED until #56 (G1 + G2) is applied.
    """
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-204",
                            "statement": "Function X does not exist in the binary"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-204.md",
           "# F099\n\nFunction X does not exist; dynamic_re trace captured no "
           "call to X across the run window.\n\n"
           + _env_fault_note() + "\n"
           + _signoff("13/13 string bytes matched"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-204", ws / "facts", reg)
    assert not allowed, ("existence conclusion from env-faulted dynamic miss "
                         "must not be PROVEN")
    assert effective == "STAMP"
    assert "INFERENCE" in reason


def test_absent_no_calls_observed_downgrades(tmp_path):
    """'absent' conclusion based on 'no calls observed' under env fault -> STAMP.

    RED until #56: 'absent' / 'no calls observed' are not in #48's vocabulary.
    """
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-205",
                            "statement": "Handler H is absent from the call graph"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-205.md",
           "# F098\n\nHandler H absent — no calls observed to H in the trace.\n\n"
           + _env_fault_note() + "\n"
           + _signoff("byte anchors 13/13"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-205", ws / "facts", reg)
    assert not allowed, "'absent' conclusion from env-faulted miss must not be PROVEN"
    assert effective == "STAMP"
    assert "INFERENCE" in reason


def test_existence_reason_names_environmental_problem(tmp_path):
    """When #56 rejects an existence-from-dynamic-miss claim, the reason
    MUST name the environmental negative evidence (not the generic
    byte-anchor message). Requires G1 (broadened basis vocab).

    RED until G1 is applied (without G1 the reason is the generic
    'byte-anchor insufficient' message even after G2 downgrades it).
    """
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-204",
                            "statement": "Function X does not exist in the binary"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-204.md",
           "# F099\n\nFunction X does not exist; no call captured for X.\n\n"
           + _env_fault_note() + "\n"
           + _signoff("13/13 string bytes matched"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-204", ws / "facts", reg)
    assert not allowed
    assert effective == "STAMP"
    assert ("environmental" in reason.lower() or "existence" in reason.lower()), (
        "reason must name the environmental negative evidence / existence "
        f"problem, got: {reason!r}")


def test_routing_no_call_captured_reason_names_environmental(tmp_path):
    """G1 diagnostic for routing claims too: a routing claim whose
    dynamic-miss basis is phrased 'no call captured' (not '0 hits') must
    still get the environmental-evidence reason. RED until G1."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-206",
                            "statement": "HandleCommand is not on the inject path (routing)"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-206.md",
           "# F040b\n\nrouting: HandleCommand not on inject path; no call "
           "captured across the trace.\n\n"
           + _env_fault_note() + "\n"
           + _signoff("byte anchors 13/13"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-206", ws / "facts", reg)
    assert not allowed
    assert effective == "STAMP"
    assert "environmental" in reason.lower(), (
        f"reason must name environmental evidence for 'no call captured' basis, got: {reason!r}")


# =====================================================================
# Static xref replaces the dynamic-miss conclusion
# =====================================================================

def test_existence_env_negative_with_static_xref_passes(tmp_path):
    """Existence claim + no-call-captured + env-fault, but sign-off carries
    independent static xref -> PROVEN (static evidence replaces the miss)."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-204",
                            "statement": "Function X does not exist in the binary"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-204.md",
           "# F099\n\nFunction X does not exist; no call captured for X.\n\n"
           + _env_fault_note() + "\n"
           + _signoff("ghidra function list has no X; xref scan from entry "
                      "points reaches no X callsite (capstone disasm confirms)"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-204", ws / "facts", reg)
    assert allowed, f"static xref must cover the existence inference: {reason}"
    assert effective == "PROVEN"


# =====================================================================
# Complementarity with #48 — no duplicate gate, no over-flagging
# =====================================================================

def test_complementarity_same_gate_function():
    """#56 introduces NO new gate: both the F040 routing case and the new
    existence case are handled by check_inference_blind_scope (#48's gate).
    """
    import blind_gate
    # the generalized rule lives inside the #48 function — no new public entry
    assert hasattr(blind_gate, "check_inference_blind_scope")
    assert not hasattr(blind_gate, "check_env_negative_gate"), (
        "#56 must not add a duplicate gate; the rule extends check_inference_blind_scope")


def test_complementarity_positive_existence_not_over_flagged(tmp_path):
    """A POSITIVE existence claim with no dynamic-miss basis and a byte-anchor
    sign-off must still pass — proves #56's broader vocabulary does not
    duplicate/expand #48's byte-anchor gate into false positives."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-11",
                            "statement": "Function Foo exists at 0x401000"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-11.md",
           "# F011\n\nFoo exists at 0x401000; byte-anchored.\n\n"
           + _signoff("13/13 string bytes matched"))
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-11", ws / "facts", reg)
    assert allowed, f"positive existence claim must not be over-flagged: {reason}"
    assert effective == "PROVEN"


def test_complementarity_byte_anchor_only_claim_still_passes(tmp_path):
    """A pure byte-anchor claim (no inferential pattern at all) still passes —
    #56 does not disturb #48's RED3 contract."""
    ws = tmp_path / "ws"
    reg = _claim_register([{"id": "C-1",
                            "statement": "13 ASCII strings in .rdata at 0x4000"}])
    _write(ws / "claim-register.yaml", reg)
    _write(ws / "facts" / "C-1.md", "# F001\n\nbyte anchors only\n")
    from blind_gate import check_inference_blind_scope
    allowed, effective, reason = check_inference_blind_scope("C-1", ws / "facts", reg)
    assert allowed
    assert effective == "PROVEN"
