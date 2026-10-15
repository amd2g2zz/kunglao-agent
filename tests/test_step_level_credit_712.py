# -*- coding: utf-8 -*-
"""tests/test_step_level_credit_712.py — step-level ladder credit (#712):
dense reward at step boundaries (TIPS/TRACE-style turn-level credit).

The card's four pins (issue acceptance):

  1. banked at SubagentStop — a step's credit lands in the Q-cell Beta at
     the step boundary, BEFORE claim-terminal (settle -> update -> decide
     now includes the learning update).
  2. O(step) learning — a 10-step rollout produces 10 credit observations
     (and 10 transitions), not 1 claim-terminal signal.
  3. claim-terminal calibration — the residual
     ``ladder_credit - sum(step_credit)`` corrects the cumulative Beta:
     over-credit is clawed back, under-credit is topped up, and the
     post-terminal endpoint equals the step-less (legacy) endpoint —
     dense credit changes the PATH, not the DESTINATION.
  4. evidence-quality weighted — cross-validated=1.0 / unverified=0.3 /
     refuted=0.0 (× source-reliability weight when provenance carries an
     Admiralty credibility letter), never a uniform per-step constant.

Plus the backward-compatibility acceptance: a claim that settles with NO
step credit banks the legacy settlement row byte-identically.

All window arithmetic is explicit (fixture timestamps, settle ``now=``
injection) — no wall-clock sleeps anywhere.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (SCRIPTS, SCRIPTS.parent / "tests", ROOT / "hooks"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from rlvr import incremental_reward as ir  # noqa: E402
from rlvr import q_cells as qc  # noqa: E402
from rlvr import step_grain as sg  # noqa: E402

T0 = datetime(2026, 10, 15, 8, 0, 0, tzinfo=timezone.utc)
FAM = "static-symbolic"


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ws(tmp_path: Path, claims: list[dict]) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}), encoding="utf-8")
    return ws


def _dispatch(ws: Path, claim: str) -> dict:
    """The pending dispatch row (credit=None) the settlement faces match."""
    return qc.record_dispatch_observation(
        ws, "dispatch envelope",
        envelope_meta={"method_family": FAM, "action_type": "dispatch",
                       "context_recipe": "facts_snapshot",
                       "verification_mode": "none", "tier": 0},
        claim=claim)


def _launch(ws: Path, claim: str, ts: datetime) -> None:
    """A launch stash stamped at the fixture time (the window's first
    boundary for step 1 — record_launch writes real-now, we rewrite ts)."""
    doc = ir.record_launch(ws, claim, "static-first")
    assert doc is not None
    p = ws / "runs" / f"dispatch-launch-{claim}.json"
    raw = json.loads(p.read_text(encoding="utf-8"))
    raw["ts"] = _ts(ts)
    p.write_text(json.dumps(raw), encoding="utf-8")


def _fact(ws: Path, name: str, *, status: str, verify_status: str,
          claim_id: str, creator: str | None = None,
          credibility: str | None = None,
          mtime: datetime | None = None) -> Path:
    meta = {
        "id": name,
        "type": "fact",
        "status": status,
        "verify_status": verify_status,
        "claim_id": claim_id,
        "creator": creator if creator is not None else claim_id,
    }
    if credibility:
        meta["provenance"] = [{"role": "sample_raw",
                               "path": "bins/x",
                               "content_sha256": "0" * 64,
                               "credibility": credibility}]
    path = ws / "facts" / f"{name}.md"
    path.write_text(
        "---\n" + yaml.safe_dump(meta, sort_keys=False) + "---\n\nbody\n",
        encoding="utf-8")
    if mtime is not None:
        epoch = mtime.timestamp()
        os.utime(path, (epoch, epoch))
    return path


def _step_rows(ws: Path) -> list[dict]:
    return [r for r in qc.JSONLQStore(ws).observations()
            if r.get("credit_kind") == "step"]


def _calibration_rows(ws: Path) -> list[dict]:
    return [r for r in qc.JSONLQStore(ws).observations()
            if r.get("credit_kind") == "step_calibration"]


def _cell(ws: Path, gamma=1.0):
    """The dispatch-opened cell's counts under the given γ face."""
    disp = next(r for r in qc.JSONLQStore(ws).observations()
                if r.get("source") == "dispatch")
    view = qc.fold(qc.JSONLQStore(ws), gamma=gamma)
    return view.cells[(disp["signature_hash"], disp["arm_key"])]


# ---------------------------------------------- 1. banked at the stop --

