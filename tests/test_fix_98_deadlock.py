"""RED->GREEN tests for fix-98-maker-checker-deadlock (#98, D6/F15).

Issue #98: fail-closed verification gates (#78) treat ALL exceptions identically
(ImportError and RuntimeError both produce BLOCKED). This creates a deadlock
when the verifier subagent is runtime-unavailable: the gate module imports fine
but the checker function raises (timeout, resource limit) -> claim BLOCKED ->
worker cannot self_caveat -> verifier keeps timing out.

Fix: two-tier exception classification:
  - ImportError (gate module broken) -> FAIL_CLOSED, BLOCKED (unchanged)
  - RuntimeError (verifier subagent unavailable) -> degrade to STAMP

RED tests: 3.x tests currently FAIL on the pre-fix code. Tests that assert
existing ImportError behavior (3.1, 3.7) should PASS on both pre-fix and
post-fix code (regression anchors).
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from _factories import seed_verifier_dispatch  # #57 gate 5 evidence seeder

ROOT = Path(__file__).resolve().parents[1]

import kunglao_record  # noqa: E402
import worker_budget  # noqa: E402


# ---------- helpers ----------

def _signoff_fact(ws: Path, claim_id: str) -> Path:
    """Fact file with valid BLIND verifier_sign_off block."""
    f = ws / "facts" / f"{claim_id}.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(
        f"---\nclaim: {claim_id}\n---\n\n"
        "```yaml\n"
        "verifier_sign_off:\n"
        "  verifier_id: kunglao-redteam-w2\n"
        "  refute_attempt: 'tried to refute; held'\n"
        "  sign_off_at: 2026-08-10T14:00:00Z\n"
        "  verdict: CONFIRMED\n"
        "```\n",
        encoding="utf-8")
    return f


def _self_caveat_fact(ws: Path, claim_id: str) -> Path:
    """Fact file with self_caveat in frontmatter (no verifier_sign_off)."""
    f = ws / "facts" / f"{claim_id}.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(
        f"---\nclaim: {claim_id}\n"
        f"self_caveat: 'unverified - needs verifier pass'\n"
        f"verify_status: pending\n---\n\n"
        "# Fact content\nEvidence gathered but verifier unavailable.\n",
        encoding="utf-8")
    return f


def _self_caveat_and_self_stamp_fact(ws: Path, claim_id: str) -> Path:
    """Fact with self_caveat AND self-signed verifier_sign_off."""
    f = ws / "facts" / f"{claim_id}.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(
        f"---\nclaim: {claim_id}\n"
        f"self_caveat: 'unverified - needs verifier pass'\n"
        f"verify_status: pending\n---\n\n"
        "```yaml\n"
        "verifier_sign_off:\n"
        "  verifier_id: w1\n"
        "  refute_attempt: 'checked myself'\n"
        "  sign_off_at: 2026-08-10T14:00:00Z\n"
        "  verdict: CONFIRMED\n"
        "```\n",
        encoding="utf-8")
    return f


def _register_status(ws: Path, claim_id: str) -> str:
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    return next(c["status"] for c in reg["claims"] if c["id"] == claim_id)


def _promoted_events(ws: Path) -> list:
    ledger = ws / "ledger.jsonl"
    if not ledger.exists():
        return []
    return [line for line in ledger.read_text(encoding="utf-8").splitlines()
            if line.strip() and "claim_promoted" in line]


def _unavailable(monkeypatch, module_name: str) -> None:
    """Make import module_name raise ImportError."""
    monkeypatch.setitem(sys.modules, module_name, None)


# =====================================================================
# 3.1 Regression: ImportError -> BLOCKED (existing behavior preserved)
# =====================================================================

def test_claim_migrator_import_error_still_blocked(ws_factory, monkeypatch):
    """S1: ImportError from gate import -> BLOCKED, register unchanged."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1")
    _unavailable(monkeypatch, "blind_gate")
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
    assert not ok, f"ImportError must BLOCK: {msg}"
    assert "BLOCKED" in msg
    assert _register_status(ws, "C-1") == "OPEN", "register must stay unchanged"


