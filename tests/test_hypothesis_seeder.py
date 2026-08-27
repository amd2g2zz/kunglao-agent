# -*- coding: utf-8 -*-
"""RED tests for hypothesis_seeder (issue #662, openspec/changes/issue-662-hypothesis-seed/).

TDD: imports `hypothesis_seeder` (does NOT exist yet) and the
`OPEN_HYPOTHESIS_AT_CLOSE` convergence event — RED until implementation lands.

Covers tasks.md §3:
  RED1: seed creates one scaffold per PQ (marker/status/competitor_group)
  RED2: idempotent — second run no-op; marker survives HypothesisStore rewrite
  RED3: no task_spec -> [] no crash
  RED4: malformed task_spec -> [] no crash
  RED5: build_digest seeds then sec_g lists the scaffold
  RED6: convergence DRAIN -> BLOCKED naming H-id with open hypothesis at close
  RED7: hypothesis refuted/superseded -> DRAIN proceeds (CONVERGED)
  RED8: scaffold shape per design D1/D3 (C-PENDING + empty candidates)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


# ---------- helpers ----------

def _task_spec(ws: Path, pqs: list[dict]) -> Path:
    ws.mkdir(parents=True, exist_ok=True)
    lines = ["primary_questions:"]
    for q in pqs:
        lines.append(f"  - id: {q['id']}")
        if q.get("need"):
            lines.append(f"    need: {q['need']}")
    p = ws / "task_spec.yaml"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _hypo(ws: Path, hid: str, status: str, claim_id: str = "C-1",
          body_first_line: str = "pq:q1", extra_fm: str = "") -> Path:
    hyp_dir = ws / "hypotheses"
    hyp_dir.mkdir(parents=True, exist_ok=True)
    p = hyp_dir / f"{hid}.md"
    p.write_text(
        f"---\nid: {hid}\nclaim_id: {claim_id}\ncompetitor_group: pq-q1\n"
        f"candidates: []\nstatus: {status}\nschema_rev: 1\n{extra_fm}"
        f"---\n\n{body_first_line}\n\nbody text\n",
        encoding="utf-8")
    return p


# =====================================================================
# RED1: seed creates one scaffold per PQ
# =====================================================================

def test_red1_seed_creates_scaffold_per_pq(tmp_path):
    from hypothesis_seeder import seed_from_task_spec
    ws = tmp_path / "ws"
    _task_spec(ws, [{"id": "q1", "need": "model_selection"}, {"id": "q2"}])
    created = seed_from_task_spec(ws)
    assert len(created) == 2, f"expected 2 scaffolds, got {created}"
    hyp_dir = ws / "hypotheses"
    files = sorted(p.name for p in hyp_dir.glob("H-*.md"))
    assert len(files) == 2
    for f in files:
        text = (hyp_dir / f).read_text(encoding="utf-8")
        assert "status: open" in text
        assert "competitor_group: pq-q" in text
    ids = {c["qid"] for c in created}
    assert ids == {"q1", "q2"}


# =====================================================================
# RED2: idempotent; marker survives HypothesisStore rewrite
# =====================================================================

def test_red2_idempotent_and_marker_survives_rewrite(tmp_path):
    from hypothesis_seeder import seed_from_task_spec
    from hypothesis_store import HypothesisStore
    ws = tmp_path / "ws"
    _task_spec(ws, [{"id": "q1"}])
    first = seed_from_task_spec(ws)
    assert len(first) == 1
    # Rewrite through the store (refute transition rewrites the file;
    # body must survive, so the marker survives)
    store = HypothesisStore(ws / "hypotheses")
    store.transition("H-001", "refuted", refuting_fact_id="F999")
    second = seed_from_task_spec(ws)
    assert second == [], f"re-seed after adjudicated scaffold must be no-op, got {second}"
    files = list((ws / "hypotheses").glob("H-*.md"))
    assert len(files) == 1, f"no new file expected, found {files}"


# =====================================================================
# RED3: no task_spec -> [] no crash
# =====================================================================

def test_red3_no_task_spec_returns_empty(tmp_path):
    from hypothesis_seeder import seed_from_task_spec
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    assert seed_from_task_spec(ws) == []


# =====================================================================
# RED4: malformed task_spec -> [] no crash
# =====================================================================

def test_red4_malformed_task_spec_returns_empty(tmp_path):
    from hypothesis_seeder import seed_from_task_spec
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n  - broken: [\n", encoding="utf-8")
    assert seed_from_task_spec(ws) == []


# =====================================================================
# RED5: build_digest seeds then sec_g lists the scaffold
# =====================================================================

def test_red5_digest_seeds_then_lists(tmp_path):
    from digest_build import build_digest
    ws = tmp_path / "ws"
    _task_spec(ws, [{"id": "q1", "need": "model_selection"}])
    (ws / "runs").mkdir(exist_ok=True)
    digest = build_digest(ws)
    seeded = list((ws / "hypotheses").glob("H-*.md"))
    assert seeded, "digest build must seed the PQ scaffold"
    assert "sec_g" in digest, "digest lacks sec_g section"
    assert "H-001" in digest, \
        f"sec_g must list the scaffold, digest tail: {digest[-200:]}"


# =====================================================================
# RED6: convergence DRAIN -> BLOCKED naming H-id (open hypothesis at close)
# =====================================================================

def test_red6_open_hypothesis_blocks_close(tmp_path):
    from convergence_check import decide
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    # No claim-register, no task_spec -> earlier DRAIN probes silent
    _hypo(ws, "H-001", "open")
    d = decide(ws)
    assert d["decision"] == "BLOCKED", \
        f"open hypothesis at close must BLOCK, got {d['decision']}"
    assert "H-001" in d["action"], f"action must name H-001: {d['action']!r}"
    assert "hypothes" in d["action"].lower()
    assert d["open_hypothesis_count"] >= 1
    assert any(h["id"] == "H-001" for h in d["open_hypotheses"])


# =====================================================================
# RED7: refuted/superseded -> DRAIN proceeds (CONVERGED)
# =====================================================================

def test_red7_refuted_hypothesis_drain_clean(tmp_path):
    from convergence_check import decide
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    _hypo(ws, "H-001", "refuted", extra_fm="refuting_fact_id: F001\n")
    d = decide(ws)
    assert d["decision"] == "CONVERGED", \
        f"refuted hypothesis must not block close, got {d['decision']} ({d['action']!r})"
    assert d["open_hypothesis_count"] == 0


# =====================================================================
# RED8: scaffold shape per design D1/D3
# =====================================================================

def test_red8_scaffold_shape(tmp_path):
    from hypothesis_seeder import seed_from_task_spec
    ws = tmp_path / "ws"
    _task_spec(ws, [{"id": "q1"}])
    seed_from_task_spec(ws)
    text = (ws / "hypotheses" / "H-001.md").read_text(encoding="utf-8")
    assert "claim_id: C-PENDING" in text, \
        f"scaffold must carry the C-PENDING placeholder: {text[:200]}"
    assert "candidates: []" in text, \
        f"scaffold must carry empty candidates (no invented analysis): {text[:200]}"
