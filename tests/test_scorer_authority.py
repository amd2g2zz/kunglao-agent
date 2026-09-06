# -*- coding: utf-8 -*-
"""tests/test_scorer_authority.py — #499 scorer authority contract tests.

The single authoritative next-claim scorer is scripts/priority_ratio.py
(specs/phase-4/contract.md §1 — the DECIDE ranker, M1 issue #2 VoI-proxy).
scripts/priority.py is a deprecated compatibility module (removal is tracked
by the #446 retirement process).

These tests pin the declaration MECHANICALLY, on a discriminating fixture
where the two scorers DISAGREE about rank #1 (weighted-sum #1 = C-A,
VoI #1 = C-B), so a regression back to the weighted scorer cannot pass:

  1. the live next-up injection (hooks/worker_pulse.py) scores via priority_ratio;
  2. the live dispatch-deviation audit (hooks/worker_budget.check_priority)
     ranks by the SAME authority — the two live faces must never disagree;
  3. caller-side filtering (contract §1: failure-blocked filtering belongs to
     the caller) — the pulse never recommends failure-blocked or
     register-terminal (e.g. RETRACTED) claims;
  4. the deprecated module declares its own deprecation and points at the
     authority, keeping its frozen API importable (#446 prerequisite);
  5. no live-path instruction surface still prescribes the deprecated scorer.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from _factories import write_hook_state

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "scripts"))

ROOT = _HERE.parent

# Live-path instruction surfaces: every file that tells the orchestrator (or
# the heartbeat) WHICH scorer to run. The deprecated priority module must not
# be prescribed on any of them. Note: the string priority_ratio.py does NOT
# contain the substring priority.py, so the check discriminates cleanly.
LIVE_PATH_SURFACES = (
    "hooks/worker_pulse.py",
    "hooks/worker_budget.py",
    "scripts/kunglao_resume.py",
    "scripts/heartbeat_loop_prompt.py",
    "scripts/convergence_check.py",
    # #867 closeout: the kicker's resume prompt prescribes the scorer, and
    # evals pin expected orchestrator behavior — both are instruction faces.
    "scripts/external_kicker.py",
    "evals/evals.json",
    "skills/kunglao-agent/SKILL.md",
    "rules/kunglao-convergence-loop.md",
    "references/decision-rights.md",
    "references/guardrails.md",
    "references/search-policy.md",
    "references/failure-modes.md",
    "references/failure-modes-lifecycle.md",
    "references/_INDEX.md",
)

def _authority_ws(path: Path, *, failure_case: bool = False) -> Path:
    """Synthetic workspace where weighted-sum #1 != VoI #1.

    weighted-sum #1 = C-A (answers_question, 0.65)
    VoI #1 (after caller-side filtering) = C-B (live competitor_group, 0.55)
    C-R (RETRACTED, leverage-boosted) is the RAW VoI #1 (0.85) — must be
    filtered because convergence_check counts RETRACTED terminal
    (TERMINAL_WITH_RETRACTED) while ratio is_open does not (#499 D2).
    With failure_case=True, C-F (promotion_attempts=1, no analysis) is both
    the raw VoI #1 and the convergence failure_blocked entry — the caller
    must skip it (contract: failure-blocked filtering belongs to the caller).
    """
    path.mkdir(parents=True)
    (path / "runs").mkdir()
    claims = [
        {"id": "C-A", "status": "OPEN", "statement": "background work",
         "answers_question": "PQ-1"},
        {"id": "C-B", "status": "OPEN", "statement": "background work",
         "competitor_group": "g1"},
        {"id": "C-B2", "status": "OPEN", "statement": "background work",
         "competitor_group": "g1", "evidence_tier_attempted": 1},
        # C-D only exists to boost the leverage of C-R (downstream OPEN
        # dependent); C-D itself is not dispatchable (its parent C-R has no
        # terminal FACT).
        {"id": "C-D", "status": "OPEN", "statement": "background work"},
        {"id": "C-R", "status": "RETRACTED", "statement": "background work",
         "answers_question": "PQ-9"},
    ]
    depends_on = {"C-D": ["C-R"]}
    if failure_case:
        claims.append({"id": "C-F", "status": "OPEN", "statement": "background work",
                       "answers_question": "PQ-8", "promotion_attempts": 1})
        claims.append({"id": "C-E", "status": "OPEN", "statement": "background work"})
        depends_on["C-E"] = ["C-F"]
    reg = {"claims": claims}
    deps = {
        "depends_on": depends_on,
        "competitor_groups": {"g1": ["C-B", "C-B2"]},
    }
    # JSON is valid YAML — keeps the fixture literal and readable
    (path / "claim-register.yaml").write_text(json.dumps(reg), encoding="utf-8")
    (path / "claim_deps.yaml").write_text(json.dumps(deps), encoding="utf-8")
    (path / "task_spec.yaml").write_text("primary_questions: []\n", encoding="utf-8")
    (path / "runs" / "worker-status-W-1.md").write_text(
        "[12:00] step: work done | status: done\n", encoding="utf-8")
    # #101: these tests pin the VOI authority, which since #101 governs the
    # EXPLOIT period only (explore period audits the cheapness face — see
    # tests/test_kunglao_decide.py). Seed verified facts >= EXPLORE_THRESHOLD
    # via rows citing C-0, a register-external claim id (facts outliving a
    # pruned claim are a legal orphan state): novelty counts derive from
    # in-register claims only, so NO scoring input moves — exactly one thing
    # changes, the gate phase, and every pinned rank/score below stays true.
    (path / "facts").mkdir()
    (path / "facts" / "_INDEX.md").write_text(
        "".join(f"F-90{i} | PROVEN | C-0 | terminal evidence\n"
                for i in range(1, 6)), encoding="utf-8")
    write_hook_state(path, active_hooks=["worker_pulse"],
                     phase="test", tier="none", user_override={},
                     expires_at=None)
    return path


def _pulse_payload(ws: Path) -> dict:
    """Real PostToolUse(Agent) payload shape carrying the dispatch prefix.

    The prefix must satisfy DISPATCH_RE (claim ids there are C-NNN); the
    cited id is inert — the pulse recomputes next-up from the register.
    """
    return {
        "hookEventName": "PostToolUse",
        "tool_name": "Agent",
        "cwd": str(ws),
        "tool_input": {"prompt": "[T1 tools=basic] claim C-02: gather background evidence"},
    }


def _run_pulse(payload: dict) -> str:
    """Run hooks/worker_pulse.py exactly as wired (JSON payload on stdin)."""
    r = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "worker_pulse.py")],
        input=json.dumps(payload), capture_output=True,
        encoding="utf-8", errors="replace",
        env={"PYTHONIOENCODING": "utf-8", **os.environ},
        cwd=str(ROOT), timeout=120,
    )
    return (r.stdout or "") + (r.stderr or "")

def test_pulse_next_up_scores_via_priority_ratio(tmp_path) -> None:
    """The live next-up injection recommends the VoI #1 (C-B), not the
    weighted-sum #1 (C-A) — the discriminating assertion for #499."""
    ws = _authority_ws(tmp_path / "ws")
    out = _run_pulse(_pulse_payload(ws))
    assert "next up: C-B" in out, (
        "worker_pulse next-up must score via priority_ratio (VoI #1 = C-B). "
        f"Got:\n{out}")
    assert "next up: C-A" not in out, (
        "worker_pulse next-up still scores via the deprecated weighted scorer "
        f"(weighted #1 = C-A recommended). Got:\n{out}")


def test_pulse_filters_failure_blocked_and_terminal(tmp_path) -> None:
    """Caller-side filtering: the raw VoI #1 (C-F failure-blocked / C-R
    RETRACTED) must never be recommended; next-up falls through to C-B."""
    ws = _authority_ws(tmp_path / "ws-fail", failure_case=True)
    out = _run_pulse(_pulse_payload(ws))
    assert "next up: C-B" in out, (
        f"next-up must fall through to C-B after filtering. Got:\n{out}")
    assert "next up: C-F" not in out, (
        "failure-blocked claim (failed attempt, no failure_analysis) must not "
        "be recommended — contract: failure-blocked filtering belongs to the "
        f"caller. Got:\n{out}")
    assert "next up: C-R" not in out, (
        "RETRACTED claim (terminal per convergence_check) must not be "
        f"recommended. Got:\n{out}")


def _novelty_ws(path: Path) -> Path:
    """Workspace where the CALLER-FILTER WIDTH changes the ranking.

    Three terminal-status claims (C-D1 DEFERRED, C-D2 STALE, C-D3 DEFERRED)
    each carry a terminal fact in action category c2_config_extract; C-A
    (OPEN, same category, answers_question) and C-B (OPEN, plain) are the
    only rankable claims:

      terminal rows retained  -> fact_counts={c2_config_extract: 3}
                                 -> N(C-A)=0.0 -> C-A 0.15 < C-B 0.31
                                 -> rank #1 = C-B
      terminal rows dropped   -> fact_counts={} -> N(C-A)=1.0
                                 -> C-A 0.40 > C-B 0.31
                                 -> rank #1 = C-A
    """
    path.mkdir(parents=True)
    (path / "runs").mkdir()
    claims = [
        {"id": "C-D1", "status": "DEFERRED", "statement": "c2 config extract"},
        {"id": "C-D2", "status": "STALE", "statement": "c2 config extract"},
        {"id": "C-D3", "status": "DEFERRED", "statement": "c2 config extract"},
        {"id": "C-A", "status": "OPEN", "statement": "c2 config extract",
         "answers_question": "PQ-1"},
        {"id": "C-B", "status": "OPEN", "statement": "background work"},
    ]
    (path / "claim-register.yaml").write_text(
        json.dumps({"claims": claims}), encoding="utf-8")
    (path / "claim_deps.yaml").write_text(
        json.dumps({"depends_on": {}, "competitor_groups": {}}), encoding="utf-8")
    (path / "task_spec.yaml").write_text("primary_questions: []\n", encoding="utf-8")
    # #101: five PROVEN rows (not three) push the workspace past the explore
    # gate — this test pins the EXPLOIT-period VoI authority. The extra rows
    # cite the SAME terminal claims, so the per-claim category counts (the
    # thing the novelty assertion is about) are untouched.
    (path / "facts").mkdir()
    (path / "facts" / "_INDEX.md").write_text(
        "F-101 | PROVEN | C-D1 | c2 config extracted\n"
        "F-102 | PROVEN | C-D2 | c2 config extracted\n"
        "F-103 | PROVEN | C-D3 | c2 config extracted\n"
        "F-104 | PROVEN | C-D1 | c2 config extracted\n"
        "F-105 | PROVEN | C-D2 | c2 config extracted\n", encoding="utf-8")
    return path


def test_check_priority_audits_against_priority_ratio(tmp_path) -> None:
    """The dispatch-deviation audit ranks by priority_ratio: dispatching the
    VoI #1 (C-B) is NOT a deviation; dispatching the weighted #1 (C-A) IS."""
    import worker_budget as wb
    ws = _authority_ws(tmp_path / "ws")
    ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), "C-B", ws=ws)
    assert (ok, deviated) == (True, False), (
        "dispatching the VoI #1 (C-B) must be a silent rank-#1 dispatch. "
        f"Got: ok={ok} deviated={deviated} msg={msg!r}")
    ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), "C-A", ws=ws)
    assert deviated is True, "dispatching the weighted #1 (C-A) must register as a deviation"
    assert "C-B" in msg, f"the advisory must name the authority #1 (C-B). Got: {msg!r}"
    # Injection M5 guard: on a failure-blocked workspace (failure_case=True,
    # C-F = failed attempt without failure_analysis), the BLOCKED pre-filter
    # must keep C-F out of the rank. Mutation replay proof: with the
    # pre-filter deleted, C-F surfaces as the raw VoI #1 (0.85) and
    # dispatching it returns a SILENT (True, '', False) rank-#1 — the audit
    # then contradicts convergence_check (cc: BLOCKED), breaking the
    # docstring promise "this audit never contradicts convergence_check".
    ws = _authority_ws(tmp_path / "ws-fail", failure_case=True)
    ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), "C-F", ws=ws)
    assert (ok, deviated) == (True, False), (
        "dispatching a failure-blocked claim is an ADVISORY, never a REJECT. "
        f"Got: ok={ok} deviated={deviated} msg={msg!r}")
    assert msg and "C-F" in msg and "C-B" in msg, (
        "dispatching failure-blocked C-F must NOT be a silent rank-#1: cc "
        "says BLOCKED for this workspace, so the audit must flag the "
        f"dispatch and name the true authority #1 (C-B). Got: {msg!r}")
    ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), "C-B", ws=ws)
    assert (ok, msg, deviated) == (True, '', False), (
        f"C-B stays the silent rank-#1 on the failure fixture. Got: {msg!r}")


