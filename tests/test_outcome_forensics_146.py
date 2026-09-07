# -*- coding: utf-8 -*-
"""tests/test_outcome_forensics_146.py — issue #146 outcome forensics.

RED-first pins (the issue is the contract):

  1. RED settlement carries the per-field mismatch vector — every
     non-matching expected entry as {field, expected, actual} in the
     row's forensics block (losses become attributable).
  2. Stage-diff: when the client result carries a ``stages`` dict, the
     runner diffs stage-wise against the case's expected stages and
     records the divergence point (first stage whose output differs from
     its expected-stage value, or an expected stage the client never
     produced); no expected stages -> stages just recorded.
  3. GREEN settlement carries derivation provenance {params_used} plus
     the client's optional ``meta`` contract (absent -> empty).
  4. Report/status schema intact — forensics fields are ADDITIVE
     (runs/oracle-status.json keeps its exact convergence shape).
  5. Failure-analysis gate arming is settlement-driven: >=1 fail
     settlement on an oracle case linked via the claim's answers_question
     <-> case target_pq (same linkage priority_ratio uses) ARMS the gate —
     re-dispatch blocked until the three questions + artifacts are
     recorded. promotion_attempts dead-arming is gone. A NEW red
     settlement re-arms (per-attempt coverage derived from settlements).
  6. Case-abandonment protocol: a case transitions to ``retired`` ONLY
     with the structured justification {attribution_class in the closed
     taxonomy, disconfirmation, replacement} — loud refusal otherwise;
     the transition is append-only; retiring emits the coverage-drop WARN
     event (registered word acceptance_coverage_decreased) and removes
     the case from the acceptance net (runner skips it; its reds no
     longer arm the gate).
  7. Bank attribution upgrade: the case-bank entry schema gains an
     OPTIONAL structured ``how`` field (the forensics block) — never
     required, back-compat with banked rows, retrieval unchanged.
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

import case_bank as cb  # noqa: E402
import event_taxonomy as et  # noqa: E402
import failure_analysis_gate as fag  # noqa: E402
import oracle_runner as orun  # noqa: E402
import posteriors as po  # noqa: E402


# ---------------------------------------------------------------- clients

GOOD_CLIENT = '''def compute(params):
    return {"auth_algo": "hmac-sha256", "nonce_len": len(str(params["nonce"]))}
'''

# Optional client contract: "meta" (derivation provenance) + "stages"
# (intermediate derivation steps the runner diffs stage-wise).
GOOD_META_STAGED_CLIENT = '''def compute(params):
    return {"auth_algo": "hmac-sha256",
            "nonce_len": len(str(params["nonce"])),
            "meta": {"algo_path": "openssl EVP_sha256", "key_len": 32},
            "stages": {"canon": "user=alice", "mac": "a1b2"}}
'''

BAD_CLIENT = '''def compute(params):
    return {"auth_algo": len(str(params["nonce"])), "nonce_len": "hmac-sha256"}
'''

CRASH_CLIENT = '''def compute(params):
    raise RuntimeError("instrumentation exploded")
'''

# Correct final fields but a wrong intermediate: the derivation diverged
# at the mac stage even though the settlement is green.
STAGE_DIVERGENT_CLIENT = '''def compute(params):
    return {"auth_algo": "hmac-sha256",
            "nonce_len": 2,
            "stages": {"canon": "user=alice", "mac": "WRONG-MAC"}}
'''

STAGE_MISSING_CLIENT = '''def compute(params):
    return {"auth_algo": "hmac-sha256", "nonce_len": 2,
            "stages": {"canon": "user=alice"}}
'''


# ----------------------------------------------------------------- cases

CASE_MAIN = {
    "id": "auth-fields",
    "channel": "device-trace",
    "hypothesis_ref": "H-001",
    "target_pq": "q1",
    "update_map": {"green_up": ["H-001"], "red_up": ["H-002"]},
    "params": {"user": "alice", "nonce": 10},
    "expected": [
        {"field": "auth_algo", "value": "hmac-sha256",
         "evidence_refs": ["F001"]},
        {"field": "nonce_len", "value": 2, "evidence_refs": ["F001"]},
    ],
    "mutations": [{"field": "auth_algo", "kind": "swap"}],
}

# Distinct signature from CASE_MAIN (#126: channel x competitor_group).
CASE_STAGED = {
    "id": "staged-auth",
    "channel": "emulator-trace",
    "hypothesis_ref": "H-002",
    "target_pq": "q1",
    "update_map": {"green_up": ["H-002"], "red_up": ["H-001"]},
    "params": {"user": "alice", "nonce": 10},
    "stages": {"canon": "user=alice", "mac": "a1b2"},  # expected stage values
    "expected": [
        {"field": "auth_algo", "value": "hmac-sha256",
         "evidence_refs": ["F002"]},
        {"field": "nonce_len", "value": 2, "evidence_refs": ["F002"]},
    ],
    "mutations": [{"field": "auth_algo", "kind": "change"}],
}


def _write_hypothesis(ws: Path, hyp_id: str, group: str) -> None:
    p = ws / "hypotheses" / f"{hyp_id}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\n"
        f"id: {hyp_id}\n"
        "claim_id: C-001\n"
        f"competitor_group: {group}\n"
        "candidates: [AES, ChaCha20]\n"
        "status: open\n"
        "schema_rev: 1\n"
        "---\n\npq:q1\n",
        encoding="utf-8")


def _mk_ws(tmp_path: Path, cases: list[dict],
           client_src: str | None) -> Path:
    ws = tmp_path / "ws"
    (ws / "oracle" / "cases").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "facts" / "F001.md").write_text(
        "# F001\n\nauth fields pinned (byte-anchored).\n", encoding="utf-8")
    (ws / "facts" / "F002.md").write_text(
        "# F002\n\nmagic bytes pinned (byte-anchored).\n", encoding="utf-8")
    _write_hypothesis(ws, "H-001", "grp-live")
    _write_hypothesis(ws, "H-002", "grp-live")
    for i, case in enumerate(cases):
        (ws / "oracle" / "cases" / f"case-{i:02d}.yaml").write_text(
            yaml.safe_dump(case, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
    if client_src is not None:
        (ws / "oracle" / "client.py").write_text(client_src, encoding="utf-8")
    return ws


# ------------------------------------------------- gate fixture helpers

PQ = "q1"


def _claim(cid: str, pq: str | None = PQ, **extra) -> dict:
    """A non-terminal claim; arming comes from settlements, so
    promotion_attempts stays 0 — the dead counter must stay dead."""
    c = {"id": cid, "status": "OPEN", "boundary_type": "positive_observation",
         "evidence_tier_attempted": 1, "promotion_attempts": 0,
         "depends_on": [], "statement": "sample does X"}
    if pq is not None:
        c["answers_question"] = pq
    c.update(extra)
    return c


def _write_register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True,
                       sort_keys=False),
        encoding="utf-8")


def _arm_red(ws: Path, case_id: str, pq: str = PQ, reds: int = 1) -> None:
    """One oracle case linked to pq carrying `reds` fail settlements.

    Settlement state = the runner's posterior ledger (runs/posteriors.yaml,
    #106: each red run is beta+1 over the Beta(1,1) prior) — the same
    ledger #132's cadence hook records into."""
    cdir = ws / "oracle" / "cases"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / f"{case_id.lower()}.yaml").write_text(
        yaml.safe_dump({"id": case_id, "target_pq": pq},
                       sort_keys=False),
        encoding="utf-8")
    led = po.PosteriorLedger.load(ws)
    led.cases[case_id] = po.CasePosterior(case_id, alpha=1.0,
                                          beta=1.0 + float(reds))
    led.save(ws)


