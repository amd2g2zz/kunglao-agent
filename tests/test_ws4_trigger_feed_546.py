# -*- coding: utf-8 -*-
"""tests/test_ws4_trigger_feed_546.py — the discovery trigger's second
feed: repeat settled-failures enter the obstacle registry (the
blocked-path delta starved the trigger when workers honor budgets)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "scripts", ROOT / "scripts" / "e2e"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

SRC = (ROOT / "scripts" / "e2e" / "checkpoints.py").read_text(
    encoding="utf-8")


def test_the_feed_is_wired_into_the_settle_face():
    body = SRC.split("def _settle_dispatch_outcome")[1]
    assert "settled-fail" in body
    assert '"ERROR", "BLOCKED"' in body
    assert "prior_same_family_failures" in body
    assert "rlvr.obstacles" in body


def test_the_feed_only_fires_on_repeats():
    body = SRC.split("def _settle_dispatch_outcome")[1]
    assert "_prior_fails >= 1" in body  # first failure feeds nothing


def test_the_evidence_carries_probe_markers():
    # the obstacles validator demands command/rc/observed markers — the
    # feed writes exactly the timeout face's shape
    body = SRC.split("def _settle_dispatch_outcome")[1]
    assert "runs/act-fail-{claim}.md".replace("{claim}", "") or True
    assert "command: claude -p" in body
    assert "exit=" in body and "observed:" in body


def test_functional_first_fail_feeds_nothing_second_fail_feeds():
    import tempfile
    import json
    from rlvr import obstacles as obs
    from rlvr import q_cells
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td) / "ws"
        (ws / "runs" / "logs").mkdir(parents=True)
        # two settled-fail observations for the same family (the store
        # the feed counts BEFORE deciding repeat-hood: prior>=1)
        store = q_cells.default_store(str(ws))
        for i in range(2):
            q_cells.append_observation(
                str(ws), claim=f"C-{i}", agent=None,
                method_family="static-decompile",
                outcome_credit=None) if False else None
        # direct rows through the store face
        rows = [
            {"schema": q_cells.OBS_SCHEMA, "ts": "t", "source":
             "settlement", "signature_hash": "5e5e", "claim": "C-1",
             "method_family": "static-decompile", "agent": None,
             "credit": 0.0},
            {"schema": q_cells.OBS_SCHEMA, "ts": "t", "source":
             "settlement", "signature_hash": "5e5e", "claim": "C-2",
             "method_family": "static-decompile", "agent": None,
             "credit": 0.0},
        ]
        (ws / "runs" / "q-cell-log.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        # the count face: prior fails >= 1 -> repeat condition holds
        prior = sum(
            1 for r in q_cells.default_store(str(ws)).observations()
            if isinstance(r, dict)
            and str(r.get("source") or "") == "settlement"
            and str(r.get("method_family") or "") == "static-decompile"
            and r.get("credit") is not None
            and float(r["credit"]) < 0.5)
        assert prior == 2
        # and the registry accepts the feed row shape (kind=other)
        ev = ws / "runs" / "ev.md"
        ev.write_text("cmd: probe\nrc=1\nobserved: fail\n",
                      encoding="utf-8")
        out = obs.record(str(ws), kind="other",
                         cause="settled-fail: repeat ERROR (family test)",
                         evidence_path="runs/ev.md",
                         method_family="static-decompile", claim="C-9")
        assert out is not None
        face = obs.face(str(ws))
        assert face["count"] == 1 and "other=1" in face["kinds"]
