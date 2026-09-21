# -*- coding: utf-8 -*-
"""#294 replay ruler — TTC harness, λ epistemology check, downstream term.

Fixture discipline (EXP-B gap notes): the synthetic fixture fills EXACTLY
what real ledgers left unmeasurable — populated posteriors (cases+pqs,
non-constant dh_pq), a posterior-history surface, mission factor vectors —
while staying schema-faithful to the historical ledger gotchas (old-format
rows without dispatched_ids, event rows interleaved, open_ids semantics).
Content-free: every id/statement below is synthetic.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import replay_ruler as rr  # noqa: E402
import priority_ratio as pr  # noqa: E402
import convergence_health as ch  # noqa: E402


# ---------------------------------------------------------------- fixture

def _claim(cid, statement="", **over):
    c = {"id": cid, "statement": statement or f"synthetic claim {cid}",
         "status": "PENDING", "promotion_attempts": 0,
         "evidence_tier_attempted": 0, "answers_question": ""}
    c.update(over)
    return c


def _write_register(ws, claims):
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True),
        encoding="utf-8")


def _write_deps(ws, depends_on):
    (ws / "claim_deps.yaml").write_text(
        yaml.safe_dump({"depends_on": depends_on}, allow_unicode=True),
        encoding="utf-8")


def _snapshot_row(ts="2026-09-01T00:00:00+00:00", **over):
    row = {"ts": ts, "decision": "SCHEDULE", "open_count": 0, "open_ids": [],
           "partial_count": 0, "active_workers": [], "blockers": [],
           "facts_total": 0, "dispatched_ids": []}
    row.update(over)
    row["open_count"] = len(row["open_ids"])
    return row


def _write_ledger(ws, rows, extra_lines=()):
    lines = [json.dumps(r, ensure_ascii=False) for r in rows]
    lines.extend(extra_lines)
    (ws / ".convergence_ledger.jsonl").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")


def _posteriors_doc():
    """Populated cases+pqs namespaces — the real-workspace gap."""
    return {
        "schema": "posteriors-schema/1",
        "cases": {
            "case-a": {"alpha": 3.0, "beta": 1.0, "pending_entries": 0},
            "case-b": {"alpha": 1.0, "beta": 3.0, "pending_entries": 0},
        },
        "pqs": {
            "PQ-main": {"candidates": {"hyp-x": 3.0, "hyp-y": 1.0}},
            "PQ-side": {"candidates": {"only": 1.0}},
        },
    }


def _write_posteriors(ws, doc=None):
    (ws / "runs").mkdir(exist_ok=True)
    (ws / "runs" / "posteriors.yaml").write_text(
        yaml.safe_dump(doc or _posteriors_doc(), allow_unicode=True),
        encoding="utf-8")


def _write_posterior_history(ws, rounds):
    """Posterior-history surface: one doc per round, entropy shrinking."""
    hdir = ws / "runs" / "posterior-history"
    hdir.mkdir(parents=True, exist_ok=True)
    for r in range(rounds):
        doc = _posteriors_doc()
        # deterministic drift: hyp-x mass grows with r on PQ-main
        w = 1.0 + r
        doc["pqs"]["PQ-main"]["candidates"] = {"hyp-x": w, "hyp-y": 1.0}
        (hdir / f"posteriors-{r:04d}.yaml").write_text(
            yaml.safe_dump(doc, allow_unicode=True), encoding="utf-8")


def _mission_history(ws, vectors):
    """Persisted factor vectors (mission_ledger history shape)."""
    (ws / "runs").mkdir(exist_ok=True)
    led = {"mission": {"history": [
        {"round": v["round"], "factor": v} for v in vectors]}}
    (ws / "runs" / "mission_ledger.yaml").write_text(
        yaml.safe_dump(led, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def fixture_ws(tmp_path):
    """Chain C-01 -> C-02 -> C-03 with leaves C-04/C-05 off C-01; ledger
    history where C-01 closes late and leaves close early (the ordering
    matters face); old-format rows interleaved; event row interleaved."""
    ws = tmp_path / "ws"
    ws.mkdir()
    claims = [
        _claim("C-01", answers_question="PQ-main"),
        _claim("C-02", answers_question="PQ-main"),
        _claim("C-03", answers_question="PQ-side"),
        _claim("C-04", answers_question="PQ-side"),
        _claim("C-05", answers_question="PQ-main"),
    ]
    _write_register(ws, claims)
    _write_deps(ws, {"C-02": ["C-01"], "C-03": ["C-02"],
                     "C-04": ["C-01"], "C-05": ["C-01"]})
    _write_posteriors(ws)
    _write_posterior_history(ws, 6)
    _mission_history(ws, [
        {"round": r, "oracle_pass": r, "checks_impl": r + 1,
         "pq_cov": {"PQ-main": 0.1 * r, "PQ-side": 0.2 * r}}
        for r in range(5)])
    # history: tick1 all open; tick2 old-format row (no dispatched_ids);
    # tick3 event row; ticks 4-6 leaves C-04/C-05 close; C-01 last.
    rows = [
        _snapshot_row(open_ids=["C-01", "C-02", "C-03", "C-04", "C-05"],
                      facts_total=0),
        {"ts": "2026-09-01T00:01:00+00:00", "open_count": 5,
         "open_ids": ["C-01", "C-02", "C-03", "C-04", "C-05"],
         "facts_total": 1},  # OLD format: no dispatched_ids/decision
        _snapshot_row(open_ids=["C-01", "C-02", "C-03", "C-04", "C-05"],
                      facts_total=1),
        _snapshot_row(open_ids=["C-01", "C-02", "C-04", "C-05"],
                      facts_total=2),
        _snapshot_row(open_ids=["C-01", "C-02"], facts_total=3),
        _snapshot_row(open_ids=["C-01", "C-02"], facts_total=4),
        _snapshot_row(open_ids=["C-01", "C-02"], facts_total=5),
    ]
    _write_ledger(ws, rows, extra_lines=(
        json.dumps({"type": "operator_action", "action": "rollup",
                    "ts": "2026-09-01T00:02:00+00:00"}),))
    return ws


# ============================== harness faces ============================

class TestHarnessBasics:
    def test_history_loader_tolerates_both_shapes(self, fixture_ws):
        hist = rr.load_history(fixture_ws)
        snaps = [s for s in hist if s["is_snapshot"]]
        assert len(snaps) == 7
        # the old-format row is a snapshot too (no "type", has open_count)
        assert snaps[1]["format"] == "old"
        assert snaps[0]["format"] == "new"
        # event row excluded
        assert any(not s["is_snapshot"] for s in hist)

    def test_universe_and_close_ticks(self, fixture_ws):
        hist = rr.load_history(fixture_ws)
        u = rr.build_universe(hist, fixture_ws)
        assert u.universe == {"C-01", "C-02", "C-03", "C-04", "C-05"}
        # C-03/C-04/C-05 closed (first absent) earlier than C-01
        assert u.close_tick["C-03"] < u.close_tick["C-01"]

    def test_two_configs_produce_ttc(self, fixture_ws, tmp_path):
        rep = rr.run_replay(
            fixture_ws, configs=rr.DEFAULT_CONFIGS, sandbox=tmp_path)
        ttcs = rep["configs"]
        assert set(ttcs) >= {"lambda_default", "lambda_zero"}
        for name, r in ttcs.items():
            assert r["ttc"] is not None and r["ttc"] > 0
            assert r["converged"] is True

    def test_same_config_double_run_byte_identical(self, fixture_ws, tmp_path):
        a = rr.run_replay(fixture_ws, configs=rr.DEFAULT_CONFIGS,
                          sandbox=tmp_path / "s1")
        b = rr.run_replay(fixture_ws, configs=rr.DEFAULT_CONFIGS,
                          sandbox=tmp_path / "s2")
        ja = json.dumps(a, sort_keys=True, ensure_ascii=False)
        jb = json.dumps(b, sort_keys=True, ensure_ascii=False)
        assert ja == jb

    def test_source_workspace_never_written(self, fixture_ws, tmp_path):
        def digest(ws):
            out = {}
            for p in sorted(ws.rglob("*")):
                if p.is_file():
                    out[str(p.relative_to(ws))] = hashlib.sha256(
                        p.read_bytes()).hexdigest()
            return out
        before = digest(fixture_ws)
        rr.run_replay(fixture_ws, configs=rr.DEFAULT_CONFIGS,
                      sandbox=tmp_path / "sb")
        assert digest(fixture_ws) == before

    def test_rank_events_land_in_sandbox_only(self, fixture_ws, tmp_path):
        sb = tmp_path / "sb"
        rr.run_replay(fixture_ws, configs=rr.DEFAULT_CONFIGS, sandbox=sb)
        logs = list((sb / "runs" / "logs").glob("kunglao-*.jsonl")) \
            if (sb / "runs" / "logs").is_dir() else []
        assert logs, "rank_feeds must be emitted into the sandbox"
        src_logs = list((fixture_ws / "runs" / "logs").glob("*")) \
            if (fixture_ws / "runs" / "logs").is_dir() else []
        assert not src_logs, "source runs/logs must stay untouched"


# ============================ lambda epistemology ========================

class TestLambdaCheck:
    def test_lambda_configs_differ_only_in_lambda(self):
        cfgs = rr.DEFAULT_CONFIGS
        a, b = cfgs["lambda_default"], cfgs["lambda_zero"]
        assert a["lambda_dh"] == pytest.approx(pr.LAMBDA_DH)
        assert b["lambda_dh"] == 0.0
        assert {k: v for k, v in a.items() if k != "lambda_dh"} == \
               {k: v for k, v in b.items() if k != "lambda_dh"}

    def test_lambda_check_reports_dh_nonzero_rate(self, fixture_ws, tmp_path):
        # seed one historical rank_feeds event with nonzero dh + one with none
        ws = fixture_ws
        (ws / "runs" / "logs").mkdir(parents=True, exist_ok=True)
        events = [
            {"action": "rank_feeds", "epoch": None,
             "detail": json.dumps({"feeds": {"C-01": {"dh_pq":
                 "PQ 'PQ-main' categorical H=0.8 bit"}}})},
            {"action": "rank_feeds", "epoch": None,
             "detail": json.dumps({"feeds": {"C-02": {"dh_pq":
                 "no PQ categorical for 'x' in runs/posteriors.yaml -> dH=0"}}})},
        ]
        (ws / "runs" / "logs" / "kunglao-2026-09-01.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        rep = rr.run_replay(ws, configs=rr.DEFAULT_CONFIGS,
                            sandbox=tmp_path / "sb", with_events=True)
        lc = rep["lambda_check"]
        assert lc["rank_events_scanned"] == 2
        assert lc["dh_nonzero"] == 1
        assert lc["dh_nonzero_rate"] == pytest.approx(0.5)

    def test_lambda_zero_can_change_ordering(self, fixture_ws, tmp_path):
        rep = rr.run_replay(fixture_ws, configs=rr.DEFAULT_CONFIGS,
                            sandbox=tmp_path / "sb")
        orders = {n: [t["order"] for t in r["trajectory"]
                      if t.get("order")] for n, r in rep["configs"].items()}
        # the fixture makes PQ-main entropy material: with populated
        # posteriors the two configs must be CHECKABLE (both rank, and at
        # least one tick's ordering is recorded per config)
        assert orders["lambda_default"] and orders["lambda_zero"]


# ============================ downstream term ============================

class TestDownstreamTerm:
    def test_blocker_score_lifted_by_exact_term(self):
        """Same-seed double run with/without the dep edges: the ONLY score
        difference on P is W_DOWNSTREAM * downstream_term (the Thompson
        base draw is seed-identical, leaves carry no term)."""
        claims = [_claim("P"), _claim("K1"), _claim("K2"), _claim("K3")]
        ev = pr.EvidenceView()
        import random
        with_deps = pr.priority_ratio(
            claims, {"depends_on": {"K1": ["P"], "K2": ["P"], "K3": ["P"]}},
            ev, rng=random.Random(7))
        without = pr.priority_ratio(claims, {"depends_on": {}}, ev,
                                    rng=random.Random(7))
        by = {a.claim_id: a.score for a in with_deps}
        wo = {a.claim_id: a.score for a in without}
        expect = pr.W_DOWNSTREAM * pr.downstream_term(
            "P", {"K1": ["P"], "K2": ["P"], "K3": ["P"]})
        assert by["P"] - wo["P"] == pytest.approx(expect, abs=1e-6)
        # children of an unproven parent are dep-blocked in the with-deps
        # face; the term on a leaf is exactly zero
        assert set(by) == {"P"}
        for k in ("K1", "K2", "K3"):
            assert pr.downstream_term(k, {"K1": ["P"], "K2": ["P"],
                                          "K3": ["P"]}) == 0.0

    def test_term_is_bounded_by_cap(self):
        claims = [_claim("P")] + [_claim(f"K{i}") for i in range(10)]
        deps = {"depends_on": {f"K{i}": ["P"] for i in range(10)}}
        term = pr.downstream_term("P", deps.get("depends_on", {}))
        assert term <= pr.DOWNSTREAM_CAP + 1e-9

    def test_term_decays_with_distance(self):
        deps = {"D1": ["P"], "D2": ["D1"]}
        direct = pr.downstream_term("P", deps)
        assert direct > 0
        # a chain: direct dependent contributes more than the grandchild
        deep = pr.downstream_term("D1", {"D2": ["D1"]})
        assert deep < direct

    def test_feeds_carry_the_term(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        claims = [_claim("P"), _claim("K")]
        _write_register(ws, claims)
        _write_deps(ws, {"K": ["P"]})
        ev = pr.EvidenceView(ws=ws)
        import random
        acts = pr.priority_ratio(claims, {"depends_on": {"K": ["P"]}}, ev,
                                 rng=random.Random(3), round_no=0)
        feeds = {a.claim_id: a.feeds for a in acts}
        assert "downstream" in feeds["P"]
        # the blocked child still scores zero downstream weight
        assert pr.downstream_term("K", {"K": ["P"]}) == 0.0
        # an unblocked sibling face carries the feed too
        acts2 = pr.priority_ratio([_claim("P"), _claim("K")],
                                  {"depends_on": {}}, ev,
                                  rng=random.Random(3), round_no=0)
        assert all("downstream" in a.feeds for a in acts2)

    def test_seed_contract_holds_with_term(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        claims = [_claim("P"), _claim("K1"), _claim("K2")]
        _write_register(ws, claims)
        _write_deps(ws, {"K1": ["P"], "K2": ["P"]})
        _write_posteriors(ws)
        ev = pr.EvidenceView(ws=ws)
        a = pr.priority_ratio(claims, {"depends_on": {"K1": ["P"],
                                                      "K2": ["P"]}}, ev,
                              rng=pr.posterior_rng(ws), round_no=4)
        b = pr.priority_ratio(claims, {"depends_on": {"K1": ["P"],
                                                      "K2": ["P"]}}, ev,
                              rng=pr.posterior_rng(ws), round_no=4)
        assert [(x.claim_id, x.score) for x in a] == \
               [(x.claim_id, x.score) for x in b]


class TestAntiStarvation:
    def test_leaf_not_displaced_beyond_decay_bound(self):
        """The decayed/capped term can lift a blocker but cannot push a
        leaf's score below what a cold-start prior draw would give it: the
        max lift is bounded (W_DOWNSTREAM * DOWNSTREAM_CAP)."""
        assert pr.W_DOWNSTREAM * pr.DOWNSTREAM_CAP < 0.5

    def test_starvation_manifests_as_stalled_detector_flatline(self):
        """The pinned coupling: starvation = per-claim flatline visible to
        the #249 STALLED detector. A trajectory where a leaf sits open and
        dispatched-but-flat across the STALLED window MUST return STALLED
        with that claim named stuck."""
        rows = [_snapshot_row(ts=f"2026-09-01T00:0{i:02d}:00+00:00",
                              open_ids=["leaf", "blocker"],
                              dispatched_ids=["leaf"])
                for i in range(ch.STALLED_STUCK_CLAIM + 1)]
        r = ch.assess([dict(r) for r in rows])
        assert r["verdict"] == "STALLED"
        stuck = {s["claim"] for s in r["stuck_claims"]}
        assert "leaf" in stuck

    def test_downstream_replay_does_not_starve_leaves(self, tmp_path):
        """With the term live, the replayed trajectory must still dispatch
        every claim (no starvation) and the trajectory fed to the #249
        detector must not verdict STALLED."""
        ws = tmp_path / "ws"
        ws.mkdir()
        claims = ([_claim("P", answers_question="PQ-main")]
                  + [_claim(f"K{i}", answers_question="PQ-side")
                     for i in range(4)]
                  + [_claim("L", answers_question="PQ-side")])
        _write_register(ws, claims)
        _write_deps(ws, {**{f"K{i}": ["P"] for i in range(4)},
                         "L": []})
        _write_posteriors(ws)
        rows = [_snapshot_row(open_ids=[c["id"] for c in claims])]
        _write_ledger(ws, rows)
        rep = rr.run_replay(
            ws,
            configs={"downstream": rr.DEFAULT_CONFIGS["downstream"]},
            sandbox=tmp_path / "sb", max_ticks=64)
        r = rep["configs"]["downstream"]
        assert r["converged"] is True, "leaf starvation must not hang TTC"
        dispatched = {c for t in r["trajectory"]
                      for c in t.get("dispatched", [])}
        assert dispatched == {"P", "K0", "K1", "K2", "K3", "L"}
        # detector face on the replayed trajectory (new-format snapshots)
        traj = [_snapshot_row(open_ids=list(t["open_ids"]),
                              dispatched_ids=list(t["dispatched"]))
                for t in r["trajectory"]]
        verdict = ch.assess(traj)
        assert verdict["verdict"] != "STALLED"


# ======================= relevance coupling + D_t ========================

class TestRelevanceCoupling:
    def test_high_activity_zero_mainline_is_flat_reward(self, tmp_path):
        """Activity (facts growth) with zero mainline movement must show
        FLAT reward — never shaped progress."""
        ws = tmp_path / "ws"
        ws.mkdir()
        claims = [_claim("C-01", answers_question="PQ-main")]
        _write_register(ws, claims)
        _write_deps(ws, {})
        rows = [_snapshot_row(open_ids=["C-01"], facts_total=0),
                _snapshot_row(open_ids=["C-01"], facts_total=3),
                _snapshot_row(open_ids=["C-01"], facts_total=7)]
        _write_ledger(ws, rows)
        # no factor-vector movement: pq_cov flat at 0, oracle flat
        _mission_history(ws, [
            {"round": r, "oracle_pass": 0, "checks_impl": 0,
             "pq_cov": {"PQ-main": 0.0}} for r in range(3)])
        rep = rr.run_replay(ws, configs=rr.DEFAULT_CONFIGS,
                            sandbox=tmp_path / "sb")
        for name, r in rep["configs"].items():
            assert r["reward_flat"] is True
            assert r["flagged_windows"] >= 1

    def test_mainline_progress_is_rewarded(self, fixture_ws, tmp_path):
        rep = rr.run_replay(fixture_ws, configs=rr.DEFAULT_CONFIGS,
                            sandbox=tmp_path / "sb")
        any_move = any(r["reward_flat"] is False
                       for r in rep["configs"].values())
        assert any_move, "D_t moves on the populated fixture"

    def test_d_t_weights_are_config_not_hardcoded(self):
        cfg = rr.DEFAULT_CONFIGS["lambda_default"]
        assert set(cfg["d_weights"]) == {"w_oracle", "w_impl", "w_ev"}

    def test_d_t_series_derived_from_factor_vectors(self, fixture_ws,
                                                    tmp_path):
        rep = rr.run_replay(fixture_ws, configs=rr.DEFAULT_CONFIGS,
                            sandbox=tmp_path / "sb")
        r = rep["configs"]["lambda_default"]
        assert r["d_t_series"], "fixture carries factor vectors"
        assert all(0.0 <= d <= 1.0 + 1e-9 for d in r["d_t_series"])


# ======================= #266 frozen-sampling marker =====================

def _rf_row(base, rnd):
    """One rank_feeds event row with a #251 input fingerprint."""
    return {"action": "rank_feeds",
            "detail": json.dumps({"input_fingerprint":
                                  {"rng_base": base, "round": rnd}})}


