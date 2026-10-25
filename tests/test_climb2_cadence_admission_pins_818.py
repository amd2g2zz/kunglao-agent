#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb2_cadence_admission_pins_818.py — #818 climb segment 2C.

Behavior pins on REAL fixtures for the two cadence/admission faces the
first climb leg left unmeasured. Pin discipline: expectations derive from
the fixture each test wrote — no repo-state literalization.

Faces:
  scripts/oracle_case_admission.py — the #301 counterfeit-coin classes,
  the quantified verification 4-tuple, tree/bounce root faces, admit_set,
  legacy sweep + baseline ratchet, CLI arcs;
  scripts/oracle_cadence.py — run-start registration assertion (Standard 11
  bounded repetition), run_cadence per-face contract (unregistered /
  refused / marker-gate infra / broken client / green run + vacuous
  separation), missing-intent census.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import oracle_case_admission as oca  # noqa: E402
import oracle_cadence as ocad  # noqa: E402

GOOD_CLIENT = '''def compute(params):
    return {"magic": "MZ", "liveness_marker": "alive"}
'''

STRICT_DEAD_CLIENT = '''LIVENESS_CONTRACT = 2

def compute(params):
    return {"magic": "MZ"}
'''

LEGAL_VERIFICATION = {
    "artifact": "magic bytes pinned by facts/F001",
    "artifact_kind": "constant",
    "criterion": "byte-match",
    "threshold": {"exact": True},
    "feeds_decision": "C-001",
}


def _case_doc(cid: str = "c1", **extra) -> dict:
    doc = {
        "id": cid,
        "channel": "static",
        "hypothesis_ref": "H-001",
        "update_map": {"green_up": ["H-001"], "red_up": ["H-002"]},
        "params": {"blob": "cafe"},
        "expected": [{"field": "magic", "value": "MZ",
                      "evidence_refs": ["F001"]}],
        "mutations": [{"field": "magic", "kind": "change"}],
        "verification": dict(LEGAL_VERIFICATION),
    }
    doc.update(extra)
    return doc


def _write_hypotheses(ws: Path) -> None:
    for hid, group in (("H-001", "grp-live"), ("H-002", "grp-live")):
        p = ws / "hypotheses" / f"{hid}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "---\n"
            f"id: {hid}\n"
            "claim_id: C-001\n"
            f"competitor_group: {group}\n"
            "candidates: [MZ, PE]\n"
            "status: open\n"
            "schema_rev: 1\n"
            "---\n\npq:q1\n",
            encoding="utf-8")


def _mk_case_set(tmp_path: Path, docs: list[dict],
                 client_src: str | None = GOOD_CLIENT) -> Path:
    """A full <ws>/oracle/cases set that load_cases would bless."""
    ws = tmp_path / "ws"
    (ws / "oracle" / "cases").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "facts" / "F001.md").write_text("pinned\n", encoding="utf-8")
    _write_hypotheses(ws)
    for i, doc in enumerate(docs):
        (ws / "oracle" / "cases" / f"case-{i:02d}.yaml").write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
    if client_src is not None:
        (ws / "oracle" / "client.py").write_text(client_src,
                                                 encoding="utf-8")
    return ws


