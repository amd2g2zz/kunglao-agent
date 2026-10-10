# -*- coding: utf-8 -*-
"""tests/test_credit_settle_634.py — the live round-credit settlement CLI
(#634): assembly from terminal claims + fact artifacts, the dry-run face,
idempotency at any wall-clock distance, and the Q-cell bank ride-through —
plus the live-seam legs the same pass carries (cross-task store rows, case
posteriors for the ranker, episode tiers).

Fixtures are SYNTHETIC (no workspace data)."""
from __future__ import annotations

import random

import yaml


def _ws(tmp_path, claims):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}), encoding="utf-8")
    return ws


def test_no_terminal_claims_is_a_quiet_noop(tmp_path):
    import settle_round_credit as src
    ws = _ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    out = src.run(ws)
    assert out["settled"] == 0 and "nothing to settle" in out["reason"]


def test_settlement_banks_the_pending_dispatch_row(tmp_path):
    import settle_round_credit as src
    from rlvr import q_cells
    ws = _ws(tmp_path, [{"id": "C-9", "status": "REFUTED"}])
    q_cells.record_dispatch_observation(
        ws, "dispatch envelope",
        envelope_meta={"method_family": "static-symbolic"}, claim="C-9")
    out = src.run(ws)
    assert out["settled"] == 1 and out["rounds"] == 1
    rows = q_cells.JSONLQStore(ws).observations()
    banked = [r for r in rows if r.get("source") == "settlement"]
    assert len(banked) == 1
    assert banked[0]["dispatch_id"] == "C-9"
    assert banked[0]["credit"] is not None


def test_idempotent_second_pass_appends_nothing(tmp_path):
    import settle_round_credit as src
    from rlvr import q_cells
    ws = _ws(tmp_path, [{"id": "C-9", "status": "REFUTED"}])
    q_cells.record_dispatch_observation(
        ws, "dispatch envelope",
        envelope_meta={"method_family": "static-symbolic"}, claim="C-9")
    src.run(ws)
    n1 = len(q_cells.JSONLQStore(ws).observations())
    src.run(ws)
    n2 = len(q_cells.JSONLQStore(ws).observations())
    assert n2 == n1  # identity-ts freeze + settlement-presence guard


def test_dry_run_never_writes(tmp_path):
    import settle_round_credit as src
    from rlvr import q_cells
    ws = _ws(tmp_path, [{"id": "C-9", "status": "REFUTED"}])
    q_cells.record_dispatch_observation(
        ws, "dispatch envelope",
        envelope_meta={"method_family": "static-symbolic"}, claim="C-9")
    out = src.run(ws, dry_run=True)
    assert out["dry_run"] is True and out["would_settle"] == 1
    rows = q_cells.JSONLQStore(ws).observations()
    assert rows and all(r.get("source") == "dispatch" for r in rows)


# --------------------------------- the live-seam legs (store / cases / tiers)

def _case_ws(tmp_path, claims, cases=(), name="ws"):
    """Workspace + claim register + a pending dispatch row per claim (the
    live bank trigger), optional oracle case files."""
    from rlvr import q_cells
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    (ws / "facts").mkdir(exist_ok=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}), encoding="utf-8")
    if cases:
        cdir = ws / "oracle" / "cases"
        cdir.mkdir(parents=True)
        for case_id, target_pq in cases:
            (cdir / f"{case_id}.yaml").write_text(
                yaml.safe_dump({"id": case_id, "target_pq": target_pq}),
                encoding="utf-8")
    for c in claims:
        q_cells.record_dispatch_observation(
            ws, "dispatch envelope",
            envelope_meta={"method_family": "static-symbolic"},
            claim=str(c["id"]))
    return ws


def _ledger(ws):
    import posteriors as po
    return po.PosteriorLedger.load(ws)


def test_bank_writes_the_cross_task_store_row(tmp_path):
    """The bank keys a cross-task store row from the matched dispatch row:
    the write face had no live caller before this wire, so the store file
    never existed and compose's sampler stayed store-blind."""
    import settle_round_credit as src
    from rlvr import strategy_store
    ws = _case_ws(tmp_path, [{"id": "C-9", "status": "REFUTED"}])
    src.run(ws)
    rows = [r for r in strategy_store.load_rows(ws=None)
            if str((r.get("provenance") or {}).get("dispatch_id")) == "C-9"]
    assert len(rows) == 1, "the settled dispatch must key exactly one row"
    row = rows[0]
    assert row["method_family"] == "static-symbolic"
    assert row["arm_key"] == "static-symbolic|facts_snapshot|none|0"
    assert row["status"] == "ROUND_CREDIT"
    assert row["workspace_id"] == ws.name
    # the replay adds no second row (the first-settlement clock)
    src.run(ws)
    again = [r for r in strategy_store.load_rows(ws=None)
             if str((r.get("provenance") or {}).get("dispatch_id")) == "C-9"]
    assert len(again) == 1


def test_unmatched_dispatch_writes_no_store_row(tmp_path):
    """No pending dispatch row -> no banked credit -> no store row: the
    honest gap, never a fabricated bucket."""
    import settle_round_credit as src
    from rlvr import strategy_store
    ws = _ws(tmp_path, [{"id": "C-9", "status": "REFUTED"}])
    out = src.run(ws)
    assert out["settled"] == 1  # the ledger row still settles
    assert strategy_store.load_rows(ws=None) == []


