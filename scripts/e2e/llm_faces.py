# -*- coding: utf-8 -*-
"""e2e.llm_faces — the subprocess seam + the three C6/C7 LLM faces.

CommandRunner is the ONE subprocess boundary of the runner (tests script
it); every command goes through uv run --project <repo> exactly as the
runbook CANON line specifies. The dispatch faces are how C6/C7 execute
LLM-shaped acts:

  orchestrator (default) — the runner NEVER runs the loop itself: it
      emits a machine-readable dispatch-request file and waits (ticks)
      for the orchestrator/agent act (open-loop honesty);
  auto (--auto-llm) — shells out to headless `claude -p <prompt>
      --output-format json` from the repo dir per dispatch act;
  dry (--dry-llm) — a scripted responder writing the minimal
      fixture-shaped worker-status + fact + verify-note + verdict files
      so the whole C6/C7 pipeline is testable with zero LLM/network.

No face ever degrades silently: every act lands in structured evidence.
"""
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from e2e import model

#: per-command timeouts (seconds) — every subprocess call is bounded.
SCRIPT_TIMEOUT_S = 600
CLAUDE_ACT_TIMEOUT_S = 1_800


class CommandRunner:
    """The subprocess seam. Captured output + hard timeout; timeouts come
    back as CmdOutcome(rc=-1, timed_out=True) — recorded, never retried."""

    def __init__(self, repo: Path):
        self.repo = Path(repo)

    def py_cmd(self, script: str, *args: str) -> list[str]:
        """Runbook CANON: uv run --project $REPO python $REPO/scripts/<s>."""
        return ["uv", "run", "--project", str(self.repo), "python",
                str(self.repo / "scripts" / script), *args]

    def console_cmd(self, subcommand: str, ws: Path, *args: str) -> list[str]:
        """Registered console script face (#416): uv run ... kunglao <sub>."""
        return ["uv", "run", "--project", str(self.repo), "kunglao",
                subcommand, str(ws), *args]

    def run(self, cmd: list[str], cwd: Path | None = None,
            timeout: int | None = None) -> model.CmdOutcome:
        timeout = timeout or SCRIPT_TIMEOUT_S
        try:
            proc = subprocess.run(
                [str(c) for c in cmd], cwd=str(cwd) if cwd else None,
                capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace")
        except subprocess.TimeoutExpired as exc:
            tail = f"{(exc.stdout or '')[-400:]}" if exc.stdout else ""
            return model.CmdOutcome(
                rc=-1, stdout=tail,
                stderr=f"TIMEOUT after {timeout}s: {' '.join(map(str, cmd))}",
                timed_out=True)
        except OSError as exc:
            return model.CmdOutcome(
                rc=-1, stdout="", stderr=f"OSERROR {type(exc).__name__}: {exc}")
        return model.CmdOutcome(rc=proc.returncode, stdout=proc.stdout,
                                stderr=proc.stderr)


@dataclass
class ActRecord:
    """One dispatch/verdict act's evidence slice."""
    claim: str
    mode: str
    outcome: str          # DISPATCHED | EMITTED | TIMEOUT | ERROR
    detail: dict

    def to_dict(self) -> dict:
        return {"claim": self.claim, "mode": self.mode,
                "outcome": self.outcome, "detail": self.detail}


class OrchestratorFace:
    """Default mode: emit dispatch-request files, wait for external acts."""

    mode = "orchestrator"

    def __init__(self, evidence_dir: Path):
        self.evidence_dir = Path(evidence_dir)

    def dispatch_act(self, req: model.DispatchRequest) -> ActRecord:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"dispatch-{req.claim}-{req.emitted_ts or model.utc_now()}.json"
        path.write_text(
            json.dumps(req.to_dict(), indent=2, sort_keys=True,
                       ensure_ascii=False) + "\n", encoding="utf-8")
        return ActRecord(req.claim, self.mode, "EMITTED",
                         {"dispatch_request": str(path)})

    def wait_verdict(self, ws: Path, poll_seconds: float,
                     deadline: float, sleep_fn=time.sleep) -> bool:
        """Orchestrator mode: evidence/verdict.json is written by the
        verdict-scorer act; poll until it exists or the deadline passes."""
        while time.monotonic() < deadline:
            if (Path(ws) / "evidence" / "verdict.json").is_file():
                return True
            sleep_fn(poll_seconds)
        return (Path(ws) / "evidence" / "verdict.json").is_file()


class AutoLlmFace:
    """--auto-llm: real headless claude execution, fully automatic."""

    mode = "auto"

    def __init__(self, runner: CommandRunner, evidence_dir: Path):
        self.runner = runner
        self.evidence_dir = Path(evidence_dir)

    def dispatch_act(self, req: model.DispatchRequest) -> ActRecord:
        prompt = Path(req.prompt_file).read_text(encoding="utf-8")
        cmd = ["claude", "-p", prompt, "--output-format", "json"]
        outcome = self.runner.run(cmd, cwd=self.runner.repo,
                                  timeout=CLAUDE_ACT_TIMEOUT_S)
        return ActRecord(
            req.claim, self.mode,
            "DISPATCHED" if outcome.rc == 0 else
            ("TIMEOUT" if outcome.timed_out else "ERROR"),
            {"cmd": cmd[:1], "rc": outcome.rc,
             "stdout_tail": outcome.stdout[-model.TAIL_CHARS:],
             "stderr_tail": outcome.stderr[-model.TAIL_CHARS:]})

    def verdict_act(self, ws: Path, prompt: str) -> ActRecord:
        outcome = self.runner.run(
            ["claude", "-p", prompt, "--output-format", "json"],
            cwd=self.runner.repo, timeout=CLAUDE_ACT_TIMEOUT_S)
        return ActRecord(
            "verdict", self.mode,
            "DISPATCHED" if outcome.rc == 0 else
            ("TIMEOUT" if outcome.timed_out else "ERROR"),
            {"rc": outcome.rc,
             "stdout_tail": outcome.stdout[-model.TAIL_CHARS:]})


class DryLlmFace:
    """--dry-llm: scripted responder (fixture-shaped, zero LLM/network).

    Writes exactly what the per-tick contract expects to observe:
    runs/worker-status-<id>.md FIRST, then facts/F<NNN>.md, plus the
    verify-note + reimpl artifact the C7 promotion path consumes, and
    (on the verdict step) evidence/verdict.json. Honest limitation: the
    dry reimpl is a stub — a REAL checker run on it may honestly FAIL;
    dry mode tests the pipeline, not the solver."""

    mode = "dry"

    def __init__(self, evidence_dir: Path, claim_counter: dict | None = None):
        self.evidence_dir = Path(evidence_dir)
        self.claim_counter = claim_counter if claim_counter is not None else {}

    def dispatch_act(self, req: model.DispatchRequest) -> ActRecord:
        ws = Path(req.workspace)
        n = self.claim_counter.get(req.claim, 0) + 1
        self.claim_counter[req.claim] = n
        artifacts: list[str] = []
        # 1. worker-status FIRST (worker-side rule, W-15)
        status = ws / "runs" / f"worker-status-dry-{req.claim}-{n}.md"
        status.parent.mkdir(parents=True, exist_ok=True)
        status.write_text(
            f"# worker status (dry)\nclaim: {req.claim}\nstatus: DONE\n",
            encoding="utf-8")
        artifacts.append(str(status))
        # 2. fact file with recovered-constants evidence
        fact = ws / "facts" / f"F{len(self.claim_counter):03d}.md"
        fact.parent.mkdir(parents=True, exist_ok=True)
        fact.write_text(
            f"---\nclaim: {req.claim}\nstatus: PROVEN\n"
            "evidence: static read of target/derive.py (dry fixture)\n"
            "---\nconstants recovered: 0 / 13 / 7 (dry placeholder)\n",
            encoding="utf-8")
        artifacts.append(str(fact))
        # 3. verify-note (outcome_capture convention for the gate)
        note = ws / "runs" / f"{req.claim}-verify-note.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(
            f"# verify — {req.claim}\noutcome: passes\n"
            "redteam: CONFIRMED (dry)\n", encoding="utf-8")
        artifacts.append(str(note))
        # 4. reimpl artifact (deliverable stand-in)
        reimpl = ws / "artifacts" / "derive_reimpl.py"
        reimpl.parent.mkdir(parents=True, exist_ok=True)
        reimpl.write_text(
            "def derive(data: bytes) -> int:\n"
            "    # dry-llm stub re-implementation (pipeline test only)\n"
            "    return 42\n", encoding="utf-8")
        artifacts.append(str(reimpl))
        return ActRecord(req.claim, self.mode, "DISPATCHED",
                         {"artifacts": artifacts})

    def verdict_act(self, ws: Path, prompt: str = "") -> ActRecord:
        verdict_dir = Path(ws) / "evidence"
        verdict_dir.mkdir(parents=True, exist_ok=True)
        (verdict_dir / "verdict.json").write_text(
            json.dumps({
                "schema": "analysis_verdict/11", "generated_by": "dry-llm",
                "primary_questions": [
                    {"id": "pq-1", "verdict": "PROVEN",
                     "fact": "constants recovered (dry)"},
                    {"id": "pq-2", "verdict": "PROVEN",
                     "fact": "reimpl reproduces probes (dry)"},
                ]}, indent=2) + "\n", encoding="utf-8")
        return ActRecord("verdict", self.mode, "DISPATCHED",
                         {"verdict_file": str(verdict_dir / "verdict.json")})