def _bump_red(ws: Path, case_id: str, reds: int) -> None:
    led = po.PosteriorLedger.load(ws)
    led.cases[case_id] = po.CasePosterior(case_id, alpha=1.0,
                                          beta=1.0 + float(reds))
    led.save(ws)


def _record(ws: Path, cid: str, **kw) -> dict:
    lib = kw.pop("library", None) or _empty_lib(ws)
    return fag.record_analysis(
        ws, cid, kw.get("assumption", ""), kw.get("validity", ""),
        kw.get("next_method", ""), kw.get("outcome"), kw.get("what_happened"),
        validated_capability=kw.get("capability"),
        identified_obstacle=kw.get("obstacle"),
        source=kw.get("source"), library=lib)


def _empty_lib(ws: Path) -> Path:
    lib = ws.parent / "lessons-lib"
    lib.mkdir(parents=True, exist_ok=True)
    return lib


def _retire_kw() -> dict:
    return {"attribution_class": "case-wrong",
            "disconfirmation": "single-green on the salted client and red "
                               "here matches no implementation split — the "
                               "expected value pins a pre-salt layout",
            "replacement": "re-derive expected from F003 and re-admit as "
                           "auth-fields-v2"}


def _log_rows(ws: Path) -> list[dict]:
    out: list[dict] = []
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return out
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    out.append(row)
    return out


