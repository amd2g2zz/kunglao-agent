# -*- coding: utf-8 -*-
"""tests/test_e2e_runner.py — T0.4 gold-standard E2E acceptance harness.

Unit pins (RED-first) for scripts/e2e/ (the runbook productization):
  - adjudication table: expected rc sets per checkpoint step; C5 analysis
    stop rcs (5/6/7) classify BLOCKED, everything else out-of-set is FAIL;
  - resolve-answer synthesis: task.yaml anchors used VERBATIM, lane/type
    re-supplied (rehearsal finding #1), unknown decision ids surfaced;
  - contamination guard: ONLY the task.yaml-declared analysis material
    (workspace_scaffold.files) enters the workspace — answer sources
    (reference.py) never do; ground_truth.json / checker.py never
    do (rehearsal finding kin);
  - evidence schema + resume: per-checkpoint JSON evidence anchors resume;
    PASS steps are skipped, non-PASS steps re-run;
  - budget accounting: exhausted budget -> exit 4 PARTIAL, never silent;
  - ONE dry-llm integration test: full C1->C7+oracle pipeline against a
    stub repo fixture with every subprocess scripted at the CommandRunner
    boundary (the real kunglao scripts are never executed here).

The runbook (.claude/e2e-runbook-source.md) is the spec; deviations are
productization only (paths via config, scripted faces at seams).
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from e2e import checkpoints, evidence, llm_faces, model  # noqa: E402


# ---------------------------------------------------------------------------
# fixtures: a tiny stub repo (task unit + fake scripts) — no real kunglao
# scripts are executed anywhere in this file.
# ---------------------------------------------------------------------------

ANCHORS = {
    "goal_verbatim": "Recover the three parameters and re-implement derive.",
    "success_criterion": "A derive() re-implementation that reproduces every probe.",
    "verification_method": "reproduction",
}

TASK_YAML = """schema: kunglao-eval-task/1
task_id: py-derive-v1
tier: smoke
family: py-derive
anchors:
  goal_verbatim: Recover the three parameters and re-implement derive.
  success_criterion: A derive() re-implementation that reproduces every probe.
  verification_method: reproduction
workspace_scaffold:
  files:
  - target/derive.py
"""

DERIVE_PY = "def derive(data: bytes) -> int:\n    return 42\n"

GROUND_TRUTH = '{"offset": 0, "mul": 13, "fold": 7}\n'

# --- a synthetic NATIVE-family unit (the rust-so-crack-v1 shape,
# family-agnostic): the task declares a binary analysis material plus the
# checker's answer source. The .so must stage; reference.py must not.
NATIVE_TASK_YAML = """schema: kunglao-eval-task/1
task_id: arm-kdf-l0
tier: release
family: arm-native-kdf
anchors:
  goal_verbatim: Recover the mutated constants and re-implement kdf_derive.
  success_criterion: Byte-exact reproduction on every probe.
  verification_method: reproduction
workspace_scaffold:
  files:
  - target/libkdf.so
  - reference.py
checker:
  entrypoint: checker.py
  self_check_candidate: reference.py
