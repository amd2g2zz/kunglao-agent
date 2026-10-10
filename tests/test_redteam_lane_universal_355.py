# -*- coding: utf-8 -*-
"""Issue 355 — the red-team checker is lane-universal by design.

Owner ruling (2026-09-23): "redteam是用来做对抗校验的。跟web没有冲突。跟
malware更是没有关系。所有的证据都需要redteam去做对抗" — the checker is
defined by its FUNCTION (adversarial verification: blind re-derivation,
>=2 independent paths, machine-check oracle), not by any material domain.
Issue 342's `lane: malware|web` preserved the wrong frame (a lane LIST on the
checker); issue 355 removes the axis: agents/kunglao-redteam.md declares NO
`lane:`, and hooks/dispatch_gate treats a lane-absent agent as permitted on
every lane. The `lane:` axis governs maker-type agents only (ghidra-light,
go-symbols, pefile-signature, floss-filter — material contracts, unchanged).

Contract pinned here:
  1. THE fixture: kunglao-redteam dispatches rc=0 on all six lanes
     (malware / algorithm / protocol / web / data / app) — the four lanes
     issue 342 left blocked are the regression core.
  2. role agents (redteam, init-worker, verdict-scorer) declare no lane —
     lane-universal by construction, no runtime role detection involved.
  3. maker lane-gating unchanged: ghidra-light still refused on web,
     allowed on malware. web-re-worker stays lane-absent (its unchanged
     contract — it never declared a lane; gating it would be a maker lane
     contract change, out of issue-355 scope).
  4. identity cannot dodge the gate: a plugin-qualified subagent_type
     ("kunglao-agent:ghidra-light") resolves to the same agents/<bare>.md
     frontmatter (the _waiting_target_id bare-segment convention) — a
     crafted payload id must not bypass the lane refusal.
  5. blind_gate semantics unchanged and lane-agnostic: PROVEN promotion
     still requires sign-off + dispatched-verifier evidence on a
     non-web lane too.
"""
from __future__ import annotations

import importlib.util
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

ALL_LANES = ("malware", "algorithm", "protocol", "web", "data", "app")
ROLE_AGENTS = ("kunglao-redteam", "kunglao-init-worker", "verdict-scorer")


# ------------------------------------------------------------------ harness

def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    assert len(parts) >= 3, f"{path.name} must carry frontmatter"
    data = yaml.safe_load(parts[1])
    assert isinstance(data, dict)
    return data


