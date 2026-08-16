# -*- coding: utf-8 -*-
"""Tests for issue #236 — write-side gates (scripts/write_gate.py).

2026-08-12 combined failure chain (self-synthesis + self-stamping + fake
blocker) exposed that all kunglao mechanical gates are READ-side (dispatch
discipline, verify anchors, convergence judgment); the WRITE side (how state
comes into being: verify_status stamping, expected-anchor origin, defer
reasons) is bare. This module pins three write-side mechanical constraints,
audited against the repo's REAL artifact schema (references/schema.md,
references/guardrails.md §1b):

- R1 maker-checker re-verification:
  * a NOTE (notes/*.md) with verify_status=passes must have an independent
    verifier record under runs/ (*-verify-*.md citing the note id with a
    positive verdict). The 2026-08-12 create-runs.py shape — verify_status
    stamped pending→passes with no verifier record — must be flagged.
  * a FACT (facts/*.md) with status PROVEN/VERIFIED must carry independent
    verifier evidence: verifier_sign_off (verifier_id != register worker_id
    / producing script), or verified_by_run naming a real runs record, or a
    runs verify record (verify-redteam-*.md CONFIRMED citing the fact /
    verify-<fid>-*.json overall=VERIFIED or l2=CONFIRMED).
- R2 independent expected anchor: a fact carrying an expected/output hash
  whose verified_by_run resolves to the same script that produced the
  artifact (provenance recompute_script) is the adapt-final.py self-anchor
  pattern → violation.
- R3 defer_reason checkability: decision-rights row citations in
  claim-register.yaml defer_reason must resolve to rows that exist in
  references/decision-rights.md (fake-blocker vector). Only decision-shaped
  citations count ("row 5 of PE header table" is not a citation).
  claim_migrator refuses DEFERRED writes whose defer_reason cites a
  nonexistent row.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import write_gate  # noqa: E402
import kunglao_record  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REF_FILE = ROOT / "references" / "decision-rights.md"

# ---------- helpers ----------

DECISION_RIGHTS_ROWS = 15
DECISION_RIGHTS = (
    "# Decision rights — who decides what (three-way matrix)\n"
    "\n"
    "| # | Decision | 机械 (script/hook) | LLM (orchestrator) | 用户 |\n"
    "| --- | --- | --- | --- | --- |\n"
    + "".join(f"| {n} | Decision {n} | ✅ | — | — |\n"
              for n in range(1, DECISION_RIGHTS_ROWS + 1))
)
_HASH = "6cecd136d02b71948cdc8a36251c977629a877da5696d5631bf6b63289b3b9c5"


def _decision_rows() -> set[int]:
    return set(range(1, DECISION_RIGHTS_ROWS + 1))


def _write_decision_rights(ws: Path) -> Path:
    refs = ws / "references"
    refs.mkdir(parents=True, exist_ok=True)
    p = refs / "decision-rights.md"
    p.write_text(DECISION_RIGHTS, encoding="utf-8")
    return p


def _write_note(ws: Path, nid: str, *, verify_status: str,
                claim_id: str = "C-1") -> None:
    """Real note shape: notes/<id>.md frontmatter id + claim_id + verify_status."""
    notes = ws / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    (notes / f"{nid}.md").write_text(
        f"---\nid: {nid}\nclaim_id: {claim_id}\n"
        f"verify_status: {verify_status}\n---\n", encoding="utf-8")


def _write_note_verify_record(ws: Path, nid: str, *, verdict: str = "passes",
                              claim_id: str = "C-1") -> None:
    """Real verifier record: runs/<ts>-verify-<note_id>.md (outcome_capture shape)."""
    runs = ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"2026-08-11T00-00-00-verify-{nid}.md").write_text(
        f"---\nclaim_id: {claim_id}\nverify_status: {verdict}\n---\n\n"
        f"## Overall verdict\n{verdict}\n", encoding="utf-8")


def _write_fact(ws: Path, fid: str, *, status: str = "PROVEN",
                claim_id: str = "C-1", expected: str | None = None,
                verified_by_run: str | None = None,
                provenance_lines: list[str] | None = None,
                signoff: dict | None = None) -> None:
    """Real fact shape: frontmatter id/claim_id/status (+ optional expected/
    verified_by_run/provenance) and optional verifier_sign_off yaml block."""
    facts = ws / "facts"
    facts.mkdir(parents=True, exist_ok=True)
    lines = [f"---\nid: {fid}\nclaim_id: {claim_id}\nstatus: {status}"]
    if expected:
        lines.append(f"expected: {expected}")
    if verified_by_run:
        lines.append(f"verified_by_run: {verified_by_run}")
    if provenance_lines:
        lines.append("provenance:")
        lines.extend(f"  {ln}" for ln in provenance_lines)
    lines.append("---\n")
    if signoff:
        lines.append("```yaml\nverifier_sign_off:")
        lines.append(f"  verifier_id: {signoff['verifier_id']}")
        lines.append(f"  refute_attempt: '{signoff.get('refute_attempt', 'tried; held')}'")
        lines.append(f"  sign_off_at: {signoff.get('sign_off_at', '2026-08-10T14:00:00Z')}")
        if "verdict" in signoff:
            lines.append(f"  verdict: {signoff['verdict']}")
        lines.append("```\n")
    (facts / f"{fid}.md").write_text("\n".join(lines), encoding="utf-8")


def _write_redteam_record(ws: Path, fid: str, *, verdict: str = "CONFIRMED") -> None:
    runs = ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "verify-redteam-20260812.md").write_text(
        f"## redteam {fid}\nverdict: {verdict}\n", encoding="utf-8")


def _write_verify_json(ws: Path, fid: str, *, overall: str = "VERIFIED",
                       l2: str | None = None) -> None:
    """kunglao_verify.py L603-610 output shape: runs/verify-<fid>-<ts>.json."""
    runs = ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"verify-{fid}-20260811T000000Z.json").write_text(
        json.dumps({"fact_id": fid, "claim_id": "C-1", "overall": overall,
                    "l2": {"verdict": l2 or "NOT-RUN", "gaps": []},
                    "l1": {"verdict": "PASS" if overall == "VERIFIED" else "FAIL",
                           "actual_sha256": _HASH, "cmd": "python -c 1"}}),
        encoding="utf-8")


def _write_register(ws: Path, claims: list[dict]) -> None:
    """claims: [{"id", "status", "defer_reason"?, "worker_id"?}]."""
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n" + "".join(
            f"- id: {c['id']}\n"
            f"  status: {c['status']}\n"
            + (f"  worker_id: {c['worker_id']}\n" if c.get("worker_id") else "")
            + (f"  defer_reason: {c['defer_reason']}\n"
               if c.get("defer_reason") else "")
            for c in claims
        ), encoding="utf-8")


def _rules(violations: list[dict]) -> set[str]:
    return {v["rule"] for v in violations}


# =====================================================================
# R1a: note maker-checker — verify_status=passes needs a verify record
# =====================================================================

def test_r1_note_passes_without_record_is_violation(tmp_path):
    """create-runs.py shape: note stamped passes, no verifier record → R1."""
    ws = tmp_path / "ws"
    _write_note(ws, "01-draft", verify_status="passes")
    violations = write_gate.audit_workspace(ws)
    assert "R1" in _rules(violations), f"expected R1 violation: {violations}"
    r1 = next(v for v in violations if v["rule"] == "R1")
    assert r1["file"] == "notes/01-draft.md"
    assert "independent" in r1["detail"].lower()


def test_r1_note_passes_with_verify_record_clean(tmp_path):
    """Note passes + runs/<ts>-verify-<note_id>.md with passes → clean."""
    ws = tmp_path / "ws"
    _write_note(ws, "01-draft", verify_status="passes")
    _write_note_verify_record(ws, "01-draft", verdict="passes")
    assert write_gate.audit_workspace(ws) == []


def test_r1_note_record_without_positive_verdict_is_violation(tmp_path):
    """Record citing the note but FAILED content → still R1 (content-aware)."""
    ws = tmp_path / "ws"
    _write_note(ws, "01-draft", verify_status="passes")
    _write_note_verify_record(ws, "01-draft", verdict="fails")
    violations = write_gate.audit_workspace(ws)
    assert "R1" in _rules(violations)


def test_r1_note_pending_not_audited(tmp_path):
    ws = tmp_path / "ws"
    _write_note(ws, "01-draft", verify_status="pending")
    assert "R1" not in _rules(write_gate.audit_workspace(ws))


# =====================================================================
# R1b: fact maker-checker — PROVEN/VERIFIED needs verifier evidence
# =====================================================================

def test_r1_fact_proven_without_verifier_evidence_is_violation(tmp_path):
    ws = tmp_path / "ws"
    _write_fact(ws, "F-1", status="PROVEN")
    violations = write_gate.audit_workspace(ws)
    assert "R1" in _rules(violations), f"expected R1 violation: {violations}"
    r1 = next(v for v in violations if v["rule"] == "R1")
    assert r1["file"] == "facts/F-1.md"


def test_r1_fact_proven_with_independent_signoff_clean(tmp_path):
    """verifier_sign_off verifier_id=kunglao-redteam-w2 != worker_id=w1 → clean."""
    ws = tmp_path / "ws"
    _write_register(ws, [{"id": "C-1", "status": "OPEN", "worker_id": "w1"}])
    _write_fact(ws, "F-1", status="PROVEN",
                signoff={"verifier_id": "kunglao-redteam-w2",
                         "verdict": "CONFIRMED"})
    assert write_gate.audit_workspace(ws) == []


def test_r1_fact_signoff_self_stamp_is_violation(tmp_path):
    """verifier_sign_off verifier_id == worker_id → self-stamp R1."""
    ws = tmp_path / "ws"
    _write_register(ws, [{"id": "C-1", "status": "OPEN", "worker_id": "w1"}])
    _write_fact(ws, "F-1", status="PROVEN",
                signoff={"verifier_id": "w1", "verdict": "CONFIRMED"})
    violations = write_gate.audit_workspace(ws)
    assert "R1" in _rules(violations)
    r1 = next(v for v in violations if v["rule"] == "R1")
    assert "self-stamp" in r1["detail"].lower()


def test_r1_fact_verified_by_run_without_record_is_violation(tmp_path):
    """verified_by_run naming an actor with no record anywhere → R1."""
    ws = tmp_path / "ws"
    _write_fact(ws, "F-1", status="PROVEN", verified_by_run="kunglao-redteam-w2")
    violations = write_gate.audit_workspace(ws)
    assert "R1" in _rules(violations)
    r1 = next(v for v in violations if v["rule"] == "R1")
    assert "kunglao-redteam-w2" in r1["detail"]


def test_r1_fact_verified_by_run_with_verify_json_clean(tmp_path):
    """verified_by_run + the actor's runs/verify-<fid>-*.json VERIFIED → clean."""
    ws = tmp_path / "ws"
    _write_fact(ws, "F-1", status="PROVEN", verified_by_run="kunglao-redteam-w2")
    _write_verify_json(ws, "F-1", overall="VERIFIED")
    assert write_gate.audit_workspace(ws) == []


