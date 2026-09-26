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
      (loop.status=exhausted), never a crash, on BOTH kill faces: the
      runner kills an over-wall-cap session (timed_out) and the CLI stops
      itself at/over --max-budget-usd (rc=1 + cost report) — either way
      the row is still harvested + graded; a sub-budget rc=1 stays
      session_error (a genuine crash);
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
    # exp5: every stub invocation APPENDS one call row — the gap-redo
    # tests count sessions this way (session-argv.json stays last-argv).
    with (cwd / "session-calls.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": sys.argv, "mode": mode}) + "\\n")
    if mode == "escape":
        # exp3 Part A: the workspace-escape face — the session writes to a
        # HARNESS-SURFACE file OUTSIDE its cwd (the 2026-09-24 incident:
        # an Edit on the worktree-level agents/kunglao-redteam.md), then
        # falls through to the normal ledger path (grading still runs).
        tgt = os.environ.get("K334_ESCAPE_TARGET", "")
        if tgt:
            p = Path(tgt)
            p.write_text(p.read_text(encoding="utf-8") + "# ESCAPE-JUNK\\n",
                         encoding="utf-8")
    if mode == "slow":
        (cwd / ".convergence_ledger.jsonl").write_text(
            json.dumps({"open_count": 0}) + "\\n", encoding="utf-8")
        time.sleep(60)
        sys.exit(0)
    if mode == "crash":
        # rc=1 with NO cost report: a genuine mid-session crash face
        sys.exit(1)
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
    if mode == "late-dispatch":
        # exp8 I4: dispatch signals landing AFTER the ledger's last
        # sample cursor (signals_rows=3) — the settle face must count
        # the late dispatch (exp4 read 0 ticks on all 7 units).
        (runs / "signals.jsonl").write_text(
            json.dumps({"ts": "t1", "kind": "dispatch", "claim": "C-101"}) + "\\n"
            + json.dumps({"ts": "t2", "kind": "deliver", "claim": "C-101"}) + "\\n"
            + json.dumps({"ts": "t3", "kind": "verify"}) + "\\n"
            + json.dumps({"ts": "t4", "kind": "dispatch", "claim": "C-104"}) + "\\n",
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
    if mode == "budget":
        # rc=1 WITH the claude --output-format json cost line: the CLI-side
        # --max-budget-usd stop face (print mode exits non-zero at/over
        # the cap — the 2026-09-24 sweep's session_error class)
        print(json.dumps({"type": "result", "total_cost_usd": 15.14,
                          "usage": {"input_tokens": 251052,
                                    "output_tokens": 71887}}))
        sys.exit(1)
    if mode == "candidate-bad-escape":
        # #380 P3-2: the REDO session escapes the harness surface (the
        # main session stays clean) — the summary-counter divergence face.
        if sum(1 for _ in open(cwd / "session-calls.jsonl")) >= 2:
            tgt = os.environ.get("K334_ESCAPE_TARGET", "")
            if tgt:
                ep = Path(tgt)
                ep.write_text(ep.read_text(encoding="utf-8")
                              + "# ESCAPE-JUNK\\n", encoding="utf-8")
    if mode in ("candidate-bad", "candidate-bad-escape", "budget-bad"):
        # exp5 gap-redo faces: a DELIVERED candidate that FAILS the
        # mechanical checker (wrong output on every probe → PAIR_MISMATCH)
        (runs / "deliverables" / "candidate.py").write_text(
            "def derive(b):\\n"
            "    return len(b)  # deliberately wrong (test-only stub)\\n",
            encoding="utf-8")
    if mode == "budget-bad":
        # FAIL verdict + CLI-side budget stop: cost >= cap so the
        # gap-redo decision must deny on budget exhaustion
        print(json.dumps({"type": "result", "total_cost_usd": 15.14,
                          "usage": {"input_tokens": 251052,
                                    "output_tokens": 71887}}))
        sys.exit(1)
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

    def test_cli_budget_cap_exit_is_terminal_exhausted_row(
            self, tmp_path, monkeypatch):
        """The CLI-side budget face: `claude -p --max-budget-usd` stops the
        session ITSELF at/over the cap and exits rc=1 (the 2026-09-24
        sweep's session_error class: 9/12 units rc=1 at $15.0x against a
        $15.0 cap). The module contract — budget exhaustion is a TERMINAL
        metric row, never a crash — covers BOTH kill faces: the runner's
        wall cap AND the CLI's budget stop."""
        monkeypatch.setenv("K334_STUB_MODE", "budget")
        row = lr.run_loop_task(
            PY, tmp_path, budget_usd=15.0, wall_cap_s=60.0,
            session_cmd=_stub_session_cmd(tmp_path))
        loop = row["loop"]
        assert loop["status"] == "exhausted", \
            "CLI budget-cap exit (rc=1, cost>=cap) is budget exhaustion: " \
            "the terminal exhausted row, never session_error"
        assert loop["session"]["timed_out"] is False, \
            "the runner never fired the wall cap: the CLI stopped itself"
        assert loop["session"]["returncode"] == 1
        assert loop["session"]["session_cost"][
            "total_cost_usd"] == pytest.approx(15.14)
        assert row["verdict"] == "PASS", \
            "whatever the loop wrote before the kill is still harvested " \
            "and graded (the stub's candidate is checker-green)"

    def test_sub_budget_rc1_stays_session_error(self, tmp_path, monkeypatch):
        """The guard face: rc=1 WITHOUT a budget-cap cost report is a
        genuine session crash — session_error must survive for it."""
        monkeypatch.setenv("K334_STUB_MODE", "crash")
        row = lr.run_loop_task(
            PY, tmp_path, budget_usd=15.0, wall_cap_s=60.0,
            session_cmd=_stub_session_cmd(tmp_path))
        assert row["loop"]["status"] == "session_error", \
            "sub-budget rc=1 is a real crash: the misclassification fix " \
            "must not swallow it"
        assert row["loop"]["session"]["session_cost"] is None
        assert row["verdict"] == "SKIP", \
            "the crash left no deliverable: structured BAD_CANDIDATE row"


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
        mapped suffix). Both now consume the single-source contract
        (issue 352), TF families included (issue 356 union)."""
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


# --------------------------------------- (j) CC-DEFAULT arm (harness var)
class TestCcDefaultArm:
    def test_cc_default_argv_has_no_plugin(self):
        """The harness-variable face: same caps, NO --plugin-dir, NO
        kunglao flags — plain default-harness claude."""
        argv = lr.build_cc_default_argv("PROMPT", 7.5)
        assert argv[:3] == ["claude", "-p", "PROMPT"]
        assert "--plugin-dir" not in argv
        assert "--permission-mode" in argv
        assert argv[argv.index("--max-budget-usd") + 1] == "7.5"

    def test_launch_session_plugin_false_uses_cc_default_face(self,
                                                              tmp_path):
        recorded = {}

        def _fake_builder(prompt, budget):
            recorded["prompt"] = prompt
            recorded["budget"] = budget
            return ["echo-cmd", prompt]

        orig = lr.build_cc_default_argv
        lr.build_cc_default_argv = _fake_builder
        try:
            lr.launch_session(tmp_path, "PROMPT", budget_usd=1.0,
                              wall_cap_s=1, plugin=False)
        finally:
            lr.build_cc_default_argv = orig
        assert recorded["prompt"] == "PROMPT"
        assert recorded["budget"] == 1.0

    def test_cc_default_workspace_is_neutral_and_complete(self, tmp_path):
        """Neutral cwd: unit material + TASK.md only — no kunglao-init
        scaffold (no claim-register/task_spec), anchors verbatim in the
        prompt, deliverable path mandated."""
        tdir = next(d for d in ds.iter_task_dirs(tier="release")
                    if d.name == "arm-kdf-l0")
        task = ds.load_task(tdir)
        ws, prompt = lr.init_cc_default_workspace(tdir, tmp_path)
        for rel in task["workspace_scaffold"]["files"]:
            assert (ws / rel).read_bytes() == (tdir / rel).read_bytes()
        assert (ws / "TASK.md").is_file()
        assert not (ws / "claim-register.yaml").exists()
        assert not (ws / "task_spec.yaml").exists()
        for field in ds.ANCHOR_FIELDS:
            assert task["anchors"][field] in prompt
        assert task["workspace_scaffold"]["candidate_contract"] in prompt
        assert "runs/deliverables/candidate.py" in prompt
        # the kunglao invocation face must NOT appear
        assert "/kunglao-agent" not in prompt

    def test_run_loop_task_cc_default_end_to_end(self, tmp_path,
                                                 monkeypatch):
        """arm='cc-default' drives the STUB seam end to end and labels
        rows arm=cc-default with the same checker verdict contract. The
        session command MUST stay wired to the stub — an unwired seam
        would spawn a real claude session inside a unit test."""
        monkeypatch.setenv("K334_STUB_MODE", "candidate")

        def _ccd_stub(task_dir, root, *, wall_cap_s=None):
            ws = lr.init_workspace(_task_dir(PY), root)
            return ws, "solve it; deliver to runs/deliverables/candidate.py"

        monkeypatch.setattr(lr, "init_cc_default_workspace", _ccd_stub)
        row = lr.run_loop_task(PY, tmp_path, budget_usd=1.0,
                               wall_cap_s=5, arm="cc-default",
                               session_cmd=_stub_session_cmd(tmp_path))
        assert row["arm"] == "cc-default"
        assert row["verdict"] in ("PASS", "FAIL", "SKIP")


# --------------------------------- (j) harness escape gate (exp3 Part A)
# The 2026-09-24 sweep caught a spawned analysis session ESCAPING its
# workspace TWICE (activity log 2026-09-24T04:18:44, session
# 2026-09-24_68ea2493): an Edit tool call targeting the worktree-level
# agents/kunglao-redteam.md — a checker permission-widening. Workspace
# isolation is advisory; bypassPermissions sessions can write anywhere.
# The gate: hash the harness surface (agents/ hooks/ skills/ scripts/)
# BEFORE each session spawn and AFTER session exit; on drift emit a loud
# event row (EMIT_ACTIONS-registered harness_drift), restore the drifted
# files from HEAD (git checkout --), and mark the session row
# harness_contaminated (diagnostic — the verdict is unaffected, grading
# already ran on the workspace's own deliverable).

class TestHarnessEscapeGate:
    def _fake_root(self, tmp_path: Path) -> Path:
        """A synthetic harness root: the four surface dirs + a git HEAD —
        restore proves itself against a real checkout, never the live
        repo tree (parallel-safe)."""
        import subprocess as sp

        root = tmp_path / "repo"
        for rel in ("agents/kunglao-redteam.md", "hooks/gate.py",
                    "skills/kunglao-agent/SKILL.md", "scripts/runner.py"):
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"original {rel}\n", encoding="utf-8")
        pyc = root / "scripts" / "__pycache__"
        pyc.mkdir(parents=True)
        (pyc / "runner.pyc").write_bytes(b"\x00")

        def git(*args: str) -> None:
            r = sp.run(["git", "-C", str(root), *args],
                       capture_output=True, text=True)
            assert r.returncode == 0, r.stderr

        git("init", "-q")
        git("add", "-A")
        git("-c", "user.email=t@t", "-c", "user.name=t",
            "commit", "-qm", "base")
        return root

    def test_hashes_cover_four_surface_dirs_skip_pycache(self, tmp_path):
        root = self._fake_root(tmp_path)
        h = lr.harness_surface_hashes(root)
        assert "agents/kunglao-redteam.md" in h
        assert "hooks/gate.py" in h
        assert "skills/kunglao-agent/SKILL.md" in h
        assert "scripts/runner.py" in h
        assert not any("__pycache__" in k for k in h), \
            "pycache is not harness surface"

    def test_default_root_is_the_repo(self):
        h = lr.harness_surface_hashes()
        assert any(k.startswith("agents/") for k in h)
        assert any(k.startswith("hooks/") for k in h)
        assert any(k.startswith("scripts/") for k in h)

    def test_drift_reports_changed_added_deleted(self):
        before = {"a.md": "1", "b.md": "2", "c.md": "3"}
        assert lr.harness_drift(before, dict(before)) == []
        after = {"a.md": "1", "b.md": "X", "d.md": "4"}
        assert lr.harness_drift(before, after) == \
            ["b.md", "c.md", "d.md"], \
            "changed + deleted (c) + added (d) are drift, sorted"
        after_del = {"a.md": "1", "c.md": "3"}
        assert lr.harness_drift(before, after_del) == ["b.md"], \
            "a deleted surface file is drift too"

    def test_restore_reverts_modified_file_from_head(self, tmp_path):
        root = self._fake_root(tmp_path)
        p = root / "agents" / "kunglao-redteam.md"
        before = lr.harness_surface_hashes(root)
        p.write_text(p.read_text(encoding="utf-8") + "TAMPERED\n",
                     encoding="utf-8")
        drifted = lr.harness_drift(before, lr.harness_surface_hashes(root))
        assert drifted == ["agents/kunglao-redteam.md"]
        restored = lr.restore_harness(drifted, root=root)
        assert restored == drifted
        assert "TAMPERED" not in p.read_text(encoding="utf-8"), \
            "git checkout -- put HEAD bytes back"

    def test_restore_reverts_deleted_file_from_head(self, tmp_path):
        root = self._fake_root(tmp_path)
        p = root / "skills" / "kunglao-agent" / "SKILL.md"
        before = lr.harness_surface_hashes(root)
        p.unlink()
        drifted = lr.harness_drift(before, lr.harness_surface_hashes(root))
        assert drifted == ["skills/kunglao-agent/SKILL.md"]
        assert lr.restore_harness(drifted, root=root) == drifted
        assert p.is_file(), "deleted tracked file restored from HEAD"

    def test_restore_removes_untracked_addition(self, tmp_path):
        root = self._fake_root(tmp_path)
        before = lr.harness_surface_hashes(root)
        rogue = root / "agents" / "rogue-tool.md"
        rogue.write_text("rogue\n", encoding="utf-8")
        drifted = lr.harness_drift(before, lr.harness_surface_hashes(root))
        assert drifted == ["agents/rogue-tool.md"]
        assert lr.restore_harness(drifted, root=root) == drifted
        assert not rogue.exists(), \
            "session-created addition removed (not in HEAD to restore)"

    def test_escape_session_detected_reverted_marked(self, tmp_path,
                                                     monkeypatch):
        """THE incident face: a session writes OUTSIDE its workspace onto
        the harness surface — detected, reverted from HEAD, the session
        row is marked harness_contaminated, the loud event row lands, and
        the verdict is UNAFFECTED (grading already ran)."""
        root = self._fake_root(tmp_path)
        target = root / "agents" / "kunglao-redteam.md"
        monkeypatch.setenv(lr.ENV_HARNESS_ROOT, str(root))
        monkeypatch.setenv("K334_STUB_MODE", "escape")
        monkeypatch.setenv("K334_ESCAPE_TARGET", str(target))
        row = lr.run_loop_task(PY, tmp_path, budget_usd=1.0,
                               wall_cap_s=60.0,
                               session_cmd=_stub_session_cmd(tmp_path))
        assert "ESCAPE-JUNK" not in target.read_text(encoding="utf-8"), \
            "the escape write was reverted from HEAD"
        sess = row["loop"]["session"]
        assert sess["harness_contaminated"] is True
        assert sess["harness_drift_files"] == ["agents/kunglao-redteam.md"]
        assert row["verdict"] == "PASS", \
            "verdict unaffected: grading already ran"
        ev = json.loads((tmp_path / "harness-events.jsonl")
                        .read_text(encoding="utf-8").splitlines()[-1])
        assert ev["action"] == "harness_drift"
        assert ev["task"] == PY
        assert ev["drifted"] == ["agents/kunglao-redteam.md"]
        assert ev["restored"] == ["agents/kunglao-redteam.md"]

    def test_clean_session_leaves_no_contamination(self, tmp_path,
                                                   monkeypatch):
        root = self._fake_root(tmp_path)
        monkeypatch.setenv(lr.ENV_HARNESS_ROOT, str(root))
        monkeypatch.setenv("K334_STUB_MODE", "candidate")
        row = lr.run_loop_task(PY, tmp_path, budget_usd=1.0,
                               wall_cap_s=60.0,
                               session_cmd=_stub_session_cmd(tmp_path))
        assert row["loop"]["session"]["harness_contaminated"] is False
        assert row["loop"]["session"]["harness_drift_files"] == []
        assert not (tmp_path / "harness-events.jsonl").exists()

    def test_harness_drift_is_registered_emit_word(self):
        import event_taxonomy
        assert "harness_drift" in event_taxonomy.EMIT_ACTIONS

    def test_tier_summary_counts_contaminated_sessions(self, tmp_path,
                                                       monkeypatch):
        root = self._fake_root(tmp_path)
        monkeypatch.setenv(lr.ENV_HARNESS_ROOT, str(root))
        monkeypatch.setenv("K334_STUB_MODE", "escape")
        monkeypatch.setenv("K334_ESCAPE_TARGET",
                           str(root / "agents" / "kunglao-redteam.md"))
        rc, doc = lr.run_loop_tier([PY], tmp_path, budget_usd=1.0,
                                   wall_cap_s=60.0,
                                   session_cmd=_stub_session_cmd(tmp_path))
        assert rc == 0
        assert doc["summary"]["harness_contaminated"] == 1


# ------------------------------ (k) wall partition injection (exp5 M1)
# exp4 distillate (case-dispatch-budget-partition Rule 1): 6/7 orchestrated
# sessions soloed past 60–90% wall before dispatching — the orchestrator
# cannot partition a cap it was never told. The runner owns the cap, so
# the cap must COMMUNICATE into each session's prompt as a first-class
# WALL_BUDGET_PARTITION block. Contract communication, not a behavior rule.

class TestWallPartitionBlock:
    def test_block_is_first_class_and_derived_from_actual_cap(self):
        block = lr.wall_partition_block(3600.0)
        assert "WALL_BUDGET_PARTITION" in block
        assert "TOTAL WALL CAP: 3600s" in block
        assert "SOLO/DIRECT ATTEMPT HARD CAP: 1800s" in block, \
            "solo cap = 50% of wall (the card's ≤50%-rule)"
        assert "FINAL DELIVERABLE DUE BY 3300s" in block, \
            "deliverable due before the 300s checker/harvest reserve"
        # derived, not hardcoded: a different cap renders different numbers
        block2 = lr.wall_partition_block(7200.0)
        assert "TOTAL WALL CAP: 7200s" in block2
        assert "SOLO/DIRECT ATTEMPT HARD CAP: 3600s" in block2
        assert "FINAL DELIVERABLE DUE BY 6900s" in block2

    def test_loop_prompt_carries_partition_prominently(self):
        tdir = _task_dir(PY)
        task = ds.load_task(tdir)
        prompt = lr.build_loop_prompt(tdir, task,
                                      "runs/deliverables/candidate.py",
                                      wall_cap_s=3600.0)
        assert "WALL_BUDGET_PARTITION" in prompt
        # first-class = near the top, before the goal anchors
        assert prompt.index("WALL_BUDGET_PARTITION") \
            < prompt.index("GOAL (verbatim)")

    def test_loop_prompt_without_cap_stays_unchanged(self):
        """Backward-compatible face: no cap → no block (pure prompt
        builder; existing anchors/contract-only posture unchanged)."""
        tdir = _task_dir(PY)
        task = ds.load_task(tdir)
        prompt = lr.build_loop_prompt(tdir, task,
                                      "runs/deliverables/candidate.py")
        assert "WALL_BUDGET_PARTITION" not in prompt

    def test_cc_default_prompt_carries_partition_too(self, tmp_path):
        tdir = next(d for d in ds.iter_task_dirs(tier="release")
                    if d.name == "arm-kdf-l0")
        ws, prompt = lr.init_cc_default_workspace(tdir, tmp_path,
                                                  wall_cap_s=3600.0)
        assert "WALL_BUDGET_PARTITION" in prompt
        assert "WALL_BUDGET_PARTITION" in (ws / "TASK.md").read_text("utf-8"), \
            "the contract lands in TASK.md as well (the session's own copy)"
        assert "/kunglao-agent" not in prompt

    def test_e2e_session_receives_partition_in_prompt(self, tmp_path,
                                                      monkeypatch):
        """THE M1 pin: the prompt the session ACTUALLY received carries
        the partition block (stub records its argv)."""
        monkeypatch.setenv("K334_STUB_MODE", "candidate")
        row = lr.run_loop_task(
            PY, tmp_path, budget_usd=1.0, wall_cap_s=3600.0,
            session_cmd=_stub_session_cmd(tmp_path))
        ws = Path(row["loop"]["workspace"])
        argv = json.loads((ws / "session-argv.json").read_text("utf-8"))
        assert "WALL_BUDGET_PARTITION" in argv[-1]
        assert "TOTAL WALL CAP: 3600s" in argv[-1]

    def test_partition_adds_no_ground_truth(self):
        tdir = _task_dir(PY)
        task = ds.load_task(tdir)
        gt = json.loads((tdir / "ground_truth.json").read_text("utf-8"))
        prompt = lr.build_loop_prompt(tdir, task,
                                      "runs/deliverables/candidate.py",
                                      wall_cap_s=3600.0)
        for v in (gt.get("constants") or {}).values():
            s = v if isinstance(v, str) else str(v)
            assert s not in prompt


# ------------------------------ (l) gap-redo round (exp5 M2)
# exp3/exp4 diagnosis: mod-crypto-l1 delivered a candidate the checker
# failed 0/20 and NO redo round ran in-wall. M2: runner-driven, ONE
# gap-redo session on checker-FAIL with wall+budget remaining; the redo
# input is GAP-shape only (which faces failed, counts) — never the
# checker's derived answer; the redo's verdict replaces (checker-strict).

class TestGapRedo:
    # ---- pure decision function
    def test_fail_with_remaining_budget_and_wall_is_allowed(self):
        rec = {"wall_s": 2980.0,
               "session_cost": {"total_cost_usd": 8.0}}
        d = lr.gap_redo_decision("FAIL", rec, wall_cap_s=3600.0,
                                 budget_usd=15.0)
        assert d["allowed"] is True
        assert d["reason"] == "checker_fail_within_budget"

    def test_pass_verdict_never_redoes(self):
        rec = {"wall_s": 100.0, "session_cost": {"total_cost_usd": 1.0}}
        d = lr.gap_redo_decision("PASS", rec, wall_cap_s=3600.0,
                                 budget_usd=15.0)
        assert d["allowed"] is False
        assert d["reason"] == "not_checker_fail"

    def test_wall_exhausted_denies_redo(self):
        rec = {"wall_s": 3600.0, "session_cost": {"total_cost_usd": 2.0}}
        d = lr.gap_redo_decision("FAIL", rec, wall_cap_s=3600.0,
                                 budget_usd=15.0)
        assert d["allowed"] is False
        assert d["reason"] == "wall_exhausted"

    def test_budget_exhausted_denies_redo(self):
        rec = {"wall_s": 100.0,
               "session_cost": {"total_cost_usd": 14.9}}
        d = lr.gap_redo_decision("FAIL", rec, wall_cap_s=3600.0,
                                 budget_usd=15.0)
        assert d["allowed"] is False
        assert d["reason"] == "budget_exhausted"

    def test_missing_cost_report_reads_as_zero_spent(self):
        rec = {"wall_s": 100.0, "session_cost": None}
        d = lr.gap_redo_decision("FAIL", rec, wall_cap_s=3600.0,
                                 budget_usd=15.0)
        assert d["allowed"] is True, \
            "no cost report (stub seam) → assume nothing spent"

    # ---- gap extraction shape (GAP-shape only)
    def test_gap_block_is_shape_only_never_answers(self, tmp_path):
        """The CHECKER GAP block carries failure codes/counts and constant
        NAMES at most — never ground-truth values or published outputs."""
        tdir = _task_dir(PY)
        task = ds.load_task(tdir)
        res = {
            "verdict": "FAIL",
            "failures": [{"code": "PAIR_MISMATCH",
                          "detail": "pairs 0/16 match "
                                    "(threshold 16 at ratio 1.0)"}],
            "evidence": "",
        }
        block = lr.render_gap_block(lr.extract_checker_gap(res))
        assert "CHECKER GAP" in block
        assert "PAIR_MISMATCH" in block
        assert "0/16" in block
        gt = json.loads((tdir / "ground_truth.json").read_text("utf-8"))
        for v in (gt.get("constants") or {}).values():
            s = v if isinstance(v, str) else str(v)
            assert s not in block, "ground-truth constant value leaked"
        for pair in (gt.get("published_pairs") or []):
            out = pair.get("out")
            if out is not None:
                assert str(out) not in block, "published output leaked"

    # ---- e2e through run_loop_task (stub seam)
    def test_checker_fail_triggers_exactly_one_gap_redo(self, tmp_path,
                                                        monkeypatch):
        """checker-FAIL + budget remaining → exactly ONE redo session
        (same workspace), its verdict replaces the original, the redo
        prompt carries the GAP block, and the row is marked."""
        monkeypatch.setenv("K334_STUB_MODE", "candidate-bad")
        row = lr.run_loop_task(
            PY, tmp_path, budget_usd=15.0, wall_cap_s=3600.0,
            session_cmd=_stub_session_cmd(tmp_path))
        ws = Path(row["loop"]["workspace"])
        calls = [json.loads(l) for l in
                 (ws / "session-calls.jsonl").read_text("utf-8")
                 .splitlines() if l.strip()]
        assert len(calls) == 2, "original + exactly one gap-redo session"
        assert row["gap_redo"] is True
        loop = row["loop"]
        assert loop["gap_redo"]["ran"] is True
        assert loop["gap_redo"]["verdict_replaced"] is True
        assert loop["gap_redo"]["decision"]["allowed"] is True
        redo_prompt = calls[1]["argv"][-1]
        assert "GAP-REDO" in redo_prompt
        assert "CHECKER GAP" in redo_prompt
        assert "PAIR_MISMATCH" in redo_prompt
        assert "WALL_BUDGET_PARTITION" in redo_prompt, \
            "the redo gets the partition recomputed for its remaining cap"
        gt = json.loads((Path(__file__).resolve().parents[1]
                         / "eval/v1/tasks/smoke/py-derive-v1/ground_truth.json")
                        .read_text("utf-8"))
        for v in (gt.get("constants") or {}).values():
            s = v if isinstance(v, str) else str(v)
            assert s not in redo_prompt, "ground truth leaked into redo"
        # checker-strict: the stub writes a bad candidate again → FAIL stands
        assert row["verdict"] == "FAIL"
        assert loop["session"]["returncode"] == 0, "first session"
        assert loop["gap_redo"]["session"]["returncode"] == 0, "redo session"

    def test_budget_exhausted_suppresses_redo(self, tmp_path, monkeypatch):
        """FAIL verdict but session cost ≥ cap → NO redo session; the
        original FAIL stands and the suppression reason is recorded."""
        monkeypatch.setenv("K334_STUB_MODE", "budget-bad")
        row = lr.run_loop_task(
            PY, tmp_path, budget_usd=15.0, wall_cap_s=3600.0,
            session_cmd=_stub_session_cmd(tmp_path))
        ws = Path(row["loop"]["workspace"])
        calls = [json.loads(l) for l in
                 (ws / "session-calls.jsonl").read_text("utf-8")
                 .splitlines() if l.strip()]
        assert len(calls) == 1, "budget-exhausted: no redo session spawned"
        assert row["gap_redo"] is False
        assert row["verdict"] == "FAIL"
        assert row["loop"]["gap_redo"]["ran"] is False
        # #380 P3-4: stored ONCE — the decision carries the reason
        assert row["loop"]["gap_redo"]["decision"]["reason"] == \
            "budget_exhausted"
        assert row["loop"]["status"] == "exhausted"

    def test_tier_summary_counts_gap_redo(self, tmp_path, monkeypatch):
        monkeypatch.setenv("K334_STUB_MODE", "candidate-bad")
        rc, doc = lr.run_loop_tier(
            [PY], tmp_path, budget_usd=15.0, wall_cap_s=3600.0,
            session_cmd=_stub_session_cmd(tmp_path))
        assert rc == 0
        assert doc["summary"]["gap_redo"] == 1


# ------------------------------ (m) EXP-8 high-ROI injections
# Five contract/injection-level closures, each backed by measured evidence:
#   I1 deliverable schedule (post2: 5/5 deliverers pass, 7/7 non-deliverers
#      die; exp5 arm-kdf delivered AT budget death — 0/16 graded on a rush)
#   I2 layer checkpoints (exp4: 13/14 chain sessions scored 0/N despite
#      real peels — the layer_out/ convention was invisible)
#   I3 family self-check (mod-crypto-l1 delivered a 0/20 candidate an
#      in-session probe would have caught)
#   I4 factor settle (exp4: dispatch-tick face 0 on all 7 units — the
#      last value_m sample predated the 60-90%-wall dispatches)
#   I5 T1_DIRECT affirmative (CC-default 12/12 proves the direct path
#      exists; the demoted toolfirst advisory left no affirmative)

CHAIN_JS = "chain-l1-js-v1"
CHAIN_GO = "chain-l2-go-v1"
CRYPTO = "mod-crypto-l1"


def _tier_task_dir(tier: str, task_id: str) -> Path:
    d = ROOT / "eval" / "v1" / "tasks" / tier / task_id
    assert d.is_dir(), f"task dir not found: {d}"
    return d


class TestDeliverableScheduleBlock:
    """I1: the wall-partition block carries the deliverable schedule."""

    def test_block_carries_deliverable_schedule(self):
        block = lr.wall_partition_block(3600.0)
        assert "DELIVERABLE_SCHEDULE" in block
        assert "continuously improve" in block
        assert "CURRENT on-disk state is what gets graded" in block

    def test_schedule_is_derived_from_actual_cap(self):
        block = lr.wall_partition_block(3600.0)
        assert "draft the candidate on disk by 1800s" in block, \
            "the 50%-wall mark (solo cap) is the draft deadline"
        block2 = lr.wall_partition_block(7200.0)
        assert "draft the candidate on disk by 3600s" in block2

    def test_loop_prompt_carries_schedule(self):
        tdir = _task_dir(PY)
        task = ds.load_task(tdir)
        prompt = lr.build_loop_prompt(tdir, task,
                                      "runs/deliverables/candidate.py",
                                      wall_cap_s=3600.0)
        assert "DELIVERABLE_SCHEDULE" in prompt

    def test_cc_default_prompt_carries_schedule_too(self, tmp_path):
        tdir = next(d for d in ds.iter_task_dirs(tier="release")
                    if d.name == "arm-kdf-l0")
        _ws, prompt = lr.init_cc_default_workspace(tdir, tmp_path,
                                                   wall_cap_s=3600.0)
        assert "DELIVERABLE_SCHEDULE" in prompt


class TestLayerCheckpointsBlock:
    """I2: chain prompts name the grader's exact layer_out/ paths."""

    def test_js_unit_paths_exact(self):
        paths = lr.chain_layer_paths(_tier_task_dir("chain", CHAIN_JS))
        assert paths == ["layer_out/1-unpacked.js", "layer_out/2-config.json"]

    def test_go_unit_paths_exact(self):
        paths = lr.chain_layer_paths(_tier_task_dir("chain", CHAIN_GO))
        assert paths == ["layer_out/1-unpacked.json", "layer_out/2-config.json",
                         "layer_out/3-core.go"]

    def test_non_chain_unit_has_no_paths(self):
        assert lr.chain_layer_paths(_task_dir(PY)) == []
        assert lr.chain_layer_paths(_tier_task_dir("release", CRYPTO)) == []

    def test_block_lists_exact_paths(self):
        block = lr.layer_checkpoints_block(
            ["layer_out/1-unpacked.js", "layer_out/2-config.json"])
        assert "LAYER_CHECKPOINTS" in block
        assert "- layer_out/1-unpacked.js" in block
        assert "- layer_out/2-config.json" in block
        assert "a layer counts only if its file exists and verifies" in block

    def test_chain_prompt_carries_block(self):
        tdir = _tier_task_dir("chain", CHAIN_JS)
        task = ds.load_task(tdir)
        prompt = lr.build_loop_prompt(
            tdir, task, "runs/deliverables/candidate.js",
            wall_cap_s=3600.0,
            layer_paths=lr.chain_layer_paths(tdir))
        assert "LAYER_CHECKPOINTS" in prompt
        assert "layer_out/1-unpacked.js" in prompt
        assert "layer_out/2-config.json" in prompt

    def test_chain_prompt_leaks_no_ground_truth(self):
        """The block lifts PATH STRINGS only — no digests, no probe
        payloads, no expected outputs."""
        tdir = _tier_task_dir("chain", CHAIN_JS)
        task = ds.load_task(tdir)
        prompt = lr.build_loop_prompt(
            tdir, task, "runs/deliverables/candidate.js",
            wall_cap_s=3600.0,
            layer_paths=lr.chain_layer_paths(tdir))
        gt = json.loads((tdir / "ground_truth.json").read_text("utf-8"))
        for layer in gt["chain"]["layers"]:
            for op in layer["ops"]:
                assert op.get("sha256") not in prompt, "digest leaked"
        for p in gt["chain"]["probes"]:
            assert str(p.get("payload")) not in prompt, "payload leaked"
            assert str(p.get("out")) not in prompt, "expected output leaked"

    def test_non_chain_prompt_has_no_layer_block(self):
        tdir = _task_dir(PY)
        task = ds.load_task(tdir)
        prompt = lr.build_loop_prompt(tdir, task,
                                      "runs/deliverables/candidate.py",
                                      wall_cap_s=3600.0, layer_paths=[])
        assert "LAYER_CHECKPOINTS" not in prompt

    def test_redo_prompt_carries_layer_block(self):
        tdir = _tier_task_dir("chain", CHAIN_GO)
        task = ds.load_task(tdir)
        prompt = lr.build_redo_prompt(
            tdir, task, "runs/deliverables/candidate.go", "CHECKER GAP: x",
            wall_cap_s=1800.0, budget_usd=5.0,
            layer_paths=lr.chain_layer_paths(tdir))
        assert "layer_out/3-core.go" in prompt


