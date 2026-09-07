# -*- coding: utf-8 -*-
"""tests/test_kunglao_decide.py — kd single-path ranking tests (#100, #107).

#107 (Thompson rebuild, owner ruling "探索和价值网络完全重构，之前的
不要了"): kunglao-decide has ONE ranking path — the Thompson ranker in
priority_ratio, seeded by pr.posterior_rng(ws). The explore/exploit dual
path (the count-threshold gate, the cheapness face, the explore_mode
output field) is deleted: there is no phase to switch on and no second
ranking face. #100's dependency-gate standard SURVIVES the rebuild (it
lives in the unchanged candidate filter): a parent counts as satisfied
only when it holds a terminal fact (``evidence.terminal_fact_claims``) —
an IN_PROGRESS/PARK parent is work in flight or suspended, never a
satisfied dependency (#634 revival is explicit via mission_stall.revive).

#101 (one ranking authority): with the dual path gone, DECIDE and the
dispatch-gate top-1 audit (worker_budget.check_priority) run the SAME
ranker with the SAME seed — an authority_mismatch is structurally
impossible. These tests pin that agreement end-to-end.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

from _factories import write_claims_register

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


def _load_kd():
    """kunglao-decide.py is hyphenated (CLI name) — importlib load, same
    pattern as tests/test_failopen_emit.py (unique module name per file)."""
    name = "kunglao_decide_107"
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


# ---------- #100: the dependency gate survives the rebuild -------------------

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
def test_gate_blocks_child_of_inflight_or_park_parent(
        tmp_path, parent_status, per_claim_dep):
    """#100 probe: depends_on {C-2: [C-1]}, parent IN_PROGRESS/PARK →
    C-2 must NOT dispatch (the #634 revival protocol is explicit; an
    in-flight/parked parent is not a satisfied dependency). Both dep
    faces: claim_deps.yaml authoritative and the #594/#596 per-claim
    register fallback."""
    kd = _load_kd()
    deps = {} if per_claim_dep else {"C-2": ["C-1"]}
    ws = _ws(tmp_path, _probe_claims(parent_status, per_claim_dep=per_claim_dep),
             deps=deps)
    out = kd.decide(ws)
    ids = [a["claim_id"] for a in out["top_actions"]]
    assert "C-2" not in ids, (
        f"child of a {parent_status} parent must not dispatch (#100); "
        f"got top_actions={ids}")
    assert ids == ["C-3"], f"only the dep-free claim stays dispatchable; got {ids}"


def test_gate_allows_child_when_parent_holds_terminal_fact(tmp_path):
    """No over-block: a parent holding a terminal fact is a satisfied
    dependency even while its register row is still OPEN — the exact
    evidence.terminal_fact_claims standard the ranker applies."""
    kd = _load_kd()
    ws = _ws(tmp_path, _probe_claims("OPEN", per_claim_dep=False),
             deps={"C-2": ["C-1"]})
    facts = ws / "facts"
    facts.mkdir()
    (facts / "_INDEX.md").write_text(
        "F-001 | PROVEN | C-1 | parent closed\n", encoding="utf-8")
    out = kd.decide(ws)
    ids = [a["claim_id"] for a in out["top_actions"]]
    assert "C-2" in ids, (
        f"a terminal-fact parent must satisfy the dependency gate; got {ids}")


# ---------- determinism: reorder stability + seeded reproduction ------------

def test_dispatch_order_survives_register_reorder(tmp_path):
    """Same register content, different file order → identical dispatch
    order (the per-claim rng fork is keyed by claim_id, not list position;
    the empty posterior ledger seeds Random(0))."""
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
        f"register reorder must not change dispatch order; "
        f"a={out_a} b={out_b}")


def test_decide_is_deterministic_and_seed_reproducible(tmp_path):
    """kd.decide is deterministic for the same posterior state, and its
    top_actions scores reproduce a direct ranker call with the same
    posterior_rng seed (one ranker, one seed)."""
    kd = _load_kd()
    sys.path.insert(0, str(SCRIPTS))
    import priority_ratio as pr
    claims = [
        {"id": "C-1", "status": "OPEN", "statement": "background work"},
        {"id": "C-2", "status": "OPEN", "statement": "background work",
         "evidence_tier_attempted": 1},
    ]
    ws = _ws(tmp_path, claims)
    out1 = kd.decide(ws)
    out2 = kd.decide(ws)
    assert out1["top_actions"] == out2["top_actions"]
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    deps = yaml.safe_load((ws / "claim_deps.yaml").read_text(encoding="utf-8"))
    ev = pr.EvidenceView.from_workspace(ws)
    actions = pr.priority_ratio(reg["claims"], deps, ev, rng=pr.posterior_rng(ws))
    expected = [{"claim_id": a.claim_id, "action": a.action,
                 "score": round(a.score, 3), "skill": None}
                for a in actions[:out1["free_slots"]]]
    assert out1["top_actions"] == expected


# ---------- #101: one ranking authority (structurally, post-#107) -----------

def _conflict_claims() -> list[dict]:
    """Workspace where the OLD faces disagreed (pre-#107 cheapness #1 !=
    Thompson #1). C-3 is dep-blocked and must never appear; the rank order
    itself is the ranker's business — the assertions pin AGREEMENT, not a
    hand-computed order."""
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


def test_decide_top1_passes_gate_silently(tmp_path):
    """#101 acceptance, now by construction: dispatching DECIDE's own #1
    passes check_priority without agent-reasoning (deviated=False) — both
    faces rank through the same Thompson ranker + posterior seed."""
    kd = _load_kd()
    import worker_budget as wb
    ws = _conflict_ws(tmp_path)
    out = kd.decide(ws)
    assert out["top_actions"], out
    top_id = out["top_actions"][0]["claim_id"]
    ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), top_id, ws=ws)
    assert (ok, deviated) == (True, False), (
        f"dispatching DECIDE #1 ({top_id}) must pass the gate silently "
        f"(#101 single authority); got ok={ok} deviated={deviated} "
        f"msg={msg!r}")


def test_deviation_msg_names_thompson_authority(tmp_path):
    """#101 trace requirement: a deviation is judged under the single
    Thompson authority — the advisory msg names it so post-mortems can
    classify the deviation (a dep-blocked claim is rank-None: advisory
    without a deviation, also naming the authority)."""
    import worker_budget as wb
    ws = _conflict_ws(tmp_path, name="ws-auth")
    _ok, msg, deviated = wb.check_priority(
        str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
        str(ws / "task_spec.yaml"), "C-1", ws=ws)
    assert deviated is True, f"C-1 is a non-#1 dispatch; got msg={msg!r}"
    assert "thompson" in msg.lower(), (
        f"deviation msg must name the single ranking authority; got {msg!r}")


def test_gate_and_decide_agree_on_the_full_order(tmp_path):
    """Agreement over the WHOLE order: for every dispatchable claim, the
    gate's advisory names the SAME rank position DECIDE printed (one
    ranker, one seed) — and the dep-blocked claim is rank-None on both
    faces. Dispatching a rank>=2 claim deviates (contract), but the msg's
    "rank #N" must equal DECIDE's N for that claim."""
    kd = _load_kd()
    import worker_budget as wb
    ws = _conflict_ws(tmp_path, name="ws-agree")
    out = kd.decide(ws)
    kd_ids = [a["claim_id"] for a in out["top_actions"]]
    assert "C-3" not in kd_ids
    full = kd_ids + [c["id"] for c in _conflict_claims()
                     if c["id"] not in kd_ids and c["id"] != "C-3"]
    for cid in full:
        _ok, msg, deviated = wb.check_priority(
            str(ws / "claim-register.yaml"), str(ws / "claim_deps.yaml"),
            str(ws / "task_spec.yaml"), cid, ws=ws)
        rank = full.index(cid) + 1
        if rank == 1:
            assert (deviated, msg) == (False, ""), (
                f"rank #1 dispatch ({cid}) must be silent; got {msg!r}")
        else:
            assert deviated is True and f"rank #{rank}" in msg, (
                f"dispatching {cid} must deviate as rank #{rank} under the "
                f"same ordering DECIDE printed; got msg={msg!r}")


# ---------- fail-open / loud-failure posture --------------------------------

def test_unknown_posterior_schema_lands_conservative_blocked(tmp_path):
    """The #106 version wall propagates: an unknown runs/posteriors.yaml
    schema version must NOT silently rank — kd.decide lands conservative
    BLOCKED with the error text (loud, per the no-backcompat policy)."""
    kd = _load_kd()
    ws = _ws(tmp_path, [{"id": "C-1", "status": "OPEN",
                         "statement": "work"}])
    (ws / "runs" / "posteriors.yaml").write_text(
        "schema: posteriors-schema/999\ncases: {}\npqs: {}\n", encoding="utf-8")
    out = kd.decide(ws)
    assert out["decision"] == "BLOCKED", out
    assert out["exit_code"] == 4
    assert "PosteriorSchemaError" in out.get("error", "")
    assert out["top_actions"] == []