def test_r1_fact_with_redteam_confirmed_record_clean(tmp_path):
    """runs/verify-redteam-*.md CONFIRMED citing the fact → clean."""
    ws = tmp_path / "ws"
    _write_fact(ws, "F-1", status="PROVEN")
    _write_redteam_record(ws, "F-1", verdict="CONFIRMED")
    assert write_gate.audit_workspace(ws) == []


def test_r1_redteam_record_without_confirmed_verdict_is_violation(tmp_path):
    """redteam md citing the fact but FAILED content → R1 (content-aware)."""
    ws = tmp_path / "ws"
    _write_fact(ws, "F-1", status="PROVEN")
    _write_redteam_record(ws, "F-1", verdict="FAILED")
    violations = write_gate.audit_workspace(ws)
    assert "R1" in _rules(violations)


def test_r1_fact_open_status_not_audited(tmp_path):
    ws = tmp_path / "ws"
    _write_fact(ws, "F-1", status="OPEN")
    assert "R1" not in _rules(write_gate.audit_workspace(ws))


# =====================================================================
# R2: independent expected anchor — verifier != producing script
# =====================================================================

def test_r2_verified_by_run_equals_recompute_script_is_violation(tmp_path):
    """adapt-final.py pattern: verified_by_run == provenance recompute_script."""
    ws = tmp_path / "ws"
    _write_fact(ws, "F-1", status="PROVEN", expected=_HASH,
                verified_by_run="scripts/re/adapt_final.py",
                provenance_lines=["- {role: recompute_script, path: scripts/re/adapt_final.py}"])
    violations = write_gate.audit_workspace(ws)
    assert "R2" in _rules(violations), f"expected R2 violation: {violations}"
    r2 = next(v for v in violations if v["rule"] == "R2")
    assert "adapt_final.py" in r2["detail"]
    assert "self-verify" in r2["detail"].lower() or "self-anchor" in r2["detail"].lower()


