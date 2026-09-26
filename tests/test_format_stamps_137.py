# -*- coding: utf-8 -*-
"""tests/test_format_stamps_137.py — format stamps on persisted state rows
(issue 137, v0.1.6 promoted slice).

Workspaces self-describe: NEW writes to the persisted state surfaces carry
a ``schema`` format stamp so #294's replay can read HISTORICAL formats
without guessing. Legacy rows (pre-stamp) stay readable — absence of the
field = legacy, never an error (the #135/#136 tolerance pattern; the
no-backcompat policy applies to code faces, not to historical workspace
data — historical files are NEVER rewritten).

Surfaces already stamped (verified here as regression guards, not changed):
  - runs/posteriors.yaml      — schema posteriors-schema/1 (mandatory,
                                loud reject on unknown — version wall)
  - task_terminal_settlement  — schema task-terminal-settlement/1 in the
                                detail payload (issue 136)

Surfaces stamped BY THIS ISSUE (new writes only):
  - .convergence_ledger.jsonl snapshot rows (convergence_check._append_ledger)
  - .convergence_ledger.jsonl operator_action rows (record_operator_action)
  - runs/case-bank.jsonl rows (case_bank.append)

All fixtures here are SYNTHETIC (privacy rule: no real workspace data).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import case_bank as cb  # noqa: E402
import status_defs  # noqa: E402


# ---------- synthetic helpers ----------

def _ledger_lines(ws: Path) -> list[dict]:
    p = ws / ".convergence_ledger.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _decision_dict() -> dict:
    """Minimal decision payload for _append_ledger (snapshot writer shape)."""
    return {
        "decision": "CONTINUE",
        "open_count": 1,
        "open_claims": [{"id": "C-001"}],
        "partial_count": 0,
        "active_workers": 0,
        "active_blockers": [],
    }


def _bank_entry(roi_class: str = "POSITIVE") -> dict:
    e = {
        "claim_id": "C-001",
        "method": "device-trace(xxx)",
        "roi_class": roi_class,
        "context_tags": ["auth"],
    }
    if roi_class == "NEGATIVE":
        e["attribution"] = "wrong anchor length assumed"
    return e


# ---------- A. ledger snapshot rows (new writes carry the stamp) ----------

def test_new_snapshot_row_carries_schema_stamp(tmp_path):
    from convergence_check import _append_ledger
    _append_ledger(tmp_path, _decision_dict())
    rows = _ledger_lines(tmp_path)
    assert len(rows) == 1
    assert rows[0]["schema"] == status_defs.LEDGER_FORMAT


def test_new_operator_action_row_carries_schema_stamp(tmp_path):
    from convergence_check import record_operator_action
    record_operator_action(tmp_path, action="defer", claim_id="C-001",
                           reason="waiting on external gate")
    rows = _ledger_lines(tmp_path)
    assert len(rows) == 1
    assert rows[0]["schema"] == status_defs.LEDGER_FORMAT
    assert rows[0]["type"] == status_defs.LedgerLineType.OPERATOR_ACTION


def test_ledger_format_constant_is_namespaced():
    """The stamp names the surface AND the shape — 'convergence-ledger/2'
    (v2 = the dispatched_ids + stamp era), mirroring the repo's
    '<name>/<rev>' convention (posteriors-schema/1, task-terminal-settlement/1).
    """
    assert status_defs.LEDGER_FORMAT == "convergence-ledger/2"


# ---------- B. legacy ledger rows stay readable (absence = legacy) ----------

def test_legacy_rows_classify_without_stamp():
    """Pre-stamp rows (no schema field) keep their LedgerLineType — the
    type-contract tolerance is unchanged by the new field."""
    legacy_snapshot = {"ts": "2026-01-01T00:00:00", "decision": "CONTINUE",
                       "open_count": 0}
    legacy_operator = {"type": "operator_action", "action": "defer"}
    legacy_outcome = {"type": "outcome", "claim_id": "C-9", "result": "pass"}
    assert status_defs.ledger_line_type(legacy_snapshot) == "snapshot"
    assert status_defs.ledger_line_type(legacy_operator) == "operator_action"
    assert status_defs.ledger_line_type(legacy_outcome) == "outcome"


def test_resume_snapshot_reader_reads_legacy_and_new_rows(tmp_path):
    """external_kicker._ledger_last_snapshot (the recovery read path)
    counts and returns the LAST snapshot whether or not it carries the
    stamp — a legacy workspace resumes exactly as before."""
    from external_kicker import _ledger_last_snapshot
    legacy = {"ts": "t0", "decision": "CONTINUE", "open_count": 2}
    _append_raw(tmp_path, [legacy])
    last, count = _ledger_last_snapshot(tmp_path)
    assert count == 1 and last["open_count"] == 2
    # a NEW stamped row appended after legacy rows stays a snapshot
    from convergence_check import _append_ledger
    _append_ledger(tmp_path, _decision_dict())
    last, count = _ledger_last_snapshot(tmp_path)
    assert count == 2 and last["decision"] == "CONTINUE"


def test_replay_load_history_reads_legacy_and_new_rows(tmp_path):
    """#294 replay_ruler.load_history tolerates both generations: legacy
    snapshots still infer format=new/old from dispatched_ids; stamped new
    rows read identically (is_snapshot=True either way)."""
    from replay_ruler import load_history
    legacy_old = {"ts": "t0", "decision": "CONTINUE", "open_count": 1}
    legacy_new = {"ts": "t1", "decision": "CONTINUE", "open_count": 1,
                  "dispatched_ids": ["C-001"]}
    _append_raw(tmp_path, [legacy_old, legacy_new])
    hist = load_history(tmp_path)
    assert [h["is_snapshot"] for h in hist] == [True, True]
    assert [h["format"] for h in hist] == ["old", "new"]
    from convergence_check import _append_ledger
    _append_ledger(tmp_path, _decision_dict())
    hist = load_history(tmp_path)
    assert len(hist) == 3 and hist[-1]["is_snapshot"] is True
    # the row-level stamp is carried through, not stripped
    assert hist[-1]["row"]["schema"] == status_defs.LEDGER_FORMAT


def _append_raw(ws: Path, rows: list[dict]) -> None:
    p = ws / ".convergence_ledger.jsonl"
    with open(p, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------- C. case-bank rows ----------

def test_new_case_bank_row_carries_schema_stamp(tmp_path):
    stored = cb.append(tmp_path, _bank_entry())
    assert stored["schema"] == cb.SCHEMA_ID
    on_disk = cb.read_entries(tmp_path)
    assert on_disk and on_disk[0]["schema"] == cb.SCHEMA_ID


def test_case_bank_schema_constant_is_namespaced():
    assert cb.SCHEMA_ID == "case-bank/2"


def test_legacy_case_bank_rows_readable(tmp_path):
    """Pre-stamp rows (no schema; the #146 `how` field absent) read back
    through read_entries/retrieve — historical banks are never rewritten
    and never rejected."""
    legacy = {
        "ts": "2026-01-01T00:00:00Z",
        "claim_id": "C-900",
        "method": "legacy-method",
        "context_tags": ["auth"],
        "intent_uncertainty": "",
        "outcome_observed": {},
        "roi_class": "NEGATIVE",
        "attribution": "assumed AES where RC4 shipped",
        "premise_correction": None,
        "how": None,
    }
    p = tmp_path / "runs" / "case-bank.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(legacy, ensure_ascii=False) + "\n")
    entries = cb.read_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0]["roi_class"] == "NEGATIVE"
    assert "schema" not in entries[0]  # genuinely legacy-shaped
    # retrieval consumes the legacy row without error
    got = cb.retrieve(tmp_path, ["auth"], limit=5)
    assert [e["claim_id"] for e in got] == ["C-900"]


def test_mixed_generations_coexist_in_one_bank(tmp_path):
    """A bank with legacy rows then NEW stamped rows reads both — the
    stamp is additive per row, generations interleave freely."""
    legacy = dict(_bank_entry(), claim_id="C-OLD", ts="2026-01-01T00:00:00Z")
    cb.append(tmp_path, legacy)  # writer output (stamped)
    # force a true legacy row on disk (pre-stamp writer output)
    p = cb.bank_path(tmp_path)
    rows = [json.loads(line) for line in
            p.read_text(encoding="utf-8").splitlines()]
    for r in rows:
        r.pop("schema", None)
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                         for r in rows), encoding="utf-8")
    cb.append(tmp_path, dict(_bank_entry(), claim_id="C-NEW"))
    claims = [e["claim_id"] for e in cb.read_entries(tmp_path)]
    assert claims == ["C-OLD", "C-NEW"]


# ---------- D. already-stamped surfaces (regression guards) ----------

def test_posteriors_ledger_stamp_is_mandatory():
    from posteriors import SCHEMA_ID, PosteriorSchemaError, PosteriorLedger
    assert SCHEMA_ID == "posteriors-schema/1"
    with pytest.raises(PosteriorSchemaError):
        PosteriorLedger.from_doc({"schema": "posteriors-schema/99",
                                  "cases": {}, "pqs": {}})


def test_terminal_settlement_row_schema_stamp_unchanged():
    import terminal_settlement as ts
    assert ts.SCHEMA == "task-terminal-settlement/1"


# ---------- E. r2 review FIX-2: the other two ledger append sites ----------

def test_retract_operator_action_row_carries_schema_stamp(tmp_path):
    """retract_claim's operator_action row (its own _append_ledger, distinct
    from convergence_check's) carries the same single-home stamp — a
    retraction must not emit a row indistinguishable from legacy."""
    import yaml
    import retract_claim as rc
    (tmp_path / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-1", "status": "PROVEN"}]},
                       allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    r = rc.retract_claim(tmp_path, "C-1", reason="refuted", by="verify-run")
    assert r["ok"] is True
    rows = _ledger_lines(tmp_path)
    assert len(rows) == 1
    assert rows[0]["type"] == status_defs.LedgerLineType.OPERATOR_ACTION
    assert rows[0]["schema"] == status_defs.LEDGER_FORMAT
    assert rows[0]["action"] == "retract"


def test_outcome_capture_rows_carry_schema_stamp(tmp_path):
    """outcome_capture's OUTCOME rows (both the verify-note and the
    red-team parse faces) carry the stamp — a capture tomorrow is
    read-by-field, not legacy-by-inference."""
    import outcome_capture as oc
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "2026-08-11T00-00-00-verify-01-draft.md").write_text(
        "---\nclaim_id: C-1\nverify_status: passes\n---\n\n"
        "## Overall verdict\npasses\n",
        encoding="utf-8")
    (runs / "2026-08-11T00-01-00-verify-redteam-x.md").write_text(
        "## RED-TEAM VERDICT\nCONFIRMED\n", encoding="utf-8")
    added = oc.capture(tmp_path)
    assert added == 2
    rows = oc.read_outcome_rows(tmp_path)
    assert {r["checker"] for r in rows} == {"verify-note", "red-team"}
    assert all(r["schema"] == status_defs.LEDGER_FORMAT for r in rows)
    assert all(r["type"] == status_defs.LedgerLineType.OUTCOME for r in rows)
