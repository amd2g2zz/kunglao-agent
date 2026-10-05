# -*- coding: utf-8 -*-
"""e2e.runtime — the runner's execution context + shared seams.

Everything the checkpoint implementations (e2e.steps-of-driver in
checkpoints.py) need that is NOT a checkpoint itself:

  RunContext    state + runner + LLM face + injected clock/sleep (the
                test injection point at the subprocess boundary)
  promote_claims  the C7 promotion seam through the repo's own
                register_proven_gate (#819) + #880 emit_settlements
  resolve_task_dir / family_of / new_run_id / resume_plan
  record_result / parse_decision / top_claim / budget_ok / tail

Pure plumbing; the runbook semantics live in checkpoints.py.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

from e2e import audit, evidence, llm_faces, model

IMPORT_ERRORS = ("ModuleNotFoundError", "ImportError", "NameError")


@dataclass
class RunContext:
    """Everything a checkpoint needs; the injection point for tests
    (scripted runner, fake clock, stubbed sleep)."""
    state: model.RunState
    runner: llm_faces.CommandRunner
    face: llm_faces.OrchestratorFace | llm_faces.AutoLlmFace | llm_faces.DryLlmFace
    clock: object
    sleep_fn: object
    acts: list[dict] = field(default_factory=list)
    # K1 wiring (matrix4): per claim-key dispatch-attempt ladder — the
    # Luby schedule's index. Default-empty keeps every older test and
    # the emit-dispatch path working unchanged.
    attempts: dict[str, int] = field(default_factory=dict)

    @property
    def ws(self) -> Path:
        return Path(self.state.ws)

    @property
    def repo(self) -> Path:
        return Path(self.state.repo)

    def cmd(self, cmd: list[str], cwd: Path | None = None,
            timeout: int | None = None) -> tuple[model.CmdOutcome, int]:
        """Run one bounded command; returns (outcome, duration_ms)."""
        started = self.clock.monotonic()
        outcome = self.runner.run(cmd, cwd=cwd, timeout=timeout)
        duration_ms = int((self.clock.monotonic() - started) * 1000)
        return outcome, duration_ms

    def py(self, script: str, *args: str, timeout: int | None = None
            ) -> tuple[model.CmdOutcome, int]:
        return self.cmd(self.runner.py_cmd(script, *args), timeout=timeout)

    def console(self, subcommand: str, *args: str,
                timeout: int | None = None) -> tuple[model.CmdOutcome, int]:
        return self.cmd(
            self.runner.console_cmd(subcommand, self.ws, *args),
            timeout=timeout)


def resolve_task_dir(repo: Path, unit: str) -> Path:
    """Resolve eval/v1/tasks/<tier>/<unit> — exactly one match or refuse."""
    import yaml  # noqa: PLC0415

    base = Path(repo) / "eval/v1/tasks"
    matches = sorted(p for p in base.glob(f"*/{unit}") if p.is_dir())
    if not matches:
        raise FileNotFoundError(f"no eval unit {unit!r} under {base}")
    task_yaml = matches[0] / "task.yaml"
    if not task_yaml.is_file():
        raise FileNotFoundError(f"missing {task_yaml}")
    doc = yaml.safe_load(task_yaml.read_text(encoding="utf-8")) or {}
    tier = str(doc.get("tier") or "")
    if tier and tier != matches[0].parent.name:
        raise FileNotFoundError(
            f"task.yaml tier {tier!r} does not match parent directory "
            f"{matches[0].parent.name!r}")
    return matches[0]


def family_of(task_dir: Path) -> str:
    """The unit's family directory name (e.g. smoke — the task statement's
    'family dir: smoke/py-derive-v1')."""
    return task_dir.parent.name


def new_run_id() -> str:
    from datetime import datetime  # noqa: PLC0415

    return "e2e-" + datetime.now().strftime("%Y%m%d-%H%M%S")


def resume_plan(evidence_dir: Path) -> dict[str, str]:
    """Evidence-anchored resume: PASS steps SKIP, everything else RUN."""
    plan: dict[str, str] = {}
    for checkpoint, name in model.CHECKPOINT_STEPS:
        sid = model.step_id(checkpoint, name)
        doc = evidence.load_checkpoint(evidence_dir, sid)
        plan[sid] = ("SKIP" if doc and doc.get("status") == model.PASS
                     else "RUN")
    return plan


def promote_claims(repo: Path, ws: Path, claim_ids: list[str]) -> dict:
    """C7 promotion through the repo's own gate (#819 fail-closed).

    Honors check_register_transitions' VERDICT ({ok, violations, waivers}
    — it returns, it does not raise): ok=False with unwaived violations
    means the register is NOT written and the caller must record FAIL
    with the violations (review F3 — the gate is never ceremonial).
    Settlements (#880 emit_settlements) fire only after an allowed write.
    Unit tests monkeypatch this seam or the gate module's internals."""
    rpg = _load_repo_module(repo, "register_proven_gate")
    import yaml  # noqa: PLC0415

    reg = Path(ws) / "claim-register.yaml"
    old_text = reg.read_text(encoding="utf-8") if reg.is_file() else ""
    doc = yaml.safe_load(old_text) if old_text.strip() else {}
    claims = (doc or {}).get("claims") or []
    wanted = set(claim_ids)
    promoted: list[str] = []
    for claim in claims:
        if str(claim.get("id")) in wanted and \
                str(claim.get("status", "")).upper() != "PROVEN":
            claim["status"] = "PROVEN"
            promoted.append(str(claim["id"]))
    (doc or {}).setdefault("claims", [])
    doc["claims"] = claims
    new_text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    verdict = rpg.check_register_transitions(Path(ws), new_text,
                                             old_text or None)
    if not verdict.get("ok"):
        # gate refused: no write, no settlement — violations ride evidence
        return {"ok": False,
                "violations": list(verdict.get("violations") or []),
                "waivers": list(verdict.get("waivers") or []),
                "promoted": [], "settlements": 0, "written": False}
    reg.write_text(new_text, encoding="utf-8")
    settlements = rpg.emit_settlements(Path(ws), new_text, old_text or None)
    return {"ok": True, "violations": [], "waivers": [],
            "promoted": promoted, "settlements": int(settlements or 0),
            "written": True}


def _load_repo_module(repo: Path, name: str):
    """Import a repo scripts/ module WITHOUT disturbing sys.path when it
    is already importable (the #770 twin-resolution guard: only pytest.ini
    pythonpath may insert scripts/hooks; a conditional fallback insert is
    allowed solely for out-of-repo invocations)."""
    import importlib.util  # noqa: PLC0415

    if importlib.util.find_spec(name) is None:
        sys.path.insert(0, str(Path(repo) / "scripts"))
    return importlib.import_module(name)


def tail(text: str) -> str:
    return (text or "")[-model.TAIL_CHARS:]


def record_result(ctx: RunContext, checkpoint: str, name: str, status: str,
                  rc: int | None, out: model.CmdOutcome | None,
                  duration_ms: int, detail: dict,
                  evidence_paths: list[str] | None = None
                  ) -> model.CheckpointResult:
    """Adjudicate → write evidence → record in run-state → ONE audit
    event. Every checkpoint result lands on disk the moment it exists
    (resume anchor) and leaves exactly one row in the unified stream
    (owner ruling 2026-09-29 §1/§3): checkpoint_<status> for C1-C7,
    oracle_verdict for the ORACLE step (no twin row — the exactly-one
    guarantee)."""
    result = model.CheckpointResult(
        checkpoint=checkpoint, name=name, status=status, rc=rc,
        stdout_tail=tail(out.stdout) if out else "",
        stderr_tail=tail(out.stderr) if out else "",
        duration_ms=duration_ms,
        evidence_paths=[str(p) for p in (evidence_paths or [])],
        ts=model.utc_now(), detail=detail)
    path = evidence.write_checkpoint(Path(ctx.state.evidence_dir), result)
    result.evidence_paths.append(str(path))
    evidence.write_checkpoint(Path(ctx.state.evidence_dir), result)
    ctx.state.steps[result.step] = status
    if checkpoint == "ORACLE":
        audit.emit_oracle_verdict(
            str(ctx.ws), step=result.step, status=status, rc=rc,
            duration_ms=duration_ms, verdict=detail.get("verdict"),
            min_pair_ratio=detail.get("min_pair_ratio"))
    else:
        audit.emit_checkpoint(
            str(ctx.ws), step=result.step, status=status, rc=rc,
            duration_ms=duration_ms, failed_step=detail.get("failed_step"))
    return result


def parse_decision(outcome: model.CmdOutcome) -> tuple[str | None, dict | None]:
    """(decision-upper, doc) from a convergence_check --json stdout."""
    doc = model.parse_last_json(outcome.stdout)
    if doc is None:
        return None, None
    decision = doc.get("decision")
    return (str(decision).upper() if decision else None), doc


def ranked_claims(outcome: model.CmdOutcome) -> list[str]:
    """ALL dispatchable claim ids from a priority_ratio --json stdout, in
    RANK order (#459 — the loop dispatches up to max-parallel per tick).

    Parses the same faces as top_claim (see below); top_claim is
    ranked_claims()[0] — one parser, two views, no drift. A repeated id is
    de-duplicated (never double-dispatched in one wave)."""
    ids: list[str] = []

    def _cid(entry) -> str | None:
        if isinstance(entry, dict):
            raw = entry.get("claim_id") or entry.get("claim")
            return str(raw) if raw else None
        return None

    doc = model.parse_last_json(outcome.stdout) or {}
    for entry in doc.get("actions") or doc.get("ranking") or []:
        cid = _cid(entry)
        if cid:
            ids.append(cid)
    if not ids:
        ids = [str(c) for c in doc.get("ranked_order") or []]
    if not ids:
        # #454/#454-r2: bare top-level array face (the current ranker emits
        # json.dumps(..., indent=2) — pretty-printed multi-line). Try the
        # WHOLE stdout first, then individual lines as fallback.
        import json as _json
        text = (outcome.stdout or "").strip()
        candidates = [text]
        candidates.extend(
            chunk.strip() for chunk in reversed(text.splitlines())
            if chunk.strip().startswith("["))
        for chunk in candidates:
            try:
                arr = _json.loads(chunk)
            except (ValueError, TypeError):
                continue
            if isinstance(arr, list):
                ids = [c for c in map(_cid, arr) if c]
                break
    unique: list[str] = []
    for cid in ids:
        if cid not in unique:
            unique.append(cid)
    return unique


def top_claim(outcome: model.CmdOutcome) -> str | None:
    """Rank #1 claim id from a priority_ratio --json stdout (ranked_claims
    restricted to its first element — the pre-#459 single-claim view)."""
    ids = ranked_claims(outcome)
    return ids[0] if ids else None


def budget_ok(ctx: RunContext) -> bool:
    """True when budget remains. Refreshes consumed-seconds from the
    injected clock first (no wall-clock assumptions in tests)."""
    ctx.state.budget_consumed_seconds = max(
        ctx.state.budget_consumed_seconds,
        ctx.clock.monotonic() - ctx.state.started_monotonic)
    return ctx.state.budget_remaining_seconds() > 0
