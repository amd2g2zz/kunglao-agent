# -*- coding: utf-8 -*-
"""tests/test_rl_v2_gap_formulation_943.py — the gap_formulation
perception face (#943).

Owner framing: the three-layer responsibility split — PERCEPTION
produces candidate gap formulations (advisory only, no execution
authority), the LOOP decides (budget + salience threshold), DISTILL
executes (#938's contract unchanged). Pins, written before the face
(TDD order):

  FIVE SOURCES  each source's signal lands in the clusters: worker
                shelf-miss receipts (the ledger's distill action rows —
                the loop's shelf-miss trigger is their producer),
                stagnation signals (the arbiter rows' delta_p series run
                through the stagnation face), belief open_questions
                accumulation (age = the deterministic rollout count,
                never a wall clock), refuted hypotheses + low-credit
                settlement drafts (the ladder's REFUTED class +
                step_credit's own provisional floor), and the memory
                query — an INJECTED Callable seam (#583's bridge plugs
                in later; absent = the source contributes nothing).
  CLUSTERING    same (gap_type, stage) signals merge — one cluster per
                key, strengths sum, receipts carry provenance.
  DRAFT         the R3-aligned candidate record: schema, gap_type,
                stage, subjects, draft, formulation,
                exploration_direction, salience, source_receipts,
                sources.
  SALIENCE      deterministic and monotone — stronger signals score
                strictly higher (receipt counts, stagnation segment
                length, open-question age, credit deficit magnitude).
  ADVISORY      the face fires nothing: aggregate() lands zero ledger
                rows and never a distill row — firing stays the loop's
                decision discipline.
  SEAMS         formulate_fn absent -> the structured draft lands
                without prose (honest gap, not a refusal); present ->
                the prose lands. memory_query absent -> nothing
                suppressed; present -> already-distilled gaps don't
                re-trigger (the 蒸馏克制裁定 honored at the memory
                layer). Suppressed candidates consume no formulate_fn
                call.
  FAIL-CLOSED   poison signals (non-finite delta_p/credit, non-string
                formulations, non-mapping seam returns) raise, named —
                a poisoned read must never silently formulate.
  LOOP READ     the thin loop read (loop913.read_gap_candidates):
                the loop's decision point sees the ranked candidates;
                the read is row-silent and fires nothing.

Simulated memory/LLM seams live in THIS file only; the production face
is mock-free and deterministic.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop",
           ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import loop as loop913  # noqa: E402
from loop_worker import mock_worker  # noqa: E402
from rlvr import consolidated_ledger as cl  # noqa: E402
from rlvr import q_cells  # noqa: E402
from rlvr import learning_seal as seal  # noqa: E402
from settlement import per_dispatch as pd  # noqa: E402
from state import gap_formulation as gf  # noqa: E402

PV = "loop913-test"


@pytest.fixture(autouse=True)
def _unarmed_seal(monkeypatch, tmp_path):
    monkeypatch.setattr(seal, "KEY_PATH", tmp_path / "absent.key")
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})


@pytest.fixture(autouse=True)
def _isolated_store_root(monkeypatch, tmp_path):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))


# ------------------------------------------------------------ builders

def _base_ws(tmp_path, *, questions: bool = True,
             name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    if questions:
        (ws / "task_spec.yaml").write_text(
            "primary_questions:\n- id: pq1\n  q: the offsets question\n",
            encoding="utf-8")
    return ws


def _assign(ws, rid, sid, family, ts):
    q_cells.append_action(ws, kind="assign_step", rollout_id=rid,
                          step_id=sid, target=family,
                          params={"method_family": family, "tier": 1,
                                  "phase": "explore",
                                  "intent": {"expected_output": "x"},
                                  "distribution": {}},
                          policy_version=PV, ts=ts)


def _arbiter(ws, rid, delta, ts):
    kind = "terminate_rollout" if delta > 0 else "rollback"
    q_cells.append_action(ws, kind=kind, rollout_id=rid, target="core",
                          params={"rule": "test-rule", "delta_p": delta},
                          policy_version=PV, ts=ts)


def _shelf_row(ws, formulation, ts):
    q_cells.append_action(ws, kind="distill", rollout_id="ro-w-lap1",
                          step_id="ro-w-lap1-s01", target="core",
                          params={"formulation": formulation},
                          budget={"wall_s": 600.0, "max_calls": None},
                          policy_version=PV, ts=ts)


def _refuted_fact(ws, fid):
    d = ws / "facts"
    d.mkdir(exist_ok=True)
    (d / f"{fid}.md").write_text(
        f"---\nid: {fid}\nstatus: REFUTED\nverify_status: passes\n"
        f"confidence: low\n---\n\nthe refuted claim\n", encoding="utf-8")


def _low_credit_draft(ws, rid, did, credit, ts):
    priced = pd.price_dispatch(rid, did, 0.4,
                               {"mechanical": True, "scope_verifier": True,
                                "redteam": True},
                               progress_delta=round(credit * 0.7, 6),
                               ts=ts)
    assert abs(priced["credit"] - credit) < 1e-9
    cl.append(ws, "settlement", priced)


def _by_key(candidates, gap_type, stage):
    for c in candidates:
        if c["gap_type"] == gap_type and c["stage"] == stage:
            return c
    return None


def _ledger_lines(ws) -> int:
    n = 0
    for rel in ("experience.jsonl", "settlement.jsonl"):
        p = ws / "runs" / rel
        if p.is_file():
            n += len(p.read_text(encoding="utf-8").splitlines())
    return n


def _five_source_ws(tmp_path) -> Path:
    """One workspace carrying all five sources' signals."""
    ws = _base_ws(tmp_path)
    # source 2 — stagnation: three flat rollouts, the flat direction named
    _arbiter(ws, "ro-t-lap1", 0.0, "2026-01-01T00:00:01Z")
    _arbiter(ws, "ro-t-lap2", 0.0, "2026-01-01T00:00:02Z")
    _assign(ws, "ro-t-lap3", "ro-t-lap3-s01", "static-decompile",
            "2026-01-01T00:00:03Z")
    _arbiter(ws, "ro-t-lap3", 0.0, "2026-01-01T00:00:04Z")
    # source 1 — the shelf-miss receipt (the ledger's distill row)
    _shelf_row(ws, "formulate the unpack rung", "2026-01-01T00:00:05Z")
    # source 3 — the open question rides task_spec (pq1; 3 rollouts aged)
    # source 4a — refuted hypotheses
    _refuted_fact(ws, "F0101")
    _refuted_fact(ws, "F0102")
    # source 4b — the low-credit settlement draft on a named family
    _assign(ws, "ro-t-lap1", "ro-t-lap1-s02", "dynamic-trace",
            "2026-01-01T00:00:06Z")
    _low_credit_draft(ws, "ro-t-lap1", "ro-t-lap1-s02", 0.1,
                      "2026-01-01T00:00:07Z")
    return ws


