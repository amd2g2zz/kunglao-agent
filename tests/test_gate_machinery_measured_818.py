# -*- coding: utf-8 -*-
"""tests/test_gate_machinery_measured_818.py — the event taxonomy and
the coverage-floor ratchet, in the MEASURED leg (issue #818 coverage
climb).

Both modules' unit pins live in fast-tier files
(test_orchestration_event_taxonomy, test_coverage_floor_520) the CI
measured-set coverage leg does not execute. This file re-pins the
classification contract (every taxonomy class rides a REAL producer
row shape) and the ratchet file contract (load/validate/check/monotone
faces + every documented ValueError).
"""
from __future__ import annotations

import json
from pathlib import Path

import event_taxonomy as et  # noqa: E402  (scripts/ on pytest path)
import coverage_floor as cf  # noqa: E402

FLOOR = Path(__file__).resolve().parents[1] / "coverage-floor.json"


# ---------- the taxonomy classification ----------

def test_ledger_events_classify_through_both_word_fields() -> None:
    assert et.classify_event({"event_type": "fact_written"},
                             "ledger") == et.FACT_WRITTEN
    assert et.classify_event({"action": "fact_verified"},
                             "ledger") == et.FACT_VERIFIED
    # the event_type face wins when both are present
    assert et.classify_event({"event_type": "fact_written",
                              "action": "fact_verified"},
                             "ledger") == et.FACT_WRITTEN
    assert et.classify_event({"event_type": "unregistered-word"},
                             "ledger") is None
    assert et.classify_event({}, "ledger") is None


def test_convergence_rows_classify_by_type_and_result() -> None:
    assert et.classify_event({}, "convergence") == et.SNAPSHOT
    assert et.classify_event({"type": "snapshot"}, "convergence") \
        == et.SNAPSHOT
    assert et.classify_event({"type": "outcome", "result": "passes"},
                             "convergence") == et.OUTCOME_PASSED
    assert et.classify_event({"type": "outcome", "result": "CONFIRMED"},
                             "convergence") == et.OUTCOME_PASSED
    assert et.classify_event({"type": "outcome", "result": "partial"},
                             "convergence") == et.OUTCOME_PARTIAL
    assert et.classify_event({"type": "outcome", "result": "fails"},
                             "convergence") == et.OUTCOME_FAILED
    assert et.classify_event({"type": "outcome", "result": "refuted"},
                             "convergence") == et.OUTCOME_FAILED
    assert et.classify_event({"type": "outcome", "result": "shrug"},
                             "convergence") is None
    assert et.classify_event({"type": "operator_action"},
                             "convergence") == et.OPERATOR_ACTION
    assert et.classify_event({"type": "mystery"}, "convergence") is None
    assert et.classify_event({}, "unknown-source") is None


def test_worker_and_claim_status_maps() -> None:
    assert et.classify_worker_status("in-progress") == et.WORKER_STEP
    assert et.classify_worker_status("DONE") == et.WORKER_COMPLETED
    assert et.classify_worker_status("blocked") == et.WORKER_FAILED
    assert et.classify_worker_status("") is None
    assert et.classify_worker_status("waiting") is None
    assert et.classify_claim_status("proven") == et.CLAIM_PROMOTED
    assert et.classify_claim_status("refuted") == et.CLAIM_REFUTED
    assert et.classify_claim_status("PARTIALLY-VERIFIED") == \
        et.CLAIM_PARTIAL
    assert et.classify_claim_status("dead") == et.CLAIM_DEAD
    assert et.classify_claim_status("OPEN") is None


def test_taxonomy_words_are_registered_constants() -> None:
    # the 25-class taxonomy: every constant is a plain snake_case word
    for word in (et.FACT_WRITTEN, et.CLAIM_PROMOTED, et.SNAPSHOT,
                 et.OUTCOME_FAILED, et.WORKER_STEP, et.BLOCKER_OPENED):
        assert word and word == word.lower()


# ---------- classify_workspace on a real fixture workspace ----------

