# -*- coding: utf-8 -*-
"""tests/test_verdict_scorer_script.py — contract tests for the DETERMINISTIC
verdict scorer (owner ruling: the LLM judgment surface sinks to a script).

The verdict-scorer LLM judgment surface sank to scripts/verdict_scorer.py:
scoring is pure mechanical matching (answers_question + PROVEN status +
C0a/C0b bands + reproduction replay demand + contradiction consume).
These tests pin the ruling faces — the scoring table the retired rubric
documented is now CODE, so the contract moved from "the agent file says"
to "the script computes".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import verdict_scorer  # noqa: E402

FACT = """---
id: {fid}
status: PROVEN
confidence_band: PROVEN-FULL
claim_id: {cid}
answers_question: {qid}
---

# {fid}

{conclusion}
"""

FACT_NO_BAND = """---
id: F-001
status: PROVEN
confidence_band: PROVEN-PARTIAL
claim_id: C-001
answers_question: q1
---

# F-001

the answer body
"""


def _ws(tmp_path, task_spec, claims, index_rows, fact_files=None,
        evidence=None):
    ws = tmp_path / "ws"
    (ws / "evidence").mkdir(parents=True)
    if task_spec is not None:
        (ws / "task_spec.yaml").write_text(task_spec, encoding="utf-8")
    reg = "claims:\n" + "\n".join(claims)
    (ws / "claim-register.yaml").write_text(reg, encoding="utf-8")
    if index_rows is not None:
        facts = ws / "facts"
        facts.mkdir()
        header = "# facts index\n\n"
        body = "".join(f"{r}\n" for r in index_rows)
        (facts / "_INDEX.md").write_text(header + body, encoding="utf-8")
    for fid, text in (fact_files or {}).items():
        (ws / "facts" / f"{fid}.md").write_text(text, encoding="utf-8")
    for name, doc in (evidence or {}).items():
        (ws / "evidence" / name).write_text(
            json.dumps(doc, indent=2), encoding="utf-8")
    return ws


def _replay_artifact(claim_id="C-001"):
    return {
        "schema": "replay-equivalence/1",
        "claim_id": claim_id,
        "captured_inputs": ["cap-01"],
        "variables": {"mode": ["fast"]},
        "strength": 1,
        "withheld_inputs": [],
        "pairs": [{
            "input_id": "cap-01",
            "inputs": {"mode": "fast"},
            "ref_output": "aaaa",
            "repro_output": "aaaa",
            "byte_equal": True,
            "divergence_offset": None,
        }],
    }


TASK_SPEC = """\
sample_sha256: abc123
primary_questions:
  - id: q1
    question: what is the answer
