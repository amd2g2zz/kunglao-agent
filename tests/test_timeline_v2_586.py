#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_timeline_v2_586.py — timeline v2, the dual DAG, ICD-203 notes,
and the promotion write-back (issue #586).

Six scope families, one module each:
  1. the structured progress projection (runs/timeline.jsonl) — a mechanical
     projection of the decide/settle/dispatch event stream, never hand-written;
  2. global_plan rendered FROM the projection at the resume face (open thread
     = latest `next` per claim line); the stub diagnostic re-arms;
  3. the settle-note writing convention (template + shape lint);
  4. the evidence DAG view (artifact -> fact -> claim -> question);
  5. the result DAG populates at claim creation (both debt readers agree);
  6. promotion write-back (citing facts' frontmatter syncs within the settle).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import kunglao_log  # noqa: E402
import register_proven_gate as rpg  # noqa: E402
import timeline_face  # noqa: E402
import note_convention  # noqa: E402
import evidence_dag  # noqa: E402
from rlvr import verification_debt as vd  # noqa: E402


# ---------------------------------------------------------------- fixtures --

TS0 = "2026-10-09T10:00:00Z"
TS1 = "2026-10-09T10:05:00Z"
TS2 = "2026-10-09T10:10:00Z"
TS3 = "2026-10-09T10:15:00Z"


def _row(action, claim=None, ts=TS0, *, detail=None, exit_=None,
         artifact=None, actor="orchestrator", epoch=0):
    row = {
        "ts": ts, "actor": actor, "action": action,
        "claim": claim, "tool": None, "artifact": artifact,
        "duration_ms": None, "exit": exit_, "detail": detail,
        "arm": None, "epoch": epoch, "hypothesis_ref": None,
        "matched_rule": None, "trace_id": None, "version": None,
        "channel": "local", "null_reasons": {},
    }
    return row


def _write_log(ws: Path, rows: list[dict]) -> None:
    d = ws / "runs" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    lines = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    (d / "kunglao-2026-10-09.jsonl").write_text(lines, encoding="utf-8")


def _write_register(ws: Path, claims: list[dict]) -> None:
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True,
                       sort_keys=False), encoding="utf-8")


def _write_fact(ws: Path, fid: str, claim: str, *, status="INFERRED",
                source="static-decompile", confidence="medium",
                evidence_eid=None, evidence_path=None,
                with_provenance=True) -> Path:
    prov_entry = {"role": "sample_raw", "path": "evidence/consts.json",
                  "content_sha256": "a" * 64, "credibility": "A1"}
    if evidence_eid:
        prov_entry["eid"] = evidence_eid
    elif evidence_path:
        prov_entry["path"] = evidence_path
    fm = {
        "id": fid, "type": "fact", "title": f"fact {fid}", "status": status,
        "created": "2026-10-09", "last_reviewed": "2026-10-09",
        "source": source, "confidence": confidence, "claim_id": claim,
        "boundary_type": "observation",
        "promotion_gate": "a rerun confirming the constant",
        "claim": "the constants of the target sample",
        "reproduce": "python3 runs/verify-const.py",
        "expected": "the three constants byte-match",
        "verified": "pending",
    }
    if with_provenance:
        fm["provenance"] = [prov_entry]
    body = (f"# {fid}\n\n## Status\n\n{status}\n\n"
            "observation text\n\n## Code excerpt\n\n"
            "```c\nconst unsigned int K = 0x1;\n```\n")
    p = ws / "facts" / f"{fid}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\n" + yaml.safe_dump(fm, sort_keys=False) +
                 "---\n" + body, encoding="utf-8")
    return p


def _write_index(ws: Path, rows: list[tuple[str, str, str]]) -> None:
    lines = ["# facts index", "", "# fact | status | claim | conclusion"]
    for fid, status, claim in rows:
        lines.append(f"{fid} | {status} | {claim} | concluded")
    (ws / "facts" / "_INDEX.md").write_text("\n".join(lines) + "\n",
                                            encoding="utf-8")


