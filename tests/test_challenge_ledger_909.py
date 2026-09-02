# -*- coding: utf-8 -*-
"""#909: challenge_ledger — adversarial-loop data layer.

Issue #909 (user rulings 2026-09-03): the maker-checker loop is in GAN
collapse — redteam's cheapest PASS is replaying the worker's own path.
This ledger is the DATA LAYER of the fix: structured challenges with a
hard grounding requirement (no falsifier, no entry, no round cost),
append-only rounds chained by HMAC, an assertion freeze that makes
moving-the-goalposts detectable, and an orchestrator-side summary whose
trust root (the HMAC key) is unreachable from the worker's process
context — so a worker that reverse-engineers every validation rule
still cannot forge a resolved state (#909 anti-forgery layer 2).

Design rulings baked into these tests:
  - a challenge WITHOUT a falsifier is rejected at write time (it never
    enters the ledger, so it never burns a round);
  - the dimension tag is a FREE label plus a one-line self-description
    (machine validates structure, never vocabulary — the attack surface
    is an open set, the user's examples were illustrations);
  - the assertion snapshot taken at round 1 must match at every later
    write: a worker that edits its claim mid-battle gets REJECTED and
    must re-file as a new claim;
  - round files are append-only (write-once per round) and chained
    (each round signs the previous round's file sha);
  - the orchestrator summary needs the key; a worker-side forger with
    the wrong key produces a summary the gate rejects.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import challenge_ledger as cl  # noqa: E402
from adversarial_gate import check_adversarial_gate, BLOCKED  # noqa: E402

KEY = b"k" * 32


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs" / "challenges" / "C-12").mkdir(parents=True)
    return ws


def _valid_challenge() -> dict:
    return {
        "kind": "challenge",
        "id": "CH-1",
        "dimension": "counterexample",
        "dimension_free": "DES xref present while AES xref is zero",
        "target": "assertion-2: cipher is AES-256-CBC",
        "falsifier": {"cmd": "python tools/xref.py DES bins/x.bin",
                      "expect": "hits>=1"},
        "impact": "if true, the AES conclusion and key-derivation chain fail",
    }


def test_challenge_without_falsifier_rejected(tmp_path):
    """No falsifier -> the challenge never enters the ledger (a
    hand-wavy 'please double-check' must not burn a round)."""
    ws = _ws(tmp_path)
    bad = _valid_challenge()
    del bad["falsifier"]
    try:
        cl.append_event(ws, "C-12", bad, key=b"k" * 32)
    except cl.InvalidEvent:
        pass
    else:
        raise AssertionError("falsifier-less challenge accepted")
    assert cl.rounds(ws, "C-12") == []


def test_round1_writes_snapshot_and_hmac_chain(tmp_path):
    ws = _ws(tmp_path)
    key = KEY
    cl.begin_claim(ws, "C-12",
                   assertion_text="cipher is AES-256-CBC; key from argv",
                   key=key)
    cl.append_event(ws, "C-12", _valid_challenge(), key=key)
    rounds = cl.rounds(ws, "C-12")
    assert len(rounds) == 1
    doc = json.loads(rounds[0].read_text(encoding="utf-8"))
    assert doc["assertion_snapshot_sha"]
    # the chain anchors to the meta (snapshot) file bytes — stronger than
    # null: forging meta.json breaks every downstream link
    import hashlib
    meta_sha = hashlib.sha256(
        (ws / "runs" / "challenges" / "C-12" / "meta.json").read_bytes()
    ).hexdigest()
    assert doc["prev_round_sha"] == meta_sha
    assert doc["hmac"]


def test_assertion_drift_rejected(tmp_path):
    """Moving the goalposts: claim text changed mid-battle -> the write
    is rejected and the worker must re-file as a NEW claim."""
    ws = _ws(tmp_path)
    key = KEY
    cl.begin_claim(ws, "C-12", assertion_text="cipher is AES-256-CBC",
                   key=key)
    cl.append_event(ws, "C-12", _valid_challenge(), key=key)
    # the worker quietly weakens its claim ("suspected AES") ...
    try:
        cl.append_event(ws, "C-12",
                        {"kind": "rebuttal", "id": "RB-1", "rebutts": "CH-1",
                         "new_evidence": {"artifact": "evidence/F-77.md"},
                         "argument": "..."},
                        key=key,
                        assertion_text="cipher is *suspected* AES-256-CBC")
    except cl.AssertionDrift:
        pass
    else:
        raise AssertionError("assertion drift accepted")


def test_rebuttal_must_reference_challenge(tmp_path):
    ws = _ws(tmp_path)
    key = KEY
    cl.begin_claim(ws, "C-12", assertion_text="A", key=key)
    cl.append_event(ws, "C-12", _valid_challenge(), key=key)
    orphan = {"kind": "rebuttal", "id": "RB-9", "rebutts": "CH-404",
              "new_evidence": {"artifact": "evidence/x.md"},
              "argument": "..."}
    try:
        cl.append_event(ws, "C-12", orphan, key=key)
    except cl.InvalidEvent:
        pass
    else:
        raise AssertionError("rebuttal referencing unknown challenge accepted")


def test_chain_tamper_detected(tmp_path):
    """Rewriting round-1 after round-2 exists -> chain validation fails
    (append-only + prev_round_sha chaining)."""
    ws = _ws(tmp_path)
    key = KEY
    cl.begin_claim(ws, "C-12", assertion_text="A", key=key)
    cl.append_event(ws, "C-12", _valid_challenge(), key=key)
    cl.append_event(ws, "C-12",
                    {"kind": "rebuttal", "id": "RB-1", "rebutts": "CH-1",
                     "new_evidence": {"artifact": "evidence/x.md"},
                     "argument": "..."},
                    key=key)
    rounds = cl.rounds(ws, "C-12")
    doc = json.loads(rounds[0].read_text(encoding="utf-8"))
    # forge a friendlier round-1 ...
    doc["events"][0]["impact"] = "(forged: harmless)"
    rounds[0].write_text(json.dumps(doc), encoding="utf-8")
    ok, why = cl.verify_chain(ws, "C-12", key=key)
    assert not ok, "tampered chain passed verification"
    assert "round-1" in why or "sha" in why.lower()


def test_summary_needs_the_key(tmp_path):
    """The anti-forgery trust root: the signature gate authenticates the
    summary with ITS OWN key (authenticate_summary). A worker-side forger
    that read this module and mints a summary with the wrong key fails
    authentication — knowing the algorithm is worthless without the key."""
    ws = _ws(tmp_path)
    real_key = b"k" * 32
    cl.begin_claim(ws, "C-12", assertion_text="A", key=real_key)
    cl.append_event(ws, "C-12", _valid_challenge(), key=real_key)
    good = cl.summary(ws, "C-12", key=real_key)
    assert cl.authenticate_summary(good, key=real_key) is True
    assert good["open_challenges"] == ["CH-1"]
    assert good["chain_ok"] is True
    # the forgery: same code path, wrong (worker-known) key
    forged = cl.summary(ws, "C-12", key=b"f" * 32)
    assert cl.authenticate_summary(forged, key=real_key) is False
    # a hand-crafted "all clear" doc with no valid hmac also fails
    naked = {"claim": "C-12", "rounds": 0, "chain_ok": True,
             "chain_why": "ok", "open_challenges": []}
    assert cl.authenticate_summary(naked, key=real_key) is False


def test_round_cap_enforced(tmp_path):
    """MAX_ADVERSARIAL_ROUNDS is a hard gate: appending to round 6 is
    refused — nobody configures their way past the user's '最大最大5轮'."""
    ws = _ws(tmp_path)
    key = KEY
    cl.begin_claim(ws, "C-12", assertion_text="A", key=key)
    for _ in range(cl.MAX_ADVERSARIAL_ROUNDS):
        cl.append_event(ws, "C-12", _valid_challenge(), key=key)
    # rounds are advanced explicitly; simulate the cap by forcing the
    # active round counter to the max
    cl._set_active_round(ws, "C-12", cl.MAX_ADVERSARIAL_ROUNDS + 1)
    try:
        cl.append_event(ws, "C-12", _valid_challenge(), key=key)
    except cl.RoundCapExceeded:
        pass
    else:
        raise AssertionError("round 6 accepted")


