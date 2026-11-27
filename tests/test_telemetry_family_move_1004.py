# -*- coding: utf-8 -*-
"""tests/test_telemetry_family_move_1004.py — the telemetry family move
(issue 1004 R2b).

The intervention grain, the prediction ledger, the mainline situation
stream, and the strategy-log dispatch face move their IO onto the
consolidated telemetry family (``consolidated_ledger.append/read``):
``runs/telemetry.jsonl`` becomes the single live file, the per-module
IO silos retire (the consolidated append's lock is the ONE guard),
public APIs stay byte-compatible. (Issue-1004 R3, the schema cutover,
deleted the compat window this slice's dual-read pins served: read() is
family-only now, chronology IS file order, and the R4 migrate fixture
pins the global order instead. The
entries remain until the schema-cutover slice).

Pins defined here:
  1. API compatibility  record_intervention / register / settle /
     read_ledger / append_snapshot / read_situations /
     _log_strategy_dispatch signatures unchanged; rows land in the
     family file carrying their registered stamps; the legacy rels are
     no longer written by production code.
  2. Lock pin           no per-module lock rel appears on disk; the
     consolidated ``.telemetry.lock`` is the single guard.
  3. Strategy stamp     new strategy-log rows carry the registered
     ``strategy-log/1`` stamp at write; the reader filters by stamp
     prefix so historical UNSTAMPED rows and new stamped rows coexist
     under one read face (the pre-stamp rule), never leaking across
     schemas.
  4. Stamp discipline   the multi-schema family file leaks nothing
     across prefix reads.
     dual-read order the future migration must reproduce.
  5. Seal interplay     no telemetry producer signs; a sealed row
     through the telemetry family path still passes trusted_rows (an
     armed workspace must not refuse its own rows because the file
     name changed).
  6. Read faces ride    the strategy-log join (triples), the issue-109
     first-dispatch face (dispatch_gate), and the rl-sampler-exit
     liveness fingerprint all read the family.
  7. Writer tripwire    no production writer names a telemetry
     rel LITERAL inside a write-method call (a literal tripwire, not a
     full data-flow wall: a variable-mediated writer would pass — the
     sanctioned faces define the legacy rels as documented compat-window
     constants and touch no write call with them).

The R2a budget-present retarget (state.py ``_cost_face_present``) is
guarded here too — this slice edits the same module and must not undo
it.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rlvr.consolidated_ledger as cl  # noqa: E402
import rlvr.prediction_ledger as pl  # noqa: E402
import rlvr.state as rstate  # noqa: E402
import rlvr.step_ledger as sl  # noqa: E402
import rlvr.triples as tr  # noqa: E402
import dispatch_gate as dg  # noqa: E402
import rlvr.learning_seal as seal  # noqa: E402

INTERVENTION_STAMP = "intervention/1"
PREDICTION_STAMP = "prediction-ledger/1"
SITUATION_STAMP = "situation/1"
STRATEGY_STAMP = "strategy-log/1"

#: the four telemetry legacy rels this slice retires the writers of
TELEMETRY_LEGACY_RELS = (
    "runs/interventions.jsonl",
    "runs/predictions.jsonl",
    "runs/situation-stream.jsonl",
    "runs/strategy-log.jsonl",
)


def _family_rows(ws: Path) -> list[dict]:
    p = ws / "runs" / "telemetry.jsonl"
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _write_rows(ws: Path, rel: str, rows: list[dict]) -> None:
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                         for r in rows), encoding="utf-8")


# ---------- 1. API compatibility ----------

class TestApiCompatibility:
    def test_public_signatures_unchanged(self):
        expect = {
            # (module, name) -> parameter list (None = positional order
            # unchecked, only the public parameter names pinned)
            (sl.__name__, "record_intervention"):
                ["ws", "trigger", "actor", "subject", "note", "ts"],
            (pl.__name__, "register"):
                ["ws", "claim_id", "statement", "discriminator", "actor"],
            (pl.__name__, "settle"): ["ws", "prediction_id", "outcome"],
            (pl.__name__, "read_ledger"): ["ws"],
            (pl.__name__, "pending"): ["ws"],
            (pl.__name__, "backlog"): ["ws"],
            (rstate.__name__, "append_snapshot"):
                ["ws", "trigger", "tick", "ts"],
            (rstate.__name__, "read_situations"): ["ws"],
            (dg.__name__, "_log_strategy_dispatch"):
                ["ws", "claim_id", "prompt_text"],
        }
        mod_of = {sl.__name__: sl, pl.__name__: pl,
                  rstate.__name__: rstate, dg.__name__: dg}
        for (mod_name, name), params in expect.items():
            got = list(inspect.signature(
                getattr(mod_of[mod_name], name)).parameters)
            assert got == params, f"{mod_name}.{name}{got} != {params}"

    def test_intervention_lands_in_family_file_with_own_stamp(
            self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        row = sl.record_intervention(ws, trigger="operator-stop",
                                     actor="owner", subject="C-1",
                                     note="pulled the plug")
        assert row is not None
        rows = _family_rows(ws)
        assert rows == [row]
        assert rows[0]["schema"] == INTERVENTION_STAMP == \
            sl.INTERVENTION_SCHEMA
        # the legacy rel is NOT written by production code anymore
        assert not (ws / "runs" / "interventions.jsonl").exists()

    def test_prediction_rows_land_in_family_file_with_own_stamp(
            self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        row = pl.register(ws, "C-2", "the toolchain pin holds",
                          "sha256 digest changes", actor="test-rig")
        assert row is not None
        rows = _family_rows(ws)
        assert len(rows) == 1
        assert rows[0]["schema"] == PREDICTION_STAMP == pl.SCHEMA
        assert rows[0]["id"] == "P-1"
        assert rows[0]["status"] == pl.STATUS_PENDING
        settled = pl.settle(ws, "P-1", pl.STATUS_CONFIRMED)
        assert settled is not None  # the transition row
        rows = _family_rows(ws)
        assert len(rows) == 2
        assert rows[1]["schema"] == PREDICTION_STAMP
        assert rows[1]["status"] == pl.STATUS_CONFIRMED
        assert not (ws / "runs" / "predictions.jsonl").exists()

    def test_situation_row_lands_in_family_file_with_own_stamp(
            self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        res = rstate.append_snapshot(ws, trigger="worker_return", tick=2)
        assert res["appended"] is True
        rows = _family_rows(ws)
        assert len(rows) == 1
        assert rows[0]["schema"] == SITUATION_STAMP == \
            rstate.SITUATION_SCHEMA
        assert rows[0]["trigger"] == "worker_return"
        assert not (ws / "runs" / "situation-stream.jsonl").exists()

    def test_strategy_row_lands_in_family_file_with_own_stamp(
            self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        dg._log_strategy_dispatch(ws, "C-1", "go [strategy s1]")
        rows = _family_rows(ws)
        assert len(rows) == 1
        assert rows[0]["schema"] == STRATEGY_STAMP
        assert rows[0]["event"] == "dispatch"
        assert rows[0]["strategy"] == "s1"
        assert rows[0]["declared"] is True
        assert rows[0]["claim"] == "C-1"
        assert "attempts_at_snapshot" in rows[0]
        assert not (ws / "runs" / "strategy-log.jsonl").exists()

    def test_budget_present_retarget_stays(self, tmp_path):
        """The R2a retarget (state.py _cost_face_present) is untouched by
        this slice's edits to the same module: a settlement-family cost
        row keeps the budget dim present."""
        import cost_gate as cg
        ws = tmp_path / "ws"
        ws.mkdir()
        cg.append_event(ws, 12.5, "hook")
        snap = rstate.snapshot(ws)
        assert snap["budget"]["present"] is True


# ---------- 2. the lock pin ----------

class TestSingleGuardLock:
    def test_family_lock_is_the_only_lock_rels_on_disk(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        sl.record_intervention(ws, trigger="t", actor="a", subject="s")
        pl.register(ws, "C-1", "statement", "discriminator", actor="a")
        rstate.append_snapshot(ws, trigger="terminal")
        dg._log_strategy_dispatch(ws, "C-1", "[strategy s1] go")
        # the consolidated append's lock is the ONE guard
        assert (ws / "runs" / ".telemetry.lock").exists()
        # no per-module lock rel ever appears
        for lock in (".interventions.lock", ".predictions.lock",
                     ".situation-stream.lock", ".strategy-log.lock"):
            assert not (ws / "runs" / lock).exists(), lock
        # the moved modules carry no lock machinery of their own
        assert not hasattr(sl, "_locked_append")
        assert not hasattr(sl, "_lock_path")


# ---------- 3. the strategy stamp + coexistence ----------

class TestStrategyStamp:
    def test_native_stamp_is_registered(self):
        # registered so a dead dispatch writer reads 0, never absent
        # (the historical unstamped rows get the stamp at migration —
        # the R4 retire-CLI's verified counts)
        assert STRATEGY_STAMP in cl.NATIVE_SCHEMAS["telemetry"]
        assert STRATEGY_STAMP in cl.REGISTERED["telemetry"]

    def test_prefix_discipline_no_cross_schema_leak(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        dg._log_strategy_dispatch(ws, "C-1", "[strategy s1] go")
        rstate.append_snapshot(ws, trigger="terminal")
        sl.record_intervention(ws, trigger="t", actor="a", subject="s")
        strategies = cl.read(ws, "telemetry",
                             schema_prefix="strategy-log")
        situations = cl.read(ws, "telemetry", schema_prefix="situation")
        interventions = cl.read(ws, "telemetry",
                                schema_prefix="intervention")
        assert [r["schema"] for r in strategies] == [STRATEGY_STAMP]
        assert [r["schema"] for r in situations] == [SITUATION_STAMP]
        assert [r["schema"] for r in interventions] == [INTERVENTION_STAMP]


# ---------- 5. the seal interplay ----------

class TestSealInterplay:
    def test_telemetry_producers_do_not_sign(self):
        """No telemetry producer seals rows before append (the seal wall
        is the settlement/learning faces' machinery) — pinned so a silent
        signing introduction cannot bypass this suite's IO pins."""
        banned = "learning_seal"
        targets = [SCRIPTS / "rlvr" / "step_ledger.py",
                   SCRIPTS / "rlvr" / "prediction_ledger.py",
                   SCRIPTS / "rlvr" / "state.py",
                   SCRIPTS / "rlvr" / "triples.py"]
        for path in targets:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    assert node.module != banned, path.name
                if isinstance(node, ast.Import):
                    assert not any(a.name == banned for a in node.names), \
                        path.name

    def test_armed_workspace_accepts_its_own_family_rows(
            self, tmp_path, monkeypatch):
        key = tmp_path / "learning.key"
        key.write_bytes(b"k" * 48)
        monkeypatch.setattr(seal, "KEY_PATH", key)
        monkeypatch.setattr(seal, "_ANCHOR", {"build": None})
        assert seal.armed() is True
        ws = tmp_path / "ws"
        ws.mkdir()
        row = {"schema": SITUATION_STAMP, "ts": "2026-11-08T00:00:00Z",
               "trigger": "terminal", "tick": 1, "state": {},
               "signature": "", "signature_hash": ""}
        sealed = seal.sign_row(row)
        assert "seal" in sealed
        assert cl.append(ws, "telemetry", sealed) is True
        out = rstate.read_situations(ws)
        assert len(out) == 1
        ok, why = seal.verify_row(out[0])
        assert ok is True, why
        kept = seal.trusted_rows(out, op="test.telemetry-family-move")
        assert kept == out


# ---------- 6. the read faces ride the family ----------

class TestReadFacesRide:
    def test_pq_first_dispatch_face_sees_family_rows(self, tmp_path):
        import yaml
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(yaml.safe_dump(
            {"claims": [
                {"id": "C-1", "answers_question": "q1"},
                {"id": "C-2", "answers_question": "q1"}]}),
            encoding="utf-8")
        qmap = {"C-1": "q1", "C-2": "q1"}
        assert dg._pq_dispatched_before(ws, "q1", qmap) is False
        dg._log_strategy_dispatch(ws, "C-2", "go [strategy s1]")
        assert dg._pq_dispatched_before(ws, "q1", qmap) is True

    def test_triples_join_reads_family_rows(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        dg._log_strategy_dispatch(ws, "C-3", "go [strategy exploit-b]")
        assert tr._strategy_arm_by_claim(ws) == {"C-3": "exploit-b"}

    def test_window_boundary_resolves_identically_in_both_faces(
            self, tmp_path):
        """ONE window semantic value: the triples arm join and the
        issue-109 first-dispatch face window the SAME strategy-log
        stream with the SAME rlvr.triples constant — a claim whose
        answering dispatch sits inside the window resolves in BOTH
        faces; one outside the window resolves in NEITHER (the pre-fix
        divergence — triples unwindowed while the gate windowed — is
        the bug shape)."""
        import yaml
        from rlvr import triples as _tr
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(yaml.safe_dump(
            {"claims": [{"id": "C-2", "answers_question": "q1"}]}),
            encoding="utf-8")
        # ONLY C-2 answers q1 (C-9 deliberately absent from the map —
        # its in-window rows must never satisfy the gate face)
        qmap = {"C-2": "q1"}
        # MAX+5 rows: the FIRST 3 are C-2 dispatches (the only q1
        # answers); the rest ride C-9 with strategy "s". The last-MAX
        # window drops all three C-2 rows.
        rows = [{"schema": STRATEGY_STAMP,
                 "ts": "2026-11-08T00:00:00Z", "event": "dispatch",
                 "strategy": "s", "declared": True,
                 "claim": "C-2" if i < 3 else "C-9",
                 "attempts_at_snapshot": 0}
                for i in range(_tr.STRATEGY_LOG_MAX + 5)]
        _write_rows(ws, "runs/telemetry.jsonl", rows)
        # OUTSIDE the window: BOTH faces read no C-2 history
        assert dg._pq_dispatched_before(ws, "q1", qmap) is False
        assert "C-2" not in tr._strategy_arm_by_claim(ws)
        assert "C-9" in tr._strategy_arm_by_claim(ws)  # inside: visible
        # a fresh C-2 dispatch slides the claim back INSIDE the window:
        # BOTH faces resolve it, identically
        dg._log_strategy_dispatch(ws, "C-2", "go [strategy exploit-c]")
        assert dg._pq_dispatched_before(ws, "q1", qmap) is True
        assert tr._strategy_arm_by_claim(ws).get("C-2") == "exploit-c"

    def test_rl_sampler_exit_fingerprint_reads_the_family(self, tmp_path):
        spec = importlib.util.spec_from_file_location(
            "liveness_gate_1004", ROOT / "devkit" / "liveness_gate.py")
        lg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lg)
        ws = tmp_path / "ws"
        ws.mkdir()
        dg._log_strategy_dispatch(ws, "C-1",
                                  "retry declaring the sampled exit "
                                  "[strategy sampled]")
        fp = next(f for f in lg.load_fingerprints()["fingerprints"]
                  if f["id"] == "rl-sampler-exit")
        ok, detail = lg.evaluate_fingerprint(ws, fp)
        assert ok, detail


# ---------- 7. production writers never touch the legacy rels ----------

_WRITE_METHODS = {"open", "write_text", "write_bytes", "unlink",
                  "replace", "rename", "touch", "mkdir"}
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
        """Literal tripwire (not a data-flow wall): a production write
        call whose source segment names a telemetry legacy rel fails;
        a variable-mediated writer (path built in steps) would pass —
        the sanctioned faces define the legacy rels as documented
        compat-window constants and never touch a write call with
        them."""
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
                if any(rel in seg for rel in TELEMETRY_LEGACY_RELS):
                    offenders.append(f"{path.relative_to(ROOT)}: {seg[:80]}")
        assert not offenders, (
            "production writers must not name a telemetry legacy rel "
            "literal in a write call (literal tripwire — the writers "
            "ride the consolidated family; variable-mediated writers "
            "are out of this tripwire's reach):\n"
            + "\n".join(offenders))
