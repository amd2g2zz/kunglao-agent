#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb2_matrix_runner_pins_818.py — #818 climb segment 2F.

Behavior pins on REAL fixtures for the #578/#694 five-arm matrix registry
faces the climb had not measured. Pin discipline: expectations derive from
the fixture each test wrote — no repo-state literalization.

Faces (scripts/eval_matrix_runner.py):
  the declarative arm registry (structural arm/sampling/unit validation,
  same-cost contract, store modes), the cartesian run planner with the
  B2 multi-sample expansion and arm/unit filters, the pure launch shape
  (store dirs, child env stripping, child argv, warm-source fault
  prediction), store materialization (cold/warm, per-run/per-arm), and
  the progress faces.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_matrix_runner as emr  # noqa: E402


def _arm(aid: str, face: str = "cc-default", store: str = "none",
         **extra) -> dict:
    arm = {"id": aid, "runner_face": face, "store": store}
    arm.update(extra)
    return arm


def _doc(arms: list[dict], units: list | None = None,
         budget: dict | None = None, warm: dict | None = None) -> dict:
    return {
        "schema": "ws5-five-arms/1",
        "arms": arms,
        "units": units if units is not None
        else [{"id": "u1", "tier": "release"}],
        "budget": budget if budget is not None else {"budget_usd": 2.0},
        "warm_up": warm or {},
    }


def _write_cfg(tmp_path: Path, doc: dict) -> Path:
    p = tmp_path / "matrix.yaml"
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return p


BASE_ARM = _arm("a-cc")


# ------------------------------------------------- 1. arm registry law

