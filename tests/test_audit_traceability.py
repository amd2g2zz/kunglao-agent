# -*- coding: utf-8 -*-
"""tests/test_audit_traceability.py — P5 issue #26: trace the 46 fake PROVEN via the index.

RED tests for the index-traceability dimension of audit_legacy_proven.

Covers:
  RED1: PROVEN fact provenance cites index eid + hash matches → has-raw-evidence
  RED2: PROVEN fact cites derived summary.json (not in index) → derivation-only
  RED3: PROVEN fact has no provenance or path doesn't exist → unverifiable
  RED4: empty workspace doesn't crash
"""
from __future__ import annotations

import hashlib
import json
import textwrap
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
SCRIPTS = ROOT / "scripts"
sys_path_added = False
# #340: audit_legacy_proven lives in tools/auxiliary/, build_evidence_index
# in tools/pipelines/ — both are needed for this module's imports.
for _sub in ("auxiliary", "pipelines"):
    if str(TOOLS / _sub) not in __import__("sys").path:
        __import__("sys").path.insert(0, str(TOOLS / _sub))
        sys_path_added = True

import audit_legacy_proven as alp


# ---------- helpers ----------

def _write(p: Path, content: bytes | str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _build_index(ws: Path) -> dict:
    """Use P1 builder to create evidence/_index.json in ws."""
    import build_evidence_index as bei
    return bei.build_and_write(ws)


def _write_claim_register(ws: Path, claims: list[dict]) -> None:
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


def _write_fact(ws: Path, name: str, frontmatter_extras: str = "") -> Path:
    """Write a minimal fact file with YAML frontmatter."""
    facts = ws / "facts"
    facts.mkdir(exist_ok=True)
    f = facts / f"{name}.md"
    f.write_text(
        f"---\nid: {name}\nstatus: PROVEN\n{frontmatter_extras}\n---\n\nConclusion.\n",
        encoding="utf-8",
    )
    return f


# =====================================================================
# RED1: provenance cites index eid + hash matches → has-raw-evidence
# =====================================================================

def test_traceability_has_raw_evidence(tmp_path):
    """PROVEN fact whose provenance cites a raw evidence path that's in the index
    with matching hash → has-raw-evidence."""
    ws = tmp_path / "ws-raw"
    ws.mkdir()

    # Create raw evidence
    raw = b"capture line1\ncapture line2\n"
    _write(ws / "evidence" / "x64dbg-c206-capture.txt", raw)

    # Build evidence index
    _build_index(ws)
    idx = json.loads((ws / "evidence" / "_index.json").read_text("utf-8"))
    entry = idx["entries"][0]

    # Write claim + fact with provenance citing the raw evidence
    _write_claim_register(ws, [
        {"id": "C-001", "status": "PROVEN", "statement": "test raw",
         "boundary_type": "observation", "evidence_tier_attempted": 2, "promotion_attempts": 1},
    ])
    _write_index(ws, [("F001", "PROVEN", "C-001", "fact with raw provenance")])

    fact_provenance = textwrap.dedent(f"""\
        provenance:
          - path: {entry["path"]}
        """)
    _write_fact(ws, "F001", frontmatter_extras=fact_provenance)

    result = alp.audit_workspace(ws)

    assert result["total_proven"] == 1
    e = result["entries"][0]
    assert e["index_traceability"] == "has-raw-evidence", \
        f"fact citing index path with matching hash should be has-raw-evidence, got {e['index_traceability']}"


# =====================================================================
# RED2: provenance cites derived summary.json (not in index) → derivation-only
# =====================================================================

def test_traceability_derivation_only(tmp_path):
    """PROVEN fact whose provenance only cites derived summary.json (not in index)
    → derivation-only."""
    ws = tmp_path / "ws-derived"
    ws.mkdir()

    # Create raw + derived evidence
    _write(ws / "evidence" / "x64dbg-capture.txt", "raw capture\n")
    _write(ws / "analysis_artifacts" / "vm_runtime" / "summary.json", '{"net": 0}')

    # Build evidence index (summary.json excluded as derivation)
    _build_index(ws)

    _write_claim_register(ws, [
        {"id": "C-002", "status": "PROVEN", "statement": "test derived",
         "boundary_type": "observation", "evidence_tier_attempted": 2, "promotion_attempts": 1},
    ])
    _write_index(ws, [("F002", "PROVEN", "C-002", "fact citing derived")])

    fact_provenance = textwrap.dedent("""\
        provenance:
          - path: analysis_artifacts/vm_runtime/summary.json
        """)
    _write_fact(ws, "F002", frontmatter_extras=fact_provenance)

    result = alp.audit_workspace(ws)

    assert result["total_proven"] == 1
    e = result["entries"][0]
    assert e["index_traceability"] == "derivation-only", \
        f"fact citing only derived should be derivation-only, got {e['index_traceability']}"


# =====================================================================
# RED3a: no provenance at all → unverifiable
# =====================================================================

def test_traceability_no_provenance_unverifiable(tmp_path):
    """PROVEN fact with no provenance block → unverifiable."""
    ws = tmp_path / "ws-noprovn"
    ws.mkdir()

    _write(ws / "evidence" / "capture.txt", "raw\n")
    _build_index(ws)

    _write_claim_register(ws, [
        {"id": "C-003", "status": "PROVEN", "statement": "no provenance",
         "boundary_type": "observation", "evidence_tier_attempted": 2, "promotion_attempts": 1},
    ])
    _write_index(ws, [("F003", "PROVEN", "C-003", "no provenance")])

    # Fact file with no provenance field
    _write_fact(ws, "F003")

    result = alp.audit_workspace(ws)

    e = result["entries"][0]
    assert e["index_traceability"] == "unverifiable", \
        f"fact with no provenance should be unverifiable, got {e['index_traceability']}"


# =====================================================================
# RED3b: fact file doesn't exist → unverifiable
# =====================================================================

def test_traceability_missing_fact_file_unverifiable(tmp_path):
    """PROVEN claim whose fact file doesn't exist on disk → unverifiable."""
    ws = tmp_path / "ws-nofile"
    ws.mkdir()

    _write(ws / "evidence" / "capture.txt", "raw\n")
    _build_index(ws)

    _write_claim_register(ws, [
        {"id": "C-004", "status": "PROVEN", "statement": "missing fact file",
         "boundary_type": "observation", "evidence_tier_attempted": 2, "promotion_attempts": 1},
    ])
    _write_index(ws, [("F004", "PROVEN", "C-004", "fact file missing")])

    # Don't create the fact file
    result = alp.audit_workspace(ws)

    e = result["entries"][0]
    assert e["index_traceability"] == "unverifiable"


# =====================================================================
# RED4: empty workspace doesn't crash
# =====================================================================

def test_traceability_empty_workspace(tmp_path):
    """Empty workspace (no claim-register.yaml) → empty result, no crash."""
    ws = tmp_path / "ws-empty-trace"
    ws.mkdir()

    result = alp.audit_workspace(ws)

    assert result["total_proven"] == 0
    assert result["traceability_summary"]["has-raw-evidence"] == 0
    assert result["traceability_summary"]["derivation-only"] == 0
    assert result["traceability_summary"]["unverifiable"] == 0


# =====================================================================
# Edge: no evidence index → all unverifiable (can't trace without index)
# =====================================================================

def test_traceability_no_index_all_unverifiable(tmp_path):
    """Workspace with no evidence/_index.json and no evidence dirs → unverifiable."""
    ws = tmp_path / "ws-noindex"
    ws.mkdir()

    _write_claim_register(ws, [
        {"id": "C-005", "status": "PROVEN", "statement": "test",
         "boundary_type": "observation", "evidence_tier_attempted": 2, "promotion_attempts": 1},
    ])
    _write_index(ws, [("F005", "PROVEN", "C-005", "test")])

    fact_provenance = textwrap.dedent("""\
        provenance:
          - path: evidence/some-file.txt
        """)
    _write_fact(ws, "F005", frontmatter_extras=fact_provenance)

    result = alp.audit_workspace(ws)

    e = result["entries"][0]
    assert e["index_traceability"] == "unverifiable", \
        "without evidence index, nothing is traceable"


# =====================================================================
# Edge: mixed workspace — multiple claims different traceability
# =====================================================================

def test_traceability_mixed(tmp_path):
    """Workspace with 3 PROVEN claims: one has-raw, one derivation-only, one unverifiable."""
    ws = tmp_path / "ws-mixed-trace"
    ws.mkdir()

    # Raw evidence
    _write(ws / "evidence" / "capture.txt", "raw capture\n")
    # Derived evidence
    _write(ws / "analysis_artifacts" / "vm_runtime" / "summary.json", '{"net":0}')

    _build_index(ws)
    idx = json.loads((ws / "evidence" / "_index.json").read_text("utf-8"))
    raw_entry = idx["entries"][0]

    _write_claim_register(ws, [
        {"id": "C-101", "status": "PROVEN", "statement": "has raw",
         "boundary_type": "observation", "evidence_tier_attempted": 2, "promotion_attempts": 1},
        {"id": "C-102", "status": "PROVEN", "statement": "derived only",
         "boundary_type": "observation", "evidence_tier_attempted": 2, "promotion_attempts": 1},
        {"id": "C-103", "status": "PROVEN", "statement": "no provenance",
         "boundary_type": "observation", "evidence_tier_attempted": 2, "promotion_attempts": 1},
    ])
    _write_index(ws, [
        ("F101", "PROVEN", "C-101", "raw-backed"),
        ("F102", "PROVEN", "C-102", "derived-backed"),
        ("F103", "PROVEN", "C-103", "no provenance"),
    ])

    # F101: cites raw evidence in index
    _write_fact(ws, "F101", frontmatter_extras=f"provenance:\n  - path: {raw_entry['path']}\n")
    # F102: cites only derived
    _write_fact(ws, "F102", frontmatter_extras="provenance:\n  - path: analysis_artifacts/vm_runtime/summary.json\n")
    # F103: no provenance
    _write_fact(ws, "F103")

    result = alp.audit_workspace(ws)

    by_id = {e["claim_id"]: e["index_traceability"] for e in result["entries"]}
    assert by_id["C-101"] == "has-raw-evidence"
    assert by_id["C-102"] == "derivation-only"
    assert by_id["C-103"] == "unverifiable"

    ts = result["traceability_summary"]
    assert ts["has-raw-evidence"] == 1
    assert ts["derivation-only"] == 1
    assert ts["unverifiable"] == 1


# =====================================================================
# Edge: hash mismatch → not has-raw-evidence (tampered evidence)
# =====================================================================

def test_traceability_hash_mismatch_not_raw(tmp_path):
    """Fact cites index path but file was tampered (hash mismatch) → derivation-only."""
    ws = tmp_path / "ws-tamper"
    ws.mkdir()

    _write(ws / "evidence" / "capture.txt", "original content\n")
    _build_index(ws)
    idx = json.loads((ws / "evidence" / "_index.json").read_text("utf-8"))
    entry = idx["entries"][0]

    # Tamper the file after index was built
    (ws / entry["path"]).write_bytes(b"TAMPERED")

    _write_claim_register(ws, [
        {"id": "C-201", "status": "PROVEN", "statement": "tampered",
         "boundary_type": "observation", "evidence_tier_attempted": 2, "promotion_attempts": 1},
    ])
    _write_index(ws, [("F201", "PROVEN", "C-201", "tampered evidence")])

    _write_fact(ws, "F201", frontmatter_extras=f"provenance:\n  - path: {entry['path']}\n")

    result = alp.audit_workspace(ws)

    e = result["entries"][0]
    assert e["index_traceability"] != "has-raw-evidence", \
        "hash mismatch should prevent has-raw-evidence classification"
