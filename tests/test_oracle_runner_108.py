# -*- coding: utf-8 -*-
"""tests/test_oracle_runner_108.py — issue #108 half B: mutation-must-fail
oracle self-test + half A's status-file contract.

The oracle is LLM-built: it catches wrong analysis (a wrong client fails the
case) but not its own design errors (a mis-pinned case passes a wrong
implementation too). What is mechanical: a deliberately-mutated client — one
declared field swapped / omitted / changed — MUST turn the case red; a case
that stays green under all its declared mutations is flagged
``low_discriminativity`` (the case observes nothing its author claims
distinguishes it).

Contract pinned here:
  - correct client -> green; wrong client (field order swapped) -> red
  - no client runnable -> ALL cases pending, never green (instrumented=False)
  - expected entry without evidence_refs and without a pending-observation
    marker -> the runner REFUSES (lint-style OracleCaseError, no silent
    invented values — the doubao convention made mechanical)
  - --mutation: every declared mutation must turn its case red; an
    all-green-under-mutation case is flagged low_discriminativity
  - runs/oracle-status.json carries the convergence convention
    {"cases": {id: {"status", "pending_entries", "instrumented"}}}
  - every real verdict updates #106's PosteriorLedger (Bernoulli observation
    — "runner red/green is the only reward signal", posteriors.py)
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

import oracle_runner as orun  # noqa: E402  (RED: module does not exist yet)
import posteriors as po  # noqa: E402


# ---------------------------------------------------------------- fixtures

GOOD_CLIENT = '''def compute(params):
    return {"auth_algo": "hmac-sha256", "nonce_len": len(str(params["nonce"]))}
'''

# 换字段序 (the issue's canonical near-miss): the two signed fields' values
# are transposed — a wrong implementation every mis-pinned case would pass.
BAD_CLIENT = '''def compute(params):
    return {"auth_algo": len(str(params["nonce"])), "nonce_len": "hmac-sha256"}
'''

CRASH_CLIENT = '''def compute(params):
    raise RuntimeError("instrumentation exploded")
'''

CASE_GOOD = {
    "id": "auth-fields",
    "description": "signed auth field ordering discriminator",
    "params": {"user": "alice", "nonce": 10},
    "expected": [
        {"field": "auth_algo", "value": "hmac-sha256",
         "evidence_refs": ["F001"]},
        {"field": "nonce_len", "value": 2, "evidence_refs": ["F001"]},
    ],
    "mutations": [{"field": "auth_algo", "kind": "swap"}],
}

# Declares a mutation on a field the case never observes: under the mutation
# the case stays green -> the case discriminates nothing it claims to.
CASE_BLIND = {
    "id": "blind-spot",
    "description": "declares a mutation on an unobserved field",
    "params": {"blob": "cafe"},
    "expected": [
        {"field": "magic", "value": "MZ", "evidence_refs": ["F002"]},
    ],
    "mutations": [{"field": "checksum", "kind": "change"}],
}

BLIND_CLIENT = '''def compute(params):
    return {"magic": "MZ", "checksum": "cafe"}
'''

# serves every synthetic case (auth fields + blind-spot's magic/checksum)
UNIVERSAL_CLIENT = '''def compute(params):
    return {"auth_algo": "hmac-sha256",
            "nonce_len": len(str(params.get("nonce", ""))),
            "magic": "MZ",
            "checksum": params.get("blob", "")}
'''


def _mk_ws(tmp_path: Path, cases: list[dict], client_src: str | None) -> Path:
    ws = tmp_path / "ws"
    (ws / "oracle" / "cases").mkdir(parents=True)
    for i, case in enumerate(cases):
        (ws / "oracle" / "cases" / f"case-{i:02d}.yaml").write_text(
            yaml.safe_dump(case, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
    if client_src is not None:
        (ws / "oracle" / "client.py").write_text(client_src, encoding="utf-8")
    return ws


def _write_client(ws: Path, src: str, name: str = "probe_client") -> Path:
    p = ws / "oracle" / f"{name}.py"
    p.write_text(src, encoding="utf-8")
    return p


def _load_client(path: Path):
    return orun.load_client(path)


# ------------------------------------------------------------ client loader

def test_load_client_missing_is_none(tmp_path: Path) -> None:
    assert orun.load_client(tmp_path / "nope.py") is None


def test_load_client_contract(tmp_path: Path) -> None:
    ws = _mk_ws(tmp_path, [CASE_GOOD], None)
    compute = _load_client(_write_client(ws, GOOD_CLIENT))
    assert compute({"nonce": 10})["nonce_len"] == 2


# -------------------------------------------------------------- check face

def test_correct_client_green_wrong_client_red(tmp_path: Path) -> None:
    ws = _mk_ws(tmp_path, [CASE_GOOD], None)
    cases = orun.load_cases(ws / "oracle" / "cases")
    good = orun.check_case(cases[0], _load_client(_write_client(ws, GOOD_CLIENT)))
    assert good["status"] == "pass"
    assert good["pending_entries"] == 0
    assert good["instrumented"] is True
    bad = orun.check_case(cases[0], _load_client(_write_client(ws, BAD_CLIENT)))
    assert bad["status"] == "fail"
    assert bad["instrumented"] is True
    # the red verdict must name WHAT mismatched (an actionable oracle face)
    assert any("auth_algo" in f for f in bad["failures"])


def test_no_client_all_pending_never_green(tmp_path: Path) -> None:
    ws = _mk_ws(tmp_path, [CASE_GOOD], None)
    report = orun.run(ws / "oracle" / "cases", None)
    assert report["counts"] == {"red": 0, "green": 0, "pending": 1}
    row = report["cases"]["auth-fields"]
    assert row["status"] == "pending"
    assert row["instrumented"] is False


def test_client_crash_is_pending_not_green(tmp_path: Path) -> None:
    ws = _mk_ws(tmp_path, [CASE_GOOD], None)
    cases = orun.load_cases(ws / "oracle" / "cases")
    row = orun.check_case(cases[0], _load_client(_write_client(ws, CRASH_CLIENT)))
    assert row["status"] == "pending"
    assert row["error"]  # the crash is recorded, not swallowed


def test_pending_observation_entries_count_not_compare(tmp_path: Path) -> None:
    case = {
        "id": "scaffold",
        "params": {},
        "expected": [
            {"field": "auth_algo", "value": "hmac-sha256",
             "pending-observation": True},
            {"field": "nonce_len", "value": 2, "evidence_refs": ["F001"]},
        ],
    }
    ws = _mk_ws(tmp_path, [case], None)
    (ws / "oracle" / "client.py").write_text(GOOD_CLIENT, encoding="utf-8")
    row = orun.check_case(orun.load_cases(ws / "oracle" / "cases")[0],
                          _load_client(ws / "oracle" / "client.py"))
    # observed entry passes, but the scaffold entry is owed: status is
    # pending (unknown is not pass), and pending_entries reports N=1.
    assert row["status"] == "pending"
    assert row["pending_entries"] == 1


# ------------------------------------------------------------------- lint

def test_expected_entry_without_refs_or_pending_refuses(tmp_path: Path) -> None:
    case = {
        "id": "invented",
        "params": {},
        "expected": [{"field": "auth_algo", "value": "guess"}],  # no anchor
    }
    ws = _mk_ws(tmp_path, [case], None)
    with pytest.raises(orun.OracleCaseError) as ei:
        orun.load_cases(ws / "oracle" / "cases")
    assert "auth_algo" in str(ei.value)
    assert "evidence_refs" in str(ei.value)


def test_empty_evidence_refs_also_refuses(tmp_path: Path) -> None:
    case = {
        "id": "empty-refs",
        "params": {},
        "expected": [{"field": "auth_algo", "value": "x",
                      "evidence_refs": []}],
    }
    ws = _mk_ws(tmp_path, [case], None)
    with pytest.raises(orun.OracleCaseError):
        orun.load_cases(ws / "oracle" / "cases")


# --------------------------------------------------------------- mutation

def test_mutation_declared_swap_turns_case_red(tmp_path: Path) -> None:
    ws = _mk_ws(tmp_path, [CASE_GOOD], None)
    compute = _load_client(_write_client(ws, GOOD_CLIENT))
    cases = orun.load_cases(ws / "oracle" / "cases")
    mp = orun.mutation_pass(cases, compute)
    rows = mp["mutations"]["auth-fields"]
    assert rows[0]["field"] == "auth_algo" and rows[0]["kind"] == "swap"
    assert rows[0]["red"] is True
    assert mp["low_discriminativity"] == []


def test_mutation_all_green_case_flagged_low_discriminativity(tmp_path: Path) -> None:
    ws = _mk_ws(tmp_path, [CASE_BLIND], None)
    compute = _load_client(_write_client(ws, BLIND_CLIENT))
    cases = orun.load_cases(ws / "oracle" / "cases")
    assert orun.check_case(cases[0], compute)["status"] == "pass"
    mp = orun.mutation_pass(cases, compute)
    assert mp["low_discriminativity"] == ["blind-spot"]
    assert mp["mutations"]["blind-spot"][0]["red"] is False


def test_mutation_without_declarations_never_flags(tmp_path: Path) -> None:
    case = {k: v for k, v in CASE_GOOD.items() if k != "mutations"}
    ws = _mk_ws(tmp_path, [case], None)
    compute = _load_client(_write_client(ws, GOOD_CLIENT))
    mp = orun.mutation_pass(orun.load_cases(ws / "oracle" / "cases"), compute)
    assert mp["low_discriminativity"] == []
    assert mp["mutations"] == {}


# ------------------------------------------------------- status + ledger IO

def test_status_file_carries_convergence_convention(tmp_path: Path) -> None:
    ws = _mk_ws(tmp_path, [CASE_GOOD, CASE_BLIND], None)
    _write_client(ws, UNIVERSAL_CLIENT, name="client")
    report = orun.run(ws / "oracle" / "cases", ws / "oracle" / "client.py")
    orun.write_status(ws, report)
    doc = json.loads((ws / "runs" / "oracle-status.json").read_text("utf-8"))
    assert doc["schema"] == orun.SCHEMA_ID
    assert doc["cases"]["auth-fields"] == {
        "status": "pass", "pending_entries": 0, "instrumented": True}
    assert set(doc["cases"]["blind-spot"]) == {
        "status", "pending_entries", "instrumented"}


def test_real_verdict_updates_posteriors_ledger(tmp_path: Path) -> None:
    """#106 reuse: a real runner verdict is a Bernoulli observation — the
    ledger's case posterior must move (green -> alpha+1)."""
    ws = _mk_ws(tmp_path, [CASE_GOOD], None)
    _write_client(ws, GOOD_CLIENT, name="client")
    report = orun.run(ws / "oracle" / "cases", ws / "oracle" / "client.py")
    orun.record_posteriors(ws, report)
    led = po.PosteriorLedger.load(ws)
    cp = led.cases["auth-fields"]
    assert cp.alpha == pytest.approx(2.0)
    assert cp.beta == pytest.approx(1.0)
    # a pending verdict is NOT an observation — no ledger write
    report2 = orun.run(ws / "oracle" / "cases", None)
    orun.record_posteriors(ws, report2)
    led2 = po.PosteriorLedger.load(ws)
    assert led2.cases["auth-fields"].alpha == pytest.approx(2.0)


