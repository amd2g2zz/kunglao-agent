# -*- coding: utf-8 -*-
"""tests/test_reward_contract_1007.py — the reward-unit contract.

Issue 1007: ``round_credit`` is a PROVENANCE SUM (credit units), not a
[0,1] reward. The observed ledger row ``reward: 2.01`` is exactly
``2 x 1.0`` credited artifacts + ONE trace total for the single demotion
class present — the formula in ``references/contracts/reward-rules.yaml``,
not a rail violation.

This suite pins the contract:
  (a) task / q-cell settlement rewards live on the [0,1] bounded rail and
      are clamped there;
  (b) a round-credit row with two cited artifacts + one demotion class
      reproduces 2.01 from the formula (the value itself is NOT clamped);
  (c) a [0,1]-only consumer (the prior feed) excludes the round-credit
      row explicitly and reports the exclusion.

All fixtures are SYNTHETIC (privacy rule). The external workspace row
that motivated the issue (beike-verification, ``reward: 2.01``, credited
F004/F005 + demoted F006/F007) is replayed here by shape, never read
from the external path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rollout_ledger as rl  # noqa: E402
import reward_settlement as rs  # noqa: E402
import scalar_settlement as ss  # noqa: E402
from rlvr import q_cells  # noqa: E402

RULES_PATH = ROOT / "references" / "contracts" / "reward-rules.yaml"
README_PATH = ROOT / "scripts" / "rlvr" / "README.md"
TS = "2026-11-05T00:00:00Z"

DISPATCHES = [{"dispatch_id": "C-005", "round": 4}]


def _sig(type_: str, source: str, value, ts: str = TS) -> dict:
    return {"type": type_, "source": source, "value": value, "ts": ts}


def _artifact(aid: str, creator: str = "C-005", *, status: str = "PROVEN",
              cited: bool = False) -> dict:
    return {"id": aid, "creator": creator, "status": status,
            "verify_status": "passes", "cited_by_deliverable": cited,
            "answers_question": False, "oracle_backed_refutation": False}


def _task_row(reward: float, anchor: str = "C-001") -> dict:
    return {"rollout_id": f"task/{anchor}", "kind": "task",
            "anchor": anchor, "ts": TS, "signals": [],
            "reward": reward,
            "settlement": {"reward": reward, "band": "SETTLED_GREEN",
                           "rule_id": "task/oracle-green",
                           "evidence_refs": []}}


def _round_row(reward: float, anchor: str = "C-005") -> dict:
    return {"rollout_id": f"round_credit/{anchor}", "kind": "round_credit",
            "anchor": anchor, "ts": TS, "signals": [],
            "reward": reward,
            "settlement": {"reward": reward, "band": "ROUND_CREDIT",
                           "rule_id": "round/provenance-credit",
                           "evidence_refs": []}}


# ==========================================================================
# 1. the schema declares the reward range/unit PER KIND
# ==========================================================================

class TestPerKindRewardRailDeclaration:
    def test_rail_constants_and_kind_map_are_declared(self):
        assert rl.REWARD_RAIL_BOUNDED == "bounded"
        assert rl.REWARD_RAIL_PROVENANCE == "provenance"
        # the four settlement-scalar kinds are [0,1]
        for kind in ("task", "self_distill", "hybrid_distill",
                     "hypothesis"):
            assert rl.reward_rail_of(kind) == rl.REWARD_RAIL_BOUNDED, kind
            assert rl.reward_range_of(kind) == (0.0, 1.0), kind
        # round_credit is the provenance sum: no [0,1] range at all
        assert rl.reward_rail_of("round_credit") == \
            rl.REWARD_RAIL_PROVENANCE
        assert rl.reward_range_of("round_credit") is None

    def test_bounded_rows_lint_requires_the_0_1_range(self):
        for reward in (0.0, 0.5, 1.0):
            assert rl.row_schema_lint(_task_row(reward)) == [], reward
        high = _task_row(2.01)
        low = _task_row(-0.5)
        assert any("bounded" in e for e in rl.row_schema_lint(high))
        assert any("bounded" in e for e in rl.row_schema_lint(low))

    def test_provenance_rows_are_not_range_checked(self):
        # 2.01 (and negative provenance, waste > credit) stay legal
        assert rl.row_schema_lint(_round_row(2.01)) == []
        assert rl.row_schema_lint(_round_row(-0.99)) == []

    def test_explicit_rail_marker_must_agree_with_the_kind(self):
        row = _round_row(2.01)
        row["settlement"]["reward_rail"] = rl.REWARD_RAIL_BOUNDED
        assert any("reward_rail" in e for e in rl.row_schema_lint(row))
        row["settlement"]["reward_rail"] = rl.REWARD_RAIL_PROVENANCE
        assert rl.row_schema_lint(row) == []

    def test_credit_units_must_match_the_settled_value(self):
        row = _round_row(2.01)
        row["settlement"]["credit_units"] = 2.01
        assert rl.row_schema_lint(row) == []
        row["settlement"]["credit_units"] = 1.0
        assert any("credit_units" in e for e in rl.row_schema_lint(row))

    def test_settle_refuses_a_bounded_kind_outside_the_rail(self, tmp_path):
        """The write boundary never lands a row the read face would
        silently skip: a task settlement at 2.01 is refused loudly."""
        ws = tmp_path / "ws"
        ws.mkdir()
        rl.record(ws, kind="task", anchor="C-001",
                  signals=[_sig("claim_terminal", "convergence_check",
                                "PROVEN")])
        bad = rl.settle(ws, "task/C-001",
                        {"reward": 2.01, "band": "SETTLED_GREEN",
                         "rule_id": "task/oracle-green",
                         "evidence_refs": []})
        assert bad["appended"] is False
        assert "bounded" in str(bad.get("reason") or "")
        good = rl.settle(ws, "task/C-001",
                         {"reward": 1.0, "band": "SETTLED_GREEN",
                          "rule_id": "task/oracle-green",
                          "evidence_refs": []})
        assert good["appended"] is True

    def test_signed_delta_v_kind_keeps_its_unit(self):
        """The pre-existing mainline_decision rows settle a SIGNED ΔV
        (verification_ladder). The unit declaration must not turn them
        into bounded rows — a negative ΔV stays legal."""
        import verification_ladder  # noqa: F401 — registers the kind
        assert rl.reward_rail_of("mainline_decision") == \
            rl.REWARD_RAIL_SIGNED
        assert rl.reward_range_of("mainline_decision") is None
        row = {"rollout_id": "mainline_decision/t1",
               "kind": "mainline_decision", "anchor": "t1", "ts": TS,
               "signals": [], "reward": -0.3,
               "settlement": {"reward": -0.3,
                              "band": "MAINLINE_DECISION",
                              "rule_id": "mainline/delta-v",
                              "evidence_refs": []}}
        assert rl.row_schema_lint(row) == []

    def test_legacy_round_credit_row_still_lints_clean(self):
        """Rows written before the marker existed are NOT dropped on
        read: the KIND declaration is authoritative; `credit_units` and
        `reward_rail` are additive audit fields, never required."""
        legacy = {"rollout_id": "round_credit/C-001",
                  "kind": "round_credit", "anchor": "C-001", "ts": TS,
                  "signals": [], "reward": 2.01,
                  "settlement": {"reward": 2.01, "band": "ROUND_CREDIT",
                                 "rule_id": "round/provenance-credit",
                                 "evidence_refs": ["creator:C-001"]}}
        assert rl.row_schema_lint(legacy) == []

    def test_dirty_non_mapping_settlement_is_skipped_not_raised(
            self, tmp_path):
        """The rail lint must not break the fail-open read path: a dirty
        row whose settlement is not a mapping is skipped with a WARN
        (the pre-contract behavior), never an AttributeError out of
        read()/settled()/fold()."""
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        dirty = {"schema": rl.SCHEMA, "rollout_id": "task/C-1",
                 "kind": "task", "anchor": "C-1", "ts": TS,
                 "signals": [], "reward": None, "settlement": "oops"}
        (ws / "runs" / "rollout-ledger.jsonl").write_text(
            json.dumps(dirty) + "\n", encoding="utf-8")
        assert rl.read(ws) == []
        assert rl.settled(ws) == []
        assert rl.fold(ws, "task/C-1") is None
        assert rl.pending_settlement(ws) == []


# ==========================================================================
# 2. the round-credit FORMULA reproduces 2.01 (value unchanged)
# ==========================================================================

class TestRoundCreditFormula:
    def test_two_cited_plus_one_demotion_class_settles_2_01(self, tmp_path):
        """The issue's fixture shape: two cited artifacts (F004/F005) +
        one demotion class (F006/F007 both ``uncited_verified``) =
        2 x 1.0 + ONE x 0.01 = 2.01. Unclamped by construction."""
        ws = tmp_path / "ws"
        ws.mkdir()
        artifacts = [
            _artifact("F004-captcha-trigger-chain", cited=True),
            _artifact("F005-captcha-resource-localization", cited=True),
            _artifact("F006-param-localization-protocol"),
            _artifact("F007-login-entry-observation"),
        ]
        out = ss.round_credit(DISPATCHES, artifacts, waste=[])
        row = out["rows"][0]
        assert row["credited"] == ["F004-captcha-trigger-chain",
                                   "F005-captcha-resource-localization"]
        assert {e["reason"] for e in row["demoted"]} == \
            {ss.DEMOTION_UNCITED_VERIFIED}
        assert row["r"] == 2.01

        # the formula decomposition the yaml declares
        class_total = ss.TRACE_CANONICAL * len(
            {e["reason"] for e in row["demoted"]})
        formula = ss.ROUND_CREDIT_FULL * len(row["credited"]) \
            + class_total - row["waste"]
        assert formula == 2.01

        res = ss.settle_round_credit(ws, DISPATCHES, artifacts, waste=[],
                                     now=TS)
        assert res["settled"] == 1
        row = rl.fold(ws, "round_credit/C-005")
        st = row["settlement"]
        # value unchanged; the row now carries the UNIT explicitly
        assert row["reward"] == 2.01
        assert st["reward"] == 2.01
        assert st["credit_units"] == 2.01
        assert st["reward_rail"] == rl.REWARD_RAIL_PROVENANCE
        assert rl.reward_rail_of(row) == rl.REWARD_RAIL_PROVENANCE
        assert rl.row_schema_lint(row) == []

    def test_value_ladder_constants_and_yaml_are_unchanged(self):
        assert ss.ROUND_CREDIT_FULL == 1.0
        assert ss.TRACE_CANONICAL == 0.01
        import yaml
        doc = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
        ladder = doc["round_credit"]["value_ladder"]
        assert ladder["full"] == 1.0
        assert ladder["trace"] == 0.01

    def test_yaml_declares_the_two_units(self):
        import yaml
        doc = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
        units = doc["reward_units"]
        assert units["bounded"]["range"] == [0.0, 1.0]
        assert set(units["bounded"]["kinds"]) >= {
            "task", "self_distill", "hybrid_distill", "hypothesis"}
        assert units["provenance"]["kinds"] == ["round_credit"]
        assert units["provenance"]["field"] == "credit_units"
        assert units["provenance"]["rail"] == "provenance"
        # the round-credit section points at the unit explicitly
        assert doc["round_credit"]["reward_rail"] == "provenance"


# ==========================================================================
# 3. bounded-rail consumers clamp, and [0,1]-only readers EXCLUDE
# ==========================================================================

class TestBoundedRewardConsumer:
    def test_clamp_helpers_keep_task_scalars_in_0_1(self):
        assert ss.clamp_credit(2.01) == 1.0
        assert ss.clamp_credit(-0.5) == 0.0
        assert ss.clamp_credit(0.4) == 0.4
        assert ss.rail_of(2.01) == "GOLD"

    def test_q_cell_append_boundary_clamps_to_0_1(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        out = q_cells.append_observation(
            ws, "sig-hash", "chain-js", 2.01, source="settlement")
        assert out["appended"] is True
        assert out["row"]["credit"] == 1.0

    def test_prior_feed_excludes_the_round_credit_row_and_reports_it(
            self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rl.record(ws, kind="task", anchor="C-001", signals=[])
        rl.settle(ws, "task/C-001", _task_row(1.0)["settlement"])
        ss.settle_round_credit(
            ws, DISPATCHES,
            [_artifact("F004-a", cited=True), _artifact("F005-b", cited=True),
             _artifact("F006-c"), _artifact("F007-d")], waste=[], now=TS)

        split = rs.bounded_reward_rows(ws)
        assert [r["rollout_id"] for r in split["rows"]] == ["task/C-001"]
        assert [e["rollout_id"] for e in split["excluded"]] == \
            ["round_credit/C-005"]
        assert split["excluded"][0]["rail"] == rl.REWARD_RAIL_PROVENANCE
        assert split["excluded"][0]["reward"] == 2.01
        # NEVER silently read as a reward
        assert all(r["settlement"]["reward"] <= 1.0 for r in split["rows"])

        # the Beta prior feed counts only the bounded task row
        assert rs.prior_observations(ws) == (1, 0)
        # the scalar feed is explicitly task-kind already
        assert ss.scalar_observations(ws) == []

    def test_compute_priors_reports_the_exclusion(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rl.record(ws, kind="task", anchor="C-001", signals=[])
        rl.settle(ws, "task/C-001", _task_row(1.0)["settlement"])
        ss.settle_round_credit(
            ws, DISPATCHES,
            [_artifact("F004-a", cited=True), _artifact("F005-b", cited=True),
             _artifact("F006-c"), _artifact("F007-d")], waste=[], now=TS)
        from compute_priors import compute_priors
        doc = compute_priors([ws])
        ledger_src = doc["sources"]["rollout_ledger"]
        assert ledger_src["alpha"] == 1
        assert ledger_src["beta"] == 0
        assert [e["rollout_id"] for e in ledger_src["excluded"]] == \
            ["round_credit/C-005"]
        # the 2.01 never enters the Beta mass
        assert doc["alpha"] == 2.0 and doc["beta"] == 1.0

    def test_strategy_store_decay_excludes_provenance_rows(self, tmp_path):
        """The γ-ladder EMA is a [0,1]-only consumer: it must not clamp
        2.01 into a maximum outcome. Provenance rows leave the ladder
        and are reported by ``decayed_exclusions()``."""
        from rlvr import strategy_store
        ws = tmp_path / "ws"
        ws.mkdir()
        rl.record(ws, kind="task", anchor="C-001", signals=[])
        rl.settle(ws, "task/C-001", _task_row(1.0)["settlement"])
        ss.settle_round_credit(
            ws, DISPATCHES,
            [_artifact("F004-a", cited=True), _artifact("F005-b", cited=True),
             _artifact("F006-c"), _artifact("F007-d")], waste=[], now=TS)
        store = strategy_store.PosteriorStrategyStore(ws)
        # the excluded row keeps the unit default weight, never an outcome
        assert store.decayed_weight("round_credit/C-005") == 1.0
        # the bounded row still rides the ladder
        assert store.decayed_weight("task/C-001") == 1.0
        excluded = store.decayed_exclusions()
        assert [e["rollout_id"] for e in excluded] == \
            ["round_credit/C-005"]
        assert excluded[0]["rail"] == rl.REWARD_RAIL_PROVENANCE
        assert excluded[0]["reward"] == 2.01

    def test_decision_view_surfaces_the_reward_rail(self, tmp_path):
        """The newest-settlement display face names the unit next to the
        value: a 2.01 reads as ``provenance``, not as a reward."""
        import decision_view as dv
        ws = tmp_path / "ws"
        ws.mkdir()
        ss.settle_round_credit(
            ws, DISPATCHES,
            [_artifact("F004-a", cited=True), _artifact("F005-b", cited=True),
             _artifact("F006-c"), _artifact("F007-d")], waste=[], now=TS)
        face = dv.build_view(ws)["faces"]["just_settled"]
        assert face["kind"] == "round_credit"
        assert face["reward"] == 2.01
        assert face["reward_rail"] == rl.REWARD_RAIL_PROVENANCE

    def test_readme_documents_the_two_units(self):
        text = README_PATH.read_text(encoding="utf-8")
        assert "Reward units" in text
        low = text.lower()
        assert "credit_units" in low
        assert "provenance" in low
        for token in ("2.01", "[0,1]", "round_credit"):
            assert token in text