"""
ELF_SO = b"\x7fELF\x02\x01\x01native-kdf-material-bytes"
REFERENCE_PY = "def kdf_derive(data: bytes) -> str:\n    return 'answer'\n"


@pytest.fixture()
def native_stub_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    task = repo / "eval/v1/tasks/release/arm-kdf-l0"
    (task / "target").mkdir(parents=True)
    (task / "target/libkdf.so").write_bytes(ELF_SO)
    (task / "reference.py").write_text(REFERENCE_PY, encoding="utf-8")
    (task / "task.yaml").write_text(NATIVE_TASK_YAML, encoding="utf-8")
    return repo


@pytest.fixture()
def nested_stub_repo(tmp_path: Path) -> Path:
    """Declared material with a nested relative path (no answer files)."""
    repo = tmp_path / "repo"
    task = repo / "eval/v1/tasks/release/synth-nested"
    (task / "target/deep").mkdir(parents=True)
    (task / "target/deep/nested.so").write_bytes(ELF_SO, )
    (task / "task.yaml").write_text(
        NATIVE_TASK_YAML.replace("arm-kdf-l0", "synth-nested").replace(
            "  - target/libkdf.so\n  - reference.py\n",
            "  - target/deep/nested.so\n"),
        encoding="utf-8")
    return repo


@pytest.fixture()
def stub_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    task = repo / "eval/v1/tasks/smoke/py-derive-v1"
    (task / "target").mkdir(parents=True)
    (task / "target/derive.py").write_text(DERIVE_PY, encoding="utf-8")
    (task / "task.yaml").write_text(TASK_YAML, encoding="utf-8")
    # contamination surface: these must NEVER enter the workspace
    (task / "checker.py").write_text("# checker\n", encoding="utf-8")
    (task / "ground_truth.json").write_text(GROUND_TRUTH, encoding="utf-8")
    (repo / "scripts").mkdir()
    return repo


# ---------------------------------------------------------------------------
# scripted CommandRunner (the subprocess boundary seam)
# ---------------------------------------------------------------------------

class ScriptedRunner(llm_faces.CommandRunner):
    """Matches argv patterns to scripted (rc, stdout) outcomes.

    Inherits the REAL command builders (py_cmd/console_cmd — the runbook
    CANON uv forms); only run() is scripted. Static rules via
    .on(needles..., rc=, stdout=) fire any number of times; sequenced
    rules via .seq(needles..., outcomes=[...]) fire once each, in order
    (for stateful decisions like DISPATCH then CONVERGED). Unmatched
    commands fail the test loudly — no silent defaults.
    """

    def __init__(self) -> None:
        super().__init__(Path("."))
        self.rules: list[tuple[tuple[str, ...], int, str]] = []
        self.queues: list[tuple[tuple[str, ...], list[tuple[int, str]]]] = []
        self.calls: list[str] = []

    def on(self, *needles: str, rc: int = 0, stdout: str = "",
           stderr: str = "") -> None:
        self.rules.append((needles, rc, stdout, stderr))

    def seq(self, *needles: str, outcomes: list[tuple[int, str]]) -> None:
        self.queues.append((needles, list(outcomes)))

    def run(self, cmd: list[str], cwd: Path | None = None,
            timeout: int | None = None) -> model.CmdOutcome:
        argv = [str(c) for c in cmd]
        self.calls.append(" ".join(argv))
        for needles, queue in self.queues:
            if all(n in " ".join(argv) for n in needles) and queue:
                item = queue.pop(0)
                rc, stdout = item[0], item[1]
                stderr = item[2] if len(item) > 2 else ""
                return model.CmdOutcome(rc=rc, stdout=stdout,
                                        stderr=stderr)
        for needles, rc, stdout, stderr in self.rules:
            if all(n in " ".join(argv) for n in needles):
                return model.CmdOutcome(rc=rc, stdout=stdout,
                                        stderr=stderr)
        raise AssertionError(f"unscripted command: {argv}")


@dataclass
class FakeClock:
    now: float = 1000.0
    sleeps: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


# ---------------------------------------------------------------------------
# adjudication table
# ---------------------------------------------------------------------------

class TestAdjudicationTable:
    REQUIRED_STEPS = (
        "C1-init-pending", "C1-init-resolved", "C2-hooks", "C3-heartbeat",
        "C4-entry", "C5-analysis", "C5-second-tick", "C6-pre",
        "C6-goal-op", "C6-env-check", "C6-dispatch", "C7-convergence",
        "C7-completion", "ORACLE",
    )

    def test_expected_rc_table_covers_every_runbook_step(self):
        for step in self.REQUIRED_STEPS:
            assert step in model.EXPECTED_RC, f"missing step {step}"

    def test_runbook_exit_contracts_pinned(self):
        assert model.EXPECTED_RC["C1-init-pending"] == frozenset({8})
        assert model.EXPECTED_RC["C1-init-resolved"] == frozenset({0})
        assert model.EXPECTED_RC["C2-hooks"] == frozenset({0})
        assert model.EXPECTED_RC["C5-analysis"] == frozenset({0})
        assert model.EXPECTED_RC["C7-convergence"] == frozenset({0})
        assert model.EXPECTED_RC["ORACLE"] == frozenset({0})

    def test_adjudicate_pass_on_expected_fail_on_deviation(self):
        assert model.adjudicate("C2-hooks", 0) == "PASS"
        assert model.adjudicate("C2-hooks", 1) == "FAIL"
        assert model.adjudicate("C1-init-pending", 8) == "PASS"
        assert model.adjudicate("C1-init-pending", 0) == "FAIL"

    def test_analysis_stop_rcs_classify_blocked_not_fail(self):
        assert model.adjudicate("C5-analysis", 5) == "BLOCKED"
        assert model.adjudicate("C5-analysis", 6) == "BLOCKED"
        assert model.adjudicate("C5-analysis", 7) == "BLOCKED"
        assert model.classify_analysis_rc(5) == "stale-workspace"
        assert model.classify_analysis_rc(6) == "heartbeat-verify-failed"
        assert model.classify_analysis_rc(7) == "intake-answers-missing"
        assert model.classify_analysis_rc(0) is None
        assert model.adjudicate("C5-analysis", 9) == "FAIL"

    def test_init_hard_toolchain_fail_is_blocked(self):
        # runbook C1: exit-4 HARD toolchain fail -> STOP (BLOCKED), not FAIL
        assert model.adjudicate("C1-init-pending", 4) == "BLOCKED"
        assert model.classify_init_stop_rc(4) == "toolchain-hard-fail"

    def test_unknown_step_rejected_loudly(self):
        with pytest.raises(KeyError):
            model.adjudicate("C9-not-in-runbook", 0)

    def test_exit_code_constants_match_spec(self):
        assert model.EXIT_OK == 0
        assert model.EXIT_CHECKPOINT_FAIL == 2
        assert model.EXIT_BLOCKED == 3
        assert model.EXIT_BUDGET_PARTIAL == 4

    def test_default_budget_is_runbook_four_hours(self):
        assert model.DEFAULT_BUDGET_SECONDS == 14400
        # honest tick wait: the runbook's real 5m, exactly once
        assert model.TICK_WAIT_SECONDS_DEFAULT == 300


# ---------------------------------------------------------------------------
# resolve-answer synthesis (C1)
# ---------------------------------------------------------------------------

class TestResolveSynthesis:
    def test_anchor_decision_ids_answered_verbatim(self):
        pending = ["goal_verbatim", "success_criterion", "verification_method"]
        answers, unmapped = model.synthesize_answers(
            pending, ANCHORS, lane="algorithm", type_="linux")
        assert unmapped == []
        assert answers["goal_verbatim"] == ANCHORS["goal_verbatim"]
        assert answers["success_criterion"] == ANCHORS["success_criterion"]
        assert answers["verification_method"] == "reproduction"

    def test_lane_and_type_decisions_resupplied(self):
        pending = ["type", "goal_verbatim"]
        answers, unmapped = model.synthesize_answers(
            pending, ANCHORS, lane="algorithm", type_="linux")
        assert answers["type"] == "linux"
        assert unmapped == []

    def test_unknown_decision_ids_surfaced_never_guessed(self):
        pending = ["goal_verbatim", "mystery-knob"]
        answers, unmapped = model.synthesize_answers(
            pending, ANCHORS, lane="algorithm", type_="linux")
        assert "mystery-knob" in unmapped
        assert "mystery-knob" not in answers

    def test_answers_file_is_flat_json_object(self):
        pending = ["goal_verbatim"]
        answers, _ = model.synthesize_answers(
            pending, ANCHORS, lane="algorithm", type_="linux")
        doc = json.loads(json.dumps(answers))
        assert isinstance(doc, dict)
        assert set(doc) >= {"goal_verbatim"}

    def test_load_anchors_reads_task_yaml_verbatim(self, stub_repo):
        task_yaml = (stub_repo / "eval/v1/tasks/smoke/py-derive-v1/task.yaml")
        anchors = model.load_anchors(task_yaml)
        assert anchors == ANCHORS

    def test_load_anchors_missing_anchor_fails_loudly(self, tmp_path):
        bad = tmp_path / "task.yaml"
        bad.write_text("schema: kunglao-eval-task/1\ntask_id: x\n", encoding="utf-8")
        with pytest.raises(model.AnchorError):
            model.load_anchors(bad)


# ---------------------------------------------------------------------------
# contamination guard + workspace staging
# ---------------------------------------------------------------------------

class TestContaminationGuard:
    def test_staging_copies_only_target_derive(self, stub_repo, tmp_path):
        ws = tmp_path / "ws"
        model.stage_workspace(
            stub_repo / "eval/v1/tasks/smoke/py-derive-v1", ws)
        assert (ws / "target/derive.py").read_text(encoding="utf-8") == DERIVE_PY
        assert not (ws / "checker.py").exists()
        assert not (ws / "ground_truth.json").exists()
        assert not (ws / "target/ground_truth.json").exists()

    def test_guard_flags_planted_ground_truth_and_checker(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "target/derive.py").parent.mkdir(parents=True)
        (ws / "target/derive.py").write_text(DERIVE_PY, encoding="utf-8")
        assert model.check_contamination(ws) == []
        (ws / "eval/ground_truth.json").parent.mkdir(parents=True)
        (ws / "eval/ground_truth.json").write_text("{}", encoding="utf-8")
        nested = ws / "a/checker.py"
        nested.mkdir(parents=True)
        (nested / "x.txt").write_text("x", encoding="utf-8")
        violations = model.check_contamination(ws)
        assert any("ground_truth.json" in v for v in violations)
        assert any("checker.py" in v for v in violations)

    def test_checker_resolved_from_repo_tree_never_ws(self, stub_repo, tmp_path):
        ws = tmp_path / "ws"
        model.stage_workspace(
            stub_repo / "eval/v1/tasks/smoke/py-derive-v1", ws)
        checker = model.resolve_checker(stub_repo, "smoke", "py-derive-v1")
        assert checker == (stub_repo / "eval/v1/tasks/smoke/py-derive-v1/checker.py")
        assert ws not in checker.parents  # never resolved from the workspace

    # ------------------------------------------------ contamination pins

    def test_staging_native_unit_stages_declared_material_never_reference(
            self, native_stub_repo, tmp_path):
        """A native unit's declared analysis material (the .so)
        stages; the checker's answer source (reference.py) never does —
        the checker invokes it harness-side from the REPO tree."""
        ws = tmp_path / "ws"
        model.stage_workspace(
            native_stub_repo / "eval/v1/tasks/release/arm-kdf-l0", ws)
        assert (ws / "target/libkdf.so").read_bytes() == ELF_SO
        staged = sorted(p.relative_to(ws).as_posix()
                        for p in ws.rglob("*") if p.is_file())
        assert staged == ["target/libkdf.so"], \
            f"answer source staged into the workspace: {staged}"

    def test_staging_preserves_nested_declared_paths(
            self, nested_stub_repo, tmp_path):
        """Declared relative paths land at the SAME relative path under
        WS (deep target trees, not flattened into WS/target)."""
        ws = tmp_path / "ws"
        model.stage_workspace(
            nested_stub_repo / "eval/v1/tasks/release/synth-nested", ws)
        assert (ws / "target/deep/nested.so").read_bytes() == ELF_SO
        assert list(ws.rglob("reference.py")) == []

    def test_staging_excludes_answer_names_even_without_self_check(
            self, tmp_path):
        """Belt and suspenders: a misconfigured unit that lists
        reference.py WITHOUT declaring it self_check_candidate still
        never stages it (name-denylist backstop)."""
        repo = tmp_path / "repo"
        task = repo / "eval/v1/tasks/release/synth-misconf"
        (task / "target").mkdir(parents=True)
        (task / "target/libkdf.so").write_bytes(ELF_SO)
        (task / "reference.py").write_text(REFERENCE_PY, encoding="utf-8")
        (task / "task.yaml").write_text(
            NATIVE_TASK_YAML.replace("arm-kdf-l0", "synth-misconf")
            .replace("checker:\n  entrypoint: checker.py\n"
                     "  self_check_candidate: reference.py\n", "checker:\n"),
            encoding="utf-8")
        ws = tmp_path / "ws"
        model.stage_workspace(task, ws)
        assert list(ws.rglob("reference.py")) == []
        assert (ws / "target/libkdf.so").read_bytes() == ELF_SO

    def test_staging_missing_declared_file_fails_loudly(
            self, native_stub_repo, tmp_path):
        """A declared file absent from the task unit is a loud failure
        naming the missing path — never a silent partial stage."""
        (native_stub_repo / "eval/v1/tasks/release/arm-kdf-l0/target/libkdf.so") \
            .unlink()
        with pytest.raises(FileNotFoundError, match="libkdf.so"):
            model.stage_workspace(
                native_stub_repo / "eval/v1/tasks/release/arm-kdf-l0",
                tmp_path / "ws")

    def test_staging_without_declared_files_fails_loudly(self, tmp_path):
        """A unit with no workspace_scaffold.files has no analysis
        material — refuse loudly (AnchorError kin), never an empty mount."""
        repo = tmp_path / "repo"
        task = repo / "eval/v1/tasks/release/synth-empty"
        task.mkdir(parents=True)
        (task / "task.yaml").write_text(
            NATIVE_TASK_YAML.replace("arm-kdf-l0", "synth-empty").replace(
                "workspace_scaffold:\n  files:\n"
                "  - target/libkdf.so\n  - reference.py\n",
                "workspace_scaffold:\n  files: []\n"),
            encoding="utf-8")
        with pytest.raises(model.AnchorError, match="workspace_scaffold.files"):
            model.stage_workspace(task, tmp_path / "ws")

    def test_guard_flags_planted_reference_py(self, tmp_path):
        """Defense-in-depth: reference.py is an answer source —
        its presence ANYWHERE in the workspace is a contamination
        violation (the checker's own copy lives in the REPO tree)."""
        ws = tmp_path / "ws"
        nested = ws / "a/reference.py"
        nested.parent.mkdir(parents=True)
        nested.write_text(REFERENCE_PY, encoding="utf-8")
        violations = model.check_contamination(ws)
        assert any("reference.py" in v for v in violations)


# ---------------------------------------------------------------------------
# evidence schema + resume
# ---------------------------------------------------------------------------

def _result(step: str, status: str = "PASS") -> model.CheckpointResult:
    if "-" in step:
        checkpoint, name = step.split("-", 1)
    else:
        checkpoint, name = step, step.lower()
    return model.CheckpointResult(
        checkpoint=checkpoint, name=name, status=status, rc=0,
        stdout_tail="out", stderr_tail="", duration_ms=10,
        evidence_paths=[], ts="2026-09-28T00:00:00Z", detail={})


class TestEvidenceSchema:
    REQUIRED_KEYS = {"checkpoint", "name", "status", "rc", "stdout_tail",
                     "stderr_tail", "duration_ms", "evidence_paths", "ts",
                     "detail"}

    def test_checkpoint_evidence_has_required_schema(self, tmp_path):
        res = _result("C2-hooks")
        path = evidence.write_checkpoint(tmp_path, res)
        assert path.name == f"{res.step}.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert self.REQUIRED_KEYS <= set(doc)
        assert doc["status"] in {"PASS", "FAIL", "BLOCKED", "SKIP"}

    def test_roundtrip_load_for_resume(self, tmp_path):
        evidence.write_checkpoint(tmp_path, _result("C5-analysis"))
        loaded = evidence.load_checkpoint(tmp_path, "C5-analysis")
        assert loaded is not None and loaded["status"] == "PASS"
        assert evidence.load_checkpoint(tmp_path, "C9-x") is None

    def test_report_contains_table_budget_and_verdict(self, tmp_path):
        state = model.RunState(
            run_id="r1", unit="py-derive-v1", family="smoke",
            repo=str(tmp_path), task_dir=str(tmp_path),
            ws=str(tmp_path / "ws"), evidence_dir=str(tmp_path),
            budget_seconds=100, llm_mode="dry",
            started_ts="2026-09-28T00:00:00Z", started_monotonic=0.0,
            anchors=dict(ANCHORS))
        results = [_result("C1-init"), _result("ORACLE")]
        report = evidence.build_report(
            state, results, final_status="ALL-PASS", exit_code=0,
            final_verdict={"verdict": "PASS", "min_pair_ratio": 1.0})
        assert report["final_status"] == "ALL-PASS"
        assert len(report["checkpoints"]) == 2
        assert report["budget"]["seconds"] == 100
        assert report["oracle"]["verdict"] == "PASS"
        assert report["workspace"] == str(tmp_path / "ws")
        text = evidence.render_summary(report)
        assert "ORACLE" in text and "PASS" in text


class TestBudgetEnforcement:
    def test_budget_remaining_from_injected_clock(self):
        state = model.RunState(
            run_id="r", unit="u", family="smoke", repo=".", task_dir=".",
            ws=".", evidence_dir=".", budget_seconds=100, llm_mode="dry",
            started_ts="t", started_monotonic=0.0, anchors={})
        state.budget_consumed_seconds = 40
        assert state.budget_remaining_seconds() == 60
        state.budget_consumed_seconds = 200
        assert state.budget_remaining_seconds() == 0

    def test_exhausted_budget_yields_exit_4_partial(self, stub_repo, tmp_path):
        runner = ScriptedRunner()
        clock = FakeClock()
        rc = checkpoints.run_pipeline(
            model.PipelineArgs(unit="py-derive-v1", repo=stub_repo,
                               ws_root=tmp_path / "wsroot", budget_seconds=0,
                               llm_mode="dry", tick_wait_seconds=0,
                               run_id="broke"),
            cmd_runner=runner, clock=clock, sleep_fn=clock.sleep)
        assert rc == model.EXIT_BUDGET_PARTIAL
        assert runner.calls == []  # nothing ran: no silent partial work
        report = json.loads(
            (stub_repo / "runs/e2e/broke/report.json").read_text(encoding="utf-8"))
        assert report["final_status"] == "PARTIAL"
        assert report["checkpoints"] == []

    def test_midloop_budget_exhaustion_is_partial_exit_4(self, stub_repo,
                                                         tmp_path):
        """F4: the runbook's mid-flight budget stop is PARTIAL/4 even when
        it fires INSIDE the C6 loop (was BLOCKED/3)."""
        runner, clock = ScriptedRunner(), FakeClock()
        ws_root = tmp_path / "wsroot"
        settings = ws_root / "e2e-ws-mid4/.claude/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        hb = ws_root / "e2e-ws-mid4/runs/.heartbeat.json"
        hb.parent.mkdir(parents=True)
        hb.write_text('{"interval_min": 5}\n', encoding="utf-8")
        pending_doc = json.dumps({"decisions": [
            {"decision_id": "goal_verbatim"},
            {"decision_id": "success_criterion"},
            {"decision_id": "verification_method"}]})
        runner.on("kunglao-init.py", "--resolve", rc=0)
        runner.on("kunglao-init.py", "--lane", rc=8, stdout=pending_doc)
        runner.on("hook_activation.py", "--wire-up", rc=0, stdout="PASS\n")
        runner.on("hook_activation.py", "--heartbeat-on", rc=0)
        runner.on("heartbeat_tick.py", rc=0)
        runner.on("kunglao", "check-stale", rc=0,
                  stdout=json.dumps({"status": "current", "rc": 0}))
        runner.on("kunglao", "analysis", rc=0)
        runner.on("goal_operationalization.py", rc=0,
                  stdout=json.dumps({"errors": []}))
        runner.on("env_check.py", rc=0, stdout="OVERALL: PASS")
        runner.on("priority_ratio.py", "--json", rc=0,
                  stdout=json.dumps({"actions": [
                      {"claim_id": "C-004", "action": "static_re"}]}))
        # never converges: the loop spins until the budget guard trips
        runner.on("convergence_check.py", "--json", rc=1,
                  stdout=json.dumps({"decision": "DISPATCH"}))
        # timeline (FakeClock advances only on sleep): start 1000;
        # C5 sleeps 60 -> 1060; loop iter1 sleeps 60 -> 1120; iter2 guard
        # sees consumed 120 == budget -> exhausted
        rc = checkpoints.run_pipeline(
            model.PipelineArgs(unit="py-derive-v1", repo=stub_repo,
                               ws_root=ws_root, budget_seconds=120,
                               llm_mode="dry", tick_wait_seconds=60,
                               run_id="mid4", max_ticks=30),
            cmd_runner=runner, clock=clock, sleep_fn=clock.sleep)
        assert rc == model.EXIT_BUDGET_PARTIAL
        report = json.loads(
            (stub_repo / "runs/e2e/mid4/report.json").read_text(encoding="utf-8"))
        assert report["final_status"] == "PARTIAL"
        by_step = {c["step"]: c for c in report["checkpoints"]}
        assert by_step["C6-loop"]["status"] == "BLOCKED"
        assert by_step["C6-loop"]["detail"]["stop_class"] == "budget-exhausted"
        # C7/ORACLE never ran — honest partial, not a fabricated verdict
        assert "C7-completion" not in by_step and "ORACLE" not in by_step


class TestResume:
    def test_pass_steps_skipped_non_pass_rerun(self, tmp_path):
        evidence.write_checkpoint(tmp_path, _result("C1-init"))
        evidence.write_checkpoint(tmp_path, _result("C2-hooks", status="FAIL"))
        plan = checkpoints.resume_plan(tmp_path)
        assert plan["C1-init"] == "SKIP"
        assert plan["C2-hooks"] == "RUN"
        assert plan["C3-heartbeat"] == "RUN"

    def test_run_id_resolution_from_evidence_root(self, tmp_path):
        (tmp_path / "runs/e2e/abc").mkdir(parents=True)
        (tmp_path / "runs/e2e/abc/run-state.json").write_text("{}", encoding="utf-8")
        assert evidence.resolve_run_dir(tmp_path, "abc").name == "abc"
        with pytest.raises(FileNotFoundError):
            evidence.resolve_run_dir(tmp_path, "nope")


# ---------------------------------------------------------------------------
# F1 pin: the REAL eval_checker stdout format (scripts/eval_checker.py run()
# tail — METRIC lines via eval_dataset.metric_line, FAILURE lines, terminal
# "EVIDENCE <path>" then "VERDICT <v>"; NO JSON object on stdout).
# ---------------------------------------------------------------------------

REAL_CHECKER_STDOUT_TEMPLATE = """METRIC ttc_seconds=0.123
METRIC dispatch_count=1
METRIC pass_at_k_contribution=1
METRIC converged=1
EVIDENCE {evidence_path}
VERDICT {verdict}
"""

REAL_EVIDENCE_DOC = {
    "schema": "kunglao-eval-evidence/1", "task_id": "py-derive-v1",
    "eval_version": "eval-v1", "family": "py-derive", "tier": "smoke",
    "candidate": "/ws/artifacts/derive_reimpl.py",
    "faces": {"replay": {"matched": 12, "count": 12,
                         "toolchain": "python3", "ttc_seconds": 0.123}},
    "metrics": {"ttc_seconds": 0.123, "dispatch_count": 1,
                "pass_at_k_contribution": 1, "converged": 1},
    "verdict": "PASS", "failures": [],
}


class TestCheckerOutputParsing:
    """Pin the parser against the real checker's stdout shape (F1)."""

    def test_parses_metric_evidence_and_terminal_verdict(self):
        stdout = REAL_CHECKER_STDOUT_TEMPLATE.format(
            evidence_path="/repo/runs/eval/evidence-x.json", verdict="PASS")
        parsed = model.parse_checker_output(stdout)
        assert parsed["verdict"] == "PASS"
        assert parsed["evidence_path"] == "/repo/runs/eval/evidence-x.json"
        assert parsed["metrics"]["ttc_seconds"] == 0.123
        assert parsed["metrics"]["dispatch_count"] == 1
        assert parsed["metrics"]["converged"] == 1
        assert parsed["failures"] == []

    def test_failure_lines_captured_and_verdict_fail(self):
        stdout = ("METRIC ttc_seconds=1.5\n"
                  "METRIC dispatch_count=2\n"
                  "METRIC pass_at_k_contribution=0\n"
                  "METRIC converged=0\n"
                  "FAILURE code=PAIR_MISMATCH detail=probe 7 expected 9 got 8\n"
                  "EVIDENCE /repo/runs/eval/evidence-y.json\n"
                  "VERDICT FAIL\n")
        parsed = model.parse_checker_output(stdout)
        assert parsed["verdict"] == "FAIL"
        assert len(parsed["failures"]) == 1
        assert "PAIR_MISMATCH" in parsed["failures"][0]

    def test_no_json_object_is_required_or_assumed(self):
        """The real checker never prints a JSON object on stdout — a JSON
        blob must NOT be mistaken for the verdict channel."""
        stdout = ("some log line {\"verdict\": \"PASS\"}\n"
                  "EVIDENCE /e.json\nVERDICT FAIL\n")
        parsed = model.parse_checker_output(stdout)
        assert parsed["verdict"] == "FAIL"

    def test_missing_verdict_line_is_none_never_guessed(self):
        parsed = model.parse_checker_output("METRIC ttc_seconds=1.0\n")
        assert parsed["verdict"] is None
        assert parsed["evidence_path"] is None


class TestOracleRealFormat:
    """checkpoint_oracle must PASS only on the REAL checker output (F1)."""

    def _ctx(self, stub_repo, tmp_path, stdout, rc=0):
        ws = tmp_path / "ws"
        (ws / "artifacts").mkdir(parents=True, exist_ok=True)
        (ws / "artifacts/derive_reimpl.py").write_text(DERIVE_PY,
                                                       encoding="utf-8")
        ev_dir = tmp_path / "ev"
        state = model.RunState(
            run_id="o1", unit="py-derive-v1", family="smoke",
            repo=str(stub_repo),
            task_dir=str(stub_repo / "eval/v1/tasks/smoke/py-derive-v1"),
            ws=str(ws), evidence_dir=str(ev_dir), budget_seconds=100,
            llm_mode="dry", started_ts="t", started_monotonic=0.0,
            anchors=dict(ANCHORS))
        runner = ScriptedRunner()
        runner.on("checker.py", "--candidate", rc=rc, stdout=stdout)
        face = llm_faces.face_for("dry", runner, ev_dir)
        return checkpoints.RunContext(
            state=state, runner=runner, face=face, clock=FakeClock(),
            sleep_fn=lambda _s: None)

    def test_real_format_pass_with_full_replay_ratio(self, stub_repo, tmp_path):
        ev = stub_repo / "runs/eval/evidence-x.json"
        ev.parent.mkdir(parents=True, exist_ok=True)
        ev.write_text(json.dumps(REAL_EVIDENCE_DOC), encoding="utf-8")
        stdout = REAL_CHECKER_STDOUT_TEMPLATE.format(
            evidence_path="runs/eval/evidence-x.json", verdict="PASS")
        result = checkpoints.checkpoint_oracle(self._ctx(stub_repo, tmp_path,
                                                         stdout))
        assert result.status == "PASS", result.detail
        assert result.detail["verdict"] == "PASS"
        assert result.detail["min_pair_ratio"] == 1.0  # 12/12 from evidence
        assert result.detail["pairs"] == {"matched": 12, "count": 12}

    def test_real_format_fail_verdict_fails_even_at_rc0(self, stub_repo,
                                                        tmp_path):
        ev = stub_repo / "runs/eval/evidence-x.json"
        ev.parent.mkdir(parents=True, exist_ok=True)
        ev.write_text(json.dumps(REAL_EVIDENCE_DOC), encoding="utf-8")
        stdout = REAL_CHECKER_STDOUT_TEMPLATE.format(
            evidence_path="runs/eval/evidence-x.json", verdict="FAIL")
        result = checkpoints.checkpoint_oracle(self._ctx(stub_repo, tmp_path,
                                                         stdout))
        assert result.status == "FAIL"
        assert result.detail["verdict"] == "FAIL"

    def test_partial_replay_ratio_fails(self, stub_repo, tmp_path):
        doc = json.loads(json.dumps(REAL_EVIDENCE_DOC))
        doc["faces"]["replay"]["matched"] = 11  # 11/12 < required 1.0
        ev = stub_repo / "runs/eval/evidence-x.json"
        ev.parent.mkdir(parents=True, exist_ok=True)
        ev.write_text(json.dumps(doc), encoding="utf-8")
        stdout = REAL_CHECKER_STDOUT_TEMPLATE.format(
            evidence_path="runs/eval/evidence-x.json", verdict="PASS")
        result = checkpoints.checkpoint_oracle(self._ctx(stub_repo, tmp_path,
                                                         stdout))
        assert result.status == "FAIL"
        assert result.detail["min_pair_ratio"] == 11 / 12

    def test_missing_evidence_file_is_fail_not_vacuous_pass(self, stub_repo,
                                                             tmp_path):
        """The checker ALWAYS writes the evidence file; its absence is real
        breakage — never a lenient pass (reviewer: vacuous ratio_ok)."""
        stdout = REAL_CHECKER_STDOUT_TEMPLATE.format(
            evidence_path="runs/eval/evidence-gone.json", verdict="PASS")
        result = checkpoints.checkpoint_oracle(self._ctx(stub_repo, tmp_path,
                                                         stdout))
        assert result.status == "FAIL"
        assert result.detail.get("evidence_error")


# ---------------------------------------------------------------------------
# F2 pin: settlement rows carry action="claim_settled" (the REAL #880
# emitter — register_proven_gate.emit_settlements -> kunglao_log.emit;
# the runbook's "action=settlement" does not match the repo).
# ---------------------------------------------------------------------------

REAL_SETTLEMENT_ROW = {
    "ts": "2026-09-28T10:00:00Z", "actor": "hook:write_guard",
    "action": "claim_settled", "claim": "C-004", "trace_id": "tr-1",
    "duration_ms": 123456,
    "detail": "{\"from\": \"OPEN\", \"to\": \"PROVEN\", \"tools\": [], "
              "\"outcome\": \"PROVEN\"}",
}


class TestSettlementAction:
    def test_scan_counts_claim_settled_rows(self, tmp_path):
        log = tmp_path / "runs/logs/kunglao-2026-09-28.jsonl"
        log.parent.mkdir(parents=True)
        log.write_text(
            json.dumps({"action": "dispatch", "claim": "C-004"}) + "\n"
            + json.dumps(REAL_SETTLEMENT_ROW) + "\n"
            + json.dumps({"action": "cockpit_sample"}) + "\n",
            encoding="utf-8")
        scan = model.scan_settlement_rows(tmp_path)
        assert scan["rows"] == 1
        assert scan["files"] == [str(log)]

    def test_legacy_settlement_action_is_not_counted(self, tmp_path):
        """action='settlement' has NO emitter in the repo — must read 0."""
        log = tmp_path / "runs/logs/kunglao-2026-09-28.jsonl"
        log.parent.mkdir(parents=True)
        log.write_text(json.dumps({"action": "settlement"}) + "\n",
                       encoding="utf-8")
        assert model.scan_settlement_rows(tmp_path)["rows"] == 0

    def test_settlement_action_constant_pinned_to_repo_emitter(self):
        assert model.SETTLEMENT_ACTION == "claim_settled"


# ---------------------------------------------------------------------------
# F3 pin: promote_claims honors check_register_transitions' verdict.
# ---------------------------------------------------------------------------

class TestPromotionGateHonored:
    def _ws_with_register(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        reg = ws / "claim-register.yaml"
        reg.write_text(
            "claims:\n  - id: C-004\n    status: OPEN\n"
            "    statement: x\n    answers_question: pq-1\n",
            encoding="utf-8")
        return ws, reg

    def test_gate_not_ok_blocks_write_and_reports_violations(
            self, stub_repo, tmp_path, monkeypatch):
        import register_proven_gate as rpg
        ws, reg = self._ws_with_register(tmp_path)
        before = reg.read_text(encoding="utf-8")
        verdict = {"ok": False,
                   "violations": ["C-004: latest verify-note outcome != "
                                  "passes"],
                   "waivers": []}
        monkeypatch.setattr(rpg, "check_register_transitions",
                            lambda ws, new, old=None: verdict)
        out = checkpoints.promote_claims(stub_repo, ws, ["C-004"])
        assert out["ok"] is False
        assert out["written"] is False
        assert out["violations"] == verdict["violations"]
        assert reg.read_text(encoding="utf-8") == before  # NOT written

    def test_gate_ok_writes_and_settles(self, stub_repo, tmp_path,
                                        monkeypatch):
        import register_proven_gate as rpg
        ws, reg = self._ws_with_register(tmp_path)
        monkeypatch.setattr(rpg, "check_register_transitions",
                            lambda ws, new, old=None: {
                                "ok": True, "violations": [], "waivers": []})

        def fake_emit(ws, new_text, old_text=None):
            log = ws / "runs/logs/kunglao-2026-09-28.jsonl"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(json.dumps(REAL_SETTLEMENT_ROW) + "\n",
                           encoding="utf-8")
            return 1
        monkeypatch.setattr(rpg, "emit_settlements", fake_emit)
        out = checkpoints.promote_claims(stub_repo, ws, ["C-004"])
        assert out["ok"] is True and out["written"] is True
        assert "PROVEN" in reg.read_text(encoding="utf-8")
        assert out["settlements"] == 1


# ---------------------------------------------------------------------------
# dispatch request schema
# ---------------------------------------------------------------------------

class TestDispatchRequest:
    def test_serializes_the_v1_envelope(self, tmp_path):
        req = model.DispatchRequest(
            claim="C-004", workspace=str(tmp_path), prompt_file="p.md",
            run_id="r1")
        doc = req.to_dict()
        assert doc["schema_version"] == "kunglao_dispatch/1"
        assert doc["claim"] == "C-004"
        assert doc["tier"] == 1
        assert doc["agent"] == "kunglao-worker"
        assert json.loads(json.dumps(doc))["tools"] == ["grep", "python3"]


# ---------------------------------------------------------------------------
# dry-llm integration: scripted C1->C7 + oracle, every scripted stdout in
# the REAL repo scripts' shapes (F1/F2 re-pin: checker text format,
# claim_settled rows; the promote path runs for real with only the
# register_proven_gate internals patched).
# ---------------------------------------------------------------------------

def _script_pipeline(runner: ScriptedRunner, stub_repo: Path,
                     ws_root: Path, run_id: str) -> None:
    """Script every subprocess the pipeline issues, in the REAL output
    shapes (eval_checker text emission; convergence/priority JSON faces)."""
    settings = ws_root / f"e2e-ws-{run_id}/.claude/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({
        "hooks": {"PreToolUse": [
            {"hooks": [{"command":
                        "python3 hooks/lib_kunglao.py --precheck"}]}]}}),
        encoding="utf-8")
    # the scripted --heartbeat-on "creates" the heartbeat state
    hb = ws_root / f"e2e-ws-{run_id}/runs/.heartbeat.json"
    hb.parent.mkdir(parents=True)
    hb.write_text('{"interval_min": 5}\n', encoding="utf-8")
    pending_doc = json.dumps({
        "schema_version": "pending/1", "flow": "init",
        "decisions": [
            {"decision_id": "goal_verbatim", "question": "goal?"},
            {"decision_id": "success_criterion", "question": "done?"},
            {"decision_id": "verification_method", "question": "how?"},
        ]})
    # rule order: the --resolve re-entry also carries --lane, so the
    # resolve rule must be checked BEFORE the plain --lane rule.
    runner.on("kunglao-init.py", "--resolve", rc=0)
    runner.on("kunglao-init.py", "--lane", rc=8, stdout=pending_doc)
    runner.on("lib_kunglao.py", rc=0)
    runner.on("hook_activation.py", "--wire-up", rc=0,
              stdout="selfcheck write_guard PASS\nselfcheck yaml PASS\n")
    runner.on("hook_activation.py", "--heartbeat-on", rc=0)
    runner.on("heartbeat_tick.py", rc=0)
    runner.on("kunglao", "check-stale", rc=0,
              stdout=json.dumps({"status": "current", "rc": 0}))
    runner.on("kunglao", "analysis", rc=0)
    runner.on("goal_operationalization.py", rc=0,
              stdout=json.dumps({"schema": "goal-operationalization/1",
                                 "errors": []}))
    runner.on("env_check.py", rc=0, stdout="OVERALL: PASS  (snapshot: s)")
    runner.on("priority_ratio.py", "--json", rc=0,
              stdout=json.dumps({"actions": [
                  {"claim_id": "C-004", "action": "static_re"}]}))
    runner.on("completion_gate.py", rc=0)
    # REAL checker emission: METRIC lines + EVIDENCE path + VERDICT (F1)
    ev_rel = "runs/eval/evidence-py-derive-v1-20260928.json"
    ev = stub_repo / ev_rel
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text(json.dumps(REAL_EVIDENCE_DOC), encoding="utf-8")
    runner.on("checker.py", "--candidate", rc=0, stdout=(
        "METRIC ttc_seconds=0.123\n"
        "METRIC dispatch_count=1\n"
        "METRIC pass_at_k_contribution=1\n"
        "METRIC converged=1\n"
        f"EVIDENCE {ev_rel}\n"
        "VERDICT PASS\n"))
    # stateful: C6-pre DISPATCH -> loop DISPATCH (act) -> loop
    # CONVERGED (facts landed) -> C7 CONVERGED
    runner.seq("convergence_check.py", "--json", outcomes=[
        (1, json.dumps({"decision": "DISPATCH"})),
        (1, json.dumps({"decision": "DISPATCH"})),
        (0, json.dumps({"decision": "CONVERGED"})),
        (0, json.dumps({"decision": "CONVERGED"})),
    ])


