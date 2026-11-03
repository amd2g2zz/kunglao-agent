# -*- coding: utf-8 -*-
"""tests/test_claims_store_measured_818.py — the claims store's
refusal/fail-open faces in the MEASURED leg (issue #818; counts double:
the Wave-0 claims-store tooth).

The saga's happy paths and crash-recovery pins live in
tests/test_claims_store_800*.py (fast tier — not executed by the CI
measured-set leg). This file re-pins, on REAL workspaces: the
unknown-claim refusals (apply + commit_dispatch), the provenance ledger
row a refusal lands, corrupt-journal and corrupt-audit fail-open reads,
and the dispatch-id identity face.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import claims_store as cs  # noqa: E402  (scripts/ on pytest path)


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-1\n    status: OPEN\n", encoding="utf-8")
    return ws


def _provenance(ws: Path) -> list:
    p = ws / cs.PROVENANCE_REL
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------- unknown-claim refusals ----------

def test_apply_unknown_claim_is_refused_and_recorded(tmp_path) -> None:
    ws = _ws(tmp_path)
    res = cs.apply(ws, "C-404", "settle_proven", actor="test")
    assert res.ok is False
    assert res.reason == "unknown-claim"
    (row,) = _provenance(ws)
    assert row["claim"] == "C-404"
    assert row["outcome"] == "refused"
    assert row["reason"] == "unknown-claim"
    assert row["actor"] == "test"
    assert row["schema"] == cs.PROVENANCE_SCHEMA


def test_commit_dispatch_unknown_claim_is_a_no_intent_refusal(
        tmp_path) -> None:
    ws = _ws(tmp_path)
    res = cs.commit_dispatch(ws, "C-404")
    assert res.ok is False
    assert res.reason == "no-intent"


def test_mint_dispatch_ids_are_unique_and_shape_stable() -> None:
    a, b = cs.mint_dispatch_id(), cs.mint_dispatch_id()
    assert a != b
    assert re.fullmatch(r"[0-9a-f]{12}", a), a   # uuid4-hex[:12] identity


# ---------- fail-open journal / audit reads ----------

def test_journal_corrupt_reads_as_none(tmp_path) -> None:
    ws = _ws(tmp_path)
    p = ws / cs.JOURNAL_REL
    p.write_text("{corrupt json", encoding="utf-8")
    assert cs._journal_load(ws) is None
    assert cs.commit_dispatch(ws, "C-1").ok is False


def test_journal_clear_removes_the_file(tmp_path) -> None:
    ws = _ws(tmp_path)
    p = ws / cs.JOURNAL_REL
    p.write_text(json.dumps({"claim": "C-1"}), encoding="utf-8")
    cs._journal_save(ws, None)
    assert not p.exists()
    # clearing twice stays silent (missing_ok)
    cs._journal_save(ws, None)


def test_missing_rollout_audit_corrupt_reads_as_empty(tmp_path) -> None:
    ws = _ws(tmp_path)
    p = ws / cs.MISSING_ROLLOUT_AUDIT_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("]]] not json", encoding="utf-8")
    assert cs._audit_state_load(ws) == {}
    # a non-dict document degrades to empty too
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert cs._audit_state_load(ws) == {}


def test_provenance_schema_version_is_pinned() -> None:
    assert cs.PROVENANCE_SCHEMA == "claims-provenance/1"
