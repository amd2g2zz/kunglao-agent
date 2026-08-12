"""RED->GREEN tests for fail-closed-verification-gates (#78).

Issue #78: required verification gates must FAIL CLOSED when unavailable.
Three promotion/verification paths previously manufactured a passing result
when a mandatory checker was missing:

1. `claim_migrator` caught ImportError from the BLIND / contradiction /
   inference gates and CONTINUED toward PROVEN (scripts/kunglao_record.py).
2. The hook-side direct-edit backstop permitted an unreadable register AND an
   unavailable `blind_gate` (hooks/worker_budget.py).
3. The disassembly post-gate wrote `{"ok": true, "skipped": ...}` for an
   import error or ANY exception (scripts/kunglao_verify.py).

TDD: every test here is RED on the pre-fix code (a terminal state IS written
or `ok: true` IS returned) and GREEN after the fail-closed fix. The
available-checker regression tests at the bottom pin the normal paths.

Mutation matrix (acceptance criteria): missing module / ImportError /
checker exception / corrupt register / missing sign-off / malformed binary —
none may produce a PROVEN/VERIFIED terminal state or a passing disasm receipt.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

# Module-level imports are safe: the gates are imported lazily INSIDE the
# functions under test, so sys.modules monkeypatching drives unavailability.
import kunglao_record  # noqa: E402
import kunglao_verify  # noqa: E402
import worker_budget  # noqa: E402


# ---------- helpers ----------

def _signoff_fact(ws: Path, fact_id: str, claim_id: str) -> Path:
    """Fact file with a valid BLIND verifier_sign_off block."""
    f = ws / "facts" / f"{fact_id}.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(
        f"---\nid: {fact_id}\nclaim: {claim_id}\n---\n\n"
        "```yaml\n"
        "verifier_sign_off:\n"
        "  verifier_id: kunglao-redteam-w2\n"
        "  refute_attempt: 'tried to refute; held'\n"
        "  sign_off_at: 2026-08-10T14:00:00Z\n"
        "  verdict: CONFIRMED\n"
        "```\n",
        encoding="utf-8")
    return f


def _register_status(ws: Path, claim_id: str) -> str:
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    return next(c["status"] for c in reg["claims"] if c["id"] == claim_id)


def _promoted_events(ws: Path) -> list[dict]:
    ledger = ws / "ledger.jsonl"
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _unavailable(monkeypatch, module_name: str) -> None:
    """Make `import module_name` raise ImportError (missing-module mutation)."""
    monkeypatch.setitem(sys.modules, module_name, None)


def _raising_checker(monkeypatch, module_name: str, func_name: str,
                     exc: Exception) -> None:
    """Inject a fake module whose checker raises (checker-exception mutation)."""
    fake = types.ModuleType(module_name)

    def boom(*_a, **_k):
        raise exc

    setattr(fake, func_name, boom)
    monkeypatch.setitem(sys.modules, module_name, fake)


# =====================================================================
# claim_migrator — BLIND / contradiction / inference gates fail closed
# =====================================================================

def test_claim_migrator_blocks_proven_when_blind_gate_missing(ws_factory, monkeypatch):
    """Issue #78 reproduction: gate imports unavailable -> NOT (True, PROVEN)."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1", "C-1")
    _unavailable(monkeypatch, "blind_gate")
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
    assert not ok, f"checker unavailability must not permit PROVEN: {msg}"
    assert "BLOCKED" in msg and "blind_gate" in msg
    assert "ImportError" in msg or "ModuleNotFoundError" in msg
    assert _register_status(ws, "C-1") == "OPEN", "register must stay unchanged"
    assert not _promoted_events(ws), "no claim_promoted ledger event"


def test_claim_migrator_blocks_proven_when_contradiction_gate_missing(
        ws_factory, monkeypatch):
    """BLIND gate passes, contradiction gate missing -> still BLOCKED."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1", "C-1")
    _unavailable(monkeypatch, "fact_contradiction_gate")
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
    assert not ok
    assert "BLOCKED" in msg and "fact_contradiction_gate" in msg
    assert _register_status(ws, "C-1") == "OPEN"


def test_claim_migrator_blocks_proven_when_inference_gate_missing(
        ws_factory, monkeypatch):
    """BLIND + contradiction pass, inference-scope gate missing -> BLOCKED."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1", "C-1")
    import blind_gate
    monkeypatch.delattr(blind_gate, "check_inference_blind_scope", raising=False)
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
    assert not ok
    assert "BLOCKED" in msg and "check_inference_blind_scope" in msg
    assert _register_status(ws, "C-1") == "OPEN"


