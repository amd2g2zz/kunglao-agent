# -*- coding: utf-8 -*-
"""Issue #342 — web-lane verifier coverage (V2).

Failure class: agents/kunglao-redteam.md carried `lane: malware` (issue 208
material contract), so the ONLY checker agent was lane-gated to malware while
web-re-worker produces web-lane facts — web claims could not promote PROVEN
without the orchestrator silently violating the lane contract.

Lane-keying finding (drives the whole face): scripts/route_capability.py has
NO lane axis — it routes by the `triggers:` frontmatter (intent/features) of
agents/*.md, and kunglao-redteam deliberately has no triggers block (role
agent: check_agent_type skips claim routing for it, "dispatched by protocol
position, not claim routing" — #310 design). The lane axis lives in
hooks/dispatch_gate._lane_gate, which reads the agent's `lane:` frontmatter
against the workspace's task_spec.yaml lane (enum single-sourced in
scripts/lane_spec.py). Therefore the single-source alignment is:

  - agents/kunglao-redteam.md: `lane: malware|web` (the '|' multi-lane form)
  - hooks/dispatch_gate: the declaration parser accepts the multi-lane form
    and the gate refuses only when the workspace lane is OUTSIDE the
    declared set (malware-only behavior preserved for the other four agents;
    kunglao-redteam additionally admitted on web, still refused on
    algorithm/protocol/data/app)
  - the malware face of the redteam contract stays byte-identical; the web
    face is purely additive (allowedTools + BLIND evidence + machine-check
    shapes + attack angles)

ISSUE-355 ADDENDUM (supersedes the lane-LIST frame, keeps this module's intent):
the owner ruled the checker is lane-UNIVERSAL — adversarial verification is
a function, not a domain, so kunglao-redteam.md now declares NO `lane:` and
a lane-absent agent is permitted on every lane. The two tests below that
pinned the malware|web list were reshaped to pin the universal face (the
refusal-on-four-lanes pin inverted into the six-lane admission fixture,
which lives in test_redteam_lane_universal_355.py); every other pin in this
module — allowedTools, additive contract sections, agenttype role rule,
maker route, blind_gate semantics — is unchanged and still green.

Contract pinned here:
  1. kunglao-redteam on a lane: web workspace passes the lane gate (rc=0)
  2. kunglao-redteam on algorithm/protocol/data/app is still refused (rc=2)
  3. the agenttype gate does NOT reject a kunglao-redteam dispatch on a
     web-lane claim (role-agent rule, no agent-reasoning needed)
  4. the maker route for web-lane claims is unchanged (web-re-worker)
  5. blind_gate semantics are lane-agnostic and unchanged: a web-lane claim
     promotes PROVEN with verifier sign-off + dispatch evidence, and is
     blocked without the dispatch evidence
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

REDTEAM = ROOT / "agents" / "kunglao-redteam.md"


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    assert len(parts) >= 3, f"{path.name} must carry frontmatter"
    data = yaml.safe_load(parts[1])
    assert isinstance(data, dict)
    return data


def _declared_lanes() -> set[str]:
    """The parsed lane set of kunglao-redteam.md via the hook's parser."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "dispatch_gate_342", ROOT / "hooks" / "dispatch_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return set(mod._agent_lane_declaration("kunglao-redteam"))


# ------------------------------------------------------------------
# the declaration (was: the malware|web multi-lane list; issue 355: lane-absent)
# ------------------------------------------------------------------

def test_redteam_declares_no_lane_universal():
    """Issue 355: the checker declares NO lane — lane-universal by the owner
    ruling (adversarial checking is a function, not a domain). The parser
    sees no binding, so no lane can refuse it."""
    assert _declared_lanes() == set()
    assert "lane" not in _frontmatter(REDTEAM)


def test_redteam_allowedtools_carry_camoufox():
    """The web face's browser instrumentation is in the tool rack."""
    tools = _frontmatter(REDTEAM).get("allowedTools") or []
    assert "mcp__camoufox-reverse__*" in tools


def test_web_contract_sections_are_additive():
    """The web face must ADD to the malware contract, not replace it: the
    malware BLIND evidence line, the malware machine-check shapes and the
    existing camoufox 'separate supply' acknowledgment all stay, and the
    four issue-named web attack angles are present."""
    text = REDTEAM.read_text(encoding="utf-8")
    # malware face untouched (spot anchors)
    assert "bins/<sha>" in text
    assert "the web lane uses camoufox browser instrumentation" in text
    for token in ("evidence/unpack_out", "verify_signer_offline",
                  "replay_equivalence.py"):
        assert token in text, f"web machine-check shape missing: {token}"
    for angle in ("initiator attribution", "replay-window contamination",
                  "sampled-input bias", "environment gap"):
        assert angle in text, f"web attack angle missing: {angle}"