def test_budget_filter_keeps_terminal_rows_for_novelty(tmp_path) -> None:
    """Injection M4 guard: the claims list handed to _ratio_rank KEEPS
    DEFERRED/STALE rows — the caller filter removes only RETRACTED (+ the
    failure-blocked set). Widening the filter set back to the full terminal
    set drops those rows before _fact_count_by_category, silently erasing
    their categories from novelty counting and flipping rank #1 (C-B -> C-A).
    """
    import worker_budget as wb
    ws = _novelty_ws(tmp_path / "ws-novelty")
    ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), "C-B", ws=ws)
    assert (ok, msg, deviated) == (True, '', False), (
        "with DEFERRED/STALE rows retained, their 3 terminal facts saturate "
        "c2_config_extract novelty -> C-B (0.31) outranks C-A (0.15) and the "
        "C-B dispatch is a silent rank-#1. A deviation here means the caller "
        f"filter over-filtered terminal rows. Got: ok={ok} deviated={deviated} msg={msg!r}")
    ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), "C-A", ws=ws)
    assert deviated is True, (
        "C-A (novelty-suppressed by the retained terminal facts) is NOT rank #1")
    assert "C-B" in msg, f"the advisory must name the authority #1 (C-B). Got: {msg!r}"


@pytest.mark.parametrize("rel", LIVE_PATH_SURFACES)
def test_live_path_prescribes_authority_only(rel: str) -> None:
    """No live-path instruction surface may still prescribe the deprecated module."""
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert "priority.py" not in text, (
        f"{rel} still prescribes the deprecated scorer — the sanctioned "
        "scorer is priority_ratio.py (#499)")


def test_worker_pulse_wiring_subprocess_target() -> None:
    """Static wiring: the pulse next-up subprocess targets priority_ratio.

    EXACT-path assertion (injection M1 postmortem): the earlier substring
    check (`"priority_ratio.py" in src`) was satisfied by the code COMMENT,
    not the wiring — under mutation M1 (subprocess target reverted to
    priority.py) this test itself stayed green while the wiring had flipped;
    only the e2e pulse tests caught it. The exact construction below appears
    solely in the wiring line, so a comment can no longer mask a flip.
    """
    src = (ROOT / "hooks" / "worker_pulse.py").read_text(encoding="utf-8")
    assert 'str(SKILL_DIR / "scripts" / "priority_ratio.py")' in src, (
        "worker_pulse.py must construct its next-up subprocess target from "
        "scripts/priority_ratio.py (#499) — exact wiring construction, not "
        "just the module name appearing somewhere in the file")
