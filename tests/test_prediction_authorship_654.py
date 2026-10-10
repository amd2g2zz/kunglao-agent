# -*- coding: utf-8 -*-
"""Issue #654 4-L5 + 5-F4 — scaffold-aimed discriminators refused;
prediction rows carry authorship; unattributed rows cannot settle.

Lens findings:

  4-L5 — the settle is substring containment in the verifier note, and
  the note's ``verdict:`` frontmatter line is MANDATED by the dispatch
  contract (the engine parses it at checkpoints.py:1308/1518/1553) — a
  discriminator aimed at the mandated scaffold settles on contract
  compliance, not on the claim's truth (base rate ~1 by construction).
  Fix: register refuses a discriminator whose token set intersects the
  mandated marker tokens.

  5-F4 — runs/predictions.jsonl is not a carrier: a raw JSONL append
  via Bash skips is_trivial and the duplicate-discriminator refusal,
  and rows carried no authorship field. Fix: register REQUIRES a
  non-empty ``actor`` (stamped ``registered_by``), and the settle faces
  refuse any pending row lacking ``registered_by`` — the bypass now
  mints rows that can never bank lift. Residual (named, not solved): a
  forger who copies the authorship SHAPE is the red-team trust class.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rlvr import prediction_ledger as pl  # noqa: E402


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _warn_recorder(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        pl, "warn",
        lambda op, reason, **kw: calls.append((str(op), str(reason))))
    return calls


# ---------------------------------------------------------------- 4-L5

def test_scaffold_aimed_discriminator_refused(tmp_path, monkeypatch) -> None:
    ws = _ws(tmp_path)
    calls = _warn_recorder(monkeypatch)
    row = pl.register(ws, "C-1", "the sample decrypts under key X",
                      "verdict:", actor="worker-C-1")
    assert row is None
    assert len(calls) == 1 and "scaffold" in calls[0][1]
    assert pl.read_ledger(ws) == []


def test_scaffold_variant_refused(tmp_path, monkeypatch) -> None:
    """``verdict: verified`` and prose containing the mandated token are
    the same exploit shape."""
    ws = _ws(tmp_path)
    _warn_recorder(monkeypatch)
    assert pl.register(ws, "C-1", "the dumpsys output shows the flag",
                       "verdict: verified", actor="worker-C-1") is None
    assert pl.register(ws, "C-1", "the dumpsys output shows the flag",
                       "the verdict line appears", actor="worker-C-1") is None
    assert pl.read_ledger(ws) == []


def test_honest_discriminator_still_registers(tmp_path, monkeypatch) -> None:
    ws = _ws(tmp_path)
    _warn_recorder(monkeypatch)
    row = pl.register(ws, "C-1", "the sample decrypts under key X",
                      "frida-server dumpsys offset 0x40", actor="worker-C-1")
    assert row is not None
    assert row["registered_by"] == "worker-C-1"


def test_actor_is_required(tmp_path) -> None:
    ws = _ws(tmp_path)
    for bad in ("", "   ", None):
        try:
            pl.register(ws, "C-1", "s", "offset 0x40 marker", actor=bad)
            raised = False
        except ValueError:
            raised = True
        assert raised, f"actor={bad!r} must be refused at the boundary"


# ---------------------------------------------------------------- 5-F4

def _register_one(ws: Path) -> dict:
    row = pl.register(ws, "C-3", "the exported function resolves late",
                      "export-table ordinal 0x2a", actor="worker-C-3")
    assert row is not None
    return row


def test_settle_matching_refuses_unattributed_row(tmp_path,
                                                  monkeypatch) -> None:
    """The 5-F4 trigger verbatim: a raw JSONL append via Bash (no
    register face, no authorship) must never settle."""
    ws = _ws(tmp_path)
    _warn_recorder(monkeypatch)
    forged = {"schema": pl.SCHEMA, "id": "P-1", "claim_id": "C-3",
              "statement": "forged", "discriminator": "verdict: verified",
              "registered_ts": "2026-10-11T00:00:00Z",
              "status": pl.STATUS_PENDING}
    with (ws / "runs" / "predictions.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(forged) + "\n")
    settled = pl.settle_matching(ws, "C-3",
                                 "the verifier note says verdict: verified")
    assert settled == []
    statuses = [r.get("status") for r in pl.read_ledger(ws)]
    assert statuses == [pl.STATUS_PENDING]  # the forged row never settles


def test_settle_refuses_unattributed_row(tmp_path, monkeypatch) -> None:
    ws = _ws(tmp_path)
    calls = _warn_recorder(monkeypatch)
    forged = {"schema": pl.SCHEMA, "id": "P-1", "claim_id": "C-3",
              "statement": "s", "discriminator": "d",
              "registered_ts": "2026-10-11T00:00:00Z",
              "status": pl.STATUS_PENDING}
    with (ws / "runs" / "predictions.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(forged) + "\n")
    assert pl.settle(ws, "P-1", "confirmed") is None
    assert len(calls) == 1


def test_registered_row_settles_with_authorship(tmp_path, monkeypatch) -> None:
    ws = _ws(tmp_path)
    _warn_recorder(monkeypatch)
    _register_one(ws)
    settled = pl.settle_matching(
        ws, "C-3", "observed: export-table ordinal 0x2a resolves late")
    assert settled, "the honest, attributed prediction settles"
    latest = pl.latest_by_id(ws)[settled[0]]
    assert latest["registered_by"] == "worker-C-3"