# ================ 1. red settlement: per-field mismatch vector =========

def test_red_settlement_carries_per_field_mismatch_vector(tmp_path):
    """A FAIL row's forensics block names EVERY non-matching expected
    entry as {field, expected, actual} — the loss is attributable."""
    ws = _mk_ws(tmp_path, [CASE_MAIN], None)
    cases = orun.load_cases(ws / "oracle" / "cases")
    bad_src = ws / "oracle" / "bad.py"
    bad_src.write_text(BAD_CLIENT, encoding="utf-8")
    row = orun.check_case(cases[0], orun.load_client(bad_src))
    assert row["status"] == "fail"
    assert row["forensics"]["mismatches"] == [
        {"field": "auth_algo", "expected": "hmac-sha256", "actual": 2},
        {"field": "nonce_len", "expected": 2, "actual": "hmac-sha256"},
    ]


def test_run_report_rows_carry_the_mismatch_vector(tmp_path):
    """run() report rows carry the same forensics (the report is what the
    settlement hook consumes)."""
    ws = _mk_ws(tmp_path, [CASE_MAIN], BAD_CLIENT)
    report = orun.run(ws / "oracle" / "cases",
                      ws / "oracle" / "client.py")
    assert report["counts"]["red"] == 1
    assert report["cases"]["auth-fields"]["forensics"]["mismatches"][0] == {
        "field": "auth_algo", "expected": "hmac-sha256", "actual": 2}


def test_green_row_has_no_mismatches(tmp_path):
    ws = _mk_ws(tmp_path, [CASE_MAIN], GOOD_CLIENT)
    cases = orun.load_cases(ws / "oracle" / "cases")
    row = orun.check_case(cases[0], orun.load_client(ws / "oracle"
                                                     / "client.py"))
    assert row["status"] == "pass"
    assert row["forensics"]["mismatches"] == []


# ===================== 2. stage diff + divergence point ================

def test_stage_divergence_point_recorded(tmp_path):
    """A client-exposed stages dict is diffed against the case's expected
    stage values; the first differing stage is the divergence point —
    even when the final settlement is green."""
    ws = _mk_ws(tmp_path, [CASE_STAGED], STAGE_DIVERGENT_CLIENT)
    cases = orun.load_cases(ws / "oracle" / "cases")
    row = orun.check_case(cases[0], orun.load_client(ws / "oracle"
                                                     / "client.py"))
    assert row["status"] == "pass"
    assert row["forensics"]["stages"] == {"canon": "user=alice",
                                          "mac": "WRONG-MAC"}
    assert row["forensics"]["divergence_point"] == "mac"


def test_stage_missing_from_client_is_divergence(tmp_path):
    """An expected stage the client never produced is itself the
    divergence (missing output differs from its expected value)."""
    ws = _mk_ws(tmp_path, [CASE_STAGED], STAGE_MISSING_CLIENT)
    cases = orun.load_cases(ws / "oracle" / "cases")
    row = orun.check_case(cases[0], orun.load_client(ws / "oracle"
                                                     / "client.py"))
    assert row["forensics"]["divergence_point"] == "mac"


def test_stages_without_expected_values_just_recorded(tmp_path):
    """No expected stage values in the case -> the stages are recorded and
    no divergence point is claimed (nothing to differ from)."""
    ws = _mk_ws(tmp_path, [CASE_MAIN], GOOD_META_STAGED_CLIENT)
    cases = orun.load_cases(ws / "oracle" / "cases")
    row = orun.check_case(cases[0], orun.load_client(ws / "oracle"
                                                     / "client.py"))
    assert row["status"] == "pass"
    assert row["forensics"]["stages"] == {"canon": "user=alice",
                                          "mac": "a1b2"}
    assert row["forensics"]["divergence_point"] is None