def _dispatch_fixture(ws: Path) -> None:
    """An e2e-shaped loop: PQ claim dispatched, failed once (dead end),
    re-dispatched, settled PROVEN; one convergence decision between."""
    _write_register(ws, [
        {"id": "C-001", "status": "PROVEN", "answers_question": "pq-1"},
    ])
    _write_fact(ws, "F001-const", "C-001")
    rows = [
        _row("convergence_decision", ts=TS0,
             detail=json.dumps({"decision": "DISPATCH", "tick": 1})),
        _row("dispatch_attempt", claim="C-001", ts=TS0,
             detail=json.dumps({"mode": "auto", "claim": "C-001",
                                "command": ["claude", "-p", "hi"],
                                "cwd": str(ws), "timeout": 600})),
        _row("checkpoint_pass", ts=TS0, epoch=1,
             detail=json.dumps({"step": "C6-loop", "status": "PASS",
                                "rc": 0, "duration_ms": 10})),
        _row("dispatch_result", claim="C-001", ts=TS1, exit_=1,
             detail=json.dumps({"mode": "auto", "claim": "C-001", "rc": 1,
                                "timed_out": False,
                                "stderr_tail": "boom: probe crashed"})),
        _row("dispatch_attempt", claim="C-001", ts=TS2,
             detail=json.dumps({"mode": "auto", "claim": "C-001",
                                "command": ["claude", "-p", "hi again"],
                                "cwd": str(ws), "timeout": 600})),
        _row("dispatch_result", claim="C-001", ts=TS2, exit_=0,
             detail=json.dumps({"mode": "auto", "claim": "C-001", "rc": 0,
                                "timed_out": False, "artifacts":
                                ["artifacts/const.txt"]})),
        _row("claim_settled", claim="C-001", ts=TS3, actor="hook:write_guard",
             detail=json.dumps({"from": "IN_PROGRESS", "to": "PROVEN",
                                "tools": ["grep"], "outcome": "PROVEN"})),
    ]
    _write_log(ws, rows)


# ------------------------------------------------- 1. the projection --------

class TestTimelineProjection:
    def test_fields_complete_and_ts_real(self, tmp_path):
        ws = tmp_path / "ws"
        _dispatch_fixture(ws)
        steps = timeline_face.project(ws)
        assert steps, "a dispatched+settled fixture projects steps"
        for step in steps:
            assert set(timeline_face.FIELDS) <= set(step), \
                "every reference field is present"
            # ts is a real ISO instant, never a placeholder
            ts = step["ts"]
            assert ts and ts != "-"
            datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def test_settlement_step_sources(self, tmp_path):
        ws = tmp_path / "ws"
        _dispatch_fixture(ws)
        steps = timeline_face.project(ws)
        settled = [s for s in steps if s["role"] == "claim_settled"]
        assert len(settled) == 1
        s = settled[0]
        assert s["evidence_ids"] == ["F001-const"]
        assert "PROVEN" in (s["result_summary"] or "")
        assert s["decision_delta"] == "DISPATCH"
        assert "C6-loop" in (s["stage"] or "")
        assert s["next"] and "PROVEN" in s["next"]
        assert s["command_or_ref"], "settled step cites its dispatch record"

    def test_dead_ends_produce_entries_with_gap(self, tmp_path):
        ws = tmp_path / "ws"
        _dispatch_fixture(ws)
        steps = timeline_face.project(ws)
        dead = [s for s in steps if s["role"] == "dispatch_result"
                and s["result_summary"] and "failed" in s["result_summary"]]
        assert len(dead) == 1, "the failed act gets its own entry"
        d = dead[0]
        assert "probe crashed" in (d["result_summary"] or ""), \
            "the dead end cites its gap evidence"

    def test_projection_is_deterministic(self, tmp_path):
        ws = tmp_path / "ws"
        _dispatch_fixture(ws)
        again = timeline_face.project(ws)
        assert timeline_face.project(ws) == again

    def test_unreadable_ledger_skips(self, tmp_path):
        ws = tmp_path / "ws"
        d = ws / "runs" / "logs"
        d.mkdir(parents=True)
        p = d / "kunglao-2026-10-09.jsonl"
        p.write_text("rows", encoding="utf-8")
        p.chmod(0o000)
        try:
            assert timeline_face.project(ws) is None
            out = timeline_face.render_and_write(ws)
            assert out["status"] == "skipped"
            assert not (ws / timeline_face.TIMELINE_REL).exists()
        finally:
            p.chmod(0o644)

    def test_render_and_write(self, tmp_path):
        ws = tmp_path / "ws"
        _dispatch_fixture(ws)
        out = timeline_face.render_and_write(ws)
        assert out["status"] == "rendered" and out["wrote"] is True
        rel = ws / "runs" / "timeline.jsonl"
        rows = [json.loads(ln) for ln in
                rel.read_text(encoding="utf-8").splitlines() if ln.strip()]
        assert rows and all(set(timeline_face.FIELDS) <= set(r) for r in rows)


