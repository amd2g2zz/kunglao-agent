# -*- coding: utf-8 -*-
"""tests/test_eval_matrix_ws5.py — the WS5 five-arm matrix harness.

The harness is MEASUREMENT PREP ONLY: the launcher (orchestration, zero
model calls of its own) plus the readout. Faces pinned here:

  (a) REGISTRY — the declarative arm config parses and validates: the
      five declared arms (ids, runner faces, store kinds), the no-L1
      arm's exact recall-switch env, the unit list (the repo units match
      the split firewall's interpolation holdout READ-ONLY; the two
      blocked-path constructions ride the operator corpus); malformed
      registries REFUSE (bad schema, duplicate ids, an ambiguous loop
      arm, a cc arm that claims a store, a unit without tier);
  (b) DRY-RUN SHAPE — the dry-run lists what WOULD launch (one progress
      row per arm x unit with the child argv, the store face, the
      declared env), writes the progress JSON with every run planned,
      creates NO run dir and spawns NO session (a launch-sized sentinel
      on subprocess.run proves the zero-launch claim); the dry-run
      PREDICTS launch-time refusals (a warm arm without a usable store
      source refuses in the plan, not just at launch);
  (c) CHILD CONSTRUCTION — the child env is HERMETIC (the ablation
      faces are stripped from the inherited environment before the
      arm's declared env merges; the store face is set per arm kind;
      the operator corpus rides its own env var and the repo corpus
      UNSETS it), and the child argv drives the existing per-unit
      runner with the arm's face + caps;
  (d) STORE ISOLATION — cold arms get a materialized EMPTY store dir,
      warm arms get an ISOLATED COPY of the configured warm store
      (arms never share a live store mid-matrix);
  (e) REPORT — the readout over SYNTHETIC completed runs: per arm x
      unit final_status / budget / transitions / facts, decision
      primitives (rewarded rows, propensity-bearing learned rows, mean
      r), the per-unit regret against the post-hoc best arm, and the
      per-arm learned share; missing cells report as missing, never
      invented.

Pure Python + tmp_path fixtures — no sessions, no corpus, no network.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (SCRIPTS,):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import eval_matrix_report as mr  # noqa: E402
import eval_matrix_runner as mx  # noqa: E402

REAL_CONFIG = ROOT / "docs" / "design" / "ws5-five-arms.yaml"
SPLIT = ROOT / "eval" / "v1" / "split.yaml"


# ---- helpers --------------------------------------------------------------

def _write_config(tmp_path: Path, doc: dict) -> Path:
    p = tmp_path / "arms.yaml"
    p.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return p


def _minimal_config(**over) -> dict:
    doc = {
        "schema": "ws5-five-arms/1",
        "budget": {"budget_usd": 1.0, "wall_cap_s": 60},
        "arms": [
            {"id": "a-cold", "runner_face": "loop", "store": "cold",
             "env": {}},
            {"id": "a-warm", "runner_face": "loop", "store": "warm",
             "env": {}},
        ],
        "units": [
            # a unit that RESOLVES against the committed corpus — the
            # dry-run's resolve face must pass for plan rows to carry
            {"id": "py-derive-v1", "corpus": "repo", "tier": "smoke"},
        ],
        "warm_up": {"store_source": None, "warm_context_source": None},
    }
    doc.update(over)
    return doc


def _results_doc(unit: str, verdict: str, loop_status: str, ws: Path,
                 cost: float | None, wall_s: float) -> dict:
    return {"schema": "kunglao-eval-results/1", "rows": [{
        "task_id": unit, "verdict": verdict,
        "loop": {"status": loop_status,
                 "session": {"session_cost": (
                     {"total_cost_usd": cost} if cost is not None else None),
                     "wall_s": wall_s},
                 "workspace": str(ws)},
    }]}


def _transitions(ws: Path, rows: list[dict]) -> None:
    p = ws / "runs" / "transitions.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows),
                 encoding="utf-8")


def _cell(tmp_path: Path, arm: str, unit: str, *, verdict: str,
          loop_status: str = "completed", cost: float | None = 1.0,
          rows: list[dict] | None = None, facts: int = 0,
          ws_name: str | None = None) -> Path:
    """One synthetic completed run: results doc + workspace ledgers."""
    ws = tmp_path / "ws" / (ws_name or f"{arm}-{unit}")
    ws.mkdir(parents=True, exist_ok=True)
    run_dir = tmp_path / arm / unit
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "eval-results-20260101T000000Z-1.json").write_text(
        json.dumps(_results_doc(unit, verdict, loop_status, ws, cost,
                                90.0)),
        encoding="utf-8")
    if rows is not None:
        _transitions(ws, rows)
    if facts:
        (ws / "facts").mkdir(exist_ok=True)
        for i in range(facts):
            (ws / "facts" / f"F{i:03d}.md").write_text(
                "---\nstatus: PROVEN\n---\n", encoding="utf-8")
    return run_dir


# ---- (a) the registry ------------------------------------------------------

def test_real_registry_declares_the_five_arms():
    doc = mx.load_config(REAL_CONFIG)
    arms = mx.config_arms(doc)
    assert [a["id"] for a in arms] == [
        "cc-bare", "cc-warm-context", "kunglao-cold", "kunglao-warm",
        "kunglao-warm-no-l1"]
    assert [a["runner_face"] for a in arms] == [
        "cc-default", "cc-warm-context", "loop", "loop", "loop"]
    assert [a["store"] for a in arms] == [
        "none", "none", "cold", "warm", "warm"]


def test_real_registry_no_l1_arm_declares_the_recall_switch():
    doc = mx.load_config(REAL_CONFIG)
    arm = {a["id"]: a for a in mx.config_arms(doc)}["kunglao-warm-no-l1"]
    assert arm["env"] == {"KUNGLAO_RECALL": "0"}
    # every OTHER arm leaves the switch undeclared (default = recall on)
    for other in mx.config_arms(doc):
        if other["id"] != "kunglao-warm-no-l1":
            assert "KUNGLAO_RECALL" not in (other.get("env") or {})


def test_real_registry_units_match_the_split_firewall_readonly():
    """The repo units in the registry COPY the split's interpolation
    holdout list — drift between the registry and the firewall file is
    a capability-verdict integrity bug. The split is READ, never
    written."""
    doc = mx.load_config(REAL_CONFIG)
    split = yaml.safe_load(SPLIT.read_text(encoding="utf-8"))
    holdout = list(split["holdout"]["interpolation"])
    units = mx.config_units(doc)
    repo_units = [u["id"] for u in units if u["corpus"] == "repo"]
    assert repo_units == holdout
    assert all(u["tier"] == "release" for u in units
               if u["corpus"] == "repo")
    # the extrapolation face: the two blocked-path constructions ride
    # the operator corpus (permanent local-only material)
    op = [u for u in units if u["corpus"] == "operator"]
    assert [u["id"] for u in op] == ["tf-novelvm-rust-v1",
                                     "tf-novelcipher-c-v1"]
    assert all(u["tier"] == "toolflex" for u in op)


@pytest.mark.parametrize("mutate,frag", [
    ({"schema": "nope/9"}, "schema"),
    ({"arms": []}, "non-empty"),
    ({"arms": [{"id": "x", "runner_face": "bogus", "store": "none"}]},
     "runner_face"),
    ({"arms": [{"id": "x", "runner_face": "loop", "store": "none"}]},
     "cold|warm"),
    ({"arms": [{"id": "x", "runner_face": "cc-default",
                "store": "warm"}]}, "never read the store"),
    ({"units": [{"id": "u", "corpus": "bogus", "tier": "release"}]},
     "corpus"),
    ({"units": [{"id": "u", "corpus": "repo"}]}, "tier"),
])
def test_malformed_registry_refuses(tmp_path, mutate, frag):
    doc = _minimal_config()
    doc.update(mutate)
    with pytest.raises(mx.ConfigError, match=frag):
        mx.load_config(_write_config(tmp_path, doc))


def test_duplicate_arm_and_unit_ids_refuse(tmp_path):
    doc = _minimal_config(arms=[
        {"id": "a", "runner_face": "loop", "store": "cold", "env": {}},
        {"id": "a", "runner_face": "loop", "store": "cold", "env": {}}])
    with pytest.raises(mx.ConfigError, match="duplicate arm id"):
        mx.load_config(_write_config(tmp_path, doc))
    doc2 = _minimal_config(units=[{"id": "u", "corpus": "repo",
                                   "tier": "release"},
                                  {"id": "u", "corpus": "repo",
                                   "tier": "release"}])
    with pytest.raises(mx.ConfigError, match="duplicate unit id"):
        mx.load_config(_write_config(tmp_path, doc2))


# ---- (c) child construction ------------------------------------------------

def _plan(tmp_path: Path, **over) -> mx.RunPlan:
    defaults = dict(arm_id="kunglao-warm-no-l1", runner_face="loop",
                    unit="u-1", tier="release", corpus="repo",
                    run_dir=tmp_path / "arm" / "u-1", store_kind="warm",
                    env_extra=(("KUNGLAO_RECALL", "0"),))
    defaults.update(over)
    return mx.RunPlan(**defaults)


def test_child_env_is_hermetic(tmp_path):
    """The ablation faces never leak from the ambient shell into an arm:
    stripped first, then the arm's declared env merges (declared wins)."""
    base = {"KUNGLAO_RECALL": "1", "KUNGLAO_EXPANSION": "0",
            "KUNGLAO_PREDICT_BEFORE_TRY": "1", "PATH": os.environ["PATH"]}
    env = mx.child_env(_plan(tmp_path), base)
    assert env["KUNGLAO_RECALL"] == "0"  # the arm's declaration
    assert "KUNGLAO_EXPANSION" not in env
    assert "KUNGLAO_PREDICT_BEFORE_TRY" not in env


