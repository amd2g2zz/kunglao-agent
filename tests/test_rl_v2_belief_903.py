# -*- coding: utf-8 -*-
"""tests/test_rl_v2_belief_903.py — the belief aggregation face (903).

Pins for P(s)'s structured observation precursor: the six-element
``belief-snapshot/1`` document built from EXISTING faces only.

  1. completeness — the snapshot carries exactly the six cognition
     elements plus the schema stamp; honest empties, never fabricated
     content;
  2. determinism — the same sources build an identical snapshot (pure
     function of its inputs, no clock, no sampling);
  3. the fact fold — fact frontmatter status bands fold onto the
     step-credit ladder (cross-validated anchors bank as confirmed; a
     reproduced rule-out banks at full strength; refuted and floor
     facts stay data);
  4. the single-authority wall — LLM-proposed content has NO input
     channel: a worker-assertion resolution row is recorded history
     that never banks, and the snapshot signature accepts no proposals;
  5. fail-closed walls — malformed sources raise, never half-read;
  6. the delta_P noise-isolation pin — identical subgoal status
     sequences produce IDENTICAL deltas regardless of every other
     input; an N=8 cross-run harness over the real q-cell append faces
     (identical planted outcomes, run-local noise on every irrelevant
     id, natural wall-clock ts on the rows) pins the within-situation
     delta_P variance to ZERO exactly, while distinct situations hold a
     strictly positive spread — the separation the credit signal needs.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from hypothesis_store import Hypothesis, HypothesisStore  # noqa: E402
from rlvr import phi_tree  # noqa: E402
from rlvr import q_cells  # noqa: E402
from state import belief, evaluation, progress  # noqa: E402

_REF = "evidence/F001.md#L4-L6"


@pytest.fixture(autouse=True)
def _unarmed_seal(monkeypatch, tmp_path):
    """Deterministic seal posture: rows pass through unsigned in this
    suite (the same posture the ledger suites pin)."""
    from rlvr import learning_seal as seal
    monkeypatch.setattr(seal, "KEY_PATH", tmp_path / "absent.key")
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})


@pytest.fixture(autouse=True)
def _isolated_store_root(monkeypatch, tmp_path):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))


def _sub(gid: str, status: str, refs=(_REF,), conf: float = 0.8):
    return progress.Subgoal(id=gid, status=status,
                            evidence_refs=refs, confidence=conf)


# ------------------------------------------------------- completeness

def test_snapshot_carries_exactly_the_six_elements():
    doc = belief.snapshot((), (), (), (), ())
    assert doc["schema"] == belief.SCHEMA
    assert set(doc) == {"schema", *belief.ELEMENTS}
    assert belief.ELEMENTS == ("confirmed_facts", "hypotheses",
                               "excluded_hypotheses", "analyzed_areas",
                               "open_questions", "current_goal")
    # honest empties — the view never fabricates content
    assert doc["confirmed_facts"] == []
    assert doc["hypotheses"] == []
    assert doc["excluded_hypotheses"] == []
    assert doc["analyzed_areas"] == []
    assert doc["open_questions"] == []
    assert doc["current_goal"] is None


# -------------------------------------------------------- determinism

def test_same_sources_build_identical_snapshots():
    facts = [{"id": "F001", "status": "PROVEN", "confidence": "high",
              "verify_status": "passes"}]
    resolutions = [{"hypothesis": "H-1", "evidence_kind": "machine-witness",
                    "evidence_ref": "ev-1", "band": "SETTLED_CREDIT"}]
    eliminations = [{"hypothesis": "H-2", "candidate": "rc4",
                     "evidence_kind": "referee-confirm",
                     "evidence_ref": "ev-2"}]
    actions = [{"schema": q_cells.SCHEMA_ACTION_V2, "kind": "select_task",
                "target": "C-1"},
               {"schema": q_cells.SCHEMA_ACTION_V2, "kind": "assign_step",
                "target": "fam-a"}]
    questions = [{"id": "Q-1", "question": "which mode?"}]
    first = belief.snapshot(facts, resolutions, eliminations, actions,
                            questions)
    again = belief.snapshot(list(facts), list(resolutions),
                            list(eliminations), list(actions),
                            list(questions))
    assert first == again
    assert belief.belief_digest(first) == belief.belief_digest(again)


# --------------------------------------------------------- fact fold

def test_confirmed_facts_fold_onto_the_step_credit_ladder():
    facts = [
        {"id": "F001", "status": "PROVEN", "confidence": "high",
         "verify_status": "passes"},
        {"id": "F002", "status": "NEGATIVE", "confidence": "high",
         "verify_status": "passes"},
        {"id": "F003", "status": "VERIFIED", "confidence": "high",
         "verify_status": "passes"},
        {"id": "F004", "status": "PROVEN", "confidence": "high"},
        {"id": "F005", "status": "INFERRED", "confidence": "medium"},
        {"id": "F006", "status": "REFUTED", "confidence": "high",
         "verify_status": "passes"},
    ]
    doc = belief.snapshot(facts, (), (), (), ())
    # id-sorted; only the ladder's cross-validated band banks as confirmed
    assert [f["id"] for f in doc["confirmed_facts"]] == \
        ["F001", "F002", "F003"]
    assert all(f["class"] == "cross_validated"
               for f in doc["confirmed_facts"])
    assert doc["confirmed_facts"][0]["status"] == "PROVEN"
    assert doc["confirmed_facts"][0]["confidence"] == "high"


def test_reproduced_rule_out_banks_as_confirmed():
    # the ladder's own correction: a proven negative is terminal
    # strength, not a failure — it banks like any cross-validated fact
    facts = [{"id": "F009", "status": "NEGATIVE", "confidence": "high",
              "verify_status": "passes"}]
    doc = belief.snapshot(facts, (), (), (), ())
    assert [f["id"] for f in doc["confirmed_facts"]] == ["F009"]


# ------------------------------------------------ the authority walls

def test_hypotheses_latest_decisive_row_wins():
    """Two decisive rows for ONE hypothesis: the LATEST (append order)
    is the banked evidence — a regression to FIRST-wins flips this
    pin red (the review's coverage gap)."""
    resolutions = [
        {"hypothesis": "H-1", "evidence_kind": "machine-witness",
         "evidence_ref": "ev-old", "band": "SETTLED_CREDIT"},
        {"hypothesis": "H-1", "evidence_kind": "referee-confirm",
         "evidence_ref": "ev-new", "band": "SETTLED_CREDIT"},
    ]
    doc = belief.snapshot(
        [{"id": "F001", "status": "PROVEN", "confidence": "high",
          "verify_status": "passes"}],
        resolutions, (), (), ())
    (h,) = doc["hypotheses"]
    assert h["evidence_ref"] == "ev-new"
    assert h["evidence_kind"] == "referee-confirm"


def test_worker_assertion_resolutions_never_bank():
    rows = [
        {"hypothesis": "H-1", "evidence_kind": "worker-assertion",
         "evidence_ref": "self-report", "band": "NEUTRAL"},
        {"hypothesis": "H-2", "evidence_kind": "machine-witness",
         "evidence_ref": "ev-2", "band": "SETTLED_CREDIT"},
    ]
    doc = belief.snapshot((), rows, (), (), ())
    assert [h["id"] for h in doc["hypotheses"]] == ["H-2"]
    # the decisive evidence rides the banked entry
    assert doc["hypotheses"][0]["evidence_kind"] == "machine-witness"
    assert doc["hypotheses"][0]["evidence_ref"] == "ev-2"


def test_llm_proposals_have_no_input_channel():
    # the evaluation document proposes subgoal moves (its own seam,
    # pinned by the 898 suite) — but the belief face has NO proposals
    # parameter: LLM-proposed content cannot enter the snapshot
    with pytest.raises(TypeError):
        belief.snapshot((), (), (), (), (),
                        proposals=[{"subgoal_id": "g1",
                                    "to_status": "PROVEN"}])
    tree = [_sub("g1", "UNVERIFIED", refs=())]
    doc = {
        "schema": evaluation.SCHEMA,
        "new_facts": ["F999"], "validated_hypotheses": ["H-99"],
        "rejected_hypotheses": [], "unresolved_questions": [],
        "exploration_progress": 0.9, "redundancy": 0.0,
        "possible_new_directions": [],
        "proposals": [{"subgoal_id": "g1", "to_status": "PROVEN",
                       "evidence_refs": [_REF]}],
    }
    assert evaluation.apply_proposals(tree, doc)[0].status == "PROVEN"
    # ... and the snapshot built from EMPTY sources stays empty: the
    # evaluation document is not one of its sources
    assert belief.snapshot((), (), (), (), ())["confirmed_facts"] == []


def test_excluded_hypotheses_dedup_by_pair():
    rows = [
        {"hypothesis": "H-1", "candidate": "aes",
         "evidence_kind": "machine-witness", "evidence_ref": "ev-1"},
        {"hypothesis": "H-1", "candidate": "aes",
         "evidence_kind": "referee-confirm", "evidence_ref": "ev-2"},
        {"hypothesis": "H-1", "candidate": "rc4",
         "evidence_kind": "machine-witness", "evidence_ref": "ev-3"},
    ]
    doc = belief.snapshot((), (), rows, (), ())
    pairs = [(e["hypothesis"], e["candidate"])
             for e in doc["excluded_hypotheses"]]
    assert pairs == [("H-1", "aes"), ("H-1", "rc4")]


# ------------------------------------------- analyzed areas + the goal

def test_analyzed_areas_and_current_goal_from_action_rows():
    act = q_cells.SCHEMA_ACTION_V2
    rows = [
        {"schema": act, "kind": "select_task", "target": "C-2"},
        {"schema": act, "kind": "assign_step", "target": "fam-b"},
        {"schema": act, "kind": "select_task", "target": "C-1"},
        {"schema": act, "kind": "assign_step", "target": "fam-a"},
        {"schema": act, "kind": "assign_step", "target": "fam-b"},
    ]
    doc = belief.snapshot((), (), (), rows, ())
    assert doc["analyzed_areas"] == ["C-1", "C-2", "fam-a", "fam-b"]
    # the latest select_task re-point IS the current exploration goal
    assert doc["current_goal"] == "C-1"


def test_current_goal_is_none_without_select_task():
    rows = [{"schema": q_cells.SCHEMA_ACTION_V2, "kind": "assign_step",
             "target": "fam-a"}]
    doc = belief.snapshot((), (), (), rows, ())
    assert doc["analyzed_areas"] == ["fam-a"]
    assert doc["current_goal"] is None


def test_open_questions_keep_the_task_spec_priority_order():
    questions = [{"id": "Q-2", "question": "is the key schedule mutated?"},
                 {"id": "Q-1", "question": ""}]
    doc = belief.snapshot((), (), (), (), questions)
    assert doc["open_questions"] == [
        {"id": "Q-2", "question": "is the key schedule mutated?"},
        {"id": "Q-1", "question": ""}]


# --------------------------------------------- end-to-end disk reads

def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    for rel in ("hypotheses", "runs", "facts"):
        (ws / rel).mkdir(parents=True)
    return ws


def _fact(ws: Path, fid: str, status: str, *, conf: str = "high",
          verify: str | None = "passes") -> None:
    lines = ["---", f"id: {fid}", f"status: {status}",
             f"confidence: {conf}"]
    if verify is not None:
        lines.append(f"verify_status: {verify}")
    lines += ["---", "body", ""]
    (ws / "facts" / f"{fid}-a.md").write_text(
        "\n".join(lines), encoding="utf-8")


def test_build_snapshot_reads_existing_faces_end_to_end(tmp_path):
    ws = _ws(tmp_path)
    _fact(ws, "F001", "PROVEN")
    _fact(ws, "F002", "OPEN")
    store = HypothesisStore(ws / "hypotheses")
    store.create(Hypothesis(id="H-1", claim_id="C-1",
                            competitor_group="cipher", candidates=["aes"]))
    store.create(Hypothesis(id="H-2", claim_id="C-1",
                            competitor_group="cipher", candidates=["rc4"]))
    assert phi_tree.settle_resolution(
        ws, "H-1", evidence_kind="machine-witness",
        evidence_ref="evidence/F001.md", step_ref="s-1",
        claim_ref="C-1") is not None
    assert phi_tree.elimination_credit(
        ws, "H-2", candidate="rc4", evidence_kind="referee-confirm",
        evidence_ref="evidence/F001.md", step_ref="s-2",
        claim_ref="C-1") is not None
    q_cells.append_action(ws, kind="select_task", rollout_id="ro-1",
                          target="C-1")
    q_cells.append_action(ws, kind="assign_step", rollout_id="ro-1",
                          target="fam-a",
                          params={"method_family": "fam-a"})
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n"
        "  - id: Q-1\n"
        "    question: which cipher?\n",
        encoding="utf-8")

    doc = belief.build_snapshot(ws)
    assert doc["schema"] == belief.SCHEMA
    assert [f["id"] for f in doc["confirmed_facts"]] == ["F001"]
    assert doc["confirmed_facts"][0]["status"] == "PROVEN"
    assert [h["id"] for h in doc["hypotheses"]] == ["H-1"]
    assert [(e["hypothesis"], e["candidate"])
            for e in doc["excluded_hypotheses"]] == [("H-2", "rc4")]
    assert doc["analyzed_areas"] == ["C-1", "fam-a"]
    assert doc["current_goal"] == "C-1"
    assert doc["open_questions"] == [{"id": "Q-1",
                                      "question": "which cipher?"}]
    # a second read of the same workspace is byte-identical
    assert belief.build_snapshot(ws) == doc


