# -*- coding: utf-8 -*-
"""e2e.evidence — run-state IO, checkpoint evidence, final report.

Every checkpoint result lands immediately as
<repo>/runs/e2e/<runid>/<step>.json; --resume reads those files back
(evidence-anchored resume). Deterministic: sorted keys, sorted steps.
"""
from __future__ import annotations

import json
from pathlib import Path

from e2e import model

RUN_STATE_FILE = "run-state.json"
REPORT_FILE = "report.json"


def evidence_root(repo: Path) -> Path:
    return Path(repo) / "runs" / "e2e"


def resolve_run_dir(repo: Path, run_id: str) -> Path:
    """Resolve runs/e2e/<run_id>; FileNotFoundError when absent."""
    run_dir = evidence_root(repo) / run_id
    if not run_dir.is_dir():
        raise FileNotFoundError(f"no such e2e run: {run_dir}")
    return run_dir


def write_checkpoint(evidence_dir: Path,
                     result: model.CheckpointResult) -> Path:
    path = Path(evidence_dir) / f"{result.step}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True,
                   ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_checkpoint(evidence_dir: Path, step: str) -> dict | None:
    path = Path(evidence_dir) / f"{step}.json"
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def write_run_state(evidence_dir: Path, state: model.RunState) -> Path:
    path = Path(evidence_dir) / RUN_STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state.to_dict(), indent=2, sort_keys=True,
                   ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_run_state(evidence_dir: Path) -> model.RunState | None:
    path = Path(evidence_dir) / RUN_STATE_FILE
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return model.RunState.from_dict(doc)
    except (ValueError, KeyError):
        return None


def build_report(state: model.RunState,
                 results: list[model.CheckpointResult],
                 final_status: str, exit_code: int,
                 final_verdict: dict | None = None) -> dict:
    """The final run report: per-checkpoint table, budget, oracle verdict."""
    checkpoints = [r.to_dict() for r in results]
    statuses = [r.status for r in results]
    if final_status == "ALL-PASS" and model.BLOCKED in statuses:
        final_status = "BLOCKED"
    return {
        "schema": "e2e-run-report/1",
        "run_id": state.run_id,
        "unit": state.unit,
        "family": state.family,
        "llm_mode": state.llm_mode,
        "workspace": state.ws,
        "evidence_dir": state.evidence_dir,
        "final_status": final_status,
        "exit_code": exit_code,
        "budget": {
            "seconds": state.budget_seconds,
            "consumed_seconds": round(state.budget_consumed_seconds, 3),
            "remaining_seconds": round(
                state.budget_remaining_seconds(), 3),
        },
        "checkpoints": checkpoints,
        "oracle": dict(final_verdict or {}),
        "total_duration_ms": state.total_duration_ms,
    }


def render_summary(report: dict) -> str:
    """Human summary to stdout: per-checkpoint table, budget, verdict."""
    lines = [
        f"E2E run {report['run_id']} ({report['unit']}, mode="
        f"{report['llm_mode']})",
        "-" * 64,
        f"{'STEP':<16} {'STATUS':<10} {'RC':>4} {'MS':>9}",
    ]
    for cp in report["checkpoints"]:
        lines.append(f"{cp['step']:<16} {cp['status']:<10} "
                     f"{str(cp['rc']):>4} {cp['duration_ms']:>9}")
    budget = report["budget"]
    lines.append("-" * 64)
    lines.append(f"final_status: {report['final_status']} "
                 f"(exit {report['exit_code']})")
    lines.append(f"budget: {budget['consumed_seconds']}s consumed / "
                 f"{budget['seconds']}s ({budget['remaining_seconds']}s left)")
    oracle = report.get("oracle") or {}
    if oracle:
        lines.append(f"oracle: VERDICT {oracle.get('verdict', '?')} "
                     f"min_pair_ratio={oracle.get('min_pair_ratio', '?')}")
    lines.append(f"evidence: {report['evidence_dir']}")
    return "\n".join(lines)