# ------------------------------------------------- five-source pin

def test_five_sources_each_land_in_clusters(tmp_path):
    ws = _five_source_ws(tmp_path)
    report = gf.aggregate(ws)
    assert report["schema"] == gf.SCHEMA
    assert report["advisory"] is True
    cs = report["candidates"]
    keys = {(c["gap_type"], c["stage"]) for c in cs}
    assert keys == {("tool", "shelf"), ("method", "static-decompile"),
                    ("context", "spec"), ("knowledge", "claim"),
                    ("knowledge", "dynamic-trace")}
    tool = _by_key(cs, "tool", "shelf")
    assert tool["sources"] == ["shelf_miss"]
    assert tool["subjects"] == ["formulate the unpack rung"]
    assert tool["salience"] == pytest.approx(1.0)
    assert tool["source_receipts"][0]["formulation"] \
        == "formulate the unpack rung"
    method = _by_key(cs, "method", "static-decompile")
    assert method["sources"] == ["stagnation"]
    assert method["salience"] == pytest.approx(3.0)
    assert method["source_receipts"][0]["flat_segments"] == 3
    assert method["subjects"] == ["ro-t-lap3"]
    context = _by_key(cs, "context", "spec")
    assert context["sources"] == ["open_question"]
    assert context["subjects"] == ["pq1"]
    assert context["salience"] == pytest.approx(1.75)  # 1.0 + 3/4 age term
    claim = _by_key(cs, "knowledge", "claim")
    assert claim["sources"] == ["refuted_credit"]
    assert claim["subjects"] == ["F0101", "F0102"]
    assert claim["salience"] == pytest.approx(2.0)
    credit = _by_key(cs, "knowledge", "dynamic-trace")
    assert credit["sources"] == ["refuted_credit"]
    assert credit["subjects"] == ["ro-t-lap1-s02"]
    assert credit["salience"] == pytest.approx(0.2)  # 0.3 floor - 0.1 credit


# --------------------------------------------------- clustering pins