def test_claim_migrator_blocks_proven_when_gate_raises(ws_factory, monkeypatch):
    """Checker exception (non-ImportError) must also fail closed."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1", "C-1")
    import blind_gate

    def boom(*_a, **_k):
        raise RuntimeError("boom: gate crashed")

    monkeypatch.setattr(blind_gate, "check_proven_gate", boom)
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
    assert not ok, f"gate exception must not permit PROVEN: {msg}"
    assert "BLOCKED" in msg and "RuntimeError" in msg
    assert _register_status(ws, "C-1") == "OPEN"


def test_claim_migrator_gate_failure_does_not_affect_other_claims(
        ws_factory, monkeypatch):
    """Fail-closed is per-claim: other claims' statuses untouched."""
    ws = ws_factory(claims=[
        {"id": "C-1", "status": "OPEN"},
        {"id": "C-2", "status": "PROVEN"},
    ])
    _signoff_fact(ws, "C-1", "C-1")
    _unavailable(monkeypatch, "blind_gate")
    ok, _ = kunglao_record.claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
    assert not ok
    assert _register_status(ws, "C-2") == "PROVEN"


# =====================================================================
# worker_budget hook backstop — direct register edits fail closed
# =====================================================================

def _proven_via_direct_edit(ws: Path) -> Path:
    reg_path = ws / "claim-register.yaml"
    text = reg_path.read_text(encoding="utf-8").replace(
        "status: OPEN", "status: PROVEN")
    reg_path.write_text(text, encoding="utf-8")
    return reg_path


def test_hook_blocks_proven_when_blind_gate_unavailable(ws_factory, monkeypatch):
    """Direct register edit to PROVEN must not bypass an unavailable BLIND gate."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1", "C-1")
    reg_path = _proven_via_direct_edit(ws)
    before = {"C-1": "OPEN"}
    _unavailable(monkeypatch, "blind_gate")
    ok, reason = worker_budget.compare_register_change_proven_gate(
        reg_path, before, "kunglao-orch", ws / "facts")
    assert not ok, f"PROVEN edit must be blocked when blind_gate unavailable: {reason}"
    assert "blind_gate" in reason


def test_hook_blocks_proven_when_register_unreadable(ws_factory):
    """Unreadable register after a write -> cannot verify -> fail closed."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    reg_path = ws / "claim-register.yaml"
    reg_path.write_text("claims: [{{{ not: yaml\n", encoding="utf-8")
    before = {"C-1": "OPEN"}
    ok, reason = worker_budget.compare_register_change_proven_gate(
        reg_path, before, "kunglao-orch", ws / "facts")
    assert not ok, f"unreadable register must fail closed: {reason}"
    assert "unreadable" in reason


def test_hook_blocks_proven_when_gate_raises(ws_factory, monkeypatch):
    """A raising BLIND gate blocks the direct edit instead of crashing open."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1", "C-1")
    reg_path = _proven_via_direct_edit(ws)
    before = {"C-1": "OPEN"}
    _raising_checker(monkeypatch, "blind_gate", "check_proven_gate",
                     RuntimeError("boom"))
    ok, reason = worker_budget.compare_register_change_proven_gate(
        reg_path, before, "kunglao-orch", ws / "facts")
    assert not ok, f"raising gate must block the edit: {reason}"


# =====================================================================
# kunglao_verify disasm post-gate — never ok:true when it did not run
# =====================================================================

def _passing_fact(ws: Path, fact_id: str) -> Path:
    f = ws / "facts" / f"{fact_id}.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(
        f"---\nid: {fact_id}\nclaim: C-1\n"
        "reproduce: 'import struct; print(hex(0x5A4D))'\n"
        "expected: '0x5a4d'\n---\n",
        encoding="utf-8")
    return f


def test_verify_disasm_checker_unavailable_is_non_passing(
        ws_factory, tmp_path, monkeypatch):
    """Supplied binary + unavailable disasm checker -> NEVER disasm.ok=true."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _passing_fact(ws, "F-001")
    binary = tmp_path / "sample.bin"
    binary.write_bytes(b"MZ\x90\x00")
    _unavailable(monkeypatch, "disasm_constant_check")
    out = kunglao_verify.verify(ws, "F-001", binary_path=binary)
    assert out["disasm"]["ok"] is False, \
        f"unavailable checker must never serialize ok=true: {out['disasm']}"
    assert out["overall"] != "VERIFIED", \
        f"unavailable required gate must downgrade overall: {out['overall']}"
    receipt = out["disasm"]
    for key in ("state", "checker", "checker_version", "error_class", "reason"):
        assert key in receipt, f"audit receipt missing {key}: {receipt}"


