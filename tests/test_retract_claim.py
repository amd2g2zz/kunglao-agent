# -*- coding: utf-8 -*-
"""Tests for retract_claim.py — RETRACTED terminal state + dependency blast-radius
reopening + report citation gate (#331).

TDD RED phase: these tests define the contract BEFORE implementation.
RED runs (expected fails until retract_claim.py exists):
  - test_retract_sets_retracted_with_metadata
  - test_retract_propagates_single_level
  - test_retract_cascades_three_levels        (blast radius: A→B→C all reopened)
  - test_retract_idempotent                   (repeated retraction does not re-propagate)
  - test_retract_excludes_already_open_and_dead_dependents
  - test_retract_writes_ledger_operator_action
  - test_retract_does_not_touch_failure_registry (retraction != execution failure)
  - test_convergence_check_treats_retracted_as_terminal
  - test_priority_excludes_retracted
  - test_priority_reopened_dependents_dispatchable
  - test_anchors_gate_blocks_retracted_fact    (gate blocks)
  - test_anchors_gate_passes_clean_facts
  - test_dry_run_writes_nothing

Issue #331 acceptance:
  - 3-level dependency chain A→B→C: retract A → B/C all reopen; retract again (A idempotent) → no change
  - convergence check judges RETRACTED correctly; report referencing a RETRACTED fact is blocked by the gate
  - propagation/idempotency/cascade/gate-blocking each with at least 1 case
Run: python -m pytest tests/test_retract_claim.py -q
"""
import sys
from pathlib import Path

# sibling import (scripts/ on sys.path for both direct-run and pytest)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import yaml  # noqa: E402
import retract_claim as rc  # noqa: E402
import convergence_check as cc  # noqa: E402
import priority as pr  # noqa: E402


# ---------- helpers ----------