# ---- reviewer-909 security findings: H1/H2/H3/H4 regression locks ----

def _valid_arbitration() -> dict:
    return {"kind": "arbitration", "round_final": True,
            "outcome": "rebutted", "basis": ["RB-1"]}


def test_h1_tail_forged_arbitration_rejected(tmp_path):
    """H1: fabricating a tail-round arbitration (outcome=rebutted) with
    a WRONG key must fail verify_chain — the chain must authenticate
    every round's hmac, not just forward-link them."""
    ws = _ws(tmp_path)
    key = KEY
    cl.begin_claim(ws, "C-12", assertion_text="A", key=key)
    cl.append_event(ws, "C-12", _valid_challenge(), key=key)
    cl.append_event(ws, "C-12",
                    {"kind": "rebuttal", "id": "RB-1", "rebutts": "CH-1",
                     "new_evidence": {"cmd": "x"}, "argument": "ok"},
                    key=key)
    # attacker (worker, no key) appends a "cleared" tail round
    d = ws / "runs" / "challenges" / "C-12"
    prev = cl.rounds(ws, "C-12")[-1]
    forged = {"round": 3, "claim": "C-12",
              "assertion_snapshot_sha": "x", "prev_round_sha":
              hashlib.sha256(prev.read_bytes()).hexdigest(),
              "events": [_valid_arbitration()],
              "hmac": "00" * 32}
    (d / "round-3.json").write_text(json.dumps(forged), encoding="utf-8")
    cl._set_active_round(ws, "C-12", 3)
    ok, why = cl.verify_chain(ws, "C-12", key=key)
    assert not ok, "forged tail round passed chain verification"
    assert "round-3" in why