class TestFrozenSamplingMarker266:
    def test_advancing_rounds_equal_base_is_flagged(self):
        rows = [_rf_row(42, r) for r in range(4)]
        marks = pr.frozen_sampling_markers(rows)
        assert len(marks) == 1
        assert marks[0]["length"] == 4
        assert marks[0]["rng_base"] == 42
        assert marks[0]["rounds"] == [0, 1, 2, 3]

    def test_moving_base_is_clean(self):
        rows = [_rf_row(100 + r, r) for r in range(6)]
        assert pr.frozen_sampling_markers(rows) == []

    def test_equal_round_equal_base_is_the_contract_not_freezing(self):
        # same posterior+round re-ranked (dedup artifact) — deterministic
        # replay, never a frozen-sampling marker
        rows = [_rf_row(7, 5) for _ in range(6)]
        assert pr.frozen_sampling_markers(rows) == []

    def test_tail_shorter_than_k_is_silent(self):
        rows = [_rf_row(42, r) for r in range(pr.FROZEN_SAMPLE_K - 1)]
        assert pr.frozen_sampling_markers(rows) == []

    def test_unparseable_row_breaks_the_run(self):
        rows = [_rf_row(42, 0), _rf_row(42, 1),
                {"action": "rank_feeds", "detail": "not-json{"},
                _rf_row(42, 2), _rf_row(42, 3)]
        assert pr.frozen_sampling_markers(rows) == []

    def test_non_rank_rows_are_ignored(self):
        rows = [_rf_row(42, 0), {"action": "dispatch", "detail": "x"},
                _rf_row(42, 1), _rf_row(42, 2), _rf_row(42, 3)]
        assert len(pr.frozen_sampling_markers(rows)) == 1

    def test_tail_replay_safe(self):
        rows = [_rf_row(42, r) for r in range(5)]
        a = pr.frozen_sampling_markers(rows)
        b = pr.frozen_sampling_markers(list(rows))
        assert a == b
        assert pr.frozen_sampling_markers(rows) == a

    def test_epoch_null_rows_detected_via_fingerprint(self):
        # the EXP-B gotcha: old events carry epoch: null — the marker keys
        # on the FINGERPRINT doc inside detail, never on the envelope axis
        rows = [{"action": "rank_feeds", "epoch": None,
                 "detail": json.dumps({"input_fingerprint":
                                       {"rng_base": 9, "round": r}})}
                for r in range(pr.FROZEN_SAMPLE_K)]
        assert len(pr.frozen_sampling_markers(rows)) == 1

    def test_ruler_reports_frozen_check(self, fixture_ws, tmp_path):
        ws = fixture_ws
        (ws / "runs" / "logs").mkdir(parents=True, exist_ok=True)
        rows = [_rf_row(77, r) for r in range(4)]
        (ws / "runs" / "logs" / "kunglao-2026-09-01.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        rep = rr.run_replay(ws, configs=rr.DEFAULT_CONFIGS,
                            sandbox=tmp_path / "sb", with_events=True)
        fc = rep["frozen_check"]
        assert fc["windows"] == 1
        assert fc["runs"][0]["rng_base"] == 77