def test_no_stages_divergence_stays_none(tmp_path):
    ws = _mk_ws(tmp_path, [CASE_MAIN], BAD_CLIENT)
    cases = orun.load_cases(ws / "oracle" / "cases")
    row = orun.check_case(cases[0], orun.load_client(ws / "oracle"
                                                     / "client.py"))
    assert row["status"] == "fail"
    assert row["forensics"]["stages"] == {}
    assert row["forensics"]["divergence_point"] is None


# ============== 3. green settlement: derivation provenance =============

def test_green_settlement_carries_params_and_meta(tmp_path):
    """params_used is the derivation's input record; a client ``meta``
    key is surfaced verbatim (optional contract)."""
    ws = _mk_ws(tmp_path, [CASE_MAIN], GOOD_META_STAGED_CLIENT)
    cases = orun.load_cases(ws / "oracle" / "cases")
    row = orun.check_case(cases[0], orun.load_client(ws / "oracle"
                                                     / "client.py"))
    assert row["status"] == "pass"
    assert row["forensics"]["params_used"] == {"user": "alice",
                                               "nonce": 10}
    assert row["forensics"]["meta"] == {"algo_path": "openssl EVP_sha256",
                                        "key_len": 32}


def test_meta_absent_is_empty(tmp_path):
    ws = _mk_ws(tmp_path, [CASE_MAIN], GOOD_CLIENT)
    cases = orun.load_cases(ws / "oracle" / "cases")
    row = orun.check_case(cases[0], orun.load_client(ws / "oracle"
                                                     / "client.py"))
    assert row["forensics"]["meta"] == {}


def test_crash_and_no_client_forensics_shape(tmp_path):
    """Unknown is not pass: a crashed client keeps params_used (compute
    was invoked), no client -> all forensics empty, nothing invented."""
    ws = _mk_ws(tmp_path, [CASE_MAIN], CRASH_CLIENT)
    cases = orun.load_cases(ws / "oracle" / "cases")
    row = orun.check_case(cases[0], orun.load_client(ws / "oracle"
                                                     / "client.py"))
    assert row["status"] == "pending"
    assert row["forensics"]["params_used"] == {"user": "alice",
                                               "nonce": 10}
    assert row["forensics"]["mismatches"] == []

    ws2 = _mk_ws(tmp_path / "b", [CASE_MAIN], None)
    row2 = orun.check_case(orun.load_cases(ws2 / "oracle" / "cases")[0],
                           None)
    assert row2["status"] == "pending"
    assert row2["forensics"] == {"params_used": {}, "meta": {},
                                 "mismatches": [], "stages": {},
                                 "divergence_point": None}


# =============== 4. report/status schema intact (additive only) ========

def test_report_and_status_schema_intact(tmp_path):
    """Forensics fields are ADDITIVE: every pre-existing report key and
    status-file field survives unchanged."""
    ws = _mk_ws(tmp_path, [CASE_MAIN], BAD_CLIENT)
    report = orun.run(ws / "oracle" / "cases",
                      ws / "oracle" / "client.py")
    assert set(report) >= {"schema", "cases_dir", "client", "cases",
                           "counts", "mutation"}
    row = report["cases"]["auth-fields"]
    assert set(row) >= {"status", "pending_entries", "instrumented",
                        "failures", "error"}

    orun.write_status(ws, report)
    doc = json.loads((ws / "runs" / "oracle-status.json")
                     .read_text(encoding="utf-8"))
    assert doc["schema"] == "oracle-status/1"
    assert set(doc["cases"]["auth-fields"]) == {"status", "pending_entries",
                                                "instrumented"}
    assert set(doc) == {"schema", "cases", "low_discriminativity", "counts"}


# ====== 5. failure-analysis gate: settlement-driven arming =============

