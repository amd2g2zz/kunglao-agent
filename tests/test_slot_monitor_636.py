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


# ---------- decision-table kill tests: CLI faces, boundaries, stubs ----------

def test_cli_plain_text_face_lists_verdicts(tmp_path, capsys):
    import slot_monitor as sm
    ws = _ws(tmp_path)
    _worker(ws, mtime_age_s=41 * 60)
    assert sm.main([str(ws)]) == 0
    out = capsys.readouterr().out
    assert "slot: active=1 free=2 [C005=gone]" in out


def test_cli_no_workers_face(tmp_path, capsys):
    import slot_monitor as sm
    ws = _ws(tmp_path)
    assert sm.main([str(ws)]) == 0
    assert "no active workers" in capsys.readouterr().out


def test_cli_refuses_non_workspace(tmp_path, capsys):
    import slot_monitor as sm
    bare = tmp_path / "bare"
    bare.mkdir()
    assert sm.main([str(bare)]) == 3
    assert "not a kunglao workspace" in capsys.readouterr().err


def test_report_written_with_trailing_newline_and_utc_ts(tmp_path):
    import slot_monitor as sm
    ws = _ws(tmp_path)
    _worker(ws)
    assert sm.main([str(ws)]) == 0
    raw = (ws / "runs" / ".slot-report.json").read_text(encoding="utf-8")
    assert raw.endswith("\n")
    doc = json.loads(raw)
    assert doc["workers"][0]["verdict"] == "keep"
    assert doc["ts"].endswith("Z")


def test_report_dir_created_when_runs_absent(tmp_path):
    import slot_monitor as sm
    ws = tmp_path / "ws2"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": []}), encoding="utf-8")
    assert sm.main([str(ws)]) == 0
    assert (ws / "runs" / ".slot-report.json").is_file()


def test_keep_worker_emits_no_signal_row(tmp_path):
    import slot_monitor as sm
    ws = _ws(tmp_path)
    _worker(ws)
    assert sm.main([str(ws), "--json"]) == 0
    p = ws / "runs" / "signals.jsonl"
    assert (not p.exists()) or p.read_text(encoding="utf-8").strip() == ""


def test_slot_signal_row_exact_shape(tmp_path):
    import slot_monitor as sm
    ws = _ws(tmp_path)
    _worker(ws, mtime_age_s=41 * 60)
    assert sm.main([str(ws), "--json"]) == 0
    row = json.loads((ws / "runs" / "signals.jsonl").read_text(
        encoding="utf-8").splitlines()[-1])
    assert set(row) == {"ts", "kind", "worker", "verdict", "age_s",
                        "silence_s"}
    assert row["kind"] == "slot" and row["worker"] == "C005"
    assert row["verdict"] == "gone"
    assert isinstance(row["age_s"], int) and isinstance(row["silence_s"], int)
    report = json.loads((ws / "runs" / ".slot-report.json").read_text(
        encoding="utf-8"))
    assert row["ts"] == report["ts"]


def _utime_at(path, when_ts):
    os.utime(path, (when_ts, when_ts))


def test_stuck_and_dead_boundaries(tmp_path):
    import liveness_policy as lp
    import slot_monitor as sm
    from datetime import datetime, timezone
    ws = _ws(tmp_path)
    now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    f = _worker(ws, first_ts=time.strftime(
        "%Y-%m-%dT%H:%M", time.gmtime(now.timestamp() - 60)))
    _utime_at(f, now.timestamp() - lp.STUCK_MINUTES * 60)
    assert sm.scan(ws, now=now)["workers"][0]["verdict"] == "ping"
    _utime_at(f, now.timestamp() - (lp.DEAD_WORKER_MINUTES * 60 - 1))
    assert sm.scan(ws, now=now)["workers"][0]["verdict"] == "ping"
    _utime_at(f, now.timestamp() - lp.DEAD_WORKER_MINUTES * 60)
    assert sm.scan(ws, now=now)["workers"][0]["verdict"] == "gone"


def test_frozen_flag_matrix(tmp_path):
    import slot_monitor as sm
    ws = _ws(tmp_path)
    old = time.strftime("%Y-%m-%dT%H:%M", time.gmtime(time.time() - 4000))
    _worker(ws, first_ts=old, progress=2)
    # prior progress differs from the current count: not frozen, keep
    (ws / "runs" / ".slot-report.json").write_text(json.dumps(
        {"workers": [{"worker": "C005", "progress_lines": 1}]}),
        encoding="utf-8")
    out = sm.scan(ws)
    assert out["workers"][0]["frozen"] is False
    assert out["workers"][0]["verdict"] == "keep"
    # absent from the prior report: not frozen even when aged
    (ws / "runs" / ".slot-report.json").write_text(
        json.dumps({"workers": []}), encoding="utf-8")
    assert sm.scan(ws)["workers"][0]["frozen"] is False


