# -*- coding: utf-8 -*-
"""Completion transaction (issue #202): CONVERGED requires a GLOBAL
contradiction recompute — the workspace facts index, not a pre-filled
oracle, is the authority.

Replay #2 mechanism: two same-topic PROVEN facts with opposite
conclusions; decide() returns CONVERGED and judge() trusts the oracle.
"""
import sys
from pathlib import Path

import yaml

# #770: bind the scripts TWIN by explicit path (#762 convention) — the ini
# orders hooks before scripts, so a bare import of this shared name resolves
# to the hooks side and is NOT what this suite exercises.
import importlib.util

_cg_scripts_spec = importlib.util.spec_from_file_location("completion_gate_scripts", Path(__file__).resolve().parents[1] / "scripts" / "completion_gate.py")
cg_scripts = importlib.util.module_from_spec(_cg_scripts_spec)
import sys as _sys
_sys.modules["completion_gate_scripts"] = cg_scripts
_cg_scripts_spec.loader.exec_module(cg_scripts)

import convergence_check


def _contradictory_ws(ws: Path) -> Path:
    (ws / "facts").mkdir(parents=True)
    (ws / "facts" / "_INDEX.md").write_text(
        "# facts\n"
        "F001 | PROVEN | C-001 | payload is shellcode\n"
        "F002 | PROVEN | C-002 | payload is not shellcode\n",
        encoding="utf-8",
    )
    (ws / "facts" / "F001.md").write_text("sample_refs: artifact-A\n", encoding="utf-8")
    (ws / "facts" / "F002.md").write_text("sample_refs: artifact-A\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(
            {"claims": [
                {"id": "C-001", "status": "PROVEN", "answers_question": "q1"},
                {"id": "C-002", "status": "PROVEN", "answers_question": "q1"},
            ]},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n"
        "  - id: q1\n"
        "    q: What behavior was found?\n"
        "    need: yes_no_with_evidence\n",
        encoding="utf-8",
    )
    return ws


def test_judge_blocks_on_global_contradiction(tmp_path):
    """judge() must recompute GLOBAL contradictions from the workspace
    facts index, not trust a pre-filled oracle (research replay #2)."""
    ws = tmp_path / "ws"
    _contradictory_ws(ws)

    oracle = {
        "task_text": "analyze the payload",
        "open_items": [],
        "workspace_path": str(ws),
    }
    code, reason = cg_scripts.judge(oracle)
    assert code != 0, f"judge must block on global contradiction, got {code}: {reason}"
    assert "CONTRADICTION" in reason.upper()


def test_decide_downgrades_converged_on_contradiction(tmp_path):
    """When the register says CONVERGED, decide() must run the completion
    transaction (contradiction recompute) and downgrade the decision
    (research replay #2: detected_conflicts non-empty + CONVERGED)."""
    ws = tmp_path / "ws"
    _contradictory_ws(ws)

    d = convergence_check.decide(ws)
    assert d["decision"] != "CONVERGED", d
    assert "CONTRADICTION" in (d.get("action") or "").upper()
