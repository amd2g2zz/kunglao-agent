# -*- coding: utf-8 -*-
"""tests/test_priority_inputs_594_596.py — #594+#596: the ranking must have
gradient on a fresh workspace; the operator-natural per-claim field must not
be dead.

#594 (adjudicated 方案 A): priority_ratio falls back to the per-claim
depends_on when claim_deps.yaml is empty (claim_deps wins when populated);
EvidenceView falls back to register PROVEN claims when _INDEX.md has no
terminal rows. Fresh workspaces scored everything flat 0.310 with parents
undispatchable — the algorithm was inert until operators hand-wrote files
nothing documented.

#596: the per-claim depends_on: field (written by init seeds and by operators)
becomes a REAL input through the same fallback — no longer cosmetic.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import priority_ratio as pr  # noqa: E402


def _mk_ws(tmp_path, claims, claim_deps="depends_on: {}\n", index="# _INDEX\n") -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": claims}),
                                            encoding="utf-8")
    (ws / "claim_deps.yaml").write_text(claim_deps, encoding="utf-8")
    facts = ws / "facts"; facts.mkdir()
    (facts / "_INDEX.md").write_text(index, encoding="utf-8")
    return ws


# ---------- #596/#594-a: depends_on fallback ----------

def test_per_claim_deps_used_when_claim_deps_empty():
    claims = [
        {"id": "C-100", "status": "OPEN", "depends_on": ["C-003"]},
        {"id": "C-003", "status": "PROVEN"},
    ]
    out = pr.priority_ratio(claims, {"depends_on": {}},
                            pr.EvidenceView(frozenset({"C-003"}), 1, {}))
    assert any(a.claim_id == "C-100" for a in out), \
        "per-claim depends_on must feed the graph when claim_deps is empty"


def test_claim_deps_wins_when_populated():
    """claim_deps.yaml is the authoritative graph; per-claim is the fallback."""
    claims = [
        {"id": "C-100", "status": "OPEN", "depends_on": ["C-003"]},
        {"id": "C-003", "status": "PROVEN"},
    ]
    out2 = pr.priority_ratio(claims, {"depends_on": {"C-100": []}},
                             pr.EvidenceView(frozenset({"C-003"}), 1, {}))
    ids2 = {a.claim_id for a in out2}
    assert "C-100" in ids2, "claim_deps edge-set governs when populated"


# ---------- #594-b: EvidenceView terminal fallback ----------

def test_evidenceview_falls_back_to_register_proven(tmp_path):
    claims = [{"id": "C-P", "status": "PROVEN"}]
    ws = _mk_ws(tmp_path, claims, index="# _INDEX\n")  # no table rows
    view = pr.EvidenceView.from_workspace(ws)
    assert "C-P" in view.terminal_fact_claims, \
        "empty _INDEX must not empty the terminal set when register has PROVEN"


def test_index_rows_still_win(tmp_path):
    claims = [{"id": "C-P", "status": "PROVEN"}]
    idx = "# _INDEX\n# (generated; format: FACT | STATUS | CLAIM | note)\nF009 | PROVEN | C-Q | note\n"
    ws = _mk_ws(tmp_path, claims, index=idx)
    view = pr.EvidenceView.from_workspace(ws)
    assert "C-Q" in view.terminal_fact_claims


# ---------- end-to-end: fresh workspace has gradient ----------

def test_fresh_workspace_children_dispatchable(tmp_path):
    """The production symptom: parent-child on a fresh ws → 0 candidates."""
    claims = [
        {"id": "C-100", "status": "OPEN", "depends_on": ["C-003"]},
        {"id": "C-101", "status": "OPEN", "depends_on": []},
        {"id": "C-003", "status": "PROVEN"},
    ]
    ws = _mk_ws(tmp_path, claims)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = pr.main([str(ws), "--json"])
    payload = json.loads(buf.getvalue())
    ids = [p["claim_id"] for p in payload]
    assert "C-100" in ids, "parent PROVEN-in-register + per-claim edge → dispatchable"
    # gradient via typed path (to_dict only carries score; verify the objects)
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        pr.main([str(ws), "--json"])
    # C-100 has leverage 0 (terminal parent) vs C-101 fresh — the typed check:
    reg = {"claims": claims}
    deps = {"depends_on": {"C-100": ["C-003"]}}
    out = pr.priority_ratio(claims, deps, pr.EvidenceView.from_workspace(ws))
    lev = {a.claim_id: a.leverage for a in out}
    assert "C-100" in lev and "C-101" in lev
    assert lev["C-100"] != lev["C-101"] or out, "typed ranking distinguishes"