def test_owner_review_boundary(tmp_path):
    import slot_monitor as sm
    from datetime import datetime, timezone
    ws = _ws(tmp_path)
    now = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    ts = time.strftime("%Y-%m-%dT%H:%M",
                       time.gmtime(now.timestamp() - 3700))
    _worker(ws, first_ts=ts, progress=1)
    (ws / "runs" / ".slot-report.json").write_text(json.dumps(
        {"workers": [{"worker": "C005", "progress_lines": 1}]}),
        encoding="utf-8")
    assert sm.scan(ws, now=now)["workers"][0]["verdict"] == "keep"
    ts_old = time.strftime("%Y-%m-%dT%H:%M",
                           time.gmtime(now.timestamp() - 3900))
    _worker(ws, first_ts=ts_old, progress=1)
    assert sm.scan(ws, now=now)["workers"][0]["verdict"] == "terminate_review"


def test_status_tail_truncated_to_160(tmp_path):
    import slot_monitor as sm
    ws = _ws(tmp_path)
    ts = time.strftime("%Y-%m-%dT%H:%M", time.gmtime())
    long_line = f"[{ts}] step: " + "x" * 300 + " | status: in-progress"
    (ws / "runs" / "worker-status-C005.md").write_text(
        long_line + "\n", encoding="utf-8")
    out = sm.scan(ws)
    assert len(out["workers"][0]["status_tail"]) == 160


def test_worker_naming_order_and_claim_extraction(tmp_path):
    import slot_monitor as sm
    ws = _ws(tmp_path)
    _worker(ws)
    ts = time.strftime("%Y-%m-%dT%H:%M", time.gmtime())
    for name in ("worker-status-C12.md", "worker-status-w7.md"):
        (ws / "runs" / name).write_text(
            f"[{ts}] step: x | status: in-progress\n", encoding="utf-8")
    out = sm.scan(ws)
    by_id = {w["worker"]: w["claim"] for w in out["workers"]}
    assert out["active"] == 3
    assert [w["worker"] for w in out["workers"]] == ["C005", "C12", "w7"]
    assert by_id["C12"] == "C-12" and by_id["w7"] is None


def test_waiting_status_file_not_active(tmp_path):
    import slot_monitor as sm
    ws = _ws(tmp_path)
    ts = time.strftime("%Y-%m-%dT%H:%M", time.gmtime())
    (ws / "runs" / "worker-status-C005.md").write_text(
        f"[{ts}] wait: awaiting signal | status: waiting\n",
        encoding="utf-8")
    out = sm.scan(ws)
    assert out["active"] == 0 and out["workers"] == []


def test_progress_counts_step_lines_only(tmp_path):
    import slot_monitor as sm
    ws = _ws(tmp_path)
    ts = time.strftime("%Y-%m-%dT%H:%M", time.gmtime())
    (ws / "runs" / "worker-status-C005.md").write_text(
        f"[{ts}] step: a | status: in-progress\n"
        f"[{ts}] wait: interim | status: in-progress\n"
        f"[{ts}] step: b | status: in-progress\n", encoding="utf-8")
    assert sm.scan(ws)["workers"][0]["progress_lines"] == 2


def test_worker_cap_source_ladder(tmp_path, monkeypatch):
    import sys
    import types
    import slot_monitor as sm
    cc = types.ModuleType("convergence_check")
    cc.WORKER_CAP = 3
    monkeypatch.setitem(sys.modules, "convergence_check", cc)
    assert sm._worker_cap() == 3
    empty_cc = types.ModuleType("convergence_check")
    monkeypatch.setitem(sys.modules, "convergence_check", empty_cc)
    wg = types.ModuleType("workguard")
    wg.WORKER_CAP = 2
    monkeypatch.setitem(sys.modules, "workguard", wg)
    assert sm._worker_cap() == 2
    monkeypatch.setitem(sys.modules, "workguard",
                        types.ModuleType("workguard"))
    assert sm._worker_cap() is None


def test_age_s_exact_and_clamps(tmp_path):
    import slot_monitor as sm
    from datetime import datetime, timezone
    now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    past = time.strftime("%Y-%m-%dT%H:%M",
                         time.gmtime(now.timestamp() - 300))
    assert sm._age_s(f"[{past}] step: x", mtime=0.0, now=now) == 300.0
    future = time.strftime("%Y-%m-%dT%H:%M",
                           time.gmtime(now.timestamp() + 300))
    assert sm._age_s(f"[{future}] step: x", mtime=0.0, now=now) == 0.0
    assert sm._age_s("no timestamp at all", mtime=now.timestamp() - 42.0,
                     now=now) == 42.0


def test_read_json_faces(tmp_path):
    import slot_monitor as sm
    p = tmp_path / "j.json"
    assert sm._read_json(p) is None
    p.write_text("{not json", encoding="utf-8")
    assert sm._read_json(p) is None
    p.write_text('{"a": 1}', encoding="utf-8")
    assert sm._read_json(p) == {"a": 1}