# ------------------------------------------------------------------
# lane gate end-to-end (the dispatch-time enforcement point)
# ------------------------------------------------------------------

def _run_dispatch_gate(root: Path, ws: Path, subagent_type: str,
                       prompt: str = "[T1] claim C-1 — test"):
    payload = json.dumps({
        "cwd": str(root),
        "workspace": str(ws),
        "tool_input": {"prompt": prompt, "subagent_type": subagent_type},
    })
    return subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "dispatch_gate.py")],
        input=payload, capture_output=True, text=True, timeout=60,
        cwd=str(ROOT), errors="replace")


def _write_lane_ws(root: Path, lane: str | None) -> Path:
    """The 208 harness shape: the workspace is the SIBLING
    `malware-analysis-workspace` of the cwd root — dispatch_gate resolves
    `<cwd>/<layout.workspace_dir>` and ignores payload['workspace']."""
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    lines = (f"lane: {lane}\n" if lane else "") + (
        "goal_verbatim: recover the web signature algorithm\n"
        "success_criterion: offline replay reproduces captured pairs\n"
        "verification_method: replay-evidence\n")
    (ws / "task_spec.yaml").write_text(lines, encoding="utf-8")
    return ws


def test_redteam_passes_lane_gate_on_web_workspace(tmp_path):
    """THE V2 unblock: the checker is dispatchable on the web lane."""
    ws = _write_lane_ws(tmp_path, "web")
    r = _run_dispatch_gate(tmp_path, ws, "kunglao-redteam")
    assert r.returncode == 0, \
        f"kunglao-redteam must pass lane: web — {r.returncode}: {r.stdout}{r.stderr}"
    assert "lane_routing" not in r.stdout + r.stderr


@pytest.mark.parametrize("lane", ["malware", "algorithm", "protocol",
                                  "web", "data", "app"])
def test_redteam_admitted_on_every_lane_355(tmp_path, lane):
    """Issue-355 inversion of the four-lane refusal pin: with the lane axis
    removed from the checker, EVERY lane admits it (the six-lane fixture
    lives in test_redteam_lane_universal_355.py; this keeps the 342-face
    coverage green under the new contract)."""
    ws = _write_lane_ws(tmp_path, lane)
    r = _run_dispatch_gate(tmp_path, ws, "kunglao-redteam")
    assert r.returncode == 0, \
        f"kunglao-redteam must pass lane: {lane} — {r.stdout}{r.stderr}"
    assert "lane_routing" not in r.stdout + r.stderr


def test_redteam_passes_lane_gate_on_malware_and_legacy(tmp_path):
    """The malware face is untouched: declared malware lane AND the legacy
    lane-less contract both keep current behavior."""
    ws = _write_lane_ws(tmp_path, "malware")
    r = _run_dispatch_gate(tmp_path, ws, "kunglao-redteam")
    assert r.returncode == 0, f"malware lane must allow: {r.stderr}"
    ws_legacy = _write_lane_ws(tmp_path, None)
    r = _run_dispatch_gate(tmp_path, ws_legacy, "kunglao-redteam")
    assert r.returncode == 0, f"legacy lane-less must allow: {r.stderr}"


def test_malware_only_agents_keep_single_lane_refusal(tmp_path):
    """An untouched malware-only agent (ghidra-light) is still refused on
    web — the multi-lane parser changes only kunglao-redteam's binding."""
    ws = _write_lane_ws(tmp_path, "web")
    r = _run_dispatch_gate(tmp_path, ws, "ghidra-light")
    assert r.returncode == 2, "ghidra-light must stay malware-only"
    assert "lane_routing" in r.stdout + r.stderr


# ------------------------------------------------------------------
# agenttype gate + maker route (web lane unchanged, verifier unblocked)
# ------------------------------------------------------------------

def _register(ws: Path, statement: str) -> Path:
    p = ws / "claim-register.yaml"
    p.write_text(yaml.safe_dump(
        {"claims": [{"id": "C-001", "status": "OPEN",
                     "statement": statement}]},
        allow_unicode=True), encoding="utf-8")
    return p


def _paths(ws: Path) -> dict:
    return {
        "workspace": str(ws),
        "state": ws / "analysis_state.txt",
        "register": ws / "claim-register.yaml",
        "deps": ws / "claim_deps.yaml",
        "task_spec": ws / "task_spec.yaml",
    }