def test_classify_workspace_counts_real_rows(tmp_path) -> None:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "blockers").mkdir()
    (ws / "runs" / "logs").mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-1\n    status: PROVEN\n"
        "  - id: C-2\n    status: OPEN\n", encoding="utf-8")
    (ws / ".convergence_ledger.jsonl").write_text(
        json.dumps({"type": "snapshot"}) + "\n"
        + json.dumps({"type": "outcome", "result": "passes"}) + "\n",
        encoding="utf-8")
    from kunglao_log import emit
    emit(ws, actor="t", action="fact_written", claim="C-1")
    (ws / "blockers" / "B1.md").write_text(
        "premise broken\n", encoding="utf-8")
    counts = et.classify_workspace(ws)
    assert counts.get(et.SNAPSHOT) == 1
    assert counts.get(et.OUTCOME_PASSED) == 1
    assert counts.get(et.FACT_WRITTEN) == 1
    assert counts.get(et.CLAIM_PROMOTED) == 1
    assert counts.get(et.BLOCKER_OPENED) == 1
    # the statusline face reads the same counts
    line = et.statusline_json(ws)
    assert line and isinstance(line, dict)
    text = et.round_digest_text(ws)
    assert isinstance(text, str)


# ---------- the coverage-floor ratchet machinery ----------

def test_floor_file_contract_on_the_live_ratchet() -> None:
    data = cf.load_floor(FLOOR)   # raises ValueError on any violation
    assert data["schema"] == "coverage-floor/1"
    assert data["measured_set"] == ["scripts", "hooks"]
    assert float(data["min_floor"]) >= cf.TARGET_FLOOR
    assert cf.min_floor_target(FLOOR) == float(data["min_floor"])


def test_load_floor_documented_value_errors(tmp_path) -> None:
    def broken(**over) -> dict:
        doc = json.loads(FLOOR.read_text(encoding="utf-8"))
        doc.update(over)
        p = tmp_path / "floor.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        return p

    import pytest
    with pytest.raises(ValueError, match="schema must be"):
        cf.load_floor(broken(schema="other/9"))
    with pytest.raises(ValueError, match="missing key"):
        doc = json.loads(FLOOR.read_text(encoding="utf-8"))
        del doc["baseline_measured"]
        p = tmp_path / "missing.json"
        p.write_text(json.dumps(doc), encoding="utf-8")
        cf.load_floor(p)
    with pytest.raises(ValueError, match="must be positive"):
        cf.load_floor(broken(floor=-1))
    with pytest.raises(ValueError, match="silent bar-drop"):
        cf.load_floor(broken(floor=10.0))
    with pytest.raises(ValueError, match="never trails"):
        cf.load_floor(broken(min_floor=10.0))
    with pytest.raises(ValueError, match="measured_set"):
        cf.load_floor(broken(measured_set=["scripts"]))


def test_check_and_monotone_cmd_faces(tmp_path, capsys) -> None:
    # the check face: below floor -> rc 2, above floor -> rc 0 with the
    # climb-pending note naming the target
    cov = tmp_path / "cov.json"
    cov.write_text(json.dumps({"totals": {"percent_covered": 40.0}}),
                   encoding="utf-8")
    assert cf.main(["check", "--coverage-json", str(cov),
                    "--floor-file", str(FLOOR)]) == 2
    cov.write_text(json.dumps({"totals": {"percent_covered": 99.0}}),
                   encoding="utf-8")
    assert cf.main(["check", "--coverage-json", str(cov),
                    "--floor-file", str(FLOOR)]) == 0
    out = capsys.readouterr().out
    # the climb note keys on floor vs target (57 < 70): it rides even a
    # passing measurement; the surplus names the ratchet opportunity
    assert "measured=99.00%" in out
    assert "climb pending: target=70.00%" in out
    assert "ratchet opportunity" in out
    # a missing coverage json is a contract error (rc 3), never a crash
    assert cf.main(["check", "--coverage-json",
                    str(tmp_path / "void.json"),
                    "--floor-file", str(FLOOR)]) == 3


def test_monotone_cmd_faces(tmp_path) -> None:
    repo = Path(__file__).resolve().parents[1]
    # the live branch floor: never below the base branch's floor
    assert cf.main(["monotone", "--base-ref", "origin/dev",
                    "--repo", str(repo), "--floor-file", str(FLOOR)]) == 0
    # a base ref with no ratchet file: first landing, vacuously monotone
    assert cf.main(["monotone", "--base-ref", "does-not-exist-ref",
                    "--repo", str(repo), "--floor-file", str(FLOOR)]) == 0
    assert cf.floor_from_git(repo, "origin/dev") == 57.0
    import pytest
    with pytest.raises(ValueError, match="no coverage-floor.json"):
        cf.floor_from_git(repo, "does-not-exist-ref")
