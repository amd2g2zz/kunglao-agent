# -*- coding: utf-8 -*-
"""tests/test_eval_loop_runner_334.py — the loop runner (#334).

The loop launch is a REAL Claude Code + kunglao-plugin session doing real
analysis — the runner's only jobs: workspace init -> launch the real
session (budget caps) -> wait -> harvest the ledgers the REAL loop wrote
-> run the final mechanical check. Faces pinned here:

  (a) LAUNCH SHAPE — the production argv is the real `claude` CLI's
      documented flags (`-p`, `--plugin-dir`, `--permission-mode`,
      `--output-format json`, `--max-budget-usd`); the session launcher is
      ONE thin adapter function (harness-neutral: the pi face swaps at
      v0.2 by replacing the adapter alone);
  (b) INIT WIRING — a fresh workspace is kunglao-init'ed with the task's
      three anchors landed (task_spec.yaml carries goal_verbatim /
      success_criterion / verification_method verbatim from the task
      unit) and the target present as the analysis subject (bins/);
  (c) SEAM — tests NEVER invoke the real model face: an env/cmd
      overridable session command (a stub that writes a plausible ledger
      into its cwd, clearly labeled test-only) stands in; the stub also
      records its argv so the prompt hand-off is asserted;
  (d) HARVEST — loop metrics are computed FROM THE LEDGER FILES the
      session wrote: convergence decision (convergence_check subprocess),
      rounds (snapshot rows in .convergence_ledger.jsonl, the
      priority_ratio.round_index contract), dispatch count + cost tokens
      (the #12 factor vectors in runs/mission_ledger.yaml), oracle case
      green rate (runs/oracle-status.json), PROVEN claims
      (claim-register.yaml), the #136 task_terminal_settlement row
      (runs/logs/kunglao-*.jsonl);
  (e) BUDGET — budget exhaustion is a TERMINAL metric row
      (loop.status=exhausted), never a crash: the runner kills an
      over-wall-cap session and still harvests + emits the row;
  (f) EXTRACTOR — the loop's deliverable maps to checker candidate form
      (runs/deliverables/candidate<suffix> primary, deterministic
      workspace fallback scan, None -> structured BAD_CANDIDATE row);
  (g) END-TO-END — stub session -> harvested row (arm=loop) with loop
      metrics + the REAL #299 checker verdict on the stub-written
      candidate; the results doc is kunglao-eval-results/1, comparable
      with the #236 bare rows;
  (h) LEAKAGE — the loop prompt carries the anchors + the candidate
      contract + the deliverable path ONLY: no ground-truth answers, no
      thresholds/oracle vocabulary.

Integration tier: real kunglao-init + real convergence_check +
real eval_checker subprocesses (py face; go/js self-skip on absent
toolchains per the 299 degradation contract).
"""
from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TASKS = ROOT / "eval" / "v1" / "tasks" / "smoke"

import eval_dataset as ds
import eval_loop_runner as lr


PY = "py-derive-v1"


def _task_dir(task_id: str) -> Path:
    hits = sorted(TASKS.glob(task_id)) or sorted(TASKS.glob(f"*/{task_id}"))
    assert hits, f"task dir not found for {task_id}"
    return hits[0]