def test_same_stage_signals_merge(tmp_path):
    ws = _base_ws(tmp_path, questions=False)
    _shelf_row(ws, "formulate the unpack rung", "2026-01-01T00:00:01Z")
    _shelf_row(ws, "formulate the unpack rung", "2026-01-01T00:00:02Z")
    _shelf_row(ws, "a different gap entirely", "2026-01-01T00:00:03Z")
    cs = gf.aggregate(ws)["candidates"]
    # one (gap_type, stage) cluster: same-stage signals merge, the
    # subjects enumerate the distinct objects, strengths sum
    shelf = [c for c in cs if c["gap_type"] == "tool"]
    assert len(shelf) == 1
    assert shelf[0]["salience"] == pytest.approx(3.0)
    assert len(shelf[0]["source_receipts"]) == 3
    assert shelf[0]["subjects"] == ["a different gap entirely",
                                    "formulate the unpack rung"]


# --------------------------------------------------- the draft shape

def test_candidate_draft_structure(tmp_path):
    ws = _five_source_ws(tmp_path)
    cs = gf.aggregate(ws)["candidates"]
    required = ("schema", "gap_type", "stage", "subjects", "draft",
                "formulation", "exploration_direction", "salience",
                "source_receipts", "sources")
    for c in cs:
        for field in required:
            assert field in c, field
        assert c["schema"] == gf.CANDIDATE_SCHEMA
        assert c["draft"]["gap_type"] == c["gap_type"]
        assert c["draft"]["stage"] == c["stage"]
        assert c["draft"]["subjects"] == c["subjects"]
        assert sum(c["draft"]["strengths"].values()) \
            == pytest.approx(c["salience"])
        assert c["exploration_direction"] == c["subjects"]
        assert c["source_receipts"]
    tool = _by_key(cs, "tool", "shelf")
    assert tool["draft"]["strengths"] == {"shelf_miss": 1.0}


# ------------------------------------------------ salience monotonicity

def test_salience_monotone_in_receipt_count(tmp_path):
    one = _base_ws(tmp_path, questions=False, name="ws-one")
    _shelf_row(one, "gap a", "2026-01-01T00:00:01Z")
    two = _base_ws(tmp_path, questions=False, name="ws-two")
    for i in (1, 2):
        _shelf_row(two, "gap a", f"2026-01-01T00:00:0{i}Z")
    s1 = _by_key(gf.aggregate(one)["candidates"], "tool", "shelf")
    s2 = _by_key(gf.aggregate(two)["candidates"], "tool", "shelf")
    assert s2["salience"] > s1["salience"]


def test_salience_monotone_in_flat_tail(tmp_path):
    short = _base_ws(tmp_path, questions=False, name="ws-short")
    _arbiter(short, "ro-a", 1.0, "2026-01-01T00:00:01Z")
    _arbiter(short, "ro-b", 0.0, "2026-01-01T00:00:02Z")
    _arbiter(short, "ro-c", 0.0, "2026-01-01T00:00:03Z")
    long_ws = _base_ws(tmp_path, questions=False, name="ws-long")
    for i, rid in enumerate(("ro-a", "ro-b", "ro-c")):
        _arbiter(long_ws, rid, 0.0, f"2026-01-01T00:00:0{i + 1}Z")
    s_short = _by_key(gf.aggregate(short)["candidates"], "method",
                      "unknown")
    s_long = _by_key(gf.aggregate(long_ws)["candidates"], "method",
                     "unknown")
    assert s_long["salience"] > s_short["salience"]


def test_salience_monotone_in_workspace_age(tmp_path):
    """The age term is a WORKSPACE-LEVEL constant: the pin varies the
    workspace's rollout count (what ages is the workspace, not any
    single question)."""
    young = _base_ws(tmp_path, name="ws-young")
    _arbiter(young, "ro-y", 1.0, "2026-01-01T00:00:01Z")
    old = _base_ws(tmp_path, name="ws-old")
    for i in (1, 2):
        _arbiter(old, f"ro-o{i}", 1.0, f"2026-01-01T00:00:0{i}Z")
    s_young = _by_key(gf.aggregate(young)["candidates"], "context", "spec")
    s_old = _by_key(gf.aggregate(old)["candidates"], "context", "spec")
    assert s_old["salience"] > s_young["salience"]


def test_salience_monotone_in_credit_deficit(tmp_path):
    small = _base_ws(tmp_path, questions=False, name="ws-small")
    _assign(small, "ro-s", "ro-s-s01", "dynamic-trace",
            "2026-01-01T00:00:01Z")
    _low_credit_draft(small, "ro-s", "ro-s-s01", 0.2,
                      "2026-01-01T00:00:02Z")
    big = _base_ws(tmp_path, questions=False, name="ws-big")
    _assign(big, "ro-b", "ro-b-s01", "dynamic-trace",
            "2026-01-01T00:00:01Z")
    _low_credit_draft(big, "ro-b", "ro-b-s01", 0.1,
                      "2026-01-01T00:00:02Z")
    s_small = _by_key(gf.aggregate(small)["candidates"], "knowledge",
                      "dynamic-trace")
    s_big = _by_key(gf.aggregate(big)["candidates"], "knowledge",
                    "dynamic-trace")
    assert s_big["salience"] > s_small["salience"]