def _patch_gate(monkeypatch, ok: bool) -> None:
    """Patch ONLY the register_proven_gate internals; the runner's real
    promote_claims path (gate verdict honored, register written on ok,
    settlements emitted) executes for real (F3 re-pin)."""
    import register_proven_gate as rpg

    def fake_emit(ws, new_text, old_text=None):
        # REAL #880 row shape: action="claim_settled" (F2 re-pin)
        log = ws / "runs/logs/kunglao-2026-09-28.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        rows = [json.dumps({**REAL_SETTLEMENT_ROW, "claim": cid}) + "\n"
                for cid in ("C-004", "C-005")]
        log.write_text("".join(rows), encoding="utf-8")
        return len(rows)

    if ok:
        monkeypatch.setattr(rpg, "check_register_transitions",
                            lambda ws, new, old=None: {
                                "ok": True, "violations": [],
                                "waivers": []})
    else:
        monkeypatch.setattr(rpg, "check_register_transitions",
                            lambda ws, new, old=None: {
                                "ok": False,
                                "violations": [
                                    "C-004: latest verify-note outcome != "
                                    "passes"],
                                "waivers": []})
    monkeypatch.setattr(rpg, "emit_settlements", fake_emit)


class TestDryLlmIntegration:
    def test_full_pipeline_green_and_uncontaminated(self, stub_repo, tmp_path):
        runner = ScriptedRunner()
        clock = FakeClock()
        ws_root = tmp_path / "wsroot"
        _script_pipeline(runner, stub_repo, ws_root, "dry1")
        monkey_patch = pytest.MonkeyPatch()
        _patch_gate(monkey_patch, ok=True)

        args = model.PipelineArgs(
            unit="py-derive-v1", repo=stub_repo, ws_root=ws_root,
            budget_seconds=14400, llm_mode="dry", tick_wait_seconds=0,
            run_id="dry1")
        try:
            rc = checkpoints.run_pipeline(
                args, cmd_runner=runner, clock=clock, sleep_fn=clock.sleep)
        finally:
            monkey_patch.undo()

        assert rc == model.EXIT_OK, f"pipeline exit {rc}"

        report = json.loads(
            (stub_repo / "runs/e2e/dry1/report.json").read_text(encoding="utf-8"))
        assert report["final_status"] == "ALL-PASS"
        assert report["oracle"]["verdict"] == "PASS"
        assert report["oracle"]["min_pair_ratio"] == 1.0  # 12/12 replay pairs
        by_step = {c["step"]: c["status"] for c in report["checkpoints"]}
        for step in ("C1-init", "C2-hooks", "C3-heartbeat", "C4-entry",
                     "C5-analysis", "C6-pre", "C6-loop", "C7-completion",
                     "ORACLE"):
            assert by_step.get(step) == "PASS", f"{step}: {by_step.get(step)}"

        # workspace never contaminated; the tick wait never exceeded 5m
        ws = Path(report["workspace"])
        assert not list(ws.rglob("ground_truth.json"))
        assert not list(ws.rglob("checker.py"))
        assert (ws / "target/derive.py").exists()
        assert all(s in (0, 300) for s in clock.sleeps)

        # init re-entered WITH lane/type flags repeated (rehearsal finding #1)
        resolve_calls = [c for c in runner.calls if "--resolve" in c]
        assert resolve_calls, "no --resolve re-entry recorded"
        for call in resolve_calls:
            assert "--lane" in call and "--type" in call

        # goal-op doc validated from verbatim anchors (rehearsal finding #2)
        goal_op = (ws / "goal-operationalization.yaml").read_text(encoding="utf-8")
        assert ANCHORS["goal_verbatim"] in goal_op
        # claims C-004/C-005 + primary questions registered; promotion
        # landed through the honored gate
        register = (ws / "claim-register.yaml").read_text(encoding="utf-8")
        assert "C-004" in register and "C-005" in register
        assert "PROVEN" in register  # the ok=True gate allowed the write
        spec = (ws / "task_spec.yaml").read_text(encoding="utf-8")
        assert "pq-1" in spec and "pq-2" in spec
        # C7 saw the REAL settlement rows (claim_settled, F2)
        c7 = [c for c in report["checkpoints"]
              if c["step"] == "C7-completion"][0]
        assert c7["detail"]["settlement_rows"] >= 1
        assert c7["detail"]["settlement_action"] == "claim_settled"

    def test_promotion_gate_violation_fails_c6_loop(self, stub_repo, tmp_path):
        """F3: an unwaived gate violation must FAIL the promote step — no
        register write, no fabricated C6-loop PASS."""
        runner = ScriptedRunner()
        clock = FakeClock()
        ws_root = tmp_path / "wsroot"
        _script_pipeline(runner, stub_repo, ws_root, "gate-red")
        monkey_patch = pytest.MonkeyPatch()
        _patch_gate(monkey_patch, ok=False)

        args = model.PipelineArgs(
            unit="py-derive-v1", repo=stub_repo, ws_root=ws_root,
            budget_seconds=14400, llm_mode="dry", tick_wait_seconds=0,
            run_id="gate-red")
        try:
            rc = checkpoints.run_pipeline(
                args, cmd_runner=runner, clock=clock, sleep_fn=clock.sleep)
        finally:
            monkey_patch.undo()

        assert rc == model.EXIT_CHECKPOINT_FAIL
        report = json.loads(
            (stub_repo / "runs/e2e/gate-red/report.json")
            .read_text(encoding="utf-8"))
        assert report["final_status"] == "FAIL"
        c6 = [c for c in report["checkpoints"] if c["step"] == "C6-loop"][0]
        assert c6["status"] == "FAIL"
        assert c6["detail"]["failed_step"] == "promote-gate"
        assert any("verify-note" in v
                   for v in c6["detail"]["promotion"]["violations"])
        # register NOT promoted: the gate refused the write
        register = (Path(report["workspace"]) / "claim-register.yaml")
        assert "PROVEN" not in register.read_text(encoding="utf-8")
        # pipeline stopped before the oracle — no verdict fabricated
        by_step = {c["step"] for c in report["checkpoints"]}
        assert "ORACLE" not in by_step