# The test-only session stub: a tiny python script used AS the session
# command through the runner's seam. It (1) records its argv into its cwd,
# (2) writes a plausible ledger set for mode=candidate, (3) sleeps past any
# wall cap for mode=slow. Clearly labeled test-only — the PRODUCTION path
# constructs the real `claude` CLI argv (face (a)) and never sees this.
_STUB_SESSION = textwrap.dedent("""\
    # TEST-ONLY stub session (issue #334 tests) — never a production face.
    import json, os, sys, time
    from pathlib import Path
    cwd = Path.cwd()
    (cwd / "session-argv.json").write_text(
        json.dumps(sys.argv), encoding="utf-8")
    mode = os.environ.get("K334_STUB_MODE", "candidate")
    if mode == "slow":
        (cwd / ".convergence_ledger.jsonl").write_text(
            json.dumps({"open_count": 0}) + "\\n", encoding="utf-8")
        time.sleep(60)
        sys.exit(0)
    runs = cwd / "runs"
    (runs / "logs").mkdir(parents=True, exist_ok=True)
    (runs / "deliverables").mkdir(parents=True, exist_ok=True)
    (cwd / ".convergence_ledger.jsonl").write_text(
        json.dumps({"open_count": 2, "decision": "DISPATCH"}) + "\\n"
        + json.dumps({"open_count": 1, "decision": "VERIFY"}) + "\\n"
        + json.dumps({"open_count": 0, "decision": "CONVERGED"}) + "\\n",
        encoding="utf-8")
    vec = {"round": 1, "v_norm": 0.5,
           "events": {"dispatch": 2, "verify": 1, "confirmed_with_diff": 1,
                      "toss": 0},
           "cost_tokens": 120.0, "cost_rounds": 1, "signals_rows": 3}
    vec2 = dict(vec, round=2, cost_tokens=340.0,
                events=dict(vec["events"], dispatch=3))
    import yaml as _y
    (runs / "mission_ledger.yaml").write_text(
        _y.safe_dump({"mission": {"history": [vec, vec2]}}),
        encoding="utf-8")
    (runs / "oracle-status.json").write_text(json.dumps({
        "schema": "oracle-status/1",
        "cases": {"case-a": {"status": "pass"},
                  "case-b": {"status": "pass"},
                  "case-c": {"status": "fail"}}}), encoding="utf-8")
    # token spend lives at the workspace ROOT (tuition_curve.cost_state)
    (cwd / "cost_events.jsonl").write_text(
        json.dumps({"amount": 0.4}) + "\\n"
        + json.dumps({"amount": 0.25}) + "\\n", encoding="utf-8")
    day = time.strftime("%Y-%m-%d", time.gmtime())
    (runs / "logs" / f"kunglao-{day}.jsonl").write_text(
        json.dumps({"action": "dispatch", "claim": "C-009"}) + "\\n"
        + json.dumps({"action": "task_terminal_settlement",
                      "schema": "task-terminal-settlement/1"}) + "\\n",
        encoding="utf-8")
    # the deliverable: the task's own reference implementation (a checker-
    # green candidate) written where the loop prompt mandates it
    src = sorted((cwd / "bins").glob("*.py"))[0]
    (runs / "deliverables" / "candidate.py").write_text(
        src.read_text(encoding="utf-8"), encoding="utf-8")
""")


def _stub_session_cmd(tmp_path: Path) -> str:
    stub = tmp_path / "k334_stub_session.py"
    stub.write_text(_STUB_SESSION, encoding="utf-8")
    return f'"{sys.executable}" "{stub}"'


@pytest.fixture()
def stub_candidate_src() -> Path:
    """The reference py-derive implementation (checker-green candidate):
    the task unit's own constructed target source."""
    return _task_dir(PY) / "target" / "derive.py"


# ---------------------------------------------------------------- (a) shape
class TestLaunchShape:
    def test_production_argv_uses_documented_claude_flags(self):
        argv = lr.build_claude_argv(
            "PROMPT", plugin_dir=Path("/repo"), budget_usd=2.5)
        assert argv[0] == "claude"
        assert "-p" in argv
        assert argv[argv.index("-p") + 1] == "PROMPT", \
            "prompt travels as the positional (claude -p <prompt>)"
        assert "--plugin-dir" in argv
        assert argv[argv.index("--plugin-dir") + 1] == "/repo"
        assert "--permission-mode" in argv
        assert argv[argv.index("--permission-mode") + 1] == \
            "bypassPermissions"
        assert "--output-format" in argv
        assert argv[argv.index("--output-format") + 1] == "json"
        assert "--max-budget-usd" in argv
        assert argv[argv.index("--max-budget-usd") + 1] == "2.5"

    def test_session_command_override_skips_claude_argv(self, tmp_path):
        """The adapter seam: an explicit session command replaces the claude
        argv wholesale (only the prompt is appended as the positional)."""
        rec = lr.launch_session(
            tmp_path, "THE PROMPT", budget_usd=1.0, wall_cap_s=30.0,
            session_cmd=f'"{sys.executable}" -c "pass"')
        assert rec["argv"][0] == sys.executable
        assert rec["argv"][-1] == "THE PROMPT"

    def test_env_override_session_command(self, tmp_path, monkeypatch):
        stub = tmp_path / "stub.py"
        stub.write_text("import sys\n", encoding="utf-8")
        monkeypatch.setenv(lr.ENV_SESSION_CMD, f"{sys.executable} {stub}")
        rec = lr.launch_session(tmp_path, "P", budget_usd=1.0,
                                wall_cap_s=30.0)
        assert rec["argv"][:2] == [sys.executable, str(stub)]

    def test_missing_session_binary_is_terminal_record_not_crash(
            self, tmp_path):
        rec = lr.launch_session(
            tmp_path, "P", budget_usd=1.0, wall_cap_s=30.0,
            session_cmd="/nonexistent/k334-no-such-binary")
        assert rec["returncode"] is None
        assert rec["launch_error"]