def _mk_reg(ws: Path, claims: list) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _mk_deps(ws: Path, depends_on: dict) -> None:
    (ws / "claim_deps.yaml").write_text(
        yaml.safe_dump({"depends_on": depends_on}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _mk_index(ws: Path, lines: list) -> None:
    facts = ws / "facts"
    facts.mkdir(exist_ok=True)
    (facts / "_INDEX.md").write_text(
        "# _INDEX\n\n" + "\n".join(lines) + "\n", encoding="utf-8"
    )


def _load_reg(ws: Path) -> dict:
    return yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8")
    ) or {}


def _claim(reg: dict, cid: str) -> dict:
    return next(c for c in reg["claims"] if c["id"] == cid)


def _ledger_rows(ws: Path) -> list:
    p = ws / ".convergence_ledger.jsonl"
    if not p.exists():
        return []
    import json
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------- RED: retraction mechanics ----------

def test_retract_sets_retracted_with_metadata(tmp_path):
    """PROVEN claim -> RETRACTED + retract_reason/retract_by/retracted_ts."""
    _mk_reg(tmp_path, [{"id": "C-1", "status": "PROVEN"}])
    r = rc.retract_claim(tmp_path, "C-1", reason="refuted", by="facts/F020.md#L12")
    assert r["ok"] is True
    assert r["retracted"] is True
    assert r["before"] == "PROVEN"
    claim = _claim(_load_reg(tmp_path), "C-1")
    assert claim["status"] == "RETRACTED"
    assert claim["retract_reason"] == "refuted"
    assert claim["retract_by"] == "facts/F020.md#L12"
    assert claim.get("retracted_ts")


def test_retract_propagates_single_level(tmp_path):
    """A retracted -> direct dependent B reopened with reopened_by=A and attempts reset."""
    _mk_reg(tmp_path, [
        {"id": "A", "status": "PROVEN"},
        {"id": "B", "status": "PROVEN", "promotion_attempts": 2},
    ])
    _mk_deps(tmp_path, {"B": ["A"]})
    r = rc.retract_claim(tmp_path, "A", reason="refuted", by="verify-run")
    assert r["reopened"] == ["B"]
    reg = _load_reg(tmp_path)
    b = _claim(reg, "B")
    assert b["status"] == "OPEN"
    assert b["reopened_by"] == "A"
    assert b["promotion_attempts"] == 0, "reopened claim must be re-dispatchable"
    assert _claim(reg, "A")["status"] == "RETRACTED"


def test_retract_cascades_three_levels(tmp_path):
    """Blast radius: A→B→C all PROVEN; retracting A reopens B AND C."""
    _mk_reg(tmp_path, [
        {"id": "A", "status": "PROVEN"},
        {"id": "B", "status": "PROVEN"},
        {"id": "C", "status": "PROVEN"},
    ])
    _mk_deps(tmp_path, {"B": ["A"], "C": ["B"]})
    r = rc.retract_claim(tmp_path, "A", reason="superseded", by="facts/F030.md")
    assert sorted(r["reopened"]) == ["B", "C"]
    reg = _load_reg(tmp_path)
    assert _claim(reg, "B")["status"] == "OPEN"
    assert _claim(reg, "B")["reopened_by"] == "A"
    assert _claim(reg, "C")["status"] == "OPEN"
    assert _claim(reg, "C")["reopened_by"] == "A"


def test_retract_idempotent(tmp_path):
    """Re-retracting the same id is a no-op: no re-propagation, no rewrite, one ledger row."""
    _mk_reg(tmp_path, [
        {"id": "A", "status": "PROVEN"},
        {"id": "B", "status": "PROVEN"},
    ])
    _mk_deps(tmp_path, {"B": ["A"]})
    first = rc.retract_claim(tmp_path, "A", reason="refuted", by="v1")
    assert first["reopened"] == ["B"]
    snapshot = (tmp_path / "claim-register.yaml").read_bytes()
    rows_before = len(_ledger_rows(tmp_path))

    second = rc.retract_claim(tmp_path, "A", reason="refuted", by="v1")
    assert second["ok"] is True
    assert second.get("already_retracted") is True
    assert second["reopened"] == []
    assert (tmp_path / "claim-register.yaml").read_bytes() == snapshot, \
        "idempotent re-retract must not rewrite the register"
    assert len(_ledger_rows(tmp_path)) == rows_before, \
        "idempotent re-retract must not append another retraction row"
    retractions = [row for row in _ledger_rows(tmp_path) if row.get("action") == "retract"]
    assert len(retractions) == 1


def test_retract_unknown_claim_rejected(tmp_path):
    """Unknown claim id -> ok False, no write, no ledger row."""
    _mk_reg(tmp_path, [{"id": "C-1", "status": "PROVEN"}])
    before = (tmp_path / "claim-register.yaml").read_bytes()
    r = rc.retract_claim(tmp_path, "C-404", reason="refuted", by="x")
    assert r["ok"] is False
    assert "C-404" in r["reason"]
    assert (tmp_path / "claim-register.yaml").read_bytes() == before
    assert _ledger_rows(tmp_path) == []


def test_retract_invalid_reason_rejected(tmp_path):
    """retract_reason must be refuted|superseded; anything else rejected."""
    _mk_reg(tmp_path, [{"id": "C-1", "status": "PROVEN"}])
    before = (tmp_path / "claim-register.yaml").read_bytes()
    r = rc.retract_claim(tmp_path, "C-1", reason="oops", by="x")
    assert r["ok"] is False
    assert "reason" in r["reason"].lower() or "oops" in r["reason"]
    assert (tmp_path / "claim-register.yaml").read_bytes() == before


def test_retract_requires_evidence_pointer(tmp_path):
    """retract_by (evidence pointer) is mandatory — a bare retraction is rejected."""
    _mk_reg(tmp_path, [{"id": "C-1", "status": "PROVEN"}])
    before = (tmp_path / "claim-register.yaml").read_bytes()
    r = rc.retract_claim(tmp_path, "C-1", reason="refuted", by="")
    assert r["ok"] is False
    assert "retract_by" in r["reason"]
    assert (tmp_path / "claim-register.yaml").read_bytes() == before
    assert _ledger_rows(tmp_path) == []


def test_retract_excludes_already_open_and_dead_dependents(tmp_path):
    """Blast radius only reopens settled verdicts: OPEN stays untouched, DEAD stays quarantined."""
    _mk_reg(tmp_path, [
        {"id": "A", "status": "PROVEN"},
        {"id": "B", "status": "OPEN"},
        {"id": "C", "status": "DEAD", "promotion_attempts": 5},
        {"id": "D", "status": "VERIFIED"},
    ])
    _mk_deps(tmp_path, {"B": ["A"], "C": ["A"], "D": ["A"]})
    r = rc.retract_claim(tmp_path, "A", reason="refuted", by="v")
    assert r["reopened"] == ["D"]
    reg = _load_reg(tmp_path)
    b = _claim(reg, "B")
    assert b["status"] == "OPEN" and "reopened_by" not in b
    c = _claim(reg, "C")
    assert c["status"] == "DEAD", "DLQ-quarantined claim must not be reopened"
    assert _claim(reg, "D")["status"] == "OPEN"


def test_retract_skips_in_progress_dependent(tmp_path):
    """In-flight dependent is NOT reset — reopening it to OPEN+attempts=0 while
    its worker still runs would allow a second dispatch of the same claim
    (double-dispatch). IN_PROGRESS keeps its status and attempts; the skip is
    reported so the orchestrator knows a live worker is running on a dead premise.
    """
    _mk_reg(tmp_path, [
        {"id": "A", "status": "PROVEN"},
        {"id": "B", "status": "IN_PROGRESS", "promotion_attempts": 1},
        {"id": "C", "status": "PROVEN"},
    ])
    _mk_deps(tmp_path, {"B": ["A"], "C": ["A"]})
    r = rc.retract_claim(tmp_path, "A", reason="refuted", by="v")
    assert r["reopened"] == ["C"], "only the settled dependent is reopened"
    assert r["skipped_in_progress"] == ["B"]
    reg = _load_reg(tmp_path)
    b = _claim(reg, "B")
    assert b["status"] == "IN_PROGRESS", "in-flight claim must not be reset to OPEN"
    assert b["promotion_attempts"] == 1, "in-flight claim must keep its attempts"
    assert "reopened_by" not in b
    # no double dispatch: IN_PROGRESS is not dispatchable
    rows = pr.rank_claims(reg, yaml.safe_load(
        (tmp_path / "claim_deps.yaml").read_text(encoding="utf-8")), pr.DEFAULT_WEIGHTS)
    assert "B" not in [row["id"] for row in rows]
    # the skip is recorded in the ledger row (convergence-visible audit trail)
    led = [row for row in _ledger_rows(tmp_path) if row.get("action") == "retract"]
    assert led and led[0].get("skipped_in_progress") == ["B"]


def test_retract_writes_ledger_operator_action(tmp_path):
    """Retraction is recorded as an operator_action row (retraction ≠ execution failure)."""
    _mk_reg(tmp_path, [{"id": "A", "status": "PROVEN"}, {"id": "B", "status": "PROVEN"}])
    _mk_deps(tmp_path, {"B": ["A"]})
    rc.retract_claim(tmp_path, "A", reason="superseded", by="facts/F007.md")
    rows = [r for r in _ledger_rows(tmp_path) if r.get("action") == "retract"]
    assert len(rows) == 1
    row = rows[0]
    assert row["type"] == "operator_action"
    assert row["claim_id"] == "A"
    assert row["reason"] == "superseded"
    assert row["after"] == "RETRACTED"
    assert row["reopened"] == ["B"]
    assert row.get("ts")


def test_retract_does_not_touch_failure_registry(tmp_path):
    """Item 6: retraction is premise death, not execution failure — no failure-registry entry."""
    _mk_reg(tmp_path, [{"id": "A", "status": "PROVEN"}])
    failure_reg = tmp_path / "analyses" / "failure-A.yaml"
    failure_reg.parent.mkdir(parents=True, exist_ok=True)
    failure_reg.write_text("claim_id: A\nstate: BLOCKED\n", encoding="utf-8")
    rc.retract_claim(tmp_path, "A", reason="refuted", by="v")
    assert failure_reg.read_text(encoding="utf-8") == "claim_id: A\nstate: BLOCKED\n", \
        "retraction must not mutate the failure registry"
    assert not (tmp_path / "analyses" / "failure-retract-A.yaml").exists()


def test_dry_run_writes_nothing(tmp_path):
    """--dry-run reports the blast radius but changes no file and writes no ledger row."""
    _mk_reg(tmp_path, [{"id": "A", "status": "PROVEN"}, {"id": "B", "status": "PROVEN"}])
    _mk_deps(tmp_path, {"B": ["A"]})
    before_reg = (tmp_path / "claim-register.yaml").read_bytes()
    r = rc.retract_claim(tmp_path, "A", reason="refuted", by="v", dry_run=True)
    assert r["ok"] is True and r["reopened"] == ["B"]
    assert (tmp_path / "claim-register.yaml").read_bytes() == before_reg
    assert _ledger_rows(tmp_path) == []


# ---------- RED: consumer compatibility (issue items 3 & 4) ----------

def test_convergence_check_treats_retracted_as_terminal(tmp_path):
    """RETRACTED does not block convergence and is not dispatched."""
    _mk_reg(tmp_path, [{"id": "C-1", "status": "RETRACTED"}])
    reg = _load_reg(tmp_path)
    assert cc._open_claims(reg) == []
    d = cc.decide(tmp_path)
    assert d["decision"] == "CONVERGED", f"RETRACTED-only register must converge, got {d['decision']}: {d['action']}"


def test_retracted_claim_not_flagged_orphan(tmp_path):
    """A RETRACTED claim without answers_question is withdrawn, not an orphan."""
    reg = {"claims": [
        {"id": "C-1", "status": "RETRACTED"},
        {"id": "C-2", "status": "PROVEN"},
    ]}
    orphans = cc._orphan_terminal_claims(reg, {"Q1"})
    assert [o["id"] for o in orphans] == ["C-2"], \
        "RETRACTED must be excluded from the orphan gate (it answers nothing by design)"


def test_priority_excludes_retracted(tmp_path):
    """RETRACTED claims never appear in the dispatch queue."""
    _mk_reg(tmp_path, [
        {"id": "A", "status": "RETRACTED", "promotion_attempts": 0},
        {"id": "B", "status": "OPEN", "promotion_attempts": 0},
    ])
    _mk_deps(tmp_path, {})
    reg = _load_reg(tmp_path)
    rows = pr.rank_claims(reg, {}, pr.DEFAULT_WEIGHTS)
    ids = [r["id"] for r in rows]
    assert "A" not in ids
    assert "B" in ids


def test_priority_reopened_dependents_dispatchable(tmp_path):
    """A dependent of a RETRACTED claim is dispatchable (its parent is terminal)."""
    _mk_reg(tmp_path, [
        {"id": "A", "status": "RETRACTED"},
        {"id": "B", "status": "OPEN", "promotion_attempts": 0},
    ])
    _mk_deps(tmp_path, {"B": ["A"]})
    reg = _load_reg(tmp_path)
    deps = yaml.safe_load((tmp_path / "claim_deps.yaml").read_text(encoding="utf-8"))
    rows = pr.rank_claims(reg, deps, pr.DEFAULT_WEIGHTS)
    ids = [r["id"] for r in rows]
    assert "B" in ids, "reopened dependent must be dispatchable"


# ---------- RED: report citation gate (issue item 5) ----------

def test_anchors_gate_blocks_retracted_fact(tmp_path):
    """A report anchors file citing a fact owned by a RETRACTED claim -> FAIL violations."""
    _mk_reg(tmp_path, [
        {"id": "C-1", "status": "RETRACTED"},
        {"id": "C-2", "status": "PROVEN"},
    ])
    _mk_index(tmp_path, [
        "F010 | PROVEN | C-1 | sample is packed",
        "F011 | PROVEN | C-2 | family attribution",
    ])
    anchors = tmp_path / "fact_anchors.md"
    anchors.write_text(
        "# anchors\n- F010: packer UPX\n- F011: family Zbot\n", encoding="utf-8"
    )
    violations = rc.check_retracted_references(tmp_path, anchors)
    assert len(violations) == 1
    v = violations[0]
    assert v["fact"] == "F010"
    assert v["claim_id"] == "C-1"
    assert "F010" in v["ref"]


def test_anchors_gate_passes_clean_facts(tmp_path):
    """Anchors citing only facts of non-retracted claims -> no violations."""
    _mk_reg(tmp_path, [
        {"id": "C-1", "status": "RETRACTED"},
        {"id": "C-2", "status": "PROVEN"},
    ])
    _mk_index(tmp_path, [
        "F010 | PROVEN | C-1 | sample is packed",
        "F011 | PROVEN | C-2 | family attribution",
    ])
    anchors = tmp_path / "fact_anchors.md"
    anchors.write_text("# anchors\n- F011: family Zbot\n", encoding="utf-8")
    assert rc.check_retracted_references(tmp_path, anchors) == []


def test_anchors_gate_missing_file_clean(tmp_path):
    """No anchors file on disk -> nothing to check -> clean."""
    _mk_reg(tmp_path, [{"id": "C-1", "status": "RETRACTED"}])
    _mk_index(tmp_path, ["F010 | PROVEN | C-1 | packed"])
    assert rc.check_retracted_references(tmp_path) == []


# ---------- RED: CLI exit codes ----------

def test_cli_retract_exit_codes(tmp_path):
    """main(): 1=reopened, 0=idempotent repeat, 2=unknown claim, SystemExit(2)=missing --by."""
    _mk_reg(tmp_path, [{"id": "A", "status": "PROVEN"}, {"id": "B", "status": "PROVEN"}])
    _mk_deps(tmp_path, {"B": ["A"]})
    assert rc.main([str(tmp_path), "A", "--reason", "refuted", "--by", "v"]) == 1
    assert rc.main([str(tmp_path), "A", "--reason", "refuted", "--by", "v"]) == 0
    assert rc.main([str(tmp_path), "C-404", "--reason", "refuted", "--by", "v"]) == 2
    import pytest
    with pytest.raises(SystemExit) as exc:
        rc.main([str(tmp_path), "A", "--reason", "refuted"])
    assert exc.value.code == 2


def test_cli_anchors_gate_exit(tmp_path):
    """main() --check-anchors: 3=FAIL on retracted fact citation, 0=clean."""
    _mk_reg(tmp_path, [{"id": "C-1", "status": "RETRACTED"}, {"id": "C-2", "status": "PROVEN"}])
    _mk_index(tmp_path, [
        "F010 | PROVEN | C-1 | packed",
        "F011 | PROVEN | C-2 | family",
    ])
    dirty = tmp_path / "dirty_anchors.md"
    dirty.write_text("- F010: UPX\n", encoding="utf-8")
    assert rc.main([str(tmp_path), "--check-anchors", str(dirty)]) == 3
    clean = tmp_path / "clean_anchors.md"
    clean.write_text("- F011: Zbot\n", encoding="utf-8")
    assert rc.main([str(tmp_path), "--check-anchors", str(clean)]) == 0


# ---------- guard: single source of truth (mirrors test_status_defs.py) ----------

def test_retract_module_exports_single_retracted_source(tmp_path):
    """RETRACTED lives in retract_claim.py; consumers import, never redefine."""
    assert rc.RETRACTED == "RETRACTED"
    assert rc.TERMINAL_WITH_RETRACTED >= {"PROVEN", "RETRACTED", "DEAD"}
    for mod_name, mod in (("convergence_check", cc), ("priority", pr)):
        src = sys.modules[mod_name].__file__
        text = Path(src).read_text(encoding="utf-8")
        assert "RETRACTED" in text, f"{mod_name} must be RETRACTED-aware"
        assert "TERMINAL = {" not in text, f"{mod_name} must not redefine TERMINAL"
