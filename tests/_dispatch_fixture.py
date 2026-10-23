# -*- coding: utf-8 -*-
"""tests/_dispatch_fixture.py — the #800 R2 dispatch-ledger fixture.

Settle-face fixtures mint REAL dispatch ids (dispatch-ledger rows +
q-cell pending observations stamped with the id). A fixture without
ledger rows is a pre-#800 workspace and settles nothing (no-backcompat
ruling 2026-09-01: the compat claim-alias fallback is gone).
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import claims_store  # noqa: E402


def mint_dispatches(ws, claims, family: str = "static_recovery",
                    agent: str = "w-test", pending: bool = True) -> dict:
    """For every claim: OPEN the register, run the dispatch
    transaction (ledger dispatched -> committed), optionally stamp the
    q-cell pending observation with the REAL dispatch id, then restore
    the intended statuses. Returns {claim_id: dispatch_id}.

    pending=False is the STARVED shape (the bridge face's production
    case): the dispatch ledgered but the q-cell observation never
    recorded — the bank finds no match (the honest gap) and the
    claim-level pool bridge admits instead."""
    from rlvr import q_cells

    register = Path(ws) / "claim-register.yaml"
    open_doc = {"claims": [{**c, "status": "OPEN"} for c in claims]}
    register.write_text(yaml.safe_dump(open_doc), encoding="utf-8")
    dids = {}
    for c in claims:
        cid = str(c["id"])
        began = claims_store.begin_dispatch(
            ws, cid, "hook:worker_budget", tier=1, prompt="fixture",
            agent=agent, method_family=family)
        assert began.ok, cid
        assert claims_store.commit_dispatch(ws, cid).ok, cid
        dids[cid] = began.journal_id
    if pending:
        for cid, did in dids.items():
            out = q_cells.record_dispatch_observation(
                ws, "fixture envelope",
                envelope_meta={"method_family": family},
                claim=cid, agent=agent, dispatch_id=did)
            assert out["appended"] is True, cid
    register.write_text(yaml.safe_dump({"claims": claims}),
                        encoding="utf-8")
    return dids


def mint_one(ws, claim: dict, family: str = "static_recovery",
             agent: str = "w-test") -> str:
    """Mint ONE claim's dispatch (OPEN-flip -> transaction -> pending
    row stamped with the real id -> status restore); returns the
    dispatch_id. For fixtures that dispatch mid-test."""
    return mint_dispatches(ws, [claim], family=family,
                           agent=agent)[str(claim["id"])]
