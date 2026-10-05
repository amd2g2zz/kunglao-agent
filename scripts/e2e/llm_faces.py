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
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from e2e import audit, model

#: per-command timeouts (seconds) — every subprocess call is bounded.
SCRIPT_TIMEOUT_S = 600
def _act_timeout_s() -> int:
    """#473: env-overridable act timeout — rounds may run longer acts
    without code changes. Garbage falls back to the default."""
    raw = os.environ.get("KUNGLAO_E2E_ACT_TIMEOUT_S", "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 1_800
    return value if value > 0 else 1_800


CLAUDE_ACT_TIMEOUT_S = _act_timeout_s()


def _req_timeout_s(req) -> int:
    """The effective act timeout: the request's Luby-ladder value when
    the C6 loop set one (matrix4 K1 wiring), else the flat default."""
    override = getattr(req, "timeout_s", None)
    return override if isinstance(override, int) and override > 0 \
        else CLAUDE_ACT_TIMEOUT_S

#: the default tool rack for auto-mode acts (byte-compatible with the
#: pre-rack history); a request declaring its own tools rack rides it
#: through verbatim (the distill act declares a WebSearch-inclusive
#: rack — retrieval needs the web face).
DEFAULT_RACK = ("Read", "Write", "Edit", "Bash", "Grep", "Glob")

#: the distill act's agent identity (the reserved non-register claim
#: space is distill-<attempt-n>; these acts never enter the claim
#: register or the ranker)
DISTILL_AGENT = "kunglao-distill"


#: the envelope's legacy default tools value — requests constructed
#: without an explicit rack carry this; it is NOT a real rack (the
#: historical claude act always ran the DEFAULT_RACK below), so the
#: rack derivation treats it as undeclared.
LEGACY_UNDECLARED_RACK = ("grep", "python3")


def _rack_of(req: model.DispatchRequest) -> tuple[str, ...]:
    """The act's tool rack: a request declaring a rack of its own rides
    it verbatim (the distill act declares a WebSearch-inclusive rack);
    the envelope default and the legacy undeclared value keep the exact
    historical DEFAULT_RACK (byte-compatibility for every existing
    request shape — pins included)."""
    declared = tuple(req.tools or ())
    if declared and declared not in (DEFAULT_RACK, LEGACY_UNDECLARED_RACK):
        return declared
    return DEFAULT_RACK


#: the scripted distillation candidate: a REAL parameter-recovery
#: decoder implementing the re-library method (anchor-differential
#: keystream view over a known structural header, period detection,
#: structural verify) — it recovers the key from the sample bytes; no
#: fixture constants are baked in. The dry face scripts the retrieval
#: content; the candidate itself genuinely runs in the engine's oracle.
_DRY_DISTILL_CANDIDATE = '''#!/usr/bin/env python3
"""transform-recover — anchor-differential byte-transform recovery.

Method (from the re-library decode card): when an unknown byte-level
transform is position-local, invert the additive component first,
recover the keystream view over a KNOWN structural anchor (magic +
version + reserved zeros), detect the keystream period, then verify by
re-decoding the anchor and declared structure. No key material is
baked in — everything is recovered from the sample bytes.
"""
import hashlib
import json
import sys

ANCHOR = b"KLG1" + (3).to_bytes(2, "little") + b"\\x00" * 10


def main(argv):
    if len(argv) < 2:
        print(json.dumps({"error": "usage: transform-recover <sample>"}))
        return 2
    data = open(argv[1], "rb").read()
    n = min(len(ANCHOR), len(data))
    # keystream view: invert the position add, then xor with the anchor
    stream = [((data[i] - i) & 0xFF) ^ ANCHOR[i] for i in range(n)]
    period = None
    for p in range(1, 17):
        if all(stream[i] == stream[i % p] for i in range(n)):
            period = p
            break
    if period is None:
        print(json.dumps({"error": "no period <= 16 fits the anchor"}))
        return 1
    key = bytes(stream[:period])
    plain = bytes((((data[i] - i) & 0xFF) ^ key[i % period])
                  for i in range(len(data)))
    ok = plain.startswith(ANCHOR)
    print(json.dumps({
        "magic": plain[:4].decode("ascii", "replace"),
        "magic=KLG1": "yes" if ok else "no",
        "period": period,
        "key_hex": key.hex(),
        "plain_sha256": hashlib.sha256(plain).hexdigest(),
        "anchor_verified": ok,
    }))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
'''


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

    def launch_dispatch(self, req: model.DispatchRequest) -> str:
        """Launch phase (#459): write the request file + emit the ATTEMPT
        row. Called sequentially from the main thread so a wave's attempts
        land in launch order BEFORE any act executes. Returns the launch
        handle (the request-file path) run_dispatch consumes."""
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        path = self.evidence_dir / f"dispatch-{req.claim}-{req.emitted_ts or model.utc_now()}.json"
        path.write_text(
            json.dumps(req.to_dict(), indent=2, sort_keys=True,
                       ensure_ascii=False) + "\n", encoding="utf-8")
        # unified audit trail (owner ruling 2026-09-29 §2): attempt row for
        # EVERY dispatch act, stream AND ActRecord.
        audit.emit_dispatch_attempt(req.workspace, req.claim, mode=self.mode,
                                    artifact=str(path))
        return str(path)

    def run_dispatch(self, req: model.DispatchRequest,
                     handle=None) -> ActRecord:
        """Execution phase (#459): emit the RESULT row + mint the record.
        The orchestrator face runs no subprocess — the result's exit is a
        documented null ("orchestrator_face_no_subprocess"), never a
        fabricated 0."""
        artifact = str(handle) if handle else ""
        audit.emit_dispatch_result(req.workspace, req.claim, mode=self.mode,
                                   rc=None, artifacts=[artifact])
        return ActRecord(req.claim, self.mode, "EMITTED",
                         {"dispatch_request": artifact})

    def dispatch_act(self, req: model.DispatchRequest) -> ActRecord:
        return self.run_dispatch(req, self.launch_dispatch(req))

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

    def launch_dispatch(self, req: model.DispatchRequest) -> None:
        """Launch phase (#459): the ATTEMPT row, emitted from the main
        thread so every attempt precedes every result in a wave. The
        command rides with the prompt elided to its file pointer — the
        prompt body lives in the dispatch-prompt evidence file, and the
        stream stays one-line-per-event readable."""
        ws = Path(req.workspace)
        audit.emit_dispatch_attempt(
            req.workspace, req.claim, mode=self.mode,
            command=["claude", "-p", f"<prompt-file:{req.prompt_file}>",
                     "--output-format", "json",
                     "--allowedTools", ",".join(_rack_of(req))],
            cwd=str(ws), timeout=_req_timeout_s(req))
        return None

    def run_dispatch(self, req: model.DispatchRequest,
                     handle=None) -> ActRecord:
        """Execution phase (#459): the headless claude act — safe to run
        in a pool thread (its subprocess + parse + result row share no
        mutable state with the other acts of the wave)."""
        # #472 guard: the prompt read is the known pre-subprocess crash
        # point — a missing/undecodable prompt file yields an ERROR
        # record + explained rc-null instead of losing the wave's act.
        try:
            prompt = Path(req.prompt_file).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            audit.emit_dispatch_result(
                req.workspace, req.claim, mode=self.mode, rc=None,
                stderr_full=f"prompt file unreadable: "
                            f"{type(exc).__name__}: {exc}",
                exit_null_reason="prompt_file_unreadable")
            return ActRecord(req.claim, self.mode, "ERROR",
                             {"error": f"{type(exc).__name__}: {exc}",
                              "guard": "prompt_file"})
        # #456 fix: run IN the workspace (the agent must read/write the
        # claim register, facts, target material) — NOT in the repo.
        # The prompt carries the repo path for script access.
        ws = Path(req.workspace)
        cmd = ["claude", "-p", prompt, "--output-format", "json",
               "--allowedTools", ",".join(_rack_of(req))]
        started = time.monotonic()
        outcome = self.runner.run(cmd, cwd=str(ws),
                                  timeout=_req_timeout_s(req))
        duration_ms = int((time.monotonic() - started) * 1000)
        # Parse the claude -p JSON for the agent's actual result
        # (rc=0 does NOT mean the analysis succeeded — #456 bug 2)
        result_status = "DISPATCHED"
        try:
            _doc = json.loads(outcome.stdout) if outcome.stdout else {}
            _agent_result = (_doc.get("result") or "").strip()
            # word-boundary + case-insensitive: "Blocked:" parses,
            # "unblocked" does not (substring scan misfired both ways)
            if re.search(r"\bblocked\b", _agent_result, re.IGNORECASE):
                result_status = "BLOCKED"
            elif outcome.timed_out:
                result_status = "TIMEOUT"
        except (ValueError, TypeError):
            if outcome.timed_out:
                result_status = "TIMEOUT"
        if result_status == "DISPATCHED" and outcome.rc != 0:
            result_status = "TIMEOUT" if outcome.timed_out else "ERROR"
        # RESULT after execution; failure carries the FULL stderr (§2
        # diagnosis face — tails stay thrifted, the exact moment you need
        # the text is the failure, not the pass).
        audit.emit_dispatch_result(
            req.workspace, req.claim, mode=self.mode, rc=outcome.rc,
            timed_out=outcome.timed_out, duration_ms=duration_ms,
            stdout_tail=outcome.stdout[-model.TAIL_CHARS:],
            stderr_tail=outcome.stderr[-model.TAIL_CHARS:],
            stderr_full=(outcome.stderr if (outcome.rc != 0 or
                                            outcome.timed_out) else None))
        return ActRecord(
            req.claim, self.mode, result_status,
            {"cmd": ["claude", "-p"], "rc": outcome.rc,
             "cwd": str(ws),
             "timeout": CLAUDE_ACT_TIMEOUT_S,
             "timed_out": outcome.timed_out,
             "duration_ms": duration_ms,
             "stdout_tail": outcome.stdout[-model.TAIL_CHARS:],
             "stderr_tail": outcome.stderr[-model.TAIL_CHARS:]})

    def dispatch_act(self, req: model.DispatchRequest) -> ActRecord:
        self.launch_dispatch(req)
        return self.run_dispatch(req)

    def verdict_act(self, ws: Path, prompt: str) -> ActRecord:
        # #513: run IN the workspace with Read/Write/Grep — the old face
        # ran cwd=repo with no tools and produced nothing
        outcome = self.runner.run(
            ["claude", "-p", prompt, "--output-format", "json",
             "--allowedTools", "Read,Write,Grep,Glob"],
            cwd=Path(ws), timeout=CLAUDE_ACT_TIMEOUT_S)
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
    dry mode tests the pipeline, not the solver.

    Distill acts (agent kunglao-distill) get their own responder: the
    scripted retrieval CONTENT lands as a real report + a REAL
    parameter-recovery candidate — the engine's validation, oracle,
    and landing then run their genuine code paths on it (the dry face
    scripts the LLM's reading, never the verification).
    """

    mode = "dry"

    def __init__(self, evidence_dir: Path, claim_counter: dict | None = None):
        self.evidence_dir = Path(evidence_dir)
        self.claim_counter = claim_counter if claim_counter is not None else {}
        # #459: waves run acts in pool threads — the dry face serializes
        # its counter + fixture writes so parallel dry acts stay
        # deterministic (dry is a scripted responder; concurrency would
        # only race the fixture file names, never real analysis).
        self._lock = threading.Lock()

    def launch_dispatch(self, req: model.DispatchRequest) -> None:
        """Launch phase (#459): the dry face dispatches too — the ATTEMPT
        row from the main thread, in launch order."""
        audit.emit_dispatch_attempt(req.workspace, req.claim, mode=self.mode,
                                    cwd=str(Path(req.workspace)), timeout=None)
        return None

    def run_dispatch(self, req: model.DispatchRequest,
                     handle=None) -> ActRecord:
        ws = Path(req.workspace)
        started = time.monotonic()
        if req.agent == DISTILL_AGENT:
            return self._distill_act(req, ws, started)
        artifacts: list[str] = []
        with self._lock:
            n = self.claim_counter.get(req.claim, 0) + 1
            self.claim_counter[req.claim] = n
            # 1. worker-status FIRST (worker-side rule, W-15)
            status = ws / "runs" / f"worker-status-dry-{req.claim}-{n}.md"
            status.parent.mkdir(parents=True, exist_ok=True)
            status.write_text(
                f"# worker status (dry)\nclaim: {req.claim}\n"
                "status: DONE\n", encoding="utf-8")
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
        duration_ms = int((time.monotonic() - started) * 1000)
        audit.emit_dispatch_result(req.workspace, req.claim, mode=self.mode,
                                   rc=0, duration_ms=duration_ms,
                                   artifacts=artifacts)
        return ActRecord(req.claim, self.mode, "DISPATCHED",
                         {"artifacts": artifacts})

    def _distill_act(self, req: model.DispatchRequest, ws: Path,
                     started: float) -> ActRecord:
        """The scripted distillation act: re-library retrieval content +
        a REAL anchor-differential recovery candidate, staged in the
        attempt directory the engine validates + oracles + lands. The
        prompt's JSON header carries the trigger echo (token, sample
        hint) — the scripted responder reads exactly what the real LLM
        would read."""
        attempt = req.claim.split("distill-", 1)[-1] or "attempt-1"
        attempt_dir = ws / "runs" / "distill-candidates" / attempt
        attempt_dir.mkdir(parents=True, exist_ok=True)
        prompt = ""
        try:
            prompt = Path(req.prompt_file).read_text(encoding="utf-8")
        except OSError:
            prompt = ""
        token, sample_hint = "crypto:decode", None
        for line in prompt.splitlines():
            if line.startswith("token: "):
                token = line[len("token: "):].strip()
            elif line.startswith("sample: "):
                sample_hint = line[len("sample: "):].strip() or None
        (attempt_dir / "transform-recover.py").write_text(
            _DRY_DISTILL_CANDIDATE, encoding="utf-8")
        report = {
            "schema": "distill-report/1",
            "trigger": {"kind": "shelf-miss", "token": token,
                        "sample_hint": sample_hint},
            "sources": [
                {"kind": "relibrary", "ref": "references/re-library/"
                                            "patterns/decode/"
                                            "byte-transform-id.md"},
            ],
            "hops": [],
            "methods": [
                "unknown byte-transform identification: invert the "
                "position-add first, recover the keystream view over a "
                "known structural anchor, detect the period, verify by "
                "re-decoding the header",
            ],
            "candidates": [
                {"name": "transform-recover",
                 "file": "transform-recover.py",
                 "capability": token,
                 "oracle": {"expect_rc": 0,
                            "expect_stdout_contains": "magic=KLG1"}},
            ],
        }
        report_path = attempt_dir / "report.json"
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n", encoding="utf-8")
        duration_ms = int((time.monotonic() - started) * 1000)
        artifacts = [str(report_path),
                     str(attempt_dir / "transform-recover.py")]
        audit.emit_dispatch_result(req.workspace, req.claim, mode=self.mode,
                                   rc=0, duration_ms=duration_ms,
                                   artifacts=artifacts)
        return ActRecord(req.claim, self.mode, "DISPATCHED",
                         {"artifacts": artifacts})

    def dispatch_act(self, req: model.DispatchRequest) -> ActRecord:
        self.launch_dispatch(req)
        return self.run_dispatch(req)

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


def _wave_act(face, req: model.DispatchRequest, handle) -> ActRecord:
    """#472 act cage — the ONE place a raising act is converted to
    evidence. Every dispatched act lands: an Exception from a face's
    run_dispatch still completes the act's ATTEMPT/RESULT pair (rc=None
    with the caged reason — there was no subprocess exit to fabricate)
    and yields an ERROR ActRecord (the existing outcome vocabulary), so
    sibling acts and the tick's records survive one act's crash.
    BaseException (operator interrupts) still propagates."""
    try:
        return face.run_dispatch(req, handle)
    except Exception as exc:  # noqa: BLE001 — the cage; record, never lose
        audit.emit_dispatch_result(
            req.workspace, req.claim, mode=face.mode, rc=None,
            stderr_full=f"{type(exc).__name__}: {exc}",
            exit_null_reason="wave_act_exception")
        return ActRecord(req.claim, face.mode, "ERROR",
                         {"error": f"{type(exc).__name__}: {exc}",
                          "caged": "wave_act"})


def run_dispatch_parallel(
        face, launched: list[tuple[model.DispatchRequest, object]]
        ) -> list[ActRecord]:
    """#459 bounded-concurrency execution wave.

    Precondition: every request's ATTEMPT row was already emitted by
    launch_dispatch in the CALLER's thread (launch order, before any act
    executes). This runs the acts — independent `claude -p` processes in
    the same workspace — in one thread-pool wave and WAITS for all of
    them to land: a timeout on one act never cancels the others (each
    subprocess carries its own timeout). Returns ActRecords in LANDING
    order (as_completed); a wave of one runs inline (no pool spin-up —
    the common single-claim tick keeps its exact sequential behavior).
    #472: every act goes through the _wave_act cage (pool wave and
    inline wave alike) — one crashing act is recorded as an ERROR act,
    never an uncaged exception that loses the whole wave."""
    if len(launched) <= 1:
        return [_wave_act(face, req, handle) for req, handle in launched]
    with ThreadPoolExecutor(max_workers=len(launched)) as pool:
        futures = [pool.submit(_wave_act, face, req, handle)
                   for req, handle in launched]
        results: list[ActRecord] = []
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 — cage belt: the
                # submit path itself failed before _wave_act could cage
                results.append(
                    ActRecord("unknown", getattr(face, "mode", "?"),
                              "ERROR",
                              {"error": f"{type(exc).__name__}: {exc}",
                               "caged": "future_belt"}))
        return results


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