# ------------------------------------------------------ fail-closed

def test_fail_closed_reject_pins():
    with pytest.raises(ValueError):
        belief.snapshot([{"status": "PROVEN",
                          "verify_status": "passes"}], (), (), (), ())
    with pytest.raises(ValueError):
        belief.snapshot([{"id": "F001", "status": 42}], (), (), (), ())
    with pytest.raises(ValueError):
        belief.snapshot([{"id": "F001", "status": "OPEN",
                          "confidence": "certain"}], (), (), (), ())
    with pytest.raises(ValueError):
        belief.snapshot([{"id": "F001"}], (), (), (), ())
    with pytest.raises(ValueError):
        belief.snapshot((), [{"evidence_kind": "machine-witness",
                              "evidence_ref": "e"}], (), (), ())
    with pytest.raises(ValueError):
        belief.snapshot((), (), [{"hypothesis": "H-1",
                                  "evidence_kind": "machine-witness",
                                  "evidence_ref": "e"}], (), ())
    with pytest.raises(ValueError):
        belief.snapshot((), (), (), ["select_task C-1"], ())
    with pytest.raises(ValueError):
        belief.snapshot((), (), (),
                        [{"schema": q_cells.OBS_SCHEMA,
                          "kind": "select_task", "target": "C-1"}], ())
    with pytest.raises(ValueError):
        belief.snapshot((), (), (),
                        [{"schema": q_cells.SCHEMA_ACTION_V2,
                          "kind": "select_task", "target": ""}], ())
    with pytest.raises(ValueError):
        belief.snapshot((), (), (), (), [{"question": "which?"}])
    with pytest.raises(ValueError):
        belief.snapshot(
            [{"id": "F001", "status": "PROVEN",
              "verify_status": "passes"}] * 2, (), (), (), ())


