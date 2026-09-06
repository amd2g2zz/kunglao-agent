# -*- coding: utf-8 -*-
"""tests/test_scorer_authority.py — #499/#107 scorer authority contract tests.

The single authoritative next-claim scorer is scripts/priority_ratio.py
(specs/phase-4/contract.md §1). #107 rebuilt it as the Thompson ranker and
deleted the explore/exploit dual path, so there is exactly ONE ranking face:
kunglao-decide, the dispatch-deviation audit (worker_budget.check_priority)
and the worker_pulse next-up injection all rank through it.

These tests pin the declaration MECHANICALLY — every live face must agree
with a direct call into the ranker module made in the test itself (same
inputs, same seed), so any authority drift (a copied ranker, a second seed,
a hardcoded order) cannot pass:

  1. the live next-up injection (hooks/worker_pulse.py) scores via
     priority_ratio — its recommendation equals the module's own top;
  2. the live dispatch-deviation audit (worker_budget.check_priority)
     audits against the SAME ranker + posterior seed — dispatching the
     module's top is silent, anything else deviates with a `thompson` tag;
  3. caller-side filtering (contract §1: failure-blocked / RETRACTED
     filtering belongs to the caller) stays MINIMAL — a rank-None dispatch
     stays an advisory, never a silent pass;
  4. no live-path instruction surface still prescribes a deprecated scorer.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
import pytest
from _factories import write_hook_state

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "scripts"))

ROOT = _HERE.parent

# Live-path instruction surfaces: every file that tells the orchestrator (or
# the heartbeat) WHICH scorer to run. A deprecated module must not be
# prescribed on any of them. Note: the string priority_ratio.py does NOT
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
    """Synthetic workspace with a NON-TRIVIAL rank order (five claims, one
    competitor group, one RETRACTED row the caller must filter, and — with
    failure_case=True — a failed attempt the caller must filter too)."""
    path.mkdir(parents=True)
    (path / "runs").mkdir()
    claims = [
        {"id": "C-A", "status": "OPEN", "statement": "background work",
         "answers_question": "PQ-1"},
        {"id": "C-B", "status": "OPEN", "statement": "background work",
         "competitor_group": "g1"},
        {"id": "C-B2", "status": "OPEN", "statement": "background work",
         "competitor_group": "g1", "evidence_tier_attempted": 1},
        # C-D only exists to give C-R a downstream dependent in the graph.
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
    write_hook_state(path, active_hooks=["worker_pulse"],
                     phase="test", tier="none", user_override={},
                     expires_at=None)
    return path


def _authority_rank(ws: Path, *, rng_posterior: bool):
    """A direct call into THE ranker with the caller filters the live faces
    apply: minus RETRACTED (and, when ws carries them, the failure-blocked
    set). rng_posterior=True reproduces check_priority's seed; False is the
    CLI/pulse default seed."""
    import priority_ratio as pr
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    deps = yaml.safe_load((ws / "claim_deps.yaml").read_text(encoding="utf-8"))
    claims = [c for c in reg["claims"]
              if (c.get("status") or "").upper() != "RETRACTED"]
    if ws is not None:
        try:
            import failure_analysis_gate as fag
            blocked = {b["claim_id"] for b in fag.scan_workspace(ws)
                       if b.get("state") == "BLOCKED"}
            claims = [c for c in claims if c.get("id") not in blocked]
        except Exception:
            pass
    ev = pr.EvidenceView.from_workspace(ws)
    rng = pr.posterior_rng(ws) if rng_posterior else None
    return pr.priority_ratio(claims, deps, ev, rng=rng)


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


def _pulse_expected_top(ws: Path) -> str:
    """The ranker's top among the claims cc would still count open (the
    pulse's own eligibility filter)."""
    import convergence_check as cc
    cc_open = {c.get("id") for c in cc.decide(ws).get("open_claims", [])
               if c.get("id")}
    for a in _authority_rank(ws, rng_posterior=False):
        if a.claim_id in cc_open:
            return a.claim_id
    raise AssertionError("no eligible rank in fixture")


def test_pulse_next_up_scores_via_priority_ratio(tmp_path) -> None:
    """The live next-up injection recommends THE RANKER's top — computed by
    calling priority_ratio in this test with the same inputs (any authority
    drift between pulse and module fails here)."""
    ws = _authority_ws(tmp_path / "ws")
    expected = _pulse_expected_top(ws)
    out = _run_pulse(_pulse_payload(ws))
    assert f"next up: {expected}" in out, (
        f"worker_pulse next-up must equal the priority_ratio top "
        f"({expected}). Got:\n{out}")


