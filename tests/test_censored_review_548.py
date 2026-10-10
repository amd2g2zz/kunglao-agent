# -*- coding: utf-8 -*-
"""Issue 548 — the censored-outcome review face over the transition ledger.

Question (issue 548): does "timeout banks as failure" punish slow-but-
correct arms? The review buckets per-family settlements into
censored-with-facts vs clean-failure and asks whether the punishment
tracks Φ movement (unfair) or wall time only (fair). Synthetic pins:

  1. censored acts that moved Φ while the posterior banked half-credit
     → verdict "unfair", with the numbers in the report;
  2. censored acts with zero Φ movement → verdict "fair";
  3. empty ledgers → an honest empty report;
  4. malformed rows are skipped AND counted, never silently dropped;
  5. the Kaplan-Meier posterior face joins the sibling audit stream.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rlvr import censored_review as cr  # noqa: E402


# ---- fixtures ---------------------------------------------------------------

def _row(claim: str, family: str, status: str, *, facts: int = 0,
         phi_before: float = 0.0, phi_after: float = 0.0,
         r_incr: float = 0.0, credit: float | None = 0.0,
         censored: bool | None = None) -> dict:
    row = {
        "ts": "2026-10-07T00:00:00Z",
        "dispatch_id": claim,
        "s": "",
        "a": family,
        "o": {"status": status, "class": "", "facts": facts},
        "s_prime_phi": phi_after,
        "phi_before": phi_before,
        "r_incr": r_incr,
        "r_settle": credit,
        "done": False,
    }
    if censored is not None:
        row["censored"] = censored
    return row


def _write_ws(tmp_path: Path, name: str, lines: list[str]) -> Path:
    """One workspace whose runs/transitions.jsonl holds exactly `lines`."""
    ws = tmp_path / name
    runs = ws / "runs"
    runs.mkdir(parents=True)
    (runs / "transitions.jsonl").write_text(
        "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return ws


def _unfair_workspace(tmp_path: Path) -> Path:
    """Censored acts carried real Φ movement (0 → 0.4) while the posterior
    banked half-credit; clean failures moved nothing and banked zero."""
    fam = "rust-apk-beacon"
    lines = [
        json.dumps(_row(f"C-{i:03d}", fam, "TIMEOUT", facts=4,
                        phi_after=0.4, r_incr=0.3, credit=0.5))
        for i in range(3)
    ] + [
        json.dumps(_row(f"E-{i:03d}", fam, "ERROR", facts=0,
                        r_incr=-0.05, credit=0.0))
        for i in range(3)
    ]
    return _write_ws(tmp_path, "ws-unfair", lines)


def _fair_workspace(tmp_path: Path) -> Path:
    """Censored acts show zero Φ movement — punishment tracks time only."""
    fam = "hypothesis-falsification"
    lines = [
        json.dumps(_row(f"C-{i:03d}", fam, "TIMEOUT", facts=5,
                        credit=0.5))
        for i in range(3)
    ] + [
        json.dumps(_row(f"E-{i:03d}", fam, "ERROR", facts=0,
                        credit=0.0))
        for i in range(3)
    ]
    return _write_ws(tmp_path, "ws-fair", lines)


# ---- face 1: the verdict ----------------------------------------------------

def test_unfair_verdict_when_censored_acts_moved_phi(tmp_path):
    ws = _unfair_workspace(tmp_path)
    report = cr.review([ws])
    fam = report["families"]["rust-apk-beacon"]
    assert fam["verdict"] == "unfair"
    basis = fam["verdict_basis"]
    assert basis["censored_mean_phi_delta"] == 0.4
    assert basis["clean_failure_mean_phi_delta"] == 0.0
    assert basis["censored_mean_credit"] == 0.5
    cens = fam["censored_with_facts"]
    assert cens["count"] == 3
    assert cens["mean_phi_delta"] == 0.4
    assert cens["mean_credit"] == 0.5
    assert cens["mean_r_incr"] == 0.3
    clean = fam["clean_failure"]
    assert clean["count"] == 3
    assert clean["mean_credit"] == 0.0


def test_fair_verdict_when_censored_phi_is_zero(tmp_path):
    ws = _fair_workspace(tmp_path)
    report = cr.review([ws])
    fam = report["families"]["hypothesis-falsification"]
    assert fam["verdict"] == "fair"
    assert fam["verdict_basis"]["censored_mean_phi_delta"] == 0.0


def test_fair_when_phi_signal_exists_but_margin_not_met(tmp_path):
    """Φ moved a little in both buckets — the gap carries no signal."""
    fam = "sf-symbolic"
    lines = [
        json.dumps(_row(f"C-{i:03d}", fam, "TIMEOUT", facts=2,
                        phi_after=0.06, credit=0.5))
        for i in range(3)
    ] + [
        json.dumps(_row(f"E-{i:03d}", fam, "ERROR", facts=0,
                        phi_after=0.05, credit=0.0))
        for i in range(3)
    ]
    ws = _write_ws(tmp_path, "ws-margin", lines)
    fam_entry = cr.review([ws])["families"][fam]
    assert fam_entry["verdict"] == "fair"


def test_underpowered_verdict_below_min_bucket_rows(tmp_path):
    fam = "thin-family"
    lines = [json.dumps(_row("C-001", fam, "TIMEOUT", facts=4,
                             phi_after=0.4, credit=0.5))]
    ws = _write_ws(tmp_path, "ws-thin", lines)
    fam_entry = cr.review([ws])["families"][fam]
    assert fam_entry["verdict"] == "underpowered"
    assert fam_entry["censored_with_facts"]["count"] == 1
    assert fam_entry["clean_failure"]["count"] == 0
    assert fam_entry["clean_failure"]["mean_credit"] is None


def test_success_rows_stay_out_of_the_failure_buckets(tmp_path):
    fam = "static-xref"
    lines = [
        json.dumps(_row("S-001", fam, "DISPATCHED", facts=3,
                        phi_after=0.2, credit=1.0)),
        json.dumps(_row("C-001", fam, "TIMEOUT", facts=2, credit=0.5)),
    ]
    ws = _write_ws(tmp_path, "ws-success", lines)
    fam_entry = cr.review([ws])["families"][fam]
    assert fam_entry["success"]["count"] == 1
    assert fam_entry["success"]["mean_credit"] == 1.0
    assert fam_entry["censored_with_facts"]["count"] == 1
    assert fam_entry["clean_failure"]["count"] == 0


def test_explicit_censored_field_wins_over_status_derivation(tmp_path):
    """A row carrying its own `censored` flag beats the TIMEOUT derivation
    (the producer's flag is authoritative when present)."""
    fam = "flagged-family"
    lines = [
        json.dumps(_row("C-001", fam, "TIMEOUT", facts=4, credit=0.5,
                        censored=False)),
        json.dumps(_row("E-001", fam, "ERROR", facts=0, credit=0.0)),
    ]
    ws = _write_ws(tmp_path, "ws-flag", lines)
    fam_entry = cr.review([ws])["families"][fam]
    # not censored by its own flag → falls into the clean-failure bucket
    assert fam_entry["censored_with_facts"]["count"] == 0
    assert fam_entry["clean_failure"]["count"] == 2


# ---- face 2: the ledger scan ------------------------------------------------

def test_empty_ledger_gives_empty_report(tmp_path):
    ws_empty_file = _write_ws(tmp_path, "ws-empty", [])
    report = cr.review([ws_empty_file])
    assert report["schema"] == "censored-review/1"
    assert report["families"] == {}
    assert report["rows_total"] == 0
    assert report["files_scanned"] == 1

    ws_missing = tmp_path / "ws-missing"
    ws_missing.mkdir()
    report2 = cr.review([ws_missing])
    assert report2["families"] == {}
    assert report2["files_scanned"] == 0


def test_malformed_rows_skipped_and_counted(tmp_path):
    fam = "messy-family"
    good = json.dumps(_row("C-001", fam, "TIMEOUT", facts=4,
                           phi_after=0.4, credit=0.5))
    raw_lines = [
        good,
        "this is not json",
        "{broken json",
        "[]",
        "42",
        json.dumps({"ts": "2026-10-07T00:00:00Z", "dispatch_id": "X-001"}),
    ]
    ws = _write_ws(tmp_path, "ws-messy", raw_lines)
    report = cr.review([ws])
    assert report["rows_total"] == 1
    assert report["skipped_malformed"] == 5
    fam_entry = report["families"][fam]
    assert fam_entry["censored_with_facts"]["count"] == 1


def test_non_settlement_rows_counted_separately(tmp_path):
    fam = "pending-family"
    lines = [
        json.dumps(_row("C-001", fam, "TIMEOUT", facts=4, credit=None)),
        json.dumps(_row("E-001", fam, "ERROR", facts=0, credit=0.0)),
    ]
    ws = _write_ws(tmp_path, "ws-pending", lines)
    report = cr.review([ws])
    assert report["rows_non_settlement"] == 1
    assert report["rows_settlement"] == 1
    # the unsettled row never inflates a bucket
    assert report["families"][fam]["censored_with_facts"]["count"] == 0


def test_multi_workspace_aggregation(tmp_path):
    fam = "shared-family"
    ws_a = _write_ws(tmp_path, "ws-a", [
        json.dumps(_row("C-001", fam, "TIMEOUT", facts=4, credit=0.5)),
    ])
    ws_b = _write_ws(tmp_path, "ws-b", [
        json.dumps(_row("C-002", fam, "TIMEOUT", facts=2, credit=0.5)),
        json.dumps(_row("E-001", fam, "ERROR", facts=0, credit=0.0)),
    ])
    report = cr.review([ws_a, ws_b])
    assert report["files_scanned"] == 2
    fam_entry = report["families"][fam]
    assert fam_entry["censored_with_facts"]["count"] == 2
    assert fam_entry["clean_failure"]["count"] == 1


# ---- face 3: the Kaplan-Meier posterior join --------------------------------

def test_km_posterior_join_from_audit_stream(tmp_path):
    fam = "rust-apk-beacon"
    ws = _write_ws(tmp_path, "ws-km", [
        json.dumps(_row("C-001", fam, "TIMEOUT", facts=4, credit=0.5)),
    ])
    logs = ws / "runs" / "logs"
    logs.mkdir(parents=True)
    audit_rows = [
        {"action": "posterior_updated", "claim": None,
         "detail": {"cell": fam, "counts": {"credit": 0.5,
                                            "censored": True,
                                            "facts_citing": 4}}},
        {"action": "posterior_updated", "claim": None,
         "detail": json.dumps({"cell": fam,
                               "counts": {"credit": 1.0,
                                          "censored": False,
                                          "facts_citing": 5}})},
        {"action": "dispatch_result", "detail": {"rc": 0}},
        {"action": "posterior_updated",
         "detail": "{not parseable"},
    ]
    (logs / "e2e-audit.jsonl").write_text(
        "\n".join(json.dumps(r) for r in audit_rows) + "\n",
        encoding="utf-8")
    report = cr.review([ws])
    km = report["families"][fam]["km_posterior"]
    assert km["rows"] == 2
    assert km["censored_true"] == 1
    assert km["censored_false"] == 1
    assert km["mean_credit_censored"] == 0.5
    assert km["mean_credit_observed"] == 1.0


def test_km_face_absent_without_audit_stream(tmp_path):
    ws = _fair_workspace(tmp_path)
    fam_entry = cr.review([ws])["families"]["hypothesis-falsification"]
    assert fam_entry["km_posterior"]["rows"] == 0
    assert fam_entry["km_posterior"]["censored_true"] == 0


# ---- face 4: the CLI ---------------------------------------------------------

def test_main_prints_report_and_json_flag_writes_file(tmp_path, capsys):
    ws = _unfair_workspace(tmp_path)
    out = tmp_path / "report.json"
    rc = cr.main([str(ws), "--json", str(out)])
    assert rc == 0
    stdout_report = json.loads(capsys.readouterr().out)
    assert stdout_report["schema"] == "censored-review/1"
    assert "rust-apk-beacon" in stdout_report["families"]
    assert out.is_file()
    file_report = json.loads(out.read_text(encoding="utf-8"))
    assert file_report == stdout_report


def test_find_transition_files_requires_runs_component(tmp_path):
    hits = _write_ws(tmp_path, "ws-find", [])
    stray = tmp_path / "loose"
    stray.mkdir()
    (stray / "transitions.jsonl").write_text("", encoding="utf-8")
    found = cr.find_transition_files([tmp_path])
    assert found == [hits / "runs" / "transitions.jsonl"]
