# -*- coding: utf-8 -*-
"""tests/test_completion_681.py — issue #681: the completion judgment
disagrees with the independent checker.

Measured (e2e audit 2026-10-11): every checker-PASSING delivery was
reported BLOCKED/PARTIAL by the pipeline, and only 1 of 93 runs ever
reached ORACLE. Root causes pinned here:

  1. the stage sequence breaks on first FAIL/BLOCKED, so the ORACLE
     never judges the best-so-far candidate;
  2. resolve_candidate hardcodes artifacts/derive_reimpl.py when
     task.yaml does not declare checker.candidate — wrong suffix for
     .go/.js/.json/.txt families (a silent .py fallback);
  3. finalize trusts the pipeline's own final_status without ever
     running the unit checker on what was actually delivered.

The fix contract (D-681.1 / D-681.2):
  - completion = the independent unit checker's PASS (label
    "checker-PASS", exit 0) even when an intermediate stage blocked;
  - an undeclared candidate on a mismatching family suffix is a TYPED
    candidate-undeclared event, never a silent .py fallback;
  - runs/deliverable-best-so-far.json always points at the current
    best candidate (monotone delivery).
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_contract as ec  # noqa: E402
from e2e import checkpoints, llm_faces, model  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "eval" / "v1").is_dir(),
    reason="the eval corpus is local-only material (never tracked)")

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# fixtures — a self-contained stub repo (mirrors test_e2e_runner's shape)
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

REAL_EVIDENCE_DOC = {
    "schema": "kunglao-eval-evidence/1",
    "faces": {"replay": {"matched": 12, "count": 12}},
    "verdict": "PASS",
}


@pytest.fixture()
def stub_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    task = repo / "eval/v1/tasks/smoke/py-derive-v1"
    (task / "target").mkdir(parents=True)
    (task / "target/derive.py").write_text(DERIVE_PY, encoding="utf-8")
    (task / "task.yaml").write_text(TASK_YAML, encoding="utf-8")
    (task / "checker.py").write_text("# checker\n", encoding="utf-8")
    (repo / "scripts").mkdir()
    return repo


class ScriptedRunner(llm_faces.CommandRunner):
    """The subprocess seam: match argv patterns to scripted outcomes."""

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
                stderr = item[2] if len(item) > 2 else ""
                return model.CmdOutcome(rc=item[0], stdout=item[1],
                                        stderr=stderr)
        for needles, rc, stdout, stderr in self.rules:
            if all(n in " ".join(argv) for n in needles):
                return model.CmdOutcome(rc=rc, stdout=stdout, stderr=stderr)
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


def _script_common(runner: ScriptedRunner, stub_repo: Path,
                   ws_root: Path, run_id: str) -> None:
    """Everything through C6 green (the shapes from test_e2e_runner)."""
    settings = ws_root / f"e2e-ws-{run_id}/.claude/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"hooks": {"PreToolUse": [
        {"hooks": [{"command":
                    "python3 hooks/lib_kunglao.py --precheck"}]}]}}),
        encoding="utf-8")
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


def _script_checker_pass(runner: ScriptedRunner, stub_repo: Path) -> None:
    """The independent checker's REAL stdout shape (F1) — VERDICT PASS
    with a 12/12 replay evidence file in the repo tree."""
    ev_rel = "runs/eval/evidence-681.json"
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


def _patch_gate(monkeypatch, ok: bool) -> None:
    import register_proven_gate as rpg

    def fake_emit(ws, new_text, old_text=None):
        log = Path(ws) / "runs/logs/kunglao-2026-09-28.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        rows = [json.dumps({
            "ts": "2026-09-28T10:00:00Z", "actor": "hook:write_guard",
            "action": "claim_settled", "claim": cid, "trace_id": "tr-1",
            "duration_ms": 1,
            "detail": "{\"from\": \"OPEN\", \"to\": \"PROVEN\", "
                      "\"tools\": [], \"outcome\": \"PROVEN\"}"}) + "\n"
                for cid in ("C-004", "C-005")]
        log.write_text("".join(rows), encoding="utf-8")
        return len(rows)

    monkeypatch.setattr(rpg, "check_register_transitions",
                        lambda ws, new, old=None: {
                            "ok": ok, "violations": [] if ok else [
                                "C-004: latest verify-note outcome != passes"],
                            "waivers": []})
    monkeypatch.setattr(rpg, "emit_settlements", fake_emit)


# ---------------------------------------------------------------------------
# T2/D-681.1 — the checker is the completion oracle
# ---------------------------------------------------------------------------

class TestCheckerIsCompletionOracle:
    def test_checker_pass_is_completion_even_if_pipeline_reported_blocked(
            self, stub_repo, tmp_path, monkeypatch):
        """A stage BLOCKED (C7 convergence) + unit checker VERDICT PASS on
        the delivered candidate = completion: the final label is the
        distinct checker-PASS (never BLOCKED/PARTIAL), exit 0, and the
        ORACLE evidence lands even though the stage loop broke early."""
        runner = ScriptedRunner()
        clock = FakeClock()
        ws_root = tmp_path / "wsroot"
        run_id = "681-blocked-pass"
        _script_common(runner, stub_repo, ws_root, run_id)
        # C6-pre DISPATCH -> loop DISPATCH -> loop CONVERGED (loop exits)
        # -> C7 sees DISPATCH: convergence never lands, C7 BLOCKED
        runner.seq("convergence_check.py", "--json", outcomes=[
            (1, json.dumps({"decision": "DISPATCH"})),
            (1, json.dumps({"decision": "DISPATCH"})),
            (0, json.dumps({"decision": "CONVERGED"})),
            (1, json.dumps({"decision": "DISPATCH"})),
        ])
        _script_checker_pass(runner, stub_repo)
        _patch_gate(monkeypatch, ok=True)
        # the agent's best-so-far delivery sits at the resolved path
        ws = ws_root / f"e2e-ws-{run_id}"
        (ws / "artifacts").mkdir(parents=True, exist_ok=True)
        (ws / "artifacts/derive_reimpl.py").write_text(DERIVE_PY,
                                                       encoding="utf-8")
        try:
            rc = checkpoints.run_pipeline(
                model.PipelineArgs(
                    unit="py-derive-v1", repo=stub_repo, ws_root=ws_root,
                    budget_seconds=14400, llm_mode="dry",
                    tick_wait_seconds=0, run_id=run_id),
                cmd_runner=runner, clock=clock, sleep_fn=clock.sleep)
        finally:
            monkeypatch.undo()

        report = json.loads(
            (stub_repo / f"runs/e2e/{run_id}/report.json")
            .read_text(encoding="utf-8"))
        assert report["final_status"] == "checker-PASS", report
        assert report["final_status"] not in ("BLOCKED", "PARTIAL")
        assert rc == model.EXIT_OK, rc
        # the ORACLE ran at finalize and its verdict rides the report
        by_step = {c["step"]: c for c in report["checkpoints"]}
        assert by_step["ORACLE"]["status"] == "PASS"
        assert report["oracle"]["verdict"] == "PASS"
        # the blocked stage stays visible — checker-PASS is a distinct
        # label, not a laundering of the C7 BLOCKED row
        assert by_step["C7-completion"]["status"] == "BLOCKED"

    def test_checker_fail_keeps_the_blocked_label(self, stub_repo, tmp_path,
                                                  monkeypatch):
        """The ruling only upgrades on a checker PASS; a checker FAIL (or
        a missing evidence file) keeps the pipeline's own label."""
        runner = ScriptedRunner()
        clock = FakeClock()
        ws_root = tmp_path / "wsroot"
        run_id = "681-blocked-fail"
        _script_common(runner, stub_repo, ws_root, run_id)
        runner.seq("convergence_check.py", "--json", outcomes=[
            (1, json.dumps({"decision": "DISPATCH"})),
            (1, json.dumps({"decision": "DISPATCH"})),
            (0, json.dumps({"decision": "CONVERGED"})),
            (1, json.dumps({"decision": "DISPATCH"})),
        ])
        # checker runs but the verdict is FAIL
        ev_rel = "runs/eval/evidence-681-f.json"
        ev = stub_repo / ev_rel
        ev.parent.mkdir(parents=True, exist_ok=True)
        doc = json.loads(json.dumps(REAL_EVIDENCE_DOC))
        doc["faces"]["replay"]["matched"] = 9
        ev.write_text(json.dumps(doc), encoding="utf-8")
        runner.on("checker.py", "--candidate", rc=1, stdout=(
            f"EVIDENCE {ev_rel}\nVERDICT FAIL\n"))
        _patch_gate(monkeypatch, ok=True)
        ws = ws_root / f"e2e-ws-{run_id}"
        (ws / "artifacts").mkdir(parents=True, exist_ok=True)
        (ws / "artifacts/derive_reimpl.py").write_text(DERIVE_PY,
                                                       encoding="utf-8")
        try:
            rc = checkpoints.run_pipeline(
                model.PipelineArgs(
                    unit="py-derive-v1", repo=stub_repo, ws_root=ws_root,
                    budget_seconds=14400, llm_mode="dry",
                    tick_wait_seconds=0, run_id=run_id),
                cmd_runner=runner, clock=clock, sleep_fn=clock.sleep)
        finally:
            monkeypatch.undo()

        report = json.loads(
            (stub_repo / f"runs/e2e/{run_id}/report.json")
            .read_text(encoding="utf-8"))
        assert report["final_status"] == "BLOCKED"
        assert rc == model.EXIT_BLOCKED

    def test_partial_with_checker_pass_upgrades_too(self, stub_repo, tmp_path,
                                                    monkeypatch):
        """T4: the ORACLE-on-partial face — a budget-exhausted PARTIAL run
        with a delivered candidate is judged by the checker; PASS upgrades
        the label."""
        runner = ScriptedRunner()
        clock = FakeClock()
        ws_root = tmp_path / "wsroot"
        run_id = "681-partial-pass"
        _script_common(runner, stub_repo, ws_root, run_id)
        # never converges: the loop spins until the budget guard trips
        runner.on("convergence_check.py", "--json", rc=1,
                  stdout=json.dumps({"decision": "DISPATCH"}))
        _script_checker_pass(runner, stub_repo)
        _patch_gate(monkeypatch, ok=True)
        ws = ws_root / f"e2e-ws-{run_id}"
        (ws / "artifacts").mkdir(parents=True, exist_ok=True)
        (ws / "artifacts/derive_reimpl.py").write_text(DERIVE_PY,
                                                       encoding="utf-8")
        # timeline: start 1000; C5 sleeps 60 -> 1060; loop iter1 sleeps
        # 60 -> 1120; iter2 guard sees consumed 120 == budget -> partial
        try:
            rc = checkpoints.run_pipeline(
                model.PipelineArgs(
                    unit="py-derive-v1", repo=stub_repo, ws_root=ws_root,
                    budget_seconds=120, llm_mode="dry", tick_wait_seconds=60,
                    run_id=run_id, max_ticks=30),
                cmd_runner=runner, clock=clock, sleep_fn=clock.sleep)
        finally:
            monkeypatch.undo()

        report = json.loads(
            (stub_repo / f"runs/e2e/{run_id}/report.json")
            .read_text(encoding="utf-8"))
        assert report["final_status"] == "checker-PASS", report
        assert rc == model.EXIT_OK
        by_step = {c["step"]: c for c in report["checkpoints"]}
        assert by_step["ORACLE"]["status"] == "PASS"


