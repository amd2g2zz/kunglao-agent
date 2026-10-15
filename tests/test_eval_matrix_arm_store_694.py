# -*- coding: utf-8 -*-
"""tests/test_eval_matrix_arm_store_694.py — per-arm accumulating store mode.

Within-sequence learning needs ONE store per arm across its unit
sequence (rows written by an earlier unit stay visible to later units),
while arms stay mutually isolated. The default keeps the per-run
isolated copy; a registry declaration `warm_up.store_mode: per-arm`
switches the store's location and materialization cadence only — no
other face moves. Faces pinned here:

  (a) REGISTRY — warm_up.store_mode validates (per-run default, per-arm
      accepted, anything else refuses the whole matrix);
  (b) STORE LOCATION — child_env points the store env at the cell's own
      <run>/store under per-run and at the shared <arm>/store under
      per-arm: two units of one arm share one path, two arms never do;
  (c) MATERIALIZATION — the first unit of an arm materializes (cold:
      empty dir; warm: one isolated copy of the source); later units
      reuse the dir with accumulated rows intact; a torn warm dir
      (store file missing) is repaired by the copy; the per-run cadence
      and the warm-source refusal are unchanged;
  (d) LAUNCH GROUPS — an accumulating arm's cells ride ONE sequential
      group in declared order (concurrent same-arm cells would race
      the shared live store); every other cell keeps its own group;
      the launcher dispatches groups, and the progress spine records
      the declared scope.

Pure Python + tmp_path fixtures — no sessions, no corpus, no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (SCRIPTS,):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import eval_matrix_runner as mx  # noqa: E402


# ---- helpers --------------------------------------------------------------

def _write_config(tmp_path: Path, doc: dict) -> Path:
    p = tmp_path / "arms.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return p


def _config(store_mode: str | None, *, units: list | None = None) -> dict:
    warm_up = {"store_source": None, "warm_context_source": None}
    if store_mode is not None:
        warm_up["store_mode"] = store_mode
    return {
        "schema": "ws5-five-arms/1",
        "budget": {"budget_usd": 1.0, "wall_cap_s": 60},
        "arms": [
            {"id": "a-cold", "runner_face": "loop", "store": "cold",
             "env": {}},
        ],
        "units": units or [
            {"id": "py-derive-v1", "corpus": "repo", "tier": "smoke"},
        ],
        "warm_up": warm_up,
    }


def _plan(tmp_path: Path, *, arm: str = "a-cold", unit: str = "u-1",
          store_mode: str = "per-run",
          store_kind: str = "cold") -> mx.RunPlan:
    return mx.RunPlan(
        arm_id=arm, runner_face="loop", unit=unit, tier="release",
        corpus="repo", run_dir=tmp_path / arm / unit,
        store_kind=store_kind, env_extra=(), store_mode=store_mode)


# ---- (a) registry ----------------------------------------------------------

def test_registry_default_is_per_run(tmp_path):
    doc = mx.load_config(_write_config(tmp_path, _config(None)))
    assert mx.config_store_mode(doc) == "per-run"


def test_registry_accepts_per_arm_and_refuses_anything_else(tmp_path):
    doc = mx.load_config(_write_config(tmp_path, _config("per-arm")))
    assert mx.config_store_mode(doc) == "per-arm"
    with pytest.raises(mx.ConfigError, match="store_mode"):
        mx.load_config(_write_config(tmp_path, _config("per-wobble")))


# ---- (b) store location ----------------------------------------------------

def test_store_dir_per_run_is_isolated_per_arm_is_shared(tmp_path):
    run_a1 = mx.store_dir_of(_plan(tmp_path, unit="u-1"))
    run_a2 = mx.store_dir_of(_plan(tmp_path, unit="u-2"))
    arm_a1 = mx.store_dir_of(_plan(tmp_path, unit="u-1",
                                   store_mode="per-arm"))
    arm_a2 = mx.store_dir_of(_plan(tmp_path, unit="u-2",
                                   store_mode="per-arm"))
    arm_b1 = mx.store_dir_of(_plan(tmp_path, arm="a-other", unit="u-1",
                                   store_mode="per-arm"))
    assert run_a1 != run_a2  # per-run: every cell its own store
    assert arm_a1 == arm_a2  # per-arm: one store across the sequence
    assert arm_a1 != arm_b1  # arms never share
    assert arm_a1 == tmp_path / "a-cold" / "store"


def test_child_env_store_face_follows_store_mode(tmp_path):
    per_run = mx.child_env(_plan(tmp_path, unit="u-1"))
    per_arm_1 = mx.child_env(_plan(tmp_path, unit="u-1",
                                   store_mode="per-arm"))
    per_arm_2 = mx.child_env(_plan(tmp_path, unit="u-2",
                                   store_mode="per-arm"))
    assert per_run[mx.STORE_ENV] == str(tmp_path / "a-cold" / "u-1"
                                        / "store")
    assert per_arm_1[mx.STORE_ENV] == str(tmp_path / "a-cold" / "store")
    assert per_arm_2[mx.STORE_ENV] == per_arm_1[mx.STORE_ENV]


# ---- (c) materialization ---------------------------------------------------

def test_per_arm_cold_materializes_once_and_accumulates(tmp_path):
    first = _plan(tmp_path, unit="u-1", store_mode="per-arm")
    second = _plan(tmp_path, unit="u-2", store_mode="per-arm")
    d1 = mx.materialize_store(first, None)
    assert d1.is_dir() and list(d1.iterdir()) == []
    (d1 / mx.STORE_FILE).write_text("accumulated\n", encoding="utf-8")
    d2 = mx.materialize_store(second, None)
    assert d2 == d1
    assert (d2 / mx.STORE_FILE).read_text("utf-8") == "accumulated\n"


def test_per_arm_warm_copies_once_then_reuses(tmp_path):
    src = tmp_path / "warm-src"
    src.mkdir()
    (src / mx.STORE_FILE).write_text("seed\n", encoding="utf-8")
    first = _plan(tmp_path, unit="u-1", store_mode="per-arm",
                  store_kind="warm")
    second = _plan(tmp_path, unit="u-2", store_mode="per-arm",
                   store_kind="warm")
    d1 = mx.materialize_store(first, src)
    assert (d1 / mx.STORE_FILE).read_text("utf-8") == "seed\n"
    (d1 / mx.STORE_FILE).write_text("seed\nrow-2\n", encoding="utf-8")
    d2 = mx.materialize_store(second, src)
    assert d2 == d1
    # no per-unit re-copy: a re-copy would wipe the accumulated row
    assert (d2 / mx.STORE_FILE).read_text("utf-8") == "seed\nrow-2\n"


def test_per_arm_warm_torn_dir_is_repaired_by_the_copy(tmp_path):
    src = tmp_path / "warm-src"
    src.mkdir()
    (src / mx.STORE_FILE).write_text("seed\n", encoding="utf-8")
    torn = tmp_path / "a-cold" / "store"
    torn.mkdir(parents=True)  # dir exists, store file missing
    plan = _plan(tmp_path, unit="u-1", store_mode="per-arm",
                 store_kind="warm")
    d = mx.materialize_store(plan, src)
    assert (d / mx.STORE_FILE).read_text("utf-8") == "seed\n"


def test_per_run_materialization_is_unchanged(tmp_path):
    src = tmp_path / "warm-src"
    src.mkdir()
    (src / mx.STORE_FILE).write_text("seed\n", encoding="utf-8")
    warm_1 = _plan(tmp_path, unit="u-1", store_kind="warm")
    warm_2 = _plan(tmp_path, unit="u-2", store_kind="warm")
    d1 = mx.materialize_store(warm_1, src)
    (d1 / mx.STORE_FILE).write_text("mutated\n", encoding="utf-8")
    d2 = mx.materialize_store(warm_2, src)
    assert d1 != d2
    assert (d2 / mx.STORE_FILE).read_text("utf-8") == "seed\n"
    cold = _plan(tmp_path, unit="u-3")
    d3 = mx.materialize_store(cold, None)
    assert d3.is_dir() and list(d3.iterdir()) == []


def test_per_arm_warm_without_source_still_refuses(tmp_path):
    with pytest.raises(mx.ConfigError, match="warm claim would be false"):
        mx.materialize_store(
            _plan(tmp_path, unit="u-1", store_mode="per-arm",
                  store_kind="warm"), None)


# ---- (d) launch groups -----------------------------------------------------

def test_launch_groups_serialize_an_accumulating_arm_only(tmp_path):
    plans = [
        _plan(tmp_path, unit="u-1", store_mode="per-arm"),
        _plan(tmp_path, unit="u-2", store_mode="per-arm"),
        _plan(tmp_path, arm="a-other", unit="u-1"),
        _plan(tmp_path, arm="a-other", unit="u-2"),
    ]
    groups = mx.launch_groups(plans)
    assert [[p.unit for p in g] for g in groups] == [
        ["u-1", "u-2"], ["u-1"], ["u-2"]]


def test_launch_groups_gather_an_arm_even_when_interleaved(tmp_path):
    """The one-group-per-arm guarantee is ENFORCED for any plan order,
    not maintained by arm-major caller discipline: an interleaved list
    must still yield exactly one group per accumulating arm."""
    plans = [
        _plan(tmp_path, arm="a-cold", unit="u-1", store_mode="per-arm"),
        _plan(tmp_path, arm="a-other", unit="u-1", store_mode="per-arm"),
        _plan(tmp_path, arm="a-cold", unit="u-2", store_mode="per-arm"),
        _plan(tmp_path, arm="a-other", unit="u-2", store_mode="per-arm"),
    ]
    groups = mx.launch_groups(plans)
    assert len(groups) == 2
    by_arm = {g[0].arm_id: [p.unit for p in g] for g in groups}
    assert by_arm == {"a-cold": ["u-1", "u-2"],
                      "a-other": ["u-1", "u-2"]}


def test_launch_groups_never_split_an_arm_around_a_per_run_cell(tmp_path):
    plans = [
        _plan(tmp_path, arm="a-cold", unit="u-1", store_mode="per-arm"),
        _plan(tmp_path, arm="a-other", unit="u-1"),  # per-run singleton
        _plan(tmp_path, arm="a-cold", unit="u-2", store_mode="per-arm"),
    ]
    groups = mx.launch_groups(plans)
    cold = [g for g in groups if g[0].arm_id == "a-cold"]
    assert len(cold) == 1
    assert [p.unit for p in cold[0]] == ["u-1", "u-2"]


def test_plan_runs_carries_the_declared_store_mode(tmp_path):
    doc = _config("per-arm", units=[
        {"id": "py-derive-v1", "corpus": "repo", "tier": "smoke"},
        {"id": "py-derive-v2", "corpus": "repo", "tier": "smoke"},
    ])
    loaded = mx.load_config(_write_config(tmp_path, doc))
    plans = mx.plan_runs(loaded, tmp_path / "out", arms_filter=None,
                         units_filter=None)
    assert [p.store_mode for p in plans] == ["per-arm", "per-arm"]


def test_plan_runs_keeps_a_storeless_arm_on_per_run(tmp_path):
    """The scope only binds store-bearing arms: a cc face never reads
    the store, so its cells stay independent per-run plans."""
    doc = _config("per-arm")
    doc["arms"].append({"id": "cc-bare", "runner_face": "cc-default",
                        "store": "none", "env": {}})
    loaded = mx.load_config(_write_config(tmp_path, doc))
    plans = mx.plan_runs(loaded, tmp_path / "out", arms_filter=None,
                         units_filter=None)
    assert {p.arm_id: p.store_mode for p in plans} == {
        "a-cold": "per-arm", "cc-bare": "per-run"}


def test_launch_dispatches_groups_not_individual_plans(tmp_path,
                                                       monkeypatch):
    """The launcher schedules GROUPS (sequential inside an accumulating
    group), never loose plans — proven by the parallel path."""
    seen: list[list[str]] = []

    def _fake_group(group, **kw):
        seen.append([p.unit for p in group])
        return [mx._run_row(p, "planned") for p in group]

    monkeypatch.setattr(mx, "_launch_group", _fake_group)
    plans = [
        _plan(tmp_path, unit="u-1", store_mode="per-arm"),
        _plan(tmp_path, unit="u-2", store_mode="per-arm"),
        _plan(tmp_path, arm="a-other", unit="u-1"),
    ]
    progress = mx.launch(
        plans, tmp_path / "out", budget_usd=1.0, wall_cap_s=60,
        session_cmd=None, plugin_dir=None, warm_source=None,
        warm_context_from=None, operator_root=None, max_parallel=3,
        dry_run=False, store_mode="per-arm")
    assert seen == [["u-1", "u-2"], ["u-1"]]
    assert [r["unit"] for r in progress["runs"]] == ["u-1", "u-2", "u-1"]
    assert progress["store_mode"] == "per-arm"


def test_progress_rows_carry_store_mode_for_accumulating_arms(tmp_path):
    doc = _config("per-arm")
    cfg = _write_config(tmp_path, doc)
    rc = mx.main(["--config", str(cfg), "--dry-run",
                  "--out", str(tmp_path / "m")])
    assert rc == mx.RC_OK
    progress = json.loads(
        (tmp_path / "m" / "progress.json").read_text("utf-8"))
    assert progress["store_mode"] == "per-arm"
    (row,) = progress["runs"]
    assert row["store_mode"] == "per-arm"
    assert row["store_env"].endswith(
        str(Path("a-cold") / "store"))
