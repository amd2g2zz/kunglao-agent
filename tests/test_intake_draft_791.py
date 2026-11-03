# -*- coding: utf-8 -*-
"""tests/test_intake_draft_791.py — #791 §3 bounded-intelligent intake draft.

The draft is the intake dialogue's durable face: deliverables / acceptance /
not_done / diff_vs_verbatim + primary_questions (FIRST-CLASS output,
addendum 1) are drafted from the verbatim task, shown to the user, and
CONFIRMED before declared_ts is stamped. The intelligence lives in the
drafting; the authority stays with the user; #412's structural-facts
constitution is NOT reopened (no analysis at init; the confirm wall is
mechanical).

Enforcement semantics (addendum 1 decision): the goal-operationalization
scaffold ships UNSTAMPED (declared_ts: "") — the existing declared_ts gate
(convergence INVALID face) is what makes the confirm dialogue
un-skippable; the confirm face is the only stamping path.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import intake_draft  # noqa: E402
import goal_operationalization as goal_op  # noqa: E402


def _ws(tmp_path, task_spec=None, goal_op=True) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "runs").mkdir()
    if task_spec is not None:
        (ws / "task_spec.yaml").write_text(
            yaml.safe_dump(task_spec, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
    if goal_op:
        (ws / "goal-operationalization.yaml").write_text(yaml.safe_dump({
            "schema": "goal-operationalization/1",
            "draft": True,
            "goal_verbatim": "recover the login signature",
            "deliverables": [], "acceptance": [], "not_done": [],
            "constraint_witness": {"schema": "constraint-witness/1",
                                   "witnesses": {}},
            "diff_vs_verbatim": "",
            "generalization": "required",
            "declared_ts": "",
        }, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return ws


_ANSWERS = {
    "confirmed": True,
    "classification_confirmed": True,
    "primary_questions": [
        {"id": "q1", "need": "which parameter carries the signature"},
        {"id": "q2", "need": "what mutates the signature"},
    ],
    "deliverables": ["the recovered signing function, replayable"],
    "acceptance": ["replay produces the captured signature"],
    "not_done": ["a hardcoded captured signature does NOT count"],
    "diff_vs_verbatim": ["scope narrowed to the login request only"],
    "probe_cases": ["fresh-input: sign a never-captured login payload"],
    "constraint_witness": {
        "schema": "constraint-witness/1",
        "witnesses": {
            "a hardcoded captured signature does NOT count": {
                "none": "the counterexample is witnessed at delivery replay",
            },
        },
    },
}


# ---------- 1. scaffold ----------

class TestScaffold:
    def test_scaffold_written_unconfirmed(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "web", "project_type": "web"})
        path = intake_draft.scaffold(ws)
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert doc["schema"] == intake_draft.SCHEMA
        assert doc["confirmed"] is False
        assert doc["declared_ts"] == ""
        assert doc["classification"]["lane"] == "web"
        assert doc["classification"]["prescan_probes"] == []
        assert doc["classification"]["difficulty_factor_set"] == "web"

    def test_scaffold_idempotent_never_clobbers(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "web"})
        first = intake_draft.scaffold(ws)
        before = first.read_text(encoding="utf-8")
        assert intake_draft.scaffold(ws) == first
        assert first.read_text(encoding="utf-8") == before

    def test_classification_echoes_binary_consequence(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "malware", "project_type": "android"})
        doc = yaml.safe_load(intake_draft.scaffold(ws).read_text(
            encoding="utf-8"))
        assert doc["classification"]["prescan_probes"] == ["apkid", "die"]
        assert doc["classification"]["difficulty_factor_set"] == "binary"
        assert "device_root" in doc["classification"]["capabilities"]


# ---------- 2. confirm: the wall ----------

class TestConfirm:
    def test_confirm_stamps_declared_ts_and_fills_goal_op(
            self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "web"})
        intake_draft.scaffold(ws)
        report = intake_draft.confirm(ws, dict(_ANSWERS))
        assert report["draft"] is not None
        draft = yaml.safe_load(
            (ws / "runs" / "intake-draft.yaml").read_text(encoding="utf-8"))
        assert draft["confirmed"] is True
        assert draft["declared_ts"], "confirm stamps declared_ts"
        goal = goal_op.load(ws / "goal-operationalization.yaml")
        assert goal["declared_ts"] == draft["declared_ts"]
        assert goal["deliverables"] == _ANSWERS["deliverables"]
        assert goal["diff_vs_verbatim"] == _ANSWERS["diff_vs_verbatim"]
        assert goal_op.validate(goal)["errors"] == []

    def test_confirm_merges_primary_questions_first_class(
            self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "web"})
        intake_draft.scaffold(ws)
        intake_draft.confirm(ws, dict(_ANSWERS))
        spec = yaml.safe_load((ws / "task_spec.yaml").read_text(
            encoding="utf-8"))
        assert [q["id"] for q in spec["primary_questions"]] == ["q1", "q2"]

    def test_unconfirmed_flag_refused(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "web"})
        intake_draft.scaffold(ws)
        answers = dict(_ANSWERS, confirmed=False)
        with pytest.raises(intake_draft.IntakeDraftError):
            intake_draft.confirm(ws, answers)

    def test_classification_unconfirmed_refused(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "web"})
        intake_draft.scaffold(ws)
        answers = dict(_ANSWERS, classification_confirmed=False)
        with pytest.raises(intake_draft.IntakeDraftError):
            intake_draft.confirm(ws, answers)

    def test_empty_primary_questions_refused(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "web"})
        intake_draft.scaffold(ws)
        answers = dict(_ANSWERS, primary_questions=[])
        with pytest.raises(intake_draft.IntakeDraftError):
            intake_draft.confirm(ws, answers)

    def test_malformed_primary_questions_refused(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "web"})
        intake_draft.scaffold(ws)
        answers = dict(_ANSWERS, primary_questions=[{"nope": 1}, {"nope2": 2}])
        with pytest.raises(intake_draft.IntakeDraftError):
            intake_draft.confirm(ws, answers)

    def test_rubber_stamp_diff_refused_at_confirm(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "web"})
        intake_draft.scaffold(ws)
        answers = dict(_ANSWERS, diff_vs_verbatim=["identical to the "
                                                   "verbatim task"])
        with pytest.raises(intake_draft.IntakeDraftError):
            intake_draft.confirm(ws, answers)

    def test_empty_not_done_refused(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "web"})
        intake_draft.scaffold(ws)
        answers = dict(_ANSWERS, not_done=[])
        with pytest.raises(intake_draft.IntakeDraftError):
            intake_draft.confirm(ws, answers)

    def test_double_confirm_refused(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "web"})
        intake_draft.scaffold(ws)
        intake_draft.confirm(ws, dict(_ANSWERS))
        with pytest.raises(intake_draft.IntakeDraftError):
            intake_draft.confirm(ws, dict(_ANSWERS))

    def test_stamped_goal_op_never_touched(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "web"})
        intake_draft.scaffold(ws)
        goal_path = ws / "goal-operationalization.yaml"
        goal = goal_op.load(goal_path)
        goal["deliverables"] = ["already audited"]
        goal["declared_ts"] = "2026-10-01T00:00:00Z"
        goal["first_dispatch_ts"] = "2026-10-02T00:00:00Z"
        goal["constitution"] = {"generalization": goal["generalization"]}
        goal_path.write_text(yaml.safe_dump(goal), encoding="utf-8")
        before = goal_path.read_text(encoding="utf-8")
        report = intake_draft.confirm(ws, dict(_ANSWERS))
        assert goal_path.read_text(encoding="utf-8") == before
        assert report["goal_op"] is None


# ---------- 3. R2/R5 pins stay green ----------

class TestR2R5Pins:
    def test_post_stamp_edit_still_refused(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "web"})
        intake_draft.scaffold(ws)
        intake_draft.confirm(ws, dict(_ANSWERS))
        goal_path = ws / "goal-operationalization.yaml"
        goal = goal_op.load(goal_path)
        goal["first_dispatch_ts"] = "2026-10-02T00:00:00Z"
        goal["constitution"] = {
            "generalization": goal["generalization"],
            "deliverables": goal["deliverables"],
            "acceptance": goal["acceptance"],
            "not_done": goal["not_done"],
            "diff_vs_verbatim": goal["diff_vs_verbatim"],
            "probe_cases": goal.get("probe_cases") or [],
            "constraint_witness": {},
        }
        # R5: dropping a declared not_done entry post-dispatch is refused
        goal["not_done"] = []
        assert any("not_done" in e
                   for e in goal_op.validate(goal)["errors"])

    def test_validate_still_rejects_unstamped(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "web"})
        intake_draft.scaffold(ws)
        goal = goal_op.load(ws / "goal-operationalization.yaml")
        errors = goal_op.validate(goal)["errors"]
        assert any("declared_ts" in e for e in errors), (
            "an unstamped translation is not a record (R4) — the scaffold "
            "must stay INVALID until the draft is confirmed")
