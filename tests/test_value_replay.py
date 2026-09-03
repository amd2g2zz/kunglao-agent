# -*- coding: utf-8 -*-
"""A1 (#823): value_replay — offline z_self relabeling + bucket priors.

Synthetic good/bad workspaces: good = clean first-pass (z_self=1, high
reward score); bad = verify thrash + gate interceptions + PROVEN-without-
verify (z_self=0, low score — the Live-run sample regression shape, C-020 #819
pattern). The replay-validation gate (good > bad) must hold or P1 is
blocked from feeding A4.
"""
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import value_replay


def _mk_ws(root: Path, claims: list[dict], verifies: list[dict],
           ledger_actions: list[dict], depth: str = "standard") -> Path:
    ws = root
    (ws / "facts").mkdir(parents=True)
    (ws / "runs" / "logs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True), encoding="utf-8")
    rows = [f"F{i + 1:03d} | {c['status']} | {c['id']} | synthetic" for i, c in enumerate(claims)]
    (ws / "facts" / "_INDEX.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"depth": depth, "time_budget_minutes": 60}), encoding="utf-8")
    for v in verifies:
        name = f"verify-{v['fact_id']}-{v['seq']}.json"
        (ws / "runs" / name).write_text(json.dumps(v["body"]), encoding="utf-8")
    with (ws / "runs" / "logs" / "kunglao-2026-08-28.jsonl").open("w", encoding="utf-8") as f:
        for a in ledger_actions:
            f.write(json.dumps({"actor": "hook", "action": a,
                                "claim": None, "tool": None, "artifact": None,
                                "duration_ms": None, "exit": None, "detail": None}) + "\n")
    return ws


def _claim(cid, status="PROVEN", tier=1):
    return {"id": cid, "status": status, "statement": "c2 config extract",
            "evidence_tier_attempted": tier, "promotion_attempts": 0}


def _verify(fact_id, seq, overall, l2="VERIFIED"):
    return {"fact_id": fact_id, "seq": seq,
            "body": {"fact_id": fact_id, "overall": overall,
                     "l1": {"verdict": "PASS" if overall == "VERIFIED" else "REJECTED"},
                     "l2": {"verdict": l2 if overall == "VERIFIED" else "NOT-RUN"}}}


def test_good_ws_z_self_one(tmp_path):
    ws = _mk_ws(tmp_path / "good",
                [_claim("C-001"), _claim("C-002")],
                [_verify("F001", 1, "VERIFIED"), _verify("F002", 1, "VERIFIED")],
                [])
    z = value_replay.z_self(ws)
    assert z["z_self"] == 1
    assert z["channels"]["reopen"]["triggered"] is False
    assert z["channels"]["gate_blocked"]["triggered"] is False


def test_bad_ws_verify_thrash_is_reopen(tmp_path):
    ws = _mk_ws(tmp_path / "bad",
                [_claim("C-001")],
                [_verify("F001", 1, "REJECTED"), _verify("F001", 2, "VERIFIED")],
                [])
    z = value_replay.z_self(ws)
    assert z["channels"]["reopen"]["triggered"] is True
    assert z["z_self"] == 0


def test_bad_ws_gate_interception(tmp_path):
    ws = _mk_ws(tmp_path / "gate",
                [_claim("C-001")],
                [_verify("F001", 1, "VERIFIED")],
                ["top1_reject", "write_blocked", "converge"])
    z = value_replay.z_self(ws)
    assert z["channels"]["gate_blocked"]["triggered"] is True
    assert sorted(z["channels"]["gate_blocked"]["evidence"]) == ["top1_reject", "write_blocked"]
    assert z["z_self"] == 0


def test_unavailable_channels_marked_partial(tmp_path):
    ws = _mk_ws(tmp_path / "partial", [_claim("C-001")], [], [])
    z = value_replay.z_self(ws)
    assert z["channels"]["notes_due"]["available"] is False
    assert z["channels"]["human_turns"]["available"] is False
    assert z["partial"] is True
    assert z["z_self"] == 1  # available channels all clean


def test_extra_supplements_unavailable_channels(tmp_path):
    ws = _mk_ws(tmp_path / "extra", [_claim("C-001")],
                [_verify("F001", 1, "VERIFIED")], [])
    z = value_replay.z_self(ws, extra={"notes_due": 2, "human_turns": 1})
    assert z["channels"]["notes_due"]["available"] is True
    assert z["channels"]["notes_due"]["triggered"] is True
    assert z["channels"]["human_turns"]["triggered"] is True
    assert z["z_self"] == 0


def test_ws_score_rewards_supported_proven_only(tmp_path):
    good = _mk_ws(tmp_path / "s_good",
                  [_claim("C-001"), _claim("C-002", "PARTIAL")],
                  [_verify("F001", 1, "VERIFIED")], [])
    s_good = value_replay.ws_score(good)
    assert s_good["total"] == pytest.approx(10.0)  # +10 supported proven; PARTIAL 0
    assert s_good["unsupported_proven"] == 0

    # Live-run sample shape: PROVEN swept with zero passing verify → no reward
    bad = _mk_ws(tmp_path / "s_bad",
                 [_claim("C-001"), _claim("C-002")],
                 [_verify("F001", 1, "REJECTED")], [])
    s_bad = value_replay.ws_score(bad)
    assert s_bad["unsupported_proven"] == 2  # both PROVEN lack passing verify
    assert s_bad["total"] < s_good["total"]


def test_replay_validation_gate(tmp_path):
    good = _mk_ws(tmp_path / "g",
                  [_claim("C-001"), _claim("C-002")],
                  [_verify("F001", 1, "VERIFIED"), _verify("F002", 1, "VERIFIED")], [])
    bad = _mk_ws(tmp_path / "b",
                 [_claim("C-001"), _claim("C-002")],
                 [_verify("F001", 1, "REJECTED")], [])
    assert value_replay.replay_validation_pass([good], [bad]) is True
    assert value_replay.replay_validation_pass([bad], [good]) is False


def test_priors_buckets_and_pairs(tmp_path):
    g1 = _mk_ws(tmp_path / "p1", [_claim("C-001")],
                [_verify("F001", 1, "VERIFIED")], [], depth="deep")
    g2 = _mk_ws(tmp_path / "p2", [_claim("C-001")],
                [_verify("F001", 1, "VERIFIED")], [], depth="deep")
    b1 = _mk_ws(tmp_path / "p3", [_claim("C-001")],
                [_verify("F001", 1, "REJECTED"), _verify("F001", 2, "VERIFIED")],
                [], depth="deep")
    priors = value_replay.build_priors([g1, g2, b1])
    bucket = priors["buckets"]["deep|none"]
    assert bucket["n"] == 3
    assert bucket["p_complete"] == pytest.approx(0.6667)  # 4-decimal prior table
    assert bucket["token_median"] is None  # historical token data absent
    assert bucket["ws_ids"] == ["p1", "p2", "p3"]

    pairs = value_replay.score_outcome_pairs([g1])
    assert len(pairs) == 1
    assert pairs[0]["outcome"] == 1
    assert pairs[0]["ws"] == "p1"
    assert "score" in pairs[0]
