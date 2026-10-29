# -*- coding: utf-8 -*-
"""tests/test_step_record.py — the step/1 record layer (issue 859, P1).

Every pin asserts observable behavior (the plan's testing strategy — no
mock-shape pins):

  - step/1 schema faces: one accept pin, reject pins per field class
    (missing / blank / wrong type), the discriminability rule (a
    hypothesis with no kill-experiment clause is refused), the
    conclusion-contraction rule (a conclusion referencing none of the
    step's hypotheses is refused), the reusable_when observable-
    condition contract, the confidence and reward{value, source}
    contracts;
  - the three trajectory views (index / segment / tree) over a
    five-step fixture with exactly one confirmed anchor and one
    deviation — including the clause-scoping face ("H2 dies; H1
    survives" kills only H2) and the no-mutation face;
  - the goal-backward planner: the chain derives from the success
    criterion, gap=True only where no known evidence covers the
    checkpoint, and claims open only at the gaps;
  - the dispatch envelope: build_loop_prompt renders a given plan
    block into the prompt and stays byte-identical when the block is
    absent (the default call path must not move).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
for _p in (SCRIPTS, SCRIPTS.parent / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import eval_loop_runner as lr  # noqa: E402
from rlvr import step_record as sr  # noqa: E402

# ------------------------------------------------------------- fixtures

H1 = {"id": "H1", "claim": "the K-array is the standard MD5 constant set",
      "kill_test": "diff the dumped K-array against the reference table"}
H2 = {"id": "H2", "claim": "the round primitive is unmutated",
      "kill_test": "run the known-answer test on the primitive"}
H3 = {"id": "H3", "claim": "the padding order is big-endian counter mode",
      "kill_test": "reorder the assembly until the capture reproduces"}


def _step(**over):
    doc = {
        "task": "recover the licensing key from the tf-snake binary",
        "environment": {"type": "protected-binary", "auth_state": "local"},
        "observation": "the entry stub decrypts a constant table at 0x4010",
        "hypotheses": [dict(H1), dict(H2)],
        "action": "dump the decrypted constant table",
        "result": "the dump shows a 64-word table, first word 0x67452301",
        "conclusion": "The dump matches the reference head, so H1 survives; "
                      "H2 stays open until the known-answer test runs.",
        "confidence": 0.8,
        "reusable_when": ["sample carries an obfuscated constant table"],
        "used_recalled": False,
        "reward": {"value": 0.5, "source": "evidence"},
    }
    doc.update(over)
    return doc


def _trajectory():
    """Five steps, one CONFIRMED anchor (s1), one deviation (s2), the
    rest contraction-quiet. The deviation kills H2 only; H3 is asserted
    afterwards."""
    return [
        _step(  # s0 — preparation, no verdict
            conclusion="Preparation checkpoint declared: H1 and H2 are "
                       "asserted; the kill experiments are staged.",
            action="declare preparation done, start core work"),
        _step(  # s1 — the confirmed anchor
            observation="known-answer run on the primitive head passes",
            action="run the known-answer test on the primitive head",
            conclusion="The known-answer check ran clean, so H1 survives; "
                       "H2 remains open.",
            confidence=0.9),
        _step(  # s2 — the deviation (kills H2 only)
            observation="the round output diverges from every reference",
            action="diff the round output against the reference variants",
            conclusion="H2 is falsified: the primitive diverges from every "
                       "reference; the family head still matches.",
            confidence=0.75),
        _step(  # s3 — refinement asserted, no verdict
            observation="the capture matches a counter-mode assembly",
            hypotheses=[dict(H3)],
            action="try the big-endian counter assembly order",
            conclusion="H3 asserted: the padding order is the next "
                       "discriminating experiment target.",
            confidence=0.6),
        _step(  # s4 — quiet step
            observation="the reordered assembly still misses the tail",
            hypotheses=[dict(H3)],
            action="compare the capture tail against both assembly orders",
            conclusion="H3 assertion recorded; the tail comparison is "
                       "staged for the following step.",
            confidence=0.55),
    ]


# ------------------------------------------------------- schema faces

class TestSchemaFaces:
    def test_accepts_a_valid_step(self):
        assert sr.validate_step(_step())

    def test_validate_returns_the_document_reference(self):
        doc = _step()
        assert sr.validate_step(doc) is doc

    def test_accepts_explicit_schema_field(self):
        assert sr.validate_step(_step(schema="step/1"))

    def test_rejects_a_non_mapping_root(self):
        with pytest.raises(sr.StepRecordError):
            sr.validate_step(["not", "a", "mapping"])

    def test_rejects_a_foreign_schema(self):
        with pytest.raises(sr.StepRecordError, match="schema"):
            sr.validate_step(_step(schema="episode/1"))

    @pytest.mark.parametrize("field", [
        "task", "environment", "observation", "hypotheses", "action",
        "result", "conclusion", "confidence", "reusable_when",
        "used_recalled", "reward"])
    def test_missing_required_field_is_rejected(self, field):
        doc = _step()
        del doc[field]
        with pytest.raises(sr.StepRecordError, match=field):
            sr.validate_step(doc)

    @pytest.mark.parametrize("field", [
        "task", "observation", "action", "result", "conclusion"])
    def test_blank_string_field_is_rejected(self, field):
        with pytest.raises(sr.StepRecordError):
            sr.validate_step(_step(**{field: "   "}))

    @pytest.mark.parametrize("env", [
        "protected-binary", {"auth_state": "local"}, {"type": ""},
        {"type": "   "}])
    def test_environment_must_carry_a_type(self, env):
        with pytest.raises(sr.StepRecordError, match="environment"):
            sr.validate_step(_step(environment=env))

    # -- discriminability ----------------------------------------------

    def test_hypothesis_without_kill_clause_is_rejected(self):
        with pytest.raises(sr.StepRecordError, match="discriminable"):
            sr.validate_step(_step(
                hypotheses=[{"claim": "the packer is UPX"}]))

    def test_plain_string_hypothesis_is_rejected(self):
        with pytest.raises(sr.StepRecordError):
            sr.validate_step(_step(hypotheses=["the packer is UPX"]))

    def test_hypothesis_without_claim_is_rejected(self):
        with pytest.raises(sr.StepRecordError, match="claim"):
            sr.validate_step(_step(
                hypotheses=[{"kill_test": "unpack and compare sections"}]))

    def test_empty_hypotheses_list_is_rejected(self):
        with pytest.raises(sr.StepRecordError, match="hypotheses"):
            sr.validate_step(_step(hypotheses=[]))

    def test_alternative_discriminability_vocabulary_is_accepted(self):
        assert sr.validate_step(_step(
            hypotheses=[{
                "statement": "the packer is UPX",
                "falsifier": "section-histogram diff against UPX signatures",
            }],
            conclusion="The section histogram matches UPX, so the packer "
                       "hypothesis survives."))

    # -- conclusion contraction -----------------------------------------

    def test_conclusion_referencing_no_hypothesis_is_rejected(self):
        with pytest.raises(sr.StepRecordError, match="conclusion"):
            sr.validate_step(_step(
                conclusion="Nothing decided: the dump was taken and the "
                           "loop continues."))

    def test_contraction_by_hypothesis_id_is_accepted(self):
        assert sr.validate_step(_step(
            conclusion="H1 dies: the dumped K-array is not the reference "
                       "set; the search re-enters at the constant layer."))

    def test_contraction_by_claim_terms_is_accepted(self):
        assert sr.validate_step(_step(
            conclusion="The constant array matches the reference set, so "
                       "the first hypothesis survives."))

    # -- confidence ------------------------------------------------------

    @pytest.mark.parametrize("bad", [1.5, -0.1, "0.5", None, True, 2])
    def test_illegal_confidence_is_rejected(self, bad):
        with pytest.raises(sr.StepRecordError, match="confidence"):
            sr.validate_step(_step(confidence=bad))

    @pytest.mark.parametrize("edge", [0, 0.0, 1, 1.0])
    def test_confidence_boundaries_are_accepted(self, edge):
        assert sr.validate_step(_step(confidence=edge))

    # -- reusable_when ---------------------------------------------------

    @pytest.mark.parametrize("bad", [[], [""], ["   "], [42],
                                     "obfuscated constant table"])
    def test_illegal_reusable_when_is_rejected(self, bad):
        with pytest.raises(sr.StepRecordError, match="reusable_when"):
            sr.validate_step(_step(reusable_when=bad))

    # -- used_recalled ---------------------------------------------------

    @pytest.mark.parametrize("bad", ["yes", 0, 1, None])
    def test_non_bool_used_recalled_is_rejected(self, bad):
        with pytest.raises(sr.StepRecordError, match="used_recalled"):
            sr.validate_step(_step(used_recalled=bad))

    @pytest.mark.parametrize("flag", [True, False])
    def test_bool_used_recalled_is_accepted(self, flag):
        assert sr.validate_step(_step(used_recalled=flag))

    # -- reward ----------------------------------------------------------

    @pytest.mark.parametrize("bad", [
        "0.5", {"value": "0.5", "source": "evidence"},
        {"value": 0.5, "source": "pass@k"}, {"value": 0.5},
        {"source": "evidence"}, {"value": True, "source": "evidence"}])
    def test_illegal_reward_is_rejected(self, bad):
        with pytest.raises(sr.StepRecordError):
            sr.validate_step(_step(reward=bad))

    @pytest.mark.parametrize("source", [
        "phi_gain", "evidence", "checkpoint", "cost"])
    def test_every_reward_source_is_accepted(self, source):
        assert sr.validate_step(
            _step(reward={"value": 0.25, "source": source}))


# ------------------------------------------------------------- views

class TestViews:
    def test_index_view_rows(self):
        traj = _trajectory()
        rows = sr.index_view(traj)
        assert [r["i"] for r in rows] == [0, 1, 2, 3, 4]
        assert set(rows[0]) == {"i", "action", "conclusion"}
        assert rows[0]["action"] == traj[0]["action"]
        assert rows[2]["conclusion"] == traj[2]["conclusion"]

    def test_segment_view_runs_anchor_to_deviation(self):
        traj = _trajectory()
        seg = sr.segment_view(traj)
        assert seg["anchor"] == 1
        assert seg["deviation"] == 2
        assert [s["conclusion"] for s in seg["steps"]] == \
            [traj[1]["conclusion"], traj[2]["conclusion"]]

    def test_segment_view_is_open_ended_without_deviation(self):
        traj = _trajectory()
        seg = sr.segment_view(traj[:2])
        assert seg["anchor"] == 1
        assert seg["deviation"] is None
        assert len(seg["steps"]) == 1

    def test_segment_view_is_none_without_a_confirmed_anchor(self):
        assert sr.segment_view(_trajectory()[:1]) is None

    def test_refute_outranks_confirm_in_one_conclusion(self):
        pre = _step(conclusion="H1 survives the known-answer check.")
        mixed = _step(conclusion="H2 dies; H1 survives.")
        seg = sr.segment_view([pre, mixed])
        assert seg["anchor"] == 0
        assert seg["deviation"] == 1

    def test_tree_view_hypothesis_state_chain(self):
        chain = sr.tree_view(_trajectory())
        assert [c["i"] for c in chain] == [0, 1, 2, 3, 4]
        assert chain[0]["alive"] == ["H1", "H2"]
        assert chain[1]["alive"] == ["H1", "H2"]
        assert chain[2]["alive"] == ["H1"]
        assert chain[3]["alive"] == ["H1", "H3"]
        assert chain[4]["alive"] == ["H1", "H3"]

    def test_tree_death_is_clause_scoped(self):
        pre = _step(conclusion="H1 survives the known-answer check.")
        mixed = _step(conclusion="H2 dies; H1 survives.")
        chain = sr.tree_view([pre, mixed])
        assert chain[0]["alive"] == ["H1", "H2"]
        assert chain[1]["alive"] == ["H1"]

    def test_cross_step_explicit_kill_flips_alive_state(self):
        base = _step(
            conclusion="Preparation checkpoint declared: H1 and H2 are "
                       "asserted; the kill experiments are staged.")
        later = _step(
            hypotheses=[dict(H3)],
            conclusion="H1 dies: the reference diff shows the constant "
                       "set diverges; H3 asserted for the composition "
                       "layer.")
        chain = sr.tree_view([base, later])
        assert chain[0]["alive"] == ["H1", "H2"]
        assert chain[1]["alive"] == ["H2", "H3"]

    def test_short_id_kill_does_not_reach_a_longer_id(self):
        h10 = {"id": "H10", "claim": "the export table is a decoy",
               "kill_test": "call every export and compare behavior"}
        s0 = _step(hypotheses=[dict(H1), dict(h10)],
                   conclusion="H1 and H10 are both asserted for the "
                              "constant sweep.")
        s1 = _step(hypotheses=[dict(H1), dict(h10)],
                   conclusion="H10 is falsified: every export behaves "
                              "identically to the entry point.")
        chain = sr.tree_view([s0, s1])
        assert chain[0]["alive"] == ["H1", "H10"]
        assert chain[1]["alive"] == ["H1"]

    def test_segment_view_anchors_at_the_last_confirmation(self):
        traj = _trajectory()
        traj.append(_step(
            hypotheses=[dict(H3)],
            conclusion="H3 survives the tail comparison; the assembly "
                       "order is confirmed."))
        seg = sr.segment_view(traj)
        assert seg["anchor"] == 5
        assert seg["deviation"] is None
        assert len(seg["steps"]) == 1

    def test_empty_trajectory_views_are_well_defined(self):
        assert sr.index_view([]) == []
        assert sr.segment_view([]) is None
        assert sr.tree_view([]) == []

    def test_views_never_mutate_the_trajectory(self):
        traj = _trajectory()
        sr.index_view(traj)
        sr.segment_view(traj)
        sr.tree_view(traj)
        assert traj[1]["hypotheses"][0]["id"] == "H1"
        assert traj[0]["conclusion"].startswith("Preparation")


# ----------------------------------------------------- backward plan

_CRITERION = ("the candidate reproduces the published digest and "
              "passes the static face")
_EVIDENCE = ["reproduction of the published digest recorded in "
             "evidence/digest.json"]


class TestBackwardPlan:
    def test_chain_derives_from_the_criterion(self):
        plan = sr.backward_plan(_CRITERION, [])
        assert [c["id"] for c in plan] == ["ck-1", "ck-2"]
        assert plan[0]["criterion"] == \
            "the candidate reproduces the published digest"
        assert plan[1]["criterion"] == "passes the static face"
        for ck in plan:
            assert {"id", "criterion", "evidence_needed", "gap"} <= set(ck)

    def test_gap_only_where_no_evidence_covers(self):
        plan = sr.backward_plan(_CRITERION, _EVIDENCE)
        assert plan[0]["gap"] is False
        assert plan[1]["gap"] is True

    def test_all_checkpoints_gap_when_no_known_evidence(self):
        plan = sr.backward_plan(_CRITERION, [])
        assert all(c["gap"] is True for c in plan)

    def test_duplicate_clauses_collapse_to_one_checkpoint(self):
        plan = sr.backward_plan("reproduce the digest and reproduce the "
                                "digest", [])
        assert len(plan) == 1

    def test_empty_criterion_is_refused(self):
        with pytest.raises(sr.StepRecordError):
            sr.backward_plan("   ", [])

    def test_claims_open_only_at_gaps(self):
        plan = sr.backward_plan(_CRITERION, _EVIDENCE)
        claims = sr.claim_checkpoints(plan)
        assert [c["id"] for c in claims] == \
            [c["id"] for c in plan if c["gap"]]
        assert all(c["gap"] is True for c in claims)
        assert all(c["gap"] is False
                   for c in plan if c not in claims)


# ------------------------------------------------ dispatch envelope

_TASK = {
    "anchors": {
        "goal_verbatim": "recover the flag from the sample",
        "success_criterion": "the checker verdict is PASS",
        "verification_method": "replay-evidence",
    },
    "workspace_scaffold": {
        "files": ["bins/sample.bin"],
        "candidate_contract": "one source file",
    },
}
_DELIV = "runs/deliverables/candidate.py"
_PLAN_BLOCK = ("GOAL-BACKWARD PLAN (claims open only at gaps):\n"
               "- ck-1 reproduce the published digest [gap]\n"
               "- ck-2 passes the static face [covered]\n"
               "HYPOTHESES: H1 the packer is UPX (kill: section diff)")


class TestDispatchEnvelope:
    def test_default_call_path_is_unchanged(self):
        base = lr.build_loop_prompt(Path("."), _TASK, _DELIV)
        assert "GOAL-BACKWARD PLAN" not in base
        assert lr.build_loop_prompt(
            Path("."), _TASK, _DELIV, plan_block=None) == base

    def test_plan_block_is_rendered_when_given(self):
        prompt = lr.build_loop_prompt(
            Path("."), _TASK, _DELIV, plan_block=_PLAN_BLOCK)
        assert _PLAN_BLOCK in prompt
        # extras ride as first-class sections before the anchors
        assert prompt.index(_PLAN_BLOCK) < prompt.index("GOAL (verbatim)")

    def test_plan_block_rides_with_the_existing_blocks(self):
        prompt = lr.build_loop_prompt(
            Path("."), _TASK, _DELIV, probe_block="SELF CHECK: probe",
            plan_block=_PLAN_BLOCK)
        assert _PLAN_BLOCK in prompt
        assert "SELF CHECK: probe" in prompt
