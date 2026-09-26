# -*- coding: utf-8 -*-
"""tests/test_scalar_settlement_379.py — two-level settlement + 3-tuple (#379).

Acceptance checkboxes covered here (issue 379 + implementation spec):
  - every tier constructible from synthetic dimensions (pure if-then, no
    judgment slots);
  - first-match severity order pinned; RED overrides;
  - probe sub-scores feed dense partial (static X/Y, replay N/M, chain
    layers-completed);
  - round credit: provenance-attributed artifacts counted, attributed waste
    subtracted, untraced marked not counted, NO positional discount;
  - 3-tuple (s, a, r) extracted at settlement as the birth certificate;
  - scalar prior: exponential-family (Normal-Gamma) update, Beta counts
    untouched;
  - gamma absence pinned (no discount factor anywhere, source + behavior);
  - v1 regression pins: rules version 2 keeps /1 rows foldable, settled()
    interface unchanged.
All fixtures are SYNTHETIC (privacy rule).

NOTE: the forbidden-fragment needles below are assembled from parts so
this test file does not itself carry the escape-hatch strings it forbids.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rollout_ledger as rl  # noqa: E402
import reward_settlement as rs  # noqa: E402
import scalar_settlement as ss  # noqa: E402

RULES_PATH = ROOT / "references" / "contracts" / "reward-rules.yaml"

# forbidden escape-hatch patterns (assembled from parts)
_ESC_CALL = re.compile(r"\b(eval|" + "ex" + "ec)\s*\\(")
_NEEDLES = ("subprocess", "os." + "system", "__import__", "importlib",
            "urllib", "socket")


def _sig(type_: str, source: str, value, ts="2026-09-25T00:00:00Z",
         **extra):
    sig = {"type": type_, "source": source, "value": value, "ts": ts}
    sig.update(extra)
    return sig


def _seed(ws: Path, kind: str, anchor: str, signals: list[dict]) -> str:
    rl.record(ws, kind=kind, anchor=anchor, signals=signals)
    return f"{kind}/{anchor}"


# ---------- rules table v2 validity ----------

class TestRulesFileV2:
    def test_rules_version_bumped_v1_rows_foldable(self):
        """reward-rules/2 = version 2 of the versioned rules file; the four
        /1 rows remain foldable in the same table (issue 379 versioning)."""
        doc = rs.load_rules(RULES_PATH)
        assert doc["schema"] == "reward-rules/1"  # fold contract unchanged
        assert doc["version"] == 2
        rule_ids = {r["rule_id"] for r in doc["rules"]}
        assert {"task/oracle-green", "task/oracle-red",
                "self_distill/adverse", "self_distill/helped"} <= rule_ids

    def test_tier_table_declares_the_five_scalars(self):
        doc = rs.load_rules(RULES_PATH)
        scalars = doc["tier_table"]["scalars"]
        assert scalars["GOLD"] == 1.0
        assert scalars["SILVER"] == 0.7
        assert scalars["BRONZE"] == 0.4
        assert scalars["NEUTRAL"] == 0.0
        assert scalars["RED"] == 0.0

    def test_tier_severity_order_total_with_red_override(self):
        doc = rs.load_rules(RULES_PATH)
        tt = doc["tier_table"]
        order = list(tt["severity_order"])
        assert set(order) == set(tt["scalars"])
        assert order.index("GOLD") < order.index("SILVER") \
            < order.index("BRONZE") < order.index("NEUTRAL")
        assert tt["red_override"] is True

    def test_cost_reference_cites_measured_numbers(self):
        """The ONE free parameter k derives from the exp1-7 measured cost
        distribution — the actual numbers cited in the rules file."""
        doc = rs.load_rules(RULES_PATH)
        cr = doc["cost_reference"]
        medians = cr["unit_class_median_usd"]
        assert set(medians) == {"cc-default", "loop"}
        assert medians["cc-default"] > 0 and medians["loop"] > 0
        assert cr["k"] > 1
        cited = str(cr["measured_source"])
        # the measured figures themselves must be on the page (README
        # benchmark + exp1-7 record: ~$0.95-2/unit cc-default, $5-15/unit
        # loop, $30 the exp7 labeled higher cap)
        assert "0.95" in cited and "11.4" in cited
        assert "5-15" in cited
        assert "30" in cited and "exp7" in cited

    def test_every_dimension_declares_mechanical_source(self):
        doc = rs.load_rules(RULES_PATH)
        for name, dim in doc["tier_table"]["dimensions"].items():
            assert str(dim.get("source") or "").strip(), name
            assert "model" not in str(dim.get("source")).lower(), name

    def test_round_credit_section_pins_no_positional_discount(self):
        doc = rs.load_rules(RULES_PATH)
        rc = doc["round_credit"]
        assert rc["positional_discount"] is False
        assert "creator" in str(rc["attribution"])
        assert rc["untraced"]["counted"] is False

    def test_scalar_module_import_surface_has_no_model_call_path(self):
        """U3 extended: the scalar engine is pure if-then over machine
        signals — the import surface has no model-call path."""
        ALLOW = {"__future__", "json", "sys", "os", "re", "time",
                 "datetime", "pathlib", "typing", "yaml",
                 "rollout_ledger", "harness_common", "kunglao_log",
                 "reward_settlement"}  # the sibling U2/U3 engine itself
        tree = ast.parse(
            (SCRIPTS / "scalar_settlement.py").read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        outside = [m for m in imported if m.split(".")[0] not in ALLOW]
        assert not outside, \
            f"scalar engine imports outside allowlist: {outside}"
        text = (SCRIPTS / "scalar_settlement.py").read_text(
            encoding="utf-8")
        for needle in _NEEDLES:
            assert needle not in text, needle
        assert not _ESC_CALL.search(text), "escape hatch in scalar engine"


# ---------- tier construction from synthetic dimensions ----------

def _episode_signals(**kw) -> list[dict]:
    """A synthetic task-row signal set shaped like the machine faces:
    oracle verdict + probe sub-scores + manifest dims + cost."""
    signals = []
    if kw.get("verdict"):
        signals.append(_sig("oracle_verdict", "oracle_runner",
                            kw["verdict"]))
    if kw.get("static") is not None:
        signals.append(_sig("static_probes", "eval_checker", kw["static"]))
    if kw.get("replay") is not None:
        signals.append(_sig("replay_probes", "eval_checker", kw["replay"]))
    if kw.get("dense") is not None:
        signals.append(_sig("dense_layers", "eval_chain_grader", kw["dense"]))
    if kw.get("difficulty"):
        signals.append(_sig("unit_difficulty", "unit_manifest",
                            kw["difficulty"]))
    if kw.get("evidence"):
        signals.append(_sig("evidence_class", "rerun_discipline",
                            kw["evidence"]))
    if kw.get("cost") is not None:
        signals.append(_sig("session_cost", "cost_telemetry", kw["cost"]))
        signals.append(_sig("unit_class", "strategy_arm",
                            kw.get("unit_class", "loop")))
    return signals


def _tier(signals):
    doc = rs.load_rules(RULES_PATH)
    return ss.classify_tier(signals, doc["tier_table"],
                            doc["cost_reference"])


class TestTierConstruction:
    def test_gold(self):
        out = _tier(_episode_signals(
            verdict="pass", difficulty="hard", evidence="reproducible",
            cost=8.0))
        assert out["tier"] == "GOLD"
        assert out["tier_reward"] == 1.0
        assert out["tier_rule_id"] == "tier/gold"

    def test_silver_reproducible_standard(self):
        out = _tier(_episode_signals(
            verdict="pass", difficulty="standard", evidence="reproducible",
            cost=8.0))
        assert out["tier"] == "SILVER"
        assert out["tier_reward"] == 0.7

    def test_silver_hard_but_asserted(self):
        out = _tier(_episode_signals(
            verdict="pass", difficulty="hard", evidence="asserted",
            cost=8.0))
        assert out["tier"] == "SILVER"
        assert out["tier_reward"] == 0.7

    def test_bronze_standard_asserted(self):
        out = _tier(_episode_signals(
            verdict="pass", difficulty="standard", evidence="asserted",
            cost=8.0))
        assert out["tier"] == "BRONZE"
        assert out["tier_reward"] == 0.4

    def test_bronze_when_cost_between_median_and_k(self):
        """cost in (median, k*median] forfeits GOLD/SILVER — BRONZE."""
        doc = rs.load_rules(RULES_PATH)
        loop_median = doc["cost_reference"]["unit_class_median_usd"]["loop"]
        k = doc["cost_reference"]["k"]
        out = _tier(_episode_signals(
            verdict="pass", difficulty="hard", evidence="reproducible",
            cost=loop_median * (k * 0.5)))  # 1.5x median, <= k*median
        assert out["tier"] == "BRONZE"

    def test_expensive_pass_is_the_inefficient_fold(self):
        """cost > k * class-median = the issue's INEFFICIENT tier, folded
        into BRONZE scalar 0.4 with the inefficiency named in the rule."""
        doc = rs.load_rules(RULES_PATH)
        loop_median = doc["cost_reference"]["unit_class_median_usd"]["loop"]
        k = doc["cost_reference"]["k"]
        out = _tier(_episode_signals(
            verdict="pass", difficulty="hard", evidence="reproducible",
            cost=loop_median * k * 1.1))
        assert out["tier"] == "BRONZE"
        assert out["tier_reward"] == 0.4
        assert out["tier_rule_id"] == "tier/bronze-expensive"
        assert out["inefficient"] is True

    def test_red_overrides_everything(self):
        out = _tier(_episode_signals(
            verdict="fail", difficulty="hard", evidence="reproducible",
            cost=1.0, dense={"completed": 0, "total": 4}))
        assert out["tier"] == "RED"
        assert out["tier_reward"] == 0.0

    def test_neutral_single_signal(self):
        out = _tier([_sig("oracle_verdict", "oracle_runner", "pass")])
        assert out["tier"] == "NEUTRAL"
        assert out["tier_reward"] == 0.0

    def test_neutral_no_verdict(self):
        out = _tier(_episode_signals(
            verdict=None, difficulty="hard", evidence="reproducible",
            cost=8.0))
        # no oracle verdict: difficulty+evidence+cost present but the
        # outcome axis is missing -> pending
        assert out["tier"] == "NEUTRAL"

    def test_first_match_gold_beats_silver(self):
        out = _tier(_episode_signals(
            verdict="pass", difficulty="hard", evidence="reproducible",
            cost=1.0))
        assert out["tier_rule_id"] == "tier/gold"

    def test_cc_default_class_uses_its_own_median(self):
        """A cc-default-priced pass at $1.5 is AT its class median: GOLD
        still reachable on the cheap arm — class reference, not global."""
        out = _tier(_episode_signals(
            verdict="pass", difficulty="hard", evidence="reproducible",
            cost=1.5, unit_class="cc-default"))
        assert out["tier"] == "GOLD"


# ---------- probe sub-scores feed dense partial ----------

class TestDensePartial:
    def test_replay_subscores_feed_partial(self):
        out = _tier(_episode_signals(
            verdict="fail", replay={"passed": 3, "total": 5},
            difficulty="standard", evidence="reproducible", cost=8.0))
        assert out["dimensions"]["outcome"]["outcome"] == "partial"
        assert out["tier"] == "BRONZE"
        assert out["tier_reward"] == 0.4
        assert out["tier_rule_id"] == "tier/partial-dense"
        assert out["dimensions"]["outcome"]["p"] == pytest.approx(0.6)

    def test_static_subscores_feed_partial(self):
        out = _tier(_episode_signals(
            verdict="fail", static={"passed": 2, "total": 4},
            difficulty="hard", evidence="asserted", cost=8.0))
        assert out["dimensions"]["outcome"]["outcome"] == "partial"

    def test_chain_dense_layers_feed_partial(self):
        out = _tier(_episode_signals(
            verdict="fail", dense={"completed": 2, "total": 4},
            difficulty="hard", evidence="reproducible", cost=8.0))
        assert out["dimensions"]["outcome"]["outcome"] == "partial"
        assert out["dimensions"]["outcome"]["p"] == pytest.approx(0.5)
        assert out["tier_reward"] == 0.4

    def test_zero_progress_fail_stays_fail(self):
        out = _tier(_episode_signals(
            verdict="fail", replay={"passed": 0, "total": 5},
            static={"passed": 0, "total": 4},
            dense={"completed": 0, "total": 4},
            difficulty="hard", evidence="reproducible", cost=8.0))
        assert out["dimensions"]["outcome"]["outcome"] == "fail"
        assert out["tier"] == "RED"

    def test_partial_never_reaches_gold_or_silver(self):
        """A partial outcome caps at the BRONZE-equivalent scalar even with
        perfect hard/reproducible/cheap dimensions."""
        out = _tier(_episode_signals(
            verdict="fail", dense={"completed": 3, "total": 4},
            difficulty="hard", evidence="reproducible", cost=1.0))
        assert out["tier"] == "BRONZE"
        assert out["tier_reward"] == 0.4


# ---------- round credit settlement ----------

def _artifact(aid, creator, status="PROVEN", verify="passes",
              cited=False, refutation=False):
    return {"id": aid, "creator": creator, "status": status,
            "verify_status": verify, "cited_by_deliverable": cited,
            "oracle_backed_refutation": refutation}


DISPATCHES = [{"dispatch_id": "tr-m1-d1", "round": 1},
              {"dispatch_id": "tr-m1-d2", "round": 2}]


class TestRoundCredit:
    def test_provenance_attributed_artifacts_counted(self):
        artifacts = [_artifact("F001-a", "tr-m1-d1"),
                     _artifact("F002-b", "tr-m1-d1", cited=True),
                     _artifact("F003-c", "tr-m1-d1", status="OPEN")]
        out = ss.round_credit(DISPATCHES, artifacts, waste=[])
        row = next(r for r in out["rows"] if r["dispatch_id"] == "tr-m1-d1")
        assert row["credited"] == ["F001-a", "F002-b"]
        assert row["r"] == 2.0

    def test_oracle_backed_refutation_counts(self):
        artifacts = [_artifact("F010-n", "tr-m1-d1", status="NEGATIVE",
                               refutation=True),
                     _artifact("F011-n", "tr-m1-d1", status="NEGATIVE",
                               refutation=False)]
        out = ss.round_credit(DISPATCHES, artifacts, waste=[])
        row = out["rows"][0]
        assert row["credited"] == ["F010-n"]
        assert row["r"] == 1.0

    def test_attributed_waste_subtracted(self):
        artifacts = [_artifact("F020-a", "tr-m1-d2")]
        waste = [{"kind": "decoy_follow", "dispatch_id": "tr-m1-d2",
                  "ref": "C-9"}]
        out = ss.round_credit(DISPATCHES, artifacts, waste)
        row = next(r for r in out["rows"] if r["dispatch_id"] == "tr-m1-d2")
        assert row["waste"] == 1.0
        assert row["r"] == 0.0  # 1 credited - 1 waste

    def test_untraced_marked_not_counted(self):
        artifacts = [_artifact("F030-x", creator=None),
                     _artifact("F031-y", "tr-m1-d1")]
        out = ss.round_credit(DISPATCHES, artifacts, waste=[])
        assert out["untraced"] == ["F030-x"]
        row = out["rows"][0]
        assert "F030-x" not in row["credited"]
        assert row["r"] == 1.0

    def test_no_positional_discount_order_invariant(self):
        """gamma ruled out: round ORDER changes nothing — per-dispatch r is
        a provenance sum, never position-weighted."""
        artifacts = [_artifact("F040-a", "tr-m1-d1"),
                     _artifact("F041-b", "tr-m1-d2")]
        waste = [{"kind": "decoy_follow", "dispatch_id": "tr-m1-d2",
                  "ref": "C-9"}]
        fwd = ss.round_credit(DISPATCHES, artifacts, waste)
        rev = ss.round_credit(list(reversed(DISPATCHES)), artifacts, waste)
        by_dispatch = lambda out: {r["dispatch_id"]: r["r"]
                                   for r in out["rows"]}
        assert by_dispatch(fwd) == by_dispatch(rev) \
            == {"tr-m1-d1": 1.0, "tr-m1-d2": 0.0}

    def test_round_credit_rows_land_in_the_ledger(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        artifacts = [_artifact("F050-a", "tr-m1-d1")]
        waste = [{"kind": "decoy_follow", "dispatch_id": "tr-m1-d1",
                  "ref": "C-9"}]
        res = ss.settle_round_credit(ws, DISPATCHES, artifacts, waste,
                                     now="2026-09-25T00:00:00Z")
        assert res["settled"] == 2
        row = rl.fold(ws, "round_credit/tr-m1-d1")
        assert row["settlement"]["band"] == "ROUND_CREDIT"
        assert row["settlement"]["reward"] == 0.0
        assert row["settlement"]["credited"] == ["F050-a"]
        assert row["settlement"]["waste"] == 1.0
        # idempotent at a LATER wall-clock time: the signal ts freezes at
        # the row identity, so record/settle dedupe (no ledger churn)
        again = ss.settle_round_credit(ws, DISPATCHES, artifacts, waste,
                                       now="2026-09-25T09:99:00Z")
        assert again["settled"] == 0
        assert len([r for r in rl.read(ws)
                    if r["rollout_id"] == "round_credit/tr-m1-d1"]) == 2

    def test_round_credit_rows_feed_no_prior(self, tmp_path):
        """ROUND_CREDIT band is polarity-none: the Beta prior feed (v1)
        must not read it; the scalar feed reads episode scalars only."""
        ws = tmp_path / "ws"
        ws.mkdir()
        ss.settle_round_credit(ws, DISPATCHES,
                               [_artifact("F060-a", "tr-m1-d1")], [])
        assert rs.prior_observations(ws) == (0, 0)
        assert ss.scalar_observations(ws) == []


# ---------- 3-tuple extraction ----------

class TestExperienceTuple:
    def _seed_episode(self, ws: Path) -> str:
        # real settled-episode shape: v1 terminal corroboration present
        signals = ([_sig("claim_terminal", "convergence_check", "PROVEN")]
                   + _episode_signals(
                       verdict="pass", difficulty="hard",
                       evidence="reproducible", cost=8.0))
        signals += [_sig("unit_family", "unit_manifest", "chain-js"),
                    _sig("unit_tier", "unit_manifest", "chain"),
                    _sig("strategy_arm", "strategy_arm", "loop"),
                    _sig("method_choices", "strategy_arm",
                         ["dispatch", "checkpoint-layers"])]
        _seed(ws, "task", "C-379", signals)
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        ss.settle_workspace_scalars(ws, rules_path=RULES_PATH)
        return "task/C-379"

    def test_tuple_extracted_from_real_shaped_episode(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rid = self._seed_episode(ws)
        row = rl.fold(ws, rid)
        st = row["settlement"]
        tup = st["experience_tuple"]
        assert tup["s"] == {"family": "chain-js", "tier": "chain",
                            "difficulty": "hard"}
        assert tup["a"] == {"arm": "loop",
                            "choices": ["dispatch", "checkpoint-layers"]}
        assert tup["r"] == 1.0
        assert st["tier"] == "GOLD"
        assert st["tier_reward"] == 1.0

    def test_v1_band_and_reward_unchanged_on_scalar_amendment(self, tmp_path):
        """settled() interface unchanged: the scalar amendment refines
        within the v1 settlement — band SETTLED_GREEN, reward 1.0 stay."""
        ws = tmp_path / "ws"
        ws.mkdir()
        rid = self._seed_episode(ws)
        row = rl.fold(ws, rid)
        assert row["settlement"]["band"] == "SETTLED_GREEN"
        assert row["settlement"]["reward"] == 1.0
        assert row["settlement"]["rule_id"] == "task/oracle-green"
        assert row["reward"] == 1.0
        # and the v1 polarity feed still reads the row
        assert rs.prior_observations(ws, kind="task") == (1, 0)

    def test_tuples_read_face(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        self._seed_episode(ws)
        tups = ss.tuples(ws)
        assert len(tups) == 1
        assert tups[0]["s"]["family"] == "chain-js"
        assert tups[0]["r"] == 1.0
        assert tups[0]["rollout_id"] == "task/C-379"

    def test_tuple_absent_dims_are_explicit_nulls(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        signals = [_sig("oracle_verdict", "oracle_runner", "pass"),
                   _sig("claim_terminal", "convergence_check", "PROVEN")]
        _seed(ws, "task", "C-380", signals)
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        ss.settle_workspace_scalars(ws, rules_path=RULES_PATH)
        st = rl.fold(ws, "task/C-380")["settlement"]
        # GREEN band but no dims -> tier NEUTRAL, s-fields null, not missing
        assert st["tier"] == "NEUTRAL"
        assert st["experience_tuple"]["s"] == {"family": None,
                                               "tier": None,
                                               "difficulty": None}
        assert st["experience_tuple"]["r"] == 0.0


# ---------- scalar prior (exponential family) ----------

class TestScalarPrior:
    def test_scalar_observations_from_settled_episodes(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        gold = ([_sig("claim_terminal", "convergence_check", "PROVEN")]
                + _episode_signals(verdict="pass", difficulty="hard",
                                   evidence="reproducible", cost=8.0))
        bronze = ([_sig("claim_terminal", "convergence_check", "PROVEN")]
                  + _episode_signals(verdict="pass", difficulty="standard",
                                     evidence="asserted", cost=9.0))
        red = ([_sig("claim_terminal", "convergence_check", "NEGATIVE")]
               + _episode_signals(verdict="fail", difficulty="hard",
                                  evidence="reproducible", cost=1.0,
                                  dense={"completed": 0, "total": 4}))
        _seed(ws, "task", "C-1", gold)
        _seed(ws, "task", "C-2", bronze)
        _seed(ws, "task", "C-3", red)
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        ss.settle_workspace_scalars(ws, rules_path=RULES_PATH)
        obs = sorted(ss.scalar_observations(ws), reverse=True)
        assert obs == [1.0, 0.4, 0.0]

    def test_neutral_is_not_an_observation(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _seed(ws, "task", "C-4",
              [_sig("oracle_verdict", "oracle_runner", "pass"),
               _sig("claim_terminal", "convergence_check", "PROVEN")])
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        ss.settle_workspace_scalars(ws, rules_path=RULES_PATH)
        assert ss.scalar_observations(ws) == []

    def test_normal_gamma_update_shape_and_direction(self):
        post = ss.normal_gamma_update([1.0, 1.0, 0.4])
        assert post["n"] == 3
        assert post["mu"] == pytest.approx(0.725)  # (0.5 + 3*0.8) / 4
        assert post["kappa"] == pytest.approx(4.0)
        assert 0.5 < post["mu"] < 1.0

    def test_normal_gamma_empty_is_the_documented_prior(self):
        post = ss.normal_gamma_update([])
        assert post["n"] == 0
        assert post["mu"] == 0.5
        assert post["kappa"] == 1.0

    def test_merge_equals_one_update_over_all_observations(self):
        """Pooling per-workspace posteriors is EXACT: the weak prior
        enters once, so merge([ws1],[ws2]) == update(all obs)."""
        direct = ss.normal_gamma_update([1.0, 0.4])
        p1 = ss.normal_gamma_update([1.0])
        p2 = ss.normal_gamma_update([0.4])
        merged = ss.merge_normal_gamma_posts([p1, p2])
        assert merged["n"] == direct["n"] == 2
        for key in ("mu", "kappa", "alpha", "beta"):
            assert merged[key] == pytest.approx(direct[key]), key

    def test_merge_empty_is_the_weak_prior(self):
        weak = ss.normal_gamma_update([])
        assert ss.merge_normal_gamma_posts([]) == weak
        assert ss.merge_normal_gamma_posts(
            [ss.normal_gamma_update([])]) == weak

    def test_advisory_signals_never_corroborate_a_tier(self):
        """U3 behavioral pin at the tier layer: a model-judged advisory
        score is neither an outcome nor a corroborator — a single machine
        verdict plus any number of advisory signals stays NEUTRAL."""
        out = _tier([_sig("oracle_verdict", "oracle_runner", "pass"),
                     _sig("quality_score", "model", 0.97, advisory=True),
                     _sig("quality_score", "model", 0.93, advisory=True)])
        assert out["tier"] == "NEUTRAL"
        assert out["tier_reward"] == 0.0

    def test_compute_priors_additive_scalar_source(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _seed(ws, "task", "C-5",
              [_sig("claim_terminal", "convergence_check", "PROVEN")]
              + _episode_signals(verdict="pass", difficulty="hard",
                                 evidence="reproducible", cost=8.0))
        rs.settle_workspace(ws, rules_path=RULES_PATH)
        import compute_priors as cp
        before = cp.compute_priors([ws])  # v1 polarity feed only
        ss.settle_workspace_scalars(ws, rules_path=RULES_PATH)
        doc = cp.compute_priors([ws])
        src = doc["sources"]["scalar_ledger"]
        assert src["n"] == 1
        assert src["mean"] == pytest.approx(1.0)
        assert src["posterior"]["n"] == 1
        # Beta counts untouched BY the scalar settlement (NOT
        # Beta-Bernoulli): alpha/beta identical before vs after
        assert doc["alpha"] == before["alpha"]
        assert doc["beta"] == before["beta"]
        # v1 namespaces unchanged in shape
        assert doc["sources"]["rollout_ledger"] \
            == before["sources"]["rollout_ledger"] \
            == {"alpha": 1, "beta": 0}


# ---------- gamma absence pinned ----------

class TestGammaAbsence:
    MODULES = ("scalar_settlement.py", "compute_priors.py")

    def test_no_discount_or_decay_terms_in_source(self):
        for name in self.MODULES:
            text = (SCRIPTS / name).read_text(encoding="utf-8").lower()
            for needle in ("discount", "decay", "γ", "g=0.9"):
                assert needle not in text, f"{name}: {needle}"

    def test_gamma_word_only_as_the_normal_gamma_prior_name(self):
        """'gamma' may appear ONLY spelled as the Normal-Gamma conjugate
        prior name — never as a per-step discount symbol."""
        for name in self.MODULES:
            for line in (SCRIPTS / name).read_text(
                    encoding="utf-8").splitlines():
                low = line.lower()
                if "gamma" not in low:
                    continue
                assert "normal_gamma" in low or "normal-gamma" in low, \
                    f"{name}: bare gamma: {line.strip()}"

    def test_no_positional_weighting_in_round_credit(self):
        """Behavioral half of the gamma pin: the pure round-credit core
        has no round-position parameter to weight by."""
        import inspect
        params = set(inspect.signature(ss.round_credit).parameters)
        assert "round" not in params


# ---------- fact provenance read face (creator field) ----------

class TestFactProvenanceFace:
    def _fact(self, ws: Path, fid: str, creator, status="PROVEN",
              verify="passes", trace=None) -> None:
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "facts").mkdir(exist_ok=True)
        lines = ["---", f"id: {fid}", "type: fact", f"status: {status}"]
        if verify:
            lines.append(f"verify_status: {verify}")
        if creator:
            lines.append(f"creator: {creator}")
        if trace:
            lines.append(f"trace_id: {trace}")
        lines += ["---", "", "## Claim", "", "demo", "",
                  "## Status", "", status]
        (ws / "facts" / f"{fid}.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")

    def test_creator_field_attribution(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        self._fact(ws, "F001-a", "tr-m1-d1")
        rows = ss.fact_artifacts(ws)
        assert rows == [{"id": "F001-a", "creator": "tr-m1-d1",
                         "status": "PROVEN", "verify_status": "passes",
                         "cited_by_deliverable": False,
                         "oracle_backed_refutation": False}]

    def test_trace_id_fallback_attributes_to_the_mission(self, tmp_path):
        """No creator -> trace_id fallback (mission-stable attribution,
        not dispatch-exact — the fallback is coarser by design)."""
        ws = tmp_path / "ws"
        ws.mkdir()
        self._fact(ws, "F002-b", creator=None, trace="tr-m9-mission")
        rows = ss.fact_artifacts(ws)
        assert rows[0]["creator"] == "tr-m9-mission"

    def test_cited_ids_face(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        self._fact(ws, "F003-c", "tr-m1-d1")
        rows = ss.fact_artifacts(ws, cited_ids={"F003-c"})
        assert rows[0]["cited_by_deliverable"] is True

    def test_no_facts_dir_is_empty(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        assert ss.fact_artifacts(ws) == []

    def test_creator_is_a_known_frontmatter_key(self, tmp_path):
        """lint_facts #532 known-key table grew by exactly this key."""
        import lint_facts
        assert "creator" in lint_facts.KNOWN_FRONTMATTER_KEYS
