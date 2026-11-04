# -*- coding: utf-8 -*-
"""tests/test_memory_bridge.py — the native-memory bridge + recall
sensors (issue 862, P4 of the learning-loop live-wire program).

Every pin asserts observable behavior (files landed, index row values,
gate thresholds, exact bandit arithmetic), never call shapes:

  write-through  a settled episode's differential lands as hot index
                 rows (runs/memory/index.jsonl) + cold detail files
                 (runs/memory/<family>/<key>.md); a second stamp of the
                 same content is a zero write (已会零写);
  retire         a mastered family's memory view is seen by the
                 scheduler's retire face ("learned");
  sensors        ignored = retrievals−citations delta; cited-and-harmed
                 marks the key and drops its score; refutation NARROWS
                 reusable_when (exceptions appended, originals kept,
                 never deleted) and retires only after repeated hits;
  gate           the pollution gate gets MORE conservative as
                 consecutive ignored / harmed history grows (rising
                 threshold pinned with exact numbers);
  bandit         exponential credit update, exact deterministic values;
  real faces     the three P7-confirmed findings: cost stamp carries the
                 real spend, the family feature engages the scheduler's
                 family join end-to-end, and value-table cells count
                 distinct missions (no commit-row inflation).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rlvr import memory_bridge as mb  # noqa: E402
import rlvr.episode_settle as es  # noqa: E402
import rlvr.pool_indexer as pi  # noqa: E402
import rlvr.pool_scheduler as ps  # noqa: E402


def _mk_ws(tmp_path: Path, *, family: str = "tf-snake") -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    claims = {
        "claims": [
            {"id": "C-001", "status": "PROVEN", "title": "packaging"},
            {"id": "C-002", "status": "PROVEN", "title": "control points"},
            {"id": "C-003", "status": "PROVEN", "title": "trainer"},
        ]
    }
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(claims), encoding="utf-8")
    runs = ws / "runs"
    runs.mkdir()
    rows = [
        {"schema": "rollout-ledger/1",
         "rollout_id": "mainline_decision/t1", "kind": "mainline_decision",
         "ts": "t1", "signals": [], "reward": None},
        {"schema": "rollout-ledger/1",
         "rollout_id": "mainline_decision/t2", "kind": "mainline_decision",
         "ts": "t2", "signals": [], "reward": None},
    ]
    (runs / "rollout-ledger.jsonl").write_text(
        "\n".join(str(__import__("json").dumps(r)) for r in rows) + "\n",
        encoding="utf-8")
    (ws / "cost_events.jsonl").write_text(
        '{"amount": 0.4}\n{"amount": 0.25}\n', encoding="utf-8")
    spec = f"family: {family}\nprimary_questions:\n- id: pq1\n  q: win\n"
    (ws / "task_spec.yaml").write_text(spec, encoding="utf-8")
    return ws


def _settled_episode(tmp_path: Path, **kw) -> tuple[Path, dict]:
    ws = _mk_ws(tmp_path, **kw)
    es.settle_mission(ws)
    ep = next(iter(es.episode_pool.list_episodes(ws)))
    doc, _body = es.episode_schema.read_episode_file(ep)
    return ws, doc


def _row(**over) -> dict:
    row = {"schema": "memory-key/1", "key": "fam-x:abc", "family": "fam-x",
           "summary": "the packer lives at offset 0x40",
           "reusable_when": ["family:fam-x"], "exceptions": [],
           "score": 0.0, "retrievals": 0, "citations": 0,
           "consec_ignored": 0, "harmed": 0, "refutations": 0,
           "retired": False, "source_claim": "C-001",
           "created": "t", "updated": "t"}
    row.update(over)
    return row


# ----------------------------------------------------- differential writes

class TestStampWritesThrough:
    def test_hot_index_row_and_cold_detail_file(self, tmp_path):
        ws, doc = _settled_episode(tmp_path)
        out = mb.stamp_family_memory(ws, doc)
        assert out["family"] == "tf-snake", \
            "the bare scheduler vocabulary, prefix stripped"
        assert len(out["written"]) == 3, "one row per reusable fragment"
        rows = mb.load_rows(ws)
        assert {r["key"] for r in rows} == set(out["written"])
        assert all(r["family"] == "tf-snake" for r in rows)
        frags = {r["summary"] for r in rows}
        assert "C-001: packaging" in frags
        detail = ws / "runs" / "memory" / "tf-snake" / \
            f"{out['written'][0]}.md"
        assert detail.is_file(), "cold detail sinks to the file face"
        assert "packaging" in detail.read_text(encoding="utf-8")

    def test_differential_second_stamp_is_zero_write(self, tmp_path):
        ws, doc = _settled_episode(tmp_path)
        first = mb.stamp_family_memory(ws, doc)
        assert len(first["written"]) == 3
        second = mb.stamp_family_memory(ws, doc)
        assert second["written"] == [], "已会零写: nothing new to learn"
        assert second["skipped"] == 3
        assert len(mb.load_rows(ws)) == 3

    def test_mastered_family_seen_by_retire_face(self, tmp_path):
        ws, doc = _settled_episode(tmp_path)
        out = mb.stamp_family_memory(ws, doc)
        assert out["mastered"] is True, "positive completed mission = method"
        view = mb.family_view(ws)
        assert view["tf-snake"]["mastered"] is True
        task = {"task_id": "t", "family": "tf-snake"}
        assert ps.retire_reasons(task, {"memory": view}) == "learned"

    def test_failed_episode_lands_attribution_row_not_mastered(self, tmp_path):
        ws = _mk_ws(tmp_path)
        reg = yaml.safe_load((ws / "claim-register.yaml")
                             .read_text(encoding="utf-8"))
        reg["claims"][2]["status"] = "NEGATIVE"
        (ws / "claim-register.yaml").write_text(
            yaml.safe_dump(reg), encoding="utf-8")
        es.settle_mission(ws)
        ep = next(iter(es.episode_pool.list_episodes(ws)))
        doc, _b = es.episode_schema.read_episode_file(ep)
        out = mb.stamp_family_memory(ws, doc)
        assert out["mastered"] is False
        rows = mb.load_rows(ws)
        assert any("did not reach" in r["summary"] for r in rows), \
            "the clean attribution is the failed mission's lesson"

    def test_stamp_without_family_refuses_loudly(self, tmp_path):
        ws = _mk_ws(tmp_path)
        doc = {"context_features": ["register:proven"],
               "reusable_fragments": ["x"], "outcome": {"status":
                                                        "completed"},
               "reward": 1.0}
        with pytest.raises(ValueError):
            mb.stamp_family_memory(ws, doc)


# ---------------------------------------------------------- recall sensors

class TestRecallSensors:
    def test_ignored_is_retrievals_minus_citations(self, tmp_path):
        ws = _mk_ws(tmp_path)
        mb.stamp_family_memory(ws, {
            "context_features": ["family:tf-snake"],
            "reusable_fragments": ["unpack via macho dump"],
            "outcome": {"status": "completed"}, "reward": 1.0,
            "claim": "C-100"})
        key = mb.load_rows(ws)[0]["key"]
        mb.record_usage(ws, key, "retrieved")
        mb.record_usage(ws, key, "retrieved")
        row = mb.load_rows(ws)[0]
        assert row["retrievals"] == 2 and row["citations"] == 0
        assert mb.find_ignored(mb.load_rows(ws)) == [key], \
            "retrieved but never cited = ignored recall"
        out = mb.close_recall_window(ws, cited_keys=[])
        assert out["ignored"] == [key]
        row = mb.load_rows(ws)[0]
        assert row["consec_ignored"] == 1, "the streak is what the gate reads"
        assert mb.find_ignored(mb.load_rows(ws)) == [], "window closed"
        mb.record_usage(ws, key, "cited_helped")
        assert mb.load_rows(ws)[0]["consec_ignored"] == 0, \
            "a citation breaks the ignored streak"

    def test_residual_delta_does_not_strike_cited_key_next_window(
            self, tmp_path):
        """A healthy cited window must close its own delta: a key
        retrieved-then-cited in window 1 keeps NO open retrievals−
        citations residue, so window 2 (zero activity) cannot strike it
        — 'a citation breaks the ignored streak' holds across the
        boundary, not just inside one window."""
        ws = _mk_ws(tmp_path)
        mb.stamp_family_memory(ws, {
            "context_features": ["family:tf-snake"],
            "reusable_fragments": ["cited advice"],
            "outcome": {"status": "completed"}, "reward": 1.0,
            "claim": "C-100"})
        key = mb.load_rows(ws)[0]["key"]
        mb.record_usage(ws, key, "retrieved")
        mb.record_usage(ws, key, "retrieved")
        mb.record_usage(ws, key, "cited_helped")
        first = mb.close_recall_window(ws, cited_keys=[key])
        assert first["ignored"] == [], "window 1 was healthy (cited)"
        row = mb.load_rows(ws)[0]
        score_after_w1 = row["score"]
        assert score_after_w1 == pytest.approx(mb.BANDIT_ALPHA)
        second = mb.close_recall_window(ws, cited_keys=[])
        assert second["ignored"] == [], \
            "no residual delta strikes a cited key a window later"
        row = mb.load_rows(ws)[0]
        assert row["consec_ignored"] == 0
        assert row["score"] == score_after_w1

    def test_cited_and_harmed_marks_key_and_drops_score(self, tmp_path):
        ws = _mk_ws(tmp_path)
        mb.stamp_family_memory(ws, {
            "context_features": ["family:tf-snake"],
            "reusable_fragments":["wrong offset advice"],
            "outcome": {"status": "completed"}, "reward": 1.0,
            "claim": "C-100"})
        key = mb.load_rows(ws)[0]["key"]
        row = mb.record_usage(ws, key, "cited_harmed")
        assert row["citations"] == 1 and row["harmed"] == 1
        assert row["score"] == pytest.approx(-mb.BANDIT_ALPHA), \
            "the citing step's negative reward IS the recall's reward"
        assert mb.find_harmed(mb.load_rows(ws)) == [key]

    def test_refute_narrows_reusable_when_never_deletes(self, tmp_path):
        ws = _mk_ws(tmp_path)
        mb.stamp_family_memory(ws, {
            "context_features": ["family:tf-snake", "register:proven"],
            "reusable_fragments": ["KAT passes unmutated"],
            "outcome": {"status": "completed"}, "reward": 1.0,
            "claim": "C-100"})
        key = mb.load_rows(ws)[0]["key"]
        before = mb.load_rows(ws)[0]["reusable_when"]
        row = mb.refute_narrow(ws, key, "the binary is re-signed")
        assert row["reusable_when"] == before, "narrowing, never deletion"
        assert "except when: the binary is re-signed" in row["exceptions"]
        assert row["refutations"] == 1
        row = mb.refute_narrow(ws, key, "run on a debug build")
        row = mb.refute_narrow(ws, key, "fat binary variant")
        assert row["retired"] is True, "repeated refutation retires (soft)"
        detail = next((ws / "runs" / "memory" / "tf-snake").glob("*.md"))
        assert detail.is_file(), "the row still exists on disk"
        gate = mb.recall_gate(row)
        assert gate["admit"] is False


# ---------------------------------------------------------------- the gate

class TestRecallGate:
    def test_fresh_row_admits(self):
        gate = mb.recall_gate(_row())
        assert gate["threshold"] == mb.GATE_BASE
        assert gate["admit"] is True

    def test_pollution_rises_the_threshold(self):
        fresh = _row()
        ignored2 = _row(consec_ignored=2, score=-0.096)
        g0, g2 = mb.recall_gate(fresh), mb.recall_gate(ignored2)
        assert g2["threshold"] == pytest.approx(2 * mb.GATE_IGNORED_STEP)
        assert g2["threshold"] > g0["threshold"], "the bar RISES"
        assert g0["admit"] is True and g2["admit"] is False

    def test_harmed_history_raises_faster_than_ignored(self):
        one_ignored = mb.recall_gate(_row(consec_ignored=1))
        one_harmed = mb.recall_gate(_row(harmed=1))
        assert one_harmed["threshold"] > one_ignored["threshold"]
        both = mb.recall_gate(_row(consec_ignored=1, harmed=1))
        assert both["threshold"] == pytest.approx(
            mb.GATE_IGNORED_STEP + mb.GATE_HARMED_STEP)

    def test_threshold_is_capped(self):
        gate = mb.recall_gate(_row(consec_ignored=50, harmed=50))
        assert gate["threshold"] == mb.GATE_MAX


# ------------------------------------------------------------------ bandit

class TestUsageBandit:
    def test_exact_deterministic_credit(self):
        r = mb.bandit_update(_row(), 1.0)
        assert r["score"] == pytest.approx(mb.BANDIT_ALPHA)
        r = mb.bandit_update(r, 1.0)
        assert r["score"] == pytest.approx(0.64)

    def test_same_sequence_same_scores(self):
        seq = [1.0, 1.0, -1.0, -0.15]
        a = _row(key="k1")
        b = _row(key="k2")
        for v in seq:
            a = mb.bandit_update(a, v)
            b = mb.bandit_update(b, v)
        assert a["score"] == b["score"]
        assert a["score"] == pytest.approx(
            0.6 * (0.6 * (0.6 * 0.4 + 0.4) + 0.4 * -1.0) + 0.4 * -0.15)

    def test_score_clamped_and_input_not_mutated(self):
        r = _row(score=0.9)
        out = mb.bandit_update(r, 1.0)
        assert out["score"] == pytest.approx(0.94)
        out = mb.bandit_update(_row(score=1.0), 1.0)
        assert out["score"] <= 1.0
        assert _row(score=0.9)["score"] == 0.9, "rows are immutable"


class TestRanking:
    def test_only_admitted_rows_ranked_by_score(self):
        good = _row(key="f:good", score=0.8,
                    reusable_when=["family:fam-x"])
        stale = _row(key="f:stale", consec_ignored=4,
                     reusable_when=["family:fam-x"])
        other = _row(key="f:other", score=0.9,
                     reusable_when=["family:other"])
        out = mb.rank_rows([good, stale, other], ["family:fam-x"])
        assert [r["key"] for r in out] == ["f:good"], \
            "the pollution-gated key stops surfacing (attention tax)"


# ------------------------------------------- three P7-confirmed real faces

class TestRealFaceFixes:
    def test_cost_stamp_carries_real_spend(self, tmp_path):
        ws, doc = _settled_episode(tmp_path)
        assert doc["cost"]["spend_usd"] == pytest.approx(0.65)
        assert doc["cost"]["tokens"] == pytest.approx(6500.0), \
            "$1 == 10k tokens (the settlement cost_t norm) — the cost " \
            "face reads the real dollar spend, not a zero stamp"
        assert doc["reward_block"]["cost_term"] == pytest.approx(0.65)

    def test_family_feature_engages_scheduler_join(self, tmp_path):
        ws, doc = _settled_episode(tmp_path)
        assert "family:tf-snake" in doc["context_features"]
        table = pi.value_table(ws)
        joined = [k for k in table if "family:tf-snake" in k[0]]
        assert joined, "settle -> value_table carries the family feature"
        task = {"task_id": "t", "family": "family:tf-snake",
                "direct_value": 2.0, "base_cost": 1.0}
        state = {"value_table": table,
                 "family_counts": {"family:tf-snake": 1}}
        v = ps.task_value(task, state)
        assert v == pytest.approx(2.0 - 0.65), \
            "the empirical family cost (real spend) prices the task"
        stranger = dict(task, family="family:other")
        state2 = {"value_table": table,
                  "family_counts": {"family:other": 1}}
        assert ps.task_value(stranger, state2) == pytest.approx(1.0), \
            "an unmatched family falls back to base_cost (join is real)"

    def test_value_table_n_equals_distinct_missions(self, tmp_path):
        ws, doc = _settled_episode(tmp_path)
        table = pi.value_table(ws)
        key = next(k for k in table if k[1] == "switch")
        assert table[key]["n"] == 1, \
            "2 same-action commits of ONE mission must not inflate n"
        other = dict(doc)
        other["id"] = "mission-C-002"
        other["claim"] = "C-002"
        es.episode_pool.write_episode(ws, other)
        table = pi.value_table(ws)
        assert table[key]["n"] == 2, "a second distinct mission counts once"

    def test_zero_reward_stays_in_the_value_table(self, tmp_path):
        """An honestly-zero reward is STAMPED, not absent: the `or {}`
        fold dropped falsy rewards from the cell — a 0.0 episode must
        land in its cell and count in n; None stays unstamped."""
        ws = _mk_ws(tmp_path)
        (ws / "runs" / "verification-C-777.md").write_text(
            "verdict: verified\nclaim: C-777\n", encoding="utf-8")
        zero = {"schema": "episode/1", "id": "mission-C-777",
                "claim": "C-777",
                "created": "2026-10-29T00:00:00Z",
                "updated": "2026-10-29T00:00:00Z",
                "context_features": ["family:tf-snake"],
                "commits": [{"seq": 1, "action": "persist",
                             "summary": "an honest zero"}],
                "outcome": {"status": "completed", "verified": True,
                            "evidence_ref": ""},
                "cost": {"tokens": 0, "seconds": 0},
                "utility": {"retrievals": 0, "citations": 0, "utility": 0.0},
                "reusable_fragments": [], "milestones": [],
                "reward": 0.0}
        es.episode_pool.write_episode(ws, zero)
        table = pi.value_table(ws)
        key = next(k for k in table if "family:tf-snake" in k[0])
        assert table[key]["n"] == 1, "the zero-reward episode counts"
        assert table[key]["mean_reward"] == 0.0, "the honest zero holds"
        # an ABSENT reward key is the unstamped shape (the schema only
        # constrains the key when present; `doc.get("reward")` -> None)
        bare = {k: v for k, v in zero.items() if k != "reward"}
        bare["id"] = "mission-C-778"
        bare["claim"] = "C-778"
        (ws / "runs" / "verification-C-778.md").write_text(
            "verdict: verified\nclaim: C-778\n", encoding="utf-8")
        es.episode_pool.write_episode(ws, bare)
        table = pi.value_table(ws)
        assert table[key]["n"] == 1, \
            "absent = unstamped (the honest gap), 0.0 is stamped"

    def test_one_stamp_reaches_the_scheduler_family_join(self, tmp_path):
        """ONE canonical vocabulary: a memory row stamped once is found
        by the scheduler's family join in the scheduler's own BARE
        family vocabulary — no companion token (the battery's
        double-stamp smell)."""
        ws, doc = _settled_episode(tmp_path)
        mb.stamp_family_memory(ws, doc)
        view = mb.family_view(ws)
        assert view.get("tf-snake", {}).get("mastered") is True, \
            "the family face keys the bare name the scheduler joins on"
        task = {"task_id": "t", "family": "tf-snake"}
        assert ps.retire_reasons(task, {"memory": view}) == "learned"
        assert {r["family"] for r in mb.load_rows(ws)} == {"tf-snake"}, \
            "rows carry the bare family, keys never mix vocabularies"


class TestMasteryIdentity:
    def test_scrambled_stamp_does_not_master_true_family(self, tmp_path):
        """Mastery validates the family IDENTITY of the underlying
        episode, not just the settlement's shape (the E1c finding:
        misfiled episodes re-mastered every family). The episode's OWN
        family must match the family being mastered — a misfiled stamp
        masters nothing, so a family can only ever be mastered by its
        own episodes."""
        ws, doc = _settled_episode(tmp_path)
        assert doc["family"] == "tf-snake", \
            "the episode's OWN family rides the settle stamp"
        scrambled = dict(doc, context_features=[
            "family:other-fam",
            *(f for f in doc["context_features"]
              if not f.startswith("family:"))])
        out = mb.stamp_family_memory(ws, scrambled)
        assert out["mastered"] is False, \
            "shape alone (completed + positive reward) masters nothing"
        view = mb.family_view(ws)
        assert not view.get("other-fam", {}).get("mastered"), \
            "never the mislabeled one"
        assert not view.get("tf-snake", {}).get("mastered"), \
            "a scrambled stamp never masters the true family"
        un = mb.stamp_family_memory(ws, doc)
        assert un["mastered"] is True, "unscrambled stamping does"
        assert mb.family_view(ws)["tf-snake"]["mastered"] is True
