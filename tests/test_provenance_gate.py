# -*- coding: utf-8 -*-
"""RED tests for provenance_gate (P2, PRD evidence-integrity-icd203 issue #24).

TDD: these tests import provenance_gate which does NOT exist yet → RED.
Implementation in scripts/provenance_gate.py makes them GREEN.

Covers:
  RED1: provenance cites derived summary.json (not in index) → reject
  RED2: provenance cites non-existent eid → reject
  RED3: provenance cites index eid but file hash mismatch → reject
  RED4: provenance cites index eid + hash matches → pass

Additional edges: no provenance field, multiple refs, path-based ref,
all-refs-must-pass, missing index file.
"""
from __future__ import annotations

import hashlib
import json
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TOOLS = ROOT / "tools"
sys_path_added = False
if str(TOOLS) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(TOOLS))
    sys_path_added = True


# ---------- helpers ----------

def _write(p: Path, content: bytes | str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _build_index(ws: Path) -> Path:
    """Use the P1 builder to create evidence/_index.json in ws."""
    import build_evidence_index as bei
    bei.build_and_write(ws)
    return ws / "evidence" / "_index.json"


def _fixture_ws(tmp_path: Path) -> Path:
    """Create a workspace with raw + derived evidence, then build index."""
    ws = tmp_path / "ws"
    # raw evidence (will be in index)
    _write(ws / "evidence" / "x64dbg-c206-capture.txt", "capture line1\ncapture line2\n")
    _write(ws / "analysis_artifacts" / "vm_runtime" / "full_trace.txt", "TRACE " * 100)
    _write(ws / "evidence" / "yara-packer-C003.json", '{"packer": "upx"}')
    # derived evidence (NOT in index)
    _write(ws / "analysis_artifacts" / "vm_runtime" / "summary.json", '{"net": 0}')
    _write(ws / "evidence" / "verdict.json", '{"verdict": "malware"}')
    _build_index(ws)
    return ws


def _write_fact(ws: Path, name: str, provenance_block: str) -> Path:
    """Write a fact file with a provenance YAML block."""
    facts = ws / "facts"
    facts.mkdir(exist_ok=True)
    f = facts / f"{name}.md"
    f.write_text(provenance_block, encoding="utf-8")
    return f


# A fact whose provenance cites a raw evidence by eid
_FACT_CITES_EID = textwrap.dedent("""\
    # F-TEST-01

    Some conclusion about the sample.

    ```yaml
    provenance:
      - eid: {eid}
    ```
    """)


_FACT_CITES_PATH = textwrap.dedent("""\
    # F-TEST-02

    Some conclusion.

    ```yaml
    provenance:
      - path: {path}
    ```
    """)


_FACT_CITES_DERIVED = textwrap.dedent("""\
    # F-TEST-03

    Conclusion based on summary.

    ```yaml
    provenance:
      - path: analysis_artifacts/vm_runtime/summary.json
    ```
    """)


_FACT_CITES_NONEXISTENT_EID = textwrap.dedent("""\
    # F-TEST-04

    ```yaml
    provenance:
      - eid: E999
    ```
    """)


_FACT_NO_PROVENANCE = textwrap.dedent("""\
    # F-TEST-05

    No provenance at all.
    """)


_FACT_CITES_MULTIPLE = textwrap.dedent("""\
    # F-TEST-06

    ```yaml
    provenance:
      - eid: {eid1}
      - eid: {eid2}
    ```
    """)


# =====================================================================
# RED4: provenance cites valid index eid + hash matches → pass
# =====================================================================

def test_provenance_cites_valid_eid_passes(tmp_path):
    """RED4: fact cites eid that's in index, file hash matches → ok."""
    ws = _fixture_ws(tmp_path)
    idx = json.loads((ws / "evidence" / "_index.json").read_text("utf-8"))
    # pick the first entry
    entry = idx["entries"][0]
    fact = _write_fact(ws, "F-test-valid", _FACT_CITES_EID.format(eid=entry["eid"]))
    from provenance_gate import check_provenance_gate
    ok, reason = check_provenance_gate(fact, ws)
    assert ok, f"valid eid should pass: {reason}"


# =====================================================================
# RED1: provenance cites derived summary.json (not in index) → reject
# =====================================================================

def test_provenance_cites_derived_rejected(tmp_path):
    """RED1: fact cites summary.json (derived, not in index) → reject."""
    ws = _fixture_ws(tmp_path)
    fact = _write_fact(ws, "F-test-derived", _FACT_CITES_DERIVED)
    from provenance_gate import check_provenance_gate
    ok, reason = check_provenance_gate(fact, ws)
    assert not ok, "derived summary.json must be rejected"
    assert "summary.json" in reason or "not in index" in reason or "derived" in reason.lower() or "index" in reason.lower()


# =====================================================================
# RED2: provenance cites non-existent eid → reject
# =====================================================================

def test_provenance_cites_nonexistent_eid_rejected(tmp_path):
    """RED2: fact cites eid E999 that doesn't exist in index → reject."""
    ws = _fixture_ws(tmp_path)
    fact = _write_fact(ws, "F-test-noexist", _FACT_CITES_NONEXISTENT_EID)
    from provenance_gate import check_provenance_gate
    ok, reason = check_provenance_gate(fact, ws)
    assert not ok, "non-existent eid must be rejected"
    assert "E999" in reason or "not found" in reason.lower() or "not in index" in reason.lower()


# =====================================================================
# RED3: provenance cites index eid but file hash mismatch → reject
# =====================================================================

def test_provenance_cites_eid_hash_mismatch_rejected(tmp_path):
    """RED3: fact cites valid eid but file on disk was tampered → reject."""
    ws = _fixture_ws(tmp_path)
    idx = json.loads((ws / "evidence" / "_index.json").read_text("utf-8"))
    entry = idx["entries"][0]
    # tamper the file
    target = ws / entry["path"]
    target.write_bytes(b"TAMPERED CONTENT")
    fact = _write_fact(ws, "F-test-tamper", _FACT_CITES_EID.format(eid=entry["eid"]))
    from provenance_gate import check_provenance_gate
    ok, reason = check_provenance_gate(fact, ws)
    assert not ok, "hash mismatch must be rejected"
    assert "hash" in reason.lower() or "mismatch" in reason.lower() or "sha256" in reason.lower()


# =====================================================================
# Edge: no provenance field → reject
# =====================================================================

def test_no_provenance_rejected(tmp_path):
    """Fact with no provenance block → reject."""
    ws = _fixture_ws(tmp_path)
    fact = _write_fact(ws, "F-test-noprovn", _FACT_NO_PROVENANCE)
    from provenance_gate import check_provenance_gate
    ok, reason = check_provenance_gate(fact, ws)
    assert not ok, "no provenance must be rejected"
    assert "provenance" in reason.lower() or "no evidence" in reason.lower()


# =====================================================================
# Edge: path-based ref that's in index → pass
# =====================================================================

def test_provenance_cites_valid_path_passes(tmp_path):
    """Fact cites path that's in index → pass."""
    ws = _fixture_ws(tmp_path)
    idx = json.loads((ws / "evidence" / "_index.json").read_text("utf-8"))
    entry = idx["entries"][0]
    fact = _write_fact(ws, "F-test-path", _FACT_CITES_PATH.format(path=entry["path"]))
    from provenance_gate import check_provenance_gate
    ok, reason = check_provenance_gate(fact, ws)
    assert ok, f"valid path ref should pass: {reason}"


# =====================================================================
# Edge: multiple refs, all valid → pass; one invalid → reject
# =====================================================================

def test_multiple_valid_refs_pass(tmp_path):
    """Multiple provenance refs, all in index → pass."""
    ws = _fixture_ws(tmp_path)
    idx = json.loads((ws / "evidence" / "_index.json").read_text("utf-8"))
    e1, e2 = idx["entries"][0], idx["entries"][1]
    fact = _write_fact(ws, "F-test-multi-ok", _FACT_CITES_MULTIPLE.format(eid1=e1["eid"], eid2=e2["eid"]))
    from provenance_gate import check_provenance_gate
    ok, reason = check_provenance_gate(fact, ws)
    assert ok, f"all-valid refs should pass: {reason}"


def test_multiple_refs_one_derived_rejected(tmp_path):
    """Multiple refs, one is derived → reject."""
    ws = _fixture_ws(tmp_path)
    idx = json.loads((ws / "evidence" / "_index.json").read_text("utf-8"))
    e1 = idx["entries"][0]
    body = textwrap.dedent(f"""\
        # F-TEST

        ```yaml
        provenance:
          - eid: {e1["eid"]}
          - path: analysis_artifacts/vm_runtime/summary.json
        ```
        """)
    fact = _write_fact(ws, "F-test-multi-bad", body)
    from provenance_gate import check_provenance_gate
    ok, reason = check_provenance_gate(fact, ws)
    assert not ok, "one derived ref must reject the whole fact"


# =====================================================================
# Edge: no index file → reject with clear reason
# =====================================================================

def test_no_index_file_rejected(tmp_path):
    """Workspace has no evidence/_index.json → reject."""
    ws = tmp_path / "empty-ws"
    ws.mkdir()
    facts = ws / "facts"
    facts.mkdir()
    fact = facts / "F-test.md"
    fact.write_text("# fact\n```yaml\nprovenance:\n  - eid: E001\n```", encoding="utf-8")
    from provenance_gate import check_provenance_gate
    ok, reason = check_provenance_gate(fact, ws)
    assert not ok, "missing index must be rejected"
    assert "index" in reason.lower()


# =====================================================================
# CLI entry (skills-review F5 / issue #196)
# =====================================================================

def test_provenance_gate_cli_exits_nonzero_on_bad_ref(tmp_path):
    """CLI contract: argparse entry, exit 0 = provenance OK, 1 = rejected.
    (skills-review F5: this checker had no CLI — now CI-visible.)"""
    import subprocess
    import sys

    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "evidence").mkdir()
    # Index with a DIFFERENT eid — E999 must be reported as not-found.
    (ws / "evidence" / "_index.json").write_text(
        '{"entries": [{"eid": "E001", "path": "evidence/cap.txt", '
        '"sha256": "deadbeef"}], "schema": "evidence-index/1"}',
        encoding="utf-8",
    )
    fact = ws / "facts" / "F001.md"
    fact.write_text(
        "```yaml\nprovenance:\n  - eid: E999\n```\n", encoding="utf-8"
    )
    r = subprocess.run(
        [sys.executable, "scripts/provenance_gate.py", str(fact), str(ws)],
        capture_output=True, text=True,
    )
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "E999" in (r.stdout + r.stderr)
