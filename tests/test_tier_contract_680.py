# -*- coding: utf-8 -*-
"""tests/test_tier_contract_680.py — the dispatch tier contract (#680).

The envelope's `tier` is a free LLM input with no consistency check against
`action_tier` (the claim's own mechanical next tier), and NOTHING ever writes
`evidence_tier_attempted` — so `check_tier_gate`'s ladder can never climb
(C-007 self-deadlock: LLM declares tier=2, gate rejects on eta=0, nobody
does tier-1 work to raise eta).

RED first: these tests pin the contract BEFORE the fix lands.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HOOKS))

import priority_ratio as pr  # noqa: E402


def _mk_ws(tmp_path: Path, claims: list[dict]) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True),
        encoding="utf-8")
    (ws / "claim_deps.yaml").write_text("depends_on: {}\n", encoding="utf-8")
    facts = ws / "facts"
    facts.mkdir()
    (facts / "_INDEX.md").write_text("# _INDEX\n", encoding="utf-8")
    return ws


def _claim(cid: str, eta: int = 0, status: str = "OPEN",
           statement: str = "plain open question") -> dict:
    return {"id": cid, "status": status, "statement": statement,
            "evidence_tier_attempted": eta, "promotion_attempts": 0}


def _envelope(cid: str, tier: int) -> str:
    return ('{"kunglao_dispatch": {"version": 1, "claim": "%s", '
            '"tier": %d, "tools": ["grep"], "agent": "w-test", '
            '"method_family": "static-decompile"}}' % (cid, tier))


def _payload(prompt: str) -> dict:
    return {"tool_input": {"name": "w-test", "description": "", "prompt": prompt}}


def _paths(ws: Path) -> dict:
    return {"workspace": str(ws), "state": ws / "analysis_state.txt",
            "register": ws / "claim-register.yaml",
            "deps": ws / "claim_deps.yaml",
            "task_spec": ws / "task_spec.yaml"}


# =====================================================================
# 1. envelope tier must match action_tier — mismatch REJECTs
# =====================================================================

def test_envelope_tier_mismatch_with_action_tier_is_rejected(tmp_path, capsys):
    """C-007's deadlock shape: eta=0 claim (action_tier=1) dispatched at
    tier=2 -> REJECT with the correct value in the guidance."""
    from worker_budget_sinks import pre_check
    ws = _mk_ws(tmp_path, [_claim("C-001", eta=0)])
    prompt = f"{_envelope('C-001', 2)}\nfacts-snapshot: 1 facts"
    rc = pre_check(_payload(prompt), _paths(ws))
    captured = capsys.readouterr()
    assert rc == 2, captured.err
    assert "REJECT tiercons" in captured.err
    # the guidance names the CORRECT value (action_tier = 1), not a bare refusal
    assert "tier=1" in captured.err


def test_envelope_tier_match_allows_dispatch(tmp_path, capsys):
    """The mirror: the SAME claim dispatched at its action_tier passes the
    consistency gate (the ladder is climbable)."""
    from worker_budget_sinks import pre_check
    ws = _mk_ws(tmp_path, [_claim("C-001", eta=0)])
    prompt = f"{_envelope('C-001', 1)}\nfacts-snapshot: 1 facts"
    rc = pre_check(_payload(prompt), _paths(ws))
    assert rc == 0, capsys.readouterr().err


def test_agent_reasoning_records_deviation_but_allows(tmp_path, capsys):
    """A recorded deviation (`agent-reasoning:` prefix) keeps the dispatch
    moving — same discipline as the #310/#496 deviation faces. Shape: the
    consistency gate would reject a CHEAPER declared tier (eta=1 ->
    action_tier=2, declared 1); the tier gate itself is ungated at tier 1."""
    from worker_budget_sinks import pre_check
    ws = _mk_ws(tmp_path, [_claim("C-001", eta=1)])
    prompt = (f"agent-reasoning: rerun the static pass before climbing\n"
              f"{_envelope('C-001', 1)}\nfacts-snapshot: 1 facts")
    rc = pre_check(_payload(prompt), _paths(ws))
    captured = capsys.readouterr()
    assert rc == 0, captured.err
    assert "TIER (deviation recorded)" in captured.err


def test_claim_not_in_register_is_allowed(tmp_path, capsys):
    """Uncheckable (dispatched claim not yet in register) -> allow, same
    posture as check_promotion_attempts."""
    from worker_budget_sinks import pre_check
    ws = _mk_ws(tmp_path, [_claim("C-001", eta=0)])
    prompt = f"{_envelope('C-002', 2)}\nfacts-snapshot: 1 facts"
    rc = pre_check(_payload(prompt), _paths(ws))
    # not rejected by the tier-consistency gate (some other gate may fire;
    # the point is tiercons does not)
    captured = capsys.readouterr()
    assert "REJECT tiercons" not in captured.err


def test_verifier_remediation_dispatch_skips_tiercons(tmp_path, capsys):
    """#680 D2 mirror: a kunglao-redteam dispatch for a PROVEN claim is
    the flagged-evidence remediation — its tier is not the claim's
    evidence-ladder step, so the consistency gate must not block it
    (same pass-through as the drift gate)."""
    from worker_budget_sinks import pre_check
    ws = _mk_ws(tmp_path, [_claim("C-001", eta=0, status="PROVEN")])
    prompt = f"{_envelope('C-001', 2)}\nfacts-snapshot: 1 facts"
    payload = {"tool_input": {"name": "kunglao-redteam", "description": "",
                              "prompt": prompt}}
    rc = pre_check(payload, _paths(ws))
    captured = capsys.readouterr()
    assert "REJECT tiercons" not in captured.err, captured.err
    assert rc == 0, captured.err


# =====================================================================
# 2. eta writer — ALLOW dispatch raises evidence_tier_attempted
# =====================================================================

def test_eta_written_at_dispatch_allow_tail(tmp_path, capsys):
    """After an ALLOW dispatch, the claim's evidence_tier_attempted is
    updated to max(current_eta, tier_used) — the missing writer that lets
    the tier ladder climb."""
    from worker_budget_sinks import pre_check
    ws = _mk_ws(tmp_path, [_claim("C-001", eta=0)])
    prompt = f"{_envelope('C-001', 1)}\nfacts-snapshot: 1 facts"
    rc = pre_check(_payload(prompt), _paths(ws))
    assert rc == 0, capsys.readouterr().err
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    c = next(x for x in reg["claims"] if x["id"] == "C-001")
    assert c["evidence_tier_attempted"] == 1


def test_eta_writer_never_lowers_eta(tmp_path, capsys):
    """max(eta, tier): a cheaper tier (recorded deviation — the consistency
    gate would otherwise reject the mismatch) leaves eta=2 untouched."""
    from worker_budget_sinks import pre_check
    ws = _mk_ws(tmp_path, [_claim("C-001", eta=2)])
    prompt = (f"agent-reasoning: cheap static rerun before the VM cycle\n"
              f"{_envelope('C-001', 1)}\nfacts-snapshot: 1 facts")
    rc = pre_check(_payload(prompt), _paths(ws))
    assert rc == 0, capsys.readouterr().err
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    c = next(x for x in reg["claims"] if x["id"] == "C-001")
    assert c["evidence_tier_attempted"] == 2


# =====================================================================
# 3. rank_feeds carries tiers (additive key)
# =====================================================================

def test_rank_feeds_carries_tiers(tmp_path, monkeypatch):
    """The rank_feeds payload gains an ADDITIVE `tiers` key mapping each
    claim to its action_tier — the decision face can finally SEE the tier."""
    import kunglao_log
    calls: list[dict] = []

    def _fake(ws, actor, action, **kw):
        calls.append({"actor": actor, "action": action, **kw})

    monkeypatch.setattr(kunglao_log, "emit", _fake)
    ws = _mk_ws(tmp_path, [_claim("C-001", eta=0), _claim("C-002", eta=1)])
    claims = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))["claims"]
    pr.priority_ratio(claims, {"depends_on": {}}, pr.EvidenceView(ws=ws))
    rows = [c for c in calls if c["action"] == "rank_feeds"]
    assert len(rows) == 1
    payload = json.loads(rows[0]["detail"])
    assert "tiers" in payload
    assert payload["tiers"]["C-001"] == 1
    assert payload["tiers"]["C-002"] == 2
    # existing keys untouched (additive-only contract)
    for key in ("feeds", "scores", "ranked_order", "input_fingerprint"):
        assert key in payload


def test_action_to_dict_carries_tier():
    """Action.to_dict() exposes tier so --json consumers see it."""
    a = pr.Action(claim_id="C-1", action="evidence_collection", score=0.5,
                  skill=None, tier=2, attempts=0, cost=1.0)
    d = a.to_dict()
    assert d["tier"] == 2


# =====================================================================
# 4. acceptance claim dispatchable at its computed tier
# =====================================================================

def test_acceptance_claim_dispatchable_at_computed_tier(tmp_path, capsys):
    """The C-007 shape: an acceptance-criterion claim (eta=0) IS
    dispatchable — at tier=action_tier — instead of self-deadlocking
    behind its own tier gate."""
    from worker_budget_sinks import pre_check
    acceptance = ("acceptance criterion: >=10 requests with >90% pass rate "
                  "through the replay harness")
    ws = _mk_ws(tmp_path, [_claim("C-007", eta=0, statement=acceptance)])
    # tier_for_claim sees no VM/dynamic signal -> conservative T1
    from tier_rules import tier_for_claim
    computed = tier_for_claim({"statement": acceptance})
    assert computed == 1
    prompt = f"{_envelope('C-007', computed)}\nfacts-snapshot: 1 facts"
    rc = pre_check(_payload(prompt), _paths(ws))
    assert rc == 0, capsys.readouterr().err