def test_c3_first_tick_waiting_second_is_pass():
    """#450: a FIRST tick's rc=1 with the waiting-for-second-tick
    continuity reason is CORRECT #415 behavior — C3 passes (continuity
    itself is C5's job). The acceptance is wired in checkpoint_c3's
    waiting_second predicate; this pin holds the wiring in place."""
    code = (SCRIPTS / "e2e" / "checkpoints.py").read_text(
        encoding="utf-8")
    assert "wait for the SECOND tick" in code, (
        "the #450 waiting-reason acceptance must stay wired")
    assert "waiting_second_tick" in code
    assert ".heartbeat-tick.json" in code, (
        "#450 r2: the predicate must read the TICK REPORT artifact "
        "(heartbeat.stderr lives there, not the process stderr — "
        "reviewer-450-1's finding)")
    assert 'out_tick.rc == 1' in code, (
        "the rc==1 gate: only the waiting reason passes, never rc>=2")
    assert '_hb.get("rc") == 1' in code, (
        "the report-level rc gate: the heartbeat STEP inside the report "
        "must also be rc==1, not just the process rc")


def test_top_claim_bare_pretty_printed_array():
    """#454: priority_ratio --json emits json.dumps(..., indent=2) — a
    pretty-printed MULTI-LINE array. top_claim must parse the whole
    stdout, not just single lines starting with '['."""
    import sys as _sys
    _sys.path.insert(0, str(SCRIPTS / "e2e"))
    from runtime import top_claim
    from model import CmdOutcome
    # the real ranker face: indent=2, multi-line
    real = '''[
  {
    "claim_id": "C-005",
    "action": "evidence_collection",
    "score": 0.976
  },
  {
    "claim_id": "C-004",
    "action": "protocol_reconstruction",
    "score": 0.911
  }
]'''
    assert top_claim(CmdOutcome(rc=0, stdout=real, stderr="",
                                timed_out=False)) == "C-005"
    # object envelope (backward face)
    env = '{"actions": [{"claim_id": "C-001", "score": 0.9}]}'
    assert top_claim(CmdOutcome(rc=0, stdout=env, stderr="",
                                timed_out=False)) == "C-001"
    # garbage
    assert top_claim(CmdOutcome(rc=0, stdout="not json", stderr="",
                                timed_out=False)) is None
    # empty
    assert top_claim(CmdOutcome(rc=0, stdout="", stderr="",
                                timed_out=False)) is None


# ---------------------------------------------------------------------------
# Owner ruling 2026-09-29 (「需要完整补全。另外日志太分散、格式尽量统一」):
# ONE unified audit stream per workspace — <ws>/runs/logs/e2e-audit.jsonl —
# in the exact kunglao_log.emit 17-field schema. Every checkpoint result,
# dispatch attempt/result, convergence decision, and oracle verdict leaves
# EXACTLY ONE event; the kernel-facing hooks (method_family / strategy /
# posterior / mainline) exist ready for activation.
# ---------------------------------------------------------------------------