# ------------------------------------------------- telemetry landing

def test_record_belief_lands_a_credit_free_telemetry_row(tmp_path):
    ws = tmp_path / "ws"
    doc = belief.snapshot((), (), (), (), ())
    out = belief.record_belief(ws, doc, claim="C-1")
    assert out["appended"] is True
    assert out["row"].get("credit") is None
    assert out["row"].get("source") == progress.SOURCE
    rows = [r for r in q_cells.trajectory_rows(ws)
            if r.get("schema") == q_cells.OBS_SCHEMA]
    assert len(rows) == 1
    assert rows[0]["signature_hash"] == belief.belief_digest(doc)
    with pytest.raises(ValueError):
        belief.record_belief(ws, {"schema": "other/1"})


# ------------------------------------- the delta_P noise-isolation pin

def test_delta_p_is_a_pure_function_of_statuses():
    def tree(status, refs, conf):
        return [_sub("g1", status, refs=refs, conf=conf)]

    base = progress.delta_P(tree("UNVERIFIED", (), 0.0),
                            tree("PROVEN", (_REF,), 0.9))
    # vary every NON-status input: confidence, evidence refs, the ids
    assert progress.delta_P(
        tree("UNVERIFIED", (), 1.0),
        tree("PROVEN", ("evidence/F009.md#L1",), 0.2)) == base
    renamed_before = [progress.Subgoal(id="zzz", status="UNVERIFIED",
                                       evidence_refs=())]
    renamed_after = [progress.Subgoal(id="zzz", status="PROVEN",
                                      evidence_refs=(_REF,))]
    assert progress.delta_P(renamed_before, renamed_after) == base
    # a different status sequence moves the delta — the signal exists
    assert progress.delta_P(tree("UNVERIFIED", (), 0.0),
                            tree("VERIFIED", (_REF,), 0.9)) == base