def test_main_end_to_end_writes_status(tmp_path: Path, capsys) -> None:
    ws = _mk_ws(tmp_path, [CASE_GOOD, CASE_BLIND], None)
    _write_client(ws, UNIVERSAL_CLIENT, name="client")
    rc = orun.main([str(ws), "--json", "--mutation"])
    assert rc == 0  # no red cases (the blind spot is flagged, not red)
    doc = json.loads((ws / "runs" / "oracle-status.json").read_text("utf-8"))
    assert doc["counts"] == {"red": 0, "green": 2, "pending": 0}
    assert doc["low_discriminativity"] == ["blind-spot"]
    out = json.loads(capsys.readouterr().out)
    assert out["counts"]["green"] == 2


def test_main_red_case_exit_code(tmp_path: Path) -> None:
    ws = _mk_ws(tmp_path, [CASE_GOOD], None)
    (ws / "oracle" / "client.py").write_text(BAD_CLIENT, encoding="utf-8")
    assert orun.main([str(ws)]) == 1  # red -> rc 1


def test_main_lint_refusal_exit_and_no_status_write(tmp_path: Path) -> None:
    case = {"id": "invented", "params": {},
            "expected": [{"field": "auth_algo", "value": "guess"}]}
    ws = _mk_ws(tmp_path, [case], GOOD_CLIENT)
    assert orun.main([str(ws)]) == 2
    assert not (ws / "runs" / "oracle-status.json").exists()