def face_for(mode: str, runner: CommandRunner,
             evidence_dir: Path) -> OrchestratorFace | AutoLlmFace | DryLlmFace:
    if mode == "orchestrator":
        return OrchestratorFace(evidence_dir)
    if mode == "auto":
        return AutoLlmFace(runner, evidence_dir)
    if mode == "dry":
        return DryLlmFace(evidence_dir)
    raise ValueError(f"unknown llm mode {mode!r}")


class AutonomousFace:
    """--autonomous (owner ruling 2026-09-29: zero intervention — command,
    wait, key). ONE headless claude session launched IN THE WORKSPACE with
    the plugin armed; the loop prompt + hooks + WORKGUARD drive everything.
    The runner does NOT dispatch, does NOT tick, does NOT intervene — it
    launches the session and polls for the verdict within the budget."""

    mode = "autonomous"

    def __init__(self, runner: CommandRunner, evidence_dir: Path,
                 budget_seconds: int = 14_400):
        self.runner = runner
        self.evidence_dir = Path(evidence_dir)
        self.budget_seconds = budget_seconds

    def launch(self, ws: Path) -> ActRecord:
        """Launch the autonomous session. Returns once the session exits
        (converged, budget-broken, or errored). The session itself is the
        WHOLE analysis — init already wrote CLAUDE.md, task_spec.yaml,
        armed hooks; the SessionStart hook injects the constitution."""
        prompt = (
            "Run the full analysis for this workspace per the CLAUDE.md "
            "instructions and task_spec.yaml. Complete every primary "
            "question, verify per the declared verification method, and "
            "write the verdict. The heartbeat loop and hooks are armed — "
            "follow the loop prompt's contract.")
        cmd = ["claude", "-p", prompt, "--output-format", "json"]
        outcome = self.runner.run(
            cmd, cwd=str(ws), timeout=self.budget_seconds)
        return ActRecord(
            "autonomous-session", self.mode,
            "COMPLETED" if outcome.rc == 0 else
            ("TIMEOUT" if outcome.timed_out else "ERROR"),
            {"rc": outcome.rc,
             "stdout_tail": outcome.stdout[-model.TAIL_CHARS:],
             "stderr_tail": outcome.stderr[-model.TAIL_CHARS:]})