def test_step_credit_banked_at_subagent_stop(tmp_path):
    """A step's evidence-quality credit banks into the Q-cell at
    SubagentStop — the row exists BEFORE any claim-terminal settlement,
    so the posterior moves during the rollout, not only at the end."""
    from rlvr import ledger as rl
    ws = _ws(tmp_path, [{"id": "C-71", "status": "IN_PROGRESS"}])
    _dispatch(ws, "C-71")
    _launch(ws, "C-71", ts=T0)
    _fact(ws, "F710-proven", status="PROVEN", verify_status="passes",
          claim_id="C-71", mtime=T0 + timedelta(seconds=9))
    out = sg.settle_step(ws, "sess-a", now=T0 + timedelta(seconds=60))

    rows = _step_rows(ws)
    assert len(rows) == 1, "the step boundary must bank one credit row"
    assert rows[0]["credit"] == pytest.approx(1.0)
    assert rows[0]["source"] == "settlement"
    assert (str(rows[0].get("dispatch_id")) == "C-71"
            or str(rows[0].get("claim")) == "C-71")
    assert (out or {}).get("step_credit") == pytest.approx(1.0)
    # NOT claim-terminal: no round-credit ledger settlement exists yet
    assert rl.fold(ws, "round_credit/C-71") is None, (
        "step credit must land at the stop, before claim-terminal")


# ----------------------------------- 2. O(step) — ten steps, ten signals --

def test_ten_step_rollout_produces_ten_signals(tmp_path):
    """Ten subagent completions produce ten credit observations AND ten
    transitions: the learning signal count is O(steps), never O(claims).
    Each banked step visibly moves the cell's success mass (γ=1 read)."""
    from rlvr import ledger as rl
    ws = _ws(tmp_path, [{"id": "C-72", "status": "IN_PROGRESS"}])
    _dispatch(ws, "C-72")
    successes: list[float] = []
    for k in range(1, 11):
        step_now = T0 + timedelta(seconds=10 * k)
        _launch(ws, "C-72", ts=step_now - timedelta(seconds=5))
        _fact(ws, f"F72{k}-step", status="PROVEN", verify_status="passes",
              claim_id="C-72", mtime=step_now - timedelta(seconds=1))
        sg.settle_step(ws, "sess-b", now=step_now)
        successes.append(_cell(ws).success)

    assert len(_step_rows(ws)) == 10, (
        "a 10-step rollout must produce 10 step_credit observations")
    assert len(ir.read_transitions(ws)) == 10, "one transition per step"
    # O(step): every step moved the Beta (strictly increasing, γ=1)
    assert all(b > a for a, b in zip(successes, successes[1:])), (
        f"success mass must accrue per step, got {successes}")
    assert successes[-1] == pytest.approx(10.0)
    # still before claim-terminal — the dense signals are not one signal
    assert rl.fold(ws, "round_credit/C-72") is None


# ------------------------------- 3. claim-terminal residual correction --

def test_claim_terminal_calibration_corrects_cumulative_beta(tmp_path):
    """At claim-terminal the residual (ladder - Σstep) corrects the
    cumulative Beta in BOTH directions — over-credit clawed back,
    under-credit topped up — and the endpoint equals the step-less
    (legacy) settlement: dense credit changes the path, not the
    destination. Exact at the explicit γ=1 calibration face."""
    from rlvr import scalar
    cited = {"id": "F80-cited", "creator": "C-73", "status": "PROVEN",
             "verify_status": "passes", "cited_by_deliverable": True,
             "answers_question": False, "oracle_backed_refutation": False}

    def _rollout(claim, fact_status, fact_verify, steps):
        ws = _ws(tmp_path / claim, [{"id": claim, "status": "IN_PROGRESS"}])
        _dispatch(ws, claim)
        for k in range(1, steps + 1):
            step_now = T0 + timedelta(seconds=10 * k)
            _launch(ws, claim, ts=step_now - timedelta(seconds=5))
            _fact(ws, f"F8{k}-s", status=fact_status,
                  verify_status=fact_verify, claim_id=claim,
                  mtime=step_now - timedelta(seconds=1))
            sg.settle_step(ws, "sess-c", now=step_now)
        return ws

    # OVER-credit: three cross-validated steps bank Σ=3.0, the ladder
    # settles 1.0 — the terminal row claws back 2.0 (and the failure
    # mass the provisional rows did not carry stays 0).
    ws = _rollout("C-73", "PROVEN", "passes", 3)
    assert _cell(ws).success == pytest.approx(3.0)  # interim inflated
    res = scalar.settle_round_credit(
        ws, [{"dispatch_id": "C-73", "round": 1}], [dict(cited,
                                                         creator="C-73")], [])
    assert res["banked"] == ["C-73"]
    calib = _calibration_rows(ws)
    assert len(calib) == 1, "the first settlement banks ONE calibration row"
    assert calib[0]["credit"] == pytest.approx(-2.0)  # 1.0 - 3.0
    cell = _cell(ws)
    assert cell.success == pytest.approx(1.0)   # cumulative == ladder
    assert cell.failure == pytest.approx(0.0)   # endpoint (1-L) == (0, 0+0)

    # UNDER-credit: one provisional step banks 0.3, the ladder settles
    # 1.0 — the terminal row tops up +0.7 onto the success mass.
    ws2 = _rollout("C-74", "OPEN", "pending", 1)
    assert _cell(ws2).success == pytest.approx(0.3)
    scalar.settle_round_credit(
        ws2, [{"dispatch_id": "C-74", "round": 1}], [dict(cited,
                                                          creator="C-74")], [])
    assert _cell(ws2).success == pytest.approx(1.0)
    assert _cell(ws2).failure == pytest.approx(0.0)  # 0.7 failure washed

    # REFUTED terminal: cross-validated steps banked 2.0 but the claim
    # settles 0 (no cited artifact) — full clawback to the (0, 1) endpoint.
    ws3 = _rollout("C-75", "PROVEN", "passes", 2)
    scalar.settle_round_credit(
        ws3, [{"dispatch_id": "C-75", "round": 1}], [], [])
    assert _cell(ws3).success == pytest.approx(0.0)
    assert _cell(ws3).failure == pytest.approx(1.0)