# ---------------------------------------------------------------------------
# T3/D-681.2 — the candidate resolution contract
# ---------------------------------------------------------------------------

class TestCandidateResolutionContract:
    def test_candidate_path_from_task_yaml_declaration(self, tmp_path):
        """A declared checker.candidate is the unit's contract path — used
        verbatim (ws-relative), whatever the family language."""
        task = tmp_path / "task.yaml"
        task.write_text(yaml.safe_dump({
            "task_id": "js-sign-v1", "family": "js-sign",
            "checker": {"candidate": "client.js"}}), encoding="utf-8")
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "client.js").write_text("module.exports = {};\n",
                                      encoding="utf-8")
        events: list[dict] = []
        got = model.resolve_candidate(ws, task, events=events)
        assert got == ws / "client.js", got
        assert events == []  # a declaration silences the typed event

    def test_undeclared_candidate_is_typed_error_not_silent_py_fallback(
            self, tmp_path):
        """An undeclared .js family is NOT silently resolved to the .py
        default: the resolver still returns a path (fail-open) but emits
        exactly one typed candidate-undeclared event naming the expected
        suffix."""
        task = tmp_path / "task.yaml"
        task.write_text(yaml.safe_dump({
            "task_id": "js-sign-v1", "family": "js-sign"}),
            encoding="utf-8")
        ws = tmp_path / "ws"
        ws.mkdir()
        events: list[dict] = []
        got = model.resolve_candidate(ws, task, events=events)
        # fail-open: the default path still resolves (no raise)
        assert got == ws / "artifacts" / "derive_reimpl.py", got
        # typed: exactly one candidate-undeclared event, family-aware
        assert len(events) == 1, events
        ev = events[0]
        assert ev["event"] == "candidate-undeclared"
        assert ev["expected_suffix"] == ".js"
        assert ev["task_id"] == "js-sign-v1"

    def test_undeclared_python_family_stays_silent(self, tmp_path):
        """The .py default MATCHES the py-derive contract — no event, no
        noise (the smoke-rehearsal shape is legitimate for .py)."""
        task = tmp_path / "task.yaml"
        task.write_text(yaml.safe_dump({
            "task_id": "py-derive-v1", "family": "py-derive"}),
            encoding="utf-8")
        ws = tmp_path / "ws"
        ws.mkdir()
        events: list[dict] = []
        got = model.resolve_candidate(ws, task, events=events)
        assert got == ws / "artifacts" / "derive_reimpl.py", got
        assert events == []

    def test_unregistered_family_fails_open_without_event(self, tmp_path):
        """An unknown family cannot be judged against a contract suffix —
        fail-open (no event, no raise), never a KeyError into the
        pipeline."""
        task = tmp_path / "task.yaml"
        task.write_text(yaml.safe_dump({
            "task_id": "x-v1", "family": "no-such-family"}),
            encoding="utf-8")
        ws = tmp_path / "ws"
        ws.mkdir()
        events: list[dict] = []
        got = model.resolve_candidate(ws, task, events=events)
        assert got == ws / "artifacts" / "derive_reimpl.py", got
        assert events == []

    def test_every_declared_candidate_matches_the_family_suffix(self):
        """The declarations themselves obey D-681.2: every tracked unit
        that declares checker.candidate declares a path whose suffix is
        the family's contract suffix (eval_contract single source)."""
        bad: list[str] = []
        for task_yaml in sorted(
                (REPO / "eval/v1/tasks").rglob("task.yaml")):
            doc = yaml.safe_load(task_yaml.read_text(encoding="utf-8")) or {}
            cand = ((doc.get("checker") or {}).get("candidate")
                    if isinstance(doc.get("checker"), dict) else None)
            if not isinstance(cand, str) or not cand.strip():
                continue
            fam = doc.get("family")
            want = ec.candidate_suffix(fam)  # KeyError = unregistered fam
            if Path(cand.strip()).suffix != want:
                bad.append(f"{task_yaml}: {cand!r} != {want}")
        assert bad == [], bad

    def test_non_string_declaration_is_a_validation_error(self):
        """The schema/mirror know checker.candidate (review MEDIUM): a
        declared non-string candidate is a typed validation error, never
        a silent fall-through to the default path."""
        import eval_dataset as ds
        task = ds.load_task(REPO / "eval/v1/tasks/smoke/py-derive-v1")
        task["checker"]["candidate"] = 123
        ok, errors = ds.validate_task(task)
        assert not ok
        assert any("checker.candidate" in e for e in errors), errors

    def test_string_declaration_passes_the_mirror(self):
        import eval_dataset as ds
        task = ds.load_task(REPO / "eval/v1/tasks/smoke/py-derive-v1")
        task["checker"]["candidate"] = "client.py"
        ok, errors = ds.validate_task(task)
        assert ok, errors

    def test_suffix_mismatch_units_carry_a_declaration(self):
        """Every tracked unit whose family grades a non-.py candidate
        declares its contract path — the silent .py fallback class is
        closed at the source, not only diagnosed at the resolver."""
        undeclared: list[str] = []
        for task_yaml in sorted(
                (REPO / "eval/v1/tasks").rglob("task.yaml")):
            doc = yaml.safe_load(task_yaml.read_text(encoding="utf-8")) or {}
            fam = doc.get("family")
            if ec.candidate_suffix(fam) == ".py":
                continue
            cand = ((doc.get("checker") or {}).get("candidate")
                    if isinstance(doc.get("checker"), dict) else None)
            if not (isinstance(cand, str) and cand.strip()):
                undeclared.append(f"{task_yaml} (family {fam})")
        assert undeclared == [], undeclared


