# -*- coding: utf-8 -*-
"""tests/test_case_amendment_742.py — the case posterior tracks the
register (issue 742).

The case-posterior observation pair (case_id, claim_id) is observed
ONCE (issue 730): the case-observation ledger row IS the dedup record, and
``CasePosterior.update`` is a pure +1 conjugate. When a claim's settled
outcome is later CORRECTED (evidence flips PROVEN→REFUTED), the ledger
serves the corrected value to nothing — the belief keeps the first
outcome forever, and ``priority_ratio`` Thompson-prices dispatchable
claims from exactly that stale belief.

The fix mirrors the credit-amendment shape for the pair grain:

  - a ``case-amendment/1`` row (append-only, same experience family)
    records the flip {from_passed, to_passed, d_alpha, d_beta} — the
    original case-observation/1 row stays byte-untouched as history;
  - ``reconcile_case_settlements`` folds BOTH stamps (last-amendment-
    wins) into the pair's effective outcome, compares it with the
    claim's CURRENT decisive register status, and applies a ±1 flip to
    the belief — belief-first, floored at the Beta(1,1) support so a
    desynced ledger can never push the posterior outside its support;
  - idempotence lives in the fold: once the row lands the effective
    outcome equals the target and every re-run is a read-scan no-op;
  - honest gaps: a non-decisive terminal, a removed claim, a retired
    case, an unobserved pair — none fabricates a correction.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import settle_round_credit as src  # noqa: E402
from rlvr import consolidated_ledger as cl  # noqa: E402


# ---------- fixtures --------------------------------------------------------

def _ws(tmp_path: Path, claims: list[dict]) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True),
        encoding="utf-8")
    return ws


def _arm_case(ws: Path, cid: str, pq: str) -> None:
    cdir = ws / "oracle" / "cases"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / f"{cid}.yaml").write_text(yaml.safe_dump({
        "id": cid,
        "channel": "probe",
        "target_pq": pq,
        "hypothesis_ref": "H-001",
        "update_map": {"red_up": ["H-002"]},
        "expected": [{"field": "probe", "value": "observed",
                      "evidence_refs": ["E-001"]}],
        "mutations": [{"kind": "omit", "target": "E-001"}],
    }), encoding="utf-8")


def _observe(ws: Path, cid: str, claim: str, passed: bool) -> None:
    """Drive the production first-observation face directly for setup."""
    src._apply_case_observations(ws, [(cid, claim, passed)], source="fresh")


def _belief(ws: Path, cid: str) -> tuple[float, float]:
    import posteriors as po
    led = po.PosteriorLedger.load(ws)
    cp = led.cases.get(cid)
    return (cp.alpha, cp.beta) if cp else (1.0, 1.0)


def _amendment_rows(ws: Path) -> list[dict]:
    return cl.read(ws, "experience", schema_prefix="case-amendment")


def _observation_rows(ws: Path) -> list[dict]:
    return cl.read(ws, "experience", schema_prefix="case-observation")


# ---------- 1. the defect: the flip reaches the belief ----------------------

def test_outcome_flip_amends_the_pair_once(tmp_path):
    """PROVEN→REFUTED: the first outcome's alpha is clawed back and the
    failure mass lands — exactly once; the re-run is a no-op."""
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    assert _belief(ws, "case-q2") == (2.0, 1.0)

    # the correction: the register status flips
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-1", "status": "REFUTED",
                                    "answers_question": "q2"}]}),
        encoding="utf-8")
    out = src.reconcile_case_settlements(ws)
    assert out["case_amendments"] == 1, out
    assert _belief(ws, "case-q2") == (1.0, 2.0)

    rows = _amendment_rows(ws)
    assert len(rows) == 1
    assert rows[0]["from_passed"] is True
    assert rows[0]["to_passed"] is False
    assert rows[0]["source"] == "reconcile"

    # converged: a re-run appends nothing
    again = src.reconcile_case_settlements(ws)
    assert again["case_amendments"] == 0, again
    assert len(_amendment_rows(ws)) == 1


def test_within_class_status_change_writes_nothing(tmp_path):
    """PROVEN→VERIFIED is the same polarity — no flip, no row."""
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-1", "status": "VERIFIED",
                                    "answers_question": "q2"}]}),
        encoding="utf-8")
    out = src.reconcile_case_settlements(ws)
    assert out["case_amendments"] == 0, out
    assert _amendment_rows(ws) == []
    assert _belief(ws, "case-q2") == (2.0, 1.0)


# ---------- 2. honest gaps ---------------------------------------------------

def test_non_decisive_terminal_is_not_a_target(tmp_path):
    """STALE says nothing about the case — the observation stands."""
    ws = _ws(tmp_path, [{"id": "C-1", "status": "REFUTED",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", False)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-1", "status": "STALE",
                                    "answers_question": "q2"}]}),
        encoding="utf-8")
    out = src.reconcile_case_settlements(ws)
    assert out["case_amendments"] == 0, out
    assert _amendment_rows(ws) == []


def test_removed_claim_is_not_a_target(tmp_path):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "REFUTED",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", False)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": []}), encoding="utf-8")
    out = src.reconcile_case_settlements(ws)
    assert out["case_amendments"] == 0, out
    assert _amendment_rows(ws) == []


def test_retired_case_is_not_a_target(tmp_path):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "REFUTED",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", False)
    (ws / "oracle" / "cases" / "case-q2.yaml").write_text(
        yaml.safe_dump({"id": "case-q2", "status": "retired",
                        "target_pq": "q2"}), encoding="utf-8")
    out = src.reconcile_case_settlements(ws)
    assert out["case_amendments"] == 0, out
    assert _amendment_rows(ws) == []


def test_unobserved_pair_is_the_fresh_legs_job(tmp_path):
    """A pair with no observation row is not the reconcile's surface —
    the fresh/late legs keep their semantics byte-identically."""
    ws = _ws(tmp_path, [{"id": "C-1", "status": "REFUTED",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    out = src.reconcile_case_settlements(ws)
    assert out["case_amendments"] == 0, out
    assert _observation_rows(ws) == []


# ---------- 3. the record stays history --------------------------------------

def test_original_observation_rows_are_byte_untouched(tmp_path):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    before = _observation_rows(ws)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-1", "status": "REFUTED",
                                    "answers_question": "q2"}]}),
        encoding="utf-8")
    src.reconcile_case_settlements(ws)
    assert _observation_rows(ws) == before      # append-only wall holds


# ---------- 4. the runner-banked mass survives ------------------------------

def test_delta_composes_with_runner_banked_mass(tmp_path):
    """The runner face banks extra mass without ledger rows; the
    amendment is a DELTA on the accumulator, never a yaml-wide
    recompute — the runner's contribution must survive the flip."""
    import posteriors as po
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    # the offline runner face tops the case up (its own report rows)
    led = po.PosteriorLedger.load(ws)
    cp = led.cases["case-q2"]
    cp.update(True)
    led.cases["case-q2"] = cp
    led.save(ws)
    assert _belief(ws, "case-q2") == (3.0, 1.0)

    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-1", "status": "REFUTED",
                                    "answers_question": "q2"}]}),
        encoding="utf-8")
    src.reconcile_case_settlements(ws)
    assert _belief(ws, "case-q2") == (2.0, 2.0)   # 3-1 / 1+1: delta, not reset


