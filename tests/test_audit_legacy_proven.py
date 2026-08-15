# -*- coding: utf-8 -*-
"""tests/test_audit_legacy_proven.py — M4 issue #16: audit tool for 46 fake PROVEN.

RED: fixture (mixed verified/unverified PROVEN) → audit classifies correctly
RED: empty workspace does not crash
RED: no facts/_INDEX → all PROVEN judged unverified
"""
from __future__ import annotations

import json
from pathlib import Path

import audit_legacy_proven as alp


# ---------- helpers ----------

def _write_claim_register(ws: Path, claims: list[dict]) -> None:
    """Write a minimal claim-register.yaml with the given claims."""
    import yaml
    data = {"claims": claims}
    (ws / "claim-register.yaml").write_text(
        yaml.dump(data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


def _write_index(ws: Path, entries: list[tuple[str, str, str, str]]) -> None:
    """Write facts/_INDEX.md with pipe-delimited entries.

    Each entry: (fact_id, status, claim_id, description)
    """
    facts_dir = ws / "facts"
    facts_dir.mkdir(parents=True, exist_ok=True)
    lines = [f"{fid} | {st} | {cid} | {desc}" for fid, st, cid, desc in entries]
    (facts_dir / "_INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------- Test 1: mixed classification ----------

def test_mixed_proven_classification(tmp_path):
    """Fixture with verified + has-evidence + unverified PROVEN → correct 3-way split."""
    ws = tmp_path / "ws-mixed"
    ws.mkdir()

    claims = [
        {"id": "C-001", "status": "PROVEN", "statement": "unverified claim",
         "boundary_type": "observation", "evidence_tier_attempted": 2, "promotion_attempts": 1},
        {"id": "C-002", "status": "PROVEN", "statement": "has evidence claim",
         "boundary_type": "observation", "evidence_tier_attempted": 2, "promotion_attempts": 1},
        {"id": "C-003", "status": "PROVEN", "statement": "blind verified claim",
         "boundary_type": "observation", "evidence_tier_attempted": 3, "promotion_attempts": 1},
        {"id": "C-004", "status": "OPEN", "statement": "not proven",
         "boundary_type": "observation", "evidence_tier_attempted": 0, "promotion_attempts": 0},
        {"id": "C-005", "status": "REFUTED", "statement": "refuted",
         "boundary_type": "observation", "evidence_tier_attempted": 1, "promotion_attempts": 0},
    ]
    _write_claim_register(ws, claims)

    _write_index(ws, [
        ("F001", "PROVEN", "C-001", "plain proven, no verifier"),
        ("F002", "VERIFIED-BY-W-C100-test", "C-002", "verifier worked, not BLIND"),
        ("F003", "VERIFIED-BY-W01 (kong-redteam BLIND)", "C-003", "blind verified"),
    ])

    result = alp.audit_workspace(ws)

    # Only PROVEN claims should appear (3), not OPEN or REFUTED
    assert result["total_proven"] == 3, f"expected 3 PROVEN, got {result['total_proven']}"

    by_cat = {e["category"] for e in result["entries"]}
    assert by_cat == {"unverified", "has-evidence-no-signoff", "verified"}, \
        f"expected all 3 categories, got {by_cat}"

    # Check each claim landed in the right bucket
    by_id = {e["claim_id"]: e["category"] for e in result["entries"]}
    assert by_id["C-001"] == "unverified", "C-001 plain PROVEN → unverified"
    assert by_id["C-002"] == "has-evidence-no-signoff", "C-002 VERIFIED-BY → has-evidence-no-signoff"
    assert by_id["C-003"] == "verified", "C-003 BLIND → verified"

    # Summary counts
    summary = result["summary"]
    assert summary["verified"] == 1
    assert summary["has-evidence-no-signoff"] == 1
    assert summary["unverified"] == 1


# ---------- Test 2: empty workspace ----------

def test_empty_workspace_no_crash(tmp_path):
    """Empty workspace (no claim-register.yaml) → empty result, no crash."""
    ws = tmp_path / "ws-empty"
    ws.mkdir()

    result = alp.audit_workspace(ws)

    assert result["total_proven"] == 0
    assert result["entries"] == []
    assert result["summary"]["verified"] == 0
    assert result["summary"]["unverified"] == 0
    assert result["summary"]["has-evidence-no-signoff"] == 0


# ---------- Test 3: no _INDEX.md → all unverified ----------

def test_no_index_all_unverified(tmp_path):
    """No facts/_INDEX.md → all PROVEN claims classified as unverified."""
    ws = tmp_path / "ws-noindex"
    ws.mkdir()

    claims = [
        {"id": "C-101", "status": "PROVEN", "statement": "claim A",
         "boundary_type": "observation", "evidence_tier_attempted": 2, "promotion_attempts": 1},
        {"id": "C-102", "status": "PROVEN", "statement": "claim B",
         "boundary_type": "observation", "evidence_tier_attempted": 2, "promotion_attempts": 1},
    ]
    _write_claim_register(ws, claims)
    # No facts/_INDEX.md created

    result = alp.audit_workspace(ws)

    assert result["total_proven"] == 2
    assert all(e["category"] == "unverified" for e in result["entries"]), \
        "without _INDEX, all PROVEN should be unverified"
    assert result["summary"]["unverified"] == 2
    assert result["summary"]["verified"] == 0


# ---------- Test 4: multiple facts per claim ----------

def test_multiple_facts_one_claim_highest_wins(tmp_path):
    """If a claim has multiple facts, best verification wins (BLIND > VERIFIED-BY > PROVEN)."""
    ws = tmp_path / "ws-multi"
    ws.mkdir()

    claims = [
        {"id": "C-201", "status": "PROVEN", "statement": "multi-fact claim",
         "boundary_type": "observation", "evidence_tier_attempted": 3, "promotion_attempts": 1},
    ]
    _write_claim_register(ws, claims)

    _write_index(ws, [
        ("F010", "PROVEN", "C-201", "plain proven fact"),
        ("F011", "VERIFIED-BY-W-C201-verifier", "C-201", "verifier checked"),
        ("F012", "VERIFIED-BY-W02 (kong-redteam BLIND)", "C-201", "blind verified"),
    ])

    result = alp.audit_workspace(ws)

    assert result["total_proven"] == 1
    assert result["entries"][0]["category"] == "verified", \
        "claim with BLIND fact should be verified even if other facts are plain PROVEN"


# ---------- Test 5: JSON output format ----------

def test_json_output(tmp_path):
    """Audit produces valid JSON output file."""
    ws = tmp_path / "ws-json"
    ws.mkdir()

    claims = [
        {"id": "C-301", "status": "PROVEN", "statement": "test",
         "boundary_type": "observation", "evidence_tier_attempted": 1, "promotion_attempts": 1},
    ]
    _write_claim_register(ws, claims)
    _write_index(ws, [
        ("F301", "PROVEN", "C-301", "test fact"),
    ])

    out_path = tmp_path / "audit-test.json"
    alp.run_audit(ws, output=str(out_path))

    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert "total_proven" in data
    assert "summary" in data
    assert "entries" in data
    assert data["total_proven"] == 1
