# -*- coding: utf-8 -*-
"""tests/test_settlement_family_move_1004.py — the settlement family move
(issue 1004 R2a).

The rollout ledger, the attributed-waste grain, and the cost-event face
move their IO onto the consolidated settlement family
(``consolidated_ledger.append/read``): ``runs/settlement.jsonl`` becomes
the single live file, the per-module flock/lock rels retire (the
consolidated append's lock is the ONE guard), public APIs stay
byte-compatible, and the compat window stays (LEGACY entries remain
until the schema-cutover slice).

Pins defined here:
  1. API compatibility  record/settle/fold/settled/pending_settlement
     signatures and semantics unchanged; rows land in the family file
     carrying their EXISTING ``rollout-ledger/1`` stamp; the legacy rel
     is no longer written by production code.
  2. Lock pin           the per-module lock rel never appears on disk;
     the consolidated ``.settlement.lock`` is the single guard.
  3. Cost rows          new cost rows carry a registered ``cost-event/1``
     stamp at write; the reader filters by stamp prefix so historical
     UNSTAMPED rows and new stamped rows coexist under one read face.
  4. Chronology         legacy ``runs/rollout-ledger.jsonl`` rows first,
     then live rows — the dual-read order the future migration must
     reproduce.
  5. Seal interplay     a sealed row written through the family path is
     still accepted by ``trusted_rows`` (an armed workspace must not
     refuse its own rows because the file name changed).
  6. Waste rows         ``attributed-waste/1`` rows land in the family
     file; the waste writer's own lock rel retires.
  7. Fold/settled ride ROW IDENTITY across the file boundary — never
     file position.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import ast
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rlvr.consolidated_ledger as cl  # noqa: E402
import rlvr.ledger as rl  # noqa: E402
import rlvr.learning_seal as seal  # noqa: E402
import rlvr.step_grain as sg  # noqa: E402
import cost_gate as cg  # noqa: E402
import tuition_curve as tc  # noqa: E402

ROLL_STAMP = "rollout-ledger/1"
COST_STAMP = "cost-event/1"
WASTE_STAMP = "attributed-waste/1"


def _sig(type_: str, source: str, value, ts="2026-11-08T00:00:00Z",
         **extra):
    sig = {"type": type_, "source": source, "value": value, "ts": ts}
    sig.update(extra)
    return sig


def _rollout_row(rid: str, kind: str, anchor: str, ts: str,
                 signals: list[dict], settlement: dict | None = None,
                 reward: float | None = None) -> dict:
    return {"schema": ROLL_STAMP, "rollout_id": rid, "kind": kind,
            "anchor": anchor, "ts": ts, "signals": signals,
            "reward": reward, "settlement": settlement}


def _family_rows(ws: Path) -> list[dict]:
    p = ws / "runs" / "settlement.jsonl"
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------- 1. API compatibility ----------

class TestApiCompatibility:
    def test_public_signatures_unchanged(self):
        expect = {
            "record": ["ws", "kind", "anchor", "signals", "rollout_id",
                       "ts"],
            "settle": ["ws", "rollout_id", "settlement", "ts"],
            "fold": ["ws", "rollout_id"],
            "settled": ["ws", "kind", "window"],
            "pending_settlement": ["ws"],
            "read": ["ws"],
        }
        for name, params in expect.items():
            got = list(inspect.signature(getattr(rl, name)).parameters)
            assert got == params, f"{name}{got} != {params}"

    def test_record_settle_land_in_family_file_with_existing_stamp(
            self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        res = rl.record(ws, kind="task", anchor="C-1",
                        signals=[_sig("claim_terminal", "rollup",
                                      "PROVEN")])
        assert res["appended"] is True
        rows = _family_rows(ws)
        assert len(rows) == 1
        assert rows[0]["schema"] == ROLL_STAMP == rl.SCHEMA
        assert rows[0]["rollout_id"] == "task/C-1"
        # the legacy rel is NOT written by production code anymore
        assert not (ws / "runs" / "rollout-ledger.jsonl").exists()
        st = rl.settle(ws, "task/C-1",
                       settlement={"reward": 1.0, "band": "SETTLED_GREEN",
                                   "rule_id": "task/oracle-green",
                                   "evidence_refs": ["runs/oracle.json"]})
        assert st["appended"] is True
        rows = _family_rows(ws)
        assert len(rows) == 2
        assert rows[1]["schema"] == ROLL_STAMP
        assert rows[1]["settlement"]["band"] == "SETTLED_GREEN"

    def test_semantics_smoke_dedupe_amendment_pending_settled(
            self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        sigs = [_sig("claim_terminal", "rollup", "PROVEN")]
        a = rl.record(ws, kind="task", anchor="C-1", signals=sigs)
        b = rl.record(ws, kind="task", anchor="C-1", signals=sigs)
        assert a["appended"] and not b["appended"]
        assert b["reason"] == "duplicate: unchanged"
        assert len(rl.pending_settlement(ws)) == 1
        rl.settle(ws, "task/C-1",
                  settlement={"reward": 1.0, "band": "SETTLED_GREEN",
                              "rule_id": "task/oracle-green",
                              "evidence_refs": []})
        again = rl.settle(ws, "task/C-1",
                          settlement={"reward": 1.0, "band": "SETTLED_GREEN",
                                      "rule_id": "task/oracle-green",
                                      "evidence_refs": []})
        assert again["appended"] is False
        assert again["reason"] == "duplicate: already settled"
        settled = rl.settled(ws, kind="task")
        assert len(settled) == 1
        assert settled[0]["band"] == "SETTLED_GREEN"
        assert rl.pending_settlement(ws) == []
        fold = rl.fold(ws, "task/C-1")
        assert fold is not None and fold["settlement"]["reward"] == 1.0
        assert rl.settled(ws, kind="self_distill") == []

    def test_consolidated_read_face_is_the_family_source(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rl.record(ws, kind="task", anchor="C-2",
                  signals=[_sig("s", "src", 1)])
        family = cl.read(ws, "settlement", schema_prefix="rollout-ledger")
        assert [r["rollout_id"] for r in family] == ["task/C-2"]


# ---------- 2. the lock pin ----------

class TestSingleGuardLock:
    def test_per_module_lock_rel_never_appears(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rl.record(ws, kind="task", anchor="C-1",
                  signals=[_sig("s", "src", 1)])
        rl.settle(ws, "task/C-1",
                  settlement={"reward": 1.0, "band": "SETTLED_GREEN",
                              "rule_id": "r", "evidence_refs": []})
        sg.record_attributed_waste(ws, claim_ref="C-1", step_id="s1",
                                   kind="wall_s_overrun", budget_s=1.0,
                                   actual_s=2.0)
        # the retired per-module lock rels never touch the disk
        assert not (ws / "runs" / ".rollout-ledger.lock").exists()
        assert not (ws / "runs" / ".attributed-waste.lock").exists()
        assert not hasattr(rl, "LOCK_REL")
        assert not hasattr(rl, "_locked_append")
        assert not hasattr(rl, "_lock_path")
        # the consolidated append's lock is the ONE guard
        assert (ws / "runs" / ".settlement.lock").exists()

    def test_concurrent_record_writers_all_land(self, tmp_path):
        """The consolidated flock serializes the family append section
        (the concurrency guarantee moves with the IO, it does not
        weaken)."""
        ws = tmp_path / "ws"
        ws.mkdir()
        import threading

        def worker(i: int) -> None:
            rl.record(ws, kind="task", anchor=f"C-{i:03d}",
                      signals=[_sig("s", "src", i)])
        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        rows = rl.read(ws)
        assert len(rows) == 20
        assert len({r["rollout_id"] for r in rows}) == 20


# ---------- 3. cost rows ----------

class TestCostRows:
    def test_native_stamp_is_registered(self):
        assert COST_STAMP in cl.NATIVE_SCHEMAS["settlement"]
        # the legacy rel registers the stamp too: the coexistence face —
        # unstamped historical rows pass a cost-prefixed family read,
        # and the migration stamps them (the retire-CLI's verified
        # counts).
        assert cl.LEGACY["settlement"]["cost_events.jsonl"] == \
            (COST_STAMP,)

    def test_append_event_writes_stamped_family_row(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        cg.append_event(ws, 12.5, "hook")
        rows = _family_rows(ws)
        assert len(rows) == 1
        assert rows[0]["schema"] == COST_STAMP
        assert rows[0]["amount"] == 12.5
        assert rows[0]["source"] == "hook"
        assert rows[0]["ts"].endswith("Z")
        assert not (ws / "cost_events.jsonl").exists()

    def test_hook_writer_writes_stamped_family_row(self, tmp_path):
        import importlib.util
        name = "cost_input_capture_1004"
        mod = sys.modules.get(name)
        if mod is None:
            spec = importlib.util.spec_from_file_location(
                name, ROOT / "hooks" / "cost_input_capture.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        rc = mod.process_event({
            "tool_name": "Agent",
            "tool_response": "... COST WARNING: session total ~$12.34 ...",
            "cwd": str(ws)})
        assert rc == 0
        rows = _family_rows(ws)
        assert len(rows) == 1
        assert rows[0]["schema"] == COST_STAMP
        assert rows[0]["amount"] == 12.34
        assert rows[0]["source"] == "Agent"
        assert not (ws / "cost_events.jsonl").exists()

    def test_family_append_survives_a_broken_facade_sibling(
            self, tmp_path, monkeypatch):
        """A broken rlvr facade sibling must not starve cost capture:
        the record face falls back to a DIRECT file-location load of the
        ledger core and the row still lands."""
        import importlib.util
        name = "cost_input_capture_1004fb"
        mod = sys.modules.get(name)
        if mod is None:
            spec = importlib.util.spec_from_file_location(
                name, ROOT / "hooks" / "cost_input_capture.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)

        class _BrokenFacade:
            def __getattr__(self, attr):
                raise ImportError("simulated broken facade sibling")

        monkeypatch.setitem(sys.modules, "rlvr", _BrokenFacade())
        rc = mod.process_event({
            "tool_name": "Agent",
            "tool_response": "... COST WARNING: session total ~$9.99 ...",
            "cwd": str(ws)})
        assert rc == 0
        rows = _family_rows(ws)
        assert len(rows) == 1
        assert rows[0]["schema"] == COST_STAMP
        assert rows[0]["amount"] == 9.99
        assert not (ws / "cost_events.jsonl").exists()

    def test_reader_coexists_legacy_unstamped_and_new_stamped(
            self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "cost_events.jsonl").write_text(
            json.dumps({"ts": "2026-11-01T00:00:00Z", "amount": 3.0,
                        "source": "legacy"}) + "\n",
            encoding="utf-8")
        cg.append_event(ws, 4.0, "hook")
        events = cg.load_events(ws)
        assert [e["amount"] for e in events] == [3.0, 4.0]
        # the legacy file was not appended to — the new row rode the family
        assert len((ws / "cost_events.jsonl").read_text(
            encoding="utf-8").splitlines()) == 1

    def test_cost_single_source_reader_sees_both_faces(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "cost_events.jsonl").write_text(
            json.dumps({"ts": "2026-11-01T00:00:00Z", "amount": 3.0,
                        "source": "legacy"}) + "\n",
            encoding="utf-8")
        cg.append_event(ws, 4.5, "hook")
        state = tc.cost_state(ws)
        assert state["spent"] == 7.5
        assert state["latest"] == 4.5


# ---------- 4. chronology (the dual-read order) ----------

class TestChronology:
    def test_legacy_rows_first_then_live(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        legacy_rows = [
            _rollout_row("task/A", "task", "A", "2026-10-01T00:00:00Z",
                         [_sig("s", "src", "a")]),
            _rollout_row("task/B", "task", "B", "2026-10-02T00:00:00Z",
                         [_sig("s", "src", "b")]),
        ]
        p = ws / "runs" / "rollout-ledger.jsonl"
        p.parent.mkdir(parents=True)
        p.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n"
                    for r in legacy_rows), encoding="utf-8")
        rl.record(ws, kind="task", anchor="C",
                  signals=[_sig("s", "src", "c")])
        ids = [r["rollout_id"] for r in rl.read(ws)]
        assert ids == ["task/A", "task/B", "task/C"]
        # the dual-read order the future migration must reproduce
        family = cl.read(ws, "settlement", schema_prefix="rollout-ledger")
        assert [r["rollout_id"] for r in family] == ids

    def test_compat_window_stays_legacy_entries_registered(self):
        # the schema cutover slice removes these — not this one.
        assert "runs/rollout-ledger.jsonl" in cl.LEGACY["settlement"]
        assert "runs/attributed-waste.jsonl" in cl.LEGACY["settlement"]
        assert "cost_events.jsonl" in cl.LEGACY["settlement"]
        assert inspect.signature(cl.read).parameters[
            "include_legacy"].default is True

    def test_fold_and_settled_ride_row_identity_across_the_boundary(
            self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        legacy = _rollout_row(
            "task/X", "task", "X", "2026-10-01T00:00:00Z",
            [_sig("claim_terminal", "rollup", "DEFERRED")],
            settlement={"reward": 0.0, "band": "NEUTRAL",
                        "rule_id": "task/pending",
                        "evidence_refs": [], "settled_ts":
                        "2026-10-01T01:00:00Z"},
            reward=0.0)
        p = ws / "runs" / "rollout-ledger.jsonl"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
        # identity dedupe across the boundary (same signal set -> no-op)
        dup = rl.record(ws, kind="task", anchor="X",
                        signals=[_sig("claim_terminal", "rollup",
                                      "DEFERRED")])
        assert dup["appended"] is False
        # the re-settlement amendment lands in the FAMILY file
        st = rl.settle(ws, "task/X",
                       settlement={"reward": 1.0, "band": "SETTLED_GREEN",
                                   "rule_id": "task/oracle-green",
                                   "evidence_refs": []})
        assert st["appended"] is True
        assert all(r["rollout_id"] == "task/X" for r in _family_rows(ws))
        fold = rl.fold(ws, "task/X")
        assert fold["ts"] == "2026-10-01T00:00:00Z"  # identity: FIRST row
        assert fold["signals"][0]["value"] == "DEFERRED"
        assert fold["settlement"]["reward"] == 1.0  # settlement: LAST
        settled = rl.settled(ws, kind="task")
        assert len(settled) == 1
        assert settled[0]["band"] == "SETTLED_GREEN"


# ---------- 5. the seal interplay ----------

class TestSealInterplay:
    def test_armed_workspace_accepts_its_own_family_rows(
            self, tmp_path, monkeypatch):
        key = tmp_path / "learning.key"
        key.write_bytes(b"k" * 48)
        monkeypatch.setattr(seal, "KEY_PATH", key)
        monkeypatch.setattr(seal, "_ANCHOR", {"build": None})
        assert seal.armed() is True
        ws = tmp_path / "ws"
        ws.mkdir()
        row = _rollout_row("task/C-1", "task", "C-1",
                           "2026-11-08T00:00:00Z",
                           [_sig("claim_terminal", "rollup", "PROVEN")])
        sealed = seal.sign_row(row)
        assert "seal" in sealed
        assert cl.append(ws, "settlement", sealed) is True
        out = rl.read(ws)
        assert len(out) == 1
        ok, why = seal.verify_row(out[0])
        assert ok is True, why
        kept = seal.trusted_rows(out, op="test.family-move")
        assert kept == out

    def test_unarmed_rows_ride_legacy_with_notice(self, tmp_path,
                                                  monkeypatch):
        missing = tmp_path / "no-key.key"
        monkeypatch.setattr(seal, "KEY_PATH", missing)
        monkeypatch.setattr(seal, "_NOTICE", {"shown": False})
        assert seal.armed() is False
        ws = tmp_path / "ws"
        ws.mkdir()
        rl.record(ws, kind="task", anchor="C-1",
                  signals=[_sig("s", "src", 1)])
        rows = rl.read(ws)
        assert len(rows) == 1
        assert seal.trusted_rows(rows, op="test.unarmed") == rows


# ---------- 6. waste rows ----------

class TestWasteRows:
    def test_waste_lands_in_family_file_with_own_stamp(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        row = sg.record_attributed_waste(ws, claim_ref="C-5",
                                         step_id="step-1",
                                         kind="wall_s_overrun",
                                         budget_s=600.0, actual_s=900.0)
        assert row is not None
        assert row["schema"] == WASTE_STAMP
        rows = _family_rows(ws)
        assert rows == [row]
        assert not (ws / "runs" / "attributed-waste.jsonl").exists()
        # the waste read face: the family read filtered by its stamp
        family = cl.read(ws, "settlement", schema_prefix="attributed-waste")
        assert [r["step_id"] for r in family] == ["step-1"]

    def test_waste_write_failure_is_fail_open(self, tmp_path,
                                              monkeypatch):
        ws = tmp_path / "ws"
        ws.mkdir()

        def refuse(target_ws, family, row):
            assert family == "settlement"
            return False
        monkeypatch.setattr(cl, "append", refuse)
        assert sg.record_attributed_waste(ws, claim_ref="C-5",
                                          step_id="s", kind="k",
                                          budget_s=1.0,
                                          actual_s=2.0) is None


# ---------- 7. production writers never touch the legacy rels ----------

_WRITE_METHODS = {"open", "write_text", "write_bytes", "unlink",
                  "replace", "rename", "touch", "mkdir"}
_LEGACY_RELS = ("runs/rollout-ledger.jsonl", "runs/attributed-waste.jsonl",
                "cost_events.jsonl")
# sanctioned legacy-face machinery: the migration core reads/moves the
# legacy rels and the retire CLI extends it — both retire in the
# schema-cutover / retire-CLI slices.
_MIGRATION_FACES = ("rlvr/consolidated_ledger.py",
                    "consolidate_ledgers.py")


def _production_sources() -> list[Path]:
    out = [p for base in (SCRIPTS, ROOT / "hooks")
           for p in sorted(base.rglob("*.py"))]
    return [p for p in out
            if p.name != "conftest.py"
            and not any(face in p.as_posix() for face in _MIGRATION_FACES)]


class TestNoLegacyWrites:
    def test_no_production_call_writes_a_legacy_rel(self):
        offenders: list[str] = []
        for path in _production_sources():
            src = path.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = (func.attr if isinstance(func, ast.Attribute)
                        else getattr(func, "id", ""))
                if name not in _WRITE_METHODS:
                    continue
                seg = ast.get_source_segment(src, node) or ""
                if any(rel in seg for rel in _LEGACY_RELS):
                    offenders.append(f"{path.relative_to(ROOT)}: {seg[:80]}")
        assert not offenders, (
            "production code must not write the settlement family's "
            "legacy rels (the writers ride the consolidated family):\n"
            + "\n".join(offenders))

    def test_moved_modules_stay_model_call_free(self):
        """The settlement path stays machine-only (defense in depth; the
        engine-level pins live in the settlement suites)."""
        banned = ("llm", "model", "judge", "anthropic", "openai",
                  "subprocess", "socket", "urllib", "http")
        targets = [SCRIPTS / "rlvr" / "ledger.py",
                   SCRIPTS / "rlvr" / "step_grain.py",
                   SCRIPTS / "cost_gate.py",
                   ROOT / "hooks" / "cost_input_capture.py"]
        for path in targets:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported: list[str] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.append(node.module)
            bad = [m for m in imported for b in banned if b in m.lower()]
            assert not bad, f"{path.name} must stay machine-only, saw {bad}"