# ------------------------------------- 2. global_plan renders from it -------

class TestGlobalPlanFromTimeline:
    def test_plan_renders_open_threads(self, tmp_path):
        ws = tmp_path / "ws"
        _dispatch_fixture(ws)
        _write_register(ws, [
            {"id": "C-001", "status": "PROVEN"},
            {"id": "C-002", "status": "OPEN", "statement": "next up"},
        ])
        out = timeline_face.render_and_write(ws)
        assert out["plan_wrote"] is True
        text = (ws / "global_plan.txt").read_text(encoding="utf-8")
        assert text.startswith(timeline_face.PLAN_RENDER_MARK)
        assert "C-002" in text, "open register claims get their thread line"

    def test_stub_diagnostic_re_arms_against_rendered_face(self, tmp_path):
        import plan_stages
        ws = tmp_path / "rendered"
        ws.mkdir()
        (ws / "runs").mkdir()
        _write_register(ws, [{"id": "C-001", "status": "OPEN"}])
        (ws / "global_plan.txt").write_text(
            timeline_face.PLAN_RENDER_MARK + "\nC-001: dispatch\n",
            encoding="utf-8")
        (ws / "runs" / "plan-stages.yaml").write_text(
            yaml.safe_dump({"stages": [
                {"id": "s1", "name": "n", "goal": "g", "claims": "C-001",
                 "expected_evidence": "e", "exit_criteria": "x",
                 "status": "active"},
                {"id": "s2", "name": "n", "goal": "g", "claims": "C-001",
                 "expected_evidence": "e", "exit_criteria": "x",
                 "status": "pending"}]}), encoding="utf-8")
        assert not any("init stub" in v for v in
                       plan_stages.check(ws)["violations"]), \
            "the rendered face is not the stub"
        stub = tmp_path / "stubws"
        stub.mkdir()
        (stub / "runs").mkdir()
        (stub / "claim-register.yaml").write_text("claims: []\n",
                                                  encoding="utf-8")
        (stub / "global_plan.txt").write_text(
            plan_stages.PLAN_STUB_MARK + "\n", encoding="utf-8")
        assert any("init stub" in v
                   for v in plan_stages.check(stub)["violations"])

    def test_resume_face_renders_projection(self, tmp_path, monkeypatch):
        import kunglao_resume
        calls: list[Path] = []
        real = timeline_face.render_and_write

        def spy(ws):
            calls.append(Path(ws))
            return real(ws)

        monkeypatch.setattr(timeline_face, "render_and_write", spy)
        monkeypatch.setattr(kunglao_resume, "timeline_face", timeline_face)
        ws = tmp_path / "ws"
        _dispatch_fixture(ws)
        (ws / "runs" / ".heartbeat.json").write_text("{}", encoding="utf-8")
        kunglao_resume.main([str(ws), "--json"])
        assert calls and calls[0] == ws, \
            "resume renders the projection before building the brief"


# ------------------------------------- 3. the note convention ---------------

class TestNoteConvention:
    def test_templates_for_three_kinds(self):
        for kind in ("verify", "retro", "gap"):
            text = note_convention.template(kind)
            assert text and kind in text

    def test_constructed_sample_passes(self):
        note = "\n".join([
            "## Assertion",
            "the fold multiplier is 0x1000003b1",
            "## Derivation",
            "re-derived from evidence/consts.json and runs/verify-x.py",
            "## Evidence",
            "- evidence/consts.json",
            "- facts/F001-const.md",
            "## Uncertainty",
            "none — the replay confirms all three constants byte-exactly",
        ])
        assert note_convention.check_note(note) == []

    def test_missing_uncertainty_fails(self):
        note = ("\n".join([
            "## Assertion", "x",
            "## Derivation", "runs/verify-x.py",
            "## Evidence", "- evidence/consts.json",
        ]))
        assert any("uncertainty" in v.lower()
                   for v in note_convention.check_note(note))

    def test_missing_evidence_link_fails(self):
        note = ("\n".join([
            "## Assertion", "x",
            "## Derivation", "derived by reading",
            "## Evidence", "trust me",
            "## Uncertainty", "none",
        ]))
        assert note_convention.check_note(note), \
            "evidence must cite a link, not a bare claim"


