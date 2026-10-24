#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb2_oracle_pins_818.py — #818 climb segment 2B: oracle_runner pins.

Behavior pins on REAL fixtures (tmp_path workspaces: real hypothesis store
files, real case YAMLs, real client modules on disk) for the oracle faces
the first climb leg left unmeasured. Pin discipline: no repo-state
literalization — every expectation derives from the fixture the test wrote.

Faces (scripts/oracle_runner.py):
  declared channels + signatures (#126) / evidence-ref resolution +
  self-anchor refusal / expected shape law / mutation + update_map parse /
  load_cases admission refusals / client loader (digest snapshot, era
  stamp, broken-client hard error) / liveness classification + settle
  filter (issue 303 D2) / probe quality gate / stage divergence +
  check_case verdict matrix / perturbation + mutation-must-fail /
  run + status write + posterior/PQ settlement faces / #146 retirement
  protocol / CLI arcs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import oracle_runner as orun  # noqa: E402


# ---------------------------------------------------------------- fixtures

GOOD_CLIENT = '''def compute(params):
    return {"auth_algo": "hmac-sha256",
            "nonce_len": len(str(params.get("nonce", "")))}
'''

STRICT_DEAD_CLIENT = '''LIVENESS_CONTRACT = 2

def compute(params):
    return {"auth_algo": "hmac-sha256", "nonce_len": 2}
'''

STRICT_ALIVE_CLIENT = '''LIVENESS_CONTRACT = 2

def compute(params):
    return {"auth_algo": "hmac-sha256",
            "nonce_len": len(str(params.get("nonce", ""))),
            "liveness_marker": "alive"}
'''

CASE_AUTH = {
    "id": "auth-fields",
    "channel": "device-trace",
    "hypothesis_ref": "H-001",
    "update_map": {"green_up": ["H-001"], "red_up": ["H-002"]},
    "params": {"nonce": 10},
    "expected": [
        {"field": "auth_algo", "value": "hmac-sha256",
         "evidence_refs": ["F001"]},
        {"field": "nonce_len", "value": 2, "evidence_refs": ["F001"]},
    ],
    "mutations": [{"field": "auth_algo", "kind": "swap"}],
    "verification": {
        "artifact": "auth field layout pinned by facts/F001",
        "artifact_kind": "hook-state",
        "criterion": "byte-match",
        "threshold": {"exact": True},
        "feeds_decision": "C-001",
    },
}


def _write_hypothesis(ws: Path, hyp_id: str, group: str,
                      status: str = "open") -> None:
    p = ws / "hypotheses" / f"{hyp_id}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\n"
        f"id: {hyp_id}\n"
        "claim_id: C-001\n"
        f"competitor_group: {group}\n"
        "candidates: [AES, ChaCha20]\n"
        f"status: {status}\n"
        "schema_rev: 1\n"
        "---\n\npq:q1\n",
        encoding="utf-8")


