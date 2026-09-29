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

    def on(self, *needles: str, rc: int = 0, stdout: str = "") -> None:
        self.rules.append((needles, rc, stdout))

    def seq(self, *needles: str, outcomes: list[tuple[int, str]]) -> None:
        self.queues.append((needles, list(outcomes)))

    def run(self, cmd: list[str], cwd: Path | None = None,
            timeout: int | None = None) -> model.CmdOutcome:
        argv = [str(c) for c in cmd]
        self.calls.append(" ".join(argv))
        for needles, queue in self.queues:
            if all(n in " ".join(argv) for n in needles) and queue:
                rc, stdout = queue.pop(0)
                return model.CmdOutcome(rc=rc, stdout=stdout, stderr="")
        for needles, rc, stdout in self.rules:
            if all(n in " ".join(argv) for n in needles):
                return model.CmdOutcome(rc=rc, stdout=stdout, stderr="")
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