def test_fail_settlement_arms_gate(tmp_path):
    """>=1 fail settlement on a target_pq-linked case ARMS the gate —
    with promotion_attempts at 0 (the dead counter stays dead)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1")])
    _arm_red(ws, "CASE-1", reds=1)

    blocked = fag.scan_workspace(ws)
    assert [b["claim_id"] for b in blocked] == ["C-1"]
    assert blocked[0]["state"] == "BLOCKED"
    # the derived settlement face replaces the dead counter
    assert "promotion_attempts" not in blocked[0]
    assert blocked[0]["red_settlements"] == {"CASE-1": 1}


def test_recorded_analysis_unblocks(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1")])
    _arm_red(ws, "CASE-1", reds=1)

    r = _record(ws, "C-1", assumption="spawn keeps the app alive",
                validity="not-justified",
                next_method="switch to listen mode",
                capability="frida JNI bridge works",
                obstacle="spawn times out under selinux",
                source="lesson-hit")
    assert r["recorded"] is True
    assert r["entry"]["covers_settlements"] == 1
    assert fag.check_claim(ws, "C-1")["state"] == "OK_COVERED"


def test_new_red_settlement_re_arms(tmp_path):
    """A NEW fail settlement after a covering analysis re-arms the gate —
    each failed attempt needs its own analysis (coverage now derives from
    settlements instead of the unwritten counter)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1")])
    _arm_red(ws, "CASE-1", reds=1)
    _record(ws, "C-1", assumption="a", validity="not-justified",
            next_method="b", capability="c", obstacle="o",
            source="lesson-hit")
    assert fag.check_claim(ws, "C-1")["state"] == "OK_COVERED"

    _bump_red(ws, "CASE-1", reds=2)
    assert fag.check_claim(ws, "C-1")["state"] == "BLOCKED"


def test_no_linkage_no_arming(tmp_path):
    """Reds on a case whose target_pq does not match the claim's
    answers_question arm nothing (the priority_ratio linkage)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1", pq=None),
                         _claim("C-2", pq="other-pq")])
    _arm_red(ws, "CASE-1", pq="q1", reds=2)

    assert fag.scan_workspace(ws) == []
    assert fag.check_claim(ws, "C-1")["state"] == "OK_NO_PRIOR_FAILURE"
    assert fag.check_claim(ws, "C-2")["state"] == "OK_NO_PRIOR_FAILURE"


def test_gate_does_not_arm_on_attempts_counter_alone(tmp_path):
    """promotion_attempts > 0 with zero fail settlements arms NOTHING —
    the dead-arming path is removed, not patched."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1", promotion_attempts=3)])
    assert fag.scan_workspace(ws) == []
    assert fag.check_claim(ws, "C-1")["state"] == "OK_NO_PRIOR_FAILURE"