class TestFamilySelfCheckBlock:
    """I3: registered families get their probe pattern injected."""

    def test_map_has_exactly_three_entries(self):
        # #380 P3-5: the pin moved to the general mechanism — the map is
        # derived from the template headers (non-growth = the templates
        # dir's content), not a hard special-case map in code.
        assert lr.FAMILY_PROBE_SHAPES == \
            lr.derive_family_probe_shapes(lr.SELFCHECK_TEMPLATE_DIR)
        assert lr.FAMILY_PROBE_SHAPES == {
            "mod-crypto-native": "crypto",
            "arm-native-kdf": "kdf",
            "req-sign": "sign",
        }

    def test_crypto_block_is_pair_match(self):
        block = lr.self_check_block("mod-crypto-native")
        assert block.startswith("SELF_CHECK:")
        assert "PAIR-MATCH PROBE" in block
        assert "EVERY pair" in block

    def test_kdf_block_is_static_constant(self):
        block = lr.self_check_block("arm-native-kdf")
        assert "STATIC-CONSTANT PROBE" in block

    def test_sign_block_is_sign_verify(self):
        block = lr.self_check_block("req-sign")
        assert "SIGN-VERIFY PROBE" in block

    def test_unregistered_family_gets_no_block(self):
        assert lr.self_check_block("py-derive") == ""
        assert lr.self_check_block(None) == ""

    def test_missing_template_degrades_to_directive(self, monkeypatch,
                                                    tmp_path):
        monkeypatch.setattr(lr, "SELFCHECK_TEMPLATE_DIR", tmp_path)
        block = lr.self_check_block("mod-crypto-native")
        assert block.startswith("SELF_CHECK:")
        assert "PAIR-MATCH" not in block, "snippet absent, directive stays"

    def test_release_unit_prompt_carries_self_check(self):
        tdir = _tier_task_dir("release", CRYPTO)
        task = ds.load_task(tdir)
        prompt = lr.build_loop_prompt(
            tdir, task, "runs/deliverables/candidate.py", wall_cap_s=3600.0,
            probe_block=lr.self_check_block(task["family"]))
        assert "SELF_CHECK:" in prompt
        assert "PAIR-MATCH PROBE" in prompt

    def test_templates_exist_for_every_registered_shape(self):
        for shape in set(lr.FAMILY_PROBE_SHAPES.values()):
            p = lr.SELFCHECK_TEMPLATE_DIR / f"probe-{shape}.md"
            assert p.is_file(), f"missing probe template: {p}"