def test_backward_compatible_settlement_without_step_credit(tmp_path):
    """A claim that settles with NO step credit (any claim settling
    before this change) takes the legacy face: no credit_kind column on
    the settlement row, and the folded endpoint is the pre-#712
    (L, 1-L)."""
    from rlvr import scalar
    ws = _ws(tmp_path, [{"id": "C-76", "status": "IN_PROGRESS"}])
    _dispatch(ws, "C-76")
    cited = {"id": "F86-cited", "creator": "C-76", "status": "PROVEN",
             "verify_status": "passes", "cited_by_deliverable": True,
             "answers_question": False, "oracle_backed_refutation": False}
    res = scalar.settle_round_credit(
        ws, [{"dispatch_id": "C-76", "round": 1}], [cited], [])
    assert res["banked"] == ["C-76"]
    assert not _calibration_rows(ws), "no step rows -> no calibration row"
    rows = [r for r in qc.JSONLQStore(ws).observations()
            if r.get("source") == "settlement"]
    assert len(rows) == 1
    assert "credit_kind" not in rows[0], "legacy settlement row shape"
    assert rows[0]["credit"] == pytest.approx(1.0)
    cell = _cell(ws)
    assert cell.success == pytest.approx(1.0)
    assert cell.failure == pytest.approx(0.0)


def test_terminal_endpoint_is_independent_of_step_count(tmp_path):
    """The path/destination invariant: the SAME claim outcome settles to
    the SAME cell endpoint whether it took three banked steps or none —
    calibration exists so dense credit never shifts the end state."""
    from rlvr import scalar
    cited = {"id": "F88-cited", "status": "PROVEN", "verify_status": "passes",
             "cited_by_deliverable": True, "answers_question": False,
             "oracle_backed_refutation": False}

    # stepped: three provisional (0.3) steps then a full settlement
    ws = _ws(tmp_path / "stepped", [{"id": "C-77", "status": "IN_PROGRESS"}])
    _dispatch(ws, "C-77")
    for k in range(1, 4):
        step_now = T0 + timedelta(seconds=10 * k)
        _launch(ws, "C-77", ts=step_now - timedelta(seconds=5))
        _fact(ws, f"F77{k}-s", status="OPEN", verify_status="pending",
              claim_id="C-77", mtime=step_now - timedelta(seconds=1))
        sg.settle_step(ws, "sess-d", now=step_now)
    scalar.settle_round_credit(
        ws, [{"dispatch_id": "C-77", "round": 1}],
        [dict(cited, creator="C-77")], [])

    # step-less twin: same ladder, zero steps
    ws2 = _ws(tmp_path / "plain", [{"id": "C-78", "status": "IN_PROGRESS"}])
    _dispatch(ws2, "C-78")
    scalar.settle_round_credit(
        ws2, [{"dispatch_id": "C-78", "round": 1}],
        [dict(cited, creator="C-78")], [])

    a, b = _cell(ws), _cell(ws2)
    assert a.success == pytest.approx(b.success)
    assert a.failure == pytest.approx(b.failure)