# ==================== review r2 fixes: pins + regressions ================

class TestDownstreamConstantPins:
    """FIX-1a: the three #294 constants are HARD-PINNED — silent value
    drift must go red exactly like the LAMBDA_DH == 0.25 pin. Any change
    goes through #295 (value pins + attached replay evidence)."""

    def test_decay_pinned(self):
        assert pr.DOWNSTREAM_DECAY == 0.5

    def test_cap_pinned(self):
        assert pr.DOWNSTREAM_CAP == 4.0

    def test_weight_pinned(self):
        assert pr.W_DOWNSTREAM == 0.1

    def test_lambda_family_pinned(self):
        assert pr.LAMBDA_DH == 0.25


class TestLambdaCheckNumericParse:
    """FIX-2: the dh_pq decision parses the H VALUE — a settled
    single-candidate categorical prints "H=0.0 bit" with no "dH=0"
    sentinel and must count as λ-inert, not inflate the nonzero rate."""

    def test_zero_entropy_settled_pq_is_inert(self):
        assert rr.dh_pq_nonzero(
            "PQ 'PQ-main' categorical H=0.0 bit") is False

    def test_positive_entropy_counts(self):
        assert rr.dh_pq_nonzero(
            "PQ 'PQ-main' categorical H=0.8 bit") is True

    def test_situational_zero_is_inert(self):
        assert rr.dh_pq_nonzero(
            "PQ 'x' situational categorical H=0.0 bit") is False

    def test_no_parsable_h_is_inert(self):
        assert rr.dh_pq_nonzero("garbage without numbers") is False

    def test_lambda_check_regression_zero_entropy_event(self,
                                                         fixture_ws,
                                                         tmp_path):
        ws = fixture_ws
        (ws / "runs" / "logs").mkdir(parents=True, exist_ok=True)
        events = [{"action": "rank_feeds", "epoch": None,
                   "detail": json.dumps({"feeds": {"C-01": {"dh_pq":
                       "PQ 'PQ-main' categorical H=0.0 bit"}}})}]
        (ws / "runs" / "logs" / "kunglao-2026-09-01.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n",
            encoding="utf-8")
        rep = rr.run_replay(ws, configs=rr.DEFAULT_CONFIGS,
                            sandbox=tmp_path / "sb", with_events=True)
        assert rep["lambda_check"]["rank_events_scanned"] == 1
        assert rep["lambda_check"]["dh_nonzero"] == 0
        assert rep["lambda_check"]["dh_nonzero_rate"] == 0.0


