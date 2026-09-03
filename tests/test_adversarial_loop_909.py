# -*- coding: utf-8 -*-
"""#909: adversarial_loop — orchestrator-side process CLI.

Covers the issue-909 process rulings end to end:

  1. contest phase — rounds 1-5 are challenge<->rebuttal only; arbitration
     before round 5 is refused (exit 5, "stalemate arbitration requires
     5 rounds");
  2. stalemate — at 5 rounds the orchestrator arbitrates; outcome=rebutted
     clears the open-challenge set;
  3. outcome=upheld does NOT clear open challenges (ledger semantics:
     only outcome=rebutted clears — open_challenges still lists them, and
     the signature gate then BLOCKS: the upheld->FAILED path);
  4. verify-run is the on-demand summons face: ONE disputed falsifier
     command, timeout-capped, packaged as a verifier_call event JSON the
     orchestrator can file via `verifier-call`;
  5. the HMAC key is never printed (any command, stdout or stderr);
  6. ledger rejections map to named exit codes (InvalidEvent -> 2).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import adversarial_loop as al  # noqa: E402

KEY = b"adversarial-loop-test-key-0123456789abcdef"


@pytest.fixture
def kf(tmp_path: Path) -> Path:
    p = tmp_path / "orchestrator.key"
    p.write_bytes(KEY)
    return p


def _call(kf: Path, capsys, *args: str):
    """Run one CLI invocation; drain and parse its stdout JSON."""
    rc = al.main(["--keyfile", str(kf), *args])
    cap = capsys.readouterr()
    doc = json.loads(cap.out) if cap.out.strip() else None
    return rc, doc, cap.err


def _ev_file(tmp_path: Path, name: str, ev: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(ev), encoding="utf-8")
    return p


def _challenge(cid: str = "CH-1") -> dict:
    return {"kind": "challenge", "id": cid,
            "dimension": "counterexample",
            "dimension_free": "DES xref present while AES xref is zero",
            "target": "assertion-2: cipher is AES-256-CBC",
            "falsifier": {"cmd": "echo hits", "expect": "hits>=1"},
            "impact": "if true, the cipher conclusion fails"}


def _rebuttal(rid: str, ch: str) -> dict:
    return {"kind": "rebuttal", "id": rid, "rebutts": ch,
            "new_evidence": {"artifact": "evidence/F-77.md"},
            "argument": "xref hits come from the DES reference table"}


def _push_5_rounds(tmp_path: Path, kf: Path, ws: Path, capsys) -> None:
    _call(kf, capsys, "begin", str(ws), "C-12",
          "--assertion", "cipher is AES-256-CBC")
    seq = [_challenge("CH-1"), _rebuttal("RB-1", "CH-1"),
           _challenge("CH-2"), _rebuttal("RB-2", "CH-2"),
           _challenge("CH-3")]
    for i, ev in enumerate(seq):
        f = _ev_file(tmp_path, f"ev{i}.json", ev)
        rc, _, err = _call(kf, capsys, ev["kind"], str(ws), "C-12",
                           "--file", str(f))
        assert rc == 0, err


# ---- 1. contest phase: no per-round verdict, arbitration gated ----

def test_contest_phase_arbitration_refused_before_round_5(tmp_path, kf, capsys):
    ws = tmp_path / "ws"
    rc, _, err = _call(kf, capsys, "begin", str(ws), "C-12", "--assertion", "A")
    assert rc == al.EXIT_OK, err
    f = _ev_file(tmp_path, "ch1.json", _challenge())
    rc, _, err = _call(kf, capsys, "challenge", str(ws), "C-12",
                       "--file", str(f))
    assert rc == al.EXIT_OK, err
    rc, out, err = _call(kf, capsys, "status", str(ws), "C-12")
    assert rc == al.EXIT_OK, err
    assert out["rounds"] == 1
    assert out["open_challenges"] == ["CH-1"]
    assert out["chain_ok"] is True
    assert "hmac" not in out  # status never echoes the summary hmac
    rc, out, err = _call(kf, capsys, "arbitrate", str(ws), "C-12",
                         "--outcome", "rebutted", "--basis", "CH-1")
    assert rc == al.EXIT_EARLY_ARBITRATION == 5
    assert out["reason"] == al.PREMATURE_REASON


# ---- 2. stalemate: arbitration at round 5+, rebutted clears ----

def test_stalemate_at_5_rounds_rebutted_clears(tmp_path, kf, capsys):
    ws = tmp_path / "ws"
    _push_5_rounds(tmp_path, kf, ws, capsys)
    rc, out, err = _call(kf, capsys, "arbitrate", str(ws), "C-12",
                         "--outcome", "rebutted", "--basis", "CH-3,RB-2")
    assert rc == al.EXIT_OK, err
    assert out["open_challenges_after"] == []
    rc, out, err = _call(kf, capsys, "status", str(ws), "C-12")
    assert rc == al.EXIT_OK, err
    assert out["rounds"] == 6
    assert out["open_challenges"] == []
    assert out["chain_ok"] is True


# ---- 3. upheld does NOT clear the open set (ledger semantics) ----

def test_upheld_keeps_open_challenges_listed(tmp_path, kf, capsys):
    """Only outcome=rebutted clears the open set
    (challenge_ledger.open_challenges); upheld leaves the challenges
    listed — the signature gate then BLOCKS them, which IS the
    upheld->FAILED path."""
    ws = tmp_path / "ws"
    _push_5_rounds(tmp_path, kf, ws, capsys)
    rc, out, err = _call(kf, capsys, "arbitrate", str(ws), "C-12",
                         "--outcome", "upheld", "--basis", "CH-3")
    assert rc == al.EXIT_OK, err
    assert out["open_challenges_after"] == ["CH-3"]
    rc, out, err = _call(kf, capsys, "status", str(ws), "C-12")
    assert rc == al.EXIT_OK, err
    assert out["open_challenges"] == ["CH-3"]
    r6 = json.loads(
        (ws / "runs" / "challenges" / "C-12" / "round-6.json")
        .read_text(encoding="utf-8"))
    assert r6["events"][0]["outcome"] == "upheld"
    assert r6["events"][0]["round_final"] is True


# ---- 4. verify-run: the on-demand verifier summons face ----

def test_verify_run_packages_finding_and_files_it(tmp_path, kf, capsys):
    ws = tmp_path / "ws"
    _call(kf, capsys, "begin", str(ws), "C-12", "--assertion", "A")
    rc, ev, err = _call(kf, capsys, "verify-run", str(ws), "C-12", "echo hits")
    assert rc == 0, err
    assert ev["kind"] == "verifier_call" and ev["id"]
    assert ev["finding"]["rc"] == 0 and "hits" in ev["finding"]["stdout"]
    assert ev["finding"]["timed_out"] is False
    # the orchestrator files the finding via verifier-call
    f = _ev_file(tmp_path, "vc.json", ev)
    rc, _, err = _call(kf, capsys, "verifier-call", str(ws), "C-12",
                       "--file", str(f))
    assert rc == 0, err
    # a failing falsifier is a FINDING, not a CLI failure
    rc, ev3, err = _call(kf, capsys, "verify-run", str(ws), "C-12", "exit 3")
    assert rc == 0, err
    assert ev3["finding"]["rc"] == 3
    # timeout honored
    t0 = time.monotonic()
    rc, evt, err = _call(kf, capsys, "verify-run", str(ws), "C-12",
                         "sleep 5", "--timeout", "1")
    elapsed = time.monotonic() - t0
    assert rc == 0, err
    assert evt["finding"]["timed_out"] is True
    assert evt["finding"]["duration_sec"] < 2, (
        "timeout=1 must surface a <2s duration_sec, not wall-clock drift")
    assert elapsed < 4


# ---- 5. the key never reaches stdout/stderr ----

def test_key_never_printed(tmp_path, kf, capsys):
    """Leak check accumulates EVERY invocation's output — each _call drains
    capsys, so a trailing readouterr() would always see an empty buffer
    (vacuous pass). The key material must appear nowhere across the whole
    begin/challenge/status/verify-run/arbitrate surface."""
    ws = tmp_path / "ws"
    leaked = []

    def drain(rc, out, err):
        leaked.append(out if isinstance(out, str) else json.dumps(out or ""))
        leaked.append(err)
        return rc

    drain(*_call(kf, capsys, "begin", str(ws), "C-12", "--assertion", "A"))
    f = _ev_file(tmp_path, "ch.json", _challenge())
    drain(*_call(kf, capsys, "challenge", str(ws), "C-12", "--file", str(f)))
    drain(*_call(kf, capsys, "status", str(ws), "C-12"))
    drain(*_call(kf, capsys, "verify-run", str(ws), "C-12", "echo hits"))
    drain(*_call(kf, capsys, "arbitrate", str(ws), "C-12",
                 "--outcome", "rebutted", "--basis", "CH-1"))
    all_output = "\n".join(leaked)
    assert KEY.decode() not in all_output


# ---- 6. ledger rejections map to exit codes ----

def test_invalid_event_maps_to_exit_2(tmp_path, kf, capsys):
    ws = tmp_path / "ws"
    _call(kf, capsys, "begin", str(ws), "C-12", "--assertion", "A")
    bad = _challenge()
    del bad["falsifier"]  # grounding violation: no falsifier, no entry
    f = _ev_file(tmp_path, "bad.json", bad)
    rc, _, _ = _call(kf, capsys, "challenge", str(ws), "C-12",
                     "--file", str(f))
    assert rc == 2
    # challenge against an unopened ledger is also an InvalidEvent
    f2 = _ev_file(tmp_path, "ch9.json", _challenge("CH-9"))
    rc, _, _ = _call(kf, capsys, "challenge", str(ws), "C-99",
                     "--file", str(f2))
    assert rc == 2
    # rejected events burned no round
    rc, out, _ = _call(kf, capsys, "status", str(ws), "C-12")
    assert rc == 0
    assert out["rounds"] == 0


# ---- extras: cap mapping + closed-ledger guard ----

def test_post_stalemate_contest_write_is_round_capped(tmp_path, kf, capsys):
    ws = tmp_path / "ws"
    _push_5_rounds(tmp_path, kf, ws, capsys)
    _call(kf, capsys, "arbitrate", str(ws), "C-12", "--outcome", "rebutted",
          "--basis", "CH-3")
    f = _ev_file(tmp_path, "late.json", _challenge("CH-9"))
    rc, _, _ = _call(kf, capsys, "challenge", str(ws), "C-12",
                     "--file", str(f))
    assert rc == 4


def test_double_arbitration_refused(tmp_path, kf, capsys):
    ws = tmp_path / "ws"
    _push_5_rounds(tmp_path, kf, ws, capsys)
    rc, _, _ = _call(kf, capsys, "arbitrate", str(ws), "C-12",
                     "--outcome", "rebutted", "--basis", "CH-3")
    assert rc == 0
    # double arbitration is now guarded by the DATA layer: append_event
    # raises InvalidEvent (exit 2) on a second round_final — one guard,
    # one owner (the CLI pre-check was a drifted duplicate)
    rc, _, err = _call(kf, capsys, "arbitrate", str(ws), "C-12",
                       "--outcome", "upheld", "--basis", "CH-3")
    assert rc == al.EXIT_INVALID_EVENT
    assert "final arbitration" in err
