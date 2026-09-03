# -*- coding: utf-8 -*-
"""TDD RED — apkid pre-scan at android intake (#669).

apkid_scanner.py wraps `apkid scan --json <apk>` and writes a fail-open
evidence file. The output feeds the hypothesis seeder (#662 extension) so
apkid tags become pq-family competitor candidates — the "system optimum"
wire per the user's directive.

Spec: openspec/changes/issue-669-apkid-prescan/specs/apkid-prescan/spec.md
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


_HERE = Path(__file__).parent
SCRIPTS = _HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))


# ---------------------------------------------------------------------------
# Helpers — synthetic apkid JSON (the real binary is rarely installed in CI)
# ---------------------------------------------------------------------------

def _synthetic_apkid_json() -> str:
    """Two findings: Bangcle (packer) + R8 (compiler). apkid's real shape
    is `{"results": {"<apk>": {"findings": [...]}}, "apkid_version": "..."}`
    — we synthesize that shape directly."""
    return json.dumps({
        "apkid_version": "2.1.5",
        "results": {
            "test.apk": {
                "findings": [
                    {
                        "rule": "Bangcle",
                        "category": "packer",
                        "description": "string encryption + dynamic DEX loading",
                        "matched_files": ["classes.dex"],
                    },
                    {
                        "rule": "R8",
                        "category": "compiler",
                        "description": "R8 minifier",
                        "matched_files": ["classes.dex"],
                    },
                ],
            },
        },
    })


# ---------------------------------------------------------------------------
# RED1 — happy-path parse -> evidence/apkid.json with status:ok + summary rollup
# ---------------------------------------------------------------------------

def test_red1_happy_path_writes_evidence_with_status_ok(tmp_path, monkeypatch):
    """synthetic apkid JSON on PATH -> evidence/apkid.json with status:ok,
    summary rollup (Bangcle -> packer, R8 -> compiler), total 2."""
    from apkid_scanner import run
    monkeypatch.setattr("shutil.which",
                        lambda n: "/usr/bin/apkid" if n == "apkid" else None)

    fake_apk = tmp_path / "test.apk"
    fake_apk.write_bytes(b"PK\x03\x04")
    def fake_run(args, **kw):
        if "--version" in args:
            return subprocess.CompletedProcess(args, 0, stdout="apkid 2.1.5", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout=_synthetic_apkid_json(), stderr="")
    monkeypatch.setattr("subprocess.run", fake_run)

    rc = run(workspace=tmp_path, apk_path=str(fake_apk))
    assert rc == 0, f"expected rc=0 on happy path, got {rc}"

    evidence = tmp_path / "evidence" / "apkid.json"
    assert evidence.exists(), "evidence/apkid.json must be written"
    data = json.loads(evidence.read_text(encoding="utf-8"))
    assert data["status"] == "ok", data
    assert data["tool"] == "apkid"
    assert data["version"] == "2.1.5"
    assert data["target"] == str(fake_apk)
    assert "scanned_at" in data
    assert data["summary"]["packer"] == ["Bangcle"], data
    assert data["summary"]["compiler"] == ["R8"], data
    assert data["summary"]["total"] == 2, data
    assert len(data["findings"]) == 2


# ---------------------------------------------------------------------------
# RED2 — apkid binary missing -> status:unavailable, exit 0
# ---------------------------------------------------------------------------

def test_red2_missing_binary_writes_status_unavailable(tmp_path, monkeypatch):
    """apkid not on PATH -> evidence/apkid.json status:unavailable, rc=0
    (intake continues, fail-open)."""
    from apkid_scanner import run
    monkeypatch.setattr("shutil.which", lambda n: None)

    fake_apk = tmp_path / "test.apk"
    fake_apk.write_bytes(b"PK\x03\x04")
    rc = run(workspace=tmp_path, apk_path=str(fake_apk))
    assert rc == 0, f"expected rc=0 (fail-open), got {rc}"

    evidence = tmp_path / "evidence" / "apkid.json"
    assert evidence.exists()
    data = json.loads(evidence.read_text(encoding="utf-8"))
    assert data["status"] == "unavailable", data
    assert "reason" in data and data["reason"], data
    assert data["findings"] == [], data
    assert data["summary"]["total"] == 0


# ---------------------------------------------------------------------------
# RED3 — non-APK input -> status:error, exit 1
# ---------------------------------------------------------------------------

def test_red3_non_apk_input_writes_status_error(tmp_path, monkeypatch):
    """target is .jar or .dex -> status:error, rc=1 (still no crash)."""
    from apkid_scanner import run
    monkeypatch.setattr("shutil.which",
                        lambda n: "/usr/bin/apkid" if n == "apkid" else None)
    monkeypatch.setattr("subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], 0, stdout="apkid 2.1.5", stderr=""))

    fake_jar = tmp_path / "test.jar"
    fake_jar.write_bytes(b"PK\x03\x04")
    rc = run(workspace=tmp_path, apk_path=str(fake_jar))
    assert rc == 1, f"expected rc=1 on non-APK, got {rc}"

    evidence = tmp_path / "evidence" / "apkid.json"
    assert evidence.exists()
    data = json.loads(evidence.read_text(encoding="utf-8"))
    assert data["status"] == "error", data
    assert "not" in data["reason"].lower() or "apk" in data["reason"].lower(), data


# ---------------------------------------------------------------------------
# RED4 — schema shape: all top-level + summary keys always populated
# ---------------------------------------------------------------------------

def test_red4_schema_shape_always_populated(tmp_path, monkeypatch):
    """All summary keys (packer, compiler, obfuscator, anti_vm, anti_debug,
    total) MUST always be present even when apkid returns zero findings."""
    from apkid_scanner import run
    monkeypatch.setattr("shutil.which",
                        lambda n: "/usr/bin/apkid" if n == "apkid" else None)
    empty_json = json.dumps({"apkid_version": "2.1.5",
                             "results": {"x.apk": {"findings": []}}})
    monkeypatch.setattr("subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess(
            a[0], 0,
            stdout="apkid 2.1.5" if "--version" in a[0] else empty_json,
            stderr=""))

    fake_apk = tmp_path / "test.apk"
    fake_apk.write_bytes(b"PK\x03\x04")
    rc = run(workspace=tmp_path, apk_path=str(fake_apk))
    assert rc == 0

    data = json.loads((tmp_path / "evidence" / "apkid.json").read_text(encoding="utf-8"))
    for k in ("tool", "version", "target", "scanned_at", "findings",
              "summary", "status", "reason"):
        assert k in data, f"missing top-level key: {k} in {data}"
    for k in ("packer", "compiler", "obfuscator", "anti_vm", "anti_debug", "total"):
        assert k in data["summary"], f"missing summary.{k} in {data}"
    assert data["summary"]["packer"] == []
    assert data["summary"]["compiler"] == []
    assert data["summary"]["obfuscator"] == []
    assert data["summary"]["anti_vm"] == []
    assert data["summary"]["anti_debug"] == []
    assert data["summary"]["total"] == 0


# ---------------------------------------------------------------------------
# RED5 — toolchain FIXES + _STATIC_NEXT_ACTIONS contain apkid
# ---------------------------------------------------------------------------

def test_red5_toolchain_registers_apkid():
    """scripts/toolchain.py exposes apkid in FIXES dict + _STATIC_NEXT_ACTIONS."""
    import toolchain
    assert "apkid" in toolchain.FIXES, f"FIXES keys: {sorted(toolchain.FIXES)}"
    assert "apkid" in toolchain._STATIC_NEXT_ACTIONS, \
        f"_STATIC_NEXT_ACTIONS keys: {sorted(toolchain._STATIC_NEXT_ACTIONS)}"
    action = toolchain._STATIC_NEXT_ACTIONS["apkid"]
    assert action.action == "install"
    assert action.command and "apkid" in action.command


# ---------------------------------------------------------------------------
# RED6 — hypothesis seeder extends competitor_groups from apkid output
# (the "system optimum" wire: apkid tags feed the existing pipe)
# ---------------------------------------------------------------------------

def test_red6_hypothesis_seeder_appends_apkid_candidates(tmp_path):
    """When evidence/apkid.json exists with packer findings AND a PQ
    mentions 'packer', the seeded hypothesis carries the apkid candidate."""
    from hypothesis_seeder import seed_from_task_spec, seed_apkid_candidates
    from hypothesis_store import HypothesisStore

    (tmp_path / "task_spec.yaml").write_text(
        "primary_questions:\n"
        "  - id: Q-packer-family\n"
        "    question: which packer is this APK wrapped with\n",
        encoding="utf-8",
    )
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "apkid.json").write_text(json.dumps({
        "tool": "apkid",
        "version": "2.1.5",
        "target": "test.apk",
        "scanned_at": "2026-08-25T00:00:00Z",
        "findings": [
            {"rule": "Bangcle", "category": "packer",
             "description": "x", "matched_files": ["classes.dex"]},
        ],
        "summary": {"packer": ["Bangcle"], "compiler": [], "obfuscator": [],
                    "anti_vm": [], "anti_debug": [], "total": 1},
        "status": "ok",
        "reason": "",
    }), encoding="utf-8")

    seed_from_task_spec(tmp_path)
    n = seed_apkid_candidates(tmp_path)
    assert n == 1, f"expected 1 candidate appended, got {n}"

    store = HypothesisStore(tmp_path / "hypotheses")
    hyp = store.get("H-001")
    assert "apkid:packer:Bangcle" in hyp.candidates, hyp.candidates


def test_red6b_hypothesis_seeder_no_apkid_file_is_noop(tmp_path):
    """When evidence/apkid.json is absent, seed_apkid_candidates returns 0
    and does not raise (fail-open per design D6)."""
    from hypothesis_seeder import seed_from_task_spec, seed_apkid_candidates
    (tmp_path / "task_spec.yaml").write_text(
        "primary_questions:\n  - id: Q1\n    question: what is in this apk\n",
        encoding="utf-8",
    )
    seed_from_task_spec(tmp_path)
    n = seed_apkid_candidates(tmp_path)
    assert n == 0