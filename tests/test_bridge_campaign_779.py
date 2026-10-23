# -*- coding: utf-8 -*-
"""tests/test_bridge_campaign_779.py — the synthetic campaign replay
(issue #779 acceptance): the win-kdf three-unit ledger shape — three
ladder units (l0/l1/l2) settling in ONE workspace with an armed oracle
net — replayed against the learning→decision bridge.

Four metrics pinned by this module (issue #779 acceptance, mirrored in
docs/architecture/acceptance-bridge.md):

  1. posterior shift > 0 after bridged observations (case Beta moved by
     the settle legs AND q-cell family mass moved by the bridge);
  2. usage rows have sampled_family non-empty;
  3. fingerprint rl-posterior-moved flips green on the bridged
     posterior-store credit rows;
  4. fingerprint rl-sampler-exit flips green on the sampled-exit
     evidence (the gate's strategy-log row through the #496 writer).

Every byte in every fixture is SYNTHETIC — no eval corpus, no real
workspace material (privacy rule; the win-kdf shape is a structural
replay, not the unit data).
"""
from __future__ import annotations

import importlib.util
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

DEVKIT = ROOT / "devkit"
_spec = importlib.util.spec_from_file_location(
    "liveness_gate_779", DEVKIT / "liveness_gate.py")
_lg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_lg)

# the three-unit win-kdf ladder SHAPE: unit id, status, declared family
# (all three registered tokens), linked hypothesis + oracle case
UNITS = (
    ("win-l0", "PROVEN", "crypto-core-identification", "H-l0", "case-l0"),
    ("win-l1", "PROVEN", "kdf-chain-reconstruction", "H-l1", "case-l1"),
    ("win-l2", "REFUTED", "dynamic-trace", "H-l2", "case-l2"),
)


def _fingerprint(ws, fp_id: str) -> tuple[bool, str]:
    fp = next(f for f in _lg.load_fingerprints()["fingerprints"]
              if f["id"] == fp_id)
    return _lg.evaluate_fingerprint(ws, fp)


def _build_campaign_ws(tmp_path):
    """The three-unit campaign workspace: terminal claims (each with a
    cited fact artifact), armed oracle cases (the five arming fields),
    open hypotheses joined to the claims, usage rows per claim — and NO
    q-cell dispatch rows (the starved-campaign shape: the observation
    net missed the dispatches, the claims settled anyway)."""
    import method_families as mf

    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "oracle" / "cases").mkdir(parents=True)
    (ws / "hypotheses").mkdir()
    claims = []
    for uid, status, fam, hid, case_id in UNITS:
        cid = f"C-{uid}"
        claims.append({"id": cid, "status": status,
                       "answers_question": f"PQ-{uid}",
                       "verification": {"method": "reproduction"}})
        (ws / "facts" / f"F-{uid}.md").write_text(
            f"---\nid: F-{uid}\ncreator: {cid}\nclaim_id: {cid}\n"
            f"status: {status}\nverify_status: passes\n---\nsynthetic\n",
            encoding="utf-8")
        (ws / "hypotheses" / f"{hid}.md").write_text(
            f"---\nid: {hid}\nclaim_id: {cid}\n"
            f"competitor_group: pq-PQ-{uid}\ncandidates: [x]\n"
            f"status: open\nschema_rev: 1\n---\nsynthetic\n",
            encoding="utf-8")
        (ws / "oracle" / "cases" / f"{case_id}.yaml").write_text(
            yaml.safe_dump({"id": case_id, "target_pq": f"PQ-{uid}",
                            "channel": "unit",
                            "hypothesis_ref": hid,
                            "update_map": {"green_up": [hid],
                                           "red_up": []},
                            "expected": [
                                {"field": "derived_key",
                                 "value": "synthetic",
                                 "evidence_refs": [
                                     f"facts/F-{uid}.md"]}],
                            "mutations": [{"field": "k", "kind":
                                           "swap"}]}),
            encoding="utf-8")
        mf.append_usage_row(ws, cid, fam, "w-test")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}), encoding="utf-8")
    # #800 R2: ledger rows for every claim (the starved shape is kept —
    # still NO q-cell pending rows; the observation net missed them)
    from _dispatch_fixture import mint_dispatches

    mint_dispatches(ws, claims, pending=False)
    return ws


def _expected_shape_ok(expected) -> bool:
    """The runner's ONE shape law (the arming gate shares it)."""
    from oracle_runner import expected_shape_error

    return expected_shape_error(expected) is None


def _family_mass(ws, family):
    from rlvr import q_cells

    return q_cells.fold(q_cells.default_store(ws)).family_mass(family)


def _store_rows(ws):
    return [json.loads(ln) for ln in
            (ws / "runs" / "posterior-store.jsonl")
            .read_text(encoding="utf-8").splitlines() if ln.strip()]