# ------------------------------------- 4. the evidence DAG view -------------

def _dag_fixture(ws: Path) -> None:
    (ws / "evidence").mkdir(parents=True, exist_ok=True)
    (ws / "evidence" / "consts.json").write_text("{}\n", encoding="utf-8")
    (ws / "evidence" / "_index.json").write_text(json.dumps({
        "schema": "evidence-index-v1",
        "entries": [{"eid": "eid-a1", "path": "evidence/consts.json",
                     "sha256": "b" * 64, "size": 3, "type": "json",
                     "source_reliability": "B3"}],
    }), encoding="utf-8")
    _write_fact(ws, "F001-const", "C-001", evidence_eid="eid-a1")
    _write_register(ws, [{"id": "C-001", "status": "OPEN",
                          "answers_question": "pq-1"}])
    (ws / "task_spec.yaml").write_text(yaml.safe_dump({
        "primary_questions": [{"id": "pq-1", "question": "what are the consts?"}],
    }), encoding="utf-8")


class TestEvidenceDag:
    def test_every_fact_reachable_both_ways(self, tmp_path):
        ws = tmp_path / "ws"
        _dag_fixture(ws)
        dag = evidence_dag.build(ws)
        assert dag["artifacts"] and "eid-a1" in dag["artifacts"]
        assert dag["facts"]["F001-const"]["artifacts"] == ["eid-a1"]
        assert dag["facts"]["F001-const"]["claims"] == ["C-001"]
        assert dag["claims"]["C-001"]["question"] == "pq-1"
        assert dag["questions"]["pq-1"]["claims"] == ["C-001"]
        assert evidence_dag.unreachable(dag) == []

    def test_broken_edge_reported(self, tmp_path):
        ws = tmp_path / "ws"
        _dag_fixture(ws)
        _write_fact(ws, "F002-orphan", "C-001", with_provenance=False)
        dag = evidence_dag.build(ws)
        bad = evidence_dag.unreachable(dag)
        assert any("F002-orphan" in b for b in bad), \
            "a fact without artifact edges is reported"

    def test_render_text_human_face(self, tmp_path):
        ws = tmp_path / "ws"
        _dag_fixture(ws)
        text = evidence_dag.render_text(evidence_dag.build(ws))
        for token in ("eid-a1", "F001-const", "C-001", "pq-1"):
            assert token in text


# ------------------------------------- 5. the result DAG populates ----------

class TestResultDagPopulates:
    def test_e2e_claims_declare_dependencies(self):
        from e2e import checkpoints
        by_id = {c["id"]: c for c in checkpoints.CLAIM_APPENDS}
        assert by_id["C-005"].get("depends_on") == ["C-004"], \
            "the synthesis claim declares its analysis parent at creation"

    def test_claim_deps_nonempty_and_debt_positive(self, tmp_path):
        import _scriptlib
        ws = tmp_path / "ws"
        ws.mkdir()
        claims = [
            {"id": "C-004", "status": "OPEN", "depends_on": []},
            {"id": "C-005", "status": "OPEN", "depends_on": ["C-004"]},
        ]
        _write_register(ws, claims)
        touched = _scriptlib.sync_dep_edges(ws, claims)
        assert touched == ["C-005"]
        doc = yaml.safe_load((ws / "claim_deps.yaml").read_text("utf-8"))
        assert doc["depends_on"] == {"C-005": ["C-004"]}, \
            "the authoritative DAG store is non-empty"
        face = vd.debt(ws)
        assert face["D"] > 0, "D > 0 is reachable at smoke scale"

    def test_both_debt_readers_agree(self, tmp_path):
        import _scriptlib
        ws = tmp_path / "ws"
        ws.mkdir()
        claims = [
            {"id": "C-004", "status": "OPEN", "depends_on": []},
            {"id": "C-005", "status": "OPEN", "depends_on": ["C-004"]},
        ]
        _write_register(ws, claims)
        _scriptlib.sync_dep_edges(ws, claims)
        deps_doc = yaml.safe_load((ws / "claim_deps.yaml").read_text("utf-8"))
        from_dag = vd._edges(deps_doc)
        from_claims = vd._edges(claims)
        assert from_dag == from_claims, \
            "the DAG file and the per-claim fields carry the same graph"