def test_child_env_store_faces_per_kind(tmp_path):
    cold = mx.child_env(_plan(tmp_path, store_kind="cold", env_extra=()))
    warm = mx.child_env(_plan(tmp_path, store_kind="warm", env_extra=()))
    none = mx.child_env(_plan(tmp_path, store_kind="none", env_extra=()))
    assert cold[mx.STORE_ENV] == str(tmp_path / "arm" / "u-1" / "store")
    assert warm[mx.STORE_ENV] == cold[mx.STORE_ENV]
    assert mx.STORE_ENV not in none  # cc faces: unset, not defaulted


def test_child_env_corpus_face(tmp_path):
    op = mx.child_env(_plan(tmp_path, corpus="operator"),
                      {"PATH": "x"}, operator_root="/op-root")
    assert op[mx.EVAL_ROOT_ENV] == "/op-root"
    repo = mx.child_env(_plan(tmp_path, corpus="repo"),
                        {mx.EVAL_ROOT_ENV: "/op-root", "PATH": "x"})
    assert mx.EVAL_ROOT_ENV not in repo  # repo units run the committed tree
    with pytest.raises(mx.ConfigError, match="operator corpus"):
        mx.child_env(_plan(tmp_path, corpus="operator"), {"PATH": "x"})


def test_child_argv_drives_the_existing_runner_face(tmp_path):
    plan = _plan(tmp_path)
    argv = mx.child_argv(plan, budget_usd=2.0, wall_cap_s=1800)
    assert str(mx.RUNNER_SCRIPT) in argv
    i = argv.index("--arm")
    assert argv[i + 1] == "loop"
    j = argv.index("--tasks")
    assert argv[j + 1] == "u-1"
    k = argv.index("--tier")
    assert argv[k + 1] == "release"
    assert "--budget-usd 2.0 --wall-cap-s 1800" != " ".join(argv)  # sanity
    assert argv[argv.index("--budget-usd") + 1] == "2.0"
    # the attribution arm carries its train workspace
    cc = _plan(tmp_path, arm_id="cc-warm-context",
               runner_face="cc-warm-context", store_kind="none",
               env_extra=())
    cc_argv = mx.child_argv(cc, budget_usd=2.0, wall_cap_s=1,
                            warm_context_from=Path("/train-ws"))
    assert cc_argv[cc_argv.index("--warm-context-from") + 1] == \
        "/train-ws"
    with pytest.raises(mx.ConfigError, match="no source workspace"):
        mx.child_argv(cc, budget_usd=2.0, wall_cap_s=1)


