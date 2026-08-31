# -*- coding: utf-8 -*-
"""tests/test_migrate_facts_809.py - #809 zero-contamination property tests."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import migrate_facts


def _mk_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "bins").mkdir()
    (ws / "runs").mkdir()
    (ws / "bins" / "sample.bin").write_bytes(b"MZ sample-A-bytes")
    (ws / "facts" / "F001.md").write_text(
        "---\n"
        "id: F001\n"
        "claim: crash in worker thread\n"
        "claim_id: C-001\n"
        "status: PARTIALLY-VERIFIED\n"
        "provenance:\n"
        "  - role: artifact\n"
        "    path: bins/sample.bin\n"
        "---\n"
        "body describing sample A behavior only.\n",
        encoding="utf-8")
    return ws


def _map(tmp_path, sha):
    m = {"sample_sha256": sha,
         "facts": {"F001": {
             "slug": "sample-overview",
             "title": "Curated Title A",
             "source": "static-decompile",
             "provenance_override": [["artifact", "bins/sample.bin", None]],
         }}}
    p = tmp_path / "map.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    return str(p)


def _ledger_rows(ws):
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return []
    rows = []
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def test_map_inert_on_sample_mismatch(tmp_path):
    ws = _mk_ws(tmp_path)
    mp = _map(tmp_path, "0" * 64)
    r = migrate_facts.migrate_workspace(ws, map_path=mp)
    assert r["errors"] == []
    assert any("INERT" in w for w in r["warnings"]), r["warnings"]
    fm, _b, _e = migrate_facts.parse_frontmatter(
        (ws / "facts" / "F001.md").read_text(encoding="utf-8"))
    assert fm["title"] != "Curated Title A"
    assert fm["source"] == "inference"
    rows = _ledger_rows(ws)
    assert any(r2.get("action") == "env_incident"
               and "INERT" in str(r2.get("detail")) for r2 in rows)


def test_map_applies_on_fingerprint_match(tmp_path):
    ws = _mk_ws(tmp_path)
    sha = migrate_facts._workspace_sample_sha256(ws)
    mp = _map(tmp_path, sha)
    r = migrate_facts.migrate_workspace(ws, map_path=mp)
    assert r["errors"] == []
    fm, _b, _e = migrate_facts.parse_frontmatter(
        (ws / "facts" / "F001.md").read_text(encoding="utf-8"))
    assert fm["title"] == "Curated Title A"
    assert fm["source"] == "static-decompile"
    idx = (ws / "facts" / "_INDEX.md").read_text(encoding="utf-8")
    assert idx.startswith("# Facts Index\n")
    assert "865e8eb4" not in idx


def test_no_map_conservative(tmp_path):
    ws = _mk_ws(tmp_path)
    r = migrate_facts.migrate_workspace(ws)
    assert r["errors"] == []
    fm, _b, _e = migrate_facts.parse_frontmatter(
        (ws / "facts" / "F001.md").read_text(encoding="utf-8"))
    assert fm["source"] == "inference"
    assert any("inference" in w for w in r["warnings"])
    assert not any("INERT" in w for w in r["warnings"])


def test_malformed_map_fail_closed(tmp_path):
    ws = _mk_ws(tmp_path)
    mp = tmp_path / "bad.json"
    mp.write_text("{ broken json", encoding="utf-8")
    rc = migrate_facts.main([str(ws), "--map", str(mp)])
    assert rc == 1
    body = (ws / "facts" / "F001.md").read_text(encoding="utf-8")
    assert body.startswith("---\nid: F001\n")
    r = migrate_facts.migrate_workspace(ws, map_path=str(mp))
    assert any("unreadable/malformed" in e for e in r["errors"])


def test_rerun_idempotent(tmp_path):
    ws = _mk_ws(tmp_path)
    sha = migrate_facts._workspace_sample_sha256(ws)
    mp = _map(tmp_path, sha)
    r1 = migrate_facts.migrate_workspace(ws, map_path=mp)
    assert r1["errors"] == []
    assert len(r1["migrated"]) == 1
    r2 = migrate_facts.migrate_workspace(ws, map_path=mp)
    assert r2["migrated"] == []