def test_claim_migrator_contradiction_import_error_still_blocked(
        ws_factory, monkeypatch):
    """S1: contradiction gate ImportError -> BLOCKED."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1")
    _unavailable(monkeypatch, "fact_contradiction_gate")
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
    assert not ok
    assert "BLOCKED" in msg
    assert _register_status(ws, "C-1") == "OPEN"


# =====================================================================
# 3.2 RED: claim_migrator blind_gate runtime error -> STAMP degraded
# =====================================================================

def test_claim_migrator_blind_gate_runtime_error_degrades_to_stamp(
        ws_factory, monkeypatch):
    """S2: gate imports OK, check_proven_gate raises RuntimeError -> STAMP.

    Currently FAILS: claim_migrator returns (False, BLOCKED) for all
    exceptions, so register stays OPEN instead of becoming STAMP.
    """
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1")
    import blind_gate

    def boom(*_a, **_k):
        raise RuntimeError("verifier subagent timeout: budget exceeded")

    monkeypatch.setattr(blind_gate, "check_proven_gate", boom)
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
    assert ok, (f"Runtime error should degrade to STAMP (migration succeeds), "
                f"not BLOCK: {msg}")
    assert _register_status(ws, "C-1") == "STAMP", \
        f"Expected STAMP, got {_register_status(ws, 'C-1')}"
    assert "runtime" in msg.lower() or "degrad" in msg.lower(), \
        f"Message should explain degradation: {msg}"


def test_claim_migrator_blind_gate_timeout_error_degrades_to_stamp(
        ws_factory, monkeypatch):
    """S2 variant: TimeoutError specifically."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1")
    import blind_gate

    def boom(*_a, **_k):
        raise TimeoutError("verifier dispatch timed out after 120s")

    monkeypatch.setattr(blind_gate, "check_proven_gate", boom)
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
    assert ok, f"TimeoutError should degrade to STAMP: {msg}"
    assert _register_status(ws, "C-1") == "STAMP"


# =====================================================================
# 3.3 RED: contradiction gate runtime error -> STAMP
# =====================================================================

def test_claim_migrator_contradiction_gate_runtime_error_degrades(
        ws_factory, monkeypatch):
    """S3: contradiction gate raises RuntimeError -> STAMP.

    Currently FAILS: returns (False, BLOCKED).
    """
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1")
    import fact_contradiction_gate

    def boom(*_a, **_k):
        raise RuntimeError("contradiction checker: resource limit reached")

    monkeypatch.setattr(
        fact_contradiction_gate, "check_proven_contradiction", boom)
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
    assert ok, f"Contradiction gate runtime error should degrade to STAMP: {msg}"
    assert _register_status(ws, "C-1") == "STAMP"


# =====================================================================
# 3.4 RED: inference gate runtime error -> STAMP
# =====================================================================

def test_claim_migrator_inference_gate_runtime_error_degrades(
        ws_factory, monkeypatch):
    """S4: inference gate raises RuntimeError -> STAMP.

    Currently FAILS: returns (False, BLOCKED).
    """
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1")
    import blind_gate

    def boom(*_a, **_k):
        raise RuntimeError("inference checker: verifier unavailable")

    monkeypatch.setattr(blind_gate, "check_inference_blind_scope", boom)
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
    assert ok, f"Inference gate runtime error should degrade to STAMP: {msg}"
    assert _register_status(ws, "C-1") == "STAMP"


# =====================================================================
# 3.5 RED: blind_gate recognizes self_caveat
# =====================================================================

def test_blind_gate_self_caveat_returns_stamp(ws_factory):
    """S5: fact with self_caveat in frontmatter -> (False, STAMP).

    Currently FAILS: blind_gate returns (False, STAMP) but with generic
    "verifier_sign_off missing" reason, not self_caveat-specific.
    """
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _self_caveat_fact(ws, "C-1")
    from blind_gate import check_proven_gate
    allowed, effective, reason = check_proven_gate("C-1", ws / "facts")
    assert allowed is False, "self_caveat fact must not be PROVEN"
    assert effective == "STAMP", f"Expected STAMP, got {effective}"
    assert "self_caveat" in reason.lower(), \
        f"Reason should mention self_caveat: {reason}"