# ---- (b) dry-run shape ------------------------------------------------------

def test_dry_run_lists_and_never_launches(tmp_path, monkeypatch):
    """The zero-launch claim, mechanically: a launch-sized sentinel on
    subprocess.run — the dry-run completes only if nothing spawns."""
    def _boom(*a, **k):  # any spawn fails the dry-run
        raise AssertionError("dry-run must not launch sessions")
    monkeypatch.setattr(mx.subprocess, "run", _boom)
    doc = _minimal_config()
    cfg = _write_config(tmp_path, doc)
    rc = mx.main(["--config", str(cfg), "--dry-run",
                  "--out", str(tmp_path / "matrix")])
    assert rc == mx.RC_OK
    out = tmp_path / "matrix"
    progress = json.loads((out / "progress.json").read_text("utf-8"))
    assert progress["schema"] == mx.SCHEMA_PROGRESS
    assert progress["dry_run"] is True
    runs = progress["runs"]
    assert {(r["arm"], r["unit"]) for r in runs} == {
        ("a-cold", "py-derive-v1"), ("a-warm", "py-derive-v1")}
    for row in runs:
        assert row["status"] in ("planned", "refused", "unresolvable")
        assert row["argv"], "the dry-run lists the child argv"
    # no run dir is created — the dry-run touches nothing on disk
    assert not (out / "a-cold").exists()
    assert not (out / "a-warm").exists()


