# -*- coding: utf-8 -*-
"""tests/test_rlvr_obstacles_461.py — obstacle/1 attribution registry
(issue 461 Phase 1, intervention-based attribution-in-state).

Pins the attribution-evidence contract:
  - schema obstacle/1 over runs/obstacles/OBS-<n>.json: closed kind
    enum, single-line machine-checkable cause (<= 200 chars),
    workspace-relative evidence_path citing an EXISTING intervention
    artifact that carries a probe-execution marker (the blocker
    schema-v2 discipline), verbatim method_family;
  - no verdict semantics: no status field, never an obstacle claim;
  - loud-result fail-open record (named reason, no file, never a
    raise); exclusive-create mint (concurrent producers never
    overwrite); parsed-number id sort (rollover-safe);
  - tolerant structural read; face digest for the state signature;
  - the three canonical failure signatures (missing env entry /
    anti-analysis trigger / encrypted layer) with expected rows;
  - the worker-contract doc carries the intervention protocol;
  - CLI/library share one validation path.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from rlvr import obstacles  # noqa: E402

TS = "2026-09-30T00:00:00Z"

# probe artifacts carry the command + exit code + verbatim output shape
_PROBE_TEXT = (
    "cmd: isolation-probe --variant=clean --probe=env-entry-set\n"
    "rc=0\n"
    "ANDROID_SDK_ROOT=/opt/android-sdk\n")
_PROSE_TEXT = (
    "the tool failed because the environment is not configured "
    "correctly and nothing works, retried several times, still broken")


def _probe_file(ws: Path, name: str = "probe.txt",
                text: str = _PROBE_TEXT) -> str:
    d = ws / "runs" / "probes"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")
    return f"runs/probes/{name}"


def _record(ws, **kw):
    base = dict(kind="missing_env_entry",
                cause="unidbg aborts: ANDROID_SDK_ROOT unset (probe rc=1)",
                evidence_path=_probe_file(ws),
                method_family="replay-harness-verification",
                ts=TS)
    base.update(kw)
    return obstacles.record(ws, **base)


# ---------- schema validation ----------

class TestSchemaValidation:
    def _row(self, ws, **kw):
        base = {
            "schema": "obstacle/1", "id": "OBS-001", "ts": TS,
            "kind": "detection_trigger",
            "cause": "frida attach detected: exit 30s after attach (rc=1)",
            "evidence_path": _probe_file(ws),
            "method_family": "dynamic-trace",
        }
        base.update(kw)
        return base

    def test_minimal_row_valid(self, tmp_path):
        assert obstacles.validate_obstacle(self._row(tmp_path),
                                           tmp_path) == []

    def test_unknown_kind_rejected(self, tmp_path):
        errs = obstacles.validate_obstacle(
            self._row(tmp_path, kind="cosmic_interference"), tmp_path)
        assert any("kind" in e for e in errs)

    @pytest.mark.parametrize("cause,why", [
        ("", "empty"),
        ("   ", "blank"),
        ("line one\nline two", "multiline"),
        ("x" * 201, "over-long"),
    ])
    def test_bad_cause_rejected(self, tmp_path, cause, why):
        errs = obstacles.validate_obstacle(
            self._row(tmp_path, cause=cause), tmp_path)
        assert any("cause" in e for e in errs), why

    @pytest.mark.parametrize("path,why", [
        ("/etc/passwd", "absolute"),
        ("../../etc/passwd", "parent segment"),
        ("runs/../../secrets.txt", "nested parent"),
    ])
    def test_bad_evidence_path_rejected(self, tmp_path, path, why):
        errs = obstacles.validate_obstacle(
            self._row(tmp_path, evidence_path=path), tmp_path)
        assert any("evidence_path" in e for e in errs), why

    def test_missing_artifact_rejected(self, tmp_path):
        errs = obstacles.validate_obstacle(self._row(
            tmp_path, evidence_path="runs/probes/never-written.txt"),
            tmp_path)
        assert any("exist" in e for e in errs)

    def test_artifact_without_probe_marker_rejected(self, tmp_path):
        prose = _probe_file(tmp_path, "prose.txt", _PROSE_TEXT)
        errs = obstacles.validate_obstacle(
            self._row(tmp_path, evidence_path=prose), tmp_path)
        assert any("probe" in e for e in errs)

    def test_empty_method_family_rejected(self, tmp_path):
        errs = obstacles.validate_obstacle(
            self._row(tmp_path, method_family="  "), tmp_path)
        assert any("method_family" in e for e in errs)

    def test_row_has_no_verdict_field(self, tmp_path):
        """Attribution is never a verdict: no status, no dead call."""
        out = _record(tmp_path)
        forbidden = {"status", "verdict", "dead", "terminal"}
        assert not (set(out["row"]) & forbidden)


# ---------- record ----------

class TestRecord:
    def test_minimal_mint(self, tmp_path):
        out = _record(tmp_path)
        assert out["appended"] is True
        p = tmp_path / "runs" / "obstacles" / "OBS-001.json"
        assert p.is_file()
        row = json.loads(p.read_text(encoding="utf-8"))
        assert row["schema"] == "obstacle/1"
        assert row["id"] == "OBS-001"
        assert row["kind"] == "missing_env_entry"
        assert row["method_family"] == "replay-harness-verification"
        assert row["ts"] == TS
        assert row["evidence_path"] == "runs/probes/probe.txt"

    def test_sequential_ids(self, tmp_path):
        _record(tmp_path)
        out2 = _record(tmp_path, evidence_path=_probe_file(
            tmp_path, "p2.txt"))
        assert out2["row"]["id"] == "OBS-002"

    def test_fail_open_named_reason_never_raises(self, tmp_path):
        out = obstacles.record(
            tmp_path, kind="not-a-kind", cause="x",
            evidence_path="runs/probes/none.txt",
            method_family="dynamic-trace", ts=TS)
        assert out["appended"] is False
        assert out.get("reason") or out.get("errors")
        assert not (tmp_path / "runs" / "obstacles").exists() or \
            not list((tmp_path / "runs" / "obstacles").glob("OBS-*.json"))

    def test_optional_join_keys_roundtrip(self, tmp_path):
        out = _record(tmp_path, claim="C-12", dispatch_id="d-3")
        row = json.loads((tmp_path / "runs" / "obstacles" /
                          "OBS-001.json").read_text(encoding="utf-8"))
        assert row["claim"] == "C-12"
        assert row["dispatch_id"] == "d-3"


# ---------- read ----------

class TestRead:
    def test_tolerant_corrupt_row_skipped(self, tmp_path):
        _record(tmp_path)
        (tmp_path / "runs" / "obstacles" / "OBS-002.json").write_text(
            "{not json", encoding="utf-8")
        rows = obstacles.read(tmp_path)
        assert [r["id"] for r in rows] == ["OBS-001"]

    def test_invalid_schema_row_skipped(self, tmp_path):
        _record(tmp_path)
        (tmp_path / "runs" / "obstacles" / "OBS-002.json").write_text(
            json.dumps({"schema": "obstacle/9", "id": "OBS-002"}),
            encoding="utf-8")
        rows = obstacles.read(tmp_path)
        assert [r["id"] for r in rows] == ["OBS-001"]

    def test_parsed_number_sort_rollover_safe(self, tmp_path):
        d = tmp_path / "runs" / "obstacles"
        d.mkdir(parents=True)
        for n in (999, 1000, 1001):
            (d / f"OBS-{n}.json").write_text(json.dumps({
                "schema": "obstacle/1", "id": f"OBS-{n}", "ts": TS,
                "kind": "other", "cause": f"synthetic {n}",
                "evidence_path": "runs/probes/x.txt",
                "method_family": "other"}), encoding="utf-8")
        rows = obstacles.read(tmp_path)
        assert [r["id"] for r in rows] == [
            "OBS-999", "OBS-1000", "OBS-1001"]

    def test_missing_registry_empty(self, tmp_path):
        assert obstacles.read(tmp_path) == []


# ---------- exclusive-create mint ----------

class TestMint:
    def test_exclusive_create_primitive_refuses_existing(self, tmp_path):
        p = tmp_path / "OBS-001.json"
        assert obstacles._exclusive_create(p, b"first") is True
        assert obstacles._exclusive_create(p, b"second") is False
        assert p.read_bytes() == b"first"

    def test_concurrent_records_distinct_ids(self, tmp_path):
        _probe_file(tmp_path, "shared.txt")
        barrier = threading.Barrier(8)
        results: list = []

        def worker(i: int):
            barrier.wait()
            out = _record(
                tmp_path, cause=f"synthetic concurrent failure {i}",
                evidence_path="runs/probes/shared.txt",
                method_family="dynamic-trace")
            results.append(out)

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert all(r["appended"] for r in results)
        ids = sorted(r["row"]["id"] for r in results)
        assert len(set(ids)) == 8
        assert ids == [f"OBS-{n:03d}" for n in range(1, 9)]


# ---------- face digest ----------

class TestFace:
    def test_empty_face(self, tmp_path):
        assert obstacles.face(tmp_path) == {
            "present": False, "count": 0, "kinds": ""}

    def test_two_kinds_canonical_pattern(self, tmp_path):
        _record(tmp_path, kind="detection_trigger",
                method_family="dynamic-trace")
        _record(tmp_path, kind="missing_env_entry",
                method_family="replay-harness-verification")
        face = obstacles.face(tmp_path)
        assert face["present"] is True
        assert face["count"] == 2
        assert face["kinds"] == \
            "detection_trigger=1|missing_env_entry=1"


# ---------- CLI ----------

class TestCLI:
    def test_cli_record_and_face_share_validation(self, tmp_path, capsys):
        rel = _probe_file(tmp_path, "cli.txt")
        rc = obstacles.main([
            "record", str(tmp_path), "--kind", "tool_limit",
            "--cause", "jadx 300s timeout on flattened switch (rc=124)",
            "--evidence-path", rel,
            "--method-family", "static-decompile",
            "--ts", TS])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert out["appended"] is True
        face_rc = obstacles.main(["face", str(tmp_path)])
        face = json.loads(capsys.readouterr().out)
        assert face_rc == 0
        assert face["count"] == 1
        assert face["kinds"] == "tool_limit=1"

    def test_cli_rejects_invalid_without_raising(self, tmp_path, capsys):
        rc = obstacles.main([
            "record", str(tmp_path), "--kind", "bogus",
            "--cause", "x", "--evidence-path", "runs/probes/nope.txt",
            "--method-family", "static-decompile", "--ts", TS])
        out = json.loads(capsys.readouterr().out)
        assert rc == 1
        assert out["appended"] is False


# ---------- three canonical failure signatures (Req 3) ----------

class TestCanonicalFailureSignatures:
    def test_missing_env_entry(self, tmp_path):
        rel = _probe_file(tmp_path, "unidbg-env.txt", (
            "cmd: env -u ANDROID_SDK_ROOT unidbg run.apk\n"
            "rc=1\n"
            "stderr: java.lang.IllegalStateException: SDK dir not set\n"))
        out = _record(
            tmp_path,
            kind="missing_env_entry",
            cause="unidbg aborts: ANDROID_SDK_ROOT unset "
                  "(differential probe rc=1, set-var rerun rc=0)",
            evidence_path=rel,
            method_family="replay-harness-verification")
        assert out["appended"] is True
        row = out["row"]
        assert row["kind"] == "missing_env_entry"
        assert row["method_family"] == "replay-harness-verification"
        assert "\n" not in row["cause"]

    def test_detection_trigger(self, tmp_path):
        rel = _probe_file(tmp_path, "frida-isolation.txt", (
            "cmd: frida -U -f app.nk.target -l probe.js --no-pause\n"
            "rc=1\n"
            "stdout: Process terminated 30s after attach "
            "(ptrace stop observed in both reruns)\n"))
        out = _record(
            tmp_path,
            kind="detection_trigger",
            cause="anti-frida ptrace guard kills process 30s after "
                  "attach (probe rc=1, two reruns identical)",
            evidence_path=rel,
            method_family="dynamic-trace")
        assert out["appended"] is True
        assert out["row"]["kind"] == "detection_trigger"
        assert out["row"]["method_family"] == "dynamic-trace"

    def test_encryption_layer(self, tmp_path):
        rel = _probe_file(tmp_path, "config-entropy.txt", (
            "cmd: python tools/crypto-tool.py entropy assets/config.bin\n"
            "rc=0\n"
            "stdout: entropy=7.98/8.0 header=Salted__ size=4096\n"))
        out = _record(
            tmp_path,
            kind="encryption_layer",
            cause="assets/config.bin is an encrypted blob (entropy 7.98, "
                  "Salted__ header; key not present in binary)",
            evidence_path=rel,
            method_family="obfuscation-peeling")
        assert out["appended"] is True
        assert out["row"]["kind"] == "encryption_layer"
        assert out["row"]["method_family"] == "obfuscation-peeling"


# ---------- worker-contract doc pin (Req 3) ----------

class TestWorkerContractPin:
    def test_worker_doc_carries_intervention_protocol(self):
        text = (ROOT / "agents" / "kunglao-worker.md").read_text(
            encoding="utf-8")
        assert "Attribution-at-failure protocol" in text
        for kind in obstacles.KINDS:
            assert kind in text, kind
        assert "runs/probes/" in text
        assert "obstacles.py" in text
        assert "OBS-" in text
