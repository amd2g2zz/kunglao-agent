#!/usr/bin/env python3
"""Safe repository-only replays for long-horizon closure failures."""
from __future__ import annotations

import inspect
import json
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "hooks"))

import convergence_check
import fact_contradiction_gate
import kunglao_record
import provenance_gate


def write_workspace(root: Path, *, contradictory: bool = False) -> Path:
    workspace = root / ("contradiction" if contradictory else "omission")
    (workspace / "facts").mkdir(parents=True)
    (workspace / "runs").mkdir()
    (workspace / "task_spec.yaml").write_text(
        "primary_questions:\n"
        "  - id: q1\n"
        "    q: What behavior was found?\n"
        "    need: yes_no_with_evidence\n",
        encoding="utf-8",
    )
    claims = [{"id": "C-001", "status": "PROVEN", "answers_question": "q1"}]
    if contradictory:
        claims.append({"id": "C-002", "status": "PROVEN", "answers_question": "q1"})
    (workspace / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, sort_keys=False), encoding="utf-8"
    )
    if contradictory:
        index = (
            "# facts\n"
            "F001 | PROVEN | C-001 | payload is shellcode\n"
            "F002 | PROVEN | C-002 | payload is not shellcode\n"
        )
        (workspace / "facts" / "F001.md").write_text(
            "sample_refs: artifact-A\n", encoding="utf-8"
        )
        (workspace / "facts" / "F002.md").write_text(
            "sample_refs: artifact-A\n", encoding="utf-8"
        )
    else:
        index = (
            "# facts\n"
            "F001 | PROVEN | C-001 | embedded shellcode discovered; "
            "downstream payload analysis not performed\n"
        )
        (workspace / "facts" / "F001.md").write_text(
            "Evidence says embedded shellcode exists.\n"
            "Next question: extract and analyze the payload.\n",
            encoding="utf-8",
        )
    (workspace / "facts" / "_INDEX.md").write_text(index, encoding="utf-8")
    return workspace


def write_activated(root: Path, *, with_oracle: bool) -> Path:
    """ACTIVATED workspace: claim-register + real .hook_state.json (+ optional
    unsatisfied task-oracle). The completion hook must block it either way
    (replay #4 second half, issue #200)."""
    import datetime as dt
    import json

    ws = root / ("activated_ws" if with_oracle else "activated_ws_no_oracle")
    (ws / "facts").mkdir(parents=True)
    (ws / "facts" / "_INDEX.md").write_text("# facts\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": []}, sort_keys=False), encoding="utf-8"
    )
    expires = (dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(minutes=30)
               ).isoformat(timespec="seconds").replace("+00:00", "Z")
    (ws / ".hook_state.json").write_text(json.dumps({
        "ts": "2026-08-13T00:00:00Z",
        "tier": "none",
        "phase": "IDLE",
        "active_hooks": ["completion_gate"],
        "paused_hooks": [],
        "user_override": {},
        "expires_at": expires,
    }, indent=2), encoding="utf-8")
    if with_oracle:
        (ws / "task-oracle.yaml").write_text(
            yaml.safe_dump({
                "task_text": "analyze the payload",
                "open_items": [{"id": "G1", "desc": "unresolved", "closed_by": ""}],
                "deferrals": [],
            }, sort_keys=False), encoding="utf-8"
        )
    return ws


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="kunglao-replay-") as temp_dir:
        root = Path(temp_dir)
        omission = write_workspace(root)
        contradiction = write_workspace(root, contradictory=True)

        omission_decision = convergence_check.decide(omission)
        contradiction_pairs = fact_contradiction_gate.scan_conflicts(
            contradiction / "facts" / "_INDEX.md", contradiction / "facts"
        )
        contradiction_decision = convergence_check.decide(contradiction)

        summary_fact = omission / "facts" / "F001.md"
        provenance_ok, provenance_reason = provenance_gate.check_provenance_gate(
            summary_fact, omission
        )
        migrator_source = inspect.getsource(kunglao_record.claim_migrator)

        import completion_gate as hook_completion_gate

        # #200: replay #4 workspaces — recompute the hook exit codes instead
        # of the old hardcoded forbidden_outcome_observed=True.
        no_oracle_rc = hook_completion_gate.process_event(
            {"cwd": str(write_activated(root, with_oracle=False))})
        second_stop_rc = hook_completion_gate.process_event(
            {"cwd": str(write_activated(root, with_oracle=True)),
             "stop_hook_active": True})

        results = {
            "scope": "repository-only; no sample or VM execution",
            "replays": [
                {
                    "id": "discovered-shellcode-not-materialized-as-obligation",
                    "current_decision": omission_decision["decision"],
                    "forbidden_outcome_observed": omission_decision["decision"] == "CONVERGED",
                    "mechanism": "convergence reads registered claims and index status, not next questions in fact bodies",
                },
                {
                    "id": "global-contradiction-not-consulted-at-completion",
                    "detected_conflicts": contradiction_pairs,
                    "current_decision": contradiction_decision["decision"],
                    "forbidden_outcome_observed": bool(contradiction_pairs)
                    and contradiction_decision["decision"] == "CONVERGED",
                    "mechanism": "promotion-time contradiction gate exists, but convergence_check does not scan global conflicts",
                },
                {
                    "id": "summary-without-raw-provenance",
                    "provenance_gate_result": provenance_ok,
                    "provenance_gate_reason": provenance_reason,
                    "promotion_path_calls_provenance_gate": "check_provenance_gate" in migrator_source,
                    "forbidden_outcome_observed": not provenance_ok
                    and "check_provenance_gate" not in migrator_source,
                    "mechanism": "the checker rejects summary-only evidence, but the PROVEN migration path does not call it",
                },
                {
                    "id": "completion-hook-opt-in-bypass",
                    "activated_ws_no_oracle_rc": no_oracle_rc,
                    "second_stop_rc": second_stop_rc,
                    # #200: no hardcoded True — recomputed from the actual hook
                    # exit codes. Both must be non-zero for the closure to hold.
                    "forbidden_outcome_observed": (
                        no_oracle_rc == 0 or second_stop_rc == 0
                    ),
                    "mechanism": "missing oracle and second Stop attempt now fail closed (exit 3 / exit 1) instead of passing through",
                },
            ],
        }
        results["summary"] = {
            "replays": len(results["replays"]),
            "forbidden_outcomes_observed": sum(
                1 for replay in results["replays"] if replay["forbidden_outcome_observed"]
            ),
        }
        output = ROOT / ".research-tree" / "experiments" / "incident-replay-result.json"
        output.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