def test_dry_run_predicts_warm_refusal(tmp_path):
    """A warm arm without a usable store source refuses in the PLAN —
    the dry-run's shape and the launch's behavior never disagree."""
    doc = _minimal_config()
    cfg = _write_config(tmp_path, doc)
    mx.main(["--config", str(cfg), "--dry-run",
             "--out", str(tmp_path / "m1")])
    progress = json.loads(
        (tmp_path / "m1" / "progress.json").read_text("utf-8"))
    warm = [r for r in progress["runs"] if r["arm"] == "a-warm"]
    assert warm and all(r["status"] == "refused" and "warm" in
                        r.get("detail", "") for r in warm)
    cold = [r for r in progress["runs"] if r["arm"] == "a-cold"]
    assert all(r["status"] == "planned" for r in cold)


def test_dry_run_with_warm_source_plans_the_copy(tmp_path):
    src = tmp_path / "warm-src"
    src.mkdir()
    (src / mx.STORE_FILE).write_text('{"schema": "posterior-store/1"}\n',
                                     encoding="utf-8")
    doc = _minimal_config()
    cfg = _write_config(tmp_path, doc)
    mx.main(["--config", str(cfg), "--dry-run", "--warm-store", str(src),
             "--out", str(tmp_path / "m2")])
    progress = json.loads(
        (tmp_path / "m2" / "progress.json").read_text("utf-8"))
    warm = [r for r in progress["runs"] if r["arm"] == "a-warm"]
    assert all(r["status"] == "planned" for r in warm)
    assert warm[0]["store"] == "warm"
    assert warm[0]["store_env"].endswith("/store")


# ---- (d) store isolation ----------------------------------------------------

def test_materialize_cold_is_empty_warm_is_an_isolated_copy(tmp_path):
    src = tmp_path / "warm-src"
    src.mkdir()
    (src / mx.STORE_FILE).write_text("rows-here\n", encoding="utf-8")
    warm_plan = _plan(tmp_path / "m")
    cold_plan = _plan(tmp_path / "m", arm_id="a-cold", store_kind="cold",
                      env_extra=(), run_dir=tmp_path / "m" / "a-cold"
                      / "u-1")
    warm_dir = mx.materialize_store(warm_plan, src)
    cold_dir = mx.materialize_store(cold_plan, None)
    assert (warm_dir / mx.STORE_FILE).read_text("utf-8") == "rows-here\n"
    assert cold_dir.is_dir() and list(cold_dir.iterdir()) == []
    # the copy is isolated: writes to the source never reach a run that
    # already materialized (and vice versa)
    (src / mx.STORE_FILE).write_text("MUTATED\n", encoding="utf-8")
    assert (warm_dir / mx.STORE_FILE).read_text("utf-8") == "rows-here\n"


def test_materialize_warm_without_source_refuses(tmp_path):
    with pytest.raises(mx.ConfigError, match="warm claim would be false"):
        mx.materialize_store(_plan(tmp_path / "m"), None)
    src = tmp_path / "empty-src"
    src.mkdir()
    with pytest.raises(mx.ConfigError, match=mx.STORE_FILE):
        mx.materialize_store(_plan(tmp_path / "m2"), src)


# ---- (e) the report over synthetic runs ------------------------------------

