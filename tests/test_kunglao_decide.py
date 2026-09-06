# -*- coding: utf-8 -*-
"""tests/test_kunglao_decide.py — kd explore-face tests (#100, #101).

#100 (explore dependency gate): the explore-mode candidate filter must use
the EXPLOIT-path standard — a parent counts as satisfied only when it holds
a terminal fact (``evidence.terminal_fact_claims``, the same set
priority_ratio gates on). Pre-fix, ``terminal_ids = {cid | not is_open}``
made IN_PROGRESS and PARK parents count as "satisfied", so explore (the
cold-start default, verified facts < 5) dispatched children of in-flight or
parked claims — bypassing the #634 revival protocol (revival is explicit via
mission_stall.revive, never an explore side effect). Same per-claim
depends_on fallback as the VoI path (#594/#596).

L-1 (same card): explore ties break by claim_id, not register file order —
a same-content register reorder must not silently reshuffle dispatch order.

#101 (dual ranking authority): DECIDE explore ranks by cheapness while the
dispatch-gate top-1 audit (worker_budget.check_priority) ranked by pure VoI
with zero explore awareness — an orchestrator dispatching its own DECIDE #1
was REJECTed as a "deviation" (authority_mismatch conflict class, exit 2
without ``agent-reasoning:``). Post-fix the gate audits against the
cheapness face during explore (same candidate filter, same tie-break) and
keeps the VoI authority in exploit period (regression-pinned here and in
tests/test_scorer_authority.py, whose fixtures are exploit-period seeded).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from _factories import write_claims_register

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


def _load_kd():
    """kunglao-decide.py is hyphenated (CLI name) — importlib load, same
    pattern as tests/test_failopen_emit.py (unique module name per file)."""
    name = "kunglao_decide_100"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, SCRIPTS / "kunglao-decide.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _write_yaml(ws: Path, rel: str, doc: dict) -> None:
    # JSON is valid YAML — keeps fixture literals readable
    (ws / rel).write_text(json.dumps(doc), encoding="utf-8")


def _ws(tmp_path: Path, claims: list[dict], *, deps: dict | None = None,
        groups: dict | None = None, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    write_claims_register(ws, claims)
    _write_yaml(ws, "claim_deps.yaml",
                {"depends_on": deps or {}, "competitor_groups": groups or {}})
    _write_yaml(ws, "task_spec.yaml", {"primary_questions": []})
    return ws


# ---------- #100: explore-mode dependency gate ------------------------------

def _probe_claims(parent_status: str, *, per_claim_dep: bool) -> list[dict]:
    child = {"id": "C-2", "status": "OPEN", "statement": "child work"}
    if per_claim_dep:
        child["depends_on"] = ["C-1"]
    return [
        {"id": "C-1", "status": parent_status, "statement": "parent work"},
        child,
        {"id": "C-3", "status": "OPEN", "statement": "free work"},
    ]


@pytest.mark.parametrize("parent_status", ["IN_PROGRESS", "PARK"])
@pytest.mark.parametrize("per_claim_dep", [False, True],
                         ids=["claim_deps", "per_claim_fallback"])
def test_explore_blocks_child_of_inflight_or_park_parent(
        tmp_path, parent_status, per_claim_dep):
    """#100 probe: depends_on {C-2: [C-1]}, parent IN_PROGRESS/PARK →
    explore must NOT dispatch C-2 (the #634 revival protocol is explicit;
    an in-flight/parked parent is not a satisfied dependency). Both dep
    faces: claim_deps.yaml authoritative and the #594/#596 per-claim
    register fallback."""
    kd = _load_kd()
    deps = {} if per_claim_dep else {"C-2": ["C-1"]}
    ws = _ws(tmp_path, _probe_claims(parent_status, per_claim_dep=per_claim_dep),
             deps=deps)
    out = kd.decide(ws)
    assert out["explore_mode"] is True, out
    ids = [a["claim_id"] for a in out["top_actions"]]
    assert "C-2" not in ids, (
        f"child of a {parent_status} parent must not dispatch in explore "
        f"(#100); got top_actions={ids}")
    assert ids == ["C-3"], f"only the dep-free claim stays dispatchable; got {ids}"


def test_explore_allows_child_when_parent_holds_terminal_fact(tmp_path):
    """No over-block: a parent holding a terminal fact is a satisfied
    dependency even while its register row is still OPEN — the exact
    evidence.terminal_fact_claims standard the VoI path applies."""
    kd = _load_kd()
    ws = _ws(tmp_path, _probe_claims("OPEN", per_claim_dep=False),
             deps={"C-2": ["C-1"]})
    facts = ws / "facts"
    facts.mkdir()
    (facts / "_INDEX.md").write_text(
        "F-001 | PROVEN | C-1 | parent closed\n", encoding="utf-8")
    out = kd.decide(ws)
    assert out["explore_mode"] is True, out
    ids = [a["claim_id"] for a in out["top_actions"]]
    assert "C-2" in ids, (
        f"a terminal-fact parent must satisfy the dependency gate; got {ids}")


# ---------- #100 L-1: deterministic explore tie-break ------------------------

def test_explore_tie_breaks_by_claim_id_not_register_order(tmp_path):
    """Two equal-cheapness T1 claims: the dispatch order must follow
    claim_id, not the register file order (pre-fix the stable sort kept
    register order, so a same-content reorder silently reshuffled)."""
    kd = _load_kd()
    claims = [
        {"id": "C-2", "status": "OPEN", "statement": "work two"},
        {"id": "C-1", "status": "OPEN", "statement": "work one"},
    ]
    ws = _ws(tmp_path, claims)
    out = kd.decide(ws)
    ids = [a["claim_id"] for a in out["top_actions"]]
    assert ids == ["C-1", "C-2"], (
        f"equal-score ties must break by claim_id; got {ids}")


def test_explore_dispatch_order_survives_register_reorder(tmp_path):
    """Same register content, different file order → identical dispatch
    order (the reorder-stability property the tie-break exists for)."""
    kd = _load_kd()
    claims = [
        {"id": "C-2", "status": "OPEN", "statement": "work two"},
        {"id": "C-1", "status": "OPEN", "statement": "work one"},
        {"id": "C-3", "status": "OPEN", "statement": "work three",
         "evidence_tier_attempted": 1},
    ]
    ws_a = _ws(tmp_path, claims, name="ws-a")
    ws_b = _ws(tmp_path, list(reversed(claims)), name="ws-b")
    out_a = kd.decide(ws_a)["top_actions"]
    out_b = kd.decide(ws_b)["top_actions"]
    assert out_a == out_b, (
        f"register reorder must not change explore dispatch order; "
        f"a={out_a} b={out_b}")


# ---------- #101: one ranking authority per phase ----------------------------

def _conflict_claims() -> list[dict]:
    """Explore-period workspace where cheapness #1 != VoI #1:

      C-1  plain T1            -> cheapness 1.0 (rank #1) / VoI 0.31 (#3)
      C-2  g1 T2 + C-3 child   -> leverage 1.0 + live group D=1.0, cost 3
                                  -> VoI 0.333 (#2) / cheapness 0.333 (#3)
      C-3  dep-blocked child   -> not a candidate on either face
      C-4  g1 T1               -> VoI 0.55 (#1) / cheapness 1.0 (rank #2)

    Dispatching DECIDE's own explore #1 (C-1) must NOT register as a
    deviation (pre-fix: deviated=True 'rank #3 ... rank #1 is C-4')."""
    return [
        {"id": "C-1", "status": "OPEN", "statement": "background work"},
        {"id": "C-2", "status": "OPEN", "statement": "background work",
         "competitor_group": "g1", "evidence_tier_attempted": 1},
        {"id": "C-3", "status": "OPEN", "statement": "background work",
         "depends_on": ["C-2"]},
        {"id": "C-4", "status": "OPEN", "statement": "background work",
         "competitor_group": "g1"},
    ]


def _conflict_ws(tmp_path, name="ws") -> Path:
    return _ws(tmp_path, _conflict_claims(),
               deps={"C-3": ["C-2"]},
               groups={"g1": ["C-2", "C-4"]}, name=name)


def test_explore_dispatch_of_decide_top1_passes_gate(tmp_path):
    """#101 acceptance: during explore, dispatching DECIDE's own #1 passes
    check_priority without agent-reasoning (deviated=False) — the gate
    audits the same cheapness ranking DECIDE used."""
    kd = _load_kd()
    import worker_budget as wb
    ws = _conflict_ws(tmp_path)
    out = kd.decide(ws)
    assert out["explore_mode"] is True, out
    assert out["top_actions"], out
    assert out["top_actions"][0]["claim_id"] == "C-1", (
        f"explore #1 must be the cheap-T1 C-1; got {out['top_actions']}")
    ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), "C-1", ws=ws)
    assert (ok, deviated) == (True, False), (
        f"dispatching DECIDE explore #1 must pass the gate silently "
        f"(#101 authority_mismatch); got ok={ok} deviated={deviated} "
        f"msg={msg!r}")


def test_explore_deviation_msg_names_explore_authority(tmp_path):
    """#101 trace requirement: an explore-period deviation is judged under
    the cheapness authority — the advisory msg names it so post-mortems can
    distinguish the authority class from a VoI deviation."""
    import worker_budget as wb
    ws = _conflict_ws(tmp_path, name="ws-auth")
    _ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), "C-2", ws=ws)
    assert deviated is True, f"C-2 is cheapness rank #3; got msg={msg!r}"
    assert "explore" in msg.lower(), (
        f"explore-period deviation msg must name the ranking authority "
        f"(#101 authority class); got {msg!r}")


def test_exploit_period_keeps_voi_authority(tmp_path):
    """Regression guard: past the explore gate (verified facts >= 5) the
    VoI authority is byte-preserved — C-4 (0.55) outranks C-1 (0.06), the
    exact opposite of the explore face."""
    import worker_budget as wb
    ws = _conflict_ws(tmp_path, name="ws-exploit")
    claims = [{"id": "C-T", "status": "DEFERRED", "statement": "background work"}]
    reg = ws / "claim-register.yaml"
    reg.write_text(reg.read_text(encoding="utf-8")
                   + "\n".join(f"- id: {c['id']}\n  status: {c['status']}\n"
                               f"  statement: {c['statement']}\n"
                               for c in claims), encoding="utf-8")
    facts = ws / "facts"
    facts.mkdir()
    (facts / "_INDEX.md").write_text(
        "".join(f"F-90{i} | PROVEN | C-T | terminal evidence\n"
                for i in range(1, 6)), encoding="utf-8")
    kd = _load_kd()
    out = kd.decide(ws)
    assert out["explore_mode"] is False, out
    ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), "C-4", ws=ws)
    assert (ok, deviated) == (True, False), (
        f"exploit-period VoI #1 (C-4) must stay a silent dispatch; "
        f"got deviated={deviated} msg={msg!r}")
    ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), "C-1", ws=ws)
    assert deviated is True, (
        f"exploit-period C-1 (VoI rank #3) must still register as a "
        f"deviation; got msg={msg!r}")
