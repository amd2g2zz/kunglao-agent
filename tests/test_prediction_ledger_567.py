# -*- coding: utf-8 -*-
"""tests/test_prediction_ledger_567.py — the prediction ledger (#567).

Delayed settlement for unverifiable-now assertions: a claim attaches
falsifiable predictions with non-trivial prior uncertainty; later
observations settle them into transition-ledger rows the existing
settlement pipeline already consumes.

Pinned:
  1. registration — the prediction-ledger/1 row shape, P-N id allocation,
     duplicate-discriminator dedup.
  2. the anti-trivial guard — a discriminator that merely restates the
     statement (token subset) is refused at registration; the base-rate
     floor and the log-lift math are pinned constants.
  3. settlement — confirmed AND refuted paths append a transition row
     (action_type="prediction-settle", r_settle from the credit mapping,
     the log-lift riding the row as lift weight); the ledger row history
     is append-only.
  4. age expiry — predictions older than the TTL flip to expired on read
     (never deleted); the pending/backlog faces carry count + max age.
  5. the compose backlog line — the seam renders an open-predictions
     section exactly when the backlog is non-empty.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rlvr import prediction_ledger as pl  # noqa: E402


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _ledger_rows(ws: Path) -> list[dict]:
    p = ws / "runs" / "predictions.jsonl"
    if not p.is_file():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _transitions(ws: Path) -> list[dict]:
    p = ws / "runs" / "transitions.jsonl"
    if not p.is_file():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def _age_row(ws: Path, pred_id: str, hours: float) -> None:
    """Rewrite one prediction's registered_ts to `hours` ago (the only
    way a pure-unit test can age a row — the read faces own the clock)."""
    p = ws / "runs" / "predictions.jsonl"
    rows = _ledger_rows(ws)
    stamp = (datetime.now(tz=timezone.utc)
             - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for row in rows:
        if row.get("id") == pred_id:
            row["registered_ts"] = stamp
    p.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")


# --------------------------------------------------------- 1. registration

def test_register_row_shape_and_id_allocation(tmp_path):
    ws = _ws(tmp_path)
    row = pl.register(ws, "C-1",
                      "the stage handoff occurs inside region R",
                      "handoff marker at offset 0x40 in region R dump", actor="worker-C-1")
    assert row is not None
    assert row["schema"] == "prediction-ledger/1"
    assert row["id"] == "P-1"
    assert row["claim_id"] == "C-1"
    assert row["status"] == "pending"
    assert row["registered_ts"].endswith("Z")
    # the eight schema fields, exactly — nothing else rides a pending
    # row (registered_by is the 5-F4 authorship stamp)
    assert set(row) == {"schema", "id", "claim_id", "statement",
                        "discriminator", "registered_by",
                        "registered_ts", "status"}
    assert row["registered_by"] == "worker-C-1"
    second = pl.register(ws, "C-1", "blob decrypts under scheme X",
                         "decrypted header starts with the magic bytes", actor="worker-C-1")
    assert second["id"] == "P-2"
    assert len(_ledger_rows(ws)) == 2


def test_register_refuses_trivial_discriminator(tmp_path, capsys):
    ws = _ws(tmp_path)
    # the discriminator only restates statement tokens: base rate ~1,
    # banks ~0 lift — refused, nothing appended, reason on the warn face
    row = pl.register(ws, "C-1",
                      "the config table lists three builders",
                      "config table builders", actor="worker-C-1")
    assert row is None
    assert _ledger_rows(ws) == []
    assert "trivial" in capsys.readouterr().err.lower()


def test_register_refuses_duplicate_discriminator(tmp_path):
    ws = _ws(tmp_path)
    first = pl.register(ws, "C-1", "blob decrypts under scheme X",
                        "decrypted header starts with the magic bytes", actor="worker-C-1")
    assert first is not None
    dup = pl.register(ws, "C-2", "another phrasing of the same bet",
                      "  Decrypted header starts with the magic bytes.  ", actor="worker-C-1")
    assert dup is None  # dedup by discriminator, across claims
    assert len(_ledger_rows(ws)) == 1


def test_register_rejects_empty_input(tmp_path):
    ws = _ws(tmp_path)
    with pytest.raises(ValueError):
        pl.register(ws, "C-1", "  ", "offset 0x40 marker", actor="worker-C-1")
    with pytest.raises(ValueError):
        pl.register(ws, "C-1", "a real statement", "", actor="worker-C-1")
    assert _ledger_rows(ws) == []


# ---------------------------------------------- 2. anti-trivial math pin

def test_base_rate_trivial_vs_nontrivial():
    statement = "the config table lists three builders"
    assert pl.base_rate("config table builders", statement) == 1.0
    assert pl.base_rate(
        "builder count field equals 3 in the hex dump", statement) \
        == pl.BASE_RATE_FLOOR


def test_log_lift_pin_and_floor_clamp():
    # trivial: banks ~0 (log of 1)
    assert pl.log_lift(1.0) == pytest.approx(0.0)
    # the floor is THE one constant: maximum lift bounded at log(100)
    assert pl.log_lift(pl.BASE_RATE_FLOOR) == pytest.approx(math.log(100.0))
    # below-floor base rates clamp at the floor — never an inflated lift
    assert pl.log_lift(0.0001) == pytest.approx(math.log(100.0))
    assert pl.BASE_RATE_FLOOR == 0.01


# -------------------------------------------------------- 3. settlement

def test_settle_confirmed_appends_transition_row(tmp_path):
    ws = _ws(tmp_path)
    row = pl.register(ws, "C-1", "blob decrypts under scheme X",
                      "decrypted header starts with the magic bytes", actor="worker-C-1")
    t_row = pl.settle(ws, row["id"], "confirmed")
    assert t_row is not None
    # the transition-ledger shape, via the existing face
    assert t_row["action_type"] == "prediction-settle"
    assert t_row["dispatch_id"] == "C-1"
    assert t_row["r_settle"] == 1.0
    assert t_row["o"]["status"] == "confirmed"
    # the log-lift rides the row as lift weight
    assert t_row["lift"] == pytest.approx(math.log(100.0), abs=1e-5)
    # the ledger history: pending row + settle row (append-only)
    rows = _ledger_rows(ws)
    assert len(rows) == 2
    assert rows[0]["status"] == "pending"
    assert rows[1]["id"] == row["id"]
    assert rows[1]["status"] == "confirmed"
    assert rows[1]["settled_ts"].endswith("Z")


def test_settle_refuted_banks_zero_credit(tmp_path):
    ws = _ws(tmp_path)
    row = pl.register(ws, "C-1", "blob decrypts under scheme X",
                      "decrypted header starts with the magic bytes", actor="worker-C-1")
    t_row = pl.settle(ws, row["id"], "refuted")
    assert t_row is not None
    assert t_row["r_settle"] == 0.0
    assert t_row["o"]["status"] == "refuted"
    assert _ledger_rows(ws)[-1]["status"] == "refuted"


def test_settle_rejects_invalid_outcome_and_unknown_id(tmp_path):
    ws = _ws(tmp_path)
    row = pl.register(ws, "C-1", "blob decrypts under scheme X",
                      "decrypted header starts with the magic bytes", actor="worker-C-1")
    with pytest.raises(ValueError):
        pl.settle(ws, row["id"], "vibes")
    assert pl.settle(ws, "P-999", "confirmed") is None
    assert _transitions(ws) == []
    assert len(_ledger_rows(ws)) == 1


def test_double_settle_is_refused(tmp_path):
    ws = _ws(tmp_path)
    row = pl.register(ws, "C-1", "blob decrypts under scheme X",
                      "decrypted header starts with the magic bytes", actor="worker-C-1")
    assert pl.settle(ws, row["id"], "confirmed") is not None
    n = len(_ledger_rows(ws))
    assert pl.settle(ws, row["id"], "refuted") is None
    assert len(_ledger_rows(ws)) == n  # no new history
    assert len(_transitions(ws)) == 1


# ---------------------------------------------------------- 4. ttl / age

def test_ttl_expiry_flips_on_read_never_deletes(tmp_path):
    ws = _ws(tmp_path)
    row = pl.register(ws, "C-1", "blob decrypts under scheme X",
                      "decrypted header starts with the magic bytes", actor="worker-C-1")
    assert [r["id"] for r in pl.pending(ws)] == [row["id"]]
    _age_row(ws, row["id"], pl.PREDICTION_TTL_HOURS + 9)
    # flipped out of pending, visible as expired, bytes untouched on disk
    assert pl.pending(ws) == []
    assert [r["id"] for r in pl.expired(ws)] == [row["id"]]
    assert pl.backlog(ws) == {"count": 0, "max_age_hours": 0.0}
    assert len(_ledger_rows(ws)) == 1  # never deleted


def test_backlog_face_carries_count_and_max_age(tmp_path):
    ws = _ws(tmp_path)
    assert pl.backlog(ws) == {"count": 0, "max_age_hours": 0.0}
    pl.register(ws, "C-1", "blob decrypts under scheme X",
                "decrypted header starts with the magic bytes", actor="worker-C-1")
    pl.register(ws, "C-2", "stage handoff lands in region R",
                "handoff marker at offset 0x40 in region R dump", actor="worker-C-1")
    _age_row(ws, "P-2", 30.0)
    b = pl.backlog(ws)
    assert b["count"] == 2
    assert b["max_age_hours"] == pytest.approx(30.0, abs=0.01)


# --------------------------------------- 5. the evidence-matching face

def test_settle_matching_containment_settles_claim_predictions(tmp_path):
    ws = _ws(tmp_path)
    mine = pl.register(ws, "C-1", "blob decrypts under scheme X",
                       "decrypted header starts with the magic bytes", actor="worker-C-1")
    other = pl.register(ws, "C-2", "stage handoff lands in region R",
                        "handoff marker at offset 0x40 in region R dump", actor="worker-C-1")
    note = ("ran the probe; observed: the decrypted header starts with the "
            "magic bytes per evidence/replay.json")
    settled = pl.settle_matching(ws, "C-1", note)
    assert settled == [mine["id"]]
    # only the matching claim's prediction settled; the other stays open
    assert _ledger_rows(ws)[-1]["status"] == "confirmed"
    assert [r["id"] for r in pl.pending(ws)] == [other["id"]]
    # no match -> nothing settles
    assert pl.settle_matching(ws, "C-2", "nothing relevant here") == []
    # settled rows are not re-settled by a second pass
    assert pl.settle_matching(ws, "C-1", note) == []


def test_settle_matching_ignores_expired_predictions(tmp_path):
    ws = _ws(tmp_path)
    row = pl.register(ws, "C-1", "blob decrypts under scheme X",
                      "decrypted header starts with the magic bytes", actor="worker-C-1")
    _age_row(ws, row["id"], pl.PREDICTION_TTL_HOURS + 1)
    assert pl.settle_matching(ws, "C-1",
                              "the decrypted header starts with the "
                              "magic bytes") == []
    assert pl.pending(ws) == []


# ------------------------------------------ 6. the compose backlog line

class _Store:
    """Explicit stub of the compose.StrategyStore protocol seam."""

    def __init__(self, lead=None, cell_count=None):
        self.lead = lead
        self.cell_count_value = cell_count

    def method_lead(self, state_fingerprint: str):
        return self.lead

    def decayed_weight(self, row_id: str) -> float:
        return 1.0

    def cell_count(self, state_fingerprint: str):
        return self.cell_count_value


def _seam_sections(ws: Path) -> list[dict]:
    from rlvr import compose  # noqa: PLC0415
    obj = compose.compose(ws, tick=0, store=_Store())
    compose.write_seam(ws, obj)
    doc = json.loads((ws / "runs" / "round-strategy.json").read_text(
        encoding="utf-8"))
    return doc.get("sections") or []


def test_compose_seam_renders_open_predictions_when_backlog_nonempty(
        tmp_path):
    ws = _ws(tmp_path)
    pl.register(ws, "C-1", "blob decrypts under scheme X",
                "decrypted header starts with the magic bytes", actor="worker-C-1")
    sections = _seam_sections(ws)
    titles = [s["title"] for s in sections]
    assert "open-predictions" in titles
    body = next(s["body"] for s in sections if s["title"] == "open-predictions")
    assert "P-1" in body
    assert "decrypted header starts with the magic bytes" in body


def test_compose_seam_silent_when_backlog_empty(tmp_path):
    ws = _ws(tmp_path)
    assert "open-predictions" not in [s["title"] for s in _seam_sections(ws)]


# ------------------------------------- 7. the settled-backlog invariant

def test_settled_predictions_leave_the_backlog(tmp_path):
    ws = _ws(tmp_path)
    row = pl.register(ws, "C-1", "blob decrypts under scheme X",
                      "decrypted header starts with the magic bytes", actor="worker-C-1")
    pl.settle(ws, row["id"], "confirmed")
    assert pl.pending(ws) == []
    assert pl.expired(ws) == []
    assert pl.backlog(ws) == {"count": 0, "max_age_hours": 0.0}