def test_r2_independent_verified_by_run_clean(tmp_path):
    """verified_by_run different from producing script + verify record → clean."""
    ws = tmp_path / "ws"
    _write_fact(ws, "F-1", status="PROVEN", expected=_HASH,
                verified_by_run="kunglao-redteam-w2",
                provenance_lines=["- {role: recompute_script, path: scripts/re/adapt_final.py}"])
    _write_verify_json(ws, "F-1", overall="VERIFIED")
    assert write_gate.audit_workspace(ws) == []


def test_r2_basename_resolution_catches_self_anchor(tmp_path):
    """verified_by_run/provenance written as bare basenames still compare equal."""
    ws = tmp_path / "ws"
    _write_fact(ws, "F-1", status="PROVEN", expected=_HASH,
                verified_by_run="adapt_final.py",
                provenance_lines=["- {role: recompute_script, path: scripts/re/adapt_final.py}"])
    _write_verify_json(ws, "F-1", overall="VERIFIED")
    violations = write_gate.audit_workspace(ws)
    assert "R2" in _rules(violations)


# =====================================================================
# End-to-end: create-runs.py incident shape must be flagged
# =====================================================================

def test_incident_create_runs_self_stamp_shape_flagged(tmp_path):
    """The documented 2026-08-12 vector: create-runs.py stamps a note's
    verify_status pending→passes (no verifier record) and writes a fact's
    verified_by_run pointing at the producing script. Both must be flagged —
    this proves the gate is not vacuous against the real incident shape."""
    ws = tmp_path / "ws"
    # note stamped passes with NO verify record
    _write_note(ws, "01-draft", verify_status="passes")
    # fact with self-referential verified_by_run (producer self-anchors)
    _write_fact(ws, "F-1", status="PROVEN", expected=_HASH,
                verified_by_run="scripts/re/adapt_final.py",
                provenance_lines=["- {role: recompute_script, path: scripts/re/adapt_final.py}"])
    violations = write_gate.audit_workspace(ws)
    assert "R1" in _rules(violations) and "R2" in _rules(violations), \
        f"incident shape must be flagged: {violations}"
    files = {(v["rule"], v["file"]) for v in violations}
    assert ("R1", "notes/01-draft.md") in files, "stamped note must be flagged"
    assert ("R1", "facts/F-1.md") in files, "fact without verifier evidence flagged"
    assert ("R2", "facts/F-1.md") in files, "self-anchor must be flagged"