def test_h2_full_refabrication_needs_key(tmp_path):
    """H2: refabricating meta + all rounds with recomputed links but NO
    key must fail — every round's hmac is verified against the key."""
    ws = _ws(tmp_path)
    key = KEY
    cl.begin_claim(ws, "C-12", assertion_text="A", key=key)
    cl.append_event(ws, "C-12", _valid_challenge(), key=key)
    # attacker rewrites history without the key (recomputes prev links)
    d = ws / "runs" / "challenges" / "C-12"
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    meta["assertion_snapshot_sha"] = hashlib.sha256(b"WEAK").hexdigest()
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    r1 = json.loads((d / "round-1.json").read_text(encoding="utf-8"))
    r1["prev_round_sha"] = hashlib.sha256(
        (d / "meta.json").read_bytes()).hexdigest()
    (d / "round-1.json").write_text(json.dumps(r1), encoding="utf-8")
    ok, why = cl.verify_chain(ws, "C-12", key=key)
    assert not ok, "refabricated history passed verification"


def test_h3_stale_summary_replayed(tmp_path):
    """H3: a legitimately minted all-clear summary must NOT stay valid
    after new challenges land — the summary binds the ledger head."""
    ws = _ws(tmp_path)
    key = KEY
    cl.begin_claim(ws, "C-12", assertion_text="A", key=key)
    cl.append_event(ws, "C-12", _valid_challenge(), key=key)
    cl.append_event(ws, "C-12",
                    {"kind": "rebuttal", "id": "RB-1", "rebutts": "CH-1",
                     "new_evidence": {"cmd": "x"}, "argument": "ok"},
                    key=key)
    stale_clear = cl.summary(ws, "C-12", key=key)   # genuinely valid NOW
    assert cl.authenticate_summary(stale_clear, key=key)
    # ... then a NEW challenge lands
    ch2 = dict(_valid_challenge(), id="CH-2")
    cl.append_event(ws, "C-12", ch2, key=key)
    # replaying the stale all-clear must fail authentication
    assert not cl.authenticate_summary(stale_clear, key=key, ws=ws, claim="C-12"), \
        "stale summary replay accepted (H3)"


def test_h4_ledger_deletion_flips_to_unopened(tmp_path):
    """H4: rm -rf runs/challenges/<claim>/ makes the gate say 'loop
    never opened'. The claim register mirror is the cross-check (the
    gate must receive opened=True from the orchestrator's register
    view); until wiring, the gate API accepts opened_hint and refuses
    to sign when the register says the loop opened but no ledger exists."""
    ws = _ws(tmp_path)
    cl.begin_claim(ws, "C-12", assertion_text="A", key=KEY)
    # deletion
    import shutil
    shutil.rmtree(ws / "runs" / "challenges" / "C-12")
    allowed, verdict, reason = check_adversarial_gate(
        "C-12", ws, key=KEY, opened_hint=True)
    assert allowed is False and verdict == BLOCKED
    assert "deleted" in reason.lower() or "opened" in reason.lower()


# ---- reviewer round-2 findings: H5/H6/H7/H8 regression locks ----

