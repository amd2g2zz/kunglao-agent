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


# ------------------------------------------- pin 2: append-only migration

def test_migration_appends_never_rewrites_history(tmp_path, monkeypatch):
    monkeypatch.delenv(cl.STORE_ENV, raising=False)
    ws = _ws(tmp_path)
    runs = ws / "runs"
    obs = {"schema": "q-cell-obs/1", "ts": TS, "source": "settlement",
           "signature_hash": "sig", "method_family": "web-re",
           "claim": "C-1", "credit": 1.0}
    step = {"schema": "step-record/1", "ts": TS, "session_id": "s1",
            "tool": "Bash"}
    ev = {"schema": "evidence-item/1", "ts": TS, "id": "e1",
          "kind": "confirm"}
    (runs / "transitions.jsonl").write_text(
        json.dumps({"ts": TS, "dispatch_id": "C-1", "r_incr": 0.5}) + "\n"
        + json.dumps({"ts": TS, "dispatch_id": "C-2", "r_incr": -1.0})
        + "\n", "utf-8")
    (runs / "q-cell-log.jsonl").write_text(json.dumps(obs) + "\n", "utf-8")
    (runs / "step-ledger.jsonl").write_text(json.dumps(step) + "\n",
                                            "utf-8")
    (runs / "evidence-credit.jsonl").write_text(json.dumps(ev) + "\n",
                                                "utf-8")
    before = {name: (runs / name).read_bytes() for name in (
        "transitions.jsonl", "q-cell-log.jsonl", "step-ledger.jsonl",
        "evidence-credit.jsonl")}

    report = cl.migrate(ws)
    # originals archived byte-identical (never rewritten, never deleted)
    # and MOVED — the read face can never double-count them
    for name, raw in before.items():
        arch = runs / "archive" / name
        assert arch.is_file()
        assert arch.read_bytes() == raw
        assert not (runs / name).exists()
    # every historical row survives; intra-schema order preserved; the
    # missing stamp is the ONLY structural addition
    rows = _lines(runs / "experience.jsonl")
    assert rows == [
        {"ts": TS, "dispatch_id": "C-1", "r_incr": 0.5,
         "schema": "transition/1"},
        {"ts": TS, "dispatch_id": "C-2", "r_incr": -1.0,
         "schema": "transition/1"},
        obs, step, ev,
    ]
    assert report["experience"]["runs/transitions.jsonl"]["appended"] == 2

    # a re-run appends NOTHING (idempotent — never a duplicated history)
    again = cl.migrate(ws)
    assert _lines(runs / "experience.jsonl") == rows
    assert again["experience"]["runs/transitions.jsonl"]["status"] \
        == "absent"

    # dry-run writes nothing at all
    dry_ws = _ws(tmp_path / "d")
    (dry_ws / "runs" / "transitions.jsonl").write_text(
        json.dumps({"ts": TS, "dispatch_id": "C-9"}) + "\n", "utf-8")
    dry = cl.migrate(dry_ws, dry_run=True)
    assert dry["experience"]["runs/transitions.jsonl"]["status"] \
        == "dry-run"
    assert not (dry_ws / "runs" / "experience.jsonl").exists()
    assert (dry_ws / "runs" / "transitions.jsonl").is_file()


def test_migration_never_guesses_a_second_schema_stamp(tmp_path,
                                                       monkeypatch):
    """A rel with TWO registered stamps (step-ledger: step-record/1+2)
    copying an unstamped row must NOT invent a stamp — verbatim copy."""
    monkeypatch.delenv(cl.STORE_ENV, raising=False)
    ws = _ws(tmp_path)
    (ws / "runs" / "step-ledger.jsonl").write_text(
        json.dumps({"ts": TS, "session_id": "s1"}) + "\n", "utf-8")
    cl.migrate(ws)
    rows = _lines(ws / "runs" / "experience.jsonl")
    assert rows == [{"ts": TS, "session_id": "s1"}]  # verbatim, no guess


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


def test_append_refuses_unserializable_and_malformed_stamps(tmp_path):
    """Review hardening (t5-721-core F1/F3): a non-serializable row and
    a non-string / unstripped / blank stamp are REFUSED — ONE warn,
    never a raise, never a half-write."""
    ws = _ws(tmp_path)
    p = ws / "runs" / "experience.jsonl"
    assert cl.append(ws, "experience",
                     {"schema": "step-record/1", "ts": TS,
                      "reads": {TS}}) is False          # a set is not JSON
    assert cl.append(ws, "experience", {"schema": 123, "ts": TS}) is False
    assert cl.append(ws, "experience",
                     {"schema": " s/1 ", "ts": TS}) is False
    assert cl.append(ws, "experience", {"schema": "  ", "ts": TS}) is False
    assert not p.exists()                                 # no half-write


def test_read_unknown_family_fails_open(tmp_path):
    """F2 symmetry: append() refuses an unknown family gracefully — read()
    must too (no KeyError escapes into a consumer)."""
    ws = _ws(tmp_path)
    assert cl.read(ws, "nope") == []


def test_read_accepts_a_tuple_of_prefixes(tmp_path):
    ws = _ws(tmp_path)
    assert cl.append(ws, "experience",
                     {"schema": "step-record/1", "ts": TS}) is True
    assert cl.append(ws, "experience",
                     {"schema": "evidence-item/1", "ts": TS}) is True
    assert cl.append(ws, "experience",
                     {"schema": "q-cell-obs/1", "ts": TS}) is True
    got = cl.read(ws, "experience",
                  schema_prefix=("step-record", "evidence-item"))
    assert sorted(r["schema"] for r in got) == ["evidence-item/1",
                                                "step-record/1"]


# ------------------------------------------------------- the migration CLI

def test_cli_migrates_reports_and_reads_liveness(tmp_path, monkeypatch,
                                                 capsys):
    monkeypatch.delenv(cl.STORE_ENV, raising=False)
    ws = _ws(tmp_path)
    (ws / "runs" / "transitions.jsonl").write_text(
        json.dumps({"ts": TS, "dispatch_id": "C-1"}) + "\n", "utf-8")
    import consolidate_ledgers as cli  # noqa: PLC0415 — scripts on path

    # dry-run writes nothing
    assert cli.main([str(ws), "--dry-run"]) == 0
    assert (ws / "runs" / "transitions.jsonl").is_file()
    assert "dry-run" in capsys.readouterr().out
    # the real migration moves the rel into the archive
    assert cli.main([str(ws)]) == 0
    assert (ws / "runs" / "archive" / "transitions.jsonl").is_file()
    assert not (ws / "runs" / "transitions.jsonl").exists()
    assert "migrated" in capsys.readouterr().out
    # liveness: the migrated row is visible under its stamp, and a dead
    # registered schema still reports 0 (the alarm, never silence)
    assert cli.main([str(ws), "--liveness"]) == 0
    out = capsys.readouterr().out
    assert "experience:transition/1\t1" in out
    assert "experience:step-record/1\t0" in out
    # bad args: missing workspace / unknown family
    assert cli.main([str(tmp_path / "nope")]) == 2
    assert cli.main([str(ws), "--families", "bogus"]) == 2


def test_knowledge_family_rides_the_guarded_root(tmp_path, monkeypatch):
    monkeypatch.setenv(cl.STORE_ENV, str(tmp_path / "root"))
    p = cl.family_path(tmp_path / "ws", "knowledge")
    assert p == tmp_path / "root" / "knowledge-store.jsonl"
    from rlvr import strategy_store as ss  # noqa: PLC0415 — the pin
    assert p == ss.store_path().parent / "knowledge-store.jsonl"