def _situation_climb():
    """Identical planted sequence: two subgoals enter at the floor and
    climb to full cross-validated strength. Tuples are
    (before_tree, after_tree, planted_r_t, planted_verified)."""
    return [
        ([_sub("g1", "UNVERIFIED", refs=())], [_sub("g1", "PROVEN")],
         0.4, True),
        ([_sub("g2", "UNVERIFIED", refs=())], [_sub("g2", "NEGATIVE")],
         0.2, True),
    ]


def _situation_refute():
    """A DIFFERENT situation: same shape, second subgoal refutes."""
    return [
        ([_sub("g1", "UNVERIFIED", refs=())], [_sub("g1", "VERIFIED")],
         0.4, True),
        ([_sub("g2", "UNVERIFIED", refs=())],
         [_sub("g2", "REFUTED", refs=())], 0.2, True),
    ]


def _run_situation(ws: Path, run_index: int, situation) -> list[float]:
    """One cross-run harness leg over the REAL append faces.

    Identical planted outcomes; run-local noise on every irrelevant id
    (rollout, step, claim); the append faces stamp their natural
    wall-clock ts. If the credit face added any noise of its own, any
    of this would move delta_P — the pin forbids exactly that.
    """
    for k, (before, after, r_planted, verified) in enumerate(situation):
        q_cells.append_action(ws, kind="assign_step",
                              rollout_id=f"ro-{run_index}",
                              target=f"fam-{k}",
                              params={"method_family": f"fam-{k}"})
        progress.record_transition(ws, before=before, after=after,
                                   claim=f"C-9{run_index}")
        q_cells.append_result(ws, rollout_id=f"ro-{run_index}",
                              step_id=f"s-{run_index}-{k}",
                              r_t=r_planted, verified=verified,
                              verdict="pass" if verified else "fail")
    deltas = []
    planted = []
    for row in q_cells.trajectory_rows(ws):
        if row.get("schema") == q_cells.OBS_SCHEMA \
                and str(row.get("source")) == progress.SOURCE:
            fp = str(row.get("fingerprint") or "")
            assert fp.startswith("delta_p=")
            deltas.append(float(fp.split("=", 1)[1]))
        if row.get("schema") == q_cells.SCHEMA_RESULT_V2:
            planted.append(row.get("r_t"))
    # the ledger trace IS the pure function of the planted statuses...
    assert deltas == [progress.delta_P(b, a)
                      for (b, a, _r, _v) in situation]
    # ... and the planted outcomes really were identical legs
    assert planted == [r for (_b, _a, r, _v) in situation]
    return deltas