# ---------------------------------------------------------------------------
# T2 delivery face — the monotone best-so-far hand-off
# ---------------------------------------------------------------------------

class TestMonotoneDelivery:
    def test_best_so_far_candidate_is_delivered_on_partial(
            self, stub_repo, tmp_path, monkeypatch):
        """A budget-exhausted PARTIAL run (checker FAIL — no upgrade)
        still hands its best-so-far candidate to the delivery file."""
        runner = ScriptedRunner()
        clock = FakeClock()
        ws_root = tmp_path / "wsroot"
        run_id = "681-partial-deliver"
        _script_common(runner, stub_repo, ws_root, run_id)
        runner.on("convergence_check.py", "--json", rc=1,
                  stdout=json.dumps({"decision": "DISPATCH"}))
        ev_rel = "runs/eval/evidence-681-d.json"
        ev = stub_repo / ev_rel
        ev.parent.mkdir(parents=True, exist_ok=True)
        ev.write_text(json.dumps(REAL_EVIDENCE_DOC), encoding="utf-8")
        runner.on("checker.py", "--candidate", rc=1, stdout=(
            f"EVIDENCE {ev_rel}\nVERDICT FAIL\n"))
        _patch_gate(monkeypatch, ok=True)
        ws = ws_root / f"e2e-ws-{run_id}"
        (ws / "artifacts").mkdir(parents=True, exist_ok=True)
        (ws / "artifacts/derive_reimpl.py").write_text(DERIVE_PY,
                                                       encoding="utf-8")
        try:
            checkpoints.run_pipeline(
                model.PipelineArgs(
                    unit="py-derive-v1", repo=stub_repo, ws_root=ws_root,
                    budget_seconds=120, llm_mode="dry", tick_wait_seconds=60,
                    run_id=run_id, max_ticks=30),
                cmd_runner=runner, clock=clock, sleep_fn=clock.sleep)
        finally:
            monkeypatch.undo()

        delivery = json.loads(
            (ws / "runs/deliverable-best-so-far.json").read_text(
                encoding="utf-8"))
        assert delivery["candidate_rel"] == "artifacts/derive_reimpl.py"
        assert delivery["unit"] == "py-derive-v1"
        assert delivery["run_id"] == run_id
        # exact digest pin: the file hashed is the delivered candidate
        # as it stands on disk after the run (the dry act may have
        # overwritten the planted stub — the digest tracks the bytes)
        assert delivery["candidate_sha256"] == hashlib.sha256(
            (ws / "artifacts/derive_reimpl.py").read_bytes()).hexdigest()

    def test_no_candidate_writes_no_delivery_file(self, stub_repo, tmp_path,
                                                  monkeypatch):
        """Honest absence: a run whose workspace never gained a candidate
        (budget 0 — nothing ran) delivers nothing — never a fabricated
        pointer."""
        runner = ScriptedRunner()
        clock = FakeClock()
        ws_root = tmp_path / "wsroot"
        run_id = "681-nodeliver"
        _patch_gate(monkeypatch, ok=True)
        try:
            rc = checkpoints.run_pipeline(
                model.PipelineArgs(
                    unit="py-derive-v1", repo=stub_repo, ws_root=ws_root,
                    budget_seconds=0, llm_mode="dry", tick_wait_seconds=0,
                    run_id=run_id),
                cmd_runner=runner, clock=clock, sleep_fn=clock.sleep)
        finally:
            monkeypatch.undo()

        assert rc == model.EXIT_BUDGET_PARTIAL
        ws = ws_root / f"e2e-ws-{run_id}"
        assert not (ws / "runs/deliverable-best-so-far.json").exists()
        report = json.loads(
            (stub_repo / f"runs/e2e/{run_id}/report.json")
            .read_text(encoding="utf-8"))
        assert report["final_status"] == "PARTIAL"

    def test_delivered_file_is_never_retracted(self, stub_repo, tmp_path):
        """The monotone half: a later finalize that finds NO candidate
        leaves the already-delivered file untouched — a delivered
        artifact is not retracted by a subsequent resume."""
        ws = tmp_path / "ws"
        (ws / "artifacts").mkdir(parents=True)
        cand = ws / "artifacts/derive_reimpl.py"
        cand.write_text(DERIVE_PY, encoding="utf-8")
        ev_dir = tmp_path / "ev"
        state = model.RunState(
            run_id="monotone", unit="py-derive-v1", family="smoke",
            repo=str(stub_repo),
            task_dir=str(stub_repo / "eval/v1/tasks/smoke/py-derive-v1"),
            ws=str(ws), evidence_dir=str(ev_dir), budget_seconds=100,
            llm_mode="dry", started_ts="t", started_monotonic=0.0,
            anchors=dict(ANCHORS))
        runner = ScriptedRunner()
        ctx = checkpoints.RunContext(
            state=state, runner=runner,
            face=llm_faces.face_for("dry", runner, ev_dir),
            clock=FakeClock(), sleep_fn=lambda _s: None)

        out = ws / "runs/deliverable-best-so-far.json"
        checkpoints._deliver_best_so_far(ctx, "PARTIAL")
        first = out.read_text(encoding="utf-8")
        assert json.loads(first)["candidate_sha256"] == hashlib.sha256(
            DERIVE_PY.encode()).hexdigest()

        cand.unlink()  # the next finalize finds nothing to deliver
        checkpoints._deliver_best_so_far(ctx, "PARTIAL")
        assert out.read_text(encoding="utf-8") == first  # untouched
