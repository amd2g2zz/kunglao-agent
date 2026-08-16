# -*- coding: utf-8 -*-
"""RED tests for issue #238 — role-contract completion (F2/F3/F6).

Pins three contract additions to the kunglao-agent repo:
- F3: `kunglao_verify.check_expected_anchor_source` — a fact whose `expected`
      is embedded in the source of its own provenance `recompute_script` is a
      tautological verification (script output compared against the script's
      own constant) and MUST be lint-rejected before promotion.
- F6: `kunglao_verify.check_cross_workflow_redteam` — a fact marked
      `provenance: cross_workflow` (transcribed from an external workflow such
      as mal-recon) MUST carry a kunglao-redteam record before entering the
      fact base; absence is a WARNING (non-blocking), not a rejection.
- F2: SKILL.md orchestrator section MUST state the read/write boundary —
      reading state (claim-register/plan) and reading evidence (evidence/*)
      are allowed, but writing a fact from read evidence is maker behavior
      (worker or `synthesis: true` + source).

Driven by 2026-08-12 incidents:
- F3: adapt-final.py was run by the orchestrator with its own script
      self-computing the expected sha256 — the compare was script-output vs
      script-constant, i.e. no independent anchor.
- F6: F001-F003 provenance transcribed from mal-recon entered the fact base
      without a kunglao-redteam spot check.

RED phase: check_expected_anchor_source / check_cross_workflow_redteam do not
exist yet, so every code test below fails; the F2 wording pins fail until
SKILL.md is updated.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import kunglao_verify as kv  # noqa: E402


# ---------- helpers ----------

def _write_fact(ws: Path, fid: str, *, expected: str,
                provenance_lines: list[str], reproduce: str = "print('ok')",
                redteam_verdict: str | None = None) -> dict:
    """Write a fact file with a provenance block and return load_fact() dict."""
    facts = ws / "facts"
    facts.mkdir(parents=True, exist_ok=True)
    prov = "\n".join(f"  {ln}" for ln in provenance_lines)
    rtv = f"\nredteam_verdict: {redteam_verdict}" if redteam_verdict else ""
    (facts / f"{fid}.md").write_text(
        f"---\nid: {fid}\nclaim: c\nverified: false\nreproduce: {reproduce}\n"
        f"expected: {expected}{rtv}\nprovenance:\n{prov}\n---\n",
        encoding="utf-8")
    return kv.load_fact(ws, fid)


def _recompute_fact(ws: Path, fid: str, script_src: str, expected: str) -> dict:
    """Fact whose provenance recompute_script points at a real script file."""
    re_dir = ws / "scripts" / "re"
    re_dir.mkdir(parents=True, exist_ok=True)
    script = re_dir / "adapt_final.py"
    script.write_text(script_src, encoding="utf-8")
    return _write_fact(
        ws, fid, expected=expected,
        provenance_lines=[f"- {{role: recompute_script, path: scripts/re/adapt_final.py}}"])


# ---------- F3: expected-anchor source gate (unit) ----------

def test_f3_rejects_expected_sha256_embedded_in_producing_script(tmp_path):
    """adapt-final.py shape: script hardcodes the expected sha256 constant."""
    embedded = "6cecd136d02b71948cdc8a36251c977629a877da5696d5631bf6b63289b3b9c5"
    src = f"import hashlib\nEXPECTED = {embedded!r}\nprint(EXPECTED)\n"
    fact = _recompute_fact(tmp_path, "F-901", src, embedded)
    ok, reason = kv.check_expected_anchor_source(fact)
    assert ok is False
    assert "self-computed" in reason.lower() or "tautolog" in reason.lower()


def test_f3_rejects_expected_text_embedded_in_producing_script(tmp_path):
    """Non-hash expected: raw expected string found inside the script source."""
    src = 'expected = "frameRateNum=fps; gopLength=0xFFFFFFFF"\nprint(expected)\n'
    fact = _recompute_fact(tmp_path, "F-902", src, "frameRateNum=fps; gopLength=0xFFFFFFFF")
    ok, reason = kv.check_expected_anchor_source(fact)
    assert ok is False
    assert "self-computed" in reason.lower() or "tautolog" in reason.lower()


def test_f3_passes_when_expected_not_in_script(tmp_path):
    """Script derives output from the sample; expected is an independent constant."""
    src = "import sys\nprint(sys.argv[1:])\n"
    fact = _recompute_fact(tmp_path, "F-903", src, "0x5a4d")
    ok, reason = kv.check_expected_anchor_source(fact)
    assert ok is True


def test_f3_passes_without_recompute_script(tmp_path):
    """No producing script in provenance → nothing to be tautological with."""
    fact = _write_fact(tmp_path, "F-904", expected="0x5a4d",
                       provenance_lines=["- {role: sample, path: bins/sample}"])
    ok, _ = kv.check_expected_anchor_source(fact)
    assert ok is True


def test_f3_passes_when_script_missing(tmp_path):
    """Unresolvable script → gate passes (L1 reproduce will fail separately)."""
    fact = _write_fact(tmp_path, "F-905", expected="0x5a4d",
                       provenance_lines=["- {role: recompute_script, path: scripts/re/ghost.py}"])
    ok, _ = kv.check_expected_anchor_source(fact)
    assert ok is True


# ---------- F3: wired into verify() (integration) ----------

def test_f3_self_computed_expected_rejects_overall(tmp_path):
    """verify() overall=REJECTED when the expected anchor gate fails."""
    embedded = "6cecd136d02b71948cdc8a36251c977629a877da5696d5631bf6b63289b3b9c5"
    re_dir = tmp_path / "scripts" / "re"
    re_dir.mkdir(parents=True, exist_ok=True)
    (re_dir / "adapt_final.py").write_text(
        f"print({embedded!r})\n", encoding="utf-8")
    fact = _write_fact(
        tmp_path, "F-910", expected=embedded, reproduce=f"python scripts/re/adapt_final.py",
        provenance_lines=["- {role: recompute_script, path: scripts/re/adapt_final.py}"])
    out = kv.verify(tmp_path, "F-910")
    assert out["overall"] == "REJECTED", f"F3 tautology must block promotion: {out}"
    assert "expected" in out["lint"]["reason"].lower() or "anchor" in out["lint"]["reason"].lower()


def test_f3_independent_expected_keeps_verified(tmp_path):
    """A well-anchored fact still verifies end-to-end (no regression)."""
    fact = _write_fact(tmp_path, "F-911", expected="0x5a4d",
                       reproduce="import struct; print(hex(0x5A4D))",
                       provenance_lines=["- {role: sample, path: bins/sample}"])
    out = kv.verify(tmp_path, "F-911")
    assert out["overall"] == "VERIFIED", f"independent anchor must not be blocked: {out}"


# ---------- F6: cross_workflow redteam record (unit) ----------

def test_f6_cross_workflow_without_redteam_warns(tmp_path):
    """F001-F003 shape: provenance=cross_workflow, no redteam record → WARN."""
    fact = _write_fact(tmp_path, "F-920", expected="0x5a4d",
                       provenance_lines=["- {role: sample, path: bins/sample}"])
    fact["provenance"] = "cross_workflow"  # top-level marker form
    ok, reason = kv.check_cross_workflow_redteam(fact, tmp_path)
    assert ok is False
    assert "redteam" in reason.lower()


def test_f6_cross_workflow_role_entry_without_record_warns(tmp_path):
    """Marker as provenance role entry also warns without a record."""
    fact = _write_fact(tmp_path, "F-921", expected="0x5a4d",
                       provenance_lines=["- {role: cross_workflow, source: mal-recon}"])
    ok, reason = kv.check_cross_workflow_redteam(fact, tmp_path)
    assert ok is False
    assert "redteam" in reason.lower()


def test_f6_cross_workflow_with_frontmatter_verdict_ok(tmp_path):
    """redteam_verdict: CONFIRMED in frontmatter satisfies the record."""
    fact = _write_fact(tmp_path, "F-922", expected="0x5a4d",
                       provenance_lines=["- {role: sample, path: bins/sample}"],
                       redteam_verdict="CONFIRMED")
    fact["provenance"] = "cross_workflow"
    ok, _ = kv.check_cross_workflow_redteam(fact, tmp_path)
    assert ok is True


def test_f6_cross_workflow_with_runs_record_ok(tmp_path):
    """runs/verify-redteam-*.md citing the fact id satisfies the record."""
    fact = _write_fact(tmp_path, "F-923", expected="0x5a4d",
                       provenance_lines=["- {role: sample, path: bins/sample}"])
    fact["provenance"] = "cross_workflow"
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "verify-redteam-F-923.md").write_text(
        "RED-TEAM VERDICT: CONFIRMED — F-923 re-derived from sample bytes.\n",
        encoding="utf-8")
    ok, _ = kv.check_cross_workflow_redteam(fact, tmp_path)
    assert ok is True


def test_f6_non_cross_workflow_always_ok(tmp_path):
    """Ordinary facts are untouched by the F6 gate."""
    fact = _write_fact(tmp_path, "F-924", expected="0x5a4d",
                       provenance_lines=["- {role: sample, path: bins/sample}"])
    ok, _ = kv.check_cross_workflow_redteam(fact, tmp_path)
    assert ok is True


def test_f6_cross_workflow_l2_confirm_file_ok(tmp_path):
    """runs/verify-<fid>-*.json with l2.verdict=CONFIRMED satisfies the record."""
    import json
    fact = _write_fact(tmp_path, "F-925", expected="0x5a4d",
                       provenance_lines=["- {role: sample, path: bins/sample}"])
    fact["provenance"] = "cross_workflow"
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "verify-F-925-20260812T000000Z.json").write_text(
        json.dumps({"l2": {"verdict": "CONFIRMED", "gaps": []}}), encoding="utf-8")
    ok, _ = kv.check_cross_workflow_redteam(fact, tmp_path)
    assert ok is True


# ---------- F6: wired into verify() (integration) ----------

def test_f6_warning_does_not_reject_overall(tmp_path):
    """F6 is a WARNING: overall stays VERIFIED, warning surfaced in output."""
    # marker must live in the fact FILE — verify() reloads from disk
    facts = tmp_path / "facts"
    facts.mkdir(parents=True, exist_ok=True)
    (facts / "F-930.md").write_text(
        "---\nid: F-930\nclaim: c\nverified: false\n"
        "reproduce: import struct; print(hex(0x5A4D))\nexpected: 0x5a4d\n"
        "provenance: cross_workflow\n---\n",
        encoding="utf-8")
    out = kv.verify(tmp_path, "F-930")
    assert out["overall"] == "VERIFIED", f"F6 warning must not reject: {out}"
    assert out["warnings"], f"cross_workflow warning must be surfaced: {out}"
    assert "CROSS_WORKFLOW_NO_REDTEAM" in out["warnings"][0]["code"]


# ---------- F2: SKILL.md read/write boundary (wording pins) ----------

SKILL = ROOT / "skills" / "kunglao-agent" / "SKILL.md"


def test_f2_skill_md_states_read_write_boundary():
    """Orchestrator section must distinguish read-state from read-evidence→write-fact."""
    text = SKILL.read_text(encoding="utf-8", errors="ignore")
    # reading evidence is allowed...
    assert "read" in text.lower()
    # ...but writing a fact from read evidence is maker behavior, not maintenance
    assert "synthesis" in text, "SKILL.md must mention synthesis as the maker-route for orchestrator notes"


def test_f2_skill_md_distinguishes_state_read_from_evidence_read():
    """Wording must not confuse 'reading state to decide' with 'reading evidence to write facts'."""
    text = SKILL.read_text(encoding="utf-8", errors="ignore")
    assert "claim-register" in text
    assert "maker" in text.lower()


def test_f6_skill_md_states_cross_workflow_redteam_rule():
    """SKILL.md must state the F6 rule: cross_workflow facts need a redteam pass."""
    text = SKILL.read_text(encoding="utf-8", errors="ignore")
    assert "cross_workflow" in text
    assert "redteam" in text.lower()


def test_f2_skill_md_stays_within_line_budget():
    """#238 edits must not push SKILL.md past the 500-line contract cap."""
    lines = SKILL.read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 500, f"SKILL.md {len(lines)} lines > 500"
