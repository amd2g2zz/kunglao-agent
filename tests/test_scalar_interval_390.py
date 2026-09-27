# -*- coding: utf-8 -*-
"""tests/test_scalar_interval_390.py — deterministic validator face (issues 390/396).

Scope (owner redesign 2026-09-26; issue 396 supersedes the band-matching
shape of issue 390/388-remainder): the issue-390 owner-ruled intervals
are DEMOTED to the verifier's OUTPUT SCALE. This module pins the
deterministic validator in scalar_settlement.py — the three mechanical
passes over a parsed verifier verdict doc (the XML->dict adapter lives
with the verifier face, a later maker on issue 396):

  1. citation resolution — every evidence citation must resolve to a real
     ledger rollout id / fact id; ONE unresolvable citation rejects the
     WHOLE verdict doc (fail-closed hallucination wall);
  2. rail clamping — verifier-emitted credit scalars clamp into the
     declared rails (GOLD [0.85, 1.0] / SILVER [0.55, 0.85] /
     BRONZE [0.15, 0.55] / TRACE [0.0, 0.05] canonical 0.01 /
     NEUTRAL+RED {0.0}); declared reference bands, NOT tuned weights;
  3. oracle non-overridability — a pass verdict locks reward at 1.0
     (hard currency); a fail verdict caps at the TRACE rail top (0.05)
     and floors at the TRACE canonical 0.01 when the trajectory carries
     rerun-reproducible evidence (anti-surrender: refuted-with-replay-
     evidence = low positive; surrender with no evidence settles 0.0).

Amendment-path pins: late evidence amends settled rows through the
append-only ledger (record amendment -> settle reopens); the audit chain
stays answerable; no band-matching rules are added and the rules yaml is
NOT rewritten by this change.
All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

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


def _sig(type_: str, source: str, value, ts="2026-09-26T00:00:00Z",
         **extra):
    sig = {"type": type_, "source": source, "value": value, "ts": ts}
    sig.update(extra)
    return sig


def _verdict_doc(actions, trajectory_credit):
    """Parsed verifier verdict doc shape (XML->dict is the verifier
    face's job; the validator only sees this structured form)."""
    return {"actions": list(actions), "trajectory_credit": trajectory_credit}


def _action(aid, credit, evidence):
    return {"action_id": aid, "credit": credit, "evidence": list(evidence)}


def _seed_fact(ws: Path, fid: str, status="NEGATIVE", verify="passes") -> None:
    """Synthetic fact file (fact provenance face the citations resolve to)."""
    (ws / "facts").mkdir(parents=True, exist_ok=True)
    (ws / "facts" / f"{fid}.md").write_text(
        "\n".join(["---", f"id: {fid}", "type: fact", f"status: {status}",
                   f"verify_status: {verify}", "creator: tr-d1", "---", "",
                   "## Claim", "demo", ""]) + "\n", encoding="utf-8")


# ---------- the declared output rails (issue-390 intervals, now the scale) -

class TestOutputRails:
    def test_rails_declared_exactly(self):
        """The owner-ruled issue-390 intervals, verbatim, as clamp bounds."""
        r = ss.OUTPUT_RAILS
        assert r["GOLD"]["range"] == [0.85, 1.0]
        assert r["SILVER"]["range"] == [0.55, 0.85]
        assert r["BRONZE"]["range"] == [0.15, 0.55]
        assert r["TRACE"]["range"] == [0.0, 0.05]
        assert r["TRACE"]["canonical"] == 0.01
        assert r["NEUTRAL"]["range"] == [0.0, 0.0]
        assert r["RED"]["range"] == [0.0, 0.0]

    def test_rails_are_clamp_bounds_not_tuned_weights(self):
        """Declared reference bands — the constant carries the derivation
        note (no tuned weights) on its face."""
        import inspect
        src = inspect.getsource(ss)
        assert "NOT tuned weights" in src
        assert "0.01" in str(ss.OUTPUT_RAILS["TRACE"]["canonical"])

    def test_rules_yaml_not_rewritten_by_this_change(self):
        """issue-396 rescope: the validator adds NO rules-table rewrite. The
        shipped yaml stays the /1-schema document it was."""
        doc = rs.load_rules(RULES_PATH)
        assert doc["schema"] == "reward-rules/1"
        assert "tier_table" in doc  # untouched issue-379/388 territory

    def test_rail_of_names_the_band(self):
        assert ss.rail_of(0.9) == "GOLD"
        assert ss.rail_of(0.7) == "SILVER"
        assert ss.rail_of(0.3) == "BRONZE"
        assert ss.rail_of(0.02) == "TRACE"
        assert ss.rail_of(0.01) == "TRACE"
        assert ss.rail_of(0.0, "fail") == "RED"
        assert ss.rail_of(0.0, "pass") == "NEUTRAL"

    def test_clamp_credit_bounds(self):
        assert ss.clamp_credit(0.62) == pytest.approx(0.62)
        assert ss.clamp_credit(-0.5) == 0.0
        assert ss.clamp_credit(1.7) == 1.0
        assert ss.clamp_credit(None) == 0.0
        assert ss.clamp_credit("0.3") == pytest.approx(0.3)


# ---------- pass 1: citation resolution (hallucination wall) ---------------

class TestCitationResolution:
    def test_all_citations_resolve(self, tmp_path):
        _seed_fact(tmp_path, "F100-a")
        rl.record(tmp_path, kind="task", anchor="C-1", signals=[])
        registry = ss.resolvable_registry(tmp_path)
        doc = _verdict_doc([_action("a1", 0.7, ["F100-a", "task/C-1"])], 0.7)
        out = ss.validate_verdict_doc(doc, registry, "pass", False)
        assert out["ok"] is True
        assert out["errors"] == []

    def test_one_fake_citation_rejects_the_whole_doc(self, tmp_path):
        _seed_fact(tmp_path, "F100-a")
        registry = ss.resolvable_registry(tmp_path)
        doc = _verdict_doc([
            _action("a1", 0.7, ["F100-a"]),
            _action("a2", 0.3, ["F999-fake"]),
        ], 0.5)
        out = ss.validate_verdict_doc(doc, registry, "pass", False)
        assert out["ok"] is False
        assert any("a2" in e and "F999-fake" in e for e in out["errors"])
        assert out["reward"] == 0.0  # nothing settles on a rejected doc

    def test_rejected_doc_writes_no_settlement(self, tmp_path):
        signals = [_sig("oracle_verdict", "oracle_runner", "pass")]
        rl.record(tmp_path, kind="task", anchor="C-2", signals=signals)
        before = len(rl.read(tmp_path))
        res = ss.apply_trajectory_settlement(
            tmp_path, "task/C-2",
            _verdict_doc([_action("a1", 0.9, ["F-nope"])], 0.9),
            oracle_verdict="pass", has_reproducible_evidence=False)
        assert res["settled"] is False
        assert res["reason"] == "validation failed"
        assert len(rl.read(tmp_path)) == before  # fail-closed: no write


# ---------- pass 2: rail clamping ----------

class TestRailClamping:
    def test_per_action_credits_clamped_into_rails(self):
        doc = _verdict_doc([
            _action("in-range", 0.62, []),
            _action("over", 1.7, []),
            _action("under", -0.4, []),
        ], 0.62)
        out = ss.validate_verdict_doc(doc, set(), None, False)
        credits = {a["action_id"]: a["credit"] for a in out["actions"]}
        assert credits["in-range"] == pytest.approx(0.62)
        assert credits["over"] == 1.0
        assert credits["under"] == 0.0
        rails = {a["action_id"]: a["rail"] for a in out["actions"]}
        assert rails["in-range"] == "SILVER"
        assert rails["over"] == "GOLD"
        assert rails["under"] == "NEUTRAL"


# ---------- pass 3: oracle non-overridability + anti-surrender -------------

class TestOracleNonOverridability:
    def test_pass_locks_reward_at_one(self):
        """The checker verdict is the hard currency: verifier credit
        cannot LOWER a pass."""
        out = ss.validate_verdict_doc(
            _verdict_doc([_action("a1", 0.3, ["x"])], 0.3),
            {"x"}, "pass", False)
        assert out["ok"] is True
        assert out["locked"] is True
        assert out["reward"] == 1.0
        assert out["tier"] == "GOLD"

    def test_fail_capped_at_trace_top(self):
        """Verifier credit cannot RAISE a fail into pass territory."""
        out = ss.validate_verdict_doc(
            _verdict_doc([_action("a1", 0.9, ["x"])], 0.9),
            {"x"}, "fail", True)
        assert out["ok"] is True
        assert out["capped"] is True
        assert out["reward"] == pytest.approx(0.05)
        assert out["tier"] == "TRACE"

    def test_no_oracle_verdict_no_lock_no_cap(self):
        out = ss.validate_verdict_doc(
            _verdict_doc([_action("a1", 0.62, ["x"])], 0.62),
            {"x"}, None, False)
        assert out["locked"] is False and out["capped"] is False
        assert out["reward"] == pytest.approx(0.62)


class TestAntiSurrender:
    """Owner design addition (issue 390 in-flight note + issue-396 rubric
    line): refuted/NEGATIVE WITH replay evidence = low positive (TRACE
    0.01-class) — verified negative findings are real RE deliverables.
    Surrender (no replay evidence) stays RED-equivalent zero. Reuses the
    TRACE rail; no new band, no new reward kind."""

    def test_refuted_with_replay_evidence_floors_at_trace(self):
        out = ss.validate_verdict_doc(
            _verdict_doc([_action("a1", 0.0, ["x"])], 0.0),
            {"x"}, "fail", True)
        assert out["ok"] is True
        assert out["floor_applied"] is True
        assert out["reward"] == pytest.approx(0.01)
        assert out["tier"] == "TRACE"

    def test_refuted_measured_credit_survives_above_floor(self):
        """The floor is a FLOOR: a verifier-scored 0.02 stays 0.02 (and
        anything above the cap is capped) — measured, not flattened."""
        out = ss.validate_verdict_doc(
            _verdict_doc([_action("a1", 0.02, ["x"])], 0.02),
            {"x"}, "fail", True)
        assert out["floor_applied"] is False
        assert out["reward"] == pytest.approx(0.02)

    def test_surrender_without_evidence_stays_zero(self):
        out = ss.validate_verdict_doc(
            _verdict_doc([_action("a1", 0.0, ["x"])], 0.0),
            {"x"}, "fail", False)
        assert out["ok"] is True
        assert out["floor_applied"] is False
        assert out["reward"] == 0.0
        assert out["tier"] == "RED"


# ---------- settlement writer + amendment path ----------

class TestAmendmentPath:
    def _seed_refuted(self, ws: Path) -> None:
        signals = [_sig("oracle_verdict", "oracle_runner", "fail"),
                   _sig("claim_terminal", "convergence_check", "REFUTED"),
                   _sig("unit_difficulty", "unit_manifest", "hard")]
        rl.record(ws, kind="task", anchor="C-am1", signals=signals)

    def test_valid_doc_settles_trajectory_credit(self, tmp_path):
        self._seed_refuted(tmp_path)
        _seed_fact(tmp_path, "F200-a")
        res = ss.apply_trajectory_settlement(
            tmp_path, "task/C-am1",
            _verdict_doc([_action("probe-wall", 0.02, ["F200-a"])], 0.02),
            oracle_verdict="fail", has_reproducible_evidence=True)
        assert res["settled"] is True
        st = rl.fold(tmp_path, "task/C-am1")["settlement"]
        assert st["tier"] == "TRACE"
        assert st["tier_reward"] == pytest.approx(0.02)
        assert st["trajectory_rule_id"] == "trajectory/verifier-credit"
        assert st["oracle_locked"] is False

    def test_late_evidence_amends_the_settled_row(self, tmp_path):
        """Surrender settles 0.0; rerun-reproducible evidence arriving
        LATE reopens the settled row through a record amendment and the
        re-applied validator floors it to the TRACE canonical."""
        self._seed_refuted(tmp_path)
        _seed_fact(tmp_path, "F201-a")
        first = ss.apply_trajectory_settlement(
            tmp_path, "task/C-am1",
            _verdict_doc([_action("a1", 0.0, ["F201-a"])], 0.0),
            oracle_verdict="fail", has_reproducible_evidence=False)
        assert first["settled"] is True
        assert rl.fold(tmp_path, "task/C-am1")["settlement"]["reward"] == 0.0
        rows_after_first = len(rl.read(tmp_path))
        # LATE EVIDENCE: a new machine signal joins the same rollout
        late = _sig("evidence_class", "rerun_discipline", "reproducible",
                    ts="2026-09-26T09:00:00Z")
        rec = rl.record(tmp_path, kind="task", anchor="C-am1",
                        signals=[_sig("oracle_verdict", "oracle_runner",
                                      "fail"),
                                 _sig("claim_terminal", "convergence_check",
                                      "REFUTED"),
                                 _sig("unit_difficulty", "unit_manifest",
                                      "hard"), late])
        assert rec["appended"] is True  # signal-set change amends
        second = ss.apply_trajectory_settlement(
            tmp_path, "task/C-am1",
            _verdict_doc([_action("a1", 0.0, ["F201-a"])], 0.0),
            oracle_verdict="fail", has_reproducible_evidence=True)
        assert second["settled"] is True
        st = rl.fold(tmp_path, "task/C-am1")["settlement"]
        assert st["reward"] == pytest.approx(0.01)  # floor now applies
        assert st["tier"] == "TRACE"
        assert st["anti_surrender_floor"] is True
        # append-only audit chain: rows only grew, nothing rewritten
        assert len(rl.read(tmp_path)) > rows_after_first

    def test_identical_reapplication_is_idempotent(self, tmp_path):
        self._seed_refuted(tmp_path)
        _seed_fact(tmp_path, "F202-a")
        args = dict(oracle_verdict="fail", has_reproducible_evidence=True)
        doc = _verdict_doc([_action("a1", 0.02, ["F202-a"])], 0.02)
        assert ss.apply_trajectory_settlement(
            tmp_path, "task/C-am1", doc, **args)["settled"] is True
        again = ss.apply_trajectory_settlement(
            tmp_path, "task/C-am1", doc, **args)
        assert again["settled"] is False
        assert "duplicate" in str(again["reason"])

    def test_v1_hard_currency_survives_the_amendment(self, tmp_path):
        """The v1 rule-settled band/reward lineage is preserved: the
        trajectory amendment carries the prior settlement forward (audit
        chain answers 'where did this score come from')."""
        signals = [_sig("oracle_verdict", "oracle_runner", "fail"),
                   _sig("claim_terminal", "convergence_check", "NEGATIVE"),
                   _sig("unit_difficulty", "unit_manifest", "hard"),
                   _sig("evidence_class", "rerun_discipline",
                        "reproducible")]
        rl.record(tmp_path, kind="task", anchor="C-am2", signals=signals)
        rs.settle_workspace(tmp_path, rules_path=RULES_PATH)
        _seed_fact(tmp_path, "F203-a")
        res = ss.apply_trajectory_settlement(
            tmp_path, "task/C-am2",
            _verdict_doc([_action("a1", 0.02, ["F203-a"])], 0.02),
            oracle_verdict="fail", has_reproducible_evidence=True)
        assert res["settled"] is True
        st = rl.fold(tmp_path, "task/C-am2")["settlement"]
        assert st["band"] == "SETTLED_RED"   # v1 lineage carried forward
        assert st["rule_id"] == "task/oracle-red"
        assert st["reward"] == pytest.approx(0.02)  # v3 authoritative scalar
        assert st["tier"] == "TRACE"


# ---------- invariants ----------

class TestInvariants396:
    def test_validator_is_off_the_signal_matching_path(self):
        """The validator adds NO band-matching rules: no new rules-table
        rows, no severity machinery — three mechanical passes only."""
        import inspect
        src = inspect.getsource(ss)
        assert "severity_order" not in ss.OUTPUT_RAILS.__repr__().lower()
        # the validator functions take no tier_table/rules doc
        for fn in (ss.validate_verdict_doc, ss.oracle_lock,
                   ss.resolve_citations, ss.clamp_credit):
            params = set(inspect.signature(fn).parameters)
            assert "tier_table" not in params and "rules_path" not in params

    def test_no_model_call_path_in_validator_surface(self):
        """Validator stays pure/deterministic: same inputs -> same output,
        no sampling slot (determinism posture: verifier judgment is
        sampled; the validator never is)."""
        doc = _verdict_doc([_action("a1", 0.7, ["x"])], 0.7)
        a = ss.validate_verdict_doc(doc, {"x"}, "fail", True)
        b = ss.validate_verdict_doc(doc, {"x"}, "fail", True)
        assert a == b

    def test_settled_interface_unchanged(self, tmp_path):
        """rl.settled()/fold row shape untouched: the validator writes
        through the SAME rl.settle amendment path, no new interfaces."""
        self_test = TestAmendmentPath()
        self_test._seed_refuted(tmp_path)
        _seed_fact(tmp_path, "F204-a")
        ss.apply_trajectory_settlement(
            tmp_path, "task/C-am1",
            _verdict_doc([_action("a1", 0.0, ["F204-a"])], 0.0),
            oracle_verdict="fail", has_reproducible_evidence=False)
        rows = list(rl.settled(tmp_path, kind="task"))
        assert len(rows) == 1
        row = rows[0]
        for key in ("rollout_id", "kind", "anchor", "signals", "settlement",
                    "reward"):
            assert key in row, key
