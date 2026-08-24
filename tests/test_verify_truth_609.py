# -*- coding: utf-8 -*-
"""tests/test_verify_truth_609.py — #609: --verify must not vouch for a dead cron.

RED: verify_loop trusted the file marker (loop_registered=true) with no
liveness cross-check — a cron deleted after one successful fire left verify
returning OK forever. Adjudicated fix (方案 A): when the marker is true, also
check last_tick_ts freshness (STALE_MINUTES via liveness_policy; corrupt →
treated as stale, fail-closed). Marker semantics (#461) unchanged.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import heartbeat_loop_prompt as hlp  # noqa: E402


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_hb(ws: Path, *, registered: bool, last_tick: str | None) -> None:
    runs = ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    state = {
        "started_ts": _ts(datetime.now(tz=timezone.utc) - timedelta(hours=2)),
        "interval_min": 5,
        "loop_registered": registered,
    }
    if last_tick is not None:
        state["last_tick_ts"] = last_tick
    (runs / ".heartbeat.json").write_text(json.dumps(state), encoding="utf-8")


def test_fresh_tick_ok(tmp_path, capsys):
    _write_hb(tmp_path, registered=True,
              last_tick=_ts(datetime.now(tz=timezone.utc) - timedelta(minutes=2)))
    assert hlp.verify_loop(str(tmp_path)) == 0
    assert "OK" in capsys.readouterr().out


def test_registered_but_stale_tick_fails(tmp_path, capsys):
    from liveness_policy import STALE_MINUTES
    _write_hb(tmp_path, registered=True,
              last_tick=_ts(datetime.now(tz=timezone.utc) - timedelta(minutes=STALE_MINUTES + 10)))
    assert hlp.verify_loop(str(tmp_path)) == 1
    err = capsys.readouterr().err
    assert "registered" in err and "NOT TICKING" in err


def test_registered_but_no_tick_fails(tmp_path, capsys):
    _write_hb(tmp_path, registered=True, last_tick=None)
    assert hlp.verify_loop(str(tmp_path)) == 1
    assert "NOT TICKING" in capsys.readouterr().err


def test_corrupt_tick_treated_stale(tmp_path, capsys):
    _write_hb(tmp_path, registered=True, last_tick="not-a-timestamp")
    assert hlp.verify_loop(str(tmp_path)) == 1
    assert "NOT TICKING" in capsys.readouterr().err


def test_marker_false_still_fails(tmp_path, capsys):
    _write_hb(tmp_path, registered=False,
              last_tick=_ts(datetime.now(tz=timezone.utc)))
    assert hlp.verify_loop(str(tmp_path)) == 1
    assert "CRON NOT REGISTERED" in capsys.readouterr().err
