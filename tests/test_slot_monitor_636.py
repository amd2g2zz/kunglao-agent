# -*- coding: utf-8 -*-
"""tests/test_slot_monitor_636.py — the #636 slot decision table + the
#638 teardown addendum: verdict thresholds (keep/ping/gone/terminate_review
from liveness_policy + the 1800s owner trigger), the slot ledger,
kind=slot signal emission, and loop_scheduler's sanctioned --remove face.
Synthetic fixtures with controlled mtimes."""
from __future__ import annotations

import json
import os
import time

import yaml


def _ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": []}), encoding="utf-8")
    return ws


def _worker(ws, *, first_ts=None, mtime_age_s=0, progress=1):
    if first_ts is None:
        first_ts = time.strftime("%Y-%m-%dT%H:%M", time.gmtime())
    p = ws / "runs" / "worker-status-C005.md"
    lines = [f"[{first_ts}] step: s{i} | status: in-progress"
             for i in range(progress)]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    now = time.time()
    os.utime(p, (now - mtime_age_s, now - mtime_age_s))
    return p


def test_fresh_worker_keeps(tmp_path):
    import slot_monitor as sm
    ws = _ws(tmp_path)
    _worker(ws, progress=2)
    out = sm.scan(ws)
    assert out["active"] == 1 and out["free"] == 2
    assert out["workers"][0]["verdict"] == "keep"
    assert out["workers"][0]["claim"] == "C-005"


def test_silence_20m_pings(tmp_path):
    import slot_monitor as sm
    ws = _ws(tmp_path)
    _worker(ws, mtime_age_s=21 * 60)
    assert sm.scan(ws)["workers"][0]["verdict"] == "ping"


def test_silence_41m_gone(tmp_path):
    import slot_monitor as sm
    ws = _ws(tmp_path)
    _worker(ws, mtime_age_s=41 * 60)
    assert sm.scan(ws)["workers"][0]["verdict"] == "gone"


def test_long_frozen_review(tmp_path):
    import slot_monitor as sm
    ws = _ws(tmp_path)
    old = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(time.time() - 4000))
    _worker(ws, first_ts=old, progress=1)
    (ws / "runs" / ".slot-report.json").write_text(json.dumps(
        {"workers": [{"worker": "C005", "progress_lines": 1}]}),
        encoding="utf-8")
    out = sm.scan(ws)
    assert out["workers"][0]["frozen"] is True
    assert out["workers"][0]["verdict"] == "terminate_review"


def test_non_keep_emits_slot_signal(tmp_path):
    import slot_monitor as sm
    ws = _ws(tmp_path)
    _worker(ws, mtime_age_s=41 * 60)
    assert sm.main([str(ws), "--json"]) == 0
    rows = [json.loads(ln) for ln in
            (ws / "runs" / "signals.jsonl").read_text(
                encoding="utf-8").splitlines()]
    assert any(r["kind"] == "slot" and r["verdict"] == "gone" for r in rows)


def test_loop_scheduler_remove_face(tmp_path):
    import loop_scheduler as ls
    ws = _ws(tmp_path)
    assert ls.upsert_durable_loop(ws, "5m") == 0
    assert ls.main([str(ws), "--check"]) == 0
    assert ls.main([str(ws), "--remove"]) == 0
    assert ls.main([str(ws), "--check"]) == 2  # no entry left
    assert ls.main([str(ws), "--remove"]) == 0  # idempotent
