# -*- coding: utf-8 -*-
"""tests/test_observability_58.py — issue #58 observability overhaul.

Sublayers (one class per sublayer, matching the commit split):
  S1   trace_id inheritance — emit() auto-stamps the workspace's current
       mission trace (runs/.trace-state.json, #879 allocator state) when the
       caller omits it; explicit kwarg still wins; explicit None is the
       documented out-of-band face; no trace at all is DOCUMENTED via the
       null_reasons sibling instead of silently starving.
  S3   version stamp — emit() defaults version to the cached checkout SHA.
  S2b  null starvation + one-way logging — normally-required fields that land
       null must carry a reason (caller-supplied or auto "omitted"); the
       result digest closes the loop (files_written/claims_touched/verdict).
  S2   subagent lifecycle — six per-transition event types + derived-event
       ingestion with dedupe (the write_guard/dispatch emitters are the #57
       sibling follow-up; this pins the ledger-side contract).
  S4   notes governance — notes_gate: NN-slug naming, mandatory ICD-203
       landing fields, verified-entry check (pending self-write without a
       verify event), provenance-completeness reporting.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import kunglao_log  # noqa: E402
from kunglao_log import (  # noqa: E402
    allocate_trace_id,
    emit_lifecycle,
    emit_result_digest,
    ingest_lifecycle,
    LIFECYCLE_PHASES,
    log_path,
)

_SHA = "a" * 64


def _rows(ws) -> list[dict]:
    p = log_path(ws)
    if not p.exists():
        return []
    return [json.loads(l) for l in
            p.read_text(encoding="utf-8").strip().splitlines() if l.strip()]


# ---------------------------------------------------------------- S1 --------

class TestS1TraceInheritance:
    def test_emit_without_trace_id_inherits_current_mission_trace(self, tmp):
        """The #879 allocator ran (dispatch face); every later omission joins
        the same chain WITHOUT caller discipline."""
        tid, _created = allocate_trace_id(tmp)
        kunglao_log.emit(tmp, actor="hook:dispatch_gate", action="dispatch",
                         claim="C-001", detail="tier=1")
        kunglao_log.emit(tmp, actor="worker:kunglao-worker", action="verify",
                         claim="C-001")
        rows = _rows(tmp)
        assert len(rows) == 2
        assert {r["trace_id"] for r in rows} == {tid}, (
            f"omitted trace_id must inherit the mission trace {tid}; "
            f"got {[r['trace_id'] for r in rows]}")

    def test_explicit_trace_id_still_wins(self, tmp):
        allocate_trace_id(tmp)
        kunglao_log.emit(tmp, actor="orchestrator", action="converge",
                         trace_id="tr-other-mission-0009")
        row = _rows(tmp)[0]
        assert row["trace_id"] == "tr-other-mission-0009"

    def test_no_trace_allocated_null_reasons_documents_it(self, tmp):
        """No allocation happened -> the row cannot silently starve: the
        null_reasons sibling names the gap."""
        kunglao_log.emit(tmp, actor="orchestrator", action="converge")
        row = _rows(tmp)[0]
        assert row["trace_id"] is None
        assert row["null_reasons"].get("trace_id") == "no_trace_allocated"

    def test_explicit_none_is_the_documented_out_of_band_face(self, tmp):
        allocate_trace_id(tmp)
        kunglao_log.emit(tmp, actor="orchestrator", action="converge",
                         trace_id=None)
        row = _rows(tmp)[0]
        assert row["trace_id"] is None
        assert row["null_reasons"].get("trace_id") == "explicit_out_of_band"

    def test_inheritance_reads_a_freshly_allocated_state(self, tmp):
        """Cache correctness: an allocation AFTER a prior trace-less emit is
        still picked up (mtime-keyed memo, not a stale one-shot read)."""
        kunglao_log.emit(tmp, actor="orchestrator", action="converge")
        assert _rows(tmp)[0]["trace_id"] is None
        tid, _ = allocate_trace_id(tmp)
        kunglao_log.emit(tmp, actor="orchestrator", action="converge")
        assert _rows(tmp)[1]["trace_id"] == tid


# ---------------------------------------------------------------- S3 --------

class TestS3VersionStamp:
    def test_emit_without_version_fills_repo_sha(self, tmp, monkeypatch):
        """Pin the default-fill logic (not the sha value): the cached
        _repo_sha() is the version default when the caller omits it."""
        monkeypatch.setattr(kunglao_log, "_repo_sha", lambda: _SHA)
        kunglao_log.emit(tmp, actor="orchestrator", action="dispatch")
        row = _rows(tmp)[0]
        assert row["version"] == _SHA

    def test_explicit_version_still_wins(self, tmp, monkeypatch):
        monkeypatch.setattr(kunglao_log, "_repo_sha", lambda: _SHA)
        kunglao_log.emit(tmp, actor="orchestrator", action="dispatch",
                         version="v9.9.9-test")
        assert _rows(tmp)[0]["version"] == "v9.9.9-test"

    def test_unavailable_sha_is_documented_not_silent(self, tmp, monkeypatch):
        monkeypatch.setattr(kunglao_log, "_repo_sha", lambda: None)
        kunglao_log.emit(tmp, actor="orchestrator", action="dispatch")
        row = _rows(tmp)[0]
        assert row["version"] is None
        assert row["null_reasons"].get("version") == "repo_sha_unavailable"


# ---------------------------------------------------------------- S2b -------

class TestS2bNullReasonsAndDigest:
    def test_required_field_omission_writes_null_reasons_sibling(self, tmp):
        """arm/epoch/hypothesis_ref/matched_rule/duration_ms are the measured
        100%-null starved set (#58 S2b): an omission without a stated reason
        is auto-documented, so the log stops being silently hollow."""
        kunglao_log.emit(tmp, actor="orchestrator", action="dispatch")
        row = _rows(tmp)[0]
        nr = row["null_reasons"]
        for f in ("arm", "epoch", "hypothesis_ref", "matched_rule",
                  "duration_ms"):
            assert f in nr, f"starved field {f} undocumented: {nr}"
            assert nr[f], f"reason must be non-empty for {f}"

    def test_caller_null_reasons_win_and_present_fields_are_skipped(self, tmp):
        kunglao_log.emit(tmp, actor="orchestrator", action="dispatch",
                         duration_ms=42,
                         null_reasons={"arm": "no_experiment",
                                       "duration_ms": "should be ignored"})
        nr = _rows(tmp)[0]["null_reasons"]
        assert nr["arm"] == "no_experiment"
        assert "duration_ms" not in nr

    def test_all_required_present_yields_empty_null_reasons(self, tmp):
        kunglao_log.emit(tmp, actor="orchestrator", action="dispatch",
                         duration_ms=1, arm="a", epoch=1,
                         hypothesis_ref="H-001", matched_rule="r1",
                         trace_id="tr-m-0001")
        assert _rows(tmp)[0]["null_reasons"] == {}

    def test_emit_result_digest_schema(self, tmp):
        """The one-way-logging fix: completion records carry WHAT CAME BACK."""
        emit_result_digest(tmp, actor="worker:kunglao-worker", claim="C-001",
                           files_written=["facts/F001-loader.md"],
                           claims_touched=["C-001"], verdict="delivered",
                           exit=0)
        row = _rows(tmp)[0]
        assert row["action"] == "result_digest"
        assert row["actor"] == "worker:kunglao-worker"
        assert row["claim"] == "C-001"
        payload = json.loads(row["detail"])
        assert payload["files_written"] == ["facts/F001-loader.md"]
        assert payload["claims_touched"] == ["C-001"]
        assert payload["verdict"] == "delivered"


# ---------------------------------------------------------------- S2 --------

class TestS2SubagentLifecycle:
    def test_emit_lifecycle_writes_six_transition_types(self, tmp):
        tid, _ = allocate_trace_id(tmp)
        for i, phase in enumerate(LIFECYCLE_PHASES):
            emit_lifecycle(tmp, actor="worker:kunglao-worker",
                           phase=phase, claim="C-001",
                           digest={"step": i})
        rows = _rows(tmp)
        assert [r["action"] for r in rows] == [
            f"lifecycle_{p}" for p in LIFECYCLE_PHASES]
        for r in rows:
            assert r["claim"] == "C-001"
            assert r["trace_id"] == tid, "lifecycle rows join the mission chain"
        assert json.loads(rows[0]["detail"]) == {"step": 0}

    def test_emit_lifecycle_unknown_phase_never_raises_and_writes_nothing(
            self, tmp, capsys):
        emit_lifecycle(tmp, actor="worker:kunglao-worker", phase="heartbeat")
        assert _rows(tmp) == []
        assert "lifecycle" in capsys.readouterr().err

    def test_lifecycle_words_are_registered_vocabulary(self):
        """Reverse emit-gate contract: the six transition words must be in the
        controlled EMIT_ACTIONS vocabulary (CI-anchored)."""
        import event_taxonomy
        for phase in LIFECYCLE_PHASES:
            assert f"lifecycle_{phase}" in event_taxonomy.EMIT_ACTIONS
        assert "result_digest" in event_taxonomy.EMIT_ACTIONS

    def test_ingest_lifecycle_dedupes_within_batch(self, tmp):
        cands = [{"actor": "worker:kunglao-worker", "phase": "spawned",
                  "claim": "C-001"},
                 {"actor": "worker:kunglao-worker", "phase": "spawned",
                  "claim": "C-001"}]
        out = ingest_lifecycle(tmp, cands)
        assert len(out) == 1
        assert len(_rows(tmp)) == 1

    def test_ingest_lifecycle_dedupes_against_ledger(self, tmp):
        emit_lifecycle(tmp, actor="worker:kunglao-worker", phase="completed",
                       claim="C-001")
        before = len(_rows(tmp))
        out = ingest_lifecycle(tmp, [
            {"actor": "worker:kunglao-worker", "phase": "completed",
             "claim": "C-001"}])
        assert out == []
        assert len(_rows(tmp)) == before

    def test_ingest_lifecycle_distinguishes_actors_and_claims(self, tmp):
        out = ingest_lifecycle(tmp, [
            {"actor": "worker:kunglao-worker", "phase": "started",
             "claim": "C-001"},
            {"actor": "verifier:kunglao-redteam", "phase": "started",
             "claim": "C-001"},
            {"actor": "worker:kunglao-worker", "phase": "started",
             "claim": "C-002"},
        ])
        assert len(out) == 3
        assert len(_rows(tmp)) == 3


# ---------------------------------------------------------------- S4 --------

def _note_fm(**extra) -> str:
    fm = {
        "id": "N-01",
        "title": "sample identity",
        "type": "note",
        "status": "INFERRED",
        "confidence": "medium",
        "claim_id": "C-001",
        "verify_status": "pending",
        "provenance": [
            {"role": "capture_log", "path": "evidence/x.log",
             "content_sha256": _SHA, "credibility": "B2"},
        ],
        "facts_used": ["F001-sample"],
    }
    fm.update(extra)
    lines = []
    for k, v in fm.items():
        if k == "provenance":
            lines.append("provenance:")
            for entry in v:
                cells = ", ".join(f"{ek}: {ev}" for ek, ev in entry.items())
                lines.append(f"  - {{{cells}}}")
        elif isinstance(v, list):
            lines.append(f"{k}: [{', '.join(map(str, v))}]")
        else:
            lines.append(f"{k}: {v}")
    return "---\n" + "\n".join(lines) + "\n---\n\nbody\n"


def _ws_with_note(tmp: Path, name: str = "01-sample-identity",
                  fm: str | None = None) -> Path:
    (tmp / "notes").mkdir(parents=True, exist_ok=True)
    (tmp / "notes" / f"{name}.md").write_text(
        fm if fm is not None else _note_fm(), encoding="utf-8")
    (tmp / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: OPEN\n", encoding="utf-8")
    return tmp


class TestS4NotesGate:
    def _lint(self, ws: Path) -> dict:
        import notes_gate
        return notes_gate.lint_notes(ws)

    def _codes(self, report: dict, sev: str) -> list[str]:
        return [code for _s, code, _m in report[sev]]

    def test_nn_slug_name_passes(self, tmp):
        report = self._lint(_ws_with_note(tmp))
        assert "NONCONFORMING_NAME" not in self._codes(report, "errors")

    def test_legacy_claim_id_filename_flagged(self, tmp):
        report = self._lint(_ws_with_note(tmp, name="C-202"))
        assert "NONCONFORMING_NAME" in self._codes(report, "errors")

    def test_off_convention_filename_flagged(self, tmp):
        report = self._lint(_ws_with_note(tmp, name="F300-progress-q4"))
        assert "NONCONFORMING_NAME" in self._codes(report, "errors")

    def test_missing_mandatory_icd203_fields_caught(self, tmp):
        fm = _note_fm().replace("confidence: medium\n", "")
        report = self._lint(_ws_with_note(tmp, fm=fm))
        codes = self._codes(report, "errors")
        assert "MISSING_CONFIDENCE" in codes
        assert "MISSING_PROVENANCE" not in codes or \
            "provenance" in fm  # only the dropped field errors

    def test_missing_provenance_caught(self, tmp):
        fm = _note_fm()
        fm = fm.replace(
            "provenance:\n  - {role: capture_log, path: evidence/x.log, "
            "content_sha256: " + _SHA + ", credibility: B2}\n", "")
        report = self._lint(_ws_with_note(tmp, fm=fm))
        assert "MISSING_PROVENANCE" in self._codes(report, "errors")

    def test_pending_verify_self_write_flagged(self, tmp):
        """THE #58 S4 face: a pending note for a claim with no verify event
        anywhere is an unverified self-write."""
        report = self._lint(_ws_with_note(tmp))
        codes = self._codes(report, "errors")
        assert "SELF_WRITE_UNVERIFIED" in codes

    def test_ledger_verify_event_clears_the_flag(self, tmp):
        ws = _ws_with_note(tmp)
        kunglao_log.emit(ws, actor="orchestrator", action="verify",
                         claim="C-001", artifact="F001")
        report = self._lint(ws)
        assert "SELF_WRITE_UNVERIFIED" not in self._codes(report, "errors")

    def test_terminal_register_claim_clears_the_flag(self, tmp):
        ws = _ws_with_note(tmp, fm=_note_fm(verify_status="passes"))
        (ws / "claim-register.yaml").write_text(
            "claims:\n  - id: C-001\n    status: PROVEN\n", encoding="utf-8")
        report = self._lint(ws)
        assert "SELF_WRITE_UNVERIFIED" not in self._codes(report, "errors")

    def test_unbacked_passes_stamp_flagged(self, tmp):
        ws = _ws_with_note(tmp, fm=_note_fm(verify_status="passes"))
        report = self._lint(ws)
        assert "SELF_WRITE_UNVERIFIED" in self._codes(report, "errors")

    def test_provenance_completeness_in_report(self, tmp):
        ws = _ws_with_note(tmp)
        (ws / "notes" / "02-no-prov.md").write_text(
            _note_fm(id="N-02").replace(
                "provenance:\n  - {role: capture_log, path: evidence/x.log, "
                "content_sha256: " + _SHA + ", credibility: B2}\n", ""),
            encoding="utf-8")
        report = self._lint(ws)
        pc = report["provenance_completeness"]
        assert pc["notes_total"] == 2
        assert pc["notes_with_provenance"] == 1
        assert pc["ratio"] == 0.5

    def test_no_evidence_linkage_warns(self, tmp):
        # a note anchored to NEITHER facts nor provenance artifacts — it also
        # trips MISSING_PROVENANCE (provenance is mandatory); the warning
        # names the missing anchor on top
        fm = _note_fm().replace("facts_used: [F001-sample]\n", "")
        fm = fm.replace(
            "provenance:\n  - {role: capture_log, path: evidence/x.log, "
            "content_sha256: " + _SHA + ", credibility: B2}\n", "")
        report = self._lint(_ws_with_note(tmp, fm=fm))
        assert "NO_EVIDENCE_LINKAGE" in self._codes(report, "warnings")

    def test_clean_verified_note_is_issue_free(self, tmp):
        ws = _ws_with_note(tmp, fm=_note_fm(verify_status="passes"))
        (ws / "claim-register.yaml").write_text(
            "claims:\n  - id: C-001\n    status: PROVEN\n", encoding="utf-8")
        report = self._lint(ws)
        assert report["errors"] == [], report["errors"]
        assert report["warnings"] == [], report["warnings"]

    def test_check_note_single_note_face_for_write_guard_wiring(self, tmp):
        """The #57 sibling wiring surface: one pending note text -> its
        SELF_WRITE_UNVERIFIED issue without anything on disk."""
        import notes_gate
        ws = _ws_with_note(tmp)
        issues = notes_gate.check_note(ws, "01-x.md", _note_fm())
        codes = {code for _s, code, _m in issues}
        assert "SELF_WRITE_UNVERIFIED" in codes

    def test_cli_rc(self, tmp):
        script = REPO_ROOT / "scripts" / "notes_gate.py"
        ws_bad = tmp / "ws-bad"
        ws_bad.mkdir()
        _ws_with_note(ws_bad)  # pending self-write -> errors -> rc 1
        r = subprocess.run([sys.executable, str(script), str(ws_bad)],
                           capture_output=True, text=True, timeout=60,
                           errors="replace")
        assert r.returncode == 1, f"stderr={r.stderr!r}"
        ws_clean = tmp / "ws-clean"
        ws_clean.mkdir()
        _ws_with_note(ws_clean, fm=_note_fm(verify_status="passes"))
        (ws_clean / "claim-register.yaml").write_text(
            "claims:\n  - id: C-001\n    status: PROVEN\n", encoding="utf-8")
        r0 = subprocess.run([sys.executable, str(script), str(ws_clean)],
                            capture_output=True, text=True, timeout=60,
                            errors="replace")
        assert r0.returncode == 0, f"stderr={r0.stderr!r}"
        rj = subprocess.run([sys.executable, str(script), str(ws_clean),
                             "--json"], capture_output=True, text=True,
                            timeout=60, errors="replace")
        payload = json.loads(rj.stdout)
        assert payload["provenance_completeness"]["notes_total"] == 1