def _log_sampled_exit(ws, cid: str) -> None:
    """The sampled exit's strategy-log row through the REAL #496
    pass-path writer (the retry's `[strategy sampled]` marker — the
    sampled family became the exit once the case prior fed the draw)."""
    spec = importlib.util.spec_from_file_location(
        "dispatch_gate_779", ROOT / "hooks" / "dispatch_gate.py")
    dg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dg)
    dg._log_strategy_dispatch(ws, cid, "retry declaring the sampled exit "
                              "[strategy sampled]")


def test_expected_shape_is_armed(tmp_path):
    """Sanity: the synthetic case docs carry a runner-valid `expected` —
    the arming gate arms them (the campaign's reward source exists)."""
    import settle_round_credit as src

    ws = _build_campaign_ws(tmp_path)
    for case_path in sorted((ws / "oracle" / "cases").glob("*.yaml")):
        doc = yaml.safe_load(case_path.read_text(encoding="utf-8"))
        assert _expected_shape_ok(doc["expected"])
    assert len(src.armed_case_ids(ws)) == 3


def test_campaign_replay_four_metrics(tmp_path):
    """THE acceptance replay: settle the three-unit campaign, then pin
    the four metrics on the ledger evidence."""
    import posteriors as po
    import settle_round_credit as src
    from rlvr import strategy_store as ss

    ws = _build_campaign_ws(tmp_path)
    out = src.run(ws)
    assert out["settled"] == 3, out
    assert out.get("cases_armed") == 3

    # ---- metric 1: posterior shift > 0 after bridged observations
    led = po.PosteriorLedger.load(ws)
    for _uid, _status, _fam, _hid, case_id in UNITS:
        cp = led.cases.get(case_id)
        assert cp is not None, f"{case_id} never observed"
        assert (cp.alpha - 1.0) + (cp.beta - 1.0) > 0, \
            f"{case_id} posterior never moved"
    bridged_mass = sum(sum(_family_mass(ws, fam))
                       for _u, _s, fam, _h, _c in UNITS)
    assert bridged_mass > 0, "bridged pool mass never moved"

    # ---- metric 2: usage rows have sampled_family non-empty
    import method_families as mf
    view = ss.reconcile_declaration(ws, UNITS[1][2])
    assert view["sampled_family"], "the sampler never exited"
    mf.append_usage_row(ws, "C-win-l1", UNITS[1][2], "w-test",
                        propensity=view.get("propensity"),
                        sampled_family=view.get("sampled_family"),
                        prior_source=view.get("prior_source"))
    assert mf.read_usage(ws)[-1]["sampled_family"]
    # the retry declares the sampled exit; the #496 strategy-log writer
    # lands the row the fingerprint counts (the real pass-path producer)
    _log_sampled_exit(ws, "C-win-l1")

    # ---- metric 3: rl-posterior-moved flips green on bridge rows
    rows = _store_rows(ws)
    assert len(rows) >= 3
    assert all(r["schema"] == "posterior-store/1" for r in rows)
    ok, detail = _fingerprint(ws, "rl-posterior-moved")
    assert ok, detail

    # ---- metric 4: rl-sampler-exit flips green on the sampled exit
    ok, detail = _fingerprint(ws, "rl-sampler-exit")
    assert ok, detail


def test_sampled_exit_row_rides_the_real_writer(tmp_path):
    """The rl-sampler-exit evidence row comes through the #496 strategy
    log writer on the pass path: a retry whose prompt carries the
    sampled-exit marker lands `event=dispatch, strategy=sampled` — the
    exact row the fingerprint counts."""
    ws = _build_campaign_ws(tmp_path)
    _log_sampled_exit(ws, "C-win-l1")
    ok, detail = _fingerprint(ws, "rl-sampler-exit")
    assert ok, detail


def test_campaign_bridge_credits_match_settled_rewards(tmp_path):
    """Counts/credits are never normalized away: every bridged store row
    carries EXACTLY the settled ladder value (the signal contract's
    per-observation clause)."""
    import settle_round_credit as src
    from rlvr import ledger as rl

    ws = _build_campaign_ws(tmp_path)
    src.run(ws)
    store_rows = _store_rows(ws)
    assert len(store_rows) == len(UNITS)
    for uid, _status, fam, _hid, _case in UNITS:
        cid = f"C-{uid}"
        reward = float(rl.fold(ws, f"round_credit/{cid}")
                       ["settlement"]["reward"])
        row = next(r for r in store_rows
                   if str((r.get("provenance") or {}).get("dispatch_id"))
                   == cid)
        assert row["credit"] == pytest.approx(reward)
        assert row["method_family"] == fam
        assert row["credit_kind"] == "step"
