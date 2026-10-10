# -*- coding: utf-8 -*-
"""Script-harvest wiring + fixture chain (the post-run face, dry mode).

What this file pins, per the script-harvest spec (openspec issue-477):
  - the three audit words ride BOTH vocabularies and the 17-field row
    shape holds (e2e stream + production emit vocabulary);
  - the e2e host's finalize step fires the whole chain post-run:
    candidate -> staged double-run verification -> run-local landing ->
    playbook record -> complete audit trail + harvest ledger counters;
  - the negatives: nothing swept -> no rows; a raising engine never
    breaks the host (fail-open); contamination never sweeps;
  - the fixture substrate lives in tests/fixtures/harvest-477/
    (deterministic candidate, nondeterministic candidate, PROVEN fact).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "harvest-477"
for p in (str(SCRIPTS),):
    if p not in sys.path:
        sys.path.insert(0, p)

from e2e import audit, checkpoints, llm_faces, model  # noqa: E402
import online_distill as od  # noqa: E402
import script_harvest as sh  # noqa: E402

ANCHORS = {
    "goal_verbatim": "Extract the digest of the anchored sample.",
    "success_criterion": "The digest line matches the expected bytes.",
    "verification_method": "reproduction",
}


def _mk_ctx(tmp_path: Path, mode: str = "dry"):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    ev_dir = tmp_path / "ev"
    ev_dir.mkdir(parents=True, exist_ok=True)
    state = model.RunState(
        run_id="r1", unit="harvest-fixture", family="smoke",
        repo=str(ROOT), task_dir=str(ROOT / "eval/v1/tasks/smoke"),
        ws=str(ws), evidence_dir=str(ev_dir), budget_seconds=100,
        llm_mode=mode, started_ts="2026-10-01T00:00:00Z",
        started_monotonic=0.0, anchors=dict(ANCHORS))
    runner = llm_faces.CommandRunner(ROOT)
    face = llm_faces.face_for(mode, runner, ev_dir)
    return checkpoints.RunContext(
        state=state, runner=runner, face=face,
        clock=_FakeClock(), sleep_fn=lambda _s: None)


class _FakeClock:
    def monotonic(self) -> float:
        return 0.0


def stage_fixture_ws(ws: Path) -> None:
    """The fixture workspace: the anchored sample + the success-traced
    deterministic candidate + the one-off + the nondeterministic
    candidate, all written "during the run" (mtimes are fresh)."""
    bins = ws / "bins"
    bins.mkdir(exist_ok=True)
    (bins / "sample.bin").write_bytes((FIXTURE / "sample.blob").read_bytes())
    scripts = ws / "scripts"
    scripts.mkdir(exist_ok=True)
    (scripts / "byte_digest.py").write_text(
        (FIXTURE / "byte_digest.py").read_text(encoding="utf-8"),
        encoding="utf-8")
    (scripts / "byte_noise.py").write_text(
        (FIXTURE / "byte_noise.py").read_text(encoding="utf-8"),
        encoding="utf-8")
    (scripts / "scratch_helper.py").write_text(
        "# a one-off: no document ever cites this file\n",
        encoding="utf-8")
    facts = ws / "facts"
    facts.mkdir(exist_ok=True)
    (facts / "F007-sample-digest.md").write_text(
        (FIXTURE / "fact-F007.md").read_text(encoding="utf-8"),
        encoding="utf-8")
    (facts / "F008-byte-noise-digest.md").write_text(
        (FIXTURE / "fact-F008.md").read_text(encoding="utf-8"),
        encoding="utf-8")


def _audit_rows(ws: Path) -> list:
    path = audit.audit_path(ws)
    assert path.is_file(), "missing unified audit stream"
    return [json.loads(ln) for ln
            in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------------------------------------------------------------------------
# vocabulary
# ---------------------------------------------------------------------------

class TestHarvestVocabulary:
    def test_three_words_in_e2e_vocabulary_and_category(self):
        for word in ("harvest_scan", "script_harvested", "harvest_landed"):
            assert word in audit.AUDIT_ACTIONS
        assert "harvest" in audit.CATEGORIES
        for word in ("harvest_scan", "script_harvested",
                     "harvest_landed"):
            assert audit._category(word) == "harvest"

    def test_three_words_in_production_emit_vocabulary(self):
        import event_taxonomy
        for word in ("harvest_scan", "script_harvested",
                     "harvest_landed"):
            assert word in event_taxonomy.EMIT_ACTIONS

    def test_emitter_rows_carry_the_17_field_schema(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        assert audit.emit_harvest_scan(
            str(ws), swept=2, candidates=1, skipped=1, archived=0,
            playbook="runs/harvest-playbook.json")
        assert audit.emit_script_harvested(
            str(ws), "byte-digest", script="scripts/byte_digest.py",
            signals={"verified_trace": ["F007-sample-digest"],
                     "reuse_trace": []},
            facts=[{"id": "F007-sample-digest", "claim_id": "C-004",
                    "status": "PROVEN"}])
        assert audit.emit_harvest_landed(
            str(ws), "byte-digest",
            tool_path="tools-local/byte-digest.py")
        rows = _audit_rows(ws)
        assert [r["action"] for r in rows] == ["harvest_scan",
                                               "script_harvested",
                                               "harvest_landed"]
        for row in rows:
            assert len(row) == 17
        scan = json.loads(rows[0]["detail"])
        assert scan["swept"] == 2
        assert scan["candidates"] == 1
        landed = json.loads(rows[2]["detail"])
        assert landed["name"] == "byte-digest"
        assert rows[2]["tool"] == "tools-local/byte-digest.py"


# ---------------------------------------------------------------------------
# the fixture chain through the finalize step
# ---------------------------------------------------------------------------

class TestFixtureChainE2E:
    def test_full_chain_sweep_to_landing(self, tmp_path):
        ctx = _mk_ctx(tmp_path)
        stage_fixture_ws(ctx.ws)
        checkpoints._harvest_scripts(ctx)
        # landing: exactly the verified candidate, with its manifest
        tool = ctx.ws / "tools-local" / "byte-digest.py"
        assert tool.is_file(), "candidate must land in tools-local"
        manifest = json.loads(
            (ctx.ws / "tools-local" / "byte-digest.manifest.json")
            .read_text(encoding="utf-8"))
        assert manifest["schema"] == "harvest-manifest/1"
        assert manifest["source_path"] == "scripts/byte_digest.py"
        assert manifest["fixture"]["runs"] == 2
        # the other two scripts never landed
        assert not (ctx.ws / "tools-local" / "byte-noise.py").exists()
        assert not (ctx.ws / "tools-local" / "scratch-helper.py").exists()
        # playbook chain record exists
        pb = json.loads((ctx.ws / "runs" / "harvest-playbook.json")
                        .read_text(encoding="utf-8"))
        assert pb["schema"] == "harvest-playbook/1"
        assert pb["chains"][0]["script"] == "scripts/byte_digest.py"
        # audit trail: one scan row + classified/archived + landed rows
        rows = _audit_rows(ctx.ws)
        actions = [r["action"] for r in rows]
        assert actions.count("harvest_scan") == 1
        assert actions.count("harvest_landed") == 1
        assert actions.count("script_harvested") == 2  # landed + archived
        scan = json.loads(next(r for r in rows
                               if r["action"] == "harvest_scan")["detail"])
        assert scan["swept"] == 3
        assert scan["candidates"] == 2
        assert scan["skipped"] == 1
        assert scan["archived"] == 1
        # ledger: harvest counters debited, distill untouched
        state = od.ledger_state(ctx.ws)
        assert state["harvest_used"] == 1
        assert state["global"]["harvest_landed"] == 1
        assert state["per_run_used"] == 0
        # the worker's own files are never mutated
        assert (ctx.ws / "scripts" / "byte_digest.py").read_text(
            encoding="utf-8") == (FIXTURE / "byte_digest.py").read_text(
                encoding="utf-8")

    def test_no_scripts_no_rows(self, tmp_path):
        ctx = _mk_ctx(tmp_path)
        checkpoints._harvest_scripts(ctx)
        assert not (ctx.ws / "tools-local").exists()
        assert not audit.audit_path(ctx.ws).is_file() or \
            not [r for r in _audit_rows(ctx.ws)
                 if r["action"].startswith("harvest_")
                 or r["action"] == "script_harvested"]
        assert od.ledger_state(ctx.ws)["harvest_used"] == 0

    def test_raising_engine_never_breaks_the_host(self, tmp_path,
                                                  monkeypatch):
        ctx = _mk_ctx(tmp_path)
        (ctx.ws / "scripts").mkdir()
        (ctx.ws / "scripts" / "x.py").write_text("print(1)\n",
                                                 encoding="utf-8")

        def boom(*a, **k):
            raise RuntimeError("engine exploded")

        monkeypatch.setattr(sh, "run_harvest", boom)
        checkpoints._harvest_scripts(ctx)  # must not raise
        assert not (ctx.ws / "tools-local").exists()
        assert not audit.audit_path(ctx.ws).is_file() or \
            not [r for r in _audit_rows(ctx.ws)
                 if r["action"].startswith("harvest_")]


# ---------------------------------------------------------------------------
# static host pins
# ---------------------------------------------------------------------------

class TestHostPins:
    def test_finalize_hosts_the_sweep_once(self):
        src = (SCRIPTS / "e2e" / "checkpoints.py").read_text(
            encoding="utf-8")
        assert "def _harvest_scripts(ctx" in src
        assert "_harvest_scripts(ctx)" in src

    def test_contamination_abort_never_sweeps(self):
        src = (SCRIPTS / "e2e" / "checkpoints.py").read_text(
            encoding="utf-8")
        abort = src[src.index("def _abort_contaminated"):]
        abort = abort[:abort.index("\ndef ", 1)]
        assert "_harvest_scripts" not in abort