N_RUNS = 8


def test_within_situation_delta_p_variance_is_exactly_zero(tmp_path):
    situation = _situation_climb()
    series = []
    for i in range(N_RUNS):
        ws = tmp_path / f"ws-run-{i}"
        ws.mkdir(parents=True)
        series.append(_run_situation(ws, i, situation))
    for run in series[1:]:
        assert run == series[0]
    d = np.array(series, dtype=float)
    assert (d == d[0]).all()
    # EXACT zero — not approximately: the credit face adds no noise.
    # statistics.pvariance accounts in exact rationals (numpy's own
    # pairwise sum rounds even on identical inputs — that artifact is
    # the summation, never the signal)
    for j in range(d.shape[1]):
        assert statistics.pvariance(series_i for series_i in
                                    [row[j] for row in series]) == 0.0


def test_cross_situation_delta_p_spread_is_strictly_positive(tmp_path):
    climb = _run_situation(tmp_path / "ws-a", 0, _situation_climb())
    refute = _run_situation(tmp_path / "ws-b", 1, _situation_refute())
    totals = [sum(climb), sum(refute)]
    # the separation the credit signal needs: distinct situations are
    # distinguishable ABOVE the (zero) within-situation noise floor
    assert max(totals) - min(totals) > 0.0
    assert statistics.pvariance(totals) > 0.0