# ---------- 5. the belief-first refusal is loud -----------------------------

def test_row_refusal_surfaces_in_the_error_field(tmp_path, monkeypatch):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-1", "status": "REFUTED",
                                    "answers_question": "q2"}]}),
        encoding="utf-8")

    import rlvr.consolidated_ledger as _cl
    real_append = _cl.append
    monkeypatch.setattr(_cl, "append",
                        lambda *a, **k: real_append(*a, **k) and False)
    out = src.reconcile_case_settlements(ws)
    assert out.get("case_amendments_error"), out
    assert out["case_amendments"] == 0


# ---------- 6. the pass wires the leg ---------------------------------------

def test_run_surfaces_an_errored_reconcile_without_crashing(
        tmp_path, monkeypatch):
    """The reviewer's CI-blind spot: a refused amendment row driven
    through run() itself — the tick must surface the error field, never
    crash (the tick-must-not-die contract)."""
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-1", "status": "REFUTED",
                                    "answers_question": "q2"}]}),
        encoding="utf-8")

    import rlvr.consolidated_ledger as _cl
    real_append = _cl.append
    monkeypatch.setattr(_cl, "append",
                        lambda *a, **k: real_append(*a, **k) and False)
    out = src.run(ws)
    assert out.get("case_amendments") == 0
    assert out.get("case_observations_error"), out


def test_run_wires_the_reconcile_leg(tmp_path):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "REFUTED",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", False)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-1", "status": "PROVEN",
                                    "answers_question": "q2"}]}),
        encoding="utf-8")
    out = src.run(ws)
    assert out.get("case_amendments") == 1, out
    rows = _amendment_rows(ws)
    assert rows and rows[0]["to_passed"] is True
