# -*- coding: utf-8 -*-
"""Credit attribution of terminal claims, and per-file oracle case errors.

Settlement keys its credit on a committed dispatch-ledger row. A terminal
claim without one is told apart from the persisted data, never guessed:

  - no dispatch attempt ever touched it     -> ``not_dispatched`` (nothing owed)
  - an attempt exists, none was committed   -> ``uncredited`` plus one durable
    ``credit_unattributable`` event (deduplicated across settlement passes)

The oracle runner reports each broken case file on its own (``case_errors``),
and the convergence decision carries them as ``oracle_case_errors`` — only
when there are some — with one ``oracle_case_error`` event per distinct
error fingerprint. Fixtures are synthetic.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

import claims_store
import convergence_check as cc
import event_taxonomy
import kunglao_log
import oracle_runner as orun
import settle_round_credit as src
import test_decide_regression_anchor as anchor
from _dispatch_fixture import mint_dispatches
from rlvr import production_terminal, q_cells
from test_oracle_runner_108 import CASE_BLIND, CASE_GOOD, _mk_ws
from test_production_terminal_1005 import terminal_workspace


# ------------------------------------------------------------------ helpers

def _settle_ws(tmp_path: Path, claims: list[dict]) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}), encoding="utf-8")
    return ws


def _append_raw(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)


def _append(path: Path, row: dict) -> None:
    _append_raw(path, json.dumps(row) + "\n")


def _events(ws: Path, action: str) -> list[dict]:
    rows = []
    for day in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        for line in day.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("action") == action:
                rows.append(row)
    return rows


@pytest.fixture
def warned(monkeypatch) -> list[str]:
    seen: list[str] = []
    monkeypatch.setattr(src, "warn",
                        lambda op, reason, **_kw: seen.append(f"{op}: {reason}"))
    return seen


def _trace_register(ws: Path, cid: str) -> None:
    doc = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    for claim in doc["claims"]:
        if claim["id"] == cid:
            claim["dispatch_count"] = 2
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")


def _trace_ledger(ws: Path, cid: str) -> None:
    _append(ws / "runs" / "dispatch-ledger.jsonl",
            {"schema": "dispatch-ledger/1", "dispatch_id": "d1", "claim": cid,
             "state": "failed", "actor": "hook:worker_budget"})


def _trace_experience(ws: Path, cid: str) -> None:
    out = q_cells.record_dispatch_observation(
        ws, "dispatch envelope",
        envelope_meta={"method_family": "static-symbolic"},
        claim=cid, agent="w-test")
    assert out["appended"] is True


def _trace_q_cell_log(ws: Path, cid: str) -> None:
    _append(ws / "runs" / "q-cell-log.jsonl",
            {"schema": "q-cell-obs/1", "source": "dispatch", "claim": cid,
             "method_family": "red-team-verification", "dispatch_id": None})


def _trace_provenance(ws: Path, cid: str) -> None:
    _append(ws / "runs" / "claims-provenance.jsonl",
            {"schema": "claims-provenance/1", "claim": cid, "event": "dispatch",
             "outcome": "failed", "reason": "step-register-failed",
             "journal": "j1"})


TRACES = {
    "register": _trace_register,
    "ledger": _trace_ledger,
    "experience": _trace_experience,
    "q_cell_log": _trace_q_cell_log,
    "provenance": _trace_provenance,
}


# ------------------------------------------------- credit attribution (run)

def test_never_dispatched_terminal_claim_is_reported_quietly(tmp_path, warned):
    ws = _settle_ws(tmp_path, [{"id": "C-1", "status": "PROVEN"}])
    out = src.run(ws)
    assert out["not_dispatched"] == ["C-1"]
    assert "uncredited" not in out and "off_ledger" not in out
    assert _events(ws, "credit_unattributable") == []
    assert not [w for w in warned if "C-1" in w or "dispatch-ledger" in w]


@pytest.mark.parametrize("source", sorted(TRACES))
def test_attempted_but_uncommitted_claim_is_uncredited_with_one_event(
        tmp_path, warned, source):
    ws = _settle_ws(tmp_path, [{"id": "C-2", "status": "PROVEN"}])
    TRACES[source](ws, "C-2")
    first = src.run(ws)
    second = src.run(ws)
    assert first["uncredited"] == ["C-2"] and second["uncredited"] == ["C-2"]
    assert "not_dispatched" not in first and "off_ledger" not in first
    rows = _events(ws, "credit_unattributable")
    assert len(rows) == 1, "settlement re-runs must not repeat the row"
    assert rows[0]["claim"] == "C-2"
    detail = json.loads(rows[0]["detail"])
    assert detail["claim"] == "C-2" and detail["reason"]
    assert detail["sources"] == [source]
    assert not [w for w in warned if "dispatch-ledger" in w]


def test_aborted_dispatch_through_the_real_api_is_uncredited(tmp_path):
    ws = _settle_ws(tmp_path, [{"id": "C-2", "status": "OPEN"}])
    began = claims_store.begin_dispatch(
        ws, "C-2", "hook:worker_budget", tier=1, prompt="fixture",
        agent="w-test", method_family="static_recovery")
    assert began.ok
    assert claims_store.abort_dispatch(ws, "C-2", "hook:worker_budget").ok
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-2", "status": "PROVEN"}]}),
        encoding="utf-8")
    out = src.run(ws)
    assert out["uncredited"] == ["C-2"]
    detail = json.loads(_events(ws, "credit_unattributable")[0]["detail"])
    assert detail["sources"] == ["ledger", "provenance"]


def test_dedup_survives_day_log_removal(tmp_path):
    ws = _settle_ws(tmp_path, [{"id": "C-2", "status": "PROVEN"}])
    _trace_register(ws, "C-2")
    src.run(ws)
    assert len(_events(ws, "credit_unattributable")) == 1
    for day in (ws / "runs" / "logs").glob("kunglao-*.jsonl"):
        day.unlink()
    src.run(ws)
    assert _events(ws, "credit_unattributable") == []


def test_dry_run_classifies_without_writing(tmp_path):
    ws = _settle_ws(tmp_path, [{"id": "C-1", "status": "PROVEN"},
                               {"id": "C-2", "status": "PROVEN"}])
    _trace_register(ws, "C-2")
    out = src.run(ws, dry_run=True)
    assert out["not_dispatched"] == ["C-1"] and out["uncredited"] == ["C-2"]
    assert not (ws / kunglao_log.EMIT_ONCE_REL).exists()
    assert _events(ws, "credit_unattributable") == []


def test_reason_does_not_claim_there_are_no_terminal_claims_when_all_were_skipped(
        tmp_path):
    ws = _settle_ws(tmp_path, [{"id": "C-1", "status": "PROVEN"},
                               {"id": "C-2", "status": "PROVEN"}])
    _trace_register(ws, "C-2")
    out = src.run(ws)
    assert out["settled"] == 0
    assert "committed dispatch" in out["reason"]
    assert "nothing to settle" in out["reason"]
    empty = src.run(_settle_ws(tmp_path / "empty", []))
    assert empty["reason"] == "no terminal claims - nothing to settle"


def test_committed_dispatch_claims_are_in_neither_list(tmp_path):
    claims = [{"id": "C-1", "status": "PROVEN"},
              {"id": "C-2", "status": "PROVEN"},
              {"id": "C-3", "status": "PROVEN"}]
    ws = _settle_ws(tmp_path, claims)
    mint_dispatches(ws, [claims[2]], pending=False)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}), encoding="utf-8")
    _trace_register(ws, "C-2")
    out = src.run(ws)
    assert out["not_dispatched"] == ["C-1"]
    assert out["uncredited"] == ["C-2"]
    assert out["rounds"] == 1


def test_dispatch_attempts_unions_every_trace_source(tmp_path):
    ws = _settle_ws(tmp_path, [{"id": "C-A", "status": "PROVEN"},
                               {"id": "C-B", "status": "PROVEN"},
                               {"id": "C-C", "status": "PROVEN"},
                               {"id": "C-D", "status": "PROVEN"}])
    _trace_register(ws, "C-A")
    _trace_ledger(ws, "C-B")
    _trace_provenance(ws, "C-B")
    _trace_experience(ws, "C-C")
    _trace_q_cell_log(ws, "C-C")
    _append_raw(ws / "runs" / "dispatch-ledger.jsonl", "not json\n[1]\n")
    _append_raw(ws / "runs" / "q-cell-log.jsonl", "\n{broken\n")
    assert claims_store.dispatch_attempts(ws) == {
        "C-A": ["register"],
        "C-B": ["ledger", "provenance"],
        "C-C": ["experience", "q_cell_log"],
    }


def test_dispatch_attempts_on_a_bare_workspace_is_empty(tmp_path):
    assert claims_store.dispatch_attempts(tmp_path / "missing") == {}


def test_dispatch_attempts_survives_an_unreadable_register(tmp_path, capsys):
    ws = _settle_ws(tmp_path, [{"id": "C-A", "status": "PROVEN"}])
    _trace_ledger(ws, "C-A")
    (ws / "claim-register.yaml").write_text("claims: [unclosed\n",
                                            encoding="utf-8")
    assert claims_store.dispatch_attempts(ws) == {"C-A": ["ledger"]}
    assert "register read failed" in capsys.readouterr().err


@pytest.mark.skipif(not hasattr(os, "geteuid") or os.geteuid() == 0,
                    reason="file permissions are not enforced for root")
def test_dispatch_attempts_survives_an_unreadable_trace_file(tmp_path, capsys):
    ws = _settle_ws(tmp_path, [{"id": "C-A", "status": "PROVEN"}])
    _trace_register(ws, "C-A")
    _trace_provenance(ws, "C-B")
    log = ws / "runs" / "claims-provenance.jsonl"
    log.chmod(0)
    try:
        assert claims_store.dispatch_attempts(ws) == {"C-A": ["register"]}
    finally:
        log.chmod(0o600)
    assert "claims-provenance.jsonl read failed" in capsys.readouterr().err


def _dirty_trace(source: str, ws: Path, claim) -> None:
    """Append one trace row carrying a deliberately unusable claim value."""
    if source == "register":
        doc = yaml.safe_load(
            (ws / "claim-register.yaml").read_text(encoding="utf-8"))
        doc["claims"].append({"id": claim, "dispatch_count": 5})
        (ws / "claim-register.yaml").write_text(yaml.safe_dump(doc),
                                               encoding="utf-8")
    elif source == "ledger":
        _append(ws / "runs" / "dispatch-ledger.jsonl",
                {"schema": "dispatch-ledger/1", "dispatch_id": "d1",
                 "claim": claim, "state": "failed", "actor": "w"})
    elif source == "experience":
        _append(ws / "runs" / "experience.jsonl",
                {"schema": "q-cell-obs/1", "source": "dispatch",
                 "claim": claim, "method_family": "static-symbolic"})
    elif source == "q_cell_log":
        _append(ws / "runs" / "q-cell-log.jsonl",
                {"schema": "q-cell-obs/1", "source": "dispatch",
                 "claim": claim, "method_family": "red-team-verification"})
    elif source == "provenance":
        _append(ws / "runs" / "claims-provenance.jsonl",
                {"schema": "claims-provenance/1", "claim": claim,
                 "event": "dispatch", "outcome": "failed", "journal": "j1"})
    else:
        raise AssertionError(f"unknown trace source: {source}")


DIRTY_CLAIMS = [
    pytest.param(["a"], id="list"),
    pytest.param({"x": 1}, id="dict"),
    pytest.param("not a claim!", id="nonconforming-text"),
    pytest.param("", id="empty"),
    pytest.param("  ", id="whitespace"),
    pytest.param(" C-1! ", id="strip-then-nonconforming"),
    pytest.param(True, id="bool"),
    pytest.param(42, id="int"),
    pytest.param(None, id="none"),
    pytest.param("['a']", id="literal-bracket-text"),
]


@pytest.mark.parametrize("dirty", DIRTY_CLAIMS)
@pytest.mark.parametrize("source", sorted(TRACES))
def test_dirty_claim_rows_are_skipped_not_stringified(
        tmp_path, source, dirty):
    """A trace row whose claim value is not a usable id must never mint a
    phantom key, whichever of the five sources it lands in."""
    ws = _settle_ws(tmp_path, [{"id": "C-REAL", "status": "PROVEN"}])
    _trace_register(ws, "C-REAL")
    _dirty_trace(source, ws, dirty)
    assert claims_store.dispatch_attempts(ws) == {"C-REAL": ["register"]}


@pytest.mark.parametrize("dirty", [["a"], {"x": 1}, "not a claim!"])
def test_dirty_rows_never_affect_the_real_claims_classification(
        tmp_path, dirty):
    """A dirty row in one source must not perturb a real claim's
    classification through another."""
    ws = _settle_ws(tmp_path, [{"id": "C-REAL", "status": "PROVEN"}])
    _trace_ledger(ws, "C-REAL")
    _dirty_trace("provenance", ws, dirty)
    assert claims_store.dispatch_attempts(ws) == {"C-REAL": ["ledger"]}


def test_well_formed_scalar_still_classifies_uncredited(tmp_path):
    """Regression: a normal scalar claim id is still detected as an
    attempt through every trace source."""
    for source in sorted(TRACES):
        ws = _settle_ws(tmp_path / source, [{"id": "C-2", "status": "PROVEN"}])
        TRACES[source](ws, "C-2")
        assert claims_store.dispatch_attempts(ws) == {"C-2": [source]}
        out = src.run(ws)
        assert out["uncredited"] == ["C-2"], source


def test_mixed_dirty_and_real_rows_across_sources(tmp_path):
    """Dirty rows across several sources plus one real row yield exactly
    the real claim, with the real trace kinds."""
    ws = _settle_ws(tmp_path, [{"id": "C-2", "status": "PROVEN"}])
    _trace_ledger(ws, "C-2")
    _trace_provenance(ws, "C-2")
    _dirty_trace("ledger", ws, ["phantom"])
    _dirty_trace("q_cell_log", ws, {"phantom": 1})
    _dirty_trace("provenance", ws, "not a claim!")
    assert claims_store.dispatch_attempts(ws) == {
        "C-2": ["ledger", "provenance"]}


# --------------------------------------------------------- settle_stop face

def test_settle_stop_still_completes_and_records_uncredited(tmp_path):
    ws = terminal_workspace(tmp_path)
    doc = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    doc["claims"][0]["dispatch_count"] = 1
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")

    result = production_terminal.settle_stop(ws)
    assert result["status"] == "completed"
    record = json.loads(
        (ws / "runs" / "production-terminal.json").read_text(encoding="utf-8"))
    assert record["status"] == "completed"
    assert record["uncredited"] == ["C-001"]
    spans = production_terminal.inspect(ws)["spans"]
    done = next(r for r in spans if r["gen_ai.operation.name"] == "settlement"
                and r["event"] == "completed")
    assert done["uncredited"] == ["C-001"]
    assert len(_events(ws, "credit_unattributable")) == 1

    assert production_terminal.settle_stop(ws)["status"] == "completed"
    assert len(_events(ws, "credit_unattributable")) == 1


def test_settle_stop_records_an_empty_uncredited_list_when_none(tmp_path):
    ws = terminal_workspace(tmp_path)
    assert production_terminal.settle_stop(ws)["status"] == "completed"
    record = json.loads(
        (ws / "runs" / "production-terminal.json").read_text(encoding="utf-8"))
    assert record["uncredited"] == []
    done = next(r for r in production_terminal.inspect(ws)["spans"]
                if r["gen_ai.operation.name"] == "settlement"
                and r["event"] == "completed")
    assert "uncredited" not in done


# ------------------------------------------------------- emit_once (log face)

def test_emit_once_appends_a_row_once_per_action_and_key(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert kunglao_log.emit_once(ws, "orchestrator", "credit_unattributable",
                                 "k1", claim="C-1", detail="d") is True
    assert kunglao_log.emit_once(ws, "orchestrator", "credit_unattributable",
                                 "k1", claim="C-1", detail="d") is False
    assert kunglao_log.emit_once(ws, "orchestrator", "credit_unattributable",
                                 "k2", claim="C-2") is True
    assert kunglao_log.emit_once(ws, "orchestrator", "oracle_case_error",
                                 "k1") is True
    assert len(_events(ws, "credit_unattributable")) == 2
    assert len(_events(ws, "oracle_case_error")) == 1


def test_emit_once_does_not_record_a_row_that_never_landed(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    real_emit = kunglao_log.emit
    monkeypatch.setattr(kunglao_log, "emit", lambda *a, **k: False)
    assert kunglao_log.emit_once(ws, "orchestrator", "oracle_case_error",
                                 "k1") is False
    monkeypatch.setattr(kunglao_log, "emit", real_emit)
    assert kunglao_log.emit_once(ws, "orchestrator", "oracle_case_error",
                                 "k1") is True


def test_emit_once_reads_a_corrupt_state_file_as_empty_and_heals_it(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    state = ws / kunglao_log.EMIT_ONCE_REL
    state.write_text("{not json", encoding="utf-8")
    assert kunglao_log.emit_once(ws, "orchestrator", "oracle_case_error",
                                 "k1") is True
    assert json.loads(state.read_text(encoding="utf-8")) == {
        "oracle_case_error": ["k1"]}
    assert kunglao_log.emit_once(ws, "orchestrator", "oracle_case_error",
                                 "k1") is False


@pytest.mark.parametrize("state", ["[1, 2]", '{"a": "not-a-list"}', ""])
def test_emit_once_reads_an_ill_shaped_state_file_as_empty(tmp_path, state):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / kunglao_log.EMIT_ONCE_REL).write_text(state, encoding="utf-8")
    assert kunglao_log.emit_once(ws, "orchestrator", "oracle_case_error",
                                 "k1") is True
    assert len(_events(ws, "oracle_case_error")) == 1


def test_new_event_actions_are_registered():
    words = event_taxonomy.EMIT_ACTIONS
    assert "credit_unattributable" in words and "oracle_case_error" in words
    assert list(words) == sorted(set(words))


# ------------------------------------------------- oracle case_errors (read)

def _with(case: dict, **overrides) -> dict:
    return {**case, **overrides}


DEFECTS = [
    ("expected_mapping",
     {"expected": {"evidence_refs": ["F001"]}}, "expected"),
    ("expected_without_anchor",
     {"expected": [{"field": "auth_algo", "value": "x"}]}, "expected"),
    ("expected_ref_unresolved",
     {"expected": [{"field": "auth_algo", "value": "x",
                    "evidence_refs": ["F404"]}]}, "expected"),
    ("mutations_empty", {"mutations": []}, "mutations"),
    ("mutation_without_field",
     {"mutations": [{"kind": "omit", "target": "F001"}]}, "mutations"),
    ("channel_missing", {"channel": ""}, "channel"),
    ("hypothesis_unresolved", {"hypothesis_ref": "H-404"}, "hypothesis_ref"),
    ("update_map_missing", {"update_map": None}, "update_map"),
    ("update_map_foreign_id",
     {"update_map": {"green_up": ["H-999"], "red_up": []}}, "update_map"),
    ("stages_not_mapping", {"stages": ["a"]}, "stages"),
    ("verification_missing", {"verification": None}, "verification"),
]


@pytest.mark.parametrize("name,overrides,field",
                         DEFECTS, ids=[d[0] for d in DEFECTS])
def test_case_errors_match_the_first_load_cases_refusal(
        tmp_path, name, overrides, field):
    ws = _mk_ws(tmp_path, [_with(CASE_GOOD, **overrides)], None)
    cases_dir = ws / "oracle" / "cases"
    with pytest.raises(orun.OracleCaseError) as refusal:
        orun.load_cases(cases_dir)
    errors = orun.case_errors(cases_dir)
    assert len(errors) == 1
    row = errors[0]
    assert set(row) == {"file", "case", "error", "field", "fix"}
    assert row["file"] == "case-00.yaml" and row["case"] == "auth-fields"
    assert row["error"] == str(refusal.value)
    assert row["field"] == refusal.value.field == field
    assert isinstance(row["fix"], str) and row["fix"] and "\n" not in row["fix"]


def test_case_errors_name_the_mapping_shaped_expected_field(tmp_path):
    case = _with(CASE_GOOD, expected={"evidence_refs": ["F001"]})
    ws = _mk_ws(tmp_path, [case], None)
    (row,) = orun.case_errors(ws / "oracle" / "cases")
    assert row["file"] == "case-00.yaml"
    assert row["case"] == "auth-fields"
    assert row["field"] == "expected"
    assert "`expected`" in row["error"]
    assert "list" in row["fix"]


def test_case_errors_report_each_broken_file_on_its_own(tmp_path):
    ws = _mk_ws(tmp_path, [], None)
    cases_dir = ws / "oracle" / "cases"
    (cases_dir / "a-bad-expected.yaml").write_text(yaml.safe_dump(
        _with(CASE_GOOD, id="a", expected={"evidence_refs": ["F001"]})),
        encoding="utf-8")
    (cases_dir / "b-valid.yaml").write_text(
        yaml.safe_dump(CASE_BLIND), encoding="utf-8")
    (cases_dir / "c-not-a-mapping.yaml").write_text("- one\n- two\n",
                                                     encoding="utf-8")
    (cases_dir / "d-broken-yaml.yaml").write_text("key: [unclosed\n",
                                                   encoding="utf-8")
    errors = orun.case_errors(cases_dir)
    assert [(e["file"], e["case"], e["field"]) for e in errors] == [
        ("a-bad-expected.yaml", "a", "expected"),
        ("c-not-a-mapping.yaml", None, None),
        ("d-broken-yaml.yaml", None, None),
    ]
    assert "not a mapping" in errors[1]["error"]
    assert errors[2]["error"].startswith("d-broken-yaml.yaml:")
    assert all(e["fix"] for e in errors)


def test_case_errors_name_the_id_field_for_a_blank_case_id(tmp_path):
    ws = _mk_ws(tmp_path, [_with(CASE_GOOD, id="  ")], None)
    cases_dir = ws / "oracle" / "cases"
    with pytest.raises(orun.OracleCaseError) as refusal:
        orun.load_cases(cases_dir)
    (row,) = orun.case_errors(cases_dir)
    assert row["field"] == refusal.value.field == "id"
    assert row["case"] is None and row["error"] == str(refusal.value)


def test_case_errors_keep_the_set_level_signature_check(tmp_path):
    ws = _mk_ws(tmp_path, [CASE_GOOD, _with(CASE_GOOD, id="twin")], None)
    cases_dir = ws / "oracle" / "cases"
    with pytest.raises(orun.OracleCaseError) as refusal:
        orun.load_cases(cases_dir)
    (row,) = orun.case_errors(cases_dir)
    assert row["file"] == "case-01.yaml" and row["case"] == "twin"
    assert row["error"] == str(refusal.value)
    assert "duplicate action signature" in row["error"]


def test_case_errors_skip_retired_cases_and_empty_sets(tmp_path):
    retired = _with(CASE_GOOD, status="retired",
                    expected={"evidence_refs": ["F001"]})
    ws = _mk_ws(tmp_path, [retired], None)
    assert orun.case_errors(ws / "oracle" / "cases") == []
    assert orun.case_errors(tmp_path / "no-such-dir") == []
    valid = _mk_ws(tmp_path / "v", [CASE_GOOD, CASE_BLIND], None)
    assert orun.case_errors(valid / "oracle" / "cases") == []


LINK_STUB = {"id": "case-c-1", "target_pq": "q1"}


def test_case_errors_stay_faithful_for_a_link_stub(tmp_path):
    ws = _mk_ws(tmp_path, [LINK_STUB], None)
    cases_dir = ws / "oracle" / "cases"
    with pytest.raises(orun.OracleCaseError) as refusal:
        orun.load_cases(cases_dir)
    (row,) = orun.case_errors(cases_dir)
    assert row["error"] == str(refusal.value)
    assert row["field"] == "expected" and row["case"] == "case-c-1"


def test_holds_runner_cases_tells_link_stubs_from_attempts(tmp_path):
    missing = tmp_path / "missing"
    assert orun.holds_runner_cases(missing) is False
    stubs = _mk_ws(tmp_path / "stubs", [LINK_STUB, {"id": "x", "status": "a"}],
                   None)
    assert orun.holds_runner_cases(stubs / "oracle" / "cases") is False
    for key in orun.CASE_RUNNER_KEYS:
        ws = _mk_ws(tmp_path / f"key-{key}", [{**LINK_STUB, key: "v"}], None)
        assert orun.holds_runner_cases(ws / "oracle" / "cases") is True, key
    listed = _mk_ws(tmp_path / "list", [], None)
    (listed / "oracle" / "cases" / "a.yaml").write_text("- 1\n",
                                                        encoding="utf-8")
    assert orun.holds_runner_cases(listed / "oracle" / "cases") is True
    broken = _mk_ws(tmp_path / "broken", [LINK_STUB], None)
    (broken / "oracle" / "cases" / "z.yaml").write_text("k: [unclosed\n",
                                                        encoding="utf-8")
    assert orun.holds_runner_cases(broken / "oracle" / "cases") is True


def test_case_errors_never_write(tmp_path):
    ws = _mk_ws(tmp_path, [_with(CASE_GOOD, expected={"evidence_refs": []})],
                None)

    def fingerprint():
        return sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size)
                      for p in ws.rglob("*") if p.is_file())

    before = fingerprint()
    assert len(orun.case_errors(ws / "oracle" / "cases")) == 1
    assert fingerprint() == before


def test_load_cases_behaviour_is_unchanged(tmp_path):
    valid = _mk_ws(tmp_path / "v", [CASE_GOOD, CASE_BLIND], None)
    loaded = orun.load_cases(valid / "oracle" / "cases")
    assert [c["id"] for c in loaded] == ["auth-fields", "blind-spot"]

    broken = _mk_ws(tmp_path / "b", [
        _with(CASE_GOOD, expected={"evidence_refs": ["F001"]}),
        _with(CASE_BLIND, mutations=[])], None)
    with pytest.raises(orun.OracleCaseError) as refusal:
        orun.load_cases(broken / "oracle" / "cases")
    assert str(refusal.value) == (
        "case-00.yaml: case 'auth-fields' needs a non-empty `expected` list")

    (broken / "oracle" / "cases" / "case-00.yaml").write_text(
        "key: [unclosed\n", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        orun.load_cases(broken / "oracle" / "cases")


def test_oracle_case_error_carries_an_optional_field():
    assert orun.OracleCaseError("plain").field is None
    assert orun.OracleCaseError("named", field="expected").field == "expected"
    assert str(orun.OracleCaseError("named", field="expected")) == "named"


# ------------------------------------------------------- decide() reporting

def _decide_ws(tmp_path: Path, cases: list[dict]) -> Path:
    ws = _mk_ws(tmp_path, cases, None)
    (ws / "runs").mkdir(exist_ok=True)
    anchor._reg(ws, [{"id": "C-1", "status": "PROVEN", "answers_question": "q1"}])
    anchor._ts(ws, anchor._pq_canonical())
    anchor._notes(ws, {"n1.md": ("C-1", "passes")})
    anchor._fact_dir(ws)
    return ws


def _write_case(ws: Path, name: str, case: dict) -> None:
    (ws / "oracle" / "cases" / name).write_text(
        yaml.safe_dump(case, sort_keys=False), encoding="utf-8")


def test_decide_carries_oracle_case_errors_only_when_there_are_some(tmp_path):
    ws = _decide_ws(tmp_path, [])
    baseline = cc.decide(ws, emit_snapshot=False)
    assert "oracle_case_errors" not in baseline

    _write_case(ws, "ok-a.yaml", CASE_GOOD)
    _write_case(ws, "ok-b.yaml", CASE_BLIND)
    assert cc.decide(ws, emit_snapshot=False) == baseline

    _write_case(ws, "zz-bad.yaml", _with(
        CASE_BLIND, id="bad", channel="probe",
        expected={"evidence_refs": ["F002"]}))
    decision = cc.decide(ws, emit_snapshot=False)
    errors = decision.pop("oracle_case_errors")
    assert [(e["file"], e["case"], e["field"]) for e in errors] == [
        ("zz-bad.yaml", "bad", "expected")]
    assert decision == baseline
    assert json.loads(json.dumps(errors)) == errors


def test_decide_ignores_a_directory_of_link_stubs(tmp_path):
    ws = _decide_ws(tmp_path, [])
    baseline = cc.decide(ws, emit_snapshot=False)
    _write_case(ws, "case-c-1.yaml", LINK_STUB)
    assert cc.decide(ws, emit_snapshot=False) == baseline
    cc.decide(ws)
    assert _events(ws, "oracle_case_error") == []
    assert not (ws / kunglao_log.EMIT_ONCE_REL).exists()


def test_decide_names_a_link_stub_that_blocks_a_runnable_set(tmp_path):
    ws = _decide_ws(tmp_path, [CASE_GOOD])
    _write_case(ws, "0-stub.yaml", LINK_STUB)
    with pytest.raises(orun.OracleCaseError):
        orun.load_cases(ws / "oracle" / "cases")
    errors = cc.decide(ws, emit_snapshot=False)["oracle_case_errors"]
    assert [(e["file"], e["field"]) for e in errors] == [
        ("0-stub.yaml", "expected")]


def test_decide_without_a_cases_directory_is_unchanged(tmp_path):
    ws = anchor._ws(tmp_path, "plain")
    anchor._reg(ws, [{"id": "C-1", "status": "PROVEN", "answers_question": "q1"}])
    anchor._ts(ws, anchor._pq_canonical())
    anchor._notes(ws, {"n1.md": ("C-1", "passes")})
    anchor._fact_dir(ws)
    assert "oracle_case_errors" not in cc.decide(ws, emit_snapshot=False)


def test_human_view_names_the_first_case_error(tmp_path):
    ws = _decide_ws(tmp_path, [_with(CASE_GOOD,
                                     expected={"evidence_refs": ["F001"]})])
    decision = cc.decide(ws, emit_snapshot=False)
    lines = [ln for ln in cc._human(decision).splitlines()
             if ln.startswith("oracle case errors:")]
    assert len(lines) == 1
    assert "case-00.yaml" in lines[0] and "expected" in lines[0]

    clean = _decide_ws(tmp_path / "clean", [CASE_GOOD])
    assert "oracle case errors" not in cc._human(
        cc.decide(clean, emit_snapshot=False))


def test_case_errors_never_change_the_verdict_or_add_a_blocker(tmp_path):
    ws = _decide_ws(tmp_path, [])
    baseline = cc.decide(ws, emit_snapshot=False)
    blockers = sorted(p.name for p in (ws / "blockers").glob("*"))
    _write_case(ws, "bad.yaml", _with(CASE_GOOD,
                                      expected={"evidence_refs": ["F001"]}))
    decision = cc.decide(ws)
    assert decision["decision"] == baseline["decision"]
    assert decision["exit_code"] == baseline["exit_code"]
    assert decision["active_blockers"] == baseline["active_blockers"]
    assert sorted(p.name for p in (ws / "blockers").glob("*")) == blockers


def test_case_error_event_is_emitted_once_per_fingerprint(tmp_path):
    ws = _decide_ws(tmp_path, [_with(CASE_GOOD,
                                     expected={"evidence_refs": ["F001"]})])
    cc.decide(ws)
    cc.decide(ws)
    rows = _events(ws, "oracle_case_error")
    assert len(rows) == 1
    detail = json.loads(rows[0]["detail"])
    assert detail["file"] == "case-00.yaml" and detail["case"] == "auth-fields"
    assert detail["field"] == "expected" and detail["fingerprint"]
    assert detail["error"] and detail["fix"]

    _write_case(ws, "second.yaml", _with(
        CASE_BLIND, id="second", expected={"evidence_refs": ["F002"]}))
    cc.decide(ws)
    cc.decide(ws)
    rows = _events(ws, "oracle_case_error")
    assert len(rows) == 2
    fingerprints = {json.loads(r["detail"])["fingerprint"] for r in rows}
    assert len(fingerprints) == 2


def test_decide_without_snapshot_emission_writes_no_case_error_state(tmp_path):
    ws = _decide_ws(tmp_path, [_with(CASE_GOOD,
                                     expected={"evidence_refs": ["F001"]})])
    for _ in range(2):
        decision = cc.decide(ws, emit_snapshot=False)
        assert len(decision["oracle_case_errors"]) == 1
    assert not (ws / kunglao_log.EMIT_ONCE_REL).exists()
    assert _events(ws, "oracle_case_error") == []


def test_a_reporter_crash_leaves_decide_intact(tmp_path, monkeypatch, capsys):
    ws = _decide_ws(tmp_path, [CASE_GOOD])
    baseline = cc.decide(ws, emit_snapshot=False)
    capsys.readouterr()

    def boom(_cases_dir):
        raise RuntimeError("reporter exploded")

    monkeypatch.setattr(orun, "case_errors", boom)
    assert cc.decide(ws, emit_snapshot=False) == baseline
    first = capsys.readouterr().err
    assert first.count("oracle_case_errors") == 1
    assert "RuntimeError" in first
    assert cc.decide(ws, emit_snapshot=False) == baseline
    assert capsys.readouterr().err.count("oracle_case_errors") == 0


def test_an_emission_crash_leaves_decide_intact(tmp_path, monkeypatch, capsys):
    ws = _decide_ws(tmp_path, [_with(CASE_GOOD,
                                     expected={"evidence_refs": ["F001"]})])
    expected = cc.decide(ws, emit_snapshot=False)
    capsys.readouterr()

    def boom(*_a, **_k):
        raise OSError("disk gone")

    monkeypatch.setattr(kunglao_log, "emit_once", boom)
    decision = cc.decide(ws)
    assert decision["decision"] == expected["decision"]
    assert decision["oracle_case_errors"] == expected["oracle_case_errors"]
    assert "oracle_case_error_emit" in capsys.readouterr().err
