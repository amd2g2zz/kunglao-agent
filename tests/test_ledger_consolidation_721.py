# -*- coding: utf-8 -*-
"""tests/test_ledger_consolidation_721.py — the 4-file ledger
consolidation (issue #721): one consolidation core — append-only, row
schema stamps, flock; the append-only migration; the compat read window;
per-schema liveness counters.

The card's pins:

  1. Row schema stamps in the consolidated files — `append()` refuses a
     stampless row (an unattributable row in a multi-schema file is the
     orphan-store bug class #721 exists to kill).
  2. Migration APPENDS, never rewrites — the originals land in
     runs/archive/ byte-identical; every historical row survives (values
     preserved; a schema stamp is the only structural addition, and only
     where a pre-stamp row lacked it); a re-run appends nothing.
  3. Readers accept both paths during the compat window — legacy archive
     rows first, then the consolidated file; the stamp filter keeps
     foreign schemas out of a family read.
  4. Per-schema liveness counters are visible — every registered schema
     reports a count (a dead schema reads 0, never silently absent).

The knowledge family rides the guarded cross-task root
(strategy_store.store_root — KUNGLAO_POSTERIOR_STORE override), pinned
here so the two resolvers can never drift.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (SCRIPTS, SCRIPTS.parent / "tests", ROOT / "hooks"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from rlvr import consolidated_ledger as cl  # noqa: E402

TS = "2026-10-16T00:00:00Z"


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _lines(p: Path) -> list[dict]:
    return [json.loads(ln) for ln in p.read_text("utf-8").splitlines()
            if ln.strip()]


# ---------------------------------------------------- pin 1: row stamps

def test_consolidated_files_carry_row_schema_stamps(tmp_path):
    ws = _ws(tmp_path)
    row = {"schema": "step-record/1", "ts": TS, "session_id": "s1",
           "tool": "Bash"}
    assert cl.append(ws, "experience", row) is True
    p = ws / "runs" / "experience.jsonl"
    assert p.is_file()
    assert _lines(p) == [row]
    # the flock guard rides the house lock-file pattern
    assert (ws / "runs" / ".experience.lock").exists()
    # a stampless row is REFUSED — the file stays attributable
    before = p.read_text("utf-8")
    assert cl.append(ws, "experience", {"ts": TS,
                                        "dispatch_id": "C-1"}) is False
    assert p.read_text("utf-8") == before
    # an unknown family is refused (ONE warn, never a raise)
    assert cl.append(ws, "nope", row) is False
    # a non-dict is refused
    assert cl.append(ws, "experience", ["schema"]) is False


def test_appends_stay_well_formed_under_concurrency(tmp_path):
    ws = _ws(tmp_path)
    n_threads, per_thread = 4, 10

    def _writer(t: int):
        for i in range(per_thread):
            assert cl.append(ws, "experience", {
                "schema": "step-record/1", "ts": TS,
                "session_id": f"s{t}", "tool": f"t{i}"}) is True

    threads = [threading.Thread(target=_writer, args=(t,))
               for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    rows = _lines(ws / "runs" / "experience.jsonl")
    assert len(rows) == n_threads * per_thread  # no torn/merged lines
    assert all(r["schema"] == "step-record/1" for r in rows)


# ------------------------------- pin 3: the compat read window

def test_readers_accept_both_paths_during_compat(tmp_path, monkeypatch):
    monkeypatch.delenv(cl.STORE_ENV, raising=False)
    ws = _ws(tmp_path)
    runs = ws / "runs"
    # (a) legacy-only workspace: the unstamped archive still reads
    legacy = {"ts": TS, "dispatch_id": "C-1"}  # the pre-stamp archive row
    (runs / "transitions.jsonl").write_text(json.dumps(legacy) + "\n",
                                            "utf-8")
    assert cl.read(ws, "experience", schema_prefix="transition") == [legacy]
    # ...and never leaks into another schema's read
    assert cl.read(ws, "experience", schema_prefix="q-cell-obs") == []

    # (b) live writes land in the consolidated file and read back with
    # the legacy rows first (chronology); the stamp filter keeps foreign
    # schemas out of a family read
    live = {"schema": "transition/1", "ts": TS, "dispatch_id": "C-2"}
    assert cl.append(ws, "experience", live) is True
    assert cl.append(ws, "experience", {"schema": "step-record/1",
                                        "ts": TS}) is True
    got = cl.read(ws, "experience", schema_prefix="transition")
    assert got == [legacy, live]
    assert len(cl.read(ws, "experience")) == 3       # unfiltered = all
    # a stamped legacy row filters on ITS stamp (exact archive window)
    (runs / "q-cell-log.jsonl").write_text(json.dumps(
        {"schema": "q-cell-obs/1", "ts": TS}) + "\n", "utf-8")
    assert [r["schema"] for r in
            cl.read(ws, "experience", schema_prefix="step-record")] == \
        ["step-record/1"]
    assert cl.read(ws, "experience", schema_prefix="q-cell-obs") == \
        [{"schema": "q-cell-obs/1", "ts": TS}]


# ------------------------------------------- pin 4: per-schema liveness

def test_per_schema_liveness_counters_visible(tmp_path, monkeypatch):
    monkeypatch.delenv(cl.STORE_ENV, raising=False)
    ws = _ws(tmp_path)
    live = cl.liveness(ws)
    # every registered experience schema is visible; the dead ones read 0
    for stamp in ("transition/1", "q-cell-obs/1", "step-record/1",
                  "step-record/2", "evidence-item/1",
                  "credit-amendment/1"):
        assert live[f"experience:{stamp}"] == 0
    assert cl.append(ws, "experience",
                     {"schema": "step-record/2", "ts": TS}) is True
    assert cl.append(ws, "experience",
                     {"schema": "step-record/2", "ts": TS}) is True
    # a foreign stamp still shows (attribution beats the registry)
    assert cl.append(ws, "experience",
                     {"schema": "claim-ref/9", "ts": TS}) is True
    live = cl.liveness(ws)
    assert live["experience:step-record/2"] == 2
    assert live["experience:step-record/1"] == 0  # dead schema = alarm
    assert live["experience:claim-ref/9"] == 1
    # legacy rels count during the compat window (unstamped bucket)
    (ws / "runs" / "transitions.jsonl").write_text(
        json.dumps({"ts": TS}) + "\n", "utf-8")
    assert cl.liveness(ws)["experience:(no-schema)"] == 1


def test_knowledge_family_rides_the_guarded_root(tmp_path, monkeypatch):
    monkeypatch.setenv(cl.STORE_ENV, str(tmp_path / "root"))
    p = cl.family_path(tmp_path / "ws", "knowledge")
    assert p == tmp_path / "root" / "knowledge-store.jsonl"
    from rlvr import strategy_store as ss  # noqa: PLC0415 — the pin
    assert p == ss.store_path().parent / "knowledge-store.jsonl"
