# -*- coding: utf-8 -*-
"""Issue 250 — semantic refutation: the xref/RegisterNatives regression.

The canonical case from the issue body: fact F1 "xref null -> uncalled"
stored as a WORLD fact, correct as a tool observation, wrong as a world
claim. The agent's own earlier finding (JNI_OnLoad -> RegisterNatives
dynamic registration; VM dispatch makes call sites DATA) never retracts it
because refutation_propagate walks ONLY depends_on structural edges.

After: when a fact carries `assumptions: [<topic>=<polarity>]` and a
PROVEN/VERIFIED fact or claim's content matches the assumption's topic
with a CONTRADICTING polarity, the assumption-carrying fact's claim gets
`needs_re-eval: true` (marking only, no cascade, idempotent — same
semantics as the structural face).
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import refutation_propagate as rp  # noqa: E402


def write_register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, sort_keys=False), encoding="utf-8")


def load_register(ws: Path) -> dict:
    return yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}


def write_fact(ws: Path, fid: str, *, status: str, title: str,
               claim_id: str = "", assumptions: list | None = None,
               body: str = "") -> None:
    d = ws / "facts"
    d.mkdir(parents=True, exist_ok=True)
    fm = {"id": fid, "type": "fact", "title": title, "status": status,
          "created": "2026-09-18", "last_reviewed": "2026-09-18"}
    if claim_id:
        fm["claim_id"] = claim_id
    if assumptions is not None:
        fm["assumptions"] = assumptions
    head = yaml.safe_dump(fm, sort_keys=False)
    (d / f"{fid}.md").write_text(f"---\n{head}---\n\n{body}\n",
                                 encoding="utf-8")


# ---------- THE named regression: xref null -> uncalled vs RegisterNatives ----------

def test_xref_uncalled_invalidated_by_register_natives(tmp_path):
    """F1: 'sub_1234 is uncalled' (world claim) presupposes dispatch=static.
    F2: PROVEN finding — JNI_OnLoad registers natives via RegisterNatives,
    VM dispatch resolves calls dynamically. F2 must flag F1's claim."""
    write_register(tmp_path, [
        {"id": "C-101", "status": "PROVEN"},
        {"id": "C-102", "status": "PROVEN"},
    ])
    write_fact(
        tmp_path, "F001-uncalled", status="PROVEN",
        title="sub_1234 has no callers",
        claim_id="C-101", assumptions=["dispatch=static"],
        body="xref index is empty for sub_1234, so the function is never called.")
    write_fact(
        tmp_path, "F002-jni", status="PROVEN",
        title="JNI_OnLoad registers natives via RegisterNatives",
        claim_id="C-102",
        body=("JNI_OnLoad calls RegisterNatives to bind sub_1234; VM "
              "dispatch resolves native calls dynamically through the "
              "registration table."))

    marked = rp.mark_dependents(tmp_path)

    assert "C-101" in marked, (
        "the xref conclusion's claim must be flagged needs_re-eval by the "
        "PROVEN dynamic-registration finding")
    reg = load_register(tmp_path)
    f1 = next(c for c in reg["claims"] if c["id"] == "C-101")
    assert f1.get("needs_re-eval") is True
    f2 = next(c for c in reg["claims"] if c["id"] == "C-102")
    assert not f2.get("needs_re-eval"), "the underminer itself is untouched"


def test_structural_face_still_runs_alongside(tmp_path):
    write_register(tmp_path, [
        {"id": "C-001", "status": "REFUTED"},
        {"id": "C-002", "status": "PROVEN"},
    ])
    (tmp_path / "claim_deps.yaml").write_text(
        "depends_on:\n  C-002:\n  - C-001\n", encoding="utf-8")
    marked = rp.mark_dependents(tmp_path)
    assert "C-002" in marked


def test_no_contradiction_source_no_marks(tmp_path):
    write_register(tmp_path, [{"id": "C-101", "status": "PROVEN"}])
    write_fact(
        tmp_path, "F001-uncalled", status="PROVEN",
        title="sub_1234 has no callers",
        claim_id="C-101", assumptions=["dispatch=static"],
        body="xref index is empty")
    write_fact(
        tmp_path, "F003-static", status="PROVEN",
        title="static xref finds two call sites",
        claim_id="C-103",
        body="static xref table shows two references; dispatch stays static")
    assert rp.mark_dependents(tmp_path) == []


def test_open_underminer_does_not_flag(tmp_path):
    write_register(tmp_path, [
        {"id": "C-101", "status": "PROVEN"},
        {"id": "C-102", "status": "OPEN"},
    ])
    write_fact(
        tmp_path, "F001-uncalled", status="PROVEN",
        title="sub_1234 has no callers",
        claim_id="C-101", assumptions=["dispatch=static"], body="xref empty")
    write_fact(
        tmp_path, "F002-maybe", status="INFERRED",
        title="dynamic dispatch suspected",
        claim_id="C-102", body="dispatch may resolve dynamically")
    assert rp.mark_dependents(tmp_path) == []


def test_semantic_face_dry_run_marks_nothing(tmp_path):
    write_register(tmp_path, [
        {"id": "C-101", "status": "PROVEN"},
        {"id": "C-102", "status": "PROVEN"},
    ])
    write_fact(
        tmp_path, "F001-uncalled", status="PROVEN",
        title="sub_1234 has no callers",
        claim_id="C-101", assumptions=["dispatch=static"], body="xref empty")
    write_fact(
        tmp_path, "F002-jni", status="PROVEN",
        title="RegisterNatives dynamic registration",
        claim_id="C-102", body="dispatch resolves calls dynamically")

    marked = rp.mark_dependents(tmp_path, dry_run=True)

    assert "C-101" in marked  # reported
    reg = load_register(tmp_path)
    f1 = next(c for c in reg["claims"] if c["id"] == "C-101")
    assert not f1.get("needs_re-eval"), "dry-run must not write the register"


def test_idempotent_second_run_no_remarks(tmp_path):
    write_register(tmp_path, [
        {"id": "C-101", "status": "PROVEN"},
        {"id": "C-102", "status": "PROVEN"},
    ])
    write_fact(
        tmp_path, "F001-uncalled", status="PROVEN",
        title="sub_1234 has no callers",
        claim_id="C-101", assumptions=["dispatch=static"], body="xref empty")
    write_fact(
        tmp_path, "F002-jni", status="PROVEN",
        title="RegisterNatives dynamic registration",
        claim_id="C-102", body="dispatch resolves calls dynamically")
    assert rp.mark_dependents(tmp_path) == ["C-101"]
    assert rp.mark_dependents(tmp_path) == []
