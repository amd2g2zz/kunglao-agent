# -*- coding: utf-8 -*-
"""tests/test_bridge_779.py — the credit-into-pool bridge (issue #779
Face 2) and its degeneracy-series contract (Face 2c).

The measured defect (issue #779): claims settled while the strategy
pools starved — zero ``credit_kind=step`` rows, unmatched dispatch
rows, so the sampler's pools stayed at prior while claims reached
terminal. The bridge: at settle, resolve the claim's dispatch
``method_family`` from the method-family-log usage rows keyed by cid
and admit a claim-level ``observe_step_credit`` observation into the
pool with credit = the claim's terminal credit — ONLY when the claim
has no step records AND no banked terminal mass (step-grade stays when
records exist; a matched terminal bank already fed the pool — a second
admission would double-count one observation).

Bridge-produced pool observations must count in the degeneracy series
``rlvr.signal_guard.recent_credits`` monitors: every admission appends
a ``posterior-store/1`` credit row to ``<ws>/runs/posterior-store.jsonl``
(the file the breaker reads), carrying the settled credit and the
resolved family. All fixtures are SYNTHETIC (privacy rule).
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
    if p not in sys.path:
        sys.path.insert(0, p)

from rlvr.signal_guard import recent_credits  # noqa: E402

FAM = "kdf-chain-reconstruction"  # a REGISTERED token (method_families.yaml)


def _ws(tmp_path, claims, name="ws"):
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}), encoding="utf-8")
    # #800 R2: mint real dispatch ids — settle resolves the REAL id
    # from the dispatch ledger (pre-#800 fixtures settle nothing).
    # pending=False: this suite pins the STARVED bridge face (the
    # bank never matched, the claim-level admission feeds the pool).
    from _dispatch_fixture import mint_dispatches

    mint_dispatches(ws, claims, family=FAM, pending=False)
    return ws


def _fact(ws, fid: str, creator: str, status: str = "PROVEN") -> None:
    """One cited fact artifact: terminal status + question-bearing claim
    provenance (the issue-433 citation relation's answers_question leg)
    -> FULL credit for the creator dispatch."""
    (ws / "facts" / f"{fid}.md").write_text(
        f"---\nid: {fid}\ncreator: {creator}\nclaim_id: {creator}\n"
        f"status: {status}\nverify_status: passes\n---\nbody\n",
        encoding="utf-8")


def _claim(cid: str, status: str = "PROVEN") -> dict:
    return {"id": cid, "status": status, "answers_question": "PQ-1",
            "verification": {"method": "reproduction"}}


def _usage_row(ws, cid: str, family: str) -> None:
    """One usage row via THE producer face (the #432 ALLOW-tail append)."""
    import method_families as mf

    mf.append_usage_row(ws, cid, family, "w-test")


def _qcell_rows(ws):
    from rlvr import q_cells

    return q_cells.JSONLQStore(ws).observations()


def _family_mass(ws, family: str) -> tuple[float, float]:
    from rlvr import q_cells

    fold = q_cells.fold(q_cells.default_store(ws))
    return fold.family_mass(family)


def _terminal_credit(ws, cid: str) -> float:
    """The settled ladder value (the round_credit settlement's reward)."""
    from rlvr import ledger as rl

    row = rl.fold(ws, f"round_credit/{cid}")
    assert row is not None and row.get("settlement") is not None
    return float(row["settlement"]["reward"])


# ----------------------------------------------- the bridge admission (2a)


def test_bridge_admits_claim_credit_when_pool_starved(tmp_path):
    """A settled claim with NO step records and NO matchable dispatch row
    gains one claim-level admission into the pool, credit = the terminal
    credit — the pool can no longer starve while claims settle."""
    import settle_round_credit as src

    ws = _ws(tmp_path, [_claim("C-1")])
    _fact(ws, "F-1", "C-1")
    _usage_row(ws, "C-1", FAM)
    out = src.run(ws)
    assert out["settled"] == 1
    credit = _terminal_credit(ws, "C-1")
    assert credit == pytest.approx(1.0)
    steps = [r for r in _qcell_rows(ws)
             if str(r.get("credit_kind") or "") == "step"
             and str(r.get("claim") or "") == "C-1"]
    assert len(steps) == 1, "exactly one bridged admission"
    assert steps[0]["credit"] == pytest.approx(credit)
    assert steps[0]["method_family"] == FAM
    s, f = _family_mass(ws, FAM)
    assert (s, f) == (pytest.approx(credit), pytest.approx(1.0 - credit))
    assert out.get("pool_bridged") == 1


def test_bridge_skips_when_step_records_exist(tmp_path):
    """Step-grade stays when records exist — the bridge never stacks a
    claim-level row on top of step rows (the #712 residual owns it)."""
    import settle_round_credit as src
    from rlvr import q_cells

    ws = _ws(tmp_path, [_claim("C-1")])
    _fact(ws, "F-1", "C-1")
    _usage_row(ws, "C-1", FAM)
    # a pending dispatch row + one banked step record (the dense signal)
    q_cells.record_dispatch_observation(
        ws, "envelope", envelope_meta={"method_family": FAM}, claim="C-1")
    q_cells.observe_step_credit(ws, "C-1", 0.4)
    out = src.run(ws)
    steps = [r for r in _qcell_rows(ws)
             if str(r.get("credit_kind") or "") == "step"
             and str(r.get("claim") or "") == "C-1"]
    assert len(steps) == 1, "the pre-existing step record only"
    assert out.get("pool_bridged") == 0


def test_bridge_skips_when_terminal_mass_already_banked(tmp_path):
    """A matched terminal bank already fed the pool (the #462 W5 solve
    row): bridging again would double-count ONE observation."""
    import claims_store
    import settle_round_credit as src
    from rlvr import q_cells

    ws = _ws(tmp_path, [_claim("C-1")])
    _fact(ws, "F-1", "C-1")
    _usage_row(ws, "C-1", FAM)
    # #800 R2: the pending row carries the REAL dispatch id (the
    # claim-alias shape is gone) — the bank matches under the one key
    did = claims_store.latest_committed_dispatch(
        ws, "C-1")["dispatch_id"]
    q_cells.record_dispatch_observation(
        ws, "envelope", envelope_meta={"method_family": FAM},
        claim="C-1", dispatch_id=did)
    out = src.run(ws)
    credit = _terminal_credit(ws, "C-1")
    steps = [r for r in _qcell_rows(ws)
             if str(r.get("credit_kind") or "") == "step"
             and str(r.get("claim") or "") == "C-1"]
    assert steps == [], "no bridged row on a matched terminal bank"
    s, f = _family_mass(ws, FAM)
    assert (s, f) == (pytest.approx(credit), pytest.approx(1.0 - credit)), \
        "the pool moved EXACTLY once"
    assert out.get("pool_bridged") == 0


def test_bridge_is_idempotent_across_replays(tmp_path):
    """The bridge keys on the FIRST-settlement set: a replay pass admits
    nothing new (the settlement-presence guard is the clock)."""
    import settle_round_credit as src

    ws = _ws(tmp_path, [_claim("C-1")])
    _fact(ws, "F-1", "C-1")
    _usage_row(ws, "C-1", FAM)
    src.run(ws)
    n1 = len(_qcell_rows(ws))
    store1 = _posterior_store_rows(ws)
    src.run(ws)
    assert len(_qcell_rows(ws)) == n1
    assert _posterior_store_rows(ws) == store1


def test_bridge_without_usage_family_records_the_honest_gap(tmp_path):
    """No usage row for the cid: the family resolution is the honest gap
    (empty family) — no pool address exists, so the pool admission is
    refused (never a fabricated bucket), while the settled credit still
    lands in the breaker series (the store row records the empty
    family)."""
    import settle_round_credit as src

    ws = _ws(tmp_path, [_claim("C-1")])
    _fact(ws, "F-1", "C-1")
    out = src.run(ws)
    assert out.get("pool_bridged") == 0
    steps = [r for r in _qcell_rows(ws)
             if str(r.get("credit_kind") or "") == "step"
             and str(r.get("claim") or "") == "C-1"]
    assert steps == [], "no pool admission without a family address"
    rows = [r for r in _posterior_store_rows(ws)
            if str((r.get("provenance") or {}).get("dispatch_id")) == "C-1"]
    assert len(rows) == 1 and rows[0]["credit"] == pytest.approx(
        _terminal_credit(ws, "C-1"))


# ------------------------------- the degeneracy-series contract (2c face)


def _posterior_store_rows(ws: Path) -> list[dict]:
    store = Path(ws) / "runs" / "posterior-store.jsonl"
    if not store.is_file():
        return []
    return [json.loads(ln) for ln in
            store.read_text(encoding="utf-8").splitlines() if ln.strip()]


def test_bridge_appends_credit_row_to_posterior_store(tmp_path):
    """Every bridged admission appends one ``posterior-store/1`` credit
    row to <ws>/runs/posterior-store.jsonl — the file the degeneracy
    breaker and the rl-posterior-moved fingerprint read — carrying the
    settled credit, the step kind and the resolved family."""
    import settle_round_credit as src

    ws = _ws(tmp_path, [_claim("C-1")])
    _fact(ws, "F-1", "C-1")
    _usage_row(ws, "C-1", FAM)
    src.run(ws)
    rows = [r for r in _posterior_store_rows(ws)
            if str((r.get("provenance") or {}).get("dispatch_id")) == "C-1"]
    assert len(rows) == 1
    row = rows[0]
    assert row["schema"] == "posterior-store/1"
    assert row["credit"] == pytest.approx(_terminal_credit(ws, "C-1"))
    assert row["credit_kind"] == "step"
    assert row["method_family"] == FAM
    assert recent_credits(ws, 5) == [pytest.approx(
        float(row["credit"]))]


def test_breaker_freezes_on_degenerate_bridge_traffic(tmp_path):
    """Five identical bridge credits = a dead signal: the NEXT pass
    freezes the posterior-moving legs (case observations AND the bridge)
    and raises the blocker — bridge traffic counts in the series."""
    import settle_round_credit as src

    claims = [_claim(f"C-{i}") for i in range(1, 6)]
    ws = _ws(tmp_path, claims + [_claim("C-6")])
    for i in range(1, 7):
        _fact(ws, f"F-{i}", f"C-{i}")
        _usage_row(ws, f"C-{i}", FAM)
    # pass 1: five full-credit settlements -> five identical 1.0 credits
    ws_claims = yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8"))
    for c in ws_claims["claims"]:
        if c["id"] == "C-6":
            c["status"] = "OPEN"  # settles on pass 2
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(ws_claims), encoding="utf-8")
    out1 = src.run(ws)
    assert out1["settled"] == 5
    assert out1.get("pool_bridged") == 5
    assert recent_credits(ws, 5) == [1.0] * 5
    # pass 2: C-6 turns terminal — the breaker fires BEFORE any leg
    ws_claims = yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8"))
    ws_claims["claims"] = [c for c in ws_claims["claims"]
                           if c["id"] == "C-6"]
    ws_claims["claims"][0]["status"] = "PROVEN"
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(ws_claims), encoding="utf-8")
    logs = ws / "runs" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    out2 = src.run(ws)
    assert out2.get("signal_frozen") is True, out2
    assert out2.get("pool_bridged") == 0, "the frozen pass bridges nothing"
    # the blocker lands on the CURRENT UTC day file — glob the day files,
    # never a hardcoded calendar date (kunglao_log._day_file owns naming)
    rows = [json.loads(ln) for p in sorted(logs.glob("kunglao-*.jsonl"))
            for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert any(r.get("action") == "signal_degenerate" for r in rows)


def test_breaker_stays_cold_on_varied_bridge_traffic(tmp_path):
    """Mixed bridge credits (1.0 / 0.0): distinct >= 2 — no freeze, the
    bridge keeps admitting."""
    import settle_round_credit as src

    ws = _ws(tmp_path, [_claim("C-1", "PROVEN"), _claim("C-2", "REFUTED"),
                        _claim("C-3")])
    _fact(ws, "F-1", "C-1")
    _fact(ws, "F-2", "C-2", status="REFUTED")
    _fact(ws, "F-3", "C-3")
    _usage_row(ws, "C-1", FAM)
    _usage_row(ws, "C-2", FAM)
    _usage_row(ws, "C-3", FAM)
    claims = yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8"))
    claims["claims"] = [c for c in claims["claims"] if c["id"] != "C-3"]
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(claims), encoding="utf-8")
    out1 = src.run(ws)
    assert out1.get("pool_bridged") == 2
    credits = recent_credits(ws, 5)
    assert len(credits) == 2 and len(set(credits)) >= 2
    # pass 2: the third claim settles — no freeze, bridge admits
    claims = yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8"))
    claims["claims"] = [{"id": "C-3", "status": "PROVEN",
                         "answers_question": "PQ-1",
                         "verification": {"method": "reproduction"}}]
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(claims), encoding="utf-8")
    out2 = src.run(ws)
    assert out2.get("signal_frozen") is None
    assert out2.get("pool_bridged") == 1