def test_ranking_is_salience_desc_and_deterministic(tmp_path):
    ws = _five_source_ws(tmp_path)
    first = gf.aggregate(ws)
    second = gf.aggregate(ws)
    assert first == second                      # pure — no clock anywhere
    sals = [c["salience"] for c in first["candidates"]]
    assert sals == sorted(sals, reverse=True)
    assert sals[0] == pytest.approx(3.0)        # the flat method gap leads


# ------------------------------------------------------- advisory-only

def test_face_lands_no_rows_and_never_a_distill_row(tmp_path):
    ws = _five_source_ws(tmp_path)
    before = _ledger_lines(ws)
    distill_before = len([r for r in q_cells.trajectory_rows(ws)
                          if r.get("kind") == "distill"])
    memory = lambda draft: {"distilled": False}  # noqa: E731 — consulted
    prose = lambda draft: "prose"  # noqa: E731 — consulted
    gf.aggregate(ws, memory_query=memory, formulate_fn=prose)
    assert _ledger_lines(ws) == before
    assert len([r for r in q_cells.trajectory_rows(ws)
                if r.get("kind") == "distill"]) == distill_before


# --------------------------------------------------------- the seams

def test_seam_absence_is_structured_draft_without_prose(tmp_path):
    ws = _five_source_ws(tmp_path)
    report = gf.aggregate(ws)
    assert report["seams"] == {"memory_query": False, "formulate_fn": False}
    assert report["memory_suppressed"] == []
    for c in report["candidates"]:
        assert c["formulation"] == ""           # the honest empty prose
        assert c["draft"]["subjects"]           # the draft fully lands


def test_formulate_fn_prose_lands(tmp_path):
    ws = _five_source_ws(tmp_path)

    def formulate(draft):
        return (f"在 {draft['stage']} 阶段对 "
                f"{'、'.join(draft['subjects'])} 类样本缺 "
                f"{draft['gap_type']}")

    report = gf.aggregate(ws, formulate_fn=formulate)
    assert report["seams"]["formulate_fn"] is True
    tool = _by_key(report["candidates"], "tool", "shelf")
    assert tool["formulation"] == ("在 shelf 阶段对 formulate the unpack "
                                   "rung 类样本缺 tool")


def test_formulate_fn_decline_is_honest_empty(tmp_path):
    ws = _five_source_ws(tmp_path)
    report = gf.aggregate(ws, formulate_fn=lambda draft: "   ")
    for c in report["candidates"]:
        assert c["formulation"] == ""


def test_memory_query_receives_the_draft(tmp_path):
    ws = _five_source_ws(tmp_path)
    seen: list[dict] = []
    gf.aggregate(ws, memory_query=seen.append)
    assert seen
    for draft in seen:
        assert {"gap_type", "stage", "subjects", "strengths"} \
            <= set(draft)


def test_already_distilled_gaps_do_not_retrigger(tmp_path):
    ws = _five_source_ws(tmp_path)
    calls = {"n": 0}

    def memory(draft):
        calls["n"] += 1
        return {"distilled": True} if draft["stage"] == "shelf" else None

    report = gf.aggregate(ws, memory_query=memory,
                          formulate_fn=lambda draft: "prose")
    assert calls["n"] == 5                       # every cluster consulted
    assert _by_key(report["candidates"], "tool", "shelf") is None
    suppressed = report["memory_suppressed"]
    assert len(suppressed) == 1
    assert suppressed[0]["reason"] == gf.SUPPRESS_REASON
    assert suppressed[0]["candidate"]["stage"] == "shelf"
    assert suppressed[0]["memory_receipt"] == {"distilled": True}
    # restraint: suppressed gaps consume no prose budget
    assert len(report["candidates"]) == 4
    for c in report["candidates"]:
        assert c["formulation"] == "prose"


def test_empty_workspace_is_honest_empty(tmp_path):
    ws = _base_ws(tmp_path, questions=False)
    report = gf.aggregate(ws)
    assert report["candidates"] == []
    assert report["memory_suppressed"] == []


# --------------------------------------------------------- fail-closed