def test_agenttype_gate_does_not_reject_redteam_on_web_claim(tmp_path):
    """A web-lane verification dispatch of kunglao-redteam passes
    check_agent_type WITHOUT agent-reasoning (role-agent rule: protocol-
    position dispatches skip claim routing — #310 design kept intact)."""
    from worker_budget import check_agent_type
    ws = tmp_path / "ws"
    ws.mkdir()
    _register(ws, "web: recover the js signature algorithm — replay the "
                  "captured requests to verify the initiator attribution")
    ok, msg = check_agent_type(_paths(ws), "C-001",
                               "facts-snapshot: 0 facts", "kunglao-redteam")
    assert ok, f"verifier dispatch must not be rejected: {msg}"


def test_route_capability_maker_face_for_web_claims_unchanged(tmp_path):
    """The web-lane MAKER route stays web-re-worker (route_capability keys
    on the agents' triggers: frontmatter, not lanes — redteam has no
    triggers block and must stay out of the maker table)."""
    import route_capability as rc
    table = rc.load_specialist_table()
    rec, _ = rc.recommend_agent_type(
        {}, "deobfuscate the frontend js and trace the signature "
            "parameter of the webpage", table)
    assert rec == "web-re-worker"
    assert all(s["name"] != "kunglao-redteam" for s in table), \
        "kunglao-redteam must stay a role agent (no triggers: block)"


# ------------------------------------------------------------------
# blind_gate semantics on the web lane (unchanged, proven with fixtures)
# ------------------------------------------------------------------

VALID_SIGNOFF = """\
```yaml
verifier_sign_off:
  verifier_id: kunglao-redteam-w2
  refute_attempt: "tried alternate signer paths; captured pairs hold"
  sign_off_at: 2026-09-22T14:00:00Z
  verdict: CONFIRMED
```
"""


def _web_fact(ws: Path, claim_id: str) -> Path:
    facts = ws / "facts"
    facts.mkdir(exist_ok=True)
    f = facts / f"{claim_id}-web-signature.md"
    f.write_text(
        f"---\nid: {claim_id}-web-signature\ntype: fact\nstatus: INFERRED\n"
        f"created: 2026-09-20\nclaim_id: {claim_id}\n---\n\n"
        "signer recovered from unpack_out registry; replayed offline.\n"
        + VALID_SIGNOFF, encoding="utf-8")
    return f


def test_web_lane_proven_promotion_passes_with_verifier_evidence(tmp_path):
    """blind_gate is lane-agnostic: a web-lane claim with BLIND sign-off +
    dispatched-verifier evidence may promote PROVEN (semantics unchanged)."""
    from blind_gate import check_proven_gate, check_verifier_dispatch_evidence
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "lane: web\ngoal_verbatim: recover the web signature algorithm\n"
        "success_criterion: offline replay reproduces captured pairs\n"
        "verification_method: replay-evidence\n", encoding="utf-8")
    _web_fact(ws, "C-7")
    (ws / "runs" / "verify-redteam-C-7.md").write_text(
        "# Red-team verification: C-7\nRED-TEAM VERDICT: CONFIRMED\n",
        encoding="utf-8")
    ok, reason = check_verifier_dispatch_evidence(ws, "C-7")
    assert ok, f"red-team DIFF names the claim — evidence must pass: {reason}"
    allowed, effective, reason = check_proven_gate("C-7", ws / "facts")
    assert allowed and effective == "PROVEN", reason


def test_web_lane_proven_blocked_without_dispatch_evidence(tmp_path):
    """Same web-lane fixture minus the verifier dispatch record: the
    sign-off alone does NOT promote — the composed promotion gate (the
    compare_register_change_proven_gate face the hook enforces, sign-off +
    dispatched-verifier evidence) blocks the write. Missing records are not
    fail-open (#57 gate 5)."""
    from blind_gate import (check_proven_gate,
                            check_verifier_dispatch_evidence)
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-7", "status": "PROVEN"}]},
                       allow_unicode=True), encoding="utf-8")
    (ws / "task_spec.yaml").write_text("lane: web\n", encoding="utf-8")
    _web_fact(ws, "C-7")
    ok, reason = check_verifier_dispatch_evidence(ws, "C-7")
    assert not ok, "PROVEN without a dispatched verifier must be blocked"
    assert "dispatch" in reason.lower()
    # the sign-off face itself is valid — the block comes from evidence
    allowed, effective, _ = check_proven_gate("C-7", ws / "facts")
    assert allowed and effective == "PROVEN"
    # the composed promotion gate (what compare_register_change enforces
    # for EVERY actor incl. the orchestrator) refuses the promotion
    sys.path.insert(0, str(ROOT / "hooks"))
    from worker_budget_gates import compare_register_change_proven_gate
    allowed, reason = compare_register_change_proven_gate(
        ws / "claim-register.yaml",
        {"C-7": "VERIFIED"},
        "kunglao-worker",
        ws / "facts")
    assert not allowed, f"promotion must be blocked without evidence: {reason}"