def test_h5_truncate_to_empty_rejected(tmp_path):
    """H5: delete all round files but keep dir+meta. The register
    anchor (opened_hint carries max_rounds_seen) must catch the
    truncation: the summary's rounds count is lower than the register's
    monotonic record -> gate BLOCKED."""
    ws = _ws(tmp_path)
    cl.begin_claim(ws, "C-12", assertion_text="A", key=KEY)
    cl.append_event(ws, "C-12", _valid_challenge(), key=KEY)
    for rp in cl.rounds(ws, "C-12"):
        rp.unlink()
    summary = cl.summary(ws, "C-12", key=KEY)
    from adversarial_gate import check_adversarial_gate, BLOCKED
    allowed, verdict, reason = check_adversarial_gate(
        "C-12", ws, key=KEY, summary=summary,
        opened_hint=True, opened_max_rounds=1)
    assert allowed is False and verdict == BLOCKED
    assert "round" in reason.lower() or "truncat" in reason.lower()


def test_h6_head_rollback_rejected(tmp_path):
    """H6: delete the newest round + rewind .active-round so a stale
    all-clear summary's head_sha matches again. Defense: summary also
    binds rounds-count via the register anchor (monotonic), and
    .active-round may only move FORWARD (rewind detected)."""
    ws = _ws(tmp_path)
    cl.begin_claim(ws, "C-12", assertion_text="A", key=KEY)
    cl.append_event(ws, "C-12", _valid_challenge(), key=KEY)
    cl.append_event(ws, "C-12",
                    {"kind": "rebuttal", "id": "RB-1", "rebutts": "CH-1",
                     "new_evidence": {"cmd": "x"}, "argument": "ok"},
                    key=KEY)
    stale_clear = cl.summary(ws, "C-12", key=KEY)  # rounds=2 all-clear
    # attacker: new challenge lands, then roll everything back
    ch2 = dict(_valid_challenge(), id="CH-2")
    cl.append_event(ws, "C-12", ch2, key=KEY)
    cl.rounds(ws, "C-12")[-1].unlink()
    cl._set_active_round(ws, "C-12", 2)
    # freshness check against the ROLLBACK state would pass head_sha...
    # so the gate must also compare against the register's monotonic
    # rounds record: 3 > 2 -> rejected.
    from adversarial_gate import check_adversarial_gate, BLOCKED
    allowed, verdict, reason = check_adversarial_gate(
        "C-12", ws, key=KEY,
        summary=cl.summary(ws, "C-12", key=KEY),
        opened_hint=True, opened_max_rounds=3)
    assert allowed is False and verdict == BLOCKED


def test_h7_meta_hmac_verified(tmp_path):
    """H7: meta.json's own hmac was never checked -> a pre-round-1
    rewrite of assertion_snapshot_sha voided the freeze. verify_chain
    must authenticate meta's round-0 hmac."""
    ws = _ws(tmp_path)
    cl.begin_claim(ws, "C-12", assertion_text="A", key=KEY)
    d = ws / "runs" / "challenges" / "C-12"
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    meta["assertion_snapshot_sha"] = hashlib.sha256(b"WEAK").hexdigest()
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    ok, why = cl.verify_chain(ws, "C-12", key=KEY)
    assert not ok, "meta rewrite without key passed"
    assert "meta" in why.lower()


def test_h8_malformed_round_fail_closed(tmp_path):
    """H8: hmac as int / events as non-list must fail CLOSED (gate
    BLOCKED, no exception escapes)."""
    ws = _ws(tmp_path)
    cl.begin_claim(ws, "C-12", assertion_text="A", key=KEY)
    cl.append_event(ws, "C-12", _valid_challenge(), key=KEY)
    rp = cl.rounds(ws, "C-12")[0]
    doc = json.loads(rp.read_text(encoding="utf-8"))
    doc["hmac"] = 12345  # int where hex str belongs
    rp.write_text(json.dumps(doc), encoding="utf-8")
    ok, why = cl.verify_chain(ws, "C-12", key=KEY)
    assert ok is False and why  # malformed -> not-ok, never raises
    # events as dict (not list)
    doc["hmac"] = "ab" * 32
    doc["events"] = {"kind": "challenge"}
    rp.write_text(json.dumps(doc), encoding="utf-8")
    ok, why = cl.verify_chain(ws, "C-12", key=KEY)
    assert ok is False