def _poison(ws, family, row):
    assert cl.append(ws, family, row) is True


def test_poison_distill_formulation_raises(tmp_path):
    ws = _base_ws(tmp_path, questions=False)
    _poison(ws, "experience", {
        "schema": q_cells.SCHEMA_ACTION_V2, "ts": "2026-01-01T00:00:01Z",
        "kind": "distill", "rollout_id": "ro-p", "step_id": None,
        "target": "core", "params": {"formulation": 123}})
    with pytest.raises(gf.GapFormulationError, match="formulation"):
        gf.aggregate(ws)


def test_poison_delta_p_raises(tmp_path):
    ws = _base_ws(tmp_path, questions=False)
    _poison(ws, "experience", {
        "schema": q_cells.SCHEMA_ACTION_V2, "ts": "2026-01-01T00:00:01Z",
        "kind": "rollback", "rollout_id": "ro-p", "step_id": None,
        "target": "core",
        "params": {"rule": "x", "delta_p": float("nan")}})
    with pytest.raises(gf.GapFormulationError, match="delta_p"):
        gf.aggregate(ws)


def test_signed_negative_delta_p_is_a_legal_signal(tmp_path):
    """The arbiter rows' delta_p domain is SIGNED finite: production
    rollback rows legitimately carry negative ΔP (loop.py lands
    rollback for any non-positive delta; progress.delta_P prices
    penalitive edges) — a historical regression row must never poison
    the read. A flat signed tail still lands the stagnation signal; a
    real negative move correctly resets the flat streak."""
    ws = _base_ws(tmp_path, questions=False)
    _arbiter(ws, "ro-n1", -2.5, "2026-01-01T00:00:01Z")  # real move
    _arbiter(ws, "ro-n2", -1e-7, "2026-01-01T00:00:02Z")  # signed flat
    _arbiter(ws, "ro-n3", -1e-7, "2026-01-01T00:00:03Z")
    cs = gf.aggregate(ws)["candidates"]                   # no raise
    method = _by_key(cs, "method", "unknown")
    assert method is not None
    assert method["salience"] == pytest.approx(2.0)
    assert method["source_receipts"][0]["flat_segments"] == 2


def test_poison_credit_raises(tmp_path):
    ws = _base_ws(tmp_path, questions=False)
    _poison(ws, "settlement", {
        "schema": pd.DRAFT_SCHEMA, "ts": "2026-01-01T00:00:01Z",
        "batch_id": pd.batch_id("ro-p"), "rollout_id": "ro-p",
        "dispatch_id": "ro-p-s01", "spend": 0.4,
        "verdicts": {"mechanical": True, "scope_verifier": True,
                     "redteam": True},
        "credit": float("nan")})
    with pytest.raises(gf.GapFormulationError, match="credit"):
        gf.aggregate(ws)


def test_broken_formulate_seam_raises(tmp_path):
    ws = _five_source_ws(tmp_path)
    with pytest.raises(gf.GapFormulationError, match="formulate_fn"):
        gf.aggregate(ws, formulate_fn=lambda draft: 123)


def test_broken_memory_seam_raises(tmp_path):
    ws = _five_source_ws(tmp_path)
    with pytest.raises(gf.GapFormulationError, match="memory_query"):
        gf.aggregate(ws, memory_query=lambda draft: 123)


# ----------------------------------------------------- the loop read

def _shelf_worker(formulation: str):
    calls = {"n": 0}

    def worker(situation: str, family: str) -> dict:
        out = mock_worker(situation, family)
        if out["verified"] and calls["n"] == 0:
            calls["n"] += 1
            return {**out, "shelf_miss": formulation}
        return out

    return worker


def test_loop_read_returns_ranked_candidates_row_silent(tmp_path):
    ws = tmp_path / "ws"
    loop913.run_loop(ws, laps=1, seed=7, spawn_slots=1,
                     worker=_shelf_worker("formulate the unpack rung"))
    before = _ledger_lines(ws)
    cs = loop913.read_gap_candidates(ws)
    assert _ledger_lines(ws) == before          # the read lands nothing
    tool = _by_key(cs, "tool", "shelf")
    assert tool is not None
    assert "formulate the unpack rung" in tool["subjects"]
    sals = [c["salience"] for c in cs]
    assert sals == sorted(sals, reverse=True)


def test_loop_read_plain_worker_has_no_shelf_gap(tmp_path):
    ws = tmp_path / "ws"
    loop913.run_loop(ws, laps=1, seed=7, spawn_slots=1,
                     worker=mock_worker)
    assert _by_key(loop913.read_gap_candidates(ws), "tool", "shelf") is None
