# -*- coding: utf-8 -*-
"""Tests for #525 lessons nursery two-stage lifecycle (draft → active).

Lesson files written by aggregate_lessons() default to stage: draft, which
means they appear in the library but injection carries the [unverified]
tag so consumers don't trust them blindly. Promotion to stage: active
happens only after mechanical verification (L1 reproduce via
kunglao-verify) — promote_lesson() flips the frontmatter, emits a
stage_transition event in the kunglao_log, and rejects demotion back to
draft (lessons cannot regress; they can only be retired).

Frontmatter contract (per #525, capa-nursery analogy):
  trigger_precision:
    tool:              <api/tool signature>
    error_signature:   <mechanical error fingerprint>
    family:            <family / obfuscation_class identifier>
    unit:              <numeric scope, matches global numeric-fidelity>
Missing trigger_precision or any sub-field → write gate FAILS.

Linkage with #524: aggregate_lessons remains the writer; this change only
adds a default stage and validates frontmatter. Idempotency, dedup,
queue, BLOCKED retrieval all behave as before.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import yaml  # noqa: E402


def _import_fag():
    """Lazy import — failure_analysis_gate.py may set defaults pointing
    at $HOME; tests inject library/queue paths."""
    import failure_analysis_gate as fag  # noqa: E402
    return fag


def _write_register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _claim(cid: str, attempts: int = 3, statement: str = "topic") -> dict:
    return {"id": cid, "status": "OPEN", "boundary_type": "positive_observation",
            "evidence_tier_attempted": 1, "promotion_attempts": attempts,
            "depends_on": [], "statement": statement}


def _lesson_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    assert len(parts) >= 3, f"missing frontmatter delimiters in {path}"
    return yaml.safe_load(parts[1])


def _record_with_precision(ws, cid, *, tool="frida.attach", err="ENOENT",
                           family="process.attach", unit="attempt"):
    """Record an analysis that closes the loop AND carries the precision
    fields the nursery demands at write time."""
    fag = _import_fag()
    return fag.record_analysis(
        ws, cid,
        assumption="static import table",
        validity="not-justified",
        next_method="runtime frida attach",
        outcome="PROVEN",
        what_happened="frida attached and saw NtCreateThreadEx",
        validated_capability="frida runtime observable",
        identified_obstacle="static import shows nothing",
        source="lesson-hit",
        trigger_precision={
            "tool": tool,
            "error_signature": err,
            "family": family,
            "unit": unit,
        })


# ---------- write path: stage defaults to draft ----------

def test_aggregate_writes_lesson_as_draft(tmp_path):
    """A fresh lesson written by aggregate_lessons starts at stage=draft;
    frontmatter carries trigger_precision; injection is allowed (file in
    library) but stage marks it unverified."""
    fag = _import_fag()
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-1", statement="attach C2 by hook")])
    _record_with_precision(ws, "C-1")
    lib = tmp_path / "lib"

    # Act
    res = fag.aggregate_lessons(ws, library=lib, reflect_queue=tmp_path / "q.json")

    # Assert
    assert res["lessons_written"] == 1
    files = list(lib.glob("lesson-*.md"))
    assert len(files) == 1
    fm = _lesson_frontmatter(files[0])
    assert fm["stage"] == "draft"
    assert fm["trigger_precision"]["tool"] == "frida.attach"
    assert fm["trigger_precision"]["error_signature"] == "ENOENT"
    assert fm["trigger_precision"]["family"] == "process.attach"
    assert fm["trigger_precision"]["unit"] == "attempt"


def test_aggregate_skips_lesson_missing_precision(tmp_path):
    """An analysis written WITHOUT trigger_precision must NOT be promoted
    into the library — the write gate fails, the analysis is rejected
    (or routed to /reflect with reason 'missing-precision')."""
    fag = _import_fag()
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-2")])
    # legacy record WITHOUT trigger_precision
    fag.record_analysis(
        ws, "C-2",
        assumption="a", validity="not-justified",
        next_method="b", outcome="PROVEN", what_happened="ok",
        validated_capability="x", identified_obstacle="y",
        source="lesson-hit")
    lib = tmp_path / "lib"
    q = tmp_path / "q.json"

    # Act
    res = fag.aggregate_lessons(ws, library=lib, reflect_queue=q)

    # Assert — not in library, queued for human reflect
    assert res["lessons_written"] == 0
    assert list(lib.glob("lesson-*.md")) == []
    items = json.loads(q.read_text(encoding="utf-8"))
    assert any(i["claim_id"] == "C-2" and i["reason"] == "missing-precision"
               for i in items)


def test_aggregate_incomplete_precision_subfield_rejected(tmp_path):
    """trigger_precision present but a sub-field missing (e.g. no unit) is
    treated like missing the whole field — gate fail."""
    fag = _import_fag()
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-3")])
    fag.record_analysis(
        ws, "C-3",
        assumption="a", validity="not-justified",
        next_method="b", outcome="PROVEN", what_happened="ok",
        validated_capability="x", identified_obstacle="y",
        source="lesson-hit",
        trigger_precision={"tool": "x", "error_signature": "y", "family": "z"})
    lib = tmp_path / "lib"
    q = tmp_path / "q.json"

    res = fag.aggregate_lessons(ws, library=lib, reflect_queue=q)

    assert res["lessons_written"] == 0
    items = json.loads(q.read_text(encoding="utf-8"))
    assert any(i["claim_id"] == "C-3" and i["reason"] == "missing-precision"
               for i in items)


# ---------- promote path ----------

def test_promote_lesson_flips_stage_and_audits(tmp_path):
    """promote_lesson() flips stage draft→active, stamps promoted_at,
    appends a stage_transition event to kunglao_log, and refuses to
    re-promote an already-active lesson."""
    fag = _import_fag()
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-4")])
    _record_with_precision(ws, "C-4", tool="ghidra.decompile",
                           err="Cannot LE", family="ghidra.script")
    lib = tmp_path / "lib"
    fag.aggregate_lessons(ws, library=lib, reflect_queue=tmp_path / "q.json")
    files = list(lib.glob("lesson-*.md"))
    assert len(files) == 1
    lesson_path = files[0]

    # Act
    res = fag.promote_lesson(lesson_path, workspace=ws,
                             promoted_by="kunglao-verify",
                             evidence="reproduce run #42 L1 OK")

    # Assert
    assert res["promoted"] is True
    fm = _lesson_frontmatter(lesson_path)
    assert fm["stage"] == "active"
    assert fm["promoted_at"]
    assert fm["promoted_by"] == "kunglao-verify"
    assert fm["promoted_evidence"] == "reproduce run #42 L1 OK"

    # Audit log
    log_rows = []
    for p in (ws / "runs" / "logs").glob("kunglao-*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                log_rows.append(json.loads(line))
    transitions = [r for r in log_rows if r.get("action") == "lesson_stage_transition"]
    assert len(transitions) == 1
    t = transitions[0]
    assert t["actor"] == "nursery"
    assert t["claim"] == "C-4"
    assert "draft→active" in t["detail"]
    assert "promoted_by=kunglao-verify" in t["detail"]


def test_promote_active_lesson_is_noop(tmp_path):
    """Re-promoting an already-active lesson is idempotent — no audit row,
    no rewrite of promoted_at timestamp."""
    fag = _import_fag()
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-5")])
    _record_with_precision(ws, "C-5")
    lib = tmp_path / "lib"
    fag.aggregate_lessons(ws, library=lib, reflect_queue=tmp_path / "q.json")
    lesson_path = next(lib.glob("lesson-*.md"))

    fag.promote_lesson(lesson_path, workspace=ws, promoted_by="kunglao-verify",
                       evidence="run #1")
    first = _lesson_frontmatter(lesson_path)["promoted_at"]

    res = fag.promote_lesson(lesson_path, workspace=ws, promoted_by="kunglao-verify",
                             evidence="run #2")
    assert res["promoted"] is False
    assert res["already_active"] is True
    assert _lesson_frontmatter(lesson_path)["promoted_at"] == first


def test_promote_rejects_demotion(tmp_path):
    """promote_lesson() must not silently move active → draft; lessons
    only retire (separate signal). Demotion attempt raises."""
    fag = _import_fag()
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-6")])
    _record_with_precision(ws, "C-6")
    lib = tmp_path / "lib"
    fag.aggregate_lessons(ws, library=lib, reflect_queue=tmp_path / "q.json")
    lesson_path = next(lib.glob("lesson-*.md"))
    fag.promote_lesson(lesson_path, workspace=ws, promoted_by="kunglao-verify",
                       evidence="run #1")

    # Act + Assert — attempting demotion raises (no silent flip)
    try:
        fag.promote_lesson(lesson_path, workspace=ws, promoted_by="rollback",
                           evidence="undo", demote_to="draft")
    except ValueError as exc:
        assert "demotion" in str(exc).lower() or "cannot" in str(exc).lower()
    else:
        raise AssertionError("demotion should have raised ValueError")


# ---------- retrieval: draft lessons are visible but tagged ----------

def test_blocked_retrieval_tags_draft_lessons(tmp_path):
    """similar_lessons from BLOCKED output keeps draft lessons visible
    (nursery model — don't hide them) but each entry carries stage so the
    consumer can label injection 'unverified'."""
    fag = _import_fag()
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_register(ws, [_claim("C-7", attempts=3, statement="frida attach fails on vm")])
    lib = tmp_path / "lib"
    lib.mkdir()
    # seed 3 lessons that overlap the topic; all draft by default
    for i, (tool, err, fam) in enumerate([
            ("frida.attach", "ENOENT", "process.attach"),
            ("frida.attach", "EACCES", "process.attach"),
            ("ghidra.decompile", "Cannot LE", "ghidra.script")]):
        (lib / f"lesson-seed{i}.md").write_text(
            f"---\ntype: lesson\nstage: draft\n"
            f"outcome: PROVEN\nclaim_topic: frida attach\n"
            f"next_method: static-xref-{i}\nsources: [C-9]\n"
            f"trigger_precision:\n  tool: {tool}\n  error_signature: {err}\n"
            f"  family: {fam}\n  unit: attempt\n"
            f"---\n\n# Lesson\nfrida attach variant {i}\n",
            encoding="utf-8")

    res = fag.check_claim(ws, "C-7", library=lib)
    sim = res.get("similar_lessons") or []
    assert len(sim) == 3
    for s in sim:
        assert s.get("stage") == "draft"