# ---------------------------------------------------------------- (b) init
class TestInitWiring:
    def test_init_workspace_lands_anchors_and_target(self, tmp_path):
        tdir = _task_dir(PY)
        task = ds.load_task(tdir)
        ws = lr.init_workspace(tdir, tmp_path)
        assert (ws / "claim-register.yaml").is_file()
        assert (ws / "runs").is_dir()
        spec = yaml.safe_load((ws / "task_spec.yaml").read_text("utf-8"))
        for field in ds.ANCHOR_FIELDS:
            assert spec[field] == task["anchors"][field], \
                f"anchor {field} must land verbatim (#191)"
        assert spec["lane"] == "algorithm"
        # the analysis subject: the task's scaffold files copied in
        entry = task["workspace_scaffold"]["entry"]
        assert (ws / "bins" / Path(entry).name).is_file()
        assert (ws / entry).is_file()

    def test_init_workspace_is_fresh_per_call(self, tmp_path):
        tdir = _task_dir(PY)
        ws1 = lr.init_workspace(tdir, tmp_path)
        ws2 = lr.init_workspace(tdir, tmp_path)
        assert ws1 != ws2, "each eval task run gets a FRESH workspace"


# ---------------------------------------------------------------- (c) seam
class TestSessionSeam:
    def test_stub_session_runs_in_workspace_cwd(self, tmp_path):
        ws = lr.init_workspace(_task_dir(PY), tmp_path)
        rec = lr.launch_session(
            ws, "RUN THE LOOP", budget_usd=1.0, wall_cap_s=60.0,
            session_cmd=_stub_session_cmd(tmp_path))
        assert rec["returncode"] == 0
        argv = json.loads((ws / "session-argv.json").read_text("utf-8"))
        assert argv[-1] == "RUN THE LOOP", \
            "the prompt is handed to the session command"
        assert (ws / ".convergence_ledger.jsonl").is_file(), \
            "the stub wrote its ledgers into the workspace cwd"


# -------------------------------------------------------------- (d) harvest
class TestHarvest:
    @pytest.fixture()
    def seeded_ws(self, tmp_path):
        """A REAL init'd workspace + stub-written ledgers: the harvest
        contract runs against genuine workspace files. The launch baseline
        (init writes no ledger row) is captured post-init — the runner's
        own sequence."""
        ws = lr.init_workspace(_task_dir(PY), tmp_path)
        baseline = lr.count_snapshot_rows(ws)
        rec = lr.launch_session(
            ws, "RUN", budget_usd=1.0, wall_cap_s=60.0,
            session_cmd=_stub_session_cmd(tmp_path))
        assert rec["returncode"] == 0
        return ws, baseline

    def test_metrics_computed_from_ledger_files(self, seeded_ws):
        ws, baseline = seeded_ws
        assert baseline == 0, "init writes no ledger row: ticks are the loop's"
        m = lr.harvest(ws, baseline_rounds=baseline)
        assert m["rounds"] == 3, \
            "LOOP snapshot rows in .convergence_ledger.jsonl " \
            "(the tick axis; the harvest probe's own convergence_check " \
            "append lands after the count)"
        assert m["dispatch_count"] == 5, \
            "sum of #12 factor-vector events.dispatch (2 + 3)"
        assert m["oracle_cases_green"] == 2
        assert m["oracle_cases_total"] == 3
        assert m["oracle_green_rate"] == pytest.approx(2 / 3)
        assert m["proven_claims"] == 3, "init's three structural seeds"
        assert m["tokens_cost"] == pytest.approx(0.65)
        assert m["terminal_row"] is True, "#136 settlement row present"
        assert m["factor_vectors"] == 2
        # a fresh init'd workspace has an empty operationalization: the
        # real convergence_check face answers BLOCKED, not CONVERGED
        assert m["decision"] == "BLOCKED"
        assert m["converged"] is False

    def test_converged_decision_mapping(self):
        assert lr.is_converged_decision("CONVERGED") is True
        for other in ("DISPATCH", "VERIFY", "SATURATED", "BLOCKED", "PARK",
                      "", None):
            assert lr.is_converged_decision(other) is False

    def test_harvest_on_untouched_workspace(self, tmp_path):
        ws = lr.init_workspace(_task_dir(PY), tmp_path)
        assert lr.count_snapshot_rows(ws) == 0, \
            "fresh init: no ledger, no ticks"
        m = lr.harvest(ws)
        assert m["rounds"] == 0
        assert m["dispatch_count"] == 0
        assert m["oracle_cases_total"] == 0
        assert m["oracle_green_rate"] == 0.0, "empty denominator: 0.0"
        assert m["terminal_row"] is False
        assert m["tokens_cost"] == 0.0


