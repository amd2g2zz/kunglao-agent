# -*- coding: utf-8 -*-
"""e2e.constraint_witness — the mechanical witness leg of the oracle verdict.

goal_operationalization's lint refuses a not_done counterexample with no
witness at intake; this module is the settlement-time half: it evaluates
the workspace's declared constraint-witness block (schema
constraint-witness/1) against the delivered workspace and composes the
joint verdict

    verdict = witness AND outcome

A witness spec binds exactly one of:

  check: <shell command>  exit 0 = the counterexample does NOT hold (the
                          constraint is satisfied); any other exit = a
                          violation, and the oracle turns RED even when
                          the outcome checker is green
  none: <reason>          an explicit declaration that no mechanical
                          witness exists — recorded, never a red

Posture: FAIL-OPEN + WARN. A workspace that predates the contract (no
file, no witness block, unreadable YAML) evaluates to UNDECLARED with a
warning and never blocks the outcome leg — the hard refusal lives at
intake (the lint) and at the dispatch gate (convergence re-validates the
document). An unrunnable check (spawn error / timeout / rc -1) is an
errored entry with a warning, never a silent pass and never a red. A
check that RAN and exited non-zero is the only witness-side RED.

Each check runs as `sh -c` with cwd = the workspace and KUNGLAO_WS /
KUNGLAO_REPO exported, through the injected runner when the checkpoint
supplies one (the scripted seam) or the local subprocess default.
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import goal_operationalization as goal_op
import kunglao_log

PASS, FAIL, UNDECLARED = "PASS", "FAIL", "UNDECLARED"
WITNESS_TIMEOUT_S = 60
_GOAL_OP_NAME = "goal-operationalization.yaml"
_WARN_TAG = "e2e.constraint_witness"


class _Outcome:
    """Default-runner outcome — the rc/timed_out fields the verdict reads
    (mirrors model.CmdOutcome's shape without importing the model)."""

    def __init__(self, rc: int, timed_out: bool = False,
                 stderr: str = "") -> None:
        self.rc = rc
        self.timed_out = timed_out
        self.stderr = stderr


def _default_run(cmd: list[str], cwd: Path):
    try:
        proc = subprocess.run([str(c) for c in cmd], cwd=str(cwd),
                              capture_output=True, text=True,
                              timeout=WITNESS_TIMEOUT_S,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return _Outcome(-1, timed_out=True, stderr="timeout")
    except OSError as exc:
        return _Outcome(-1, stderr=f"{type(exc).__name__}: {exc}")
    return _Outcome(proc.returncode, stderr=proc.stderr or "")


def _warn(warnings: list[str], message: str) -> None:
    warnings.append(message)
    kunglao_log.warn(_WARN_TAG, message)


def _load_doc(path: Path, warnings: list[str]) -> dict | None:
    try:
        doc = goal_op.load(path)
    except goal_op.GoalOpError as exc:
        _warn(warnings, f"goal operationalization unreadable "
                        f"(fail-open): {exc}")
        return None
    if not isinstance(doc, dict):
        _warn(warnings, "goal operationalization is not a mapping "
                        "(fail-open)")
        return None
    return doc


def _rows(doc: dict) -> list[str]:
    value = doc.get("not_done")
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v.strip()]


def _check_command(check: str, ws: Path, repo: Path) -> list[str]:
    """The check runs in the workspace with both roots exported — the
    sh -c string form keeps it runner-agnostic (no env plumbing)."""
    script = (f"export KUNGLAO_WS={shlex.quote(str(ws))}; "
              f"export KUNGLAO_REPO={shlex.quote(str(repo))}; "
              f"{check}")
    return ["sh", "-c", script]


def evaluate(ws, repo, run=None) -> dict:
    """Evaluate the workspace's constraint-witness block.

    Returns {"status", "declared", "entries", "warnings"}: status is
    FAIL only when a check ran and exited non-zero (a violation),
    UNDECLARED for the fail-open pre-contract postures, PASS otherwise.
    run(cmd, cwd) injects the checkpoint's command seam; the default
    executes locally with a hard timeout.
    """
    ws = Path(ws)
    repo = Path(repo)
    run = run or _default_run
    warnings: list[str] = []
    entries: list[dict] = []

    doc = _load_doc(ws / _GOAL_OP_NAME, warnings)
    if doc is None:
        return {"status": UNDECLARED, "declared": False,
                "entries": entries, "warnings": warnings}
    block = goal_op.witness_block(doc)
    if block is None or block.get("schema") != goal_op.WITNESS_SCHEMA:
        _warn(warnings, "no declared constraint-witness block (fail-open: "
                        "the outcome leg runs unwitnessed)")
        return {"status": UNDECLARED, "declared": False,
                "entries": entries, "warnings": warnings}
    rows = _rows(doc)
    if not rows:
        _warn(warnings, "no not_done rows to witness (fail-open: draft "
                        "workspace)")
        return {"status": UNDECLARED, "declared": True,
                "entries": entries, "warnings": warnings}
    witnesses = goal_op.witness_map(doc)

    for row in rows:
        spec = witnesses.get(row)
        if not isinstance(spec, dict) or any(
                k not in ("check", "none") for k in spec):
            _warn(warnings, f"witness spec unusable for {row!r} "
                            "(fail-open)")
            entries.append({"constraint": row, "kind": "invalid",
                            "verdict": "error", "rc": None})
            continue
        none_reason = spec.get("none")
        if isinstance(none_reason, str) and none_reason.strip():
            entries.append({"constraint": row, "kind": "none",
                            "verdict": "declared-none",
                            "reason": none_reason.strip(), "rc": None})
            continue
        check = spec.get("check")
        if not (isinstance(check, str) and check.strip()):
            _warn(warnings, f"witness spec carries neither check nor "
                            f"none for {row!r} (fail-open)")
            entries.append({"constraint": row, "kind": "invalid",
                            "verdict": "error", "rc": None})
            continue
        outcome = run(_check_command(check, ws, repo), ws)
        rc = getattr(outcome, "rc", -1)
        timed_out = bool(getattr(outcome, "timed_out", False))
        if timed_out or rc == -1:
            detail = str(getattr(outcome, "stderr", ""))[:200]
            _warn(warnings, f"witness check errored (fail-open) for "
                            f"{row!r}: rc={rc} {detail}")
            entries.append({"constraint": row, "kind": "check",
                            "verdict": "error", "rc": rc,
                            "detail": detail})
        elif rc == 0:
            entries.append({"constraint": row, "kind": "check",
                            "verdict": "holds", "rc": 0})
        else:
            detail = str(getattr(outcome, "stderr", ""))[:200]
            entries.append({"constraint": row, "kind": "check",
                            "verdict": "violation", "rc": rc,
                            "detail": detail})

    status = FAIL if any(e["verdict"] == "violation" for e in entries) \
        else PASS
    return {"status": status, "declared": True, "entries": entries,
            "warnings": warnings}


def joint(outcome_status: str, witness_status: str) -> str:
    """verdict = witness AND outcome. UNDECLARED is the fail-open witness
    leg (warned at evaluate time, never blocking); any FAIL on either
    side yields FAIL."""
    if FAIL in (outcome_status, witness_status):
        return FAIL
    if outcome_status == PASS:
        return PASS
    return outcome_status
