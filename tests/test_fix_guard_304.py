# -*- coding: utf-8 -*-
"""tests/test_fix_guard_304.py — issue 304 (satellite D4): fix-as-guard.

THE RULE: a fix is real only as a mechanical guard wired into the tool —
an assert/check (artifact-size check, marker grep, did-suffix check).
Documentation beside the tool is wishful; a "fix" without its guard does
not settle.

Seam (T0): the fix record is the failure-analysis entry
(analyses/failure-<claim>.yaml; ``next_method`` IS the fix); the
settlement-forensics beat is the closure-outcome fill (``--outcome`` /
``--what-happened`` — the settlement verdict vocabulary). Extends the
issue-146 doctrine: the settlement record must carry evidence that a
guard exists and is wired (file + check reference), else it is REJECTED
with the named reason. A guard that never fires across the settlement
window is flagged guard_dormant (WARN-level finding), never silently
accepted.

Contract (issue 304, RED first):

  a. a fix record without a wired guard -> settlement rejected with the
     named reason (GUARD_MISSING);
  b. fix records carry (guard_type, guard_location, check_reference)
     fields; presence validated mechanically (closed guard_type
     vocabulary; guard_location file exists; check_reference greps in
     it — else GUARD_UNRESOLVED);
  c. a guard that exists but never fires across the settlement window
     is flagged guard_dormant at the settlement beat (register_proven_gate.
     emit_settlements transaction), ledger-deduped, never a blocker.

Fast tier: pure unit + tmp_path workspace faces; no process spawns, no
network, no nested pytest.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import failure_analysis_gate as fag  # noqa: E402
import fix_guard as fxg  # noqa: E402
from kunglao_log import _all_rows  # noqa: E402

# Guard evidence that resolves mechanically against the repo root for ANY
# tmp workspace: the vocabulary file exists and contains the anchor token.
GUARD_OK = {"guard_type": "marker-grep",
            "guard_location": "scripts/event_taxonomy.py",
            "check_reference": "EMIT_ACTIONS"}


# ----------------------------------------------------------------- fixtures

def _write_register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True,
                       sort_keys=False),
        encoding="utf-8")


def _claim(cid: str) -> dict:
    return {"id": cid, "status": "OPEN", "boundary_type": "positive_observation",
            "evidence_tier_attempted": 1, "promotion_attempts": 0,
            "answers_question": "q1", "depends_on": [],
            "statement": "sample does X"}


def _record(ws: Path, cid: str, **kw) -> dict:
    return fag.record_analysis(
        ws, cid, kw.get("assumption", ""), kw.get("validity", ""),
        kw.get("next_method", ""), kw.get("outcome"), kw.get("what_happened"),
        validated_capability=kw.get("capability"),
        identified_obstacle=kw.get("obstacle"),
        source=kw.get("source", "lesson-hit"),
        library=kw.get("library"),
        guard_type=kw.get("guard_type"),
        guard_location=kw.get("guard_location"),
        check_reference=kw.get("check_reference"))


def _analysis_entry(ws: Path, cid: str) -> dict:
    p = ws / "analyses" / f"failure-{cid}.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _ledger(ws: Path) -> list[dict]:
    return _all_rows(ws)


# ------------------------------------------- acceptance (a): named refusal

class TestFixSettlementRequiresGuard:
    """A fix record without a wired guard does not settle (issue 304 a)."""

    def test_closure_win_over_replaced_method_rejected(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_register(ws, [_claim("C-1")])
        # failure-time record: the method was replaced (not-justified) —
        # legal without a guard, no settlement happened yet.
        r1 = _record(ws, "C-1", assumption="spawn keeps it alive",
                     validity="not-justified", next_method="listen mode",
                     source="reference-hit")
        assert r1["recorded"], r1

        # Act — the settlement beat: claim closes on a WIN verdict.
        r2 = _record(ws, "C-1", outcome="PROVEN", what_happened="it worked")

        # Assert — rejected with the NAMED reason.
        assert r2["recorded"] is False
        assert r2["reason"].startswith(fxg.GUARD_MISSING), r2["reason"]

    def test_combined_fix_settlement_without_guard_rejected(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_register(ws, [_claim("C-2")])
        r = _record(ws, "C-2", assumption="a", validity="not-justified",
                    next_method="b", outcome="VERIFIED", what_happened="ok")
        assert r["recorded"] is False
        assert r["reason"].startswith(fxg.GUARD_MISSING), r["reason"]

    def test_loss_verdicts_stay_ungated(self, tmp_path):
        """REFUTED/NEGATIVE closures believe nothing — no guard required."""
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_register(ws, [_claim("C-3")])
        for outcome in ("REFUTED", "NEGATIVE"):
            r = _record(ws, "C-3", assumption="a", validity="not-justified",
                        next_method="b", outcome=outcome,
                        what_happened="the fix did not hold")
            assert r["recorded"] is True, (outcome, r)

    def test_adequate_method_closure_stays_ungated(self, tmp_path):
        """A win on a justified-adequate method replaced nothing — not a
        fix settlement."""
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_register(ws, [_claim("C-4")])
        r = _record(ws, "C-4", assumption="a",
                    validity="justified-adequate", next_method="same probe",
                    outcome="PROVEN", what_happened="ok")
        assert r["recorded"] is True, r

    def test_refusal_emits_guard_missing_event(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_register(ws, [_claim("C-5")])
        _record(ws, "C-5", assumption="a", validity="not-justified",
                next_method="b", outcome="PROVEN", what_happened="ok")
        words = [str(r.get("action") or "") for r in _ledger(ws)]
        assert "guard_missing" in words, words

    def test_refusal_writes_no_analysis_file(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_register(ws, [_claim("C-6")])
        _record(ws, "C-6", assumption="a", validity="not-justified",
                next_method="b", outcome="PROVEN", what_happened="ok")
        assert not (ws / "analyses" / "failure-C-6.yaml").exists()


# ------------------------------- acceptance (b): the mechanical evidence

class TestGuardEvidence:
    """fix records carry (guard_type, guard_location, check_reference);
    presence + wiring validated mechanically (issue 304 b)."""

    def test_guarded_fix_settlement_records_fields(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_register(ws, [_claim("C-1")])
        r = _record(ws, "C-1", assumption="a", validity="not-justified",
                    next_method="b", outcome="PROVEN", what_happened="ok",
                    **GUARD_OK)
        assert r["recorded"] is True, r
        entry = _analysis_entry(ws, "C-1")
        assert entry["guard_type"] == "marker-grep"
        assert entry["guard_location"] == "scripts/event_taxonomy.py"
        assert entry["check_reference"] == "EMIT_ACTIONS"

    def test_guard_type_outside_closed_vocabulary_rejected(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_register(ws, [_claim("C-2")])
        r = _record(ws, "C-2", assumption="a", validity="not-justified",
                    next_method="b", outcome="PROVEN", what_happened="ok",
                    guard_type="should-be-fine-now",
                    guard_location="scripts/event_taxonomy.py",
                    check_reference="EMIT_ACTIONS")
        assert r["recorded"] is False
        assert r["reason"].startswith(fxg.GUARD_MISSING), r["reason"]
        assert "should-be-fine-now" in r["reason"]

    def test_unresolvable_location_rejected(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_register(ws, [_claim("C-3")])
        r = _record(ws, "C-3", assumption="a", validity="not-justified",
                    next_method="b", outcome="PROVEN", what_happened="ok",
                    guard_type="marker-grep",
                    guard_location="scripts/no_such_guard_304.py",
                    check_reference="EMIT_ACTIONS")
        assert r["recorded"] is False
        assert r["reason"].startswith(fxg.GUARD_UNRESOLVED), r["reason"]

    def test_check_reference_not_in_file_rejected(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_register(ws, [_claim("C-4")])
        r = _record(ws, "C-4", assumption="a", validity="not-justified",
                    next_method="b", outcome="PROVEN", what_happened="ok",
                    guard_type="marker-grep",
                    guard_location="scripts/event_taxonomy.py",
                    check_reference="NO_SUCH_ANCHOR_304")
        assert r["recorded"] is False
        assert r["reason"].startswith(fxg.GUARD_UNRESOLVED), r["reason"]

    def test_guard_fields_preserved_from_prior(self, tmp_path):
        """The failure-time record carries the evidence; the closure beat
        inherits it (same preserve rule as the three artifacts)."""
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_register(ws, [_claim("C-5")])
        r1 = _record(ws, "C-5", assumption="a", validity="not-justified",
                     next_method="b", source="reference-hit", **GUARD_OK)
        assert r1["recorded"], r1
        r2 = _record(ws, "C-5", outcome="PROVEN", what_happened="it held")
        assert r2["recorded"] is True, r2
        entry = _analysis_entry(ws, "C-5")
        assert entry["check_reference"] == "EMIT_ACTIONS"


# ------------------------------------------------- pure faces (unit level)

class TestPureFaces:
    def test_is_fix_settlement_shape(self):
        assert fxg.is_fix_settlement("not-justified", "b", "PROVEN")
        assert fxg.is_fix_settlement("not-justified", "b", "verified")
        assert not fxg.is_fix_settlement("not-justified", "b", "REFUTED")
        assert not fxg.is_fix_settlement("justified-adequate", "b", "PROVEN")
        assert not fxg.is_fix_settlement("not-justified", "", "PROVEN")

    def test_normalize_rejects_partial_evidence(self):
        guard, err = fxg.normalize_guard(
            {"guard_type": "marker-grep", "guard_location": "x.py"})
        assert guard is None and err is not None
        assert err.startswith(fxg.GUARD_MISSING)

    def test_normalize_returns_new_stripped_dict(self):
        rec = dict(GUARD_OK)
        guard, err = fxg.normalize_guard(rec)
        assert err is None
        assert guard == GUARD_OK
        assert guard is not rec  # immutable: never the input object

    def test_evaluate_guard_resolves_through_repo_root(self):
        guard, err = fxg.evaluate_guard(GUARD_OK, (Path("/nonexistent-304"),
                                                   fxg.REPO_ROOT))
        assert err is None and guard is not None

    def test_guard_types_are_the_issue_named_examples(self):
        assert fxg.GUARD_TYPES == ("artifact-size", "did-suffix",
                                   "marker-grep")


# --------------------- acceptance (c): dormancy across the settlement window

class TestDormancy:
    def _write_guarded_analysis(self, ws: Path, cid: str) -> None:
        d = ws / "analyses"
        d.mkdir(parents=True, exist_ok=True)
        entry = {"claim": cid, "next_method": "listen mode",
                 "outcome": "PROVEN", **GUARD_OK}
        (d / f"failure-{cid}.yaml").write_text(
            yaml.safe_dump(entry, allow_unicode=True, sort_keys=False),
            encoding="utf-8")

    def test_guard_with_zero_fires_flagged(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        self._write_guarded_analysis(ws, "C-9")
        flagged = fxg.flag_dormant_guards(ws)
        assert [g["claim"] for g in flagged] == ["C-9"]
        words = [str(r.get("action") or "") for r in _ledger(ws)]
        assert "guard_dormant" in words, words

    def test_guard_with_a_fire_record_not_flagged(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        self._write_guarded_analysis(ws, "C-9")
        from kunglao_log import emit
        emit(ws, "orchestrator", "guard_fired", claim="C-9",
             detail=fxg.fire_detail(GUARD_OK))
        assert fxg.flag_dormant_guards(ws) == []
        words = [str(r.get("action") or "") for r in _ledger(ws)]
        assert "guard_dormant" not in words, words

    def test_flag_is_ledger_deduped(self, tmp_path):
        """One WARN per guard — the second settlement beat stays silent."""
        ws = tmp_path / "ws"
        ws.mkdir()
        self._write_guarded_analysis(ws, "C-9")
        assert len(fxg.flag_dormant_guards(ws)) == 1
        assert fxg.flag_dormant_guards(ws) == []
        rows = [r for r in _ledger(ws)
                if str(r.get("action") or "") == "guard_dormant"]
        assert len(rows) == 1, rows

    def test_unguarded_analyses_are_invisible_to_the_flag(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        d = ws / "analyses"
        d.mkdir(parents=True)
        (d / "failure-C-7.yaml").write_text(
            yaml.safe_dump({"claim": "C-7", "next_method": "b",
                            "outcome": "PROVEN"}, sort_keys=False),
            encoding="utf-8")
        assert fxg.flag_dormant_guards(ws) == []

    def test_pure_dormant_guards_face(self):
        guarded = [{"claim": "C-1", **GUARD_OK}]
        assert fxg.dormant_guards(guarded, []) == guarded
        fired = [{"action": "guard_fired",
                  "detail": json.dumps({"check_reference":
                                        GUARD_OK["check_reference"]})}]
        assert fxg.dormant_guards(guarded, fired) == []
        junk = [{"action": "guard_fired", "detail": "not-json"}]
        assert fxg.dormant_guards(guarded, junk) == guarded

    def test_settlement_beat_flags_dormant_guard(self, tmp_path):
        """The dormancy flag hangs at the per-claim settlement transaction
        (register_proven_gate.emit_settlements) — the same beat that
        settles the claim."""
        from register_proven_gate import emit_settlements
        ws = tmp_path / "ws"
        ws.mkdir()
        self._write_guarded_analysis(ws, "C-1")
        (ws / "claim-register.yaml").write_text(
            yaml.safe_dump({"claims": [{"id": "C-1", "status": "OPEN"}]},
                           sort_keys=False),
            encoding="utf-8")
        n = emit_settlements(
            ws,
            yaml.safe_dump({"claims": [{"id": "C-1", "status": "PROVEN"}]},
                           sort_keys=False))
        assert n == 1
        words = [str(r.get("action") or "") for r in _ledger(ws)]
        assert "guard_dormant" in words, words

    def test_dormant_words_registered(self):
        et = pytest.importorskip("event_taxonomy")
        for word in ("guard_fired", "guard_dormant", "guard_missing",
                     "guard_unresolved"):
            assert word in et.EMIT_ACTIONS, word


# ------------------------------------------------------------ CLI surface

class TestCliFlags:
    def test_cli_rejects_unguarded_fix_settlement(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_register(ws, [_claim("C-1")])
        rc = fag.main([str(ws), "C-1", "--record",
                       "--validity", "not-justified",
                       "--next-method", "b",
                       "--outcome", "PROVEN",
                       "--what-happened", "ok",
                       "--source", "reference-hit",
                       "--json"])
        assert rc == 1
        assert not (ws / "analyses" / "failure-C-1.yaml").exists()

    def test_cli_accepts_guarded_fix_settlement(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        _write_register(ws, [_claim("C-2")])
        rc = fag.main([str(ws), "C-2", "--record",
                       "--validity", "not-justified",
                       "--next-method", "b",
                       "--outcome", "PROVEN",
                       "--what-happened", "ok",
                       "--source", "reference-hit",
                       "--guard-type", "marker-grep",
                       "--guard-location", "scripts/event_taxonomy.py",
                       "--check-reference", "EMIT_ACTIONS",
                       "--json"])
        assert rc == 0
        entry = _analysis_entry(ws, "C-2")
        assert entry["guard_type"] == "marker-grep"
        assert entry["check_reference"] == "EMIT_ACTIONS"