# ---------------------------------------------------------------- (e) budget
class TestBudgetExhaustion:
    def test_over_wall_session_is_terminal_exhausted_row(self, tmp_path):
        monkeyish = {"K334_STUB_MODE": "slow"}
        old = {k: os.environ.get(k) for k in monkeyish}
        os.environ.update(monkeyish)
        try:
            row = lr.run_loop_task(
                PY, tmp_path, budget_usd=1.0, wall_cap_s=1.0,
                session_cmd=_stub_session_cmd(tmp_path))
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        assert row["loop"]["status"] == "exhausted", \
            "budget exhaustion is a TERMINAL metric row, never a crash"
        assert row["arm"] == "loop"
        assert row["verdict"] == "SKIP", \
            "no deliverable landed before the kill: structured SKIP"
        assert any(f["code"] == "BAD_CANDIDATE" for f in row["failures"])
        assert row["loop"]["session"]["timed_out"] is True


# ------------------------------------------------------------- (f) extractor
class TestExtractor:
    def test_primary_deliverable_path(self, tmp_path):
        task = ds.load_task(_task_dir(PY))
        ws = tmp_path
        d = ws / "runs" / "deliverables"
        d.mkdir(parents=True)
        (d / "candidate.py").write_text("def derive(b):\n    return 0\n",
                                        encoding="utf-8")
        got = lr.extract_candidate(ws, task)
        assert got is not None
        assert got.suffix == ".py"
        assert got.read_text("utf-8").startswith("def derive")

    def test_fallback_scan_finds_workspace_deliverable(self, tmp_path):
        task = ds.load_task(_task_dir(PY))
        ws = tmp_path
        d = ws / "deliverables"
        d.mkdir(parents=True)
        (d / "derive_final.py").write_text("def derive(b):\n    return 1\n",
                                           encoding="utf-8")
        got = lr.extract_candidate(ws, task)
        assert got is not None and got.suffix == ".py"

    def test_no_deliverable_is_none(self, tmp_path):
        task = ds.load_task(_task_dir(PY))
        assert lr.extract_candidate(tmp_path, task) is None


# ------------------------------------------------------------- (g) end-to-end
class TestEndToEnd:
    def test_stub_run_produces_loop_row_with_real_checker_verdict(
            self, tmp_path, stub_candidate_src):
        row = lr.run_loop_task(
            PY, tmp_path, budget_usd=1.0, wall_cap_s=60.0,
            session_cmd=_stub_session_cmd(tmp_path))
        assert row["task_id"] == PY
        assert row["arm"] == "loop"
        assert row["family"] == "py-derive"
        assert row["verdict"] == "PASS", \
            "the stub's candidate is checker-green (the plumbing is real)"
        assert row["loop"]["checker_rc"] == 0
        loop = row["loop"]
        assert loop["status"] == "completed"
        assert loop["metrics"]["rounds"] == 3
        assert loop["metrics"]["dispatch_count"] == 5
        assert loop["metrics"]["oracle_green_rate"] == pytest.approx(2 / 3)
        assert loop["metrics"]["terminal_row"] is True
        assert loop["session"]["returncode"] == 0
        assert row["evidence_ref"], "checker evidence archived"

    def test_results_doc_shape_comparable_with_bare_rows(
            self, tmp_path, stub_candidate_src):
        rc, doc = lr.run_loop_tier(
            [PY], tmp_path, budget_usd=1.0, wall_cap_s=60.0,
            session_cmd=_stub_session_cmd(tmp_path))
        assert rc == 0
        assert doc["schema"] == ds.RESULTS_SCHEMA
        assert doc["arm"] == "loop"
        assert doc["tier"] == "smoke"
        assert len(doc["rows"]) == 1
        r = doc["rows"][0]
        for key in ("task_id", "family", "checker_kind", "metrics",
                    "verdict", "failures", "evidence_ref", "arm"):
            assert key in r, f"results-row contract key {key}"
        assert set(r["metrics"]) == set(ds.REQUIRED_METRICS)
        assert (tmp_path / "doc.json").exists() or True  # doc written by caller
        paths = list(tmp_path.glob("eval-results-*.json"))
        assert paths, "kunglao-eval-results/1 doc persisted"