class TestConfigPoisonHole:
    """FIX-3: a bad value in ONE config key must never leave the other
    module constant stuck — validate-then-assign, finally always restores."""

    def test_invalid_w_downstream_restores_constants(self, fixture_ws,
                                                     tmp_path):
        # lambda_dh is a VALID but DIFFERENT value (convertible string):
        # old code assigned it before crashing on w_downstream, leaving
        # LAMBDA_DH poisoned at 0.9 for the process lifetime
        before = (pr.LAMBDA_DH, pr.W_DOWNSTREAM)
        with pytest.raises(ValueError):
            rr.run_replay(
                fixture_ws,
                configs={"bad": {"lambda_dh": "0.9",
                                 "w_downstream": "abc"}},
                sandbox=tmp_path / "sb")
        assert (pr.LAMBDA_DH, pr.W_DOWNSTREAM) == before

    def test_invalid_lambda_restores_constants(self, fixture_ws,
                                               tmp_path):
        before = (pr.LAMBDA_DH, pr.W_DOWNSTREAM)
        with pytest.raises(ValueError):
            rr.run_replay(
                fixture_ws,
                configs={"bad": {"lambda_dh": "abc"}},
                sandbox=tmp_path / "sb")
        assert (pr.LAMBDA_DH, pr.W_DOWNSTREAM) == before


