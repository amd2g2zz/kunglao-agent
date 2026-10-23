# -*- coding: utf-8 -*-
"""tests/test_signal_guard_773.py — the learning-signal degeneracy
breaker (#773 Gate C, contract rl-signal-contract/1 §3).

Five consecutive identical settlement credits = a dead signal: freeze
the posterior-moving legs, raise the signal_degenerate blocker, recover
manually. All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rlvr.signal_guard import (  # noqa: E402
    check_degeneracy,
    freeze_if_degenerate,
    recent_credits,
)


def _seed_store(ws: Path, credits: list[float]) -> None:
    store = ws / "runs" / "posterior-store.jsonl"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(
        "".join(json.dumps({"schema": "posterior-store/1",
                            "credit": c}) + "\n" for c in credits),
        encoding="utf-8")


def test_check_degeneracy_flags_five_identical():
    v = check_degeneracy([1.0, 1.0, 1.0, 1.0, 1.0])
    assert v["degenerate"] and v["distinct"] == 1


def test_check_degeneracy_passes_varied():
    v = check_degeneracy([1.0, 0.3, 1.0, 0.3, 1.0])
    assert not v["degenerate"] and v["distinct"] == 2


def test_check_degeneracy_ignores_short_series():
    assert not check_degeneracy([1.0, 1.0, 1.0])["degenerate"]


def test_check_degeneracy_ignores_non_numeric():
    v = check_degeneracy([1.0, 1.0, 1.0, 1.0, 1.0, "x", None])  # type: ignore[list-item]
    assert v["degenerate"]


def test_recent_credits_reads_the_store(tmp_path):
    ws = tmp_path / "ws"
    _seed_store(ws, [0.3, 1.0])
    assert recent_credits(ws, 5) == [0.3, 1.0]


def test_recent_credits_absent_store_is_empty(tmp_path):
    assert recent_credits(tmp_path / "nope", 5) == []


def test_freeze_emits_blocker_and_returns_true(tmp_path):
    ws = tmp_path / "ws"
    _seed_store(ws, [1.0] * 5)
    logs = ws / "runs" / "logs"
    logs.mkdir(parents=True)
    (logs / "kunglao-2026-10-19.jsonl").write_text("", encoding="utf-8")
    assert freeze_if_degenerate(ws, [1.0] * 5) is True
    # emit() lands on the CURRENT UTC day file (kunglao_log._day_file
    # owns the naming) — read every day file, never a hardcoded calendar
    # date (a pinned date rots the day after it was written).
    rows = [json.loads(l) for p in sorted(logs.glob("kunglao-*.jsonl"))
            for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert any(r.get("action") == "signal_degenerate" for r in rows)


def test_freeze_varied_returns_false(tmp_path):
    ws = tmp_path / "ws"
    _seed_store(ws, [1.0, 0.3])
    assert freeze_if_degenerate(ws, [1.0, 0.3]) is False


def test_settle_freezes_on_degenerate_series(tmp_path):
    import settle_round_credit as src
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [
            {"id": "C-1", "status": "PROVEN",
             "verification": {"method": "reproduction"}}]}),
        encoding="utf-8")
    _seed_store(ws, [1.0] * 5)
    out = src.run(ws)
    assert out.get("signal_frozen") is True, out
    assert out.get("case_observations") == 0


def test_settle_unfrozen_when_signal_varied(tmp_path):
    import settle_round_credit as src
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [
            {"id": "C-1", "status": "PROVEN",
             "verification": {"method": "reproduction"}}]}),
        encoding="utf-8")
    _seed_store(ws, [1.0, 0.3, 1.0])
    out = src.run(ws)
    assert out.get("signal_frozen") is None
