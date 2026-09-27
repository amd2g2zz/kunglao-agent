# -*- coding: utf-8 -*-
"""tests/test_tagged_logging_293.py — issue 293 tagged operational logging.

Three contracts, one file:

  1. TAGGED DECISIONS — every state-changing/decision line of the six post2
     product scripts (plan_drift_detector / hypothesis_bridge / target_ladder
     / plan_epistemics / claim_granularity / progress_timeline) is visible in
     the unified event ledger (runs/logs/kunglao-*.jsonl) with
     actor=<script-name>. Emission is ADDITIVE: the CLI stdout/stderr faces
     pinned by tests/test_shared_primitives_292.py stay byte-identical
     (emit writes to the event log, never to stdout).
  2. CONTEXT MANIFEST — a dispatch through the real assembly path
     (dispatch_context.build_dispatch_context) records the
     actually-assembled context inventory as ONE `context_manifest` event:
     every item carries a source tag; the manifest rides `detail` JSON and
     introduces NO new event-row keys (old events without it stay readable;
     the row schema is unchanged).
  3. INVESTMENT-ARC FIELDS — a multi-dispatch hypothesis campaign (a family)
     opens its arc with budget / max_runs / stop_condition, closes it with
     the value attribution (which arm won). Per-attempt events state WHAT
     happened and carry NO worth fields — the "WHAT not worth" rule is
     asserted as absence.

All faces run in-process against tmp-path workspaces; rows are read back
from the real jsonl (no emit mocking — the ledger itself is the assertion
surface).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import claim_granularity as cg  # noqa: E402
import dispatch_context as dc  # noqa: E402
import hypothesis_bridge as hb  # noqa: E402
import hypothesis_store as hstore  # noqa: E402
import plan_drift_detector as pdd  # noqa: E402
import plan_epistemics as pe  # noqa: E402
import progress_timeline as pt  # noqa: E402
import target_ladder as tl  # noqa: E402
from kunglao_log import tail  # noqa: E402

# RED-tolerant: pre-implementation the constant does not exist yet; the
# dedicated arc tests below still assert its presence and value.
ARC_BUDGET = getattr(hb, "ARC_BUDGET", None)

# the ONE event-row schema — no issue-293 event may add a top-level key
# (version-compat by construction: old consumers keep reading via .get())
_BASE_ROW_KEYS = {
    "ts", "actor", "action", "claim", "tool", "artifact", "duration_ms",
    "exit", "detail", "arm", "epoch", "hypothesis_ref", "matched_rule",
    "trace_id", "version", "channel", "null_reasons",
}
_WORTH_FIELDS = ("budget", "max_runs", "stop_condition")


def rows_for(ws: Path, actor: str) -> list[dict]:
    return [r for r in tail(ws, 1000) if r.get("actor") == actor]


# --------------------------------------------------------------- helpers --

def _write_reg(ws: Path, claims: list[dict]) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True,
                       sort_keys=False), encoding="utf-8")


def _mk_hyp(ws: Path, hid: str) -> hstore.Hypothesis:
    store = hstore.HypothesisStore(ws / "hypotheses")
    return store.create(hstore.Hypothesis(
        id=hid, claim_id="C-PENDING",
        competitor_group=hb.family_group(hid),
        candidates=[], status="open", body=f"test family {hid}\n"))


def _detail(row: dict) -> dict:
    return json.loads(row["detail"]) if row.get("detail") else {}


def test_event_rows_introduce_no_new_schema_keys(tmp_path):
    """Version-compat pin: an issue-293 emission (manifest face below) must ride
    the EXISTING row fields (detail JSON), never add top-level keys."""
    ws = tmp_path / "m"
    (ws / "facts").mkdir(parents=True)
    (ws / "facts" / "F001-loader.md").write_text(
        "---\nid: F001\nclaim_id: C-001\n---\nbody\n", encoding="utf-8")
    _write_reg(ws, [{"id": "C-001", "status": "OPEN"}])
    dc.build_dispatch_context(ws=ws, claim_id="C-001", tier=2,
                              tools=["Read"], agent_name="kunglao-worker")
    rows = tail(ws, 10)
    assert rows, "manifest event must be on the ledger"
    for r in rows:
        assert set(r.keys()) <= _BASE_ROW_KEYS


# ===========================================================================
# 1. TAGGED DECISIONS — the six scripts
# ===========================================================================

# ---- plan_drift_detector: the drift verdict is a decision record ----------

def _pdd_ws(tmp_path: Path, claims: list[dict], plan_ids: list[str]) -> Path:
    ws = tmp_path / "pdd"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True),
        encoding="utf-8")
    (ws / "global_plan.txt").write_text(
        "# plan\n" + "".join(f"- {cid}: work\n" for cid in plan_ids),
        encoding="utf-8")
    return ws


def test_pdd_drift_verdict_is_tagged_and_persisted(tmp_path):
    ws = _pdd_ws(tmp_path,
                 [{"id": "C-001", "status": "OPEN"},
                  {"id": "C-002", "status": "OPEN"}],
                 ["C-001"])  # C-002 in register, missing from plan
    rc = pdd.check(ws)
    assert rc == 1
    fired = [r for r in rows_for(ws, "plan_drift_detector")
             if r["action"] == "detector_fired"]
    assert len(fired) == 1
    row = fired[0]
    assert row["exit"] == 1
    detail = _detail(row)
    assert detail["detector"] == "plan_drift_detector"
    assert detail["by_type"].get("ORPHAN_CLAIM") == 1


def test_pdd_clean_check_emits_nothing(tmp_path):
    """The issue-459 anchor face: a fresh/clean check emits nothing (no warn,
    no event) — the clean path changes no state; detector_fired is the
    decision record."""
    ws = _pdd_ws(tmp_path, [{"id": "C-001", "status": "OPEN"}], ["C-001"])
    assert pdd.check(ws) == 0
    assert rows_for(ws, "plan_drift_detector") == []


# ---- hypothesis_bridge: refusals + investment arc -------------------------

def test_hb_mint_refusal_is_tagged(tmp_path):
    ws = tmp_path / "hb"
    _write_reg(ws, [])
    r = hb.mint_family_arms(ws, "H-001", ["cand-a"])
    assert r["refused"]
    refused = [r for r in rows_for(ws, "hypothesis_bridge")
               if r["action"] == "mint_refused"]
    assert len(refused) == 1
    assert refused[0]["hypothesis_ref"] == "H-001"


def test_hb_arc_open_carries_budget_maxruns_stopcondition(tmp_path):
    ws = tmp_path / "hb2"
    _write_reg(ws, [])
    _mk_hyp(ws, "H-001")
    r = hb.mint_family_arms(ws, "H-001", ["arm one", "arm two"])
    assert not r["refused"] and len(r["minted"]) == 2
    opens = [r for r in rows_for(ws, "hypothesis_bridge")
             if r["action"] == "investment_arc_open"]
    assert len(opens) == 1  # exactly one arc open, at the FIRST mint
    row = opens[0]
    assert row["hypothesis_ref"] == "H-001"
    d = _detail(row)
    assert d["budget"] == ARC_BUDGET
    assert d["max_runs"] == 2
    assert d["stop_condition"]
    assert sorted(d["arms"]) == sorted(m["id"] for m in r["minted"])
    # a top-up mint rides the per-attempt face only — no second arc open
    hb.mint_family_arms(ws, "H-001", ["arm three"])
    opens = [r for r in rows_for(ws, "hypothesis_bridge")
             if r["action"] == "investment_arc_open"]
    assert len(opens) == 1


def test_hb_arc_close_carries_value_attribution(tmp_path):
    ws = tmp_path / "hb3"
    _write_reg(ws, [])
    _mk_hyp(ws, "H-001")
    r = hb.mint_family_arms(ws, "H-001", ["arm one", "arm two"])
    arm_ids = [m["id"] for m in r["minted"]]
    reg = yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8"))
    for c in reg["claims"]:
        if c["id"] == arm_ids[0]:
            c["status"] = "PROVEN"
    _write_reg(ws, reg["claims"])
    report = hb.sync_family_ledger(ws)
    assert report["confirmed"] == ["H-001"]
    closes = [r for r in rows_for(ws, "hypothesis_bridge")
              if r["action"] == "investment_arc_close"]
    assert len(closes) == 1
    d = _detail(closes[0])
    assert d["verdict"] == "confirm"
    assert d["winning_arm"] == arm_ids[0]  # the worth, AT CLOSE only
    assert set(d["arms"]) == set(arm_ids)


def test_hb_per_attempt_events_carry_no_worth_fields(tmp_path):
    """THE 'WHAT not worth' rule: per-attempt rows state what happened and
    never what it was worth — no budget/max_runs/stop_condition anywhere in
    the row (value attribution only at arc close)."""
    ws = tmp_path / "hb4"
    _write_reg(ws, [])
    _mk_hyp(ws, "H-001")
    hb.mint_family_arms(ws, "H-001", ["arm one", "arm two"])
    per_attempt = [r for r in rows_for(ws, "hypothesis_bridge")
                   if r["action"] in ("family_arms_minted", "family_ensured",
                                      "family_superseded")]
    assert per_attempt, "per-attempt faces must be on the ledger"
    for row in per_attempt:
        blob = json.dumps(row, ensure_ascii=False)
        for field in _WORTH_FIELDS:
            assert field not in blob, (
                f"per-attempt row {row['action']} carries worth field "
                f"{field!r}: {blob}")


# ---- target_ladder: mints + the settlement gate block ---------------------

def _tl_obstacle_ws(tmp_path: Path, *, with_ladder: bool) -> Path:
    ws = tmp_path / "tl"
    _write_reg(ws, [{"id": "C-090", "status": "OPEN",
                     "origin": "failure-obstacle",
                     "obstacle_for": "C-001",
                     "obstacle_class": "interception"}])
    if with_ladder:
        (ws / "runs").mkdir(parents=True)
        (ws / "runs" / "target-ladder-C-090.yaml").write_text(
            yaml.safe_dump({
                "obstacle_class": "interception",
                "attempts": [
                    {"level": "T1", "family": "hooking", "action": "a"},
                    {"level": "T2", "family": "repackaging", "action": "b"},
                    {"level": "T3", "family": "ca-install", "action": "c"},
                ],
                "inventory": [
                    {"family": "hooking", "tried": "frida attach",
                     "failed_because": "cert pinning"},
                    {"family": "repackaging", "tried": "apk resign",
                     "failed_because": "integrity check"},
                ],
            }, allow_unicode=True), encoding="utf-8")
    return ws


def test_tl_mint_refusal_is_tagged(tmp_path):
    ws = tmp_path / "tl1"  # no register at all
    r = tl.mint_sibling_claims(ws, "C-090")
    assert r["refused"]
    refused = [r for r in rows_for(ws, "target_ladder")
               if r["action"] == "mint_refused"]
    assert len(refused) == 1


def test_tl_sibling_mint_is_tagged(tmp_path):
    ws = _tl_obstacle_ws(tmp_path, with_ladder=True)
    r = tl.mint_sibling_claims(ws, "C-090")
    assert not r["refused"] and len(r["minted"]) == 2
    rows = [r for r in rows_for(ws, "target_ladder")
            if r["action"] == "siblings_minted"]
    assert len(rows) == 1
    assert rows[0]["claim"] == "C-090"
    d = _detail(rows[0])
    assert sorted(m["id"] for m in r["minted"]) == \
        sorted(m["id"] for m in d["minted"])
    # idempotent re-mint mints nothing and emits nothing new
    before = len(rows_for(ws, "target_ladder"))
    tl.mint_sibling_claims(ws, "C-090")
    assert len(rows_for(ws, "target_ladder")) == before


def test_tl_settlement_gate_block_is_tagged(tmp_path):
    ws = _tl_obstacle_ws(tmp_path, with_ladder=False)
    blocker = tl.settlement_blocker(ws, "C-090")
    assert blocker
    rows = [r for r in rows_for(ws, "target_ladder")
            if r["action"] == "ladder_reject"]
    assert len(rows) == 1
    assert rows[0]["claim"] == "C-090"
    assert "TARGET LADDER GATE" in rows[0]["detail"]


# ---- plan_epistemics: the mint face ----------------------------------------

def _pe_vmp_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "pe"
    (ws / "evidence").mkdir(parents=True)
    (ws / "evidence" / "die.json").write_text(
        json.dumps({"derived": {"detected_packer": "VmProtect"}}),
        encoding="utf-8")
    return ws


def test_pe_mint_is_tagged_and_idempotent_face_is_silent(tmp_path):
    ws = _pe_vmp_ws(tmp_path)
    summary = pe.mint_workspace(ws)
    assert len(summary["minted"]) == 2
    rows = [r for r in rows_for(ws, "plan_epistemics")
            if r["action"] == "epistemic_claims_minted"]
    assert len(rows) == 1
    d = _detail(rows[0])
    assert d["target_class"] == "vmp"
    assert len(d["claims"]) == 2
    assert len(d["seeded"]) == 2
    # idempotent re-run: nothing minted -> no state change -> no event
    pe.mint_workspace(ws)
    assert len([r for r in rows_for(ws, "plan_epistemics")
                if r["action"] == "epistemic_claims_minted"]) == 1


# ---- claim_granularity: verdict + split fan-out ----------------------------

MONO_PLAN = "goal: g\nsteps:\n" + "".join(
    f"  {i}. step {i} does things\n" for i in range(1, 13))


def test_cg_monolithic_verdict_is_tagged(tmp_path, monkeypatch):
    ws = tmp_path / "cg"
    (ws / "runs").mkdir(parents=True)
    _write_reg(ws, [{"id": "C-001", "status": "OPEN"}])
    (ws / "runs" / "plan-C001.md").write_text(MONO_PLAN, encoding="utf-8")
    monkeypatch.setattr(sys, "argv",
                        ["claim_granularity.py", str(ws), "--check", "C-001"])
    assert cg.main() == 1
    rows = [r for r in rows_for(ws, "claim_granularity")
            if r["action"] == "granularity_reject"]
    assert len(rows) == 1
    assert rows[0]["claim"] == "C-001"
    assert "GRANULARITY GATE" in rows[0]["detail"]


def test_cg_split_mint_is_tagged_with_parent_supersession(tmp_path):
    ws = tmp_path / "cg2"
    (ws / "runs").mkdir(parents=True)
    _write_reg(ws, [{"id": "C-001", "status": "OPEN"}])
    (ws / "runs" / "plan-C001.md").write_text(MONO_PLAN, encoding="utf-8")
    r = cg.mint_split_claims(ws, "C-001")
    assert not r["refused"] and r["minted"]
    rows = [r for r in rows_for(ws, "claim_granularity")
            if r["action"] == "split_units_minted"]
    assert len(rows) == 1
    assert rows[0]["claim"] == "C-001"
    d = _detail(rows[0])
    assert d["parent_superseded"] is True
    assert d["parent"] == "C-001"


def test_cg_split_refusal_is_tagged(tmp_path):
    ws = tmp_path / "cg3"  # no register
    r = cg.mint_split_claims(ws, "C-001")
    assert r["refused"]
    refused = [r for r in rows_for(ws, "claim_granularity")
               if r["action"] == "mint_refused"]
    assert len(refused) == 1


# ---- progress_timeline: the render skip decisions ---------------------------

def _pt_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "pt"
    logs = ws / "runs" / "logs"
    logs.mkdir(parents=True)
    row = {"ts": "2026-09-21T10:00:00Z", "epoch": 5, "actor": "worker",
           "action": "evidence_captured", "claim": "C-001",
           "detail": "found the loader"}
    (logs / "kunglao-2026-09-21.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8")
    return ws


def test_pt_success_face_stays_off_the_ledger(tmp_path):
    """The rendered timeline is a derived VIEW (issue 282/issue 530): a successful
    render writes the file, never an event (an event after the write would
    break the zero-gap invariant; an event before it would change the
    pinned issue-292 file bytes)."""
    ws = _pt_ws(tmp_path)
    pt.render_and_repair(ws)
    assert rows_for(ws, "progress_timeline") == []


def test_pt_render_skip_is_tagged(tmp_path):
    ws = _pt_ws(tmp_path)
    pt.render_and_repair(ws)
    before = len(tail(ws, 1000))
    # unreadable ledger: a directory at the day-file path (the issue-282 face)
    day = ws / "runs" / "logs" / "kunglao-2026-09-19.jsonl"
    day.write_text("x", encoding="utf-8")
    day.unlink()
    day.mkdir()
    status = pt.render_and_repair(ws)
    assert status["status"] == "skipped"
    rows = [r for r in rows_for(ws, "progress_timeline")
            if r["action"] == "timeline_render_skipped"]
    assert len(rows) == 1
    assert "unreadable" in rows[0]["detail"]
    assert len(tail(ws, 1000)) == before + 1


# ===========================================================================
# 2. CONTEXT MANIFEST — the dispatch assembly point
# ===========================================================================

def test_dispatch_assembly_emits_context_manifest(tmp_path):
    ws = tmp_path / "m2"
    (ws / "facts").mkdir(parents=True)
    (ws / "facts" / "F001-loader.md").write_text(
        "---\nid: F001\nclaim_id: C-001\n---\nbody\n", encoding="utf-8")
    (ws / "runs").mkdir(parents=True)
    (ws / "runs" / "plan-C001.md").write_text("# plan\nsteps\n",
                                              encoding="utf-8")
    _write_reg(ws, [{"id": "C-001", "status": "OPEN"},
                    {"id": "C-002", "status": "OPEN",
                     "obstacle_for": "C-001"}])
    ctx = dc.build_dispatch_context(ws=ws, claim_id="C-001", tier=2,
                                    tools=["Read"],
                                    agent_name="kunglao-worker")
    rows = [r for r in tail(ws, 100)
            if r["action"] == "context_manifest"]
    assert len(rows) == 1
    row = rows[0]
    assert row["actor"] == "dispatch_context"
    assert row["claim"] == "C-001"
    d = _detail(row)
    assert d["kind"] == "context_manifest"
    assert d["count"] == len(d["items"]) > 0
    by_source = {}
    for item in d["items"]:
        assert set(item) == {"kind", "ref", "source"}
        by_source.setdefault(item["source"], []).append(item["ref"])
    assert "F001-loader.md" in by_source["fact_snapshot"]
    assert "runs/plan-C001.md" in by_source["plan_ref"]
    assert "C-002" in by_source["sibling_claims"]
    # additive, not a replacement: the returned context shape is unchanged
    dc.validate_context_shape(ctx)


def test_manifest_event_is_old_consumer_compatible(tmp_path):
    """A reader that only knows the pre-issue-293 schema (tail + .get) keeps
    working over a ledger that now carries manifest/arc events."""
    ws = tmp_path / "m3"
    _write_reg(ws, [])
    _mk_hyp(ws, "H-001")
    hb.mint_family_arms(ws, "H-001", ["arm one"])
    dc.build_dispatch_context(ws=ws, claim_id="C-001", tier=1, tools=[],
                              agent_name="kunglao-worker")
    for r in tail(ws, 100):
        assert isinstance(r.get("ts"), str)
        assert isinstance(r.get("action"), str)
        assert isinstance(r.get("null_reasons"), dict)


# ===========================================================================
# 3. ARC VOCABULARY WIRING
# ===========================================================================

def test_arc_budget_matches_worker_budget_cap():
    """Cross-face sync (the PLAN_REPAIR_WINDOW_ROUNDS pattern): the arc
    budget literal restates the TS pool's real drop cap
    (hooks/worker_budget_core.MAX_PROMOTION_ATTEMPTS)."""
    import importlib.util as ilu
    spec = ilu.spec_from_file_location(
        "wbc_293", ROOT / "hooks" / "worker_budget_core.py")
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert ARC_BUDGET == mod.MAX_PROMOTION_ATTEMPTS


def test_arc_words_registered_in_emit_vocabulary():
    import event_taxonomy as et
    for word in ("context_manifest", "investment_arc_open",
                 "investment_arc_close", "mint_refused", "siblings_minted",
                 "split_units_minted", "epistemic_claims_minted",
                 "timeline_render_skipped", "ladder_reject",
                 "granularity_reject"):
        assert word in et.EMIT_ACTIONS, f"{word} unregistered"


def test_new_actors_adopted_in_legacy_vocabulary():
    import kunglao_log
    for actor in ("target_ladder", "plan_epistemics", "claim_granularity",
                  "progress_timeline"):
        assert actor in kunglao_log.LEGACY_ACTORS, f"{actor} unadopted"