def _mk_ws(tmp_path: Path, cases: list[dict],
           client_src: str | None = None) -> tuple[Path, Path]:
    ws = tmp_path / "ws"
    (ws / "oracle" / "cases").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "facts" / "F001.md").write_text(
        "# F001\n\nauth fields pinned.\n", encoding="utf-8")
    _write_hypothesis(ws, "H-001", "grp-live")
    _write_hypothesis(ws, "H-002", "grp-live")
    for i, case in enumerate(cases):
        (ws / "oracle" / "cases" / f"case-{i:02d}.yaml").write_text(
            yaml.safe_dump(case, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
    client = None
    if client_src is not None:
        client = ws / "oracle" / "client.py"
        client.write_text(client_src, encoding="utf-8")
    return ws, client


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


# ---------------- 1. declared channels + signatures (#126) ----------------

class TestChannelFaces:
    def test_declared_token_vocabulary(self) -> None:
        assert orun.action_channel("frida stalker trace") == "device-trace"
        assert orun.action_channel("IDA-server dump") == "device-trace"
        assert orun.action_channel("qiling emulator") == "emulator-trace"
        assert orun.action_channel("ghidra decomp") == "static"

    def test_word_boundary_and_adhoc_fallback(self) -> None:
        # a token inside a longer word never matches
        assert orun.action_channel("validate notes") == "adhoc:validate notes"
        assert orun.action_channel("").startswith("adhoc")

    def test_signature_is_the_pure_dedup_axis(self) -> None:
        assert orun.action_signature("device-trace", "grp") == \
            ("device-trace", "grp")
        assert orun.action_signature(None, None) == ("", "")


# ---------------- 2. evidence refs (#126) ----------------

class TestEvidenceRefs:
    def _ws(self, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        (ws / "facts").mkdir(parents=True)
        (ws / "evidence").mkdir()
        (ws / "facts" / "F001.md").write_text("body", encoding="utf-8")
        (ws / "evidence" / "dump.bin").write_text("bytes", encoding="utf-8")
        return ws

    def test_fact_ref_and_evidence_file_resolve(self, tmp_path) -> None:
        ws = self._ws(tmp_path)
        got = orun._resolve_evidence_ref(ws, ws / "oracle" / "c.yaml",
                                         "c1", "f", "F001")
        assert got.name == "F001.md"
        got2 = orun._resolve_evidence_ref(ws, ws / "oracle" / "c.yaml",
                                          "c1", "f", "dump.bin")
        assert got2.parent.name == "evidence"

    def test_empty_ref_is_refused(self, tmp_path) -> None:
        ws = self._ws(tmp_path)
        with pytest.raises(orun.OracleCaseError, match="empty evidence_ref"):
            orun._resolve_evidence_ref(ws, ws / "c.yaml", "c1", "f", "  ")

    def test_self_anchor_into_runs_or_oracle_refused(self, tmp_path) -> None:
        ws = self._ws(tmp_path)
        for bad in ("runs/oracle-status.json", "oracle/client.py",
                    "Facts/oracle-status-x"):
            with pytest.raises(orun.OracleCaseError, match="self-anchor"):
                orun._resolve_evidence_ref(ws, ws / "c.yaml", "c1", "f", bad)

    def test_unresolvable_ref_is_refused(self, tmp_path) -> None:
        ws = self._ws(tmp_path)
        with pytest.raises(orun.OracleCaseError, match="declarations"):
            orun._resolve_evidence_ref(ws, ws / "c.yaml", "c1", "f",
                                       "F999")


# ---------------- 3. the expected shape law ----------------

class TestExpectedShape:
    def test_top_level_faults(self) -> None:
        assert orun.expected_shape_error(None) == orun.EXPECTED_TOP_LEVEL_FAULT
        assert orun.expected_shape_error([]) == orun.EXPECTED_TOP_LEVEL_FAULT
        assert "mapping" in orun.expected_shape_error(["x"])

    def test_entry_faults_name_the_field(self) -> None:
        assert "field" in orun.expected_shape_error([{"value": 1}])
        assert "lacks a `value`" in orun.expected_shape_error(
            [{"field": "f"}])
        assert "pending-observation" in orun.expected_shape_error(
            [{"field": "f", "value": 1}])

    def test_pending_marker_and_ref_anchored_are_legal(self) -> None:
        ok = orun.expected_shape_error([
            {"field": "f", "value": 1, "pending-observation": True},
            {"field": "g", "value": 2, "evidence_refs": ["F001"]},
        ])
        assert ok is None

    def test_parse_expected_resolves_refs_and_marks_pending(
            self, tmp_path) -> None:
        ws = tmp_path / "ws"
        (ws / "facts").mkdir(parents=True)
        (ws / "facts" / "F001.md").write_text("b", encoding="utf-8")
        out = orun._parse_expected(
            ws, ws / "c.yaml", "c1",
            [{"field": "a", "value": 1, "evidence_refs": ["F001"]},
             {"field": "b", "value": 2, "pending-observation": True}])
        assert out[0]["pending"] is False
        assert out[1]["pending"] is True

    def test_parse_expected_refuses_bad_ref(self, tmp_path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir(parents=True)
        with pytest.raises(orun.OracleCaseError):
            orun._parse_expected(ws, ws / "c.yaml", "c1",
                                 [{"field": "a", "value": 1,
                                   "evidence_refs": ["F404"]}])


# ---------------- 4. mutations + update_map parse ----------------

class TestMutationAndUpdateMap:
    def test_shorthand_and_known_kinds(self, tmp_path) -> None:
        p = tmp_path / "c.yaml"
        out = orun._parse_mutations(p, "c1", ["auth", {"field": "x",
                                                       "kind": "omit"}])
        assert out[0] == {"field": "auth", "kind": "change"}
        assert out[1] == {"field": "x", "kind": "omit"}

    def test_unknown_kind_and_non_list_refused(self, tmp_path) -> None:
        p = tmp_path / "c.yaml"
        with pytest.raises(orun.OracleCaseError, match="unknown kind"):
            orun._parse_mutations(p, "c1", [{"field": "x", "kind": "yeet"}])
        with pytest.raises(orun.OracleCaseError, match="must be a list"):
            orun._parse_mutations(p, "c1", "auth")

    def test_update_map_refusal_classes(self, tmp_path) -> None:
        p = tmp_path / "c.yaml"
        open_groups = {"H-001": "g", "H-002": "g"}
        with pytest.raises(orun.OracleCaseError, match="is required"):
            orun._parse_update_map(p, "c1", "g", None, open_groups)
        with pytest.raises(orun.OracleCaseError, match="nothing rises"):
            orun._parse_update_map(p, "c1", "g", {"green_up": []},
                                   open_groups)
        with pytest.raises(orun.OracleCaseError, match="red_up"):
            orun._parse_update_map(p, "c1", "g",
                                   {"green_up": ["H-001"], "red_up": "x"},
                                   open_groups)
        with pytest.raises(orun.OracleCaseError, match="live candidates"):
            orun._parse_update_map(p, "c1", "g",
                                   {"green_up": ["H-404"]}, open_groups)
        with pytest.raises(orun.OracleCaseError, match="own competitor"):
            orun._parse_update_map(p, "c1", "g",
                                   {"green_up": ["H-002"]}, {"H-002": "other"})
        ok = orun._parse_update_map(p, "c1", "g",
                                    {"green_up": ["H-001"],
                                     "red_up": ["H-002"]}, open_groups)
        assert ok == {"green_up": ["H-001"], "red_up": ["H-002"]}


# ---------------- 5. load_cases admission ----------------

class TestLoadCasesAdmission:
    def test_valid_set_loads_with_full_shape(self, tmp_path) -> None:
        ws, client = _mk_ws(tmp_path, [CASE_AUTH], GOOD_CLIENT)
        cases = orun.load_cases(ws / "oracle" / "cases")
        assert len(cases) == 1
        c = cases[0]
        assert c["id"] == "auth-fields"
        assert c["channel"] == "device-trace"
        assert c["competitor_group"] == "grp-live"
        assert c["mutations"][0]["kind"] == "swap"
        assert c["expected"][0]["pending"] is False

    def test_retired_case_skipped_before_lints(self, tmp_path) -> None:
        retired = dict(CASE_AUTH, id="old-one", status="retired",
                       expected=[{"field": "x", "value": 1,
                                  "pending-observation": True}],
                       hypothesis_ref="H-404", channel="dead-channel")
        ws, _ = _mk_ws(tmp_path, [CASE_AUTH, retired], GOOD_CLIENT)
        cases = orun.load_cases(ws / "oracle" / "cases")
        assert [c["id"] for c in cases] == ["auth-fields"]
        assert orun.retired_case_ids(ws / "oracle" / "cases") == ["old-one"]

    def test_singleton_competition_refused(self, tmp_path) -> None:
        case = dict(CASE_AUTH, update_map={"green_up": ["H-001"]})
        ws, _ = _mk_ws(tmp_path, [case], GOOD_CLIENT)
        (ws / "hypotheses" / "H-002.md").unlink()  # group thinned to 1 OPEN
        with pytest.raises(orun.OracleCaseError, match=">=2"):
            orun.load_cases(ws / "oracle" / "cases")

    def test_missing_channel_refused(self, tmp_path) -> None:
        case = {k: v for k, v in CASE_AUTH.items() if k != "channel"}
        ws, _ = _mk_ws(tmp_path, [case], GOOD_CLIENT)
        with pytest.raises(orun.OracleCaseError, match="`channel` is required"):
            orun.load_cases(ws / "oracle" / "cases")

    def test_duplicate_signature_refused(self, tmp_path) -> None:
        twin = dict(CASE_AUTH, id="twin")
        ws, _ = _mk_ws(tmp_path, [CASE_AUTH, twin], GOOD_CLIENT)
        with pytest.raises(orun.OracleCaseError, match="duplicate action"):
            orun.load_cases(ws / "oracle" / "cases")

    def test_missing_mutations_refused(self, tmp_path) -> None:
        case = {k: v for k, v in CASE_AUTH.items() if k != "mutations"}
        ws, _ = _mk_ws(tmp_path, [case], GOOD_CLIENT)
        with pytest.raises(orun.OracleCaseError, match="rubber stamp"):
            orun.load_cases(ws / "oracle" / "cases")

    def test_unresolvable_hypothesis_ref_refused(self, tmp_path) -> None:
        case = dict(CASE_AUTH, hypothesis_ref="H-404")
        ws, _ = _mk_ws(tmp_path, [case], GOOD_CLIENT)
        with pytest.raises(orun.OracleCaseError, match="links nothing"):
            orun.load_cases(ws / "oracle" / "cases")

    def test_require_hypothesis_ref_shape(self, tmp_path) -> None:
        p = tmp_path / "c.yaml"
        for bad in ("", "a/b", "..", "."):
            with pytest.raises(orun.OracleCaseError, match="hypothesis_ref"):
                orun._require_hypothesis_ref(p, "c1", bad)


# ---------------- 6. client loader ----------------

class TestClientLoader:
    def test_missing_client_reads_none(self, tmp_path) -> None:
        assert orun.load_client(tmp_path / "nope.py") is None
        assert orun.load_client(None) is None

    def test_broken_client_is_a_hard_error(self, tmp_path) -> None:
        p = tmp_path / "broken.py"
        p.write_text("x = 1  # no compute here\n", encoding="utf-8")
        with pytest.raises(orun.OracleCaseError, match="compute"):
            orun.load_client(p)

    def test_good_client_stamps_liveness_era(self, tmp_path) -> None:
        _, client = _mk_ws(tmp_path, [CASE_AUTH], STRICT_ALIVE_CLIENT)
        compute = orun.load_client(client)
        assert callable(compute)
        assert getattr(compute, "_liveness_contract", 0) == 2
        legacy = tmp_path / "legacy.py"
        legacy.write_text(GOOD_CLIENT, encoding="utf-8")
        assert getattr(orun.load_client(legacy), "_liveness_contract") == 1

    def test_snapshot_reuse_is_byte_addressed(self, tmp_path) -> None:
        _, client = _mk_ws(tmp_path, [CASE_AUTH], GOOD_CLIENT)
        c1 = orun.load_client(client)
        c2 = orun.load_client(client)  # identical bytes -> same snapshot
        assert c1 is c2 or c1.__module__ == c2.__module__


# ---------------- 7. liveness classification (issue 303 D2) ----------------

class TestLivenessFaces:
    def test_classify_row_eras(self) -> None:
        assert orun.classify_row({}) == "legacy"
        assert orun.classify_row({"liveness": "absent"}) == "infra"
        assert orun.classify_row({"liveness": "present"}) == "business"

    def test_settled_rows_drop_infra_and_pending(self) -> None:
        report = {"cases": {
            "pass-legacy": {"status": "pass"},
            "pass-infra": {"status": "pass", "liveness": "absent"},
            "fail-ok": {"status": "fail"},
            "pend": {"status": "pending"},
        }}
        settled = orun._settled_rows(report)
        assert settled == {"pass-legacy": True, "fail-ok": False}

    def test_probe_quality_gate_faces(self, tmp_path) -> None:
        assert orun.probe_quality_gate(None) == []
        assert orun.probe_quality_gate(tmp_path / "ghost.py") == []
        legacy = tmp_path / "legacy.py"
        legacy.write_text(GOOD_CLIENT, encoding="utf-8")
        assert orun.probe_quality_gate(legacy) == []
        strict_dead = tmp_path / "dead.py"
        strict_dead.write_text(STRICT_DEAD_CLIENT, encoding="utf-8")
        violations = orun.probe_quality_gate(strict_dead)
        assert violations and "liveness_marker" in violations[0]
        strict_alive = tmp_path / "alive.py"
        strict_alive.write_text(STRICT_ALIVE_CLIENT, encoding="utf-8")
        assert orun.probe_quality_gate(strict_alive) == []

    def test_emit_infra_dead_lands_repair_item(self, tmp_path) -> None:
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        orun._emit_infra_dead(ws, "c1", "marker_absent",
                              {"status": "pending"})
        rows = _event_rows(ws, "probe_infra_dead")
        assert rows and "c1" in rows[0].get("detail", "")


# ---------------- 8. check_case verdict matrix ----------------

class TestCheckCase:
    def _case(self) -> dict:
        return {
            "id": "auth-fields", "channel": "device-trace",
            "hypothesis_ref": "H-001", "competitor_group": "grp-live",
            "update_map": {"green_up": ["H-001"], "red_up": ["H-002"]},
            "params": {"nonce": 10},
            "expected_stages": {},
            "expected": [
                {"field": "auth_algo", "value": "hmac-sha256",
                 "evidence_refs": [], "pending": False},
                {"field": "nonce_len", "value": 2,
                 "evidence_refs": [], "pending": False},
            ],
            "mutations": [], "verification": {},
        }

    def test_no_client_is_honest_pending(self) -> None:
        row = orun.check_case(self._case(), None)
        assert row["status"] == "pending"
        assert row["instrumented"] is False
        assert row["error"] is None

    def test_green_red_and_crash_rows(self, tmp_path) -> None:
        good = orun.load_client(_client(tmp_path, GOOD_CLIENT))
        row = orun.check_case(self._case(), good)
        assert row["status"] == "pass"
        assert row["forensics"]["params_used"] == {"nonce": 10}
        bad_src = GOOD_CLIENT.replace('"hmac-sha256"', '"md5"')
        bad = orun.load_client(_client(tmp_path, bad_src))
        row = orun.check_case(self._case(), bad)
        assert row["status"] == "fail"
        assert row["failures"] and row["forensics"]["mismatches"]
        crash = orun.load_client(_client(
            tmp_path, 'def compute(p):\n    raise RuntimeError("x")\n'))
        row = orun.check_case(self._case(), crash)
        assert row["status"] == "pending" and row["error"]
        assert row["forensics"]["params_used"] == {"nonce": 10}

    def test_non_dict_result_is_contained(self, tmp_path) -> None:
        client = orun.load_client(_client(
            tmp_path, 'def compute(p):\n    return [1, 2]\n'))
        row = orun.check_case(self._case(), client)
        assert row["status"] == "pending"
        assert "expected dict" in row["error"]

    def test_strict_dead_probe_routes_infra_pending(self, tmp_path) -> None:
        dead = orun.load_client(_client(tmp_path, STRICT_DEAD_CLIENT))
        row = orun.check_case(self._case(), dead)
        assert row["liveness"] == "absent"
        assert row["status"] == "pending", (
            "a dead instrument is no evidence — never business pass/fail")

    def test_strict_alive_probe_classifies_business(self, tmp_path) -> None:
        alive = orun.load_client(_client(tmp_path, STRICT_ALIVE_CLIENT))
        row = orun.check_case(self._case(), alive)
        assert row["liveness"] == "present"
        assert row["status"] == "pass"

    def test_stage_divergence_faces(self, tmp_path) -> None:
        assert orun._stage_divergence({"s1": 1}, {"s1": 1}) is None
        assert orun._stage_divergence({"s1": 2}, {"s1": 1}) == "s1"
        assert orun._stage_divergence({}, {"s2": 1}) == "s2"
        staged = GOOD_CLIENT.replace(
            'return {',
            'return {"stages": {"parse": "bad"},')
        case = self._case()
        case["expected_stages"] = {"parse": "ok"}
        client = orun.load_client(_client(tmp_path, staged))
        row = orun.check_case(case, client)
        assert row["forensics"]["stages"] == {"parse": "bad"}
        assert row["forensics"]["divergence_point"] == "parse"


def _client(tmp_path: Path, src: str) -> Path:
    p = tmp_path / f"client-{abs(hash(src)) % 99999}.py"
    p.write_text(src, encoding="utf-8")
    return p


# ---------------- 9. perturbation + mutation pass ----------------

class TestMutationFaces:
    def test_perturb_is_guaranteed_different(self) -> None:
        assert orun._perturb(True) is False
        assert orun._perturb(3) == 4
        assert orun._perturb("s") == "s#mutated"
        assert orun._perturb([1, 2]) == [2, 1]
        assert orun._perturb({}) == {"mutated": True}
        assert orun._perturb(None) == "mutated"

    def test_mutated_client_kinds(self, tmp_path) -> None:
        compute = orun.load_client(_client(tmp_path, GOOD_CLIENT))
        omit = orun._mutated_client(compute, {"field": "auth_algo",
                                              "kind": "omit"}, None)
        assert "auth_algo" not in omit({})
        change = orun._mutated_client(compute, {"field": "nonce_len",
                                                "kind": "change"}, None)
        assert change({})["nonce_len"] != 0
        swap = orun._mutated_client(compute, {"field": "auth_algo",
                                              "kind": "swap"}, "nonce_len")
        out = swap({})
        assert out["auth_algo"] != "hmac-sha256"
        missing = orun._mutated_client(compute, {"field": "ghost",
                                                 "kind": "change"}, None)
        assert missing({})["auth_algo"] == "hmac-sha256"  # nothing to mutate

    def test_mutation_must_fail_and_blind_flag(self, tmp_path) -> None:
        ws, client = _mk_ws(tmp_path, [CASE_AUTH], GOOD_CLIENT)
        cases = orun.load_cases(ws / "oracle" / "cases")
        compute = orun.load_client(client)
        result = orun.mutation_pass(cases, compute)
        rows = result["mutations"]["auth-fields"]
        assert rows and rows[0]["red"] is True
        assert result["low_discriminativity"] == []

    def test_no_client_nothing_to_discriminate(self, tmp_path) -> None:
        ws, _ = _mk_ws(tmp_path, [CASE_AUTH], GOOD_CLIENT)
        cases = orun.load_cases(ws / "oracle" / "cases")
        result = orun.mutation_pass(cases, None)
        assert result == {"mutations": {}, "low_discriminativity": []}


# ---------------- 10. run + status + posterior/PQ settlement ----------------

class TestRunFaces:
    def test_run_green_end_to_end(self, tmp_path) -> None:
        ws, client = _mk_ws(tmp_path, [CASE_AUTH], GOOD_CLIENT)
        report = orun.run(ws / "oracle" / "cases", client)
        assert report["counts"] == {"red": 0, "green": 1, "pending": 0}
        assert report["cases"]["auth-fields"]["status"] == "pass"
        assert report["mutation"] is None
        assert report["retired"] == []
        # #157 observation events landed on the unified log
        obs = _event_rows(ws, "observation")
        assert obs and "auth-fields" in obs[0].get("detail", "")

    def test_run_without_client_all_pending(self, tmp_path) -> None:
        ws, _ = _mk_ws(tmp_path, [CASE_AUTH], None)
        report = orun.run(ws / "oracle" / "cases", None)
        assert report["counts"]["pending"] == 1
        assert report["client"] is None

    def test_write_status_and_fingerprint(self, tmp_path) -> None:
        ws, client = _mk_ws(tmp_path, [CASE_AUTH], GOOD_CLIENT)
        report = orun.run(ws / "oracle" / "cases", client)
        out = orun.write_status(ws, report)
        assert out.is_file()
        doc = json.loads(out.read_text("utf-8"))
        assert doc["cases"]["auth-fields"]["status"] == "pass"
        fp1 = orun._report_fingerprint(report)
        fp2 = orun._report_fingerprint(report)
        assert fp1 == fp2 and len(fp1) == 64

    def test_record_posteriors_moves_beta_and_emits(self, tmp_path) -> None:
        import posteriors as po
        ws, client = _mk_ws(tmp_path, [CASE_AUTH], GOOD_CLIENT)
        bad_src = GOOD_CLIENT.replace('"hmac-sha256"', '"md5"')
        bad = _client(tmp_path, bad_src)
        report = orun.run(ws / "oracle" / "cases", bad)
        out = orun.record_posteriors(ws, report)
        assert out is not None and out.is_file()
        led = po.PosteriorLedger.load(ws)
        # Beta(1,1) uniform prior + one red observation -> beta 2
        assert led.cases["auth-fields"].beta == 2.0
        events = _event_rows(ws, "posterior_update")
        assert events and "auth-fields" in events[0].get("detail", "")

    def test_pending_record_is_a_no_op(self, tmp_path) -> None:
        ws, _ = _mk_ws(tmp_path, [CASE_AUTH], None)
        report = orun.run(ws / "oracle" / "cases", None)
        assert orun.record_posteriors(ws, report) is None


class TestPqSettlement:
    def _ws_with_pq_decl(self, tmp_path: Path, client_src: str) -> tuple:
        case = dict(CASE_AUTH)
        case["target_pq"] = "q1"
        case["pq_update"] = {
            "green_up": {"alpha": 2.0},
            "red_up": {"beta": 1.5},
            "eliminate_on_fail": ["beta"],
        }
        return _mk_ws(tmp_path, [case], client_src)

    def _task_spec_with_candidates(self, ws: Path) -> None:
        (ws / "task_spec.yaml").write_text(yaml.safe_dump({
            "primary_questions": [
                {"id": "q1", "candidates": ["alpha", "beta"]},
            ]}), encoding="utf-8")

    def test_pass_settles_green_face(self, tmp_path) -> None:
        import posteriors as po
        ws, client = self._ws_with_pq_decl(tmp_path, GOOD_CLIENT)
        self._task_spec_with_candidates(ws)
        report = orun.run(ws / "oracle" / "cases", client)
        led = po.PosteriorLedger.load(ws)
        records = orun.record_pq_updates(ws, report, led)
        applied = [r for r in records if r["status"] == "applied"]
        assert applied and applied[0]["channel"] == "evidence"
        assert applied[0]["name"] == "alpha"
        # delta_h_bits = h_before - h_after: POSITIVE = sharpening (the
        # strength-2 evidence raised alpha's mass, entropy fell)
        assert applied[0]["delta_h_bits"] > 0
        assert applied[0]["h_standing_bits"] == applied[0]["h_after_bits"]
        events = _event_rows(ws, "pq_posterior_update")
        assert events

    def test_fail_runs_red_face_then_elimination(self, tmp_path) -> None:
        import posteriors as po
        bad_src = GOOD_CLIENT.replace('"hmac-sha256"', '"md5"')
        ws, client = self._ws_with_pq_decl(tmp_path, bad_src)
        self._task_spec_with_candidates(ws)
        report = orun.run(ws / "oracle" / "cases", client)
        led = po.PosteriorLedger.load(ws)
        records = orun.record_pq_updates(ws, report, led)
        channels = [r["channel"] for r in records if r["status"] == "applied"]
        assert channels == ["evidence", "eliminate"]  # D4: evidence first
        assert led.pqs["q1"].probs.get("beta") == 0.0

    def test_ensure_pq_idempotent_and_absent(self, tmp_path) -> None:
        import posteriors as po
        ws = tmp_path / "ws"
        ws.mkdir(parents=True)
        led = po.PosteriorLedger()
        assert orun.ensure_pq(led, ws, "q9") is None  # no task_spec entry
        self._task_spec_with_candidates(ws)
        pq1 = orun.ensure_pq(led, ws, "q1")
        assert pq1 is not None
        pq2 = orun.ensure_pq(led, ws, "q1")
        assert pq2 is pq1  # never reseeded

    def test_apply_pq_event_skip_faces(self, tmp_path) -> None:
        import posteriors as po
        pq = po.PQCategorical("q1", {"alpha": 1.0, "beta": 1.0})
        rec = orun.apply_pq_event(pq, "evidence", "ghost", 1.0)
        assert rec["status"] == "skipped" and "unknown candidate" in rec["reason"]
        rec = orun.apply_pq_event(pq, "psychic", "alpha", 1.0)
        assert rec["status"] == "skipped" and "channel" in rec["reason"]
        lone = po.PQCategorical("q2", {"solo": 1.0})
        rec = orun.apply_pq_event(lone, "eliminate", "solo", None)
        assert rec["status"] == "skipped" and "settled" in rec["reason"]

    def test_bad_declaration_is_a_skipped_record(self, tmp_path) -> None:
        import posteriors as po
        case = dict(CASE_AUTH, target_pq="q1",
                    pq_update={"green_up": {"alpha": "not-a-number"}})
        ws, client = _mk_ws(tmp_path, [case], GOOD_CLIENT)
        self._task_spec_with_candidates(ws)
        report = orun.run(ws / "oracle" / "cases", client)
        led = po.PosteriorLedger.load(ws)
        records = orun.record_pq_updates(ws, report, led)
        assert records and records[0]["status"] == "skipped"
        assert "not a number" in records[0]["reason"]


# ---------------- 11. retirement protocol (#146) ----------------

class TestRetirement:
    def _armed_ws(self, tmp_path: Path) -> Path:
        ws, _ = _mk_ws(tmp_path, [CASE_AUTH], GOOD_CLIENT)
        return ws

    def test_retire_appends_and_warns_coverage(self, tmp_path) -> None:
        ws = self._armed_ws(tmp_path)
        rec = orun.retire_case(
            ws, "auth-fields", attribution_class="case-wrong",
            disconfirmation="alt attributions argued away",
            replacement="re-capture via the new harness")
        assert rec["status"] == "retired"
        assert rec["armed_cases_after"] == rec["armed_cases_before"] - 1
        doc = yaml.safe_load(
            next((ws / "oracle" / "cases").glob("*.yaml"))
            .read_text("utf-8"))
        assert doc["status"] == "retired"
        assert doc["retirement"]["attribution_class"] == "case-wrong"
        rows = _event_rows(ws, "acceptance_coverage_decreased")
        assert rows and "auth-fields" in rows[0].get("detail", "")

    def test_double_retire_refused(self, tmp_path) -> None:
        ws = self._armed_ws(tmp_path)
        orun.retire_case(ws, "auth-fields", attribution_class="case-wrong",
                         disconfirmation="argued", replacement="plan")
        with pytest.raises(orun.OracleCaseError, match="one-way"):
            orun.retire_case(ws, "auth-fields",
                             attribution_class="case-wrong",
                             disconfirmation="argued", replacement="plan")

    def test_refusals_need_full_justification(self, tmp_path) -> None:
        ws = self._armed_ws(tmp_path)
        for kwargs in (
            {"attribution_class": "off-taxonomy",
             "disconfirmation": "a", "replacement": "r"},
            {"attribution_class": "case-wrong",
             "disconfirmation": "", "replacement": "r"},
            {"attribution_class": "case-wrong",
             "disconfirmation": "a", "replacement": ""},
        ):
            with pytest.raises(orun.OracleCaseError):
                orun.retire_case(ws, "auth-fields", **kwargs)

    def test_unknown_case_refused(self, tmp_path) -> None:
        ws = self._armed_ws(tmp_path)
        with pytest.raises(orun.OracleCaseError, match="nothing to retire"):
            orun.retire_case(ws, "ghost", attribution_class="case-wrong",
                             disconfirmation="a", replacement="r")

    def test_armed_count_tolerates_unreadable(self, tmp_path) -> None:
        cases_dir = tmp_path / "cases"
        cases_dir.mkdir()
        (cases_dir / "broken.yaml").write_text("{bad", encoding="utf-8")
        assert orun._armed_case_count(cases_dir) == 0


# ---------------- 12. CLI arcs ----------------

class TestCliArcs:
    def test_retire_flag_refusal_exits_2(self, tmp_path, capsys) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        rc = orun.main([str(ws), "--retire", "ghost"])
        assert rc == 2
        assert "RETIRE REFUSED" in capsys.readouterr().err

    def test_no_case_set_reads_clean_zero(self, tmp_path, capsys) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        rc = orun.main([str(ws)])
        assert rc == 0
        assert "nothing to bless" in capsys.readouterr().err

    def test_lint_refusal_exits_2_before_io(self, tmp_path, capsys) -> None:
        case = {k: v for k, v in CASE_AUTH.items() if k != "channel"}
        ws, _ = _mk_ws(tmp_path, [case], GOOD_CLIENT)
        rc = orun.main([str(ws), "--json"])
        assert rc == 2
        assert "REFUSED" in capsys.readouterr().err

    def test_green_run_json_exits_0_and_writes_status(
            self, tmp_path, capsys) -> None:
        ws, client = _mk_ws(tmp_path, [CASE_AUTH], GOOD_CLIENT)
        rc = orun.main([str(ws), "--client", str(client), "--json"])
        assert rc == 0
        report = json.loads(capsys.readouterr().out)
        assert report["counts"]["green"] == 1
        assert (ws / "runs" / "oracle-status.json").is_file()

    def test_red_run_exits_1(self, tmp_path) -> None:
        bad_src = GOOD_CLIENT.replace('"hmac-sha256"', '"md5"')
        ws, client = _mk_ws(tmp_path, [CASE_AUTH], bad_src)
        assert orun.main([str(ws), "--client", str(client)]) == 1