class TestUnifiedAuditTrail:
    AUDIT_RELPATH = Path("runs") / "logs" / "e2e-audit.jsonl"

    def _rows(self, ws: Path) -> list[dict]:
        from e2e import audit
        path = audit.audit_path(ws)
        assert path.is_file(), f"missing unified audit stream: {path}"
        return [json.loads(line) for line
                in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def _ctx(self, stub_repo, tmp_path, mode="dry", runner=None,
             ws: Path | None = None):
        ws = ws or (tmp_path / "ws")
        ws.mkdir(parents=True, exist_ok=True)
        ev_dir = tmp_path / "ev"
        state = model.RunState(
            run_id="a1", unit="py-derive-v1", family="smoke",
            repo=str(stub_repo),
            task_dir=str(stub_repo / "eval/v1/tasks/smoke/py-derive-v1"),
            ws=str(ws), evidence_dir=str(ev_dir), budget_seconds=100,
            llm_mode=mode, started_ts="t", started_monotonic=0.0,
            anchors=dict(ANCHORS))
        runner = runner or ScriptedRunner()
        face = llm_faces.face_for(mode, runner, ev_dir)
        return checkpoints.RunContext(
            state=state, runner=runner, face=face, clock=FakeClock(),
            sleep_fn=lambda _s: None)

    # -- schema: the stream IS kunglao_log's 17-field schema ----------------

    def test_stream_uses_kunglao_log_17_field_schema(self, tmp_path):
        """Spot-check field names: an audit row carries EXACTLY the field
        set of a real kunglao_log.emit row (schema drift = red here)."""
        import kunglao_log
        from e2e import audit
        ws_a, ws_b = tmp_path / "a", tmp_path / "b"
        ws_a.mkdir()
        ws_b.mkdir()
        assert kunglao_log.emit(ws_a, "orchestrator", "warn",
                                detail="schema reference row")
        assert audit.emit(ws_b, "orchestrator", "convergence_decision",
                          claim="C-004", exit=0, detail={"decision": "DISPATCH"})
        ref = json.loads(
            (kunglao_log.log_path(ws_a)).read_text(encoding="utf-8"))
        row = self._rows(ws_b)[0]
        assert len(ref) == 17
        assert sorted(row) == sorted(ref), (
            f"schema drift: audit={sorted(row)} vs kunglao_log={sorted(ref)}")
        for name in ("ts", "actor", "action", "claim", "tool", "artifact",
                     "duration_ms", "exit", "detail", "arm", "epoch",
                     "hypothesis_ref", "matched_rule", "trace_id", "version",
                     "channel", "null_reasons"):
            assert name in row

    # -- checkpoint results land exactly once ------------------------------

    def test_checkpoint_pass_lands_exactly_one_event(self, stub_repo, tmp_path):
        from e2e.runtime import record_result
        ctx = self._ctx(stub_repo, tmp_path)
        record_result(ctx, "C1", "init", "PASS", 0, None, 5, {})
        rows = self._rows(ctx.ws)
        assert len(rows) == 1, "exactly-one-event guarantee violated"
        row = rows[0]
        assert row["action"] == "checkpoint_pass"
        assert row["actor"] == "orchestrator"
        detail = json.loads(row["detail"])
        assert set(detail) == {"step", "status", "rc", "duration_ms",
                               "failed_step"}
        assert detail["step"] == "C1-init"
        assert detail["status"] == "PASS"
        assert detail["rc"] == 0
        assert detail["duration_ms"] == 5

    def test_checkpoint_fail_carries_failed_step(self, stub_repo, tmp_path):
        from e2e.runtime import record_result
        ctx = self._ctx(stub_repo, tmp_path)
        record_result(ctx, "C6", "loop", "FAIL", 2, None, 7,
                      {"failed_step": "tick"})
        (row,) = self._rows(ctx.ws)
        assert row["action"] == "checkpoint_fail"
        detail = json.loads(row["detail"])
        assert detail["failed_step"] == "tick"
        assert detail["step"] == "C6-loop"

    def test_blocked_and_skip_statuses_have_vocabulary(self, stub_repo,
                                                       tmp_path):
        from e2e.runtime import record_result
        ctx = self._ctx(stub_repo, tmp_path)
        record_result(ctx, "C5", "analysis", "BLOCKED", 5, None, 1,
                      {"stop_class": "stale-workspace"})
        record_result(ctx, "C6", "loop", "SKIP", None, None, 0, {})
        actions = [r["action"] for r in self._rows(ctx.ws)]
        assert actions == ["checkpoint_blocked", "checkpoint_skip"]

    # -- the oracle verdict is ONE row, never a checkpoint twin ------------

    def test_oracle_result_emits_single_oracle_verdict(self, stub_repo,
                                                       tmp_path):
        from e2e.runtime import record_result
        ctx = self._ctx(stub_repo, tmp_path)
        record_result(ctx, "ORACLE", "oracle", "PASS", 0, None, 5,
                      {"verdict": "PASS", "min_pair_ratio": 1.0})
        rows = self._rows(ctx.ws)
        assert len(rows) == 1, "oracle verdict must not get a checkpoint_* twin"
        row = rows[0]
        assert row["action"] == "oracle_verdict"
        detail = json.loads(row["detail"])
        assert detail["verdict"] == "PASS"
        assert detail["min_pair_ratio"] == 1.0
        assert detail["step"] == "ORACLE"

    # -- dispatch acts: attempt BEFORE result, both in the stream ----------

    def test_dry_dispatch_act_writes_attempt_then_result(self, stub_repo,
                                                         tmp_path):
        ctx = self._ctx(stub_repo, tmp_path)
        request = model.DispatchRequest(
            claim="C-004", workspace=str(ctx.ws),
            prompt_file=str(tmp_path / "ev" / "p.md"), run_id="a1")
        act = ctx.face.dispatch_act(request)
        assert act.outcome == "DISPATCHED"
        rows = self._rows(ctx.ws)
        assert [r["action"] for r in rows] == ["dispatch_attempt",
                                               "dispatch_result"]
        attempt = json.loads(rows[0]["detail"])
        assert attempt["claim"] == "C-004"
        assert attempt["mode"] == "dry"
        result = json.loads(rows[1]["detail"])
        assert rows[1]["exit"] == 0
        assert result["claim"] == "C-004"

    def _prompt_file(self, tmp_path: Path) -> str:
        path = tmp_path / "ev" / "p.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("dispatch prompt body\n", encoding="utf-8")
        return str(path)

    def test_auto_dispatch_failure_logs_full_stderr(self, stub_repo, tmp_path):
        class _FailRunner(ScriptedRunner):
            def run(self, cmd, cwd=None, timeout=None):
                self.calls.append(" ".join(str(c) for c in cmd))
                return model.CmdOutcome(rc=1, stdout="",
                                        stderr="FULL-STDERR-BODY",
                                        timed_out=False)

        runner = _FailRunner()
        ctx = self._ctx(stub_repo, tmp_path, mode="auto", runner=runner)
        request = model.DispatchRequest(
            claim="C-005", workspace=str(ctx.ws),
            prompt_file=self._prompt_file(tmp_path), run_id="a1")
        act = ctx.face.dispatch_act(request)
        assert act.outcome == "ERROR"
        rows = self._rows(ctx.ws)
        assert [r["action"] for r in rows] == ["dispatch_attempt",
                                               "dispatch_result"]
        result = json.loads(rows[1]["detail"])
        assert rows[1]["exit"] == 1
        # the diagnosis face: FULL stderr, not just the tail
        assert result["stderr"] == "FULL-STDERR-BODY"
        assert result["stderr_tail"] == "FULL-STDERR-BODY"
        assert result["timed_out"] is False
        # ActRecord carries the same slice (BOTH faces, per the ruling)
        assert act.detail["rc"] == 1
        assert "duration_ms" in act.detail and "timeout" in act.detail

    def test_auto_dispatch_attempt_detail_has_command_cwd_timeout(
            self, stub_repo, tmp_path):
        class _OkRunner(ScriptedRunner):
            def run(self, cmd, cwd=None, timeout=None):
                return model.CmdOutcome(rc=0, stdout="ok", stderr="")

        runner = _OkRunner()
        ctx = self._ctx(stub_repo, tmp_path, mode="auto", runner=runner)
        request = model.DispatchRequest(
            claim="C-004", workspace=str(ctx.ws),
            prompt_file=self._prompt_file(tmp_path), run_id="a1")
        ctx.face.dispatch_act(request)
        rows = self._rows(ctx.ws)
        attempt = json.loads(rows[0]["detail"])
        # the auto face runs IN the workspace (in-workspace dispatch), not
        # the repo
        assert attempt["cwd"] == str(ctx.ws)
        assert attempt["timeout"] == llm_faces.CLAUDE_ACT_TIMEOUT_S
        assert "claude" in attempt["command"]

    # -- convergence decisions + report integration ------------------------

    def test_convergence_decision_lands_in_stream(self, stub_repo, tmp_path):
        from e2e import audit
        ctx = self._ctx(stub_repo, tmp_path)
        audit.emit_convergence_decision(str(ctx.ws), "DISPATCH", tick=3,
                                        claim="C-004")
        (row,) = self._rows(ctx.ws)
        assert row["action"] == "convergence_decision"
        assert row["claim"] == "C-004"
        detail = json.loads(row["detail"])
        assert detail["decision"] == "DISPATCH"
        assert detail["tick"] == 3

    def test_report_audit_trail_populated(self, stub_repo, tmp_path):
        from e2e import audit
        ws = tmp_path / "ws"
        ctx = self._ctx(stub_repo, tmp_path, ws=ws)
        audit.emit(str(ctx.ws), "orchestrator", "checkpoint_pass")
        audit.emit(str(ctx.ws), "orchestrator", "dispatch_attempt",
                   claim="C-004")
        report = evidence.build_report(
            ctx.state, [], final_status="ALL-PASS", exit_code=0,
            final_verdict=None)
        trail = report["audit_trail"]
        assert trail["path"] == str(ws / self.AUDIT_RELPATH)
        assert trail["line_count"] == 2
        assert trail["first_ts"] and trail["last_ts"]
        cats = trail["categories"]
        assert cats["checkpoint"] == 1 and cats["dispatch"] == 1
        assert cats["decision"] == 0 and cats["oracle"] == 0

    def test_report_audit_trail_missing_stream_is_zeroed(self, stub_repo,
                                                         tmp_path):
        ctx = self._ctx(stub_repo, tmp_path)
        report = evidence.build_report(
            ctx.state, [], final_status="ALL-PASS", exit_code=0,
            final_verdict=None)
        trail = report["audit_trail"]
        assert trail["line_count"] == 0
        assert trail["first_ts"] is None and trail["last_ts"] is None
        assert trail["path"] == str(ctx.ws / self.AUDIT_RELPATH)

    # -- kernel-facing hooks: exist, ready, land in the stream -------------

    def test_kernel_hooks_ready_and_categorized(self, stub_repo, tmp_path):
        from e2e import audit
        ctx = self._ctx(stub_repo, tmp_path)
        audit.emit_method_family(str(ctx.ws), "C-004", "mod-crypto-js")
        audit.emit_strategy_composed(str(ctx.ws), "strategy-001",
                                     {"arms": ["static_re", "dynamic"]})
        audit.emit_posterior_update(str(ctx.ws), "static_re:beta",
                                    {"alpha": 2, "beta": 1})
        audit.emit_mainline_decision(str(ctx.ws), "C-004", dv=0.25)
        rows = self._rows(ctx.ws)
        assert [r["action"] for r in rows] == [
            "method_family_recorded", "strategy_composed",
            "posterior_updated", "mainline_decision"]
        mainline = json.loads(rows[3]["detail"])
        assert mainline["dv"] == 0.25
        stats = audit.read_stats(ctx.ws)
        assert stats["categories"]["kernel"] == 4

    def test_dispatch_envelope_method_family_optional_and_hooked(
            self, stub_repo, tmp_path):
        from e2e.checkpoints import _run_dispatch_act
        # default envelope: NO method_family key (byte-compatible)
        request = model.DispatchRequest(
            claim="C-004", workspace="/tmp/x", prompt_file="/tmp/p.md",
            run_id="a1")
        assert "method_family" not in request.to_dict()
        # a run configured with a method family: envelope carries it and
        # the dispatch act leaves a method_family_recorded event
        ctx = self._ctx(stub_repo, tmp_path)
        ctx.state.method_family = "mod-crypto-js"
        detail: dict = {"acts": []}
        terminal = _run_dispatch_act(ctx, "C-004", set(), detail)
        assert terminal is None
        actions = [r["action"] for r in self._rows(ctx.ws)]
        assert actions == ["method_family_recorded", "dispatch_attempt",
                           "dispatch_result"]

    def test_dispatch_envelope_kernel_samples_the_family(
            self, stub_repo, tmp_path):
        """W4 (#462): an UNDECLARED run gets a kernel-sampled family —
        the DTS call site 2 draw rides the envelope AND the stream
        records the receipt (real sampled values, not the inert
        placeholder)."""
        from e2e.checkpoints import _run_dispatch_act
        ctx = self._ctx(stub_repo, tmp_path)
        assert ctx.state.method_family == ""  # nothing declared
        detail: dict = {"acts": []}
        terminal = _run_dispatch_act(ctx, "C-004", set(), detail)
        assert terminal is None
        rows = self._rows(ctx.ws)
        actions = [r["action"] for r in rows]
        assert actions == ["method_family_recorded", "dispatch_attempt",
                           "dispatch_result"]
        rec = json.loads(rows[0]["detail"])
        fam = rec["method_family"]
        assert fam, "the sampler must produce a real family token"
        # the sampled family rode the envelope (inside kunglao_dispatch)
        prompt_file = (Path(ctx.state.evidence_dir)
                       / "dispatch-prompt-C-004.md")
        envelope = json.loads(
            prompt_file.read_text(encoding="utf-8").splitlines()[0])
        assert envelope["kunglao_dispatch"]["method_family"] == fam
        # the DTS receipt rides the row (the deterministic sampler face)
        assert rec["envelope"]["schema"] == "q-cell-sample/1"
        assert fam in rec["envelope"]["candidates"]
        # declared runs keep the proposal-channel face (no sample)
        ctx2 = self._ctx(stub_repo, tmp_path, ws=tmp_path / "ws-declared")
        ctx2.state.method_family = "static-decompile"
        _run_dispatch_act(ctx2, "C-005", set(), {"acts": []})
        rec2 = json.loads(self._rows(ctx2.ws)[0]["detail"])
        assert rec2["method_family"] == "static-decompile"
        assert rec2["envelope"] is None  # no sampler receipt for a proposal

    def test_dispatch_envelope_sampler_failure_stays_fail_open(
            self, stub_repo, tmp_path, monkeypatch, capsys):
        """W4 review MEDIUM-2: a sampler crash NEVER breaks the dispatch
        loop — the envelope mints undeclared (byte-compatible v1 shape),
        no method_family_recorded row, the dispatch act still lands."""
        from e2e.checkpoints import _run_dispatch_act

        def _boom(*_a, **_k):
            raise RuntimeError("sampler exploded")

        monkeypatch.setattr("rlvr.q_cells.sample_method_family", _boom)
        ctx = self._ctx(stub_repo, tmp_path)
        detail: dict = {"acts": []}
        terminal = _run_dispatch_act(ctx, "C-004", set(), detail)
        capsys.readouterr()
        assert terminal is None  # the loop proceeds
        rows = self._rows(ctx.ws)
        actions = [r["action"] for r in rows]
        assert actions == ["dispatch_attempt", "dispatch_result"]
        prompt_file = (Path(ctx.state.evidence_dir)
                       / "dispatch-prompt-C-004.md")
        envelope = json.loads(
            prompt_file.read_text(encoding="utf-8").splitlines()[0])
        assert "method_family" not in envelope["kunglao_dispatch"]

    def test_dispatch_envelope_prior_never_rides_retired_tokens(
            self, stub_repo, tmp_path, capsys):
        """W4 review MEDIUM-1: the history prior is INTERSECTED with the
        #432 registry — a retired token recorded while registered must
        never ride the prior again (the fail-closed vocabulary gate would
        lockstep-reject every dispatch in the workspace)."""
        from rlvr import q_cells
        ctx = self._ctx(stub_repo, tmp_path)
        # history: two rows of a since-retired token, one registered
        for _ in range(2):
            q_cells.append_observation(
                Path(ctx.ws), "abcdabcdabcd", "zz-retired-token", None,
                source="dispatch")
        q_cells.append_observation(
            Path(ctx.ws), "abcdabcdabcd", "static-decompile", None,
            source="dispatch")
        from e2e.checkpoints import _sample_envelope_family
        capsys.readouterr()
        fam, receipt = _sample_envelope_family(Path(ctx.ws))
        assert fam == "static-decompile", \
            "retired tokens never ride the prior"
        assert receipt["schema"] == "q-cell-sample/1"
        assert "zz-retired-token" not in receipt["candidates"]
        # outcome rows never enter any prior: five settlement rows for
        # the registered family must not inflate its share (the shared
        # proposal-channel definition — review MEDIUM)
        for _ in range(5):
            q_cells.observe(Path(ctx.ws), "abcdabcdabcd",
                            "static-decompile", 1.0)
        fam2, receipt2 = _sample_envelope_family(Path(ctx.ws))
        assert receipt2["candidates"]["static-decompile"]["p_llm"] \
            == pytest.approx(1.0), \
            "settlement-source rows must not inflate the prior"

    # -- the stats reader is tolerant --------------------------------------

    def test_stats_tolerate_corrupt_and_blank_lines(self, stub_repo, tmp_path):
        from e2e import audit
        ctx = self._ctx(stub_repo, tmp_path)
        audit.emit(str(ctx.ws), "orchestrator", "oracle_verdict")
        path = audit.audit_path(ctx.ws)
        with path.open("a", encoding="utf-8") as fh:
            fh.write("NOT JSON AT ALL\n")
            fh.write("\n")
        stats = audit.read_stats(ctx.ws)
        assert stats["line_count"] == 1
        assert stats["categories"]["oracle"] == 1

    def test_audit_emit_never_raises_on_unwritable_ws(self):
        from e2e import audit
        # a path THROUGH a file cannot be mkdir'd: emit must degrade, not raise
        blocked = Path("/dev/null") / "nope" / "runs" / "logs"
        assert audit.emit(str(blocked), "orchestrator",
                          "checkpoint_pass") is False


class TestClaimRollbackAndDynamicClaims:
    """#456 bug-2 (claim freed on BLOCKED/TIMEOUT/ERROR acts) and bug-3
    (PQ/claims resolved from the unit's task_spec — never the hardcoded
    py-derive templates)."""

    def _ctx(self, stub_repo, tmp_path, mode="auto"):
        ws = tmp_path / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        ev_dir = tmp_path / "ev"
        state = model.RunState(
            run_id="a1", unit="py-derive-v1", family="smoke",
            repo=str(stub_repo),
            task_dir=str(stub_repo / "eval/v1/tasks/smoke/py-derive-v1"),
            ws=str(ws), evidence_dir=str(ev_dir), budget_seconds=100,
            llm_mode=mode, started_ts="t", started_monotonic=0.0,
            anchors=dict(ANCHORS))
        runner = ScriptedRunner()
        face = llm_faces.face_for(mode, runner, ev_dir)
        return checkpoints.RunContext(
            state=state, runner=runner, face=face, clock=FakeClock(),
            sleep_fn=lambda _s: None)

    def test_blocked_act_frees_claim(self, stub_repo, tmp_path):
        # claude -p exits rc=0 with the agent reporting BLOCKED — the
        # signature #456 bug-2 case. The claim must leave the dispatched
        # set so the next tick can re-dispatch it.
        from e2e.checkpoints import _run_dispatch_act
        ctx = self._ctx(stub_repo, tmp_path)
        ctx.runner.on("claude", "-p", rc=0,
                      stdout='{"result": "BLOCKED: sandbox cannot reach '
                             'the workspace"}')
        dispatched: set = set()
        detail: dict = {"acts": []}
        assert _run_dispatch_act(ctx, "C-005", dispatched, detail) is None
        assert "C-005" not in dispatched
        assert detail["acts"][-1]["outcome"] == "BLOCKED"

    def test_error_act_frees_claim(self, stub_repo, tmp_path):
        from e2e.checkpoints import _run_dispatch_act
        ctx = self._ctx(stub_repo, tmp_path)
        ctx.runner.on("claude", "-p", rc=124, stdout="")
        dispatched: set = set()
        detail: dict = {"acts": []}
        assert _run_dispatch_act(ctx, "C-005", dispatched, detail) is None
        assert "C-005" not in dispatched
        assert detail["acts"][-1]["outcome"] == "ERROR"

    def test_clean_act_keeps_claim_dispatched(self, stub_repo, tmp_path):
        # rc=0, no BLOCKED text: the act is presumed landed — the claim
        # stays dispatched (healthy path, not a dead loop).
        from e2e.checkpoints import _run_dispatch_act
        ctx = self._ctx(stub_repo, tmp_path)
        ctx.runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
        dispatched: set = set()
        detail: dict = {"acts": []}
        assert _run_dispatch_act(ctx, "C-005", dispatched, detail) is None
        assert "C-005" in dispatched
        assert detail["acts"][-1]["outcome"] == "DISPATCHED"

    def test_resolve_claims_reads_top_level_task_spec(self, tmp_path):
        # kunglao-init's task_spec.yaml carries goal_verbatim at the TOP
        # LEVEL — round-4 read only anchors{} and silently fell back to
        # the py-derive defaults.
        from e2e import checkpoints
        spec = tmp_path / "task_spec.yaml"
        spec.write_text(
            "lane: algorithm\n"
            "task_id: rust-apk-beacon-v1\n"
            "goal_verbatim: Unpack target/beacon.apk and recover the "
            "ChaCha20 sigma word.\n"
            "success_criterion: Re-implementation reproduces probe "
            "outputs byte-exact.\n",
            encoding="utf-8")
        keep = (checkpoints.PRIMARY_QUESTIONS,
                checkpoints.CLAIM_APPENDS)
        try:
            checkpoints._resolve_claims(spec)
            statements = " ".join(c["statement"]
                                  for c in checkpoints.CLAIM_APPENDS)
            assert "derive.py" not in statements
            assert "rust-apk-beacon-v1" in statements
            assert "beacon.apk" in (
                checkpoints.PRIMARY_QUESTIONS[0]["question"])
        finally:
            checkpoints.PRIMARY_QUESTIONS, checkpoints.CLAIM_APPENDS = keep

    def test_resolve_claims_still_supports_nested_anchors(self, tmp_path):
        from e2e import checkpoints
        spec = tmp_path / "task_spec.yaml"
        spec.write_text(
            "task_id: legacy-unit\n"
            "anchors:\n"
            "  goal_verbatim: Recover the mutated constants.\n"
            "  success_criterion: Probes reproduce byte-exact.\n",
            encoding="utf-8")
        keep = (checkpoints.PRIMARY_QUESTIONS,
                checkpoints.CLAIM_APPENDS)
        try:
            checkpoints._resolve_claims(spec)
            assert "legacy-unit" in (
                checkpoints.CLAIM_APPENDS[0]["statement"])
        finally:
            checkpoints.PRIMARY_QUESTIONS, checkpoints.CLAIM_APPENDS = keep


class TestReviewFixes456R2:
    """Round-2 fixes from the independent #456/#457 review: word-boundary
    BLOCKED parse, never-raise _resolve_claims (incl. stale-global leak),
    fail-open audit serialization."""

    def _ctx(self, stub_repo, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        ev_dir = tmp_path / "ev"
        state = model.RunState(
            run_id="a1", unit="py-derive-v1", family="smoke",
            repo=str(stub_repo),
            task_dir=str(stub_repo / "eval/v1/tasks/smoke/py-derive-v1"),
            ws=str(ws), evidence_dir=str(ev_dir), budget_seconds=100,
            llm_mode="auto", started_ts="t", started_monotonic=0.0,
            anchors=dict(ANCHORS))
        runner = ScriptedRunner()
        face = llm_faces.face_for("auto", runner, ev_dir)
        return checkpoints.RunContext(
            state=state, runner=runner, face=face, clock=FakeClock(),
            sleep_fn=lambda _s: None)

    def test_blocked_parse_word_boundary_and_case(self, stub_repo, tmp_path):
        # "Blocked:" (mixed case) must parse — the old case-sensitive
        # scan resurrected the stuck-claim death loop
        from e2e.checkpoints import _run_dispatch_act
        ctx = self._ctx(stub_repo, tmp_path)
        ctx.runner.on("claude", "-p", rc=0,
                      stdout='{"result": "Blocked: cannot reach /tmp"}')
        d: dict = {"acts": []}
        _run_dispatch_act(ctx, "C-005", set(), d)
        assert d["acts"][-1]["outcome"] == "BLOCKED"

    def test_unblocked_word_does_not_parse_blocked(self, stub_repo,
                                                   tmp_path):
        from e2e.checkpoints import _run_dispatch_act
        ctx = self._ctx(stub_repo, tmp_path)
        ctx.runner.on("claude", "-p", rc=0,
                      stdout='{"result": "register unblocked and '
                             'written"}')
        dispatched: set = set()
        d: dict = {"acts": []}
        _run_dispatch_act(ctx, "C-005", dispatched, d)
        assert d["acts"][-1]["outcome"] == "DISPATCHED"
        assert "C-005" in dispatched  # landed act stays claimed

    def test_resolve_claims_never_raises_and_restores_defaults(
            self, tmp_path):
        from e2e import checkpoints as cp
        spec = tmp_path / "task_spec.yaml"
        spec.write_text("task_id: beacon-x\ngoal_verbatim: Unpack the "
                        "APK.\nsuccess_criterion: Probes match.\n",
                        encoding="utf-8")
        cp._resolve_claims(spec)  # resolve beacon-shaped claims first
        assert "beacon-x" in cp.CLAIM_APPENDS[0]["statement"]
        # every degenerate shape: no raise, defaults restored (no leak)
        for text in ("", "# comments only\n", "- a\n- b\n", "goal_verbatim: "
                     "[unclosed"):
            spec.write_text(text, encoding="utf-8")
            cp._resolve_claims(spec)
            assert "derive.py" in cp.CLAIM_APPENDS[0]["statement"], (
                f"stale claims leaked for spec={text!r}")
        # a fresh valid spec still resolves after the degenerates
        spec.write_text("task_id: unit-z\ngoal_verbatim: G\n"
                        "success_criterion: S\n", encoding="utf-8")
        cp._resolve_claims(spec)
        assert "unit-z" in cp.CLAIM_APPENDS[0]["statement"]
        cp.PRIMARY_QUESTIONS, cp.CLAIM_APPENDS = (
            cp._DEFAULT_PQ, cp._DEFAULT_CLAIMS)

    def test_audit_emit_degrades_on_unserializable_detail(self, tmp_path):
        from e2e import audit
        ws = tmp_path / "ws"
        ws.mkdir()
        class Opaque:
            def __repr__(self):
                return "<opaque>"
        # must not raise; must land a row with the degradation marker
        assert audit.emit_strategy_composed(
            str(ws), "s-1", strategy={"obj": Opaque()}) is True
        rows = [json.loads(line) for line
                in audit.audit_path(ws).read_text(encoding="utf-8")
                .splitlines() if line.strip()]
        assert rows, "no row landed for unserializable detail"
        assert "<unserializable" in rows[-1]["detail"]


class TestParallelDispatch459:
    """#459: when the ranker returns multiple dispatchable claims, ONE tick
    dispatches up to max-parallel acts concurrently — launch all (attempt
    rows in launch order), wait for all to land, per-act rollback, global
    budget guard between launches (never abandons in-flight acts)."""

    @pytest.fixture(autouse=True)
    def _clean_parallel_env(self, monkeypatch):
        # the default bound (3) must hold unless a test sets the env knob
        monkeypatch.delenv("KUNGLAO_E2E_MAX_PARALLEL", raising=False)

    def _ctx(self, stub_repo, tmp_path, mode="auto", runner=None):
        ws = tmp_path / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        ev_dir = tmp_path / "ev"
        state = model.RunState(
            run_id="p1", unit="py-derive-v1", family="smoke",
            repo=str(stub_repo),
            task_dir=str(stub_repo / "eval/v1/tasks/smoke/py-derive-v1"),
            ws=str(ws), evidence_dir=str(ev_dir), budget_seconds=14400,
            llm_mode=mode, started_ts="t", started_monotonic=1000.0,
            anchors=dict(ANCHORS))
        runner = runner or ScriptedRunner()
        face = llm_faces.face_for(mode, runner, ev_dir)
        return checkpoints.RunContext(
            state=state, runner=runner, face=face, clock=FakeClock(),
            sleep_fn=lambda _s: None)

    def _script_tick(self, runner, claims):
        """One tick worth of subprocesses: heartbeat, DISPATCH decision,
        multi-claim ranker (the #454 bare-array face), one claude act per
        claim (the act's prompt carries `claim: <id>` — the needle)."""
        runner.on("heartbeat_tick.py", rc=0)
        runner.on("convergence_check.py", "--json", rc=1,
                  stdout=json.dumps({"decision": "DISPATCH"}))
        runner.on("priority_ratio.py", "--json", rc=0,
                  stdout=json.dumps([{"claim_id": c, "action": "static_re"}
                                     for c in claims]))
        for c in claims:
            runner.on("claude", "-p", f"claim: {c}", rc=0,
                      stdout=json.dumps({"result": f"done {c}"}))

    def _dispatch_rows(self, ws):
        from e2e import audit
        rows = [json.loads(line) for line
                in audit.audit_path(ws).read_text(encoding="utf-8")
                .splitlines() if line.strip()]
        return [r for r in rows if str(r["action"]).startswith("dispatch_")]

    def test_two_claims_dispatch_concurrently_loop_waits_for_both(
            self, stub_repo, tmp_path):
        # the acceptance case: 2 dispatchable actions, both acts launched
        # in ONE tick, both recorded, both attempts before any result
        ctx = self._ctx(stub_repo, tmp_path)
        self._script_tick(ctx.runner, ["C-004", "C-005"])
        detail: dict = {"acts": [], "ticks": 1, "decision": None}
        dispatched: set = set()
        flow, terminal, _ms = checkpoints._loop_one_tick(
            ctx, dispatched, detail, tick_wait_seconds=0, total_ms=0)
        assert flow == "continue" and terminal is None
        # BOTH acts recorded — the tick waited for the whole wave
        assert {a["claim"] for a in detail["acts"]} == {"C-004", "C-005"}
        assert dispatched == {"C-004", "C-005"}  # clean landings stay claimed
        # audit stream: attempts in launch order, THEN results as they land
        rows = self._dispatch_rows(ctx.ws)
        assert [r["action"] for r in rows] == [
            "dispatch_attempt", "dispatch_attempt",
            "dispatch_result", "dispatch_result"]
        assert [r["claim"] for r in rows[:2]] == ["C-004", "C-005"]
        assert {r["claim"] for r in rows[2:]} == {"C-004", "C-005"}

    def test_max_parallel_bounds_the_wave(self, stub_repo, tmp_path,
                                          monkeypatch):
        monkeypatch.setenv("KUNGLAO_E2E_MAX_PARALLEL", "2")
        claims = ["C-004", "C-005", "C-006", "C-007", "C-008"]
        ctx = self._ctx(stub_repo, tmp_path)
        self._script_tick(ctx.runner, claims)
        detail: dict = {"acts": [], "ticks": 1, "decision": None}
        flow, terminal, _ms = checkpoints._loop_one_tick(
            ctx, set(), detail, tick_wait_seconds=0, total_ms=0)
        assert flow == "continue" and terminal is None
        # exactly 2 acts per tick wave — the top-2 ranked claims
        assert len(detail["acts"]) == 2
        assert {a["claim"] for a in detail["acts"]} == {"C-004", "C-005"}
        assert len([c for c in ctx.runner.calls
                    if c.startswith("claude -p")]) == 2

    def test_per_act_rollback_under_concurrency(self, stub_repo, tmp_path):
        # one act TIMEOUT, the other lands — ONLY the timed-out claim is
        # freed; a timeout on one act never kills the other
        class _TimeoutOneRunner(ScriptedRunner):
            def run(self, cmd, cwd=None, timeout=None):
                argv = " ".join(str(c) for c in cmd)
                if "claim: C-005" in argv:
                    self.calls.append(argv)
                    return model.CmdOutcome(rc=-1, stdout="",
                                            stderr="TIMEOUT after 1800s",
                                            timed_out=True)
                return super().run(cmd, cwd=cwd, timeout=timeout)

        ctx = self._ctx(stub_repo, tmp_path, runner=_TimeoutOneRunner())
        self._script_tick(ctx.runner, ["C-004", "C-005"])
        detail: dict = {"acts": [], "ticks": 1, "decision": None}
        dispatched: set = set()
        flow, terminal, _ms = checkpoints._loop_one_tick(
            ctx, dispatched, detail, tick_wait_seconds=0, total_ms=0)
        assert flow == "continue" and terminal is None
        outcomes = {a["claim"]: a["outcome"] for a in detail["acts"]}
        assert outcomes == {"C-004": "DISPATCHED", "C-005": "TIMEOUT"}
        assert dispatched == {"C-004"}  # only the timed-out claim freed

    def test_budget_exhaustion_mid_wave_stops_launches_not_inflight(
            self, stub_repo, tmp_path, monkeypatch):
        # the guard is GLOBAL: exhausted between launches stops NEW acts
        # but the already-launched in-flight act still lands + records
        ctx = self._ctx(stub_repo, tmp_path)
        self._script_tick(ctx.runner, ["C-004", "C-005"])
        guard_calls: list[int] = []

        def counting_guard(_ctx):
            guard_calls.append(1)
            return len(guard_calls) < 3  # tick-top + launch1 pass; stop @2nd

        monkeypatch.setattr(checkpoints, "_guard_budget", counting_guard)
        detail: dict = {"acts": [], "ticks": 1, "decision": None}
        dispatched: set = set()
        flow, terminal, _ms = checkpoints._loop_one_tick(
            ctx, dispatched, detail, tick_wait_seconds=0, total_ms=0)
        # the tick completes: the in-flight act landed, no budget stop here
        assert flow == "continue" and terminal is None
        assert len(guard_calls) == 3  # guard consulted per launch
        assert [a["claim"] for a in detail["acts"]] == ["C-004"]
        assert dispatched == {"C-004"}
        assert len([c for c in ctx.runner.calls
                    if c.startswith("claude -p")]) == 1

    def test_max_parallel_constant_and_env_override(self, monkeypatch):
        assert checkpoints.MAX_PARALLEL_DISPATCH == 3
        monkeypatch.setenv("KUNGLAO_E2E_MAX_PARALLEL", "5")
        assert checkpoints._max_parallel_dispatch() == 5
        monkeypatch.setenv("KUNGLAO_E2E_MAX_PARALLEL", "0")
        assert checkpoints._max_parallel_dispatch() == 1  # floor: never 0
        monkeypatch.setenv("KUNGLAO_E2E_MAX_PARALLEL", "garbage")
        assert checkpoints._max_parallel_dispatch() == 3  # unparseable: default
        monkeypatch.delenv("KUNGLAO_E2E_MAX_PARALLEL")
        assert checkpoints._max_parallel_dispatch() == 3

    def test_ranked_claims_returns_all_dispatchable_in_rank_order(self):
        from e2e.runtime import ranked_claims

        def out(stdout: str):
            return model.CmdOutcome(rc=0, stdout=stdout, stderr="",
                                    timed_out=False)

        # the real ranker face: pretty-printed bare array, rank order kept
        real = ("[\n  {\"claim_id\": \"C-005\", \"action\": "
                "\"evidence_collection\", \"score\": 0.976},\n  "
                "{\"claim_id\": \"C-004\", \"action\": "
                "\"protocol_reconstruction\", \"score\": 0.911}\n]")
        assert ranked_claims(out(real)) == ["C-005", "C-004"]
        # object envelope (backward face)
        env = '{"actions": [{"claim_id": "C-001"}, {"claim_id": "C-002"}]}'
        assert ranked_claims(out(env)) == ["C-001", "C-002"]
        # ranked_order face
        assert ranked_claims(out('{"ranked_order": ["C-009", "C-007"]}')
                             ) == ["C-009", "C-007"]
        # a repeated id (envelope face, both key spellings) never
        # double-dispatches in one wave — dedup keeps first-rank order
        dup = ('{"actions": [{"claim_id": "C-004"}, {"claim_id": "C-005"}, '
               '{"claim": "C-004"}]}')
        assert ranked_claims(out(dup)) == ["C-004", "C-005"]
        # empty / garbage: no claims, never a guessed id
        assert ranked_claims(out("")) == []
        assert ranked_claims(out("not json")) == []


# ===========================================================================
# #472 — pre-release exception/logging audit fixes (RED-first batch)
# ===========================================================================

class TestWaveActCage472:
    """HIGH #1: a raising act never loses the wave — every dispatched
    act lands in structured evidence (cage = record + move on)."""

    def _req(self, ws, claim):
        return model.DispatchRequest(claim=claim, workspace=str(ws),
                                     prompt_file="", run_id="r1")

    def _rows(self, ws):
        from e2e import audit
        return [json.loads(line) for line
                in audit.audit_path(ws).read_text(encoding="utf-8")
                .splitlines() if line.strip()]

    def test_raising_act_mid_wave_is_caged_and_siblings_land(
            self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()

        class _FlakyFace:
            mode = "stub"

            def run_dispatch(self, req, handle=None):
                if req.claim == "C-005":
                    raise OSError("simulated act crash")
                return llm_faces.ActRecord(req.claim, self.mode,
                                           "DISPATCHED", {})

        launched = [(self._req(ws, c), None)
                    for c in ("C-004", "C-005", "C-006")]
        acts = llm_faces.run_dispatch_parallel(_FlakyFace(), launched)
        outcomes = {a.claim: a.outcome for a in acts}
        assert outcomes == {"C-004": "DISPATCHED", "C-005": "ERROR",
                            "C-006": "DISPATCHED"}
        err = next(a for a in acts if a.outcome == "ERROR")
        assert err.mode == "stub"  # the record preserves the face
        assert "OSError" in err.detail["error"]
        # the caged act's ATTEMPT/RESULT pair completes with an
        # EXPLAINED rc-null — not the orchestrator no-subprocess reason
        results = {r["claim"]: r for r in self._rows(ws)
                   if r["action"] == "dispatch_result"}
        assert results["C-005"]["exit"] is None
        assert results["C-005"]["null_reasons"]["exit"] == (
            "wave_act_exception")
        assert "OSError" in results["C-005"]["detail"]

    def test_wave_of_one_raising_act_is_caged(self, tmp_path):
        # the inline wave-of-one path carries the same cage — the common
        # single-claim tick must not die with the wave's records lost
        ws = tmp_path / "ws"
        ws.mkdir()

        class _BoomFace:
            mode = "stub"

            def run_dispatch(self, req, handle=None):
                raise RuntimeError("single-act wave crash")

        acts = llm_faces.run_dispatch_parallel(
            _BoomFace(), [(self._req(ws, "C-004"), None)])
        assert len(acts) == 1
        assert acts[0].outcome == "ERROR" and acts[0].claim == "C-004"

    def test_auto_face_missing_prompt_file_yields_error_record(
            self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        face = llm_faces.AutoLlmFace(ScriptedRunner(), tmp_path / "ev")
        req = model.DispatchRequest(
            claim="C-004", workspace=str(ws),
            prompt_file=str(tmp_path / "gone.md"), run_id="r1")
        act = face.run_dispatch(req)  # must NOT raise
        assert act.outcome == "ERROR" and act.claim == "C-004"
        row = [r for r in self._rows(ws)
               if r["action"] == "dispatch_result"][0]
        assert row["exit"] is None
        assert row["null_reasons"]["exit"] == "prompt_file_unreadable"


class TestResolveClaimsWarn472:
    """HIGH #2: spec-UNREADABLE warns; anchors-absent and file-absent
    stay silent-legitimate (the #456 documented fallback faces)."""

    def _clear_dedupe(self):
        import kunglao_log
        kunglao_log._WARN_LAST.pop("e2e.resolve_claims", None)

    def test_corrupt_spec_warns_and_restores_defaults(self, tmp_path,
                                                      capsys):
        from e2e import checkpoints as cp
        spec = tmp_path / "task_spec.yaml"
        spec.write_text("goal_verbatim: [unclosed\n", encoding="utf-8")
        self._clear_dedupe()
        capsys.readouterr()
        cp._resolve_claims(spec)
        assert "derive.py" in cp.CLAIM_APPENDS[0]["statement"]
        err = capsys.readouterr().err
        assert "e2e.resolve_claims" in err
        assert "defaults restored" in err

    def test_non_mapping_spec_warns(self, tmp_path, capsys):
        from e2e import checkpoints as cp
        spec = tmp_path / "task_spec.yaml"
        spec.write_text("- a\n- b\n", encoding="utf-8")
        self._clear_dedupe()
        capsys.readouterr()
        cp._resolve_claims(spec)
        err = capsys.readouterr().err
        assert "e2e.resolve_claims" in err
        assert "not a mapping" in err

    def test_anchors_absent_spec_stays_silent(self, tmp_path, capsys):
        from e2e import checkpoints as cp
        spec = tmp_path / "task_spec.yaml"
        spec.write_text("task_id: u\nother: x\n", encoding="utf-8")
        self._clear_dedupe()
        capsys.readouterr()
        cp._resolve_claims(spec)
        assert "derive.py" in cp.CLAIM_APPENDS[0]["statement"]
        assert "e2e.resolve_claims" not in capsys.readouterr().err

    def test_missing_spec_file_stays_silent(self, tmp_path, capsys):
        from e2e import checkpoints as cp
        spec = tmp_path / "never-written.yaml"
        self._clear_dedupe()
        capsys.readouterr()
        cp._resolve_claims(spec)
        assert "derive.py" in cp.CLAIM_APPENDS[0]["statement"]
        assert "e2e.resolve_claims" not in capsys.readouterr().err


class TestAuditEmitSafeNumerics472:
    """MEDIUM #4 (twin site): e2e.audit's event dict coerces garbage
    numerics to documented nulls — the twin of kunglao_log's cage."""

    def test_dispatch_result_garbage_numerics_coerce(self, tmp_path):
        from e2e import audit
        ws = tmp_path / "ws"
        ws.mkdir()
        assert audit.emit_dispatch_result(
            str(ws), "C-004", mode="dry", rc="not-an-int",
            duration_ms="garbage") is True
        rows = [json.loads(line) for line
                in audit.audit_path(ws).read_text(encoding="utf-8")
                .splitlines() if line.strip()]
        row = rows[-1]
        assert row["exit"] is None and row["duration_ms"] is None
        assert row["null_reasons"]["exit"] == "value_unparseable"
        assert row["null_reasons"]["duration_ms"] == "value_unparseable"


class TestPipelineStepCage472:
    """MEDIUM #6: a raising checkpoint step lands a FAIL result and the
    report is still written (finalize runs) — the harness's product IS
    the report; a crash must not lose it."""

    def test_raising_step_lands_fail_report(self, stub_repo, tmp_path,
                                            monkeypatch):
        def _boom(_ctx):
            raise RuntimeError("checkpoint exploded")

        monkeypatch.setattr(checkpoints, "checkpoint_c1", _boom)
        sink: list = []
        rc = checkpoints.run_pipeline(
            model.PipelineArgs(unit="py-derive-v1", repo=stub_repo,
                               ws_root=tmp_path / "wsroot",
                               budget_seconds=100, llm_mode="dry",
                               tick_wait_seconds=0, run_id="cage1"),
            cmd_runner=ScriptedRunner(), clock=FakeClock(),
            sleep_fn=FakeClock().sleep, report_sink=sink)
        assert rc == model.EXIT_CHECKPOINT_FAIL
        report = sink[0]
        assert report["final_status"] == "FAIL"
        sid = model.step_id("C1", "init")
        by_step = {c["step"]: c for c in report["checkpoints"]}
        assert by_step[sid]["status"] == "FAIL"
        assert "RuntimeError: checkpoint exploded" in (
            by_step[sid]["detail"]["error"])


class TestFactLanding473:
    """#473: envelope carries the incremental-facts + STATUS contract;
    act timeout is env-overridable with a safe default."""

    def _ctx(self, stub_repo, tmp_path, mode="dry"):
        ws = tmp_path / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        ev_dir = tmp_path / "ev"
        state = model.RunState(
            run_id="a1", unit="py-derive-v1", family="smoke",
            repo=str(stub_repo),
            task_dir=str(stub_repo / "eval/v1/tasks/smoke/py-derive-v1"),
            ws=str(ws), evidence_dir=str(ev_dir), budget_seconds=100,
            llm_mode=mode, started_ts="t", started_monotonic=0.0,
            anchors=dict(ANCHORS))
        return checkpoints.RunContext(
            state=state, runner=ScriptedRunner(),
            face=llm_faces.face_for(mode, ScriptedRunner(), ev_dir),
            clock=FakeClock(), sleep_fn=lambda _s: None)

    def test_envelope_carries_fact_landing_contract(self, stub_repo,
                                                    tmp_path):
        from e2e.checkpoints import _run_dispatch_act
        ctx = self._ctx(stub_repo, tmp_path)
        detail: dict = {"acts": []}
        _run_dispatch_act(ctx, "C-005", set(), detail)
        prompt = (Path(ctx.state.evidence_dir)
                  / "dispatch-prompt-C-005.md").read_text(encoding="utf-8")
        assert "INCREMENTALLY" in prompt
        assert "positive_observation" in prompt
        assert "STATUS: DONE" in prompt and "STATUS: BLOCKED" in prompt
        assert "zero facts is a failed act" in prompt

    def test_act_timeout_env_override_and_garbage_fallback(self, monkeypatch):
        import importlib
        from e2e import llm_faces as lf
        monkeypatch.setenv("KUNGLAO_E2E_ACT_TIMEOUT_S", "3600")
        assert importlib.reload(lf).CLAUDE_ACT_TIMEOUT_S == 3600
        monkeypatch.setenv("KUNGLAO_E2E_ACT_TIMEOUT_S", "garbage")
        assert importlib.reload(lf).CLAUDE_ACT_TIMEOUT_S == 1800
        monkeypatch.setenv("KUNGLAO_E2E_ACT_TIMEOUT_S", "-5")
        assert importlib.reload(lf).CLAUDE_ACT_TIMEOUT_S == 1800
        monkeypatch.delenv("KUNGLAO_E2E_ACT_TIMEOUT_S", raising=False)
        assert importlib.reload(lf).CLAUDE_ACT_TIMEOUT_S == 1800


class TestVerifierDispatch484:
    """#484: DISPATCH_VERIFIER decisions dispatch a verifier act — the
    missing consumer that promotes maker products toward CONVERGED."""

    def _ctx(self, stub_repo, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        ev_dir = tmp_path / "ev"
        state = model.RunState(
            run_id="a1", unit="py-derive-v1", family="smoke",
            repo=str(stub_repo),
            task_dir=str(stub_repo / "eval/v1/tasks/smoke/py-derive-v1"),
            ws=str(ws), evidence_dir=str(ev_dir), budget_seconds=100,
            llm_mode="auto", started_ts="t", started_monotonic=0.0,
            anchors=dict(ANCHORS))
        runner = ScriptedRunner()
        return checkpoints.RunContext(
            state=state, runner=runner,
            face=llm_faces.face_for("auto", runner, ev_dir),
            clock=FakeClock(), sleep_fn=lambda _s: None)

    def test_verifier_act_fires_with_contract(self, stub_repo, tmp_path):
        from e2e.checkpoints import _run_verifier_act
        ctx = self._ctx(stub_repo, tmp_path)
        ctx.runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
        dispatched: set = set()
        detail: dict = {"acts": []}
        assert _run_verifier_act(ctx, "C-005", dispatched, detail) is None
        prompt = (Path(ctx.state.evidence_dir)
                  / "dispatch-prompt-V-C-005.md").read_text(encoding="utf-8")
        assert "kunglao-verifier" in prompt
        assert "you VERIFY, you never make" in prompt
        assert "NEVER write facts" in prompt
        assert "STATUS: DONE" in prompt
        assert "V:C-005" in dispatched  # in-flight; freed on failure only

    def test_verifier_act_rollback_on_timeout(self, stub_repo, tmp_path):
        from e2e.checkpoints import _run_verifier_act
        ctx = self._ctx(stub_repo, tmp_path)
        ctx.runner.on("claude", "-p", rc=-1, stdout="")
        dispatched: set = set()
        detail: dict = {"acts": []}
        _run_verifier_act(ctx, "C-005", dispatched, detail)
        assert "V:C-005" not in dispatched
        assert detail["acts"][-1]["outcome"] == "ERROR"  # rc!=0, not timed

    def test_loop_dispatches_verifier_on_decision(self, stub_repo,
                                                  tmp_path, monkeypatch):
        # convergence says DISPATCH_VERIFIER → a verifier act launches
        ctx = self._ctx(stub_repo, tmp_path)
        ctx.state.budget_seconds = 10_000  # FakeClock epoch exceeds 100
        ctx.runner.on("heartbeat_tick", rc=0, stdout="ok")
        ctx.runner.on("convergence_check", rc=1,
                      stdout='{"decision": "DISPATCH_VERIFIER"}')
        ctx.runner.on("priority_ratio", rc=0,
                      stdout='[{"claim_id": "C-005"}]')
        ctx.runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
        from e2e.checkpoints import _loop_one_tick
        flow, terminal, _ = _loop_one_tick(ctx, set(), {"acts": []}, 0, 0)
        assert flow == "continue" and terminal is None
        launched = [Path(c) for c in [f"dispatch-prompt-V-C-005.md"]]
        assert (Path(ctx.state.evidence_dir) / "dispatch-prompt-V-C-005.md"
                ).is_file()


class TestYamlCorruption482:
    """#482: loud-stop on consecutive CRASHED, resume breaker reset,
    and the YAML-safe state writer."""

    def _ctx(self, stub_repo, tmp_path, budget=10_000):
        ws = tmp_path / "ws"
        ws.mkdir(parents=True, exist_ok=True)
        ev_dir = tmp_path / "ev"
        state = model.RunState(
            run_id="a1", unit="py-derive-v1", family="smoke",
            repo=str(stub_repo),
            task_dir=str(stub_repo / "eval/v1/tasks/smoke/py-derive-v1"),
            ws=str(ws), evidence_dir=str(ev_dir), budget_seconds=budget,
            llm_mode="dry", started_ts="t", started_monotonic=0.0,
            anchors=dict(ANCHORS))
        return checkpoints.RunContext(
            state=state, runner=ScriptedRunner(),
            face=llm_faces.face_for("dry", ScriptedRunner(), ev_dir),
            clock=FakeClock(), sleep_fn=lambda _s: None)

    def test_three_crashed_ticks_stop_loudly(self, stub_repo, tmp_path,
                                             monkeypatch):
        monkeypatch.setenv("KUNGLAO_CRASHED_STOP_N", "3")
        ctx = self._ctx(stub_repo, tmp_path)
        ctx.runner.on("heartbeat_tick", rc=0, stdout="ok")
        ctx.runner.on("convergence_check", rc=65,
                      stdout='{"decision": "CRASHED"}',
                      stderr="yaml.scanner.ScannerError: mapping values")
        from e2e.checkpoints import _loop_one_tick
        detail: dict = {"acts": []}
        terminal = None
        for tick in range(1, 4):
            flow, terminal, _ = _loop_one_tick(
                ctx, set(), detail, 0, 0)
            assert flow == "continue" or terminal is not None
            if terminal is not None:
                break
        assert terminal is not None, "3 crashed ticks must stop"
        assert terminal.status == model.BLOCKED
        det = terminal.detail
        assert det["stop_class"] == "convergence-crashed"
        assert det["crashed_ticks"] == 3
        assert "ScannerError" in det["stderr_tail"]

    def test_single_crashed_tick_does_not_stop(self, stub_repo, tmp_path,
                                               monkeypatch):
        monkeypatch.setenv("KUNGLAO_CRASHED_STOP_N", "3")
        ctx = self._ctx(stub_repo, tmp_path)
        ctx.runner.seq("heartbeat_tick", outcomes=[(0, "ok"), (0, "ok")])
        ctx.runner.seq("convergence_check", outcomes=[
            (65, '{"decision": "CRASHED"}'),
            (1, '{"decision": "DISPATCH"}')])
        ctx.runner.on("priority_ratio", rc=0,
                      stdout='[{"claim_id": "C-005"}]')
        from e2e.checkpoints import _loop_one_tick
        for _ in range(2):
            flow, terminal, _ = _loop_one_tick(
                ctx, set(), {"acts": []}, 0, 0)
            assert terminal is None

    def test_ws_yaml_set_with_colon_roundtrips(self, tmp_path):
        import subprocess, sys as _sys
        f = tmp_path / "reg.yaml"
        f.write_text("claims:\n- id: C-004\n  evidence: old\n",
                     encoding="utf-8")
        prose = "mapped (facts/F007: 0x19d68 AES-shaped 0x1a1fc pass)"
        r = subprocess.run(
            [_sys.executable, "scripts/ws_yaml.py", "set", str(f),
             "claims.0.evidence", f'"{prose}"'],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        import yaml
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert doc["claims"][0]["evidence"] == prose

    def test_ws_yaml_get_del_and_exit_codes(self, tmp_path):
        import subprocess, sys as _sys
        f = tmp_path / "s.yaml"
        f.write_text("a:\n  b: 1\n", encoding="utf-8")
        r = subprocess.run(
            [_sys.executable, "scripts/ws_yaml.py", "get", str(f), "a.b"],
            capture_output=True, text=True)
        assert r.returncode == 0 and "1" in r.stdout
        r = subprocess.run(
            [_sys.executable, "scripts/ws_yaml.py", "del", str(f), "a.b"],
            capture_output=True, text=True)
        assert r.returncode == 0
        r = subprocess.run(
            [_sys.executable, "scripts/ws_yaml.py", "get", str(f), "a.z"],
            capture_output=True, text=True)
        assert r.returncode == 5