def test_pulse_filters_failure_blocked_and_terminal(tmp_path) -> None:
    """Caller-side filtering: the failure-blocked (C-F) and RETRACTED (C-R)
    rows must never be recommended; next-up falls through to the ranker's
    top among the eligible set."""
    ws = _authority_ws(tmp_path / "ws-fail", failure_case=True)
    expected = _pulse_expected_top(ws)
    assert expected not in ("C-F", "C-R"), "fixture sanity: filtered rows"
    out = _run_pulse(_pulse_payload(ws))
    assert f"next up: {expected}" in out, (
        f"next-up must fall through to the eligible top ({expected}). "
        f"Got:\n{out}")
    assert "next up: C-F" not in out, (
        "failure-blocked claim (failed attempt, no failure_analysis) must not "
        f"be recommended — contract: failure-blocked filtering belongs to the "
        f"caller. Got:\n{out}")
    assert "next up: C-R" not in out, (
        "RETRACTED claim (terminal per convergence_check) must not be "
        f"recommended. Got:\n{out}")


def test_check_priority_audits_against_thompson_ranker(tmp_path) -> None:
    """The dispatch-deviation audit ranks by THE ranker with the posterior
    seed: dispatching the module's top is a silent rank-#1 pass; dispatching
    any other dispatchable claim deviates, and the advisory names the
    authority (thompson) plus the true #1."""
    import worker_budget as wb
    ws = _authority_ws(tmp_path / "ws")
    actions = _authority_rank(ws, rng_posterior=True)
    top = actions[0]
    ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), top.claim_id, ws=ws)
    assert (ok, msg, deviated) == (True, '', False), (
        f"dispatching the ranker #1 ({top.claim_id}) must be a silent "
        f"rank-#1 dispatch. Got: ok={ok} deviated={deviated} msg={msg!r}")
    other = next(a for a in actions if a.claim_id != top.claim_id)
    ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), other.claim_id, ws=ws)
    assert deviated is True, (
        f"dispatching a non-#1 ({other.claim_id}) must register as a deviation")
    assert top.claim_id in msg and "thompson" in msg.lower(), (
        f"the advisory must name the authority #1 ({top.claim_id}) and the "
        f"thompson authority. Got: {msg!r}")
    # Injection M5 guard: on a failure-blocked workspace (failure_case=True,
    # C-F = failed attempt without failure_analysis), the BLOCKED pre-filter
    # must keep C-F out of the rank — dispatching it is an ADVISORY naming
    # the true authority #1, never a silent pass.
    ws = _authority_ws(tmp_path / "ws-fail", failure_case=True)
    fail_top = _authority_rank(ws, rng_posterior=True)[0]
    ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), "C-F", ws=ws)
    assert (ok, deviated) == (True, False), (
        "dispatching a failure-blocked claim is an ADVISORY, never a REJECT. "
        f"Got: ok={ok} deviated={deviated} msg={msg!r}")
    assert msg and "C-F" in msg and fail_top.claim_id in msg, (
        "dispatching failure-blocked C-F must NOT be a silent rank-#1: cc "
        "says BLOCKED for this workspace, so the audit must flag the "
        f"dispatch and name the true authority #1 ({fail_top.claim_id}). "
        f"Got: {msg!r}")
    ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), fail_top.claim_id, ws=ws)
    assert (ok, msg, deviated) == (True, '', False), (
        f"the filtered rank's #1 ({fail_top.claim_id}) stays a silent "
        f"dispatch on the failure fixture. Got: {msg!r}")


def test_rank_none_dispatch_gets_advisory_not_silent_pass(tmp_path) -> None:
    """The caller filter stays MINIMAL: a RETRACTED row is removed by the
    caller (rank-None for the audit), and a dispatch of it is flagged with
    an advisory — never a silent pass that would contradict
    convergence_check's terminal counting."""
    import worker_budget as wb
    ws = _authority_ws(tmp_path / "ws-retract")
    ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), "C-R", ws=ws)
    assert (ok, deviated) == (True, False), (
        f"a rank-None dispatch is an advisory, never a REJECT; got "
        f"{ok=} {deviated=} {msg=!r}")
    assert "C-R" in msg and "not in dispatchable set" in msg, (
        f"the advisory must say the dispatched claim is undispatchable. "
        f"Got: {msg!r}")


@pytest.mark.parametrize("rel", LIVE_PATH_SURFACES)
def test_live_path_prescribes_authority_only(rel: str) -> None:
    """No live-path instruction surface may still prescribe a deprecated module."""
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert "priority.py" not in text, (
        f"{rel} still prescribes the deprecated scorer — the sanctioned "
        "scorer is priority_ratio.py (#499/#107)")


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