class TestArmValidation:
    def test_minimal_cc_arm_is_legal(self, tmp_path) -> None:
        cfg = _write_cfg(tmp_path, _doc([BASE_ARM]))
        assert emr.load_config(cfg)["arms"][0]["id"] == "a-cc"

    def test_arm_faults_name_the_face(self, tmp_path) -> None:
        faults = [
            _arm(""),                                     # missing id
            {"id": "x", "runner_face": "psychic",
             "store": "none"},                            # unknown face
            _arm("x", face="cc-default", store="warm"),   # cc reads store
            _arm("x", face="loop", store="none"),         # loop needs store
            _arm("x", face="loop", store="none",
                 env={"A": 1}),                           # env not str->str
            _arm("x", face="loop", store="warm",
                 sampling={"mode": "multi-sample", "samples": 2,
                           "budget_each": 1.0}),          # loop + sampling
            "not-a-mapping",
        ]
        for bad in faults:
            with pytest.raises(emr.ConfigError):
                emr._validate_arm(0, bad)

    def test_loop_arm_with_store_is_legal(self) -> None:
        aid, face = emr._validate_arm(
            0, _arm("a-loop", face="loop", store="cold"))
        assert (aid, face) == ("a-loop", "loop")

    def test_sampling_protocol_law(self, tmp_path) -> None:
        with pytest.raises(emr.ConfigError, match="mode"):
            emr._validate_sampling(0, _arm("x", sampling={"mode": "psy",
                                                          "samples": 2,
                                                          "budget_each": 1}))
        with pytest.raises(emr.ConfigError, match="samples"):
            emr._validate_sampling(0, _arm(
                "x", sampling={"mode": "multi-sample", "samples": 1,
                               "budget_each": 1}))
        with pytest.raises(emr.ConfigError, match="budget_each"):
            emr._validate_sampling(0, _arm(
                "x", sampling={"mode": "multi-sample", "samples": 2,
                               "budget_each": 0}))
        ok = emr._validate_sampling(
            0, _arm("x", sampling={"mode": "multi-sample", "samples": 2,
                                   "budget_each": 1.0}))
        assert ok == {"mode": "multi-sample", "samples": 2,
                      "budget_each": 1.0}
        assert emr._validate_sampling(0, _arm("x")) == {}

    def test_same_cost_contract(self, tmp_path) -> None:
        discounted = _doc([
            BASE_ARM,
            _arm("a-b2", sampling={"mode": "multi-sample", "samples": 4,
                                   "budget_each": 0.25}),
        ], budget={"budget_usd": 2.0})
        with pytest.raises(emr.ConfigError, match="same-cost"):
            emr.load_config(_write_cfg(tmp_path, discounted))
        # exact spend passes
        even = _doc([
            BASE_ARM,
            _arm("a-b2", sampling={"mode": "multi-sample", "samples": 4,
                                   "budget_each": 0.5}),
        ], budget={"budget_usd": 2.0})
        assert emr.load_config(_write_cfg(tmp_path, even)) is not None

    def test_registry_level_faults(self, tmp_path) -> None:
        with pytest.raises(emr.ConfigError, match="not found"):
            emr.load_config(tmp_path / "ghost.yaml")
        bad_schema = _write_cfg(tmp_path, _doc([BASE_ARM]))
        doc = yaml.safe_load(bad_schema.read_text("utf-8"))
        doc["schema"] = "wrong/9"
        bad_schema.write_text(yaml.safe_dump(doc), encoding="utf-8")
        with pytest.raises(emr.ConfigError, match="schema"):
            emr.load_config(bad_schema)
        dup = _write_cfg(tmp_path, _doc([BASE_ARM, _arm("a-cc")]))
        with pytest.raises(emr.ConfigError, match="duplicate arm"):
            emr.load_config(dup)
        dup_unit = _write_cfg(tmp_path, _doc([BASE_ARM],
                                             units=[{"id": "u1", "tier": "release"}, {"id": "u1", "tier": "release"}]))
        with pytest.raises(emr.ConfigError, match="duplicate unit"):
            emr.load_config(dup_unit)
        empty_arms = _write_cfg(tmp_path, _doc([]))
        with pytest.raises(emr.ConfigError, match="non-empty"):
            emr.load_config(empty_arms)
        bad_unit = _write_cfg(tmp_path, _doc(
            [BASE_ARM], units=[{"id": "u2", "corpus": "moon",
                                "tier": "release"}]))
        with pytest.raises(emr.ConfigError, match="corpus"):
            emr.load_config(bad_unit)
        bad_mode = _doc([BASE_ARM], warm={"store_mode": "moon"})
        with pytest.raises(emr.ConfigError, match="store_mode"):
            emr.load_config(_write_cfg(tmp_path, bad_mode))

    def test_store_mode_and_unit_normalization(self, tmp_path) -> None:
        doc = _doc([BASE_ARM], units=[{"id": "u1", "tier": "release"},
                                      "u2"])
        assert emr.config_store_mode(doc) == "per-run"
        warm_doc = _doc([BASE_ARM], warm={"store_mode": "per-arm"})
        assert emr.config_store_mode(warm_doc) == "per-arm"
        units = emr.config_units(doc)
        assert units[0] == {"id": "u1", "corpus": "repo",
                            "tier": "release"}
        assert units[1] == {"id": "u2", "corpus": "repo",
                            "tier": "release"}


# ------------------------------------------------- 2. run planning

class TestPlanRuns:
    def _loaded_doc(self, tmp_path: Path, doc: dict) -> dict:
        return emr.load_config(_write_cfg(tmp_path, doc))

    def test_cartesian_order_and_expansion(self, tmp_path) -> None:
        doc = self._loaded_doc(tmp_path, _doc(
            [_arm("a1"), _arm("a2", sampling={
                "mode": "multi-sample", "samples": 3,
                "budget_each": 2.0 / 3})],
            units=[{"id": "u1", "tier": "release"}, {"id": "u2", "tier": "release"}],
            budget={"budget_usd": 2.0}))
        plans = emr.plan_runs(doc, Path("/tmp/out"),
                              arms_filter=None, units_filter=None)
        # cc arm: 1 plan per unit; sampling arm: 3 sample dirs per unit
        assert len(plans) == 2 + 2 * 3
        expanded = [p for p in plans if p.arm_id == "a2"]
        assert [p.sample_index for p in expanded[:3]] == [0, 1, 2]
        assert expanded[0].run_dir.name == "s0"
        assert all(p.budget_each == pytest.approx(2.0 / 3)
                   for p in expanded)
        single = [p for p in plans if p.arm_id == "a1"]
        assert single[0].run_dir.name == "u1"  # no s0 nesting

    def test_filters_name_known_ids_only(self, tmp_path) -> None:
        doc = self._loaded_doc(tmp_path, _doc(
            [_arm("a1"), _arm("a2")], units=[{"id": "u1", "tier": "release"}, {"id": "u2", "tier": "release"}]))
        plans = emr.plan_runs(doc, Path("/tmp/out"),
                              arms_filter=["a2"], units_filter=["u2"])
        assert len(plans) == 1
        assert (plans[0].arm_id, plans[0].unit) == ("a2", "u2")
        with pytest.raises(emr.ConfigError, match="unknown arm"):
            emr.plan_runs(doc, Path("/tmp/out"), arms_filter=["ghost"],
                          units_filter=None)
        with pytest.raises(emr.ConfigError, match="unknown unit"):
            emr.plan_runs(doc, Path("/tmp/out"), arms_filter=None,
                          units_filter=["ghost"])