class TestSettleFactorSample:
    """I4: one final factor-vector sample — late dispatches get counted."""

    @staticmethod
    def _late_dispatch_ws(tmp_path: Path) -> Path:
        """Synthetic late-dispatch ledger: the history's last point has
        cursor 0 (sampled at init), the dispatch signals landed after."""
        ws = tmp_path / "ws-late"
        (ws / "runs").mkdir(parents=True)
        (ws / "runs" / "mission_ledger.yaml").write_text(
            "mission:\n"
            "  pqs: []\n"
            "  beta: 0.3\n"
            "  history:\n"
            "  - ts: 2026-09-26T00:00:00Z\n"
            "    v_m: 0.0\n"
            "    round: 1\n"
            "    events: {dispatch: 0, verify: 0, confirmed_with_diff: 0,"
            " toss: 0}\n"
            "    signals_rows: 0\n", encoding="utf-8")
        rows = [
            {"ts": "2026-09-26T00:10:00Z", "kind": "dispatch",
             "claim": "C-101"},
            {"ts": "2026-09-26T00:20:00Z", "kind": "dispatch",
             "claim": "C-102"},
        ]
        (ws / "runs" / "signals.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return ws

    def test_synthetic_late_dispatch_is_counted(self, tmp_path):
        ws = self._late_dispatch_ws(tmp_path)
        assert lr.settle_factor_sample(ws) is True
        led = yaml.safe_load(
            (ws / "runs" / "mission_ledger.yaml").read_text("utf-8"))
        hist = led["mission"]["history"]
        assert len(hist) == 2, "one settle sample appended"
        assert hist[-1]["events"]["dispatch"] == 2, \
            "the two post-sample dispatches land in the tick face"
        assert hist[-1]["signals_rows"] == 2
        assert lr.harvest(ws)["dispatch_count"] == 2

    def test_workspace_without_ledger_is_false(self, tmp_path):
        ws = tmp_path / "ws-bare"
        (ws / "runs").mkdir(parents=True)
        assert lr.settle_factor_sample(ws) is False

    def test_e2e_late_dispatch_counted(self, tmp_path, monkeypatch):
        """THE I4 pin: a session whose dispatch signals land after the
        ledger's last sample leaves the run row with the dispatches
        COUNTED (exp4 read 0 on all 7 units)."""
        monkeypatch.setenv("K334_STUB_MODE", "late-dispatch")
        row = lr.run_loop_task(
            PY, tmp_path, budget_usd=1.0, wall_cap_s=60.0,
            session_cmd=_stub_session_cmd(tmp_path))
        m = row["loop"]["metrics"]
        assert m["dispatch_count"] == 6, \
            "stub vectors (2 + 3) + the settle sample (1 late dispatch)"
        led = yaml.safe_load(
            (Path(row["loop"]["workspace"]) / "runs" / "mission_ledger.yaml")
            .read_text("utf-8"))
        assert led["mission"]["history"][-1]["events"]["dispatch"] == 1
        assert led["mission"]["history"][-1]["events"]["toss"] == 1, \
            "the late dispatch has no later deliver — derived toss"


class TestT1DirectLine:
    """I5: the T-1 affirmative rides the loop prompts; the control arm
    stays neutral."""

    def test_loop_prompt_carries_t1_direct(self):
        tdir = _task_dir(PY)
        task = ds.load_task(tdir)
        prompt = lr.build_loop_prompt(tdir, task,
                                      "runs/deliverables/candidate.py")
        assert "T1_DIRECT:" in prompt
        assert "tool-catalog:" in prompt

    def test_redo_prompt_carries_t1_direct(self):
        tdir = _task_dir(PY)
        task = ds.load_task(tdir)
        prompt = lr.build_redo_prompt(tdir, task,
                                      "runs/deliverables/candidate.py",
                                      "CHECKER GAP: x",
                                      wall_cap_s=1800.0, budget_usd=5.0)
        assert "T1_DIRECT:" in prompt

    def test_cc_default_prompt_stays_neutral(self, tmp_path):
        tdir = next(d for d in ds.iter_task_dirs(tier="release")
                    if d.name == "arm-kdf-l0")
        _ws, prompt = lr.init_cc_default_workspace(tdir, tmp_path,
                                                   wall_cap_s=3600.0)
        assert "T1_DIRECT" not in prompt
        assert "LAYER_CHECKPOINTS" not in prompt
        assert "SELF_CHECK" not in prompt


# ------------------------------ (n) #380 Package 3 — runner quality pack
# Nine audit findings, fixed under the same discipline: extract the shared
# machinery, kill the write-only state, derive instead of special-case,
# and document every posture choice at the site it lives.

PRE_REFACTOR_PROMPT_SHAS = {
    # captured on ar/exp8-highroi (20570a1a) BEFORE the render-helper
    # extraction — the extraction must reproduce these byte-for-byte.
    "loop_py_wall3600":
        "b79f17ab896dfb261d17e46a6fc937dd207dc96ae5babb071f41f236aadccd0d",
    "loop_py_nowall":
        "e7e888a724ce06d6a1c259dbab630366efdef8ef330b3fd44fedf9dd78df91b3",
    "loop_chain_js_layers":
        "bc3c78146372cac91bad4753b8f5484ec5ea0e44b17ccffd9450b4505d3cc147",
    "loop_crypto_probe":
        "91fde28028b7bcd1ae056d92330105909391ca9ba40662886a793674d9782612",
    "loop_py_everything":
        "6690bbc9de77f68db69298e261cbb3598ef02e45210522c853a3e96b1d15216f",
    "loop_py_no_t1":
        "21c7a84fc0cb07232a24d3bcaefdadf8bfbe5b476032d4f75a746a05521c4a7b",
    "redo_py_gap":
        "f8c593a29aad7833fdd94749d13e7de9c89267a9393b7be5cd2a9444a223b681",
    "redo_chain_go_layers":
        "89b87271d8e064789d2533caed581a93ebb55eaa034f5e2411009b8a4ea77984",
    "redo_crypto_all":
        "88bd7e8c1593f7b32049f8da43660e3e5db48b84fc16972108b223922fe90811",
}


class TestPromptRenderHelperByteIdentity:
    """#380 P3-1: build_loop_prompt / build_redo_prompt share ONE
    renderer; the extraction is byte-identical to the pre-refactor
    prompts (sha256 of the full prompt text, golden literals captured on
    the pre-refactor commit)."""

    def _cases(self):
        tdir = _task_dir(PY)
        task = ds.load_task(tdir)
        drel = "runs/deliverables/candidate.py"
        cj = ROOT / "eval/v1/tasks/chain/chain-l1-js-v1"
        cg = ROOT / "eval/v1/tasks/chain/chain-l2-go-v1"
        cr = ROOT / "eval/v1/tasks/release/mod-crypto-l1"
        return {
            "loop_py_wall3600": lr.build_loop_prompt(
                tdir, task, drel, wall_cap_s=3600.0),
            "loop_py_nowall": lr.build_loop_prompt(tdir, task, drel),
            "loop_chain_js_layers": lr.build_loop_prompt(
                cj, ds.load_task(cj), "runs/deliverables/candidate.js",
                wall_cap_s=3600.0, layer_paths=lr.chain_layer_paths(cj)),
            "loop_crypto_probe": lr.build_loop_prompt(
                cr, ds.load_task(cr), "runs/deliverables/candidate.py",
                wall_cap_s=3600.0,
                probe_block=lr.self_check_block(ds.load_task(cr)["family"])),
            "loop_py_everything": lr.build_loop_prompt(
                tdir, task, drel, wall_cap_s=1234.0,
                layer_paths=["layer_out/a.txt"], probe_block="SELF_CHECK: x",
                include_t1_direct=True),
            "loop_py_no_t1": lr.build_loop_prompt(
                tdir, task, drel, wall_cap_s=3600.0,
                include_t1_direct=False),
            "redo_py_gap": lr.build_redo_prompt(
                tdir, task, drel, "CHECKER GAP: x",
                wall_cap_s=1800.0, budget_usd=5.0),
            "redo_chain_go_layers": lr.build_redo_prompt(
                cg, ds.load_task(cg), "runs/deliverables/candidate.go",
                "CHECKER GAP (from the mechanical final check of the "
                "previously delivered candidate — gap shape only):",
                wall_cap_s=900.0, budget_usd=1.5,
                layer_paths=lr.chain_layer_paths(cg), probe_block=""),
            "redo_crypto_all": lr.build_redo_prompt(
                cr, ds.load_task(cr), "runs/deliverables/candidate.py",
                "GAPBLOCK", wall_cap_s=777.0, budget_usd=0.9,
                layer_paths=["layer_out/x"],
                probe_block=lr.self_check_block(ds.load_task(cr)["family"])),
        }

    def test_prompts_byte_identical_to_pre_refactor(self):
        import hashlib
        for name, want in PRE_REFACTOR_PROMPT_SHAS.items():
            got = hashlib.sha256(
                self._cases()[name].encode("utf-8")).hexdigest()
            assert got == want, f"{name} drifted off the pre-refactor bytes"

    def test_render_helper_exists_and_both_builders_use_it(self):
        assert hasattr(lr, "_render_task_prompt")
        import inspect
        for fn in (lr.build_loop_prompt, lr.build_redo_prompt):
            assert "_render_task_prompt" in inspect.getsource(fn), \
                f"{fn.__name__} must route through the shared renderer"


class TestRunSessionGuarded:
    """#380 P3-2: ONE guarded spawn helper for BOTH faces; the drift
    handling (hash -> launch -> hash -> restore + loud event row) can no
    longer diverge, and redo contamination feeds the summary counter."""

    def test_helper_shape(self, tmp_path, monkeypatch):
        root = TestHarnessEscapeGate()._fake_root(tmp_path)
        monkeypatch.setenv(lr.ENV_HARNESS_ROOT, str(root))
        monkeypatch.setenv("K334_STUB_MODE", "escape")
        monkeypatch.setenv("K334_ESCAPE_TARGET",
                           str(root / "agents" / "kunglao-redteam.md"))
        ws = lr.init_workspace(_task_dir(PY), tmp_path)
        rec, drifted, restored = lr.run_session_guarded(
            ws, "PROMPT", tmp_path, "t", budget_usd=1.0, wall_cap_s=60.0,
            session_cmd=_stub_session_cmd(tmp_path))
        assert rec["returncode"] == 0
        assert drifted == ["agents/kunglao-redteam.md"]
        assert restored == drifted, "the helper restores what it finds"
        ev = json.loads((tmp_path / "harness-events.jsonl")
                        .read_text(encoding="utf-8").splitlines()[-1])
        assert ev["action"] == lr.HARNESS_DRIFT_ACTION

    def test_both_spawn_sites_route_through_one_helper(self, tmp_path,
                                                       monkeypatch):
        calls: list[str] = []
        real = lr.run_session_guarded

        def spy(ws, prompt, out, task_name, **kw):
            calls.append(prompt[:20])
            return real(ws, prompt, out, task_name, **kw)

        monkeypatch.setattr(lr, "run_session_guarded", spy)
        monkeypatch.setenv("K334_STUB_MODE", "candidate-bad")
        row = lr.run_loop_task(
            PY, tmp_path, budget_usd=15.0, wall_cap_s=3600.0,
            session_cmd=_stub_session_cmd(tmp_path))
        assert len(calls) == 2, \
            "main AND gap-redo spawns both go through the guarded helper"
        assert row["loop"]["gap_redo"]["ran"] is True

    def test_redo_contamination_feeds_summary_counter(self, tmp_path,
                                                      monkeypatch):
        """THE divergence pin: a redo session that escapes marks the row's
        gap_redo.session AND the tier summary counts it (pre-fix: the
        summary only saw the main session's face)."""
        root = TestHarnessEscapeGate()._fake_root(tmp_path)
        monkeypatch.setenv(lr.ENV_HARNESS_ROOT, str(root))
        monkeypatch.setenv("K334_STUB_MODE", "candidate-bad-escape")
        monkeypatch.setenv("K334_ESCAPE_TARGET",
                           str(root / "agents" / "kunglao-redteam.md"))
        rc, doc = lr.run_loop_tier(
            [PY], tmp_path, budget_usd=15.0, wall_cap_s=3600.0,
            session_cmd=_stub_session_cmd(tmp_path))
        assert rc == 0
        row = doc["rows"][0]
        assert row["loop"]["session"]["harness_contaminated"] is False, \
            "the MAIN session stayed clean"
        assert row["loop"]["gap_redo"]["session"][
            "harness_contaminated"] is True
        assert doc["summary"]["harness_contaminated"] == 1, \
            "redo contamination is counted, not silently dropped"


class TestProbeShapeDerivation:
    """#380 P3-5: the family->probe-shape map is DERIVED from the
    template headers (a per-family template convention), not a hard
    special-case map keyed on family strings."""

    def test_derived_map_matches_the_three_registered_families(self):
        assert lr.FAMILY_PROBE_SHAPES == {
            "mod-crypto-native": "crypto",
            "arm-native-kdf": "kdf",
            "req-sign": "sign",
        }

    def test_new_family_template_grows_map_without_code_change(self,
                                                               tmp_path):
        d = tmp_path / "selfcheck"
        d.mkdir()
        (d / "probe-nonce.md").write_text(
            "<!-- probe shape: nonce (pair-match) - injected for family "
            "new-family-x -->\nbody\n", encoding="utf-8")
        derived = lr.derive_family_probe_shapes(d)
        assert derived == {"new-family-x": "nonce"}

    def test_headerless_template_is_not_registered(self, tmp_path):
        d = tmp_path / "selfcheck"
        d.mkdir()
        (d / "probe-lonely.md").write_text("no header\n", encoding="utf-8")
        assert lr.derive_family_probe_shapes(d) == {}

    def test_unreadable_template_dir_yields_empty_map(self, tmp_path):
        assert lr.derive_family_probe_shapes(tmp_path / "absent") == {}


class TestGapRedoReasonStoredOnce:
    """#380 P3-4: the row-level gap_redo['reason'] duplicated
    gap_redo['decision']['reason'] — the decision is the single store."""

    def test_gap_redo_row_has_no_top_level_reason(self, tmp_path,
                                                  monkeypatch):
        monkeypatch.setenv("K334_STUB_MODE", "budget-bad")
        row = lr.run_loop_task(
            PY, tmp_path, budget_usd=15.0, wall_cap_s=3600.0,
            session_cmd=_stub_session_cmd(tmp_path))
        gr = row["loop"]["gap_redo"]
        assert "reason" not in gr, "the duplicate store is gone"
        assert gr["decision"]["reason"] == "budget_exhausted"


class TestPostCapStatusCaveat:
    """#380 P3-8: the cost>=budget heuristic IS the consumption of the
    CLI's structured stop face (rc=1 + the json cost report); the
    crash-at/over-cap mislabel and its pass@k accounting caveat must be
    documented at the site (no structured discriminator exists to
    consume)."""

    def test_docstring_documents_heuristic_and_passk_caveat(self):
        doc = lr._post_cap_status.__doc__ or ""
        assert "heuristic" in doc.lower()
        assert "pass@k" in doc

    def test_crash_at_cap_is_still_heuristic_exhausted(self):
        rec = {"returncode": 1, "timed_out": False,
               "session_cost": {"total_cost_usd": 2.0}}
        assert lr._post_cap_status(rec, 1.0) == "exhausted"
        assert lr._post_cap_status(
            {"returncode": 1, "timed_out": False,
             "session_cost": {"total_cost_usd": 0.5}}, 1.0) == "session_error"


class TestFailOpenWarnIdiom:
    """#380 P3-9: fail-open telemetry degradations leave ONE rate-limited
    stderr trace (the _boot.warn idiom), not unbounded raw prints."""

    @staticmethod
    def _lines(capsys) -> list[str]:
        return capsys.readouterr().err.splitlines()

    def test_settle_degradation_warns_rate_limited(self, tmp_path, capsys,
                                                   monkeypatch):
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "runs" / "mission_ledger.yaml").write_text(
            "mission: {pqs: [], history: []}\n", encoding="utf-8")
        boom = OSError("ledger exploded")
        monkeypatch.setattr(
            "mission_ledger.settle",
            lambda *_a, **_k: (_ for _ in ()).throw(boom))
        for _ in range(3):
            assert lr.settle_factor_sample(ws) is False
        lines = self._lines(capsys)
        warns = [ln for ln in lines if "factor_settle" in ln
                 and "WARN" in ln]
        assert len(warns) == 1, \
            f"rate-limited to one trace per reason, got {len(warns)}"

    def test_oracle_face_unreadable_warns_rate_limited(self, tmp_path,
                                                       capsys):
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "runs" / "oracle-status.json").write_text("{broken",
                                                        encoding="utf-8")
        for _ in range(3):
            lr._oracle_face(ws)
        warns = [ln for ln in self._lines(capsys)
                 if "oracle_face" in ln and "WARN" in ln]
        assert len(warns) == 1

    def test_proven_face_unreadable_warns_rate_limited(self, tmp_path,
                                                       capsys):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "claim-register.yaml").write_text("\t: : [broken",
                                                encoding="utf-8")
        for _ in range(3):
            lr._proven_face(ws)
        warns = [ln for ln in self._lines(capsys)
                 if "claim_register" in ln and "WARN" in ln]
        assert len(warns) == 1