"""


class TestC0a:
    def test_answered_green(self, tmp_path):
        ws = _ws(
            tmp_path, TASK_SPEC,
            claims=["- id: C-001\n  status: PROVEN\n  answers_question: q1"],
            index_rows=["F-001 | PROVEN | C-001 | the answer"],
            fact_files={"F-001": FACT.format(
                fid="F-001", cid="C-001", qid="q1",
                conclusion="the answer body")},
        )
        verdict, err = verdict_scorer.score_workspace(ws)
        assert err == ""
        av = verdict["analysis_verdict"]
        assert av["complete"] is True
        assert av["correct"] is True
        entry = av["primary_questions"][0]
        assert entry["answered"] is True
        assert entry["cited_fact"] == "F-001"
        assert entry["confidence_band"] == "PROVEN-FULL"
        assert entry["gap"] is None
        assert av["unresolved"] == []
        assert verdict["self_audit"]["evidence_strength"] == "strong"

    def test_band_not_full_fails_c0a(self, tmp_path):
        ws = _ws(
            tmp_path, TASK_SPEC,
            claims=["- id: C-001\n  status: PROVEN\n  answers_question: q1"],
            index_rows=["F-001 | PROVEN | C-001 | the answer"],
            fact_files={"F-001": FACT_NO_BAND},
        )
        verdict, _ = verdict_scorer.score_workspace(ws)
        av = verdict["analysis_verdict"]
        entry = av["primary_questions"][0]
        assert entry["answered"] is False
        assert "PROVEN-FULL" in entry["gap"]
        assert av["unresolved"] == ["q1"]
        assert verdict["self_audit"]["evidence_strength"] == "weak"

    def test_claim_not_proven(self, tmp_path):
        ws = _ws(
            tmp_path, TASK_SPEC,
            claims=["- id: C-001\n  status: OPEN\n  answers_question: q1"],
            index_rows=["F-001 | PROVEN | C-001 | the answer"],
            fact_files={"F-001": FACT.format(
                fid="F-001", cid="C-001", qid="q1",
                conclusion="the answer body")},
        )
        verdict, _ = verdict_scorer.score_workspace(ws)
        entry = verdict["analysis_verdict"]["primary_questions"][0]
        assert entry["answered"] is False
        assert "not PROVEN" in entry["gap"]

    def test_no_answering_claim(self, tmp_path):
        ws = _ws(
            tmp_path, TASK_SPEC,
            claims=["- id: C-009\n  status: OPEN"],
            index_rows=None,
            fact_files=None,
        )
        verdict, _ = verdict_scorer.score_workspace(ws)
        av = verdict["analysis_verdict"]
        assert av["primary_questions"][0]["gap"] == "no answering claim"


class TestC0b:
    def test_model_selection_answered_when_candidates_closed(self, tmp_path):
        spec = TASK_SPEC + "    need: model_selection\n"
        ws = _ws(
            tmp_path, spec,
            claims=[
                "- id: C-001\n  status: PROVEN\n  answers_question: q1",
                "- id: C-002\n  status: REFUTED\n  answers_question: q1",
            ],
            index_rows=["F-001 | PROVEN | C-001 | picked candidate"],
            fact_files={"F-001": FACT.format(
                fid="F-001", cid="C-001", qid="q1",
                conclusion="picked candidate body")},
        )
        verdict, _ = verdict_scorer.score_workspace(ws)
        av = verdict["analysis_verdict"]
        assert av["complete"] is True
        assert av["primary_questions"][0]["answered"] is True

    def test_model_selection_open_candidate_fails(self, tmp_path):
        spec = TASK_SPEC + "    need: model_selection\n"
        ws = _ws(
            tmp_path, spec,
            claims=[
                "- id: C-001\n  status: PROVEN\n  answers_question: q1",
                "- id: C-002\n  status: OPEN\n  answers_question: q1",
            ],
            index_rows=["F-001 | PROVEN | C-001 | picked candidate"],
            fact_files={"F-001": FACT.format(
                fid="F-001", cid="C-001", qid="q1",
                conclusion="picked candidate body")},
        )
        verdict, _ = verdict_scorer.score_workspace(ws)
        av = verdict["analysis_verdict"]
        assert av["complete"] is False
        gap = av["primary_questions"][0]["gap"]
        assert "OPEN/PARTIAL" in gap
        assert "C-002" in gap


class TestReproduction:
    def test_repro_without_artifact_refused(self, tmp_path):
        spec = TASK_SPEC + "    reproduction: true\n"
        ws = _ws(
            tmp_path, spec,
            claims=["- id: C-001\n  status: PROVEN\n  answers_question: q1"],
            index_rows=["F-001 | PROVEN | C-001 | the answer"],
            fact_files={"F-001": FACT.format(
                fid="F-001", cid="C-001", qid="q1",
                conclusion="the answer body")},
        )
        verdict, _ = verdict_scorer.score_workspace(ws)
        entry = verdict["analysis_verdict"]["primary_questions"][0]
        assert entry["answered"] is False
        assert "ran without error is NOT evidence" in entry["gap"]

    def test_repro_with_valid_artifact_answered(self, tmp_path):
        spec = TASK_SPEC + "    reproduction: true\n"
        ws = _ws(
            tmp_path, spec,
            claims=["- id: C-001\n  status: PROVEN\n  answers_question: q1"],
            index_rows=["F-001 | PROVEN | C-001 | the answer"],
            fact_files={"F-001": FACT.format(
                fid="F-001", cid="C-001", qid="q1",
                conclusion="the answer body")},
            evidence={"replay-001.json": _replay_artifact()},
        )
        verdict, _ = verdict_scorer.score_workspace(ws)
        av = verdict["analysis_verdict"]
        assert av["complete"] is True
        assert av["primary_questions"][0]["answered"] is True


class TestContradiction:
    def test_conflict_forces_correct_false(self, tmp_path):
        ws = _ws(
            tmp_path, TASK_SPEC,
            claims=["- id: C-001\n  status: PROVEN\n  answers_question: q1"],
            index_rows=[
                "F-001 | PROVEN | C-001 | answer is five",
                "F-002 | PROVEN | C-001 | answer is seven",
            ],
            fact_files={
                "F-001": FACT.format(fid="F-001", cid="C-001", qid="q1",
                                     conclusion="answer is five"),
                "F-002": FACT.format(fid="F-002", cid="C-001", qid="q1",
                                     conclusion="answer is seven"),
            },
        )
        verdict, _ = verdict_scorer.score_workspace(ws)
        av = verdict["analysis_verdict"]
        assert av["correct"] is False
        assert av["contradictions"], "expected conflict rows"
        assert any("same-topic PROVEN contradiction" in c
                   for c in av["contradictions"])
        assert any("contradiction" in d["reason"] for d in av["degraded"])


class TestFailClosed:
    def test_blocked_missing_inputs(self, tmp_path):
        ws = tmp_path / "empty"
        ws.mkdir()
        verdict, err = verdict_scorer.score_workspace(ws)
        assert verdict is None
        assert "blocked" in err

    def test_malformed_pq_fails_closed(self, tmp_path):
        ws = _ws(
            tmp_path, "primary_questions:\n  - foo: a\n    baz: b\n",
            claims=["- id: C-001\n  status: OPEN"],
            index_rows=None,
        )
        verdict, err = verdict_scorer.score_workspace(ws)
        assert verdict is None
        assert "malformed" in err


class TestSchema:
    def test_schema_v11_shape(self, tmp_path):
        ws = _ws(
            tmp_path, TASK_SPEC,
            claims=["- id: C-001\n  status: PROVEN\n  answers_question: q1"],
            index_rows=["F-001 | PROVEN | C-001 | the answer"],
            fact_files={"F-001": FACT.format(
                fid="F-001", cid="C-001", qid="q1",
                conclusion="the answer body")},
        )
        verdict, _ = verdict_scorer.score_workspace(ws)
        assert verdict["_meta"]["source"] == "verdict-scorer"
        assert verdict["_meta"]["schema_version"] == "v11"
        assert set(verdict["analysis_verdict"]) == {
            "complete", "correct", "primary_questions", "unresolved",
            "contradictions", "degraded"}
        assert set(verdict["self_audit"]) == {
            "evidence_strength", "ignored_evidence", "open_questions"}

    def test_main_stdout(self, tmp_path, capsys):
        ws = _ws(
            tmp_path, TASK_SPEC,
            claims=["- id: C-001\n  status: PROVEN\n  answers_question: q1"],
            index_rows=["F-001 | PROVEN | C-001 | the answer"],
            fact_files={"F-001": FACT.format(
                fid="F-001", cid="C-001", qid="q1",
                conclusion="the answer body")},
        )
        rc = verdict_scorer.main([str(ws), "--stdout"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["analysis_verdict"]["complete"] is True

    def test_main_blocked_exit(self, tmp_path):
        ws = tmp_path / "empty"
        ws.mkdir()
        assert verdict_scorer.main([str(ws)]) == 2