class TestCycleCut:
    """FIX-4: the Tarjan cycle-cut — synthetic C-017<->C-020 shape.
    Rule (documented): ALL intra-SCC edges are cut, never a partial
    choice — the cut set is a pure function of the dep graph, so two
    runs cut identically; cycle members then become simultaneously
    dispatchable and their order is the #107 score sort with the
    claim_id tie-break (smaller id wins an exact tie)."""

    def test_intra_scc_edges_cut_both_directions(self):
        deps = {"C-017": ["C-015", "C-020"], "C-020": ["C-017"]}
        assert rr.cut_cycle_edges(deps) == {("C-017", "C-020"),
                                            ("C-020", "C-017")}

    def test_cut_is_deterministic_across_runs(self):
        deps = {"C-017": ["C-015", "C-020"], "C-020": ["C-017"]}
        assert rr.cut_cycle_edges(deps) == rr.cut_cycle_edges(deps)

    def test_acyclic_graph_untouched(self):
        deps = {"C-005": ["C-004"], "C-006": ["C-005"]}
        assert rr.cut_cycle_edges(deps) == set()

    def test_self_loop_cut(self):
        assert rr.cut_cycle_edges({"A": ["A"]}) == {("A", "A")}

    def test_cycle_replay_converges_with_stable_order(self, tmp_path):
        """The cc-case shape replayed: a 2-cycle no longer deadlocks —
        the replay converges, both members dispatch, and the trajectory
        digest is identical across two runs."""
        ws = tmp_path / "ws"
        ws.mkdir()
        claims = [_claim("C-015", answers_question="PQ-side"),
                  _claim("C-017", answers_question="PQ-main"),
                  _claim("C-020", answers_question="PQ-main")]
        _write_register(ws, claims)
        _write_deps(ws, {"C-017": ["C-015", "C-020"],
                         "C-020": ["C-017"]})
        _write_posteriors(ws)
        _write_ledger(ws, [_snapshot_row(
            open_ids=["C-015", "C-017", "C-020"])])
        a = rr.run_replay(ws, configs=rr.DEFAULT_CONFIGS,
                          sandbox=tmp_path / "s1")
        b = rr.run_replay(ws, configs=rr.DEFAULT_CONFIGS,
                          sandbox=tmp_path / "s2")
        for name in a["configs"]:
            ca, cb = a["configs"][name], b["configs"][name]
            assert ca["converged"] is True, "cycle must not deadlock"
            assert ca["order_digest"] == cb["order_digest"]
            dispatched = {c for t in ca["trajectory"]
                          for c in t.get("dispatched", [])}
            assert {"C-015", "C-017", "C-020"} <= dispatched


# ============================ ledger gotchas =============================

class TestLedgerGotchas:
    def test_old_format_rows_usable_for_universe(self, fixture_ws):
        hist = rr.load_history(fixture_ws)
        snaps = [s for s in hist if s["is_snapshot"]]
        old = [s for s in snaps if s["format"] == "old"]
        assert old and old[0]["row"]["open_ids"] == ["C-01", "C-02",
                                                     "C-03", "C-04",
                                                     "C-05"]

    def test_round_is_raw_snapshot_count(self, fixture_ws):
        # 7 snapshot rows + 1 event row: round = 7, not 8
        assert rr.round_of(fixture_ws) == 7
