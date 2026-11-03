# -*- coding: utf-8 -*-
"""tests/test_challenge_ledger_818.py — the adversarial-loop data layer
on real workspaces (issue #818 coverage climb).

Tamper-evidence is pinned, not simulated: every round is HMAC-chained
through real bytes on a real tmp workspace, and the pins strike the
chain with real edits — forged tails, post-hoc event edits, meta
rewrites, foreign-key summaries, and stale all-clear replays must all
fail closed. The grounding rule, the assertion freeze, the 5-round hard
cap, and the single-final-arbitration guard are exercised through the
write faces' real rejections.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import challenge_ledger as cl  # noqa: E402  (scripts/ on pytest path)

KEY = b"orchestrator-key-0123456789abcdef"


def _challenge(cid="ch-1", dim="constants") -> dict:
    return {"kind": "challenge", "id": cid, "dimension": dim,
            "dimension_free": "the IV hunt ignores the movz immediates",
            "target": "C-1 assertion", "impact": "high",
            "falsifier": {"cmd": "run probe x", "expect": "mismatch"}}


def _rebuttal(rid="rb-1", answers="ch-1") -> dict:
    return {"kind": "rebuttal", "id": rid, "rebutts": answers,
            "new_evidence": {"cmd": "replay pair y"},
            "argument": "the pair replays byte-exact"}


@pytest.fixture
def ws(tmp_path) -> Path:
    w = tmp_path / "ws"
    (w / "runs").mkdir(parents=True)
    return w


def _begin(ws: Path, claim="C-1") -> None:
    cl.begin_claim(ws, claim, assertion_text="the IV is at 0x401000",
                   key=KEY)


# ---------- begin + freeze ----------

def test_begin_claim_freezes_assertion_write_once(ws) -> None:
    _begin(ws)
    meta = json.loads(
        (ws / "runs" / "challenges" / "C-1" / "meta.json")
        .read_text(encoding="utf-8"))
    assert meta["round"] == 0
    assert cl._read_active_round(ws, "C-1") == 0
    # idempotent: a second begin never rewrites the freeze
    cl.begin_claim(ws, "C-1", assertion_text="A DIFFERENT assertion",
                   key=KEY)
    meta2 = json.loads(
        (ws / "runs" / "challenges" / "C-1" / "meta.json")
        .read_text(encoding="utf-8"))
    assert meta == meta2


def test_begin_claim_bad_claim_id_refused(ws) -> None:
    with pytest.raises(cl.InvalidEvent, match="bad claim id"):
        cl.begin_claim(ws, "nope", assertion_text="x", key=KEY)
    with pytest.raises(cl.InvalidEvent):
        cl.append_event(ws, "also-bad", _challenge(), key=KEY)


def test_events_before_begin_are_refused(ws) -> None:
    with pytest.raises(cl.InvalidEvent, match="not initialized"):
        cl.append_event(ws, "C-1", _challenge(), key=KEY)


# ---------- the grounding + validation teeth ----------

def test_ungrounded_challenge_is_rejected(ws) -> None:
    _begin(ws)
    hand_wavy = {"kind": "challenge", "id": "ch-x", "dimension": "d",
                 "dimension_free": "vibes", "target": "C-1",
                 "falsifier": {"cmd": "", "artifact": ""}}
    with pytest.raises(cl.InvalidEvent, match="without a falsifier"):
        cl.append_event(ws, "C-1", hand_wavy, key=KEY)


def test_rebuttal_must_reference_a_known_challenge(ws) -> None:
    _begin(ws)
    with pytest.raises(cl.InvalidEvent, match="unknown challenge"):
        cl.append_event(ws, "C-1", _rebuttal(answers="ch-void"), key=KEY)


def test_full_battle_rounds_chain_and_verify(ws) -> None:
    _begin(ws)
    # one event per round: the challenge opens round 1, the rebuttal
    # chains round 2, the follow-up challenge chains round 3
    r1 = cl.append_event(ws, "C-1", _challenge(), key=KEY)
    assert r1.name == "round-1.json"
    r2 = cl.append_event(ws, "C-1", _rebuttal(), key=KEY)
    assert r2.name == "round-2.json"
    cl.append_event(ws, "C-1", _challenge("ch-2", "lanes"), key=KEY)
    assert cl._read_active_round(ws, "C-1") == 3
    ok, why = cl.verify_chain(ws, "C-1", key=KEY)
    assert (ok, why) == (True, "ok")
    assert len(cl.rounds(ws, "C-1")) == 3
    # ch-1 was answered by the round-2 rebuttal; ch-2 stays open
    oc = cl.open_challenges(ws, "C-1")
    assert [c["id"] for c in oc] == ["ch-2"]


def test_cross_round_rebuttal_is_legal(ws) -> None:
    _begin(ws)
    cl.append_event(ws, "C-1", _challenge(), key=KEY)
    cl.append_event(ws, "C-1", _challenge("ch-2", "lanes"), key=KEY)
    cl.append_event(ws, "C-1", _rebuttal("rb-late", answers="ch-1"), key=KEY)
    oc = cl.open_challenges(ws, "C-1")
    assert [c["id"] for c in oc] == ["ch-2"]


def test_verifier_call_and_unknown_kinds(ws) -> None:
    _begin(ws)
    cl.append_event(ws, "C-1", _challenge(), key=KEY)
    vc = {"kind": "verifier_call", "id": "vc-1", "ref": "ch-1.falsifier",
          "verifier": "replay", "finding": "matches"}
    cl.append_event(ws, "C-1", vc, key=KEY)
    with pytest.raises(cl.InvalidEvent, match="unknown event kind"):
        cl.append_event(ws, "C-1", {"kind": "opinion"}, key=KEY)
    with pytest.raises(cl.InvalidEvent, match="needs id"):
        cl.append_event(ws, "C-1", {"kind": "verifier_call"}, key=KEY)


# ---------- the assertion freeze + round cap ----------

def test_assertion_drift_is_rejected(ws) -> None:
    _begin(ws)
    with pytest.raises(cl.AssertionDrift, match="goalposts"):
        cl.append_event(ws, "C-1", _challenge(),
                        assertion_text="a much weaker claim", key=KEY)


def test_round_cap_is_hard_but_arbitration_stays_writable(ws) -> None:
    _begin(ws)
    for i in range(cl.MAX_ADVERSARIAL_ROUNDS):
        cl.append_event(ws, "C-1", _challenge(f"ch-{i}"), key=KEY)
    assert cl._read_active_round(ws, "C-1") == cl.MAX_ADVERSARIAL_ROUNDS
    with pytest.raises(cl.RoundCapExceeded, match="hard cap"):
        cl.append_event(ws, "C-1", _challenge("ch-over"), key=KEY)
    # the TERMINAL arbitration rides past the cap exactly once
    arb = {"kind": "arbitration", "outcome": "rebutted",
           "round_final": True}
    rp = cl.append_event(ws, "C-1", arb, key=KEY)
    assert rp.name == f"round-{cl.MAX_ADVERSARIAL_ROUNDS + 1}.json"
    with pytest.raises(cl.InvalidEvent, match="final arbitration"):
        cl.append_event(ws, "C-1", arb, key=KEY)
    ok, _ = cl.verify_chain(ws, "C-1", key=KEY)
    assert ok is True
    # a rebutted final arbitration clears the remaining challenges
    assert cl.open_challenges(ws, "C-1") == []


def test_arbitration_outcome_is_validated(ws) -> None:
    _begin(ws)
    with pytest.raises(cl.InvalidEvent, match="upheld|rebutted"):
        cl.append_event(ws, "C-1", {"kind": "arbitration",
                                    "outcome": "vibes"}, key=KEY)


# ---------- tamper faces ----------

def _tail(ws: Path, claim="C-1") -> Path:
    return cl.rounds(ws, claim)[-1]


def test_forged_tail_without_the_key_fails(ws) -> None:
    _begin(ws)
    cl.append_event(ws, "C-1", _challenge(), key=KEY)
    doc = json.loads(_tail(ws).read_text(encoding="utf-8"))
    doc["events"].append(_challenge("ch-forged"))
    _tail(ws).write_text(json.dumps(doc), encoding="utf-8")
    ok, why = cl.verify_chain(ws, "C-1", key=KEY)
    assert ok is False
    assert "hmac authentication failed" in why


def test_posthoc_edit_of_history_breaks_forward_linkage(ws) -> None:
    _begin(ws)
    cl.append_event(ws, "C-1", _challenge(), key=KEY)
    cl.append_event(ws, "C-1", _rebuttal(), key=KEY)
    # edit ROUND 1 after round 2 chained over its bytes
    r1 = cl.rounds(ws, "C-1")[0]
    doc = json.loads(r1.read_text(encoding="utf-8"))
    doc["events"][0]["impact"] = "low"
    r1.write_text(json.dumps(doc), encoding="utf-8")
    ok, why = cl.verify_chain(ws, "C-1", key=KEY)
    assert ok is False
    assert "prev_round_sha mismatch" in why or \
        "hmac authentication failed" in why


def test_meta_rewrite_fails_authentication(ws) -> None:
    _begin(ws)
    meta_path = ws / "runs" / "challenges" / "C-1" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["assertion_snapshot_sha"] = "0" * 64   # rewrite the freeze
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    ok, why = cl.verify_chain(ws, "C-1", key=KEY)
    assert ok is False and "meta.json" in why


def test_unparsable_round_fails_closed(ws) -> None:
    _begin(ws)
    cl.append_event(ws, "C-1", _challenge(), key=KEY)
    _tail(ws).write_text("{not json", encoding="utf-8")
    ok, why = cl.verify_chain(ws, "C-1", key=KEY)
    assert ok is False and "unparsable" in why


# ---------- summary + authentication ----------

def test_summary_authenticates_and_binds_freshness(ws) -> None:
    _begin(ws)
    cl.append_event(ws, "C-1", _challenge(), key=KEY)
    cl.append_event(ws, "C-1", _rebuttal(), key=KEY)
    s = cl.summary(ws, "C-1", key=KEY)
    assert s["rounds"] == 2 and s["chain_ok"] is True
    assert s["open_challenges"] == []
    assert cl.authenticate_summary(s, key=KEY, ws=ws, claim="C-1") is True
    # a foreign key cannot mint an acceptable summary
    assert cl.authenticate_summary(s, key=b"wrong", ws=ws,
                                   claim="C-1") is False
    # a stale all-clear replay dies at the freshness layer
    cl.append_event(ws, "C-1", _challenge("ch-new", "lanes"), key=KEY)
    assert cl.authenticate_summary(s, key=KEY, ws=ws, claim="C-1") is False
    assert cl.current_head_sha(ws, "C-1") != s["head_sha"]


def test_summary_of_a_broken_chain_carries_the_failure(ws) -> None:
    _begin(ws)
    cl.append_event(ws, "C-1", _challenge(), key=KEY)
    doc = json.loads(_tail(ws).read_text(encoding="utf-8"))
    doc["events"] = []
    _tail(ws).write_text(json.dumps(doc), encoding="utf-8")
    s = cl.summary(ws, "C-1", key=KEY)
    assert s["chain_ok"] is False
    assert cl.authenticate_summary(s, key=KEY) is True   # hmac still true


def test_uninitialized_ledger_has_no_head_and_no_open_challenges(ws) -> None:
    assert cl.rounds(ws, "C-404") == []
    assert cl.open_challenges(ws, "C-404") == []
    # the head anchor reads the meta bytes — an uninitialized ledger has
    # none (as-found: the summary face presumes begin_claim ran)
    with pytest.raises(FileNotFoundError):
        cl.current_head_sha(ws, "C-404")
