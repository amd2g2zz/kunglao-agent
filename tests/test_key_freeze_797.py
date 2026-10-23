# -*- coding: utf-8 -*-
"""tests/test_key_freeze_797.py — issue-797 acceptance (a): task-open key
freeze + fingerprint churn measurement.

Pins (issue 797, logs-panel 2026-10-23 acceptance additions):

  (a) key freeze — the production pathology: trigger fingerprints are
      task-unique by construction (case pq-01 cycled 3 distinct
      fingerprints in 35 minutes), so signature-keyed cells can never
      recur and cross-run accumulation is structurally zero (web
      re-derived C-001..C-007 from scratch ~26h after android's
      same-version experience). The fix pinned here:

        - the learning key is FROZEN at task open (mint-once doc
          runs/learning-key.json) and is immutable for the task;
        - the frozen key is FAMILY-repeatable across runs (family-grain
          structural dims only — no state-derived material), so two
          synthetic runs of the same-family task carry the SAME key and
          their evidence accumulates in one fold;
        - the dispatch recording face consumes the frozen task anchor
          (one signature per task) — the churn source is dead by
          construction; the no-doc path stays bit-identical legacy;
        - other(...) free-text escapes are refused at the freeze
          boundary (the panel quarantine — they fragment cells without
          learning value).

  (b) fingerprint churn rate — the measurement surface for fingerprint
      stability: per-run NEW fingerprints vs REUSED fingerprints.
      churn=1.0 (all-new — the production shape) is LOUD via the
      structured verdict, Standard 11 clean: this module adds ZERO
      warn() telemetry points (pinned below), loudness is the report.

Alignment: issue-800's dispatch-ledger owns the rollout identity (dispatch
id); this card owns the CELL key — no ledger duplication, the frozen
doc keys nothing the ledger already keys. issue-807's INV-003 made the
family the live posterior grain — the frozen key is family-grain by
construction (the two cards agree on the learning grain).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import state_signature as ssig  # noqa: E402
from rlvr import key_freeze  # noqa: E402
from rlvr import q_cells  # noqa: E402

FAM = "static-symbolic"


def _bare_ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    ws.mkdir()
    return ws


def _grow_state(ws: Path, n_facts: int = 3) -> None:
    """Mutate the workspace state the snapshot discretizes (facts grow —
    the production 35-minute drift the freeze exists to kill)."""
    facts = ws / "facts"
    facts.mkdir(exist_ok=True)
    for i in range(n_facts):
        (facts / f"F00{i + 1}.md").write_text(
            f"# F00{i + 1}\nstatus: PROVEN\n", encoding="utf-8")


def _dispatch_row(ws: Path, claim: str, fingerprint: str | None = None,
                  method_family: str = FAM) -> dict:
    out = q_cells.record_dispatch_observation(
        ws, f'{{"kunglao_dispatch": {{"version": 1}}}} envelope {claim}',
        envelope_meta={"method_family": method_family}, claim=claim,
        fingerprint=fingerprint)
    assert out["appended"] is True
    return out


# ---------------------------------------------------------------- (a) freeze


def test_two_synthetic_runs_same_family_same_frozen_key(tmp_path):
    """THE pin: two synthetic runs, same-family task -> the frozen
    learning key is IDENTICAL (family-repeatable across runs — the
    production keys could never recur)."""
    run_a = key_freeze.freeze_task_key(_bare_ws(tmp_path, "run-a"), FAM)
    run_b = key_freeze.freeze_task_key(_bare_ws(tmp_path, "run-b"), FAM)
    assert run_a["key"] == run_b["key"]
    assert run_a["key"] == "static-symbolic|facts_snapshot|none|0"


def test_cross_run_family_accumulation_in_one_fold(tmp_path):
    """Same key across two runs -> the fold ACCUMULATES their evidence
    (cross-run accumulation is no longer structurally zero)."""
    ws_a = _bare_ws(tmp_path, "run-a")
    ws_b = _bare_ws(tmp_path, "run-b")
    fk_a = key_freeze.freeze_task_key(ws_a, FAM)
    fk_b = key_freeze.freeze_task_key(ws_b, FAM)
    rows = [
        {"schema": q_cells.OBS_SCHEMA, "ts": "2026-10-24T00:00:00Z",
         "source": "settlement", "signature_hash": fk_a["signature_hash"],
         "method_family": FAM, "credit": 1.0, "arm_key": fk_a["key"]},
        {"schema": q_cells.OBS_SCHEMA, "ts": "2026-10-24T01:00:00Z",
         "source": "settlement", "signature_hash": fk_b["signature_hash"],
         "method_family": FAM, "credit": 0.0, "arm_key": fk_b["key"]},
    ]
    fold = q_cells.fold(q_cells.InMemoryStore(rows), gamma=1.0)
    # both runs land in the SAME cell (identical frozen key + anchor)
    assert fold.cells[(fk_a["signature_hash"], fk_a["key"])].success == 1.0
    assert fold.cells[(fk_a["signature_hash"], fk_a["key"])].failure == 1.0
    # and the family aggregate pools both runs' mass
    s, f = fold.family_mass(FAM)
    assert (s, f) == (1.0, 1.0)


def test_refreeze_same_family_is_immutable_within_task(tmp_path):
    """Frozen means frozen: arm dims / state changes mid-task NEVER move
    the key (the production pathology was the key drifting per dispatch;
    re-freeze returns the mint-once entry)."""
    ws = _bare_ws(tmp_path)
    first = key_freeze.freeze_task_key(ws, FAM)
    _grow_state(ws)
    again = key_freeze.freeze_task_key(
        ws, FAM, context_recipe="other-recipe", verification_mode="vm",
        tier=3, agent_type="worker-x")
    assert again["created"] is False
    assert again["key"] == first["key"]
    assert again["opened_ts"] == first["opened_ts"]


def test_task_signature_immutable_across_state_changes(tmp_path):
    """The task anchor snaps ONCE (task open); state drift never moves
    it — one signature per task, the churn source is dead."""
    ws = _bare_ws(tmp_path)
    anchor = key_freeze.task_signature(ws)
    assert anchor == ssig.signature_hash(ssig.snapshot(ws))
    _grow_state(ws)
    assert ssig.signature_hash(ssig.snapshot(ws)) != anchor  # state moved
    assert key_freeze.task_signature(ws) == anchor            # anchor did not


def test_distinct_tasks_get_distinct_anchors_state_respects(tmp_path):
    """The freeze is per-task (per workspace): a DIFFERENT task's anchor
    reflects its own open state — family-repeatable keys, honest
    anchors (no cross-task key collision through the anchor dim)."""
    early = _bare_ws(tmp_path, "early")
    late = _bare_ws(tmp_path, "late")
    _grow_state(late)
    a = key_freeze.task_signature(early)
    b = key_freeze.task_signature(late)
    assert a != b


def test_dispatch_rows_carry_the_frozen_signature(tmp_path):
    """The recording face consumes the frozen anchor: two dispatch
    observations across a state change share ONE signature (intra-task
    accumulation by construction)."""
    ws = _bare_ws(tmp_path)
    anchor = key_freeze.task_signature(ws)
    row1 = _dispatch_row(ws, "C-1")
    _grow_state(ws)
    row2 = _dispatch_row(ws, "C-2")
    assert row1["signature_hash"] == anchor
    assert row2["signature_hash"] == anchor
    rows = q_cells.JSONLQStore(ws).observations()
    assert len(rows) == 2
    assert rows[0]["signature_hash"] == rows[1]["signature_hash"]


def test_undeclared_gap_mints_nothing(tmp_path):
    """The honest gap stays the honest gap: an undeclared dispatch mints
    no frozen doc (the freeze rides a real learning observation)."""
    ws = _bare_ws(tmp_path)
    out = q_cells.record_dispatch_observation(ws, "no declaration here",
                                              envelope_meta=None)
    assert out["appended"] is False
    assert not (ws / "runs" / "learning-key.json").exists()


def test_freeze_survives_reload(tmp_path):
    """The frozen doc is durable state: a fresh process face (new module
    call) reads the SAME anchor and key — the freeze is not in-memory."""
    ws = _bare_ws(tmp_path)
    frozen = key_freeze.freeze_task_key(ws, FAM)
    doc = json.loads((ws / "runs" / "learning-key.json").read_text(
        encoding="utf-8"))
    assert doc["schema"] == key_freeze.FROZEN_SCHEMA
    assert doc["task_signature"] == frozen["signature_hash"]
    assert doc["keys"][FAM]["key"] == frozen["key"]
    assert key_freeze.task_signature(ws) == frozen["signature_hash"]
    assert key_freeze.frozen_key(ws, FAM) == frozen["key"]


def test_other_escape_refused_at_the_freeze_boundary(tmp_path):
    """The panel quarantine: other(...) free-text escapes fragment cells
    without learning value — refused at the boundary, nothing written."""
    ws = _bare_ws(tmp_path)
    with pytest.raises(ValueError, match="other"):
        key_freeze.freeze_task_key(ws, "other(hotpatch the jsvmp)")
    with pytest.raises(ValueError, match="other"):
        key_freeze.freeze_task_key(ws, "other")
    assert not (ws / "runs" / "learning-key.json").exists()


def test_empty_family_refused(tmp_path):
    ws = _bare_ws(tmp_path)
    with pytest.raises(ValueError):
        key_freeze.freeze_task_key(ws, "   ")
    assert not (ws / "runs" / "learning-key.json").exists()


def test_frozen_key_read_never_mints(tmp_path):
    """frozen_key is a PURE read: a task that never froze reads None and
    creates nothing (only real freezes write the doc)."""
    ws = _bare_ws(tmp_path)
    assert key_freeze.frozen_key(ws, FAM) is None
    assert not (ws / "runs" / "learning-key.json").exists()


def test_task_signature_mint_on_read_opens_the_task(tmp_path):
    """The first consumer of the learning channel IS task open:
    task_signature snaps the anchor once and persists the doc; the
    anchor reflects the state AT OPEN (fresh computation on a bare ws),
    then never moves (the immutability pin above)."""
    ws = _bare_ws(tmp_path)
    anchor = key_freeze.task_signature(ws)
    assert anchor == ssig.signature_hash(ssig.snapshot(ws))
    assert (ws / "runs" / "learning-key.json").is_file()


def test_corrupt_doc_reopens_the_task_once(tmp_path):
    """A corrupt frozen doc is the honest not-frozen fact: the NEXT
    read re-opens the task (one fresh snap at the corruption boundary —
    the self-healing face), freezes again from there, and the doc is
    valid JSON again. frozen_key stays a pure read (None, no repair)."""
    ws = _bare_ws(tmp_path)
    assert key_freeze.task_signature(ws) is not None
    (ws / "runs").mkdir(exist_ok=True)
    (ws / "runs" / "learning-key.json").write_text("{not json",
                                                   encoding="utf-8")
    assert key_freeze.frozen_key(ws, FAM) is None       # pure read
    reopened = key_freeze.task_signature(ws)             # re-open ONCE
    assert reopened == ssig.signature_hash(ssig.snapshot(ws))
    _grow_state(ws)
    assert key_freeze.task_signature(ws) == reopened     # frozen again
    doc = json.loads((ws / "runs" / "learning-key.json").read_text(
        encoding="utf-8"))
    assert doc["schema"] == key_freeze.FROZEN_SCHEMA


# ------------------------------------------------------------ (b) churn


def test_churn_all_new_is_loud(tmp_path):
    """The production shape (pq-01: 3 distinct fingerprints / 35 min):
    churn=1.0 verdict all-new — LOUD by structure (the verdict field),
    Standard 11 clean (no telemetry, one report)."""
    report = key_freeze.churn_rate([["fp-a", "fp-b", "fp-c"]])
    assert report["churn"] == 1.0
    assert report["verdict"] == "all-new"
    assert report["dispatches"] == 3
    assert report["distinct"] == 3
    assert report["new"] == 3
    assert report["reused"] == 0


def test_churn_reused_across_runs(tmp_path):
    """Cross-run reuse is the accumulation signal: a fingerprint seen in
    an earlier run counts as reused."""
    report = key_freeze.churn_rate([["fp-a", "fp-b"], ["fp-a", "fp-c"]])
    assert report["new"] == 3
    assert report["reused"] == 1
    assert report["churn"] == pytest.approx(0.75)
    assert report["verdict"] == "accumulating"


def test_churn_full_reuse_is_frozen(tmp_path):
    """The stability face: a run that introduces ZERO new fingerprints
    (every fingerprint already known from earlier runs) reads verdict
    "frozen" — accumulation is working (churn falls from the all-new
    production shape toward the frozen face as keys repeat)."""
    report = key_freeze.churn_rate([["fp-a", "fp-b"], ["fp-a", "fp-b"]])
    assert report["churn"] == pytest.approx(0.5)
    assert report["verdict"] == "frozen"
    assert report["last_run_new"] == 0


def test_churn_no_data_is_honest(tmp_path):
    report = key_freeze.churn_rate([[], [None, ""]])
    assert report["dispatches"] == 0
    assert report["churn"] is None
    assert report["verdict"] == "no-data"


def test_churn_report_reads_the_experience_ledger(tmp_path):
    """The measurement surface over the LIVE ledger face: dispatch rows'
    fingerprints measured as one run (the workspace IS the run)."""
    ws = _bare_ws(tmp_path)
    _dispatch_row(ws, "C-1", fingerprint="fp-1")
    _dispatch_row(ws, "C-2", fingerprint="fp-1")   # reuse inside the run
    _dispatch_row(ws, "C-3", fingerprint="fp-2")
    report = key_freeze.churn_report(ws)
    assert report["dispatches"] == 3
    assert report["distinct"] == 2
    assert report["new"] == 2
    assert report["reused"] == 1
    assert report["churn"] == pytest.approx(2 / 3)
    assert report["verdict"] == "accumulating"


def test_churn_report_production_shape_all_new(tmp_path):
    """The production pathology as a measurable fixture: per-dispatch
    fresh fingerprints (the pre-freeze face) read churn=1.0 all-new."""
    ws = _bare_ws(tmp_path)
    for i, fp in enumerate(("trig-1", "trig-2", "trig-3")):
        _dispatch_row(ws, f"C-{i + 1}", fingerprint=fp)
    report = key_freeze.churn_report(ws)
    assert report["churn"] == 1.0
    assert report["verdict"] == "all-new"


def test_churn_report_bare_workspace_is_no_data(tmp_path):
    ws = _bare_ws(tmp_path)
    report = key_freeze.churn_report(ws)
    assert report["verdict"] == "no-data"
    assert report["dispatches"] == 0


def test_churn_report_unreadable_ledger_is_the_honest_gap(tmp_path):
    """An unreadable ledger is NOT the same fact as an empty one — the
    report carries the reason (the banked_mass None-vs-empty lesson)."""
    ws = _bare_ws(tmp_path)
    (ws / "runs").mkdir(parents=True)
    (ws / "runs" / "experience.jsonl").mkdir()  # a dir at the ledger rel
    report = key_freeze.churn_report(ws)
    assert report["verdict"] == "no-data"
    assert report.get("reason")


def test_key_freeze_module_adds_no_warn_points():
    """Standard 11: this card's faces report structurally (verdict
    fields, report rows) — ZERO warn() CALLS in the module (the 392-warn
    lesson: repetition is not escalation). AST-parsed so the docstring
    discussing the discipline doesn't false-positive."""
    import ast
    src = (SCRIPTS / "rlvr" / "key_freeze.py").read_text(encoding="utf-8")
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "warn"]
    assert calls == []
