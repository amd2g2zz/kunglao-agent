# -*- coding: utf-8 -*-
"""tests/test_eval_checker_snake_delegate_888.py — unit-entrypoint grading (#888).

The tf-snake units carry a unit-local ground-truth schema (snake-gt/2)
and grade through their own checker.py entrypoint (the checker drives
the GUI-only game with the candidate trainer and grades the game's own
run record). Before #888 the shared schema gate REFUSED every tf-snake
row at load time — the 2026-10-28 loop-v2 incident burned a full real
session (5400s wall, 9 dispatches, 3 PROVEN claims) and then refused to
grade it (BAD_TASK). Faces pinned here:

  (a) GATE — the schema gate is family-aware: unit-entrypoint families
      accept their unit-local ground-truth schema; every other family
      keeps the strict kunglao-eval-ground-truth gate;
  (b) TRANSLATION — a unit PASS/FAIL doc translates into the shared
      stream (VERDICT, FAILURE rows, METRIC lines, evidence archive)
      with honest ttc/dispatch metrics;
  (c) FAIL-CLOSED — checker-side faults (non-enum rc, non-JSON output,
      verdict/rc disagreement, missing entrypoint, harness-cap hang)
      are REFUSED rows, never candidate FAILs: a broken grader grades
      nothing;
  (d) ISOLATION — the shared faces (static/replay/arithmetic) never run
      for a unit-entrypoint family: the replay face would probe a
      snake-gt document for pair fields it does not carry, and the
      arithmetic verdict must not overwrite the unit's own verdict.

Stub unit checkers stand in for the real tf-snake checker.py (the real
checker launches the GUI game — never from tests); the delegation face
under test is exactly what the real checker plugs into (one
kunglao-eval-checker/1 JSON doc on stdout, rc 0/1).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import eval_checker as chk

TASK_YAML = """\
schema: kunglao-eval-task/1
task_id: stub-snake-v1
eval_version: eval-v1
tier: smoke
source: constructed
family: {family}
seed: 7
material_class: black-box
anchors:
  goal_verbatim: "produce a trainer for the protected snake game"
  success_criterion: "checker PASS on the game's own run record"
  verification_method: reproduction
workspace_scaffold:
  language: python
  files:
  - target/README.txt
  entry: target/README.txt
  candidate_contract: "ONE runnable trainer file at runs/deliverables/candidate"
checker:
  kind: replay-roundtrip
  oracles: [replay-roundtrip]
  entrypoint: checker.py
  metrics: [ttc_seconds, dispatch_count, pass_at_k_contribution, converged]
  thresholds:
    min_pair_ratio: 1.0
ground_truth:
  file: ground_truth.json
  space_bits: 128
contamination:
  held_out: true
  distiller_excluded: true
  provenance: constructed