def test_case_settlement_leg_updates_linked_case_posteriors(tmp_path):
    """The ranker's live update leg: a banked claim whose terminal status
    is decisive records one Bernoulli observation per linked oracle case
    (target_pq == answers_question); the posterior ledger is instantiated
    where no live face ever wrote it."""
    import settle_round_credit as src
    ws = _case_ws(tmp_path, [
        {"id": "C-1", "status": "PROVEN", "answers_question": "q-x"},
        {"id": "C-2", "status": "REFUTED", "answers_question": "q-x"},
        {"id": "C-3", "status": "DEFERRED", "answers_question": "q-x"},
    ], cases=[("case-a", "q-x"), ("case-b", "q-other")])
    out = src.run(ws)
    assert out["case_observations"] == 2 and out["cases_passed"] == 1 \
        and out["cases_failed"] == 1
    led = _ledger(ws)
    assert (led.cases["case-a"].alpha, led.cases["case-a"].beta) == (2.0, 2.0)
    assert "case-b" not in led.cases, \
        "an unlinked case must never receive an observation"
    assert (ws / "runs" / "posteriors.yaml").is_file()


def test_case_settlement_leg_is_idempotent_and_case_free_quiet(tmp_path):
    import settle_round_credit as src
    ws = _case_ws(tmp_path,
                  [{"id": "C-1", "status": "PROVEN",
                    "answers_question": "q-x"}],
                  cases=[("case-a", "q-x")])
    src.run(ws)
    src.run(ws)  # the replay settles nothing and observes nothing
    led = _ledger(ws)
    assert (led.cases["case-a"].alpha, led.cases["case-a"].beta) == (2.0, 1.0)
    # no oracle cases at all -> no ledger file (honest cold start)
    ws2 = _case_ws(tmp_path, [{"id": "C-2", "status": "PROVEN",
                               "answers_question": "q-x"}], name="ws2")
    out = src.run(ws2)
    assert out["case_observations"] == 0
    assert not (ws2 / "runs" / "posteriors.yaml").is_file()


def test_case_settlement_leg_feeds_the_ranker(tmp_path):
    """Rank-side integration: the ledger the settlement leg writes is the
    one the ranker prices the claim's case face from (one live writer, one
    live reader — no gap in between)."""
    import settle_round_credit as src
    import priority_ratio as pr
    ws = _case_ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                              "answers_question": "q-x"}],
                  cases=[("case-a", "q-x")])
    src.run(ws)
    led = _ledger(ws)
    actions = pr.priority_ratio(
        [{"id": "C-1", "status": "OPEN", "answers_question": "q-x"}],
        {"depends_on": {}}, pr.EvidenceView(ws=ws))
    base = random.Random(0).getrandbits(64)
    child = random.Random(f"thompson/{base}/C-1")
    expected = round(child.betavariate(led.cases["case-a"].alpha,
                                       led.cases["case-a"].beta), 6)
    assert actions[0].score == expected, \
        "the ranker's case face must draw the settled Beta"
    assert "no linked oracle case" not in actions[0].feeds["thompson_sample"]


def test_episode_tier_leg_amends_and_is_idempotent(tmp_path):
    """The episode-tier leg: a settled task rollout with no tier scalar is
    amended in the same pass (experience tuple written), and the next pass
    finds nothing left to amend."""
    import rollout_ledger as rl
    import settle_round_credit as src
    ws = _ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    rl.record(ws, kind="task", anchor="C-9", signals=[
        {"type": "oracle_verdict", "source": "checker", "value": "pass",
         "ts": "t"},
        {"type": "unit_family", "source": "manifest", "value": "kdf",
         "ts": "t"},
        {"type": "strategy_arm", "source": "eval", "value": "arm-a",
         "ts": "t"}], rollout_id="task/C-9")
    rl.settle(ws, "task/C-9", {"reward": 1.0, "band": "SETTLED_GREEN",
                               "rule_id": "r/1", "evidence_refs": []})
    out = src.run(ws)
    assert out["tiers_seen"] == 1 and out["tiers_settled"] == 1
    st = rl.fold(ws, "task/C-9")["settlement"]
    assert "tier" in st and isinstance(st.get("experience_tuple"), dict)
    assert st["experience_tuple"]["s"]["family"] == "kdf"
    rerun = src.run(ws)
    assert rerun["tiers_seen"] == 0 and rerun["tiers_settled"] == 0


def test_dry_run_counts_pending_tiers_and_writes_nothing(tmp_path):
    import rollout_ledger as rl
    import settle_round_credit as src
    ws = _ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    rl.record(ws, kind="task", anchor="C-9", signals=[
        {"type": "oracle_verdict", "source": "checker", "value": "pass",
         "ts": "t"}], rollout_id="task/C-9")
    rl.settle(ws, "task/C-9", {"reward": 1.0, "band": "SETTLED_GREEN",
                               "rule_id": "r/1", "evidence_refs": []})
    before = (ws / "runs" / "rollout-ledger.jsonl").read_bytes()
    out = src.run(ws, dry_run=True)
    assert out["would_amend_tiers"] == 1
    assert (ws / "runs" / "rollout-ledger.jsonl").read_bytes() == before