def test_calibration_never_claws_back_band_valued_steps(tmp_path):
    """D-678.4a × #712 (the independent-review finding): a step whose
    credit lands in the observation band (0, 0.05] adds NO fold mass, so
    the residual must not claw it back — the operand counts the fold's
    mass view only. A 0.05-credit step then a full ladder settles to
    the (1, 0) endpoint; the raw-sum operand would land (0.95, −0.95)."""
    from rlvr import scalar
    ws = _ws(tmp_path, [{"id": "C-81", "status": "IN_PROGRESS"}])
    _dispatch(ws, "C-81")
    _launch(ws, "C-81", ts=T0)
    # one band-valued evidence mix: unverified@F6 (0.15) + two refuted
    # (0.0) -> mean 0.05 — inside the information-option band
    _fact(ws, "F810-band", status="OPEN", verify_status="pending",
          claim_id="C-81", credibility="F6",
          mtime=T0 + timedelta(seconds=9))
    _fact(ws, "F811-ref", status="REFUTED", verify_status="passes",
          claim_id="C-81", mtime=T0 + timedelta(seconds=9))
    _fact(ws, "F812-ref", status="REFUTED", verify_status="passes",
          claim_id="C-81", mtime=T0 + timedelta(seconds=9))
    out = sg.settle_step(ws, "sess-f", now=T0 + timedelta(seconds=60))
    assert (out or {}).get("step_credit") == pytest.approx(0.05)
    assert _cell(ws).success == pytest.approx(0.0)  # band: no mass banked
    cited = {"id": "F813-cited", "creator": "C-81", "status": "PROVEN",
             "verify_status": "passes", "cited_by_deliverable": True,
             "answers_question": False, "oracle_backed_refutation": False}
    scalar.settle_round_credit(
        ws, [{"dispatch_id": "C-81", "round": 1}], [cited], [])
    cell = _cell(ws)
    assert cell.success == pytest.approx(1.0)
    assert cell.failure == pytest.approx(0.0)


# ------------------------------- 4. evidence-quality weighted (non-uniform) --

def test_step_credit_weighted_by_evidence_quality(tmp_path):
    """step_credit = f(evidence_quality, verification_status): the three
    anchors (cross-validated 1.0 / unverified 0.3 / refuted 0.0), the
    empty-evidence provisional floor, source-reliability weighting, and
    the claim+window scoping that keeps foreign/stale facts out."""
    from rlvr import step_credit as sc

    proven = {"status": "PROVEN", "verify_status": "passes"}
    pending = {"status": "OPEN", "verify_status": "pending"}
    refuted = {"status": "REFUTED", "verify_status": "passes"}

    assert sc.step_credit([proven]) == pytest.approx(1.0)
    assert sc.step_credit([pending]) == pytest.approx(0.3)
    assert sc.step_credit([refuted]) == pytest.approx(0.0)
    assert sc.step_credit([]) == pytest.approx(0.3), (
        "a step with no evidence banks the provisional floor, never 0")
    # non-uniform: mixes grade between the anchors
    assert sc.step_credit([proven, refuted]) == pytest.approx(0.5)
    assert sc.step_credit([proven, proven, pending]) == pytest.approx(
        (2.0 + 0.3) / 3)
    # source_reliability weighting (ICD-203 Admiralty letter, if available)
    b_credible = dict(proven, provenance=[{"credibility": "B2"}])
    assert sc.step_credit([b_credible]) == pytest.approx(0.9)
    f_credible = dict(proven, provenance=[{"credibility": "F6"}])
    assert sc.step_credit([f_credible]) == pytest.approx(0.5)
    # verification status dominates the letter
    assert sc.step_credit([dict(refuted,
                                provenance=[{"credibility": "A1"}])]
                          ) == pytest.approx(0.0)

    # window + claim scoping through the settle face
    ws = _ws(tmp_path, [{"id": "C-79", "status": "IN_PROGRESS"}])
    _dispatch(ws, "C-79")
    _launch(ws, "C-79", ts=T0)
    _fact(ws, "F790-mine", status="PROVEN", verify_status="passes",
          claim_id="C-79", mtime=T0 + timedelta(seconds=9))       # in
    _fact(ws, "F791-foreign", status="PROVEN", verify_status="passes",
          claim_id="C-999", mtime=T0 + timedelta(seconds=9))      # other claim
    _fact(ws, "F792-stale", status="PROVEN", verify_status="passes",
          claim_id="C-79", mtime=T0 - timedelta(seconds=60))      # before window
    items = sc.evidence_in_window(ws, claim="C-79", since_ts=_ts(T0),
                                  until=T0 + timedelta(seconds=60))
    assert [i["id"] for i in items] == ["F790-mine"]
    # the graded settle path is non-uniform across evidence classes
    ws2 = _ws(tmp_path / "graded", [{"id": "C-80", "status": "IN_PROGRESS"}])
    _dispatch(ws2, "C-80")
    _launch(ws2, "C-80", ts=T0)
    _fact(ws2, "F800-refuted", status="REFUTED", verify_status="passes",
          claim_id="C-80", mtime=T0 + timedelta(seconds=9))
    out = sg.settle_step(ws2, "sess-e", now=T0 + timedelta(seconds=60))
    assert (out or {}).get("step_credit") == pytest.approx(0.0)
    assert _step_rows(ws2)[0]["credit"] == pytest.approx(0.0)