def _load_gate_module():
    spec = importlib.util.spec_from_file_location(
        "dispatch_gate_355", ROOT / "hooks" / "dispatch_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_lane_ws(root: Path, lane: str | None) -> Path:
    """The 208/342 harness shape: the workspace is the SIBLING
    `malware-analysis-workspace` of the cwd root."""
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    lines = (f"lane: {lane}\n" if lane else "") + (
        "goal_verbatim: recover the target's core secret\n"
        "success_criterion: independent derivation reproduces the pairs\n"
        "verification_method: replay-evidence\n")
    (ws / "task_spec.yaml").write_text(lines, encoding="utf-8")
    return ws


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


# ------------------------------------- 1. THE six-lane admission fixture

def test_redteam_declares_no_lane():
    """The `lane:` line is GONE from the checker contract (issue 355): the
    parser sees no binding, and no binding means every lane."""
    mod = _load_gate_module()
    assert mod._agent_lane_declaration("kunglao-redteam") == ()
    assert "lane" not in _frontmatter(ROOT / "agents" / "kunglao-redteam.md")


@pytest.mark.parametrize("lane", ALL_LANES)
def test_redteam_rc0_on_all_six_lanes(tmp_path, lane):
    """THE acceptance fixture: rc=0 on every lane — including the four
    (algorithm / protocol / data / app) that issue 342 left refused."""
    ws = _write_lane_ws(tmp_path, lane)
    r = _run_dispatch_gate(tmp_path, ws, "kunglao-redteam")
    assert r.returncode == 0, \
        f"kunglao-redteam must pass lane: {lane} — {r.returncode}: " \
        f"{r.stdout}{r.stderr}"
    assert "lane_routing" not in r.stdout + r.stderr


def test_redteam_rc0_on_legacy_laneless_workspace(tmp_path):
    """A lane-less (legacy) contract keeps the pre-issue-208 behavior: pass."""
    ws = _write_lane_ws(tmp_path, None)
    r = _run_dispatch_gate(tmp_path, ws, "kunglao-redteam")
    assert r.returncode == 0, f"legacy lane-less must pass: {r.stderr}"


# --------------------------------- 2. role agents are lane-absent by design

def test_role_agents_declare_no_lane():
    """Role agents are dispatched by protocol position (issue 310), never by
    claim routing — none of them declares a lane axis. The 'role agent'
    determination is the git-versioned agent FILE (frontmatter truth),
    not a runtime property a dispatch payload could influence."""
    for name in ROLE_AGENTS:
        fm = _frontmatter(ROOT / "agents" / f"{name}.md")
        assert "lane" not in fm, \
            f"agents/{name}.md must not declare a lane axis (#355)"
        assert _load_gate_module()._agent_lane_declaration(name) == ()


# ------------------------------------------ 3. maker lane-gating unchanged

def test_ghidra_light_still_refused_on_web(tmp_path):
    """Regression pin (issue 342 / 208 intent): a malware-lane maker stays
    refused outside its declared lane."""
    ws = _write_lane_ws(tmp_path, "web")
    r = _run_dispatch_gate(tmp_path, ws, "ghidra-light")
    assert r.returncode == 2, \
        f"ghidra-light must stay malware-only: {r.stdout}{r.stderr}"
    assert "lane_routing" in r.stdout + r.stderr


def test_ghidra_light_allowed_on_malware_lane(tmp_path):
    ws = _write_lane_ws(tmp_path, "malware")
    r = _run_dispatch_gate(tmp_path, ws, "ghidra-light")
    assert r.returncode == 0, f"declared lane must allow: {r.stderr}"


def test_web_re_worker_contract_unchanged_lane_absent(tmp_path):
    """web-re-worker is a lane-ABSENT maker (it has never declared a
    `lane:` — verified across its full git history): its admission face is
    unchanged by issue 355 on every lane, malware included. Gating it would be
    a maker lane-contract change — explicitly out of issue-355 scope."""
    fm = _frontmatter(ROOT / "agents" / "web-re-worker.md")
    assert "lane" not in fm
    for lane in ("malware", "web"):
        ws = _write_lane_ws(tmp_path, lane)
        r = _run_dispatch_gate(tmp_path, ws, "web-re-worker")
        assert r.returncode == 0, \
            f"web-re-worker (lane-absent) must pass lane: {lane}: {r.stderr}"


# ------------------------------- 4. the payload cannot dodge the gate

def test_plugin_qualified_maker_id_cannot_dodge(tmp_path):
    """A plugin-qualified subagent_type resolves to the same
    agents/<bare>.md frontmatter (the _waiting_target_id bare-segment
    convention): 'kunglao-agent:ghidra-light' on a web workspace must be
    REFUSED, not silently admitted through an unresolvable filename."""
    ws = _write_lane_ws(tmp_path, "web")
    r = _run_dispatch_gate(tmp_path, ws, "kunglao-agent:ghidra-light")
    assert r.returncode == 2, \
        f"plugin-qualified maker id must not dodge the lane gate: " \
        f"{r.stdout}{r.stderr}"
    assert "lane_routing" in r.stdout + r.stderr


def test_plugin_qualified_role_id_stays_universal(tmp_path):
    """The mirror face: the qualified checker id parses to the lane-absent
    contract and stays admitted everywhere."""
    ws = _write_lane_ws(tmp_path, "protocol")
    r = _run_dispatch_gate(tmp_path, ws, "kunglao-agent:kunglao-redteam")
    assert r.returncode == 0, f"qualified checker id must pass: {r.stderr}"


# ----------------------------- 5. blind_gate semantics unchanged

VALID_SIGNOFF = """\
```yaml
verifier_sign_off:
  verifier_id: kunglao-redteam-w2
  refute_attempt: "tried alternate key schedules; captured pairs hold"
  sign_off_at: 2026-09-23T10:00:00Z
  verdict: CONFIRMED
```
"""


def _fact_with_signoff(ws: Path, claim_id: str) -> None:
    facts = ws / "facts"
    facts.mkdir(exist_ok=True)
    (facts / f"{claim_id}-protocol.md").write_text(
        f"---\nid: {claim_id}-protocol\ntype: fact\nstatus: INFERRED\n"
        f"created: 2026-09-23\nclaim_id: {claim_id}\n---\n\n"
        "handshake state machine re-derived from the capture.\n"
        + VALID_SIGNOFF, encoding="utf-8")


def test_blind_gate_dispatch_evidence_required_on_protocol_lane(tmp_path):
    """blind_gate is lane-agnostic AND unchanged (issue 355 touches admission
    only): on a protocol-lane workspace the sign-off alone does NOT
    promote — the dispatched-verifier evidence is still required, and the
    composed register gate still blocks the promotion."""
    from blind_gate import check_verifier_dispatch_evidence
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "runs").mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-9", "status": "PROVEN"}]},
                       allow_unicode=True), encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "lane: protocol\n" + "".join(
            f"{k}: {v}\n" for k, v in {
                "goal_verbatim": "recover the handshake state machine",
                "success_criterion": "independent derivation reproduces "
                                     "the pairs",
                "verification_method": "replay-evidence"}.items()),
        encoding="utf-8")
    _fact_with_signoff(ws, "C-9")
    ok, reason = check_verifier_dispatch_evidence(ws, "C-9")
    assert not ok, "PROVEN without a dispatched verifier must be blocked"
    assert "dispatch" in reason.lower()
    sys.path.insert(0, str(ROOT / "hooks"))
    from worker_budget_gates import compare_register_change_proven_gate
    allowed, why = compare_register_change_proven_gate(
        ws / "claim-register.yaml", {"C-9": "VERIFIED"},
        "kunglao-worker", ws / "facts")
    assert not allowed, f"promotion must be blocked without evidence: {why}"


# ----------------------------- 6. the route face stays untouched

def test_redteam_stays_out_of_the_maker_route_table():
    """route_capability keys on `triggers:` — the checker must not grow
    one (issue 342 pin, unchanged by issue 355; the ruling changes ADMISSION, not
    routing)."""
    import route_capability as rc
    table = rc.load_specialist_table()
    assert all(s["name"] != "kunglao-redteam" for s in table)