def test_retired_case_reds_stop_arming(tmp_path):
    """A retired case has left the acceptance net: its red settlements no
    longer arm the gate (retirement is the way to silence a case)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1")])
    _arm_red(ws, "CASE-1", reds=1)
    assert fag.scan_workspace(ws), "pre-condition: armed"

    orun.retire_case(ws, "CASE-1", **_retire_kw())
    assert fag.scan_workspace(ws) == []
    assert fag.check_claim(ws, "C-1")["state"] == "OK_NO_PRIOR_FAILURE"


# ================ 6. case-abandonment protocol =========================

def test_retire_refuses_incomplete_justification(tmp_path):
    """Every justification field is required; an unknown attribution
    class is refused; nothing is written on refusal."""
    ws = _mk_ws(tmp_path, [CASE_MAIN], None)
    case_file = ws / "oracle" / "cases" / "case-00.yaml"
    before = case_file.read_text(encoding="utf-8")
    full = _retire_kw()
    for missing in ("attribution_class", "disconfirmation", "replacement"):
        kw = dict(full)
        kw[missing] = "   "
        with pytest.raises(orun.OracleCaseError, match=missing):
            orun.retire_case(ws, "auth-fields", **kw)
    with pytest.raises(orun.OracleCaseError, match="attribution_class"):
        orun.retire_case(ws, "auth-fields",
                         attribution_class="it-felt-wrong",
                         disconfirmation="x", replacement="y")
    assert case_file.read_text(encoding="utf-8") == before


def test_retire_refuses_unknown_case_and_rerun(tmp_path):
    ws = _mk_ws(tmp_path, [CASE_MAIN], None)
    with pytest.raises(orun.OracleCaseError, match="no case"):
        orun.retire_case(ws, "no-such-case", **_retire_kw())
    orun.retire_case(ws, "auth-fields", **_retire_kw())
    with pytest.raises(orun.OracleCaseError, match="already"):
        orun.retire_case(ws, "auth-fields", **_retire_kw())


def test_retire_full_justification_append_only(tmp_path):
    """Retirement keeps the case in its file (append-only): the original
    expected entries survive and status/retirement are ADDED."""
    ws = _mk_ws(tmp_path, [CASE_MAIN], None)
    rec = orun.retire_case(ws, "auth-fields", **_retire_kw())
    assert rec["case_id"] == "auth-fields"
    assert rec["armed_cases_after"] == rec["armed_cases_before"] - 1

    doc = yaml.safe_load(
        (ws / "oracle" / "cases" / "case-00.yaml").read_text(encoding="utf-8"))
    assert doc["status"] == "retired"
    assert doc["retirement"]["attribution_class"] == "case-wrong"
    assert doc["retirement"]["disconfirmation"] == \
        _retire_kw()["disconfirmation"]
    assert doc["retirement"]["replacement"] == _retire_kw()["replacement"]
    assert doc["retirement"]["retired_at"]
    assert doc["expected"] == CASE_MAIN["expected"]  # nothing deleted


def test_retire_emits_coverage_decreased_warn(tmp_path):
    """Retiring shrinks the acceptance net — the WARN fires with the
    registered event word, naming the case and the armed count."""
    ws = _mk_ws(tmp_path, [CASE_MAIN], None)
    orun.retire_case(ws, "auth-fields", **_retire_kw())
    drops = [r for r in _log_rows(ws)
             if r.get("action") == "acceptance_coverage_decreased"]
    assert drops, f"no coverage WARN in {_log_rows(ws)}"
    assert "auth-fields" in (drops[-1].get("detail") or "")


def test_retired_case_leaves_the_run(tmp_path):
    """The runner stops judging retired cases: they are reported, not
    run — the remaining cases keep their verdicts."""
    ws = _mk_ws(tmp_path, [CASE_MAIN, CASE_STAGED], BAD_CLIENT)
    orun.retire_case(ws, "staged-auth", **_retire_kw())
    report = orun.run(ws / "oracle" / "cases",
                      ws / "oracle" / "client.py")
    assert report["retired"] == ["staged-auth"]
    assert set(report["cases"]) == {"auth-fields"}
    assert report["counts"] == {"red": 1, "green": 0, "pending": 0}


def test_retire_cli_refuses_and_accepts(tmp_path, capsys):
    """CLI face: --retire without the justification exits 2 loudly; the
    full justification exits 0."""
    ws = _mk_ws(tmp_path, [CASE_MAIN], None)
    rc = orun.main([str(ws), "--retire", "auth-fields"])
    assert rc == 2
    assert "REFUSED" in capsys.readouterr().err

    rc = orun.main([str(ws), "--retire", "auth-fields",
                    "--attribution-class", "case-wrong",
                    "--disconfirmation", "expected pins a pre-salt layout",
                    "--replacement", "re-derive from F003 as auth-fields-v2"])
    assert rc == 0
    doc = yaml.safe_load(
        (ws / "oracle" / "cases" / "case-00.yaml").read_text(encoding="utf-8"))
    assert doc["status"] == "retired"


def test_coverage_word_is_registered(tmp_path):
    """The coverage-drop WARN word sits in the controlled vocabulary
    (#459: an emit literal outside EMIT_ACTIONS turns the suite red)."""
    assert "acceptance_coverage_decreased" in et.EMIT_ACTIONS


# ================ 7. bank attribution upgrade: optional `how` ==========

def _bank_entry(**kw):
    base = dict(claim_id="C-1", method="ghidra-light",
                context_tags=["re", "vm"],
                intent_uncertainty="which config builder runs first",
                outcome_observed={"verdict": "passes"},
                roi_class="POSITIVE")
    base.update(kw)
    return base


def test_bank_entry_carries_optional_how(tmp_path):
    """`how` is the structured forensics block — stored verbatim, never
    required (back-compat with banked rows)."""
    how = {"mismatch_class": "field-transpose",
           "mechanism": "auth_algo carried the nonce length — the two "
                        "signed fields were built in swapped order"}
    stored = cb.append(tmp_path, _bank_entry(how=how))
    assert stored["how"] == how
    rows = cb.read_entries(tmp_path)
    assert rows[0]["how"] == how

    plain = cb.append(tmp_path, _bank_entry(claim_id="C-2"))
    assert plain["how"] is None  # absent -> None, nothing invented


def test_bank_refuses_non_dict_how(tmp_path):
    """`how` is structured or nothing: free text is refused (a label is
    not a lesson)."""
    with pytest.raises(cb.CaseBankError, match="how"):
        cb.append(tmp_path, _bank_entry(how="wrong field order"))


def test_bank_retrieval_unchanged_with_how(tmp_path):
    """Retrieval contract untouched: failures first, newest first, tag
    intersection — `how` rides along but never reorders."""
    cb.append(tmp_path, _bank_entry(
        claim_id="C-1", roi_class="POSITIVE", how={"mismatch_class": "x"}))
    cb.append(tmp_path, _bank_entry(
        claim_id="C-2", roi_class="NEGATIVE",
        attribution="guessed OEP; verify-by-replay next time",
        how={"mismatch_class": "wrong-constant",
             "mechanism": "key schedule off by one round"}))
    got = cb.retrieve(tmp_path, ["re"])
    assert [e["claim_id"] for e in got] == ["C-2", "C-1"]
    assert got[0]["how"]["mechanism"].startswith("key schedule")


# ========== review r1 fixes: regression pins (findings 1-3, 5) ==========

def test_version_wall_raises_not_silently_disarms(tmp_path):
    """r1-1: a WRONG-schema posterior ledger must RAISE (the version
    wall), never silently read as "no settlements" — that would un-arm
    the gate exactly when the ledger is untrustworthy."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1")])
    _arm_red(ws, "CASE-1", reds=1)
    (ws / "runs" / "posteriors.yaml").write_text(
        "schema: posteriors-schema/999\ncases: {}\npqs: {}\n",
        encoding="utf-8")
    with pytest.raises(po.PosteriorSchemaError):
        fag.linked_fail_settlements(ws, _claim("C-1"))


def test_non_mapping_params_contained_as_case_error(tmp_path):
    """r1-2: a non-mapping params is a per-case ERROR row (crash
    containment), never a whole-run crash."""
    ws = _mk_ws(tmp_path, [CASE_MAIN], GOOD_CLIENT)
    case_file = ws / "oracle" / "cases" / "case-00.yaml"
    doc = yaml.safe_load(case_file.read_text(encoding="utf-8"))
    doc["params"] = "oops"
    case_file.write_text(yaml.safe_dump(doc), encoding="utf-8")
    cases = orun.load_cases(ws / "oracle" / "cases")
    row = orun.check_case(cases[0], orun.load_client(ws / "oracle"
                                                     / "client.py"))
    assert row["status"] == "pending"
    assert "dict" in (row["error"] or "")
    assert row["forensics"]["params_used"] == {}


MUTATING_CLIENT = '''def compute(params):
    params["k"] = "MUTATED-BY-CLIENT"
    return {"auth_algo": "hmac-sha256", "nonce_len": 2}
'''


def test_params_used_survives_client_mutation(tmp_path):
    """r1-3: params_used is a SNAPSHOT taken before compute — a client
    that mutates its input cannot corrupt the forensic record."""
    ws = _mk_ws(tmp_path, [CASE_MAIN], MUTATING_CLIENT)
    cases = orun.load_cases(ws / "oracle" / "cases")
    row = orun.check_case(cases[0], orun.load_client(ws / "oracle"
                                                     / "client.py"))
    assert row["status"] == "pass"
    assert row["forensics"]["params_used"] == {"user": "alice",
                                               "nonce": 10}


def test_retire_cli_empty_case_id_refuses(tmp_path, capsys):
    """r1-5: `--retire ""` must refuse, never fall through to a run face."""
    ws = _mk_ws(tmp_path, [CASE_MAIN], None)
    rc = orun.main([str(ws), "--retire", "",
                    "--attribution-class", "case-wrong",
                    "--disconfirmation", "x", "--replacement", "y"])
    assert rc == 2
    assert "REFUSED" in capsys.readouterr().err
