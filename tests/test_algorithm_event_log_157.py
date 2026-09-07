# -*- coding: utf-8 -*-
"""tests/test_algorithm_event_log_157.py — algorithm event log (#157).

The value loop's three algorithm faces become event streams through the
unified kunglao_log (#157 contract: "every agent-consumed algorithm state
must be event-logged" — the dual of the display principle):

  1. rank_feeds       priority_ratio(), ONE emit per RUN (not per claim):
                      per-claim Thompson feeds + input fingerprint
                      (claims hash, evidence-view hash, rng base draw) —
                      every ranking decision exactly replayable.
  2. posterior_update record_posteriors(), per case observation:
                      alpha/beta BEFORE -> AFTER + trigger fingerprint
                      (the report hash) — belief evolution replayable.
  3. observation      oracle_runner.run(), per case result row:
                      case_id/status + the #146 forensics summary class
                      (mismatch field names for fail, derivation presence
                      for pass) — the reward signal's event face.

All three: silent fail-open (an emit crash never blocks the algorithm —
same contract as decide_fail_open, #569), structured JSON payloads riding
detail, words registered in event_taxonomy.EMIT_ACTIONS (#459 controlled
vocabulary).
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import event_taxonomy as et  # noqa: E402
import kunglao_log  # noqa: E402
import oracle_runner as orun  # noqa: E402
import posteriors as po  # noqa: E402
import priority_ratio as pr  # noqa: E402

# oracle-runner fixture builders reuse the #108 suite's shaped constants
# (same test dir is on sys.path under pytest's rootdir collection; the
# cross-test import convention of test_event_stream_adoption.py).
from test_oracle_runner_108 import (  # noqa: E402
    BAD_CLIENT,
    CASE_GOOD,
    GOOD_CLIENT,
    _mk_ws,
    _write_client,
)


# ---------- shared seam: capture kunglao_log.emit in-process ----------

@pytest.fixture
def events(monkeypatch):
    """Capture every kunglao_log.emit call made in-process after this point
    (module-attribute patch — both producers resolve emit at call time)."""
    calls: list[dict] = []

    def _fake(ws, actor, action, **kw):
        calls.append({"ws": ws, "actor": actor, "action": action, **kw})

    monkeypatch.setattr(kunglao_log, "emit", _fake)
    return calls


def _rows(calls: list[dict], word: str) -> list[dict]:
    out = []
    for c in calls:
        if c["action"] != word:
            continue
        row = dict(c)
        row["payload"] = json.loads(c["detail"])
        out.append(row)
    return out


# ---------- rank fixtures (test_priority_ratio conventions) ----------

def _claim(cid, status="OPEN", answers_question=None, eta=0, attempts=0):
    c = {"id": cid, "status": status, "evidence_tier_attempted": eta,
         "promotion_attempts": attempts, "statement": cid}
    if answers_question is not None:
        c["answers_question"] = answers_question
    return c


def _deps():
    return {"depends_on": {}, "competitor_groups": {}}


def _rank_ws(base, cases=(), pqs=None):
    """Workspace with runs/posteriors.yaml + oracle/cases/*.yaml (the
    lenient ranker-side case face: id + target_pq)."""
    ws = base / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "oracle" / "cases").mkdir(parents=True)
    led = {"schema": "posteriors-schema/1", "cases": {}, "pqs": pqs or {}}
    for case_id, target_pq, a, b in cases:
        led["cases"][case_id] = {"alpha": a, "beta": b, "pending_entries": 0}
        (ws / "oracle" / "cases" / f"{case_id}.yaml").write_text(
            yaml.safe_dump({"id": case_id, "target_pq": target_pq}),
            encoding="utf-8")
    (ws / "runs" / "posteriors.yaml").write_text(
        yaml.safe_dump(led, allow_unicode=True), encoding="utf-8")
    return ws


def _evidence(ws):
    return pr.EvidenceView(
        terminal_fact_claims=frozenset({"C-1"}), verified_fact_count=1,
        ws=Path(ws))


def _rank_inputs(ws):
    claims = [_claim("C-1", answers_question="pq-a"), _claim("C-2")]
    return claims, _deps(), _evidence(ws)


# ---------- ① rank_feeds: one emit per run, feeds + fingerprint ----------

def test_rank_feeds_registered_word():
    assert "rank_feeds" in et.EMIT_ACTIONS
    assert "posterior_update" in et.EMIT_ACTIONS
    assert "observation" in et.EMIT_ACTIONS


def test_rank_feeds_one_emit_per_run_with_feeds_and_fingerprint(
        tmp_path, events):
    ws = _rank_ws(tmp_path, cases=[("CASE-A", "pq-a", 3.0, 1.0)],
                  pqs={"pq-a": {"candidates": {"x": 1.0, "y": 1.0}}})
    claims, deps, ev = _rank_inputs(ws)
    actions = pr.priority_ratio(claims, deps, ev)

    rows = _rows(events, "rank_feeds")
    assert len(rows) == 1, "ONE rank_feeds per RUN, not per claim"
    row = rows[0]
    assert row["actor"] == "priority_ratio"
    payload = row["payload"]

    # per-claim feeds ride the payload, byte-equal to the Action.feeds
    by_id = {a.claim_id: a for a in actions}
    assert set(payload["feeds"]) == set(by_id)
    for cid, action in by_id.items():
        assert payload["feeds"][cid] == dict(action.feeds)
    assert payload["ranked_order"] == [a.claim_id for a in actions]

    # input fingerprint: claims hash + evidence-view hash + rng base draw,
    # replayable from the payload components alone
    fp = payload["input_fingerprint"]
    assert {"claims_hash", "evidence_hash", "rng_base",
            "fingerprint"} <= set(fp)
    canon = json.dumps({"claims_hash": fp["claims_hash"],
                        "evidence_hash": fp["evidence_hash"],
                        "rng_base": fp["rng_base"]},
                       sort_keys=True, ensure_ascii=False)
    assert fp["fingerprint"] == hashlib.sha256(
        canon.encode("utf-8")).hexdigest()
    assert fp["claims_hash"] == hashlib.sha256(json.dumps(
        claims, sort_keys=True, ensure_ascii=False, default=repr)
        .encode("utf-8")).hexdigest()


def test_rank_feeds_replay_same_seed_same_payload(tmp_path, events):
    """The replay proof: same rng seed + same inputs -> identical feeds
    payload (thompson draws, fingerprint), i.e. every rank decidable from
    the event tail alone."""
    ws = _rank_ws(tmp_path, cases=[("CASE-A", "pq-a", 3.0, 1.0)])
    claims, deps, ev = _rank_inputs(ws)
    pr.priority_ratio(claims, deps, ev, rng=random.Random(20260907))
    pr.priority_ratio(claims, deps, ev, rng=random.Random(20260907))
    rows = _rows(events, "rank_feeds")
    assert len(rows) == 2
    assert rows[0]["payload"] == rows[1]["payload"]


def test_rank_feeds_fingerprint_moves_with_seed_and_inputs(tmp_path, events):
    ws_a = _rank_ws(tmp_path / "a", cases=[("CASE-A", "pq-a", 3.0, 1.0)])
    ws_b = _rank_ws(tmp_path / "b", cases=[("CASE-A", "pq-a", 5.0, 1.0)])
    claims, deps, ev_a = _rank_inputs(ws_a)
    pr.priority_ratio(claims, deps, ev_a, rng=random.Random(1))
    _, _, ev_b = _rank_inputs(ws_b)
    pr.priority_ratio(claims, deps, ev_b, rng=random.Random(2))
    rows = _rows(events, "rank_feeds")
    assert len(rows) == 2
    fp_a, fp_b = (r["payload"]["input_fingerprint"] for r in rows)
    # posterior state enters through the seed derivation: different seed ->
    # different base draw -> different fingerprint
    assert fp_a["fingerprint"] != fp_b["fingerprint"]
    assert fp_a["rng_base"] != fp_b["rng_base"]
    # a different evidence VIEW (worth weights) moves the evidence component
    pr.priority_ratio(
        claims, deps,
        pr.EvidenceView(terminal_fact_claims=frozenset({"C-1"}),
                        verified_fact_count=1, ws=Path(ws_a),
                        value_class_weights={"rce": 2.0}),
        rng=random.Random(1))
    fp_c = _rows(events, "rank_feeds")[2]["payload"]["input_fingerprint"]
    assert fp_c["evidence_hash"] != fp_a["evidence_hash"]
    assert fp_c["fingerprint"] != fp_a["fingerprint"]


def test_rank_feeds_silent_when_no_ws(events):
    """Bare EvidenceView (no ws) = pure in-memory call surface — nothing to
    log to, nothing emitted (the older suites' construction stays pure)."""
    claims = [_claim("C-1")]
    ev = pr.EvidenceView()
    pr.priority_ratio(claims, _deps(), ev)
    assert _rows(events, "rank_feeds") == []


# ---------- ② posterior_update: before/after + trigger fingerprint ----------

def _oracle_report(ws, client_src):
    _write_client(ws, client_src, name="client")
    return orun.run(ws / "oracle" / "cases", ws / "oracle" / "client.py")


def test_posterior_update_before_after_matches_ledger_delta(tmp_path, events):
    ws = _mk_ws(tmp_path, [CASE_GOOD], None)
    report = _oracle_report(ws, GOOD_CLIENT)
    before = {cid: (cp.alpha, cp.beta)
              for cid, cp in po.PosteriorLedger.load(ws).cases.items()} \
        or {}
    orun.record_posteriors(ws, report)

    rows = _rows(events, "posterior_update")
    assert len(rows) == 1, "one event per REAL verdict (pass/fail), not pending"
    row = rows[0]
    assert row["actor"] == "oracle_runner"
    payload = row["payload"]
    assert payload["case_id"] == "auth-fields"
    prior = before.get("auth-fields", (1.0, 1.0))
    assert (payload["alpha_before"], payload["beta_before"]) == prior
    # the delta matches the posteriors.yaml state the write produced
    cp = po.PosteriorLedger.load(ws).cases["auth-fields"]
    assert (payload["alpha_after"], payload["beta_after"]) == (cp.alpha,
                                                               cp.beta)
    assert cp.alpha == pytest.approx(prior[0] + 1.0)  # green -> alpha+1
    # trigger fingerprint = the report hash; recomputable, report-sensitive
    canon = json.dumps(report, sort_keys=True, ensure_ascii=False,
                       default=repr)
    assert payload["trigger_fingerprint"] == hashlib.sha256(
        canon.encode("utf-8")).hexdigest()


# ---------- ③ observation: per case result row ----------

def test_observation_rows_per_case_with_forensics_summary(tmp_path, events):
    # fail face: mismatch field names ride the summary
    ws_bad = _mk_ws(tmp_path / "bad", [CASE_GOOD], None)
    report = _oracle_report(ws_bad, BAD_CLIENT)
    assert report["counts"]["red"] == 1
    rows = _rows(events, "observation")
    assert len(rows) == 1
    assert rows[0]["actor"] == "oracle_runner"
    payload = rows[0]["payload"]
    assert payload["case_id"] == "auth-fields"
    assert payload["status"] == "fail"
    assert "auth_algo" in payload["forensics"]["mismatch_fields"]

    # pass face: derivation presence rides the summary
    events.clear()
    ws_good = _mk_ws(tmp_path / "good", [CASE_GOOD], None)
    report = _oracle_report(ws_good, GOOD_CLIENT)
    assert report["counts"]["green"] == 1
    payload = _rows(events, "observation")[0]["payload"]
    assert payload["status"] == "pass"
    assert payload["forensics"]["mismatch_fields"] == []
    assert payload["forensics"]["has_derivation"] is False  # no stages pinned

    # pending face (no client): rows still emitted — the honest unknown is
    # an observation ABOUT the channel, never silence
    events.clear()
    ws_none = _mk_ws(tmp_path / "none", [CASE_GOOD], None)
    report = orun.run(ws_none / "oracle" / "cases", None)
    assert report["counts"]["pending"] == 1
    payload = _rows(events, "observation")[0]["payload"]
    assert payload["status"] == "pending"


# ---------- silent fail-open pins (the #569 contract, three faces) ------

def _boom(*args, **kwargs):
    raise RuntimeError("emit exploded")


def test_rank_feeds_emit_crash_fail_open(tmp_path, monkeypatch):
    ws = _rank_ws(tmp_path, cases=[("CASE-A", "pq-a", 3.0, 1.0)])
    claims, deps, ev = _rank_inputs(ws)
    baseline = pr.priority_ratio(claims, deps, ev, rng=random.Random(0))
    monkeypatch.setattr(kunglao_log, "emit", _boom)
    result = pr.priority_ratio(claims, deps, ev, rng=random.Random(0))
    assert [(a.claim_id, a.score, dict(a.feeds)) for a in result] == \
        [(a.claim_id, a.score, dict(a.feeds)) for a in baseline]


def test_posterior_update_emit_crash_fail_open(tmp_path, monkeypatch):
    ws = _mk_ws(tmp_path, [CASE_GOOD], None)
    report = _oracle_report(ws, GOOD_CLIENT)
    monkeypatch.setattr(kunglao_log, "emit", _boom)
    path = orun.record_posteriors(ws, report)
    assert path is not None and Path(path).exists()
    cp = po.PosteriorLedger.load(ws).cases["auth-fields"]
    assert cp.alpha == pytest.approx(2.0)  # the state write survived


MIXED_KEY_CLIENT = '''def compute(params):
    # review r1-157 HIGH repro: a client meta dict with mixed-type keys
    # rides the report verbatim — no fail-open face may choke on it
    return {"auth_algo": "hmac-sha256",
            "nonce_len": len(str(params["nonce"])),
            "meta": {1: "x", "name": "y"}}
'''


def test_posterior_update_survives_unsortable_report_keys(tmp_path, events):
    """review r1-157 HIGH: the trigger fingerprint (json.dumps sort_keys)
    must never escape record_posteriors — a mixed-key client meta used to
    raise TypeError BEFORE the ledger save, losing the posterior delta."""
    ws = _mk_ws(tmp_path, [CASE_GOOD], None)
    report = _oracle_report(ws, MIXED_KEY_CLIENT)
    assert report["counts"]["green"] == 1
    path = orun.record_posteriors(ws, report)  # must not raise
    assert path is not None and Path(path).exists()
    cp = po.PosteriorLedger.load(ws).cases["auth-fields"]
    assert cp.alpha == pytest.approx(2.0)
    # the event still carries a trigger fingerprint — the insertion-order
    # fallback serialization (deterministic per report object)
    payload = _rows(events, "posterior_update")[0]["payload"]
    canon = json.dumps(report, ensure_ascii=False, default=repr)
    assert payload["trigger_fingerprint"] == hashlib.sha256(
        canon.encode("utf-8")).hexdigest()


def test_posterior_update_emit_crash_fail_open_and_unsortable(tmp_path,
                                                               monkeypatch):
    """The belt holds even when BOTH the fingerprint fallback and the emit
    would blow up: the state write is untouchable."""
    ws = _mk_ws(tmp_path, [CASE_GOOD], None)
    report = _oracle_report(ws, MIXED_KEY_CLIENT)
    monkeypatch.setattr(kunglao_log, "emit", _boom)
    path = orun.record_posteriors(ws, report)
    assert path is not None and Path(path).exists()


def test_run_emit_crash_fail_open(tmp_path, monkeypatch):
    ws = _mk_ws(tmp_path, [CASE_GOOD], None)
    _write_client(ws, GOOD_CLIENT, name="client")
    baseline = orun.run(ws / "oracle" / "cases", ws / "oracle" / "client.py")
    monkeypatch.setattr(kunglao_log, "emit", _boom)
    report = orun.run(ws / "oracle" / "cases", ws / "oracle" / "client.py")
    assert json.dumps(report, sort_keys=True, default=repr) == \
        json.dumps(baseline, sort_keys=True, default=repr)