# --------------------------------------------------------------- (h) leakage
class TestPromptLeakage:
    def test_prompt_carries_anchors_and_contract_only(self):
        tdir = _task_dir(PY)
        task = ds.load_task(tdir)
        prompt = lr.build_loop_prompt(tdir, task,
                                      "runs/deliverables/candidate.py")
        for anchor in ds.ANCHOR_FIELDS:
            assert task["anchors"][anchor] in prompt
        assert task["workspace_scaffold"]["candidate_contract"] in prompt
        assert "runs/deliverables/candidate.py" in prompt

    def test_prompt_never_carries_ground_truth_or_thresholds(self):
        tdir = _task_dir(PY)
        task = ds.load_task(tdir)
        gt = json.loads((tdir / "ground_truth.json").read_text("utf-8"))
        prompt = lr.build_loop_prompt(tdir, task,
                                      "runs/deliverables/candidate.py")
        assert "ground_truth" not in prompt
        assert "min_pair_ratio" not in prompt
        assert "eval_checker" not in prompt
        # published-pair OUTPUTS must never appear
        for pair in gt.get("published_pairs", [])[:3]:
            out = pair.get("out")
            if out is not None:
                assert str(out) not in prompt


# ---------------------------------------- (i) native-tier runnability
# The v0.1.6 loop-arm campaign ran the runner across the release tier's
# L1 set and surfaced three native-tier gaps: a text-decode scaffold copy
# (UnicodeDecodeError on ELF targets), a language-keyed candidate suffix
# (KeyError on the native families), and a tier-wide crash on one unit's
# init failure. Pins below; all faces deterministic.

class TestNativeRunnability:
    def test_elf_scaffold_copies_byte_exact(self, tmp_path):
        """arm-kdf-l0's scaffold entry is an ELF binary: the workspace copy
        must round-trip the bytes exactly (a text decode crashed here)."""
        release = sorted(ds.iter_task_dirs(tier="release"))
        tdir = next(d for d in release if d.name == "arm-kdf-l0")
        task = ds.load_task(tdir)
        assert (tdir / task["workspace_scaffold"]["entry"]).read_bytes()[:4] \
            == b"\x7fELF", "pin expects the binary target"
        ws = lr.init_workspace(tdir, tmp_path)
        for rel in task["workspace_scaffold"]["files"]:
            assert (ws / rel).read_bytes() == (tdir / rel).read_bytes(), \
                f"scaffold file {rel} must round-trip byte-exact"
        entry = task["workspace_scaffold"]["entry"]
        assert (ws / "bins" / Path(entry).name).read_bytes() \
            == (tdir / entry).read_bytes()

    def test_candidate_suffix_parity_with_checker(self, tmp_path):
        """_candidate_suffix mirrors eval_checker._validate_candidate
        exactly across every tier's families (checker must accept the
        mapped suffix)."""
        import eval_checker as chk

        for tier in ds.TIERS:
            for d in ds.iter_task_dirs(tier=tier):
                family = ds.load_task(d)["family"]
                suffix = lr._candidate_suffix(ds.load_task(d))
                cand = tmp_path / f"{tier}-{family}-probe{suffix}"
                cand.write_bytes(b"# probe\n")
                chk._validate_candidate(cand, family)

    def test_init_failure_is_structured_skip_never_crash(self, tmp_path,
                                                         monkeypatch):
        """One unit's kunglao-init failure yields a structured SKIP row
        (loop.status=init_failed, BAD_TASK code, reason carried) — the
        tier's other units still measure."""
        def _boom(task_dir, work_root, **kw):
            raise RuntimeError("kunglao-init failed rc=1 "
                               "for some-unit: gated detail")

        monkeypatch.setattr(lr, "init_workspace", _boom)
        row = lr.run_loop_task(PY, tmp_path)
        assert row["verdict"] == "SKIP"
        assert row["loop"]["status"] == "init_failed"
        assert row["failures"][0]["code"] == "BAD_TASK"
        assert "kunglao-init failed rc=1" in row["failures"][0]["detail"]
        assert row["loop"]["workspace"] is None