def _synthetic_matrix(tmp_path: Path) -> Path:
    """Two arms x one unit, fully completed: a-warm wins on mean reward,
    a-cold leaves regret on the table."""
    _cell(tmp_path, "a-warm", "u-1", verdict="PASS", rows=[
        {"dispatch_id": "C-1", "r_incr": 0.5, "propensity": 0.4},
        {"dispatch_id": "C-2", "r_incr": 0.3, "propensity": 0.2},
        {"dispatch_id": "C-3", "r_incr": -0.1},  # rule-fired, no propensity
    ], facts=2)
    _cell(tmp_path, "a-cold", "u-1", verdict="FAIL", loop_status="exhausted",
          rows=[
              {"dispatch_id": "C-1", "r_incr": 0.0, "propensity": 0.5},
              {"dispatch_id": "C-2", "r_incr": -0.5, "propensity": 0.5},
          ], facts=0)
    return tmp_path


def test_report_matrix_cells_over_synthetic_runs(tmp_path):
    out = _synthetic_matrix(tmp_path)
    report = mr.build_report(out)
    assert report["schema"] == mr.SCHEMA_REPORT
    cells = {(c["arm"], c["unit"]): c for c in report["matrix"]}
    warm = cells[("a-warm", "u-1")]
    cold = cells[("a-cold", "u-1")]
    assert warm["final_status"] == "PASS"
    assert warm["loop_status"] == "completed"
    assert warm["budget_usd"] == 1.0
    assert warm["wall_s"] == 90.0
    assert warm["transitions"] == 3
    assert warm["facts"] == 2
    assert warm["decisions"] == 3
    assert warm["learned_decisions"] == 2
    assert warm["mean_r"] == round((0.5 + 0.3 - 0.1) / 3, 6)
    assert cold["final_status"] == "FAIL"
    assert cold["loop_status"] == "exhausted"
    assert cold["decisions"] == 2
    assert cold["mean_r"] == -0.25


def test_report_regret_against_the_post_hoc_best_arm(tmp_path):
    out = _synthetic_matrix(tmp_path)
    report = mr.build_report(out)
    cells = {(c["arm"], c["unit"]): c for c in report["matrix"]}
    warm, cold = cells[("a-warm", "u-1")], cells[("a-cold", "u-1")]
    # the best arm's regret is zero by construction; the other arm's
    # regret is the best mean minus its own mean
    assert warm["regret_vs_best_arm"] == 0.0
    assert cold["regret_vs_best_arm"] == round(warm["mean_r"] + 0.25, 6)
    arms = report["arms"]
    assert arms["a-warm"]["regret_total"] == 0.0
    assert arms["a-cold"]["regret_total"] == cold["regret_vs_best_arm"]


def test_report_learned_share_is_the_propensity_fraction(tmp_path):
    out = _synthetic_matrix(tmp_path)
    report = mr.build_report(out)
    arms = report["arms"]
    assert arms["a-warm"]["learned_share"] == round(2 / 3, 4)
    assert arms["a-cold"]["learned_share"] == 1.0
    # a rule-fired-only arm reports share 0.0, never None
    assert arms["a-warm"]["decisions"] == 3


def test_report_names_missing_cells_without_inventing(tmp_path):
    out = tmp_path
    (out / "a-warm" / "u-1").mkdir(parents=True)  # dir, no results doc
    report = mr.build_report(out)
    cells = {(c["arm"], c["unit"]): c for c in report["matrix"]}
    assert cells[("a-warm", "u-1")]["final_status"] == "missing"
    assert (out / "report.json").is_file()


def test_report_refusal_states_surface_from_the_spine(tmp_path):
    """A run the launcher refused (e.g. a warm arm without a source) is
    a reported state, not a silently absent cell."""
    out = tmp_path
    arm_dir = out / "a-warm" / "u-1"
    arm_dir.mkdir(parents=True)
    spine = {"schema": mx.SCHEMA_PROGRESS, "runs": [
        {"arm": "a-warm", "unit": "u-1", "status": "refused",
         "detail": "no warm source"}]}
    (out / "progress.json").write_text(json.dumps(spine), encoding="utf-8")
    report = mr.build_report(out)
    cell = report["matrix"][0]
    assert cell["final_status"] == "refused"
    assert cell["transitions"] == 0 and cell["facts"] == 0
