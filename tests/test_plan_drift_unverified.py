# -*- coding: utf-8 -*-
"""TDD RED — issue #241, drift class 6: UNVERIFIED_EVIDENCE.

The first 5 drift classes are all "file A vs file B" text-consistency checks
(plan vs register, plan vs deps, plan vs status). None of them ever asks
whether the STATE FILE ITSELF is wrong: a claim can sit at status: PROVEN
while its reality check (runs/verify-redteam-*.md) never happened, or while
its supporting facts carry low confidence — and drift stays 0.

This class closes that hole:
  - PROVEN claim with NO runs/verify-redteam-<C-NN>.md file            -> drift
  - PROVEN claim whose fact files (facts/F*.md, claim_id frontmatter)
    carry a low confidence tier                                       -> drift

Exit-code style mirrors the existing 5 classes (1 = drift, 2 = HARD_PAUSE
when 3+ drift warnings in the same run). All I/O is synthetic (tmp_path).
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import plan_drift_detector as pdd  # noqa: E402


def write_register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        "claims:\n" + "".join(
            f"- id: {c['id']}\n  status: {c.get('status', 'OPEN')}\n"
            f"  boundary_type: {c.get('boundary_type', 'positive_observation')}\n"
            f"  evidence_tier_attempted: {c.get('evidence_tier_attempted', 0)}\n"
            f"  promotion_attempts: {c.get('promotion_attempts', 0)}\n"
            f"  depends_on: {c.get('depends_on', '[]')}\n"
            for c in claims
        ), encoding="utf-8")


def write_verify_redteam(ws: Path, cid: str) -> Path:
    runs = ws / "runs"
    runs.mkdir(exist_ok=True)
    p = runs / f"verify-redteam-{cid}.md"
    p.write_text("RED-TEAM VERDICT: CONFIRMED\n", encoding="utf-8")
    return p


def write_fact(ws: Path, fact_id: str, claim_id: str, confidence: str) -> Path:
    facts = ws / "facts"
    facts.mkdir(exist_ok=True)
    p = facts / f"{fact_id}.md"
    p.write_text(
        f"---\nid: {fact_id}\ntype: fact\nstatus: PROVEN\n"
        f"confidence: {confidence}\nclaim_id: {claim_id}\n---\n\nraw evidence\n",
        encoding="utf-8")
    return p


def check_output(ws: Path, capsys) -> str:
    pdd.check(ws, active_only=True)
    return capsys.readouterr().out


# ---------- RED 1: PROVEN without verify-redteam file -> drift (rc 1) ----------

def test_proven_without_verify_redteam_is_drift(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    write_register(ws, [{"id": "C-001", "status": "PROVEN"}])
    (ws / "global_plan.txt").write_text("plan mentions C-001\n", encoding="utf-8")

    rc = pdd.check(ws, active_only=True)
    assert rc == 1
    out = capsys.readouterr().out
    assert "UNVERIFIED_EVIDENCE" in out
    assert "C-001" in out


# ---------- RED 2: PROVEN + verify-redteam file -> no drift (rc 0) ----------

def test_proven_with_verify_redteam_no_drift(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    write_register(ws, [{"id": "C-002", "status": "PROVEN"}])
    write_verify_redteam(ws, "C-002")
    (ws / "global_plan.txt").write_text("plan mentions C-002\n", encoding="utf-8")

    assert pdd.check(ws, active_only=True) == 0


# ---------- RED 3: dash-less verify filename (verify-redteam-C335.md) also counts ----------

def test_verify_redteam_dashless_filename_counts(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    write_register(ws, [{"id": "C-335", "status": "PROVEN"}])
    write_verify_redteam(ws, "C335")  # real-world naming: runs/verify-redteam-C335.md
    (ws / "global_plan.txt").write_text("plan mentions C-335\n", encoding="utf-8")

    assert pdd.check(ws, active_only=True) == 0


# ---------- RED 4: PROVEN + low-confidence supporting fact -> drift (rc 1) ----------

def test_proven_with_low_confidence_fact_is_drift(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    write_register(ws, [{"id": "C-003", "status": "PROVEN"}])
    write_verify_redteam(ws, "C-003")  # reality check exists...
    write_fact(ws, "F001", "C-003", "unlikely")  # ...but the fact is low-confidence
    (ws / "global_plan.txt").write_text("plan mentions C-003\n", encoding="utf-8")

    rc = pdd.check(ws, active_only=True)
    assert rc == 1
    assert "UNVERIFIED_EVIDENCE" in capsys.readouterr().out


# ---------- RED 5: high-confidence fact + verify file -> no drift (rc 0) ----------

def test_proven_with_high_confidence_fact_no_drift(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    write_register(ws, [{"id": "C-004", "status": "PROVEN"}])
    write_verify_redteam(ws, "C-004")
    write_fact(ws, "F002", "C-004", "almost_certain")
    (ws / "global_plan.txt").write_text("plan mentions C-004\n", encoding="utf-8")

    assert pdd.check(ws, active_only=True) == 0


# ---------- RED 6: OPEN / REFUTED / NEGATIVE claims are NOT flagged ----------

def test_non_proven_statuses_not_flagged(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    write_register(ws, [
        {"id": "C-005", "status": "OPEN"},
        {"id": "C-006", "status": "REFUTED"},
        {"id": "C-007", "status": "NEGATIVE"},
    ])
    (ws / "global_plan.txt").write_text("plan mentions C-005 C-006 C-007\n", encoding="utf-8")

    rc = pdd.check(ws, active_only=True)
    assert rc == 0
    assert "UNVERIFIED_EVIDENCE" not in capsys.readouterr().out


# ---------- RED 7: low confidence recognized across legacy + 7-tier names ----------

def test_legacy_low_confidence_names_also_flag(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    write_register(ws, [{"id": "C-010", "status": "PROVEN"}])
    write_verify_redteam(ws, "C-010")
    write_fact(ws, "F004", "C-010", "suspected")  # legacy -> roughly_even (low half)
    (ws / "global_plan.txt").write_text("plan mentions C-010\n", encoding="utf-8")

    assert pdd.check(ws, active_only=True) == 1