def test_blind_gate_inference_self_caveat_returns_stamp(ws_factory):
    """S5 variant: check_inference_blind_scope recognizes self_caveat."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _self_caveat_fact(ws, "C-1")
    from blind_gate import check_inference_blind_scope
    register = (ws / "claim-register.yaml").read_text(encoding="utf-8")
    allowed, effective, reason = check_inference_blind_scope(
        "C-1", ws / "facts", register)
    # self_caveat fact -> inference gate should return STAMP (or pass-through
    # for non-inferential). Either way, self_caveat must not yield PROVEN.
    if not allowed:
        assert effective == "STAMP", f"Expected STAMP, got {effective}"


# =====================================================================
# 3.6: self_caveat does NOT bypass self-stamp guard
# =====================================================================

def test_self_caveat_does_not_bypass_self_stamp_guard(ws_factory):
    """S6: self_caveat + self-signed sign-off -> self-stamp rejected."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _self_caveat_and_self_stamp_fact(ws, "C-1")
    from blind_gate import check_proven_gate
    allowed, effective, reason = check_proven_gate(
        "C-1", ws / "facts", worker_id="w1")
    assert allowed is False, "self-stamp must still be rejected"
    assert effective == "STAMP"
    # Either self_caveat or self-stamp reason must appear
    assert ("self" in reason.lower() or "self_caveat" in reason.lower()), \
        f"Reason should mention self-stamp or self_caveat: {reason}"


# =====================================================================
# 3.7 Regression: Hook import block ImportError -> block
# =====================================================================

def test_hook_import_error_still_blocks(ws_factory, monkeypatch):
    """S7: ImportError in import block -> hook blocks PROVEN edit."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1")
    reg_path = ws / "claim-register.yaml"
    reg_text = reg_path.read_text(encoding="utf-8").replace(
        "status: OPEN", "status: PROVEN")
    reg_path.write_text(reg_text, encoding="utf-8")
    before = {"C-1": "OPEN"}
    _unavailable(monkeypatch, "blind_gate")
    ok, reason = worker_budget.compare_register_change_proven_gate(
        reg_path, before, "kunglao-orch", ws / "facts")
    assert not ok, f"ImportError must block hook: {reason}"
    assert "blind_gate" in reason


# =====================================================================
# 3.8 RED: Hook execution block runtime error -> STAMP guidance
# =====================================================================

def test_hook_execution_runtime_error_gives_stamp_guidance(
        ws_factory, monkeypatch):
    """S8: gates import OK, but gate function raises during execution.

    Currently FAILS: hook returns (False, "...fail closed") with no
    STAMP guidance. After fix: returns (False, "...Downgrade to STAMP...")
    without "fail closed".
    """
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1")
    reg_path = ws / "claim-register.yaml"
    reg_text = reg_path.read_text(encoding="utf-8").replace(
        "status: OPEN", "status: PROVEN")
    reg_path.write_text(reg_text, encoding="utf-8")
    before = {"C-1": "OPEN"}
    import blind_gate

    def boom(*_a, **_k):
        raise RuntimeError("verifier subagent timeout")

    monkeypatch.setattr(blind_gate, "check_proven_gate", boom)
    ok, reason = worker_budget.compare_register_change_proven_gate(
        reg_path, before, "kunglao-orch", ws / "facts")
    assert not ok, "Runtime error should still block PROVEN (cannot be PROVEN without verification)"
    # But message should guide to STAMP, not say "fail closed"
    assert "STAMP" in reason.upper(), \
        f"Hook should guide to STAMP downgrade: {reason}"


# =====================================================================
# Regression: available-checker paths still work
# =====================================================================

def test_claim_migrator_all_gates_ok_still_promotes(ws_factory):
    """S9: all gates available + valid sign-off -> PROVEN (regression)."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1")
    seed_verifier_dispatch(ws, "C-1")  # #57 gate 5: a verifier WAS dispatched
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
    assert ok, msg
    assert _register_status(ws, "C-1") == "PROVEN"


def test_claim_migrator_no_signoff_still_downgrades_to_stamp(ws_factory):
    """Regression: gates available, no sign-off -> STAMP downgrade."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    (ws / "facts").mkdir()
    (ws / "facts" / "C-1.md").write_text(
        "---\nclaim: C-1\n---\nno signoff\n", encoding="utf-8")
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
    assert ok, "downgrade to STAMP should succeed"
    assert _register_status(ws, "C-1") == "STAMP"


def test_hook_all_gates_ok_allows_proven(ws_factory):
    """S9 regression: hook allows PROVEN when all gates pass."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1")
    seed_verifier_dispatch(ws, "C-1")  # #57 gate 5: a verifier WAS dispatched
    reg_path = ws / "claim-register.yaml"
    reg_text = reg_path.read_text(encoding="utf-8").replace(
        "status: OPEN", "status: PROVEN")
    reg_path.write_text(reg_text, encoding="utf-8")
    before = {"C-1": "OPEN"}
    ok, reason = worker_budget.compare_register_change_proven_gate(
        reg_path, before, "kunglao-orch", ws / "facts")
    assert ok, f"Valid PROVEN edit must pass: {reason}"