def test_verify_disasm_checker_raises_is_non_passing(
        ws_factory, tmp_path, monkeypatch):
    """Checker exception on a supplied binary -> ok=false + error_class."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _passing_fact(ws, "F-001")
    binary = tmp_path / "sample.bin"
    binary.write_bytes(b"MZ\x90\x00")
    _raising_checker(monkeypatch, "disasm_constant_check", "check_fact_disasm",
                     RuntimeError("boom: gate crashed"))
    out = kunglao_verify.verify(ws, "F-001", binary_path=binary)
    assert out["disasm"]["ok"] is False
    assert out["disasm"]["error_class"] == "RuntimeError"
    assert out["overall"] != "VERIFIED"


def test_verify_without_binary_skips_gate(ws_factory):
    """No binary_path -> no disasm key, unchanged behavior (regression)."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _passing_fact(ws, "F-001")
    out = kunglao_verify.verify(ws, "F-001")
    assert "disasm" not in out
    assert out["overall"] == "VERIFIED"


def test_verify_already_rejected_keeps_rejected(ws_factory, tmp_path, monkeypatch):
    """overall already REJECTED (L1 FAIL) stays REJECTED, receipt still recorded."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    f = ws / "facts" / "F-002.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("---\nid: F-002\nclaim: C-1\nreproduce: ''\nexpected: ''\n---\n",
                 encoding="utf-8")
    binary = tmp_path / "sample.bin"
    binary.write_bytes(b"MZ\x90\x00")
    _unavailable(monkeypatch, "disasm_constant_check")
    out = kunglao_verify.verify(ws, "F-002", binary_path=binary)
    assert out["overall"] == "REJECTED"
    assert out["disasm"]["ok"] is False


# =====================================================================
# Mutation sweep: no terminal state under any unavailability
# =====================================================================

def test_claim_migrator_terminal_not_written_when_blind_gate_missing(
        ws_factory, monkeypatch):
    """PROVEN (the gated terminal target) is not written when BLIND is missing."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1", "C-1")
    _unavailable(monkeypatch, "blind_gate")
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
    assert not ok, f"PROVEN must not be written when BLIND gate missing: {msg}"
    assert _register_status(ws, "C-1") == "OPEN"


def test_verify_verified_not_written_when_disasm_checker_missing(
        ws_factory, tmp_path, monkeypatch):
    """VERIFIED overall is not produced when the disasm checker is missing."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _passing_fact(ws, "F-001")
    binary = tmp_path / "sample.bin"
    binary.write_bytes(b"MZ\x90\x00")
    _unavailable(monkeypatch, "disasm_constant_check")
    out = kunglao_verify.verify(ws, "F-001", binary_path=binary)
    assert out["overall"] != "VERIFIED"


# =====================================================================
# Regression: available-checker paths are unchanged
# =====================================================================

def test_claim_migrator_proven_with_valid_signoff_still_promotes(ws_factory):
    """All gates available + valid sign-off -> PROVEN (regression)."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1", "C-1")
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
    assert ok, msg
    assert _register_status(ws, "C-1") == "PROVEN"


def test_claim_migrator_proven_without_signoff_still_downgrades(ws_factory):
    """All gates available + missing sign-off -> STAMP downgrade (regression)."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    (ws / "facts").mkdir()
    (ws / "facts" / "C-1.md").write_text("---\nid: C-1\nclaim: C-1\n---\n",
                                         encoding="utf-8")
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "PROVEN", "orchestrator")
    assert ok, "downgrade is a success (register updated to STAMP)"
    assert "STAMP" in msg
    assert _register_status(ws, "C-1") == "STAMP"


def test_hook_allows_proven_with_all_gates_available(ws_factory):
    """Direct edit to PROVEN with valid sign-off + all gates -> allowed."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _signoff_fact(ws, "C-1", "C-1")
    reg_path = _proven_via_direct_edit(ws)
    before = {"C-1": "OPEN"}
    ok, reason = worker_budget.compare_register_change_proven_gate(
        reg_path, before, "kunglao-orch", ws / "facts")
    assert ok, f"valid PROVEN edit must pass when gates available: {reason}"


def test_hook_passes_through_when_no_promotion(ws_factory):
    """No newly-PROVEN claim -> pass through regardless of gate availability."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    before = {"C-1": "OPEN"}
    ok, reason = worker_budget.compare_register_change_proven_gate(
        ws / "claim-register.yaml", before, "kunglao-orch", ws / "facts")
    assert ok, reason