# ------------------------------------------------- 3. launch shape

class TestLaunchShape:
    def _plan(self, **kw) -> emr.RunPlan:
        base = dict(arm_id="a1", runner_face="cc-default", unit="u1",
                    tier="release", corpus="repo",
                    run_dir=Path("/tmp/out/a1/u1"), store_kind="none",
                    env_extra=(("KUNGLAO_FLAG", "1"),))
        base.update(kw)
        return emr.RunPlan(**base)

    def test_store_dir_scopes(self) -> None:
        assert emr.store_dir_of(self._plan()).name == "store"
        per_arm = self._plan(store_kind="warm", store_mode="per-arm")
        assert emr.store_dir_of(per_arm) == per_arm.run_dir.parent / "store"

    def test_child_env_strips_ablations_and_sets_store(self) -> None:
        plan = self._plan(store_kind="warm")
        env = emr.child_env(plan, {"KUNGLAO_RECALL": "off",
                                   "KEEP": "yes"})
        assert "KUNGLAO_RECALL" not in env
        assert env["KEEP"] == "yes"
        assert env[emr.STORE_ENV] == str(emr.store_dir_of(plan))
        bare = emr.child_env(self._plan(), {})
        assert emr.STORE_ENV not in bare
        # the arm's declared env wins last
        flagged = emr.child_env(self._plan(), {})
        assert flagged["KUNGLAO_FLAG"] == "1"

    def test_child_env_operator_corpus_requires_root(self) -> None:
        plan = self._plan(corpus="operator")
        with pytest.raises(emr.ConfigError, match="no .*root"):
            emr.child_env(plan, {})
        env = emr.child_env(plan, {}, operator_root="/data/eval")
        assert env[emr.EVAL_ROOT_ENV] == "/data/eval"

    def test_child_argv_shape_and_warm_context_law(self) -> None:
        argv = emr.child_argv(self._plan(), budget_usd=2.0,
                              wall_cap_s=600)
        joined = " ".join(argv)
        assert "--tier release" in joined and "--tasks u1" in joined
        assert "--arm cc-default" in joined
        assert "--budget-usd 2.0" in joined and "--wall-cap-s 600" in joined
        warm = self._plan(runner_face="cc-warm-context")
        with pytest.raises(emr.ConfigError, match="warm-context-from"):
            emr.child_argv(warm, budget_usd=1.0, wall_cap_s=60)
        argv = emr.child_argv(warm, budget_usd=1.0, wall_cap_s=60,
                              warm_context_from=Path("/tmp/ws"))
        assert "--warm-context-from /tmp/ws" in " ".join(argv)
        with_session = emr.child_argv(self._plan(), budget_usd=1.0,
                                      wall_cap_s=60,
                                      session_cmd="tmux new",
                                      plugin_dir=Path("/tmp/plug"))
        assert "--session-cmd tmux new" in " ".join(with_session)
        assert "--plugin-dir /tmp/plug" in " ".join(with_session)

    def test_warm_source_fault_prediction(self, tmp_path) -> None:
        warm = self._plan(store_kind="warm")
        assert emr.warm_source_fault(self._plan(), None) is None
        assert "no warm_up.store_source" in emr.warm_source_fault(
            warm, None)
        empty = tmp_path / "empty-store"
        empty.mkdir()
        assert "posterior-store.jsonl" in emr.warm_source_fault(warm, empty)
        (empty / emr.STORE_FILE).write_text("", encoding="utf-8")
        assert emr.warm_source_fault(warm, empty) is None

    def test_materialize_cold_and_warm(self, tmp_path) -> None:
        import shutil
        cold = self._plan(run_dir=tmp_path / "cell-cold")
        out = emr.materialize_store(cold, None)
        assert out.is_dir() and list(out.iterdir()) == []
        src = tmp_path / "warm-src"
        src.mkdir()
        (src / emr.STORE_FILE).write_text('{"row": 1}\n', encoding="utf-8")
        warm = self._plan(run_dir=tmp_path / "cell-warm", store_kind="warm")
        out = emr.materialize_store(warm, src)
        assert (out / emr.STORE_FILE).read_text("utf-8") == '{"row": 1}\n'
        # a warm arm with a bad source refuses and cleans up
        broken = self._plan(run_dir=tmp_path / "cell-broken",
                            store_kind="warm")
        with pytest.raises(emr.ConfigError):
            emr.materialize_store(broken, None)
        assert not broken.run_dir.exists() or \
            not (emr.store_dir_of(broken) / emr.STORE_FILE).exists()
        shutil.rmtree(tmp_path / "cell-warm", ignore_errors=True)

    def test_per_arm_materializes_once(self, tmp_path) -> None:
        src = tmp_path / "warm-src"
        src.mkdir()
        (src / emr.STORE_FILE).write_text("v1\n", encoding="utf-8")
        plan = self._plan(run_dir=tmp_path / "arm/u1", store_kind="warm",
                          store_mode="per-arm")
        first = emr.materialize_store(plan, src)
        (src / emr.STORE_FILE).write_text("v2\n", encoding="utf-8")
        second = emr.materialize_store(plan, src)
        assert first == second
        # the within-sequence copy is NOT re-landed: accumulated state stays
        assert (second / emr.STORE_FILE).read_text("utf-8") == "v1\n"

    def test_run_row_and_progress_faces(self, tmp_path) -> None:
        plan = self._plan()
        row = emr._run_row(plan, "planned", note="x")
        assert row["arm"] == "a1" and row["status"] == "planned"
        assert "store_mode" not in row  # per-run is the silent default
        sampled = self._plan(sample_index=2, sample_count=3,
                             budget_each=0.5)
        srow = emr._run_row(sampled, "planned")
        assert srow["sample"] == 2 and srow["sample_count"] == 3
        p = emr.write_progress(tmp_path, {"cells": 1})
        assert json.loads(p.read_text("utf-8")) == {"cells": 1}
        assert emr.read_progress(tmp_path)["cells"] == 1
        assert emr.read_progress(tmp_path / "nope") is None

    def test_launch_groups_isolate_accumulating_arms(self) -> None:
        # per-arm store scope is what binds the sequence: same-arm cells
        # gather into ONE group (never concurrent over a live store)
        cold_arm = self._plan(arm_id="loop-a", runner_face="loop",
                              store_kind="cold", store_mode="per-arm")
        cold_arm2 = self._plan(arm_id="loop-a", runner_face="loop",
                               store_kind="cold", store_mode="per-arm",
                               run_dir=Path("/tmp/out/loop-a/u2"))
        cc = self._plan(arm_id="cc", run_dir=Path("/tmp/out/cc/u1"))
        groups = emr.launch_groups([cold_arm, cc, cold_arm2])
        loop_cells = [g for g in groups
                      if g and g[0].arm_id == "loop-a"]
        assert len(loop_cells) == 1 and len(loop_cells[0]) == 2
        assert [g[0].arm_id for g in groups if g[0].arm_id == "cc"] == ["cc"]