# =====================================================================
# R3: defer_reason citations must resolve to existing decision-rights rows
# =====================================================================

def test_r3_valid_row_citation_clean(tmp_path):
    """defer_reason 'decision-rights row 15' → clean (row exists)."""
    ws = tmp_path / "ws"
    _write_decision_rights(ws)
    _write_register(ws, [{"id": "C-1", "status": "DEFERRED",
                          "defer_reason": "'blocked on decision-rights row 15'"}])
    assert write_gate.audit_workspace(ws) == []


def test_r3_nonexistent_row_is_violation(tmp_path):
    """defer_reason 'row 99' → R3 violation listing the claim + row."""
    ws = tmp_path / "ws"
    _write_decision_rights(ws)
    _write_register(ws, [{"id": "C-1", "status": "DEFERRED",
                          "defer_reason": "'waiting for governance — row 99'"}])
    violations = write_gate.audit_workspace(ws)
    assert "R3" in _rules(violations), f"expected R3 violation: {violations}"
    r3 = next(v for v in violations if v["rule"] == "R3")
    assert r3["claim_id"] == "C-1"
    assert r3["row"] == 99
    assert "99" in r3["detail"]


def test_r3_row_zero_is_violation(tmp_path):
    """'row 0' is garbage — 0 is never a valid decision-rights row."""
    ws = tmp_path / "ws"
    _write_decision_rights(ws)
    _write_register(ws, [{"id": "C-1", "status": "DEFERRED",
                          "defer_reason": "'blocked on row 0'"}])
    violations = write_gate.audit_workspace(ws)
    assert "R3" in _rules(violations)


def test_r3_chinese_gangzhi_row_citation(tmp_path):
    """'治理行 15' resolves like 'row 15'."""
    ws = tmp_path / "ws"
    _write_decision_rights(ws)
    _write_register(ws, [{"id": "C-1", "status": "DEFERRED",
                          "defer_reason": "'等待治理行 15 裁定'"}])
    assert write_gate.audit_workspace(ws) == []


def test_r3_pe_header_row_not_flagged(tmp_path):
    """'row 5 of PE header table' is not a decision-rights citation → clean."""
    ws = tmp_path / "ws"
    _write_decision_rights(ws)
    _write_register(ws, [{"id": "C-1", "status": "DEFERRED",
                          "defer_reason": "'row 5 of PE header table is bogus'"}])
    assert write_gate.audit_workspace(ws) == []