# ------------------------------------- 6. the promotion write-back ----------

class TestPromotionWriteBack:
    def _ws(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_register(ws, [{"id": "C-001", "status": "OPEN"}])
        fact = _write_fact(ws, "F001-const", "C-001")
        _write_index(ws, [("F001-const", "INFERRED", "C-001")])
        old = (ws / "claim-register.yaml").read_text("utf-8")
        new = old.replace("status: OPEN", "status: PROVEN")
        return ws, fact, old, new

    def test_citing_facts_sync_within_the_settle(self, tmp_path):
        ws, fact, old, new = self._ws(tmp_path)
        assert rpg.emit_settlements(ws, new, old) == 1
        text = fact.read_text("utf-8")
        assert "status: PROVEN" in text
        assert "confidence: high" in text
        fm, body, _ = __import__("lint_facts").parse_frontmatter(text)
        assert fm["status"] == "PROVEN"
        assert "## Status" in body and "PROVEN" in body.split("## Status")[1][:40]
        index = (ws / "facts" / "_INDEX.md").read_text("utf-8")
        assert "F001-const | PROVEN |" in index

    def test_synced_fact_stays_lint_clean(self, tmp_path):
        import lint_facts
        ws, fact, old, new = self._ws(tmp_path)
        rpg.emit_settlements(ws, new, old)
        fm, body, _ = lint_facts.parse_frontmatter(
            fact.read_text(encoding="utf-8"))
        issues = lint_facts.lint_fact("F001-const", fm,
                                      {"F001-const"}, body)
        errors = [i for i in issues if i[0] == "error"]
        assert not errors, f"the synced fact must stay lint-clean: {errors}"
        assert not [i for i in lint_facts.lint_index(ws / "facts" / "_INDEX.md")
                    if i[0] == "error"]

    def test_negative_settlement_does_not_touch_facts(self, tmp_path):
        ws, fact, _, _ = self._ws(tmp_path)
        old = (ws / "claim-register.yaml").read_text("utf-8")
        new = old.replace("status: OPEN", "status: NEGATIVE")
        before = fact.read_text("utf-8")
        rpg.emit_settlements(ws, new, old)
        assert fact.read_text("utf-8") == before

    def test_skip_faces_are_honest(self, tmp_path):
        ws, _, old, new = self._ws(tmp_path)
        refuted = _write_fact(ws, "F002-refuted", "C-001", status="REFUTED",
                              source="dynamic-trace", confidence="high")
        judged = _write_fact(ws, "F003-judged", "C-001",
                             source="inference")
        out = rpg.emit_settlements(ws, new, old)
        assert out == 1
        assert "status: REFUTED" in refuted.read_text("utf-8"), \
            "a falsified fact is never flipped by promotion"
        assert "status: INFERRED" in judged.read_text("utf-8"), \
            "a judgment-source fact cannot legally carry PROVEN"
        from fact_status_sync import promote_citing_facts
        face = promote_citing_facts(ws, "C-001")
        assert face["skipped"].get("F003-judged"), "the skip names its reason"

    def test_sync_emits_one_visible_row(self, tmp_path, monkeypatch):
        ws, _, old, new = self._ws(tmp_path)
        real_emit = kunglao_log.emit
        calls: list[dict] = []

        def spy(ws_, actor, action, **kw):
            calls.append({"action": action, **kw})
            return real_emit(ws_, actor, action, **kw)

        monkeypatch.setattr(kunglao_log, "emit", spy)
        rpg.emit_settlements(ws, new, old)
        synced = [c for c in calls if c["action"] == "fact_status_synced"]
        assert synced, "the write-back is observable in the ledger"
        payload = json.loads(synced[-1]["detail"])
        assert payload["synced"] == ["F001-const"]

    def test_emit_word_registered(self):
        import event_taxonomy
        assert "fact_status_synced" in event_taxonomy.EMIT_ACTIONS


# ------------------------------------- channel disposition ------------------

def test_narrative_channel_disposition_note():
    """The old narrative channel is retired AS a progress face with an
    explicit pointer note; its preservation role keeps its readers."""
    import progress_timeline
    doc = (Path(progress_timeline.__file__).read_text("utf-8")
           .lower())
    assert "timeline_face" in doc, \
        "the sidecar docstring names the structured progress face"