"""

PASS_DOC = {"schema": "kunglao-eval-checker/1", "verdict": "PASS",
            "failures": [], "faces": {"score": True, "proof": True}}
FAIL_DOC = {"schema": "kunglao-eval-checker/1", "verdict": "FAIL",
            "failures": [{"code": "FACE_FAIL", "detail": "score"}],
            "faces": {"score": False}}


def _make_unit(tmp_path: Path, *, family: str = "tf-snake",
               checker_body: str | None = None,
               gt_schema: str = "snake-gt/2",
               with_entrypoint: bool = True) -> Path:
    unit = tmp_path / "stub-snake-v1"
    (unit / "target").mkdir(parents=True)
    (unit / "target" / "README.txt").write_text("stub\n", encoding="utf-8")
    (unit / "task.yaml").write_text(
        TASK_YAML.format(family=family), encoding="utf-8")
    (unit / "ground_truth.json").write_text(
        json.dumps({"schema": gt_schema, "require": {}}), encoding="utf-8")
    if with_entrypoint:
        body = checker_body or (
            "import json, sys\n"
            # repr() embeds PYTHON literals (True/False) — json.dumps()
            # would emit JSON booleans into Python source (NameError)
            f"print(json.dumps({PASS_DOC!r}))\n")
        (unit / "checker.py").write_text(body, encoding="utf-8")
    return unit


def _make_candidate(tmp_path: Path) -> Path:
    cand = tmp_path / "candidate"
    cand.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    cand.chmod(0o755)
    return cand


def _checker_body(doc: dict, *, rc: int | None = None,
                  raw: str | None = None,
                  sleep: float | None = None) -> str:
    lines = ["import json, sys, time"]
    if sleep is not None:
        lines.append(f"time.sleep({sleep})")
    if raw is not None:
        lines.append(f"print({raw!r})")
    else:
        lines.append(f"print(json.dumps({doc!r}))")
    lines.append(f"sys.exit({rc if rc is not None else 0})")
    return "\n".join(lines) + "\n"


# ---- (a) gate ------------------------------------------------------------

def test_unit_entrypoint_family_accepts_snake_gt_schema(tmp_path):
    unit = _make_unit(tmp_path)
    tdir, task, gt = chk.load_unit(str(unit))
    assert gt["schema"] == "snake-gt/2"
    assert task["family"] == "tf-snake"


def test_standard_family_keeps_the_strict_schema_gate(tmp_path):
    unit = _make_unit(tmp_path, family="tf-hardwall-ledger")
    with pytest.raises(chk.Refusal) as exc:
        chk.load_unit(str(unit))
    assert exc.value.code == "BAD_TASK"
    assert "snake-gt/2" in exc.value.detail


# ---- (b) translation ------------------------------------------------------

def test_pass_doc_translates_to_pass_row(tmp_path):
    unit = _make_unit(tmp_path)
    cand = _make_candidate(tmp_path)
    out = tmp_path / "out"
    rc, ev = chk.run(str(unit), cand, out)
    assert rc == chk.RC_PASS
    assert ev["verdict"] == "PASS"
    assert ev["faces"]["unit-entrypoint"]["rc"] == 0
    assert ev["metrics"]["dispatch_count"] == 1
    assert ev["metrics"]["pass_at_k_contribution"] == 1
    assert ev["metrics"]["converged"] == 1
    assert ev["metrics"]["ttc_seconds"] > 0
    evidence_files = list(out.glob("evidence-*.json"))
    assert len(evidence_files) == 1


def test_fail_doc_translates_with_its_failures(tmp_path):
    unit = _make_unit(tmp_path, checker_body=_checker_body(FAIL_DOC, rc=1))
    cand = _make_candidate(tmp_path)
    rc, ev = chk.run(str(unit), cand, tmp_path / "out")
    assert rc == chk.RC_FAIL
    assert ev["verdict"] == "FAIL"
    assert ev["failures"] == FAIL_DOC["failures"]
    assert ev["metrics"]["pass_at_k_contribution"] == 0


def test_cli_stream_carries_the_verdict_line(tmp_path):
    unit = _make_unit(tmp_path)
    cand = _make_candidate(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(Path(chk.__file__)),
         "--task", str(unit), "--candidate", str(cand),
         "--out", str(tmp_path / "out")],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0
    assert "VERDICT PASS" in proc.stdout
    assert "METRIC dispatch_count=1" in proc.stdout


# ---- (c) fail-closed -------------------------------------------------------

def test_checker_crash_is_refused_not_failed(tmp_path):
    unit = _make_unit(tmp_path,
                      checker_body=_checker_body(FAIL_DOC, rc=3))
    cand = _make_candidate(tmp_path)
    with pytest.raises(chk.Refusal) as exc:
        chk.run(str(unit), cand, tmp_path / "out")
    assert exc.value.code == "CHECKER_FAULT"


def test_non_json_output_is_refused(tmp_path):
    unit = _make_unit(tmp_path,
                      checker_body=_checker_body(FAIL_DOC, rc=1,
                                                 raw="<html>boom</html>"))
    cand = _make_candidate(tmp_path)
    with pytest.raises(chk.Refusal) as exc:
        chk.run(str(unit), cand, tmp_path / "out")
    assert exc.value.code == "CHECKER_FAULT"


def test_verdict_rc_disagreement_is_refused(tmp_path):
    unit = _make_unit(tmp_path, checker_body=_checker_body(PASS_DOC, rc=1))
    cand = _make_candidate(tmp_path)
    with pytest.raises(chk.Refusal) as exc:
        chk.run(str(unit), cand, tmp_path / "out")
    assert exc.value.code == "CHECKER_FAULT"
    assert "disagree" in exc.value.detail


def test_missing_entrypoint_is_bad_task(tmp_path):
    unit = _make_unit(tmp_path, with_entrypoint=False)
    cand = _make_candidate(tmp_path)
    with pytest.raises(chk.Refusal) as exc:
        chk.run(str(unit), cand, tmp_path / "out")
    assert exc.value.code == "BAD_TASK"


def test_harness_cap_hang_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(chk, "_UNIT_EP_TIMEOUT_S", 0.5)
    unit = _make_unit(tmp_path,
                      checker_body=_checker_body(PASS_DOC, sleep=3))
    cand = _make_candidate(tmp_path)
    with pytest.raises(chk.Refusal) as exc:
        chk.run(str(unit), cand, tmp_path / "out")
    assert exc.value.code == "CHECKER_TIMEOUT"


# ---- review-round fixes ----------------------------------------------------

BAD_ROW_DOC = {"schema": "kunglao-eval-checker/1", "verdict": "FAIL",
               "failures": [{"code": "FACE_FAIL"}], "faces": {}}


def test_malformed_failure_rows_are_refused(tmp_path):
    unit = _make_unit(tmp_path, checker_body=_checker_body(BAD_ROW_DOC,
                                                           rc=1))
    cand = _make_candidate(tmp_path)
    with pytest.raises(chk.Refusal) as exc:
        chk.run(str(unit), cand, tmp_path / "out")
    assert exc.value.code == "CHECKER_FAULT"
    assert "malformed" in exc.value.detail


def test_wrong_doc_schema_is_refused(tmp_path):
    doc = dict(PASS_DOC, schema="kunglao-eval-checker/9")
    unit = _make_unit(tmp_path, checker_body=_checker_body(doc))
    cand = _make_candidate(tmp_path)
    with pytest.raises(chk.Refusal) as exc:
        chk.run(str(unit), cand, tmp_path / "out")
    assert exc.value.code == "CHECKER_FAULT"


def test_standard_family_still_grades_through_the_shared_ladder(tmp_path):
    """The 2026-11-01 review round: the verdict-ladder extraction left
    run()'s standard path reading an unbound `verdict` — every
    non-unit-entrypoint family crashed with UnboundLocalError, and the
    rc-1 traceback mapped to a candidate FAIL. Pinned: a standard
    constant-hit unit grades through the shared arithmetic to PASS."""
    unit = tmp_path / "stub-std-v1"
    (unit / "target").mkdir(parents=True)
    (unit / "target" / "README.txt").write_text("stub\n", encoding="utf-8")
    (unit / "task.yaml").write_text(
        TASK_YAML.format(family="tf-hardwall-ledger")
        .replace("stub-snake-v1", "stub-std-v1")
        .replace("kind: replay-roundtrip", "kind: constant-hit")
        .replace("oracles: [replay-roundtrip]", "oracles: [constant-hit]")
        .replace("thresholds:\n    min_pair_ratio: 1.0",
                 "thresholds:\n    min_constant_hits: 1")
        .replace('file: ground_truth.json\n  space_bits: 128',
                 'file: ground_truth.json\n  space_bits: 32'),
        encoding="utf-8")
    (unit / "ground_truth.json").write_text(
        json.dumps({"schema": "kunglao-eval-ground-truth/1",
                    "constants": {"gold": 3735928559}}), encoding="utf-8")
    (unit / "checker.py").write_text(
        "raise AssertionError('the shared face must not delegate "
        "a standard family to the unit entrypoint')\n", encoding="utf-8")
    cand = tmp_path / "candidate.txt"
    cand.write_text("the answer embeds 0xdeadbeef\n", encoding="utf-8")
    rc, ev = chk.run(str(unit), cand, tmp_path / "out")
    assert rc == chk.RC_PASS
    assert ev["verdict"] == "PASS"
    assert ev["faces"]["static"]["hits"] == 1


# ---- (d) isolation ---------------------------------------------------------

def test_replay_face_never_probes_a_snake_gt_document(tmp_path):
    """replay-roundtrip IS in the tf-snake oracle list; without the
    unit_graded guard the standard replay face would run against a
    snake-gt document and crash on its missing pair fields."""
    import eval_dataset as ds
    unit = _make_unit(tmp_path)
    task = ds.load_task(unit)
    oracles = task["checker"]["oracles"]
    assert "replay-roundtrip" in oracles
    cand = _make_candidate(tmp_path)
    rc, ev = chk.run(str(unit), cand, tmp_path / "out")
    assert rc == chk.RC_PASS
    assert "replay" not in ev["faces"]
