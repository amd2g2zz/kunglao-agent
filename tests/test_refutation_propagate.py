# -*- coding: utf-8 -*-
"""TDD RED — issue #241: refutation propagation along claim deps.

SKILL.md contract ("refutation propagates along deps") had ZERO mechanical
implementation: nothing scanned claim-register.yaml for REFUTED/NEGATIVE
claims and re-flagged the claims that depend on them, so a refuted
dependency left dependents standing on poisoned ground while the loop kept
dispatching them.

Under test:
  - REFUTED/NEGATIVE claim -> reverse-walk claim_deps.yaml depends_on ->
    every claim whose parent list contains the refuted id gets
    `needs_re-eval: true` added to its register entry
  - statuses are NEVER changed (no cascade avalanche)
  - --dry-run marks nothing on disk
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import refutation_propagate as rp  # noqa: E402


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


def write_deps(ws: Path, depends_on: dict) -> None:
    lines = ["depends_on:"]
    for child, parents in depends_on.items():
        lines.append(f"  {child}:")
        for p in parents:
            lines.append(f"  - {p}")
    (ws / "claim_deps.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_register(ws: Path) -> dict:
    import yaml
    return yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}


def claim_by_id(reg: dict, cid: str) -> dict:
    return next(c for c in reg["claims"] if c["id"] == cid)


# ---------- RED 1: REFUTED parent -> dependent gets needs_re-eval ----------

def test_refuted_parent_marks_dependent(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    write_register(ws, [
        {"id": "C-001", "status": "REFUTED"},
        {"id": "C-002", "status": "PROVEN"},
    ])
    write_deps(ws, {"C-002": ["C-001"]})

    marked = rp.mark_dependents(ws)

    assert "C-002" in marked
    reg = load_register(ws)
    assert claim_by_id(reg, "C-002")["needs_re-eval"] is True
    # the REFUTED claim itself is untouched
    assert "needs_re-eval" not in claim_by_id(reg, "C-001")
    # the REFUTED status itself is untouched (no cascade avalanche)
    assert claim_by_id(reg, "C-001")["status"] == "REFUTED"


# ---------- RED 2: NEGATIVE parent also propagates ----------

def test_negative_parent_marks_dependent(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    write_register(ws, [
        {"id": "C-010", "status": "NEGATIVE"},
        {"id": "C-011", "status": "OPEN"},
    ])
    write_deps(ws, {"C-011": ["C-010"]})

    marked = rp.mark_dependents(ws)

    assert "C-011" in marked
    assert claim_by_id(load_register(ws), "C-011")["needs_re-eval"] is True


# ---------- RED 3: multiple dependents all marked ----------

def test_multiple_dependents_all_marked(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    write_register(ws, [
        {"id": "C-020", "status": "REFUTED"},
        {"id": "C-021", "status": "PROVEN"},
        {"id": "C-022", "status": "PROVEN"},
        {"id": "C-023", "status": "OPEN"},
    ])
    write_deps(ws, {"C-021": ["C-020"], "C-022": ["C-020"], "C-023": ["C-022"]})

    marked = rp.mark_dependents(ws)

    assert set(marked) == {"C-021", "C-022"}
    # transitive dependents are NOT marked (no cascade): only direct dependents
    assert "C-023" not in marked


# ---------- RED 4: no refuted claims -> nothing marked, no file rewrite ----------

def test_no_refuted_claims_marks_nothing(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    write_register(ws, [{"id": "C-030", "status": "PROVEN"}, {"id": "C-031", "status": "OPEN"}])
    write_deps(ws, {"C-031": ["C-030"]})

    marked = rp.mark_dependents(ws)

    assert marked == []
    reg = load_register(ws)
    assert "needs_re-eval" not in claim_by_id(reg, "C-031")


# ---------- RED 5: idempotent — already-marked dependent is not re-written ----------

def test_already_marked_dependent_stays_marked(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    write_register(ws, [
        {"id": "C-040", "status": "REFUTED"},
        {"id": "C-041", "status": "PROVEN", "depends_on": "[]"},
    ])
    write_deps(ws, {"C-041": ["C-040"]})
    # pre-marked by a previous run
    reg = load_register(ws)
    claim_by_id(reg, "C-041")["needs_re-eval"] = True
    (ws / "claim-register.yaml").write_text(
        __import__("yaml").safe_dump(reg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    before = (ws / "claim-register.yaml").read_text(encoding="utf-8")

    marked = rp.mark_dependents(ws)

    # still on disk, still true; run reports it as already-satisfied, not new
    assert claim_by_id(load_register(ws), "C-041")["needs_re-eval"] is True
    after = (ws / "claim-register.yaml").read_text(encoding="utf-8")
    assert after == before  # no rewrite churn


# ---------- RED 6: --dry-run writes nothing ----------

def test_dry_run_marks_nothing_on_disk(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    write_register(ws, [
        {"id": "C-050", "status": "REFUTED"},
        {"id": "C-051", "status": "PROVEN"},
    ])
    write_deps(ws, {"C-051": ["C-050"]})
    before = (ws / "claim-register.yaml").read_text(encoding="utf-8")

    rc = rp.main([str(ws), "--dry-run"])

    assert rc == 1  # would mark
    after = (ws / "claim-register.yaml").read_text(encoding="utf-8")
    assert after == before
    assert "C-051" in capsys.readouterr().out


# ---------- RED 7: CLI without --dry-run persists; exit 0 when nothing to do ----------

def test_cli_persists_and_exit_codes(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    write_register(ws, [
        {"id": "C-060", "status": "REFUTED"},
        {"id": "C-061", "status": "PROVEN"},
    ])
    write_deps(ws, {"C-061": ["C-060"]})

    rc = rp.main([str(ws)])
    assert rc == 1
    assert claim_by_id(load_register(ws), "C-061")["needs_re-eval"] is True

    # second run: nothing new to mark -> exit 0
    rc2 = rp.main([str(ws)])
    assert rc2 == 0


# ---------- RED 8: dependent claim not present in register -> reported, not marked ----------

def test_dependent_absent_from_register_reported(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    write_register(ws, [{"id": "C-070", "status": "REFUTED"}])
    write_deps(ws, {"C-999": ["C-070"]})  # C-999 is not a register claim

    marked = rp.mark_dependents(ws)

    assert "C-999" not in marked
    assert marked == []
