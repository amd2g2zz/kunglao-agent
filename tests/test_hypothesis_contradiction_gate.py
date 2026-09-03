# -*- coding: utf-8 -*-
"""RED tests for hypothesis-PROVEN-fact contradiction annotation (#662 gap closure).

TDD: tests call `convergence_check.decide()` on workspace fixtures that
produce OPEN_HYPOTHESIS_AT_CLOSE events with various contradiction shapes.
RED until _act_open_hypothesis is upgraded.

tasks.md §3 covers:
  RED10: explicit PROVEN fact reference in hypothesis body -> annotated BLOCKED
  RED11: candidate negated by PROVEN fact conclusion -> annotated BLOCKED
  RED12: open hypothesis no contradiction -> generic BLOCKED message
  RED13: hypothesis body mentions fact but not PROVEN -> no annotation (fail-open)
  RED14: empty PROVEN fact index -> no annotation (fail-open)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


# ---------- helpers (mirror test_decide_regression_anchor.py patterns) ----------

def _ws(base: Path, name: str) -> Path:
    ws = base / name
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    return ws


_CLEAN_INDEX = "# facts\n"


def _fact_index(ws: Path, rows: str) -> Path:
    """Write facts/_INDEX.md with custom rows. rows: raw text appended after '# facts'."""
    fdir = ws / "facts"
    fdir.mkdir(parents=True, exist_ok=True)
    (fdir / "_INDEX.md").write_text("# facts\n" + rows, encoding="utf-8")
    return fdir / "_INDEX.md"


def _hypo(ws: Path, hid: str, status: str, claim_id: str = "C-1",
          body: str = "pq:q1", candidates: str = "[]",
          extra_fm: str = "") -> Path:
    """Write a hypotheses/<hid>.md file."""
    hyp_dir = ws / "hypotheses"
    hyp_dir.mkdir(parents=True, exist_ok=True)
    p = hyp_dir / f"{hid}.md"
    p.write_text(
        f"---\nid: {hid}\nclaim_id: {claim_id}\n"
        f"competitor_group: pq-q1\ncandidates: {candidates}\n"
        f"status: {status}\nschema_rev: 1\n{extra_fm}"
        f"---\n\n{body}\n",
        encoding="utf-8")
    return p


# =====================================================================
# RED10: explicit PROVEN fact reference in hypothesis body -> annotated BLOCKED
# =====================================================================

def test_red10_explicit_proven_fact_reference_annotated(tmp_path):
    """When hypothesis body explicitly names a PROVEN fact, the BLOCKED
    message names that fact with its conclusion snippet."""
    from convergence_check import decide

    ws = _ws(tmp_path, "red10")
    _fact_index(ws, "F003 | PROVEN | C-003 | uses AES-GCM not RC4\n")
    _hypo(ws, "H-001", "open", body="This could be Cobalt Strike beacon or custom RAT.\nRefutes H-001: F003 shows AES-GCM is present.\n")
    d = decide(ws)
    assert d["decision"] == "BLOCKED", f"expected BLOCKED, got {d['decision']}"
    action = d["action"]
    assert "H-001" in action, f"action must name H-001: {action!r}"
    assert "Contradicted" in action or "F003" in action, \
        f"action must annotate contradiction with F003: {action!r}"
    assert "uses AES-GCM not RC4" in action, \
        f"action must include PROVEN fact conclusion snippet: {action!r}"


# =====================================================================
# RED11: candidate negated by PROVEN fact conclusion -> annotated BLOCKED
# =====================================================================

def test_red11_candidate_negated_by_proven_fact_annotated(tmp_path):
    """When a hypothesis carries candidates and a PROVEN fact conclusion
    contains 'not <candidate>' (negation keyword), the BLOCKED message
    annotates which PROVEN fact contradicts which candidate."""
    from convergence_check import decide

    ws = _ws(tmp_path, "red11")
    _fact_index(ws, "F005 | PROVEN | C-005 | payload uses RC4 cipher, not AES\n")
    _hypo(ws, "H-001", "open", candidates="[AES, RC4]",
          body="Could be AES or RC4 based on entropy.\n")
    d = decide(ws)
    assert d["decision"] == "BLOCKED", f"expected BLOCKED, got {d['decision']}"
    action = d["action"]
    assert "H-001" in action
    assert "Contradicted" in action or "F005" in action, \
        f"action must annotate F005 contradicts a candidate: {action!r}"
    assert "not AES" in action or "RC4" in action, \
        f"action must include the negation snippet: {action!r}"


# =====================================================================
# RED12: open hypothesis no contradiction -> generic BLOCKED (no annotation)
# =====================================================================

def test_red12_no_contradiction_generic_blocked(tmp_path):
    """When an open hypothesis has no PROVEN fact references and no
    candidates are negated, the message is the generic BLOCKED form."""
    from convergence_check import decide

    ws = _ws(tmp_path, "red12")
    _fact_index(ws, "")  # no PROVEN facts
    _hypo(ws, "H-001", "open", candidates="[]",
          body="pq:q1\n\nSeeded scaffold only — candidates pending.\n")
    d = decide(ws)
    assert d["decision"] == "BLOCKED", f"expected BLOCKED, got {d['decision']}"
    action = d["action"]
    assert "H-001" in action
    assert "Contradicted" not in action, \
        f"no contradiction expected — generic message only: {action!r}"
    # Message must still contain the standard adjudication prompt
    assert "adjudicate" in action.lower()
    assert "refuting_fact_id" in action or "superseded_by" in action


# =====================================================================
# RED13: hypothesis mentions fact but it is not PROVEN -> no annotation
# =====================================================================

def test_red13_nonproven_fact_mention_failopen(tmp_path):
    """When hypothesis body names a fact ID but that fact is not PROVEN
    (STAMP / PARTIAL / absent from index), no annotation is produced."""
    from convergence_check import decide

    ws = _ws(tmp_path, "red13")
    # F007 is STAMP, not PROVEN
    _fact_index(ws, "F007 | STAMP | C-007 | needs more evidence\n")
    _hypo(ws, "H-001", "open", body="F007 suggests custom crypto.\n")
    d = decide(ws)
    assert d["decision"] == "BLOCKED"
    action = d["action"]
    assert "H-001" in action
    # No contradiction annotation — F007 is not PROVEN
    assert "Contradicted" not in action, \
        f"non-PROVEN fact must not produce annotation: {action!r}"
    assert "F007" not in action or "STAMP" in action, \
        f"F007 should not appear as a contradiction: {action!r}"


# =====================================================================
# RED14: empty PROVEN fact index -> no annotation (fail-open)
# =====================================================================

def test_red14_empty_facts_index_failopen(tmp_path):
    """When facts/_INDEX.md is absent or empty (no PROVEN facts), the
    contradiction scan degrades silently and the generic BLOCKED fires."""
    from convergence_check import decide

    ws = _ws(tmp_path, "red14")
    # No _INDEX.md written — _fact_index helper not called
    _hypo(ws, "H-002", "open", body="pq:q2\n\nHypothesis body.\n")
    d = decide(ws)
    assert d["decision"] == "BLOCKED"
    action = d["action"]
    assert "H-002" in action
    assert "Contradicted" not in action, \
        f"no PROVEN facts -> no annotation expected: {action!r}"
    assert "adjudicate" in action.lower()
