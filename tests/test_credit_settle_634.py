# -*- coding: utf-8 -*-
"""tests/test_credit_settle_634.py — the live round-credit settlement CLI
(#634): assembly from terminal claims + fact artifacts, the dry-run face,
idempotency at any wall-clock distance, and the Q-cell bank ride-through.

Fixtures are SYNTHETIC (no workspace data)."""
from __future__ import annotations

import yaml


def _ws(tmp_path, claims):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}), encoding="utf-8")
    return ws


def test_no_terminal_claims_is_a_quiet_noop(tmp_path):
    import settle_round_credit as src
    ws = _ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    out = src.run(ws)
    assert out["settled"] == 0 and "nothing to settle" in out["reason"]


def test_settlement_banks_the_pending_dispatch_row(tmp_path):
    import settle_round_credit as src
    from rlvr import q_cells
    ws = _ws(tmp_path, [{"id": "C-9", "status": "REFUTED"}])
    q_cells.record_dispatch_observation(
        ws, "dispatch envelope",
        envelope_meta={"method_family": "static-symbolic"}, claim="C-9")
    out = src.run(ws)
    assert out["settled"] == 1 and out["rounds"] == 1
    rows = q_cells.JSONLQStore(ws).observations()
    banked = [r for r in rows if r.get("source") == "settlement"]
    assert len(banked) == 1
    assert banked[0]["dispatch_id"] == "C-9"
    assert banked[0]["credit"] is not None


def test_idempotent_second_pass_appends_nothing(tmp_path):
    import settle_round_credit as src
    from rlvr import q_cells
    ws = _ws(tmp_path, [{"id": "C-9", "status": "REFUTED"}])
    q_cells.record_dispatch_observation(
        ws, "dispatch envelope",
        envelope_meta={"method_family": "static-symbolic"}, claim="C-9")
    src.run(ws)
    n1 = len(q_cells.JSONLQStore(ws).observations())
    src.run(ws)
    n2 = len(q_cells.JSONLQStore(ws).observations())
    assert n2 == n1  # identity-ts freeze + settlement-presence guard


def test_dry_run_never_writes(tmp_path):
    import settle_round_credit as src
    from rlvr import q_cells
    ws = _ws(tmp_path, [{"id": "C-9", "status": "REFUTED"}])
    q_cells.record_dispatch_observation(
        ws, "dispatch envelope",
        envelope_meta={"method_family": "static-symbolic"}, claim="C-9")
    out = src.run(ws, dry_run=True)
    assert out["dry_run"] is True and out["would_settle"] == 1
    rows = q_cells.JSONLQStore(ws).observations()
    assert rows and all(r.get("source") == "dispatch" for r in rows)
