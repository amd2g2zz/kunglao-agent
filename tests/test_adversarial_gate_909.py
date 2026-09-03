# -*- coding: utf-8 -*-
"""#909: check_adversarial_gate — the signature-gate teeth.

The verdict-scorer's signature is the LAST line of defense for PROVEN
promotion. Issue #909: before signing, the scorer must consume the
ORCHESTRATOR-SUMMARY of the claim's adversarial ledger (not the raw
ledger state a worker could rewrite) and REFUSE to sign while:

  - an open (un-rebutted) challenge exists, or
  - the adversarial chain is broken (tamper evidence), or
  - the summary fails authentication (worker forged it with the wrong
    key — the trust root is the orchestrator's HMAC key, never the
    ledger state).

Gate shape mirrors blind_gate.check_proven_gate: (allowed, verdict,
reason) where verdict is the scorer's decision vocabulary
('SIGNED' | 'BLOCKED'). The gate is MECHANICAL, not discretionary:
the scorer has no override path, exactly like check_proven_gate has
no override for promotion_attempts.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import challenge_ledger as cl  # noqa: E402
from adversarial_gate import (  # noqa: E402
    check_adversarial_gate, BLOCKED, SIGNED,
)

KEY = b"k" * 32


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs" / "challenges" / "C-12").mkdir(parents=True)
    return ws


def _challenge() -> dict:
    return {
        "kind": "challenge", "id": "CH-1",
        "dimension": "feasibility",
        "dimension_free": "brute-forcing AES-256 needs 2^256 work",
        "target": "assertion-1: recover key by brute force",
        "falsifier": {"cmd": "python tools/entropy.py bins/x.bin",
                      "expect": "space<2^40"},
        "impact": "the whole recovery claim is infeasible",
    }


def test_no_ledger_at_all_signs(tmp_path):
    """A claim that never entered adversarial review — the gate is
    transparent (sign-off proceeds; the adversarial loop never opened)."""
    ws = _ws(tmp_path)
    allowed, verdict, reason = check_adversarial_gate("C-99", ws, key=KEY)
    assert allowed is True and verdict == SIGNED


def test_open_challenge_blocks_signing(tmp_path):
    ws = _ws(tmp_path)
    cl.begin_claim(ws, "C-12", assertion_text="A", key=KEY)
    cl.append_event(ws, "C-12", _challenge(), key=KEY)
    summary = cl.summary(ws, "C-12", key=KEY)
    allowed, verdict, reason = check_adversarial_gate(
        "C-12", ws, key=KEY, summary=summary)
    assert allowed is False and verdict == BLOCKED
    assert "CH-1" in reason


def test_rebutted_challenge_signs(tmp_path):
    ws = _ws(tmp_path)
    cl.begin_claim(ws, "C-12", assertion_text="A", key=KEY)
    cl.append_event(ws, "C-12", _challenge(), key=KEY)
    cl.append_event(ws, "C-12",
                    {"kind": "rebuttal", "id": "RB-1", "rebutts": "CH-1",
                     "new_evidence": {"cmd": "python tools/weakrng.py"},
                     "argument": "key space is 2^32 via weak RNG"},
                    key=KEY)
    summary = cl.summary(ws, "C-12", key=KEY)
    allowed, verdict, reason = check_adversarial_gate(
        "C-12", ws, key=KEY, summary=summary)
    assert allowed is True and verdict == SIGNED


def test_forged_summary_rejected(tmp_path):
    """The worker-forgery attack (#909 layer 2): a summary minted with
    a worker-known key must be REJECTED even though its ledger state
    says 'all clear'."""
    ws = _ws(tmp_path)
    cl.begin_claim(ws, "C-12", assertion_text="A", key=KEY)
    cl.append_event(ws, "C-12", _challenge(), key=KEY)
    worker_forge = cl.summary(ws, "C-12", key=b"worker-knows" + b"x" * 19)
    allowed, verdict, reason = check_adversarial_gate(
        "C-12", ws, key=KEY, summary=worker_forge)
    assert allowed is False and verdict == BLOCKED
    assert "auth" in reason.lower()


def test_tampered_chain_blocks(tmp_path):
    ws = _ws(tmp_path)
    cl.begin_claim(ws, "C-12", assertion_text="A", key=KEY)
    cl.append_event(ws, "C-12", _challenge(), key=KEY)
    cl.append_event(ws, "C-12",
                    {"kind": "rebuttal", "id": "RB-1", "rebutts": "CH-1",
                     "new_evidence": {"cmd": "python tools/weakrng.py"},
                     "argument": "ok"},
                    key=KEY)
    # tamper round-1
    rp = cl.rounds(ws, "C-12")[0]
    doc = json.loads(rp.read_text(encoding="utf-8"))
    doc["events"][0]["id"] = "CH-REWRITTEN"
    rp.write_text(json.dumps(doc), encoding="utf-8")
    summary = cl.summary(ws, "C-12", key=KEY)
    allowed, verdict, reason = check_adversarial_gate(
        "C-12", ws, key=KEY, summary=summary)
    assert allowed is False and verdict == BLOCKED
    assert "chain" in reason.lower()


def test_gate_has_no_summary_means_unopened(tmp_path):
    """Ledger exists but caller passed no summary and no claim path:
    the gate reads it itself (orchestrator-side usage), so a missing
    summary argument is fine when the ledger is empty/unopened."""
    ws = _ws(tmp_path)
    allowed, verdict, _ = check_adversarial_gate("C-55", ws, key=KEY)
    assert allowed is True and verdict == SIGNED