def test_r3_rows_parsed_from_file_not_hardcoded(tmp_path):
    """Validator uses the actual rows in the file, not a hardcoded max."""
    ws = tmp_path / "ws"
    refs = ws / "references"
    refs.mkdir(parents=True)
    (refs / "decision-rights.md").write_text(
        "| # | D |\n| --- | --- |\n| 1 | a |\n| 2 | b |\n", encoding="utf-8")
    _write_register(ws, [{"id": "C-1", "status": "DEFERRED",
                          "defer_reason": "'row 3'"}])
    violations = write_gate.audit_workspace(ws)
    assert "R3" in _rules(violations), \
        "row 3 must violate when the file only defines rows 1-2"


def test_r3_no_defer_reason_is_clean(tmp_path):
    """Claims without defer_reason are not audited."""
    ws = tmp_path / "ws"
    _write_decision_rights(ws)
    _write_register(ws, [{"id": "C-1", "status": "OPEN"}])
    assert write_gate.audit_workspace(ws) == []


# =====================================================================
# kunglao_record wiring: DEFERRED write with bad citation is refused
# =====================================================================

def test_record_refuses_deferred_write_with_bad_citation(ws_factory):
    """claim_migrator refuses a DEFERRED write citing a nonexistent row."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _write_decision_rights(ws)
    reg = (ws / "claim-register.yaml").read_text(encoding="utf-8")
    reg = reg.replace("- id: C-1\n", "- id: C-1\n"
                      "  defer_reason: 'blocked on decision-rights row 99'\n")
    (ws / "claim-register.yaml").write_text(reg, encoding="utf-8")
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "DEFERRED", "orchestrator")
    assert not ok, f"DEFERRED write must be refused: {msg}"
    assert "99" in msg
    assert "DEFER REASON" in msg.upper()
    register = (ws / "claim-register.yaml").read_text(encoding="utf-8")
    assert "status: OPEN" in register, "register must stay unchanged"


def test_record_allows_deferred_write_with_valid_citation(ws_factory):
    """Valid row citation → DEFERRED write proceeds (no regression)."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    _write_decision_rights(ws)
    reg = (ws / "claim-register.yaml").read_text(encoding="utf-8")
    reg = reg.replace("- id: C-1\n", "- id: C-1\n"
                      "  defer_reason: 'blocked on decision-rights row 15'\n")
    (ws / "claim-register.yaml").write_text(reg, encoding="utf-8")
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "DEFERRED", "orchestrator")
    assert ok, msg
    assert "status: DEFERRED" in (ws / "claim-register.yaml").read_text(encoding="utf-8")


def test_record_deferred_without_decision_rights_file_unchanged(ws_factory):
    """Workspace without references/decision-rights.md → DEFERRED still writes."""
    ws = ws_factory(claims=[{"id": "C-1", "status": "OPEN"}])
    ok, msg = kunglao_record.claim_migrator(ws, "C-1", "DEFERRED", "orchestrator")
    assert ok, f"no governance file → check skipped, write allowed: {msg}"
    assert "status: DEFERRED" in (ws / "claim-register.yaml").read_text(encoding="utf-8")


# =====================================================================
# CLI contract: exit 0 clean / 1 violations / 2 usage; --json
# =====================================================================

def test_cli_clean_exit_zero(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    assert write_gate.main([str(ws)]) == 0


def test_cli_violation_exit_one_and_human_text(tmp_path, capsys):
    ws = tmp_path / "ws"
    _write_note(ws, "01-draft", verify_status="passes")
    assert write_gate.main([str(ws)]) == 1
    out = capsys.readouterr().out
    assert "[R1]" in out
    assert "violation" in out.lower()


def test_cli_missing_arg_exit_two(tmp_path, capsys):
    assert write_gate.main([]) == 2
    capsys.readouterr()


def test_cli_json_mode(tmp_path, capsys):
    ws = tmp_path / "ws"
    _write_note(ws, "01-draft", verify_status="passes")
    assert write_gate.main([str(ws), "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False
    assert data["violations"][0]["rule"] == "R1"


def test_real_decision_rights_rows_used():
    """Real references/decision-rights.md parses to rows 1..15 (repo fact)."""
    rows = write_gate.decision_rows_from_text(
        REF_FILE.read_text(encoding="utf-8"))
    assert rows == set(range(1, 16)), f"expected rows 1..15, got {sorted(rows)}"
