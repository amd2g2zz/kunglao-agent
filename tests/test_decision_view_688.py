# -*- coding: utf-8 -*-
"""tests/test_decision_view_688.py — the decision view contract (issue 688).

Spec-first over openspec/changes/issue-688-decision-view (validate --strict
green before this file existed):

  A. additive rank_feeds payload keys — entropy / propensity / k / tiers as
     pure functions of the ranked actions: normal runs, fingerprint
     untouched, same-seed replay equality, and the three degenerate runs
     (empty / single candidate / zero score mass) degrading honestly;
  B. the six-face view model — SCHEMA, FACES, FACE_KEYS contract,
     build_view never raises (empty workspace + broken source), budget
     honest-null behind the cost-accounting blocker;
  C. face sources — rationale and candidate faces read the persisted
     payload through rank_face (including legacy rows without the new
     keys), settled / hypothesis-space / in-flight faces read the
     single-source ledgers.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import decision_view as dv  # noqa: E402
import kunglao_log  # noqa: E402
import priority_ratio as pr  # noqa: E402
import rank_face  # noqa: E402

# rank fixture builders reuse the algorithm-event-log suite's shaped
# helpers (same cross-test import convention those suites already use).
from test_algorithm_event_log_157 import _rank_inputs, _rank_ws  # noqa: E402


# ---------- shared seam: capture kunglao_log.emit in-process ----------

@pytest.fixture
def events(monkeypatch):
    """Capture every kunglao_log.emit call made in-process after this
    point (module-attribute patch — the producer resolves emit at call
    time), so payload assertions read the exact emitted document."""
    calls: list[dict] = []

    def _fake(ws, actor, action, **kw):
        calls.append({"ws": ws, "actor": actor, "action": action, **kw})

    monkeypatch.setattr(kunglao_log, "emit", _fake)
    return calls


def _payload_of(calls: list[dict]) -> dict:
    rows = [c for c in calls if c["action"] == "rank_feeds"]
    assert rows, "expected exactly the ranker's rank_feeds emit"
    return json.loads(rows[-1]["detail"])


def _seed_legacy_rank_event(ws: Path) -> None:
    """One rank_feeds row as written BEFORE the additive view keys — the
    legacy-degradation contract (old tails stay readable forever)."""
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log = ws / "runs" / "logs" / f"kunglao-{day}.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    row = {
        "ts": ts,
        "actor": "priority_ratio",
        "action": "rank_feeds",
        "detail": json.dumps({
            "feeds": {"C-1": {"thompson_sample": "Beta(4,1) -> 0.8"}},
            "scores": {"C-1": 0.5, "C-2": 0.4},
            "ranked_order": ["C-1", "C-2"],
            "input_fingerprint": {"claims_hash": "a", "evidence_hash": "b",
                                  "rng_base": 1, "round": 0,
                                  "fingerprint": "c"},
        }, sort_keys=True, ensure_ascii=False),
    }
    with log.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def _emit_direct(ws: Path, actions: list) -> dict:
    """Direct payload capture: one fail-open emit with hand-built actions
    (the shape test_event_schema_255 uses for the arm contract)."""
    calls: list[dict] = []

    def _fake(w, actor, action, **kw):
        calls.append({"action": action, **kw})

    original = kunglao_log.emit
    kunglao_log.emit = _fake
    try:
        pr._emit_rank_feeds(ws, claims=[], evidence=pr.EvidenceView(),
                            rng_base=0, actions=actions, round_no=0)
    finally:
        kunglao_log.emit = original
    return _payload_of(calls)


# ==========================================================================
# A. additive rank_feeds payload keys
# ==========================================================================

def test_rank_feeds_payload_carries_the_view_keys(tmp_path, events):
    ws = _rank_ws(tmp_path, cases=[("CASE-A", "pq-a", 3.0, 1.0)])
    claims, deps, ev = _rank_inputs(ws)
    actions = pr.priority_ratio(claims, deps, ev, rng=random.Random(11))
    payload = _payload_of(events)

    assert {"entropy", "propensity", "k", "tiers"} <= set(payload)
    assert payload["k"] == len(actions) == len(payload["ranked_order"])
    assert set(payload["tiers"]) == set(payload["ranked_order"])
    for a in actions:
        assert payload["tiers"][a.claim_id] == a.tier

    # the pinned definition: bits of the normalized score distribution,
    # top arm's score share — recomputed here from the persisted scores
    order = payload["ranked_order"]
    scores = payload["scores"]
    total = sum(max(scores[c], 0.0) for c in order)
    assert total > 0
    shares = [max(scores[c], 0.0) / total for c in order]
    expected = round(0.0 - sum(p * math.log2(p) for p in shares if p > 0), 6)
    assert payload["entropy"] == expected
    assert payload["propensity"] == round(shares[0], 6)


def test_rank_feeds_fingerprint_excludes_view_keys(tmp_path, events):
    ws = _rank_ws(tmp_path, cases=[("CASE-A", "pq-a", 3.0, 1.0)])
    claims, deps, ev = _rank_inputs(ws)
    pr.priority_ratio(claims, deps, ev, rng=random.Random(1))
    fp = _payload_of(events)["input_fingerprint"]

    assert set(fp) == {"claims_hash", "evidence_hash", "rng_base",
                       "round", "fingerprint"}
    canon = json.dumps({k: fp[k] for k in
                        ("claims_hash", "evidence_hash", "rng_base", "round")},
                       sort_keys=True, ensure_ascii=False)
    assert fp["fingerprint"] == hashlib.sha256(
        canon.encode("utf-8")).hexdigest()


def test_same_seed_replays_identical_view_keys(tmp_path, events):
    ws = _rank_ws(tmp_path, cases=[("CASE-A", "pq-a", 3.0, 1.0)])
    claims, deps, ev = _rank_inputs(ws)
    pr.priority_ratio(claims, deps, ev, rng=random.Random(7))
    pr.priority_ratio(claims, deps, ev, rng=random.Random(7))
    rows = [json.loads(c["detail"]) for c in events
            if c["action"] == "rank_feeds"]
    assert len(rows) == 2
    for key in ("entropy", "propensity", "k", "tiers"):
        assert rows[0][key] == rows[1][key], key
    assert rows[0] == rows[1]


def test_empty_rank_degrades_honestly(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    payload = _emit_direct(ws, actions=[])

    assert payload["k"] == 0
    assert payload["entropy"] is None
    assert payload["propensity"] is None
    assert payload["tiers"] == {}


def test_single_candidate_is_fully_determined(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    actions = [pr.Action(claim_id="C-1", action="dispatch", score=0.4,
                         skill=None, tier=2, attempts=0, cost=1.0)]
    payload = _emit_direct(ws, actions=actions)

    assert payload["k"] == 1
    assert payload["entropy"] == 0.0
    assert payload["propensity"] == 1.0
    assert payload["tiers"] == {"C-1": 2}


def test_zero_score_mass_cannot_be_normalized(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    actions = [
        pr.Action(claim_id="C-1", action="dispatch", score=0.0, skill=None,
                  tier=1, attempts=0, cost=1.0),
        pr.Action(claim_id="C-2", action="dispatch", score=0.0, skill=None,
                  tier=3, attempts=0, cost=10.0),
    ]
    payload = _emit_direct(ws, actions=actions)

    assert payload["k"] == 2
    assert payload["entropy"] is None
    assert payload["propensity"] is None
    assert payload["tiers"] == {"C-1": 1, "C-2": 3}


# ==========================================================================
# B. the six-face view model contract
# ==========================================================================

def test_view_contract_declares_the_six_faces():
    assert dv.SCHEMA == "decision-view/1"
    assert dv.FACES == ("in_flight", "why_this_one", "just_settled",
                        "hypothesis_space", "budget", "next_candidates")
    assert set(dv.FACE_KEYS) == set(dv.FACES)


def test_absent_shapes_match_the_face_key_contract():
    assert set(dv.ABSENT) == set(dv.FACES)
    for face in dv.FACES:
        assert set(dv.ABSENT[face]) == set(dv.FACE_KEYS[face]), face


def test_empty_workspace_yields_all_six_faces(tmp_path):
    view = dv.build_view(tmp_path)

    assert view["schema"] == dv.SCHEMA
    assert set(view["faces"]) == set(dv.FACES)
    for face, keys in dv.FACE_KEYS.items():
        assert set(view["faces"][face]) == set(keys), face
    faces = view["faces"]
    assert faces["in_flight"] == {"claims": [], "count": 0,
                                  "method_lead": None}
    assert faces["why_this_one"]["claim"] is None
    assert faces["why_this_one"]["k"] is None
    assert faces["just_settled"]["anchor"] is None
    assert faces["hypothesis_space"]["alive"] == 0
    assert faces["next_candidates"]["candidates"] == []
    assert faces["next_candidates"]["k"] is None


def test_budget_is_honest_behind_the_accounting_blocker(tmp_path):
    view = dv.build_view(tmp_path)
    assert view["faces"]["budget"] == {
        "tokens": None, "tool_calls": None, "verify_calls": None,
        "accounted": False,
    }


def test_broken_rank_source_degrades_only_the_rank_faces(tmp_path,
                                                         monkeypatch):
    def _boom(*_args, **_kw):
        raise RuntimeError("rank payload reader exploded")

    monkeypatch.setattr(rank_face, "latest_payload", _boom)
    view = dv.build_view(tmp_path)  # never raises

    faces = view["faces"]
    assert set(faces["why_this_one"]) == set(dv.FACE_KEYS["why_this_one"])
    assert faces["why_this_one"]["claim"] is None
    assert set(faces["next_candidates"]) == set(dv.FACE_KEYS["next_candidates"])
    assert faces["next_candidates"]["candidates"] == []
    # the four non-rank faces still build from their own sources
    assert faces["in_flight"]["claims"] == []
    assert faces["budget"]["accounted"] is False
    assert faces["just_settled"]["anchor"] is None
    assert faces["hypothesis_space"]["terminal"] == 0


# ==========================================================================
# C. face sources
# ==========================================================================

def test_latest_payload_absent_face(tmp_path):
    assert rank_face.latest_payload(tmp_path) == {
        "payload": {}, "ts": None, "age_s": None, "stale": True,
    }


def test_why_this_one_reads_the_persisted_keys(tmp_path):
    ws = _rank_ws(tmp_path, cases=[("CASE-A", "pq-a", 3.0, 1.0)])
    claims, deps, ev = _rank_inputs(ws)
    actions = pr.priority_ratio(claims, deps, ev, rng=random.Random(3))

    why = dv.build_view(ws)["faces"]["why_this_one"]
    persisted = rank_face.latest_payload(ws)["payload"]
    top = actions[0]

    assert why["claim"] == top.claim_id
    assert why["score"] == top.score
    assert why["entropy"] == persisted["entropy"]
    assert why["propensity"] == persisted["propensity"]
    assert why["k"] == persisted["k"] == len(actions)
    assert isinstance(why["feeds"], dict) and why["feeds"]
    assert why["ts"] is not None
    assert why["stale"] is False


def test_next_candidates_carry_score_and_tier_per_row(tmp_path):
    ws = _rank_ws(tmp_path, cases=[("CASE-A", "pq-a", 3.0, 1.0)])
    claims, deps, ev = _rank_inputs(ws)
    actions = pr.priority_ratio(claims, deps, ev, rng=random.Random(5))

    nxt = dv.build_view(ws)["faces"]["next_candidates"]
    assert nxt["k"] == len(actions)
    assert [c["claim"] for c in nxt["candidates"]] == \
        [a.claim_id for a in actions]
    for row, a in zip(nxt["candidates"], actions):
        assert row["score"] == a.score
        assert row["tier"] == a.tier


def test_legacy_payload_without_view_keys_degrades_honestly(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed_legacy_rank_event(ws)

    view = dv.build_view(ws)  # never raises
    why = view["faces"]["why_this_one"]
    nxt = view["faces"]["next_candidates"]

    assert why["claim"] == "C-1"
    assert why["entropy"] is None
    assert why["propensity"] is None
    assert why["k"] == 2  # falls back to the ranked order length
    assert nxt["k"] == 2
    assert nxt["candidates"] == [
        {"claim": "C-1", "score": 0.5, "tier": None},
        {"claim": "C-2", "score": 0.4, "tier": None},
    ]


def test_just_settled_reads_the_settlement_ledger(tmp_path):
    from rlvr import ledger as rl

    ws = tmp_path
    assert dv.build_view(ws)["faces"]["just_settled"]["anchor"] is None

    rec = rl.record(ws, "task", "C-1",
                    [{"type": "oracle", "source": "test", "value": 1,
                      "ts": "2026-01-01T00:00:00Z"}])
    assert rec["appended"], rec
    st = rl.settle(ws, rec["rollout_id"],
                   {"reward": 0.75, "band": "high", "rule_id": "r1",
                    "evidence_refs": []})
    assert st["appended"], st

    settled = dv.build_view(ws)["faces"]["just_settled"]
    assert settled["anchor"] == "C-1"
    assert settled["kind"] == "task"
    assert settled["band"] == "high"
    assert settled["reward"] == 0.75
    assert settled["ts"] is not None


def test_hypothesis_space_buckets_register_statuses(tmp_path):
    ws = tmp_path
    (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [
        {"id": "C-1", "status": "OPEN"},
        {"id": "C-2", "status": "IN_PROGRESS"},
        {"id": "C-3", "status": "PARK"},
        {"id": "C-4", "status": "RETRACTED"},
        {"id": "C-5", "status": "PROVEN"},
    ]}), encoding="utf-8")

    h = dv.build_view(ws)["faces"]["hypothesis_space"]
    assert h["alive"] == 2
    assert h["parked"] == 1
    assert h["pruned"] == 1
    assert h["terminal"] == 1
    assert h["other"] == 0
    assert {"h_bits", "h_pq", "h_trend"} <= set(h)


def test_in_flight_lists_the_working_claims(tmp_path):
    ws = tmp_path
    (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [
        {"id": "C-1", "status": "IN_PROGRESS"},
        {"id": "C-2", "status": "OPEN"},
    ]}), encoding="utf-8")
    strat = ws / "runs" / "round-strategy"
    strat.mkdir(parents=True)
    (strat / "tick-0001.yaml").write_text(yaml.safe_dump({
        "schema": "round-strategy/1",
        "dispatch": {"method_lead": "jadx"},
    }), encoding="utf-8")

    in_flight = dv.build_view(ws)["faces"]["in_flight"]
    assert in_flight["claims"] == ["C-1"]
    assert in_flight["count"] == 1
    assert in_flight["method_lead"] == "jadx"
