# -*- coding: utf-8 -*-
"""tests/test_belief_760.py — the belief: observation ingestion into the
decision state (issue 760, component b).

Before this card the loop decided on a class fingerprint: the worker's
observations never re-entered the state, so every decision was a bet on
"what this class of thing is", never on "what we just saw". The belief
is the POMDP b: the per-claim record of what is SEEN (facts with
statuses), what the worker DECLARED unknown (frontmatter `unknown:` —
tolerated absent, never fabricated), and the claim's open lifecycle.
It feeds the state signature (a `bf=` dim, present only when unknowns
are declared) and the knowledge query's audit faces.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rlvr import belief  # noqa: E402
from rlvr import l1_planner  # noqa: E402
from rlvr import l1_value as lv  # noqa: E402
from rlvr import state  # noqa: E402
from rlvr import step_grain  # noqa: E402


def _ws(tmp_path: Path, claims=None) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    doc = {"claims": claims or [{"id": "C-007", "status": "OPEN"}]}
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(doc), encoding="utf-8")
    return ws


def _fact(ws: Path, fid: str, claim: str, status: str = "PROVEN",
          unknown=None) -> None:
    meta = {"id": fid, "status": status, "claim_id": claim}
    if unknown:
        meta["unknown"] = list(unknown)
    body = yaml.safe_dump(meta)
    (ws / "facts" / f"{fid}.md").write_text(
        f"---\n{body}---\n\nsynthetic fact body\n", encoding="utf-8")


def _stash(ws: Path, claim: str, ts: str = "2026-01-01T00:00:00Z") -> None:
    (ws / "runs" / "dispatch-launch-1.json").write_text(
        json.dumps({"schema": "dispatch-launch/1", "claim": claim,
                    "action_type": "dispatch", "attempt_id": "a1",
                    "ts": ts}), encoding="utf-8")


def _rows(ws: Path) -> list[dict]:
    f = ws / "runs" / "belief.jsonl"
    if not f.is_file():
        return []
    return [json.loads(ln) for ln in
            f.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---- 1. the settle lands the belief row ------------------------------------

def test_settle_records_the_belief_row(tmp_path):
    ws = _ws(tmp_path)
    _stash(ws, "C-007")
    _fact(ws, "F-001", "C-007", "PROVEN")
    receipt = step_grain.settle_step(ws, "sess-1", outcome="completed")
    assert receipt is not None
    rows = _rows(ws)
    assert len(rows) == 1
    row = rows[0]
    assert row["schema"] == belief.BELIEF_SCHEMA
    assert row["claim"] == "C-007"
    assert row["step_ref"] == step_grain.step_id_for("sess-1", 0)
    assert row["seen"] == [{"id": "F-001", "status": "PROVEN"}]
    assert row["open_status"] == "OPEN"
    assert row["declared_unknown"] == []


def test_declared_unknowns_carried(tmp_path):
    ws = _ws(tmp_path)
    _stash(ws, "C-007")
    _fact(ws, "F-001", "C-007", "PROVEN",
          unknown=["format grammar", "entry behavior"])
    step_grain.settle_step(ws, "sess-1", outcome="completed")
    row = _rows(ws)[0]
    assert row["declared_unknown"] == ["entry behavior", "format grammar"]


def test_cold_belief_zero_fabrication(tmp_path):
    ws = _ws(tmp_path)
    _stash(ws, "C-007")   # no facts written at all
    step_grain.settle_step(ws, "sess-1", outcome="completed")
    row = _rows(ws)[0]
    assert row["seen"] == []
    assert row["declared_unknown"] == []


# ---- 2. the signature carries the belief dim --------------------------------

def test_signature_gains_belief_dim_only_when_declared(tmp_path):
    ws = _ws(tmp_path)
    snap = state.snapshot(ws)
    assert "|bf=-" in state.signature_str(snap)   # cold: absent dim
    _stash(ws, "C-007")
    _fact(ws, "F-001", "C-007", "PROVEN",
          unknown=["format grammar"])
    step_grain.settle_step(ws, "sess-1", outcome="completed")
    snap2 = state.snapshot(ws)
    assert "|bf=u" in state.signature_str(snap2)
    assert state.signature_str(snap) != state.signature_str(snap2)


# ---- 3. the knowledge query exposes the belief face -------------------------

def test_knowledge_query_exposes_the_belief_face(tmp_path):
    ws = _ws(tmp_path)
    _stash(ws, "C-007")
    _fact(ws, "F-001", "C-007", "PROVEN", unknown=["format grammar"])
    step_grain.settle_step(ws, "sess-1", outcome="completed")
    kc = l1_planner.knowledge_query(ws, "C-007")
    faces = [f for f in kc["faces"] if f.get("source") == "belief"]
    assert len(faces) == 1
    assert faces[0]["declared_unknown"] == 1
    assert faces[0]["seen"] == 1
    # the belief face is audit, never graded knowledge
    assert kc["solved"] is False


# ---- 4. the belief write never breaks the settle ----------------------------

def test_belief_write_failure_never_breaks_the_settle(tmp_path):
    ws = _ws(tmp_path)
    _stash(ws, "C-007")
    _fact(ws, "F-001", "C-007", "PROVEN")
    (ws / "runs" / "belief.jsonl").mkdir()   # the append target is a dir
    receipt = step_grain.settle_step(ws, "sess-1", outcome="completed")
    assert receipt is not None   # the settle survives the write failure


# ---- 5. the belief state conditions the policy (learning pin) ---------------

def test_unknown_state_conditions_the_policy(tmp_path):
    ws = _ws(tmp_path)
    _stash(ws, "C-007")
    _fact(ws, "F-001", "C-007", "PROVEN", unknown=["format grammar"])
    step_grain.settle_step(ws, "sess-1", outcome="completed")
    sig_u = lv.state_signature_of(ws)
    # outcomes land in THIS state's dispatch cell only
    for _ in range(8):
        lv.record_observation(ws, sig_u, "dispatch", 1.0,
                              claim="C-007", source="terminal")
    fold = lv.fold(lv.default_store(ws), gamma=1.0)
    a, b = lv.cell_posterior(fold, sig_u, "dispatch")
    assert a > 5.0 and b <= 1.0   # the cell learned, under the belief state
    receipt = l1_planner.plan_for_claim(ws, "C-007", dispatch_cost=0.5)
    assert receipt["chosen"]["action_kind"] == "dispatch"
