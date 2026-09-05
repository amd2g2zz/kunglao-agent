# -*- coding: utf-8 -*-
"""RED tests for fact_contradiction_gate (issue #47, a2b5e25c problem 2).

TDD: these tests import fact_contradiction_gate which does NOT exist yet → RED.
Implementation in scripts/fact_contradiction_gate.py makes them GREEN.

Covers:
  RED1: same-topic multi-PROVEN facts, differing conclusions, no supersedes → CONFLICT
  RED2: supersedes / superseded_by link resolves the pair
  RED3: different topics → pass
  RED4: empty / missing / comment-only state → no crash, pass
  a2b5e25c backtest: F035/F040 routing contradiction blocked; backfill supersedes passes
  edges: same conclusion (converged), line-level link key, F-035/F035 normalization,
         non-PROVEN statuses excluded
  integration: claim_migrator STAMP downgrade + worker_budget backstop
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import yaml

from _factories import seed_verifier_dispatch  # #57 gate 5 evidence seeder

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


# ---------- helpers ----------

SIGNOFF = textwrap.dedent("""\
    ```yaml
    verifier_sign_off:
      verifier_id: redteam-w1
      refute_attempt: "tried to refute; could not"
      sign_off_at: 2026-08-11T10:00:00Z
      verdict: CONFIRMED
    ```
    """)


def _fact(ws: Path, fact_id: str, status: str, claim_id: str, conclusion: str,
          extra: str = "") -> Path:
    """Write facts/<fact_id>.md (body mentions the claim) + append its index row.

    _INDEX.md row format: F<id> | <status> | <claim_id> | <conclusion>
    """
    facts = ws / "facts"
    facts.mkdir(parents=True, exist_ok=True)
    body = f"# {fact_id}\n\nAnswers claim {claim_id}\n\n{extra}".rstrip() + "\n"
    f = facts / f"{fact_id}.md"
    f.write_text(body, encoding="utf-8")
    index = facts / "_INDEX.md"
    text = index.read_text(encoding="utf-8") if index.exists() else ""
    text += f"{fact_id} | {status} | {claim_id} | {conclusion}\n"
    index.write_text(text, encoding="utf-8")
    return f


def _register_statuses(ws: Path) -> dict[str, str]:
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    return {c["id"]: c["status"] for c in reg.get("claims", [])}


# =====================================================================
# RED1: same-topic multi-PROVEN, differing conclusions, no supersedes → CONFLICT
# =====================================================================

def test_red1_same_topic_conflict(tmp_path):
    """RED1: F035/F040 same claim, different conclusions, no links → CONFLICT."""
    ws = tmp_path / "ws"
    _fact(ws, "F035", "PROVEN", "C-203", "route via mpd[.]pegasus")
    _fact(ws, "F040", "PROVEN", "C-203", "route via winhttp")
    from fact_contradiction_gate import check_proven_contradiction, scan_conflicts
    conflicts = scan_conflicts(ws / "facts" / "_INDEX.md", ws / "facts")
    assert len(conflicts) == 1, f"expected 1 conflict, got {conflicts}"
    assert {conflicts[0]["fact_a"], conflicts[0]["fact_b"]} == {"F035", "F040"}
    ok, reason = check_proven_contradiction("C-203", ws / "facts")
    assert not ok, "same-topic conflicting PROVEN pair must be blocked"
    assert "F035" in reason and "F040" in reason


def test_red1b_same_topic_via_sample_refs_overlap(tmp_path):
    """RED1b: topics via overlapping sample_refs (different claims) → CONFLICT."""
    ws = tmp_path / "ws"
    _fact(ws, "F101", "PROVEN", "C-9", "downloader", extra=(
        "```yaml\nsample_refs:\n  - bins/a\n  - bins/b\n```"))
    _fact(ws, "F102", "PROVEN", "C-10", "dropper", extra=(
        "```yaml\nsample_refs:\n  - bins/b\n```"))
    from fact_contradiction_gate import scan_conflicts
    conflicts = scan_conflicts(ws / "facts" / "_INDEX.md", ws / "facts")
    assert len(conflicts) == 1, f"expected overlap conflict, got {conflicts}"


# =====================================================================
# RED2: supersedes / superseded_by resolves the pair
# =====================================================================

def test_red2_supersedes_resolves(tmp_path):
    """RED2: F040 declares supersedes: F035 → pair resolved, allowed."""
    ws = tmp_path / "ws"
    _fact(ws, "F035", "PROVEN", "C-203", "route via mpd[.]pegasus")
    _fact(ws, "F040", "PROVEN", "C-203", "route via winhttp",
          extra="```yaml\nsupersedes: F035\n```")
    from fact_contradiction_gate import check_proven_contradiction, scan_conflicts
    assert scan_conflicts(ws / "facts" / "_INDEX.md", ws / "facts") == []
    ok, reason = check_proven_contradiction("C-203", ws / "facts")
    assert ok, f"supersedes link must resolve the pair: {reason}"


def test_red2b_superseded_by_resolves(tmp_path):
    """RED2b: F035 declares superseded_by: F040 → pair resolved, allowed."""
    ws = tmp_path / "ws"
    _fact(ws, "F035", "PROVEN", "C-203", "route via mpd[.]pegasus",
          extra="```yaml\nsuperseded_by: F040\n```")
    _fact(ws, "F040", "PROVEN", "C-203", "route via winhttp")
    from fact_contradiction_gate import check_proven_contradiction
    ok, reason = check_proven_contradiction("C-203", ws / "facts")
    assert ok, f"superseded_by link must resolve the pair: {reason}"


def test_red2c_line_level_link_resolves(tmp_path):
    """RED2c: line-level `supersedes: F035` (no yaml fence) also resolves."""
    ws = tmp_path / "ws"
    _fact(ws, "F035", "PROVEN", "C-203", "route via A")
    _fact(ws, "F040", "PROVEN", "C-203", "route via B",
          extra="supersedes: F035  # plain line, no yaml fence")
    from fact_contradiction_gate import check_proven_contradiction
    ok, reason = check_proven_contradiction("C-203", ws / "facts")
    assert ok, f"line-level supersedes must resolve: {reason}"


def test_red2d_id_form_normalization(tmp_path):
    """RED2d: `supersedes: F-035` matches fact id `F035`."""
    ws = tmp_path / "ws"
    _fact(ws, "F035", "PROVEN", "C-203", "route via A")
    _fact(ws, "F040", "PROVEN", "C-203", "route via B",
          extra="supersedes: F-035")
    from fact_contradiction_gate import check_proven_contradiction
    ok, reason = check_proven_contradiction("C-203", ws / "facts")
    assert ok, f"F-035 must normalize to F035: {reason}"


# =====================================================================
# RED3: different topics → pass
# =====================================================================

def test_red3_different_topics_pass(tmp_path):
    """RED3: different claim_ids + disjoint sample_refs → allowed."""
    ws = tmp_path / "ws"
    _fact(ws, "F001", "PROVEN", "C-1", "alpha")
    _fact(ws, "F002", "PROVEN", "C-2", "beta")
    from fact_contradiction_gate import check_proven_contradiction, scan_conflicts
    assert scan_conflicts(ws / "facts" / "_INDEX.md", ws / "facts") == []
    ok, reason = check_proven_contradiction("C-1", ws / "facts")
    assert ok, f"different topics must pass: {reason}"


# =====================================================================
# RED4: empty / missing state → no crash, pass
# =====================================================================

def test_red4_empty_state_no_crash(tmp_path):
    """RED4: empty facts dir, no index → no conflicts, allowed."""
    ws = tmp_path / "fresh"
    (ws / "facts").mkdir(parents=True)
    from fact_contradiction_gate import check_proven_contradiction, scan_conflicts
    assert scan_conflicts(ws / "facts" / "_INDEX.md", ws / "facts") == []
    ok, reason = check_proven_contradiction("C-1", ws / "facts")
    assert ok, f"empty state must not crash: {reason}"


def test_red4b_missing_index_no_crash(tmp_path):
    """RED4b: facts dir with fact files but no _INDEX.md → allowed."""
    ws = tmp_path / "fresh2"
    (ws / "facts").mkdir(parents=True)
    _fact(ws, "F001", "PROVEN", "C-1", "alpha")
    from fact_contradiction_gate import check_proven_contradiction, scan_conflicts
    assert scan_conflicts(ws / "facts" / "_INDEX.md", ws / "facts") == []
    ok, _ = check_proven_contradiction("C-1", ws / "facts")
    assert ok


def test_red4c_comment_only_index_no_crash(tmp_path):
    """RED4c: index contains only comments → allowed."""
    ws = tmp_path / "fresh3"
    facts = ws / "facts"
    facts.mkdir(parents=True)
    (facts / "_INDEX.md").write_text("# _INDEX\n# nothing yet\n", encoding="utf-8")
    from fact_contradiction_gate import scan_conflicts
    assert scan_conflicts(facts / "_INDEX.md", facts) == []


# =====================================================================
# a2b5e25c backtest: F035/F040 routing contradiction
# =====================================================================

def test_backtest_a2b5e25c_f035_f040_blocked(tmp_path):
    """Original incident state: F035/F040 both PROVEN, conflicting routing
    conclusions, no supersedes → the promotion is blocked (CONFLICT)."""
    ws = tmp_path / "ws"
    _fact(ws, "F035", "PROVEN", "C-203", "routing: config targets C2-A")
    _fact(ws, "F040", "PROVEN", "C-203", "routing: config targets C2-B")
    from fact_contradiction_gate import check_proven_contradiction
    ok, reason = check_proven_contradiction("C-203", ws / "facts")
    assert not ok, "a2b5e25c F035/F040 pair must be flagged CONFLICT"
    assert "CONFLICT" in reason and "needs-resolution" in reason


def test_backtest_a2b5e25c_backfill_supersedes_passes(tmp_path):
    """Backfilled state: F040 declares supersedes: F035 → promotion allowed."""
    ws = tmp_path / "ws"
    _fact(ws, "F035", "PROVEN", "C-203", "routing: config targets C2-A")
    _fact(ws, "F040", "PROVEN", "C-203", "routing: config targets C2-B",
          extra="```yaml\nsupersedes: F035\n```")
    from fact_contradiction_gate import check_proven_contradiction
    ok, reason = check_proven_contradiction("C-203", ws / "facts")
    assert ok, f"backfilled supersedes must allow promotion: {reason}"


# =====================================================================
# Edges
# =====================================================================

def test_edge_same_conclusion_converged_allowed(tmp_path):
    """Same topic + same conclusion (whitespace-normalized) → converged, allowed."""
    ws = tmp_path / "ws"
    _fact(ws, "F201", "PROVEN", "C-50", "encrypted with AES")
    _fact(ws, "F202", "PROVEN", "C-50", "encrypted  with   AES")
    from fact_contradiction_gate import check_proven_contradiction, scan_conflicts
    assert scan_conflicts(ws / "facts" / "_INDEX.md", ws / "facts") == []
    ok, reason = check_proven_contradiction("C-50", ws / "facts")
    assert ok, f"identical conclusions are converged, not conflicting: {reason}"


def test_edge_non_proven_statuses_excluded(tmp_path):
    """INFERRED/OPEN facts are not PROVEN → no conflict."""
    ws = tmp_path / "ws"
    _fact(ws, "F301", "INFERRED", "C-60", "x")
    _fact(ws, "F302", "OPEN", "C-60", "y")
    from fact_contradiction_gate import scan_conflicts
    assert scan_conflicts(ws / "facts" / "_INDEX.md", ws / "facts") == []


# =====================================================================
# Integration: claim_migrator downgrade (PROVEN → STAMP on CONFLICT)
# =====================================================================

def test_claim_migrator_downgrades_proven_on_conflict(ws_factory):
    """Orchestrator promotes C-203 to PROVEN while F035/F040 conflict →
    register gets STAMP, message names CONFLICT (BLIND sign-off valid)."""
    ws = ws_factory(claims=[{"id": "C-203", "status": "OPEN"}])
    _fact(ws, "F035", "PROVEN", "C-203", "route via mpd[.]pegasus", extra=SIGNOFF)
    _fact(ws, "F040", "PROVEN", "C-203", "route via winhttp", extra=SIGNOFF)
    from kunglao_record import claim_migrator
    ok, msg = claim_migrator(ws, "C-203", "PROVEN", actor="orchestrator")
    assert ok, "claim_migrator should succeed (downgrade, not reject)"
    assert _register_statuses(ws)["C-203"] == "STAMP", "CONFLICT must downgrade to STAMP"
    assert "CONFLICT" in msg


def test_claim_migrator_promotes_when_no_conflict(ws_factory):
    """No same-topic conflict + valid BLIND sign-off → PROVEN kept."""
    ws = ws_factory(claims=[{"id": "C-11", "status": "OPEN"}])
    _fact(ws, "F111", "PROVEN", "C-11", "alpha", extra=SIGNOFF)
    _fact(ws, "F222", "PROVEN", "C-22", "beta")
    seed_verifier_dispatch(ws, "C-11")  # #57 gate 5: a verifier WAS dispatched
    from kunglao_record import claim_migrator
    ok, msg = claim_migrator(ws, "C-11", "PROVEN", actor="orchestrator")
    assert ok, msg
    assert _register_statuses(ws)["C-11"] == "PROVEN", f"expected PROVEN, got: {msg}"


# =====================================================================
# Integration: worker_budget backstop (direct register write)
# =====================================================================

def test_backstop_blocks_direct_proven_on_conflict(ws_factory):
    """Orchestrator directly writes PROVEN over a CONFLICT pair → blocked."""
    ws = ws_factory(claims=[{"id": "C-203", "status": "OPEN"}])
    _fact(ws, "F035", "PROVEN", "C-203", "route via mpd[.]pegasus", extra=SIGNOFF)
    _fact(ws, "F040", "PROVEN", "C-203", "route via winhttp", extra=SIGNOFF)
    import worker_budget as wb
    reg_path = ws / "claim-register.yaml"
    reg_path.write_text(reg_path.read_text(encoding="utf-8")
                        .replace("status: OPEN", "status: PROVEN"), encoding="utf-8")
    ok, reason = wb.compare_register_change_proven_gate(
        reg_path, {"C-203": "OPEN"}, "kunglao-orch", ws / "facts")
    assert not ok, "direct PROVEN write over CONFLICT pair must be blocked"
    assert "CONFLICT" in reason


def test_backstop_allows_direct_proven_when_no_conflict(ws_factory):
    """Direct PROVEN write with no same-topic conflict → allowed."""
    ws = ws_factory(claims=[{"id": "C-11", "status": "OPEN"}])
    _fact(ws, "F111", "PROVEN", "C-11", "alpha", extra=SIGNOFF)
    _fact(ws, "F222", "PROVEN", "C-22", "beta")
    seed_verifier_dispatch(ws, "C-11")  # #57 gate 5: a verifier WAS dispatched
    import worker_budget as wb
    reg_path = ws / "claim-register.yaml"
    reg_path.write_text(reg_path.read_text(encoding="utf-8")
                        .replace("status: OPEN", "status: PROVEN"), encoding="utf-8")
    ok, reason = wb.compare_register_change_proven_gate(
        reg_path, {"C-11": "OPEN"}, "kunglao-orch", ws / "facts")
    assert ok, f"no-conflict direct PROVEN should be allowed: {reason}"