def _event_rows(ws: Path, action: str) -> list[dict]:
    rows = []
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return rows
    for log in sorted(logs.glob("kunglao-*.jsonl")):
        for line in log.read_text(encoding="utf-8",
                                  errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("action") == action:
                rows.append(row)
    return rows


# ------------- 1. counterfeit-coin classification (#301) -------------

class TestClassifyProse:
    def test_three_classes_bilingual(self) -> None:
        assert oca.classify_prose(
            "this binary uses encryption") == "category-existence"
        assert oca.classify_prose("存在某种加密算法") == "category-existence"
        assert oca.classify_prose("the model understands the header"
                                  ) == "comprehension-claim"
        assert oca.classify_prose("we traced and analyzed the loop"
                                  ) == "activity-claim"
        assert oca.classify_prose("理解了该结构") == "comprehension-claim"

    def test_mechanical_text_is_clean(self) -> None:
        assert oca.classify_prose("byte-match on 16 bytes") is None
        assert oca.classify_prose("") is None


# ------------- 2. verification 4-tuple -------------

class TestVerificationTuple:
    def test_threshold_shape_law(self) -> None:
        assert oca._threshold_errors("byte-match", None)
        assert oca._threshold_errors("byte-match", {"bogus": 1})
        assert oca._threshold_errors("byte-match", {"min_hits": 0})
        assert oca._threshold_errors("byte-match", {"min_hits": True})
        assert oca._threshold_errors("byte-match", {"min_hits": 3, "of": 2})
        assert oca._threshold_errors("byte-match", {"all": "yes"})
        assert oca._threshold_errors("byte-match", {"of": 2})
        assert oca._threshold_errors("byte-match", {"min_hits": 2}) == []
        assert oca._threshold_errors("byte-match", {"exact": True}) == []

    def test_validate_verification_faults(self) -> None:
        assert oca.validate_verification(None)
        assert oca.validate_verification("x")
        empty = {k: "" for k in LEGAL_VERIFICATION}
        faults = " ".join(oca.validate_verification(empty))
        assert "artifact" in faults and "criterion" in faults
        vague = dict(LEGAL_VERIFICATION, feeds_decision="tbd")
        assert oca.validate_verification(vague)
        fuzzy = dict(LEGAL_VERIFICATION, criterion="looks similar")
        assert "non-mechanical-criterion" in " ".join(
            oca.validate_verification(fuzzy))
        coin = dict(LEGAL_VERIFICATION,
                    criterion="contains encryption",
                    threshold={"exact": True})
        assert "category-existence" in " ".join(
            oca.validate_verification(coin))
        assert oca.validate_verification(LEGAL_VERIFICATION) == []

    def test_legality_needs_clause_and_contract(self) -> None:
        clean = {"verification": dict(LEGAL_VERIFICATION)}
        assert oca.verification_is_legal(clean) is True
        claim_no_contract = {
            "expected": [{"field": "x", "value": 1}],
        }
        assert oca.verification_is_legal(claim_no_contract) is False
        # the legality face (decomposition-children law) demands the
        # mapping from EVERY doc — even an all-pending scaffold carries
        # no contract here (lint_case is the face that exempts scaffolds)
        scaffold = {
            "expected": [{"field": "x", "value": 1,
                          "pending-observation": True}],
        }
        assert oca.verification_is_legal(scaffold) is False

    def test_clause_surfaces_scan_question_and_verification_only(
            self) -> None:
        doc = {"question": "uses encryption?",
               "verification": {"artifact": "understands the format",
                                "criterion": "byte-match"}}
        surfaces = oca._clause_surfaces(doc)
        assert len(surfaces) == 3

    def test_real_claims_vs_all_pending_scaffold(self) -> None:
        assert oca._has_real_claims(
            {"expected": [{"field": "x", "value": 1}]}) is True
        assert oca._all_pending_scaffold({"expected": [
            {"field": "x", "value": 1, "pending-observation": True}]}) is True
        assert oca._all_pending_scaffold({"expected": []}) is False


# ------------- 3. tree + bounce root faces -------------

class TestRootFaces:
    def test_decomposition_shape_faces(self, tmp_path) -> None:
        cases = tmp_path / "cases"
        cases.mkdir()
        child_legal = {"id": "child-1",
                       "verification": dict(LEGAL_VERIFICATION)}
        child_root = {"id": "child-2", "decomposition": ["child-1"],
                      "verification": dict(LEGAL_VERIFICATION)}
        for doc in (child_legal, child_root):
            (cases / f"{doc['id']}.yaml").write_text(
                yaml.safe_dump(doc), encoding="utf-8")
        docs = oca.load_case_docs(cases)
        errs = oca._validate_decomposition(["ghost"], docs)
        assert any("does not resolve" in e for e in errs)
        errs = oca._validate_decomposition(["child-2"], docs)
        assert any("depth-1" in e for e in errs)
        errs = oca._validate_decomposition([], docs)
        assert errs
        assert oca._validate_decomposition(["child-1"], docs) == []

    def test_bounce_needs_reason_and_target(self) -> None:
        assert oca._validate_bounce({})
        assert oca._validate_bounce({"reason": "r", "target": "task"}) == []

    def test_pre_gate_skips_valid_root_refuses_counterfeit(
            self, tmp_path) -> None:
        root_ok = {"id": "root", "bounce": {"reason": "vague",
                                            "target": "task layer"}}
        skip, refusal = oca.pre_gate(root_ok, tmp_path)
        assert skip is True and refusal == ""
        coin = {"id": "coin", "question": "contains encryption?"}
        skip, refusal = oca.pre_gate(coin, tmp_path)
        assert skip is False and "category-existence" in refusal
        faceless = _case_doc()
        skip, refusal = oca.pre_gate(faceless, tmp_path / "empty")
        assert skip is False and refusal == ""


# ------------- 4. admit_set + sweep -------------

class TestAdmitAndSweep:
    def test_contract_scaffold_husk_rows(self, tmp_path) -> None:
        contract = _case_doc("contract-1")
        scaffold = {"id": "scaffold-1",
                    "expected": [{"field": "x", "value": 1,
                                  "pending-observation": True}]}
        husk = {"id": "husk-1"}
        cases = tmp_path / "cases"
        cases.mkdir()
        for doc in (contract, scaffold, husk):
            (cases / f"{doc['id']}.yaml").write_text(
                yaml.safe_dump(doc), encoding="utf-8")
        report = oca.admit_set(cases)
        ids_admitted = [r["id"] for r in report["admitted"]]
        assert ids_admitted == ["contract-1", "scaffold-1"]
        assert report["admitted"][1].get("scaffold") is True
        assert report["refused"][0]["id"] == "husk-1"
        assert report["refused"][0]["class"] == "missing-verification"

    def test_valid_roots_and_bounces_reported(self, tmp_path) -> None:
        child = {"id": "c1", "verification": dict(LEGAL_VERIFICATION)}
        root = {"id": "root-1", "decomposition": ["c1"]}
        bounce = {"id": "bounce-1", "bounce": {"reason": "no artifact",
                                               "target": "task layer"}}
        cases = tmp_path / "cases"
        cases.mkdir()
        for doc in (child, root, bounce):
            (cases / f"{doc['id']}.yaml").write_text(
                yaml.safe_dump(doc), encoding="utf-8")
        report = oca.admit_set(cases)
        assert report["roots"][0]["children"] == ["c1"]
        assert report["bounced"][0]["target"] == "task layer"

    def test_bad_tree_root_refused_with_class(self, tmp_path) -> None:
        root = {"id": "root-bad", "decomposition": ["ghost-child"]}
        cases = tmp_path / "cases"
        cases.mkdir()
        (cases / "root-bad.yaml").write_text(
            yaml.safe_dump(root), encoding="utf-8")
        report = oca.admit_set(cases)
        assert report["refused"][0]["class"] == "bad-tree"

    def test_sweep_keeps_decomposes_and_ratchets(
            self, tmp_path) -> None:
        good = _case_doc("keep-1")
        root = {"id": "root-1", "decomposition": ["unminted-child"]}
        ws = _mk_case_set(tmp_path, [good, root], None)
        cases = ws / "oracle" / "cases"
        report = oca.sweep(cases)
        assert [r["id"] for r in report["keep"]] == ["keep-1"]
        assert report["decompose"][0]["id"] == "root-1"
        assert report["new_findings"] == ["root-1"]
        baseline = cases.parent / "baseline.txt"
        baseline.write_text("root-1\n", encoding="utf-8")
        report2 = oca.sweep(cases, baseline)
        assert report2["new_findings"] == []
        assert report2["baseline_count"] == 1


# ------------- 5. admission CLI arcs -------------

class TestAdmissionCli:
    def test_missing_dir_exits_2(self, capsys) -> None:
        assert oca.main([str(Path("/nonexistent-cases-xyz"))]) == 2

    def test_clean_set_exits_0_json(self, tmp_path, capsys) -> None:
        ws = _mk_case_set(tmp_path, [_case_doc("c1")], None)
        rc = oca.main([str(ws / "oracle" / "cases"), "--json"])
        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["admitted"][0]["id"] == "c1"

    def test_refusals_exit_1(self, tmp_path) -> None:
        cases = tmp_path / "cases"
        cases.mkdir()
        (cases / "husk.yaml").write_text(
            yaml.safe_dump({"id": "husk"}), encoding="utf-8")
        assert oca.main([str(cases)]) == 1


# ------------- 6. cadence faces -------------

class TestRunStartAssertion:
    def test_no_armed_cases_is_silent(self, tmp_path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        out = ocad.assert_run_start(ws)
        assert out == {"checked": True, "registered": True,
                       "reason": "no_armed_cases"}

    def test_registered_client_is_silent(self, tmp_path) -> None:
        ws = _mk_case_set(tmp_path, [_case_doc()])
        out = ocad.assert_run_start(ws)
        assert out["registered"] is True
        assert out["reason"] == "registered"

    def test_unregistered_escalates_at_the_limit(self, tmp_path) -> None:
        ws = _mk_case_set(tmp_path, [_case_doc()], None)
        for i in range(1, ocad.RUN_START_REPEAT_LIMIT + 1):
            out = ocad.assert_run_start(ws)
            assert out["occurrence"] == i
        warns = _event_rows(ws, "oracle_cadence_warn")
        assert len(warns) == ocad.RUN_START_REPEAT_LIMIT
        last = json.loads(warns[-1]["detail"].split(": ", 1)[1])
        assert last["escalated"] is True
        # beyond the limit: bounded silence, the audit keeps counting
        out = ocad.assert_run_start(ws)
        assert out["occurrence"] == ocad.RUN_START_REPEAT_LIMIT + 1
        assert len(_event_rows(ws, "oracle_cadence_warn")) \
            == ocad.RUN_START_REPEAT_LIMIT

    def test_client_fingerprint_matches_load_client_digest(
            self, tmp_path) -> None:
        ws = _mk_case_set(tmp_path, [_case_doc()])
        import hashlib
        src = (ws / "oracle" / "client.py").read_text("utf-8")
        want = hashlib.sha256(src.encode("utf-8")).hexdigest()[:16]
        assert ocad.client_fingerprint(ws / "oracle" / "client.py") == want


class TestRunCadence:
    def test_no_armed_cases_short_circuit(self, tmp_path) -> None:
        assert ocad.run_cadence(tmp_path) == {"fired": False,
                                              "reason": "no_armed_cases"}

    def test_unregistered_client_is_loud_and_unran(self, tmp_path) -> None:
        ws = _mk_case_set(tmp_path, [_case_doc()], None)
        out = ocad.run_cadence(ws)
        assert out == {"fired": True, "ran": False,
                       "reason": "client_not_registered"}
        assert _event_rows(ws, "oracle_cadence_warn")

    def test_refused_case_set_stays_a_refusal(self, tmp_path) -> None:
        ws = _mk_case_set(tmp_path, [_case_doc()])
        # strip the channel: load_cases must refuse; no status file lands
        case_path = next((ws / "oracle" / "cases").glob("*.yaml"))
        doc = yaml.safe_load(case_path.read_text("utf-8"))
        del doc["channel"]
        case_path.write_text(yaml.safe_dump(doc), encoding="utf-8")
        out = ocad.run_cadence(ws)
        assert out["reason"] == "case_set_refused"
        assert not (ws / "runs" / "oracle-status.json").exists()

    def test_strict_dead_probe_routes_infra(self, tmp_path) -> None:
        ws = _mk_case_set(tmp_path, [_case_doc()], STRICT_DEAD_CLIENT)
        out = ocad.run_cadence(ws)
        assert out["reason"] == "marker_gate_failed"
        assert out["counts"] == {"red": 0, "green": 0, "pending": 1}
        status = json.loads(
            (ws / "runs" / "oracle-status.json").read_text("utf-8"))
        row = status["cases"]["c1"]
        # the status file narrows rows to the three DRAIN fields — the
        # infra verdict shows as pending-with-instrumentation
        assert row["status"] == "pending" and row["instrumented"] is True
        assert _event_rows(ws, "probe_infra_dead")
        # a dead instrument feeds no posterior
        assert not (ws / "runs" / "posteriors.yaml").exists()

    def test_broken_client_is_dead_not_skipped(self, tmp_path) -> None:
        ws = _mk_case_set(tmp_path, [_case_doc()], "x = 1  # no compute")
        out = ocad.run_cadence(ws)
        assert out["reason"] == "client_broken"
        assert out["counts"]["pending"] == 1
        assert _event_rows(ws, "probe_infra_dead")

    def test_green_run_appends_cadence_rows(self, tmp_path) -> None:
        ws = _mk_case_set(tmp_path, [_case_doc()], GOOD_CLIENT)
        out = ocad.run_cadence(ws)
        assert out["reason"] == "ok"
        assert out["counts"]["green"] == 1
        assert out["vacuous"] == []
        rows = ocad.read_cadence_rows(ws)
        assert rows and rows[0]["status"] == "pass"
        assert (ws / "runs" / "posteriors.yaml").is_file()

    def test_second_distinct_greening_client_fires_case_vacuous(
            self, tmp_path) -> None:
        ws = _mk_case_set(tmp_path, [_case_doc()], GOOD_CLIENT)
        assert ocad.run_cadence(ws)["reason"] == "ok"
        variant = GOOD_CLIENT.replace('def compute(params):',
                                      'def compute(p):  # v2')
        (ws / "oracle" / "client.py").write_text(variant, encoding="utf-8")
        out = ocad.run_cadence(ws)
        assert out["vacuous"] == ["c1"]
        rows = _event_rows(ws, "case_vacuous")
        assert rows and "c1" in rows[0].get("detail", "")

    def test_red_run_is_no_vacuous_signal(self, tmp_path) -> None:
        bad = GOOD_CLIENT.replace('"MZ"', '"PE"')
        ws = _mk_case_set(tmp_path, [_case_doc()], bad)
        out = ocad.run_cadence(ws)
        assert out["reason"] == "ok"
        assert out["counts"]["red"] == 1
        assert out["vacuous"] == []


class TestMissingIntentCensus:
    def test_census_counts_both_faces(self, tmp_path) -> None:
        ws = tmp_path / "ws"
        (ws / "runs" / "logs").mkdir(parents=True)
        (ws / ".convergence_ledger.jsonl").write_text(
            json.dumps({"type": "outcome", "claim_id": "C-9"}) + "\n",
            encoding="utf-8")
        log = ws / "runs" / "logs" / "kunglao-test.jsonl"
        log.write_text(
            json.dumps({"action": "intent_unparsed", "detail": "x"}) + "\n",
            encoding="utf-8")
        census = ocad.missing_intent_face(ws)
        assert census["intent_unparsed_events"] == 1
        assert census["unintended_outcome_claims"] == ["C-9"]

    def test_recorded_intent_clears_the_claim(self, tmp_path) -> None:
        import roi_settlement
        ws = tmp_path / "ws"
        ws.mkdir(parents=True)
        (ws / ".convergence_ledger.jsonl").write_text(
            json.dumps({"type": "outcome", "claim_id": "C-1"}) + "\n",
            encoding="utf-8")
        roi_settlement.record_intent(ws, "C-1", method="m",
                                     context_tags=[],
                                     uncertainty="which",
                                     expected_artifact="facts/F1.md")
        census = ocad.missing_intent_face(ws)
        assert census["unintended_outcome_claims"] == []

    def test_empty_workspace_census_is_zero(self, tmp_path) -> None:
        census = ocad.missing_intent_face(tmp_path)
        assert census == {"intent_unparsed_events": 0,
                          "unintended_outcome_claims": []}
